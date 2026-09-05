"""Authenticated billing facade with one policy path."""

from __future__ import annotations

from talli_backend.application.billing_session import AuthenticatedBillingSession
from talli_backend.modules.billing.public import (
    ActivateSubscriptionCommand,
    BillingEntitlementQuery,
    BillingError,
    BillingPaymentEvent,
    BillingPaymentProvider,
    BillingSnapshotQuery,
    CancelSubscriptionCommand,
    ConfigureBillingAccountCommand,
    ManageProductionPilotEntitlementCommand,
    MarkBillingUnsupportedCommand,
    PurchaseFilingPackageCommand,
    RefundFilingPackageCommand,
)
from talli_backend.modules.billing.service import BillingService


class BillingWorkflow:
    def __init__(
        self,
        persistence: AuthenticatedBillingSession,
        provider: BillingPaymentProvider,
    ) -> None:
        self._persistence = persistence
        self._service = BillingService(persistence, provider)

    @property
    def actor_id(self):
        return self._persistence.actor_id

    def _command(self, command):
        if command.actor_id != self.actor_id:
            raise BillingError.forbidden()
        return command

    async def configure_account(self, command: ConfigureBillingAccountCommand):
        return await self._service.configure_account(self._command(command))

    async def activate_subscription(
        self, command: ActivateSubscriptionCommand
    ) -> BillingPaymentEvent:
        return await self._service.activate_subscription(self._command(command))

    async def cancel_subscription(self, command: CancelSubscriptionCommand):
        return await self._service.cancel_subscription(self._command(command))

    async def purchase_filing_package(self, command: PurchaseFilingPackageCommand):
        return await self._service.purchase_filing_package(self._command(command))

    async def refund_filing_package(self, command: RefundFilingPackageCommand):
        return await self._service.refund_filing_package(self._command(command))

    async def mark_unsupported(self, command: MarkBillingUnsupportedCommand):
        return await self._service.mark_unsupported(self._command(command))

    async def manage_pilot_entitlement(
        self, command: ManageProductionPilotEntitlementCommand
    ):
        return await self._service.manage_pilot_entitlement(self._command(command))

    async def snapshot(self, query: BillingSnapshotQuery):
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()
        return await self._service.snapshot(query)

    async def entitlement(self, query: BillingEntitlementQuery):
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()
        return await self._service.entitlement(query)


__all__ = ["BillingWorkflow"]
