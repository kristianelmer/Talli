from __future__ import annotations

from fastapi.testclient import TestClient

from talli_backend.main import create_app
from talli_backend.shared.kernel import ActorId, ActorKind, UserId

from test_billing import MemoryPersistence, account, metadata, seed_historical_event
from talli_backend.modules.billing.public import PurchaseFilingPackageCommand
from talli_backend.shared.kernel import IdempotencyKey, IncomeYear


ACTOR = ActorId(
    ActorKind.USER, UserId("20000000-0000-4000-8000-000000000001")
)
COMPANY = "10000000-0000-4000-8000-000000000001"


class BillingSessionStub(MemoryPersistence):
    def __init__(self, value=None, *, ready=False) -> None:
        super().__init__(value, ready=ready)
        self.tokens: list[str] = []

    @property
    def actor_id(self):
        return ACTOR

    async def session(self, access_token: str):
        self.tokens.append(access_token)
        return self


def client(stub: BillingSessionStub) -> TestClient:
    return TestClient(create_app(billing_session_factory=stub))


def headers(operation: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer verified-session",
        "Idempotency-Key": f"billing-api-{operation}-00000001",
        "X-Request-ID": f"billing-api-{operation}",
    }


def test_configure_and_snapshot_use_authenticated_backend_contract() -> None:
    original = account()
    stub = BillingSessionStub(original)
    response = client(stub).post(
        "/api/v1/billing/accounts/configuration",
        headers=headers("configure"),
        json={
            "companyId": COMPANY,
            "pricingPlan": "founder",
            "founderCohortNumber": 100,
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "BILLING_LEGACY_ACQUISITION_RETIRED"
    assert stub.account == original
    assert stub.tokens == ["verified-session"]

    snapshot = client(stub).get(
        "/api/v1/billing/snapshot",
        headers={"Authorization": "Bearer verified-session"},
        params={"companyIds": COMPANY},
    )
    assert snapshot.status_code == 200
    assert snapshot.json()["accounts"][0]["companyId"] == COMPANY
    assert snapshot.json()["pricing"] == []


def test_provider_retry_returns_same_event_without_bypassing_entitlement() -> None:
    stub = BillingSessionStub(account(subscription_active=True), ready=True)
    command_metadata = metadata("api-history")
    command_metadata["idempotency_key"] = IdempotencyKey(headers("filing")["Idempotency-Key"])
    seed_historical_event(stub, PurchaseFilingPackageCommand(**command_metadata, income_year=IncomeYear(2025)))
    api = client(stub)
    first = api.post(
        "/api/v1/billing/filing-package/purchase",
        headers=headers("filing"),
        json={
            "companyId": COMPANY,
            "incomeYear": 2025,
            "obligation": "aksjonaerregisteroppgaven",
        },
    )
    replay = api.post(
        "/api/v1/billing/filing-package/purchase",
        headers=headers("filing"),
        json={
            "companyId": COMPANY,
            "incomeYear": 2025,
            "obligation": "aksjonaerregisteroppgaven",
        },
    )
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json()["eventId"] == first.json()["eventId"]
    assert replay.json()["replayed"] is True

    entitlement = api.get(
        "/api/v1/billing/entitlement",
        headers={"Authorization": "Bearer verified-session"},
        params={
            "companyId": COMPANY,
            "incomeYear": 2025,
            "obligation": "aksjonaerregisteroppgaven",
        },
    )
    assert entitlement.status_code == 200
    assert entitlement.json()["status"] == "annual_billing_unavailable"
    assert entitlement.json()["allowed"] is False
    assert entitlement.json()["chargeAllowed"] is False
    assert not stub.account.filing_package_paid


def test_entitlement_rejects_an_actor_without_company_scope() -> None:
    stub = BillingSessionStub(account(subscription_active=True), ready=True)
    stub.entitlement_authorized = False

    response = client(stub).get(
        "/api/v1/billing/entitlement",
        headers={"Authorization": "Bearer verified-session"},
        params={
            "companyId": COMPANY,
            "incomeYear": 2025,
            "obligation": "aksjonaerregisteroppgaven",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "BILLING_FORBIDDEN"


def test_filing_purchase_fails_closed_when_readiness_is_missing() -> None:
    stub = BillingSessionStub(account(subscription_active=True), ready=False)
    response = client(stub).post(
        "/api/v1/billing/filing-package/purchase",
        headers=headers("blocked"),
        json={
            "companyId": COMPANY,
            "incomeYear": 2025,
            "obligation": "aksjonaerregisteroppgaven",
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "BILLING_LEGACY_ACQUISITION_RETIRED"
    assert stub.events == {}


def test_billing_rejects_missing_bearer_and_weak_operation_key() -> None:
    stub = BillingSessionStub()
    missing = client(stub).get(
        "/api/v1/billing/snapshot", params={"companyIds": COMPANY}
    )
    assert missing.status_code == 401
    weak = client(stub).post(
        "/api/v1/billing/subscriptions/activation",
        headers={"Authorization": "Bearer verified-session", "Idempotency-Key": "weak"},
        json={"companyId": COMPANY},
    )
    assert weak.status_code == 422


def test_unknown_case_profiles_keep_ordinary_entitlement_fallback() -> None:
    api = client(BillingSessionStub(account(subscription_active=True), ready=True))
    for profile in ("rf1086_no_activity_v1", "future_profile_v2", ""):
        response = api.get(
            "/api/v1/billing/entitlement",
            headers={"Authorization": "Bearer verified-session"},
            params={"companyId": COMPANY, "incomeYear": 2025,
                    "obligation": "aksjonaerregisteroppgaven", "caseProfile": profile},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "annual_billing_unavailable"
        assert response.json()["billingExempt"] is False
