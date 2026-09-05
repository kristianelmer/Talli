from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from talli_backend.adapters.supabase_billing import SupabaseBillingSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.modules.billing.public import (
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
    PurchaseFilingPackageCommand,
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
            "insert into auth.users (id, email) values (%s::uuid, %s::text), (%s::uuid, %s::text)",
            (
                OWNER_ID,
                "billing-runtime@example.test",
                OUTSIDER_ID,
                "billing-outsider@example.test",
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
            (OWNER_ID,),
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


def cleanup() -> None:
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            "delete from public.support_operators where user_id=%s::uuid", (OWNER_ID,)
        )
        connection.execute("delete from public.companies where id=%s::uuid", (COMPANY_ID,))
        connection.execute("delete from auth.users where id=%s::uuid", (OWNER_ID,))
        connection.execute("delete from auth.users where id=%s::uuid", (OUTSIDER_ID,))


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

            configure = ConfigureBillingAccountCommand(
                **metadata("configure"),
                pricing_plan=BillingPlan.FOUNDER,
                founder_cohort_number=1,
            )
            founder_pricing = BillingPricing(BillingPlan.FOUNDER, 29, 299)

            async def configure_twice():
                return await asyncio.gather(
                    session.configure_account(configure, founder_pricing),
                    session.configure_account(configure, founder_pricing),
                )

            first_account, replayed_account = asyncio.run(
                configure_twice()
            )
            assert replayed_account == first_account
            with pytest.raises(BillingError) as reused_configure:
                asyncio.run(
                    session.configure_account(
                        configure, BillingPricing(BillingPlan.STANDARD, 49, 499)
                    )
                )
            assert reused_configure.value.code == BillingErrorCode.IDEMPOTENCY_KEY_REUSED

            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute(
                    """update billing.billing_accounts set
                      subscription_active=true, filing_package_paid=true,
                      supported_case=false, refund_eligible=true,
                      refund_completed=true, no_charge_reason='legacy-state',
                      provider_customer_ref='customer-ref',
                      subscription_provider_ref='subscription-ref',
                      filing_package_payment_ref='package-ref',
                      refund_provider_ref='refund-ref'
                    where company_id=%s::uuid""",
                    (COMPANY_ID,),
                )
            reconfigured = asyncio.run(
                session.configure_account(
                    ConfigureBillingAccountCommand(
                        **metadata("reconfigure"),
                        pricing_plan=BillingPlan.STANDARD,
                        founder_cohort_number=None,
                    ),
                    BillingPricing(BillingPlan.STANDARD, 49, 499),
                )
            )
            assert reconfigured.pricing.plan is BillingPlan.STANDARD
            assert reconfigured.subscription_active is False
            assert reconfigured.filing_package_paid is False
            assert reconfigured.supported_case is True
            assert reconfigured.refund_eligible is False
            assert reconfigured.refund_completed is False
            assert reconfigured.no_charge_reason is None
            assert reconfigured.provider_customer_reference is None
            assert reconfigured.subscription_provider_reference is None
            assert reconfigured.filing_package_payment_reference is None
            assert reconfigured.refund_provider_reference is None

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

            payment = PurchaseFilingPackageCommand(
                **metadata("readiness-race"), income_year=IncomeYear(2025)
            )
            with psycopg.connect(DATABASE_URL) as connection:
                connection.execute(
                    """update public.filing_readiness_snapshots
                    set ready=false, status='blocked',
                      hard_blocks='["readiness revoked"]'::jsonb, updated_at=now()
                    where company_id=%s::uuid and income_year=2025
                      and obligation='aksjonaerregisteroppgaven'""",
                    (COMPANY_ID,),
                )
            failed_event = asyncio.run(
                session.complete_provider_event(
                    payment,
                    BillingProviderResult(
                        provider="simulation",
                        provider_reference="readiness-race-result",
                        status=BillingPaymentStatus.SUCCEEDED,
                    ),
                    founder_pricing.filing_package_nok,
                )
            )
            assert failed_event.status is BillingPaymentStatus.FAILED
            account_after_race = asyncio.run(session.find_account(CompanyId(COMPANY_ID)))
            assert account_after_race is not None
            assert account_after_race.filing_package_paid is False

            unsupported = MarkBillingUnsupportedCommand(
                **metadata("unsupported"), reason="Outside support"
            )
            first_unsupported = asyncio.run(session.mark_unsupported(unsupported))
            assert asyncio.run(session.mark_unsupported(unsupported)) == first_unsupported

            now = datetime(2026, 9, 5, tzinfo=UTC)
            pilot = ManageProductionPilotEntitlementCommand(
                **metadata("pilot"),
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
            first_pilot = asyncio.run(session.manage_pilot_entitlement(pilot))
            replayed_pilot = asyncio.run(session.manage_pilot_entitlement(pilot))
            assert replayed_pilot.entitlement_id == first_pilot.entitlement_id
        finally:
            cleanup()
    finally:
        disable_backend_login()
