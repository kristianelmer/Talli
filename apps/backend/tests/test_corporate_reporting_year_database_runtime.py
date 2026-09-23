"""Actual owner RPCs on the explicitly owned disposable reporting clone."""
import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
import pytest
from talli_backend.adapters.supabase_corporate_governance import SupabaseCorporateGovernanceSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.application.corporate_governance_workflow import CorporateGovernanceApplication
from talli_backend.modules.corporate_governance.public import CorporateGovernanceError
from talli_backend.modules.ledger.service import LedgerService
from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,CorrelationId,IncomeYear,UserId

pytestmark=pytest.mark.authority_database
URL=os.environ.get('DATABASE_URL','')
MIGRATION=Path(__file__).resolve().parents[3]/'supabase/migrations/20260923090824_ledger_reporting_amendment_read.sql'


def insert(conn,table,values):
    conn.execute(sql.SQL('insert into {} ({}) values ({})').format(sql.Identifier(*table.split('.')),
        sql.SQL(',').join(map(sql.Identifier,values)),sql.SQL(',').join(sql.Placeholder() for _ in values)),tuple(values.values()))


@pytest.fixture(scope='module',autouse=True)
def owned_clone_authority():
    assert conninfo_to_dict(URL)['dbname'].startswith('rf193_governance_'), 'Use a newly owned disposable clone only'
    roles=['ledger_store_owner','corporate_governance_store_owner','corporate_governance_workflow_executor']
    scopes={'ledger':['entries','entry_reversals','entry_corrections'],'corporate_governance':['supported_events']}
    role_changes={};acls={};schemas={}
    with psycopg.connect(URL) as conn:
        principal,bypass=conn.execute('select current_user,rolbypassrls from pg_roles where rolname=current_user').fetchone()
        assert bypass
        for role in roles:
            if not conn.execute('select pg_has_role(current_user,%s,\'SET\')',(role,)).fetchone()[0]:
                role_changes[role]=conn.execute('select admin_option,inherit_option,set_option from pg_auth_members where roleid=(select oid from pg_roles where rolname=%s) and member=(select oid from pg_roles where rolname=current_user) and grantor=member',(role,)).fetchone()
                conn.execute(sql.SQL('grant {} to {} with set true granted by {}').format(sql.Identifier(role),sql.Identifier(principal),sql.Identifier(principal)))
        for schema,tables in scopes.items():
            schemas[schema]=(conn.execute('select nspacl::text from pg_namespace where nspname=%s',(schema,)).fetchone()[0],not conn.execute('select has_schema_privilege(current_user,%s,\'USAGE\')',(schema,)).fetchone()[0])
            for table in tables:
                rel=f'{schema}.{table}'
                acl,force=conn.execute('select relacl::text,relforcerowsecurity from pg_class where oid=%s::regclass',(rel,)).fetchone()
                missing=tuple(p for p in ('SELECT','INSERT') if not conn.execute('select has_table_privilege(current_user,%s,%s)',(rel,p)).fetchone()[0])
                acls[(schema,table)]=(acl,force,missing)
            conn.execute(sql.SQL('set local role {}').format(sql.Identifier(schema+'_store_owner')))
            if schemas[schema][1]:conn.execute(sql.SQL('grant usage on schema {} to {}').format(sql.Identifier(schema),sql.Identifier(principal)))
            for table in tables:
                missing=acls[(schema,table)][2]
                if missing:conn.execute(sql.SQL('grant {} on {} to {}').format(sql.SQL(',').join(map(sql.SQL,missing)),sql.Identifier(schema,table),sql.Identifier(principal)))
            conn.execute('reset role')
    try:yield
    finally:
        with psycopg.connect(URL) as conn:
            for schema,tables in scopes.items():
                conn.execute(sql.SQL('set local role {}').format(sql.Identifier(schema+'_store_owner')))
                for table in tables:
                    missing=acls[(schema,table)][2]
                    if missing:conn.execute(sql.SQL('revoke {} on {} from {}').format(sql.SQL(',').join(map(sql.SQL,missing)),sql.Identifier(schema,table),sql.Identifier(principal)))
                if schemas[schema][1]:conn.execute(sql.SQL('revoke usage on schema {} from {}').format(sql.Identifier(schema),sql.Identifier(principal)))
                conn.execute('reset role')
                assert conn.execute('select nspacl::text from pg_namespace where nspname=%s',(schema,)).fetchone()[0]==schemas[schema][0]
                for table in tables:assert conn.execute('select relacl::text,relforcerowsecurity from pg_class where oid=%s::regclass',(f'{schema}.{table}',)).fetchone()==acls[(schema,table)][:2]
            for role,prior in role_changes.items():
                if prior is None:conn.execute(sql.SQL('revoke {} from {} granted by {}').format(sql.Identifier(role),sql.Identifier(principal),sql.Identifier(principal)))
                else:conn.execute(sql.SQL('grant {} to {} with admin {},inherit {},set {} granted by {}').format(sql.Identifier(role),sql.Identifier(principal),*(sql.SQL(str(v).lower()) for v in prior),sql.Identifier(principal)))


