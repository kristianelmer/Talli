"""Amendment-table backstop on the disposable final authority topology."""
import asyncio
import json
from uuid import uuid4

import psycopg
import pytest

from test_annual_purchase_basis_runtime import admitted
from test_governance_ledger_company_guard_database import disposable_guard_role_access
from test_rf1086_source_company_guard_database import waiting
from test_rf1086_year_source_database import DATABASE_URL, ROOT

pytestmark = pytest.mark.authority_database
MIGRATION = '20261010004653_governance_register_evidence_company_guard.sql'
TABLE = 'corporate_governance.register_evidence_amendments'


def catalog(db):
    return db.execute("""select t.oid,t.tgtype,t.tgenabled,t.tgfoid::regprocedure::text,
        t.tgnargs,t.tgqual,t.tgisinternal,t.tgconstraint,t.tgdeferrable,t.tginitdeferred,
        t.tgattr::text,t.tgoldtable,t.tgnewtable
        from pg_trigger t where t.tgrelid=%s::regclass and t.tgname='aa_company_write_guard'""", (TABLE,)).fetchone()


def authority(db):
    return (
        db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall(),
        db.execute("select oid,proowner,proacl::text,prosrc,proconfig from pg_proc where pronamespace='corporate_governance'::regnamespace order by oid").fetchall(),
        db.execute("select relowner,relacl::text,relrowsecurity,relforcerowsecurity from pg_class where oid=%s::regclass", (TABLE,)).fetchone(),
        db.execute("select nspowner,nspacl::text from pg_namespace where nspname='corporate_governance'").fetchone(),
    )


def test_amendment_company_backstop_is_exact_and_runtime_authority_stays_closed():
    with psycopg.connect(DATABASE_URL) as db:
        row = catalog(db)
        assert row is not None
        assert row[1:] == (31, 'O', 'corporate_governance.lock_company_write_v1()',
                          0, None, False, 0, False, False, '', None, None)
        for role in ('anon', 'authenticated', 'service_role', 'corporate_governance_workflow_executor'):
            assert not db.execute("select has_function_privilege(%s,'corporate_governance.lock_company_write_v1()','EXECUTE')", (role,)).fetchone()[0]
            assert not db.execute("select has_table_privilege(%s,%s,'INSERT,UPDATE,DELETE,TRUNCATE')", (role, TABLE)).fetchone()[0]


def test_guard_reapply_and_retentive_rollback_preserve_catalog_rows_and_authority():
    with psycopg.connect(DATABASE_URL) as db:
        before, permissions = catalog(db), authority(db)
        # The disposable admin sees retained rows despite FORCE RLS.
        assert db.execute('select rolbypassrls from pg_roles where rolname=current_user').fetchone()[0]
        rows = db.execute(f'select id,snapshot_text from {TABLE} order by id').fetchall()
        for directory in ('migrations', 'rollback', 'migrations'):
            db.execute((ROOT / 'supabase' / directory / MIGRATION).read_text())
            assert catalog(db) == before
            assert authority(db) == permissions
            assert db.execute(f'select id,snapshot_text from {TABLE} order by id').fetchall() == rows


@pytest.mark.parametrize('isolation', ['repeatable read', 'serializable'])
def test_direct_owner_insert_requires_read_committed_before_row_constraints(disposable_guard_role_access, isolation):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set transaction isolation level ' + isolation)
        db.execute('set local role corporate_governance_store_owner')
        with pytest.raises(psycopg.errors.RaiseException, match='rf193_company_guard_requires_read_committed'):
            # Deliberately incomplete row: the guard must precede NOT NULL/FK checks.
            db.execute(f'insert into {TABLE}(company_id) values(%s)', (uuid4(),))
        db.rollback()


def test_direct_owner_insert_waits_for_its_row_company_before_constraints(disposable_guard_role_access):
    company = uuid4()

    async def run():
        ready = asyncio.get_running_loop().create_future()

        async def insert():
            async with await psycopg.AsyncConnection.connect(DATABASE_URL) as db:
                await db.execute('set local role corporate_governance_store_owner')
                ready.set_result((await (await db.execute('select pg_backend_pid()')).fetchone())[0])
                await db.execute(f'insert into {TABLE}(company_id) values(%s)', (company,))

        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)', (company,))
            task = asyncio.create_task(insert())
            try:
                await waiting(await ready)
                assert not task.done()
            finally:
                blocker.rollback()
                # No fixture row can survive: after the lock, FORCE RLS rejects
                # the absent verified actor before NOT NULL/FK checks.
                with pytest.raises(psycopg.errors.InsufficientPrivilege, match='row-level security'):
                    await asyncio.wait_for(task, 5)

    asyncio.run(run())


def test_trigger_does_not_bypass_owner_policy_for_another_company(admitted, disposable_guard_role_access):
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('set local role corporate_governance_store_owner')
        actor = str(admitted['owner'])
        db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",
                   (actor, json.dumps({'sub': actor, 'role': 'authenticated', 'aal': 'aal2'})))
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match='row-level security'):
            db.execute(f"""insert into {TABLE}(id,company_id,income_year,event_id,actor_id,
                idempotency_key,request_sha256,revision,anchor_sha256,amendment_sha256,
                withdrawal_id,replacement_id,recorded_at,snapshot_text)
                values(%s,%s,2026,%s,%s,%s,%s,1,%s,%s,%s,%s,clock_timestamp(),'{{}}')""",
                (uuid4(),uuid4(),uuid4(),admitted['owner'],str(uuid4()),'a'*64,'b'*64,'c'*64,uuid4(),uuid4()))
        db.rollback()
