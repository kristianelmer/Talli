"""Draft retention and V2 coverage in the full restricted Supabase topology."""
import asyncio
from dataclasses import replace
from uuid import uuid4
import json
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg
from psycopg.conninfo import conninfo_to_dict

import pytest
from fastapi.testclient import TestClient

from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.adapters.postgres_company_tax_filing import PostgresCompanyTaxSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError, CompanyTaxSourceQuery, TaxDeliveryDraft,
    prepare_tax_delivery, project_company_tax_source,
)
from talli_backend.application.company_tax_filing_workflow import CompanyTaxApplication
from talli_backend.main import create_app
from talli_backend.modules.ledger.service import LedgerService
from talli_backend.shared.kernel import CompanyId, CorrelationId, IncomeYear, IdempotencyKey
from test_company_tax_delivery_database import source_runtime

pytestmark = pytest.mark.company_tax_database


class MfaSessions:
    def __init__(self, backend, actor):
        self.backend, self.actor, self.age = backend, actor, 0

    async def session(self, _token):
        claims = {'sub':str(self.actor.subject),'role':'authenticated','aal':'aal2',
            'amr':[{'method':'totp','timestamp':int(time.time())-self.age}]}
        return PostgresCompanyTaxSession(self.backend,_VerifiedActor(self.actor,json.dumps(claims)))


def test_complete_owner_source_can_be_retained_and_replayed_without_any_provider_effect(source_runtime):
    _, backend, cid, actor, sessions = source_runtime
    async def exercise():
        app = await CompanyTaxApplication(sessions,LedgerService).session('synthetic-fixture')
        query = CompanyTaxSourceQuery(CompanyId(str(cid)),IncomeYear(2025),actor)
        source = await app.delivery_source(query,correlation_id=CorrelationId('retained-source-database'))
        validator = PinnedTax2025Schemas()
        envelope = prepare_tax_delivery(source,party_number='123456',current_document_reference='synthetic-current-2025',
            schema_sha256=validator.schema_sha256)
        draft = TaxDeliveryDraft(str(uuid4()),IdempotencyKey('retained-source-database-key'),actor,envelope,validator.validate(envelope))
        session = await sessions.session('synthetic-fixture')
        async with session.transaction() as tx: first = await tx.store_delivery_draft(draft)
        async with session.transaction() as tx:
            assert await tx.store_delivery_draft(draft) == first
            assert await tx.delivery_draft_by_key(query,draft.command_key) == first
        async with session.transaction(snapshot=True) as tx:
            current = project_company_tax_source(query,await tx.filing_source_snapshot(query))
            snapshot = await tx.delivery_history_snapshot(query)
            new = project_company_tax_source(query,snapshot)
        assert current.evidence.digest == new.evidence.digest
        assert current.delivery_drafts == new.delivery_drafts
        assert snapshot.coverage['declaredExtentValid'] is False
        assert new.history_coverage.status == 'complete',new.history_coverage.reasons
        assert new.delivery_drafts[0].draft_sha256 == draft.sha256
        assert new.recorded_submissions == new.production_attempts == ()
        assert new.readiness_status == 'blocked'
        with pytest.raises(CompanyTaxError):
            async with session.transaction() as tx:
                await tx.store_delivery_draft(replace(draft,filing_id=str(uuid4())))
        return draft
    retained = asyncio.run(exercise())
    client = TestClient(create_app(company_tax_session_factory=sessions))
    legacy = client.get('/api/v1/company-tax/source-facts',params={'companyId':str(cid),'incomeYear':2025},
        headers={'Authorization':'Bearer synthetic-fixture'})
    assert legacy.status_code == 200 and 'deliveryDrafts' not in legacy.json()
    response = client.get('/api/v1/company-tax/source-facts',params={'companyId':str(cid),'incomeYear':2025,'includeDeliveryDrafts':True},
        headers={'Authorization':'Bearer synthetic-fixture'})
    assert response.status_code == 200, response.text
    facts = response.json()
    assert facts['historyCoverage']['status'] == 'complete'
    assert facts['evidence']['version'].startswith('company-tax-source-v2:')
    assert facts['deliveryDrafts'][0]['preparedBy'] == str(actor.subject)
    assert facts['deliveryDrafts'][0]['status'] == 'prepared_only'
    assert facts['recordedSubmissions'] == facts['productionAttempts'] == []
    assert 'canonical_json' not in response.text and 'envelope_xml' not in response.text
    archive_path = '/api/v1/company-tax/archive-source/delivery-drafts-v1'
    params = {'companyId':str(cid),'incomeYear':2025}
    assert client.get(archive_path,params=params).status_code == 401
    assert client.get(archive_path,params=params,headers={'Authorization':'Bearer synthetic-fixture'}).status_code == 403
    fresh = MfaSessions(backend,actor)
    archive_client = TestClient(create_app(company_tax_session_factory=fresh))
    response = archive_client.get(archive_path,params=params,headers={'Authorization':'Bearer synthetic-fixture'})
    assert response.status_code == 200,response.text
    original = response.json()
    assert original['recordCount'] == 1
    assert original['records'][0]['canonicalJson'] == retained.canonical_json
    assert original['records'][0]['draftSha256'] == retained.sha256
    assert original['coverage'] == 'complete'
    assert archive_client.get(archive_path,params={'companyId':str(uuid4()),'incomeYear':2025},
        headers={'Authorization':'Bearer synthetic-fixture'}).status_code == 404
    fresh.age = 3600
    assert archive_client.get(archive_path,params=params,headers={'Authorization':'Bearer synthetic-fixture'}).status_code == 403


