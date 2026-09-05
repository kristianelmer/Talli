"""Single-winner annual checkout with committed intent and read-only recovery."""

from asyncio import timeout
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from uuid import uuid4

from talli_backend.modules.billing.annual_policy import annual_offer
from talli_backend.modules.billing.public import (
    AnnualBillingProvider, AnnualCheckout, AnnualCheckoutPersistence,
    AnnualCheckoutPrerequisites, AnnualCheckoutQuery, AnnualProviderIntent,
    AnnualProviderObservation, AnnualProviderOperation, AnnualProviderStatus,
    AnnualPurchaseId, AnnualPurchaseStatus, BillingError, BillingErrorCode,
    BillingPaymentEventId, StartAnnualCheckoutCommand, settle_annual_checkout,
)
from talli_backend.shared.kernel import Timestamp


def checkout_fingerprint(command: StartAnnualCheckoutCommand) -> str:
    # Generated identities and refreshed assessments do not change customer intent.
    body = {
        "company": str(command.company_id), "year": command.income_year.value,
        "actor": str(command.actor_id.subject), "offer": command.offer_version,
        "terms": command.terms_digest, "accepted": command.purchase_accepted,
        "recurring": command.recurring_consent, "consent": command.consent_version,
    }
    return sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class AnnualCheckoutService:
    def __init__(
        self, persistence: AnnualCheckoutPersistence, provider: AnnualBillingProvider | None,
        *, return_url: str, management_url: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = persistence
        self._provider = provider
        self._return_url = return_url
        self._management_url = management_url
        self._now = now or (lambda: datetime.now(UTC))

    async def start_checkout(
        self, command: StartAnnualCheckoutCommand,
        prerequisites: Callable[[], Awaitable[AnnualCheckoutPrerequisites]],
    ) -> AnnualCheckout:
        if command.actor_id != self._store.actor_id:
            raise BillingError.forbidden()
        await self._store.authorize_owner_command(command.company_id)
        fingerprint = checkout_fingerprint(command)
        existing = await self._store.find_checkout(command.company_id, command.idempotency_key)
        if existing is not None:
            self._same_request(existing, command, fingerprint)
            return await self._observe(existing, newly_claimed=False)
        offer = annual_offer(command.company_id, command.income_year)
        if (command.offer_version != offer.offer_version or command.terms_digest != offer.terms_digest
                or command.consent_version != offer.offer_version):
            raise BillingError.conflict(BillingErrorCode.INVALID_INPUT)
        self._provider_enabled()
        evidence = await prerequisites()
        if (evidence.basis.company_id != command.company_id
                or evidence.basis.income_year != command.income_year
                or evidence.ready is not True
                or not timedelta(0) <= self._now() - evidence.evaluated_at.value <= timedelta(minutes=5)):
            raise BillingError.precondition(BillingErrorCode.FILING_NOT_READY)
        purchase_id = AnnualPurchaseId(str(uuid4()))
        intent = AnnualProviderIntent(
            operation_id=BillingPaymentEventId(str(uuid4())), company_id=command.company_id,
            income_year=command.income_year, operation=AnnualProviderOperation.CHECKOUT,
            amount_minor=offer.gross_minor, created_at=Timestamp(self._now()),
            agreement_external_reference=f"agreement-{purchase_id}", charge_reference=f"charge-{purchase_id}",
            return_url=self._return_url, management_url=self._management_url,
            recurring_consent=command.recurring_consent,
        )
        candidate = AnnualCheckout(
            purchase_id=purchase_id, offer=offer, accepted_by=command.actor_id.subject,
            request_fingerprint=fingerprint, idempotency_key=command.idempotency_key,
            provider=self._provider.provider, provider_account=self._provider.account_reference,
            intent=intent, status=AnnualPurchaseStatus.PENDING,
        )
        claim = await self._store.claim_checkout(candidate, evidence)
        self._same_request(claim.checkout, command, fingerprint)
        return await self._observe(claim.checkout, newly_claimed=claim.newly_claimed)

    async def poll_checkout(self, query: AnnualCheckoutQuery) -> AnnualCheckout:
        if query.actor_id != self._store.actor_id:
            raise BillingError.forbidden()
        await self._store.authorize_owner_command(query.company_id)
        checkout = await self._store.load_checkout(query.company_id, query.purchase_id)
        if checkout.offer.company_id != query.company_id or checkout.purchase_id != query.purchase_id:
            raise BillingError.not_found()
        return await self._observe(checkout, newly_claimed=False)

    def _provider_enabled(self) -> None:
        if self._provider is None or self._provider.production_enabled or not self._provider.account_reference:
            raise BillingError.unavailable(BillingErrorCode.PROVIDER_DISABLED)

    @staticmethod
    def _same_request(checkout, command, fingerprint):
        if (checkout.offer.company_id != command.company_id
                or checkout.offer.income_year != command.income_year
                or checkout.idempotency_key != command.idempotency_key
                or checkout.request_fingerprint != fingerprint):
            raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)

    async def _observe(self, checkout: AnnualCheckout, *, newly_claimed: bool) -> AnnualCheckout:
        if checkout.status in {AnnualPurchaseStatus.PAID, AnnualPurchaseStatus.FAILED, AnnualPurchaseStatus.REFUNDED}:
            return checkout
        self._provider_enabled()
        if checkout.provider != self._provider.provider or checkout.provider_account != self._provider.account_reference:
            raise BillingError.unavailable(BillingErrorCode.PROVIDER_DISABLED)
        bound_intent = checkout.intent
        if checkout.observation and checkout.observation.agreement_reference:
            bound_intent = replace(bound_intent, agreement_reference=checkout.observation.agreement_reference)
        try:
            async with timeout(12):
                observation = await (self._provider.execute(bound_intent) if newly_claimed
                                     else self._provider.reconcile(bound_intent))
            self._validate(checkout, observation)
        except Exception:
            # Never replace the operation or issue a second create after uncertainty.
            previous = checkout.observation
            observation = AnnualProviderObservation(
                provider=checkout.provider, operation=AnnualProviderOperation.CHECKOUT,
                status=AnnualProviderStatus.UNKNOWN, agreement_reference=bound_intent.agreement_reference,
                charge_reference=checkout.intent.charge_reference, amount_minor=checkout.offer.gross_minor,
                captured_minor=previous.captured_minor if previous else 0,
                refunded_minor=previous.refunded_minor if previous else 0,
                captured_at=previous.captured_at if previous else None,
            )
        return await self._store.settle_checkout(checkout, observation)

    def _validate(self, checkout, observation):
        settle_annual_checkout(checkout, observation, Timestamp(self._now()))
