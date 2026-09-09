"""Recover the original agreement-stop operation without changing purchase money."""

from asyncio import timeout
from dataclasses import replace

from talli_backend.modules.billing.public import (
    AnnualAgreementCleanup,
    AnnualAgreementCleanupPersistence,
    AnnualBillingProvider,
    AnnualCheckoutQuery,
    AnnualProviderObservation,
    AnnualProviderOperation,
    AnnualProviderStatus,
    BillingError,
    BillingErrorCode,
)


def settle_cleanup(cleanup, observation):
    if cleanup.observation and cleanup.observation.status is AnnualProviderStatus.CONFIRMED:
        return cleanup
    intent = cleanup.intent
    if not isinstance(observation, AnnualProviderObservation) or (
        intent.operation is not AnnualProviderOperation.STOP_AGREEMENT
        or intent.amount_minor != 0 or not intent.agreement_reference
        or observation.provider != cleanup.provider
        or observation.operation is not AnnualProviderOperation.STOP_AGREEMENT
        or not isinstance(observation.status, AnnualProviderStatus)
        or observation.status not in {
            AnnualProviderStatus.PENDING, AnnualProviderStatus.UNKNOWN, AnnualProviderStatus.CONFIRMED,
        }
        or observation.agreement_reference != intent.agreement_reference
        or observation.charge_reference != intent.charge_reference
        or any(type(value) is not int or value != 0 for value in (
            observation.amount_minor, observation.captured_minor, observation.refunded_minor,
        ))
        or observation.captured_at is not None or observation.checkout_url is not None
    ):
        raise BillingError.invalid()
    return replace(cleanup, observation=observation)


class AnnualAgreementCleanupService:
    def __init__(self, persistence: AnnualAgreementCleanupPersistence, provider: AnnualBillingProvider | None):
        self._store = persistence
        self._provider = provider

    async def cleanup(self, query: AnnualCheckoutQuery) -> AnnualAgreementCleanup | None:
        if query.actor_id != self._store.actor_id:
            raise BillingError.forbidden()
        claim = await self._store.claim_agreement_cleanup(query.company_id, query.purchase_id)
        if claim is None:
            return None
        cleanup = claim.cleanup
        intent = cleanup.intent
        if (cleanup.purchase_id != query.purchase_id or intent.company_id != query.company_id
                or intent.operation is not AnnualProviderOperation.STOP_AGREEMENT
                or intent.amount_minor != 0 or not intent.agreement_reference):
            raise BillingError.invalid()
        if cleanup.observation and cleanup.observation.status is AnnualProviderStatus.CONFIRMED:
            return cleanup
        if (self._provider is None or self._provider.production_enabled or not self._provider.account_reference
                or cleanup.provider != self._provider.provider
                or cleanup.provider_account != self._provider.account_reference):
            raise BillingError.unavailable(BillingErrorCode.PROVIDER_DISABLED)
        try:
            async with timeout(12):
                if claim.newly_claimed:
                    observation = await self._provider.execute(intent)
                else:
                    observation = await self._provider.reconcile(intent)
                    settle_cleanup(cleanup, observation)
                    # Recover a crash after claim but before PATCH. The adapter
                    # rechecks current charge safety and reuses this exact key.
                    if observation.status is AnnualProviderStatus.PENDING:
                        observation = await self._provider.execute(intent)
                settle_cleanup(cleanup, observation)
        except Exception:
            observation = AnnualProviderObservation(
                provider=cleanup.provider, operation=AnnualProviderOperation.STOP_AGREEMENT,
                status=AnnualProviderStatus.UNKNOWN, agreement_reference=intent.agreement_reference,
                charge_reference=intent.charge_reference, amount_minor=0,
            )
        return await self._store.settle_agreement_cleanup(cleanup, observation)
