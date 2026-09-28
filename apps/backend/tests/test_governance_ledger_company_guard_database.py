"""Real two-session tests for the Governance/Ledger company writer guard.

Run only in the disposable authority database lane. No external services or
production data are used; final cross-owner RF admission is tested separately.
"""
import asyncio
import json

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from test_annual_purchase_basis_runtime import admitted
from test_rf1086_source_company_guard_database import waiting
from test_rf1086_year_source_database import DATABASE_URL, ROOT

pytestmark = pytest.mark.authority_database
MIGRATION = '20260924080355_governance_ledger_company_write_guards.sql'
SCOPES = [('corporate_governance', 'corporate_governance_workflow_executor'),
          ('ledger', 'ledger_workflow_executor')]


@pytest.fixture(scope='module', autouse=True)
def disposable_guard_role_access():
    """Borrow SET only for the disposable admin; restore every original edge."""
    assert DATABASE_URL, 'DATABASE_URL must identify the disposable authority database'
    changed = []
    with psycopg.connect(DATABASE_URL) as db:
        principal, bypass = db.execute('select current_user,rolbypassrls from pg_roles where rolname=current_user').fetchone()
        assert bypass
        for role in ('corporate_governance_workflow_executor','ledger_workflow_executor',
                     'corporate_governance_ledger_bridge_owner','company_tax_filing_ledger_bridge_owner',
                     'corporate_governance_store_owner','ledger_store_owner'):
            if db.execute("select pg_has_role(current_user,%s,'SET')", (role,)).fetchone()[0]:
                continue
            prior = db.execute("select admin_option,inherit_option,set_option from pg_auth_members where roleid=%s::regrole and member=current_user::regrole and grantor=member", (role,)).fetchone()
            db.execute(sql.SQL('grant {} to {} with set true granted by {}').format(sql.Identifier(role),sql.Identifier(principal),sql.Identifier(principal)))
            changed.append((role, prior))
    try:
        yield
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            for role, prior in changed:
                db.execute(sql.SQL('revoke {} from {} granted by {}').format(sql.Identifier(role),sql.Identifier(principal),sql.Identifier(principal)))
                if prior is not None:
                    db.execute(sql.SQL('grant {} to {} with admin {}, inherit {}, set {} granted by {}').format(
                        sql.Identifier(role),sql.Identifier(principal),*(sql.SQL(str(v).lower()) for v in prior),sql.Identifier(principal)))


async def writer(fixture, schema, role, ready, *, original=False):
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as db:
        await db.execute(sql.SQL('set local role {}').format(sql.Identifier(role)))
        owner = str(fixture['owner'])
        await db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",
                         (owner, json.dumps({'sub': owner, 'role': 'authenticated', 'aal': 'aal2'})))
        ready.set_result((await (await db.execute('select pg_backend_pid()')).fetchone())[0])
        if original == 'corporate_bridge':
            await db.execute('select ledger.post_corporate_governance_entry_v1(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                ('guard-bridge', fixture['company'], 2026, 'SHAREHOLDER_LOAN', 'Guard test', Jsonb([]),
                 'CORPORATE_GOVERNANCE', str(fixture['company']), 'guard-test', owner, fixture['company']))
        elif original == 'tax_bridge':
            await db.execute('select ledger.post_company_tax_settlement_v1(%s,%s,%s,%s,%s,%s,%s,%s)',
                ('guard-bridge', fixture['company'], 2026, 'Guard test', Jsonb([]), str(fixture['company']), 'guard-test', owner))
        elif original:
            # Intentionally incomplete input must wait BEFORE the original body,
            # including its DECLARE initializers and its year/event locks.
            if schema == 'corporate_governance':
                await db.execute('select corporate_governance.prepare_supported_event_v1(%s,%s)',
                                 (Jsonb({'companyId': str(fixture['company'])}), owner))
            else:
                await db.execute('select backend_system.claim_ledger_workflow_v1(%s,%s,%s,%s,%s)',
                                 ('new_year_start', 'guard-order', fixture['company'], Jsonb({}), owner))
        else:
            await db.execute(sql.SQL('select {}.acquire_company_write_guard_v1(%s,%s)').format(sql.Identifier(schema)),
                             (fixture['company'], owner))


