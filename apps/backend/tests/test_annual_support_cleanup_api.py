"""Authenticated operator STOP observation; entirely synthetic provider seams."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from test_annual_cleanup_service import observation
from test_annual_support_cleanup_service import OPERATOR, CASE, COMPANY, PURCHASE, QUERY, SupportStore, Reconciler
from talli_backend.application.annual_billing import AnnualSupportCleanupRecoveryWorkflow
from talli_backend.application.billing_session import BillingAuthenticationError
from talli_backend.main import create_app
from talli_backend.modules.billing.public import BillingError, settle_annual_agreement_cleanup

PATH = '/api/v1/billing/annual/support/agreement-cleanup-recoveries'
HEADERS = {'Authorization': 'Bearer verified-operator', 'X-Request-ID': 'cleanup-recovery-http'}
BODY = {'companyId': str(COMPANY), 'purchaseId': str(PURCHASE), 'supportCaseId': str(CASE)}


class Sessions:
    actor_id = OPERATOR

    def __init__(self, store): self.support_cleanup_recovery = store

    async def session(self, token):
        if token != 'verified-operator': raise BillingAuthenticationError()
        return self


def fixture(provider_enabled=True):
    store = SupportStore()
    provider = Reconciler(store)
    return TestClient(create_app(annual_billing_session_factory=Sessions(store),
        annual_billing_provider=provider if provider_enabled else None)), store, provider


def test_post_observes_existing_stop_and_returns_sanitized_result():
    api, store, provider = fixture()
    original = store.saved
    result = api.post(PATH, headers=HEADERS, json=BODY)
    assert result.status_code == 200, result.text
    assert result.json() == BODY | {'operationId': str(original.intent.operation_id), 'incomeYear': 2026, 'status': 'confirmed'}
    assert result.headers['cache-control'] == 'no-store'
    assert result.headers['x-request-id'] == HEADERS['X-Request-ID']
    assert provider.reads == [original.intent] and store.loads == store.settlements == [QUERY]
    assert replace(store.saved, observation=None) == original
    assert original.intent.agreement_reference not in result.text
    assert str(original.cancellation_id) not in result.text


@pytest.mark.parametrize('field', ['actorId', 'sourceReference', 'idempotencyKey', 'amountMinor', 'incomeYear',
    'operationId', 'provider', 'refundRequestId', 'cancellationId', 'requestedBy'])
def test_caller_cannot_supply_authority_or_create_new_intent(field):
    api, store, provider = fixture()
    assert api.post(PATH, headers=HEADERS, json=BODY | {field: 'not-authority'}).status_code == 422
    assert not store.loads and not provider.reads


@pytest.mark.parametrize('field', BODY)
@pytest.mark.parametrize('mode', ['missing', 'malformed'])
def test_required_scope_is_validated_before_storage(field, mode):
    api, store, provider = fixture()
    body = {key: value for key, value in BODY.items() if key != field}
    if mode == 'malformed': body[field] = 'bad'
    assert api.post(PATH, headers=HEADERS, json=body).status_code == 422
    assert not store.loads and not provider.reads


def test_get_and_unauthenticated_post_never_observe():
    api, store, provider = fixture()
    assert api.get(PATH, headers=HEADERS).status_code == 405
    assert api.post(PATH, json=BODY).status_code == 401
    assert api.post(PATH, headers={'Authorization': 'Bearer wrong'}, json=BODY).status_code == 401
    assert not store.loads and not provider.reads


@pytest.mark.parametrize('mode,code', [('admin',403),('mfa',403),('missing',404),('provider',503)])
def test_denials_and_missing_original_are_not_success(mode, code):
    api, store, provider = fixture(mode != 'provider')
    if mode == 'admin': store.authorized = False
    elif mode == 'mfa': store.fresh = False
    elif mode == 'missing': store.saved = None
    result = api.post(PATH, headers=HEADERS, json=BODY)
    assert result.status_code == code
    assert result.headers['content-type'].startswith('application/problem+json')
    assert not provider.reads


def test_confirmed_replay_needs_no_provider_and_keeps_original_operation():
    api, store, provider = fixture(False)
    store.saved = settle_annual_agreement_cleanup(store.saved, observation(store.saved))
    result = api.post(PATH, headers=HEADERS, json=BODY)
    assert result.status_code == 200 and result.json()['status'] == 'confirmed'
    assert not store.settlements and not provider.reads


def test_lost_committed_response_retries_original_without_provider_read():
    api, store, provider = fixture()
    store.lose_response = True
    assert api.post(PATH, headers=HEADERS, json=BODY).status_code == 503
    store.lose_response = False
    assert api.post(PATH, headers=HEADERS, json=BODY).status_code == 200
    assert len(provider.reads) == 1


def test_workflow_rejects_session_actor_mismatch():
    api, store, provider = fixture()
    sessions = Sessions(store)
    from test_annual_cleanup_service import ACTOR
    sessions.actor_id = ACTOR
    with pytest.raises(BillingError): AnnualSupportCleanupRecoveryWorkflow(sessions, provider)
