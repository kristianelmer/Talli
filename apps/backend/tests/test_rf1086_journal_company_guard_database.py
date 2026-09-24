"""Real journal/company ordering, historical recovery and guarded predecessor read."""
import asyncio
from contextlib import contextmanager
from uuid import uuid4

import psycopg
import pytest

from test_rf1086_database_runtime import (
    DATABASE_URL, backend_url, rf_fixture_admin_access, fixture, store, confirmed,
)
from test_rf1086_source_company_guard_database import waiting
from test_rf1086_year_source_database import ROOT

pytestmark = pytest.mark.authority_database
MIGRATION = '20260924094631_rf1086_journal_company_guard.sql'
NAMES = ('prepare_operation_v1', 'append_production_filing_event',
         'claim_production_feedback_reconciliation', 'release_production_feedback_reconciliation',
         'append_production_feedback_reconciliation', 'record_production_feedback_artifact')


def command(name, f, submission, reference, lease):
    if name == NAMES[0]:
        return 'select * from shareholder_register_filing.prepare_operation_v1(%s,%s,%s,%s)', (submission, 'post_underskjema:guard-test', 'a'*64, uuid4()), None
    if name == NAMES[1]:
        with psycopg.connect(DATABASE_URL) as db:
            status = db.execute('select status from shareholder_register_filing.production_filing_submissions where id=%s', (submission,)).fetchone()[0]
        return 'select shareholder_register_filing.append_production_filing_event(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', (submission, 'post_underskjema:guard-test', 'prepared', 1, 'a'*64, uuid4(), None, None, status, False), None
    if name == NAMES[2]:
        return 'select shareholder_register_filing.claim_production_feedback_reconciliation(%s,%s)', (submission, lease), None
    if name == NAMES[3]:
        return 'select shareholder_register_filing.release_production_feedback_reconciliation(%s,%s)', (submission, lease), None
    if name == NAMES[4]:
        return 'select shareholder_register_filing.append_production_feedback_reconciliation(%s,%s,%s,%s,%s,%s,%s)', (submission, lease, reference, 'processing', [], None, None), None
    return 'select shareholder_register_filing.record_production_feedback_artifact(%s,%s,%s,%s,%s,%s,%s,%s)', (f['company'], submission, uuid4(), 'guard-artifact', 'application/xml', 1, 'a'*64, 'accepted'), 'production_feedback_document_relationship_mismatch'


