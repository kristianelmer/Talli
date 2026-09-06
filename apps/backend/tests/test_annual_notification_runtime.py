"""Mandatory owned PostgreSQL evidence; no hosted/provider connections."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from test_annual_notification_intake import AUTH, PATH, deliver, encoded, fixture, signed
from test_annual_purchase_basis_runtime import admitted, scoped, test_role_authority as billing_role_authority
from test_annual_purchase_ledger_runtime import purchased
from talli_backend.adapters.postgres_annual_notifications import PostgresAnnualNotificationInbox
from talli_backend.modules.billing.public import AnnualNotificationAccount, AnnualNotificationUnavailable
from talli_backend.shared.kernel import Timestamp

pytestmark = pytest.mark.billing_database
DATABASE_URL = os.environ.get('DATABASE_URL', '')
ROOT = Path(__file__).resolve().parents[3]
MIGRATION = '20260906204352_annual_notification_receipts.sql'
TABLE = 'backend_system.annual_notification_receipts'


@pytest.fixture(scope='module', autouse=True)
def notification_authority():
    assert DATABASE_URL, 'DATABASE_URL must identify the disposable test database'
    borrowed = []
    with psycopg.connect(DATABASE_URL) as connection:
        principal = connection.execute('select current_user').fetchone()[0]
        for role in ('annual_notification_executor', 'annual_notification_store_owner'):
            if not connection.execute("select pg_has_role(current_user, %s, 'SET')", (role,)).fetchone()[0]:
                connection.execute(sql.SQL('grant {} to {} with set true, inherit false').format(sql.Identifier(role), sql.Identifier(principal)))
                borrowed.append(role)
    try:
        yield
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            for role in borrowed:
                connection.execute(sql.SQL('revoke {} from {}').format(sql.Identifier(role), sql.Identifier(principal)))


def notification():
    body = encoded(chargeId='unknown-' + uuid4().hex)
    return AUTH.authenticate(body, signed(body, at=datetime.now(UTC)), at=datetime.now(UTC))


def store(account=None):
    return PostgresAnnualNotificationInbox(DATABASE_URL, account or AUTH.account)


def receipt_scope(connection, account=None):
    account = account or AUTH.account
    connection.execute('set local role annual_notification_executor')
    connection.execute("select set_config('talli.notification_provider', %s, true), set_config('talli.notification_account', %s, true)", (account.provider, account.reference))


def saved_rows(value):
    with psycopg.connect(DATABASE_URL) as connection:
        receipt_scope(connection, value.account)
        return connection.execute('select to_jsonb(r) from ' + TABLE + ' r where receipt_digest=%s', (value.receipt_digest,)).fetchall()


def test_exact_delivery_concurrency_commits_one_immutable_receipt():
    value = notification()
    async def receive():
        return await asyncio.gather(*(store().record_notification(value) for _ in range(12)))
    results = asyncio.run(receive())
    assert all(result == results[0] for result in results)
    assert results[0].notification == value and len(saved_rows(value)) == 1


def test_conflicting_insert_wait_uses_new_snapshot_after_winner_commits():
    value = notification()
    async def compete():
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as winner:
            await winner.execute('set local role annual_notification_executor')
            await winner.execute("select set_config('talli.notification_provider', %s, true), set_config('talli.notification_account', %s, true)", (value.account.provider, value.account.reference))
            first = await (await winner.execute('insert into ' + TABLE + '''
                (provider,provider_account,receipt_digest,agreement_reference,charge_reference,event_type,occurred_at)
                values (%s,%s,%s,%s,%s,%s,%s) returning id,received_at''',
                (value.account.provider, value.account.reference, value.receipt_digest, value.agreement_reference,
                 value.charge_reference, value.event_type, value.occurred_at.value))).fetchone()
            retry = asyncio.create_task(store().record_notification(value))
            try:
                # Prove the second connection is waiting on this uncommitted key.
                async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as observer:
                    for _ in range(80):
                        waiting = await (await observer.execute("select count(*) from pg_stat_activity where wait_event_type='Lock' and query like 'insert into backend_system.annual_notification_receipts%'" )).fetchone()
                        if waiting[0]:
                            break
                        await asyncio.sleep(.01)
                    assert waiting[0] > 0
                await winner.commit()
                result = await retry
                assert str(result.receipt_id) == str(first[0]) and result.received_at.value == first[1]
            finally:
                if not retry.done():
                    retry.cancel()
                    await asyncio.gather(retry, return_exceptions=True)
    asyncio.run(compete())
    assert len(saved_rows(value)) == 1


@pytest.mark.parametrize('change', [
    {'agreement_reference': 'different'}, {'charge_reference': None}, {'event_type': 'recurring.charge-refunded.v1'},
    {'occurred_at': Timestamp(datetime(2026, 1, 1, tzinfo=UTC))},
])
def test_same_digest_with_conflicting_evidence_cannot_overwrite_receipt(change):
    value = notification()
    original = asyncio.run(store().record_notification(value))
    with pytest.raises(AnnualNotificationUnavailable):
        asyncio.run(store().record_notification(replace(value, **change)))
    assert asyncio.run(store().record_notification(value)) == original


def test_account_and_provider_scope_isolate_identical_digest():
    value = notification()
    accounts = [value.account, AnnualNotificationAccount('vipps-mt', '999999'), AnnualNotificationAccount('other-test', '123456')]
    receipts = [asyncio.run(store(account).record_notification(replace(value, account=account))) for account in accounts]
    assert len({str(receipt.receipt_id) for receipt in receipts}) == 3
    with pytest.raises(AnnualNotificationUnavailable):
        asyncio.run(store().record_notification(replace(value, account=accounts[1])))
    for account in accounts:
        assert len(saved_rows(replace(value, account=account))) == 1


def test_unknown_signed_resource_is_retained_and_lost_http_ack_replays_it():
    database = store()
    class LoseAcknowledgement:
        account = database.account
        async def record_notification(self, value):
            await database.record_notification(value)
            raise AnnualNotificationUnavailable()
    body = encoded(chargeId='unknown-' + uuid4().hex)
    value = AUTH.authenticate(body, signed(body, at=datetime.now(UTC)), at=datetime.now(UTC))
    api, _ = fixture(LoseAcknowledgement())
    assert deliver(api, body).status_code == 503
    original = saved_rows(value)
    api, _ = fixture(database)
    assert deliver(api, body).json() == {'status': 'received'}
    assert saved_rows(value) == original and len(original) == 1


def test_deferred_commit_failure_has_no_http_ack_or_committed_receipt():
    body = encoded(chargeId='unknown-' + uuid4().hex)
    value = AUTH.authenticate(body, signed(body, at=datetime.now(UTC)), at=datetime.now(UTC))
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute('set local role annual_notification_store_owner')
        connection.execute('create constraint trigger fixture_notification_commit_failure after insert on ' + TABLE +
                           ' deferrable initially deferred for each row execute function backend_system.guard_annual_notification_receipt_v1()')
    try:
        api, _ = fixture(store())
        response = deliver(api, body)
        assert response.status_code == 503 and 'fixture_notification' not in response.text
        assert saved_rows(value) == []
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute('set local role annual_notification_store_owner')
            connection.execute('drop trigger fixture_notification_commit_failure on ' + TABLE)
    assert deliver(api, body).status_code == 200


def test_rls_requires_both_account_settings_and_never_grants_owner_or_browser_access():
    value = notification()
    asyncio.run(store().record_notification(value))
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute('set local role annual_notification_executor')
        assert connection.execute('select count(*) from ' + TABLE).fetchone()[0] == 0
        connection.execute("select set_config('talli.notification_account', '123456', true)")
        assert connection.execute('select count(*) from ' + TABLE).fetchone()[0] == 0
    for role in ('anon', 'authenticated', 'service_role', 'billing_store_owner', 'billing_executor'):
        with psycopg.connect(DATABASE_URL) as connection:
            assert not connection.execute("select has_table_privilege(%s,%s,'SELECT')", (role, TABLE)).fetchone()[0]
            assert not connection.execute("select has_any_column_privilege(%s,%s,'INSERT')", (role, TABLE)).fetchone()[0]
            assert not connection.execute("select pg_has_role(%s,'annual_notification_executor','SET')", (role,)).fetchone()[0]
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, uuid4(), role='authenticated')
        connection.execute("select set_config('talli.notification_provider','vipps-mt',true),set_config('talli.notification_account','123456',true)")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute('select * from ' + TABLE)


def test_executor_has_no_financial_or_mutation_authority_and_receipt_fields_are_immutable():
    value = notification()
    asyncio.run(store().record_notification(value))
    with psycopg.connect(DATABASE_URL) as connection:
        attributes = connection.execute("select rolcanlogin,rolinherit,rolbypassrls,rolsuper,rolcreaterole,rolcreatedb from pg_roles where rolname='annual_notification_executor'").fetchone()
        assert attributes == (False,) * 6
        for table in ('annual_purchases', 'annual_operations', 'annual_refund_cases', 'annual_refund_requests', 'annual_cancellation_requests'):
            for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'):
                assert not connection.execute("select has_table_privilege('annual_notification_executor',%s,%s)", ('billing.' + table, privilege)).fetchone()[0]
        assert connection.execute("select relrowsecurity,relforcerowsecurity from pg_class where oid=%s::regclass", (TABLE,)).fetchone() == (True, True)
    for statement in ('update ' + TABLE + " set event_type='changed'", 'delete from ' + TABLE, 'truncate ' + TABLE,
                      'insert into ' + TABLE + ' (id) values (gen_random_uuid())'):
        with psycopg.connect(DATABASE_URL) as connection:
            receipt_scope(connection)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement)
    assert len(saved_rows(value)) == 1


def test_direct_cross_account_insert_cannot_escape_scoped_rls():
    with psycopg.connect(DATABASE_URL) as connection:
        receipt_scope(connection)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute('insert into ' + TABLE + '''
                (provider,provider_account,receipt_digest,agreement_reference,event_type,occurred_at)
                values ('vipps-mt','999999',%s,'other-agreement','recurring.agreement-stopped.v1',now())''',
                (uuid4().hex * 2,))


def test_signed_refund_hint_does_not_change_original_financial_rows(admitted):
    purchase, operation = purchased(admitted)
    def financial_evidence():
        with psycopg.connect(DATABASE_URL) as connection:
            scoped(connection, admitted['owner'])
            return connection.execute('select to_jsonb(p),to_jsonb(o) from billing.annual_purchases p join billing.annual_operations o on o.purchase_id=p.id where p.id=%s', (purchase['id'],)).fetchone()
    before = financial_evidence()
    value = replace(notification(), agreement_reference='unbound-agreement', charge_reference=purchase['charge_reference'], event_type='recurring.charge-refunded.v1')
    assert asyncio.run(store().record_notification(value)).notification == value
    assert financial_evidence() == before


def test_withdrawal_and_recutover_twice_preserve_exact_evidence_and_table_identity():
    value = notification()
    original = asyncio.run(store().record_notification(value))
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        identity = connection.execute('select %s::regclass::oid', (TABLE,)).fetchone()
        for _ in range(2):
            connection.execute((ROOT / 'supabase' / 'rollback' / MIGRATION).read_text())
            try:
                with pytest.raises(AnnualNotificationUnavailable):
                    asyncio.run(store().record_notification(value))
                assert connection.execute('select %s::regclass::oid', (TABLE,)).fetchone() == identity
                assert not connection.execute("select has_any_column_privilege('annual_notification_executor',%s,'INSERT')", (TABLE,)).fetchone()[0]
            finally:
                connection.execute((ROOT / 'supabase' / 'migrations' / MIGRATION).read_text())
            assert asyncio.run(store().record_notification(value)) == original
            assert connection.execute('select %s::regclass::oid', (TABLE,)).fetchone() == identity