def test_empty_new_store_is_positively_enumerated_only_by_the_versioned_successor(source_runtime):
    _, _, cid, actor, sessions = source_runtime
    async def exercise():
        query = CompanyTaxSourceQuery(CompanyId(str(cid)),IncomeYear(2025),actor)
        async with (await sessions.session('synthetic-fixture')).transaction(snapshot=True) as tx:
            snapshot = await tx.delivery_history_snapshot(query)
            facts = project_company_tax_source(query,snapshot)
        assert snapshot.coverage['declaredExtentValid'] is False
        assert snapshot.coverage['declaredDeliveryExtentValid'] is True
        assert snapshot.coverage['deliveryDraftCount'] == 0
        assert facts.history_coverage.status == 'complete'
        assert facts.delivery_drafts == ()
        assert facts.readiness_status == 'blocked'
    asyncio.run(exercise())


def test_archive_denies_owner_revoked_while_waiting_for_current_company_guard(source_runtime):
    url,backend,cid,actor,_ = source_runtime
    client = TestClient(create_app(company_tax_session_factory=MfaSessions(backend,actor)))
    runtime = conninfo_to_dict(backend)['user']
    with psycopg.connect(url) as blocker, ThreadPoolExecutor(max_workers=1) as workers:
        accepted = blocker.execute('select accepted_at from public.company_memberships where company_id=%s and user_id=%s',
            (cid,str(actor.subject))).fetchone()[0]
        blocker.execute('select public.company_archive_lock_company_v1(%s)',(cid,))
        future = workers.submit(client.get,'/api/v1/company-tax/archive-source/delivery-drafts-v1',
            params={'companyId':str(cid),'incomeYear':2025},headers={'Authorization':'Bearer synthetic-fixture'})
        try:
            waiting = False
            for _ in range(100):
                with psycopg.connect(url,autocommit=True) as probe:
                    waiting = probe.execute("select exists(select 1 from pg_stat_activity where usename=%s and wait_event='advisory' and query like '%%lock_delivery_draft_archive_v1%%')",(runtime,)).fetchone()[0]
                if waiting: break
                time.sleep(.02)
            assert waiting, 'Observe the actual restricted archive guard wait.'
            blocker.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',
                (cid,str(actor.subject)))
            blocker.commit()
            assert future.result(timeout=10).status_code == 404
        finally:
            blocker.rollback()
            with psycopg.connect(url,autocommit=True) as restore:
                restore.execute('update public.company_memberships set accepted_at=%s where company_id=%s and user_id=%s',
                    (accepted,cid,str(actor.subject)))
