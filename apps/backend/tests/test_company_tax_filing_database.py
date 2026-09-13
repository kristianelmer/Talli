"""Actual restricted PostgreSQL ports and released HTTP on disposable contracted topology.

One outer transaction owns fixtures, migrations, grants and all HTTP effects. The
HTTP session substitutes only authentication and the connection's async facade;
production application, adapter, SQL functions and Ledger service execute intact.
"""
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import pytest

from talli_backend.adapters.postgres_company_tax_filing import PostgresCompanyTaxTransaction
from talli_backend.adapters.supabase_ledger import _VerifiedActor, _map_database_error, SupabaseLedgerWorkflowTransaction
from talli_backend.main import create_app
from talli_backend.shared.kernel import ActorId, ActorKind, UserId
from test_shareholder_register_filing_lifecycle import company, insert, _admit_opening_year

pytestmark = pytest.mark.company_tax_database
ROOT = Path(__file__).resolve().parents[3]
EXPAND = 'supabase/migrations/20260913171000_company_tax_settlement_expand.sql'
CUTOVER = 'supabase/contract-migrations/20260913172000_company_tax_settlement_cutover.sql'
ROLLBACK = 'supabase/rollback/20260913171000_company_tax_settlement_expand.sql'
CONTRACT = 'supabase/contract-migrations/20260913173000_company_tax_settlement_contract.sql'
CONTRACT_ROLLBACK = 'supabase/rollback/20260913173000_company_tax_settlement_contract.sql'


def migration(db, path):
    db.execute('reset role')
    body = (ROOT / path).read_text()
    body = re.sub(r'(?m)^begin;\s*$', '', body, count=1)
    body = re.sub(r'commit;\s*$', '', body)
    db.execute(body)


@pytest.fixture
def fixture():
    assert os.environ.get('DATABASE_URL'), 'DATABASE_URL must identify the owned disposable database'
    with psycopg.connect(os.environ['DATABASE_URL']) as db:
        try:
            if db.execute("select to_regclass('backend_system.tax_settlement_migration_state')").fetchone()[0]:
                migration(db, ROLLBACK)
            cid, owner = company(db)
            _admit_opening_year(db, cid, owner)
            migration(db, EXPAND)
            migration(db, CUTOVER)
            yield db, cid, owner
        finally:
            db.rollback()


class AsyncCursor:
    def __init__(self, cursor): self.cursor = cursor
    async def fetchall(self): return self.cursor.fetchall()


class AsyncConnection:
    def __init__(self, db): self.db = db
    async def execute(self, query, parameters=()):
        return AsyncCursor(self.db.cursor(row_factory=dict_row).execute(query, parameters))


def client(db, actor, *, legacy_ledger=False):
    role = "ledger_workflow_executor" if legacy_ledger else "company_tax_filing_workflow_executor"
    verified = _VerifiedActor(ActorId(ActorKind.USER, UserId(str(actor))), json.dumps({'sub':str(actor),'role':'authenticated','aal':'aal2'}))
    db.execute(sql.SQL('grant {} to postgres with inherit false,set true').format(sql.Identifier(role)))
    class Session:
        actor_id = verified.actor_id
        async def session(self, token): return self
        @asynccontextmanager
        async def transaction(self):
            # Reinstall the restricted login's SET-only grant after migration
            # cleanup; this harness shares the fixture owner's connection.
            db.execute(sql.SQL('grant {} to postgres with inherit false,set true').format(sql.Identifier(role)))
            try:
                with db.transaction():
                    db.execute(sql.SQL('set local role {}').format(sql.Identifier(role)))
                    db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)", (str(actor),verified.claims_json))
                    yield (SupabaseLedgerWorkflowTransaction("postgresql://unused", verified, AsyncConnection(db)) if legacy_ledger
                           else PostgresCompanyTaxTransaction(verified, AsyncConnection(db)))
            except psycopg.Error as error:
                raise _map_database_error(str(error)) from None
            finally:
                db.execute('reset role')
    return TestClient(create_app(**({"ledger_session_factory": Session()} if legacy_ledger
                                   else {"company_tax_session_factory": Session()})))


