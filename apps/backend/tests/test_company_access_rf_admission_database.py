"""Company Access's shared guard under actual restricted roles and two sessions.

Mandatory disposable-database lane; host collection alone is not runtime proof.
"""
import asyncio
import json
import os
from pathlib import Path
from datetime import timedelta
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from test_annual_purchase_basis_runtime import admitted, insert

pytestmark = pytest.mark.authority_database
DATABASE_URL = os.environ.get("DATABASE_URL", "")
ROOT = Path(__file__).resolve().parents[3]
MIGRATION = "20260924080208_company_access_rf_admission_guard.sql"
PROJECTION = "public.company_access_read_rf_admission_v1(uuid,integer,text)"
TABLES = (
    "companies", "company_memberships", "company_eligibility_assessments",
    "company_year_admissions", "company_year_acceptances", "customer_agreement_acceptances",
)
WRITERS = (
    "company_access_admit_company_year",
    "company_access_reaccept_agreement", "company_access_recheck_company_year_eligibility",
    "company_access_administer_membership", "company_access_accept_invitation",
    "company_access_request_cancellation", "company_access_resume_cancellation",
    "company_access_review_deletion", "company_access_finalize_deletion",
    "company_access_company_year_allows_consequential_v1",
)


@pytest.fixture(scope="module")
def restricted_url():
    assert DATABASE_URL, "DATABASE_URL must identify the owned disposable database"
    name, password = "ca_rf_guard_" + uuid4().hex, uuid4().hex
    with psycopg.connect(DATABASE_URL) as db:
        db.execute(sql.SQL("create role {} login noinherit nobypassrls password {}").format(
            sql.Identifier(name), sql.Literal(password)))
        db.execute(sql.SQL("grant shareholder_register_filing_executor,company_access_executor to {} with inherit false,set true").format(sql.Identifier(name)))
    try:
        yield make_conninfo(DATABASE_URL, user=name, password=password)
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute(sql.SQL("revoke shareholder_register_filing_executor,company_access_executor from {}").format(sql.Identifier(name)))
            db.execute(sql.SQL("drop role {}").format(sql.Identifier(name)))


async def actor_context(db, fixture, *, actor=None, fresh=True, role="shareholder_register_filing_executor"):
    subject = str(actor or fixture["owner"])
    claims = {"sub": subject, "role": "authenticated", "aal": "aal2",
              "amr": [{"method": "totp", "timestamp": fixture["now"].timestamp() - (0 if fresh else 7200)}]}
    await db.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
    await db.execute("select set_config('talli.verified_actor_id',%s,true),set_config('talli.verified_actor_claims',%s,true)",
                     (subject, json.dumps(claims)))


async def read_projection(db, fixture, *, subject=None, year=2026):
    return (await (await db.execute(
        "select public.company_access_read_rf_admission_v1(%s,%s,%s)",
        (fixture["company"], year, str(subject or fixture["owner"])),
    )).fetchone())[0]


async def wait_for_company_guard(pid):
    for _ in range(100):
        with psycopg.connect(DATABASE_URL) as observer:
            if observer.execute("select exists(select 1 from pg_stat_activity where pid=%s and wait_event='advisory')", (pid,)).fetchone()[0]:
                return
        await asyncio.sleep(.01)
    raise AssertionError("Selected backend did not wait on the company guard")


