"""Withdrawal writes invalidate earlier archive generations; no completion fence."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import re
from uuid import uuid4

import psycopg
import pytest

from test_rf1086_register_observation_withdrawal_database import (
    staged, connection, observed, withdraw, append, wait_for_lock,
    admitted, backend_url, cleanup_owned_fixture, rf_fixture_admin_access,
    DATABASE_URL, ROOT, TABLE, APPEND,
)
from test_rf1086_retained_archive_generations import identify, begin, generations

pytestmark = pytest.mark.authority_database
MIGRATION = '20261009220727_rf1086_withdrawal_archive_generation.sql'
TRIGGER = 'company_archive_track_rf_withdrawal'


@pytest.fixture
def tracked(staged):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute((ROOT / 'supabase/migrations' / MIGRATION).read_text())
    return staged


def migration_body():
    body = (ROOT / 'supabase/migrations' / MIGRATION).read_text()
    body = re.sub(r'(?m)^begin;\s*$', '', body, count=1)
    return re.sub(r'commit;\s*$', '', body)


def scope_generations(db, seed):
    return dict(db.execute('select income_year,generation from public.company_archive_source_generations '
                           'where company_id=%s', (seed['company'],)).fetchall())


def complete(db, attempt):
    return db.execute('select public.company_archive_complete_export(%s,%s)', (attempt, 'a' * 64)).fetchone()[0]


def receipt_generation(db, attempt):
    return db.execute('select source_generation from public.company_archive_export_receipts where attempt_id=%s',
                      (attempt,)).fetchone()[0]


def retained_rows(db, seed):
    identify(db, seed)
    db.execute('set local role shareholder_register_filing_store_owner')
    rows = db.execute('select id,snapshot_text from ' + TABLE + ' where company_id=%s order by id',
                      (seed['company'],)).fetchall()
    db.execute('reset role')
    return rows


def authority_snapshot(db):
    return (
        db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option '
                   'from pg_auth_members order by 1,2,3').fetchall(),
        db.execute('select relowner,relrowsecurity,relforcerowsecurity,relacl::text from pg_class '
                   'where oid=%s::regclass', (TABLE,)).fetchone(),
        db.execute('select oid,proowner,proacl::text,proconfig,prosecdef,provolatile,prosrc from pg_proc '
                   'where oid in (%s::regprocedure,%s::regprocedure,%s::regprocedure,%s::regprocedure) order by oid',
                   (APPEND, 'public.company_archive_track_source_write_v1()',
                    'public.company_archive_begin_export(uuid,integer)',
                    'public.company_archive_complete_export(uuid,text)')).fetchall(),
    )


def assert_tracking(db):
    assert db.execute('select tgtype,tgenabled,encode(tgargs,\'escape\'),'
                      "tgfoid='public.company_archive_track_source_write_v1()'::regprocedure "
                      'from pg_trigger where tgrelid=%s::regclass and tgname=%s', (TABLE, TRIGGER)).fetchone() == (
        29, 'O', 'year\\000company_id\\000', True)
    # Preserve the historical ten-source trigger inventory and closed command.
    assert db.execute("select count(*) from pg_trigger where tgname='company_archive_track_retained_rf'").fetchone()[0] == 10
    for role in ('anon', 'authenticated', 'service_role', 'shareholder_register_filing_executor'):
        assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (role, APPEND)).fetchone()[0]


def test_actual_withdrawal_invalidates_completed_receipt_and_inflight_export_only_in_its_year(tracked):
    original = observed(tracked)
    seed = tracked['seed']
    old_receipt = begin(seed, complete=True)
    inflight = begin(seed)
    begin(seed, year=2025, complete=True)
    before = generations(seed)
    encoded = withdraw(tracked, original)
    assert generations(seed) == {**before, 2026: before[2026] + 1}
    with psycopg.connect(DATABASE_URL) as db:
        assert receipt_generation(db, old_receipt) == before[2026]
        assert [text for _, text in retained_rows(db, seed)] == [encoded]
        with pytest.raises(psycopg.Error, match='archive_export_stale'):
            with db.transaction():
                complete(db, inflight)
        assert db.execute('select completed_at from public.company_archive_export_attempts where id=%s',
                          (inflight,)).fetchone()[0] is None
        assert db.execute('select count(*) from public.company_archive_export_receipts where attempt_id=%s',
                          (inflight,)).fetchone()[0] == 0


def test_exact_withdrawal_replay_and_noop_insert_do_not_advance_generation(tracked):
    original = observed(tracked)
    key = str(uuid4())
    encoded = withdraw(tracked, original, key=key)
    before = generations(tracked['seed'])
    assert withdraw(tracked, original, key=key) == encoded
    assert generations(tracked['seed']) == before
    with connection(tracked, role='shareholder_register_filing_store_owner') as db:
        result = db.execute('insert into ' + TABLE + ' select * from ' + TABLE +
                            ' where company_id=%s on conflict do nothing', (tracked['seed']['company'],))
        assert result.rowcount == 0
        db.execute('reset role')
        assert scope_generations(db, tracked['seed']) == before
    assert generations(tracked['seed']) == before


def test_rolled_back_withdrawal_restores_generation_and_leaves_no_receipt(tracked):
    original = observed(tracked)
    before = generations(tracked['seed'])
    with pytest.raises(RuntimeError, match='rollback owned withdrawal'):
        with connection(tracked) as db:
            append(db, original)
            # Observe the real trigger write in the same transaction.
            db.execute('reset role')
            assert scope_generations(db, tracked['seed'])[2026] == before[2026] + 1
            raise RuntimeError('rollback owned withdrawal')
    assert generations(tracked['seed']) == before
    with connection(tracked) as db:
        assert db.execute('select count(*) from ' + TABLE).fetchone()[0] == 0


@pytest.mark.parametrize('mutation', ['update ' + TABLE + " set reason='changed'", 'delete from ' + TABLE])
def test_rejected_immutable_mutation_does_not_advance_generation(tracked, mutation):
    original = observed(tracked)
    withdraw(tracked, original)
    before = generations(tracked['seed'])
    with connection(tracked, role='shareholder_register_filing_store_owner') as db:
        db.execute('alter table ' + TABLE + ' no force row level security')
        with pytest.raises(psycopg.Error, match='rf1086_register_withdrawal_immutable'):
            db.execute(mutation + ' where company_id=%s', (tracked['seed']['company'],))
    assert generations(tracked['seed']) == before


@pytest.mark.parametrize('retained', [False, True])
@pytest.mark.parametrize('prior_trigger', ['present', 'absent', 'disabled', 'conditional'])
def test_activation_and_replay_preserve_authority_and_only_invalidate_retained_scopes(tracked, retained, prior_trigger):
    original = observed(tracked)
    seed = tracked['seed']
    if retained:
        withdraw(tracked, original)
    begin(seed, year=2025, complete=True)
    begin(seed, complete=True)
    before = generations(seed)
    with psycopg.connect(DATABASE_URL) as db:
        try:
            authority = authority_snapshot(db)
            rows = retained_rows(db, seed)
            db.execute('set local role shareholder_register_filing_store_owner')
            if prior_trigger == 'absent':
                db.execute('drop trigger ' + TRIGGER + ' on ' + TABLE)
            elif prior_trigger == 'disabled':
                db.execute('alter table ' + TABLE + ' disable trigger ' + TRIGGER)
            elif prior_trigger == 'conditional':
                # Same identity/events/args but silently omits every row. It must
                # not count as prior tracking when deciding initial invalidation.
                had = db.execute("select has_function_privilege('shareholder_register_filing_store_owner',"
                                 "'public.company_archive_track_source_write_v1()','EXECUTE')").fetchone()[0]
                db.execute('reset role')
                if not had:
                    db.execute('set local role company_archive_projection_executor')
                    db.execute('grant execute on function public.company_archive_track_source_write_v1() '
                               'to shareholder_register_filing_store_owner')
                    db.execute('reset role')
                db.execute('set local role shareholder_register_filing_store_owner')
                db.execute('drop trigger ' + TRIGGER + ' on ' + TABLE)
                db.execute('create trigger ' + TRIGGER + ' after insert or update or delete on ' + TABLE +
                           ' for each row when (false) execute function '
                           "public.company_archive_track_source_write_v1('year','company_id')")
                db.execute('reset role')
                if not had:
                    db.execute('set local role company_archive_projection_executor')
                    db.execute('revoke execute on function public.company_archive_track_source_write_v1() '
                               'from shareholder_register_filing_store_owner')
            db.execute('reset role')
            db.execute(migration_body())
            bump = int(retained and prior_trigger != 'present')
            assert scope_generations(db, seed) == {**before, 2026: before[2026] + bump}
            assert authority_snapshot(db) == authority
            assert retained_rows(db, seed) == rows
            assert_tracking(db)
        finally:
            db.rollback()
    assert generations(seed) == before


@pytest.mark.parametrize('prior_guard', ['absent', 'conditional'])
def test_activation_requires_existing_company_guard_and_failure_restores_catalog(tracked, prior_guard):
    with psycopg.connect(DATABASE_URL) as db:
        before = authority_snapshot(db)
        try:
            db.execute('set local role shareholder_register_filing_store_owner')
            db.execute('drop trigger source_company_guard on ' + TABLE)
            if prior_guard == 'conditional':
                db.execute('create trigger source_company_guard before insert or update or delete on ' + TABLE +
                           ' for each row when (false) execute function '
                           'shareholder_register_filing.lock_source_company_write_v1()')
            db.execute('reset role')
            with pytest.raises(psycopg.Error, match='rf1086_archive_generation_company_guard_required'):
                db.execute(migration_body())
        finally:
            db.rollback()
        assert authority_snapshot(db) == before
        assert db.execute("select tgenabled from pg_trigger where tgrelid=%s::regclass and tgname='source_company_guard'",
                          (TABLE,)).fetchone()[0] == 'O'
        assert_tracking(db)


def test_first_activation_creates_missing_generation_for_retained_withdrawal(tracked):
    original = observed(tracked)
    withdraw(tracked, original)
    before = generations(tracked['seed'])
    with psycopg.connect(DATABASE_URL) as db:
        try:
            db.execute('set local role shareholder_register_filing_store_owner')
            db.execute('drop trigger ' + TRIGGER + ' on ' + TABLE)
            db.execute('reset role')
            db.execute('set local role company_archive_projection_executor')
            db.execute('delete from public.company_archive_source_generations where company_id=%s',
                       (tracked['seed']['company'],))
            db.execute('reset role')
            db.execute(migration_body())
            assert scope_generations(db, tracked['seed']) == {2026: 1}
            assert len(retained_rows(db, tracked['seed'])) == 1
            assert_tracking(db)
        finally:
            db.rollback()
    assert generations(tracked['seed']) == before


@pytest.mark.parametrize('retained', [False, True])
def test_application_rollback_preserves_tracking_and_closed_withdrawal_command(tracked, retained):
    original = observed(tracked)
    if retained:
        withdraw(tracked, original)
    before = generations(tracked['seed'])
    with psycopg.connect(DATABASE_URL) as db:
        authority = authority_snapshot(db)
        db.execute((ROOT / 'supabase/rollback' / MIGRATION).read_text())
        assert authority_snapshot(db) == authority
        assert_tracking(db)
    assert generations(tracked['seed']) == before


@pytest.mark.parametrize('winner', ['withdrawal', 'completion'])
def test_company_lock_serializes_withdrawal_and_export_completion_in_both_orders(tracked, winner):
    original = observed(tracked)
    seed = tracked['seed']
    attempt = begin(seed)
    before = generations(seed)
    started = Queue()

    def competing_completion():
        with psycopg.connect(DATABASE_URL) as db:
            db.execute("set local statement_timeout='8s'; set local lock_timeout='5s'")
            identify(db, seed)
            started.put(db.execute('select pg_backend_pid()').fetchone()[0])
            return complete(db, attempt)

    def competing_withdrawal():
        with connection(tracked) as db:
            started.put(db.execute('select pg_backend_pid()').fetchone()[0])
            return append(db, original)

    with ThreadPoolExecutor(max_workers=1) as pool:
        if winner == 'withdrawal':
            with connection(tracked) as db:
                append(db, original)
                pending = pool.submit(competing_completion)
                wait_for_lock(started.get(timeout=5))
            with pytest.raises(psycopg.Error, match='archive_export_stale'):
                pending.result(timeout=10)
        else:
            with psycopg.connect(DATABASE_URL) as db:
                identify(db, seed)
                complete(db, attempt)
                pending = pool.submit(competing_withdrawal)
                wait_for_lock(started.get(timeout=5))
            assert pending.result(timeout=10)
    assert generations(seed)[2026] == before[2026] + 1
    with psycopg.connect(DATABASE_URL) as db:
        if winner == 'completion':
            # A receipt completed first remains historical, now a stale generation.
            assert receipt_generation(db, attempt) == before[2026]
        else:
            assert db.execute('select count(*) from public.company_archive_export_receipts where attempt_id=%s',
                              (attempt,)).fetchone()[0] == 0
