"""Retirement of acquisition authority, distinct from historical recovery."""

import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from test_billing import MemoryPersistence, NOW, account, metadata, query, seed_historical_event
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
    RefundFilingPackageCommand,
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


def test_new_refund_uses_the_original_payment_amount_after_recovery():
    persistence = MemoryPersistence(account())
    command = acquisition("purchase_filing_package", "historical-refund-amount")
    original = seed_historical_event(persistence, command)
    persistence.events[str(command.idempotency_key)] = replace(original, amount_nok=299)
    provider = ObservedProvider()
    service = BillingService(persistence, provider)
    asyncio.run(service.purchase_filing_package(command))
    refund = RefundFilingPackageCommand(**metadata("fresh-historical-refund"), income_year=IncomeYear(2025))
    result = asyncio.run(service.refund_filing_package(refund))
    assert result.amount_nok == 299
    assert provider.calls[-1][1].amount_nok == 299
    assert not persistence.account.filing_package_paid
    decision = asyncio.run(service.entitlement(query()))
    assert not decision.allowed and not decision.charge_allowed


@pytest.mark.parametrize("change", ["missing", "pending", "failed", "other_year", "other_company", "multiple", "other_provider"])
def test_new_refund_fails_closed_without_one_confirmed_original_payment(change):
    persistence = MemoryPersistence(account())
    original_command = acquisition("purchase_filing_package", "historical-refund-scope")
    original = seed_historical_event(persistence, original_command, status=BillingPaymentStatus.SUCCEEDED)
    if change == "missing":
        persistence.events.clear()
    elif change == "multiple":
        seed_historical_event(persistence, acquisition("purchase_filing_package", "second-payment"), status=BillingPaymentStatus.SUCCEEDED)
    else:
        from talli_backend.shared.kernel import CompanyId
        changes = {
            "pending": {"status": BillingPaymentStatus.CREATED},
            "failed": {"status": BillingPaymentStatus.FAILED},
            "other_year": {"income_year": IncomeYear(2024)},
            "other_company": {"company_id": CompanyId(str(uuid4()))},
            "other_provider": {"provider": "different-merchant"},
        }
        persistence.events[str(original_command.idempotency_key)] = replace(original, **changes[change])
    provider = ObservedProvider()
    with pytest.raises(BillingError) as denied:
        asyncio.run(BillingService(persistence, provider).refund_filing_package(
            RefundFilingPackageCommand(**metadata("new-refund-denied"), income_year=IncomeYear(2025))
        ))
    assert str(denied.value.code) == "BILLING_REFUND_NOT_ALLOWED"
    assert provider.calls == []
