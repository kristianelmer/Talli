"""Monotonic checkout settlement, shared by orchestration and locked persistence."""

from dataclasses import replace

from talli_backend.modules.billing.public import (
    AnnualCheckout,
    AnnualProviderObservation,
    AnnualProviderOperation,
    AnnualProviderStatus,
    AnnualPurchaseStatus,
    BillingError,
)
from talli_backend.shared.kernel import Timestamp


def settle(checkout: AnnualCheckout, observation: AnnualProviderObservation, at: Timestamp) -> AnnualCheckout:
    if checkout.status in {
        AnnualPurchaseStatus.PAID,
        AnnualPurchaseStatus.FAILED,
        AnnualPurchaseStatus.REFUNDED,
    }:
        return checkout
    old = checkout.observation
    if not isinstance(observation, AnnualProviderObservation) or (
        observation.provider != checkout.provider
        or observation.operation is not AnnualProviderOperation.CHECKOUT
        or not isinstance(observation.status, AnnualProviderStatus)
        or observation.charge_reference != checkout.intent.charge_reference
        or observation.amount_minor != checkout.offer.gross_minor
        or any(
            type(value) is not int
            for value in (observation.amount_minor, observation.captured_minor, observation.refunded_minor)
        )
        or not 0 <= observation.refunded_minor <= observation.captured_minor <= checkout.offer.gross_minor
        or (
            observation.captured_minor > 0
            and (
                not observation.agreement_reference
                or observation.captured_at is None
                or not checkout.intent.created_at.value <= observation.captured_at.value <= at.value
            )
        )
        or (observation.captured_minor == 0 and observation.captured_at is not None)
        or (
            observation.status is AnnualProviderStatus.CONFIRMED
            and observation.captured_minor != checkout.offer.gross_minor
        )
        or (observation.status is AnnualProviderStatus.FAILED and observation.captured_minor != 0)
    ):
        raise BillingError.invalid()
    # A later locked observation wins over a valid but obsolete in-flight read.
    if old and (
        observation.captured_minor < old.captured_minor
        or observation.refunded_minor < old.refunded_minor
        or (old.captured_at and observation.captured_at != old.captured_at)
        or (old.agreement_reference and observation.agreement_reference != old.agreement_reference)
    ):
        return checkout
    status = AnnualPurchaseStatus.PENDING
    if observation.status is AnnualProviderStatus.CONFIRMED:
        status = (
            AnnualPurchaseStatus.REFUNDED
            if observation.refunded_minor == checkout.offer.gross_minor
            else AnnualPurchaseStatus.PAID
        )
    elif observation.status is AnnualProviderStatus.FAILED:
        status = AnnualPurchaseStatus.FAILED
    return replace(checkout, observation=observation, status=status)
