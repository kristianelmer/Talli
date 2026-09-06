"""Real case-bound receipt discovery across original requesters, without writes."""

import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from test_annual_refund_runtime import (
    DATABASE_URL, admitted, command, insert, paid, purchase, refund_observation,
    scoped, session, setup, source, store, test_role_authority,
)
from test_annual_refund_recovery_runtime import recorded, recovery_query
from test_annual_support_runtime import support, fingerprint
from talli_backend.adapters.postgres_annual_support import PostgresAnnualSupportReadSession
from talli_backend.adapters.supabase_annual_billing import PostgresAnnualBillingReadSession
from talli_backend.modules.billing.public import (
    AnnualProviderStatus, AnnualPurchaseId, AnnualRefundRequestId, AnnualSupportCaseId,
    AnnualRefundRecoveryTargetsQuery, AnnualSupportRefundRecoveryTargetsQuery, BillingError,
)
from talli_backend.shared.kernel import CompanyId, IdempotencyKey

pytestmark = pytest.mark.billing_database


def query(setup, paid, opened):
    return AnnualSupportRefundRecoveryTargetsQuery(
        paid.offer.company_id, paid.purchase_id, opened.support_case_id, opened.actor_id,
    )


def read(setup, value, **options):
    return asyncio.run(PostgresAnnualSupportReadSession(
        session(setup, actor=value.actor_id, current=False, **options),
    ).read_refund_recovery_targets(value))


def test_empty_discovery_and_missing_purchase_are_distinct_and_read_only(setup, paid):
    value = query(setup, paid, support(setup))
    before = fingerprint(setup)
    page = read(setup, value)
    assert page.targets == () and page.next_refund_request_id is None
    assert page.company_id == value.company_id and page.purchase_id == value.purchase_id
    with pytest.raises(BillingError) as denied:
        read(setup, replace(value, purchase_id=AnnualPurchaseId(str(uuid4()))))
    assert denied.value.code == 'BILLING_NOT_FOUND' and fingerprint(setup) == before


@pytest.mark.parametrize('mode', ['non_admin', 'inactive', 'unopened', 'wrong_scope', 'expired', 'future', 'revoked',
                                  'stale_mfa', 'wrong_case', 'wrong_company', 'owner'])
def test_denied_empty_discovery_cannot_claim_no_recorded_liability(setup, paid, mode):
    value = query(setup, paid, support(setup, mode))
    if mode == 'wrong_case': value = replace(value, support_case_id=AnnualSupportCaseId(str(uuid4())))
    if mode == 'wrong_company': value = replace(value, company_id=CompanyId(str(uuid4())))
    if mode == 'owner': value = replace(value, actor_id=setup[1])
    before = fingerprint(setup)
    with pytest.raises(BillingError) as denied:
        read(setup, value, fresh=mode != 'stale_mfa')
    assert denied.value.code == ('BILLING_STEP_UP_REQUIRED' if mode == 'stale_mfa' else 'BILLING_FORBIDDEN')
    assert fingerprint(setup) == before


@pytest.mark.parametrize('status', ['created', 'pending', 'unknown', 'confirmed', 'failed'])
def test_support_projects_stored_operation_status_only_without_sources_or_effects(setup, paid, recorded, status):
    if status != 'created':
        asyncio.run(store(setup).settle_refund(recorded[0], refund_observation(recorded[0], AnnualProviderStatus(status))))
    value = query(setup, paid, support(setup))
    before = fingerprint(setup)
    page = read(setup, value)
    assert len(page.targets) == 1 and page.targets[0].refund_request_id == recorded[1].refund_request_id
    assert page.targets[0].status.value == status
    assert set(asdict(page.targets[0])) == {'refund_request_id', 'requested_at', 'status'}
    assert fingerprint(setup) == before


