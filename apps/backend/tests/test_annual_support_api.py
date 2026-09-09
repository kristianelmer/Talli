"""Support HTTP contract; authority behavior also runs against real private stores."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from test_annual_billing_api import ACTOR, COMPANY, PURCHASE, NOW, YEAR
from talli_backend.application.annual_billing import AnnualSupportWorkflow
from talli_backend.application.billing_session import BillingAuthenticationError
from talli_backend.main import create_app
from talli_backend.modules.billing.public import (
    AnnualOperationCounts, AnnualOperationStatus, AnnualPurchaseId, AnnualPurchaseStatus,
    AnnualSupportCaseId, AnnualSupportPage, AnnualSupportPurchase, AnnualSupportQuery, BillingError,
    annual_billing_offer,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, UserId

CASE = AnnualSupportCaseId(str(uuid4()))
PATH = '/api/v1/billing/annual/support/purchases'


def purchase():
    offer = annual_billing_offer(COMPANY, YEAR)
    return AnnualSupportPurchase(
        PURCHASE, COMPANY, YEAR, AnnualPurchaseStatus.PAID, NOW, NOW, 'NOK', 149000, 149000, 50000,
        NOW, offer.paid_through, offer.export_through, True, 2, 149000, NOW.value.date(), 2, NOW,
        AnnualOperationCounts(0, 0, 1, 1, 1), AnnualOperationStatus.UNKNOWN,
    )


class Session:
    actor_id = ACTOR

    def __init__(self, page=None):
        self.support_reads = self
        self.page = page or AnnualSupportPage((purchase(),))
        self.calls = []
        self.allowed = self.fresh = True

    async def session(self, token):
        if token != 'verified-admin':
            raise BillingAuthenticationError()
        return self

    async def read_support_purchases(self, query):
        self.calls.append(query)
        if not self.allowed or query.company_id != COMPANY or query.support_case_id != CASE:
            raise BillingError.forbidden()
        if not self.fresh:
            raise BillingError.step_up_required()
        return self.page


def client(session):
    # No provider behavior belongs in this route; an object with no methods is sufficient.
    return TestClient(create_app(annual_billing_session_factory=session, annual_billing_provider=object()))


def get(api, **changes):
    return api.get(PATH, headers={'Authorization': 'Bearer verified-admin', 'X-Request-ID': 'support-fixture'},
                   params={'companyId': str(COMPANY), 'supportCaseId': str(CASE), **changes})


def test_support_projects_current_totals_and_unresolved_counts_without_private_material():
    store = Session()
    response = get(client(store), beforePurchaseId=str(PURCHASE))
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-request-id'] == 'support-fixture'
    body = response.json()
    assert body['companyId'] == str(COMPANY) and body['supportCaseId'] == str(CASE)
    value = body['purchases'][0]
    assert value['remainingRefundMinor'] == 99000 and value['refundCaseCount'] == 2
    assert value['refundOperations'] == {'created': 0, 'pending': 0, 'unknown': 1, 'confirmed': 1, 'failed': 1}
    assert value['cleanupStatus'] == 'unknown'
    assert not {'facts', 'sourceReference', 'acceptedBasis', 'provider', 'intent', 'observation', 'providerAccount'} & value.keys()
    assert store.calls[0] == AnnualSupportQuery(COMPANY, CASE, ACTOR, PURCHASE)


@pytest.mark.parametrize('header', [None, 'Bearer forged'])
def test_support_requires_verified_bearer(header):
    store = Session()
    response = client(store).get(PATH, params={'companyId': str(COMPANY), 'supportCaseId': str(CASE)},
                                 headers={'Authorization': header} if header else {})
    assert response.status_code == 401 and not store.calls


@pytest.mark.parametrize('field,value', [('companyId', 'invalid'), ('supportCaseId', 'invalid'), ('beforePurchaseId', 'invalid')])
def test_support_rejects_malformed_scope(field, value):
    store = Session()
    assert get(client(store), **{field: value}).status_code == 422
    assert not store.calls


@pytest.mark.parametrize('mode,expected', [('revoked', 403), ('stale_mfa', 403), ('wrong_case', 403), ('wrong_company', 403)])
def test_support_rechecks_authority_even_for_empty_history(mode, expected):
    store = Session(AnnualSupportPage(()))
    store.allowed = mode != 'revoked'
    store.fresh = mode != 'stale_mfa'
    response = get(client(store), **({'supportCaseId': str(uuid4())} if mode == 'wrong_case' else
                                   {'companyId': str(uuid4())} if mode == 'wrong_company' else {}))
    assert response.status_code == expected
    if mode == 'stale_mfa':
        assert response.json()['code'] == 'BILLING_STEP_UP_REQUIRED'


@pytest.mark.parametrize('mode', ['oversized', 'wrong_company', 'bad_cursor', 'empty_cursor'])
def test_workflow_rejects_out_of_scope_or_unbounded_projection(mode):
    item = purchase()
    page = {
        'oversized': AnnualSupportPage((item,)*51),
        'wrong_company': AnnualSupportPage((replace(item, company_id=CompanyId(str(uuid4()))),)),
        'bad_cursor': AnnualSupportPage((item,), AnnualPurchaseId(str(uuid4()))),
        'empty_cursor': AnnualSupportPage((), PURCHASE),
    }[mode]
    assert get(client(Session(page))).status_code == 503


def test_actor_mismatch_cannot_borrow_authenticated_support_store():
    other = ActorId(ActorKind.USER, UserId(str(uuid4())))
    store = Session()
    with pytest.raises(BillingError):
        AnnualSupportWorkflow(SimpleNamespace(actor_id=other, support_reads=store))
    with pytest.raises(BillingError):
        asyncio.run(AnnualSupportWorkflow(store).purchases(AnnualSupportQuery(COMPANY, CASE, other)))
    assert not store.calls


def test_known_refunds_cannot_make_remaining_recorded_liability_negative():
    assert replace(purchase(), recorded_refund_minor=10000).remaining_refund_minor == 0


def test_support_contract_keeps_each_recorded_year_without_requesting_new_purchase_authority():
    from talli_backend.shared.kernel import IncomeYear
    # Historical/future-year projection fixtures only. The current admission
    # source supports 2026; this does not create authority for other years.
    first = purchase()
    second = replace(first, purchase_id=AnnualPurchaseId(str(uuid4())), income_year=IncomeYear(2025))
    response = get(client(Session(AnnualSupportPage((first, second)))))
    assert response.status_code == 200
    assert [value['incomeYear'] for value in response.json()['purchases']] == [2026, 2025]
