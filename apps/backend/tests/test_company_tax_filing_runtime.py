"""Concurrent real connections, restricted login and actual canonical HTTP service.

Requires the final owned disposable topology. Authentication identities alone are
synthetic; the later browser lane exercises Supabase JWT verification end-to-end.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
from threading import Barrier
from urllib.parse import urlparse
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from talli_backend.adapters.postgres_company_tax_filing import PostgresCompanyTaxSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.main import create_app
from talli_backend.shared.kernel import ActorId, ActorKind, UserId
from test_company_tax_filing_database import company, _admit_opening_year, linked_request, request, post

pytestmark = pytest.mark.company_tax_database


@pytest.fixture
def runtime():
    url=os.environ.get('DATABASE_URL','')
    assert urlparse(url).hostname in ('127.0.0.1','localhost','::1'), 'owned disposable loopback database required'
    role='tax_runtime_'+uuid4().hex;password=uuid4().hex
    with psycopg.connect(url) as db:
        assert db.execute('select phase from backend_system.tax_settlement_migration_state').fetchone()[0]=='contracted'
        cid,owner=company(db);_admit_opening_year(db,cid,owner)
        other,outsider=company(db);_admit_opening_year(db,other,outsider)
        body=linked_request(db,cid,owner,'payment')
        db.execute(sql.SQL('create role {} login noinherit nobypassrls password {}').format(sql.Identifier(role),sql.Literal(password)))
        db.execute(sql.SQL('grant company_tax_filing_workflow_executor to {} with inherit false,set true').format(sql.Identifier(role)))
    backend=make_conninfo(url,user=role,password=password)
    def client(actor=owner):
        verified=_VerifiedActor(ActorId(ActorKind.USER,UserId(str(actor))),json.dumps({'sub':str(actor),'role':'authenticated','aal':'aal2'}))
        class Sessions:
            async def session(self,token):return PostgresCompanyTaxSession(backend,verified)
        return TestClient(create_app(company_tax_session_factory=Sessions()))
    try:
        yield url,backend,cid,owner,other,outsider,body,client
    finally:
        with psycopg.connect(url) as db:
            db.execute(sql.SQL('alter role {} nologin password null').format(sql.Identifier(role)))
        subprocess.run(['node','tests/support/tax-fixture-cleanup.mjs'],input=json.dumps([str(cid),str(other)]),text=True,env={**os.environ,'DATABASE_URL':url},check=True)
        with psycopg.connect(url) as db:
            db.execute('delete from auth.users where id=any(%s::uuid[])',([owner,outsider],))
            db.execute(sql.SQL('drop role {}').format(sql.Identifier(role)))


def concurrent(requests):
    barrier=Barrier(len(requests))
    def execute(item):
        client,body=item
        barrier.wait(timeout=10)
        return post(client,body)
    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        return list(executor.map(execute,requests))


def test_same_receipt_concurrency_never_duplicates_effects(runtime):
    url,backend,cid,owner,other,outsider,body,client=runtime
    results=concurrent([(client(),body),(client(),body)])
    assert all(r.status_code in (201,409) for r in results),[r.text for r in results]
    assert any(r.status_code==201 for r in results)
    replay=post(client(),body)
    assert replay.status_code==201 and replay.json()['replayed'] is True
    with psycopg.connect(url) as db:
        assert db.execute('select count(*) from company_tax_filing.settlements where company_id=%s',(cid,)).fetchone()[0]==1
        assert db.execute("select count(*) from ledger.entries where company_id=%s and entry_kind='TAX_SETTLEMENT'",(cid,)).fetchone()[0]==1
        assert db.execute("select count(*) from backend_system.ledger_workflow_receipts where company_id=%s and operation_name='record_tax_settlement'",(cid,)).fetchone()[0]==1
        assert db.execute('select matched_action_reference,matched_accounting_entry_id from banking.transactions where id=%s',(body['bankTransactionId'],)).fetchone()==(body['actionId'],None)


def test_concurrent_actions_cannot_claim_the_same_bank_transaction(runtime):
    url,backend,cid,owner,other,outsider,body,client=runtime
    second={**body,'actionId':str(uuid4())}
    results=concurrent([(client(),body),(client(),second)])
    assert sorted(r.status_code for r in results)==[201,422],[r.text for r in results]
    with psycopg.connect(url) as db:
        assert db.execute('select count(*) from company_tax_filing.settlements where company_id=%s',(cid,)).fetchone()[0]==1
        assert db.execute("select count(*) from ledger.entries where company_id=%s and entry_kind='TAX_SETTLEMENT'",(cid,)).fetchone()[0]==1


def test_restricted_login_cannot_read_tables_or_assume_store_roles(runtime):
    url,backend,cid,owner,other,outsider,body,client=runtime
    with psycopg.connect(backend) as db:
        for query in ['select * from company_tax_filing.settlements','set local role company_tax_filing_store_owner','set local role company_tax_filing_identity_guard_owner','set local role ledger_store_owner']:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with db.transaction():db.execute(query)
    assert post(client(),body).status_code==201
    assert post(client(outsider),body).status_code==404
    assert post(client(),body).json()['replayed'] is True