@pytest.mark.parametrize('schema,role', SCOPES)
@pytest.mark.parametrize('revoke', [False, True])
def test_guard_wait_rereads_current_owner_without_holding_local_locks(admitted, schema, role, revoke):
    async def run():
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)', (admitted['company'],))
            ready = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(writer(admitted, schema, role, ready))
            pid = await ready
            await waiting(pid)
            assert not blocker.execute("select exists(select 1 from pg_locks where pid=%s and locktype='advisory' and granted)", (pid,)).fetchone()[0]
            if revoke:
                blocker.execute("update public.company_memberships set role='read_only' where company_id=%s", (admitted['company'],))
        if revoke:
            with pytest.raises(psycopg.errors.RaiseException, match=f'{schema}_forbidden'):
                await task
        else:
            await task
    asyncio.run(run())


@pytest.mark.parametrize('schema,role', SCOPES)
def test_original_rpc_body_is_after_company_guard(admitted, schema, role):
    async def run():
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)', (admitted['company'],))
            ready = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(writer(admitted, schema, role, ready, original=True))
            pid = await ready
            await waiting(pid)
            assert not blocker.execute("select exists(select 1 from pg_locks where pid=%s and locktype='advisory' and granted)", (pid,)).fetchone()[0]
            blocker.execute("update public.company_memberships set role='read_only' where company_id=%s", (admitted['company'],))
        with pytest.raises(psycopg.errors.RaiseException, match=f'{schema}_forbidden'):
            await task
    asyncio.run(run())


@pytest.mark.parametrize('schema,role', SCOPES)
def test_unrelated_company_is_not_blocked(admitted, schema, role):
    from types import SimpleNamespace
    other = globals()['admitted'].__wrapped__(SimpleNamespace())
    async def run():
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)', (admitted['company'],))
            ready = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(writer(admitted, schema, role, ready))
            await waiting(await ready)
            await asyncio.wait_for(writer(other, schema, role, asyncio.get_running_loop().create_future()), 3)
            assert not task.done()
        await task
    asyncio.run(run())


def state(db):
    return db.execute("select p.oid,p.proowner,p.proacl::text,p.proconfig,p.prosrc from pg_proc p where p.prosrc like 'BEGIN%%rf193-company-write-guard-v1%%' order by p.oid").fetchall()


def memberships(db):
    return db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()


def test_backstops_cover_every_company_owned_source_table_and_keep_private_acls():
    with psycopg.connect(DATABASE_URL) as db:
        tables = db.execute("""select n.nspname,c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace
            where c.relkind='r' and n.nspname in ('ledger','corporate_governance')
            and exists(select 1 from pg_attribute a where a.attrelid=c.oid and a.attname='company_id' and not a.attisdropped)
            order by 1,2""").fetchall()
        tables += [('backend_system','ledger_command_receipts'),('backend_system','ledger_workflow_receipts')]
        for schema, table in tables:
            row = db.execute("select tgtype,tgenabled from pg_trigger where tgrelid=%s::regclass and tgname='aa_company_write_guard'", (f'{schema}.{table}',)).fetchone()
            assert row == (31, 'O'), (schema, table, row)
        for schema, role in SCOPES:
            helper = f'{schema}.acquire_company_write_guard_v1(uuid,text)'
            assert db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (role, helper)).fetchone()[0]
            for public_role in ('anon','authenticated','service_role'):
                assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (public_role, helper)).fetchone()[0]
        assert not db.execute("select has_table_privilege('corporate_governance_workflow_executor','shareholder_register_filing.register_observations','SELECT')").fetchone()[0]
        assert not db.execute("select has_table_privilege('corporate_governance_workflow_executor','documents.retained_originals','SELECT')").fetchone()[0]


