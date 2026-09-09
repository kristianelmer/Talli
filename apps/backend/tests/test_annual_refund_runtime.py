"""Real local persistence proof; incident/submission resolvers remain synthetic."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4

import psycopg
import pytest

from test_annual_purchase_basis_runtime import DATABASE_URL, ROOT, admitted, scoped, insert, test_role_authority
from test_annual_checkout_runtime import setup, session, candidate, observation
from test_annual_cancellation_runtime import purchase
from talli_backend.adapters.postgres_annual_refund import PostgresAnnualRefundSession
from talli_backend.modules.billing.public import (
    AnnualProviderObservation, AnnualProviderOperation, AnnualProviderStatus,
    AnnualRefundFacts, AnnualRefundReason, BillingError, RequestAnnualRefundCommand,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IdempotencyKey, Timestamp, UserId

pytestmark = pytest.mark.billing_database
MIGRATION = '20260905141500_annual_refund_requests.sql'


@pytest.fixture
def paid(setup, purchase):
    return asyncio.run(session(setup).settle_checkout(purchase, observation(
        purchase, captured=149000, status=AnnualProviderStatus.CONFIRMED,
    )))


def command(setup, purchase, **changes):
    return replace(RequestAnnualRefundCommand(
        company_id=purchase.offer.company_id, actor_id=setup[1],
        correlation_id=setup[5].correlation_id, idempotency_key=IdempotencyKey(str(uuid4())),
        purchase_id=purchase.purchase_id, source_reference=str(uuid4()),
    ), **changes)


def source(purchase, command, **changes):
    now = Timestamp(datetime.now(UTC))
    return replace(AnnualRefundFacts(
        reason=AnnualRefundReason.CHANGE_OF_MIND,
        purchased_at=purchase.observation.captured_at, first_purchased_at=purchase.observation.captured_at,
        accepted_at=purchase.intent.created_at, discovered_at=now, condition_effective_at=now,
        blocked_at=now, income_year=purchase.offer.income_year, gross_minor=purchase.offer.gross_minor,
        refunded_minor=purchase.observation.refunded_minor, production_submission_at=None,
        evidence_reference=command.source_reference,
    ), **changes)


def store(setup, facts=None, **options):
    database = session(setup, **{key: options.pop(key) for key in list(options) if key in ('actor', 'fresh')})
    if facts is None:
        return PostgresAnnualRefundSession(database, **options)

    async def resolver(connection, request):
        return facts
    return PostgresAnnualRefundSession(database, source_facts=resolver, **options)


def refund_observation(resolution, status=AnnualProviderStatus.CONFIRMED, **changes):
    operation = resolution.operation
    return replace(AnnualProviderObservation(
        provider=operation.provider, operation=AnnualProviderOperation.REFUND, status=status,
        agreement_reference=operation.intent.agreement_reference, charge_reference=operation.intent.charge_reference,
        amount_minor=operation.intent.amount_minor, captured_minor=operation.captured_minor,
        refunded_minor=operation.previous_refunded_minor + (operation.intent.amount_minor if status is AnnualProviderStatus.CONFIRMED else 0),
        captured_at=operation.captured_at,
    ), **changes)


def state(setup):
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        return connection.execute('''select
          (select count(*) from billing.annual_refund_cases where company_id=%s),
          (select count(*) from billing.annual_refund_requests where company_id=%s),
          (select count(*) from billing.annual_operations where company_id=%s and operation='refund')''',
          (str(setup[2].company_id),) * 3).fetchone()


def test_claim_is_durable_exact_and_stops_renewal_before_any_provider(setup, paid):
    request = command(setup, paid)
    first = asyncio.run(store(setup, source(paid, request)).claim_refund(request))
    replay = asyncio.run(store(setup).claim_refund(request))
    assert first.newly_claimed and not replay.newly_claimed and first.resolution == replay.resolution
    assert state(setup) == (1, 1, 1)
    current = asyncio.run(session(setup).load_checkout(request.company_id, request.purchase_id))
    assert current.renewal_canceled_at and current.status == paid.status
    assert current.offer == paid.offer and current.observation == paid.observation


@pytest.mark.parametrize('mode', ['missing_source', 'wrong_money', 'wrong_year', 'wrong_first_purchase', 'wrong_capture', 'wrong_source', 'owner_failure_reason', 'stale_mfa', 'outsider'])
def test_unverified_or_unauthorized_new_case_never_records_refund(setup, paid, mode):
    request = command(setup, paid)
    facts = source(paid, request)
    options = {}
    if mode == 'missing_source':
        facts = None
    elif mode == 'wrong_money':
        facts = replace(facts, gross_minor=100000)
    elif mode == 'wrong_year':
        from talli_backend.shared.kernel import IncomeYear
        facts = replace(facts, income_year=IncomeYear(2025))
    elif mode == 'wrong_first_purchase':
        facts = replace(facts, first_purchased_at=Timestamp(facts.first_purchased_at.value-timedelta(days=1)))
    elif mode == 'wrong_capture':
        facts = replace(facts, purchased_at=Timestamp(facts.purchased_at.value+timedelta(microseconds=1)))
    elif mode == 'wrong_source':
        facts = replace(facts, evidence_reference='other')
    elif mode == 'owner_failure_reason':
        facts = replace(facts, reason=AnnualRefundReason.TALLI_DELIVERY_FAILURE)
    elif mode == 'stale_mfa':
        options['fresh'] = False
    else:
        options['actor'] = ActorId(ActorKind.USER, UserId(str(setup[0]['outsider'])))
        request = replace(request, actor_id=options['actor'])
    with pytest.raises(BillingError):
        asyncio.run(store(setup, facts, **options).claim_refund(request))
    assert state(setup) == (0, 0, 0)
    assert asyncio.run(session(setup).load_checkout(paid.offer.company_id, paid.purchase_id)).renewal_canceled_at is None


def test_concurrent_keys_share_case_and_reserve_one_operation(setup, paid):
    request = command(setup, paid)
    facts = source(paid, request)

    async def run():
        return await asyncio.gather(*(store(setup, facts).claim_refund(replace(request, idempotency_key=IdempotencyKey(str(uuid4())))) for _ in range(4)))
    claims = asyncio.run(run())
    assert sum(claim.newly_claimed for claim in claims) == 1
    assert len({str(claim.resolution.operation.intent.operation_id) for claim in claims}) == 1
    assert state(setup) == (1, 4, 1)


def test_confirmed_refund_is_atomic_and_terminal_replay_is_provider_source_independent(setup, paid):
    request = command(setup, paid)
    original = asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution
    result = asyncio.run(store(setup).settle_refund(original, refund_observation(original)))
    replay = asyncio.run(store(setup).settle_refund(original, refund_observation(original, AnnualProviderStatus.UNKNOWN)))
    assert replay == result
    current = asyncio.run(session(setup).load_checkout(request.company_id, request.purchase_id))
    assert current.observation.refunded_minor == current.observation.captured_minor == 149000
    assert current.status.value == 'refunded' and current.renewal_canceled_at
    assert current.offer == paid.offer
    assert asyncio.run(store(setup).claim_refund(request)).resolution == result


def test_failed_operation_stays_terminal_and_new_request_reserves_distinct_attempt(setup, paid):
    request = command(setup, paid)
    original = asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution
    failed = asyncio.run(store(setup).settle_refund(original, refund_observation(original, AnnualProviderStatus.FAILED)))
    assert asyncio.run(store(setup).claim_refund(request)).resolution == failed
    retry = asyncio.run(store(setup).claim_refund(replace(request, idempotency_key=IdempotencyKey(str(uuid4())))))
    assert retry.newly_claimed and retry.resolution.operation.intent.operation_id != original.operation.intent.operation_id
    assert state(setup) == (1, 2, 2)


def test_different_case_defers_then_binds_once_after_original_failure(setup, paid):
    request = command(setup, paid)
    original = asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution
    other = command(setup, paid)
    deferred = asyncio.run(store(setup, source(paid, other)).claim_refund(other))
    assert deferred.resolution.operation is None and not deferred.newly_claimed
    assert state(setup) == (2, 2, 1)
    asyncio.run(store(setup).settle_refund(original, refund_observation(original, AnnualProviderStatus.FAILED)))
    resumed = asyncio.run(store(setup).claim_refund(other))
    assert resumed.newly_claimed and resumed.resolution.case_id == deferred.resolution.case_id
    replay = asyncio.run(store(setup).claim_refund(other))
    assert not replay.newly_claimed and resumed.resolution == replay.resolution
    assert state(setup) == (2, 2, 2)


@pytest.mark.parametrize('mode', ['request', 'intent', 'provider', 'facts', 'stale_mfa'])
def test_misbound_or_unauthorized_settlement_never_changes_money(setup, paid, mode):
    request = command(setup, paid)
    original = asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution
    altered = original
    options = {}
    if mode == 'request':
        altered = replace(original, request=replace(request, source_reference='other'))
    elif mode == 'intent':
        altered = replace(original, operation=replace(original.operation, intent=replace(original.operation.intent, amount_minor=10000)))
    elif mode == 'provider':
        altered = replace(original, operation=replace(original.operation, provider='other'))
    elif mode == 'facts':
        altered = replace(original, source_digest='f'*64)
    else:
        options['fresh'] = False
    with pytest.raises(BillingError):
        asyncio.run(store(setup, **options).settle_refund(altered, refund_observation(original)))
    current = asyncio.run(session(setup).load_checkout(request.company_id, request.purchase_id))
    assert current.observation.refunded_minor == 0 and current.status.value == 'paid'


def test_partial_capture_growth_preserves_original_refund_and_current_purchase_totals(setup, purchase):
    partial = asyncio.run(session(setup).settle_checkout(purchase, observation(purchase, captured=50000)))
    request = command(setup, partial)
    original = asyncio.run(store(setup, source(partial, request)).claim_refund(request)).resolution
    complete = observation(partial, captured=149000, captured_at=partial.observation.captured_at, status=AnnualProviderStatus.CONFIRMED)
    asyncio.run(session(setup).settle_checkout(partial, complete))
    result = asyncio.run(store(setup).settle_refund(original, refund_observation(original, captured_minor=149000)))
    current = asyncio.run(session(setup).load_checkout(request.company_id, request.purchase_id))
    assert result.operation.intent.amount_minor == 50000
    assert current.observation.captured_minor == 149000 and current.observation.refunded_minor == 50000
    assert current.status.value == 'paid'
    next_attempt = asyncio.run(store(setup).claim_refund(replace(request, idempotency_key=IdempotencyKey(str(uuid4())))))
    assert next_attempt.resolution.operation.intent.amount_minor == 99000


def test_rollback_recutover_preserves_request_case_operation_and_role_authority(setup, paid):
    request = command(setup, paid)
    original = asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution
    for _ in range(2):
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            before = connection.execute("select pg_has_role(current_user,'billing_store_owner','SET')").fetchone()
            connection.execute((ROOT/'supabase/rollback/20260905145000_annual_refund_agreement_cleanup.sql').read_text())
            connection.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
            assert connection.execute("select to_regclass('billing.annual_refund_requests')").fetchone()[0] is None
            connection.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
            connection.execute((ROOT/'supabase/migrations/20260905145000_annual_refund_agreement_cleanup.sql').read_text())
            assert connection.execute("select pg_has_role(current_user,'billing_store_owner','SET')").fetchone() == before
        assert asyncio.run(store(setup).claim_refund(request)).resolution == original


@pytest.mark.parametrize('mode', ['opened', 'no_case', 'unopened', 'wrong_scope', 'expired', 'revoked', 'stale_mfa'])
def test_support_refund_requires_current_explicit_open_billing_case(setup, paid, mode):
    actor = ActorId(ActorKind.USER, UserId(str(setup[0]['outsider'])))
    case_id = uuid4()
    now = datetime.now(UTC)
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection, 'public.support_operators', {'user_id': actor.subject.value, 'role': 'admin', 'active': True})
        grant = {
            'case_id': case_id, 'company_id': setup[0]['company'], 'operator_user_id': actor.subject.value,
            'reason': 'customer_request', 'scopes': ['profile' if mode == 'wrong_scope' else 'billing'],
            'starts_at': now-timedelta(hours=2), 'expires_at': now+timedelta(hours=-1 if mode == 'expired' else 1),
            'granted_by': actor.subject.value,
        }
        if mode == 'revoked':
            grant |= {'revoked_at': now, 'revoked_by': actor.subject.value, 'revocation_reason': 'case_closed'}
        insert(connection, 'public.support_access_grants', grant)
        if mode != 'unopened':
            insert(connection, 'public.support_case_openings', {
                'actor_id': actor.subject.value, 'operation_id': uuid4(), 'case_id': case_id,
                'company_id': setup[0]['company'],
            })
    request = command(setup, paid, actor_id=actor)
    facts = source(paid, request, reason=AnnualRefundReason.TALLI_DELIVERY_FAILURE)
    options = {'actor': actor, 'fresh': mode != 'stale_mfa', 'support_case_id': None if mode == 'no_case' else str(case_id)}
    if mode != 'opened':
        with pytest.raises(BillingError):
            asyncio.run(store(setup, facts, **options).claim_refund(request))
        assert state(setup) == (0, 0, 0)
        return
    claim = asyncio.run(store(setup, facts, **options).claim_refund(request))
    assert claim.newly_claimed and claim.resolution.request.actor_id == actor
    assert claim.resolution.decision.total_entitlement_minor == 149000
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute('update public.support_access_grants set revoked_at=%s,revoked_by=%s,revocation_reason=%s where case_id=%s',
                           (datetime.now(UTC), str(actor.subject), 'case_closed', str(case_id)))
    with pytest.raises(BillingError):
        asyncio.run(store(setup, **options).claim_refund(request))
    with pytest.raises(BillingError):
        asyncio.run(store(setup, **options).settle_refund(claim.resolution, refund_observation(claim.resolution)))


def test_refund_then_repurchase_does_not_restart_first_purchase_history(setup, paid):
    request = command(setup, paid)
    original = asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution
    asyncio.run(store(setup).settle_refund(original, refund_observation(original)))
    replacement = asyncio.run(session(setup).claim_checkout(candidate(setup, key=IdempotencyKey(str(uuid4()))), setup[4])).checkout
    replacement = asyncio.run(session(setup).settle_checkout(replacement, observation(replacement, captured=149000, status=AnnualProviderStatus.CONFIRMED)))
    second = command(setup, replacement)
    with pytest.raises(BillingError):
        asyncio.run(store(setup, source(replacement, second)).claim_refund(second))
    facts = source(replacement, second, first_purchased_at=paid.observation.captured_at)
    claim = asyncio.run(store(setup, facts).claim_refund(second))
    assert claim.resolution.facts.first_purchased_at == paid.observation.captured_at


@pytest.mark.parametrize('mode', ['claim', 'settlement'])
def test_lost_commit_response_recovers_durable_refund_state(setup, paid, mode):
    request = command(setup, paid)
    facts = source(paid, request)

    class LostResponse(PostgresAnnualRefundSession):
        async def claim_refund(self, command):
            result = await super().claim_refund(command)
            if mode == 'claim':
                raise BillingError.unavailable()
            return result

        async def settle_refund(self, resolution, result):
            await super().settle_refund(resolution, result)
            raise BillingError.unavailable()

    async def resolver(connection, command):
        return facts

    broken = LostResponse(session(setup), source_facts=resolver)
    if mode == 'claim':
        with pytest.raises(BillingError):
            asyncio.run(broken.claim_refund(request))
    else:
        original = asyncio.run(broken.claim_refund(request)).resolution
        with pytest.raises(BillingError):
            asyncio.run(broken.settle_refund(original, refund_observation(original)))
    recovered = asyncio.run(store(setup).claim_refund(request))
    assert not recovered.newly_claimed and state(setup) == (1, 1, 1)
    if mode == 'settlement':
        assert recovered.resolution.operation.observation.status is AnnualProviderStatus.CONFIRMED


def test_receipt_assignment_and_private_table_access_are_enforced_by_database(setup, paid):
    request = command(setup, paid)
    result = asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        with pytest.raises(psycopg.errors.RaiseException, match='immutable'):
            connection.execute('update billing.annual_refund_requests set operation_id=null where idempotency_key=%s', (str(request.idempotency_key),))
    for role in ['anon', 'authenticated', 'service_role', 'billing_executor']:
        with psycopg.connect(DATABASE_URL) as connection:
            assert connection.execute("select has_table_privilege(%s,'billing.annual_refund_requests','SELECT')", (role,)).fetchone()[0] is False
    assert asyncio.run(store(setup).claim_refund(request)).resolution == result


def test_operation_write_failure_rolls_back_prior_purchase_update(setup, paid):
    request = command(setup, paid)
    original = asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution
    token = uuid4().hex
    function = f'refund_fail_{token}'
    trigger = f'refund_fail_{token}'
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        connection.execute(psycopg.sql.SQL('''create function billing.{}() returns trigger language plpgsql as $body$
            begin if new.id={}::uuid then raise exception 'synthetic_refund_write_failure'; end if; return new; end; $body$''').format(
            psycopg.sql.Identifier(function), psycopg.sql.Literal(str(original.operation.intent.operation_id))))
        connection.execute(psycopg.sql.SQL('create trigger {} before update on billing.annual_operations for each row execute function billing.{}()').format(psycopg.sql.Identifier(trigger), psycopg.sql.Identifier(function)))
    try:
        with pytest.raises(BillingError):
            asyncio.run(store(setup).settle_refund(original, refund_observation(original)))
        current = asyncio.run(session(setup).load_checkout(request.company_id, request.purchase_id))
        replay = asyncio.run(store(setup).claim_refund(request)).resolution
        assert current.status.value == 'paid' and current.observation.refunded_minor == 0
        assert replay.operation.observation is None
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            scoped(connection, setup[1].subject)
            connection.execute(psycopg.sql.SQL('drop trigger {} on billing.annual_operations').format(psycopg.sql.Identifier(trigger)))
            connection.execute(psycopg.sql.SQL('drop function billing.{}()').format(psycopg.sql.Identifier(function)))


def test_older_operation_cannot_regress_newer_purchase_settlement(setup, purchase):
    partial = asyncio.run(session(setup).settle_checkout(purchase, observation(purchase, captured=50000)))
    request = command(setup, partial)
    first = asyncio.run(store(setup, source(partial, request)).claim_refund(request)).resolution
    asyncio.run(store(setup).settle_refund(first, refund_observation(first)))
    asyncio.run(session(setup).settle_checkout(partial, observation(partial, captured=149000, refunded=50000,
        captured_at=partial.observation.captured_at, status=AnnualProviderStatus.CONFIRMED)))
    second_request = replace(request, idempotency_key=IdempotencyKey(str(uuid4())))
    second = asyncio.run(store(setup).claim_refund(second_request)).resolution
    asyncio.run(store(setup).settle_refund(second, refund_observation(second)))
    asyncio.run(store(setup).settle_refund(first, refund_observation(first, AnnualProviderStatus.UNKNOWN)))
    current = asyncio.run(session(setup).load_checkout(request.company_id, request.purchase_id))
    assert current.status.value == 'refunded'
    assert current.observation.captured_minor == current.observation.refunded_minor == 149000


def test_global_key_collision_conceals_other_company_without_side_effects(setup, paid):
    from types import SimpleNamespace
    from test_annual_checkout_runtime import setup as setup_fixture
    from test_annual_purchase_basis_runtime import admitted as admitted_fixture

    request = command(setup, paid)
    asyncio.run(store(setup, source(paid, request)).claim_refund(request))
    other = setup_fixture.__wrapped__(admitted_fixture.__wrapped__(SimpleNamespace()))
    new_purchase = asyncio.run(session(other).claim_checkout(candidate(other), other[4])).checkout
    new_paid = asyncio.run(session(other).settle_checkout(new_purchase,
        observation(new_purchase, captured=149000, status=AnnualProviderStatus.CONFIRMED)))
    collision = command(other, new_paid, idempotency_key=request.idempotency_key)
    with pytest.raises(BillingError) as failure:
        asyncio.run(store(other, source(new_paid, collision)).claim_refund(collision))
    assert failure.value.code.value == 'BILLING_IDEMPOTENCY_KEY_REUSED'
    assert state(other) == (0, 0, 0)
    current = asyncio.run(session(other).load_checkout(collision.company_id, collision.purchase_id))
    assert current.renewal_canceled_at is None and current.observation.refunded_minor == 0
