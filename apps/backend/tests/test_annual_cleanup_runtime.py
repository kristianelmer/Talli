"""Independent PostgreSQL connections enforce original-agreement cleanup."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import json
from uuid import uuid4

import psycopg
import pytest

from test_annual_purchase_basis_runtime import DATABASE_URL, ROOT, admitted, insert, scoped, test_role_authority
from test_annual_checkout_runtime import setup, session, observation, counts
from test_annual_cancellation_runtime import purchase, command, cancellation
from talli_backend.adapters.postgres_annual_cleanup import PostgresAnnualCleanupSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.billing.public import (
    AnnualCancellationId,
    AnnualCheckoutQuery,
    AnnualProviderObservation,
    AnnualProviderOperation,
    AnnualProviderStatus,
    AnnualPurchaseId,
    BillingError,
    BillingPaymentEventId,
    annual_agreement_cleanup_operations,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, UserId


pytestmark = pytest.mark.billing_database


def cleanup_store(setup, **options):
    return PostgresAnnualCleanupSession(session(setup, **options))


def stop_observation(cleanup, status=AnnualProviderStatus.CONFIRMED, **changes):
    return replace(
        AnnualProviderObservation(
            provider=cleanup.provider,
            operation=AnnualProviderOperation.STOP_AGREEMENT,
            status=status,
            agreement_reference=cleanup.intent.agreement_reference,
            charge_reference=cleanup.intent.charge_reference,
            amount_minor=0,
        ),
        **changes,
    )


def prepare(setup, purchase, *, status="paid"):
    captured = 0 if status == "failed" else 149000
    current = asyncio.run(
        session(setup).settle_checkout(
            purchase,
            observation(
                purchase,
                captured=captured,
                refunded=captured if status == "refunded" else 0,
                status=AnnualProviderStatus.FAILED if status == "failed" else AnnualProviderStatus.CONFIRMED,
            ),
        )
    )
    receipt = asyncio.run(cancellation(setup).cancel_renewal(command(setup, purchase)))
    return current, receipt


@pytest.mark.parametrize("status", ["paid", "failed", "refunded"])
def test_terminal_original_purchase_claims_one_receipt_bound_stop(setup, purchase, status):
    original, receipt = prepare(setup, purchase, status=status)
    store = cleanup_store(setup, current=False)
    first = asyncio.run(store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id))
    replay = asyncio.run(store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id))
    assert first.newly_claimed and not replay.newly_claimed and first.cleanup == replay.cleanup
    assert first.cleanup.cancellation_id == receipt.cancellation_id
    assert first.cleanup.intent.operation is AnnualProviderOperation.STOP_AGREEMENT
    assert first.cleanup.intent.agreement_reference == original.observation.agreement_reference
    assert counts(setup) == (1, 2)


@pytest.mark.parametrize("mode", ["pending", "partial", "no_receipt", "missing_agreement"])
def test_unready_original_purchase_never_creates_cleanup_operation(setup, purchase, mode):
    if mode == "partial":
        asyncio.run(session(setup).settle_checkout(purchase, observation(purchase, captured=1000)))
    elif mode == "no_receipt":
        asyncio.run(
            session(setup).settle_checkout(
                purchase, observation(purchase, captured=149000, status=AnnualProviderStatus.CONFIRMED)
            )
        )
    elif mode == "missing_agreement":
        asyncio.run(
            session(setup).settle_checkout(
                purchase, observation(purchase, status=AnnualProviderStatus.FAILED, agreement=None)
            )
        )
    if mode != "no_receipt":
        asyncio.run(cancellation(setup).cancel_renewal(command(setup, purchase)))
    assert (
        asyncio.run(
            cleanup_store(setup).claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)
        )
        is None
    )
    assert counts(setup) == (1, 1)


def test_concurrent_claims_after_different_cancellation_requests_share_original_stop(setup, purchase):
    prepare(setup, purchase)
    asyncio.run(cancellation(setup).cancel_renewal(command(setup, purchase)))

    async def run():
        return await asyncio.gather(
            *(
                cleanup_store(setup).claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)
                for _ in range(2)
            )
        )

    claims = asyncio.run(run())
    assert sum(item.newly_claimed for item in claims) == 1
    assert claims[0].cleanup == claims[1].cleanup and counts(setup) == (1, 2)


def test_lost_claim_response_recovers_same_committed_operation(setup, purchase):
    prepare(setup, purchase)

    class LostResponse(PostgresAnnualCleanupSession):
        async def claim_agreement_cleanup(self, company, purchase):
            await super().claim_agreement_cleanup(company, purchase)
            raise BillingError.unavailable()

    with pytest.raises(BillingError):
        asyncio.run(
            LostResponse(session(setup)).claim_agreement_cleanup(
                purchase.offer.company_id, purchase.purchase_id
            )
        )
    result = asyncio.run(
        cleanup_store(setup).claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)
    )
    assert not result.newly_claimed and counts(setup) == (1, 2)


def test_cleanup_settlement_never_changes_purchase_money_status_or_access(setup, purchase):
    prepare(setup, purchase)
    before = asyncio.run(session(setup).load_checkout(purchase.offer.company_id, purchase.purchase_id))
    store = cleanup_store(setup)
    original = asyncio.run(
        store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)
    ).cleanup
    pending = asyncio.run(
        store.settle_agreement_cleanup(original, stop_observation(original, AnnualProviderStatus.UNKNOWN))
    )
    confirmed = asyncio.run(store.settle_agreement_cleanup(pending, stop_observation(original)))
    stale = asyncio.run(
        store.settle_agreement_cleanup(original, stop_observation(original, AnnualProviderStatus.PENDING))
    )
    assert confirmed == stale
    assert (
        asyncio.run(session(setup).load_checkout(purchase.offer.company_id, purchase.purchase_id)) == before
    )


def cleanup_snapshot(purchase):
    with psycopg.connect(DATABASE_URL) as connection:
        return connection.execute(
            """select row_to_json(p), (select jsonb_agg(to_jsonb(o) order by o.id)
            from billing.annual_operations o where o.purchase_id=p.id)
            from billing.annual_purchases p where p.id=%s""",
            (str(purchase.purchase_id),),
        ).fetchone()


def revoke_cleanup_owner(connection, setup):
    connection.execute(
        'update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',
        (setup[0]['company'], setup[0]['owner']),
    )


def interleave_cleanup_sql(store, execute, support_case=None):
    """Inject a fault around real SQL while retaining the actual transaction/RLS."""
    transaction = store._database._transaction

    class Connection:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __getattr__(self, name):
            return getattr(self.wrapped, name)

        async def execute(self, sql, *args, **kwargs):
            return await execute(self.wrapped, sql, *args, **kwargs)

    async def interleaved(work):
        async def wrapped(connection):
            if support_case is not None:
                await connection.execute("select set_config('talli.support_case_id', %s, true)",
                                         (str(support_case),))
            return await work(Connection(connection))
        return await transaction(wrapped)

    store._database._transaction = interleaved


@pytest.mark.parametrize('phase,locked', [
    (phase, locked)
    for phase in ('claim_new', 'claim_deferred', 'claim_pending', 'claim_confirmed',
                  'settle_pending', 'settle_confirmed')
    for locked in ('purchase', 'checkout', 'stop')
    if locked != 'stop' or phase not in ('claim_new', 'claim_deferred')
])
@pytest.mark.parametrize('mode', ['owner', 'mfa'])
def test_cleanup_rechecks_authority_after_real_lock(setup, purchase, phase, locked, mode):
    if phase == 'claim_deferred':
        asyncio.run(cancellation(setup).cancel_renewal(command(setup, purchase)))
    else:
        prepare(setup, purchase)
    store = cleanup_store(setup)
    original = None
    if phase not in ('claim_new', 'claim_deferred'):
        original = asyncio.run(store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)).cleanup
        if phase.endswith('confirmed'):
            original = asyncio.run(store.settle_agreement_cleanup(original, stop_observation(original)))
    before = cleanup_snapshot(purchase)
    class RecordingProvider(HttpCleanupProvider):
        def __init__(self):
            super().__init__(setup, purchase)
            self.calls = []

        async def execute(self, intent):
            self.calls.append('execute')
            return await super().execute(intent)

        async def reconcile(self, intent):
            self.calls.append('reconcile')
            return await super().reconcile(intent)

    provider = RecordingProvider()
    service = annual_agreement_cleanup_operations(store, provider)
    query = AnnualCheckoutQuery(company_id=purchase.offer.company_id, actor_id=setup[1],
                                purchase_id=purchase.purchase_id)

    async def run():
        if mode == 'mfa':
            claims = json.loads(store._database._verified.claims_json)
            claims['amr'][0]['timestamp'] = datetime.now(UTC).timestamp() - 899.5
            store._database._verified = _VerifiedActor(setup[1], json.dumps(claims))
        with psycopg.connect(DATABASE_URL) as holder, psycopg.connect(DATABASE_URL, autocommit=True) as monitor:
            if locked == 'purchase':
                holder.execute('select id from billing.annual_purchases where id=%s for update',
                               (str(purchase.purchase_id),))
            else:
                operation_id = purchase.intent.operation_id if locked == 'checkout' else original.intent.operation_id
                holder.execute('select id from billing.annual_operations where id=%s for update',
                               (str(operation_id),))
            work = (service.cleanup(query) if phase.startswith('claim') else
                    store.settle_agreement_cleanup(original, stop_observation(original)))
            pending = asyncio.create_task(work)
            try:
                waiting = 0
                for _ in range(200):
                    waiting = monitor.execute(
                        'select count(*) from pg_stat_activity where %s=any(pg_blocking_pids(pid))',
                        (holder.info.backend_pid,),
                    ).fetchone()[0]
                    if waiting:
                        break
                    await asyncio.sleep(.005)
                assert waiting and not pending.done(), 'Must observe an actual independent SQL lock wait'
                if mode == 'mfa':
                    await asyncio.sleep(.65)
                else:
                    revoke_cleanup_owner(monitor, setup)
            finally:
                holder.rollback()
            with pytest.raises(BillingError) as denied:
                await asyncio.wait_for(pending, 4)
            assert denied.value.code == ('BILLING_FORBIDDEN' if mode == 'owner' else 'BILLING_STEP_UP_REQUIRED')

    asyncio.run(run())
    assert cleanup_snapshot(purchase) == before
    assert provider.calls == []
    assert provider.executions == provider.reads == []


@pytest.mark.parametrize('point', ['before_update', 'after_update'])
@pytest.mark.parametrize('opened_support', [False, True])
@pytest.mark.parametrize('mode', ['owner', 'mfa'])
def test_cleanup_settlement_authority_loss_rolls_back_instead_of_reporting_confirmation(
    setup, purchase, point, opened_support, mode,
):
    prepare(setup, purchase)
    store = cleanup_store(setup)
    original = asyncio.run(store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)).cleanup
    revoked = []
    write_rows = []
    support_case = None
    if opened_support:
        from test_annual_support_runtime import support
        owner_as_operator = (setup[0] | {'outsider': setup[0]['owner']},) + setup[1:]
        support_case = support(owner_as_operator).support_case_id
    if mode == 'mfa':
        claims = json.loads(store._database._verified.claims_json)
        claims['amr'][0]['timestamp'] = datetime.now(UTC).timestamp() - 899.5
        store._database._verified = _VerifiedActor(setup[1], json.dumps(claims))

    async def revoke_once():
        assert not revoked
        if mode == 'mfa':
            await asyncio.sleep(.65)
        else:
            with psycopg.connect(DATABASE_URL) as connection:
                revoke_cleanup_owner(connection, setup)
        revoked.append(True)

    async def execute(connection, sql, *args, **kwargs):
        operation_write = str(sql).strip().lower().startswith('update billing.annual_operations')
        if operation_write and point == 'before_update':
            await revoke_once()
        result = await connection.execute(sql, *args, **kwargs)
        if operation_write:
            write_rows.append(result.rowcount)
        if operation_write and point == 'after_update':
            await revoke_once()
        return result

    interleave_cleanup_sql(store, execute, support_case)
    before = cleanup_snapshot(purchase)
    try:
        outcome = asyncio.run(store.settle_agreement_cleanup(original, stop_observation(original)))
    except BillingError as error:
        outcome = error
    assert write_rows == ([0] if point == 'before_update' else [1])
    assert isinstance(outcome, BillingError), (
        f'Unauthorized confirmation returned; actual update rows={write_rows}; '
        f'persisted state changed={cleanup_snapshot(purchase) != before}'
    )
    assert outcome.code == ('BILLING_FORBIDDEN' if mode == 'owner' else 'BILLING_STEP_UP_REQUIRED')
    assert revoked == [True]
    assert cleanup_snapshot(purchase) == before


def test_cleanup_zero_row_write_cannot_confirm_even_when_owner_remains_authorized(setup, purchase):
    prepare(setup, purchase)
    store = cleanup_store(setup)
    original = asyncio.run(store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)).cleanup
    rows = []

    async def execute(connection, sql, *args, **kwargs):
        operation_write = str(sql).strip().lower().startswith('update billing.annual_operations')
        # Controlled missed-write injection: use an actual cursor and unchanged
        # owner/RLS authority, not a fabricated rowcount or a disappearing locked row.
        result = await connection.execute(sql + ' and false' if operation_write else sql, *args, **kwargs)
        if operation_write:
            rows.append(result.rowcount)
        return result

    interleave_cleanup_sql(store, execute)
    before = cleanup_snapshot(purchase)
    with pytest.raises(BillingError) as denied:
        asyncio.run(store.settle_agreement_cleanup(original, stop_observation(original)))
    assert denied.value.code == 'BILLING_DEPENDENCY_UNAVAILABLE' and rows == [0]
    assert cleanup_snapshot(purchase) == before
    asyncio.run(session(setup).authorize_owner_command(purchase.offer.company_id))


@pytest.mark.parametrize('point', ['after_insert', 'deferred_resolution'])
def test_cleanup_claim_late_owner_loss_never_publishes_success_or_deferral(setup, purchase, point):
    if point == 'after_insert':
        prepare(setup, purchase)
    else:
        asyncio.run(cancellation(setup).cancel_renewal(command(setup, purchase)))
    store = cleanup_store(setup)
    revoked = []

    async def execute(connection, sql, *args, **kwargs):
        result = await connection.execute(sql, *args, **kwargs)
        statement = str(sql).strip().lower()
        at_point = (statement.startswith('insert into billing.annual_operations') if point == 'after_insert'
                    else 'annual_original_charge_resolved_v1' in statement)
        if at_point:
            assert not revoked
            with psycopg.connect(DATABASE_URL) as other:
                revoke_cleanup_owner(other, setup)
            revoked.append(True)
        return result

    interleave_cleanup_sql(store, execute)
    before = cleanup_snapshot(purchase)
    with pytest.raises(BillingError) as denied:
        asyncio.run(store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id))
    assert denied.value.code == 'BILLING_FORBIDDEN' and revoked == [True]
    assert cleanup_snapshot(purchase) == before


@pytest.mark.parametrize('point', ['before_update', 'after_update'])
def test_cleanup_sql_failure_rolls_back_without_querying_aborted_transaction(setup, purchase, point):
    prepare(setup, purchase)
    store = cleanup_store(setup)
    original = asyncio.run(store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)).cleanup
    failures = []
    after_failure = []

    async def fail(connection):
        try:
            await connection.execute('select 1 / 0')
        except psycopg.errors.DivisionByZero:
            failures.append(connection.info.transaction_status)
            raise

    async def execute(connection, sql, *args, **kwargs):
        if failures:
            after_failure.append(sql)
        operation_write = str(sql).strip().lower().startswith('update billing.annual_operations')
        if operation_write and point == 'before_update':
            await fail(connection)
        result = await connection.execute(sql, *args, **kwargs)
        if operation_write and point == 'after_update':
            await fail(connection)
        return result

    interleave_cleanup_sql(store, execute)
    before = cleanup_snapshot(purchase)
    with pytest.raises(BillingError) as denied:
        asyncio.run(store.settle_agreement_cleanup(original, stop_observation(original)))
    assert denied.value.code == 'BILLING_DEPENDENCY_UNAVAILABLE'
    assert failures == [psycopg.pq.TransactionStatus.INERROR] and after_failure == []
    assert cleanup_snapshot(purchase) == before
    recovered = asyncio.run(cleanup_store(setup).settle_agreement_cleanup(original, stop_observation(original)))
    assert recovered.observation.status is AnnualProviderStatus.CONFIRMED


@pytest.mark.parametrize('receipt_kind', ['cancellation', 'unbound_refund'])
@pytest.mark.parametrize('already_claimed', [False, True])
def test_different_accepted_owner_recovers_original_cleanup_receipt(setup, purchase, receipt_kind, already_claimed):
    if receipt_kind == 'cancellation':
        prepare(setup, purchase)
        receipt_table = 'billing.annual_cancellation_requests'
    else:
        from test_annual_refund_runtime import command as refund_command, source, store as refund_store
        current = asyncio.run(session(setup).settle_checkout(
            purchase, observation(purchase, captured=149000, refunded=149000, status=AnnualProviderStatus.CONFIRMED),
        ))
        request = refund_command(setup, current)
        resolution = asyncio.run(refund_store(setup, source(current, request)).claim_refund(request)).resolution
        assert resolution.operation is None
        receipt_table = 'billing.annual_refund_requests'
    with psycopg.connect(DATABASE_URL) as connection:
        receipts = connection.execute(
            f'select to_jsonb(r) from {receipt_table} r where purchase_id=%s', (str(purchase.purchase_id),),
        ).fetchall()
        assert len(receipts) == 1 and receipts[0][0]['requested_by'] == str(setup[1].subject)
        if receipt_kind == 'unbound_refund':
            assert receipts[0][0]['operation_id'] is None
            assert connection.execute('select count(*) from billing.annual_cancellation_requests where purchase_id=%s',
                                      (str(purchase.purchase_id),)).fetchone()[0] == 0
        insert(connection, 'public.company_memberships', {'company_id': setup[0]['company'],
            'user_id': setup[0]['outsider'], 'role': 'owner', 'accepted_at': datetime.now(UTC)})
    original = (asyncio.run(cleanup_store(setup).claim_agreement_cleanup(
        purchase.offer.company_id, purchase.purchase_id)).cleanup if already_claimed else None)
    before = cleanup_snapshot(purchase)[0]
    other = ActorId(ActorKind.USER, UserId(str(setup[0]['outsider'])))
    store = cleanup_store(setup, actor=other, current=False)
    first = asyncio.run(store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id))
    assert first.newly_claimed is not already_claimed
    if original is not None:
        assert first.cleanup == original
    receipt_id = first.cleanup.cancellation_id or first.cleanup.refund_request_id
    assert str(receipt_id) == receipts[0][0]['id']
    confirmed = asyncio.run(store.settle_agreement_cleanup(first.cleanup, stop_observation(first.cleanup)))
    assert asyncio.run(store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)).cleanup == confirmed
    assert cleanup_snapshot(purchase)[0] == before
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute(f'select to_jsonb(r) from {receipt_table} r where purchase_id=%s',
                                  (str(purchase.purchase_id),)).fetchall() == receipts


@pytest.mark.parametrize("mode", ["outsider", "stale_mfa", "wrong_company", "wrong_purchase"])
def test_cleanup_claim_reauthorizes_without_mutation(setup, purchase, mode):
    prepare(setup, purchase)
    options = {}
    company, purchase_id = purchase.offer.company_id, purchase.purchase_id
    if mode == "outsider":
        options["actor"] = ActorId(ActorKind.USER, UserId(str(setup[0]["outsider"])))
    elif mode == "stale_mfa":
        options["fresh"] = False
    elif mode == "wrong_company":
        company = CompanyId(str(uuid4()))
    else:
        purchase_id = AnnualPurchaseId(str(uuid4()))
    with pytest.raises(BillingError):
        asyncio.run(cleanup_store(setup, **options).claim_agreement_cleanup(company, purchase_id))
    assert counts(setup) == (1, 1)


@pytest.mark.parametrize("mode", ["intent", "receipt", "account", "provider", "money", "stale_mfa"])
def test_settlement_rejects_changed_identity_or_financial_evidence(setup, purchase, mode):
    prepare(setup, purchase)
    store = cleanup_store(setup)
    original = asyncio.run(
        store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)
    ).cleanup
    altered, result = original, stop_observation(original)
    if mode == "intent":
        altered = replace(
            original, intent=replace(original.intent, operation_id=BillingPaymentEventId(str(uuid4())))
        )
    elif mode == "receipt":
        altered = replace(original, cancellation_id=AnnualCancellationId(str(uuid4())))
    elif mode == "account":
        altered = replace(original, provider_account="other")
    elif mode == "provider":
        altered = replace(original, provider="other")
    elif mode == "money":
        result = replace(result, captured_minor=149000)
    else:
        store = cleanup_store(setup, fresh=False)
    with pytest.raises(BillingError):
        asyncio.run(store.settle_agreement_cleanup(altered, result))
    assert (
        asyncio.run(
            cleanup_store(setup).claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)
        ).cleanup
        == original
    )


def test_cleanup_claim_trigger_and_unique_index_reject_missing_receipt_and_second_operation(setup, purchase):
    prepare(setup, purchase)
    asyncio.run(cleanup_store(setup).claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id))
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        saved = connection.execute(
            "select intent from billing.annual_operations where purchase_id=%s and operation='stop_agreement'",
            (str(purchase.purchase_id),),
        ).fetchone()[0]
    for missing_receipt in (True, False):
        identity = str(uuid4())
        modified = saved | {"provider_intent": saved["provider_intent"] | {"operation_id": identity}}
        if missing_receipt:
            modified["cancellation_id"] = str(uuid4())
        with psycopg.connect(DATABASE_URL) as connection:
            scoped(connection, setup[1].subject)
            with pytest.raises(
                psycopg.Error,
                match="annual_cleanup_not_available"
                if missing_receipt
                else "annual_one_agreement_cleanup_per_purchase",
            ):
                connection.execute(
                    """insert into billing.annual_operations
                    (id,purchase_id,company_id,income_year,created_by,idempotency_key,request_fingerprint,operation,amount_minor,intent)
                    values (%s,%s,%s,2026,%s,%s,%s,'stop_agreement',0,%s::jsonb)""",
                    (
                        identity,
                        str(purchase.purchase_id),
                        str(purchase.offer.company_id),
                        str(setup[1].subject),
                        str(uuid4()),
                        "f" * 64,
                        json.dumps(modified),
                    ),
                )
            connection.rollback()
    assert counts(setup) == (1, 2)


def test_cleanup_evidence_survives_two_full_predecessor_cycles(setup, purchase):
    prepare(setup, purchase)
    store = cleanup_store(setup)
    original = asyncio.run(
        store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)
    ).cleanup
    saved = asyncio.run(
        store.settle_agreement_cleanup(original, stop_observation(original, AnnualProviderStatus.UNKNOWN))
    )
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
            for migration in reversed(migrations):
                connection.execute((ROOT / "supabase" / "migrations" / migration).read_text())
            principal = connection.execute("select current_user").fetchone()[0]
            connection.execute(
                psycopg.sql.SQL("grant billing_store_owner to {}").format(psycopg.sql.Identifier(principal))
            )
        assert (
            asyncio.run(
                store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)
            ).cleanup
            == saved
        )


def test_local_http_cleanup_recovers_lost_stop_response_with_real_persistence(setup, purchase):
    import httpx
    from datetime import UTC, datetime
    from test_vipps_billing import MerchantTestFixture, CONFIG
    from talli_backend.adapters.vipps_billing import VippsTestBillingProvider
    from talli_backend.modules.billing.annual_cleanup import AnnualAgreementCleanupService
    from talli_backend.modules.billing.public import AnnualCheckoutQuery

    current, receipt = prepare(setup, purchase)
    fixture = MerchantTestFixture()
    fixture.agreement.update(
        id=current.observation.agreement_reference,
        externalId=current.intent.agreement_external_reference,
        merchantRedirectUrl=current.intent.return_url,
        merchantAgreementUrl=current.intent.management_url,
    )
    fixture.charge.update(
        id=current.intent.charge_reference,
        agreementId=current.observation.agreement_reference,
        externalId=current.intent.charge_reference,
    )
    fixture.charge["history"][0]["occurred"] = current.observation.captured_at.value.isoformat()

    def lost_patch(request):
        response = fixture(request)
        if request.method == "PATCH":
            raise httpx.ReadTimeout("fixture lost stop response")
        return response

    provider = VippsTestBillingProvider(
        CONFIG, transport=httpx.MockTransport(lost_patch), now=lambda: datetime.now(UTC)
    )
    store = cleanup_store(setup, current=False)
    service = AnnualAgreementCleanupService(store, provider)
    query = AnnualCheckoutQuery(purchase.offer.company_id, setup[1], purchase.purchase_id)
    first = asyncio.run(service.cleanup(query))
    assert first.observation.status is AnnualProviderStatus.UNKNOWN
    recovered = asyncio.run(service.cleanup(query))
    assert recovered.observation.status is AnnualProviderStatus.CONFIRMED
    assert recovered.intent == first.intent and recovered.cancellation_id == receipt.cancellation_id
    assert len([request for request in fixture.requests if request.method == "PATCH"]) == 1
    assert counts(setup) == (1, 2)
    after = asyncio.run(session(setup).load_checkout(purchase.offer.company_id, purchase.purchase_id))
    assert after == replace(current, renewal_canceled_at=receipt.effective_at)


def test_cancellation_before_capture_defers_then_claims_same_purchase_after_capture(setup, purchase):
    receipt = asyncio.run(cancellation(setup).cancel_renewal(command(setup, purchase)))
    store = cleanup_store(setup)
    assert asyncio.run(store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)) is None
    asyncio.run(
        session(setup).settle_checkout(
            purchase, observation(purchase, captured=149000, status=AnnualProviderStatus.CONFIRMED)
        )
    )
    result = asyncio.run(store.claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id))
    assert result.cleanup.cancellation_id == receipt.cancellation_id
    assert result.newly_claimed and counts(setup) == (1, 2)


def cleanup_http(setup, provider=None, **options):
    """Synthetic authentication; real restricted database ports and policy."""
    from fastapi.testclient import TestClient
    from talli_backend.main import create_app
    from talli_backend.adapters.supabase_annual_billing import _AnnualBillingSession, PostgresAnnualBillingReadSession
    from talli_backend.adapters.postgres_annual_checkout import PostgresAnnualCancellationSession
    from talli_backend.adapters.postgres_annual_support import PostgresAnnualSupportReadSession
    from talli_backend.adapters.postgres_annual_support_cleanup import PostgresAnnualSupportCleanupRecoverySession
    from talli_backend.adapters.postgres_annual_refund import (
        PostgresAnnualRefundRecoverySession, PostgresAnnualSupportRefundRecoverySession,
    )
    from talli_backend.application.billing_session import BillingAuthenticationError

    class Factory:
        async def session(self, token):
            if token != "local-verified-owner":
                raise BillingAuthenticationError()
            checkout = session(setup, current=False, **options)
            return _AnnualBillingSession(
                PostgresAnnualBillingReadSession(checkout), PostgresAnnualCancellationSession(checkout),
                checkout, PostgresAnnualCleanupSession(checkout), PostgresAnnualSupportReadSession(checkout),
                PostgresAnnualRefundRecoverySession(checkout), PostgresAnnualSupportRefundRecoverySession(checkout),
                PostgresAnnualSupportCleanupRecoverySession(checkout),
            )

    return TestClient(create_app(annual_billing_session_factory=Factory(), annual_billing_provider=provider))


def post_cleanup(api, purchase):
    return api.post(
        "/api/v1/billing/annual/agreement-cleanups", headers={"Authorization": "Bearer local-verified-owner"},
        json={"companyId": str(purchase.offer.company_id), "purchaseId": str(purchase.purchase_id)},
    )


class HttpCleanupProvider:
    production_enabled = False

    def __init__(self, setup, purchase):
        self.setup = setup
        self.purchase = purchase
        self.provider = purchase.provider
        self.account_reference = purchase.provider_account
        self.executions = []
        self.reads = []
        self.lose_response = False
        self.stopped = False

    async def execute(self, intent):
        original = await cleanup_store(self.setup).claim_agreement_cleanup(intent.company_id, self.purchase.purchase_id)
        assert not original.newly_claimed and original.cleanup.intent == intent
        self.executions.append(intent)
        self.stopped = True
        if self.lose_response:
            raise TimeoutError("synthetic transport response lost")
        return stop_observation(original.cleanup)

    async def reconcile(self, intent):
        self.reads.append(intent)
        original = await cleanup_store(self.setup).claim_agreement_cleanup(intent.company_id, self.purchase.purchase_id)
        return stop_observation(original.cleanup, AnnualProviderStatus.CONFIRMED if self.stopped else AnnualProviderStatus.PENDING)


@pytest.mark.parametrize("lost_response", [False, True])
def test_http_cleanup_uses_committed_original_and_never_changes_purchase_money_or_access(setup, purchase, lost_response):
    prepare(setup, purchase)
    before = asyncio.run(session(setup).load_checkout(purchase.offer.company_id, purchase.purchase_id))
    provider = HttpCleanupProvider(setup, purchase)
    provider.lose_response = lost_response
    api = cleanup_http(setup, provider)
    first = post_cleanup(api, purchase)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == ("unknown" if lost_response else "confirmed")
    provider.lose_response = False
    confirmed = post_cleanup(api, purchase)
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    assert len(provider.executions) == 1 and len(provider.reads) == int(lost_response)
    assert post_cleanup(cleanup_http(setup), purchase).json() == confirmed.json()
    assert counts(setup) == (1, 2)
    assert asyncio.run(session(setup).load_checkout(purchase.offer.company_id, purchase.purchase_id)) == before


@pytest.mark.parametrize("mode", ["pending", "no_receipt", "provider_disabled", "stale_mfa", "outsider"])
def test_http_cleanup_preserves_database_authority_and_deferred_state(setup, purchase, mode):
    if mode == "no_receipt":
        asyncio.run(session(setup).settle_checkout(
            purchase, observation(purchase, captured=149000, status=AnnualProviderStatus.CONFIRMED),
        ))
    elif mode != "pending":
        prepare(setup, purchase)
    provider = HttpCleanupProvider(setup, purchase)
    options = {"fresh": False} if mode == "stale_mfa" else {"actor": ActorId(ActorKind.USER, UserId(str(setup[0]["outsider"])))} if mode == "outsider" else {}
    api = cleanup_http(setup, None if mode == "provider_disabled" else provider, **options)
    response = post_cleanup(api, purchase)
    if mode in {"pending", "no_receipt"}:
        assert response.status_code == 200 and response.json()["status"] == "deferred"
    else:
        assert response.status_code == (503 if mode == "provider_disabled" else 403), response.text
    assert provider.executions == provider.reads == []
    assert counts(setup) == (1, 2 if mode == "provider_disabled" else 1)