@pytest.mark.parametrize("change", ["identity", "owner", "eligibility", "confirmation", "status"])
def test_admission_sees_committed_change_after_wait(admitted, restricted_url, change):
    async def run():
        ready = asyncio.get_running_loop().create_future()

        async def reader():
            async with await psycopg.AsyncConnection.connect(restricted_url) as db:
                await actor_context(db, admitted)
                ready.set_result((await (await db.execute("select pg_backend_pid()")).fetchone())[0])
                return await read_projection(db, admitted)

        with psycopg.connect(DATABASE_URL) as writer:
            writer.execute("select public.company_archive_lock_company_v1(%s)", (admitted["company"],))
            task = asyncio.create_task(reader())
            await wait_for_company_guard(await ready)
            # Company precedes eligibility: the blocked reader must not hold it.
            with psycopg.connect(DATABASE_URL) as observer:
                assert observer.execute("select pg_try_advisory_xact_lock(hashtextextended('eligibility-recheck|'||%s,187))", (str(admitted["admission"]),)).fetchone()[0]
            if change == "identity":
                writer.execute("update public.companies set name='Renamed AS',address='New street',postal_code='0001',city='New city' where id=%s", (admitted["company"],))
            elif change == "owner":
                writer.execute("update public.company_memberships set role='read_only' where company_id=%s", (admitted["company"],))
            elif change == "eligibility":
                insert(writer, "public.company_eligibility_assessments", admitted["assessment"] | {
                    "id": uuid4(), "operation_id": uuid4(), "previous_assessment_id": admitted["current"],
                    "trigger": "before_filing", "assessed_at": writer.execute("select clock_timestamp()").fetchone()[0],
                    "decision": "blocked", "consequential_operations_allowed": False,
                })
            elif change == "confirmation":
                writer.execute("update public.companies set identity_confirmed_at=null where id=%s", (admitted["company"],))
            else:
                writer.execute("update public.companies set status_text='deleted_retention_record' where id=%s", (admitted["company"],))
        if change == "identity":
            result = await task
            assert result["legalName"] == "Renamed AS"
            assert (result["address"], result["postalCode"], result["city"]) == ("New street", "0001", "New city")
            assert result["companyId"] == str(admitted["company"])
            assert result["organizationNumber"] == admitted["org"]
            assert result["incomeYear"] == 2026 and result["acceptedOwner"] is True
            assert result["consequentialOperationsAllowed"] is True
            assert set(result) == {"companyId", "incomeYear", "organizationNumber", "legalName", "entityType",
                                   "address", "postalCode", "city", "identityConfirmedAt", "identityLockedAt",
                                   "acceptedOwner", "consequentialOperationsAllowed"}
        else:
            expected = {"owner": "company_access_forbidden", "eligibility": "company_access_company_year_not_admitted",
                        "confirmation": "company_access_identity_not_confirmed", "status": "company_access_identity_not_confirmed"}[change]
            with pytest.raises(psycopg.errors.RaiseException, match=expected):
                await task
    asyncio.run(run())



def test_mfa_expiring_while_guard_waits_is_denied(admitted, restricted_url):
    async def run():
        ready = asyncio.get_running_loop().create_future()

        async def reader():
            async with await psycopg.AsyncConnection.connect(restricted_url) as db:
                clock = (await (await db.execute("select clock_timestamp()")).fetchone())[0]
                await actor_context(db, admitted | {"now": clock - timedelta(seconds=898)})
                ready.set_result((await (await db.execute("select pg_backend_pid()")).fetchone())[0])
                return await read_projection(db, admitted)

        with psycopg.connect(DATABASE_URL) as holder:
            holder.execute("select public.company_archive_lock_company_v1(%s)", (admitted["company"],))
            task = asyncio.create_task(reader())
            await wait_for_company_guard(await ready)
            # Bounded wait crosses the existing 15-minute cutoff while the
            # projection's outer statement timestamp remains unchanged.
            await asyncio.sleep(2.1)
        with pytest.raises(psycopg.errors.RaiseException, match="company_access_forbidden"):
            await task
    asyncio.run(run())


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_admission_rejects_pre_guard_snapshot_but_legacy_read_remains_compatible(admitted, restricted_url, isolation):
    async def run():
        async with await psycopg.AsyncConnection.connect(restricted_url) as db:
            await db.execute(sql.SQL("set transaction isolation level " + isolation))
            await actor_context(db, admitted)
            assert (await (await db.execute("select public.company_access_company_year_allows_consequential_v1(%s,2026)", (admitted["company"],))).fetchone())[0]
            with pytest.raises(psycopg.errors.RaiseException, match="company_access_rf_read_committed_required"):
                await read_projection(db, admitted)
            await db.rollback()
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["outsider", "reviewer", "subject", "mfa", "year"])
def test_projection_rejects_untrusted_scope(admitted, restricted_url, failure):
    if failure == "reviewer":
        with psycopg.connect(DATABASE_URL) as seed:
            insert(seed, "public.company_memberships", {"company_id": admitted["company"], "user_id": admitted["outsider"],
                                                      "role": "reviewer", "accepted_at": admitted["now"]})

    async def run():
        async with await psycopg.AsyncConnection.connect(restricted_url) as db:
            await actor_context(db, admitted, actor=admitted["outsider"] if failure in ("outsider", "reviewer") else None, fresh=failure != "mfa")
            await db.execute("set local lock_timeout='100ms'")
            with psycopg.connect(DATABASE_URL) as holder:
                if failure != "year":
                    holder.execute("select public.company_archive_lock_company_v1(%s)", (admitted["company"],))
                with pytest.raises(psycopg.errors.RaiseException, match="company_access_company_year_not_admitted" if failure == "year" else "company_access_forbidden"):
                    await read_projection(db, admitted, subject=admitted["outsider"] if failure in ("outsider", "reviewer", "subject") else None, year=2025 if failure == "year" else 2026)
            await db.rollback()
    asyncio.run(run())


