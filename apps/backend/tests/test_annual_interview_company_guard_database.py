"""Existing interview writes serialize with RF admission without a new writer."""
import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from test_annual_purchase_basis_runtime import admitted, DATABASE_URL, ROOT, insert
from test_rf1086_source_company_guard_database import waiting

pytestmark = pytest.mark.authority_database
MIGRATION='20260929094835_annual_interview_company_guard.sql'


@pytest.fixture(scope='module',autouse=True)
def fixture_roles():
    borrowed=[]
    with psycopg.connect(DATABASE_URL) as db:
        principal=db.execute('select current_user').fetchone()[0]
        for role in ('authenticated','backend_system_annual_data_reader'):
            if db.execute("select pg_has_role(current_user,%s,'SET')",(role,)).fetchone()[0]:continue
            prior=db.execute('select admin_option,inherit_option,set_option from pg_auth_members where roleid=%s::regrole and member=current_user::regrole and grantor=member',(role,)).fetchone()
            db.execute(sql.SQL('grant {} to {} with set true granted by {}').format(sql.Identifier(role),sql.Identifier(principal),sql.Identifier(principal)))
            borrowed.append((role,prior))
    try:yield
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            for role,prior in reversed(borrowed):
                db.execute(sql.SQL('revoke {} from {} granted by {}').format(sql.Identifier(role),sql.Identifier(principal),sql.Identifier(principal)))
                if prior is not None:
                    db.execute(sql.SQL('grant {} to {} with admin {},inherit {},set {} granted by {}').format(sql.Identifier(role),sql.Identifier(principal),*(sql.SQL(str(v).lower()) for v in prior),sql.Identifier(principal)))


def bind(db,fixture,actor=None,role='authenticated'):
    actor=str(actor or fixture['owner']);claims=json.dumps({'sub':actor,'aal':'aal2'})
    db.execute(sql.SQL('set local role {}').format(sql.Identifier(role)))
    db.execute("select set_config('request.jwt.claims',%s,true),set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",(claims,actor,claims))


def values(fixture,year=2026):
    return {'id':uuid4(),'company_id':fixture['company'],'income_year':year,
            'answers':Jsonb({'has_unpaid_items':False,'authority_to_submit_confirmed':True}),
            'completed_by':fixture['owner'],'updated_by':fixture['owner']}


def seed(fixture,year=2026):
    row=values(fixture,year)
    with psycopg.connect(DATABASE_URL) as db:
        bind(db,fixture)
        insert(db,'public.annual_data',row)
    return row['id']


async def writer(fixture,ready,mode,identity,new_company=None):
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as db:
        # DELETE is maintenance-only; retain its existing lack of browser grant.
        if mode!='delete':await db.execute('set local role authenticated')
        actor=str(fixture['owner']);claims=json.dumps({'sub':actor,'aal':'aal2'})
        await db.execute("select set_config('request.jwt.claims',%s,true),set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",(claims,actor,claims))
        ready.set_result((await (await db.execute('select pg_backend_pid()')).fetchone())[0])
        if mode=='insert':
            await db.execute("insert into public.annual_data(id,company_id,income_year,answers,completed_by,updated_by) values(%s,%s,2026,%s,%s,%s)",
                             (identity,fixture['company'],Jsonb({'authority_to_submit_confirmed':True}),fixture['owner'],fixture['owner']))
        elif mode=='delete':await db.execute('delete from public.annual_data where id=%s',(identity,))
        elif mode=='move':await db.execute('update public.annual_data set company_id=%s where id=%s',(new_company,identity))
        else:await db.execute('update public.annual_data set answers=%s where id=%s',(Jsonb({'has_unpaid_items':True}),identity))


@pytest.mark.parametrize('mode',['insert','update','delete'])
def test_existing_writes_wait_for_company_admission_without_changing_facts(admitted,mode):
    identity=uuid4() if mode=='insert' else seed(admitted)
    async def run():
        with psycopg.connect(DATABASE_URL) as blocker:
            blocker.execute('select public.company_archive_lock_company_v1(%s)',(admitted['company'],))
            ready=asyncio.get_running_loop().create_future()
            task=asyncio.create_task(writer(admitted,ready,mode,identity))
            try:await waiting(await ready)
            except BaseException:
                task.cancel();await asyncio.gather(task,return_exceptions=True);raise
            # A read on the held guard still sees the pre-write committed facts.
            row=blocker.execute('select answers from public.annual_data where id=%s',(identity,)).fetchone()
            if mode=='insert':assert row is None
            else:assert row[0]['has_unpaid_items'] is False
        await task
    asyncio.run(run())
    with psycopg.connect(DATABASE_URL) as db:
        row=db.execute('select answers,completed_by,updated_by from public.annual_data where id=%s',(identity,)).fetchone()
        if mode=='delete':assert row is None
        else:
            assert row[0]==({'authority_to_submit_confirmed':True} if mode=='insert' else {'has_unpaid_items':True})
            assert row[1:]==(admitted['owner'],admitted['owner'])


