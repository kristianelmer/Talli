"""RF writer company guard: real wait ordering, revocation, and safe rollback.

This does not assert a complete cross-owner production freshness barrier or
archive generation/export coverage for the source families.
"""
import asyncio
from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_annual_purchase_basis_runtime import admitted, insert
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access
from test_rf1086_year_source_database import (
    DATABASE_URL, ROOT, session, inputs, capture, query, remove_only_owned_source_fixture,
)
from test_rf1086_source_preview_database import generate, remove_only_preview_fixture
from test_rf1086_register_observation_database import cleanup_owned_fixture

pytestmark = pytest.mark.authority_database
MIGRATION = '20260924062746_rf1086_source_company_guard.sql'
TABLES = ('year_source_versions', 'year_source_heads', 'register_observations', 'source_previews')


async def waiting(pid):
    for _ in range(50):
        with psycopg.connect(DATABASE_URL) as observer:
            if observer.execute("select exists(select 1 from pg_stat_activity where pid=%s and wait_event='advisory')", (pid,)).fetchone()[0]:
                return
        await asyncio.sleep(.01)
    raise AssertionError('Exact RF backend did not wait on the company advisory guard')


async def lock_source(store, company, pid_ready, year=2026):
    async with store._transaction() as db:
        pid_ready.set_result((await (await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
        await db.execute('select shareholder_register_filing.lock_year_source_v1(%s::uuid,%s)', (str(company), year))


@pytest.mark.parametrize('change', ['none', 'owner', 'eligibility'])
def test_company_guard_precedes_year_guard_and_rechecks_after_wait(admitted, backend_url, change):
    """The blocked operation must not hold the RF-year lock or admit stale rights."""
    async def run():
        task = None
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)', (admitted['company'],))
            ready = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(lock_source(session(admitted, backend_url), admitted['company'], ready))
            await waiting(await ready)
            # A distinct transaction can still take the later RF-year guard.
            with psycopg.connect(DATABASE_URL) as observer:
                assert observer.execute("select pg_try_advisory_xact_lock(hashtextextended('rf1086:year-source:'||%s||':2026',0))", (str(admitted['company']),)).fetchone()[0]
            if change == 'owner':
                blocker.execute("update public.company_memberships set role='read_only' where company_id=%s", (admitted['company'],))
            elif change == 'eligibility':
                insert(blocker, 'public.company_eligibility_assessments', admitted['assessment'] | {
                    'id': uuid4(), 'operation_id': uuid4(), 'previous_assessment_id': admitted['current'],
                    'trigger': 'before_payment', 'assessed_at': blocker.execute('select clock_timestamp()').fetchone()[0],
                    'decision': 'blocked', 'consequential_operations_allowed': False,
                })
        if change == 'none':
            await task
        else:
            with pytest.raises(rf.ShareholderRegisterFilingError) as caught:
                await task
            expected = rf.ShareholderRegisterFilingErrorCode.FORBIDDEN if change == 'owner' else rf.ShareholderRegisterFilingErrorCode.COMPANY_YEAR_NOT_ADMITTED
            assert caught.value.code == expected
    asyncio.run(run())


def test_company_guard_does_not_block_another_company(admitted, backend_url):
    from types import SimpleNamespace
    other = globals()['admitted'].__wrapped__(SimpleNamespace())
    async def run():
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)', (admitted['company'],))
            ready = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(lock_source(session(admitted, backend_url), admitted['company'], ready))
            await waiting(await ready)
            independent = asyncio.get_running_loop().create_future()
            await lock_source(session(other, backend_url), other['company'], independent)
            assert not task.done()
        await task
    asyncio.run(run())


def test_unaccepted_actor_is_denied_before_waiting(admitted, backend_url):
    async def run():
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)', (admitted['company'],))
            ready = asyncio.get_running_loop().create_future()
            with pytest.raises(rf.ShareholderRegisterFilingError) as caught:
                await lock_source(session(admitted, backend_url, admitted['outsider']), admitted['company'], ready)
            assert caught.value.code == rf.ShareholderRegisterFilingErrorCode.NOT_FOUND
    asyncio.run(run())


def guard_state(db):
    return db.execute("select c.relname,t.tgtype,t.tgenabled,p.prosecdef,p.proconfig,p.proacl::text from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_proc p on p.oid=t.tgfoid where c.relnamespace='shareholder_register_filing'::regnamespace and t.tgname='source_company_guard' order by c.relname").fetchall()


