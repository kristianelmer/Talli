"""Actual PostgreSQL authorization and atomicity for recorded STOP recovery."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import json
from uuid import uuid4

import psycopg
import pytest

from test_annual_purchase_basis_runtime import DATABASE_URL, admitted, database_now, insert, scoped, test_role_authority
from test_annual_checkout_runtime import setup, session, counts, observation
from test_annual_cancellation_runtime import purchase
from test_annual_cleanup_runtime import prepare, cleanup_store, stop_observation, interleave_cleanup_sql
from test_annual_support_runtime import support, fingerprint
from test_annual_support_refund_recovery_runtime import revoke
from test_annual_refund_cleanup_runtime import refund, claim
from talli_backend.adapters.postgres_annual_support_cleanup import PostgresAnnualSupportCleanupRecoverySession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.billing.public import (
    AnnualProviderStatus, AnnualPurchaseId, AnnualSupportCaseId, AnnualSupportCleanupRecoveryQuery,
    BillingError, annual_support_cleanup_recovery_operations,
)
from talli_backend.shared.kernel import CompanyId

pytestmark = pytest.mark.billing_database


@pytest.fixture
def recorded_cleanup(setup, purchase):
    prepare(setup, purchase)
    return asyncio.run(cleanup_store(setup).claim_agreement_cleanup(purchase.offer.company_id, purchase.purchase_id)).cleanup


class Provider:
    production_enabled = False

    def __init__(self, original):
        self.original = original
        self.provider = original.provider
        self.account_reference = original.provider_account
        self.reads = []
        self.before_response = None
        self.status = AnnualProviderStatus.CONFIRMED

    async def execute(self, intent): pytest.fail('Operator recovery cannot execute STOP')

    async def reconcile(self, intent):
        self.reads.append(intent)
        if self.before_response: await self.before_response()
        return stop_observation(self.original, self.status)


def recovery(setup, original, opened=None, **options):
    opened = opened or support(setup)
    query = AnnualSupportCleanupRecoveryQuery(
        original.intent.company_id, original.purchase_id, opened.support_case_id, opened.actor_id,
    )
    persistence = PostgresAnnualSupportCleanupRecoverySession(session(setup, actor=opened.actor_id, current=False, **options))
    provider = Provider(original)
    return annual_support_cleanup_recovery_operations(persistence, provider), persistence, provider, query


def test_operator_without_owner_membership_recovers_original_and_preserves_purchase_and_receipt(setup, recorded_cleanup):
    service, persistence, provider, query = recovery(setup, recorded_cleanup)
    before = fingerprint(setup)
    assert asyncio.run(persistence.load_cleanup_recovery(query)) == recorded_cleanup
    assert fingerprint(setup) == before and not provider.reads
    result = asyncio.run(service.recover_cleanup(query))
    assert replace(result, observation=None) == recorded_cleanup
    assert provider.reads == [recorded_cleanup.intent] and counts(setup) == (1, 2)
    after = fingerprint(setup)
    assert before[0] == after[0] and before[2:] == after[2:]
    with psycopg.connect(DATABASE_URL) as connection:
        row = connection.execute('select created_by,intent,request_fingerprint from billing.annual_operations where id=%s',
            (str(recorded_cleanup.intent.operation_id),)).fetchone()
        assert str(row[0]) == str(setup[1].subject) != str(query.actor_id.subject)
        assert connection.execute('select count(*) from public.company_memberships where company_id=%s and user_id=%s',
            (str(query.company_id), str(query.actor_id.subject))).fetchone()[0] == 0
    old = next(value for value in before[1] if value['id'] == str(recorded_cleanup.intent.operation_id))
    assert row[1] == old['intent'] and row[2] == old['request_fingerprint']


def test_missing_stop_never_creates_operation_even_with_cancellation_receipt(setup, purchase):
    prepare(setup, purchase)
    opened = support(setup)
    query = AnnualSupportCleanupRecoveryQuery(purchase.offer.company_id, purchase.purchase_id, opened.support_case_id, opened.actor_id)
    persistence = PostgresAnnualSupportCleanupRecoverySession(session(setup, actor=opened.actor_id, current=False))
    before = fingerprint(setup)
    with pytest.raises(BillingError) as denied: asyncio.run(persistence.load_cleanup_recovery(query))
    assert denied.value.code == 'BILLING_NOT_FOUND' and fingerprint(setup) == before
    assert counts(setup) == (1, 1)


@pytest.mark.parametrize('checkout_status', [AnnualProviderStatus.CONFIRMED, AnnualProviderStatus.UNKNOWN])
def test_refund_bound_original_stop_recovers_without_manual_cancellation(setup, purchase, checkout_status):
    captured = asyncio.run(session(setup).settle_checkout(purchase,
        observation(purchase, captured=149000, status=checkout_status)))
    request, confirmed = refund(setup, captured)
    original = claim(setup, captured).cleanup
    assert original.refund_request_id is not None and original.cancellation_id is None
    service, persistence, provider, query = recovery(setup, original)
    before = fingerprint(setup)
    result = asyncio.run(service.recover_cleanup(query))
    after = fingerprint(setup)
    assert replace(result, observation=None) == original
    assert before[0] == after[0] and before[2:] == after[2:]
    assert provider.reads == [original.intent]
    assert after[4] == []


@pytest.mark.parametrize('mode', ['non_admin', 'inactive', 'unopened', 'wrong_scope', 'expired', 'future', 'revoked',
    'stale_mfa', 'wrong_case', 'wrong_company', 'wrong_purchase', 'owner', 'actor'])
def test_case_authority_and_exact_target_are_mandatory(setup, recorded_cleanup, mode):
    opened = support(setup, mode)
    service, persistence, provider, query = recovery(setup, recorded_cleanup, opened, fresh=mode != 'stale_mfa')
    if mode == 'wrong_case': query = replace(query, support_case_id=AnnualSupportCaseId(str(uuid4())))
    elif mode == 'wrong_company': query = replace(query, company_id=CompanyId(str(uuid4())))
    elif mode == 'wrong_purchase': query = replace(query, purchase_id=AnnualPurchaseId(str(uuid4())))
    elif mode in ('owner', 'actor'):
        query = replace(query, actor_id=setup[1])
        if mode == 'owner': service = annual_support_cleanup_recovery_operations(PostgresAnnualSupportCleanupRecoverySession(session(setup)), provider)
    before = fingerprint(setup)
    with pytest.raises(BillingError): asyncio.run(service.recover_cleanup(query))
    assert not provider.reads and fingerprint(setup) == before


def test_confirmed_replay_needs_current_case_but_no_provider(setup, recorded_cleanup):
    terminal = asyncio.run(cleanup_store(setup).settle_agreement_cleanup(recorded_cleanup, stop_observation(recorded_cleanup)))
    _, persistence, provider, query = recovery(setup, recorded_cleanup)
    service = annual_support_cleanup_recovery_operations(persistence, None)
    assert asyncio.run(service.recover_cleanup(query)) == terminal
    with psycopg.connect(DATABASE_URL) as connection: revoke(connection, query, 'case')
    with pytest.raises(BillingError): asyncio.run(service.recover_cleanup(query))
    assert not provider.reads


@pytest.mark.parametrize('phase', ['load', 'settlement'])
@pytest.mark.parametrize('locked', ['purchase', 'checkout', 'stop'])
@pytest.mark.parametrize('mode', ['case', 'mfa'])
def test_actual_lock_wait_rechecks_open_case_and_elapsed_mfa(setup, recorded_cleanup, phase, locked, mode):
    async def run():
        _, persistence, _, query = recovery(setup, recorded_cleanup)
        loaded = await persistence.load_cleanup_recovery(query)
        if mode == 'mfa':
            claims = json.loads(persistence._database._verified.claims_json)
            claims['amr'][0]['timestamp'] = database_now().timestamp() - 899.5
            persistence._database._verified = _VerifiedActor(query.actor_id, json.dumps(claims))
        transaction = persistence._database._transaction
        async def patient(work):
            async def wrapped(connection):
                await connection.execute("set local lock_timeout='3s'")
                return await work(connection)
            return await transaction(wrapped)
        persistence._database._transaction = patient
        before = fingerprint(setup)
        with psycopg.connect(DATABASE_URL) as holder, psycopg.connect(DATABASE_URL, autocommit=True) as monitor:
            scoped(holder, setup[1].subject)
            if locked == 'purchase':
                holder.execute('select id from billing.annual_purchases where id=%s for update', (str(query.purchase_id),))
            else:
                holder.execute('select id from billing.annual_operations where purchase_id=%s and operation=%s for update',
                    (str(query.purchase_id), 'checkout' if locked == 'checkout' else 'stop_agreement'))
            pending = asyncio.create_task(persistence.load_cleanup_recovery(query) if phase == 'load' else
                persistence.settle_cleanup_recovery(query, loaded, stop_observation(loaded)))
            try:
                for _ in range(200):
                    waiting = monitor.execute('select count(*) from pg_stat_activity where %s=any(pg_blocking_pids(pid))',
                        (holder.info.backend_pid,)).fetchone()[0]
                    if waiting: break
                    await asyncio.sleep(.005)
                assert waiting and not pending.done(), 'Must observe an actual independent SQL lock wait'
                if mode == 'mfa': await asyncio.sleep(.65)
                else: revoke(monitor, query, mode)
            finally: holder.rollback()
            with pytest.raises(BillingError) as denied: await asyncio.wait_for(pending, 4)
            assert denied.value.code == ('BILLING_STEP_UP_REQUIRED' if mode == 'mfa' else 'BILLING_FORBIDDEN')
        assert fingerprint(setup) == before
    asyncio.run(run())


@pytest.mark.parametrize('point', ['before', 'after'])
@pytest.mark.parametrize('also_owner', [False, True])
@pytest.mark.parametrize('mode', ['case', 'admin'])
def test_revocation_around_actual_stop_write_rolls_back_even_for_owner_operator(setup, recorded_cleanup, point, also_owner, mode):
    service, persistence, provider, query = recovery(setup, recorded_cleanup)
    if also_owner:
        with psycopg.connect(DATABASE_URL) as connection:
            insert(connection, 'public.company_memberships', {'company_id': setup[0]['company'],
                'user_id': query.actor_id.subject.value, 'role': 'owner', 'accepted_at': datetime.now(UTC)})
    revoked = []
    def revoke_once():
        with psycopg.connect(DATABASE_URL) as connection: revoke(connection, query, mode)
        revoked.append(True)
    async def execute(connection, sql, *args, **kwargs):
        write = str(sql).strip().lower().startswith('update billing.annual_operations')
        if write and point == 'before': revoke_once()
        result = await connection.execute(sql, *args, **kwargs)
        if write and point == 'after': revoke_once()
        return result
    interleave_cleanup_sql(persistence, execute)
    before = fingerprint(setup)
    with pytest.raises(BillingError): asyncio.run(service.recover_cleanup(query))
    assert revoked == [True] and fingerprint(setup) == before


def test_actual_zero_row_stop_update_rolls_back_without_confirmation(setup, recorded_cleanup):
    service, persistence, provider, query = recovery(setup, recorded_cleanup)
    affected = []
    async def execute(connection, sql, *args, **kwargs):
        if str(sql).strip().lower().startswith('update billing.annual_operations'):
            result = await connection.execute(str(sql) + ' and false', *args, **kwargs)
            affected.append(result.rowcount)
            return result
        return await connection.execute(sql, *args, **kwargs)
    interleave_cleanup_sql(persistence, execute)
    before = fingerprint(setup)
    with pytest.raises(BillingError): asyncio.run(service.recover_cleanup(query))
    assert affected == [0] and fingerprint(setup) == before


def test_sql_aborted_transaction_is_not_queried_after_the_error(setup, recorded_cleanup):
    service, persistence, provider, query = recovery(setup, recorded_cleanup)
    after_error = []
    failed = False
    async def execute(connection, sql, *args, **kwargs):
        nonlocal failed
        if failed: after_error.append(str(sql))
        if str(sql).strip().lower().startswith('update billing.annual_operations'):
            failed = True
            return await connection.execute('select 1/0')
        return await connection.execute(sql, *args, **kwargs)
    interleave_cleanup_sql(persistence, execute)
    before = fingerprint(setup)
    with pytest.raises(BillingError): asyncio.run(service.recover_cleanup(query))
    assert failed and not after_error and fingerprint(setup) == before


def test_lost_commit_response_recovers_same_terminal_stop(setup, recorded_cleanup):
    service, persistence, provider, query = recovery(setup, recorded_cleanup)
    settle = persistence.settle_cleanup_recovery
    async def lose(query, cleanup, value):
        await settle(query, cleanup, value)
        raise BillingError.unavailable()
    persistence.settle_cleanup_recovery = lose
    with pytest.raises(BillingError): asyncio.run(service.recover_cleanup(query))
    assert asyncio.run(annual_support_cleanup_recovery_operations(persistence, None).recover_cleanup(query)).observation.status is AnnualProviderStatus.CONFIRMED
    assert provider.reads == [recorded_cleanup.intent] and counts(setup) == (1, 2)
