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
    BillingProviderResult,
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
    expected_payment_status,
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
        await self._persistence.authorize_owner_command(command.company_id)
        return await self._persistence.configure_account(command, _PRICING[command.pricing_plan])

    async def activate_subscription(
        self, command: ActivateSubscriptionCommand
    ) -> BillingPaymentEvent:
        await self._persistence.authorize_owner_command(command.company_id)
        account = await self._required_account(command.company_id)
        kind = BillingPaymentKind.SUBSCRIPTION
        replay = await self._payment_replay(command, kind)
        return replay or await self._payment(command, kind, account.pricing.monthly_nok)

    async def cancel_subscription(
        self, command: CancelSubscriptionCommand
    ) -> BillingPaymentEvent:
        await self._persistence.authorize_owner_command(command.company_id)
        await self._required_account(command.company_id)
        kind = BillingPaymentKind.SUBSCRIPTION_CANCELLATION
        replay = await self._payment_replay(command, kind)
        return replay or await self._payment(command, kind, 0)

    async def purchase_filing_package(
        self, command: PurchaseFilingPackageCommand
    ) -> BillingPaymentEvent:
        await self._persistence.authorize_owner_command(command.company_id)
        account = await self._required_account(command.company_id)
        kind = BillingPaymentKind.FILING_PACKAGE
        amount_nok = account.pricing.filing_package_nok
        replay = await self._payment_replay(command, kind)
        if replay is not None:
            return replay
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
            kind,
            amount_nok,
        )

    async def refund_filing_package(
        self, command: RefundFilingPackageCommand
    ) -> BillingPaymentEvent:
        await self._persistence.authorize_owner_command(command.company_id)
        account = await self._required_account(command.company_id)
        kind = BillingPaymentKind.REFUND
        amount_nok = account.pricing.filing_package_nok
        replay = await self._payment_replay(command, kind)
        if replay is not None:
            return replay
        if (
            not account.supported_case
            or not account.filing_package_paid
            or account.refund_completed
        ):
            raise BillingError.precondition(BillingErrorCode.REFUND_NOT_ALLOWED)
        return await self._payment(
            command, kind, amount_nok
        )

    async def mark_unsupported(
        self, command: MarkBillingUnsupportedCommand
    ) -> BillingAccount:
        await self._persistence.authorize_owner_command(command.company_id)
        await self._required_account(command.company_id)
        return await self._persistence.mark_unsupported(command)

    async def manage_pilot_entitlement(
        self, command: ManageProductionPilotEntitlementCommand
    ) -> ProductionPilotEntitlement:
        await self._persistence.authorize_admin_command()
        return await self._persistence.manage_pilot_entitlement(command)

    async def snapshot(self, query: BillingSnapshotQuery) -> BillingSnapshot:
        snapshot = await self._persistence.snapshot(query)
        return replace(snapshot, pricing=tuple(_PRICING.values()))

    async def entitlement(
        self, query: BillingEntitlementQuery
    ) -> BillingEntitlementDecision:
        await self._persistence.authorize_entitlement_query(query.company_id)
        if query.case_profile:
            pilot = await self._persistence.find_active_pilot_entitlement(
                company_id=query.company_id,
                user_id=query.actor_id.subject,
                income_year=query.income_year,
                obligation=query.obligation,
                case_profile=query.case_profile,
                at=self._now(),
            )
            if pilot is not None:
                ready = await self._persistence.filing_ready(
                    query.company_id, query.income_year, query.obligation
                )
                if pilot.billing_exempt:
                    if not ready:
                        return BillingEntitlementDecision(
                            company_id=query.company_id,
                            income_year=query.income_year,
                            obligation=query.obligation,
                            status=BillingStatus.ACTIVE,
                            allowed=False,
                            charge_allowed=False,
                            readiness_allowed=True,
                            billing_exempt=True,
                            message="Innsendingskontrollen må være klar før produksjonsinnsending.",
                            pilot_entitlement_id=pilot.entitlement_id,
                        )
                    return BillingEntitlementDecision(
                        company_id=query.company_id,
                        income_year=query.income_year,
                        obligation=query.obligation,
                        status=BillingStatus.PILOT_ENTITLEMENT_ACTIVE,
                        allowed=True,
                        charge_allowed=False,
                        readiness_allowed=True,
                        billing_exempt=True,
                        message="En aktiv, nøyaktig valideringsrettighet gir betalingsfritak.",
                        pilot_entitlement_id=pilot.entitlement_id,
                    )
                account = await self._persistence.find_account(query.company_id)
                return replace(
                    billing_entitlement_decision(query, account, filing_ready=ready),
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

    async def _payment_replay(
        self, command, kind: BillingPaymentKind
    ) -> BillingPaymentEvent | None:
        income_year = getattr(command, "income_year", None)
        replay = await self._persistence.find_payment_event(
            company_id=command.company_id,
            idempotency_key=command.idempotency_key,
            kind=kind,
            income_year=income_year,
        )
        if replay is not None and replay.status is not expected_payment_status(kind):
            raise BillingError.unavailable(BillingErrorCode.PROVIDER_OUTCOME_UNKNOWN)
        return replay

    async def _payment(
        self, command, kind: BillingPaymentKind, amount_nok: int
    ) -> BillingPaymentEvent:
        income_year = getattr(command, "income_year", None)
        intent = BillingProviderIntent(
            company_id=command.company_id,
            idempotency_key=command.idempotency_key,
            kind=kind,
            amount_nok=amount_nok,
            income_year=income_year,
        )
        try:
            result = await self._provider.execute(intent)
        except Exception:
            await self._persistence.complete_provider_event(
                command,
                BillingProviderResult(
                    provider=self._provider.provider,
                    provider_reference=f"quarantine_{command.idempotency_key}",
                    status=BillingPaymentStatus.FAILED,
                ),
                amount_nok,
            )
            raise BillingError.unavailable(BillingErrorCode.PROVIDER_OUTCOME_UNKNOWN)
        event = await self._persistence.complete_provider_event(command, result, amount_nok)
        if event.status is not expected_payment_status(kind):
            raise BillingError.unavailable(BillingErrorCode.PROVIDER_OUTCOME_UNKNOWN)
        return event


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
            message="Faktureringskonto kreves før produksjonsinnsending.",
        )
    if account.refund_eligible:
        return BillingEntitlementDecision(
            **common,
            status=BillingStatus.REFUND_ELIGIBLE,
            allowed=False,
            charge_allowed=False,
            readiness_allowed=False,
            message="Innsendingspakken kan refunderes etter en støttet feil.",
        )
    if not account.supported_case:
        return BillingEntitlementDecision(
            **common,
            status=BillingStatus.UNSUPPORTED_CASE,
            allowed=False,
            charge_allowed=False,
            readiness_allowed=False,
            message=account.no_charge_reason or "Saken er utenfor Talli-støtte.",
        )
    if not account.subscription_active:
        return BillingEntitlementDecision(
            **common,
            status=BillingStatus.SUBSCRIPTION_REQUIRED,
            allowed=False,
            charge_allowed=False,
            readiness_allowed=False,
            message="Aktivt abonnement kreves før produksjonsinnsending.",
        )
    if not filing_ready:
        return BillingEntitlementDecision(
            **common,
            status=BillingStatus.ACTIVE,
            allowed=False,
            charge_allowed=False,
            readiness_allowed=True,
            message="Innsendingskontrollen må være klar før innsendingspakken kan betales.",
        )
    if account.filing_package_paid:
        return BillingEntitlementDecision(
            **common,
            status=BillingStatus.READY_FOR_PRODUCTION_FILING,
            allowed=True,
            charge_allowed=False,
            readiness_allowed=True,
            message="Fakturering og innsendingsrett er klare.",
        )
    return BillingEntitlementDecision(
        **common,
        status=BillingStatus.FILING_PACKAGE_REQUIRED,
        allowed=False,
        charge_allowed=True,
        readiness_allowed=True,
        message="Innsendingspakken må betales før produksjonsinnsending.",
    )


__all__ = ["BillingService", "billing_entitlement_decision"]
