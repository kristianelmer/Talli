"""Opened-case observation of an already recorded agreement stop."""

from asyncio import timeout
from dataclasses import replace

from talli_backend.modules.billing.public import (
    AnnualAgreementCleanup, AnnualBillingProvider, AnnualProviderObservation,
    AnnualProviderOperation, AnnualProviderStatus, AnnualSupportCleanupRecoveryPersistence,
    AnnualSupportCleanupRecoveryQuery, BillingError, BillingErrorCode,
    settle_annual_agreement_cleanup,
)


def _checked(query, cleanup):
    if (not isinstance(cleanup, AnnualAgreementCleanup)
            or cleanup.purchase_id != query.purchase_id or cleanup.intent.company_id != query.company_id
            or cleanup.intent.operation is not AnnualProviderOperation.STOP_AGREEMENT
            or cleanup.intent.amount_minor != 0 or not cleanup.intent.agreement_reference):
        raise BillingError.unavailable()
    if cleanup.observation is not None:
        # Validate even a stored confirmed observation before treating it as terminal.
        settle_annual_agreement_cleanup(replace(cleanup, observation=None), cleanup.observation)
    return cleanup


class AnnualSupportCleanupRecoveryService:
    def __init__(self, persistence: AnnualSupportCleanupRecoveryPersistence, provider: AnnualBillingProvider | None):
        self._store = persistence
        self._provider = provider

    async def recover_cleanup(self, query: AnnualSupportCleanupRecoveryQuery) -> AnnualAgreementCleanup:
        if query.actor_id != self._store.actor_id:
            raise BillingError.forbidden()
        cleanup = _checked(query, await self._store.load_cleanup_recovery(query))
        if cleanup.observation and cleanup.observation.status is AnnualProviderStatus.CONFIRMED:
            return cleanup
        provider = self._provider
        if (provider is None or provider.production_enabled or not provider.account_reference
                or cleanup.provider != provider.provider or cleanup.provider_account != provider.account_reference):
            raise BillingError.unavailable(BillingErrorCode.PROVIDER_DISABLED)
        try:
            async with timeout(12):
                observation = await provider.reconcile(cleanup.intent)
            settle_annual_agreement_cleanup(cleanup, observation)
        except Exception:
            observation = AnnualProviderObservation(
                provider=cleanup.provider, operation=AnnualProviderOperation.STOP_AGREEMENT,
                status=AnnualProviderStatus.UNKNOWN, agreement_reference=cleanup.intent.agreement_reference,
                charge_reference=cleanup.intent.charge_reference, amount_minor=0,
            )
        result = _checked(query, await self._store.settle_cleanup_recovery(query, cleanup, observation))
        if replace(result, observation=None) != replace(cleanup, observation=None):
            raise BillingError.unavailable()
        return result