def test_all_four_backstops_and_narrow_privileges_are_installed():
    with psycopg.connect(DATABASE_URL) as db:
        state = guard_state(db)
        assert [r[0] for r in state] == sorted(TABLES)
        assert all(r[1] == 31 and r[2] == 'O' and r[3] is False and r[4] == ['search_path=""'] for r in state)
        assert db.execute("select has_function_privilege('shareholder_register_filing_store_owner','public.company_archive_lock_company_v1(uuid)','EXECUTE')").fetchone()[0]
        for role in ('anon', 'authenticated', 'service_role', 'shareholder_register_filing_executor'):
            assert not db.execute("select has_function_privilege(%s,'shareholder_register_filing.lock_source_company_write_v1()','EXECUTE')", (role,)).fetchone()[0]
        for role in ('anon', 'authenticated', 'service_role'):
            assert not db.execute("select has_function_privilege(%s,'shareholder_register_filing.lock_year_source_v1(uuid,integer)','EXECUTE')", (role,)).fetchone()[0]


def test_replay_and_safe_rollback_preserve_original_source_preview_and_guard(admitted, backend_url):
    store = session(admitted, backend_url)
    command, context = inputs(admitted, store)
    source = capture(store, command, context)
    preview = generate(store, source)
    with psycopg.connect(DATABASE_URL) as db:
        memberships = db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
        guards = guard_state(db)
        acl = db.execute("select proacl::text from pg_proc where oid='public.company_archive_lock_company_v1(uuid)'::regprocedure").fetchone()
        db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
        assert guard_state(db) == guards
        assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall() == memberships
        assert db.execute("select proacl::text from pg_proc where oid='public.company_archive_lock_company_v1(uuid)'::regprocedure").fetchone() == acl
    try:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
            assert guard_state(db) == guards
            writes = db.execute("select proname,has_function_privilege('shareholder_register_filing_executor',oid,'EXECUTE') from pg_proc where pronamespace='shareholder_register_filing'::regnamespace and proname=any(%s) order by proname", (['lock_year_source_v1', 'append_year_source_v1', 'append_register_observation_v1', 'append_source_preview_v1'],)).fetchall()
            assert len(writes) == 4 and all(not allowed for _, allowed in writes)
            assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall() == memberships
        assert asyncio.run(store.read_current_year_source(query(command))) == source
        assert asyncio.run(store.source_preview(preview.preview_id)) == preview
        correction = replace(command, supersedes_source_id=source.source_id, supersedes_source_sha256=source.source_sha256, correction_reason='Reviewed correction')
        with pytest.raises(rf.ShareholderRegisterFilingError):
            capture(store, correction, context)
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
    assert capture(store, correction, context).version == 2
    assert asyncio.run(store.read_year_source(query(command), source.source_id)) == source
    assert asyncio.run(store.source_preview(preview.preview_id)) == preview


@pytest.mark.parametrize('table', TABLES)
def test_each_direct_insert_backstop_waits_before_constraint_check(admitted, backend_url, table):
    """Even an owner-table insert bypassing append APIs reaches the company guard."""
    from psycopg import sql
    from test_rf1086_register_observation_database import inputs as observation_inputs, capture as observation_capture
    store = session(admitted, backend_url)
    if table == 'register_observations':
        command, context = observation_inputs(admitted, store)
        observation_capture(store, command, context)
    else:
        command, context = inputs(admitted, store)
        source = capture(store, command, context)
        if table == 'source_previews':
            generate(store, source)
    async def duplicate(ready):
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as db:
            await db.execute('set local role shareholder_register_filing_store_owner')
            await db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)", (str(store.actor_id.subject), store._verified.claims_json))
            ready.set_result((await (await db.execute('select pg_backend_pid()')).fetchone())[0])
            await db.execute(sql.SQL('insert into {} select * from {} where company_id=%s').format(
                sql.Identifier('shareholder_register_filing', table), sql.Identifier('shareholder_register_filing', table)), (admitted['company'],))
    async def run():
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)', (admitted['company'],))
            ready = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(duplicate(ready))
            await waiting(await ready)
        with pytest.raises(psycopg.errors.UniqueViolation):
            await task
    asyncio.run(run())
