from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from test_annual_purchase_basis_runtime import database_now, test_role_authority
from test_annual_refund_runtime import admitted, insert, paid, purchase, setup
from test_annual_checkout_runtime import session as annual_session

from talli_backend.application.billing_workflow import BillingWorkflow
from talli_backend.adapters.simulation_billing import SimulationBillingProvider
from talli_backend.modules.billing.service import BillingService
from talli_backend.adapters.supabase_billing import SupabaseBillingSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.billing.public import (
    ActivateSubscriptionCommand,
    BillingEntitlementQuery,
    BillingError,
    BillingErrorCode,
    BillingPaymentStatus,
    BillingObligation,
    BillingPilotCaseProfile,
    BillingPlan,
    BillingPricing,
    BillingProviderResult,
    BillingStatus,
    ConfigureBillingAccountCommand,
    ManageProductionPilotEntitlementCommand,
    MarkBillingUnsupportedCommand,
    ProductionPilotStatus,
    SystemUserRequestReference,
)
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    Timestamp,
    UserId,
)


pytestmark = pytest.mark.billing_database


DATABASE_URL = os.environ.get("DATABASE_URL", "")
OWNER_ID = "74000000-0000-4000-8000-000000000001"
COMPANY_ID = "74000000-0000-4000-8000-000000000002"
REQUEST_ID = "74000000-0000-4000-8000-000000000003"
OUTSIDER_ID = "74000000-0000-4000-8000-000000000004"
ADMIN_ID = "74000000-0000-4000-8000-000000000005"


def enable_backend_login() -> str:
    password = f"billing-{uuid4().hex}"
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            sql.SQL("alter role talli_ledger_backend login password {}").format(
                sql.Literal(password)
            )
        )
    return make_conninfo(
        DATABASE_URL, user="talli_ledger_backend", password=password
    )


def disable_backend_login() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            "alter role talli_ledger_backend nologin password null"
        )


# Fresh synthetic MFA uses the database authorization clock, one second before now.
def metadata(key: str) -> dict[str, object]:
    actor = ActorId(ActorKind.USER, UserId(OWNER_ID))
    return {
        "company_id": CompanyId(COMPANY_ID),
        "actor_id": actor,
        "correlation_id": CorrelationId(f"billing-runtime-{key}"),
        "idempotency_key": IdempotencyKey(f"billing-runtime-{key}-00000001"),
    }


def seed() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            """insert into auth.users (id, email) values
              (%s::uuid, %s::text), (%s::uuid, %s::text), (%s::uuid, %s::text)""",
            (
                OWNER_ID,
                "billing-runtime@example.test",
                OUTSIDER_ID,
                "billing-runtime-outsider@example.test",
                ADMIN_ID,
                "billing-admin@example.test",
            ),
        )
        connection.execute(
            """insert into public.companies (
              id, org_number, name, entity_type, address, postal_code, city,
              status_text, source, created_by, identity_confirmed_at, identity_locked_at
            ) values (%s::uuid, '740000002', 'Billing Runtime AS', 'AS',
              'Testveien 1', '0150', 'Oslo', 'Active', 'test', %s::uuid, now(), now())""",
            (COMPANY_ID, OWNER_ID),
        )
        connection.execute(
            """insert into public.company_memberships (
              company_id, user_id, role, accepted_at
            ) values (%s::uuid, %s::uuid, 'owner', now())""",
            (COMPANY_ID, OWNER_ID),
        )
        connection.execute(
            "insert into public.support_operators (user_id, role, active) values (%s::uuid, 'admin', true)",
            (ADMIN_ID,),
        )
        connection.execute(
            """insert into public.system_user_requests (
              id, company_id, initiating_owner_user_id, obligation, external_ref,
              status, preflight_verified_at, accepted_at
            ) values (%s::uuid, %s::uuid, %s::uuid, 'aksjonaerregisteroppgaven',
              'BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB', 'accepted', now(), now())""",
            (REQUEST_ID, COMPANY_ID, OWNER_ID),
        )
        connection.execute(
            """insert into public.filing_readiness_snapshots (
              company_id, income_year, obligation, status, ready, hard_blocks,
              warnings, accepted_warnings, created_by
            ) values (%s::uuid, 2025, 'aksjonaerregisteroppgaven', 'ready', true,
              '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, %s::uuid)""",
            (COMPANY_ID, OWNER_ID),
        )

    seed_legacy_billing()


