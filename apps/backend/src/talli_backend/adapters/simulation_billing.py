"""Declared non-production billing provider adapter."""

from __future__ import annotations

from talli_backend.modules.billing.public import (
    BillingPaymentProvider,
    BillingProviderIntent,
    BillingProviderResult,
    billing_provider_adapter,
    expected_payment_status,
)


@billing_provider_adapter(BillingPaymentProvider)
class SimulationBillingProvider:
    provider = "simulation"
    production_enabled = False

    async def execute(self, intent: BillingProviderIntent) -> BillingProviderResult:
        suffix = (
            f"_{int(intent.income_year)}" if intent.income_year is not None else ""
        )
        return BillingProviderResult(
            provider=self.provider,
            provider_reference=f"sim_{intent.kind.value}_{intent.company_id}{suffix}",
            status=expected_payment_status(intent.kind),
        )


__all__ = ["SimulationBillingProvider"]