@pytest.mark.parametrize("table", TABLES)
def test_each_backstop_blocks_direct_insert_before_duplicate_constraint(admitted, table):
    async def run():
        ready = asyncio.get_running_loop().create_future()
        key = "id" if table == "companies" else "company_id"

        async def duplicate():
            async with await psycopg.AsyncConnection.connect(DATABASE_URL) as writer:
                ready.set_result((await (await writer.execute("select pg_backend_pid()")).fetchone())[0])
                await writer.execute(sql.SQL("insert into public.{} select * from public.{} where {}=%s").format(
                    sql.Identifier(table), sql.Identifier(table), sql.Identifier(key)), (admitted["company"],))

        with psycopg.connect(DATABASE_URL) as holder:
            holder.execute("select public.company_archive_lock_company_v1(%s)", (admitted["company"],))
            task = asyncio.create_task(duplicate())
            await wait_for_company_guard(await ready)
        with pytest.raises(psycopg.errors.UniqueViolation):
            await task
    asyncio.run(run())


def test_public_membership_writer_waits_before_operation_and_row_locks(admitted, restricted_url):
    operation = uuid4()
    with psycopg.connect(DATABASE_URL) as seed:
        insert(seed, "public.company_memberships", {"company_id": admitted["company"], "user_id": admitted["outsider"],
                                                  "role": "reviewer", "accepted_at": admitted["now"]})

    async def run():
        ready = asyncio.get_running_loop().create_future()

        async def update():
            async with await psycopg.AsyncConnection.connect(restricted_url) as db:
                await actor_context(db, admitted, role="company_access_executor")
                ready.set_result((await (await db.execute("select pg_backend_pid()")).fetchone())[0])
                return await (await db.execute("select * from public.company_access_administer_membership(%s,%s,%s,'reviewer','read_only',null)",
                                              (operation, admitted["company"], admitted["outsider"]))).fetchone()

        with psycopg.connect(DATABASE_URL) as holder:
            holder.execute("select public.company_archive_lock_company_v1(%s)", (admitted["company"],))
            task = asyncio.create_task(update())
            await wait_for_company_guard(await ready)
            with psycopg.connect(DATABASE_URL) as observer:
                assert observer.execute("select pg_try_advisory_xact_lock(hashtextextended(%s,160))", (f"{admitted['owner']}|{operation}",)).fetchone()[0]
                observer.execute("select * from public.company_memberships where company_id=%s and user_id=%s for update nowait", (admitted["company"], admitted["outsider"]))
        assert (await task)[2] == "read_only"
    asyncio.run(run())



@pytest.mark.parametrize("mutation", ["membership_update", "membership_delete", "identity_update"])
def test_committed_admission_holds_back_update_and_delete(admitted, restricted_url, mutation):
    async def run():
        ready = asyncio.get_running_loop().create_future()

        async def write():
            async with await psycopg.AsyncConnection.connect(DATABASE_URL) as db:
                ready.set_result((await (await db.execute("select pg_backend_pid()")).fetchone())[0])
                statements = {
                    "membership_update": "update public.company_memberships set role='read_only' where company_id=%s",
                    "membership_delete": "delete from public.company_memberships where company_id=%s",
                    "identity_update": "update public.companies set address='Changed after claim' where id=%s",
                }
                await db.execute(statements[mutation], (admitted["company"],))

        async with await psycopg.AsyncConnection.connect(restricted_url) as reader:
            await actor_context(reader, admitted)
            original = await read_projection(reader, admitted)
            task = asyncio.create_task(write())
            await wait_for_company_guard(await ready)
            assert await read_projection(reader, admitted) == original
            await reader.commit()
        await task
        async with await psycopg.AsyncConnection.connect(restricted_url) as reader:
            await actor_context(reader, admitted)
            if mutation == "identity_update":
                assert (await read_projection(reader, admitted))["address"] == "Changed after claim"
            else:
                with pytest.raises(psycopg.errors.RaiseException, match="company_access_forbidden"):
                    await read_projection(reader, admitted)
                await reader.rollback()
    asyncio.run(run())


