"""Provider-free annual HTTP projections and local cancellation receipts."""

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from talli_backend.application.annual_billing import AnnualBillingWorkflow
from talli_backend.application.billing_session import BillingAuthenticationError
from talli_backend.main import create_app
from talli_backend.modules.billing.public import (
    AnnualBillingSnapshotQuery,
    AnnualPurchaseHistoryQuery,
    AnnualRefundRecoveryTargetsQuery, AnnualRefundRecoveryTarget, AnnualRefundRecoveryTargetPage,
    AnnualRefundRequestId, AnnualOperationStatus,
    AnnualCancellationId,
    AnnualOperationCounts,
    AnnualPurchaseId,
    AnnualPurchasePage,
    AnnualPurchaseStatus,
    AnnualPurchaseSummary,
    AnnualRenewalCancellation,
    BillingError,
    BillingErrorCode,
    annual_billing_offer,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, Timestamp, UserId

ACTOR = ActorId(ActorKind.USER, UserId(str(uuid4())))
COMPANY = CompanyId(str(uuid4()))
PURCHASE = AnnualPurchaseId(str(uuid4()))
NOW = Timestamp(datetime(2026, 9, 5, 12, tzinfo=UTC))
YEAR = IncomeYear(2026)


def summary():
    offer = annual_billing_offer(COMPANY, YEAR)
    return AnnualPurchaseSummary(
        purchase_id=PURCHASE,
        company_id=COMPANY,
        income_year=YEAR,
        status=AnnualPurchaseStatus.PAID,
        accepted_at=NOW,
        offer_version=offer.offer_version,
        terms_digest=offer.terms_digest,
        terms_text=offer.terms_text,
        currency="NOK",
        gross_minor=149000,
        net_minor=119200,
        vat_minor=29800,
        vat_basis_points=2500,
        captured_minor=149000,
        refunded_minor=0,
        captured_at=NOW,
        recurring_consent=True,
        renewal_canceled_at=None,
        paid_through=offer.paid_through,
        export_through=offer.export_through,
        renewal_date=offer.renewal_date,
        recorded_refund_minor=0,
        refund_initiate_by=None,
        refund_request_count=0,
        latest_refund_requested_at=None,
        refund_operations=AnnualOperationCounts(0, 0, 0, 0, 0),
    )


class Session:
    actor_id = ACTOR

    def __init__(self):
        self.reads = self.cancellation = self
        self.tokens = []
        self.read_calls = []
        self.receipts = {}
        self.value = summary()
        self.authorized = True
        self.fresh = True
        self.lost_response = False

    async def session(self, token):
        if token != "verified-owner":
            raise BillingAuthenticationError()
        self.tokens.append(token)
        return self

    def authorize(self, company):
        if not self.authorized or company != COMPANY:
            raise BillingError.forbidden()
        if not self.fresh:
            raise BillingError.step_up_required()

    async def read_purchases(self, query):
        self.authorize(query.company_id)
        self.read_calls.append(query)
        return AnnualPurchasePage((self.value,))

    async def read_purchase_history(self, query):
        self.authorize(query.company_id)
        self.read_calls.append(query)
        return AnnualPurchasePage((self.value,))

    async def read_refund_recovery_targets(self, query):
        self.authorize(query.company_id)
        self.read_calls.append(query)
        if query.purchase_id != PURCHASE:
            raise BillingError.not_found()
        return AnnualRefundRecoveryTargetPage(COMPANY, PURCHASE, YEAR, ())

    async def cancel_renewal(self, command):
        self.authorize(command.company_id)
        if command.purchase_id != PURCHASE:
            raise BillingError.not_found()
        key = str(command.idempotency_key)
        if key not in self.receipts:
            self.receipts[key] = AnnualRenewalCancellation(
                AnnualCancellationId(str(uuid4())),
                PURCHASE,
                COMPANY,
                YEAR,
                ACTOR.subject,
                NOW,
                NOW,
                self.value.paid_through,
                self.value.export_through,
            )
            self.value = replace(self.value, renewal_canceled_at=NOW)
            if self.lost_response:
                raise BillingError.unavailable()
        return self.receipts[key]


def client(session):
    return TestClient(create_app(annual_billing_session_factory=session))


def headers():
    return {
        "Authorization": "Bearer verified-owner",
        "Idempotency-Key": "annual-cancel-api-00001",
        "X-Request-ID": "annual-api-fixture",
    }


def snapshot(api, **changes):
    return api.get(
        "/api/v1/billing/annual/snapshot",
        headers=headers(),
        params={"companyId": str(COMPANY), "incomeYear": 2026, **changes},
    )


def refund_snapshot(api, **changes):
    return api.get(
        "/api/v1/billing/annual/refund-snapshot", headers=headers(),
        params={"companyId": str(COMPANY), "incomeYear": 2026, **changes},
    )

def history(api, **changes):
    return api.get("/api/v1/billing/annual/purchases", headers=headers(), params={"companyId": str(COMPANY), **changes})


def cancel(api, **changes):
    return api.post(
        "/api/v1/billing/annual/renewal-cancellations",
        headers=headers(),
        json={"companyId": str(COMPANY), "purchaseId": str(PURCHASE), **changes},
    )


def test_snapshot_exposes_exact_offer_and_stored_public_facts_without_mutation():
    session = Session()
    response = snapshot(client(session))
    assert response.status_code == 200
    value = response.json()
    assert value["offer"]["grossMinor"] == 149000 and value["offer"]["vatMinor"] == 29800
    assert value["purchases"][0]["purchaseId"] == str(PURCHASE)
    assert value["purchases"][0]["status"] == "paid"
    assert value["nextPurchaseId"] is None
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == "annual-api-fixture"
    assert session.receipts == {} and len(session.read_calls) == 1
    assert not (
        {
            "acceptedBasis",
            "provider",
            "providerAccount",
            "intent",
            "idempotencyKey",
            "requestFingerprint",
            "checkoutUrl",
            "acceptedBy",
        }
        & value["purchases"][0].keys()
    )
    assert not ({"ready", "canPurchase", "chargeAllowed"} & value.keys())


@pytest.mark.parametrize("status", ["created", "pending", "unknown", "confirmed", "failed"])
def test_owner_snapshot_keeps_recorded_liability_separate_from_operation_outcomes(status):
    session = Session()
    session.value = replace(session.value, recorded_refund_minor=149000, refunded_minor=50000,
                            refund_initiate_by=date(2026, 9, 4), refund_request_count=2,
                            latest_refund_requested_at=NOW,
                            refund_operations=AnnualOperationCounts(**{
                                key: int(key == status) for key in ("created", "pending", "unknown", "confirmed", "failed")
                            }))
    response = refund_snapshot(client(session))
    assert response.status_code == 200
    value = response.json()["purchases"][0]
    assert (value["recordedRefundMinor"], value["refundedMinor"], value["remainingRefundMinor"]) == (149000, 50000, 99000)
    assert value["refundInitiateBy"] == "2026-09-04" and value["refundRequestCount"] == 2
    assert value["latestRefundRequestedAt"] == "2026-09-05T12:00:00Z"
    assert value["refundOperations"][status] == 1
    assert session.receipts == {} and len(session.read_calls) == 1


def test_owner_snapshot_never_projects_negative_remaining_refund_or_adjudicates_request_only():
    session = Session()
    session.value = replace(session.value, recorded_refund_minor=37250, refunded_minor=50000)
    assert refund_snapshot(client(session)).json()["purchases"][0]["remainingRefundMinor"] == 0
    session.value = replace(summary(), refund_request_count=1, latest_refund_requested_at=NOW)
    value = refund_snapshot(client(session)).json()["purchases"][0]
    assert value["refundRequestCount"] == 1 and value["recordedRefundMinor"] == value["remainingRefundMinor"] == 0
    assert value["refundInitiateBy"] is None and not any(value["refundOperations"].values())


def test_predecessor_snapshot_shape_survives_backend_first_deployment_with_recorded_refund():
    session = Session()
    session.value = replace(session.value, recorded_refund_minor=149000, refund_request_count=1,
                            latest_refund_requested_at=NOW, refund_operations=AnnualOperationCounts(0, 0, 1, 0, 0))
    api = client(session)
    old = snapshot(api).json()
    new = refund_snapshot(api).json()
    old_keys = {"purchaseId", "companyId", "incomeYear", "status", "acceptedAt", "offerVersion", "termsDigest",
                "termsText", "currency", "grossMinor", "netMinor", "vatMinor", "vatBasisPoints", "capturedMinor",
                "refundedMinor", "capturedAt", "recurringConsent", "renewalCanceledAt", "paidThrough", "exportThrough", "renewalDate"}
    assert set(old["purchases"][0]) == old_keys
    assert old["purchases"][0] == {key: value for key, value in new["purchases"][0].items() if key in old_keys}
    assert old["offer"] == new["offer"] and old["nextPurchaseId"] == new["nextPurchaseId"]


def test_company_history_returns_recorded_years_without_reading_a_current_offer(monkeypatch):
    session = Session()
    previous = replace(session.value, income_year=IncomeYear(2025), terms_text="Recorded 2025 terms")

    async def read(query):
        session.authorize(query.company_id)
        session.read_calls.append(query)
        return AnnualPurchasePage((session.value, previous))

    session.read_purchase_history = read
    def no_offer(*args):
        raise AssertionError("Historical read must not invent a current offer")
    monkeypatch.setattr("talli_backend.application.annual_billing.annual_billing_offer", no_offer)
    cursor = str(uuid4())
    response = history(client(session), beforePurchaseId=cursor)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    value = response.json()
    assert [row["incomeYear"] for row in value["purchases"]] == [2026, 2025]
    assert value["purchases"][1]["termsText"] == "Recorded 2025 terms"
    assert "offer" not in value and value["companyId"] == str(COMPANY)
    query = session.read_calls[0]
    assert query.actor_id == ACTOR and query.company_id == COMPANY and str(query.before_purchase_id) == cursor
    assert not hasattr(query, "income_year") and session.receipts == {}


@pytest.mark.parametrize("mode", ["forbidden", "stale_mfa", "foreign_purchase", "oversize", "foreign_cursor"])
def test_company_history_authorizes_current_owner_and_rejects_invalid_page_scope(mode):
    session = Session()
    if mode == "forbidden": session.authorized = False
    if mode == "stale_mfa": session.fresh = False
    async def read(query):
        session.authorize(query.company_id)
        if mode == "foreign_purchase": return AnnualPurchasePage((replace(session.value, company_id=CompanyId(str(uuid4()))),))
        if mode == "oversize": return AnnualPurchasePage((session.value,) * 51)
        if mode == "foreign_cursor": return AnnualPurchasePage((session.value,), AnnualPurchaseId(str(uuid4())))
        return AnnualPurchasePage(())
    session.read_purchase_history = read
    response = history(client(session))
    assert response.status_code == (403 if mode in ("forbidden", "stale_mfa") else 503)
    assert "purchases" not in response.json() and session.receipts == {}


def test_company_history_empty_and_missing_cursor_are_not_conflated():
    session = Session()
    async def read(query):
        if query.before_purchase_id: raise BillingError.not_found()
        return AnnualPurchasePage(())
    session.read_purchase_history = read
    api = client(session)
    assert history(api).json()["purchases"] == []
    response = history(api, beforePurchaseId=str(uuid4()))
    assert response.status_code == 404 and response.json()["code"] == "BILLING_NOT_FOUND"


@pytest.mark.parametrize("mode", ["forbidden", "stale_mfa", "foreign_purchase"])
def test_refund_snapshot_preserves_current_owner_authorization_and_scope(mode):
    session = Session()
    if mode == "forbidden":
        session.authorized = False
    elif mode == "stale_mfa":
        session.fresh = False
    else:
        session.value = replace(session.value, company_id=CompanyId(str(uuid4())))
    response = refund_snapshot(client(session))
    assert response.status_code == (503 if mode == "foreign_purchase" else 403)
    assert "purchases" not in response.json() and session.receipts == {}


def test_cancel_response_is_local_immutable_receipt_and_preserves_purchase_access():
    session = Session()
    api = client(session)
    before = snapshot(api).json()["purchases"][0]
    first, second = cancel(api), cancel(api)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() and len(session.receipts) == 1
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["x-request-id"] == "annual-api-fixture"
    after = snapshot(api).json()["purchases"][0]
    assert after["renewalCanceledAt"] == first.json()["effectiveAt"]
    assert {k: v for k, v in after.items() if k != "renewalCanceledAt"} == {
        k: v for k, v in before.items() if k != "renewalCanceledAt"
    }
    assert "providerStatus" not in first.json()


def test_lost_response_replays_the_stored_cancellation_receipt():
    session = Session()
    session.lost_response = True
    api = client(session)
    assert cancel(api).status_code == 503
    replay = cancel(api)
    assert replay.status_code == 200 and len(session.receipts) == 1
    assert replay.json()["effectiveAt"] == snapshot(api).json()["purchases"][0]["renewalCanceledAt"]


@pytest.mark.parametrize(
    "method,path",
    [("get", "/api/v1/billing/annual/purchases"), ("get", "/api/v1/billing/annual/snapshot"), ("get", "/api/v1/billing/annual/refund-snapshot"),
     ("post", "/api/v1/billing/annual/renewal-cancellations")],
)
@pytest.mark.parametrize("token", [None, "unverified"])
def test_missing_or_invalid_authentication_never_reads_or_mutates(method, path, token):
    session = Session()
    options = {"headers": {"Idempotency-Key": "annual-invalid-auth-00001"}}
    if token:
        options["headers"]["Authorization"] = "Bearer " + token
    options["params" if method == "get" else "json"] = (
        {"companyId": str(COMPANY), "incomeYear": 2026}
        if method == "get"
        else {"companyId": str(COMPANY), "purchaseId": str(PURCHASE)}
    )
    result = getattr(client(session), method)(path, **options)
    assert result.status_code == 401
    assert result.headers["cache-control"] == "no-store"
    assert session.read_calls == [] and session.receipts == {}


@pytest.mark.parametrize("mode", ["outsider", "stale_mfa"])
def test_owner_scope_and_fresh_mfa_are_required_for_both_operations(mode):
    session = Session()
    if mode == "outsider":
        session.authorized = False
    else:
        session.fresh = False
    api = client(session)
    assert snapshot(api).status_code == cancel(api).status_code == 403
    assert session.read_calls == [] and session.receipts == {}


@pytest.mark.parametrize(
    "extra",
    [
        {"actorId": str(uuid4())},
        {"incomeYear": 2027},
        {"provider": "other"},
        {"ready": True},
        {"effectiveAt": "2020-01-01"},
    ],
)
def test_cancellation_rejects_caller_authority_and_policy_fields(extra):
    session = Session()
    assert cancel(client(session), **extra).status_code == 422
    assert session.receipts == {} and session.tokens == []


def test_wrong_company_and_purchase_do_not_disclose_receipt():
    session = Session()
    api = client(session)
    assert snapshot(api, companyId=str(uuid4())).status_code == 403
    assert cancel(api, companyId=str(uuid4())).status_code == 403
    assert cancel(api, purchaseId=str(uuid4())).status_code == 404
    assert session.receipts == {}


def test_snapshot_cursor_is_forwarded_with_verified_company_year_scope():
    session = Session()
    cursor = str(uuid4())
    assert snapshot(client(session), beforePurchaseId=cursor).status_code == 200
    query = session.read_calls[0]
    assert query.company_id == COMPANY and query.actor_id == ACTOR and query.income_year == YEAR
    assert str(query.before_purchase_id) == cursor


def test_workflow_rejects_mismatched_actor_before_read():
    import asyncio

    session = Session()
    other = ActorId(ActorKind.USER, UserId(str(uuid4())))
    with pytest.raises(BillingError):
        asyncio.run(AnnualBillingWorkflow(session).snapshot(AnnualBillingSnapshotQuery(COMPANY, YEAR, other)))
    assert session.read_calls == []


def test_factory_uses_one_verified_actor_and_maps_authentication_failure():
    import asyncio
    import json
    from types import SimpleNamespace
    from talli_backend.adapters.supabase_annual_billing import SupabaseAnnualBillingAdapter
    from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, _VerifiedActor
    from talli_backend.application.ledger_workflow import LedgerAuthenticationError

    factory = SupabaseAnnualBillingAdapter(LedgerSupabaseConfiguration(url="", anon_key="", database_url=""))
    verified = _VerifiedActor(ACTOR, json.dumps({"sub": str(ACTOR.subject)}))

    class Authentication:
        async def session(self, token):
            if token != "verified-owner":
                raise LedgerAuthenticationError()
            return SimpleNamespace(_verified=verified)

    factory._authentication = Authentication()
    result = asyncio.run(factory.session("verified-owner"))
    assert result.actor_id == result.reads.actor_id == result.cancellation.actor_id == ACTOR
    with pytest.raises(BillingAuthenticationError):
        asyncio.run(factory.session("unverified"))


def test_workflow_rejects_mixed_authenticated_ports():
    from types import SimpleNamespace

    session = Session()
    other = SimpleNamespace(actor_id=ActorId(ActorKind.USER, UserId(str(uuid4()))))
    with pytest.raises(BillingError):
        AnnualBillingWorkflow(SimpleNamespace(actor_id=ACTOR, reads=session, cancellation=other))


def test_wrong_scope_from_read_port_is_not_exposed_to_http_caller():
    session = Session()
    session.value = replace(session.value, company_id=CompanyId(str(uuid4())))
    response = snapshot(client(session))
    assert response.status_code == 503
    assert str(session.value.company_id) not in response.text