@pytest.mark.parametrize('schema', ['ledger', 'corporate_governance'])
def test_restricted_row_writer_acquires_guard_without_private_rpc_access_or_rls_bypass(schema):
    """Exercise the production trigger with an invoker/RLS write, as the overlap view does.

    Temporary rows isolate the guard's permissions from each owner's business
    validation. The workspace lane also exercises the real legacy opening write.
    """
    from uuid import uuid4
    company, outsider = uuid4(), uuid4()
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('create temporary table guard_writer_probe(company_id uuid, value integer) on commit drop')
        db.execute('alter table guard_writer_probe enable row level security')
        db.execute('alter table guard_writer_probe force row level security')
        db.execute("create policy tenant on guard_writer_probe to authenticated using(company_id=current_setting('test.guard_company')::uuid) with check(company_id=current_setting('test.guard_company')::uuid)")
        db.execute('grant select,insert,update,delete on guard_writer_probe to authenticated')
        db.execute(sql.SQL('create trigger company_guard before insert or update or delete on guard_writer_probe for each row execute function {}.lock_company_write_v1()').format(sql.Identifier(schema)))
        db.execute("select set_config('test.guard_company',%s,true)", (str(company),))
        db.execute('set local role authenticated')
        db.execute('insert into guard_writer_probe values(%s,1)', (company,))
        db.execute('update guard_writer_probe set value=2 where company_id=%s', (company,))
        assert db.execute('select value from guard_writer_probe').fetchall() == [(2,)]
        db.execute('reset role')
        assert db.execute("""select exists(select 1 from pg_locks where pid=pg_backend_pid()
            and locktype='advisory' and granted and objsubid=1
            and classid=((hashtextextended(%s,157)>>32)&4294967295)::oid
            and objid=(hashtextextended(%s,157)&4294967295)::oid)""", (str(company),str(company))).fetchone()[0]
        for statement, params in [
            ('insert into guard_writer_probe values(%s,3)', (outsider,)),
            ('update guard_writer_probe set company_id=%s', (outsider,)),
        ]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match='row-level security'):
                with db.transaction():
                    db.execute('set local role authenticated')
                    db.execute(statement, params)
        for function in [f'{schema}.lock_company_write_v1()', 'public.company_archive_lock_company_v1(uuid)']:
            assert not db.execute("select has_function_privilege('authenticated',%s,'EXECUTE')", (function,)).fetchone()[0]
        db.execute('set local role authenticated')
        db.execute('delete from guard_writer_probe where company_id=%s', (company,))
        assert db.execute('select count(*) from guard_writer_probe').fetchone()[0] == 0


def test_replay_preserves_function_identity_membership_and_rollback_fails_closed(admitted):
    with psycopg.connect(DATABASE_URL) as db:
        before, roles = state(db), memberships(db)
        schema_acl = db.execute("select oid,nspacl::text from pg_namespace where nspname in ('ledger','corporate_governance','backend_system') order by oid").fetchall()
        assert before
        db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
        assert state(db) == before and memberships(db) == roles
        assert db.execute("select oid,nspacl::text from pg_namespace where nspname in ('ledger','corporate_governance','backend_system') order by oid").fetchall() == schema_acl
    try:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
            assert state(db) == before and memberships(db) == roles
        async def denied():
            for schema, role in SCOPES:
                with pytest.raises(psycopg.errors.RaiseException, match=f'{schema}_company_guard_rollback'):
                    await writer(admitted, schema, role, asyncio.get_running_loop().create_future())
        asyncio.run(denied())
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
            assert state(db) == before and memberships(db) == roles


