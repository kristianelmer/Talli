from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from talli_backend.adapters.simulation_billing import SimulationBillingProvider
from talli_backend.modules.billing.service import BillingService
from talli_backend.adapters.supabase_billing import SupabaseBillingSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.billing.public import (
    ActivateSubscriptionCommand,
    BillingError,
    BillingErrorCode,
    BillingPaymentStatus,
    BillingPlan,
    BillingPricing,
    BillingProviderResult,
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
        connection.execute(
            "delete from public.support_operators where user_id=%s::uuid", (ADMIN_ID,)
        )
        connection.execute("delete from public.companies where id=%s::uuid", (COMPANY_ID,))
        connection.execute("delete from auth.users where id=%s::uuid", (OWNER_ID,))
        connection.execute("delete from auth.users where id=%s::uuid", (OUTSIDER_ID,))
        connection.execute("delete from auth.users where id=%s::uuid", (ADMIN_ID,))


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
                            "timestamp": datetime.now(UTC).timestamp(),
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
                            "timestamp": datetime.now(UTC).timestamp(),
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
                "amr": [{"method": "totp", "timestamp": datetime.now(UTC).timestamp()}],
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
