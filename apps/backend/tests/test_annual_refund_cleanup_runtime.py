"""Refund-triggered agreement cleanup in isolated PostgreSQL; no live MT calls."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import json
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from test_annual_purchase_basis_runtime import DATABASE_URL, ROOT, admitted, scoped, insert, test_role_authority
from test_annual_checkout_runtime import setup, session, observation
from test_annual_cancellation_runtime import purchase, cancellation, command as cancel_command
from test_annual_refund_runtime import paid, command, source, store as refund_store, refund_observation
from test_annual_cleanup_runtime import cleanup_store, stop_observation
from talli_backend.adapters.postgres_annual_checkout import _record
from talli_backend.modules.billing.public import (
    AnnualProviderStatus, AnnualRefundRequestId, BillingError,
)

pytestmark = pytest.mark.billing_database
MIGRATION = '20260905145000_annual_refund_agreement_cleanup.sql'


def refund(setup, current):
    request = command(setup, current)
    original = asyncio.run(refund_store(setup, source(current, request)).claim_refund(request)).resolution
    confirmed = asyncio.run(refund_store(setup).settle_refund(original, refund_observation(original)))
    return request, confirmed


def claim(setup, current):
    return asyncio.run(cleanup_store(setup).claim_agreement_cleanup(current.offer.company_id, current.purchase_id))


def operation_count(setup):
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        return connection.execute("select count(*) from billing.annual_operations where company_id=%s and operation='stop_agreement'", (str(setup[2].company_id),)).fetchone()[0]


def cloned_operation(setup, operation_id):
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        scoped(connection, setup[1].subject)
        row = connection.execute('select * from billing.annual_operations where id=%s', (str(operation_id),)).fetchone()
    row.update(id=uuid4(), idempotency_key=str(uuid4()), status='created', observation=None)
    row['intent']['provider_intent']['operation_id'] = str(row['id'])
    return row


def test_refund_receipt_stops_original_agreement_without_manual_cancellation(setup, paid):
    request, confirmed = refund(setup, paid)
    result = claim(setup, paid)
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        row = connection.execute('select id,requested_at from billing.annual_refund_requests where idempotency_key=%s', (str(request.idempotency_key),)).fetchone()
        assert connection.execute('select count(*) from billing.annual_cancellation_requests where purchase_id=%s', (str(paid.purchase_id),)).fetchone()[0] == 0
    assert result.newly_claimed and result.cleanup.cancellation_id is None
    assert result.cleanup.refund_request_id == AnnualRefundRequestId(str(row[0]))
    before = asyncio.run(session(setup).load_checkout(paid.offer.company_id, paid.purchase_id))
    settled = asyncio.run(cleanup_store(setup).settle_agreement_cleanup(result.cleanup, stop_observation(result.cleanup)))
    assert claim(setup, paid).cleanup == settled
    assert asyncio.run(session(setup).load_checkout(paid.offer.company_id, paid.purchase_id)) == before
    assert before.renewal_canceled_at.value == row[1]


def test_confirmed_full_refund_resolves_charge_without_rewriting_unknown_checkout(setup, purchase):
    unknown = asyncio.run(session(setup).settle_checkout(purchase, observation(purchase, captured=149000, status=AnnualProviderStatus.UNKNOWN)))
    refund(setup, unknown)
    result = claim(setup, unknown)
    assert result is not None and result.cleanup.refund_request_id is not None
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        assert connection.execute("select status from billing.annual_operations where purchase_id=%s and operation='checkout'", (str(purchase.purchase_id),)).fetchone()[0] == 'unknown'
    current = asyncio.run(session(setup).load_checkout(purchase.offer.company_id, purchase.purchase_id))
    assert current.status.value == 'refunded' and current.observation.status is AnnualProviderStatus.UNKNOWN


def test_final_partial_refund_operation_can_resolve_full_original_charge(setup, purchase):
    partial = asyncio.run(session(setup).settle_checkout(purchase, observation(purchase, captured=50000, status=AnnualProviderStatus.UNKNOWN)))
    request, first = refund(setup, partial)
    assert claim(setup, partial) is None
    # Later capture is observed by the original checkout, still with unknown outcome.
    grown = asyncio.run(session(setup).settle_checkout(partial, observation(partial, captured=149000, refunded=50000,
        captured_at=partial.observation.captured_at, status=AnnualProviderStatus.UNKNOWN)))
    from talli_backend.shared.kernel import IdempotencyKey
    second_request = replace(request, idempotency_key=IdempotencyKey(str(uuid4())))
    second = asyncio.run(refund_store(setup).claim_refund(second_request)).resolution
    assert second.operation.intent.amount_minor == 99000
    asyncio.run(refund_store(setup).settle_refund(second, refund_observation(second)))
    assert claim(setup, grown) is not None


def test_unresolved_refund_defers_new_and_unconfirmed_cleanup(setup, paid):
    asyncio.run(cancellation(setup).cancel_renewal(cancel_command(setup, paid)))
    original = claim(setup, paid).cleanup
    request = command(setup, paid)
    pending = asyncio.run(refund_store(setup, source(paid, request)).claim_refund(request)).resolution
    assert claim(setup, paid) is None
    asyncio.run(refund_store(setup).settle_refund(pending, refund_observation(pending)))
    resumed = claim(setup, paid)
    assert not resumed.newly_claimed and resumed.cleanup == original
    assert operation_count(setup) == 1


def test_later_refund_request_cannot_replace_the_actual_stop_receipt(setup, paid):
    request, confirmed = refund(setup, paid)
    from talli_backend.shared.kernel import IdempotencyKey
    later = replace(request, idempotency_key=IdempotencyKey(str(uuid4())))
    asyncio.run(refund_store(setup).claim_refund(later))
    result = claim(setup, paid).cleanup
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        ids = dict(connection.execute('select idempotency_key,id from billing.annual_refund_requests where purchase_id=%s', (str(paid.purchase_id),)).fetchall())
    assert result.refund_request_id == AnnualRefundRequestId(str(ids[str(request.idempotency_key)]))
    with pytest.raises(BillingError):
        asyncio.run(cleanup_store(setup).settle_agreement_cleanup(
            replace(result, refund_request_id=AnnualRefundRequestId(str(ids[str(later.idempotency_key)]))), stop_observation(result)))


@pytest.mark.parametrize('field,value', [
    ('provider','other'), ('agreement_reference','other'), ('charge_reference','other'),
    ('operation','checkout'), ('status','unknown'), ('amount_minor',1),
    ('captured_minor',148999), ('refunded_minor',148999), ('captured_at','2026-01-01T00:00:00+00:00'),
    ('checkout_url','https://example.test/invalid'), ('captured_minor',149000.0),
])
def test_malformed_full_refund_proof_cannot_resolve_unknown_original(setup, purchase, field, value):
    unknown = asyncio.run(session(setup).settle_checkout(purchase, observation(purchase, captured=149000, status=AnnualProviderStatus.UNKNOWN)))
    request = command(setup, unknown)
    original = asyncio.run(refund_store(setup, source(unknown, request)).claim_refund(request)).resolution
    malformed = _record(refund_observation(original)) | {field:value}
    # Deliberately malformed backend-owned fixture evidence: immutable triggers
    # remain enabled, proving cleanup independently validates the original effect.
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        connection.execute("update billing.annual_operations set status='confirmed',observation=%s::jsonb where id=%s", (json.dumps(malformed),str(original.operation.intent.operation_id)))
        connection.execute("update billing.annual_purchases set status='refunded',refunded_minor=captured_minor where id=%s", (str(purchase.purchase_id),))
    assert claim(setup, unknown) is None
    assert operation_count(setup) == 0


@pytest.mark.parametrize('field,value', [
    ('captured_minor', '149000'), ('previous_refunded_minor', '0'),
    ('captured_minor', 149000.0), ('previous_refunded_minor', 0.0),
])
def test_malformed_refund_claim_basis_cannot_resolve_unknown_original(setup, purchase, field, value):
    unknown = asyncio.run(session(setup).settle_checkout(purchase, observation(purchase, captured=149000, status=AnnualProviderStatus.UNKNOWN)))
    request = command(setup, unknown)
    original = asyncio.run(refund_store(setup, source(unknown, request)).claim_refund(request)).resolution
    asyncio.run(refund_store(setup).settle_refund(original, refund_observation(original, AnnualProviderStatus.FAILED)))
    row = cloned_operation(setup, original.operation.intent.operation_id)
    row['intent'][field] = value
    row['intent'] = Jsonb(row['intent'])
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        insert(connection, 'billing.annual_operations', row)
        connection.execute("update billing.annual_operations set status='confirmed',observation=%s where id=%s",
                           (Jsonb(_record(refund_observation(original))), row['id']))
        connection.execute("update billing.annual_purchases set status='refunded',refunded_minor=captured_minor where id=%s", (str(purchase.purchase_id),))
    assert claim(setup, unknown) is None
    assert operation_count(setup) == 0


@pytest.mark.parametrize('path', ['database_trigger', 'adapter'])
def test_cleanup_waiter_sees_pending_refund_committed_while_waiting_for_purchase(setup, paid, path):
    asyncio.run(cancellation(setup).cancel_renewal(cancel_command(setup, paid)))
    cleanup = claim(setup, paid).cleanup
    request = command(setup, paid)
    original = asyncio.run(refund_store(setup, source(paid, request)).claim_refund(request)).resolution
    asyncio.run(refund_store(setup).settle_refund(original, refund_observation(original, AnnualProviderStatus.FAILED)))
    pending = cloned_operation(setup, original.operation.intent.operation_id)
    pending['intent'] = Jsonb(pending['intent'])
    stop = cloned_operation(setup, cleanup.intent.operation_id)
    stop['intent'] = Jsonb(stop['intent'])

    async def direct_insert():
        # A distinct attempt must fail in the BEFORE guard, before the one-stop
        # unique index. A uniqueness failure cannot satisfy this assertion.
        def write():
            with psycopg.connect(DATABASE_URL) as connection:
                scoped(connection, setup[1].subject)
                with pytest.raises(psycopg.errors.RaiseException, match='annual_cleanup_not_available'):
                    insert(connection, 'billing.annual_operations', stop)
        return await asyncio.to_thread(write)

    async def run():
        with psycopg.connect(DATABASE_URL) as holder, psycopg.connect(DATABASE_URL, autocommit=True) as monitor:
            scoped(holder, setup[1].subject)
            holder.execute('select id from billing.annual_purchases where id=%s for update', (str(paid.purchase_id),))
            insert(holder, 'billing.annual_operations', pending)
            task = asyncio.create_task(direct_insert() if path == 'database_trigger' else
                                      cleanup_store(setup).claim_agreement_cleanup(paid.offer.company_id, paid.purchase_id))
            try:
                for _ in range(200):
                    waiting = monitor.execute('select count(*) from pg_stat_activity where %s=any(pg_blocking_pids(pid))',
                                              (holder.info.backend_pid,)).fetchone()[0]
                    if waiting:
                        break
                    await asyncio.sleep(.01)
                assert waiting and not task.done(), 'Cleanup must reach the held purchase lock'
                holder.commit()
                assert await asyncio.wait_for(task, 5) is None
            finally:
                holder.rollback()
    asyncio.run(run())
    assert operation_count(setup) == 1


def test_refund_cleanup_rollback_recutover_keeps_original_receipt_and_intent(setup, paid):
    refund(setup, paid)
    original = claim(setup, paid).cleanup
    for _ in range(2):
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            before = connection.execute("select pg_has_role(current_user,'billing_store_owner','SET')").fetchone()
            connection.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
            assert connection.execute("select to_regprocedure('billing.annual_original_charge_resolved_v1(uuid)')").fetchone()[0] is None
            connection.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
            assert connection.execute("select pg_has_role(current_user,'billing_store_owner','SET')").fetchone() == before
        assert claim(setup, paid).cleanup == original


@pytest.mark.parametrize('provider_resolved', [True, False])
def test_real_adapter_and_local_vipps_transport_recover_lost_refund_stop_response(setup, paid, provider_resolved):
    import httpx
    from test_vipps_billing import MerchantTestFixture, CONFIG
    from talli_backend.adapters.vipps_billing import VippsTestBillingProvider
    from talli_backend.modules.billing.annual_cleanup import AnnualAgreementCleanupService
    from talli_backend.modules.billing.public import AnnualCheckoutQuery

    refund(setup, paid)
    current = asyncio.run(session(setup).load_checkout(paid.offer.company_id, paid.purchase_id))
    fixture = MerchantTestFixture()
    fixture.agreement.update(id=current.observation.agreement_reference, externalId=current.intent.agreement_external_reference,
        merchantRedirectUrl=current.intent.return_url, merchantAgreementUrl=current.intent.management_url)
    fixture.charge.update(id=current.intent.charge_reference, agreementId=current.observation.agreement_reference,
        externalId=current.intent.charge_reference, status='REFUNDED' if provider_resolved else 'PROCESSING')
    fixture.charge['summary']['refunded'] = 149000
    fixture.charge['history'][0]['occurred'] = current.observation.captured_at.value.isoformat()

    def lost_patch(request):
        response = fixture(request)
        if request.method == 'PATCH':
            raise httpx.ReadTimeout('synthetic lost stop response')
        return response

    provider = VippsTestBillingProvider(CONFIG, transport=httpx.MockTransport(lost_patch), now=lambda: datetime.now(UTC))
    service = AnnualAgreementCleanupService(cleanup_store(setup), provider)
    query = AnnualCheckoutQuery(paid.offer.company_id, setup[1], paid.purchase_id)
    first = asyncio.run(service.cleanup(query))
    if not provider_resolved:
        assert first.observation.status is AnnualProviderStatus.PENDING
        assert asyncio.run(service.cleanup(query)).observation.status is AnnualProviderStatus.PENDING
        assert not [request for request in fixture.requests if request.method == 'PATCH']
        assert asyncio.run(session(setup).load_checkout(paid.offer.company_id, paid.purchase_id)) == current
        return
    assert first.observation.status is AnnualProviderStatus.UNKNOWN
    recovered = asyncio.run(service.cleanup(query))
    assert recovered.observation.status is AnnualProviderStatus.CONFIRMED
    assert recovered.intent == first.intent and recovered.refund_request_id == first.refund_request_id
    assert len([request for request in fixture.requests if request.method == 'PATCH']) == 1
    assert asyncio.run(session(setup).load_checkout(paid.offer.company_id, paid.purchase_id)) == current


@pytest.mark.parametrize('mode', ['both_receipts', 'neither_receipt', 'missing_receipt', 'later_receipt', 'provider', 'original_charge'])
def test_database_guard_independently_rejects_misbound_refund_stop(setup, paid, mode):
    from talli_backend.shared.kernel import IdempotencyKey

    request, confirmed = refund(setup, paid)
    original = claim(setup, paid).cleanup
    later = replace(request, idempotency_key=IdempotencyKey(str(uuid4())))
    asyncio.run(refund_store(setup).claim_refund(later))
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        scoped(connection, setup[1].subject)
        row = connection.execute('select * from billing.annual_operations where id=%s', (str(original.intent.operation_id),)).fetchone()
        later_id = connection.execute('select id from billing.annual_refund_requests where idempotency_key=%s', (str(later.idempotency_key),)).fetchone()['id']
    row['id'] = uuid4()
    row['idempotency_key'] = str(uuid4())
    row['intent']['provider_intent']['operation_id'] = str(row['id'])
    if mode == 'both_receipts':
        row['intent']['cancellation_id'] = str(uuid4())
    elif mode == 'neither_receipt':
        row['intent']['refund_request_id'] = None
    elif mode == 'missing_receipt':
        row['intent']['refund_request_id'] = str(uuid4())
    elif mode == 'later_receipt':
        row['intent']['refund_request_id'] = str(later_id)
    elif mode == 'provider':
        row['intent']['provider'] = 'other'
    else:
        row['intent']['provider_intent']['charge_reference'] = 'other-charge'
    row['intent'] = Jsonb(row['intent'])
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        with pytest.raises(psycopg.errors.RaiseException, match='annual_cleanup_not_available'):
            insert(connection, 'billing.annual_operations', row)
    assert operation_count(setup) == 1


def test_http_cleanup_recovers_refund_receipt_without_creating_manual_cancellation(setup, paid):
    from test_annual_cleanup_runtime import HttpCleanupProvider, cleanup_http, post_cleanup
    request, confirmed = refund(setup, paid)
    before = asyncio.run(session(setup).load_checkout(paid.offer.company_id, paid.purchase_id))
    provider = HttpCleanupProvider(setup, paid)
    response = post_cleanup(cleanup_http(setup, provider), paid)
    assert response.status_code == 200 and response.json()["status"] == "confirmed", response.text
    result = claim(setup, paid)
    assert result.cleanup.cancellation_id is None and result.cleanup.refund_request_id is not None
    assert provider.executions == [result.cleanup.intent]
    assert asyncio.run(session(setup).load_checkout(paid.offer.company_id, paid.purchase_id)) == before
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        assert connection.execute('select count(*) from billing.annual_cancellation_requests where purchase_id=%s', (str(paid.purchase_id),)).fetchone()[0] == 0