def seed_legacy_billing(*, event_key=None):
    root = Path(__file__).resolve().parents[3]
    migration = "20260905115700_legacy_billing_acquisition_retirement.sql"
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute((root / "supabase" / "rollback" / migration).read_text())
        try:
            connection.execute("""insert into billing.billing_accounts
                (company_id,pricing_plan,monthly_nok,filing_package_nok,updated_by)
                values (%s,'standard',49,499,%s) on conflict(company_id) do nothing""", (COMPANY_ID, OWNER_ID))
            if event_key:
                connection.execute("""insert into billing.billing_payment_events
                    (company_id,provider_reference,idempotency_key,kind,status,amount_nok,created_by)
                    values (%s,'historical-pending',%s,'subscription','created',49,%s)""", (COMPANY_ID, event_key, OWNER_ID))
        finally:
            connection.execute((root / "supabase" / "migrations" / migration).read_text())


def cleanup() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        # Contract recutover removes DELETE from the runtime receipt owner. The
        # disposable fixture janitor borrows it only for its own company cascade.
        borrowed = not connection.execute(
            "select has_table_privilege('billing_store_owner', 'billing.billing_command_receipts', 'DELETE')"
        ).fetchone()[0]
        if borrowed:
            connection.execute("grant delete on billing.billing_command_receipts to billing_store_owner")
        connection.execute(
            "delete from public.support_operators where user_id=%s::uuid", (ADMIN_ID,)
        )
        connection.execute("delete from public.companies where id=%s::uuid", (COMPANY_ID,))
        connection.execute("delete from auth.users where id=%s::uuid", (OWNER_ID,))
        connection.execute("delete from auth.users where id=%s::uuid", (OUTSIDER_ID,))
        connection.execute("delete from auth.users where id=%s::uuid", (ADMIN_ID,))
        if borrowed:
            connection.execute("revoke delete on billing.billing_command_receipts from billing_store_owner")


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
def test_non_provider_commands_replay_exactly_and_reject_key_reuse() -> None:
    backend_database_url = enable_backend_login()
    try:
        seed()
        try:
            actor = ActorId(ActorKind.USER, UserId(OWNER_ID))
            session = SupabaseBillingSession(
                backend_database_url,
                _VerifiedActor(
                    actor_id=actor,
                    claims_json=json.dumps({
                        "sub": OWNER_ID,
                        "role": "authenticated",
                        "aal": "aal2",
                        "amr": [{
                            "method": "totp",
                            "timestamp": database_now().timestamp() - 1,
                        }],
                    }),
                ),
            )

            configure = ConfigureBillingAccountCommand(**metadata("configure"), pricing_plan=BillingPlan.STANDARD)
            with pytest.raises(BillingError) as retired:
                asyncio.run(session.configure_account(configure, BillingPricing(BillingPlan.STANDARD, 49, 499)))
            assert retired.value.code == BillingErrorCode.LEGACY_ACQUISITION_RETIRED

            outsider_session = SupabaseBillingSession(
                backend_database_url,
                _VerifiedActor(
                    actor_id=ActorId(ActorKind.USER, UserId(OUTSIDER_ID)),
                    claims_json=json.dumps({
                        "sub": OUTSIDER_ID,
                        "role": "authenticated",
                        "aal": "aal2",
                    }),
                ),
            )
            with pytest.raises(BillingError) as outsider_entitlement:
                asyncio.run(
                    outsider_session.authorize_entitlement_query(CompanyId(COMPANY_ID))
                )
            assert outsider_entitlement.value.code == BillingErrorCode.FORBIDDEN

            stale_session = SupabaseBillingSession(
                backend_database_url,
                _VerifiedActor(
                    actor_id=actor,
                    claims_json=json.dumps({
                        "sub": OWNER_ID,
                        "role": "authenticated",
                        "aal": "aal1",
                    }),
                ),
            )
            with pytest.raises(BillingError) as stale_authorization:
                asyncio.run(stale_session.authorize_owner_command(CompanyId(COMPANY_ID)))
            assert stale_authorization.value.code == BillingErrorCode.STEP_UP_REQUIRED

            unsupported = MarkBillingUnsupportedCommand(
                **metadata("unsupported"), reason="Outside support"
            )
            first_unsupported = asyncio.run(session.mark_unsupported(unsupported))
            assert asyncio.run(session.mark_unsupported(unsupported)) == first_unsupported

            admin_actor = ActorId(ActorKind.USER, UserId(ADMIN_ID))
            admin_session = SupabaseBillingSession(
                backend_database_url,
                _VerifiedActor(
                    actor_id=admin_actor,
                    claims_json=json.dumps({
                        "sub": ADMIN_ID,
                        "role": "authenticated",
                        "aal": "aal2",
                        "amr": [{
                            "method": "totp",
                            "timestamp": database_now().timestamp() - 1,
                        }],
                    }),
                ),
            )
            pilot_metadata = metadata("pilot")
            pilot_metadata["actor_id"] = admin_actor
            now = datetime(2026, 9, 5, tzinfo=UTC)
            pilot = ManageProductionPilotEntitlementCommand(
                **pilot_metadata,
                entitlement_id=None,
                user_id=UserId(OWNER_ID),
                income_year=IncomeYear(2025),
                status=ProductionPilotStatus.PENDING,
                billing_exempt=False,
                system_user_request_id=SystemUserRequestReference(REQUEST_ID),
                starts_at=Timestamp(now),
                expires_at=Timestamp(now + timedelta(days=30)),
                evidence_reference="runtime-replay-evidence",
            )
            first_pilot = asyncio.run(admin_session.manage_pilot_entitlement(pilot))
            replayed_pilot = asyncio.run(admin_session.manage_pilot_entitlement(pilot))
            assert replayed_pilot.entitlement_id == first_pilot.entitlement_id

            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute(
                    "delete from public.company_memberships where company_id=%s::uuid and user_id=%s::uuid",
                    (COMPANY_ID, OWNER_ID),
                )
            removed_owner_metadata = metadata("pilot-removed-owner")
            removed_owner_metadata["actor_id"] = admin_actor
            with pytest.raises(BillingError) as removed_owner:
                asyncio.run(
                    admin_session.manage_pilot_entitlement(
                        ManageProductionPilotEntitlementCommand(
                            **removed_owner_metadata,
                            entitlement_id=None,
                            user_id=UserId(OWNER_ID),
                            income_year=IncomeYear(2025),
                            status=ProductionPilotStatus.PENDING,
                            billing_exempt=False,
                            system_user_request_id=SystemUserRequestReference(REQUEST_ID),
                            starts_at=Timestamp(now),
                            expires_at=Timestamp(now + timedelta(days=30)),
                            evidence_reference="removed-owner-must-fail",
                        )
                    )
                )
            assert removed_owner.value.code == BillingErrorCode.INVALID_INPUT
        finally:
            cleanup()
    finally:
        disable_backend_login()


