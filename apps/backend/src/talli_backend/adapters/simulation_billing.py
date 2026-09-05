"""Declared non-production billing provider adapter."""

from __future__ import annotations

from talli_backend.modules.billing.public import (
    BillingError,
    BillingErrorCode,
    BillingPaymentKind,
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
        if intent.kind in (BillingPaymentKind.SUBSCRIPTION, BillingPaymentKind.FILING_PACKAGE):
            raise BillingError.precondition(BillingErrorCode.LEGACY_ACQUISITION_RETIRED)
        return self._result(intent)

    def _result(self, intent: BillingProviderIntent) -> BillingProviderResult:
        suffix = (
            f"_{int(intent.income_year)}" if intent.income_year is not None else ""
        )
        return BillingProviderResult(
            provider=self.provider,
            provider_reference=f"sim_{intent.kind.value}_{intent.company_id}{suffix}",
            status=expected_payment_status(intent.kind),
        )

    async def reconcile(self, intent: BillingProviderIntent) -> BillingProviderResult:
        # Simulation has no external side effect. Its outcome is fully determined
        # by the durable intent, including when the process stopped before execute.
        return self._result(intent)


__all__ = ["SimulationBillingProvider"]
