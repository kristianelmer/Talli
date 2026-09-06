"""Owner receipt discovery is an additive read with no new-refund authority."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from test_annual_billing_api import ACTOR, COMPANY, PURCHASE, NOW, YEAR, Session, client
from talli_backend.application.annual_billing import AnnualBillingWorkflow
from talli_backend.modules.billing.public import (
    AnnualOperationStatus, AnnualPurchaseId, AnnualRefundRecoveryTargetsQuery,
    AnnualRefundRecoveryTarget, AnnualRefundRecoveryTargetPage, AnnualRefundRequestId, BillingError,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId


def get(api, **changes):
    return api.get('/api/v1/billing/annual/refund-recovery-targets',
        headers={'Authorization': 'Bearer verified-owner', 'X-Request-ID': 'target-discovery'},
        params={'companyId': str(COMPANY), 'purchaseId': str(PURCHASE), **changes})


def target(status=AnnualOperationStatus.CREATED):
    return AnnualRefundRecoveryTarget(AnnualRefundRequestId(str(uuid4())), NOW, status)


def page(*targets, **changes):
    return replace(AnnualRefundRecoveryTargetPage(COMPANY, PURCHASE, YEAR, targets), **changes)


def returning(value):
    session = Session()
    async def read(query):
        session.authorize(query.company_id)
        session.read_calls.append(query)
        return value
    session.read_refund_recovery_targets = read
    return session


def test_targets_expose_only_selectable_receipts_and_stored_operation_statuses():
    values = tuple(target(status) for status in AnnualOperationStatus)
    session = returning(page(*values, income_year=IncomeYear(2025), next_refund_request_id=values[-1].refund_request_id))
    cursor = str(uuid4())
    response = get(client(session), beforeRefundRequestId=cursor)
    assert response.status_code == 200
    assert response.json() == {'companyId': str(COMPANY), 'purchaseId': str(PURCHASE), 'incomeYear': 2025,
        'targets': [{'refundRequestId': str(value.refund_request_id), 'requestedAt': '2026-09-05T12:00:00Z',
                     'status': value.status.value} for value in values],
        'nextRefundRequestId': str(values[-1].refund_request_id)}
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-request-id'] == 'target-discovery'
    assert session.read_calls == [AnnualRefundRecoveryTargetsQuery(COMPANY, PURCHASE, ACTOR, AnnualRefundRequestId(cursor))]
    assert session.receipts == {}


def test_authorized_empty_targets_are_distinct_from_missing_purchase_or_cursor():
    session = Session()
    response = get(client(session))
    assert response.status_code == 200 and response.json()['targets'] == []
    assert response.json()['nextRefundRequestId'] is None
    assert get(client(session), purchaseId=str(uuid4())).status_code == 404
    async def absent(query):
        raise BillingError.not_found()
    session.read_refund_recovery_targets = absent
    response = get(client(session), beforeRefundRequestId=str(uuid4()))
    assert response.status_code == 404 and response.json()['code'] == 'BILLING_NOT_FOUND'


@pytest.mark.parametrize('mode', ['company', 'purchase', 'oversize', 'duplicate', 'cursor', 'empty_cursor'])
def test_malformed_or_misscoped_adapter_pages_are_sanitized(mode):
    value = target()
    result = page(value)
    if mode == 'company': result = replace(result, company_id=CompanyId(str(uuid4())))
    if mode == 'purchase': result = replace(result, purchase_id=AnnualPurchaseId(str(uuid4())))
    if mode == 'oversize': result = page(*(target() for _ in range(51)))
    if mode == 'duplicate': result = page(value, value)
    if mode == 'cursor': result = replace(result, next_refund_request_id=AnnualRefundRequestId(str(uuid4())))
    if mode == 'empty_cursor': result = page(next_refund_request_id=value.refund_request_id)
    response = get(client(returning(result)))
    assert response.status_code == 503
    assert 'targets' not in response.json() and str(value.refund_request_id) not in response.text


@pytest.mark.parametrize('mode', ['owner', 'mfa', 'actor'])
def test_current_owner_and_fresh_mfa_are_required_even_for_empty_targets(mode):
    session = Session()
    if mode == 'owner': session.authorized = False
    if mode == 'mfa': session.fresh = False
    if mode == 'actor':
        other = ActorId(ActorKind.USER, UserId(str(uuid4())))
        with pytest.raises(BillingError):
            asyncio.run(AnnualBillingWorkflow(session).refund_recovery_targets(
                AnnualRefundRecoveryTargetsQuery(COMPANY, PURCHASE, other)))
        assert session.read_calls == []
        return
    response = get(client(session))
    assert response.status_code == 403 and 'targets' not in response.json()


@pytest.mark.parametrize('field', ['companyId', 'purchaseId', 'beforeRefundRequestId'])
def test_invalid_identifiers_never_reach_persistence(field):
    session = Session()
    assert get(client(session), **{field: 'not-an-id'}).status_code == 422
    assert session.read_calls == []


@pytest.mark.parametrize('authorization', [None, 'Bearer invalid'])
def test_missing_or_invalid_session_never_reaches_persistence(authorization):
    session = Session()
    response = client(session).get('/api/v1/billing/annual/refund-recovery-targets',
        headers={'Authorization': authorization} if authorization else {},
        params={'companyId': str(COMPANY), 'purchaseId': str(PURCHASE)})
    assert response.status_code == 401 and session.read_calls == []
