import asyncio
import json
from dataclasses import replace
from datetime import UTC, date, datetime

import httpx
import pytest

from talli_backend.adapters.vipps_billing import VippsTestBillingProvider, VippsTestConfiguration, vipps_operation_key
from talli_backend.modules.billing.public import (
    AnnualProviderIntent, AnnualProviderOperation, AnnualProviderStatus,
    BillingError, BillingPaymentEventId,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear, Timestamp


NOW = datetime(2026, 9, 5, 12, tzinfo=UTC)
CONFIG = VippsTestConfiguration("123456", "fixture-client", "fixture-secret", "fixture-subscription", ("https://apitest.vipps.no",))


def intent(**changes):
    return replace(AnnualProviderIntent(
        operation_id=BillingPaymentEventId("10000000-0000-4000-8000-000000000002"),
        company_id=CompanyId("10000000-0000-4000-8000-000000000001"),
        income_year=IncomeYear(2026), operation=AnnualProviderOperation.CHECKOUT,
        amount_minor=149000, created_at=Timestamp(NOW),
        agreement_external_reference="talli-agreement-2026", charge_reference="talli-charge-2026",
        return_url="https://talli.example/billing/return", management_url="https://talli.example/billing",
        recurring_consent=True,
    ), **changes)


class MerchantTestFixture:
    """Local HTTP contract fixture, never claimed as actual Vipps MT evidence."""
    def __init__(self):
        self.requests = []
        self.created = False
        self.lose_create_response = False
        self.empty_lookup = False
        self.second_match = False
        self.agreement = {
            "id": "agr_local", "externalId": "talli-agreement-2026", "countryCode": "NO",
            "pricing": {"type": "LEGACY", "amount": 149000, "currency": "NOK"},
            "interval": {"unit": "YEAR", "count": 1, "text": "Every year"}, "productName": "Talli årsabonnement",
            "merchantRedirectUrl": "https://talli.example/billing/return",
            "merchantAgreementUrl": "https://talli.example/billing", "status": "ACTIVE",
        }
        self.charge = {
            "id": "talli-charge-2026", "agreementId": "agr_local", "externalId": "talli-charge-2026",
            "amount": 149000, "currency": "NOK", "transactionType": "DIRECT_CAPTURE",
            "type": "INITIAL", "status": "CHARGED",
            "summary": {"captured": 149000, "refunded": 0, "cancelled": 0}, "history": [],
        }

    def __call__(self, request):
        self.requests.append(request)
        assert request.url.host == "apitest.vipps.no"
        assert request.headers["Merchant-Serial-Number"] == "123456"
        path = request.url.path
        if path == "/accesstoken/get":
            return httpx.Response(200, json={"access_token": "fixture-access-token"})
        assert request.headers["Authorization"] == "Bearer fixture-access-token"
        if request.method == "POST" and path == "/recurring/v3/agreements":
            self.created = True
            if self.lose_create_response:
                raise httpx.ReadTimeout("fixture lost response")
            return httpx.Response(201, json={"agreementId": "agr_local", "chargeId": "talli-charge-2026",
                "vippsConfirmationUrl": "https://apitest.vipps.no/v2/register/fixture"})
        if request.method == "GET" and path == "/recurring/v3/agreements":
            rows = [self.agreement] if not self.empty_lookup and request.url.params["status"] == "ACTIVE" else []
            if rows and self.second_match:
                rows = rows + [self.agreement | {"id": "agr_duplicate"}]
            return httpx.Response(200, json=rows)
        if path.endswith("/refund"):
            body = json.loads(request.content)
            self.charge["summary"]["refunded"] += body["amount"]
            self.charge["history"].append({"event": "REFUND", "amount": body["amount"],
                "idempotencyKey": request.headers["Idempotency-Key"], "success": True,
                "occurred": NOW.isoformat()})
            return httpx.Response(204)
        if request.method == "PATCH":
            self.agreement["status"] = "STOPPED"
            return httpx.Response(204)
        if request.method == "DELETE":
            return httpx.Response(202)
        if request.method == "POST" and path.endswith("/charges"):
            self.charge["type"] = "RECURRING"
            self.charge["status"] = "PENDING"
            self.charge["summary"]["captured"] = 0
            return httpx.Response(201, json={"chargeId": "talli-charge-2026"})
        if path.endswith("/charges/talli-charge-2026"):
            return httpx.Response(200, json=self.charge)
        if path.endswith("/agr_local"):
            return httpx.Response(200, json=self.agreement)
        return httpx.Response(404)

    def provider(self):
        return VippsTestBillingProvider(CONFIG, transport=httpx.MockTransport(self), now=lambda: NOW)


def test_checkout_records_annual_amount_and_short_stable_operation_key_without_granting_payment():
    fixture = MerchantTestFixture()
    result = asyncio.run(fixture.provider().execute(intent()))
    assert result.status is AnnualProviderStatus.PENDING
    assert result.captured_minor == 0
    request = next(r for r in fixture.requests if r.url.path == "/recurring/v3/agreements")
    body = json.loads(request.content)
    assert body["pricing"] == {"type": "LEGACY", "amount": 149000, "currency": "NOK"}
    assert body["interval"] == {"unit": "YEAR", "count": 1}
    assert body["initialCharge"]["orderId"] == "talli-charge-2026"
    assert body["externalId"] == "talli-agreement-2026"
    assert len(request.headers["Idempotency-Key"]) == 40
    assert vipps_operation_key(CONFIG, intent()) == request.headers["Idempotency-Key"]
    assert not fixture.provider().production_enabled


def test_lost_checkout_response_recovers_by_read_only_reference_search_without_second_create():
    fixture = MerchantTestFixture()
    fixture.lose_create_response = True
    provider = fixture.provider()
    assert asyncio.run(provider.execute(intent())).status is AnnualProviderStatus.UNKNOWN
    assert fixture.created
    assert asyncio.run(provider.reconcile(intent())).status is AnnualProviderStatus.CONFIRMED
    writes = [r for r in fixture.requests if r.method != "GET" and "/recurring/" in r.url.path]
    assert len(writes) == 1
    statuses = {r.url.params.get("status") for r in fixture.requests if r.method == "GET" and r.url.path.endswith("/agreements")}
    assert statuses == {"PENDING", "ACTIVE", "STOPPED", "EXPIRED"}


@pytest.mark.parametrize("flag", ["empty_lookup", "second_match"])
def test_absence_and_multiple_agreements_remain_unknown_without_payment_retry(flag):
    fixture = MerchantTestFixture()
    setattr(fixture, flag, True)
    assert asyncio.run(fixture.provider().reconcile(intent())).status is AnnualProviderStatus.UNKNOWN
    assert not any(r.method != "GET" and "/recurring/" in r.url.path for r in fixture.requests)


@pytest.mark.parametrize(("target", "field", "value"), [
    ("agreement", "externalId", "other-company"),
    ("agreement", "pricing", {"type": "LEGACY", "amount": 149001, "currency": "NOK"}),
    ("agreement", "countryCode", "DK"),
    ("agreement", "productName", "Another offer"),
    ("agreement", "status", "UNKNOWN_FUTURE_STATE"),
    ("agreement", "merchantRedirectUrl", "https://other.example"),
    ("charge", "agreementId", "agr_other"),
    ("charge", "amount", 148999),
    ("charge", "currency", "EUR"),
    ("charge", "externalId", "other-charge"),
    ("charge", "type", "RECURRING"),
    ("charge", "status", "UNKNOWN_FUTURE_STATE"),
    ("charge", "summary", {"captured": 149000, "refunded": 149001}),
])
def test_mismatched_linkage_or_amount_never_confirms(target, field, value):
    fixture = MerchantTestFixture()
    getattr(fixture, target)[field] = value
    assert asyncio.run(fixture.provider().reconcile(intent(agreement_reference="agr_local"))).status is AnnualProviderStatus.UNKNOWN


def test_agreement_active_without_capture_never_grants_paid_entitlement():
    fixture = MerchantTestFixture()
    fixture.charge["summary"]["captured"] = 0
    fixture.charge["status"] = "PENDING"
    assert asyncio.run(fixture.provider().reconcile(intent())).status is AnnualProviderStatus.PENDING


def test_lost_pending_checkout_recovers_allowlisted_confirmation_url_without_recreating():
    fixture = MerchantTestFixture()
    fixture.agreement["status"] = "PENDING"
    fixture.agreement["vippsConfirmationUrl"] = "https://apitest.vipps.no/v2/register/resume"
    result = asyncio.run(fixture.provider().reconcile(intent(agreement_reference="agr_local")))
    assert result.status is AnnualProviderStatus.PENDING
    assert result.checkout_url == fixture.agreement["vippsConfirmationUrl"]
    assert not any(r.method != "GET" and "/recurring/" in r.url.path for r in fixture.requests)


@pytest.mark.parametrize("operation", [AnnualProviderOperation.REFUND, AnnualProviderOperation.CANCEL_CHARGE, AnnualProviderOperation.STOP_AGREEMENT, AnnualProviderOperation.RENEWAL])
def test_wrong_agreement_binding_rejects_before_any_consequential_request(operation):
    fixture = MerchantTestFixture()
    fixture.agreement["externalId"] = "other-company-agreement"
    amount = 149000 if operation is AnnualProviderOperation.RENEWAL else 10000 if operation is AnnualProviderOperation.REFUND else 0
    command = intent(operation=operation, amount_minor=amount, agreement_reference="agr_local",
        due_date=date(2026, 9, 6), original_charge_is_renewal=operation is AnnualProviderOperation.RENEWAL)
    assert asyncio.run(fixture.provider().execute(command)).status is AnnualProviderStatus.UNKNOWN
    assert not any(r.method != "GET" and "/recurring/" in r.url.path for r in fixture.requests)


@pytest.mark.parametrize("operation", [AnnualProviderOperation.REFUND, AnnualProviderOperation.CANCEL_CHARGE])
def test_wrong_charge_binding_rejects_before_refund_or_cancel(operation):
    fixture = MerchantTestFixture()
    fixture.charge["externalId"] = "other-charge"
    command = intent(operation=operation, amount_minor=10000 if operation is AnnualProviderOperation.REFUND else 0, agreement_reference="agr_local")
    assert asyncio.run(fixture.provider().execute(command)).status is AnnualProviderStatus.UNKNOWN
    assert not any(r.method != "GET" and "/recurring/" in r.url.path for r in fixture.requests)


def test_partial_refund_matches_operation_history_and_cumulative_totals_cannot_substitute():
    fixture = MerchantTestFixture()
    command = intent(operation=AnnualProviderOperation.REFUND, amount_minor=37250, agreement_reference="agr_local")
    result = asyncio.run(fixture.provider().execute(command))
    assert result.status is AnnualProviderStatus.CONFIRMED and result.refunded_minor == 37250
    different = replace(command, operation_id=BillingPaymentEventId("10000000-0000-4000-8000-000000000003"))
    assert asyncio.run(fixture.provider().reconcile(different)).status is AnnualProviderStatus.UNKNOWN
    assert asyncio.run(fixture.provider().reconcile(command)).status is AnnualProviderStatus.CONFIRMED
    assert len([r for r in fixture.requests if r.url.path.endswith("/refund")]) == 1


def test_cancel_accepted_is_pending_until_observed_and_stop_is_confirmed_separately():
    fixture = MerchantTestFixture()
    cancellation = intent(operation=AnnualProviderOperation.CANCEL_CHARGE, amount_minor=0, agreement_reference="agr_local")
    assert asyncio.run(fixture.provider().execute(cancellation)).status is AnnualProviderStatus.PENDING
    fixture.charge["status"] = "CANCELLED"
    assert asyncio.run(fixture.provider().reconcile(cancellation)).status is AnnualProviderStatus.CONFIRMED
    stop = replace(cancellation, operation=AnnualProviderOperation.STOP_AGREEMENT)
    assert asyncio.run(fixture.provider().execute(stop)).status is AnnualProviderStatus.CONFIRMED


def test_renewal_scheduling_is_pending_and_uses_the_merchant_charge_reference():
    fixture = MerchantTestFixture()
    command = intent(operation=AnnualProviderOperation.RENEWAL, agreement_reference="agr_local", due_date=date(2026, 9, 6), original_charge_is_renewal=True)
    assert asyncio.run(fixture.provider().execute(command)).status is AnnualProviderStatus.PENDING
    scheduled = next(r for r in fixture.requests if r.method == "POST" and r.url.path.endswith("/charges"))
    assert json.loads(scheduled.content)["orderId"] == command.charge_reference
    assert json.loads(scheduled.content)["retryDays"] == 5


def test_failures_redact_secrets_and_production_confirmation_origins_are_rejected():
    with pytest.raises(BillingError):
        replace(CONFIG, confirmation_origins=("https://api.vipps.no",))
    assert "fixture-secret" not in repr(CONFIG)
    def failing(request):
        return httpx.Response(500, text="provider diagnostic with fixture-secret")
    provider = VippsTestBillingProvider(CONFIG, transport=httpx.MockTransport(failing))
    result = asyncio.run(provider.execute(intent()))
    assert result.status is AnnualProviderStatus.UNKNOWN
    assert "fixture-secret" not in repr(result)
