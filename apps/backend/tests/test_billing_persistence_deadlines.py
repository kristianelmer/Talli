import asyncio
import time
import json
from datetime import UTC, datetime
import psycopg
import pytest
from test_supabase_billing_runtime import (
    DATABASE_URL, COMPANY_ID, OWNER_ID, metadata, seed, cleanup,
    enable_backend_login, disable_backend_login, test_role_authority,
)
from talli_backend.adapters.supabase_billing import SupabaseBillingSession
from talli_backend.adapters.supabase_ledger import _VerifiedActor
from talli_backend.adapters.simulation_billing import SimulationBillingProvider
from talli_backend.modules.billing.service import BillingService
from talli_backend.modules.billing.public import (
    BillingError, BillingPaymentKind, BillingPaymentStatus,
    CancelSubscriptionCommand, MarkBillingUnsupportedCommand,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, UserId


pytestmark = pytest.mark.billing_database

@pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
@pytest.mark.parametrize("operation", ["payment", "unsupported"])
def test_billing_lock_timeout_rolls_back_and_allows_recovery(operation):
    database_url = enable_backend_login()
    try:
        seed()
        try:
            actor = ActorId(ActorKind.USER, UserId(OWNER_ID))
            session = SupabaseBillingSession(database_url, _VerifiedActor(actor_id=actor, claims_json=json.dumps({
                "sub": OWNER_ID, "aal": "aal2", "role": "authenticated",
                "amr": [{"method": "totp", "timestamp": datetime.now(UTC).timestamp()}],
            })))
            service = BillingService(session, SimulationBillingProvider())
            command = (CancelSubscriptionCommand(**metadata("lock-payment")) if operation == "payment" else
                MarkBillingUnsupportedCommand(**metadata("lock-unsupported"), reason="Outside historical scope"))
            async def perform():
                return await (service.cancel_subscription(command) if operation == "payment" else service.mark_unsupported(command))
            with psycopg.connect(DATABASE_URL) as locker:
                locker.execute("select company_id from billing.billing_accounts where company_id=%s::uuid for update", (COMPANY_ID,))
                started = time.monotonic()
                with pytest.raises(BillingError):
                    asyncio.run(asyncio.wait_for(perform(), timeout=3))
                assert time.monotonic() - started < 3
            if operation == "payment":
                pending = asyncio.run(session.find_payment_event(company_id=CompanyId(COMPANY_ID), idempotency_key=command.idempotency_key, kind=BillingPaymentKind.SUBSCRIPTION_CANCELLATION, income_year=None))
                assert pending.status is BillingPaymentStatus.CREATED
                recovered = asyncio.run(perform())
                assert recovered.event_id == pending.event_id
                assert recovered.status is BillingPaymentStatus.CANCELED
            else:
                assert not asyncio.run(perform()).supported_case
        finally:
            cleanup()
    finally:
        disable_backend_login()
