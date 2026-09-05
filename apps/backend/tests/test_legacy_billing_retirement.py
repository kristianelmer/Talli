"""Retirement of acquisition authority, distinct from historical recovery."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from test_billing import MemoryPersistence, NOW, account, metadata, query
from talli_backend.adapters.simulation_billing import SimulationBillingProvider
from talli_backend.modules.billing.public import (
    ActivateSubscriptionCommand,
    BillingError,
    BillingPaymentEvent,
    BillingPaymentEventId,
    BillingPaymentKind,
    BillingPaymentStatus,
    BillingPlan,
    ConfigureBillingAccountCommand,
    PurchaseFilingPackageCommand,
)
from talli_backend.modules.billing.service import BillingService
from talli_backend.shared.kernel import IncomeYear


class ObservedProvider(SimulationBillingProvider):
    def __init__(self):
        self.calls = []

    async def execute(self, intent):
        self.calls.append(("execute", intent))
        return await super().execute(intent)

    async def reconcile(self, intent):
        self.calls.append(("reconcile", intent))
        return await super().reconcile(intent)


def acquisition(name, key="retired-acquisition"):
    if name == "configure_account":
        return ConfigureBillingAccountCommand(**metadata(key), pricing_plan=BillingPlan.STANDARD)
    if name == "activate_subscription":
        return ActivateSubscriptionCommand(**metadata(key))
    return PurchaseFilingPackageCommand(**metadata(key), income_year=IncomeYear(2025))


@pytest.mark.parametrize("name", ["configure_account", "activate_subscription", "purchase_filing_package"])
@pytest.mark.parametrize("has_account", [False, True])
def test_new_legacy_acquisition_cannot_reset_state_claim_an_intent_or_call_provider(name, has_account):
    original = account(subscription_active=True, filing_package_paid=True) if has_account else None
    persistence = MemoryPersistence(original, ready=True)
    provider = ObservedProvider()
    service = BillingService(persistence, provider)
    with pytest.raises(BillingError) as denied:
        asyncio.run(getattr(service, name)(acquisition(name)))
    assert str(denied.value.code) == "BILLING_LEGACY_ACQUISITION_RETIRED"
    assert persistence.account == original and persistence.events == {} and provider.calls == []


@pytest.mark.parametrize("value", [
    None,
    account(),
    account(subscription_active=True),
    account(filing_package_paid=True),
    account(subscription_active=True, filing_package_paid=True),
    account(subscription_active=True, filing_package_paid=True, refund_eligible=True),
    account(subscription_active=True, filing_package_paid=True, refund_completed=True),
    account(supported_case=False),
])
@pytest.mark.parametrize("ready", [False, True])
def test_no_legacy_flag_combination_grants_paid_or_charge_authority(value, ready):
    persistence = MemoryPersistence(value, ready=ready)
    provider = ObservedProvider()
    decision = asyncio.run(BillingService(persistence, provider).entitlement(query()))
    assert not decision.allowed and not decision.charge_allowed and not decision.billing_exempt
    assert decision.status.value == "annual_billing_unavailable"
    # Permission to prepare the independent readiness check is not paid entitlement
    # and does not assert that eligibility, readiness or operational gates passed.
    assert decision.readiness_allowed
    assert provider.calls == [] and persistence.account == value


@pytest.mark.parametrize("name", ["activate_subscription", "purchase_filing_package"])
def test_exact_successful_historical_replay_is_read_only_even_after_retirement(name):
    command = acquisition(name, "historical-replay")
    original = account(subscription_active=False, filing_package_paid=False)
    persistence = MemoryPersistence(original)
    kind = BillingPaymentKind.SUBSCRIPTION if name == "activate_subscription" else BillingPaymentKind.FILING_PACKAGE
    event = BillingPaymentEvent(
        event_id=BillingPaymentEventId(str(uuid4())), company_id=command.company_id,
        provider="simulation", provider_reference="historical-reference",
        idempotency_key=command.idempotency_key, kind=kind, status=BillingPaymentStatus.SUCCEEDED,
        amount_nok=49 if name == "activate_subscription" else 499,
        income_year=getattr(command, "income_year", None), created_by=command.actor_id.subject,
        created_at=NOW, obligation=getattr(command, "obligation", None),
    )
    persistence.events[str(command.idempotency_key)] = event
    provider = ObservedProvider()
    result = asyncio.run(getattr(BillingService(persistence, provider), name)(command))
    assert result == replace(event, replayed=True)
    assert persistence.account == original and provider.calls == []
