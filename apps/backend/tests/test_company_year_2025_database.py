"""Real admission RPCs on an owned loopback DB; all fixture facts roll back."""
import hashlib
import json
import os
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
import pytest

from talli_backend.modules.company_access.public import (
    CompanyRegistryIdentity,
    CompanyYearAdmissionGatewayCommand,
)

pytestmark = pytest.mark.authority_database


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def admission_parameters(actor, email, year):
    filename = "capability_manifest.json" if year == 2026 else "capability_manifest_2025.json"
    manifest = json.loads(files("talli_backend.modules.company_access").joinpath(filename).read_text())
    expected = {2026: "9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de",
                2025: "2ac7047f632078b0438770d172d4c2289fd947b28e93c3a7eebc6995eb519fbe"}
    assert digest(manifest) == expected[year]
    company = CompanyRegistryIdentity(org_number="314159265", name="Synthetic SQL contract fixture",
        entity_type="AS", address="Loopback fixture only", postal_code="0155", city="OSLO",
        status_text="aktiv", source="brreg")
    public = {"orgNumber": company.org_number, "name": company.name, "entityType": "AS",
              "statusText": "aktiv", "source": "brreg"}
    answers = {row["code"]: row["supportedAnswer"] for row in manifest["questions"]}
    promise = {"accountingYear": year, "startsOn": f"{year}-01-01", "endsOn": f"{year}-12-31",
        "reconstructionRequiredFrom": f"{year}-01-01", "onlyAccountingAndFilingProduct": True,
        "customerClaims": manifest["promise"]["customerClaims"]}
    command = CompanyYearAdmissionGatewayCommand(operation_id=uuid4(), verified_actor=actor,
        verified_email=email, company=company, accounting_year=year, reconstruct_from=f"{year}-01-01",
        public_facts_json=canonical(public), public_facts_sha256=digest(public),
        answers_json=canonical(answers), answers_sha256=digest(answers),
        capability_manifest_json=canonical(manifest), capability_manifest_version=f"{year}.1",
        capability_manifest_sha256=digest(manifest), company_year_promise_json=canonical(promise),
        company_year_promise_sha256=digest(promise))
    values = command.model_dump()
    result = {"p_"+key: value for key, value in values.items() if key not in ("company", "verified_actor")}
    result["p_verified_subject"] = actor
    for key, value in company.model_dump().items():
        result["p_"+key] = value
    return result


def rpc(db, function, parameters):
    arguments = sql.SQL(",").join(sql.SQL("{} => %s").format(sql.Identifier(name)) for name in parameters)
    return db.execute(sql.SQL("select * from {}({})").format(sql.Identifier("public", function), arguments),
                      tuple(parameters.values())).fetchone()


def admit(db, parameters):
    return rpc(db, "company_access_admit_company_year", parameters)


def recheck_parameters(db, actor, admission, parameters):
    result = {name: parameters[name] for name in (
        "p_accounting_year", "p_capability_manifest_json", "p_capability_manifest_version",
        "p_capability_manifest_sha256", "p_public_facts_json", "p_public_facts_sha256",
        "p_answers_json", "p_answers_sha256",
    )}
    return result | {
        "p_operation_id": uuid4(), "p_verified_subject": actor,
        "p_company_year_admission_id": admission["company_year_admission_id"],
        "p_company_id": admission["company_id"],
        "p_previous_assessment_id": db.execute(
            "select eligibility_assessment_id from public.company_year_admissions where id=%s",
            (admission["company_year_admission_id"],),
        ).fetchone()["eligibility_assessment_id"],
        "p_trigger": "before_filing", "p_decision": "supported",
        "p_reason_codes": [], "p_reason_explanations": [],
        "p_next_step_code": "CONTINUE_COMPANY_YEAR", "p_next_step": "Continue synthetic loopback year",
        "p_consequential_operations_allowed": True, "p_archive_export_available": True,
    }