async def execute_waiter(f, sql, args, ready, *, actor=None, expected_error=None):
    async with store(f, actor=actor)._transaction() as db:
        ready.set_result((await (await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
        if expected_error:
            with pytest.raises(psycopg.Error, match=expected_error):
                await db.execute(sql, args)
        else:
            await db.execute(sql, args)
        raise psycopg.Rollback


@pytest.mark.parametrize('name', NAMES)
def test_each_journal_writer_waits_before_submission_row_lock(fixture, name):
    submission, reference = confirmed(fixture)
    lease = uuid4()
    if name in (NAMES[3], NAMES[4]):
        assert asyncio.run(store(fixture).claim_feedback_lease(submission, str(lease)))
    sql, args, expected_error = command(name, fixture, submission, reference, lease)
    async def run():
        task = None
        try:
            with psycopg.connect(DATABASE_URL) as blocker:
                blocker.execute('select public.company_archive_lock_company_v1(%s)', (fixture['company'],))
                ready = asyncio.get_running_loop().create_future()
                task = asyncio.create_task(execute_waiter(fixture, sql, args, ready, expected_error=expected_error))
                await waiting(await ready)
                # This is the consequential correction/archive side of the race.
                # If the writer takes the row first, NOWAIT detects the inversion.
                assert blocker.execute('select id from shareholder_register_filing.production_filing_submissions where id=%s for update nowait', (submission,)).fetchone()
            await task
        finally:
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_blocked_journal_rechecks_current_owner(fixture):
    submission, _ = confirmed(fixture)
    async def run():
        task = None
        try:
            with psycopg.connect(DATABASE_URL) as blocker:
                blocker.execute('select public.company_archive_lock_company_v1(%s)', (fixture['company'],))
                ready = asyncio.get_running_loop().create_future()
                task = asyncio.create_task(execute_waiter(fixture, 'select shareholder_register_filing.release_production_feedback_reconciliation(%s,%s)', (submission, uuid4()), ready))
                await waiting(await ready)
                blocker.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s", (fixture['company'], fixture['owner']))
            with pytest.raises(Exception): await task
        finally:
            if task and not task.done():
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_historical_recovery_keeps_expired_pilot_stale_mfa_and_invalidated_approval(fixture):
    submission, reference = confirmed(fixture)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute("update billing.production_pilot_entitlements set starts_at=now()-interval '2 days',expires_at=now()-interval '1 day' where id=%s", (fixture['entitlement'],))
        db.execute("update shareholder_register_filing.filing_approval_snapshots set invalidated_at=now(),invalidation_reason='fixture stale approval' where id=%s", (fixture['approval'],))
    session = store(fixture, fresh=False)
    lease = str(uuid4())
    assert asyncio.run(session.claim_feedback_lease(submission, lease))
    assert asyncio.run(session.read_claimed_reference(submission, lease)) == reference
    asyncio.run(session.release_feedback_lease(submission, lease))
    with pytest.raises(Exception):
        asyncio.run(store(fixture, actor=fixture['outsider'], fresh=False).claim_feedback_lease(submission, str(uuid4())))


def test_other_company_journal_is_not_blocked(fixture, backend_url):
    other_fixture = contextmanager(globals()['fixture'].__wrapped__)
    with other_fixture(backend_url) as other:
        submission, _ = confirmed(other)
        async def run():
            with psycopg.connect(DATABASE_URL) as blocker:
                blocker.execute('select public.company_archive_lock_company_v1(%s)', (fixture['company'],))
                ready = asyncio.get_running_loop().create_future()
                await asyncio.wait_for(execute_waiter(other, 'select shareholder_register_filing.release_production_feedback_reconciliation(%s,%s)', (submission, uuid4()), ready), 2)
        asyncio.run(run())


def identities(db):
    return db.execute("select oid,proowner,proacl::text,proconfig,prosecdef,provolatile,proparallel,prosrc from pg_proc where pronamespace='shareholder_register_filing'::regnamespace and proname=any(%s) order by oid", (list(NAMES) + ['approve_production_filing'],)).fetchall()


def test_mixed_successor_replay_and_rollback_preserve_journal_identity_acl_and_recovery(fixture):
    submission, _ = confirmed(fixture)
    with psycopg.connect(DATABASE_URL) as db:
        original = identities(db)
        membership = db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
    try:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
            assert not db.execute("select has_function_privilege('shareholder_register_filing_executor','shareholder_register_filing.lock_correction_predecessor_v1(uuid,uuid,integer,text)','execute')").fetchone()[0]
            assert identities(db) == original
        lease = str(uuid4())
        assert asyncio.run(store(fixture, fresh=False).claim_feedback_lease(submission, lease))
        asyncio.run(store(fixture, fresh=False).release_feedback_lease(submission, lease))
        # Reapply the real earlier wrapper block, source barriers, and historical
        # feedback replacement. The new successor must restore only its guards.
        guard=(ROOT/'supabase/migrations/20260924080249_documents_rf_consequential_company_guards.sql').read_text()
        block=guard[guard.index('do $wrap$'):guard.index('end; $wrap$;')+len('end; $wrap$;')]
        with psycopg.connect(DATABASE_URL) as db: db.execute(block)
        for migration in ('20260924085227_rf1086_source_review_bridge.sql', '20260924091015_rf1086_source_approval_foundation.sql', '20260917110951_rf1086_action_required_read_recovery.sql', MIGRATION, MIGRATION):
            with psycopg.connect(DATABASE_URL) as db: db.execute((ROOT/'supabase/migrations'/migration).read_text())
    finally:
        for migration in ('20260924091015_rf1086_source_approval_foundation.sql', MIGRATION):
            with psycopg.connect(DATABASE_URL) as db: db.execute((ROOT/'supabase/migrations'/migration).read_text())
    with psycopg.connect(DATABASE_URL) as db:
        assert identities(db) == original
        assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall() == membership
        assert not db.execute("select has_table_privilege('shareholder_register_filing_executor','shareholder_register_filing.production_filing_submissions','UPDATE')").fetchone()[0]
        for role in ('anon','authenticated','service_role','shareholder_register_filing_executor'):
            assert not db.execute("select has_function_privilege(%s,'shareholder_register_filing.lock_submission_company_write_v1(uuid)','execute')", (role,)).fetchone()[0]


def test_journal_rejects_repeatable_read_before_mutation(fixture):
    submission, _ = confirmed(fixture)
    async def run():
        async with store(fixture)._transaction(snapshot=True) as db:
            await db.execute('select shareholder_register_filing.release_production_feedback_reconciliation(%s,%s)', (submission, uuid4()))
    with pytest.raises(Exception):
        asyncio.run(run())


@pytest.mark.parametrize('scope', ['exact', 'no-guards', 'wrong-year', 'wrong-company', 'wrong-subject'])
def test_correction_port_requires_held_scope_and_returns_exact_historical_row(fixture, scope):
    submission, _ = confirmed(fixture)
    company = uuid4() if scope == 'wrong-company' else fixture['company']
    year = 2026 if scope == 'wrong-year' else 2025
    subject = fixture['outsider'] if scope == 'wrong-subject' else fixture['owner']
    # Use the actual verified runtime claims but acquire guards as the fixture
    # admin first on this exact connection. No role privilege persists afterward.
    import json
    from test_rf1086_database_runtime import claims
    with psycopg.connect(DATABASE_URL, row_factory=psycopg.rows.dict_row) as db:
        if scope != 'no-guards':
            db.execute('select public.company_archive_lock_company_v1(%s)', (company,))
            db.execute("select pg_advisory_xact_lock(hashtextextended('rf1086:year-source:'||%s||':'||%s,0))", (str(company), str(year)))
        db.execute('set local role shareholder_register_filing_executor')
        raw = json.dumps(claims(fixture, fresh=False))
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true),set_config('request.jwt.claims',%s,true)", (str(fixture['owner']), raw, raw))
        query = 'select * from shareholder_register_filing.lock_correction_predecessor_v1(%s,%s,%s,%s)'
        args = (submission, company, year, str(subject))
        if scope == 'exact':
            result = db.execute(query, args).fetchone()
            assert str(result['id']) == submission
            assert result['company_id'] == fixture['company'] and result['income_year'] == 2025
        else:
            with pytest.raises(psycopg.Error): db.execute(query, args)
            db.rollback()
