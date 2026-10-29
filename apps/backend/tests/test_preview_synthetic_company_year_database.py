"""Loopback SQL fixtures only; these tests are not hosted clickwrap evidence."""
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
import pytest

from talli_backend.adapters.supabase_company_access import SupabaseCompanyAccessAdapter, SupabaseConfiguration
from test_company_year_2025_database import admission_parameters, admit, canonical, digest, recheck_parameters, rpc

pytestmark = pytest.mark.authority_database
ORG = "992803750"
NAME = "Synthetic private Preview SQL-fixture"
MIGRATION = "20261029101236_preview_synthetic_company_year_admission.sql"


def connection():
    url = os.environ.get("DATABASE_URL", "")
    assert url and conninfo_to_dict(url).get("host") in ("127.0.0.1", "localhost", "::1"), "owned loopback DB required"
    return psycopg.connect(url, user="supabase_admin", row_factory=dict_row)


def user(db):
    subject = uuid4()
    email = f"synthetic-registry-{subject}@example.test"
    db.execute(
        "insert into auth.users(id,instance_id,aud,role,email,encrypted_password,email_confirmed_at,created_at,updated_at) "
        "values(%s,'00000000-0000-0000-0000-000000000000','authenticated','authenticated',%s,'',now(),now(),now())",
        (subject, email),
    )
    return subject, email


def actor(db, subject, email, *, aal="aal2", age=0):
    claims = canonical({
        "sub": str(subject), "email": email, "role": "authenticated", "aal": aal,
        "amr": [{"method": "totp", "timestamp": int(datetime.now(UTC).timestamp()) - age}],
    })
    for name, value in (("talli.verified_actor_id", str(subject)), ("talli.verified_actor_claims", claims), ("request.jwt.claims", claims)):
        db.execute("select set_config(%s,%s,true)", (name, value))
    db.execute("set local role company_access_executor")


def parameters(subject, email, year=2025, **patch):
    result = admission_parameters(subject, email, year) | {
        "p_org_number": ORG, "p_name": NAME, "p_source": "browser_test",
    } | patch
    facts = json.loads(result["p_public_facts_json"])
    facts.update(orgNumber=result["p_org_number"], name=result["p_name"], source=result["p_source"])
    return result | {"p_public_facts_json": canonical(facts), "p_public_facts_sha256": digest(facts)}


def seed_existing_company(db, subject):
    company = uuid4()
    db.execute("reset role")
    db.execute(
        "insert into public.companies(id,org_number,name,entity_type,address,postal_code,city,status_text,source,"
        "created_by,identity_confirmed_at,identity_locked_at) "
        "values(%s,%s,%s,'AS','Loopback fixture only','0155','OSLO','aktiv','browser_test',%s,now(),now())",
        (company, ORG, NAME, subject),
    )
    db.execute("insert into public.company_memberships(company_id,user_id,role,accepted_at) values(%s,%s,'owner',now())", (company, subject))
    return company


def test_synthetic_admission_requires_the_exact_existing_fixture_original_owner_and_fresh_mfa():
    with connection() as db:
        try:
            owner, owner_email = user(db)
            denied, denied_email = user(db)
            actor(db, owner, owner_email)
            # The new source cannot provision any company, including the approved org.
            with pytest.raises(psycopg.Error, match="company_access_invalid_request"):
                with db.transaction():
                    admit(db, parameters(owner, owner_email))
            assert db.execute("select count(*) n from public.companies where org_number=%s", (ORG,)).fetchone()["n"] == 0
            company = seed_existing_company(db, owner)
            actor(db, owner, owner_email)
            for identity, claims in [
                (parameters(owner, owner_email, p_name="Other identity"), (owner, owner_email, "aal2", 0)),
                (parameters(owner, owner_email, p_address="Changed address"), (owner, owner_email, "aal2", 0)),
                (parameters(owner, owner_email, p_org_number="992803751"), (owner, owner_email, "aal2", 0)),
                (parameters(denied, denied_email), (denied, denied_email, "aal2", 0)),
                (parameters(owner, owner_email), (owner, owner_email, "aal1", 0)),
                (parameters(owner, owner_email), (owner, owner_email, "aal2", 901)),
            ]:
                with pytest.raises(psycopg.Error, match="company_access_invalid_request"):
                    with db.transaction():
                        actor(db, claims[0], claims[1], aal=claims[2], age=claims[3])
                        admit(db, identity)
            assert db.execute("select count(*) n from public.company_year_admissions where company_id=%s", (company,)).fetchone()["n"] == 0
            adapter = SupabaseCompanyAccessAdapter(SupabaseConfiguration(url="http://127.0.0.1:1", anon_key="loopback-only"))

            async def rows(_token, query, values):
                return db.execute(query, values).fetchall()

            adapter._database_rows = rows
            for year in [2025, 2026]:
                command = parameters(owner, owner_email, year)
                result = admit(db, command)
                assert result["company_id"] == company and result["accounting_year"] == year
                assert admit(db, command)["company_year_admission_id"] == result["company_year_admission_id"]
                replay = asyncio.run(adapter.company_year_admission_replay("synthetic", str(command["p_operation_id"])))
                assert replay["registry_source"] == "browser_test" and replay["accounting_year"] == year
                # A former owner may still read the receipt as a member. The
                # synthetic HTTP retry must therefore re-enter this SQL guard.
                with db.transaction():
                    db.execute("reset role")
                    db.execute("update public.company_memberships set role='read_only' where company_id=%s and user_id=%s", (company, owner))
                    actor(db, owner, owner_email)
                    assert asyncio.run(adapter.company_year_admission_replay("synthetic", str(command["p_operation_id"]))) is not None
                    with pytest.raises(psycopg.Error, match="company_access_invalid_request"):
                        with db.transaction():
                            admit(db, command)
                    db.execute("reset role")
                    db.execute("update public.company_memberships set role='owner' where company_id=%s and user_id=%s", (company, owner))
                    actor(db, owner, owner_email)
                with pytest.raises(psycopg.Error, match="company_access_invalid_request"):
                    with db.transaction():
                        actor(db, owner, owner_email, aal="aal1")
                        admit(db, command)
                checked = rpc(db, "company_access_recheck_company_year_eligibility", recheck_parameters(db, owner, result, command))
                assert checked["replayed"] is False
            facts = db.execute("select accounting_year,public_facts->>'source' source from public.company_eligibility_assessments where company_id=%s order by accounting_year", (company,)).fetchall()
            assert {row["accounting_year"] for row in facts} == {2025, 2026}
            assert all(row["source"] == "browser_test" for row in facts)
            with pytest.raises(psycopg.Error, match="rollback_requires_retaining_existing_promises"):
                with db.transaction():
                    db.execute("reset role")
                    source = Path("supabase/rollback", MIGRATION).read_text()
                    db.execute(source.replace("begin;", "", 1).rsplit("commit;", 1)[0])
        finally:
            db.rollback()