def test_real_sql_preserves_both_years_and_rejects_cross_year_evidence_and_changed_2025_promises():
    url = os.environ.get("DATABASE_URL", "")
    assert url and conninfo_to_dict(url).get("host") in ("127.0.0.1", "localhost", "::1"), "owned loopback DB required"
    actor = uuid4()
    email = f"year-contract-{actor}@example.test"
    with psycopg.connect(url, row_factory=dict_row) as db:
        try:
            db.execute("insert into auth.users(id,instance_id,aud,role,email,encrypted_password,email_confirmed_at,created_at,updated_at) "
                       "values(%s,'00000000-0000-0000-0000-000000000000','authenticated','authenticated',%s,'',now(),now(),now())",
                       (actor, email))
            if not db.execute("select pg_has_role(current_user,'company_access_executor','SET') allowed").fetchone()["allowed"]:
                principal = db.execute("select current_user principal").fetchone()["principal"]
                db.execute(sql.SQL("grant company_access_executor to {} with set true granted by {}").format(
                    sql.Identifier(principal), sql.Identifier(principal)))
            claims = canonical({"sub": str(actor), "email": email, "role": "authenticated", "aal": "aal2",
                "amr": [{"method": "totp", "timestamp": int(datetime.now(UTC).timestamp())}]})
            for name, value in (("talli.verified_actor_id", str(actor)), ("talli.verified_actor_claims", claims),
                                ("request.jwt.claims", claims)):
                db.execute("select set_config(%s,%s,true)", (name, value))
            db.execute("set local role company_access_executor")
            first = admission_parameters(actor, email, 2026)
            second = admission_parameters(actor, email, 2025)
            before = admit(db, first)
            after = admit(db, second)
            assert before["accounting_year"] == 2026
            assert after["accounting_year"] == 2025
            assert before["company_id"] == after["company_id"]
            assert before["company_year_admission_id"] != after["company_year_admission_id"]
            replay = admit(db, second)
            assert replay["company_year_admission_id"] == after["company_year_admission_id"]
            for patch in (
                {"p_accounting_year": 2024},
                {"p_capability_manifest_version": "2026.1", "p_capability_manifest_sha256": first["p_capability_manifest_sha256"]},
                {"p_reconstruct_from": "2026-01-01"},
            ):
                with pytest.raises(psycopg.Error, match="company_access_invalid_request"):
                    with db.transaction():
                        admit(db, second | patch | {"p_operation_id": uuid4()})
            changed = json.loads(second["p_company_year_promise_json"])
            changed["startsOn"] = "2026-01-01"
            with pytest.raises(psycopg.Error, match="company_access_invalid_request"):
                with db.transaction():
                    admit(db, second | {"p_operation_id": uuid4(), "p_company_year_promise_json": canonical(changed),
                        "p_company_year_promise_sha256": digest(changed)})
            for admission, parameters in ((before, first), (after, second)):
                command = recheck_parameters(db, actor, admission, parameters)
                recorded = rpc(db, "company_access_recheck_company_year_eligibility", command)
                assert recorded["replayed"] is False
                assert rpc(db, "company_access_recheck_company_year_eligibility", command)["replayed"] is True
                other = first if parameters is second else second
                with pytest.raises(psycopg.Error, match="company_access_invalid_request"):
                    with db.transaction():
                        rpc(db, "company_access_recheck_company_year_eligibility", command | {
                            "p_operation_id": uuid4(),
                            "p_capability_manifest_version": other["p_capability_manifest_version"],
                            "p_capability_manifest_sha256": other["p_capability_manifest_sha256"],
                        })
                with pytest.raises(psycopg.Error, match="company_access_not_found"):
                    with db.transaction():
                        rpc(db, "company_access_recheck_company_year_eligibility", command | {
                            "p_operation_id": uuid4(), "p_verified_subject": uuid4(),
                        })
            with pytest.raises(psycopg.Error, match="rollback_requires_retaining_existing_promises"):
                with db.transaction():
                    db.execute("reset role")
                    rollback = Path("supabase/rollback/20261029085410_company_year_2025_admission.sql").read_text()
                    db.execute(rollback.replace("begin;", "", 1).rsplit("commit;", 1)[0])
            rows = db.execute("select accounting_year,company_year_promise from public.company_year_admissions "
                              "where company_id=%s order by accounting_year", (after["company_id"],)).fetchall()
            assert [row["accounting_year"] for row in rows] == [2025, 2026]
            assert [row["company_year_promise"]["startsOn"] for row in rows] == ["2025-01-01", "2026-01-01"]
        finally:
            db.rollback()


def test_empty_2025_rollback_and_recutover_preserve_function_security_and_constraints():
    url = os.environ.get("DATABASE_URL", "")
    assert url and conninfo_to_dict(url).get("host") in ("127.0.0.1", "localhost", "::1"), "owned loopback DB required"

    def snapshot(db):
        return {
            "functions": db.execute(
                "select p.oid,p.proname,pg_catalog.pg_get_functiondef(p.oid) definition,"
                "p.proowner,p.proacl::text,p.proconfig,p.prosecdef from pg_catalog.pg_proc p "
                "where p.pronamespace='public'::regnamespace and p.proname in "
                "('company_access_admit_company_year','company_access_recheck_company_year_eligibility') "
                "order by p.proname"
            ).fetchall(),
            "constraints": db.execute(
                "select c.conrelid,c.conname,pg_catalog.pg_get_constraintdef(c.oid) definition "
                "from pg_catalog.pg_constraint c where c.conrelid in "
                "('public.company_year_admissions'::regclass,'public.company_year_acceptances'::regclass,"
                "'public.company_eligibility_assessments'::regclass) order by c.conrelid,c.conname"
            ).fetchall(),
            "roles": db.execute(
                "select roleid,member,grantor,admin_option,inherit_option,set_option "
                "from pg_catalog.pg_auth_members where roleid='company_access_executor'::regrole "
                "order by member,grantor"
            ).fetchall(),
        }

    with psycopg.connect(url, row_factory=dict_row) as db:
        try:
            before = snapshot(db)
            for direction in ("rollback", "migrations"):
                source = Path(f"supabase/{direction}/20261029085410_company_year_2025_admission.sql").read_text()
                db.execute(source.replace("begin;", "", 1).rsplit("commit;", 1)[0])
                if direction == "rollback":
                    rolled = snapshot(db)
                    assert rolled["roles"] == before["roles"]
                    assert all("paired-manifest v1" not in item["definition"]
                               and "-- company-access RF guard v1" in item["definition"]
                               for item in rolled["functions"])
            assert snapshot(db) == before
        finally:
            db.rollback()
