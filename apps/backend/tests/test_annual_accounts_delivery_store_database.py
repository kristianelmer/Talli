"""Owned PG17 component retention proof; authenticated full topology is separate."""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
import pytest

from talli_backend.adapters.postgres_annual_accounts import PostgresAnnualAccountsSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsError,AnnualAccountsSourceQuery,project_annual_accounts_source
from talli_backend.shared.kernel import IdempotencyKey,IncomeYear
from test_annual_accounts_delivery_source import ACTOR,COMPANY,prepare,read,source_inputs
from test_annual_accounts_source_facts import source
from test_postgres_tax_delivery_draft import draft_database
from test_postgres_tax_source_snapshot import database

pytestmark=pytest.mark.accounts_database
ROOT=Path(__file__).resolve().parents[3]
MIGRATION='20261026221935_annual_accounts_delivery_store_v1.sql'


@pytest.fixture(scope='module')
def draft():
    inputs,app,_=source_inputs()
    return prepare(read(inputs,app))


@pytest.fixture(scope='module')
def accounts_database(draft_database):
    # Reuse one strictly owned disposable PG17 fixture, including its published
    # company guard/identity policy doubles. No hosted or admin business adapter.
    with psycopg.connect(**draft_database,user='postgres',autocommit=True) as db:
        db.execute('''
          create role annual_accounts_filing_store_owner nologin noinherit nobypassrls;
          create schema annual_accounts_filing authorization annual_accounts_filing_store_owner;
          grant usage on schema annual_accounts_filing to annual_accounts_filing_workflow_executor;
          grant usage on schema extensions to annual_accounts_filing_store_owner;
          create table backend_system.annual_accounts_migration_state(phase text);
          insert into backend_system.annual_accounts_migration_state values('contracted');
          set role annual_accounts_filing_store_owner;
          create function annual_accounts_filing.assert_filing_available_v1(subject text) returns uuid
           language plpgsql volatile set search_path='' as $$ begin
           if subject is null or subject is distinct from current_setting('talli.verified_actor_id',true)
            or subject is distinct from (current_setting('talli.verified_actor_claims',true)::jsonb)->>'sub'
            or (current_setting('talli.verified_actor_claims',true)::jsonb)->>'role' is distinct from 'authenticated'
            then raise exception 'annual_accounts_forbidden'; end if;
           return subject::uuid; end $$;
          create table annual_accounts_filing.filing_previews(id uuid);
          create table annual_accounts_filing.filing_submissions(id uuid);
          create table annual_accounts_filing.filing_overrides(id uuid);
          create table annual_accounts_filing.filing_review_comments(id uuid);
          create table annual_accounts_filing.authority_permissions(id uuid);
          create table annual_accounts_filing.authority_test_runs(id uuid);
          reset role;
        ''')
        db.execute('insert into public.tax_draft_fixture_owner values(%s,%s)',(str(COMPANY),str(ACTOR.subject)))
        raw=source(True);raw.update(companyId=str(COMPANY),incomeYear=2025)
        raw['workspace']={key:[] for key in raw['workspace']}
        raw['coverage'].update(companyId=str(COMPANY),incomeYear=2025,retainedSubmissionIds=[],
            familyCounts={key:0 for key in raw['coverage']['familyCounts']})
        db.execute('create table public.accounts_delivery_fixture_source(body jsonb)')
        db.execute('insert into public.accounts_delivery_fixture_source values(%s)',(Jsonb(raw),))
        db.execute('grant select on public.accounts_delivery_fixture_source to annual_accounts_filing_store_owner')
        db.execute('''set role annual_accounts_filing_store_owner;
          create function annual_accounts_filing.read_source_snapshot_v1(company uuid,year integer,subject text)
          returns jsonb language plpgsql volatile security definer set search_path='' as $$
          declare result jsonb; extent boolean; begin
           perform annual_accounts_filing.assert_filing_available_v1(subject);
           if not public.company_access_is_accepted_owner_v1(company) then raise exception 'annual_accounts_not_found'; end if;
           if current_setting('transaction_isolation')<>'repeatable read' then raise exception 'annual_accounts_unavailable'; end if;
           select count(*)=6 into extent from pg_class c join pg_namespace n on n.oid=c.relnamespace
            where n.nspname='annual_accounts_filing' and c.relkind in ('r','p');
           select body into result from public.accounts_delivery_fixture_source;
           return result||jsonb_build_object('asOf',transaction_timestamp(),'coverage',
            (result->'coverage')||jsonb_build_object('declaredExtentValid',extent));
          end $$;
          revoke all on function annual_accounts_filing.read_source_snapshot_v1(uuid,integer,text) from public;
          grant execute on function annual_accounts_filing.read_source_snapshot_v1(uuid,integer,text) to annual_accounts_filing_workflow_executor;
          reset role;''')
        memberships='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before=db.execute(memberships).fetchall()
        db.execute((ROOT/'supabase/contract-migrations'/MIGRATION).read_text())
        assert db.execute(memberships).fetchall()==before
    return draft_database