class NoPilotPaymentProvider:
    async def execute(self, intent):
        pytest.fail("A pilot exemption must not execute a payment")

    async def reconcile(self, intent):
        pytest.fail("A pilot exemption must not reconcile a payment")


def pilot_session(setup, actor=None, *, fresh=True):
    return SupabaseBillingSession(
        DATABASE_URL, annual_session(setup, actor=actor, fresh=fresh)._verified,
    )


def pilot_financial_records(company_id):
    """Complete local money/consent records, excluding pilot management receipts."""
    tables = (
        "billing_accounts", "billing_payment_events", "annual_purchases",
        "annual_operations", "annual_refund_cases", "annual_cancellation_requests",
        "annual_refund_requests", "annual_checkout_withdrawals",
    )
    with psycopg.connect(DATABASE_URL) as connection:
        return {
            table: connection.execute(sql.SQL(
                "select coalesce(jsonb_agg(to_jsonb(r) order by to_jsonb(r)::text), '[]'::jsonb) "
                "from billing.{} r where company_id=%s"
            ).format(sql.Identifier(table)), (str(company_id),)).fetchone()[0]
            for table in tables
        }


def pilot_management_records(company_id):
    with psycopg.connect(DATABASE_URL) as connection:
        return connection.execute("""select
          (select count(*) from billing.production_pilot_entitlements where company_id=%s),
          (select count(*) from billing.billing_command_receipts where company_id=%s)""",
          (str(company_id), str(company_id))).fetchone()


