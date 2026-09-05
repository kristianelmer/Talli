"""Run against the mandatory disposable, fully migrated local database."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from talli_backend.modules.company_access import public as access
from talli_backend.adapters.supabase_company_access import SupabaseCompanyAccessAdapter, SupabaseConfiguration


pytestmark = pytest.mark.billing_database


DATABASE_URL = os.environ.get("DATABASE_URL", "")
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def test_role_authority():
    assert DATABASE_URL, "DATABASE_URL must identify the disposable test database"
    borrowed = []
    with psycopg.connect(DATABASE_URL) as connection:
        principal = connection.execute("select current_user").fetchone()[0]
        for role in ("billing_store_owner", "authenticated"):
            if not connection.execute("select pg_has_role(current_user, %s, 'SET')", (role,)).fetchone()[0]:
                connection.execute(sql.SQL("grant {} to {}").format(sql.Identifier(role), sql.Identifier(principal)))
                borrowed.append(role)
    try:
        yield
    finally:
        with psycopg.connect(DATABASE_URL) as connection:
            for role in borrowed:
                connection.execute(sql.SQL("revoke {} from {}").format(sql.Identifier(role), sql.Identifier(principal)))


def insert(connection, table, values):
    connection.execute(sql.SQL("insert into {} ({}) values ({})").format(
        sql.Identifier(*table.split(".")),
        sql.SQL(",").join(map(sql.Identifier, values)),
        sql.SQL(",").join(sql.Placeholder() for _ in values),
    ), tuple(values.values()))


def legal_fields(*, privacy=False):
    fields = {}
    for prefix in ("business_terms", "dpa") + (("privacy_notice",) if privacy else ()):
        for suffix in ("version", "effective_date", "path", "sha256"):
            fields[prefix + "_" + suffix] = getattr(access, "CURRENT_" + (prefix + "_" + suffix).upper())
    return fields | {"authority_statement_version": "authority-v1", "acceptance_method": "in_app_clickwrap"}


@pytest.fixture
def admitted(request):
    assert DATABASE_URL, "DATABASE_URL must identify the disposable test database"
    owner, outsider, company, admission, accepted, current, acceptance, legal = [uuid4() for _ in range(8)]
    now = datetime.now(UTC)
    promise = {
        "accountingYear": 2026, "startsOn": "2026-01-01", "endsOn": "2026-12-31",
        "reconstructionRequiredFrom": "2026-01-01", "onlyAccountingAndFilingProduct": True,
        "customerClaims": access.CAPABILITY_MANIFEST["promise"]["customerClaims"],
    }
    base = {
        "company_id": company, "accounting_year": 2026,
        "capability_manifest": Jsonb(access.CAPABILITY_MANIFEST),
        "capability_manifest_version": access.CURRENT_CAPABILITY_MANIFEST_VERSION,
        "capability_manifest_sha256": access.CURRENT_CAPABILITY_MANIFEST_SHA256,
    }
    assessment = base | {
        "decision": "supported", "public_facts": Jsonb({"source": "fixture"}),
        "public_facts_sha256": "a" * 64, "answers": Jsonb({"fixture": "yes"}),
        "answers_sha256": "b" * 64, "consequential_operations_allowed": True,
        "archive_export_available": True, "evaluator_version": "2026.1", "assessed_by": owner,
        "next_step_code": "CONTINUE_COMPANY_YEAR", "next_step": "Fortsett.",
    }
    org = str(100000000 + company.int % 899999999)
    with psycopg.connect(DATABASE_URL) as connection:
        for actor in (owner, outsider):
            insert(connection, "auth.users", {"id": actor, "email": f"{actor}@example.test"})
        insert(connection, "public.companies", {
            "id": company, "org_number": org, "name": "Basis Holding AS", "entity_type": "AS",
            "address": "Testveien 1", "postal_code": "0150", "city": "Oslo", "status_text": "aktiv",
            "source": "test", "created_by": owner, "identity_confirmed_at": now, "identity_locked_at": now,
        })
        insert(connection, "public.company_memberships", {"company_id": company, "user_id": owner, "role": "owner", "accepted_at": now})
        insert(connection, "public.company_eligibility_assessments", assessment | {
            "id": accepted, "operation_id": uuid4(), "trigger": "initial_admission", "assessed_at": now - timedelta(days=1),
        })
        insert(connection, "public.company_year_admissions", base | {
            "id": admission, "eligibility_assessment_id": accepted,
            "company_year_promise": Jsonb(promise), "company_year_promise_sha256": access._canonical_sha256(promise),
            "reconstruct_from": "2026-01-01", "admitted_by": owner, "admitted_at": now,
        })
        acceptance_fields = {"company_id": company, "accepted_by": owner, "accepted_at": now,
                             "customer_legal_name": "Basis Holding AS", "customer_org_number": org}
        insert(connection, "public.company_year_acceptances", acceptance_fields | legal_fields(privacy=True) | {
            "id": acceptance, "company_year_admission_id": admission, "accounting_year": 2026,
            "capability_manifest_version": "2026.1", "capability_manifest_sha256": access.CURRENT_CAPABILITY_MANIFEST_SHA256,
        })
        insert(connection, "public.customer_agreement_acceptances", acceptance_fields | legal_fields() | {"id": legal})
        insert(connection, "public.company_eligibility_assessments", assessment | {
            "id": current, "operation_id": uuid4(), "previous_assessment_id": accepted,
            "trigger": "before_payment", "assessed_at": now + getattr(request, "param", timedelta()),
        })
    return locals()


def scoped(connection, actor, *, role="billing_store_owner", fresh=True):
    connection.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
    connection.execute("select set_config('talli.verified_actor_id', %s, true), set_config('talli.verified_actor_claims', %s, true)", (
        str(actor), json.dumps({"sub": str(actor), "aal": "aal2", "amr": [{"method": "totp", "timestamp": datetime.now(UTC).timestamp() - (0 if fresh else 7200)}]}),
    ))


def basis(connection, seed, *, assessment=None, legal=None):
    return connection.execute(
        "select public.company_access_purchase_basis_v1(%s, 2026, %s, %s)",
        (seed["company"], assessment or seed["current"], legal),
    ).fetchone()[0]


def test_exact_basis_is_publicly_validated_and_billing_has_no_table_access(admitted):
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        row = basis(connection, admitted)
        assert row["assessment_id"] == str(admitted["current"])
        assert row["accepted_assessment_id"] == str(admitted["accepted"])
        assert row["legal_evidence"]["id"] == str(admitted["legal"])
        state = access.CompanyYearEligibilityStateResponse(
            company_year_eligibility_assessment_id=admitted["current"], company_year_admission_id=admitted["admission"],
            company_id=admitted["company"], accounting_year=2026, trigger="before_payment", decision="supported",
            accepted_capability_manifest_version="2026.1", accepted_capability_manifest_sha256=access.CURRENT_CAPABILITY_MANIFEST_SHA256,
            current_capability_manifest_version="2026.1", current_capability_manifest_sha256=access.CURRENT_CAPABILITY_MANIFEST_SHA256,
            accepted_company_year_promise=admitted["promise"], reason_codes=[], reason_explanations=[],
            next_step_code="CONTINUE_COMPANY_YEAR", next_step="Fortsett.", consequential_operations_allowed=True,
            archive_export_available=True, replayed=False,
        )
        class Gateway:
            async def company_year_purchase_basis(self, *args):
                return row
        result = asyncio.run(access.CompanyAccessService(Gateway()).purchase_basis("fixture-token", state))
        assert result.acceptance_id == admitted["acceptance"]
        row["legal_evidence"]["business_terms_sha256"] = "0" * 64
        with pytest.raises(access.CompanyAccessError):
            asyncio.run(access.CompanyAccessService(Gateway()).purchase_basis("fixture-token", state))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute("select * from public.company_year_acceptances")


@pytest.mark.parametrize("mode", ["outsider", "stale_mfa", "old_assessment", "wrong_legal", "browser"])
def test_unauthorized_or_changed_basis_fails_closed(admitted, mode):
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["outsider"] if mode == "outsider" else admitted["owner"],
               fresh=mode != "stale_mfa", role="authenticated" if mode == "browser" else "billing_store_owner")
        if mode == "browser":
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                basis(connection, admitted)
        else:
            assert basis(connection, admitted, assessment=admitted["accepted"] if mode == "old_assessment" else None,
                         legal=uuid4() if mode == "wrong_legal" else None) is None


def test_projection_holds_the_eligibility_lock_until_claim_transaction_commits(admitted):
    with psycopg.connect(DATABASE_URL) as claim, psycopg.connect(DATABASE_URL) as competing:
        scoped(claim, admitted["owner"])
        assert basis(claim, admitted)
        lock_sql = "select pg_try_advisory_xact_lock(hashtextextended('eligibility-recheck|' || %s::text, 187))"
        assert competing.execute(lock_sql, (admitted["admission"],)).fetchone()[0] is False
        claim.commit()
        assert competing.execute(lock_sql, (admitted["admission"],)).fetchone()[0] is True


def test_new_block_after_projection_invalidates_original_payment_basis(admitted):
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        assert basis(connection, admitted)
    with psycopg.connect(DATABASE_URL) as connection:
        insert(connection, "public.company_eligibility_assessments", admitted["assessment"] | {
            "id": uuid4(), "operation_id": uuid4(), "previous_assessment_id": admitted["current"],
            "trigger": "material_answer_changed", "assessed_at": datetime.now(UTC), "decision": "blocked",
            "consequential_operations_allowed": False,
        })
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        assert basis(connection, admitted) is None


@pytest.mark.parametrize("admitted", [timedelta(minutes=-6), timedelta(minutes=1)], indirect=True)
def test_stale_and_future_assessment_timestamps_cannot_authorize_a_claim(admitted):
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        assert basis(connection, admitted) is None


def test_rollback_and_recutover_preserve_the_exact_accepted_evidence(admitted):
    migration = "20260905080550_annual_billing_purchase_basis.sql"
    ledger = "20260905083150_annual_billing_purchase_ledger.sql"
    with psycopg.connect(DATABASE_URL) as connection:
        scoped(connection, admitted["owner"])
        before = basis(connection, admitted)
    for _ in range(2):
        with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
            connection.execute((ROOT / "supabase" / "rollback" / "20260905145000_annual_refund_agreement_cleanup.sql").read_text())
            connection.execute((ROOT / "supabase" / "rollback" / "20260905141500_annual_refund_requests.sql").read_text())
            connection.execute((ROOT / "supabase" / "rollback" / "20260905115700_legacy_billing_acquisition_retirement.sql").read_text())
            connection.execute((ROOT / "supabase" / "rollback" / "20260905103149_annual_agreement_cleanup.sql").read_text())
            connection.execute((ROOT / "supabase" / "rollback" / "20260905100130_annual_renewal_cancellation.sql").read_text())
            connection.execute((ROOT / "supabase" / "rollback" / ledger).read_text())
            connection.execute((ROOT / "supabase" / "rollback" / migration).read_text())
            assert connection.execute("select to_regprocedure('public.company_access_purchase_basis_v1(uuid,integer,uuid,uuid)')").fetchone()[0] is None
            connection.execute((ROOT / "supabase" / "migrations" / migration).read_text())
            connection.execute((ROOT / "supabase" / "migrations" / ledger).read_text())
            connection.execute((ROOT / "supabase" / "migrations" / "20260905100130_annual_renewal_cancellation.sql").read_text())
            connection.execute((ROOT / "supabase" / "migrations" / "20260905103149_annual_agreement_cleanup.sql").read_text())
            connection.execute((ROOT / "supabase" / "migrations" / "20260905115700_legacy_billing_acquisition_retirement.sql").read_text())
            connection.execute((ROOT / "supabase" / "migrations" / "20260905141500_annual_refund_requests.sql").read_text())
            connection.execute((ROOT / "supabase" / "migrations" / "20260905145000_annual_refund_agreement_cleanup.sql").read_text())
            principal = connection.execute("select current_user").fetchone()[0]
            connection.execute(sql.SQL("grant billing_store_owner to {}").format(sql.Identifier(principal)))
        with psycopg.connect(DATABASE_URL) as connection:
            scoped(connection, admitted["owner"])
            assert basis(connection, admitted) == before
            assert connection.execute("select has_function_privilege('authenticated','public.company_access_purchase_basis_v1(uuid,integer,uuid,uuid)','execute')").fetchone()[0] is False


def test_adapter_lock_contention_times_out_and_the_same_basis_recovers(admitted):
    class VerifiedLocalAdapter(SupabaseCompanyAccessAdapter):
        async def _verified_actor_context(self, access_token):
            return str(admitted["owner"]), {"sub": str(admitted["owner"]), "aal": "aal2",
                "amr": [{"method": "totp", "timestamp": datetime.now(UTC).timestamp()}]}

    with psycopg.connect(DATABASE_URL) as connection:
        principal = connection.execute("select current_user").fetchone()[0]
        had_authority = connection.execute("select pg_has_role(current_user, 'company_access_executor', 'SET')").fetchone()[0]
        if not had_authority:
            connection.execute(sql.SQL("grant company_access_executor to {}").format(sql.Identifier(principal)))
    try:
        adapter = VerifiedLocalAdapter(SupabaseConfiguration(url="http://localhost", anon_key="fixture", database_url=DATABASE_URL))
        with psycopg.connect(DATABASE_URL) as competing:
            competing.execute("select pg_advisory_xact_lock(hashtextextended('eligibility-recheck|' || %s::text, 187))", (admitted["admission"],))
            started = monotonic()
            with pytest.raises(access.CompanyAccessError) as failure:
                asyncio.run(adapter.company_year_purchase_basis("fixture", str(admitted["company"]), 2026, str(admitted["current"])))
            assert failure.value.status == 503
            assert 0.8 <= monotonic() - started < 5
            competing.commit()
        result = asyncio.run(adapter.company_year_purchase_basis("fixture", str(admitted["company"]), 2026, str(admitted["current"])))
        assert result["assessment_id"] == str(admitted["current"])
    finally:
        if not had_authority:
            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute(sql.SQL("revoke company_access_executor from {}").format(sql.Identifier(principal)))
