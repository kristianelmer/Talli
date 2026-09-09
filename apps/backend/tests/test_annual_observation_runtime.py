"""Real restricted logins, leases and financial writes in the disposable database."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from test_annual_checkout_runtime import (
    DATABASE_URL, ROOT, admitted, setup, candidate, session, observation,
    test_role_authority, checkout_company_records, interleave_checkout_sql,
)
from talli_backend.adapters.postgres_annual_observation import PostgresAnnualCheckoutObservationStore
from talli_backend.modules.billing.public import (
    AnnualProviderStatus, AnnualPurchaseStatus, BillingError,
    annual_checkout_observation_operations,
)

pytestmark = pytest.mark.billing_database


@pytest.fixture(scope="module", autouse=True)
def observer_test_admin():
    """Explicit disposable-fixture administration, never the worker principal."""
    with psycopg.connect(DATABASE_URL) as con:
        principal = con.execute('select current_user').fetchone()[0]
        borrowed = not con.execute("select pg_has_role(current_user,'annual_checkout_observer_store_owner','SET')").fetchone()[0]
        if borrowed:
            con.execute(sql.SQL('grant annual_checkout_observer_store_owner to {} with set true').format(sql.Identifier(principal)))
        con.execute('set local role annual_checkout_observer_store_owner')
        con.execute(sql.SQL('grant select,insert,update,delete on billing.annual_checkout_observation_principals,billing.annual_checkout_observation_authorities,backend_system.annual_checkout_observation_work to {}').format(sql.Identifier(principal)))
    yield
    with psycopg.connect(DATABASE_URL) as con:
        con.execute('set local role annual_checkout_observer_store_owner')
        con.execute(sql.SQL('revoke select,insert,update,delete on billing.annual_checkout_observation_principals,billing.annual_checkout_observation_authorities,backend_system.annual_checkout_observation_work from {}').format(sql.Identifier(principal)))
        con.execute('reset role')
        if borrowed:
            con.execute(sql.SQL('revoke annual_checkout_observer_store_owner from {}').format(sql.Identifier(principal)))


@pytest.fixture
def worker():
    role, password, account = 'annual_observer_' + uuid4().hex, uuid4().hex, uuid4().hex
    with psycopg.connect(DATABASE_URL) as con:
        con.execute(sql.SQL('create role {} login noinherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls password {}').format(sql.Identifier(role), sql.Literal(password)))
        con.execute(sql.SQL('grant annual_checkout_observer_executor to {} with inherit false, set true').format(sql.Identifier(role)))
        con.execute('insert into billing.annual_checkout_observation_principals(database_role,role_oid,provider,provider_account,enabled) select rolname,oid,%s,%s,true from pg_roles where rolname=%s', ('vipps-mt', account, role))
    url = make_conninfo(DATABASE_URL, user=role, password=password)
    result = SimpleNamespace(role=role, password=password, account=account, url=url,
                             store=PostgresAnnualCheckoutObservationStore(url, 'vipps-mt', account))
    try:
        yield result
    finally:
        with psycopg.connect(DATABASE_URL) as con:
            con.execute('update billing.annual_checkout_observation_principals set enabled=false where database_role=%s', (role,))
            con.execute(sql.SQL('revoke annual_checkout_observer_executor from {}').format(sql.Identifier(role)))
            con.execute(sql.SQL('drop role {}').format(sql.Identifier(role)))


def purchase(setup, worker, **changes):
    value = replace(candidate(setup), provider_account=worker.account, **changes)
    return asyncio.run(session(setup).claim_checkout(value, setup[4])).checkout


def work_record(checkout):
    with psycopg.connect(DATABASE_URL) as con:
        return con.execute('select to_jsonb(w) from backend_system.annual_checkout_observation_work w where operation_id=%s', (str(checkout.intent.operation_id),)).fetchone()[0]


def revoke(worker, *, enabled=False):
    with psycopg.connect(DATABASE_URL) as con:
        con.execute('update billing.annual_checkout_observation_principals set enabled=%s where database_role=%s', (enabled, worker.role))


class Provider:
    provider = 'vipps-mt'
    production_enabled = False
    def __init__(self, worker, checkout):
        self.account_reference = worker.account
        self.checkout = checkout
        self.calls = []
    async def execute(self, intent):
        raise AssertionError('Observation worker must never execute a provider operation')
    async def reconcile(self, intent):
        self.calls.append(intent)
        return observation(self.checkout, status=AnnualProviderStatus.CONFIRMED, captured=149000)


def test_real_login_claim_settlement_and_terminal_scan_are_account_bound(setup, worker):
    checkout = purchase(setup, worker)
    with psycopg.connect(worker.url) as con:
        con.execute('set local role annual_checkout_observer_executor')
        assert con.execute('select session_user,current_user').fetchone() == (worker.role, 'annual_checkout_observer_executor')
    provider = Provider(worker, checkout)
    result = asyncio.run(annual_checkout_observation_operations(worker.store, provider).run_once())
    assert result.value == 'reconciled'
    assert provider.calls == [checkout.intent]
    saved = checkout_company_records(setup)
    assert saved[0][0]['status'] == 'paid'
    assert saved[0][0]['accepted_by'] == str(checkout.accepted_by)
    assert saved[1][0]['created_by'] == str(checkout.accepted_by)
    assert asyncio.run(worker.store.claim_checkout_observation()) is None
    assert work_record(checkout)['completed_at'] is not None


@pytest.mark.parametrize('table', ['billing.annual_purchases','billing.annual_operations','billing.annual_checkout_observation_authorities','billing.annual_checkout_observation_principals','backend_system.annual_checkout_observation_work'])
def test_worker_cannot_directly_read_or_write_tables(worker, table):
    with psycopg.connect(worker.url) as con:
        con.execute('set local role annual_checkout_observer_executor')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            con.execute(sql.SQL('select * from {}').format(sql.Identifier(*table.split('.'))))
    with psycopg.connect(worker.url) as con:
        con.execute('set local role annual_checkout_observer_executor')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            con.execute(sql.SQL('delete from {}').format(sql.Identifier(*table.split('.'))))


def test_admin_url_cannot_become_a_worker_even_with_forged_owner_claims(setup, worker):
    purchase(setup, worker)
    store = PostgresAnnualCheckoutObservationStore(DATABASE_URL, 'vipps-mt', worker.account)
    with pytest.raises(BillingError):
        asyncio.run(store.claim_checkout_observation())


def test_account_change_or_broad_role_membership_denies_claim(setup, worker):
    purchase(setup, worker)
    wrong = PostgresAnnualCheckoutObservationStore(worker.url, 'vipps-mt', 'different-account')
    with pytest.raises(BillingError):
        asyncio.run(wrong.claim_checkout_observation())
    with psycopg.connect(DATABASE_URL) as con:
        con.execute(sql.SQL('grant billing_store_owner to {} with inherit false').format(sql.Identifier(worker.role)))
    try:
        with pytest.raises(BillingError):
            asyncio.run(worker.store.claim_checkout_observation())
    finally:
        with psycopg.connect(DATABASE_URL) as con:
            con.execute(sql.SQL('revoke billing_store_owner from {}').format(sql.Identifier(worker.role)))


def test_revoked_owner_does_not_erase_committed_observation_authority(setup, worker):
    checkout = purchase(setup, worker)
    with psycopg.connect(DATABASE_URL) as con:
        con.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s', (str(checkout.offer.company_id), str(checkout.accepted_by)))
    provider = Provider(worker, checkout)
    assert asyncio.run(annual_checkout_observation_operations(worker.store, provider).run_once()).value == 'reconciled'
    with pytest.raises(BillingError):
        asyncio.run(session(setup).settle_checkout(checkout, observation(checkout)))


def test_canceled_pending_checkout_still_observes_initial_capture(setup, worker):
    checkout = purchase(setup, worker)
    with psycopg.connect(DATABASE_URL) as con:
        con.execute('update billing.annual_purchases set renewal_canceled_at=clock_timestamp() where id=%s', (str(checkout.purchase_id),))
    assert asyncio.run(annual_checkout_observation_operations(worker.store, Provider(worker, checkout)).run_once()).value == 'reconciled'
    assert checkout_company_records(setup)[0][0]['renewal_canceled_at'] is not None


def test_simultaneous_claims_have_one_lease_and_crash_recovery_fences_the_old_worker(setup, worker):
    checkout = purchase(setup, worker)
    async def simultaneous():
        return await asyncio.gather(worker.store.claim_checkout_observation(), worker.store.claim_checkout_observation())
    values = asyncio.run(simultaneous())
    assert sum(item is not None for item in values) == 1
    first = next(item for item in values if item)
    with psycopg.connect(DATABASE_URL) as con:
        con.execute("update backend_system.annual_checkout_observation_work set lease_until=clock_timestamp()-interval '1 second' where operation_id=%s", (str(checkout.intent.operation_id),))
    second = asyncio.run(worker.store.claim_checkout_observation())
    assert second.fence == first.fence + 1 and second.token != first.token
    before = checkout_company_records(setup), work_record(checkout)
    with pytest.raises(BillingError):
        asyncio.run(worker.store.settle_checkout_observation(first, observation(checkout, status=AnnualProviderStatus.CONFIRMED, captured=149000)))
    assert (checkout_company_records(setup), work_record(checkout)) == before
    assert asyncio.run(worker.store.settle_checkout_observation(second, observation(checkout, status=AnnualProviderStatus.CONFIRMED, captured=149000))).status == AnnualPurchaseStatus.PAID


def test_provider_failure_commits_only_retry_without_fabricating_observation(setup, worker):
    checkout = purchase(setup, worker)
    provider = Provider(worker, checkout)
    async def failed(intent):
        raise TimeoutError('simulated provider read failure')
    provider.reconcile = failed
    before = checkout_company_records(setup)
    assert asyncio.run(annual_checkout_observation_operations(worker.store, provider).run_once()).value == 'retry'
    assert checkout_company_records(setup) == before
    record = work_record(checkout)
    assert record['last_outcome'] == 'retry' and record['lease_token'] is None


@pytest.mark.parametrize('reactivate', [False, True])
def test_worker_revocation_before_provider_get_invalidates_epoch(setup, worker, reactivate):
    checkout = purchase(setup, worker)
    lease = asyncio.run(worker.store.claim_checkout_observation())
    revoke(worker)
    if reactivate:
        revoke(worker, enabled=True)
    before = checkout_company_records(setup), work_record(checkout)
    with pytest.raises(BillingError):
        asyncio.run(worker.store.authorize_checkout_observation(lease))
    with pytest.raises(BillingError):
        asyncio.run(worker.store.settle_checkout_observation(lease, observation(checkout)))
    assert (checkout_company_records(setup), work_record(checkout)) == before


def test_owner_wins_while_get_in_flight_and_stale_observation_cannot_rewrite_receipt(setup, worker):
    checkout = purchase(setup, worker)
    lease = asyncio.run(worker.store.claim_checkout_observation())
    paid = asyncio.run(session(setup).settle_checkout(checkout, observation(checkout, status=AnnualProviderStatus.CONFIRMED, captured=149000)))
    before = checkout_company_records(setup)
    result = asyncio.run(worker.store.settle_checkout_observation(lease, observation(checkout, status=AnnualProviderStatus.FAILED)))
    assert result == paid and checkout_company_records(setup) == before
    assert work_record(checkout)['last_outcome'] == 'reconciled'


def test_newer_partial_observation_survives_stale_worker_result(setup, worker):
    checkout = purchase(setup, worker)
    lease = asyncio.run(worker.store.claim_checkout_observation())
    partial = asyncio.run(session(setup).settle_checkout(checkout, observation(checkout, captured=10000)))
    before = checkout_company_records(setup)
    result = asyncio.run(worker.store.settle_checkout_observation(lease, observation(checkout)))
    assert result == partial and checkout_company_records(setup) == before


def test_malformed_earlier_intent_is_quarantined_without_authority_and_later_checkout_progresses(setup, worker):
    malformed = purchase(setup, worker, request_fingerprint='f'*64)
    other_seed = admitted.__wrapped__(SimpleNamespace())
    other_setup = globals()['setup'].__wrapped__(other_seed)
    valid = purchase(other_setup, worker)
    lease = asyncio.run(worker.store.claim_checkout_observation())
    assert lease.checkout == valid
    assert work_record(malformed)['last_outcome'] == 'invalid_intent'
    with psycopg.connect(DATABASE_URL) as con:
        assert con.execute('select count(*) from billing.annual_checkout_observation_authorities where operation_id=%s', (str(malformed.intent.operation_id),)).fetchone()[0] == 0


def test_dropped_and_recreated_login_cannot_inherit_old_registry_or_lease(setup, worker):
    checkout = purchase(setup, worker)
    lease = asyncio.run(worker.store.claim_checkout_observation())
    with psycopg.connect(DATABASE_URL) as con:
        con.execute(sql.SQL('revoke annual_checkout_observer_executor from {}').format(sql.Identifier(worker.role)))
        con.execute(sql.SQL('drop role {}').format(sql.Identifier(worker.role)))
        con.execute(sql.SQL('create role {} login noinherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls password {}').format(sql.Identifier(worker.role), sql.Literal(worker.password)))
        con.execute(sql.SQL('grant annual_checkout_observer_executor to {} with inherit false,set true').format(sql.Identifier(worker.role)))
    with pytest.raises(BillingError):
        asyncio.run(worker.store.authorize_checkout_observation(lease))
    with pytest.raises(BillingError):
        asyncio.run(worker.store.claim_checkout_observation())


from contextlib import contextmanager
from time import monotonic


@contextmanager
def update_trigger(table, column, identity, body, *, phase='before'):
    """Install a scoped real SQL fault; remove it even when the assertion fails."""
    name = 'annual_observer_test_' + uuid4().hex
    owner = 'annual_checkout_observer_store_owner' if table.startswith('backend_system.') else 'billing_store_owner'
    with psycopg.connect(DATABASE_URL) as con:
        con.execute(sql.SQL('create function public.{}() returns trigger language plpgsql as {}').format(
            sql.Identifier(name), sql.Literal(f"begin if new.{column} = '{identity}'::uuid then {body} end if; return new; end;")))
        con.execute(sql.SQL('set local role {}').format(sql.Identifier(owner)))
        con.execute(sql.SQL('create trigger {} {} update on {} for each row execute function public.{}()').format(
            sql.Identifier(name), sql.SQL(phase), sql.Identifier(*table.split('.')), sql.Identifier(name)))
    try:
        yield
    finally:
        with psycopg.connect(DATABASE_URL) as con:
            con.execute(sql.SQL('set local role {}').format(sql.Identifier(owner)))
            con.execute(sql.SQL('drop trigger {} on {}').format(sql.Identifier(name), sql.Identifier(*table.split('.'))))
            con.execute('reset role')
            con.execute(sql.SQL('drop function public.{}()').format(sql.Identifier(name)))


@pytest.mark.parametrize('table,column', [('billing.annual_purchases','id'),('billing.annual_operations','id'),('backend_system.annual_checkout_observation_work','operation_id')])
def test_zero_row_business_or_lease_write_rolls_back_entire_settlement(setup, worker, table, column):
    checkout = purchase(setup, worker)
    lease = asyncio.run(worker.store.claim_checkout_observation())
    before = checkout_company_records(setup), work_record(checkout)
    identity = checkout.purchase_id if table.endswith('annual_purchases') else checkout.intent.operation_id
    with update_trigger(table, column, identity, 'return null;'):
        with pytest.raises(BillingError):
            asyncio.run(worker.store.settle_checkout_observation(lease, observation(checkout, status=AnnualProviderStatus.CONFIRMED, captured=149000)))
    assert (checkout_company_records(setup), work_record(checkout)) == before


async def wait_for_database_wait(worker, event):
    deadline = monotonic() + 4
    while monotonic() < deadline:
        with psycopg.connect(DATABASE_URL) as con:
            waiting = con.execute('select count(*) from pg_stat_activity where usename=%s and wait_event=%s', (worker.role, event)).fetchone()[0]
        if waiting:
            return
        await asyncio.sleep(0.01)
    raise AssertionError('Worker did not reach the intended database wait')


def test_revoke_during_real_purchase_lock_wait_rolls_back_without_observation(setup, worker):
    checkout = purchase(setup, worker)
    lease = asyncio.run(worker.store.claim_checkout_observation())
    before = checkout_company_records(setup), work_record(checkout)
    async def run():
        with psycopg.connect(DATABASE_URL) as locker:
            locker.execute('select id from billing.annual_purchases where id=%s for update', (str(checkout.purchase_id),))
            pending = asyncio.create_task(worker.store.settle_checkout_observation(lease, observation(checkout, status=AnnualProviderStatus.CONFIRMED, captured=149000)))
            await wait_for_database_wait(worker, 'transactionid')
            revoke(worker)
            locker.commit()
            with pytest.raises(BillingError):
                await pending
    asyncio.run(run())
    assert (checkout_company_records(setup), work_record(checkout)) == before


@pytest.mark.parametrize('table,column', [('billing.annual_purchases','id'),('billing.annual_operations','id'),('backend_system.annual_checkout_observation_work','operation_id')])
def test_revoke_during_actual_write_rolls_back_financial_and_technical_changes(setup, worker, table, column):
    checkout = purchase(setup, worker)
    lease = asyncio.run(worker.store.claim_checkout_observation())
    before = checkout_company_records(setup), work_record(checkout)
    identity = checkout.purchase_id if table.endswith('annual_purchases') else checkout.intent.operation_id
    # Use a repeatable-read login default to prove the adapter pins fresh snapshots.
    with psycopg.connect(DATABASE_URL) as con:
        con.execute(sql.SQL("alter role {} set default_transaction_isolation='repeatable read'").format(sql.Identifier(worker.role)))
    async def run():
        pending = asyncio.create_task(worker.store.settle_checkout_observation(lease, observation(checkout, status=AnnualProviderStatus.CONFIRMED, captured=149000)))
        await wait_for_database_wait(worker, 'PgSleep')
        revoke(worker)
        with pytest.raises(BillingError):
            await pending
    with update_trigger(table, column, identity, 'perform pg_catalog.pg_sleep(0.4);', phase='after'):
        asyncio.run(run())
    assert (checkout_company_records(setup), work_record(checkout)) == before


def test_expiry_during_final_lease_write_rolls_back_after_write_predicate_passed(setup, worker):
    checkout = purchase(setup, worker)
    lease = asyncio.run(worker.store.claim_checkout_observation())
    async def run():
        pending = asyncio.create_task(worker.store.settle_checkout_observation(lease, observation(checkout, status=AnnualProviderStatus.CONFIRMED, captured=149000)))
        await wait_for_database_wait(worker, 'PgSleep')
        with pytest.raises(BillingError):
            await pending
    with update_trigger('backend_system.annual_checkout_observation_work', 'operation_id', checkout.intent.operation_id,
                        'if new.lease_token is null then perform pg_catalog.pg_sleep(0.5); end if;', phase='after'):
        with psycopg.connect(DATABASE_URL) as con:
            con.execute("update backend_system.annual_checkout_observation_work set lease_until=clock_timestamp()+interval '350 milliseconds' where operation_id=%s", (str(checkout.intent.operation_id),))
        before = checkout_company_records(setup), work_record(checkout)
        asyncio.run(run())
    assert (checkout_company_records(setup), work_record(checkout)) == before


def test_quarantine_revocation_after_write_rolls_back_and_grants_no_authority(setup, worker):
    checkout = purchase(setup, worker, request_fingerprint='f'*64)
    before = checkout_company_records(setup)
    async def run():
        pending = asyncio.create_task(worker.store.claim_checkout_observation())
        await wait_for_database_wait(worker, 'PgSleep')
        revoke(worker)
        with pytest.raises(BillingError):
            await pending
    with update_trigger('backend_system.annual_checkout_observation_work', 'operation_id', checkout.intent.operation_id, 'perform pg_catalog.pg_sleep(0.4);', phase='after'):
        asyncio.run(run())
    assert checkout_company_records(setup) == before
    with psycopg.connect(DATABASE_URL) as con:
        assert con.execute('select count(*) from backend_system.annual_checkout_observation_work where operation_id=%s', (str(checkout.intent.operation_id),)).fetchone()[0] == 0
        assert con.execute('select count(*) from billing.annual_checkout_observation_authorities where operation_id=%s', (str(checkout.intent.operation_id),)).fetchone()[0] == 0


def test_worker_has_no_write_columns_or_role_escalation(worker):
    with psycopg.connect(worker.url) as con:
        con.execute('set local role annual_checkout_observer_executor')
        for table, column in [('billing.annual_purchases','captured_minor'), ('billing.annual_operations','status'), ('billing.annual_checkout_observation_principals','enabled')]:
            assert con.execute("select has_column_privilege(current_user,%s,%s,'UPDATE')", (table,column)).fetchone() == (False,)
            assert con.execute("select has_table_privilege(current_user,%s,'INSERT')", (table,)).fetchone() == (False,)
    for role in ('billing_store_owner','annual_checkout_observer_store_owner'):
        with psycopg.connect(worker.url) as con:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                con.execute(sql.SQL('set role {}').format(sql.Identifier(role)))


def test_rollback_preserves_evidence_and_recutover_requires_explicit_reactivation(setup, worker):
    checkout = purchase(setup, worker)
    lease = asyncio.run(worker.store.claim_checkout_observation())
    before_work = work_record(checkout)
    with psycopg.connect(DATABASE_URL) as con:
        before_authority = con.execute('select to_jsonb(a) from billing.annual_checkout_observation_authorities a where operation_id=%s', (str(checkout.intent.operation_id),)).fetchone()[0]
    migration = ROOT / 'supabase/migrations/20260907153938_annual_checkout_observation.sql'
    rollback = ROOT / 'supabase/rollback/20260907153938_annual_checkout_observation.sql'
    try:
        with psycopg.connect(DATABASE_URL) as con:
            con.execute(rollback.read_text())
            assert con.execute('select to_jsonb(a) from billing_annual_retired.annual_checkout_observation_authorities a where operation_id=%s', (str(checkout.intent.operation_id),)).fetchone()[0] == before_authority
        with pytest.raises(BillingError):
            asyncio.run(worker.store.authorize_checkout_observation(lease))
    finally:
        with psycopg.connect(DATABASE_URL) as con:
            con.execute(migration.read_text())
    assert work_record(checkout) == before_work
    with pytest.raises(BillingError):
        asyncio.run(worker.store.claim_checkout_observation())
    revoke(worker, enabled=True)
    with pytest.raises(BillingError):
        asyncio.run(worker.store.authorize_checkout_observation(lease))
    with psycopg.connect(DATABASE_URL) as con:
        assert con.execute('select to_jsonb(a) from billing.annual_checkout_observation_authorities a where operation_id=%s', (str(checkout.intent.operation_id),)).fetchone()[0] == before_authority


@pytest.mark.parametrize('role', ['annual_checkout_observer_executor','annual_checkout_observer_store_owner'])
def test_migration_rejects_unsafe_preexisting_role_atomically(role):
    migration = ROOT / 'supabase/migrations/20260907153938_annual_checkout_observation.sql'
    with psycopg.connect(DATABASE_URL) as con:
        con.execute(sql.SQL('alter role {} login').format(sql.Identifier(role)))
        with pytest.raises(psycopg.errors.RaiseException, match='annual_observer_unsafe_role'):
            con.execute(migration.read_text())
        con.rollback()
        assert con.execute('select rolcanlogin from pg_roles where rolname=%s', (role,)).fetchone() == (False,)


@pytest.mark.parametrize('change', ['delete','rename'])
def test_principal_tombstone_cannot_be_reused_to_reset_epoch(worker, change):
    with psycopg.connect(DATABASE_URL) as con:
        with pytest.raises(psycopg.errors.RaiseException, match='annual_observer_principal_is_permanent'):
            if change == 'delete':
                con.execute('delete from billing.annual_checkout_observation_principals where database_role=%s', (worker.role,))
            else:
                con.execute('update billing.annual_checkout_observation_principals set database_role=%s where database_role=%s', (worker.role+'_retired',worker.role))
