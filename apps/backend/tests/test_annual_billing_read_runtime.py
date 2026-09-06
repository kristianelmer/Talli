"""Stored public annual facts, stable history and owner-scoped pagination."""

import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest

from test_annual_purchase_basis_runtime import DATABASE_URL, admitted, scoped, insert, test_role_authority
from test_annual_checkout_runtime import setup, session, candidate, observation, counts
from test_annual_cancellation_runtime import purchase, cancellation, command
from test_annual_refund_runtime import paid, command as refund_command, source, store, refund_observation
from test_annual_support_runtime import fingerprint
from talli_backend.adapters.supabase_annual_billing import PostgresAnnualBillingReadSession
from talli_backend.modules.billing.public import (
    AnnualBillingSnapshotQuery,
    AnnualPurchaseHistoryQuery,
    AnnualProviderStatus,
    AnnualPurchaseId,
    BillingError,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IdempotencyKey, UserId


pytestmark = pytest.mark.billing_database


def query(setup, **changes):
    return replace(AnnualBillingSnapshotQuery(setup[2].company_id, setup[2].income_year, setup[1]), **changes)


def reads(setup, **options):
    return PostgresAnnualBillingReadSession(session(setup, **options))


def test_empty_snapshot_is_authorized_and_contains_no_invented_purchase(setup):
    page = asyncio.run(reads(setup, current=False).read_purchases(query(setup)))
    assert page.purchases == () and page.next_purchase_id is None and counts(setup) == (0, 0)


def test_snapshot_copies_exact_stored_facts_without_loading_private_evidence(setup, purchase):
    paid = asyncio.run(
        session(setup).settle_checkout(
            purchase, observation(purchase, captured=149000, status=AnnualProviderStatus.CONFIRMED)
        )
    )
    receipt = asyncio.run(cancellation(setup).cancel_renewal(command(setup, purchase)))
    before = asyncio.run(session(setup).load_checkout(purchase.offer.company_id, purchase.purchase_id))
    result = asyncio.run(reads(setup, current=False).read_purchases(query(setup)))
    value = result.purchases[0]
    assert value.purchase_id == purchase.purchase_id and value.gross_minor == 149000
    assert value.net_minor == 119200 and value.vat_minor == 29800 and value.captured_minor == 149000
    assert value.terms_text == purchase.offer.terms_text and value.terms_digest == purchase.offer.terms_digest
    assert (
        value.renewal_canceled_at == receipt.effective_at
        and value.captured_at == paid.observation.captured_at
    )
    assert not (
        {
            "intent",
            "accepted_basis",
            "provider",
            "provider_account",
            "accepted_by",
            "request_fingerprint",
            "checkout_url",
        }
        & asdict(value).keys()
    )
    assert counts(setup) == (1, 1)
    assert (
        asyncio.run(session(setup).load_checkout(purchase.offer.company_id, purchase.purchase_id)) == before
    )


@pytest.mark.parametrize("mode", ["outsider", "stale_mfa", "actor_mismatch", "wrong_company"])
def test_read_rejects_untrusted_scope_even_when_no_purchase_exists(setup, mode):
    options = {}
    request = query(setup)
    outsider = ActorId(ActorKind.USER, UserId(str(setup[0]["outsider"])))
    if mode == "outsider":
        options["actor"] = outsider
        request = replace(request, actor_id=outsider)
    elif mode == "stale_mfa":
        options["fresh"] = False
    elif mode == "actor_mismatch":
        request = replace(request, actor_id=outsider)
    else:
        request = replace(request, company_id=CompanyId(str(uuid4())))
    with pytest.raises(BillingError):
        asyncio.run(reads(setup, **options).read_purchases(request))
    assert counts(setup) == (0, 0)


def test_refunded_and_failed_history_remains_distinct_from_new_purchase(setup, purchase):
    asyncio.run(
        session(setup).settle_checkout(
            purchase,
            observation(purchase, captured=149000, refunded=149000, status=AnnualProviderStatus.CONFIRMED),
        )
    )
    second = asyncio.run(
        session(setup).claim_checkout(candidate(setup, key=IdempotencyKey(str(uuid4()))), setup[4])
    ).checkout
    asyncio.run(
        session(setup).settle_checkout(second, observation(second, status=AnnualProviderStatus.FAILED))
    )
    third = asyncio.run(
        session(setup).claim_checkout(candidate(setup, key=IdempotencyKey(str(uuid4()))), setup[4])
    ).checkout
    result = asyncio.run(reads(setup).read_purchases(query(setup)))
    assert [value.purchase_id for value in result.purchases] == [
        third.purchase_id,
        second.purchase_id,
        purchase.purchase_id,
    ]
    assert [value.status.value for value in result.purchases] == ["pending", "failed", "refunded"]
    assert [value.refunded_minor for value in result.purchases] == [0, 0, 149000]


@pytest.mark.parametrize("company_wide", [False, True])
def test_cursor_is_scoped_and_pagination_is_stable_across_tied_timestamps(setup, purchase, company_wide):
    # Use real restricted-owner claims and confirmed terminal outcomes to create
    # enough history for two pages; no synthetic source or direct ledger inserts.
    async def create_history():
        current = purchase
        identities = []
        for index in range(52):
            identities.append(current.purchase_id)
            await session(setup).settle_checkout(
                current, observation(current, status=AnnualProviderStatus.FAILED)
            )
            if index < 51:
                proposed = candidate(setup, key=IdempotencyKey(str(uuid4())))
                proposed = replace(
                    proposed, intent=replace(proposed.intent, created_at=purchase.intent.created_at)
                )
                current = (await session(setup).claim_checkout(proposed, setup[4])).checkout
        return identities

    identities = asyncio.run(create_history())
    reader = reads(setup).read_purchase_history if company_wide else reads(setup).read_purchases
    scope = AnnualPurchaseHistoryQuery(setup[2].company_id, setup[1]) if company_wide else query(setup)
    first = asyncio.run(reader(scope))
    assert len(first.purchases) == 50 and first.next_purchase_id == first.purchases[-1].purchase_id
    second = asyncio.run(reader(replace(scope, before_purchase_id=first.next_purchase_id)))
    assert len(second.purchases) == 2 and second.next_purchase_id is None
    assert [value.purchase_id for value in (*first.purchases, *second.purchases)] == sorted(
        identities, key=str, reverse=True
    )
    with pytest.raises(BillingError):
        asyncio.run(
            reader(replace(scope, before_purchase_id=AnnualPurchaseId(str(uuid4()))))
        )


def test_snapshot_during_cancellation_has_consistent_unchanged_money_and_access(setup, purchase):
    asyncio.run(
        session(setup).settle_checkout(
            purchase, observation(purchase, captured=149000, status=AnnualProviderStatus.CONFIRMED)
        )
    )

    async def run():
        return await asyncio.gather(
            reads(setup).read_purchases(query(setup)),
            cancellation(setup).cancel_renewal(command(setup, purchase)),
        )

    page, receipt = asyncio.run(run())
    value = page.purchases[0]
    assert value.captured_minor == 149000 and value.refunded_minor == 0 and value.status.value == "paid"
    assert value.renewal_canceled_at in (None, receipt.effective_at)
    assert value.paid_through == receipt.paid_through and value.export_through == receipt.export_through


def test_http_snapshot_and_cancellation_use_real_verified_owner_stores(setup, purchase):
    from fastapi.testclient import TestClient
    from talli_backend.main import create_app
    from talli_backend.adapters.supabase_annual_billing import _AnnualBillingSession
    from talli_backend.adapters.postgres_annual_checkout import PostgresAnnualCancellationSession
    from talli_backend.adapters.postgres_annual_cleanup import PostgresAnnualCleanupSession
    from talli_backend.adapters.postgres_annual_support import PostgresAnnualSupportReadSession
    from talli_backend.adapters.postgres_annual_refund import (
        PostgresAnnualRefundRecoverySession, PostgresAnnualSupportRefundRecoverySession,
    )
    from talli_backend.application.billing_session import BillingAuthenticationError

    class Factory:
        async def session(self, token):
            if token != "local-verified-owner":
                raise BillingAuthenticationError()
            checkout = session(setup, current=False)
            return _AnnualBillingSession(
                PostgresAnnualBillingReadSession(checkout), PostgresAnnualCancellationSession(checkout), checkout,
                PostgresAnnualCleanupSession(checkout), PostgresAnnualSupportReadSession(checkout),
                PostgresAnnualRefundRecoverySession(checkout), PostgresAnnualSupportRefundRecoverySession(checkout),
            )

    api = TestClient(create_app(annual_billing_session_factory=Factory()))
    headers = {"Authorization": "Bearer local-verified-owner", "Idempotency-Key": str(uuid4())}
    params = {"companyId": str(purchase.offer.company_id), "incomeYear": 2026}
    before = api.get("/api/v1/billing/annual/snapshot", params=params, headers=headers)
    assert before.status_code == 200
    receipt = api.post(
        "/api/v1/billing/annual/renewal-cancellations",
        headers=headers,
        json={"companyId": str(purchase.offer.company_id), "purchaseId": str(purchase.purchase_id)},
    )
    assert receipt.status_code == 200
    after = api.get("/api/v1/billing/annual/snapshot", params=params, headers=headers)
    assert after.status_code == 200
    value = after.json()["purchases"][0]
    assert value["renewalCanceledAt"] == receipt.json()["effectiveAt"]
    assert value["status"] == "pending" and value["capturedMinor"] == value["refundedMinor"] == 0
    assert value["paidThrough"] == before.json()["purchases"][0]["paidThrough"]
    assert counts(setup) == (1, 1), "Annual HTTP reads/cancellation must not create provider operations"


def test_existing_foreign_company_cursor_cannot_be_used_for_owned_snapshot(setup,purchase,request):
    other = globals()["setup"].__wrapped__(admitted.__wrapped__(request))
    foreign = asyncio.run(session(other).claim_checkout(candidate(other),other[4])).checkout
    with pytest.raises(BillingError) as error:
        asyncio.run(reads(setup).read_purchases(query(setup,before_purchase_id=foreign.purchase_id)))
    assert error.value.code == "BILLING_NOT_FOUND"


@pytest.mark.parametrize("status", [AnnualProviderStatus.PENDING, AnnualProviderStatus.UNKNOWN, AnnualProviderStatus.FAILED])
def test_owner_refund_history_keeps_unconfirmed_liability_and_never_mutates_evidence(setup, paid, status):
    request = refund_command(setup, paid)
    resolution = asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution
    asyncio.run(store(setup).settle_refund(resolution, refund_observation(resolution, status)))
    before = fingerprint(setup)
    value = asyncio.run(reads(setup, current=False).read_purchases(query(setup))).purchases[0]
    assert value.recorded_refund_minor == value.remaining_refund_minor == 149000
    assert value.refunded_minor == 0 and getattr(value.refund_operations, status.value) == 1
    assert value.refund_request_count == 1 and value.latest_refund_requested_at is not None
    assert value.refund_initiate_by == resolution.decision.initiate_by
    assert fingerprint(setup) == before


def test_owner_refund_history_never_sums_duplicate_cumulative_cases(setup, paid):
    first = refund_command(setup, paid)
    initial = asyncio.run(store(setup, source(paid, first)).claim_refund(first)).resolution
    second = refund_command(setup, paid)
    deferred = asyncio.run(store(setup, source(paid, second)).claim_refund(second)).resolution
    assert deferred.operation is None
    value = asyncio.run(reads(setup).read_purchases(query(setup))).purchases[0]
    assert value.recorded_refund_minor == value.remaining_refund_minor == 149000
    assert value.refund_request_count == 2 and value.refund_operations.created == 1
    assert value.refund_initiate_by == min(initial.decision.initiate_by, deferred.decision.initiate_by)


def test_owner_history_keeps_partial_settlement_distinct_from_full_recorded_refund(setup, purchase):
    partial = asyncio.run(session(setup).settle_checkout(purchase, observation(purchase, captured=50000)))
    request = refund_command(setup, partial)
    original = asyncio.run(store(setup, source(partial, request)).claim_refund(request)).resolution
    asyncio.run(session(setup).settle_checkout(partial, observation(partial, captured=149000,
        captured_at=partial.observation.captured_at, status=AnnualProviderStatus.CONFIRMED)))
    asyncio.run(store(setup).settle_refund(original, refund_observation(original, captured_minor=149000)))
    value = asyncio.run(reads(setup).read_purchases(query(setup))).purchases[0]
    assert (value.recorded_refund_minor, value.refunded_minor, value.remaining_refund_minor) == (149000, 50000, 99000)
    assert value.refund_operations.confirmed == 1 and value.refund_initiate_by == original.decision.initiate_by
    assert value.status.value == "paid"


def test_owner_read_and_refund_settlement_use_one_consistent_money_and_operation_snapshot(setup, paid):
    request = refund_command(setup, paid)
    resolution = asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution

    async def concurrent():
        return await asyncio.gather(reads(setup).read_purchases(query(setup)),
            store(setup).settle_refund(resolution, refund_observation(resolution)))

    page, _ = asyncio.run(concurrent())
    value = page.purchases[0]
    assert (value.refunded_minor, value.remaining_refund_minor, value.refund_operations.created, value.refund_operations.confirmed) in (
        (0, 149000, 1, 0), (149000, 0, 0, 1),
    )
    final = asyncio.run(reads(setup).read_purchases(query(setup))).purchases[0]
    assert final.refunded_minor == 149000 and final.remaining_refund_minor == 0 and final.refund_initiate_by is None


def test_company_history_authorizes_an_accepted_owner_without_any_admission(setup):
    company = uuid4()
    now = datetime.now(UTC)
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection, "public.companies", {
            "id": company, "org_number": str(100000000 + company.int % 899999999), "name": "Unadmitted History AS",
            "entity_type": "AS", "address": "Testveien 1", "postal_code": "0150", "city": "Oslo",
            "status_text": "aktiv", "source": "test", "created_by": setup[1].subject.value,
            "identity_confirmed_at": now, "identity_locked_at": now,
        })
        insert(connection, "public.company_memberships", {"company_id": company, "user_id": setup[1].subject.value,
            "role": "owner", "accepted_at": now})
        assert connection.execute("select count(*) from public.company_year_admissions where company_id=%s", (company,)).fetchone()[0] == 0
    scope = AnnualPurchaseHistoryQuery(CompanyId(str(company)), setup[1])
    page = asyncio.run(reads(setup, current=False).read_purchase_history(scope))
    assert page.purchases == () and page.next_purchase_id is None