def session(database,*,aal='aal2'):
    actor=_VerifiedActor(ACTOR,json.dumps({'sub':str(ACTOR.subject),'role':'authenticated','aal':aal}))
    return PostgresAnnualAccountsSession(make_conninfo(**database,user='snapshot_runtime'),actor)


async def store(database,draft,*,aal='aal2'):
    async with session(database,aal=aal).transaction() as tx:
        return await tx.store_delivery_draft(draft)


async def snapshot(database,*,aal='aal2',version=2):
    async with session(database,aal=aal).transaction(snapshot=True) as tx:
        if version==2:
            query=AnnualAccountsSourceQuery(COMPANY,IncomeYear(2025),ACTOR)
            value=await tx.filing_source_snapshot(query)
            return {'contractVersion':value.contract_version,'coverage':value.coverage,'deliveryDrafts':value.delivery_drafts,
                    'facts':project_annual_accounts_source(query,value)}
        result=await tx._one_row(f'select annual_accounts_filing.read_source_snapshot_v{version}(%s,2025,%s) as result',
            (str(COMPANY),str(ACTOR.subject)))
        return result['result']


@contextmanager
def writes(database):
    def flag(enabled):
        with psycopg.connect(**database,user='postgres',autocommit=True) as db:
            db.execute('set role annual_accounts_filing_store_owner')
            db.execute("create or replace function annual_accounts_filing.delivery_draft_writes_enabled_v1() returns boolean "
                "language plpgsql volatile security invoker set search_path='' as $$begin return "+str(enabled).lower()+"; end;$$")
    flag(True)
    try:yield
    finally:flag(False)


def fresh(draft):return replace(draft,filing_id=str(uuid4()),command_key=IdempotencyKey(uuid4().hex))


def test_reader_first_default_closure_and_positive_exact_extent(accounts_database,draft):
    with pytest.raises(AnnualAccountsError):asyncio.run(store(accounts_database,draft))
    value=asyncio.run(snapshot(accounts_database));proof=value['coverage']
    assert value['contractVersion']=='annual-accounts-source-v2' and value['deliveryDrafts']==()
    assert value['facts'].history_coverage.status=='complete',value['facts'].history_coverage.reasons
    assert proof['declaredExtentValid'] is False and proof['declaredDeliveryExtentValid'] is True
    assert proof['deliveryDraftCount']==proof['deliveryEventCount']==0
    assert proof['deliveryArchiveTrackingValid'] is proof['deliveryImmutableValid'] is True
    assert asyncio.run(snapshot(accounts_database,version=1))['coverage']['declaredExtentValid'] is False


def test_concurrent_replay_is_one_exact_immutable_record(accounts_database,draft):
    value=fresh(draft)
    async def exercise():return await asyncio.gather(store(accounts_database,value),store(accounts_database,value))
    with writes(accounts_database):first,second=asyncio.run(exercise())
    assert first==second and first.draft==value and first.draft.canonical_json==value.canonical_json
    conflict=replace(value,filing_id=str(uuid4()))
    with writes(accounts_database),pytest.raises(AnnualAccountsError):asyncio.run(store(accounts_database,conflict))
    with psycopg.connect(**accounts_database,user='postgres',autocommit=True) as db:
        assert db.execute('select count(*) from annual_accounts_filing.delivery_drafts where id=%s',(value.filing_id,)).fetchone()==(1,)
        for operation in ('update annual_accounts_filing.delivery_drafts set canonical_json=canonical_json where id=%s',
                          'delete from annual_accounts_filing.delivery_drafts where id=%s'):
            with pytest.raises(psycopg.DatabaseError):db.execute(operation,(value.filing_id,))


def test_runtime_has_rpc_only_access_and_mfa_is_required(accounts_database,draft):
    with psycopg.connect(**accounts_database,user='postgres') as db:
        for role in ('anon','authenticated','service_role','snapshot_runtime','annual_accounts_filing_workflow_executor'):
            assert db.execute("select has_table_privilege(%s,'annual_accounts_filing.delivery_drafts','SELECT,INSERT,UPDATE,DELETE')",(role,)).fetchone()==(False,)
            assert db.execute("select has_table_privilege(%s,'annual_accounts_filing.delivery_events','SELECT,INSERT,UPDATE,DELETE')",(role,)).fetchone()==(False,)
    with writes(accounts_database),pytest.raises(AnnualAccountsError):asyncio.run(store(accounts_database,fresh(draft),aal='aal1'))
    with pytest.raises(AnnualAccountsError):asyncio.run(snapshot(accounts_database,aal='aal1'))