def request(cid, kind='payable'):
    key = str(uuid4())
    return {'companyId':str(cid),'incomeYear':2026,'actionId':key,'settlementDate':'2026-04-15',
            'amount':{'amount':'125.50','currency':'NOK'},'settlementKind':kind,'documentStatus':'attached',
            'bankTransactionId':None,'documentId':None}


def post(api, body, key=None):
    key = key or body['actionId']
    return api.post('/api/v1/ledger/tax-settlements',json=body,headers={
        'Authorization':'Bearer fixture','Idempotency-Key':key,'X-Request-ID':key})


def facts(db, cid):
    db.execute('grant company_tax_filing_store_owner,ledger_store_owner,banking_store_owner to postgres')
    return {
        table: db.execute(sql.SQL('select coalesce(jsonb_agg(to_jsonb(t) order by id),\'[]\'::jsonb) from {} t where company_id=%s').format(sql.Identifier(*table.split('.'))),(cid,)).fetchone()[0]
        for table in ['company_tax_filing.settlements','ledger.entries','banking.transactions']
    }


@pytest.mark.parametrize('kind', ['payable','payment','refund'])
def test_http_post_receipt_replay_and_payload_conflict_are_atomic(fixture, kind):
    db,cid,owner = fixture
    api = client(db,owner); body = request(cid,kind)
    first = post(api,body)
    assert first.status_code == 201,first.text
    state = facts(db,cid)
    again = post(api,body)
    assert again.status_code == 201 and again.json()['replayed'] is True
    assert again.json()['postedEntry']['entryId'] == first.json()['postedEntry']['entryId']
    conflict = post(api,{**body,'amount':{'amount':'126.00','currency':'NOK'}})
    assert conflict.status_code == 409 and conflict.json()['code']=='LEDGER_IDEMPOTENCY_KEY_REUSED'
    # Historical action replay precedes fresh-input validation for a new key.
    historical = post(api,{**body,'amount':{'amount':'0','currency':'NOK'}},str(uuid4()))
    assert historical.status_code == 201 and historical.json()['replayed']
    assert facts(db,cid) == state


def test_document_failure_rolls_back_receipt_posting_and_bank_claim(fixture):
    db,cid,owner = fixture
    body=request(cid,'payment'); body['documentId']=str(uuid4())
    api=client(db,owner);before=facts(db,cid)
    failed=post(api,body)
    assert failed.status_code==422 and failed.json()['code']=='LEDGER_INVALID_INPUT'
    assert facts(db,cid)==before
    # A corrected retry with the same key proves the failed receipt was rolled back.
    body['documentId']=None
    assert post(api,body).status_code==201


def test_cross_company_action_identity_and_membership_remain_concealed(fixture):
    db,cid,owner=fixture;api=client(db,owner);body=request(cid)
    assert post(api,body).status_code==201
    foreign, outsider=company(db)
    _admit_opening_year(db,foreign,outsider)
    outsider_api=client(db,outsider)
    denied=post(outsider_api,body)
    assert denied.status_code==404 and denied.json()['code']=='LEDGER_NOT_FOUND'
    collision=post(outsider_api,{**body,'companyId':str(foreign),'amount':{'amount':'0','currency':'NOK'}},str(uuid4()))
    assert collision.status_code==409 and collision.json()['code']=='LEDGER_IDEMPOTENCY_KEY_REUSED'


