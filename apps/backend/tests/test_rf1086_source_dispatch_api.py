"""Strict send transport and recovery responses through synthetic dispatch."""
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from talli_backend import main
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.application.shareholder_register_filing_session import ShareholderRegisterFilingAuthenticationError
from test_rf1086_source_approval_api import NeverSessions
from test_rf1086_source_dispatch_workflow import Harness
from test_rf1086_source_dispatch import annual_submission
from talli_backend.application.shareholder_register_source_dispatch import ShareholderRegisterSourceDispatchWorkflow

PATH = '/api/v1/shareholder-register-filings/source-production-filings'
HEADERS = {'Authorization': 'Bearer token', 'X-Request-ID': 'source-dispatch-api'}
APPROVAL = '00000000-0000-4000-8000-000000000001'
SUBMISSION = '00000000-0000-4000-8000-000000000002'


def body():
    return {'approvalId': APPROVAL, 'manifestSha256': 'a'*64, 'expectedHead': None}


@pytest.mark.parametrize('field,value', [
    ('approvalId', None), ('approvalId', 'invalid'), ('manifestSha256', None),
    ('manifestSha256', 'A'*64), ('manifestSha256', 'a'*63), ('manifestSha256', 'a'*64+'\n'),
    ('expectedHead', 'invalid'), ('expectedHead', True), ('actorId', APPROVAL),
    ('companyId', APPROVAL), ('incomeYear', 2026), ('xml', '<caller/>'),
    ('annualReadiness', {}), ('ready', True), ('newlyPrepared', True),
    ('idempotencyKey', SUBMISSION), ('operationId', SUBMISSION),
])
def test_untrusted_fields_and_malformed_identity_never_enter_session(field, value):
    sessions = NeverSessions()
    client = TestClient(main.create_app(shareholder_register_filing_session_factory=sessions))
    response = client.post(PATH, json={**body(), field: value}, headers=HEADERS)
    assert response.status_code == 422 and sessions.calls == 0


def test_bearer_required_before_session():
    sessions = NeverSessions()
    client = TestClient(main.create_app(shareholder_register_filing_session_factory=sessions))
    assert client.post(PATH, json=body()).status_code == 401
    assert sessions.calls == 0


def test_exact_identity_and_correlation_reach_dispatch(monkeypatch):
    calls = []
    async def send(token, **args):
        calls.append((token, args))
        return rf.Rf1086SendResult(SUBMISSION)
    monkeypatch.setattr(main, 'ShareholderRegisterSourceDispatchWorkflow', lambda *args: SimpleNamespace(send=send))
    client = TestClient(main.create_app())
    response = client.post(PATH, json={**body(), 'expectedHead': SUBMISSION}, headers=HEADERS)
    assert response.status_code == 200 and response.json() == {'submissionId': SUBMISSION}
    token, args = calls[0]
    assert token == 'token' and args['approval_id'] == rf.ApprovalId(APPROVAL)
    assert args['manifest_sha256'] == 'a'*64 and args['expected_head'] == rf.SubmissionId(SUBMISSION)
    assert str(args['correlation_id']) == HEADERS['X-Request-ID']
    assert response.headers['x-request-id'] == HEADERS['X-Request-ID']


@pytest.mark.parametrize('error,status,code', [
    (ShareholderRegisterFilingAuthenticationError(), 401, 'authentication_required'),
    (rf.Rf1086ProductionError('configuration_unavailable'), 503, 'configuration_unavailable'),
    (rf.Rf1086ProductionError('payload_changed'), 409, 'payload_changed'),
    (rf.Rf1086ProductionError('step_up_required'), 409, 'step_up_required'),
    (rf.Rf1086BlockedProductionOperationError('post_hovedskjema'), 409, 'rf1086_blocked_production_operation'),
    (rf.Rf1086UnknownProductionOutcomeError('confirm'), 409, 'rf1086_unknown_production_outcome'),
    (OSError('private credential: synthetic-secret'), 503, 'send_unavailable'),
    (ValueError('private authority response'), 503, 'send_unavailable'),
])
def test_actionable_errors_preserve_uncertainty_without_leaking_details(monkeypatch, error, status, code):
    async def send(*args, **kwargs): raise error
    monkeypatch.setattr(main, 'ShareholderRegisterSourceDispatchWorkflow', lambda *args: SimpleNamespace(send=send))
    response = TestClient(main.create_app()).post(PATH, json=body(), headers=HEADERS)
    assert response.status_code == status and response.json()['code'] == code
    assert response.headers['content-type'].startswith('application/problem+json')
    assert 'private' not in response.text and 'synthetic-secret' not in response.text


@pytest.mark.parametrize('stage', [None, 'post_hovedskjema', 'post_underskjema', 'confirm'])
def test_http_dispatch_replay_and_lost_responses_never_duplicate_posts(monkeypatch, stage):
    h = Harness(monkeypatch)
    if stage:
        original = getattr(h.authority, stage)
        async def lost(**args):
            await original(**args)
            raise rf.Rf1086AuthorityError('LOST_RESPONSE')
        setattr(h.authority, stage, lost)
    monkeypatch.setattr(main, 'ShareholderRegisterSourceDispatchWorkflow', lambda *args: h.workflow)
    client = TestClient(main.create_app())
    command = {'approvalId': h.claim.approval_id.value, 'manifestSha256': h.claim.manifest_sha256,
        'expectedHead': None if h.claim.predecessor_submission_id is None else h.claim.predecessor_submission_id.value}
    first = client.post(PATH, json=command, headers=HEADERS)
    calls = list(h.authority.calls)
    second = client.post(PATH, json=command, headers=HEADERS)
    if stage:
        assert first.status_code == second.status_code == 409
        assert first.json()['code'] == second.json()['code'] == 'rf1086_unknown_production_outcome'
    else:
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json() == {'submissionId': h.claim.submission_id.value}
    assert h.authority.calls == calls and h.calls.count('bind') == 1


def test_position_reads_retained_evidence_without_configuration_claim_or_provider(monkeypatch):
    archive = annual_submission(status='accepted')
    calls = []
    class Sessions:
        async def session(self, token):
            assert token == 'token'
            calls.append('authenticated')
            return self
        actor_id = archive.source_submission_claims[0].claimed_by
        async def read_source_claim_approval(self, approval_id):
            assert approval_id.value == archive.approvals[0].id
            calls.append('approval')
            return rf.Rf1086RetainedSourceApproval(archive.approvals[0], archive.source_approval_lineage[0].manifest_text)
        async def archive_source(self, query):
            assert query.company_id == archive.company_id and query.income_year == archive.income_year
            calls.append('archive')
            return archive
    workflow = ShareholderRegisterSourceDispatchWorkflow(Sessions(), None)
    monkeypatch.setattr(main, 'ShareholderRegisterSourceDispatchWorkflow', lambda *args: workflow)
    response = TestClient(main.create_app()).get(PATH+'/'+archive.approvals[0].id, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()['disposition'] == 'confirmed'
    assert response.json()['submissionId'] == archive.source_submission_claims[0].submission_id.value
    assert calls == ['authenticated', 'approval', 'archive']


def test_position_requires_authentication_and_uuid_before_read():
    sessions = NeverSessions()
    client = TestClient(main.create_app(shareholder_register_filing_session_factory=sessions))
    assert client.get(PATH+'/'+APPROVAL).status_code == 401
    assert client.get(PATH+'/invalid', headers=HEADERS).status_code == 422
    assert sessions.calls == 0