@pytest.fixture(scope="module")
def pilot_read_authority(test_role_authority):
    """Let the disposable janitor assume the existing restricted runtime role."""
    with psycopg.connect(DATABASE_URL) as connection:
        principal = connection.execute("select current_user").fetchone()[0]
        borrowed = not connection.execute(
            "select pg_has_role(current_user, 'billing_executor', 'SET')"
        ).fetchone()[0]
        if borrowed:
            connection.execute(sql.SQL("grant billing_executor to {}").format(sql.Identifier(principal)))
    try:
        yield
    finally:
        if borrowed:
            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute(sql.SQL("revoke billing_executor from {}").format(sql.Identifier(principal)))


@pytest.fixture
def pilot_case(setup, paid, pilot_read_authority):
    """Synthetic pilot/readiness and paid fixtures prove separation, not filing readiness."""
    admin, member, request_id, other_company = [uuid4() for _ in range(4)]
    now = datetime.now(UTC)
    company = paid.offer.company_id
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute(
            "select pg_has_role(current_user, 'billing_executor', 'SET')"
        ).fetchone()[0]
        for user in (admin, member):
            insert(connection, "auth.users", {"id": user, "email": f"{user}@example.test"})
        insert(connection, "public.support_operators", {"user_id": admin, "role": "admin", "active": True})
        insert(connection, "public.company_memberships", {
            "company_id": str(company), "user_id": member, "role": "owner", "accepted_at": now,
        })
        insert(connection, "public.system_user_requests", {
            "id": request_id, "company_id": str(company), "initiating_owner_user_id": str(setup[1].subject),
            "obligation": "aksjonaerregisteroppgaven", "status": "accepted",
            "external_ref": uuid4().hex + uuid4().hex[:11],
            "preflight_verified_at": now, "accepted_at": now,
        })
        insert(connection, "public.companies", {
            "id": other_company, "org_number": str(100000000 + other_company.int % 899999999),
            "name": "Other Synthetic Pilot AS", "entity_type": "AS", "address": "Testveien 1",
            "postal_code": "0150", "city": "Oslo", "status_text": "aktiv", "source": "test",
            "created_by": str(setup[1].subject), "identity_confirmed_at": now, "identity_locked_at": now,
        })
        insert(connection, "public.company_memberships", {
            "company_id": other_company, "user_id": str(setup[1].subject), "role": "owner", "accepted_at": now,
        })
        for target in (str(company), other_company):
            connection.execute("""insert into public.filing_readiness_snapshots (
              company_id, income_year, obligation, status, ready, hard_blocks,
              warnings, accepted_warnings, created_by
            ) values (%s, 2026, 'aksjonaerregisteroppgaven', 'ready', true,
              '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, %s)""", (target, str(setup[1].subject)))
    provider = NoPilotPaymentProvider()
    admin_actor = ActorId(ActorKind.USER, UserId(str(admin)))
    management = BillingWorkflow(pilot_session(setup, admin_actor), provider)
    command = ManageProductionPilotEntitlementCommand(
        company_id=company, actor_id=admin_actor, correlation_id=CorrelationId(str(uuid4())),
        idempotency_key=IdempotencyKey(str(uuid4())), entitlement_id=None,
        user_id=setup[1].subject, income_year=IncomeYear(2026), status=ProductionPilotStatus.ACTIVE,
        billing_exempt=True, system_user_request_id=SystemUserRequestReference(str(request_id)),
        starts_at=Timestamp(now-timedelta(days=1)), expires_at=Timestamp(now+timedelta(days=1)),
        evidence_reference="synthetic-local-separation-proof",
    )
    query = BillingEntitlementQuery(
        company_id=company, actor_id=setup[1], correlation_id=command.correlation_id,
        income_year=IncomeYear(2026), obligation=BillingObligation.SHAREHOLDER_REGISTER,
        case_profile="rf1086_no_activity_v1",
    )
    return {
        "command": command, "query": query, "management": management, "provider": provider,
        "now": now, "member": ActorId(ActorKind.USER, UserId(str(member))),
        "other_company": CompanyId(str(other_company)),
    }


