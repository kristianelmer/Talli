"""Default HTTP composition, real RF workflows/adapters, local owner/SQL ports only."""
from types import SimpleNamespace
from contextlib import asynccontextmanager
from dataclasses import fields, replace

import pytest
from fastapi.testclient import TestClient

from talli_backend import main
from talli_backend.adapters.postgres_shareholder_register_filing import (
    PostgresShareholderRegisterFilingAdapter,
    PostgresShareholderRegisterSourceDispatchV3Adapter,
)
from talli_backend.application.shareholder_register_filing_session import ShareholderRegisterFilingAuthenticationError
from talli_backend.application.shareholder_register_source_correction import ShareholderRegisterSourceCorrection
from talli_backend.modules.shareholder_register_filing import public as rf
from rf1086_guarded_capture_v2_fixture import CaptureHarness, KEY
from rf1086_preview_v2_fixture import PreviewHarnessV2
from rf1086_approval_v3_fixture import ApprovalHarnessV3
from test_shareholder_register_source_api import draft
from test_rf1086_retained_readiness_observation_v2 import close_fresh_rendering
from test_rf1086_source_claim_v3 import ClaimHarnessV3
from test_rf1086_source_dispatch_v3 import workflow_history_session
from test_rf1086_retained_source_dispatch import pending_v3, retained_submission
from test_rf1086_source_dispatch import annual_submission
from test_rf1086_source_submission_archive import source_submission_archive


BASE = '/api/v1/shareholder-register-filings'
HEADERS = {'Authorization': 'Bearer synthetic-token', 'X-Request-ID': 'default-source-http',
    'Idempotency-Key': str(KEY)}


def default_client(monkeypatch, base, documents):
    """Replace the authenticated port, never create_app's RF factory or workflows."""
    factories = []

    async def authenticated(self, token):
        if token != 'synthetic-token':
            raise ShareholderRegisterFilingAuthenticationError()
        factories.append(self)
        return base.store

    monkeypatch.setattr(PostgresShareholderRegisterFilingAdapter, 'session', authenticated)
    company = getattr(base, 'company', None)

    class CompanyGateway:
        async def session_subject(self, token):
            assert token == 'synthetic-token'
            return str(base.store.actor_id.subject)

        async def memberships(self, token, subject):
            return [{'company_id': company.id, 'role': company.role, 'accepted_at': '2026-01-01T00:00:00Z'}]

        async def companies(self, token, ids):
            return [{**vars(company), 'status_text': 'Active', 'source': 'synthetic',
                'created_by': str(base.store.actor_id.subject), 'created_at': '2026-01-01T00:00:00Z'}]

    app = main.create_app(company_access_gateway=CompanyGateway(), documents_session_factory=documents)
    return TestClient(app), factories


def assert_factory(factories, store, documents):
    assert factories and all(type(item) is PostgresShareholderRegisterSourceDispatchV3Adapter for item in factories)
    receiver = store._source_correction_v3
    assert type(receiver) is ShareholderRegisterSourceCorrection
    assert receiver._sessions is factories[-1] and receiver._documents is documents


def scope(source):
    return {'companyId': str(source.company_id), 'incomeYear': int(source.income_year)}


def test_default_capture_writes_v2_and_replays_before_changed_originals(monkeypatch):
    h = CaptureHarness(monkeypatch, 'no_activity', 0)
    documents = h.workflow._documents
    client, factories = default_client(monkeypatch, h, documents)
    response = client.post(BASE + '/year-sources', json=draft(h.command), headers=HEADERS)
    assert response.status_code == 200, response.text
    source = rf.parse_rf1086_year_source_v2(h.current['snapshot_text'])
    assert response.json()['sourceId'] == source.source_id.value
    assert response.json()['sourceSha256'] == source.source_sha256
    assert h.committed and not h.guard
    assert any('append_year_source_v2(' in sql for sql, _ in h.calls)
    assert not any('append_year_source_v1(' in sql for sql, _ in h.calls)
    assert_factory(factories, h.store, documents)
    current = client.get(BASE + '/current-year-source', params=scope(source), headers=HEADERS)
    assert current.status_code == 200, current.text
    assert current.json()['currentSource']['receipt'] == response.json()
    h.replay = h.current
    h.contents.clear()
    h.calls.clear()
    replay = client.post(BASE + '/year-sources', json=draft(h.command), headers=HEADERS)
    assert replay.status_code == 200 and replay.json() == response.json()
    assert not any(sql == 'bytes' or 'append_year_source_' in sql for sql, _ in h.calls)


