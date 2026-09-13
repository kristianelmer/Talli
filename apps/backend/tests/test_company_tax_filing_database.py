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
from talli_backend.adapters.supabase_ledger import _VerifiedActor, _map_database_error
from talli_backend.main import create_app
from talli_backend.shared.kernel import ActorId, ActorKind, UserId
from test_shareholder_register_filing_lifecycle import company, insert, _admit_opening_year

pytestmark = pytest.mark.authority_database
ROOT = Path(__file__).resolve().parents[3]
EXPAND = 'supabase/migrations/20260913171000_company_tax_settlement_expand.sql'
CUTOVER = 'supabase/contract-migrations/20260913172000_company_tax_settlement_cutover.sql'
ROLLBACK = 'supabase/rollback/20260913171000_company_tax_settlement_expand.sql'


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


def client(db, actor):
    verified = _VerifiedActor(ActorId(ActorKind.USER, UserId(str(actor))), json.dumps({'sub':str(actor),'role':'authenticated','aal':'aal2'}))
    db.execute('grant company_tax_filing_workflow_executor to postgres with inherit false,set true')
    class Session:
        actor_id = verified.actor_id
        async def session(self, token): return self
        @asynccontextmanager
        async def transaction(self):
            try:
                with db.transaction():
                    db.execute('set local role company_tax_filing_workflow_executor')
                    db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)", (str(actor),verified.claims_json))
                    yield PostgresCompanyTaxTransaction('', verified, AsyncConnection(db))
            except psycopg.Error as error:
                raise _map_database_error(str(error)) from None
            finally:
                db.execute('reset role')
    return TestClient(create_app(company_tax_session_factory=Session()))


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
    generation=db.execute('select to_jsonb(g) from public.company_archive_source_generations g where company_id=%s',(cid,)).fetchall()
    migration(db,ROLLBACK)
    restored=db.execute('select jsonb_agg(to_jsonb(t) order by id) from public.holding_actions t where company_id=%s',(cid,)).fetchone()[0]
    assert restored==original['company_tax_filing.settlements']
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
