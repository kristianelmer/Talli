"""Shared company archives cross the owning lossless Accounts codec."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
import hashlib
import json
from uuid import uuid4

import pytest

from talli_backend.application.annual_accounts_workflow import AuthenticatedAnnualAccounts
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsError, build_annual_accounts_company_archive, parse_annual_accounts_company_archive,
    annual_accounts_delivery_originals, project_annual_accounts_source,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp
from test_annual_accounts_delivery_records import draft
from test_annual_accounts_delivery_event_source import event_source
from test_annual_accounts_delivery_corrections import Correction
from test_annual_accounts_delivery_journal import complete_world
from talli_backend.modules.annual_accounts_filing.delivery import _canonical


def correction_source(draft):
    query, base = event_source(draft)
    parent = complete_world(draft)
    child = Correction(parent)
    child.observe(); child.finish()
    drafts = (parent.stored, child.stored)
    events = tuple((*parent.events, *child.events))
    proof = dict(base.coverage) | {'contractVersion': 'annual-accounts-source-v4',
        'deliveryEventCodecVersion': 'annual-accounts-delivery-events-v2',
        'deliveryDraftCount': len(drafts), 'deliveryDraftDigests': {row.draft.filing_id: row.draft.sha256 for row in drafts},
        'deliveryEventCount': len(events), 'deliveryEventDigests': {str(row.sequence): row.record.sha256 for row in events}}
    return query, replace(base, contract_version='annual-accounts-source-v4', coverage=proof,
        delivery_drafts=drafts, delivery_events=events, as_of=Timestamp(child.now.value + timedelta(seconds=1))), parent.schemas


def originals(snapshot):
    return tuple(value for stored in snapshot.delivery_drafts for value in annual_accounts_delivery_originals(stored,
        tuple(row for row in snapshot.delivery_events if row.record.binding.filing_id == stored.draft.filing_id)))


def test_root_correction_and_all_pdf_signature_technical_originals_survive_exact_copy(draft):
    query, snapshot, schemas = correction_source(draft)
    archive = build_annual_accounts_company_archive(query, snapshot)
    restored = parse_annual_accounts_company_archive(archive.canonical_json, query=query, expected_sha256=archive.sha256)
    assert restored == snapshot
    assert archive.draft_count == 2 and archive.event_count == len(snapshot.delivery_events)
    assert archive.original_count == len(originals(snapshot))
    assert originals(restored) == originals(snapshot)
    assert any(row.purpose == 'pdf' for row in originals(restored))
    assert any(row.purpose == 'signature' for row in originals(restored))
    assert any(row.purpose.startswith('parent_') for row in originals(restored))
    assert project_annual_accounts_source(query, restored).evidence.digest == archive.source_sha256
    assert build_annual_accounts_company_archive(query, restored) == archive


@pytest.mark.parametrize('defect', ['scope','year','digest','whitespace','duplicate-key','codec','missing-draft','missing-event',
    'event-order','coverage','original','orphan-parent','wrong-source','extra-field'])
def test_copy_refuses_changed_scope_bytes_or_incomplete_history_even_after_outer_rehash(draft, defect):
    query, snapshot, schemas = correction_source(draft)
    archive = build_annual_accounts_company_archive(query, snapshot)
    value = json.loads(archive.canonical_json)
    if defect == 'scope': query = replace(query, company_id=CompanyId(str(uuid4())))
    elif defect == 'year': query = replace(query, income_year=IncomeYear(2024))
    elif defect == 'codec': value['codec'] = 'future'
    elif defect == 'missing-draft': value['drafts'].pop()
    elif defect == 'missing-event': value['events'].pop(5)
    elif defect == 'event-order': value['events'].reverse()
    elif defect == 'coverage': value['coverage']['deliveryArchiveTrackingValid'] = False
    elif defect == 'wrong-source': value['sourceSha256'] = '0' * 64
    elif defect == 'extra-field': value['authority'] = True
    elif defect == 'original': value['events'][5]['canonicalJson'] += ' '
    elif defect == 'orphan-parent':
        value['drafts'].pop(0)
        value['coverage']['deliveryDraftCount'] = 1
        value['coverage']['deliveryDraftDigests'].pop(draft.filing_id)
        value['events'] = [row for row in value['events'] if json.loads(row['canonicalJson'])['record']['binding']['filing_id'] != draft.filing_id]
        value['coverage']['deliveryEventCount'] = len(value['events'])
        value['coverage']['deliveryEventDigests'] = {str(row['sequence']): row['sha256'] for row in value['events']}
    raw = _canonical(value)
    if defect == 'whitespace': raw += ' '
    if defect == 'duplicate-key': raw = raw.replace('"codec":', '"codec":"discarded","codec":', 1)
    digest = '0' * 64 if defect == 'digest' else hashlib.sha256(raw.encode()).hexdigest()
    with pytest.raises(AnnualAccountsError):
        parse_annual_accounts_company_archive(raw, query=query, expected_sha256=digest)


@pytest.mark.parametrize('late_failure', [False, True])
def test_archive_holds_current_owner_guard_and_rechecks_after_repeatable_read(draft, late_failure):
    query, snapshot, schemas = correction_source(draft)
    calls = []
    class Session:
        actor_id = query.actor_id
        @asynccontextmanager
        async def transaction(self, *, snapshot=False):
            calls.append('snapshot' if snapshot else 'guard')
            class Transaction:
                async def lock_delivery_archive(self, got):
                    assert got == query and not snapshot
                    calls.append('lock')
                    if late_failure and calls.count('lock') == 2: raise AnnualAccountsError.mfa_required()
                async def filing_source_snapshot(self, got):
                    assert got == query and snapshot
                    calls.append('read')
                    return source
            yield Transaction()
    source = snapshot
    class Workflow: _schemas = schemas
    app = AuthenticatedAnnualAccounts(Session(), delivery=Workflow())
    if late_failure:
        with pytest.raises(AnnualAccountsError): asyncio.run(app.company_year_archive(query))
    else:
        assert asyncio.run(app.company_year_archive(query)).draft_count == 2
    assert calls == ['guard','lock','snapshot','read','lock']
    with pytest.raises(AnnualAccountsError):
        asyncio.run(app.company_year_archive(replace(query, actor_id=replace(query.actor_id, subject=type(query.actor_id.subject)(str(uuid4()))))))


def test_company_archive_http_uses_current_authorization_and_preserves_exact_codec(draft):
    from fastapi.testclient import TestClient
    from talli_backend.main import create_app
    from talli_backend.application.ledger_session import LedgerAuthenticationError
    query, source, schemas = correction_source(draft)
    class Sessions:
        actor_id = query.actor_id
        mfa = True
        async def session(self, token):
            if token != 'synthetic': raise LedgerAuthenticationError()
            return self
        @asynccontextmanager
        async def transaction(self, *, snapshot=False):
            owner = self
            class Transaction:
                async def lock_delivery_archive(self, got):
                    if got.company_id != query.company_id: raise AnnualAccountsError.not_found()
                    if not owner.mfa: raise AnnualAccountsError.mfa_required()
                async def filing_source_snapshot(self, got):
                    assert snapshot and got == query
                    return source
            yield Transaction()
    sessions = Sessions()
    http = TestClient(create_app(annual_accounts_session_factory=sessions))
    path = '/api/v1/annual-accounts/company-year-archive'
    params = dict(companyId=str(query.company_id), incomeYear=2025)
    headers = {'Authorization':'Bearer synthetic'}
    response = http.get(path, params=params, headers=headers)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    archive = build_annual_accounts_company_archive(query, source)
    assert response.json()['canonicalJson'] == archive.canonical_json
    assert response.json()['sha256'] == archive.sha256
    verification_path = '/api/v1/annual-accounts/company-year-archive-verifications'
    wire = response.json()
    verification = http.post(verification_path, json=wire, headers=headers)
    assert verification.status_code == 200, verification.text
    assert verification.json()['archiveSha256'] == archive.sha256
    assert verification.json()['originalCount'] == archive.original_count
    assert any(row['purpose'] == 'signature' for row in verification.json()['originals'])
    assert http.post(verification_path, json=wire).status_code == 401
    assert http.post(verification_path, json=wire | {'companyId':str(uuid4())}, headers=headers).status_code == 404
    assert http.post(verification_path, json=wire | {'canonicalJson':wire['canonicalJson'] + ' '}, headers=headers).status_code == 503
    assert http.get(path, params=params).status_code == 401
    assert http.get(path, params=params | {'companyId':str(uuid4())}, headers=headers).status_code == 404
    sessions.mfa = False
    assert http.get(path, params=params, headers=headers).status_code == 403
    assert http.post(verification_path, json=wire, headers=headers).status_code == 403

def test_complete_archived_history_survives_unavailable_schema_resources(draft, monkeypatch):
    from talli_backend.adapters.annual_accounts_schemas import PinnedAnnualAccountsSchemas
    query, snapshot, _ = correction_source(draft)
    def unavailable(*args, **kwargs):
        raise AssertionError('Archive read must not reload schema resources.')
    monkeypatch.setattr(PinnedAnnualAccountsSchemas, 'validate_pair', unavailable)
    archive = build_annual_accounts_company_archive(query, snapshot)
    restored = parse_annual_accounts_company_archive(archive.canonical_json, query=query, expected_sha256=archive.sha256)
    assert originals(restored) == originals(snapshot)
