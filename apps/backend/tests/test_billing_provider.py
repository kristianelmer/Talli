from __future__ import annotations

import asyncio
import pytest

from talli_backend.adapters.simulation_billing import SimulationBillingProvider
from talli_backend.modules.billing.public import (
    BillingError,
    BillingErrorCode,
    BillingPaymentKind,
    BillingPaymentProvider,
    BillingPaymentStatus,
    BillingProviderIntent,
)
from talli_backend.shared.kernel import CompanyId, IdempotencyKey, IncomeYear


@pytest.mark.parametrize(
    ("kind", "status"),
    [
        (BillingPaymentKind.SUBSCRIPTION, BillingPaymentStatus.SUCCEEDED),
        (BillingPaymentKind.SUBSCRIPTION_CANCELLATION, BillingPaymentStatus.CANCELED),
        (BillingPaymentKind.FILING_PACKAGE, BillingPaymentStatus.SUCCEEDED),
        (BillingPaymentKind.REFUND, BillingPaymentStatus.REFUNDED),
    ],
)
def test_simulation_provider_conforms_without_production_activation(kind, status) -> None:
    provider = SimulationBillingProvider()
    assert isinstance(provider, BillingPaymentProvider)
    assert provider.production_enabled is False
    intent = BillingProviderIntent(
            company_id=CompanyId("10000000-0000-4000-8000-000000000001"),
            idempotency_key=IdempotencyKey("provider-port-test-00000001"),
            kind=kind,
            amount_nok=0 if kind is BillingPaymentKind.SUBSCRIPTION_CANCELLATION else 499,
            income_year=IncomeYear(2025) if kind in {BillingPaymentKind.FILING_PACKAGE, BillingPaymentKind.REFUND} else None,
        )
    if kind in {BillingPaymentKind.SUBSCRIPTION, BillingPaymentKind.FILING_PACKAGE}:
        with pytest.raises(BillingError) as retired:
            asyncio.run(provider.execute(intent))
        assert retired.value.code is BillingErrorCode.LEGACY_ACQUISITION_RETIRED
        result = asyncio.run(provider.reconcile(intent))
    else:
        result = asyncio.run(provider.execute(intent))
    assert result.provider == "simulation"
    assert result.status is status
    assert result.provider_reference.startswith(f"sim_{kind.value}_")


def test_simulation_reconciles_durable_intent_after_adapter_restart() -> None:
    intent = BillingProviderIntent(
        company_id=CompanyId("10000000-0000-4000-8000-000000000001"),
        idempotency_key=IdempotencyKey("provider-reconcile-test-00000001"),
        kind=BillingPaymentKind.SUBSCRIPTION,
        amount_nok=49,
        income_year=None,
    )
    result = asyncio.run(SimulationBillingProvider().reconcile(intent))
    assert asyncio.run(SimulationBillingProvider().reconcile(intent)) == result