def read_pilot(setup, case, *, query=None, at=None):
    query = query or case["query"]
    service = BillingService(pilot_session(setup, query.actor_id), case["provider"],
                             now=lambda: at if at is not None else case["now"])
    return asyncio.run(service.entitlement(query))


def assert_ordinary_billing_unavailable(decision, *, pilot_id=None):
    assert decision.status is BillingStatus.ANNUAL_BILLING_UNAVAILABLE
    assert not decision.allowed and not decision.charge_allowed and not decision.billing_exempt
    assert decision.readiness_allowed and decision.pilot_entitlement_id == pilot_id


def test_pilot_exemption_replay_and_revocation_do_not_change_paid_purchase_or_consent(setup, paid, pilot_case):
    case = pilot_case
    before = pilot_financial_records(paid.offer.company_id)
    assert len(before["annual_purchases"]) == 1
    assert paid.status.value == "paid" and paid.intent.recurring_consent
    first = asyncio.run(case["management"].manage_pilot_entitlement(case["command"]))
    assert asyncio.run(case["management"].manage_pilot_entitlement(case["command"])) == first
    assert pilot_management_records(paid.offer.company_id) == (1, 1)
    active = read_pilot(setup, case)
    assert active.status is BillingStatus.PILOT_ENTITLEMENT_ACTIVE
    assert active.allowed and active.billing_exempt and active.readiness_allowed
    assert not active.charge_allowed and active.pilot_entitlement_id == first.entitlement_id
    assert_ordinary_billing_unavailable(read_pilot(setup, case, query=replace(case["query"], case_profile=None)))
    assert pilot_financial_records(paid.offer.company_id) == before

    revoke = replace(case["command"], entitlement_id=first.entitlement_id,
                     idempotency_key=IdempotencyKey(str(uuid4())), status=ProductionPilotStatus.REVOKED)
    revoked = asyncio.run(case["management"].manage_pilot_entitlement(revoke))
    assert revoked.status is ProductionPilotStatus.REVOKED
    assert_ordinary_billing_unavailable(read_pilot(setup, case))
    # Immutable creation replay returns history; it must not reactivate the row.
    assert asyncio.run(case["management"].manage_pilot_entitlement(case["command"])) == first
    assert_ordinary_billing_unavailable(read_pilot(setup, case))
    assert pilot_management_records(paid.offer.company_id) == (1, 2)
    assert pilot_financial_records(paid.offer.company_id) == before


@pytest.mark.parametrize("dimension", ["company", "user", "year", "obligation", "profile", "no_profile"])
def test_pilot_exemption_does_not_cross_exact_case_dimensions(setup, pilot_case, dimension):
    case = pilot_case
    asyncio.run(case["management"].manage_pilot_entitlement(case["command"]))
    changes = {
        "company": {"company_id": case["other_company"]}, "user": {"actor_id": case["member"]},
        "year": {"income_year": IncomeYear(2025)}, "obligation": {"obligation": BillingObligation.COMPANY_TAX},
        "profile": {"case_profile": "future_unknown_profile"}, "no_profile": {"case_profile": None},
    }[dimension]
    before = pilot_financial_records(case["query"].company_id)
    assert_ordinary_billing_unavailable(read_pilot(setup, case, query=replace(case["query"], **changes)))
    assert pilot_financial_records(case["query"].company_id) == before


@pytest.mark.parametrize("boundary,allowed", [("before_start", False), ("at_start", True), ("before_expiry", True), ("at_expiry", False)])
def test_pilot_exemption_time_interval_is_start_inclusive_and_expiry_exclusive(setup, pilot_case, boundary, allowed):
    case = pilot_case
    first = asyncio.run(case["management"].manage_pilot_entitlement(case["command"]))
    at = {
        "before_start": first.starts_at.value-timedelta(microseconds=1), "at_start": first.starts_at.value,
        "before_expiry": first.expires_at.value-timedelta(microseconds=1), "at_expiry": first.expires_at.value,
    }[boundary]
    decision = read_pilot(setup, case, at=at)
    if allowed:
        assert decision.status is BillingStatus.PILOT_ENTITLEMENT_ACTIVE
        assert decision.allowed and decision.billing_exempt and not decision.charge_allowed
        assert decision.pilot_entitlement_id == first.entitlement_id
    else:
        assert_ordinary_billing_unavailable(decision)


