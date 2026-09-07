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
    original = asyncio.run(session(setup).find_checkout(setup[2].company_id, setup[5].idempotency_key, checkout_fingerprint(setup[5])))

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


def checkout_records(checkout):
    with psycopg.connect(DATABASE_URL) as connection:
        purchase = connection.execute(
            "select to_jsonb(p) from billing.annual_purchases p where id=%s", (str(checkout.purchase_id),)
        ).fetchone()[0]
        operation = connection.execute(
            "select to_jsonb(o) from billing.annual_operations o where id=%s", (str(checkout.intent.operation_id),)
        ).fetchone()[0]
    return purchase, operation


def interleave_checkout_sql(store, execute, support_case=None):
    """Observe real SQL under this store's existing transaction and RLS."""
    transaction = store._transaction

    class Connection:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        async def execute(self, query, *args, **kwargs):
            return await execute(self.wrapped, query, *args, **kwargs)

    async def interleaved(work):
        async def wrapped(connection):
            if support_case is not None:
                await connection.execute("select set_config('talli.support_case_id', %s, true)", (str(support_case),))
            return await work(Connection(connection))
        return await transaction(wrapped)

    store._transaction = interleaved


@pytest.mark.parametrize("mode", ["owner", "mfa"])
@pytest.mark.parametrize("point", ["before_purchase", "between_updates", "after_operation"])
@pytest.mark.parametrize("opened_support", [False, True])
def test_checkout_late_authority_loss_cannot_commit_settlement(setup, mode, point, opened_support):
    store = session(setup)
    original = asyncio.run(store.claim_checkout(candidate(setup), setup[4])).checkout
    confirmed = observation(original, captured=149000, status=AnnualProviderStatus.CONFIRMED)
    before = checkout_records(original)
    support_case = None
    if opened_support:
        from test_annual_support_runtime import support
        owner_as_operator = (setup[0] | {"outsider": setup[0]["owner"]},) + setup[1:]
        support_case = support(owner_as_operator).support_case_id
    if mode == "mfa":
        claims = json.loads(store._verified.claims_json)
        claims["amr"][0]["timestamp"] = datetime.now(UTC).timestamp() - 899.5
        store._verified = _VerifiedActor(setup[1], json.dumps(claims))
    rows = []
    revoked = []

    async def revoke():
        assert not revoked
        if mode == "mfa":
            await asyncio.sleep(.65)
        else:
            with psycopg.connect(DATABASE_URL) as revoker:
                revoker.execute("update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s",
                                (str(original.offer.company_id), str(setup[1].subject)))
        revoked.append(True)

    async def execute(connection, query, *args, **kwargs):
        purchase_write = str(query).strip().lower().startswith("update billing.annual_purchases")
        operation_write = str(query).strip().lower().startswith("update billing.annual_operations")
        if purchase_write:
            assert (await (await connection.execute("select current_setting('talli.support_case_id', true) as support_case")).fetchone())["support_case"] == ""
        if purchase_write and point == "before_purchase":
            await revoke()
        result = await connection.execute(query, *args, **kwargs)
        if purchase_write or operation_write:
            rows.append(result.rowcount)
        if (purchase_write and point == "between_updates") or (operation_write and point == "after_operation"):
            await revoke()
        return result

    interleave_checkout_sql(store, execute, support_case)
    try:
        outcome = asyncio.run(store.settle_checkout(original, confirmed))
    except BillingError as error:
        outcome = error
    assert rows == {"before_purchase": [0], "between_updates": [1, 0], "after_operation": [1, 1]}[point]
    assert isinstance(outcome, BillingError), (
        f"Unauthorized checkout confirmation returned; real operation write rows={rows}; "
        f"persisted state changed={checkout_records(original) != before}"
    )
    assert outcome.code is (BillingErrorCode.FORBIDDEN if mode == "owner" else BillingErrorCode.STEP_UP_REQUIRED)
    assert revoked == [True]
    assert checkout_records(original) == before