@pytest.mark.parametrize("mode", ["outsider", "stale_mfa", "actor_mismatch", "wrong_company"])
def test_company_history_current_authority_is_required_even_for_empty_history(setup, mode):
    outsider = ActorId(ActorKind.USER, UserId(str(setup[0]["outsider"])))
    scope = AnnualPurchaseHistoryQuery(setup[2].company_id, setup[1])
    options = {}
    if mode == "outsider":
        options["actor"] = outsider
        scope = replace(scope, actor_id=outsider)
    elif mode == "stale_mfa": options["fresh"] = False
    elif mode == "actor_mismatch": scope = replace(scope, actor_id=outsider)
    else: scope = replace(scope, company_id=CompanyId(str(uuid4())))
    with pytest.raises(BillingError):
        asyncio.run(reads(setup, **options).read_purchase_history(scope))
    assert counts(setup) == (0, 0)


def test_company_history_survives_changed_readiness_but_not_revoked_ownership(setup, paid):
    scope = AnnualPurchaseHistoryQuery(setup[2].company_id, setup[1])
    before = fingerprint(setup)
    page = asyncio.run(reads(setup, current=False).read_purchase_history(scope))
    assert page.purchases[0].purchase_id == paid.purchase_id and page.purchases[0].terms_text == paid.offer.terms_text
    assert fingerprint(setup) == before
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("delete from public.company_memberships where company_id=%s and user_id=%s",
                           (str(scope.company_id), str(scope.actor_id.subject)))
    with pytest.raises(BillingError) as error:
        asyncio.run(reads(setup, current=False).read_purchase_history(scope))
    assert error.value.code == "BILLING_FORBIDDEN"


def test_company_history_rejects_foreign_cursor_and_distinguishes_end_of_owned_history(setup, purchase, request):
    scope = AnnualPurchaseHistoryQuery(setup[2].company_id, setup[1])
    page = asyncio.run(reads(setup).read_purchase_history(replace(scope, before_purchase_id=purchase.purchase_id)))
    assert page.purchases == () and page.next_purchase_id is None
    other = globals()["setup"].__wrapped__(admitted.__wrapped__(request))
    foreign = asyncio.run(session(other).claim_checkout(candidate(other), other[4])).checkout
    with pytest.raises(BillingError) as error:
        asyncio.run(reads(setup).read_purchase_history(replace(scope, before_purchase_id=foreign.purchase_id)))
    assert error.value.code == "BILLING_NOT_FOUND"