def test_recutover_validates_a_writer_whose_owner_cannot_execute_it():
    """The language validator requires EXECUTE independently of ownership.

    An isolated overload exercises the real wrapper migration without changing
    the callable production coordinator or its historical ACL.
    """
    signature = 'backend_system.lock_ledger_writer_year_v1(jsonb,text,boolean)'
    with psycopg.connect(DATABASE_URL, autocommit=True) as db:
        assert db.execute('select to_regprocedure(%s)', (signature,)).fetchone()[0] is None
        schema_owner, had_create = db.execute("""select pg_get_userbyid(nspowner),
            has_schema_privilege('ledger_store_owner',oid,'CREATE')
            from pg_namespace where nspname='backend_system'""").fetchone()
        try:
            with db.transaction():
                db.execute(sql.SQL('set local role {}').format(sql.Identifier(schema_owner)))
                db.execute('grant create on schema backend_system to ledger_store_owner')
                db.execute('set local role ledger_store_owner')
                db.execute("""create function backend_system.lock_ledger_writer_year_v1(
                    p_request jsonb,p_verified_subject text,p_recutover_probe boolean)
                    returns void language plpgsql volatile security definer set search_path=''
                    as $$begin raise exception 'unguarded_probe_body';end$$""")
                db.execute(sql.SQL('revoke all on function {} from public,ledger_store_owner').format(sql.SQL(signature)))
                db.execute(sql.SQL('grant execute on function {} to ledger_workflow_executor').format(sql.SQL(signature)))
                db.execute(sql.SQL('set local role {}').format(sql.Identifier(schema_owner)))
                if not had_create:
                    db.execute('revoke create on schema backend_system from ledger_store_owner')
            def identity():
                return db.execute("""select oid,proowner,proacl::text,proconfig,prosecdef
                    from pg_proc where oid=%s::regprocedure""", (signature,)).fetchone()
            def schema_acls():
                return db.execute("""select oid,nspacl::text from pg_namespace
                    where nspname in ('ledger','corporate_governance','backend_system') order by oid""").fetchall()
            before, roles, acls = identity(), memberships(db), schema_acls()
            for _ in range(2):
                db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
                assert identity() == before and memberships(db) == roles
                assert schema_acls() == acls
                assert not db.execute("select has_function_privilege('ledger_store_owner',%s,'EXECUTE')", (signature,)).fetchone()[0]
                assert db.execute("select prosrc like 'BEGIN%%rf193-company-write-guard-v1%%' from pg_proc where oid=%s::regprocedure", (signature,)).fetchone()[0]
            with pytest.raises(psycopg.errors.RaiseException, match='ledger_forbidden'):
                with db.transaction():
                    db.execute('set local role ledger_workflow_executor')
                    db.execute("select backend_system.lock_ledger_writer_year_v1('{}'::jsonb,null,true)")
        finally:
            db.execute('rollback')
            with db.transaction():
                db.execute('set local role ledger_store_owner')
                db.execute(sql.SQL('drop function if exists {}').format(sql.SQL(signature)))


@pytest.mark.parametrize('bridge,role', [('corporate_bridge','corporate_governance_ledger_bridge_owner'),
                                        ('tax_bridge','company_tax_filing_ledger_bridge_owner')])
def test_pure_bridge_delegates_enter_guard_before_inner_validation(admitted, bridge, role):
    async def run():
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)', (admitted['company'],))
            ready = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(writer(admitted, 'ledger', role, ready, original=bridge))
            await waiting(await ready)
            blocker.execute("update public.company_memberships set role='read_only' where company_id=%s", (admitted['company'],))
        with pytest.raises(psycopg.errors.RaiseException, match='ledger_forbidden'):
            await task
    asyncio.run(run())


@pytest.mark.parametrize('table,role', [('corporate_governance.supported_events','corporate_governance_store_owner'),
                                       ('ledger.entry_corrections','ledger_store_owner'),
                                       ('ledger.entry_reversals','ledger_store_owner')])
def test_direct_table_backstop_waits_before_invalid_insert_can_finish(admitted, table, role):
    async def direct(ready):
        async with await psycopg.AsyncConnection.connect(DATABASE_URL) as db:
            await db.execute(sql.SQL('set local role {}').format(sql.Identifier(role)))
            actor = str(admitted['owner'])
            await db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",
                             (actor,json.dumps({'sub': actor,'role':'authenticated','aal':'aal2'})))
            ready.set_result((await (await db.execute('select pg_backend_pid()')).fetchone())[0])
            await db.execute(sql.SQL('insert into {} (company_id) values (%s)').format(sql.Identifier(*table.split('.'))), (admitted['company'],))
    async def run():
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)', (admitted['company'],))
            ready = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(direct(ready))
            await waiting(await ready)
            assert not task.done()
        with pytest.raises(psycopg.Error):
            await task
    asyncio.run(run())