@pytest.mark.parametrize("phase", ["load_pending", "load_terminal", "settle_pending", "settle_terminal"])
@pytest.mark.parametrize("mode", ["owner", "mfa"])
@pytest.mark.parametrize("locked", ["purchase", "operation"])
def test_checkout_operation_lock_wait_rechecks_current_authority(setup, phase, mode, locked):
    store = session(setup)
    original = asyncio.run(store.claim_checkout(candidate(setup), setup[4])).checkout
    confirmed = observation(original, captured=149000, status=AnnualProviderStatus.CONFIRMED)
    if phase.endswith("terminal"):
        asyncio.run(store.settle_checkout(original, confirmed))
    before = checkout_records(original)

    async def run():
        if mode == "mfa":
            claims = json.loads(store._verified.claims_json)
            claims["amr"][0]["timestamp"] = datetime.now(UTC).timestamp() - 899.5
            store._verified = _VerifiedActor(setup[1], json.dumps(claims))
        with psycopg.connect(DATABASE_URL) as holder, psycopg.connect(DATABASE_URL, autocommit=True) as monitor:
            if locked == "purchase":
                holder.execute("select id from billing.annual_purchases where id=%s for update", (str(original.purchase_id),))
            else:
                holder.execute("select id from billing.annual_operations where id=%s for update", (str(original.intent.operation_id),))
            work = (store.load_checkout(original.offer.company_id, original.purchase_id)
                    if phase.startswith("load") else store.settle_checkout(original, confirmed))
            pending = asyncio.create_task(work)
            try:
                waiting = 0
                for _ in range(200):
                    waiting = monitor.execute(
                        "select count(*) from pg_stat_activity where %s=any(pg_blocking_pids(pid))",
                        (holder.info.backend_pid,),
                    ).fetchone()[0]
                    if waiting:
                        break
                    await asyncio.sleep(.005)
                assert waiting and not pending.done(), "Must observe an actual independent SQL lock wait"
                if mode == "mfa":
                    await asyncio.sleep(.65)
                else:
                    monitor.execute("update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s",
                                    (str(original.offer.company_id), str(setup[1].subject)))
            finally:
                holder.rollback()
            with pytest.raises(BillingError) as denied:
                await asyncio.wait_for(pending, 4)
            assert denied.value.code is (BillingErrorCode.FORBIDDEN if mode == "owner" else BillingErrorCode.STEP_UP_REQUIRED)

    asyncio.run(run())
    assert checkout_records(original) == before


@pytest.mark.parametrize("fault", ["miss_purchase", "miss_operation", "sql_before_purchase", "sql_after_purchase", "sql_after_operation"])
def test_checkout_missed_writes_and_aborted_sql_roll_back_complete_settlement(setup, fault):
    store = session(setup)
    original = asyncio.run(store.claim_checkout(candidate(setup), setup[4])).checkout
    confirmed = observation(original, captured=149000, status=AnnualProviderStatus.CONFIRMED)
    before = checkout_records(original)
    rows, aborted, after_abort = [], [], []

    async def fail_sql(connection):
        try:
            await connection.execute("select 1 / 0")
        except psycopg.DatabaseError:
            assert connection.info.transaction_status is psycopg.pq.TransactionStatus.INERROR
            aborted.append(True)
            raise

    async def execute(connection, query, *args, **kwargs):
        if aborted:
            after_abort.append(str(query))
        purchase_write = str(query).strip().lower().startswith("update billing.annual_purchases")
        operation_write = str(query).strip().lower().startswith("update billing.annual_operations")
        if purchase_write and fault == "sql_before_purchase":
            await fail_sql(connection)
        miss = (purchase_write and fault == "miss_purchase") or (operation_write and fault == "miss_operation")
        # Execute an actual missed UPDATE with intact authority and inspect its cursor.
        result = await connection.execute(query + " and false" if miss else query, *args, **kwargs)
        if purchase_write or operation_write:
            rows.append(result.rowcount)
        if (purchase_write and fault == "sql_after_purchase") or (operation_write and fault == "sql_after_operation"):
            await fail_sql(connection)
        return result

    interleave_checkout_sql(store, execute)
    with pytest.raises(BillingError) as denied:
        asyncio.run(store.settle_checkout(original, confirmed))
    assert denied.value.code is BillingErrorCode.DEPENDENCY_UNAVAILABLE
    assert rows == {"miss_purchase": [0], "miss_operation": [1, 0], "sql_before_purchase": [],
                    "sql_after_purchase": [1], "sql_after_operation": [1, 1]}[fault]
    assert aborted == ([True] if fault.startswith("sql_") else [])
    assert not after_abort
    assert checkout_records(original) == before
    assert asyncio.run(session(setup).settle_checkout(original, confirmed)).status is AnnualPurchaseStatus.PAID


