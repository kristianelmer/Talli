"""One account-bound observation of an existing checkout; no provider execution."""

from asyncio import timeout
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
import json

from talli_backend.modules.billing.public import (
    AnnualBillingProvider, AnnualCheckoutObservationPersistence,
    AnnualCheckoutObservationOutcome, AnnualPurchaseStatus, BillingError,
    BillingErrorCode, settle_annual_checkout,
    AnnualCheckout, AnnualCheckoutObservationBinding, AnnualProviderOperation,
)
from talli_backend.shared.kernel import Timestamp


def accepted_checkout_fingerprint(*, company, year, actor, offer, terms, accepted, recurring, consent):
    body = dict(company=str(company), year=year, actor=str(actor), offer=offer,
                terms=terms, accepted=accepted, recurring=recurring, consent=consent)
    return sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_observation_binding(checkout: AnnualCheckout, binding: AnnualCheckoutObservationBinding) -> None:
    intent, offer = checkout.intent, checkout.offer
    fingerprint = accepted_checkout_fingerprint(
        company=offer.company_id, year=offer.income_year.value, actor=checkout.accepted_by,
        offer=offer.offer_version, terms=offer.terms_digest, accepted=True,
        recurring=binding.recurring_consent, consent=binding.consent_version,
    )
    if (binding.purchase_id != checkout.purchase_id or binding.operation_id != intent.operation_id
            or binding.company_id != offer.company_id or binding.company_id != intent.company_id
            or binding.income_year != offer.income_year or binding.income_year != intent.income_year
            or binding.created_by != checkout.accepted_by
            or binding.accepted_at != intent.created_at or binding.created_at != intent.created_at
            or intent.operation != AnnualProviderOperation.CHECKOUT
            or type(binding.amount_minor) is not int or binding.amount_minor != offer.gross_minor
            or intent.amount_minor != offer.gross_minor
            or binding.agreement_external_reference != intent.agreement_external_reference
            or binding.charge_reference != intent.charge_reference
            or binding.recurring_consent != intent.recurring_consent
            or fingerprint != checkout.request_fingerprint
            or not checkout.provider or not checkout.provider_account):
        raise BillingError.unavailable()


class AnnualCheckoutObservationService:
    def __init__(self, persistence: AnnualCheckoutObservationPersistence, provider: AnnualBillingProvider | None):
        self._store = persistence
        self._provider = provider

    async def run_once(self) -> AnnualCheckoutObservationOutcome:
        provider = self._provider
        if (provider is None or provider.production_enabled
                or provider.provider != self._store.provider
                or not provider.account_reference
                or provider.account_reference != self._store.provider_account):
            raise BillingError.unavailable(BillingErrorCode.PROVIDER_DISABLED)
        lease = await self._store.claim_checkout_observation()
        if lease is None:
            return AnnualCheckoutObservationOutcome.IDLE
        checkout = lease.checkout
        if (checkout.provider != provider.provider or checkout.provider_account != provider.account_reference):
            raise BillingError.unavailable()
        await self._store.authorize_checkout_observation(lease)
        intent = checkout.intent
        if checkout.observation and checkout.observation.agreement_reference:
            intent = replace(intent, agreement_reference=checkout.observation.agreement_reference)
        try:
            async with timeout(12):
                observation = await provider.reconcile(intent)
            # Validate provider evidence with the same billing policy as HTTP.
            # Persistence invokes it again against the latest locked state.
            settle_annual_checkout(checkout, observation, Timestamp(datetime.now(UTC)))
        except Exception:
            observation = None
        result = await self._store.settle_checkout_observation(lease, observation)
        return (AnnualCheckoutObservationOutcome.RECONCILED
                if result.status in {AnnualPurchaseStatus.PAID, AnnualPurchaseStatus.FAILED, AnnualPurchaseStatus.REFUNDED}
                else AnnualCheckoutObservationOutcome.RETRY)
