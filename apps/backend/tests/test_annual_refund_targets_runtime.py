"""Real local read isolation, same-actor grouping and immutable operation cursors."""

import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from test_annual_refund_runtime import (
    DATABASE_URL, admitted, command, insert, paid, purchase, scoped, session,
    setup, source, store, refund_observation, test_role_authority,
)
from test_annual_refund_recovery_runtime import recovery_query, recorded, grant_open_support
from test_annual_checkout_runtime import candidate, observation
from test_annual_support_runtime import fingerprint
from talli_backend.adapters.supabase_annual_billing import PostgresAnnualBillingReadSession
from talli_backend.modules.billing.public import (
    AnnualProviderStatus, AnnualPurchaseId, AnnualRefundRecoveryTargetsQuery,
    AnnualRefundRequestId, BillingError,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IdempotencyKey, UserId

pytestmark = pytest.mark.billing_database


def query(setup, paid, **changes):
    return replace(AnnualRefundRecoveryTargetsQuery(paid.offer.company_id, paid.purchase_id, setup[1]), **changes)


def read(setup, query, **options):
    return asyncio.run(PostgresAnnualBillingReadSession(session(setup, **options)).read_refund_recovery_targets(query))


def test_empty_purchase_targets_and_absent_purchase_are_distinct(setup, paid):
    before = fingerprint(setup)
    page = read(setup, query(setup, paid), current=False)
    assert page.targets == () and page.next_refund_request_id is None
    assert page.company_id == paid.offer.company_id and page.income_year == paid.offer.income_year
    with pytest.raises(BillingError) as error:
        read(setup, query(setup, paid, purchase_id=AnnualPurchaseId(str(uuid4()))))
    assert error.value.code == 'BILLING_NOT_FOUND' and fingerprint(setup) == before


@pytest.mark.parametrize('status', ['created', 'pending', 'unknown', 'confirmed', 'failed'])
def test_stored_status_projection_has_no_mutation_or_source_requirement(setup, paid, recorded, status):
    if status != 'created':
        asyncio.run(store(setup).settle_refund(recorded[0], refund_observation(recorded[0], AnnualProviderStatus(status))))
    before = fingerprint(setup)
    page = read(setup, query(setup, paid), current=False)
    assert len(page.targets) == 1 and page.targets[0].refund_request_id == recorded[1].refund_request_id
    assert page.targets[0].status.value == status
    assert set(asdict(page.targets[0])) == {'refund_request_id', 'requested_at', 'status'}
    assert fingerprint(setup) == before


@pytest.mark.parametrize('mode', ['actor', 'mfa', 'outsider', 'support', 'revoked', 'company', 'purchase'])
def test_current_owner_scope_cannot_be_rescued_by_support(setup, paid, recorded, mode):
    value = query(setup, paid)
    options = {}
    outsider = ActorId(ActorKind.USER, UserId(str(setup[0]['outsider'])))
    if mode == 'actor': value = replace(value, actor_id=outsider)
    if mode == 'mfa': options['fresh'] = False
    if mode in ('outsider', 'support'):
        value = replace(value, actor_id=outsider)
        options['actor'] = outsider
        if mode == 'support': grant_open_support(setup, outsider)
    if mode == 'revoked':
        grant_open_support(setup, setup[1])
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',
                               (str(value.company_id), str(value.actor_id.subject)))
    if mode == 'company': value = replace(value, company_id=CompanyId(str(uuid4())))
    if mode == 'purchase': value = replace(value, purchase_id=AnnualPurchaseId(str(uuid4())))
    with pytest.raises(BillingError):
        read(setup, value, **options)


def test_other_actor_is_filtered_before_representative_and_cursor_selection(setup, paid, recorded):
    other = ActorId(ActorKind.USER, UserId(str(setup[0]['outsider'])))
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection, 'public.company_memberships', {'company_id': setup[0]['company'],
            'user_id': other.subject.value, 'role': 'owner', 'accepted_at': datetime.now(UTC)})
    scope = query(setup, paid, actor_id=other)
    assert read(setup, scope, actor=other).targets == ()
    request = replace(recorded[0].request, actor_id=other, idempotency_key=IdempotencyKey(str(uuid4())))
    result = asyncio.run(store(setup, actor=other).claim_refund(request)).resolution
    assert result.operation.intent.operation_id == recorded[0].operation.intent.operation_id
    identity = recovery_query(setup, request).refund_request_id
    page = read(setup, scope, actor=other)
    assert [value.refund_request_id for value in page.targets] == [identity]
    with pytest.raises(BillingError) as error:
        read(setup, replace(scope, before_refund_request_id=recorded[1].refund_request_id), actor=other)
    assert error.value.code == 'BILLING_NOT_FOUND'
    assert read(setup, replace(scope, before_refund_request_id=identity), actor=other).targets == ()


def test_unbound_and_unknown_cursors_do_not_allocate_or_hide_as_empty(setup, paid, recorded):
    request = command(setup, paid)
    assert asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution.operation is None
    unbound = recovery_query(setup, request).refund_request_id
    before = fingerprint(setup)
    for identity in (unbound, AnnualRefundRequestId(str(uuid4()))):
        with pytest.raises(BillingError) as error:
            read(setup, query(setup, paid, before_refund_request_id=identity))
        assert error.value.code == 'BILLING_NOT_FOUND'
    assert [value.refund_request_id for value in read(setup, query(setup, paid)).targets] == [recorded[1].refund_request_id]
    assert fingerprint(setup) == before