@pytest.mark.parametrize("actor", ["original_owner", "another_owner"])
def test_current_owner_can_load_and_replay_confirmed_checkout_without_current_readiness(setup, actor):
    store = session(setup)
    original = asyncio.run(store.claim_checkout(candidate(setup), setup[4])).checkout
    confirmed = observation(original, captured=149000, status=AnnualProviderStatus.CONFIRMED)
    terminal = asyncio.run(store.settle_checkout(original, confirmed))
    who = setup[1]
    if actor == "another_owner":
        who = ActorId(ActorKind.USER, UserId(str(setup[0]["outsider"])))
        with psycopg.connect(DATABASE_URL) as connection:
            insert(connection, "public.company_memberships", {
                "company_id": str(original.offer.company_id), "user_id": str(who.subject),
                "role": "owner", "accepted_at": datetime.now(UTC),
            })
    recovered = session(setup, actor=who, current=False)
    before = checkout_records(original)
    assert asyncio.run(recovered.load_checkout(original.offer.company_id, original.purchase_id)) == terminal
    assert asyncio.run(recovered.settle_checkout(original, confirmed)) == terminal
    assert checkout_records(original) == before


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
    assert asyncio.run(session(other).find_checkout(other[2].company_id, initial.idempotency_key, initial.request_fingerprint)) is None
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
            connection.execute((ROOT / "supabase" / "rollback" / "20260906221800_annual_checkout_withdrawals.sql").read_text())
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
            connection.execute((ROOT / "supabase" / "migrations" / "20260906221800_annual_checkout_withdrawals.sql").read_text())
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


@pytest.mark.parametrize("operation", ["start", "prepare"])
def test_real_runtime_adapter_rejects_injected_readiness_without_source_verifier(setup, operation):
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
    if operation == "start":
        response = api.post("/api/v1/billing/annual/checkouts",
            headers={"Authorization": "Bearer verified-fixture", "Idempotency-Key": str(setup[5].idempotency_key)},
            json={"companyId": str(setup[2].company_id), "incomeYear": 2026,
                  "offerVersion": setup[2].offer_version, "termsDigest": setup[2].terms_digest,
                  "purchaseAccepted": True, "recurringConsent": False, "consentVersion": setup[2].offer_version})
    else:
        response = api.get("/api/v1/billing/annual/checkout-preparation",
            headers={"Authorization": "Bearer verified-fixture"},
            params={"company_id": str(setup[2].company_id), "income_year": 2026})
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "BILLING_FILING_NOT_READY"
    assert counts(setup) == (0, 0) and not provider.executions and not provider.reconciliations


def preparation_query(setup):
    from talli_backend.modules.billing.public import AnnualCheckoutPreparationQuery
    return AnnualCheckoutPreparationQuery(setup[2].company_id, setup[2].income_year, setup[1])


def preparation_service(setup, store=None, provider=None):
    return AnnualCheckoutService(store or session(setup), provider or Provider(setup),
        return_url='https://example.test/return', management_url='https://example.test/manage')


