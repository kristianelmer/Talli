"""Canonical billing policy behind the public interface."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from talli_backend.modules.billing.public import (
    ActivateSubscriptionCommand,
    BillingAccount,
    BillingEntitlementDecision,
    BillingEntitlementQuery,
    BillingError,
    BillingErrorCode,
    BillingPaymentEvent,
    BillingPaymentKind,
    BillingPaymentProvider,
    BillingPaymentStatus,
    BillingPersistence,
    BillingPlan,
    BillingPricing,
    BillingProviderIntent,
    BillingSnapshot,
    BillingSnapshotQuery,
    BillingStatus,
    CancelSubscriptionCommand,
    ConfigureBillingAccountCommand,
    ManageProductionPilotEntitlementCommand,
    MarkBillingUnsupportedCommand,
    ProductionPilotEntitlement,
    PurchaseFilingPackageCommand,
    RefundFilingPackageCommand,
)


_PRICING = {
    BillingPlan.FOUNDER: BillingPricing(BillingPlan.FOUNDER, 29, 299),
    BillingPlan.STANDARD: BillingPricing(BillingPlan.STANDARD, 49, 499),
}


class BillingService:
    def __init__(
        self,
        persistence: BillingPersistence,
        provider: BillingPaymentProvider,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._persistence = persistence
        self._provider = provider
        self._now = now or (lambda: datetime.now(UTC))

    async def configure_account(
        self, command: ConfigureBillingAccountCommand
    ) -> BillingAccount:
        return await self._persistence.configure_account(command, _PRICING[command.pricing_plan])

    async def activate_subscription(
        self, command: ActivateSubscriptionCommand
    ) -> BillingPaymentEvent:
        account = await self._required_account(command.company_id)
        return await self._payment(
            command, BillingPaymentKind.SUBSCRIPTION, account.pricing.monthly_nok
        )

    async def cancel_subscription(
        self, command: CancelSubscriptionCommand
    ) -> BillingPaymentEvent:
        await self._required_account(command.company_id)
        return await self._payment(command, BillingPaymentKind.SUBSCRIPTION_CANCELLATION, 0)

    async def purchase_filing_package(
        self, command: PurchaseFilingPackageCommand
    ) -> BillingPaymentEvent:
        account = await self._required_account(command.company_id)
        if account.refund_eligible:
            raise BillingError.precondition(BillingErrorCode.REFUND_NOT_ALLOWED)
        if not account.supported_case:
            raise BillingError.precondition(BillingErrorCode.UNSUPPORTED_CASE)
        if not account.subscription_active:
            raise BillingError.precondition(BillingErrorCode.SUBSCRIPTION_REQUIRED)
        if not await self._persistence.filing_ready(
            command.company_id, command.income_year, command.obligation
        ):
            raise BillingError.precondition(BillingErrorCode.FILING_NOT_READY)
        return await self._payment(
            command,
            BillingPaymentKind.FILING_PACKAGE,
            account.pricing.filing_package_nok,
        )

    async def refund_filing_package(
        self, command: RefundFilingPackageCommand
    ) -> BillingPaymentEvent:
        account = await self._required_account(command.company_id)
        if (
            not account.supported_case
            or not account.filing_package_paid
            or account.refund_completed
        ):
            raise BillingError.precondition(BillingErrorCode.REFUND_NOT_ALLOWED)
        return await self._payment(
            command, BillingPaymentKind.REFUND, account.pricing.filing_package_nok
        )

    async def mark_unsupported(
        self, command: MarkBillingUnsupportedCommand
    ) -> BillingAccount:
        await self._required_account(command.company_id)
        return await self._persistence.mark_unsupported(command)

    async def manage_pilot_entitlement(
        self, command: ManageProductionPilotEntitlementCommand
    ) -> ProductionPilotEntitlement:
        return await self._persistence.manage_pilot_entitlement(command)

    async def snapshot(self, query: BillingSnapshotQuery) -> BillingSnapshot:
        snapshot = await self._persistence.snapshot(query)
        return replace(snapshot, pricing=tuple(_PRICING.values()))

    async def entitlement(
        self, query: BillingEntitlementQuery
    ) -> BillingEntitlementDecision:
        if query.case_profile:
            pilot = await self._persistence.find_active_pilot_entitlement(
                company_id=query.company_id,
                user_id=query.actor_id.subject,
                income_year=query.income_year,
                obligation=query.obligation,
                case_profile=query.case_profile,
                at=self._now(),
            )
            if pilot is not None and pilot.billing_exempt:
                return BillingEntitlementDecision(
                    company_id=query.company_id,
                    income_year=query.income_year,
                    obligation=query.obligation,
                    status=BillingStatus.PILOT_ENTITLEMENT_ACTIVE,
                    allowed=True,
                    charge_allowed=False,
                    readiness_allowed=True,
                    billing_exempt=True,
                    message="An exact active validation entitlement exempts billing.",
                    pilot_entitlement_id=pilot.entitlement_id,
                )
        account = await self._persistence.find_account(query.company_id)
        ready = await self._persistence.filing_ready(
            query.company_id, query.income_year, query.obligation
        )
        return billing_entitlement_decision(query, account, filing_ready=ready)

    async def _required_account(self, company_id) -> BillingAccount:
        account = await self._persistence.find_account(company_id)
        if account is None:
            raise BillingError.not_found()
        return account

    async def _payment(self, command, kind: BillingPaymentKind, amount_nok: int) -> BillingPaymentEvent:
        income_year = getattr(command, "income_year", None)
        replay = await self._persistence.find_payment_event(
            company_id=command.company_id,
            idempotency_key=command.idempotency_key,
            kind=kind,
            amount_nok=amount_nok,
            income_year=income_year,
        )
        if replay is not None:
            return replay
        status = {
            BillingPaymentKind.SUBSCRIPTION_CANCELLATION: BillingPaymentStatus.CANCELED,
            BillingPaymentKind.REFUND: BillingPaymentStatus.REFUNDED,
        }.get(kind, BillingPaymentStatus.SUCCEEDED)
        result = await self._provider.execute(
            BillingProviderIntent(
                company_id=command.company_id,
                idempotency_key=command.idempotency_key,
                kind=kind,
                amount_nok=amount_nok,
                income_year=income_year,
            )
        )
        if result.status is not status:
            raise BillingError.unavailable(BillingErrorCode.PROVIDER_OUTCOME_UNKNOWN)
        return await self._persistence.complete_provider_event(command, result, amount_nok)


def billing_entitlement_decision(
    query: BillingEntitlementQuery,
    account: BillingAccount | None,
    *,
    filing_ready: bool,
) -> BillingEntitlementDecision:
    common = {
        "company_id": query.company_id,
        "income_year": query.income_year,
        "obligation": query.obligation,
        "billing_exempt": False,
    }
    if account is None:
        return BillingEntitlementDecision(
            **common,
            status=BillingStatus.SUBSCRIPTION_REQUIRED,
            allowed=False,
            charge_allowed=False,
            readiness_allowed=False,
            message="Billing account is required before production filing.",
        )
    if account.refund_eligible:
        return BillingEntitlementDecision(
            **common,
            status=BillingStatus.REFUND_ELIGIBLE,
            allowed=False,
            charge_allowed=False,
            readiness_allowed=False,
            message="The filing package is eligible for refund after a supported failure.",
        )
    if not account.supported_case:
        return BillingEntitlementDecision(
            **common,
            status=BillingStatus.UNSUPPORTED_CASE,
            allowed=False,
            charge_allowed=False,
            readiness_allowed=False,
            message=account.no_charge_reason or "The case is outside Talli support.",
        )
    if not account.subscription_active:
        return BillingEntitlementDecision(
            **common,
            status=BillingStatus.SUBSCRIPTION_REQUIRED,
            allowed=False,
            charge_allowed=False,
            readiness_allowed=False,
            message="Active subscription is required before production filing.",
        )
    if account.filing_package_paid:
        return BillingEntitlementDecision(
            **common,
            status=BillingStatus.READY_FOR_PRODUCTION_FILING,
            allowed=True,
            charge_allowed=False,
            readiness_allowed=True,
            message="Billing and filing-package entitlement are ready.",
        )
    return BillingEntitlementDecision(
        **common,
        status=(BillingStatus.FILING_PACKAGE_REQUIRED if filing_ready else BillingStatus.ACTIVE),
        allowed=False,
        charge_allowed=filing_ready,
        readiness_allowed=True,
        message=(
            "Filing package payment is required before production filing."
            if filing_ready
            else "Filing readiness must pass before filing-package payment."
        ),
    )


__all__ = ["BillingService", "billing_entitlement_decision"]
