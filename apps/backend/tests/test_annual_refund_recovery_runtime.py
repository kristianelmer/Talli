"""Real local owner recovery persistence; source/provider responses remain synthetic."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from uuid import uuid4

import psycopg
import pytest

from test_annual_refund_runtime import (
    DATABASE_URL, admitted, command, insert, paid, purchase, refund_observation,
    scoped, session, setup, source, state, store, test_role_authority,
)
from test_annual_checkout_runtime import observation
from talli_backend.adapters.postgres_annual_refund import PostgresAnnualRefundRecoverySession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.billing.annual_refund import AnnualRefundRecoveryService
from talli_backend.modules.billing.public import (
    AnnualProviderStatus, AnnualPurchaseId, AnnualRefundRequestId, AnnualRefundRecoveryQuery, BillingError,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IdempotencyKey, UserId

pytestmark = pytest.mark.billing_database


def recovery_query(setup, request):
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, setup[1].subject)
        identity = connection.execute(
            'select id from billing.annual_refund_requests where company_id=%s and idempotency_key=%s',
            (str(request.company_id), str(request.idempotency_key)),
        ).fetchone()[0]
    return AnnualRefundRecoveryQuery(request.company_id, request.purchase_id,
                                    AnnualRefundRequestId(str(identity)), request.actor_id)


@pytest.fixture
def recorded(setup, paid):
    request = command(setup, paid)
    resolution = asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution
    return resolution, recovery_query(setup, request)


class Provider:
    production_enabled = False

    def __init__(self, resolution):
        self.resolution = resolution
        self.provider = resolution.operation.provider
        self.account_reference = resolution.operation.provider_account
        self.reads = []
        self.status = AnnualProviderStatus.CONFIRMED
        self.changes = {}
        self.before_response = None

    async def execute(self, intent):
        pytest.fail('Recovery must never execute')

    async def reconcile(self, intent):
        self.reads.append(intent)
        if self.before_response:
            await self.before_response()
        return refund_observation(self.resolution, self.status, **self.changes)


def recovery(setup, recorded, **options):
    resolution, query = recorded
    persistence = PostgresAnnualRefundRecoverySession(session(setup, **options))
    provider = Provider(resolution)
    return AnnualRefundRecoveryService(persistence, provider), persistence, provider, query


def test_created_request_load_is_source_free_and_recovery_allocates_nothing(setup, paid, recorded, monkeypatch):
    service, persistence, provider, query = recovery(setup, recorded)
    async def forbidden(*args):
        pytest.fail('Recovery reached source resolution or claim')
    monkeypatch.setattr(persistence._refunds, '_source_facts', forbidden)
    monkeypatch.setattr(persistence._refunds, 'claim_refund', forbidden)
    initial = state(setup)
    loaded = asyncio.run(persistence.load_refund_recovery(query))
    assert state(setup) == initial and loaded.resolution == recorded[0]
    result = asyncio.run(service.recover_refund(query))
    assert result.resolution.request == recorded[0].request
    assert result.resolution.operation.intent == recorded[0].operation.intent
    assert provider.reads == [recorded[0].operation.intent]
    assert state(setup) == initial == (1, 1, 1)
    current = asyncio.run(session(setup).load_checkout(query.company_id, query.purchase_id))
    assert current.status.value == 'refunded' and current.observation.refunded_minor == 149000
    assert current.offer == paid.offer and current.renewal_canceled_at


@pytest.mark.parametrize('mode', ['company', 'purchase', 'request', 'actor', 'mfa', 'another_owner', 'support_only'])
def test_foreign_or_unauthorized_target_never_reads_provider(setup, recorded, mode):
    options = {}
    query = recorded[1]
    if mode == 'company':
        query = replace(query, company_id=CompanyId(str(uuid4())))
    elif mode == 'purchase':
        query = replace(query, purchase_id=AnnualPurchaseId(str(uuid4())))
    elif mode == 'request':
        query = replace(query, refund_request_id=AnnualRefundRequestId(str(uuid4())))
    elif mode == 'mfa':
        options['fresh'] = False
    else:
        actor = ActorId(ActorKind.USER, UserId(str(setup[0]['outsider'])))
        options['actor'] = actor
        query = replace(query, actor_id=actor)
        if mode == 'support_only':
            grant_open_support(setup, actor)
        if mode == 'another_owner':
            with psycopg.connect(DATABASE_URL) as connection:
                insert(connection, 'public.company_memberships', {'company_id': setup[0]['company'],
                    'user_id': actor.subject.value, 'role': 'owner', 'accepted_at': datetime.now(UTC)})
    service, _, provider, _ = recovery(setup, recorded, **options)
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(query))
    assert provider.reads == [] and state(setup) == (1, 1, 1)


def test_unbound_request_cannot_allocate_when_competing_operation_fails(setup, paid, recorded):
    other = command(setup, paid)
    deferred = asyncio.run(store(setup, source(paid, other)).claim_refund(other))
    assert deferred.resolution.operation is None
    query = recovery_query(setup, other)
    original = recorded[0]
    asyncio.run(store(setup).settle_refund(original, refund_observation(original, AnnualProviderStatus.FAILED)))
    service, _, provider, _ = recovery(setup, recorded)
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(query))
    assert provider.reads == [] and state(setup) == (2, 2, 1)


def test_same_case_requests_may_share_one_original_operation(setup, paid, recorded):
    second = replace(recorded[0].request, idempotency_key=IdempotencyKey(str(uuid4())))
    shared = asyncio.run(store(setup).claim_refund(second))
    assert not shared.newly_claimed
    query = recovery_query(setup, second)
    service, _, provider, _ = recovery(setup, recorded)
    result = asyncio.run(service.recover_refund(query))
    assert result.refund_request_id == query.refund_request_id
    assert result.resolution.request == second
    assert provider.reads == [recorded[0].operation.intent]
    assert state(setup) == (1, 2, 1)


def grant_open_support(setup, actor):
    case_id = uuid4()
    now = datetime.now(UTC)
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection, 'public.support_operators', {'user_id': actor.subject.value, 'role': 'admin', 'active': True})
        insert(connection, 'public.support_access_grants', {'case_id': case_id, 'company_id': setup[0]['company'],
            'operator_user_id': actor.subject.value, 'reason': 'customer_request', 'scopes': ['billing'],
            'starts_at': now-timedelta(hours=1), 'expires_at': now+timedelta(hours=1), 'granted_by': actor.subject.value})
        insert(connection, 'public.support_case_openings', {'actor_id': actor.subject.value,
            'operation_id': uuid4(), 'case_id': case_id, 'company_id': setup[0]['company']})
    return case_id


@pytest.mark.parametrize('mode', ['owner', 'mfa'])
def test_owner_or_mfa_loss_during_provider_read_blocks_settlement_even_with_support(setup, recorded, mode):
    service, persistence, provider, query = recovery(setup, recorded)
    support_case = grant_open_support(setup, setup[1])
    persistence._refunds._support_case_id = str(support_case)
    async def revoke():
        if mode == 'owner':
            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',
                                   (str(query.company_id), str(query.actor_id.subject)))
        else:
            persistence._database._verified = session(setup, fresh=False)._verified
    provider.before_response = revoke
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(query))
    if mode == 'owner':
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute('update public.company_memberships set accepted_at=now() where company_id=%s and user_id=%s',
                               (str(query.company_id), str(query.actor_id.subject)))
    current = asyncio.run(session(setup).load_checkout(query.company_id, query.purchase_id))
    assert current.observation.refunded_minor == 0 and current.status.value == 'paid'
    assert state(setup) == (1, 1, 1)
    restored, _, _, _ = recovery(setup, recorded)
    assert asyncio.run(restored.recover_refund(query)).resolution.operation.intent == recorded[0].operation.intent


def interleave_owner_recovery_sql(persistence, execute, support_case=None):
    """Inject a fault around real SQL under the existing transaction and RLS."""
    transaction = persistence._database._transaction

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

    persistence._database._transaction = interleaved


@pytest.mark.parametrize('mode', ['owner', 'mfa'])
@pytest.mark.parametrize('point', ['before_purchase', 'between_updates', 'after_operation'])
@pytest.mark.parametrize('opened_support', [False, True])
def test_owner_recovery_late_authority_loss_rolls_back_final_settlement_write(
    setup, recorded, mode, point, opened_support,
):
    from test_annual_support_runtime import fingerprint
    service, persistence, provider, query = recovery(setup, recorded)
    support_case = grant_open_support(setup, setup[1]) if opened_support else None
    before = fingerprint(setup)
    interrupted = []
    write_rows = []
    if mode == 'mfa':
        claims = json.loads(persistence._database._verified.claims_json)
        claims['amr'][0]['timestamp'] = datetime.now(UTC).timestamp() - 899.5
        persistence._database._verified = _VerifiedActor(query.actor_id, json.dumps(claims))

    async def lose_authority():
        assert not interrupted
        if mode == 'mfa':
            await asyncio.sleep(.65)
        else:
            with psycopg.connect(DATABASE_URL) as other:
                other.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',
                              (str(query.company_id), str(query.actor_id.subject)))
        interrupted.append(True)

    async def execute(connection, sql, *args, **kwargs):
        statement = str(sql).strip().lower()
        purchase_write = statement.startswith('update billing.annual_purchases')
        operation_write = statement.startswith('update billing.annual_operations')
        if purchase_write and point == 'before_purchase':
            await lose_authority()
        result = await connection.execute(sql, *args, **kwargs)
        if purchase_write or operation_write:
            write_rows.append(result.rowcount)
        if ((purchase_write and point == 'between_updates') or
                (operation_write and point == 'after_operation')):
            await lose_authority()
        return result

    interleave_owner_recovery_sql(persistence, execute, support_case)
    try:
        outcome = asyncio.run(service.recover_refund(query))
    except BillingError as error:
        outcome = error
    finally:
        if mode == 'owner':
            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute('update public.company_memberships set accepted_at=now() where company_id=%s and user_id=%s',
                                   (str(query.company_id), str(query.actor_id.subject)))
    assert interrupted == [True]
    assert write_rows == {'before_purchase': [0], 'between_updates': [1, 0], 'after_operation': [1, 1]}[point]
    assert provider.reads == [recorded[0].operation.intent]
    assert isinstance(outcome, BillingError), (
        f'Owner recovery returned after authority loss; persisted settlement changed={fingerprint(setup) != before}'
    )
    assert outcome.code == ('BILLING_FORBIDDEN' if mode == 'owner' else 'BILLING_STEP_UP_REQUIRED')
    assert fingerprint(setup) == before


@pytest.mark.parametrize('fault', [
    'miss_purchase', 'miss_operation', 'sql_before_purchase', 'sql_after_purchase', 'sql_after_operation',
])
def test_owner_recovery_failed_writes_roll_back_without_masking_sql_failure(setup, recorded, fault):
    from test_annual_support_runtime import fingerprint
    service, persistence, provider, query = recovery(setup, recorded)
    before = fingerprint(setup)
    failed_transactions = []
    after_failure = []
    write_rows = []

    async def fail(connection):
        try:
            await connection.execute('select 1 / 0')
        except psycopg.errors.DivisionByZero:
            failed_transactions.append(connection.info.transaction_status)
            raise

    async def execute(connection, sql, *args, **kwargs):
        if failed_transactions:
            after_failure.append(sql)
        statement = str(sql).strip().lower()
        purchase_write = statement.startswith('update billing.annual_purchases')
        operation_write = statement.startswith('update billing.annual_operations')
        if purchase_write and fault == 'sql_before_purchase':
            await fail(connection)
        missed = (purchase_write and fault == 'miss_purchase') or (operation_write and fault == 'miss_operation')
        # Controlled write-failure injection uses real SQL/cursors and unchanged
        # authorization; it does not pretend a held row can disappear naturally.
        result = await connection.execute(sql + ' and false' if missed else sql, *args, **kwargs)
        if purchase_write or operation_write:
            write_rows.append(result.rowcount)
        if ((purchase_write and fault == 'sql_after_purchase') or
                (operation_write and fault == 'sql_after_operation')):
            await fail(connection)
        return result

    interleave_owner_recovery_sql(persistence, execute)
    with pytest.raises(BillingError) as denied:
        asyncio.run(service.recover_refund(query))
    assert denied.value.code == 'BILLING_DEPENDENCY_UNAVAILABLE'
    assert provider.reads == [recorded[0].operation.intent]
    assert after_failure == []
    if fault.startswith('sql'):
        assert failed_transactions == [psycopg.pq.TransactionStatus.INERROR]
    else:
        assert write_rows == ([0] if fault == 'miss_purchase' else [1, 0])
    assert fingerprint(setup) == before
    restored, _, _, _ = recovery(setup, recorded)
    assert asyncio.run(restored.recover_refund(query)).resolution.operation.intent == recorded[0].operation.intent


@pytest.mark.parametrize('status', [AnnualProviderStatus.CONFIRMED, AnnualProviderStatus.FAILED])
def test_terminal_recovery_has_no_provider_or_new_attempt(setup, recorded, status):
    resolution, query = recorded
    terminal = asyncio.run(store(setup).settle_refund(resolution, refund_observation(resolution, status)))
    service = AnnualRefundRecoveryService(PostgresAnnualRefundRecoverySession(session(setup)), None)
    result = asyncio.run(service.recover_refund(query))
    assert result.resolution == terminal and state(setup) == (1, 1, 1)


def test_concurrent_recoveries_preserve_exact_request_and_money(setup, recorded):
    async def run():
        calls = [recovery(setup, recorded) for _ in range(5)]
        results = await asyncio.gather(*(service.recover_refund(query) for service, _, _, query in calls))
        assert len({result.resolution.operation.intent.operation_id for result in results}) == 1
    asyncio.run(run())
    assert state(setup) == (1, 1, 1)
    current = asyncio.run(session(setup).load_checkout(recorded[1].company_id, recorded[1].purchase_id))
    assert current.observation.refunded_minor == 149000


def test_lost_settlement_response_recovers_committed_result_without_provider(setup, recorded):
    service, persistence, provider, query = recovery(setup, recorded)
    original_settle = persistence.settle_refund_recovery
    async def lose(result, observed):
        await original_settle(result, observed)
        raise BillingError.unavailable()
    persistence.settle_refund_recovery = lose
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(query))
    replay = AnnualRefundRecoveryService(PostgresAnnualRefundRecoverySession(session(setup)), None)
    result = asyncio.run(replay.recover_refund(query))
    assert result.resolution.operation.observation.status is AnnualProviderStatus.CONFIRMED
    assert provider.reads == [recorded[0].operation.intent] and state(setup) == (1, 1, 1)


def test_original_partial_operation_survives_later_capture_and_refund_growth(setup, purchase):
    partial = asyncio.run(session(setup).settle_checkout(purchase, observation(purchase, captured=50000)))
    request = command(setup, partial)
    original = asyncio.run(store(setup, source(partial, request)).claim_refund(request)).resolution
    query = recovery_query(setup, request)
    asyncio.run(session(setup).settle_checkout(purchase, observation(purchase, captured=149000, status=AnnualProviderStatus.CONFIRMED)))
    service, _, provider, _ = recovery(setup, (original, query))
    provider.changes = {'captured_minor': 149000}
    first = asyncio.run(service.recover_refund(query))
    assert first.resolution.operation.intent.amount_minor == 50000
    next_request = replace(request, idempotency_key=IdempotencyKey(str(uuid4())))
    next_operation = asyncio.run(store(setup).claim_refund(next_request)).resolution
    asyncio.run(store(setup).settle_refund(next_operation, refund_observation(next_operation)))
    replay = AnnualRefundRecoveryService(PostgresAnnualRefundRecoverySession(session(setup)), None)
    assert asyncio.run(replay.recover_refund(query)) == first
    current = asyncio.run(session(setup).load_checkout(query.company_id, query.purchase_id))
    assert current.observation.refunded_minor == 149000 and state(setup) == (1, 2, 2)


def test_late_unknown_observation_cannot_regress_concurrent_confirmation(setup, recorded):
    async def run():
        late, _, late_provider, query = recovery(setup, recorded)
        fast, _, _, _ = recovery(setup, recorded)
        started, release = asyncio.Event(), asyncio.Event()
        async def wait_for_confirmation():
            started.set()
            await release.wait()
        late_provider.status = AnnualProviderStatus.UNKNOWN
        late_provider.before_response = wait_for_confirmation
        pending = asyncio.create_task(late.recover_refund(query))
        await asyncio.wait_for(started.wait(), 3)
        confirmed = await fast.recover_refund(query)
        release.set()
        assert await pending == confirmed
    asyncio.run(run())
    assert state(setup) == (1, 1, 1)


@pytest.mark.parametrize('phase', ['load', 'settlement'])
def test_owner_loss_while_waiting_for_purchase_lock_cannot_reuse_prior_authority(setup, recorded, phase):
    async def run():
        _, persistence, _, query = recovery(setup, recorded)
        loaded = await persistence.load_refund_recovery(query)
        entered = asyncio.Event()
        original_load = persistence._database._load
        async def load(*args, **kwargs):
            entered.set()
            return await original_load(*args, **kwargs)
        persistence._database._load = load
        with psycopg.connect(DATABASE_URL) as lock:
            scoped(lock, setup[1].subject)
            lock.execute('select id from billing.annual_purchases where id=%s for update', (str(query.purchase_id),))
            work = (persistence.load_refund_recovery(query) if phase == 'load' else
                    persistence.settle_refund_recovery(loaded, refund_observation(recorded[0])))
            pending = asyncio.create_task(work)
            await asyncio.wait_for(entered.wait(), 3)
            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',
                                   (str(query.company_id), str(query.actor_id.subject)))
            lock.commit()
            with pytest.raises(BillingError):
                await pending
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute('update public.company_memberships set accepted_at=now() where company_id=%s and user_id=%s',
                               (str(query.company_id), str(query.actor_id.subject)))
        current = await session(setup).load_checkout(query.company_id, query.purchase_id)
        assert current.observation.refunded_minor == 0
    asyncio.run(run())
    assert state(setup) == (1, 1, 1)


@pytest.mark.parametrize('mode', ['request_fingerprint', 'case', 'year', 'operation_id', 'created_at',
                                  'operation_fingerprint', 'status', 'observation_money'])
def test_malformed_retained_rows_fail_closed_without_provider_or_writes(setup, recorded, mode):
    """Inject row corruption at the real DB read seam; never weaken fixture triggers."""
    service, persistence, provider, query = recovery(setup, recorded)
    original_transaction = persistence._database._transaction

    class Cursor:
        def __init__(self, cursor, statement):
            self.cursor, self.statement = cursor, statement

        async def fetchone(self):
            row = await self.cursor.fetchone()
            if row is None:
                return row
            if 'select * from billing.annual_refund_requests' in self.statement and mode == 'request_fingerprint':
                return row | {'request_fingerprint': 'f' * 64}
            if 'select * from billing.annual_operations where id=' not in self.statement:
                return row
            if mode == 'case':
                return row | {'refund_case_id': uuid4()}
            if mode == 'year':
                return row | {'income_year': 2025}
            if mode == 'operation_id':
                return row | {'id': uuid4()}
            if mode == 'created_at':
                return row | {'created_at': row['created_at'] - timedelta(days=1)}
            if mode == 'operation_fingerprint':
                return row | {'request_fingerprint': 'f' * 64}
            if mode == 'status':
                return row | {'status': 'confirmed'}
            if mode == 'observation_money':
                observed = refund_observation(recorded[0])
                from talli_backend.adapters.postgres_annual_checkout import _record
                return row | {'status': 'confirmed', 'observation': _record(observed)}
            return row

    class Connection:
        def __init__(self, connection):
            self.connection = connection

        async def execute(self, statement, params=None):
            return Cursor(await self.connection.execute(statement, params), statement)

    async def corrupt_transaction(work):
        return await original_transaction(lambda connection: work(Connection(connection)))
    persistence._database._transaction = corrupt_transaction
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(query))
    assert provider.reads == [] and state(setup) == (1, 1, 1)


def test_settlement_cannot_swap_between_two_requests_sharing_one_operation(setup, recorded):
    original, query = recorded
    second = replace(original.request, idempotency_key=IdempotencyKey(str(uuid4())))
    asyncio.run(store(setup).claim_refund(second))
    _, persistence, _, _ = recovery(setup, recorded)
    loaded = asyncio.run(persistence.load_refund_recovery(query))
    altered = replace(loaded, refund_request_id=recovery_query(setup, second).refund_request_id)
    with pytest.raises(BillingError):
        asyncio.run(persistence.settle_refund_recovery(altered, refund_observation(original)))
    current = asyncio.run(session(setup).load_checkout(query.company_id, query.purchase_id))
    assert current.observation.refunded_minor == 0 and state(setup) == (1, 2, 1)


def test_http_composition_uses_real_recovery_database_port_without_new_claim(setup, recorded):
    """Only token verification and provider observation are synthetic seams."""
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from talli_backend.adapters.supabase_annual_billing import SupabaseAnnualBillingAdapter
    from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration
    from talli_backend.main import create_app

    adapter = SupabaseAnnualBillingAdapter(LedgerSupabaseConfiguration(
        url='https://auth.example.test', anon_key='synthetic-auth', database_url=DATABASE_URL,
    ))
    async def verified(token):
        assert token == 'synthetic-verified-owner'
        return SimpleNamespace(_verified=session(setup)._verified)
    adapter._authentication.session = verified
    provider = Provider(recorded[0])
    api = TestClient(create_app(annual_billing_session_factory=adapter, annual_billing_provider=provider))
    query = recorded[1]
    result = api.post('/api/v1/billing/annual/refund-recoveries',
        headers={'Authorization': 'Bearer synthetic-verified-owner'},
        json={'companyId': str(query.company_id), 'purchaseId': str(query.purchase_id),
              'refundRequestId': str(query.refund_request_id)})
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'confirmed'
    assert provider.reads == [recorded[0].operation.intent] and state(setup) == (1, 1, 1)