def test_full_rollback_and_recutover_preserve_all_rows_and_archive_generations(fixture):
    db,cid,owner=fixture;api=client(db,owner)
    for kind in ['payable','payment','refund']:
        response=post(api,request(cid,kind));assert response.status_code==201,response.text
    original=facts(db,cid)
    inventory=db.execute("select definition->'indexes' from backend_system.tax_settlement_migration_inventory where resource='public.holding_actions'").fetchone()[0]
    assert {item['name'] for item in inventory} >= {'holding_actions_company_id_year_idx','holding_actions_ledger_entry_id_idx'}
    generation=db.execute('select to_jsonb(g) from public.company_archive_source_generations g where company_id=%s',(cid,)).fetchall()
    migration(db,ROLLBACK)
    restored=db.execute('select jsonb_agg(to_jsonb(t) order by id) from public.holding_actions t where company_id=%s',(cid,)).fetchone()[0]
    assert restored==original['company_tax_filing.settlements']
    restored_indexes=dict(db.execute("select indexname,indexdef from pg_indexes where schemaname='public' and tablename='holding_actions'").fetchall())
    assert all(restored_indexes[item['name']]==item['definition'] for item in inventory)
    assert post(api,request(cid)).status_code==503
    migration(db,EXPAND);migration(db,CUTOVER)
    assert facts(db,cid)==original
    assert db.execute('select to_jsonb(g) from public.company_archive_source_generations g where company_id=%s',(cid,)).fetchall()==generation


@pytest.mark.parametrize('corruption',['hash','payload','conflict'])
def test_corrupt_quarantine_aborts_rollback_without_changing_active_writer(fixture,corruption):
    db,cid,owner=fixture;api=client(db,owner);assert post(api,request(cid)).status_code==201
    facts(db,cid)
    with pytest.raises(psycopg.Error,match='tax_settlement_'):
        with db.transaction():
            db.execute("insert into backend_system.tax_settlement_quarantine(source_id,payload,payload_sha256) select id,to_jsonb(t),encode(extensions.digest(to_jsonb(t)::text,'sha256'),'hex') from company_tax_filing.settlements t where company_id=%s",(cid,))
            if corruption=='hash':
                db.execute("update backend_system.tax_settlement_quarantine set payload_sha256=repeat('0',64)")
            else:
                path='{payload,amount}' if corruption=='payload' else '{payload,extra}'
                value='-1' if corruption=='payload' else 'true'
                db.execute('update backend_system.tax_settlement_quarantine set payload=jsonb_set(payload,%s,%s::jsonb)',(path,value))
                db.execute("update backend_system.tax_settlement_quarantine set payload_sha256=encode(extensions.digest(payload::text,'sha256'),'hex')")
            migration(db,ROLLBACK)
    assert db.execute('select phase from backend_system.tax_settlement_migration_state').fetchone()[0]=='cutover'
    assert post(api,request(cid)).status_code==201


def linked_request(db,cid,owner,kind):
    db.execute('grant banking_store_owner,documents_store_owner,company_tax_filing_store_owner to postgres')
    bank,document=uuid4(),uuid4()
    insert(db,'banking.transactions',id=bank,company_id=cid,income_year=2026,transaction_date='2026-03-01',text='Tax fixture',amount='-125.50' if kind=='payment' else '125.50',source_hash=bank.hex*2,created_by=owner)
    insert(db,'public.documents',id=document,company_id=cid,income_year=2026,document_type='tax_settlement',name='Fixture tax evidence',linked_to='tax_settlement',storage_key=str(document),created_by=owner)
    return {**request(cid,kind),'bankTransactionId':str(bank),'documentId':str(document)}


@pytest.mark.parametrize('kind',['payment','refund'])
def test_linked_bank_and_document_capture_changes_only_original_matched_action(fixture,kind):
    db,cid,owner=fixture;body=linked_request(db,cid,owner,kind);api=client(db,owner)
    before=facts(db,cid)['banking.transactions'][0]
    response=post(api,body)
    assert response.status_code==201,response.text
    result=facts(db,cid)
    after=result['banking.transactions'][0]
    assert after=={**before,'matched_action_reference':body['actionId']}
    row=result['company_tax_filing.settlements'][0]
    assert row['bank_transaction_id']==body['bankTransactionId'] and row['document_id']==body['documentId']
    assert post(api,body).json()['replayed'] is True
    assert facts(db,cid)==result


