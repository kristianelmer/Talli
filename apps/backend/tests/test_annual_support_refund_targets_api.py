"""Case-bound discovery projection and verified-actor API boundaries."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from test_annual_refund_targets_api import target, page
from test_annual_support_refund_recovery_api import Sessions, HEADERS
from test_annual_support_refund_recovery_service import OPERATOR, CASE, SupportStore
from test_annual_refund_targets_api import COMPANY, PURCHASE
from talli_backend.application.annual_billing import AnnualSupportWorkflow
from talli_backend.main import create_app
from talli_backend.modules.billing.public import (
    AnnualOperationStatus, AnnualPurchaseId, AnnualRefundRequestId,
    AnnualSupportRefundRecoveryTargetsQuery, BillingError,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, UserId

PATH = '/api/v1/billing/annual/support/refund-recovery-targets'
PARAMS = {'companyId': str(COMPANY), 'purchaseId': str(PURCHASE), 'supportCaseId': str(CASE)}


def fixture(result=None):
    store = SupportStore()
    store.reads = []
    async def read(query):
        store.authorize_query(query)
        store.reads.append(query)
        return result if result is not None else page()
    store.read_refund_recovery_targets = read
    factory = Sessions(store)
    factory.support_reads = store
    return TestClient(create_app(annual_billing_session_factory=factory)), store


def get(api, **params):
    return api.get(PATH, headers=HEADERS, params=PARAMS | params)


def test_discovery_returns_only_case_purchase_and_selectable_operation_statuses():
    values = tuple(target(status) for status in AnnualOperationStatus)
    api, store = fixture(page(*values, next_refund_request_id=values[-1].refund_request_id))
    cursor = str(uuid4())
    response = get(api, beforeRefundRequestId=cursor)
    assert response.status_code == 200, response.text
    assert set(response.json()) == {'companyId', 'purchaseId', 'supportCaseId', 'incomeYear', 'targets', 'nextRefundRequestId'}
    assert response.json()['supportCaseId'] == str(CASE)
    assert all(set(value) == {'refundRequestId', 'requestedAt', 'status'} for value in response.json()['targets'])
    assert [value['status'] for value in response.json()['targets']] == [value.value for value in AnnualOperationStatus]
    assert response.headers['cache-control'] == 'no-store'
    assert store.reads == [AnnualSupportRefundRecoveryTargetsQuery(COMPANY, PURCHASE, CASE, OPERATOR, AnnualRefundRequestId(cursor))]
    assert store.loads == store.settlements == 0


def test_empty_is_distinct_from_absent_purchase_or_cursor():
    api, store = fixture()
    assert get(api).json()['targets'] == []
    async def absent(query): raise BillingError.not_found()
    store.read_refund_recovery_targets = absent
    response = get(api, beforeRefundRequestId=str(uuid4()))
    assert response.status_code == 404 and 'targets' not in response.json()


@pytest.mark.parametrize('mode', ['company', 'purchase', 'oversize', 'duplicate', 'cursor', 'empty_cursor'])
def test_malformed_scoped_projection_cannot_publish_partial_targets(mode):
    value = target()
    result = page(value)
    if mode == 'company': result = replace(result, company_id=CompanyId(str(uuid4())))
    if mode == 'purchase': result = replace(result, purchase_id=AnnualPurchaseId(str(uuid4())))
    if mode == 'oversize': result = page(*(target() for _ in range(51)))
    if mode == 'duplicate': result = page(value, value)
    if mode == 'cursor': result = replace(result, next_refund_request_id=AnnualRefundRequestId(str(uuid4())))
    if mode == 'empty_cursor': result = page(next_refund_request_id=value.refund_request_id)
    api, _ = fixture(result)
    response = get(api)
    assert response.status_code == 503 and str(value.refund_request_id) not in response.text


@pytest.mark.parametrize('field', ['companyId', 'purchaseId', 'supportCaseId', 'beforeRefundRequestId'])
def test_invalid_scoped_identity_never_reaches_store(field):
    api, store = fixture()
    assert get(api, **{field: 'invalid'}).status_code == 422 and store.reads == []


@pytest.mark.parametrize('mode', ['admin', 'mfa', 'case', 'actor'])
def test_support_authority_is_required_even_for_empty_projection(mode):
    api, store = fixture()
    if mode == 'admin': store.authorized = False
    if mode == 'mfa': store.fresh = False
    if mode == 'case':
        from talli_backend.modules.billing.public import AnnualSupportCaseId
        store.support_case_id = AnnualSupportCaseId(str(uuid4()))
    if mode == 'actor':
        other = ActorId(ActorKind.USER, UserId(str(uuid4())))
        with pytest.raises(BillingError):
            AnnualSupportWorkflow(SimpleNamespace(actor_id=other, support_reads=store))
        with pytest.raises(BillingError):
            asyncio.run(AnnualSupportWorkflow(SimpleNamespace(actor_id=OPERATOR, support_reads=store)).refund_recovery_targets(
                AnnualSupportRefundRecoveryTargetsQuery(COMPANY, PURCHASE, CASE, other)))
    else:
        response = get(api)
        assert response.status_code == 403 and 'targets' not in response.json()
    assert store.reads == [] and store.loads == store.settlements == 0


def test_missing_authentication_does_not_turn_into_empty_discovery():
    api, store = fixture()
    assert api.get(PATH, params=PARAMS).status_code == 401
    assert api.get(PATH, params=PARAMS, headers={'Authorization': 'Bearer invalid'}).status_code == 401
    assert store.reads == []
