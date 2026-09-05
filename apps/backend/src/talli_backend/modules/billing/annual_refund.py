"""Recorded refund liability, single-winner execution and original-effect recovery."""

from asyncio import timeout
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from talli_backend.modules.billing.public import (
    AnnualBillingProvider, AnnualProviderObservation, AnnualProviderOperation,
    AnnualProviderStatus, AnnualRefundOperation, AnnualRefundPersistence, AnnualRefundResolution,
    BillingError, BillingErrorCode, RequestAnnualRefundCommand, annual_refund_decision,
)
from talli_backend.shared.kernel import Timestamp


def _validate_resolution(resolution: AnnualRefundResolution, at: Timestamp) -> None:
    facts, operation = resolution.facts, resolution.operation
    if (
        len(resolution.source_digest) != 64
        or any(c not in '0123456789abcdef' for c in resolution.source_digest)
        or facts.discovered_at.value > at.value
        or facts.evidence_reference != resolution.request.source_reference
        or resolution.decision != annual_refund_decision(facts)
    ):
        raise BillingError.invalid()
    if operation is None:
        return
    intent = operation.intent
    if (
        operation.purchase_id != resolution.request.purchase_id
        or intent.operation is not AnnualProviderOperation.REFUND
        or intent.company_id != resolution.request.company_id
        or intent.income_year != facts.income_year
        or not operation.provider or not operation.provider_account
        or not intent.agreement_reference
        or type(operation.captured_minor) is not int
        or not 0 < operation.captured_minor <= facts.gross_minor
        or type(operation.previous_refunded_minor) is not int
        or not facts.refunded_minor <= operation.previous_refunded_minor < operation.captured_minor
        or intent.original_charge_minor != facts.gross_minor
        or intent.amount_minor != max(0, min(resolution.decision.total_entitlement_minor, operation.captured_minor) - operation.previous_refunded_minor)
        or intent.amount_minor <= 0
        or operation.captured_at != facts.purchased_at
        or not facts.discovered_at.value <= intent.created_at.value <= at.value
    ):
        raise BillingError.invalid()


def _validate_observation(
    operation: AnnualRefundOperation, observation: AnnualProviderObservation,
) -> None:
    intent = operation.intent
    if not isinstance(observation, AnnualProviderObservation) or (
        observation.provider != operation.provider
        or observation.operation is not AnnualProviderOperation.REFUND
        or observation.status not in {
            AnnualProviderStatus.PENDING, AnnualProviderStatus.UNKNOWN,
            AnnualProviderStatus.CONFIRMED, AnnualProviderStatus.FAILED,
        }
        or not isinstance(observation.status, AnnualProviderStatus)
        or observation.agreement_reference != intent.agreement_reference
        or observation.charge_reference != intent.charge_reference
        or any(type(value) is not int for value in (
            observation.amount_minor, observation.captured_minor, observation.refunded_minor,
        ))
        or observation.amount_minor != intent.amount_minor
        or not operation.captured_minor <= observation.captured_minor <= intent.original_charge_minor
        or observation.captured_at != operation.captured_at
        or observation.checkout_url is not None
        or not operation.previous_refunded_minor <= observation.refunded_minor <= observation.captured_minor
        or (
            observation.status is AnnualProviderStatus.CONFIRMED
            and observation.refunded_minor < operation.previous_refunded_minor + intent.amount_minor
        )
        or (
            observation.status is AnnualProviderStatus.FAILED
            and observation.refunded_minor != operation.previous_refunded_minor
        )
    ):
        raise BillingError.invalid()


def settle_refund(
    resolution: AnnualRefundResolution, observation: AnnualProviderObservation, at: Timestamp,
) -> AnnualRefundResolution:
    _validate_resolution(resolution, at)
    operation = resolution.operation
    if operation is None:
        raise BillingError.invalid()
    old = operation.observation
    if old is not None:
        _validate_observation(operation, old)
    if old is not None and old.status in {AnnualProviderStatus.CONFIRMED, AnnualProviderStatus.FAILED}:
        return resolution
    _validate_observation(operation, observation)
    if old and (observation.refunded_minor < old.refunded_minor
                or observation.captured_minor < old.captured_minor):
        return resolution
    return replace(resolution, operation=replace(operation, observation=observation))


class AnnualRefundService:
    def __init__(
        self, persistence: AnnualRefundPersistence, provider: AnnualBillingProvider | None,
        *, now: Callable[[], datetime] | None = None,
    ):
        self._store = persistence
        self._provider = provider
        self._now = now or (lambda: datetime.now(UTC))

    async def request_refund(self, command: RequestAnnualRefundCommand) -> AnnualRefundResolution:
        if command.actor_id != self._store.actor_id:
            raise BillingError.forbidden()
        # Liability, deadline and renewal stop must survive provider outage.
        claim = await self._store.claim_refund(command)
        resolution = claim.resolution
        if replace(command, correlation_id=resolution.request.correlation_id) != resolution.request:
            raise BillingError.conflict(BillingErrorCode.IDEMPOTENCY_KEY_REUSED)
        _validate_resolution(resolution, Timestamp(self._now()))
        operation = resolution.operation
        if operation is None:
            if claim.newly_claimed:
                raise BillingError.invalid()
            return resolution
        old = operation.observation
        if old is not None:
            _validate_observation(operation, old)
        if claim.newly_claimed and old is not None:
            raise BillingError.invalid()
        if old and old.status in {AnnualProviderStatus.CONFIRMED, AnnualProviderStatus.FAILED}:
            return resolution
        provider = self._provider
        if (provider is None or provider.production_enabled or not provider.account_reference
                or operation.provider != provider.provider
                or operation.provider_account != provider.account_reference):
            raise BillingError.unavailable(BillingErrorCode.PROVIDER_DISABLED)
        try:
            async with timeout(12):
                observation = await (provider.execute(operation.intent) if claim.newly_claimed
                                     else provider.reconcile(operation.intent))
                settle_refund(resolution, observation, Timestamp(self._now()))
        except Exception:
            # Absence is not permission to reissue. Keep the durable liability
            # and original identity; an unresolved/overdue case needs recovery.
            observation = AnnualProviderObservation(
                provider=operation.provider, operation=AnnualProviderOperation.REFUND,
                status=AnnualProviderStatus.UNKNOWN,
                agreement_reference=operation.intent.agreement_reference,
                charge_reference=operation.intent.charge_reference,
                amount_minor=operation.intent.amount_minor,
                captured_minor=old.captured_minor if old else operation.captured_minor,
                refunded_minor=old.refunded_minor if old else operation.previous_refunded_minor,
                captured_at=operation.captured_at,
            )
        return await self._store.settle_refund(resolution, observation)