@pytest.mark.parametrize('blocked_scope',['old','new'])
def test_reassignment_protects_both_company_scopes(admitted,blocked_scope):
    identity=seed(admitted);other=globals()['admitted'].__wrapped__(SimpleNamespace())
    with psycopg.connect(DATABASE_URL) as db:
        insert(db,'public.company_memberships',{'company_id':other['company'],'user_id':admitted['owner'],'role':'owner','accepted_at':other['now']})
    async def run():
        with psycopg.connect(DATABASE_URL) as blocker:
            company=admitted['company'] if blocked_scope=='old' else other['company']
            blocker.execute('select public.company_archive_lock_company_v1(%s)',(company,))
            ready=asyncio.get_running_loop().create_future()
            task=asyncio.create_task(writer(admitted,ready,'move',identity,other['company']))
            try:await waiting(await ready)
            except BaseException:
                task.cancel();await asyncio.gather(task,return_exceptions=True);raise
        await task
    asyncio.run(run())
    with psycopg.connect(DATABASE_URL) as db:
        assert db.execute('select company_id from public.annual_data where id=%s',(identity,)).fetchone()==(other['company'],)


def test_browser_authority_and_existing_history_reader_are_unchanged(admitted):
    for year in (2025,2026):seed(admitted,year)
    with psycopg.connect(DATABASE_URL) as db:
        bind(db,admitted,role='backend_system_annual_data_reader')
        rows=db.execute('select backend_system.list_annual_data_legacy_v1(%s,2026,%s)',(admitted['company'],str(admitted['owner']))).fetchone()[0]
        assert [r['incomeYear'] for r in rows]==[2026,2025]
        assert all(r['companyId']==str(admitted['company']) for r in rows)
    with psycopg.connect(DATABASE_URL) as db:
        bind(db,admitted,actor=admitted['outsider'])
        with pytest.raises(psycopg.errors.InsufficientPrivilege):insert(db,'public.annual_data',values(admitted,2024))
    with psycopg.connect(DATABASE_URL) as db:
        bind(db,admitted)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):db.execute('delete from public.annual_data where company_id=%s',(admitted['company'],))
    with psycopg.connect(DATABASE_URL) as db:
        for role in ('anon','authenticated','service_role','shareholder_register_filing_executor'):
            assert not db.execute("select has_function_privilege(%s,'backend_system.guard_annual_interview_write_v1()','EXECUTE')",(role,)).fetchone()[0]


def test_rollback_suspends_changes_and_replay_preserves_sources_and_authority(admitted):
    identity=seed(admitted)
    with psycopg.connect(DATABASE_URL,autocommit=True) as db:
        def state():
            return (db.execute('select to_jsonb(a) from public.annual_data a where id=%s',(identity,)).fetchone(),
                    db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall(),
                    db.execute("select relowner,relacl::text from pg_class where oid='public.annual_data'::regclass").fetchone(),
                    db.execute("select nspowner,nspacl::text from pg_namespace where nspname='backend_system'").fetchone(),
                    db.execute("select pg_get_functiondef('backend_system.list_annual_data_legacy_v1(uuid,integer,text)'::regprocedure)").fetchone(),
                    db.execute("select polname,polcmd,polroles,pg_get_expr(polqual,polrelid),pg_get_expr(polwithcheck,polrelid) from pg_policy where polrelid='public.annual_data'::regclass order by polname").fetchall())
        def guard_state():
            return db.execute("select proowner,proacl::text,proconfig,prosecdef from pg_proc where oid='backend_system.guard_annual_interview_write_v1()'::regprocedure").fetchone()
        guard_before=guard_state()
        assert db.execute("select pg_get_userbyid(proowner) from pg_proc where oid='backend_system.guard_annual_interview_write_v1()'::regprocedure").fetchone()==('company_archive_projection_executor',)
        before=state()
        for _ in range(2):
            db.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
            assert state()==before
            assert guard_state()==guard_before
            with pytest.raises(psycopg.errors.RaiseException,match='annual_interview_company_guard_rollback'):
                with db.transaction():
                    bind(db,admitted)
                    db.execute('update public.annual_data set answers=answers where id=%s',(identity,))
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
            assert state()==before
            assert guard_state()==guard_before
        with db.transaction():
            bind(db,admitted)
            db.execute('update public.annual_data set answers=answers where id=%s',(identity,))