@pytest.mark.parametrize("status", [ProductionPilotStatus.PENDING, ProductionPilotStatus.SUSPENDED,
                                    ProductionPilotStatus.COMPLETED, ProductionPilotStatus.REVOKED])
def test_inactive_pilot_exemption_never_authorizes_billing(setup, pilot_case, status):
    case = pilot_case
    asyncio.run(case["management"].manage_pilot_entitlement(replace(case["command"], status=status)))
    assert_ordinary_billing_unavailable(read_pilot(setup, case))


@pytest.mark.parametrize("mode", ["nonexempt", "not_ready", "missing_readiness"])
def test_pilot_exemption_does_not_replace_payment_or_readiness(setup, pilot_case, mode):
    case = pilot_case
    before = pilot_financial_records(case["query"].company_id)
    command = replace(case["command"], billing_exempt=mode != "nonexempt")
    first = asyncio.run(case["management"].manage_pilot_entitlement(command))
    if mode == "not_ready":
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("update public.filing_readiness_snapshots set ready=false where company_id=%s",
                               (str(command.company_id),))
    elif mode == "missing_readiness":
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("delete from public.filing_readiness_snapshots where company_id=%s",
                               (str(command.company_id),))
    decision = read_pilot(setup, case)
    if mode == "nonexempt":
        assert_ordinary_billing_unavailable(decision, pilot_id=first.entitlement_id)
    else:
        assert decision.status is BillingStatus.ACTIVE and decision.billing_exempt
        assert decision.readiness_allowed and not decision.allowed and not decision.charge_allowed
        assert decision.pilot_entitlement_id == first.entitlement_id
    assert pilot_financial_records(command.company_id) == before


@pytest.mark.parametrize("change", ["exemption", "expiry", "evidence"])
def test_pilot_management_key_reuse_cannot_change_exemption(setup, pilot_case, change):
    case = pilot_case
    command = case["command"]
    first = asyncio.run(case["management"].manage_pilot_entitlement(command))
    changes = {"exemption": {"billing_exempt": False}, "expiry": {"expires_at": Timestamp(command.expires_at.value+timedelta(days=1))},
               "evidence": {"evidence_reference": "different-synthetic-evidence"}}[change]
    with pytest.raises(BillingError) as rejected:
        asyncio.run(case["management"].manage_pilot_entitlement(replace(command, **changes)))
    assert rejected.value.code is BillingErrorCode.IDEMPOTENCY_KEY_REUSED
    assert asyncio.run(case["management"].manage_pilot_entitlement(command)) == first
    assert pilot_management_records(command.company_id) == (1, 1)


@pytest.mark.parametrize("mode", ["outsider", "unaccepted", "actor_mismatch"])
def test_pilot_entitlement_query_requires_current_membership_and_bound_actor(setup, pilot_case, mode):
    case = pilot_case
    asyncio.run(case["management"].manage_pilot_entitlement(case["command"]))
    query = case["query"]
    outsider = ActorId(ActorKind.USER, UserId(str(setup[0]["outsider"])))
    actor = query.actor_id
    if mode == "outsider":
        query = replace(query, actor_id=outsider)
        actor = outsider
    elif mode == "unaccepted":
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s",
                               (str(query.company_id), str(actor.subject)))
    else:
        actor = outsider
    workflow = BillingWorkflow(pilot_session(setup, actor), case["provider"])
    with pytest.raises(BillingError) as rejected:
        asyncio.run(workflow.entitlement(query))
    assert rejected.value.code is BillingErrorCode.FORBIDDEN