def test_default_preview_generates_and_reads_same_wire_through_held_v2(monkeypatch):
    h = PreviewHarnessV2(monkeypatch, 'no_activity', 0)
    documents = h.admission.workflow._documents
    client, factories = default_client(monkeypatch, h.base, documents)
    response = client.post(BASE + '/source-previews', json={**scope(h.source),
        'sourceId': h.source.source_id.value}, headers=HEADERS)
    assert response.status_code == 200, response.text
    saved = next(iter(h.captures.values()))
    assert response.json() == main._rf_source_preview_wire(saved.preview).model_dump(mode='json', by_alias=True)
    assert h.base.committed and not h.base.guard and h.held_proof_calls
    read = client.get(BASE + '/source-previews/' + saved.preview.preview_id.value,
        params=scope(h.source), headers=HEADERS)
    assert read.status_code == 200 and read.json() == response.json()
    assert len(h.captures) == 1 and not h.base.guard
    assert_factory(factories, h.base.store, documents)


def test_default_review_projects_context_and_approval_writes_v3_only(monkeypatch):
    h = ApprovalHarnessV3(monkeypatch)
    close_fresh_rendering(monkeypatch)
    documents = h.admission.workflow._documents
    client, factories = default_client(monkeypatch, h.base, documents)
    command = {**scope(h.source), 'previewId': h.capture.preview.preview_id.value,
        'entitlementId': h.entitlement_id}
    response = client.post(BASE + '/source-production-reviews', json=command, headers=HEADERS)
    assert response.status_code == 200, response.text
    review = response.json()
    assert set(review) == {'companyId', 'incomeYear', 'previewId', 'sourceId', 'sourceSha256',
        'entitlementId', 'reviewSha256', 'warningCodes', 'blockers', 'canApprove'}
    assert review['canApprove'] is True and review['sourceSha256'] == h.source.source_sha256
    assert 'annual_readiness' not in response.text and 'proof' not in response.text
    approval = {**command, 'reviewSha256': review['reviewSha256'],
        'acknowledgedWarningCodes': review['warningCodes'], 'realFilingConfirmed': True}
    first = client.post(BASE + '/source-production-approvals', json=approval, headers=HEADERS)
    second = client.post(BASE + '/source-production-approvals', json=approval, headers=HEADERS)
    assert first.status_code == second.status_code == 200, first.text
    assert first.json() == second.json() and len(h.approvals) == 1
    assert 'production-source-approval-v3' in next(iter(h.approvals.values()))['payload_text']
    names = [sql for sql, _ in h.base.calls]
    assert any('append_source_approval_v3(' in sql for sql in names)
    assert not any('append_source_approval_v2(' in sql for sql in names)
    assert_factory(factories, h.base.store, documents)


def test_default_preview_rejects_changed_owner_before_append(monkeypatch):
    h = PreviewHarnessV2(monkeypatch, 'no_activity', 0)
    client, _ = default_client(monkeypatch, h.base, h.admission.workflow._documents)
    h.base.owner = False
    response = client.post(BASE + '/source-previews', json={**scope(h.source),
        'sourceId': h.source.source_id.value}, headers=HEADERS)
    assert response.status_code == 403, response.text
    assert not h.captures and not h.base.committed and not h.base.guard


@pytest.mark.parametrize('field', ['companyId', 'incomeYear', 'previewId'])
def test_default_preview_read_conceals_other_scope_before_original_io(monkeypatch, field):
    h = ApprovalHarnessV3(monkeypatch)
    client, _ = default_client(monkeypatch, h.base, h.admission.workflow._documents)
    query, preview_id = scope(h.source), h.capture.preview.preview_id.value
    if field == 'previewId':
        preview_id = '00000000-0000-4000-8000-000000009999'
    else:
        query[field] = '00000000-0000-4000-8000-000000009999' if field == 'companyId' else 2024
    h.base.calls.clear()
    response = client.get(BASE + '/source-previews/' + preview_id, params=query, headers=HEADERS)
    assert response.status_code == 404, response.text
    assert not any(sql == 'bytes' or 'append_' in sql for sql, _ in h.base.calls)


