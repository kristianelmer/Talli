"""Real database retirement guards and predecessor history recovery."""

import asyncio
from datetime import UTC, datetime
import json
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from test_annual_purchase_basis_runtime import DATABASE_URL, ROOT, admitted, scoped, test_role_authority
from test_legacy_billing_retirement import ObservedProvider
from talli_backend.adapters.supabase_billing import SupabaseBillingSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.billing.public import (
    ActivateSubscriptionCommand, BillingError, BillingPaymentStatus,
    BillingPlan, BillingPricing, CancelSubscriptionCommand,
    ConfigureBillingAccountCommand, PurchaseFilingPackageCommand, RefundFilingPackageCommand,
)
from talli_backend.modules.billing.service import BillingService
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, CorrelationId, IdempotencyKey, IncomeYear, UserId

MIGRATION = "20260905115700_legacy_billing_acquisition_retirement.sql"


@pytest.fixture(scope="module", autouse=True)
def legacy_reader_authority():
    with psycopg.connect(DATABASE_URL) as connection:
        principal = connection.execute("select current_user").fetchone()[0]
        borrowed = not connection.execute("select pg_has_role(current_user, 'billing_executor', 'SET')").fetchone()[0]
        if borrowed:
            connection.execute(sql.SQL("grant billing_executor to {}").format(sql.Identifier(principal)))
    try:
        yield
    finally:
        if borrowed:
            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute(sql.SQL("revoke billing_executor from {}").format(sql.Identifier(principal)))


def install(connection, directory="migrations"):
    connection.execute((ROOT / "supabase" / directory / MIGRATION).read_text())


@pytest.fixture
def historical(admitted, request):
    options = getattr(request, "param", {})
    events = {kind: {"id": uuid4(), "key": str(uuid4())} for kind in
              ("subscription", "filing_package", "subscription_cancellation", "refund")}
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        install(connection, "rollback")
        try:
            with connection.transaction():
                scoped(connection, admitted["owner"])
                connection.execute("""insert into billing.billing_accounts
                    (company_id,pricing_plan,monthly_nok,filing_package_nok,updated_by,
                     subscription_active,filing_package_paid)
                    values (%s,'standard',49,499,%s,%s,%s)""",
                    (admitted["company"], admitted["owner"],
                     options.get("subscription_active", False), options.get("filing_package_paid", False)))
                for kind, event in events.items():
                    connection.execute("""insert into billing.billing_payment_events
                        (id,company_id,provider,provider_reference,idempotency_key,kind,status,
                         amount_nok,income_year,payload,created_by)
                        values (%s,%s,'simulation',%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""",
                        (event["id"], admitted["company"], "historical-" + event["key"], event["key"], kind,
                         "succeeded" if kind == "subscription" else "created",
                         49 if kind == "subscription" else 0 if kind == "subscription_cancellation" else 499,
                         2025 if kind in ("filing_package", "refund") else None,
                         json.dumps({"obligation": "aksjonaerregisteroppgaven" if kind == "filing_package" else None}),
                         admitted["owner"]))
        finally:
            install(connection)
    return admitted | {"events": events}


def session(state, *, fresh=True):
    return SupabaseBillingSession(DATABASE_URL, _VerifiedActor(
        actor_id=ActorId(ActorKind.USER, UserId(str(state["owner"]))),
        claims_json=json.dumps({"sub": str(state["owner"]), "role": "authenticated", "aal": "aal2",
            "amr": [{"method": "totp", "timestamp": datetime.now(UTC).timestamp() if fresh else 1}]})))


def command(state, kind, *, key=None):
    cls = {"subscription": ActivateSubscriptionCommand, "filing_package": PurchaseFilingPackageCommand,
           "subscription_cancellation": CancelSubscriptionCommand, "refund": RefundFilingPackageCommand}[kind]
    extra = {"income_year": IncomeYear(2025)} if kind in ("filing_package", "refund") else {}
    return cls(company_id=CompanyId(str(state["company"])), actor_id=session(state).actor_id,
        correlation_id=CorrelationId(str(uuid4())),
        idempotency_key=IdempotencyKey(key or state["events"][kind]["key"]), **extra)


def evidence(state):
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, state["owner"])
        account = connection.execute("select to_jsonb(account) from billing.billing_accounts account where company_id=%s", (state["company"],)).fetchone()[0]
        events = connection.execute("select to_jsonb(event) from billing.billing_payment_events event where company_id=%s order by id", (state["company"],)).fetchall()
        return account, events


@pytest.mark.parametrize("kind", ["subscription", "filing_package"])
@pytest.mark.parametrize("duplicate", [False, True])
def test_older_binary_cannot_insert_acquisition_even_with_on_conflict(historical, kind, duplicate):
    before = evidence(historical)
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, historical["owner"])
        with pytest.raises(psycopg.Error, match="billing_legacy_acquisition_retired"):
            connection.execute("""insert into billing.billing_payment_events
                (company_id,provider_reference,idempotency_key,kind,status,amount_nok,created_by)
                values (%s,'new-reference',%s,%s,'created',49,%s)
                on conflict (idempotency_key) do nothing""",
                (historical["company"], historical["events"][kind]["key"] if duplicate else str(uuid4()), kind, historical["owner"]))
    assert evidence(historical) == before


