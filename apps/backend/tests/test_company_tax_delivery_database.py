"""Source reads against the final owned Supabase topology and restricted roles."""
import asyncio
import json
import os
import subprocess
from urllib.parse import urlparse
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
import pytest

from talli_backend.adapters.postgres_company_tax_filing import PostgresCompanyTaxSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.application.company_tax_filing_workflow import CompanyTaxApplication
from talli_backend.main import create_app
from talli_backend.modules.company_tax_filing.public import CompanyTaxError, CompanyTaxSourceQuery
from talli_backend.modules.ledger.service import LedgerService
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, CorrelationId, IncomeYear, UserId
from test_shareholder_register_filing_lifecycle import company, insert


pytestmark = pytest.mark.company_tax_database


@pytest.fixture
def source_runtime():
    url = os.environ.get('DATABASE_URL', '')
    assert urlparse(url).hostname in ('localhost', '127.0.0.1', '::1')
    role, password = 'tax_source_' + uuid4().hex, uuid4().hex
    with psycopg.connect(url) as db:
        assert db.execute('select phase from backend_system.company_tax_return_migration_state').fetchone() == ('contracted',)
        cid, owner = company(db)
        now = db.execute('select clock_timestamp()').fetchone()[0]
        insert(db, 'public.annual_data', id=uuid4(), company_id=cid, income_year=2025,
            answers=Jsonb({'company_tax_additional_attachments':'none', 'shareholder_loans':False,
                'declared_owner_dividends':False, 'bought_or_sold_shares':False}),
            confirmations=Jsonb([]), no_activity_confirmed=True, annual_full_time_equivalents=0,
            completed_by=owner, completed_at=now, updated_by=owner, updated_at=now)
        db.execute(sql.SQL('create role {} login noinherit nobypassrls password {}').format(sql.Identifier(role), sql.Literal(password)))
        db.execute(sql.SQL('grant company_tax_filing_workflow_executor,ledger_executor,investments_executor to {} with inherit false,set true').format(sql.Identifier(role)))
    backend = make_conninfo(url, user=role, password=password)
    actor = ActorId(ActorKind.USER, UserId(str(owner)))
    verified = _VerifiedActor(actor, json.dumps({'sub':str(owner),'role':'authenticated','aal':'aal2'}))
    class Sessions:
        async def session(self, _token): return PostgresCompanyTaxSession(backend, verified)
    try:
        yield url, backend, cid, actor, Sessions()
    finally:
        with psycopg.connect(url) as db:
            db.execute(sql.SQL('alter role {} nologin password null').format(sql.Identifier(role)))
            db.execute('delete from public.annual_data where company_id=%s', (cid,))
        subprocess.run(['node','tests/support/tax-fixture-cleanup.mjs'], input=json.dumps([str(cid)]),
            text=True, env={**os.environ,'DATABASE_URL':url}, check=True)
        with psycopg.connect(url) as db:
            db.execute('delete from auth.users where id=%s', (str(actor.subject),))
            db.execute(sql.SQL('drop role {}').format(sql.Identifier(role)))


def test_legacy_source_http_retains_migration_lock_in_repeatable_snapshot(source_runtime):
    _, _, cid, _, sessions = source_runtime
    client = TestClient(create_app(company_tax_session_factory=sessions))
    response = client.get('/api/v1/company-tax/source-facts',
        params={'companyId':str(cid),'incomeYear':2025}, headers={'Authorization':'Bearer synthetic-fixture'})
    assert response.status_code == 200, response.text
    assert response.json()['historyCoverage']['status'] == 'complete'
    assert response.json()['readinessStatus'] == 'blocked'


def test_internal_source_reads_all_owner_contracts_through_restricted_runtime(source_runtime):
    _, backend, cid, actor, sessions = source_runtime
    async def exercise():
        async with (await sessions.session('synthetic-fixture')).transaction(snapshot=True) as transaction:
            query = CompanyTaxSourceQuery(CompanyId(str(cid)), IncomeYear(2025), actor)
            assert (await transaction.filing_company_identity(query.company_id, actor)).company_id == query.company_id
            assert await transaction.delivery_annual_interview(query) is not None
            await transaction.delivery_ledger_queries.list_entries(actor_id=actor, company_ids=(query.company_id,),
                correlation_id=CorrelationId('source-database'), cursor=None, limit=100)
            await transaction.delivery_ledger_queries.list_entry_amendments(actor_id=actor, company_id=query.company_id,
                correlation_id=CorrelationId('source-database'))
            from talli_backend.modules.investments.public import read_investment_reporting_snapshot
            await read_investment_reporting_snapshot(transaction.delivery_investments_queries, actor_id=actor,
                company_id=query.company_id, income_year=query.income_year, correlation_id=CorrelationId('source-database'))
        application = await CompanyTaxApplication(sessions, LedgerService).session('synthetic-fixture')
        query = CompanyTaxSourceQuery(CompanyId(str(cid)), IncomeYear(2025), actor)
        source = await application.delivery_source(query, correlation_id=CorrelationId('source-database'))
        assert source.annual_data['no_activity_confirmed'] is True
        assert source.ledger_entries == () and source.holding_actions == ()
        assert set(source.upstream_sha256) == {'annual','ledger','investments'}
        changed_actor = ActorId(ActorKind.USER, UserId(str(uuid4())))
        with pytest.raises(CompanyTaxError):
            await application.delivery_source(CompanyTaxSourceQuery(query.company_id, query.income_year, changed_actor),
                correlation_id=CorrelationId('source-database-forged'))
    asyncio.run(exercise())
    with psycopg.connect(backend) as runtime:
        runtime.execute('set local role company_tax_filing_workflow_executor')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute('select * from public.annual_data')