def test_support_groups_owner_and_operator_receipts_while_owner_keeps_requester_filter(setup, paid, recorded):
    opened = support(setup)
    value = query(setup, paid, opened)
    other = replace(recorded[0].request, actor_id=opened.actor_id, idempotency_key=IdempotencyKey(str(uuid4())))
    result = asyncio.run(store(setup, actor=opened.actor_id, support_case_id=str(opened.support_case_id)).claim_refund(other))
    assert result.resolution.operation.intent == recorded[0].operation.intent
    other_id = recovery_query(setup, other).refund_request_id
    before = fingerprint(setup)
    page = read(setup, value)
    assert [item.refund_request_id for item in page.targets] == [recorded[1].refund_request_id]
    for cursor in (other_id, recorded[1].refund_request_id):
        assert read(setup, replace(value, before_refund_request_id=cursor)).targets == ()
    owner = PostgresAnnualBillingReadSession(session(setup))
    owner_query = AnnualRefundRecoveryTargetsQuery(value.company_id, value.purchase_id, setup[1])
    assert asyncio.run(owner.read_refund_recovery_targets(owner_query)).targets == page.targets
    with pytest.raises(BillingError):
        asyncio.run(owner.read_refund_recovery_targets(replace(owner_query, before_refund_request_id=other_id)))
    assert fingerprint(setup) == before


@pytest.mark.parametrize('cursor_kind', ['unknown', 'unbound', 'other_purchase', 'other_company'])
def test_foreign_or_unbound_cursor_does_not_disappear_into_empty_page(setup, paid, recorded, cursor_kind):
    value = query(setup, paid, support(setup))
    if cursor_kind == 'unbound':
        request = command(setup, paid)
        assert asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution.operation is None
        cursor = recovery_query(setup, request).refund_request_id
    else:
        cursor = recorded[1].refund_request_id if cursor_kind != 'unknown' else AnnualRefundRequestId(str(uuid4()))
        if cursor_kind == 'other_purchase': value = replace(value, purchase_id=AnnualPurchaseId(str(uuid4())))
        if cursor_kind == 'other_company': value = replace(value, company_id=CompanyId(str(uuid4())))
    before = fingerprint(setup)
    with pytest.raises(BillingError):
        read(setup, replace(value, before_refund_request_id=cursor))
    assert fingerprint(setup) == before


def test_authority_revoked_after_target_select_clears_even_populated_result(setup, paid, recorded, monkeypatch):
    import talli_backend.adapters.postgres_annual_support as implementation
    value = query(setup, paid, support(setup))
    original = implementation._read_refund_recovery_targets
    async def revoke_after_read(connection, query, **options):
        result = await original(connection, query, **options)
        assert result.targets
        with psycopg.connect(DATABASE_URL) as admin:
            admin.execute('update public.support_operators set active=false where user_id=%s', (str(query.actor_id.subject),))
        return result
    monkeypatch.setattr(implementation, '_read_refund_recovery_targets', revoke_after_read)
    with pytest.raises(BillingError) as denied:
        read(setup, value)
    assert denied.value.code == 'BILLING_FORBIDDEN'


def test_mixed_requesters_keep_bounded_operation_cursor_when_representative_changes(setup, paid, monkeypatch):
    # Synthetic billing clocks create two older and 49 tied newer attempts, then
    # a pending boundary operation between them. All rows use restricted claims.
    import talli_backend.adapters.postgres_annual_refund as implementation
    opened = support(setup)
    def request_store(request, facts=None):
        return store(setup, facts, actor=request.actor_id,
                     support_case_id=str(opened.support_case_id) if request.actor_id == opened.actor_id else None)
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
            request = replace(first, idempotency_key=IdempotencyKey(str(uuid4())),
                              actor_id=opened.actor_id if index % 2 else setup[1])
            result = (await request_store(request, facts).claim_refund(request)).resolution
            operations.append(result.operation.intent.operation_id)
            if index == 50:
                assert (await store(setup, deferred_facts).claim_refund(deferred)).resolution.operation is None
            await request_store(request).settle_refund(result, refund_observation(result, AnnualProviderStatus.FAILED))
        clock[0] = base - timedelta(seconds=1)
        bound = replace(deferred, idempotency_key=IdempotencyKey(str(uuid4())), actor_id=opened.actor_id)
        boundary = (await request_store(bound).claim_refund(bound)).resolution
        # More than a page of receipts for one group must not consume the limit.
        for _ in range(52):
            await store(setup).claim_refund(replace(deferred, idempotency_key=IdempotencyKey(str(uuid4()))))
        return bound, boundary, operations

    bound, boundary, operations = asyncio.run(create())
    scope = query(setup, paid, opened)
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