def seed():
    actor,company,entry,event=[uuid4() for _ in range(4)]
    with psycopg.connect(URL) as conn:
        insert(conn,'auth.users',{'id':actor,'email':str(actor)+'@example.test'})
        insert(conn,'public.companies',{'id':company,'org_number':str(100000000+company.int%899999999),'name':'Disposable reporting AS','entity_type':'AS','created_by':actor,'source':'test'})
        insert(conn,'public.company_memberships',{'company_id':company,'user_id':actor,'role':'owner','accepted_at':datetime.now(UTC)})
        add_entry(conn,actor,company,entry)
        docs=[{'evidence_kind':'signed_resolution','document_id':str(uuid4()),'content_sha256':'c'*64}]
        insert(conn,'corporate_governance.supported_events',{'event_id':event,'event_reference':uuid4(),'company_id':company,'income_year':2026,'event_date':'2026-05-01','event_kind':'cash_capital_increase','phase':'registered','policy_version':'corporate-governance-supported-events-2026.1','canonical_facts':Jsonb({'documentFacts':docs}),'facts_sha256':'a'*64,'document_facts':Jsonb(docs),'accounting_entry_id':entry,'idempotency_key':'reporting-runtime-'+str(event),'correlation_id':'reporting-runtime','created_by':actor})
    return {'actor':actor,'company':company,'entry':entry,'event':event}


def add_entry(conn,actor,company,entry):
    insert(conn,'ledger.entries',{'id':entry,'company_id':company,'income_year':2026,'entry_kind':'CAPITAL_INCREASE','memo':'owned reporting fixture','lines':Jsonb([{'account':'1920','debit':30000,'credit':0,'currency':'NOK','description':'test'},{'account':'2000','debit':0,'credit':30000,'currency':'NOK','description':'test'}]),'risk_flags':Jsonb([]),'created_by':actor,'posted_at':datetime.now(UTC),'source_capability':'CORPORATE_GOVERNANCE','source_record_id':str(uuid4()),'correlation_id':'owned-reporting-fixture'})


def add_amendment(data,original=None,replacement=None):
    reversal=uuid4();original=original or data['entry']
    with psycopg.connect(URL) as conn:
        add_entry(conn,data['actor'],data['company'],reversal)
        if replacement is not None:add_entry(conn,data['actor'],data['company'],replacement)
        values={'original_entry_id':original,'reversal_entry_id':reversal,'company_id':data['company'],'income_year':2026,'reason':'historical retained amendment'}
        if replacement is None:values.update(reversed_by=data['actor']);table='entry_reversals'
        else:values.update(replacement_entry_id=replacement,corrected_by=data['actor']);table='entry_corrections'
        insert(conn,'ledger.'+table,values)
    return reversal


def session(data,actor=None):
    actor=actor or data['actor'];identity=ActorId(ActorKind.USER,UserId(str(actor)))
    return SupabaseCorporateGovernanceSession(URL,_VerifiedActor(identity,json.dumps({'sub':str(actor),'role':'authenticated','aal':'aal2'})))


def app(data,actor=None):
    class Factory:
        async def session(self,token):return session(data,actor)
    return CorporateGovernanceApplication(Factory(),None,LedgerService)


def read(data,actor=None):
    return asyncio.run(app(data,actor).read_reporting_year_evidence('verified-local',company_id=CompanyId(str(data['company'])),income_year=IncomeYear(2026),correlation_id=CorrelationId('runtime-reporting-read')))