@pytest.mark.parametrize("mode", ["missing_request", "foreign_company", "other_user", "unverified", "not_accepted", "owner_revoked"])
def test_pilot_management_requires_exact_verified_request_and_accepted_owner(setup, pilot_case, mode):
    case = pilot_case
    command = case["command"]
    if mode == "missing_request":
        command = replace(command, system_user_request_id=SystemUserRequestReference(str(uuid4())))
    elif mode == "foreign_company":
        command = replace(command, company_id=case["other_company"])
    elif mode == "other_user":
        command = replace(command, user_id=case["member"].subject)
    else:
        with psycopg.connect(DATABASE_URL) as connection:
            if mode == "owner_revoked":
                connection.execute("update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s",
                                   (str(command.company_id), str(command.user_id)))
            elif mode == "unverified":
                connection.execute("update public.system_user_requests set preflight_verified_at=null where id=%s",
                                   (str(command.system_user_request_id),))
            else:
                connection.execute("update public.system_user_requests set status='rejected', preflight_verified_at=null where id=%s",
                                   (str(command.system_user_request_id),))
    before = pilot_financial_records(case["query"].company_id)
    with pytest.raises(BillingError) as rejected:
        asyncio.run(case["management"].manage_pilot_entitlement(command))
    assert rejected.value.code is BillingErrorCode.INVALID_INPUT
    assert pilot_management_records(command.company_id) == (0, 0)
    assert pilot_financial_records(case["query"].company_id) == before


@pytest.mark.parametrize("mode", ["inactive_admin", "stale_mfa", "actor_mismatch"])
def test_pilot_management_replay_requires_current_admin_authority(setup, pilot_case, mode):
    case = pilot_case
    command = case["command"]
    asyncio.run(case["management"].manage_pilot_entitlement(command))
    actor = command.actor_id
    if mode == "inactive_admin":
        with psycopg.connect(DATABASE_URL) as connection:
            connection.execute("update public.support_operators set active=false where user_id=%s", (str(actor.subject),))
    elif mode == "actor_mismatch":
        actor = setup[1]
    workflow = BillingWorkflow(pilot_session(setup, actor, fresh=mode != "stale_mfa"), case["provider"])
    before = pilot_financial_records(command.company_id)
    with pytest.raises(BillingError) as rejected:
        asyncio.run(workflow.manage_pilot_entitlement(command))
    assert rejected.value.code is (BillingErrorCode.STEP_UP_REQUIRED if mode == "stale_mfa" else BillingErrorCode.FORBIDDEN)
    assert pilot_management_records(command.company_id) == (1, 1)
    assert pilot_financial_records(command.company_id) == before


@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
@pytest.mark.parametrize("failure_mode", ["timeout", "process", "storage"])
def test_committed_provider_intent_survives_lost_response_and_restart(failure_mode) -> None:
    class ProcessLost(BaseException):
        pass

    class LostResponseProvider(SimulationBillingProvider):
        executions = 0
        reconciliations = 0
        result = None
        original_intent = None
        lookup_barrier = None

        async def execute(self, intent):
            self.executions += 1
            raise AssertionError("retired acquisition must never execute")

        async def reconcile(self, intent):
            self.reconciliations += 1
            if self.original_intent is None:
                self.original_intent = intent
                # An independent connection sees the predecessor intent before I/O.
                with psycopg.connect(DATABASE_URL) as connection:
                    row = connection.execute(
                        "select status, amount_nok from billing.billing_payment_events where idempotency_key=%s",
                        (str(intent.idempotency_key),),
                    ).fetchone()
                assert row == ("created", 49)
                self.result = await super().reconcile(intent)
                if failure_mode == "process":
                    raise ProcessLost()
                if failure_mode == "storage":
                    return self.result
                raise TimeoutError("response lost after historical lookup")
            assert intent == self.original_intent
            if failure_mode == "timeout":
                if self.lookup_barrier is None:
                    self.lookup_barrier = asyncio.Event()
                if self.reconciliations == 3:
                    self.lookup_barrier.set()
                await asyncio.wait_for(self.lookup_barrier.wait(), timeout=5)
            return self.result

    class LostStorageSession(SupabaseBillingSession):
        async def complete_provider_event(self, command, result, amount_nok):
            raise BillingError.unavailable()

    backend_database_url = enable_backend_login()
    try:
        seed()
        try:
            actor = ActorId(ActorKind.USER, UserId(OWNER_ID))
            verified = _VerifiedActor(actor_id=actor, claims_json=json.dumps({
                "sub": OWNER_ID, "role": "authenticated", "aal": "aal2",
                "amr": [{"method": "totp", "timestamp": database_now().timestamp() - 1}],
            }))
            session = (LostStorageSession if failure_mode == "storage" else SupabaseBillingSession)(backend_database_url, verified)
            provider = LostResponseProvider()
            command = ActivateSubscriptionCommand(**metadata("durable-runtime"))
            seed_legacy_billing(event_key=str(command.idempotency_key))
            with pytest.raises(ProcessLost if failure_mode == "process" else BillingError):
                asyncio.run(BillingService(session, provider).activate_subscription(command))
            assert not asyncio.run(session.find_account(CompanyId(COMPANY_ID))).subscription_active
            # Even an older writer cannot reprice this historical account after retirement.
            with psycopg.connect(DATABASE_URL) as connection:
                with pytest.raises(psycopg.Error, match="billing_legacy_acquisition_retired"):
                    connection.execute(
                        "update billing.billing_accounts set monthly_nok=29 where company_id=%s::uuid",
                        (COMPANY_ID,),
                    )
            recovered_session = SupabaseBillingSession(backend_database_url, verified)
            async def recover():
                workflow = BillingService(recovered_session, provider)
                if failure_mode == "timeout":
                    first, second = await asyncio.gather(
                        workflow.activate_subscription(command),
                        workflow.activate_subscription(command),
                    )
                    assert first.event_id == second.event_id
                    assert first.status is second.status is BillingPaymentStatus.SUCCEEDED
                    return first
                return await workflow.activate_subscription(command)

            recovered = asyncio.run(recover())
            assert recovered.status is BillingPaymentStatus.SUCCEEDED
            assert recovered.amount_nok == 49
            assert not asyncio.run(recovered_session.find_account(CompanyId(COMPANY_ID))).subscription_active
            assert provider.executions == 0
            assert provider.reconciliations == (3 if failure_mode == "timeout" else 2)
            replay = asyncio.run(BillingService(recovered_session, provider).activate_subscription(command))
            assert replay.event_id == recovered.event_id
            assert replay.replayed
            assert provider.executions == 0
            assert provider.reconciliations == (3 if failure_mode == "timeout" else 2)
        finally:
            cleanup()
    finally:
        disable_backend_login()


