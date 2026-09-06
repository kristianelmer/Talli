"""Stored public annual facts, stable history and owner-scoped pagination."""

import asyncio
from dataclasses import asdict, replace
from uuid import uuid4

import psycopg
import pytest

from test_annual_purchase_basis_runtime import DATABASE_URL, admitted, scoped, test_role_authority
from test_annual_checkout_runtime import setup, session, candidate, observation, counts
from test_annual_cancellation_runtime import purchase, cancellation, command
from talli_backend.adapters.supabase_annual_billing import PostgresAnnualBillingReadSession
from talli_backend.modules.billing.public import (
    AnnualBillingSnapshotQuery,
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


def test_cursor_is_scoped_and_pagination_is_stable_across_tied_timestamps(setup, purchase):
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
    first = asyncio.run(reads(setup).read_purchases(query(setup)))
    assert len(first.purchases) == 50 and first.next_purchase_id == first.purchases[-1].purchase_id
    second = asyncio.run(reads(setup).read_purchases(query(setup, before_purchase_id=first.next_purchase_id)))
    assert len(second.purchases) == 2 and second.next_purchase_id is None
    assert [value.purchase_id for value in (*first.purchases, *second.purchases)] == sorted(
        identities, key=str, reverse=True
    )
    with pytest.raises(BillingError):
        asyncio.run(
            reads(setup).read_purchases(query(setup, before_purchase_id=AnnualPurchaseId(str(uuid4()))))
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
    from talli_backend.application.billing_session import BillingAuthenticationError

    class Factory:
        async def session(self, token):
            if token != "local-verified-owner":
                raise BillingAuthenticationError()
            checkout = session(setup, current=False)
            return _AnnualBillingSession(
                PostgresAnnualBillingReadSession(checkout), PostgresAnnualCancellationSession(checkout), checkout,
                PostgresAnnualCleanupSession(checkout), PostgresAnnualSupportReadSession(checkout),
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