def test_default_send_claims_v3_before_closed_provider_gate(monkeypatch):
    owner = ClaimHarnessV3(monkeypatch)
    close_fresh_rendering(monkeypatch)
    h = owner.h
    client, factories = default_client(monkeypatch, h.base, h.admission.workflow._documents)
    # The first durable claim is real V3 code. Stop only subsequent operation
    # history at the closed configuration gate, without a provider transport.
    @asynccontextmanager
    async def history(claim):
        async def read():
            return SimpleNamespace(assessment=SimpleNamespace(
                disposition='current_admission_required', pending_operation='confirm'),
                retained_archive=SimpleNamespace(approvals=(owner.approval,)))
        yield SimpleNamespace(read_operation_recovery=read)
    monkeypatch.setattr(h.base.store, 'source_operation_recovery_v3', history)
    response = client.post(BASE + '/source-production-filings', json={
        'approvalId': owner.approval_id.value, 'manifestSha256': owner.digest,
        'expectedHead': None}, headers=HEADERS)
    assert response.status_code == 503 and response.json()['code'] == 'configuration_unavailable'
    assert owner.existing is not None
    assert any('claim_source_submission_v3(' in sql for sql, _ in h.base.calls)
    assert_factory(factories, h.base.store, h.admission.workflow._documents)


@pytest.mark.parametrize('failure', [None, 'unknown', 'blocked'])
def test_default_send_retained_replay_or_uncertainty_has_no_provider_effect(monkeypatch, failure):
    archive = retained_submission('no_activity', 0, 'accepted', correction=False) if failure is None else pending_v3(0, failure=failure)
    store, claim, physical, events, _ = workflow_history_session(monkeypatch, archive)
    current_calls = []
    def forbidden_current_port(*args, **kwargs):
        current_calls.append('current-or-provider-port')
        raise AssertionError('Historical recovery entered current/provider admission')
    for name in ('require_configuration', 'bind_mutation_authority', 'source_admission',
            'read_source_operation_approval_v3', 'company_record'):
        monkeypatch.setattr(store, name, forbidden_current_port)
    client, factories = default_client(monkeypatch, SimpleNamespace(store=store), SimpleNamespace())
    command = {'approvalId': claim.approval_id.value, 'manifestSha256': claim.manifest_sha256,
        'expectedHead': None if claim.predecessor_submission_id is None else claim.predecessor_submission_id.value}
    first = client.post(BASE + '/source-production-filings', json=command, headers=HEADERS)
    second = client.post(BASE + '/source-production-filings', json=command, headers=HEADERS)
    assert first.json() == second.json()
    if failure is None:
        assert first.status_code == second.status_code == 200
        assert first.json() == {'submissionId': claim.submission_id.value}
    else:
        assert first.status_code == second.status_code == 409
        assert first.json()['code'] == ('rf1086_unknown_production_outcome' if failure == 'unknown' else 'rf1086_blocked_production_operation')
    assert events == ['initial-claim', 'historical-lock', 'claim', 'archive', 'released'] * 2
    assert current_calls == []
    assert_factory(factories, store, factories[-1]._documents)