def test_older_configuration_upsert_cannot_reset_a_historical_account(historical):
    before = evidence(historical)
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, historical["owner"])
        with pytest.raises(psycopg.Error, match="billing_legacy_acquisition_retired"):
            connection.execute("""insert into billing.billing_accounts
                (company_id,pricing_plan,monthly_nok,filing_package_nok,updated_by)
                values (%s,'standard',49,499,%s) on conflict(company_id) do update set supported_case=true""",
                (historical["company"], historical["owner"]))
    assert evidence(historical) == before


@pytest.mark.parametrize("assignment", [
    "subscription_active=true", "filing_package_paid=true", "monthly_nok=99",
    "filing_package_nok=999", "created_at=created_at-interval '1 day'",
])
def test_paid_flag_reactivation_and_historical_price_changes_are_rejected(historical, assignment):
    before = evidence(historical)
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, historical["owner"])
        with pytest.raises(psycopg.Error, match="billing_legacy_acquisition_retired"):
            connection.execute(f"update billing.billing_accounts set {assignment} where company_id=%s", (historical["company"],))
    assert evidence(historical) == before


@pytest.mark.parametrize("assignment", [
    "kind='subscription'", "idempotency_key='replacement-key'", "provider='replacement-provider'",
    "amount_nok=1", "income_year=2026", "id=gen_random_uuid()", "company_id=gen_random_uuid()",
    "created_at=created_at-interval '1 day'",
])
def test_cleanup_rows_cannot_be_repurposed_as_acquisition_or_other_history(historical, assignment):
    before = evidence(historical)
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, historical["owner"])
        with pytest.raises(psycopg.Error, match="billing_legacy_event_identity_immutable"):
            connection.execute(f"update billing.billing_payment_events set {assignment} where id=%s", (historical["events"]["subscription_cancellation"]["id"],))
    assert evidence(historical) == before


def test_original_obligation_and_terminal_evidence_are_immutable(historical):
    before = evidence(historical)
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, historical["owner"])
        with pytest.raises(psycopg.Error, match="billing_legacy_event_identity_immutable"):
            connection.execute("""update billing.billing_payment_events
                set payload=jsonb_build_object('obligation','skattemelding') where id=%s""",
                (historical["events"]["filing_package"]["id"],))
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, historical["owner"])
        # The predecessor UPDATE policy already hides settled rows from writes.
        assert connection.execute("""update billing.billing_payment_events
            set provider_reference='changed' where id=%s""",
            (historical["events"]["subscription"]["id"],)).rowcount == 0
    assert evidence(historical) == before


def test_adapter_rejects_new_acquisition_and_replays_without_insert(historical):
    store = session(historical)
    for kind, amount in [("subscription", 49), ("filing_package", 499)]:
        with pytest.raises(BillingError) as denied:
            asyncio.run(store.begin_provider_event(command(historical, kind, key=str(uuid4())), "simulation", amount))
        assert str(denied.value.code) == "BILLING_LEGACY_ACQUISITION_RETIRED"
        replay = asyncio.run(store.begin_provider_event(command(historical, kind), "simulation", amount))
        assert replay.replayed
    configure = ConfigureBillingAccountCommand(company_id=CompanyId(str(historical["company"])),
        actor_id=store.actor_id, correlation_id=CorrelationId("configuration"),
        idempotency_key=IdempotencyKey(str(uuid4())), pricing_plan=BillingPlan.STANDARD)
    with pytest.raises(BillingError):
        asyncio.run(store.configure_account(configure, BillingPricing(BillingPlan.STANDARD, 49, 499)))


def test_historical_acquisition_reconciles_without_restoring_any_paid_flag(historical):
    before, _ = evidence(historical)
    provider = ObservedProvider()
    service = BillingService(session(historical), provider)
    replay = asyncio.run(service.activate_subscription(command(historical, "subscription")))
    assert replay.replayed and provider.calls == []
    completed = asyncio.run(service.purchase_filing_package(command(historical, "filing_package")))
    assert completed.status is BillingPaymentStatus.SUCCEEDED
    assert [kind for kind, _ in provider.calls] == ["reconcile"]
    after, _ = evidence(historical)
    assert after == before
    again = asyncio.run(service.purchase_filing_package(command(historical, "filing_package")))
    assert again.replayed and len(provider.calls) == 1


@pytest.mark.parametrize("historical", [{"subscription_active": True, "filing_package_paid": True}], indirect=True)
def test_legacy_cancellation_and_refund_recovery_still_reduce_the_original_account(historical):
    service = BillingService(session(historical), ObservedProvider())
    canceled = asyncio.run(service.cancel_subscription(command(historical, "subscription_cancellation")))
    refunded = asyncio.run(service.refund_filing_package(command(historical, "refund")))
    assert canceled.status is BillingPaymentStatus.CANCELED and refunded.status is BillingPaymentStatus.REFUNDED
    value, _ = evidence(historical)
    assert not value["subscription_active"] and value["refund_completed"]


def test_retirement_rollback_recutover_preserves_all_historical_rows_twice(historical):
    before = evidence(historical)
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        for _ in range(2):
            install(connection, "rollback")
            install(connection)
            assert evidence(historical) == before