def test_rollback_preserves_exact_reads_and_tracking(accounts_database,draft):
    value=fresh(draft)
    with writes(accounts_database):result=asyncio.run(store(accounts_database,value))
    with psycopg.connect(**accounts_database,user='postgres',autocommit=True) as db:
        memberships='select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'
        before=db.execute(memberships).fetchall();db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
        assert db.execute(memberships).fetchall()==before
    with pytest.raises(AnnualAccountsError):asyncio.run(store(accounts_database,fresh(draft)))
    retained=asyncio.run(snapshot(accounts_database))
    assert next(row for row in retained['deliveryDrafts'] if row.draft.filing_id==value.filing_id)==result
    assert retained['coverage']['deliveryDraftDigests'][value.filing_id]==value.sha256


@pytest.mark.parametrize('change',['tracking','immutability'])
def test_changed_retention_guards_never_claim_positive_coverage(accounts_database,change):
    with psycopg.connect(**accounts_database,user='postgres',autocommit=True) as db:
        if change=='tracking':
            db.execute('alter table annual_accounts_filing.delivery_drafts disable trigger company_archive_track_accounts_delivery_drafts')
        else:
            db.execute('alter table annual_accounts_filing.delivery_events disable trigger accounts_delivery_events_immutable')
        try:
            proof=asyncio.run(snapshot(accounts_database))['coverage']
            assert proof['deliveryArchiveTrackingValid' if change=='tracking' else 'deliveryImmutableValid'] is False
        finally:
            trigger='company_archive_track_accounts_delivery_drafts' if change=='tracking' else 'accounts_delivery_events_immutable'
            table='delivery_drafts' if change=='tracking' else 'delivery_events'
            db.execute(f'alter table annual_accounts_filing.{table} enable trigger {trigger}')


def test_missing_command_uniqueness_invalidates_retention(accounts_database):
    from psycopg import sql
    with psycopg.connect(**accounts_database,user='postgres',autocommit=True) as db:
        name=db.execute("select conname from pg_constraint where conrelid='annual_accounts_filing.delivery_drafts'::regclass and contype='u'").fetchone()[0]
        db.execute(sql.SQL('alter table annual_accounts_filing.delivery_drafts drop constraint {}').format(sql.Identifier(name)))
        try:assert asyncio.run(snapshot(accounts_database))['coverage']['deliveryKeysValid'] is False
        finally:db.execute(sql.SQL('alter table annual_accounts_filing.delivery_drafts add constraint {} unique(company_id,income_year,prepared_by,command_key)').format(sql.Identifier(name)))


@pytest.mark.parametrize('change',['owner','containment'])
def test_waiting_writer_rechecks_owner_and_shutdown_after_company_guard(accounts_database,draft,change):
    value=fresh(draft)
    async def exercise():
        with psycopg.connect(**accounts_database,user='postgres') as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)',(str(COMPANY),))
            task=asyncio.create_task(store(accounts_database,value))
            try:
                waiting=0
                for _ in range(100):
                    with psycopg.connect(**accounts_database,user='postgres',autocommit=True) as probe:
                        waiting=probe.execute("select count(*) from pg_stat_activity where usename='snapshot_runtime' and wait_event='advisory'").fetchone()[0]
                    if waiting:break
                    await asyncio.sleep(.01)
                assert waiting
                with psycopg.connect(**accounts_database,user='postgres',autocommit=True) as containment:
                    if change=='owner':containment.execute('update public.tax_draft_fixture_owner set actor=null where company=%s',(str(COMPANY),))
                    else:containment.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
                blocker.commit()
                with pytest.raises(AnnualAccountsError):await task
                assert blocker.execute('select count(*) from annual_accounts_filing.delivery_drafts where id=%s',(value.filing_id,)).fetchone()==(0,)
            finally:
                blocker.rollback()
                if not task.done():
                    task.cancel()
                    try:await task
                    except asyncio.CancelledError:pass
                with psycopg.connect(**accounts_database,user='postgres',autocommit=True) as restore:
                    restore.execute('update public.tax_draft_fixture_owner set actor=%s where company=%s',(str(ACTOR.subject),str(COMPANY)))
    with writes(accounts_database):asyncio.run(exercise())