def test_preparation_reads_current_basis_without_purchase_operation_or_provider_effect(setup):
    async def run():
        store, provider = session(setup), Provider(setup)
        async def source():
            return setup[4]
        result = await preparation_service(setup, store, provider).prepare_checkout(preparation_query(setup), source)
        assert result.offer == setup[2] and result.existing_purchase is None
        assert result.consent_version == setup[5].consent_version
        assert counts(setup) == (0, 0)
        assert not provider.executions and not provider.reconciliations
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['default', 'false', 'wrong_company', 'wrong_year', 'wrong_assessment', 'wrong_legal', 'wrong_admission', 'wrong_promise', 'wrong_manifest', 'stale', 'future', 'not_ready', 'owner', 'mfa'])
def test_preparation_database_denies_untrusted_basis_and_empty_unauthorized_results(setup, mode):
    async def run():
        store = session(setup, current=mode != 'false', fresh=mode != 'mfa',
                        actor=ActorId(ActorKind.USER, UserId(str(setup[0]['outsider']))) if mode == 'owner' else None)
        if mode == 'default':
            store = PostgresAnnualCheckoutSession(DATABASE_URL, store._verified)
        evidence = setup[4]
        if mode.startswith('wrong_'):
            field = {'wrong_company': 'company_id', 'wrong_year': 'income_year', 'wrong_assessment': 'assessment_id',
                     'wrong_legal': 'legal_acceptance_id', 'wrong_admission': 'admission_id',
                     'wrong_promise': 'promise_digest', 'wrong_manifest': 'manifest_digest'}[mode]
            value = (CompanyId(str(uuid4())) if field == 'company_id' else IncomeYear(2027) if field == 'income_year'
                     else '0'*64 if field.endswith('digest') else str(uuid4()))
            evidence = replace(evidence, basis=replace(evidence.basis, **{field: value}))
        if mode in ('stale', 'future'):
            evidence = replace(evidence, evaluated_at=Timestamp(datetime.now(UTC) + timedelta(seconds=-301 if mode == 'stale' else 10)))
        if mode == 'not_ready':
            evidence = replace(evidence, ready=False)
        with pytest.raises(BillingError):
            await store.verify_checkout_preparation(setup[2].company_id, setup[2].income_year, evidence)
        if mode in ('owner', 'mfa'):
            with pytest.raises(BillingError):
                await store.find_active_checkout(setup[2].company_id, setup[2].income_year)
        assert counts(setup) == (0, 0)
    asyncio.run(run())


@pytest.mark.parametrize('status', [AnnualPurchaseStatus.PENDING, AnnualPurchaseStatus.PAID])
def test_preparation_existing_purchase_is_available_without_provider_or_new_source(setup, status):
    async def run():
        store = session(setup)
        saved = (await store.claim_checkout(candidate(setup), setup[4])).checkout
        if status is AnnualPurchaseStatus.PAID:
            saved = await store.settle_checkout(saved, observation(saved, status=AnnualProviderStatus.CONFIRMED,
                captured=149000, captured_at=saved.intent.created_at))
        before = await store.load_checkout(saved.offer.company_id, saved.purchase_id)
        unavailable = PostgresAnnualCheckoutSession(DATABASE_URL, store._verified)
        service = AnnualCheckoutService(unavailable, None, return_url='https://example.test', management_url='https://example.test')
        async def source():
            pytest.fail('Existing purchase resolved new-sale readiness')
        result = await service.prepare_checkout(preparation_query(setup), source)
        assert result.existing_purchase.purchase_id == saved.purchase_id
        assert result.existing_purchase.status is status
        assert result.offer is None and result.consent_version is None
        assert await store.load_checkout(saved.offer.company_id, saved.purchase_id) == before
        assert counts(setup) == (1, 1)
    asyncio.run(run())


def test_preparation_occupancy_race_returns_winner_without_calling_verifier(setup):
    async def run():
        async def verifier(evidence):
            pytest.fail('Occupied preparation invoked new-sale verifier')
        store = PostgresAnnualCheckoutSession(DATABASE_URL, session(setup)._verified, readiness_is_current=verifier)
        provider = Provider(setup)
        winner = None
        async def source():
            nonlocal winner
            winner = (await session(setup).claim_checkout(candidate(setup), setup[4])).checkout
            return setup[4]
        result = await preparation_service(setup, store, provider).prepare_checkout(preparation_query(setup), source)
        assert result.existing_purchase.purchase_id == winner.purchase_id
        assert counts(setup) == (1, 1)
        assert not provider.executions and not provider.reconciliations
    asyncio.run(run())


@pytest.mark.parametrize('change', ['owner', 'legal'])
def test_preparation_rechecks_authority_and_exact_legal_basis_after_verifier_await(setup, change):
    from test_annual_purchase_basis_runtime import legal_fields
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def verifier(evidence):
            entered.set()
            await release.wait()
            return True
        store = PostgresAnnualCheckoutSession(DATABASE_URL, session(setup)._verified, readiness_is_current=verifier)
        task = asyncio.create_task(store.verify_checkout_preparation(setup[2].company_id, setup[2].income_year, setup[4]))
        await asyncio.wait_for(entered.wait(), 3)
        try:
            with psycopg.connect(DATABASE_URL) as connection:
                if change == 'owner':
                    connection.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',
                                       (setup[0]['company'], setup[0]['owner']))
                else:
                    insert(connection, 'public.customer_agreement_acceptances', setup[0]['acceptance_fields'] | legal_fields() |
                           {'id': uuid4(), 'accepted_at': datetime.now(UTC)})
        finally:
            release.set()
        with pytest.raises(BillingError) as error:
            await task
        assert error.value.code in {BillingErrorCode.FORBIDDEN, BillingErrorCode.UNSUPPORTED_CASE}
        assert counts(setup) == (0, 0)
    asyncio.run(run())


