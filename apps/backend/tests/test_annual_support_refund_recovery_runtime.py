"""Real case-bound RLS recovery of owner receipts; source/provider fixtures are synthetic."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import json
from uuid import uuid4

import psycopg
import pytest

from test_annual_refund_runtime import (
    DATABASE_URL, admitted, command, insert, paid, purchase, refund_observation,
    scoped, session, setup, source, state, store, test_role_authority,
)
from test_annual_refund_recovery_runtime import recorded, recovery_query, Provider
from test_annual_support_runtime import support, fingerprint
from talli_backend.adapters.postgres_annual_refund import (
    PostgresAnnualRefundRecoverySession, PostgresAnnualSupportRefundRecoverySession,
)
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.billing.annual_refund import AnnualRefundRecoveryService, AnnualSupportRefundRecoveryService
from talli_backend.modules.billing.public import (
    AnnualProviderStatus, AnnualPurchaseId, AnnualRefundRequestId, AnnualSupportCaseId,
    AnnualSupportRefundRecoveryQuery, BillingError,
)
from talli_backend.shared.kernel import CompanyId

pytestmark = pytest.mark.billing_database


def recovery(setup, recorded, opened=None, **options):
    opened = opened or support(setup)
    original, owner_query = recorded
    query = AnnualSupportRefundRecoveryQuery(
        owner_query.company_id, owner_query.purchase_id, owner_query.refund_request_id,
        opened.support_case_id, opened.actor_id,
    )
    persistence = PostgresAnnualSupportRefundRecoverySession(
        session(setup, actor=opened.actor_id, current=False, **options),
    )
    provider = Provider(original)
    return AnnualSupportRefundRecoveryService(persistence, provider), persistence, provider, query


def revoke(connection, query, mode):
    if mode == 'admin':
        connection.execute('update public.support_operators set active=false where user_id=%s',
                           (str(query.actor_id.subject),))
    else:
        connection.execute(
            "update public.support_access_grants set revoked_at=%s,revoked_by=%s,revocation_reason='case_closed' where case_id=%s",
            (datetime.now(UTC), str(query.actor_id.subject), str(query.support_case_id)),
        )


def test_different_operator_recovers_owner_receipt_without_claim_binding_or_owner_membership(setup, recorded, monkeypatch):
    service, persistence, provider, query = recovery(setup, recorded)
    original = recorded[0]
    assert original.request.actor_id != query.actor_id
    async def forbidden(*args):
        pytest.fail('Recovery reached new refund claim or source resolution')
    monkeypatch.setattr(persistence._refunds, '_source_facts', forbidden)
    monkeypatch.setattr(persistence._refunds, 'claim_refund', forbidden)
    before = fingerprint(setup)
    loaded = asyncio.run(persistence.load_refund_recovery(query))
    assert loaded.resolution == original and fingerprint(setup) == before
    # The same operator still cannot use owner recovery, even with a valid case.
    owner_port = PostgresAnnualRefundRecoverySession(persistence._database)
    with pytest.raises(BillingError) as denied:
        asyncio.run(owner_port.load_refund_recovery(replace(recorded[1], actor_id=query.actor_id)))
    assert denied.value.code == 'BILLING_FORBIDDEN'
    result = asyncio.run(service.recover_refund(query))
    assert result.resolution.request == original.request
    assert result.resolution.operation.intent == original.operation.intent
    assert provider.reads == [original.operation.intent] and state(setup) == (1, 1, 1)
    current = asyncio.run(session(setup).load_checkout(query.company_id, query.purchase_id))
    assert current.observation.refunded_minor == 149000 and current.status.value == 'refunded'
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute('select count(*) from public.company_memberships where company_id=%s and user_id=%s',
            (str(query.company_id), str(query.actor_id.subject))).fetchone()[0] == 0


@pytest.mark.parametrize('mode', ['non_admin', 'inactive', 'unopened', 'wrong_scope', 'expired', 'future', 'revoked',
                                  'stale_mfa', 'wrong_case', 'wrong_company', 'wrong_purchase', 'wrong_request', 'owner', 'actor'])
def test_support_cannot_fall_back_to_owner_or_read_foreign_target(setup, recorded, mode):
    opened = support(setup, mode)
    service, persistence, provider, query = recovery(setup, recorded, opened, fresh=mode != 'stale_mfa')
    if mode == 'wrong_case': query = replace(query, support_case_id=AnnualSupportCaseId(str(uuid4())))
    if mode == 'wrong_company': query = replace(query, company_id=CompanyId(str(uuid4())))
    if mode == 'wrong_purchase': query = replace(query, purchase_id=AnnualPurchaseId(str(uuid4())))
    if mode == 'wrong_request': query = replace(query, refund_request_id=AnnualRefundRequestId(str(uuid4())))
    if mode in ('owner', 'actor'):
        query = replace(query, actor_id=setup[1])
        if mode == 'owner':
            service = AnnualSupportRefundRecoveryService(PostgresAnnualSupportRefundRecoverySession(session(setup)), provider)
    before = fingerprint(setup)
    with pytest.raises(BillingError) as denied:
        asyncio.run(service.recover_refund(query))
    if mode == 'stale_mfa': assert denied.value.code == 'BILLING_STEP_UP_REQUIRED'
    assert provider.reads == [] and fingerprint(setup) == before


@pytest.mark.parametrize('mode', ['admin', 'case', 'mfa'])
def test_authority_lost_during_provider_read_cannot_settle_as_original_owner(setup, recorded, mode):
    service, persistence, provider, query = recovery(setup, recorded)
    async def change():
        if mode == 'mfa':
            persistence._database._verified = session(setup, actor=query.actor_id, fresh=False)._verified
        else:
            with psycopg.connect(DATABASE_URL) as connection:
                revoke(connection, query, mode)
    provider.before_response = change
    with pytest.raises(BillingError) as denied:
        asyncio.run(service.recover_refund(query))
    assert denied.value.code == ('BILLING_STEP_UP_REQUIRED' if mode == 'mfa' else 'BILLING_FORBIDDEN')
    assert provider.reads == [recorded[0].operation.intent] and state(setup) == (1, 1, 1)
    current = asyncio.run(session(setup).load_checkout(query.company_id, query.purchase_id))
    assert current.observation.refunded_minor == 0 and current.status.value == 'paid'


@pytest.mark.parametrize('phase', ['load', 'settlement'])
@pytest.mark.parametrize('locked', ['purchase', 'refund_operation'])
@pytest.mark.parametrize('mode', ['admin', 'case', 'mfa'])
def test_real_lock_wait_rechecks_case_admin_and_elapsed_mfa(setup, recorded, phase, locked, mode):
    async def run():
        _, persistence, _, query = recovery(setup, recorded)
        loaded = await persistence.load_refund_recovery(query)
        if mode == 'mfa':
            claims = json.loads(persistence._database._verified.claims_json)
            claims['amr'][0]['timestamp'] = datetime.now(UTC).timestamp() - 899.5
            persistence._database._verified = _VerifiedActor(query.actor_id, json.dumps(claims))
        transaction = persistence._database._transaction
        async def patient_transaction(work):
            async def patient_work(connection):
                await connection.execute("set local lock_timeout='3s'")
                return await work(connection)
            return await transaction(patient_work)
        persistence._database._transaction = patient_transaction
        with psycopg.connect(DATABASE_URL) as holder, psycopg.connect(DATABASE_URL, autocommit=True) as monitor:
            scoped(holder, setup[1].subject)
            if locked == 'purchase':
                holder.execute('select id from billing.annual_purchases where id=%s for update', (str(query.purchase_id),))
            else:
                holder.execute('select id from billing.annual_operations where id=%s for update',
                               (str(recorded[0].operation.intent.operation_id),))
            work = (persistence.load_refund_recovery(query) if phase == 'load' else
                    persistence.settle_refund_recovery(query, loaded, refund_observation(recorded[0])))
            pending = asyncio.create_task(work)
            try:
                for _ in range(200):
                    waiting = monitor.execute('select count(*) from pg_stat_activity where %s=any(pg_blocking_pids(pid))',
                                              (holder.info.backend_pid,)).fetchone()[0]
                    if waiting: break
                    await asyncio.sleep(.005)
                assert waiting and not pending.done(), 'Must observe an actual independent SQL lock wait'
                if mode == 'mfa': await asyncio.sleep(.65)
                else: revoke(monitor, query, mode)
            finally:
                holder.rollback()
            with pytest.raises(BillingError) as denied:
                await asyncio.wait_for(pending, 4)
            assert denied.value.code == ('BILLING_STEP_UP_REQUIRED' if mode == 'mfa' else 'BILLING_FORBIDDEN')
        current = await session(setup).load_checkout(query.company_id, query.purchase_id)
        assert current.observation.refunded_minor == 0
    asyncio.run(run())
    assert state(setup) == (1, 1, 1)


@pytest.mark.parametrize('late_actor', ['owner', 'operator'])
def test_concurrent_owner_and_operator_unknown_cannot_regress_confirmation(setup, recorded, late_actor):
    async def run():
        operator, _, operator_provider, operator_query = recovery(setup, recorded)
        owner_provider = Provider(recorded[0])
        owner = AnnualRefundRecoveryService(PostgresAnnualRefundRecoverySession(session(setup)), owner_provider)
        owner_call = (owner, owner_provider, recorded[1])
        operator_call = (operator, operator_provider, operator_query)
        (late, late_provider, late_query), (fast, _, fast_query) = (
            (owner_call, operator_call) if late_actor == 'owner' else (operator_call, owner_call))
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed():
            started.set()
            await release.wait()
        late_provider.status = AnnualProviderStatus.UNKNOWN
        late_provider.before_response = delayed
        pending = asyncio.create_task(late.recover_refund(late_query))
        await asyncio.wait_for(started.wait(), 3)
        try:
            confirmed = await fast.recover_refund(fast_query)
        finally:
            release.set()
        assert await pending == confirmed
        assert confirmed.resolution.request == recorded[0].request
    asyncio.run(run())
    assert state(setup) == (1, 1, 1)
    current = asyncio.run(session(setup).load_checkout(recorded[1].company_id, recorded[1].purchase_id))
    assert current.observation.refunded_minor == 149000


@pytest.mark.parametrize('status', [AnnualProviderStatus.CONFIRMED, AnnualProviderStatus.FAILED])
def test_terminal_replay_is_provider_free_but_still_requires_current_case(setup, recorded, status):
    original = recorded[0]
    terminal = asyncio.run(store(setup).settle_refund(original, refund_observation(original, status)))
    _, persistence, _, query = recovery(setup, recorded)
    service = AnnualSupportRefundRecoveryService(persistence, None)
    assert asyncio.run(service.recover_refund(query)).resolution == terminal
    with psycopg.connect(DATABASE_URL) as connection:
        revoke(connection, query, 'case')
    with pytest.raises(BillingError) as denied:
        asyncio.run(service.recover_refund(query))
    assert denied.value.code == 'BILLING_FORBIDDEN' and state(setup) == (1, 1, 1)


def test_lost_support_commit_response_replays_without_provider(setup, recorded):
    service, persistence, provider, query = recovery(setup, recorded)
    settle = persistence.settle_refund_recovery
    async def lose(query, recovery, observation):
        await settle(query, recovery, observation)
        raise BillingError.unavailable()
    persistence.settle_refund_recovery = lose
    with pytest.raises(BillingError):
        asyncio.run(service.recover_refund(query))
    replay = AnnualSupportRefundRecoveryService(persistence, None)
    assert asyncio.run(replay.recover_refund(query)).resolution.operation.observation.status is AnnualProviderStatus.CONFIRMED
    assert provider.reads == [recorded[0].operation.intent] and state(setup) == (1, 1, 1)


def test_unbound_receipt_cannot_allocate_after_competing_refund_fails(setup, paid, recorded):
    request = command(setup, paid)
    assert asyncio.run(store(setup, source(paid, request)).claim_refund(request)).resolution.operation is None
    deferred_query = recovery_query(setup, request)
    asyncio.run(store(setup).settle_refund(recorded[0], refund_observation(recorded[0], AnnualProviderStatus.FAILED)))
    service, _, provider, query = recovery(setup, recorded)
    before = fingerprint(setup)
    with pytest.raises(BillingError) as denied:
        asyncio.run(service.recover_refund(replace(query, refund_request_id=deferred_query.refund_request_id)))
    assert denied.value.code == 'BILLING_NOT_FOUND' and provider.reads == []
    assert fingerprint(setup) == before and state(setup) == (2, 2, 1)


def test_real_verified_operator_composition_discovers_and_recovers_original_owner_receipt(setup, recorded):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from talli_backend.adapters.supabase_annual_billing import SupabaseAnnualBillingAdapter
    from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration
    from talli_backend.application.ledger_workflow import LedgerAuthenticationError
    from talli_backend.main import create_app

    opened = support(setup)
    verified = session(setup, actor=opened.actor_id, current=False)._verified
    assert verified.actor_id != recorded[0].request.actor_id
    class Authentication:
        async def session(self, token):
            if token != 'verified-operator-fixture': raise LedgerAuthenticationError()
            return SimpleNamespace(_verified=verified)
    factory = SupabaseAnnualBillingAdapter(LedgerSupabaseConfiguration(
        url='http://127.0.0.1:1', anon_key='local-unused', database_url=DATABASE_URL,
    ))
    factory._authentication = Authentication()
    provider = Provider(recorded[0])
    api = TestClient(create_app(annual_billing_session_factory=factory, annual_billing_provider=provider))
    headers = {'Authorization': 'Bearer verified-operator-fixture'}
    scope = {'companyId': str(recorded[1].company_id), 'purchaseId': str(recorded[1].purchase_id),
             'supportCaseId': str(opened.support_case_id)}
    before = fingerprint(setup)
    targets = api.get('/api/v1/billing/annual/support/refund-recovery-targets', params=scope, headers=headers)
    assert targets.status_code == 200, targets.text
    assert targets.json()['targets'][0]['refundRequestId'] == str(recorded[1].refund_request_id)
    assert targets.json()['targets'][0]['status'] == 'created'
    assert fingerprint(setup) == before and provider.reads == []
    body = scope | {'refundRequestId': str(recorded[1].refund_request_id)}
    result = api.post('/api/v1/billing/annual/support/refund-recoveries', json=body, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json() == body | {'incomeYear': 2026, 'status': 'confirmed'}
    assert result.headers['cache-control'] == 'no-store' and provider.reads == [recorded[0].operation.intent]
    assert str(recorded[0].request.actor_id.subject) not in result.text
    assert state(setup) == (1, 1, 1)
    with psycopg.connect(DATABASE_URL) as connection:
        revoke(connection, SimpleNamespace(actor_id=opened.actor_id, support_case_id=opened.support_case_id), 'case')
    for response in (
        api.get('/api/v1/billing/annual/support/refund-recovery-targets', params=scope, headers=headers),
        api.post('/api/v1/billing/annual/support/refund-recoveries', json=body, headers=headers),
    ):
        assert response.status_code == 403 and 'targets' not in response.json() and response.json()['status'] == 403
        assert response.json()['code'] == 'BILLING_FORBIDDEN' and 'refundRequestId' not in response.json()


@pytest.mark.parametrize('point', ['before_purchase', 'between_updates', 'after_operation'])
@pytest.mark.parametrize('also_owner', [False, True])
def test_revocation_during_settlement_writes_rolls_back_instead_of_publishing_confirmation(setup, recorded, point, also_owner):
    service, persistence, provider, query = recovery(setup, recorded)
    if also_owner:
        with psycopg.connect(DATABASE_URL) as connection:
            insert(connection, 'public.company_memberships', {'company_id': setup[0]['company'],
                'user_id': query.actor_id.subject.value, 'role': 'owner', 'accepted_at': datetime.now(UTC)})
    transaction = persistence._database._transaction
    revoked = []
    def revoke_once():
        assert not revoked
        with psycopg.connect(DATABASE_URL) as connection:
            revoke(connection, query, 'case')
        revoked.append(True)
    class Connection:
        def __init__(self, wrapped): self.wrapped = wrapped
        def __getattr__(self, name): return getattr(self.wrapped, name)
        async def execute(self, sql, *args, **kwargs):
            statement = str(sql).strip().lower()
            purchase_write = statement.startswith('update billing.annual_purchases')
            operation_write = statement.startswith('update billing.annual_operations')
            if purchase_write and point == 'before_purchase': revoke_once()
            result = await self.wrapped.execute(sql, *args, **kwargs)
            if (purchase_write and point == 'between_updates') or (operation_write and point == 'after_operation'):
                revoke_once()
            return result
    async def interleaved(work):
        async def wrapped(connection): return await work(Connection(connection))
        return await transaction(wrapped)
    persistence._database._transaction = interleaved
    before = fingerprint(setup)
    with pytest.raises(BillingError) as denied:
        asyncio.run(service.recover_refund(query))
    assert denied.value.code == 'BILLING_FORBIDDEN' and revoked == [True]
    assert provider.reads == [recorded[0].operation.intent]
    assert fingerprint(setup) == before and state(setup) == (1, 1, 1)
