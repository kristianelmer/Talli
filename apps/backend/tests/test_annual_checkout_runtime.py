"""Real independent-connection checkout proof on a disposable local PostgreSQL."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4

import psycopg
import pytest

from test_annual_purchase_basis_runtime import (
    DATABASE_URL,
    ROOT,
    admitted,
    basis,
    insert,
    scoped,
    test_role_authority,
)
from talli_backend.adapters.postgres_annual_checkout import PostgresAnnualCheckoutSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.billing.annual_policy import annual_offer
from talli_backend.modules.billing.annual_service import AnnualCheckoutService, checkout_fingerprint
from talli_backend.modules.billing.public import (
    AnnualAcceptanceBasisReference,
    AnnualCheckout,
    AnnualCheckoutPrerequisites,
    AnnualCheckoutQuery,
    AnnualProviderIntent,
    AnnualProviderObservation,
    AnnualProviderOperation,
    AnnualProviderStatus,
    AnnualPurchaseId,
    AnnualPurchaseStatus,
    BillingError,
    BillingErrorCode,
    BillingPaymentEventId,
    StartAnnualCheckoutCommand,
)
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    Timestamp,
    UserId,
)


pytestmark = pytest.mark.billing_database


@pytest.fixture
def setup(admitted):
    company = CompanyId(str(admitted["company"]))
    actor = ActorId(ActorKind.USER, UserId(str(admitted["owner"])))
    offer = annual_offer(company, IncomeYear(2026))
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        raw = basis(connection, admitted)
    evidence = AnnualCheckoutPrerequisites(
        AnnualAcceptanceBasisReference(
            company,
            offer.income_year,
            raw["assessment_id"],
            raw["legal_evidence"]["id"],
            raw["admission_id"],
            raw["company_year_promise_sha256"],
            raw["capability_manifest_sha256"],
        ),
        str(uuid4()),
        "c" * 64,
        Timestamp(datetime.now(UTC)),
        True,
    )
    command = StartAnnualCheckoutCommand(
        company_id=company,
        actor_id=actor,
        correlation_id=CorrelationId(str(uuid4())),
        idempotency_key=IdempotencyKey(str(uuid4())),
        income_year=offer.income_year,
        offer_version=offer.offer_version,
        terms_digest=offer.terms_digest,
        purchase_accepted=True,
        recurring_consent=True,
        consent_version=offer.offer_version,
    )
    return admitted, actor, offer, raw, evidence, command


def session(setup, *, actor=None, fresh=True, current=True, session_type=PostgresAnnualCheckoutSession):
    who = actor or setup[1]
    verified = _VerifiedActor(
        who,
        json.dumps(
            {
                "sub": str(who.subject),
                "aal": "aal2",
                "amr": [
                    {"method": "totp", "timestamp": datetime.now(UTC).timestamp() - (0 if fresh else 7200)}
                ],
            }
        ),
    )

    async def verifier(evidence):
        return current and evidence == setup[4]

    return session_type(DATABASE_URL, verified, readiness_is_current=verifier)


def candidate(setup, *, key=None):
    command = replace(setup[5], idempotency_key=key or setup[5].idempotency_key)
    identity = AnnualPurchaseId(str(uuid4()))
    intent = AnnualProviderIntent(
        BillingPaymentEventId(str(uuid4())),
        setup[2].company_id,
        setup[2].income_year,
        AnnualProviderOperation.CHECKOUT,
        149000,
        Timestamp(datetime.now(UTC)),
        f"agreement-{identity}",
        f"charge-{identity}",
        "https://example.test/return",
        "https://example.test/manage",
        recurring_consent=True,
    )
    return AnnualCheckout(
        identity,
        setup[2],
        setup[1].subject,
        checkout_fingerprint(command),
        command.idempotency_key,
        "vipps-mt",
        "123456",
        intent,
        AnnualPurchaseStatus.PENDING,
    )


def observation(
    checkout,
    *,
    status=AnnualProviderStatus.PENDING,
    captured=0,
    refunded=0,
    captured_at=None,
    agreement="agr-test",
):
    return AnnualProviderObservation(
        checkout.provider,
        AnnualProviderOperation.CHECKOUT,
        status,
        agreement,
        checkout.intent.charge_reference,
        149000,
        captured_minor=captured,
        refunded_minor=refunded,
        captured_at=captured_at or (Timestamp(datetime.now(UTC)) if captured else None),
    )


def counts(setup):
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        return connection.execute(
            "select (select count(*) from billing.annual_purchases where company_id=%s), (select count(*) from billing.annual_operations where company_id=%s)",
            (str(setup[2].company_id),) * 2,
        ).fetchone()


def test_independent_concurrent_claims_reuse_exact_original_intent_and_basis(setup):
    first, second = candidate(setup), candidate(setup)

    async def run():
        return await asyncio.gather(
            session(setup).claim_checkout(first, setup[4]), session(setup).claim_checkout(second, setup[4])
        )

    results = asyncio.run(run())
    assert sorted(x.newly_claimed for x in results) == [False, True]
    winner = next(x.checkout for x in results if x.newly_claimed)
    assert all(x.checkout == winner for x in results)
    assert counts(setup) == (1, 1)
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        row = connection.execute(
            "select accepted_basis,terms_text,terms_digest from billing.annual_purchases where id=%s",
            (str(winner.purchase_id),),
        ).fetchone()
        assert row == (setup[3], setup[2].terms_text, setup[2].terms_digest)
        saved = connection.execute(
            "select intent from billing.annual_operations where purchase_id=%s", (str(winner.purchase_id),)
        ).fetchone()[0]
        assert saved["readiness"] == {
            "reference": setup[4].readiness_reference,
            "digest": setup[4].readiness_digest,
            "evaluated_at": setup[4].evaluated_at.value.isoformat(),
            "ready": True,
        }


def test_different_keys_same_year_have_only_one_winner(setup):
    async def run():
        return await asyncio.gather(
            *(
                session(setup).claim_checkout(candidate(setup, key=IdempotencyKey(str(uuid4()))), setup[4])
                for _ in range(2)
            ),
            return_exceptions=True,
        )

    results = asyncio.run(run())
    assert sum(not isinstance(x, Exception) for x in results) == 1
    assert (
        next(x for x in results if isinstance(x, BillingError)).code
        == BillingErrorCode.IDEMPOTENCY_IN_PROGRESS
    )
    assert counts(setup) == (1, 1)


@pytest.mark.parametrize(
    "mode",
    [
        "stale_mfa",
        "outsider",
        "wrong_assessment",
        "wrong_legal",
        "wrong_admission",
        "wrong_digest",
        "wrong_year",
        "stale_readiness",
        "future_readiness",
        "forged_readiness",
        "unavailable_readiness",
    ],
)
def test_invalid_current_prerequisites_and_authority_never_claim(setup, mode):
    store = session(setup, fresh=mode != "stale_mfa", current=mode != "unavailable_readiness")
    checkout, evidence = candidate(setup), setup[4]
    if mode == "outsider":
        store = session(setup, actor=ActorId(ActorKind.USER, UserId(str(setup[0]["outsider"]))))
    if mode.startswith("wrong_"):
        key = {
            "wrong_assessment": "assessment_id",
            "wrong_legal": "legal_acceptance_id",
            "wrong_admission": "admission_id",
            "wrong_digest": "promise_digest",
            "wrong_year": "income_year",
        }[mode]
        value = (
            IncomeYear(2027)
            if key == "income_year"
            else ("d" * 64 if key == "promise_digest" else str(uuid4()))
        )
        evidence = replace(evidence, basis=replace(evidence.basis, **{key: value}))
    if mode in {"stale_readiness", "future_readiness"}:
        evidence = replace(
            evidence,
            evaluated_at=Timestamp(
                datetime.now(UTC) + timedelta(minutes=10 if mode == "future_readiness" else -10)
            ),
        )
    if mode == "forged_readiness":
        evidence = replace(evidence, readiness_digest="e" * 64)
    with pytest.raises(BillingError):
        asyncio.run(store.claim_checkout(checkout, evidence))
    assert counts(setup) == (0, 0)


def test_default_readiness_binding_denies_even_fixture_ready(setup):
    store = session(setup)
    closed = PostgresAnnualCheckoutSession(DATABASE_URL, store._verified)
    with pytest.raises(BillingError) as error:
        asyncio.run(closed.claim_checkout(candidate(setup), setup[4]))
    assert error.value.code == BillingErrorCode.FILING_NOT_READY
    assert counts(setup) == (0, 0)


class Provider:
    provider = "vipps-mt"
    account_reference = "123456"
    production_enabled = False

    def __init__(self, setup):
        self.setup = setup
        self.executions = []
        self.reconciliations = []

    async def execute(self, intent):
        assert counts(self.setup) == (1, 1), (
            "Independent connection must see committed intent before provider execution"
        )
        self.executions.append(intent)
        return AnnualProviderObservation(
            self.provider,
            AnnualProviderOperation.CHECKOUT,
            AnnualProviderStatus.PENDING,
            "agr-test",
            intent.charge_reference,
            149000,
        )

    async def reconcile(self, intent):
        self.reconciliations.append(intent)
        return AnnualProviderObservation(
            self.provider,
            AnnualProviderOperation.CHECKOUT,
            AnnualProviderStatus.UNKNOWN,
            intent.agreement_reference,
            intent.charge_reference,
            149000,
        )


def service(store, provider):
    return AnnualCheckoutService(
        store,
        provider,
        return_url="https://example.test/return",
        management_url="https://example.test/manage",
    )


@pytest.mark.parametrize("lost", ["claim", "settlement"])
def test_lost_committed_response_reconciles_original_and_never_creates_again(setup, lost):
    class LostResponse(PostgresAnnualCheckoutSession):
        async def claim_checkout(self, *args):
            result = await super().claim_checkout(*args)
            if lost == "claim":
                raise BillingError.unavailable()
            return result

        async def settle_checkout(self, *args):
            result = await super().settle_checkout(*args)
            if lost == "settlement":
                raise BillingError.unavailable()
            return result

    provider = Provider(setup)

    async def ready():
        return setup[4]

    with pytest.raises(BillingError):
        asyncio.run(
            service(session(setup, session_type=LostResponse), provider).start_checkout(setup[5], ready)
        )
    original = asyncio.run(session(setup).find_checkout(setup[2].company_id, setup[5].idempotency_key))

    async def blocked():
        raise AssertionError("Existing effects reconcile without readiness")

    recovered = asyncio.run(
        service(session(setup, current=False), provider).start_checkout(setup[5], blocked)
    )
    assert recovered.purchase_id == original.purchase_id and recovered.intent == original.intent
    assert len(provider.executions) == (0 if lost == "claim" else 1)
    assert len(provider.reconciliations) == 1 and counts(setup) == (1, 1)


def test_concurrent_services_execute_provider_only_for_committed_winner(setup):
    provider = Provider(setup)

    async def ready():
        return setup[4]

    async def run():
        return await asyncio.gather(
            *(service(session(setup), provider).start_checkout(setup[5], ready) for _ in range(2))
        )

    results = asyncio.run(run())
    assert results[0].purchase_id == results[1].purchase_id
    assert len(provider.executions) == 1 and len(provider.reconciliations) == 1


@pytest.mark.parametrize(
    "captured,refunded,status,expected",
    [
        (149000, 0, AnnualProviderStatus.CONFIRMED, AnnualPurchaseStatus.PAID),
        (149000, 149000, AnnualProviderStatus.CONFIRMED, AnnualPurchaseStatus.REFUNDED),
        (1000, 1000, AnnualProviderStatus.PENDING, AnnualPurchaseStatus.PENDING),
        (0, 0, AnnualProviderStatus.FAILED, AnnualPurchaseStatus.FAILED),
    ],
)
def test_settlement_classification_and_terminal_replay(setup, captured, refunded, status, expected):
    store = session(setup)
    initial = asyncio.run(store.claim_checkout(candidate(setup), setup[4])).checkout
    result = asyncio.run(
        store.settle_checkout(
            initial, observation(initial, status=status, captured=captured, refunded=refunded)
        )
    )
    assert result.status == expected
    assert asyncio.run(store.load_checkout(initial.offer.company_id, initial.purchase_id)) == result
    assert asyncio.run(store.settle_checkout(initial, observation(initial))) == result


def test_second_statement_failure_rolls_back_purchase_and_retry_settles(setup, monkeypatch):
    store = session(setup)
    initial = asyncio.run(store.claim_checkout(candidate(setup), setup[4])).checkout
    confirmed = observation(initial, status=AnnualProviderStatus.CONFIRMED, captured=149000)
    original_execute = psycopg.AsyncConnection.execute

    async def fail_operation(connection, query, *args, **kwargs):
        if isinstance(query, str) and "update billing.annual_operations set" in query:
            raise psycopg.OperationalError("fixture connection lost before operation update")
        return await original_execute(connection, query, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(psycopg.AsyncConnection, "execute", fail_operation)
        with pytest.raises(BillingError):
            asyncio.run(store.settle_checkout(initial, confirmed))
    assert asyncio.run(store.load_checkout(initial.offer.company_id, initial.purchase_id)) == initial
    assert asyncio.run(store.settle_checkout(initial, confirmed)).status == AnnualPurchaseStatus.PAID


@pytest.mark.parametrize("change", ["capture", "refund", "agreement", "timestamp"])
def test_latest_locked_state_rejects_obsolete_poll(setup, change):
    store = session(setup)
    initial = asyncio.run(store.claim_checkout(candidate(setup), setup[4])).checkout
    latest = observation(initial, captured=1000, refunded=500)
    current = asyncio.run(store.settle_checkout(initial, latest))
    changes = {
        "capture": {"captured_minor": 900},
        "refund": {"refunded_minor": 0},
        "agreement": {"agreement_reference": "different"},
        "timestamp": {"captured_at": Timestamp(latest.captured_at.value + timedelta(microseconds=1))},
    }[change]
    assert asyncio.run(session(setup).settle_checkout(initial, replace(latest, **changes))) == current


def test_settlement_waits_for_purchase_before_operation_and_reads_latest(setup):
    store = session(setup)
    initial = asyncio.run(store.claim_checkout(candidate(setup), setup[4])).checkout

    async def run():
        with (
            psycopg.connect(DATABASE_URL) as holder,
            psycopg.connect(DATABASE_URL, autocommit=True) as monitor,
        ):
            scoped(holder, setup[1].subject)
            holder.execute(
                "select id from billing.annual_purchases where id=%s for update", (str(initial.purchase_id),)
            )
            task = asyncio.create_task(session(setup).settle_checkout(initial, observation(initial)))
            # Observe the independent transaction waiting on our purchase lock.
            for _ in range(100):
                waiting = monitor.execute(
                    "select count(*) from pg_stat_activity where %s=any(pg_blocking_pids(pid))",
                    (holder.info.backend_pid,),
                ).fetchone()[0]
                if waiting:
                    break
                await asyncio.sleep(0.005)
                holder.execute("select pg_stat_clear_snapshot()")
            assert waiting and not task.done()
            # If the waiter took the operation first this would time out.
            holder.execute("set local lock_timeout='200ms'")
            holder.execute(
                "select id from billing.annual_operations where purchase_id=%s for update",
                (str(initial.purchase_id),),
            )
            holder.execute(
                "update billing.annual_purchases set status='failed' where id=%s", (str(initial.purchase_id),)
            )
            holder.execute(
                "update billing.annual_operations set status='failed' where purchase_id=%s",
                (str(initial.purchase_id),),
            )
            holder.commit()
            return await task

    assert asyncio.run(run()).status == AnnualPurchaseStatus.FAILED


def test_changed_current_eligibility_blocks_new_claim_but_existing_reconciles(setup):
    initial = asyncio.run(session(setup).claim_checkout(candidate(setup), setup[4])).checkout
    with psycopg.connect(DATABASE_URL) as connection:
        insert(
            connection,
            "public.company_eligibility_assessments",
            setup[0]["assessment"]
            | {
                "id": uuid4(),
                "operation_id": uuid4(),
                "previous_assessment_id": setup[0]["current"],
                "trigger": "material_answer_changed",
                "assessed_at": datetime.now(UTC),
                "decision": "blocked",
                "consequential_operations_allowed": False,
            },
        )
    with pytest.raises(BillingError) as error:
        asyncio.run(
            session(setup).claim_checkout(candidate(setup, key=IdempotencyKey(str(uuid4()))), setup[4])
        )
    assert error.value.code == BillingErrorCode.UNSUPPORTED_CASE
    replay = asyncio.run(session(setup, current=False).claim_checkout(candidate(setup), setup[4]))
    assert not replay.newly_claimed and replay.checkout == initial
    provider = Provider(setup)
    result = asyncio.run(
        service(session(setup, current=False), provider).poll_checkout(
            AnnualCheckoutQuery(initial.offer.company_id, setup[1], initial.purchase_id)
        )
    )
    assert result.purchase_id == initial.purchase_id and len(provider.reconciliations) == 1


def test_cross_tenant_global_key_collision_is_concealed_and_atomic(setup, request):
    other = globals()["setup"].__wrapped__(admitted.__wrapped__(request))
    initial = asyncio.run(session(setup).claim_checkout(candidate(setup), setup[4])).checkout
    with pytest.raises(BillingError) as denied:
        asyncio.run(session(other).load_checkout(initial.offer.company_id, initial.purchase_id))
    assert denied.value.code == BillingErrorCode.FORBIDDEN
    assert asyncio.run(session(other).find_checkout(other[2].company_id, initial.idempotency_key)) is None
    with pytest.raises(BillingError) as error:
        asyncio.run(session(other).claim_checkout(candidate(other, key=initial.idempotency_key), other[4]))
    assert error.value.code == BillingErrorCode.IDEMPOTENCY_KEY_REUSED
    assert counts(other) == (0, 0) and counts(setup) == (1, 1)


def test_adapter_records_survive_two_rollback_recutover_cycles(setup):
    store = session(setup)
    initial = asyncio.run(store.claim_checkout(candidate(setup), setup[4])).checkout
    current = asyncio.run(
        store.settle_checkout(initial, observation(initial, status=AnnualProviderStatus.UNKNOWN))
    )
    migration = "20260905083150_annual_billing_purchase_ledger.sql"
    for _ in range(2):
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            connection.execute((ROOT / "supabase" / "rollback" / "20260905145000_annual_refund_agreement_cleanup.sql").read_text())
            connection.execute((ROOT / "supabase" / "rollback" / "20260905141500_annual_refund_requests.sql").read_text())
            connection.execute((ROOT / "supabase" / "rollback" / "20260905115700_legacy_billing_acquisition_retirement.sql").read_text())
            connection.execute((ROOT / "supabase" / "rollback" / "20260905103149_annual_agreement_cleanup.sql").read_text())
            connection.execute(
                (
                    ROOT / "supabase" / "rollback" / "20260905100130_annual_renewal_cancellation.sql"
                ).read_text()
            )
            connection.execute((ROOT / "supabase" / "rollback" / migration).read_text())
            connection.execute((ROOT / "supabase" / "migrations" / migration).read_text())
            connection.execute(
                (
                    ROOT / "supabase" / "migrations" / "20260905100130_annual_renewal_cancellation.sql"
                ).read_text()
            )
            connection.execute((ROOT / "supabase" / "migrations" / "20260905103149_annual_agreement_cleanup.sql").read_text())
            connection.execute((ROOT / "supabase" / "migrations" / "20260905115700_legacy_billing_acquisition_retirement.sql").read_text())
            connection.execute((ROOT / "supabase" / "migrations" / "20260905141500_annual_refund_requests.sql").read_text())
            connection.execute((ROOT / "supabase" / "migrations" / "20260905145000_annual_refund_agreement_cleanup.sql").read_text())
            principal = connection.execute("select current_user").fetchone()[0]
            connection.execute(
                psycopg.sql.SQL("grant billing_store_owner to {}").format(psycopg.sql.Identifier(principal))
            )
        assert asyncio.run(store.load_checkout(initial.offer.company_id, initial.purchase_id)) == current


@pytest.mark.parametrize(
    "change", ["provider", "reference", "amount", "pre_intent_capture", "partial_confirmation"]
)
def test_invalid_provider_evidence_cannot_settle_database(setup, change):
    store = session(setup)
    initial = asyncio.run(store.claim_checkout(candidate(setup), setup[4])).checkout
    confirmed = observation(initial, status=AnnualProviderStatus.CONFIRMED, captured=149000)
    changes = {
        "provider": {"provider": "other-merchant"},
        "reference": {"charge_reference": "another-charge"},
        "amount": {"amount_minor": 150000},
        "pre_intent_capture": {
            "captured_at": Timestamp(initial.intent.created_at.value - timedelta(seconds=1))
        },
        "partial_confirmation": {"captured_minor": 1000},
    }[change]
    with pytest.raises(BillingError) as error:
        asyncio.run(store.settle_checkout(initial, replace(confirmed, **changes)))
    assert error.value.code == BillingErrorCode.INVALID_INPUT
    assert asyncio.run(store.load_checkout(initial.offer.company_id, initial.purchase_id)) == initial


def test_current_source_is_rechecked_after_waiting_for_eligibility_lock(setup):
    async def run():
        with (
            psycopg.connect(DATABASE_URL) as source,
            psycopg.connect(DATABASE_URL, autocommit=True) as monitor,
        ):
            source.execute(
                "select pg_advisory_xact_lock(hashtextextended('eligibility-recheck|' || %s::text, 187))",
                (setup[0]["admission"],),
            )
            task = asyncio.create_task(session(setup).claim_checkout(candidate(setup), setup[4]))
            for _ in range(100):
                waiting = monitor.execute(
                    "select count(*) from pg_stat_activity where %s=any(pg_blocking_pids(pid))",
                    (source.info.backend_pid,),
                ).fetchone()[0]
                if waiting:
                    break
                await asyncio.sleep(0.005)
            assert waiting and not task.done()
            insert(
                source,
                "public.company_eligibility_assessments",
                setup[0]["assessment"]
                | {
                    "id": uuid4(),
                    "operation_id": uuid4(),
                    "previous_assessment_id": setup[0]["current"],
                    "trigger": "material_answer_changed",
                    "assessed_at": datetime.now(UTC),
                    "decision": "blocked",
                    "consequential_operations_allowed": False,
                },
            )
            source.commit()
            with pytest.raises(BillingError) as error:
                await task
            assert error.value.code == BillingErrorCode.UNSUPPORTED_CASE

    asyncio.run(run())
    assert counts(setup) == (0, 0)


def test_http_checkout_and_recovery_share_the_real_stored_intent(setup):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from talli_backend.main import create_app

    store = session(setup)

    class Factory:
        async def session(self, token):
            assert token == "verified-fixture"
            return SimpleNamespace(actor_id=setup[1], checkout=store)

    class CapturedProvider(Provider):
        async def reconcile(self, intent):
            self.reconciliations.append(intent)
            return AnnualProviderObservation(
                self.provider, AnnualProviderOperation.CHECKOUT, AnnualProviderStatus.CONFIRMED,
                "agr-test", intent.charge_reference, 149000, captured_minor=149000,
                captured_at=intent.created_at,
            )

    async def source(company, year, actor):
        assert (company, year, actor) == (setup[2].company_id, IncomeYear(2026), setup[1])
        return setup[4]

    provider = CapturedProvider(setup)
    api = TestClient(create_app(annual_billing_session_factory=Factory(), annual_billing_provider=provider,
                                annual_checkout_prerequisites=source))
    headers = {"Authorization": "Bearer verified-fixture", "Idempotency-Key": str(setup[5].idempotency_key)}
    body = {"companyId": str(setup[2].company_id), "incomeYear": 2026,
            "offerVersion": setup[2].offer_version, "termsDigest": setup[2].terms_digest,
            "purchaseAccepted": True, "recurringConsent": True, "consentVersion": setup[2].offer_version}
    started = api.post("/api/v1/billing/annual/checkouts", headers=headers, json=body)
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "pending" and counts(setup) == (1, 1)
    observed = api.post("/api/v1/billing/annual/checkout-observations", headers=headers,
                        json={"companyId": body["companyId"], "purchaseId": started.json()["purchaseId"]})
    assert observed.status_code == 200, observed.text
    assert observed.json()["status"] == "paid" and observed.json()["capturedMinor"] == 149000
    replay = api.post("/api/v1/billing/annual/checkouts", headers=headers, json=body)
    assert replay.json() == observed.json()
    assert len(provider.executions) == len(provider.reconciliations) == 1
    assert counts(setup) == (1, 1)


def test_real_runtime_adapter_rejects_injected_readiness_without_source_verifier(setup):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from talli_backend.adapters.supabase_annual_billing import SupabaseAnnualBillingAdapter
    from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration
    from talli_backend.main import create_app

    verified = session(setup)._verified

    class AuthenticationFixture:
        async def session(self, token):
            assert token == "verified-fixture"
            return SimpleNamespace(_verified=verified)

    factory = SupabaseAnnualBillingAdapter(LedgerSupabaseConfiguration(
        url="http://127.0.0.1:1", anon_key="local-unused", database_url=DATABASE_URL,
    ))
    factory._authentication = AuthenticationFixture()
    provider = Provider(setup)

    async def source(company, year, actor):
        return setup[4]

    api = TestClient(create_app(annual_billing_session_factory=factory, annual_billing_provider=provider,
                                annual_checkout_prerequisites=source))
    response = api.post("/api/v1/billing/annual/checkouts",
        headers={"Authorization": "Bearer verified-fixture", "Idempotency-Key": str(setup[5].idempotency_key)},
        json={"companyId": str(setup[2].company_id), "incomeYear": 2026,
              "offerVersion": setup[2].offer_version, "termsDigest": setup[2].terms_digest,
              "purchaseAccepted": True, "recurringConsent": False, "consentVersion": setup[2].offer_version})
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "BILLING_FILING_NOT_READY"
    assert counts(setup) == (0, 0) and not provider.executions and not provider.reconciliations