def test_failure_after_ledger_and_bank_claim_rolls_back_every_effect(fixture):
    db,cid,owner=fixture;body=linked_request(db,cid,owner,'payment');api=client(db,owner)
    before=facts(db,cid)
    generation=db.execute('select to_jsonb(g) from public.company_archive_source_generations g where company_id=%s',(cid,)).fetchall()
    db.execute(sql.SQL('alter table company_tax_filing.settlements add constraint fixture_reject_capture check(company_id<>{})').format(sql.Literal(cid)))
    response=post(api,body)
    assert response.status_code==503,response.text
    assert facts(db,cid)==before
    assert db.execute('select to_jsonb(g) from public.company_archive_source_generations g where company_id=%s',(cid,)).fetchall()==generation
    db.execute('alter table company_tax_filing.settlements drop constraint fixture_reject_capture')
    assert post(api,body).status_code==201
    assert len(facts(db,cid)['ledger.entries'])==len(before['ledger.entries'])+1


@pytest.mark.parametrize('phase',['cutover','rolled_back','recutover'])
def test_document_removal_retains_tax_references_through_deployment_phases(fixture,phase):
    db,cid,owner=fixture;body=linked_request(db,cid,owner,'payment');api=client(db,owner)
    assert post(api,body).status_code==201
    if phase!='cutover': migration(db,ROLLBACK)
    if phase=='recutover': migration(db,CUTOVER)
    db.execute('grant documents_executor to postgres with inherit false,set true')
    db.execute("select set_config('talli.authorized_company_roles',%s,true)",(json.dumps({str(cid):'owner'}),))
    db.execute('set local role documents_executor')
    with pytest.raises(psycopg.Error,match='documents_evidence_linked'):
        with db.transaction():
            db.execute('select * from documents.mark_removed_v1(%s,%s,%s)',(body['documentId'],'Fixture removal',str(owner)))
    db.execute('reset role')


@pytest.mark.parametrize('reverse',[ROLLBACK,CONTRACT_ROLLBACK])
def test_contract_and_both_rollbacks_preserve_facts_and_single_writer(fixture,reverse):
    db,cid,owner=fixture;api=client(db,owner);body=request(cid)
    assert post(api,body).status_code==201
    expected=facts(db,cid)
    migration(db,CONTRACT)
    assert db.execute("select to_regclass('public.holding_actions'),to_regprocedure('backend_system.prepare_tax_settlement_v1(jsonb,text)')").fetchone()==(None,None)
    assert post(api,body).json()['replayed'] is True
    migration(db,reverse)
    assert facts(db,cid)==expected
    if reverse==ROLLBACK:
        assert post(api,body).status_code==503
        migration(db,CUTOVER)
    else:
        assert post(api,body).json()['replayed'] is True
        assert not db.execute("select has_function_privilege('ledger_workflow_executor','backend_system.prepare_tax_settlement_v1(jsonb,text)','EXECUTE')").fetchone()[0]
    migration(db,CONTRACT)
    assert facts(db,cid)==expected


def test_archive_query_preserves_source_json_and_enforces_exact_scope(fixture):
    db,cid,owner=fixture;api=client(db,owner)
    for kind in ['payable','payment','refund']: assert post(api,request(cid,kind)).status_code==201
    expected=facts(db,cid)['company_tax_filing.settlements']
    migration(db,CONTRACT)
    def query(company_id,year=2026):
        return api.get('/api/v1/company-tax/settlement-archive-source',params={'companyId':str(company_id),'incomeYear':year},headers={'Authorization':'Bearer fixture'})
    result=query(cid)
    assert result.status_code==200,result.text
    assert result.headers['cache-control']=='no-store'
    assert sorted(result.json()['settlements'],key=lambda row:row['id'])==expected
    assert query(cid,2025).json()['settlements']==[]
    assert query(uuid4()).status_code==404