def test_synthetic_admission_rejects_repeatable_read_before_any_promise_is_recorded():
    with connection() as db:
        db.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        try:
            subject, email = user(db)
            company = seed_existing_company(db, subject)
            actor(db, subject, email)
            with pytest.raises(psycopg.Error, match="company_access_invalid_request"):
                with db.transaction():
                    admit(db, parameters(subject, email))
            assert db.execute("select count(*) n from public.company_year_admissions where company_id=%s", (company,)).fetchone()["n"] == 0
        finally:
            db.rollback()


def test_empty_synthetic_rollback_and_recutover_preserve_the_function_security_and_role_memberships():
    def snapshot(db):
        return {
            "function": db.execute("select pg_get_functiondef(p.oid) definition,proowner,proacl::text,proconfig,prosecdef from pg_proc p where pronamespace='public'::regnamespace and proname='company_access_admit_company_year'").fetchone(),
            "memberships": db.execute("select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members where roleid='company_access_executor'::regrole order by member,grantor").fetchall(),
        }
    with connection() as db:
        try:
            before = snapshot(db)
            for direction in ["rollback", "migrations"]:
                source = Path("supabase", direction, MIGRATION).read_text()
                db.execute(source.replace("begin;", "", 1).rsplit("commit;", 1)[0])
            assert snapshot(db) == before
        finally:
            db.rollback()


def test_a_retained_old_function_body_cannot_admit_after_the_synthetic_path_is_rolled_back():
    """Model an invocation retaining its old compiled body across the source fence."""
    from psycopg import sql

    with connection() as db:
        try:
            subject, email = user(db)
            company = seed_existing_company(db, subject)
            original = db.execute("select pg_get_functiondef(p.oid) definition from pg_proc p where pronamespace='public'::regnamespace and proname='company_access_admit_company_year'").fetchone()["definition"]
            clone = "retained_admit_" + uuid4().hex
            copied = original.replace("public.company_access_admit_company_year(", f"pg_temp.{clone}(", 1)
            assert copied != original
            db.execute(copied)
            signature = db.execute("select p.oid::regprocedure::text signature from pg_proc p where p.pronamespace=pg_my_temp_schema() and p.proname=%s", (clone,)).fetchone()["signature"]
            db.execute(sql.SQL("alter function {} owner to company_access_executor").format(sql.SQL(signature)))
            db.execute(sql.SQL("revoke all on function {} from public,anon,authenticated,service_role").format(sql.SQL(signature)))
            command = parameters(subject, email)

            def retained_call():
                arguments = sql.SQL(",").join(sql.SQL("{} => %s").format(sql.Identifier(name)) for name in command)
                return db.execute(sql.SQL("select * from {}({})").format(sql.Identifier("pg_temp", clone), arguments), tuple(command.values())).fetchone()

            actor(db, subject, email)
            db.execute("savepoint initial_source_probe")
            assert retained_call()["company_id"] == company
            db.execute("rollback to savepoint initial_source_probe")
            db.execute("release savepoint initial_source_probe")
            db.execute("reset role")
            source = Path("supabase/rollback", MIGRATION).read_text()
            db.execute(source.replace("begin;", "", 1).rsplit("commit;", 1)[0])
            actor(db, subject, email)
            with pytest.raises(psycopg.Error, match="company_access_invalid_request"):
                with db.transaction():
                    retained_call()
            assert db.execute("select count(*) n from public.company_year_admissions where company_id=%s", (company,)).fetchone()["n"] == 0
            db.execute("reset role")
            source = Path("supabase/migrations", MIGRATION).read_text()
            db.execute(source.replace("begin;", "", 1).rsplit("commit;", 1)[0])
            actor(db, subject, email)
            assert retained_call()["company_id"] == company
        finally:
            db.rollback()