@pytest.mark.parametrize('lock_kind', ['company_year', 'eligibility'])
def test_preparation_rechecks_owner_after_actual_database_lock_wait(setup, lock_kind):
    async def run():
        with psycopg.connect(DATABASE_URL) as holder, psycopg.connect(DATABASE_URL, autocommit=True) as monitor:
            if lock_kind == 'company_year':
                holder.execute('select pg_advisory_xact_lock(hashtextextended(%s,192))',
                               (f'annual-checkout|{setup[2].company_id}|2026',))
            else:
                holder.execute("select pg_advisory_xact_lock(hashtextextended('eligibility-recheck|' || %s::text,187))",
                               (setup[0]['admission'],))
            task = asyncio.create_task(session(setup).verify_checkout_preparation(setup[2].company_id, setup[2].income_year, setup[4]))
            waiting = False
            try:
                for _ in range(100):
                    waiting = monitor.execute('select count(*) from pg_stat_activity where %s=any(pg_blocking_pids(pid))',
                                              (holder.info.backend_pid,)).fetchone()[0]
                    if waiting:
                        break
                    await asyncio.sleep(0.005)
                assert waiting and not task.done()
                monitor.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',
                                (setup[0]['company'], setup[0]['owner']))
            finally:
                holder.commit()
            with pytest.raises(BillingError) as error:
                await task
            assert error.value.code is BillingErrorCode.FORBIDDEN
            assert counts(setup) == (0, 0)
    asyncio.run(run())


def test_claim_persists_separate_consent_version(setup, monkeypatch):
    monkeypatch.setattr('talli_backend.modules.billing.annual_policy.ANNUAL_CONSENT_VERSION', 'independent-consent-v2')
    async def run():
        store, provider = session(setup), Provider(setup)
        async def source():
            return setup[4]
        accepted = replace(setup[5], consent_version='independent-consent-v2')
        saved = await preparation_service(setup, store, provider).start_checkout(accepted, source)
        with psycopg.connect(DATABASE_URL) as connection:
            row = connection.execute('select offer_version, consent_version from billing.annual_purchases where id=%s',
                                     (str(saved.purchase_id),)).fetchone()
        assert row == (setup[2].offer_version, 'independent-consent-v2')
    asyncio.run(run())


@pytest.mark.parametrize('admitted', [timedelta(seconds=-296)], indirect=True)
def test_preparation_rechecks_assessment_expiry_after_verifier_wait(setup):
    async def run():
        entered = False
        async def verifier(evidence):
            nonlocal entered
            entered = True
            await asyncio.sleep(4.1)
            return True
        store = PostgresAnnualCheckoutSession(DATABASE_URL, session(setup)._verified, readiness_is_current=verifier)
        with pytest.raises(BillingError) as error:
            await store.verify_checkout_preparation(setup[2].company_id, setup[2].income_year, setup[4])
        assert entered
        assert error.value.code is BillingErrorCode.UNSUPPORTED_CASE
        assert counts(setup) == (0, 0)
    asyncio.run(run())


def test_preparation_rechecks_fresh_mfa_after_verifier_wait(setup):
    async def run():
        entered = False
        async def verifier(evidence):
            nonlocal entered
            entered = True
            await asyncio.sleep(2.2)
            return True
        verified = _VerifiedActor(setup[1], json.dumps({'sub': str(setup[1].subject), 'aal': 'aal2',
            'amr': [{'method': 'totp', 'timestamp': datetime.now(UTC).timestamp() - 898}]}))
        store = PostgresAnnualCheckoutSession(DATABASE_URL, verified, readiness_is_current=verifier)
        with pytest.raises(BillingError) as error:
            await store.verify_checkout_preparation(setup[2].company_id, setup[2].income_year, setup[4])
        assert entered
        assert error.value.code is BillingErrorCode.STEP_UP_REQUIRED
        assert counts(setup) == (0, 0)
    asyncio.run(run())
