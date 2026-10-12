"""RF reads only the exact interview year under its existing company guard."""
import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
import pytest

from test_annual_purchase_basis_runtime import admitted, DATABASE_URL, ROOT
from test_annual_interview_company_guard_database import fixture_roles, seed
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access
from test_rf1086_year_source_database import session
from test_rf1086_source_company_guard_database import waiting
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, IncomeYear

pytestmark=pytest.mark.authority_database
MIGRATION='20260929144619_rf_annual_interview_read_admission.sql'
SIGNATURE='backend_system.list_annual_data_legacy_v1(uuid,integer,text)'


def scope_query(fixture,store):
    return rf.Rf1086SourceQuery(CompanyId(str(fixture['company'])),IncomeYear(2026),store.actor_id)


def test_exact_year_read_retains_history_semantics_and_same_connection_guard(admitted,backend_url):
    prior=seed(admitted,2025);store=session(admitted,backend_url);query=scope_query(admitted,store)
    async def run():
        async with store.source_admission(query) as scope:
            assert await scope.annual_interview() is None
        identity=seed(admitted,2026)
        async with store.source_admission(query) as scope:
            value=await scope.annual_interview()
            assert value.source_id==str(identity) and value.source_id!=str(prior)
            assert value.answers['has_unpaid_items'] is False
            with psycopg.connect(DATABASE_URL) as observer:
                assert not observer.execute('select pg_try_advisory_xact_lock(hashtextextended(%s,157))',(str(admitted['company']),)).fetchone()[0]
        with pytest.raises(rf.ShareholderRegisterFilingError):await scope.annual_interview()
    asyncio.run(run())
    with psycopg.connect(DATABASE_URL) as db:
        assert not db.execute("select has_table_privilege('shareholder_register_filing_executor','public.annual_data','SELECT')").fetchone()[0]
        for role in ('anon','authenticated','service_role'):
            assert not db.execute('select has_function_privilege(%s,%s,\'EXECUTE\')',(role,SIGNATURE)).fetchone()[0]


@pytest.mark.parametrize('revoke',[False,True])
def test_guard_wait_returns_new_interview_or_rejects_revoked_owner(admitted,backend_url,revoke):
    identity=seed(admitted);store=session(admitted,backend_url);query=scope_query(admitted,store)
    async def run():
        ready=asyncio.get_running_loop().create_future()
        original=store._transaction
        @asynccontextmanager
        async def observed_transaction(*args,**kwargs):
            async with original(*args,**kwargs) as db:
                ready.set_result((await(await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
                yield db
        store._transaction=observed_transaction
        async def read():
            async with store.source_admission(query) as scope:return await scope.annual_interview()
        task=None
        try:
            with psycopg.connect(DATABASE_URL) as blocker:
                blocker.execute('select public.company_archive_lock_company_v1(%s)',(admitted['company'],))
                task=asyncio.create_task(read())
                await waiting(await asyncio.wait_for(ready,3))
                if revoke:
                    blocker.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",(admitted['company'],admitted['owner']))
                else:
                    blocker.execute('update public.annual_data set answers=%s where id=%s',(Jsonb({'has_unpaid_items':True,'authority_to_submit_confirmed':True}),identity))
            if revoke:
                with pytest.raises(rf.ShareholderRegisterFilingError):await asyncio.wait_for(task,3)
            else:assert (await asyncio.wait_for(task,3)).answers['has_unpaid_items'] is True
        finally:
            if task is not None and not task.done():task.cancel()
            if task is not None:await asyncio.gather(task,return_exceptions=True)
    asyncio.run(run())


def test_malformed_current_answers_are_unavailable_not_truthy(admitted,backend_url):
    identity=seed(admitted)
    with psycopg.connect(DATABASE_URL) as db:
        db.execute('update public.annual_data set answers=%s where id=%s',(Jsonb({'has_unpaid_items':'false'}),identity))
    store=session(admitted,backend_url)
    async def run():
        async with store.source_admission(scope_query(admitted,store)) as scope:
            with pytest.raises(rf.ShareholderRegisterFilingError):await scope.annual_interview()
    asyncio.run(run())


def test_grant_rollback_replay_restores_restricted_migrator_authority():
    role='rf_interview_migrator_'+uuid4().hex[:10]
    with psycopg.connect(DATABASE_URL,autocommit=True) as db:
        db.execute(sql.SQL('create role {} login createrole password {}').format(sql.Identifier(role),sql.Literal(uuid4().hex)))
        try:
            db.execute(sql.SQL('grant backend_system_annual_data_reader to {} with admin true,inherit false,set false').format(sql.Identifier(role)))
            before=db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
            original=db.execute('select prosrc,proconfig,proowner,proacl::text from pg_proc where oid=%s::regprocedure',(SIGNATURE,)).fetchone()
            schemas=db.execute("select nspname,nspowner,nspacl::text from pg_namespace where nspname in ('backend_system','public') order by nspname").fetchall()
            # Connect as the restricted principal without exposing its credential.
            password=uuid4().hex
            db.execute(sql.SQL('alter role {} password {}').format(sql.Identifier(role),sql.Literal(password)))
            from psycopg.conninfo import make_conninfo
            with psycopg.connect(make_conninfo(DATABASE_URL,user=role,password=password),autocommit=True) as migrator:
                assert migrator.execute("select rolsuper,rolbypassrls,pg_has_role(current_user,'backend_system_annual_data_reader','SET') from pg_roles where rolname=current_user").fetchone()==(False,False,False)
                for _ in range(2):
                    migrator.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
                    assert not db.execute("select has_function_privilege('shareholder_register_filing_executor',%s,'EXECUTE')",(SIGNATURE,)).fetchone()[0]
                    migrator.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
                    assert db.execute("select has_function_privilege('shareholder_register_filing_executor',%s,'EXECUTE')",(SIGNATURE,)).fetchone()[0]
                    assert db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()==before
                    assert db.execute('select prosrc,proconfig,proowner,proacl::text from pg_proc where oid=%s::regprocedure',(SIGNATURE,)).fetchone()==original
                    assert db.execute("select nspname,nspowner,nspacl::text from pg_namespace where nspname in ('backend_system','public') order by nspname").fetchall()==schemas
        finally:
            # Restore the installed read even if an assertion interrupts replay.
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
            db.execute(sql.SQL('drop role {}').format(sql.Identifier(role)))
