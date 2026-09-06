"""Explicit case-bound operator recovery HTTP boundary with synthetic seams."""

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from test_annual_support_refund_recovery_service import OPERATOR, CASE, COMPANY, PURCHASE, QUERY, REQUEST, SupportStore
from test_annual_refund_recovery_service import Reconciler
from test_annual_refund_service import NOW, observation
from talli_backend.application.annual_billing import AnnualSupportRefundRecoveryWorkflow
from talli_backend.application.billing_session import BillingAuthenticationError
from talli_backend.main import create_app
from talli_backend.modules.billing.public import AnnualProviderStatus, BillingError, settle_annual_refund
from talli_backend.shared.kernel import ActorId, ActorKind, UserId

PATH = '/api/v1/billing/annual/support/refund-recoveries'
HEADERS = {'Authorization': 'Bearer verified-operator', 'X-Request-ID': 'refund-recovery-http'}
BODY = {'companyId': str(COMPANY), 'purchaseId': str(PURCHASE), 'refundRequestId': str(REQUEST), 'supportCaseId': str(CASE)}


class Sessions:
    actor_id = OPERATOR

    def __init__(self, store):
        self.support_refund_recovery = store

    async def session(self, token):
        if token != 'verified-operator':
            raise BillingAuthenticationError()
        return self


def fixture(provider_enabled=True):
    store = SupportStore()
    provider = Reconciler(store)
    return TestClient(create_app(
        annual_billing_session_factory=Sessions(store),
        annual_billing_provider=provider if provider_enabled else None,
    )), store, provider


def test_post_recovers_original_operation_and_returns_only_sanitized_identity_and_status():
    api, store, provider = fixture()
    original = store.saved
    result = api.post(PATH, headers=HEADERS, json=BODY)
    assert result.status_code == 200, result.text
    assert result.json() == BODY | {'incomeYear': 2026, 'status': 'confirmed'}
    assert result.headers['cache-control'] == 'no-store'
    assert result.headers['x-request-id'] == HEADERS['X-Request-ID']
    assert provider.reads == [original.resolution.operation.intent]
    assert store.saved.resolution.request == original.resolution.request


@pytest.mark.parametrize('field', ['actorId', 'sourceReference', 'idempotencyKey', 'amountMinor', 'incomeYear', 'caseId', 'provider', 'operationId', 'requestedBy'])
def test_caller_cannot_supply_authority_source_or_new_attempt_fields(field):
    api, store, provider = fixture()
    response = api.post(PATH, headers=HEADERS, json=BODY | {field: 'not-authority'})
    assert response.status_code == 422
    assert store.loads == store.settlements == 0 and provider.reads == []


@pytest.mark.parametrize('field', ['companyId', 'purchaseId', 'refundRequestId', 'supportCaseId'])
def test_malformed_request_identity_is_rejected_before_persistence(field):
    api, store, provider = fixture()
    assert api.post(PATH, headers=HEADERS, json=BODY | {field: 'bad'}).status_code == 422
    assert store.loads == 0 and provider.reads == []


def test_get_and_unauthenticated_calls_never_recover():
    api, store, provider = fixture()
    assert api.get(PATH, headers=HEADERS).status_code == 405
    assert api.post(PATH, json=BODY).status_code == 401
    assert api.post(PATH, headers={'Authorization': 'Bearer wrong'}, json=BODY).status_code == 401
    assert store.loads == 0 and provider.reads == []


@pytest.mark.parametrize('mode', ['admin', 'case', 'mfa', 'provider', 'missing'])
def test_denial_and_unavailable_results_do_not_claim_success(mode):
    api, store, provider = fixture(provider_enabled=mode != 'provider')
    if mode == 'admin':
        store.authorized = False
    elif mode == 'case':
        from talli_backend.modules.billing.public import AnnualSupportCaseId
        store.support_case_id = AnnualSupportCaseId(str(uuid4()))
    elif mode == 'mfa':
        store.fresh = False
    elif mode == 'missing':
        async def missing(query):
            raise BillingError.not_found()
        store.load_refund_recovery = missing
    response = api.post(PATH, headers=HEADERS, json=BODY)
    assert response.status_code == {'admin': 403, 'case': 403, 'mfa': 403, 'provider': 503, 'missing': 404}[mode]
    assert response.headers['content-type'].startswith('application/problem+json')
    assert str(store.saved.resolution.case_id) not in response.text
    assert store.saved.resolution.request.source_reference not in response.text
    assert provider.reads == []


def test_lost_committed_response_retries_same_request_without_another_provider_read():
    api, store, provider = fixture()
    original = store.saved
    store.lose_response = True
    assert api.post(PATH, headers=HEADERS, json=BODY).status_code == 503
    store.lose_response = False
    result = api.post(PATH, headers=HEADERS | {'X-Request-ID': 'next-http-correlation'}, json=BODY)
    assert result.status_code == 200 and result.json()['status'] == 'confirmed'
    assert provider.reads == [original.resolution.operation.intent]
    assert store.saved.resolution.request == original.resolution.request


def test_failed_original_can_be_read_without_provider_and_keeps_liability():
    api, store, provider = fixture(provider_enabled=False)
    store.saved = replace(store.saved, resolution=settle_annual_refund(
        store.saved.resolution, observation(store.saved.resolution, AnnualProviderStatus.FAILED), NOW,
    ))
    response = api.post(PATH, headers=HEADERS, json=BODY)
    assert response.status_code == 200 and response.json()['status'] == 'failed'
    assert store.saved.resolution.decision.total_entitlement_minor == 149000
    assert provider.reads == [] and store.settlements == 0


def test_workflow_rejects_mismatched_session_actor():
    _, store, provider = fixture()
    sessions = Sessions(store)
    sessions.actor_id = ActorId(ActorKind.USER, UserId(str(uuid4())))
    with pytest.raises(BillingError):
        AnnualSupportRefundRecoveryWorkflow(sessions, provider)


@pytest.mark.parametrize('field', ['companyId', 'purchaseId', 'refundRequestId', 'supportCaseId'])
def test_all_four_support_bindings_are_required(field):
    api, store, provider = fixture()
    response = api.post(PATH, headers=HEADERS, json={key: value for key, value in BODY.items() if key != field})
    assert response.status_code == 422 and store.loads == 0 and provider.reads == []


def test_operator_query_is_used_at_settlement_but_not_written_into_original_request():
    api, store, _ = fixture()
    original = store.saved.resolution.request
    assert original.actor_id != OPERATOR
    response = api.post(PATH, headers=HEADERS, json=BODY)
    assert response.status_code == 200
    assert store.queries == store.settlement_queries == [QUERY]
    assert store.saved.resolution.request == original
    assert str(original.actor_id.subject) not in response.text
    assert original.source_reference not in response.text