@pytest.mark.parametrize('denial', ['wrong_actor', 'revoked_owner'])
def test_default_retained_recovery_does_not_bypass_actor_or_revoked_owner(monkeypatch, denial):
    """HTTP authority ports are doubles; unchanged database cases test real revocation."""
    from talli_backend.shared.kernel import UserId
    store, claim, physical, events, _ = workflow_history_session(monkeypatch, pending_v3(0, failure='unknown'))
    if denial == 'wrong_actor':
        store._verified.actor_id = replace(store.actor_id, subject=UserId('00000000-0000-4000-8000-000000009999'))
    else:
        async def revoked(sql, args):
            assert 'lock_source_claim_recovery_v3' in sql
            raise rf.ShareholderRegisterFilingError.forbidden()
        physical.execute = revoked
    def no_provider(*args, **kwargs):
        raise AssertionError('Denied historical recovery entered provider admission')
    monkeypatch.setattr(store, 'require_configuration', no_provider)
    monkeypatch.setattr(store, 'bind_mutation_authority', no_provider)
    client, _ = default_client(monkeypatch, SimpleNamespace(store=store), SimpleNamespace())
    response = client.post(BASE + '/source-production-filings', json={
        'approvalId': claim.approval_id.value, 'manifestSha256': claim.manifest_sha256,
        'expectedHead': None if claim.predecessor_submission_id is None else claim.predecessor_submission_id.value}, headers=HEADERS)
    assert response.status_code == (409 if denial == 'wrong_actor' else 403), response.text
    assert 'archive' not in events


@pytest.mark.parametrize('archive_factory', [source_submission_archive, annual_submission], ids=['v1', 'v2'])
def test_default_send_preserves_legacy_confirmed_history_without_activation(monkeypatch, archive_factory):
    archive = archive_factory(status='accepted')
    store, claim, _, events, _ = workflow_history_session(monkeypatch, archive)
    client, _ = default_client(monkeypatch, SimpleNamespace(store=store), SimpleNamespace())
    response = client.post(BASE + '/source-production-filings', json={
        'approvalId': claim.approval_id.value, 'manifestSha256': claim.manifest_sha256,
        'expectedHead': None if claim.predecessor_submission_id is None else claim.predecessor_submission_id.value}, headers=HEADERS)
    assert response.status_code == 200 and response.json() == {'submissionId': claim.submission_id.value}
    assert events == ['initial-claim', 'historical-lock', 'claim', 'archive', 'released']


def test_default_position_uses_v3_owned_header_without_current_configuration(monkeypatch):
    from test_consequential_adapter_guards import rf_session
    archive = retained_submission('no_activity', 0, 'accepted', correction=False)
    approval, lineage = archive.approvals[0], archive.source_approval_lineage[0]
    store = rf_session()
    store._verified = SimpleNamespace(actor_id=archive.source_submission_claims[0].claimed_by)
    calls = []

    async def execute(sql, args):
        assert 'source_approval_bindings' in sql and 'company_access_is_accepted_owner_v1' in sql
        assert args == (approval.id,)
        calls.append('owned-header')
        async def fetchone():
            return {**{field.name: getattr(approval, field.name) for field in fields(approval)},
                'manifest_text': lineage.manifest_text}
        return SimpleNamespace(fetchone=fetchone)

    @asynccontextmanager
    async def transaction(**options):
        assert options == {'snapshot': True}
        yield SimpleNamespace(execute=execute)

    async def archive_source(query):
        assert (query.company_id, query.income_year, query.actor_id) == (
            archive.company_id, archive.income_year, store.actor_id)
        calls.append('archive')
        return archive

    monkeypatch.setattr(store, '_transaction', transaction)
    monkeypatch.setattr(store, 'archive_source', archive_source)
    client, _ = default_client(monkeypatch, SimpleNamespace(store=store), SimpleNamespace())
    response = client.get(BASE + '/source-production-filings/' + approval.id, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()['disposition'] == 'confirmed'
    assert calls == ['owned-header', 'archive']


@pytest.mark.parametrize('suffix,payload', [
    ('source-previews', {'companyId': 'bad', 'incomeYear': 2025, 'sourceId': 'bad'}),
    ('source-production-filings', {'approvalId': 'bad', 'manifestSha256': 'a' * 64}),
])
def test_default_routes_reject_transport_before_auth_port(monkeypatch, suffix, payload):
    calls = []
    async def no_session(self, token):
        calls.append(token)
        raise AssertionError('invalid HTTP request entered authenticated port')
    monkeypatch.setattr(PostgresShareholderRegisterFilingAdapter, 'session', no_session)
    client = TestClient(main.create_app())
    assert client.post(BASE + '/' + suffix, json=payload, headers=HEADERS).status_code == 422
    assert calls == []
