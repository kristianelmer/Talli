"""The archive read guard spans historical years without widening delivery."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from uuid import uuid4

import psycopg
import pytest

from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsError, AnnualAccountsSourceQuery
from talli_backend.shared.kernel import CompanyId, IncomeYear
from test_annual_accounts_delivery_store_database import accounts_database, session, ACTOR, COMPANY
from test_postgres_tax_delivery_draft import draft_database
from test_postgres_tax_source_snapshot import database

pytestmark = pytest.mark.accounts_database
ROOT = Path(__file__).resolve().parents[3]
CONTRACT = '20261027150656_annual_accounts_company_archive_read_guard.sql'
MEMBERSHIPS = 'select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3'


@pytest.fixture(scope='module')
def archive_database(accounts_database):
    with psycopg.connect(**accounts_database, user='postgres', autocommit=True) as db:
        before = db.execute(MEMBERSHIPS).fetchall()
        db.execute((ROOT / 'supabase/contract-migrations' / CONTRACT).read_text())
        assert db.execute(MEMBERSHIPS).fetchall() == before
    return accounts_database


async def lock(database, year, *, aal='aal2', snapshot=False, company=COMPANY, delivery=False):
    async with session(database, aal=aal).transaction(snapshot=snapshot) as tx:
        query = AnnualAccountsSourceQuery(company, IncomeYear(year), ACTOR)
        if delivery:
            await tx.lock_delivery_archive(query)
        else:
            await tx.lock_company_year_archive(query)


@pytest.mark.parametrize('year', [2000, 2024, 2025, 2026, 2100])
def test_archive_guard_accepts_current_owner_for_each_supported_archive_year(archive_database, year):
    asyncio.run(lock(archive_database, year))


@pytest.mark.parametrize('year', [1999, 2101])
def test_archive_guard_refuses_years_outside_the_public_archive_contract(archive_database, year):
    async def raw_boundary():
        async with session(archive_database).transaction() as tx:
            await tx._one_row('select annual_accounts_filing.lock_company_year_archive_v1(%s::uuid,%s::integer,%s::text) as result',
                (str(COMPANY), year, str(ACTOR.subject)))
    with pytest.raises(AnnualAccountsError):
        asyncio.run(raw_boundary())


def test_delivery_guard_remains_2025_only(archive_database):
    asyncio.run(lock(archive_database, 2025, delivery=True))
    for year in (2024, 2026):
        with pytest.raises(AnnualAccountsError):
            asyncio.run(lock(archive_database, year, delivery=True))


def test_archive_guard_keeps_owner_mfa_and_read_committed_boundaries(archive_database):
    for options in ({'aal': 'aal1'}, {'snapshot': True}, {'company': CompanyId(str(uuid4()))}):
        with pytest.raises(AnnualAccountsError):
            asyncio.run(lock(archive_database, 2026, **options))


def test_revoked_owner_is_rechecked_after_the_company_guard_wait(archive_database):
    holder = psycopg.connect(**archive_database, user='postgres')
    holder.execute('select pg_advisory_xact_lock(hashtextextended(%s,157))', (str(COMPANY),))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, lock(archive_database, 2026))
        try:
            with psycopg.connect(**archive_database, user='postgres', autocommit=True) as admin:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    waiting = admin.execute("select count(*) from pg_stat_activity where wait_event_type='Lock' and query like 'select annual_accounts_filing.lock_company_year_archive_v1%%'").fetchone()[0]
                    if waiting:
                        break
                    time.sleep(.02)
                assert waiting == 1, 'owning archive guard must actually wait before revocation'
                admin.execute('delete from public.tax_draft_fixture_owner where company=%s and actor=%s', (str(COMPANY), str(ACTOR.subject)))
            holder.commit()
            with pytest.raises(AnnualAccountsError):
                future.result(timeout=5)
        finally:
            holder.close()
            with psycopg.connect(**archive_database, user='postgres', autocommit=True) as admin:
                admin.execute('insert into public.tax_draft_fixture_owner values(%s,%s) on conflict do nothing', (str(COMPANY), str(ACTOR.subject)))


def test_only_the_existing_accounts_executor_receives_the_new_guard(archive_database):
    with psycopg.connect(**archive_database, user='postgres') as db:
        assert db.execute("select has_function_privilege('annual_accounts_filing_workflow_executor','annual_accounts_filing.lock_company_year_archive_v1(uuid,integer,text)','EXECUTE')").fetchone() == (True,)
        for role in ('anon', 'authenticated', 'service_role', 'company_tax_filing_workflow_executor'):
            assert db.execute("select has_function_privilege(%s,'annual_accounts_filing.lock_company_year_archive_v1(uuid,integer,text)','EXECUTE')", (role,)).fetchone() == (False,)
        assert db.execute("select pg_get_userbyid(proowner),prosecdef,proconfig from pg_proc where oid='annual_accounts_filing.lock_company_year_archive_v1(uuid,integer,text)'::regprocedure").fetchone() == ('annual_accounts_filing_store_owner', True, ['search_path=""'])


def test_additive_guard_rollback_and_recutover_preserve_prior_guard_and_memberships(archive_database):
    with psycopg.connect(**archive_database, user='postgres', autocommit=True) as db:
        before = db.execute(MEMBERSHIPS).fetchall()
        old_guard = db.execute("select pg_get_functiondef('annual_accounts_filing.lock_delivery_archive_v1(uuid,integer,text)'::regprocedure)").fetchone()
        db.execute((ROOT / 'supabase/rollback' / CONTRACT).read_text())
        assert db.execute("select to_regprocedure('annual_accounts_filing.lock_company_year_archive_v1(uuid,integer,text)')").fetchone() == (None,)
        assert db.execute(MEMBERSHIPS).fetchall() == before
        assert db.execute("select pg_get_functiondef('annual_accounts_filing.lock_delivery_archive_v1(uuid,integer,text)'::regprocedure)").fetchone() == old_guard
        db.execute((ROOT / 'supabase/contract-migrations' / CONTRACT).read_text())
        assert db.execute(MEMBERSHIPS).fetchall() == before
    asyncio.run(lock(archive_database, 2026))
