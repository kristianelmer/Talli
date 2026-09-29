"""Existing Ledger queries remain owned and complete inside RF admission."""
import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from test_annual_purchase_basis_runtime import admitted, DATABASE_URL, ROOT
from test_rf1086_database_runtime import backend_url, rf_fixture_admin_access
from test_rf1086_year_source_database import session
from test_rf1086_source_company_guard_database import waiting
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, CorrelationId, IncomeYear

pytestmark=pytest.mark.authority_database
MIGRATION='20260929160247_rf_annual_ledger_read_admission.sql'
SIGNATURES=('ledger.read_opening_bank_inputs_v1(uuid,integer,text)',
            'ledger.list_period_locks(uuid[],text,integer,text)')
CORRELATION=CorrelationId('rf-annual-ledger-database')


def query(fixture,store):
    return rf.Rf1086SourceQuery(CompanyId(str(fixture['company'])),IncomeYear(2026),store.actor_id)


def add_bank(db,fixture,year=2026):
    identity=uuid4()
    db.execute('insert into ledger.opening_bank_inputs(snapshot_id,company_id,income_year,bank_balance_nok,recorded_by,recorded_at) values(%s,%s,%s,%s,%s,clock_timestamp())',
        (identity,fixture['company'],year,Decimal('123.45'),fixture['owner']))
    return identity


def add_lock(db,fixture,year=2026):
    identity=uuid4()
    db.execute("insert into ledger.period_locks(id,company_id,income_year,reason,locked_by,locked_at) values(%s,%s,%s,'Original period reason',%s,clock_timestamp()-case when %s=2026 then interval '1 year' else interval '1 day' end)",
        (identity,fixture['company'],year,fixture['owner'],year))
    return identity


def test_complete_pagination_exact_year_original_values_and_expired_scope(admitted,backend_url):
    store=session(admitted,backend_url)
    with psycopg.connect(DATABASE_URL) as db:
        bank=add_bank(db,admitted);add_bank(db,admitted,2025)
        locks={year:add_lock(db,admitted,year) for year in range(2000,2101)}
    async def run():
        async with store.source_admission(query(admitted,store)) as scope:
            result=await scope.annual_ledger_inputs(CORRELATION)
            assert len(result.opening_bank_inputs)==1
            value=result.opening_bank_inputs[0]
            assert value.snapshot_id==str(bank) and value.bank_balance.amount==Decimal('123.45')
            assert str(value.recorded_by.subject)==str(admitted['owner'])
            assert len(result.period_locks)==1 and str(result.period_locks[0].period_lock_id)==str(locks[2026])
            assert result.period_locks[0].reason=='Original period reason'
            with psycopg.connect(DATABASE_URL) as observer:
                assert not observer.execute('select pg_try_advisory_xact_lock(hashtextextended(%s,157))',(str(admitted['company']),)).fetchone()[0]
        with pytest.raises(rf.ShareholderRegisterFilingError):await scope.annual_ledger_inputs(CORRELATION)
    asyncio.run(run())
    with psycopg.connect(DATABASE_URL) as db:
        for table in ('ledger.period_locks','ledger.opening_bank_inputs'):
            assert not db.execute("select has_table_privilege('shareholder_register_filing_executor',%s,'SELECT')",(table,)).fetchone()[0]
        for role in ('anon','authenticated','service_role'):
            for signature in SIGNATURES:
                assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')",(role,signature)).fetchone()[0]


def test_complete_empty_current_year_keeps_prior_facts_out(admitted,backend_url):
    store=session(admitted,backend_url)
    with psycopg.connect(DATABASE_URL) as db:add_bank(db,admitted,2025);add_lock(db,admitted,2025)
    async def run():
        async with store.source_admission(query(admitted,store)) as scope:
            result=await scope.annual_ledger_inputs(CORRELATION)
            assert result.opening_bank_inputs==() and result.period_locks==()
    asyncio.run(run())


@pytest.mark.parametrize('revoke',[False,True])
def test_wait_observes_committed_ledger_facts_or_rejects_revoked_owner(admitted,backend_url,revoke):
    store=session(admitted,backend_url)
    async def run():
        ready=asyncio.get_running_loop().create_future();original=store._transaction
        @asynccontextmanager
        async def observed(*args,**kwargs):
            async with original(*args,**kwargs) as db:
                ready.set_result((await(await db.execute('select pg_backend_pid() as pid')).fetchone())['pid'])
                yield db
        store._transaction=observed
        async def read():
            async with store.source_admission(query(admitted,store)) as scope:
                return await scope.annual_ledger_inputs(CORRELATION)
        task=None
        try:
            with psycopg.connect(DATABASE_URL) as blocker:
                blocker.execute('select public.company_archive_lock_company_v1(%s)',(admitted['company'],))
                task=asyncio.create_task(read());await waiting(await asyncio.wait_for(ready,3))
                if revoke:
                    blocker.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s",(admitted['company'],admitted['owner']))
                else:bank=add_bank(blocker,admitted);lock=add_lock(blocker,admitted)
            if revoke:
                with pytest.raises(rf.ShareholderRegisterFilingError):await asyncio.wait_for(task,3)
            else:
                result=await asyncio.wait_for(task,3)
                assert result.opening_bank_inputs[0].snapshot_id==str(bank)
                assert str(result.period_locks[0].period_lock_id)==str(lock)
        finally:
            if task is not None and not task.done():task.cancel()
            if task is not None:await asyncio.gather(task,return_exceptions=True)
    asyncio.run(run())


def test_restricted_read_grant_rollback_replay_preserves_owner_definitions_and_authority():
    role='rf_annual_ledger_migrator_'+uuid4().hex[:8]
    with psycopg.connect(DATABASE_URL,autocommit=True) as db:
        password=uuid4().hex
        db.execute(sql.SQL('create role {} login createrole password {}').format(sql.Identifier(role),sql.Literal(password)))
        try:
            db.execute(sql.SQL('grant ledger_store_owner to {} with admin true,inherit false,set false').format(sql.Identifier(role)))
            def memberships():return db.execute('select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3').fetchall()
            def functions():return [db.execute('select prosrc,proconfig,proowner,proacl::text from pg_proc where oid=%s::regprocedure',(signature,)).fetchone() for signature in SIGNATURES]
            before=memberships();original=functions()
            schema=db.execute("select nspowner,nspacl::text from pg_namespace where nspname='ledger'").fetchone()
            with psycopg.connect(make_conninfo(DATABASE_URL,user=role,password=password),autocommit=True) as migrator:
                assert migrator.execute("select rolsuper,rolbypassrls,pg_has_role(current_user,'ledger_store_owner','SET') from pg_roles where rolname=current_user").fetchone()==(False,False,False)
                for _ in range(2):
                    migrator.execute((ROOT/'supabase/rollback'/MIGRATION).read_text())
                    for signature in SIGNATURES:
                        assert not db.execute("select has_function_privilege('shareholder_register_filing_executor',%s,'EXECUTE')",(signature,)).fetchone()[0]
                    migrator.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
                    assert memberships()==before and functions()==original
                    assert db.execute("select nspowner,nspacl::text from pg_namespace where nspname='ledger'").fetchone()==schema
        finally:
            db.execute((ROOT/'supabase/migrations'/MIGRATION).read_text())
            db.execute(sql.SQL('drop role {}').format(sql.Identifier(role)))