def test_full_year_pilot_preserves_profile_identity_idempotency_and_rollback(setup, pilot_case):
    case = pilot_case
    historical = asyncio.run(case["management"].manage_pilot_entitlement(case["command"]))
    command = replace(case["command"], case_profile=BillingPilotCaseProfile.RF1086_FULL_YEAR_V1,
                      idempotency_key=IdempotencyKey(str(uuid4())))
    full_year = asyncio.run(case["management"].manage_pilot_entitlement(command))
    assert full_year.case_profile is BillingPilotCaseProfile.RF1086_FULL_YEAR_V1
    assert historical.entitlement_id != full_year.entitlement_id
    assert asyncio.run(case["management"].manage_pilot_entitlement(command)) == full_year
    assert read_pilot(setup, case).pilot_entitlement_id == historical.entitlement_id
    assert read_pilot(setup, case, query=replace(case["query"], case_profile=command.case_profile.value)).pilot_entitlement_id == full_year.entitlement_id
    with pytest.raises(BillingError) as reused:
        asyncio.run(case["management"].manage_pilot_entitlement(replace(command, case_profile=historical.case_profile)))
    assert reused.value.code is BillingErrorCode.IDEMPOTENCY_KEY_REUSED
    with pytest.raises(BillingError) as moved:
        asyncio.run(case["management"].manage_pilot_entitlement(replace(command,
            entitlement_id=historical.entitlement_id, idempotency_key=IdempotencyKey(str(uuid4())))))
    assert moved.value.code is BillingErrorCode.INVALID_INPUT
    # The rollback CHECK scans retained rows even though the table forces RLS.
    rollback = Path(__file__).resolve().parents[3] / "supabase/rollback/20260924084752_billing_rf_full_year_pilot_profile.sql"
    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(rollback.read_text())
        connection.execute("rollback")
        assert connection.execute("select case_profile from billing.production_pilot_entitlements where id=%s",
                                  (str(full_year.entitlement_id),)).fetchone()[0] == command.case_profile.value
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute("update billing.production_pilot_entitlements set case_profile='unknown_profile' where id=%s",
                               (str(full_year.entitlement_id),))
    assert asyncio.run(case["management"].manage_pilot_entitlement(command)) == full_year