def test_historical_ledger_only_reversal_changes_governance_evidence():
    data=seed();before=read(data);add_amendment(data);after=read(data)
    assert before.supported_events[0].status=='recorded'
    assert after.supported_events[0].status=='reversed' and len(after.ledger_amendments)==1
    assert before.enumeration_sha256!=after.enumeration_sha256


def test_replacement_chain_retains_both_original_receipts():
    data=seed();replacement=uuid4();add_amendment(data,replacement=replacement);add_amendment(data,original=replacement)
    result=read(data)
    assert result.supported_events[0].status=='corrected' and len(result.ledger_amendments)==2
    assert {str(row.original_entry_id) for row in result.ledger_amendments}=={str(data['entry']),str(replacement)}


def test_other_company_amendments_and_non_owner_reads_are_excluded():
    data=seed();other=seed();add_amendment(other)
    assert read(data).ledger_amendments==()
    with pytest.raises(CorporateGovernanceError):read(data,other['actor'])


def test_governance_and_ledger_reads_share_one_serializable_snapshot():
    data=seed()
    async def check():
        async with session(data).transaction() as tx:
            role=await tx._database_rows("select current_user,rolbypassrls,current_setting('transaction_isolation') as isolation from pg_roles where rolname=current_user")
            assert role==[{'current_user':'corporate_governance_workflow_executor','rolbypassrls':False,'isolation':'serializable'}]
            await tx.read_reporting_year_basis(CompanyId(str(data['company'])))
            # A separately committed receipt between the two owner reads must
            # not produce a mixed snapshot. The next transaction must see it.
            await asyncio.to_thread(add_amendment,data)
            assert await tx.list_entry_amendments(actor_id=tx.actor_id,company_id=CompanyId(str(data['company'])),correlation_id=CorrelationId('snapshot-test'))==()
    asyncio.run(check())
    assert read(data).supported_events[0].status=='reversed'


def test_read_migration_replay_preserves_original_authority_and_private_tables():
    body=re.sub(r'(?m)^begin;\s*$','',MIGRATION.read_text(),count=1);body=re.sub(r'commit;\s*$','',body)
    with psycopg.connect(URL) as conn:
        before=conn.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()
        acl=conn.execute("select nspacl::text from pg_namespace where nspname='ledger'").fetchone()
        tables=conn.execute("select oid,relacl::text,relforcerowsecurity from pg_class where oid in ('ledger.entries'::regclass,'ledger.entry_reversals'::regclass,'ledger.entry_corrections'::regclass) order by oid").fetchall()
        conn.execute(body)
        assert conn.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by roleid,member,grantor').fetchall()==before
        assert conn.execute("select nspacl::text from pg_namespace where nspname='ledger'").fetchone()==acl
        assert conn.execute("select oid,relacl::text,relforcerowsecurity from pg_class where oid in ('ledger.entries'::regclass,'ledger.entry_reversals'::regclass,'ledger.entry_corrections'::regclass) order by oid").fetchall()==tables
        assert conn.execute("select has_function_privilege('authenticated','ledger.list_entry_amendments_v1(uuid,text)','EXECUTE'),has_table_privilege('corporate_governance_workflow_executor','ledger.entry_reversals','SELECT')").fetchone()==(False,False)
        conn.rollback()


def test_read_rollback_and_recutover_preserve_original_receipts():
    data=seed();add_amendment(data)
    with psycopg.connect(URL,autocommit=True) as conn:
        before=conn.execute('select original_entry_id,reversal_entry_id,reason,reversed_at from ledger.entry_reversals where company_id=%s',(data['company'],)).fetchall()
        conn.execute((MIGRATION.parents[1]/'rollback'/MIGRATION.name).read_text())
        assert conn.execute("select to_regprocedure('ledger.list_entry_amendments_v1(uuid,text)')").fetchone()[0] is None
        conn.execute(MIGRATION.read_text())
        assert conn.execute('select original_entry_id,reversal_entry_id,reason,reversed_at from ledger.entry_reversals where company_id=%s',(data['company'],)).fetchall()==before
    assert read(data).supported_events[0].status=='reversed'