@pytest.mark.parametrize('corruption', ['non_tax', 'invalid_payload'])
def test_cutover_rejects_unsupported_source_without_changing_rows_or_writer(fixture, corruption):
    db,cid,owner=fixture
    response=post(client(db,owner),request(cid));assert response.status_code==201,response.text
    migration(db,ROLLBACK)
    if corruption=='non_tax':
        db.execute("update public.holding_actions set action_type='shareholder_loan' where company_id=%s",(cid,))
    else:
        db.execute("update public.holding_actions set payload=jsonb_set(payload,'{amount}','-1') where company_id=%s",(cid,))
    before=db.execute('select to_jsonb(t) from public.holding_actions t where company_id=%s',(cid,)).fetchall()
    with pytest.raises(psycopg.Error,match='tax_settlement_'):
        with db.transaction():migration(db,CUTOVER)
    assert db.execute('select phase from backend_system.tax_settlement_migration_state').fetchone()[0]=='rolled_back'
    assert db.execute('select to_jsonb(t) from public.holding_actions t where company_id=%s',(cid,)).fetchall()==before
    assert db.execute("select has_function_privilege('ledger_workflow_executor','backend_system.prepare_tax_settlement_v1(jsonb,text)','execute')").fetchone()[0]
    assert not db.execute("select has_function_privilege('company_tax_filing_workflow_executor','company_tax_filing.prepare_settlement_v1(jsonb,text)','execute')").fetchone()[0]


def test_shared_receipt_repair_preserves_administrative_cost_caller(fixture):
    db,cid,owner=fixture
    migration(db,CONTRACT)
    linked=linked_request(db,cid,owner,'payment')
    body={'companyId':str(cid),'incomeYear':2026,'bankTransactionId':linked['bankTransactionId'],
          'category':'SOFTWARE','payee':'Synthetic software supplier','paidDate':'2026-04-15',
          'amount':{'amount':'125.50','currency':'NOK'},'documentId':None}
    api=client(db,owner,legacy_ledger=True);key=str(uuid4())
    headers={'Authorization':'Bearer fixture','Idempotency-Key':key,'X-Request-ID':key}
    first=api.post('/api/v1/ledger/administrative-costs',json=body,headers=headers)
    assert first.status_code==201,first.text
    before=facts(db,cid)
    replay=api.post('/api/v1/ledger/administrative-costs',json=body,headers=headers)
    assert replay.status_code==201 and replay.json()['replayed']
    assert facts(db,cid)==before
    conflict=api.post('/api/v1/ledger/administrative-costs',json={**body,'payee':'Changed payee'},headers=headers)
    assert conflict.status_code==409 and conflict.json()['code']=='LEDGER_IDEMPOTENCY_KEY_REUSED'
    assert facts(db,cid)==before


def test_expand_keeps_predecessor_document_retention_until_tax_cutover(fixture):
    db,cid,owner=fixture
    migration(db,ROLLBACK)
    definition=db.execute("select pg_get_functiondef('documents.has_evidence_references_v1(uuid)'::regprocedure)").fetchone()[0]
    predecessor=definition.replace('company_tax_filing.has_document_reference_v1(p_document_id)', '''exists (
      select 1 from public.holding_actions item
      where item.document_id=p_document_id
    )''').replace('exists (select 1 from public.documents document where document.id=p_document_id and ledger.has_document_memo_reference_v1(p_document_id,document.company_id))', '''exists (
      select 1 from public.ledger_entries item
      join public.documents document on document.id=p_document_id
      where item.company_id=document.company_id
        and pg_catalog.strpos(item.memo, p_document_id::text)>0
    )''')
    assert predecessor!=definition
    db.execute(predecessor)
    before=db.execute("select pg_get_functiondef('documents.has_evidence_references_v1(uuid)'::regprocedure)").fetchone()[0]
    migration(db,EXPAND)
    assert db.execute("select pg_get_functiondef('documents.has_evidence_references_v1(uuid)'::regprocedure)").fetchone()[0]==before
    migration(db,CUTOVER)
    assert db.execute("select pg_get_functiondef('documents.has_evidence_references_v1(uuid)'::regprocedure)").fetchone()[0]==definition