def function_state(db):
    return db.execute("select p.oid,p.proowner,p.proacl::text,p.provolatile,p.prosrc from pg_proc p where p.pronamespace='public'::regnamespace and p.proname=any(%s) order by p.oid", (list(WRITERS),)).fetchall()


def test_narrow_acl_guard_topology_replay_and_safe_rollback(admitted, restricted_url):
    with psycopg.connect(DATABASE_URL) as db:
        assert db.execute("select rolcanlogin,rolinherit,rolbypassrls from pg_roles where rolname='company_access_executor'").fetchone() == (False, False, False)
        guards = db.execute("select c.relname,t.tgtype,t.tgenabled,p.prosecdef,p.proconfig from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_proc p on p.oid=t.tgfoid where t.tgname='company_access_projection_guard' order by c.relname").fetchall()
        assert [row[0] for row in guards] == sorted(TABLES)
        assert all(row[1:] == (31, 'O', True, ['search_path=""']) for row in guards)
        assert db.execute("select provolatile,prosecdef,proconfig from pg_proc where oid=%s::regprocedure", (PROJECTION,)).fetchone() == ('v', True, ['search_path=""'])
        for role in ("anon", "authenticated", "service_role"):
            assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (role, PROJECTION)).fetchone()[0]
        for role in ("shareholder_register_filing_executor", "shareholder_register_filing_store_owner"):
            assert db.execute("select has_function_privilege(%s,%s,'EXECUTE')", (role, PROJECTION)).fetchone()[0]
            for table in TABLES:
                assert not db.execute("select has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE')", (role, "public." + table)).fetchone()[0]
        members = db.execute("select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3").fetchall()
        trigger_acl = db.execute("select proacl::text from pg_proc where oid='public.company_access_guard_projection_write_v1()'::regprocedure").fetchone()
        schemas = db.execute("select nspacl::text from pg_namespace where nspname='public'").fetchone()
        before = function_state(db)
        mfa = db.execute("select proowner,proacl::text,provolatile,prosrc from pg_proc where oid='public.company_access_has_fresh_mfa_v1()'::regprocedure").fetchone()
        assert mfa[2] == 'v' and 'statement_timestamp' not in mfa[3]
        assert mfa[3].count('pg_catalog.clock_timestamp()') == 2
        assert len(before) == 11
        for row in before:
            assert row[3] == 'v'
            assert row[4].count('-- company-access RF guard v1') == 1
            marker = row[4].index('-- company-access RF guard v1')
            for token in ('pg_advisory_xact_lock', 'for update', 'company_access_lock_operation_v1'):
                if token in row[4]:
                    assert marker < row[4].index(token)
        db.execute((ROOT / "supabase/migrations" / MIGRATION).read_text())
        assert function_state(db) == before
        assert db.execute("select proacl::text from pg_proc where oid='public.company_access_guard_projection_write_v1()'::regprocedure").fetchone() == trigger_acl
        assert db.execute("select proowner,proacl::text,provolatile,prosrc from pg_proc where oid='public.company_access_has_fresh_mfa_v1()'::regprocedure").fetchone() == mfa
        assert db.execute("select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3").fetchall() == members
        assert db.execute("select nspacl::text from pg_namespace where nspname='public'").fetchone() == schemas
    try:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT / "supabase/rollback" / MIGRATION).read_text())
            assert function_state(db) == before
            assert db.execute("select proacl::text from pg_proc where oid='public.company_access_guard_projection_write_v1()'::regprocedure").fetchone() == trigger_acl
            assert not db.execute("select has_function_privilege('shareholder_register_filing_executor',%s,'EXECUTE')", (PROJECTION,)).fetchone()[0]
            assert db.execute("select count(*) from pg_trigger where tgname='company_access_projection_guard'").fetchone()[0] == 6
            assert db.execute("select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3").fetchall() == members
    finally:
        with psycopg.connect(DATABASE_URL) as db:
            db.execute((ROOT / "supabase/migrations" / MIGRATION).read_text())
    async def reread():
        async with await psycopg.AsyncConnection.connect(restricted_url) as db:
            await actor_context(db, admitted)
            assert (await read_projection(db, admitted))["companyId"] == str(admitted["company"])
    asyncio.run(reread())