def test_foreign_company_and_other_purchase_receipts_are_not_cursors(setup, paid, recorded, request):
    other = globals()['setup'].__wrapped__(admitted.__wrapped__(request))
    foreign_purchase = asyncio.run(session(other).claim_checkout(candidate(other), other[4])).checkout
    foreign_paid = asyncio.run(session(other).settle_checkout(foreign_purchase, observation(
        foreign_purchase, captured=149000, status=AnnualProviderStatus.CONFIRMED)))
    foreign_request = command(other, foreign_paid)
    asyncio.run(store(other, source(foreign_paid, foreign_request)).claim_refund(foreign_request))
    foreign_cursor = recovery_query(other, foreign_request).refund_request_id
    with pytest.raises(BillingError) as error:
        read(setup, query(setup, paid, before_refund_request_id=foreign_cursor))
    assert error.value.code == 'BILLING_NOT_FOUND'

    asyncio.run(store(setup).settle_refund(recorded[0], refund_observation(recorded[0])))
    second = asyncio.run(session(setup).claim_checkout(candidate(setup, key=IdempotencyKey(str(uuid4()))), setup[4])).checkout
    second_paid = asyncio.run(session(setup).settle_checkout(second, observation(
        second, captured=149000, status=AnnualProviderStatus.CONFIRMED)))
    with pytest.raises(BillingError) as error:
        read(setup, query(setup, second_paid, before_refund_request_id=recorded[1].refund_request_id))
    assert error.value.code == 'BILLING_NOT_FOUND'


def test_dedup_ties_and_replaced_boundary_receipt_keep_existing_operation_cursor(setup, paid, monkeypatch):
    # Synthetic billing clocks create two older and 49 tied newer attempts, then
    # a pending boundary operation between them. All rows use restricted claims.
    import talli_backend.adapters.postgres_annual_refund as implementation
    first = command(setup, paid)
    deferred = command(setup, paid)
    facts = source(paid, first)
    deferred_facts = source(paid, deferred)
    base = datetime.now(UTC) + timedelta(seconds=3)
    clock = [base]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]
    monkeypatch.setattr(implementation, 'datetime', Clock)

    async def create():
        operations = []
        for index in range(51):
            clock[0] = base - timedelta(seconds=2) if index < 2 else base
            request = replace(first, idempotency_key=IdempotencyKey(str(uuid4())))
            result = (await store(setup, facts).claim_refund(request)).resolution
            operations.append(result.operation.intent.operation_id)
            if index == 50:
                assert (await store(setup, deferred_facts).claim_refund(deferred)).resolution.operation is None
            await store(setup).settle_refund(result, refund_observation(result, AnnualProviderStatus.FAILED))
        clock[0] = base - timedelta(seconds=1)
        bound = replace(deferred, idempotency_key=IdempotencyKey(str(uuid4())))
        boundary = (await store(setup).claim_refund(bound)).resolution
        # More than a page of receipts for one group must not consume the limit.
        for _ in range(52):
            await store(setup).claim_refund(replace(deferred, idempotency_key=IdempotencyKey(str(uuid4()))))
        return bound, boundary, operations

    bound, boundary, operations = asyncio.run(create())
    scope = query(setup, paid)
    before = fingerprint(setup)
    first_page = read(setup, scope)
    assert len(first_page.targets) == 50
    old_cursor = recovery_query(setup, bound).refund_request_id
    assert first_page.next_refund_request_id == first_page.targets[-1].refund_request_id == old_cursor
    assert fingerprint(setup) == before
    second_page = read(setup, replace(scope, before_refund_request_id=old_cursor))
    assert len(second_page.targets) == 2 and second_page.next_refund_request_id is None
    all_ids = {value.refund_request_id for value in first_page.targets + second_page.targets}
    assert len(all_ids) == 52
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        rows = connection.execute('''select r.id,o.id from billing.annual_refund_requests r
            join billing.annual_operations o on o.id=r.operation_id where r.company_id=%s''',
            (str(scope.company_id),)).fetchall()
        mapping = {str(request): str(operation) for request, operation in rows}
    expected = sorted((str(value) for value in operations[2:]), reverse=True)
    assert [mapping[str(value.refund_request_id)] for value in first_page.targets[:-1]] == expected

    resumed = asyncio.run(store(setup).claim_refund(deferred)).resolution
    assert resumed.operation.intent.operation_id == boundary.operation.intent.operation_id
    new_cursor = recovery_query(setup, deferred).refund_request_id
    refreshed = read(setup, scope)
    assert refreshed.next_refund_request_id == new_cursor != old_cursor
    before = fingerprint(setup)
    assert read(setup, replace(scope, before_refund_request_id=old_cursor)) == second_page
    assert read(setup, replace(scope, before_refund_request_id=new_cursor)) == second_page
    assert fingerprint(setup) == before
