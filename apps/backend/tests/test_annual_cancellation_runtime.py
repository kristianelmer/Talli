"""Durable local renewal-stop evidence, without any provider execution."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import json
from uuid import uuid4

import psycopg
import pytest

from test_annual_purchase_basis_runtime import (
    DATABASE_URL,
    ROOT,
    admitted,
    insert,
    scoped,
    test_role_authority,
)
from test_annual_checkout_runtime import (
    setup, session, candidate, observation, counts,
    checkout_company_records, interleave_checkout_sql,
)
from talli_backend.adapters.postgres_annual_checkout import PostgresAnnualCancellationSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.billing.public import (
    AnnualPurchaseStatus,
    AnnualProviderStatus,
    AnnualPurchaseId,
    BillingError,
    BillingErrorCode,
    CancelAnnualRenewalCommand,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IdempotencyKey, UserId


pytestmark = pytest.mark.billing_database


@pytest.fixture
def purchase(setup):
    return asyncio.run(session(setup).claim_checkout(candidate(setup), setup[4])).checkout


def command(setup, purchase, **changes):
    original = setup[5]
    return replace(
        CancelAnnualRenewalCommand(
            company_id=original.company_id,
            actor_id=original.actor_id,
            correlation_id=original.correlation_id,
            idempotency_key=IdempotencyKey(str(uuid4())),
            purchase_id=purchase.purchase_id,
        ),
        **changes,
    )


def cancellation(setup, **kwargs):
    return PostgresAnnualCancellationSession(session(setup, **kwargs))


def receipts(setup):
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        return connection.execute(
            "select count(*) from billing.annual_cancellation_requests where company_id=%s",
            (str(setup[2].company_id),),
        ).fetchone()[0]


def cancellation_records(setup):
    """Read full fixture evidence even after the requesting owner is revoked."""
    with psycopg.connect(DATABASE_URL) as connection:
        requests = connection.execute(
            """select coalesce(jsonb_agg(to_jsonb(r) order by r.id), '[]'::jsonb)
               from billing.annual_cancellation_requests r where company_id=%s""",
            (str(setup[2].company_id),),
        ).fetchone()[0]
    return checkout_company_records(setup), requests


@pytest.mark.parametrize("phase", ["new", "replay", "later_key"])
@pytest.mark.parametrize("mode", ["owner", "mfa"])
@pytest.mark.parametrize("opened_support", [False, True])
def test_cancellation_final_result_requires_current_authority(setup, purchase, phase, mode, opened_support):
    request = command(setup, purchase)
    if phase != "new":
        asyncio.run(cancellation(setup).cancel_renewal(request))
    if phase == "later_key":
        request = command(setup, purchase)
    before = cancellation_records(setup)
    store = session(setup, current=False)
    support_case = None
    if opened_support:
        from test_annual_support_runtime import support
        owner_as_operator = (setup[0] | {"outsider": setup[0]["owner"]},) + setup[1:]
        support_case = support(owner_as_operator).support_case_id
    if mode == "mfa":
        claims = json.loads(store._verified.claims_json)
        claims["amr"][0]["timestamp"] = datetime.now(UTC).timestamp() - 899.5
        store._verified = _VerifiedActor(setup[1], json.dumps(claims))
    revoked, inserted = [], []

    async def execute(connection, query, *args, **kwargs):
        result = await connection.execute(query, *args, **kwargs)
        statement = str(query).strip().lower()
        insert_request = statement.startswith("insert into billing.annual_cancellation_requests")
        if insert_request:
            inserted.append(result.rowcount)
        final_result = (statement.startswith("select r.*,p.paid_through")
                        if phase == "replay" else insert_request)
        if final_result:
            assert not revoked
            if opened_support:
                assert (await (await connection.execute(
                    "select current_setting('talli.support_case_id', true) as support_case"
                )).fetchone())["support_case"] == ""
            if mode == "mfa":
                await asyncio.sleep(.65)
            else:
                with psycopg.connect(DATABASE_URL) as revoker:
                    revoker.execute(
                        "update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s",
                        (str(request.company_id), str(setup[1].subject)),
                    )
            revoked.append(True)
        return result

    interleave_checkout_sql(store, execute, support_case)
    try:
        outcome = asyncio.run(PostgresAnnualCancellationSession(store).cancel_renewal(request))
    except BillingError as error:
        outcome = error
    assert revoked == [True]
    assert inserted == ([] if phase == "replay" else [1])
    assert isinstance(outcome, BillingError), (
        f"Unauthorized {phase} cancellation returned; inserted rows={inserted}; "
        f"receipt or renewal state changed={cancellation_records(setup) != before}"
    )
    assert outcome.code is (BillingErrorCode.FORBIDDEN if mode == "owner" else BillingErrorCode.STEP_UP_REQUIRED)
    assert cancellation_records(setup) == before


@pytest.mark.parametrize("phase,locked", [
    ("new", "key"), ("replay", "key"), ("new", "purchase"), ("later_key", "purchase"),
])
@pytest.mark.parametrize("mode", ["owner", "mfa"])
def test_cancellation_lock_wait_rechecks_current_authority(setup, purchase, phase, locked, mode):
    request = command(setup, purchase)
    if phase != "new":
        asyncio.run(cancellation(setup).cancel_renewal(request))
    if phase == "later_key":
        request = command(setup, purchase)
    before = cancellation_records(setup)
    store = session(setup, current=False)

    async def run():
        if mode == "mfa":
            claims = json.loads(store._verified.claims_json)
            claims["amr"][0]["timestamp"] = datetime.now(UTC).timestamp() - 899.5
            store._verified = _VerifiedActor(setup[1], json.dumps(claims))
        with psycopg.connect(DATABASE_URL) as holder, psycopg.connect(DATABASE_URL, autocommit=True) as monitor:
            if locked == "key":
                holder.execute("select pg_advisory_xact_lock(hashtextextended(%s, 192))",
                               (f"annual-cancellation-key|{request.idempotency_key}",))
            else:
                holder.execute("select id from billing.annual_purchases where id=%s for update",
                               (str(purchase.purchase_id),))
            pending = asyncio.create_task(PostgresAnnualCancellationSession(store).cancel_renewal(request))
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
                    monitor.execute(
                        "update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s",
                        (str(request.company_id), str(setup[1].subject)),
                    )
            finally:
                holder.rollback()
            with pytest.raises(BillingError) as denied:
                await asyncio.wait_for(pending, 4)
            assert denied.value.code is (BillingErrorCode.FORBIDDEN if mode == "owner" else BillingErrorCode.STEP_UP_REQUIRED)

    asyncio.run(run())
    assert cancellation_records(setup) == before


@pytest.mark.parametrize("fault", ["no_insert", "sql_before_insert", "sql_after_insert"])
def test_cancellation_missing_insert_and_sql_abort_roll_back_both_records(setup, purchase, fault):
    store = session(setup)
    request = command(setup, purchase)
    before = cancellation_records(setup)
    inserted, aborted, after_abort = [], [], []

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
        insert_request = str(query).strip().lower().startswith("insert into billing.annual_cancellation_requests")
        if insert_request and fault == "sql_before_insert":
            await fail_sql(connection)
        if insert_request and fault == "no_insert":
            # A real zero-row INSERT under the unchanged request role and RLS.
            query = query.replace("values (gen_random_uuid(),", "select gen_random_uuid(),").replace(
                "%s,%s) returning *", "%s,%s where false returning *"
            )
        result = await connection.execute(query, *args, **kwargs)
        if insert_request:
            inserted.append(result.rowcount)
            if fault == "sql_after_insert":
                await fail_sql(connection)
        return result

    interleave_checkout_sql(store, execute)
    with pytest.raises(BillingError) as denied:
        asyncio.run(PostgresAnnualCancellationSession(store).cancel_renewal(request))
    assert denied.value.code is BillingErrorCode.DEPENDENCY_UNAVAILABLE
    assert inserted == {"no_insert": [0], "sql_before_insert": [], "sql_after_insert": [1]}[fault]
    assert aborted == ([] if fault == "no_insert" else [True])
    assert not after_abort
    assert cancellation_records(setup) == before
    result = asyncio.run(cancellation(setup).cancel_renewal(request))
    assert result.effective_at == asyncio.run(session(setup).load_checkout(
        purchase.offer.company_id, purchase.purchase_id
    )).renewal_canceled_at


@pytest.mark.parametrize("mode", ["owner", "mfa"])
def test_cancellation_loss_after_purchase_read_denies_before_insert(setup, purchase, mode):
    store = session(setup)
    request = command(setup, purchase)
    before = cancellation_records(setup)
    if mode == "mfa":
        claims = json.loads(store._verified.claims_json)
        claims["amr"][0]["timestamp"] = datetime.now(UTC).timestamp() - 899.5
        store._verified = _VerifiedActor(setup[1], json.dumps(claims))
    revoked, inserted = [], []

    async def execute(connection, query, *args, **kwargs):
        result = await connection.execute(query, *args, **kwargs)
        statement = str(query).strip().lower()
        if statement.startswith("insert into billing.annual_cancellation_requests"):
            inserted.append(result.rowcount)
        if statement.startswith("select id,income_year,paid_through,export_through"):
            assert not revoked
            if mode == "mfa":
                await asyncio.sleep(.65)
            else:
                with psycopg.connect(DATABASE_URL) as revoker:
                    revoker.execute(
                        "update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s",
                        (str(request.company_id), str(setup[1].subject)),
                    )
            revoked.append(True)
        return result

    interleave_checkout_sql(store, execute)
    with pytest.raises(BillingError) as denied:
        asyncio.run(PostgresAnnualCancellationSession(store).cancel_renewal(request))
    assert denied.value.code is (BillingErrorCode.FORBIDDEN if mode == "owner" else BillingErrorCode.STEP_UP_REQUIRED)
    assert revoked == [True] and not inserted
    assert cancellation_records(setup) == before


def test_current_owners_preserve_receipt_identity_and_original_stop_without_readiness(setup, purchase):
    first = command(setup, purchase)
    original = asyncio.run(cancellation(setup, current=False).cancel_renewal(first))
    before = cancellation_records(setup)
    assert asyncio.run(cancellation(setup, current=False).cancel_renewal(first)) == original
    assert cancellation_records(setup) == before
    other = ActorId(ActorKind.USER, UserId(str(setup[0]["outsider"])))
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection, "public.company_memberships", {
            "company_id": str(first.company_id), "user_id": str(other.subject),
            "role": "owner", "accepted_at": datetime.now(UTC),
        })
    store = cancellation(setup, actor=other, current=False)
    with pytest.raises(BillingError) as conflict:
        asyncio.run(store.cancel_renewal(replace(first, actor_id=other)))
    assert conflict.value.code is BillingErrorCode.IDEMPOTENCY_KEY_REUSED
    assert cancellation_records(setup) == before
    later = asyncio.run(store.cancel_renewal(command(setup, purchase, actor_id=other)))
    after = cancellation_records(setup)
    assert later.cancellation_id != original.cancellation_id
    assert later.requested_by == other.subject and original.requested_by == setup[1].subject
    assert later.requested_at.value > original.requested_at.value
    assert later.effective_at == original.effective_at
    assert (later.paid_through, later.export_through) == (original.paid_through, original.export_through)
    assert after[0] == before[0], "Later requests must not rewrite the original stop or purchase/operation evidence"
    assert len(after[1]) == 2 and all(receipt in after[1] for receipt in before[1])


@pytest.mark.parametrize("state", ["pending", "paid", "refunded", "failed"])
def test_local_cancellation_preserves_consent_money_status_and_access(setup, purchase, state):
    store = session(setup)
    if state != "pending":
        captured = 149000 if state in {"paid", "refunded"} else 0
        purchase = asyncio.run(
            store.settle_checkout(
                purchase,
                observation(
                    purchase,
                    captured=captured,
                    refunded=149000 if state == "refunded" else 0,
                    status=AnnualProviderStatus.FAILED
                    if state == "failed"
                    else AnnualProviderStatus.CONFIRMED,
                ),
            )
        )
    result = asyncio.run(cancellation(setup, current=False).cancel_renewal(command(setup, purchase)))
    after = asyncio.run(store.load_checkout(purchase.offer.company_id, purchase.purchase_id))
    assert after == replace(purchase, renewal_canceled_at=result.effective_at)
    assert (
        result.paid_through == purchase.offer.paid_through
        and result.export_through == purchase.offer.export_through
    )
    assert receipts(setup) == 1 and counts(setup) == (1, 1)


def test_identical_concurrent_requests_have_one_immutable_receipt(setup, purchase):
    request = command(setup, purchase)

    async def run():
        return await asyncio.gather(*(cancellation(setup).cancel_renewal(request) for _ in range(2)))

    results = asyncio.run(run())
    assert results[0] == results[1] and receipts(setup) == 1
    assert counts(setup) == (1, 1), "Local cancellation never invents a provider operation"


def test_distinct_request_keys_preserve_original_effective_time(setup, purchase):
    async def run():
        return await asyncio.gather(
            *(cancellation(setup).cancel_renewal(command(setup, purchase)) for _ in range(2))
        )

    results = asyncio.run(run())
    assert results[0].cancellation_id != results[1].cancellation_id
    assert results[0].effective_at == results[1].effective_at and receipts(setup) == 2


def test_lost_cancellation_response_recovers_committed_request(setup, purchase):
    class LostResponse(PostgresAnnualCancellationSession):
        async def cancel_renewal(self, request):
            await super().cancel_renewal(request)
            raise BillingError.unavailable()

    request = command(setup, purchase)
    with pytest.raises(BillingError):
        asyncio.run(LostResponse(session(setup)).cancel_renewal(request))
    current = asyncio.run(session(setup).load_checkout(purchase.offer.company_id, purchase.purchase_id))
    assert current.renewal_canceled_at is not None
    result = asyncio.run(cancellation(setup, current=False).cancel_renewal(request))
    assert result.effective_at == current.renewal_canceled_at and receipts(setup) == 1


@pytest.mark.parametrize(
    "mode", ["outsider", "stale_mfa", "actor_mismatch", "wrong_purchase", "wrong_company"]
)
def test_request_authority_and_scope_fail_without_mutation(setup, purchase, mode):
    request = command(setup, purchase)
    options = {}
    outsider = ActorId(ActorKind.USER, UserId(str(setup[0]["outsider"])))
    if mode == "outsider":
        options["actor"] = outsider
        request = replace(request, actor_id=outsider)
    elif mode == "stale_mfa":
        options["fresh"] = False
    elif mode == "actor_mismatch":
        request = replace(request, actor_id=outsider)
    elif mode == "wrong_purchase":
        request = replace(request, purchase_id=AnnualPurchaseId(str(uuid4())))
    elif mode == "wrong_company":
        request = replace(request, company_id=CompanyId(str(uuid4())))
    with pytest.raises(BillingError):
        asyncio.run(cancellation(setup, **options).cancel_renewal(request))
    assert receipts(setup) == 0
    assert (
        asyncio.run(session(setup).load_checkout(purchase.offer.company_id, purchase.purchase_id)) == purchase
    )


def test_later_eligibility_block_does_not_obstruct_cancellation(setup, purchase):
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
    result = asyncio.run(cancellation(setup, current=False).cancel_renewal(command(setup, purchase)))
    assert result.effective_at is not None
    assert (
        asyncio.run(session(setup).load_checkout(purchase.offer.company_id, purchase.purchase_id)).status
        == AnnualPurchaseStatus.PENDING
    )


def test_cross_tenant_key_collision_rolls_back_attempted_cancellation(setup, purchase, request):
    other = globals()["setup"].__wrapped__(admitted.__wrapped__(request))
    other_purchase = asyncio.run(session(other).claim_checkout(candidate(other), other[4])).checkout
    first = command(setup, purchase)
    asyncio.run(cancellation(setup).cancel_renewal(first))
    with pytest.raises(BillingError) as error:
        asyncio.run(
            cancellation(other).cancel_renewal(
                command(other, other_purchase, idempotency_key=first.idempotency_key)
            )
        )
    assert error.value.code == BillingErrorCode.IDEMPOTENCY_KEY_REUSED
    assert receipts(other) == 0
    assert (
        asyncio.run(session(other).load_checkout(other_purchase.offer.company_id, other_purchase.purchase_id))
        == other_purchase
    )


def test_same_key_cannot_be_reused_for_another_purchase(setup, purchase):
    first = command(setup, purchase)
    asyncio.run(cancellation(setup).cancel_renewal(first))
    asyncio.run(
        session(setup).settle_checkout(purchase, observation(purchase, status=AnnualProviderStatus.FAILED))
    )
    other = asyncio.run(
        session(setup).claim_checkout(candidate(setup, key=IdempotencyKey(str(uuid4()))), setup[4])
    ).checkout
    with pytest.raises(BillingError) as error:
        asyncio.run(cancellation(setup).cancel_renewal(replace(first, purchase_id=other.purchase_id)))
    assert error.value.code == BillingErrorCode.IDEMPOTENCY_KEY_REUSED
    assert asyncio.run(session(setup).load_checkout(other.offer.company_id, other.purchase_id)) == other


def test_failed_request_insert_rolls_back_local_stop(setup, purchase, monkeypatch):
    original_execute = psycopg.AsyncConnection.execute

    async def fail_return(connection, query, *args, **kwargs):
        result = await original_execute(connection, query, *args, **kwargs)
        if isinstance(query, str) and "insert into billing.annual_cancellation_requests" in query:
            raise psycopg.OperationalError("fixture cancellation insert result lost before commit")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(psycopg.AsyncConnection, "execute", fail_return)
        with pytest.raises(BillingError):
            asyncio.run(cancellation(setup).cancel_renewal(command(setup, purchase)))
    assert receipts(setup) == 0
    assert (
        asyncio.run(session(setup).load_checkout(purchase.offer.company_id, purchase.purchase_id)) == purchase
    )


def test_request_evidence_is_immutable_and_browser_roles_have_no_access(setup, purchase):
    result = asyncio.run(cancellation(setup).cancel_renewal(command(setup, purchase)))
    for role in ["anon", "authenticated", "service_role"]:
        with psycopg.connect(DATABASE_URL) as connection:
            scoped(connection, setup[1].subject, role=role)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("select * from billing.annual_cancellation_requests")
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "update billing.annual_cancellation_requests set effective_at=now() where id=%s",
                (str(result.cancellation_id),),
            )


def test_cancellation_evidence_survives_full_predecessor_rollback_and_recutover(setup, purchase):
    request = command(setup, purchase)
    result = asyncio.run(cancellation(setup).cancel_renewal(request))
    migrations = [
        "20260907153938_annual_checkout_observation.sql",
        "20260906221800_annual_checkout_withdrawals.sql",
        "20260905145000_annual_refund_agreement_cleanup.sql",
        "20260905141500_annual_refund_requests.sql",
        "20260905115700_legacy_billing_acquisition_retirement.sql",
        "20260905103149_annual_agreement_cleanup.sql",
        "20260905100130_annual_renewal_cancellation.sql",
        "20260905083150_annual_billing_purchase_ledger.sql",
        "20260905080550_annual_billing_purchase_basis.sql",
        "20260905061339_billing_provider_reconciliation.sql",
        "20260905010000_billing_capability.sql",
    ]
    for _ in range(2):
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            for migration in migrations:
                connection.execute((ROOT / "supabase" / "rollback" / migration).read_text())
            assert connection.execute("select to_regnamespace('billing')").fetchone()[0] is None
            assert connection.execute(
                "select to_regclass('billing_annual_retired.annual_cancellation_requests')"
            ).fetchone()[0]
            for migration in reversed(migrations):
                connection.execute((ROOT / "supabase" / "migrations" / migration).read_text())
            principal = connection.execute("select current_user").fetchone()[0]
            connection.execute(
                psycopg.sql.SQL("grant billing_store_owner to {}").format(psycopg.sql.Identifier(principal))
            )
        assert asyncio.run(cancellation(setup).cancel_renewal(request)) == result
        after = asyncio.run(session(setup).load_checkout(purchase.offer.company_id, purchase.purchase_id))
        assert after == replace(purchase, renewal_canceled_at=result.effective_at)


def test_ignored_duplicate_key_does_not_stop_another_purchase_without_receipt(setup, purchase):
    first = command(setup, purchase)
    asyncio.run(cancellation(setup).cancel_renewal(first))
    asyncio.run(
        session(setup).settle_checkout(purchase, observation(purchase, status=AnnualProviderStatus.FAILED))
    )
    other = asyncio.run(
        session(setup).claim_checkout(candidate(setup, key=IdempotencyKey(str(uuid4()))), setup[4])
    ).checkout
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        connection.execute(
            """
          insert into billing.annual_cancellation_requests
            (id,purchase_id,company_id,income_year,requested_by,idempotency_key,request_fingerprint)
          values (%s,%s,%s,2026,%s,%s,%s) on conflict (idempotency_key) do nothing
        """,
            (
                uuid4(),
                str(other.purchase_id),
                str(other.offer.company_id),
                str(setup[1].subject),
                str(first.idempotency_key),
                "a" * 64,
            ),
        )
    assert asyncio.run(session(setup).load_checkout(other.offer.company_id, other.purchase_id)) == other
    assert receipts(setup) == 1


def test_unreferenced_user_deletion_can_perform_cancellation_foreign_key_check(setup):
    identity = uuid4()
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection, "auth.users", {"id": identity, "email": f"{identity}@example.test"})
        connection.execute("delete from auth.users where id=%s", (identity,))
        assert (
            connection.execute("select count(*) from auth.users where id=%s", (identity,)).fetchone()[0] == 0
        )
