"""Verified-owner annual workflows; reads and cancellation remain provider-free."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from talli_backend.application.annual_checkout_prerequisites import unavailable_annual_checkout_prerequisites

from talli_backend.modules.billing.public import (
    AnnualAgreementCleanup,
    AnnualAgreementCleanupPersistence,
    annual_agreement_cleanup_operations,
    AnnualBillingReadPersistence,
    AnnualBillingProvider,
    AnnualCheckout,
    AnnualCheckoutPersistence,
    AnnualCheckoutPrerequisites,
    AnnualCheckoutQuery,
    AnnualCheckoutPreparation, AnnualCheckoutPreparationQuery,
    AnnualCheckoutRequestResolution,
    StartAnnualCheckoutCommand,
    annual_checkout_operations,
    AnnualBillingSnapshot,
    AnnualBillingSnapshotQuery,
    AnnualPurchaseHistoryQuery,
    AnnualPurchasePage,
    AnnualRefundRecoveryTargetsQuery, AnnualRefundRecoveryTargetPage,
    AnnualCancellationPersistence,
    AnnualRenewalCancellation,
    BillingError,
    CancelAnnualRenewalCommand,
    annual_billing_offer,
    AnnualSupportPage, AnnualSupportQuery, AnnualSupportReadPersistence,
    AnnualRefundRecovery, AnnualRefundRecoveryPersistence, AnnualRefundRecoveryQuery,
    annual_refund_recovery_operations,
)
from talli_backend.shared.kernel import ActorId, CompanyId, IncomeYear


class AuthenticatedAnnualBillingSession(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    @property
    def reads(self) -> AnnualBillingReadPersistence: ...

    @property
    def cancellation(self) -> AnnualCancellationPersistence: ...

    @property
    def checkout(self) -> AnnualCheckoutPersistence: ...

    @property
    def cleanup(self) -> AnnualAgreementCleanupPersistence: ...

    @property
    def support_reads(self) -> AnnualSupportReadPersistence: ...

    @property
    def refund_recovery(self) -> AnnualRefundRecoveryPersistence: ...


class AnnualBillingSessionFactory(Protocol):
    async def session(self, access_token: str) -> AuthenticatedAnnualBillingSession: ...


class AnnualSupportWorkflow:
    def __init__(self, session: AuthenticatedAnnualBillingSession):
        if session.actor_id != session.support_reads.actor_id:
            raise BillingError.forbidden()
        self._reads = session.support_reads

    @property
    def actor_id(self) -> ActorId:
        return self._reads.actor_id

    async def purchases(self, query: AnnualSupportQuery) -> AnnualSupportPage:
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()
        page = await self._reads.read_support_purchases(query)
        if (len(page.purchases)>50
                or any(value.company_id != query.company_id for value in page.purchases)
                or (page.next_purchase_id is not None and
                    (not page.purchases or page.next_purchase_id != page.purchases[-1].purchase_id))):
            raise BillingError.unavailable()
        return page


class AnnualBillingWorkflow:
    def __init__(self, session: AuthenticatedAnnualBillingSession):
        if session.actor_id != session.reads.actor_id or session.actor_id != session.cancellation.actor_id:
            raise BillingError.forbidden()
        self._session = session

    @property
    def actor_id(self):
        return self._session.actor_id

    async def snapshot(self, query: AnnualBillingSnapshotQuery) -> AnnualBillingSnapshot:
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()
        purchases = await self._session.reads.read_purchases(query)
        if (
            len(purchases.purchases) > 50
            or any(
                value.company_id != query.company_id or value.income_year != query.income_year
                for value in purchases.purchases
            )
            or (
                purchases.next_purchase_id is not None
                and (
                    not purchases.purchases
                    or purchases.next_purchase_id != purchases.purchases[-1].purchase_id
                )
            )
        ):
            raise BillingError.unavailable()
        return AnnualBillingSnapshot(annual_billing_offer(query.company_id, query.income_year), purchases)

    async def purchase_history(self, query: AnnualPurchaseHistoryQuery) -> AnnualPurchasePage:
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()
        page = await self._session.reads.read_purchase_history(query)
        if (len(page.purchases) > 50
                or any(value.company_id != query.company_id for value in page.purchases)
                or (page.next_purchase_id is not None and
                    (not page.purchases or page.next_purchase_id != page.purchases[-1].purchase_id))):
            raise BillingError.unavailable()
        return page

    async def cancel_renewal(self, command: CancelAnnualRenewalCommand) -> AnnualRenewalCancellation:
        if command.actor_id != self.actor_id:
            raise BillingError.forbidden()
        return await self._session.cancellation.cancel_renewal(command)

    async def refund_recovery_targets(
        self, query: AnnualRefundRecoveryTargetsQuery,
    ) -> AnnualRefundRecoveryTargetPage:
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()
        page = await self._session.reads.read_refund_recovery_targets(query)
        if (page.company_id != query.company_id or page.purchase_id != query.purchase_id
                or len(page.targets) > 50
                or len({value.refund_request_id for value in page.targets}) != len(page.targets)
                or (page.next_refund_request_id is not None and
                    (not page.targets or page.next_refund_request_id != page.targets[-1].refund_request_id))):
            raise BillingError.unavailable()
        return page


AnnualCheckoutPrerequisiteResolver = Callable[
    [CompanyId, IncomeYear, ActorId], Awaitable[AnnualCheckoutPrerequisites]
]


class AnnualAgreementCleanupWorkflow:
    """Use current owner authority to recover a previously recorded renewal stop."""

    def __init__(
        self, session: AuthenticatedAnnualBillingSession, provider: AnnualBillingProvider | None,
    ):
        if session.actor_id != session.cleanup.actor_id:
            raise BillingError.forbidden()
        self._session = session
        self._operations = annual_agreement_cleanup_operations(session.cleanup, provider)

    @property
    def actor_id(self) -> ActorId:
        return self._session.actor_id

    async def cleanup(self, query: AnnualCheckoutQuery) -> AnnualAgreementCleanup | None:
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()
        return await self._operations.cleanup(query)


class AnnualCheckoutWorkflow:
    """Authenticate once; billing owns all checkout and recovery decisions."""

    def __init__(
        self, session: AuthenticatedAnnualBillingSession,
        provider: AnnualBillingProvider | None,
        prerequisites: AnnualCheckoutPrerequisiteResolver | None = None,
    ):
        if session.actor_id != session.checkout.actor_id:
            raise BillingError.forbidden()
        self._session = session
        self._provider = provider
        self._prerequisites = prerequisites

    @property
    def actor_id(self) -> ActorId:
        return self._session.actor_id

    def _operations(self, company_id: CompanyId):
        # Server-owned destinations preserve company selection. Never accept
        # redirect URLs, merchant identity or authority facts from the browser.
        destination = f"https://talli.no/billing?companyId={company_id}"
        return annual_checkout_operations(
            self._session.checkout, self._provider,
            return_url=destination, management_url=destination,
        )

    async def start_checkout(self, command: StartAnnualCheckoutCommand) -> AnnualCheckout:
        if command.actor_id != self.actor_id:
            raise BillingError.forbidden()

        return await self._operations(command.company_id).start_checkout(
            command, self._deferred_prerequisites(command.company_id, command.income_year),
        )

    def _deferred_prerequisites(self, company_id: CompanyId, income_year: IncomeYear):
        async def prerequisites():
            if self._prerequisites is None:
                return await unavailable_annual_checkout_prerequisites()
            return await self._prerequisites(company_id, income_year, self.actor_id)
        return prerequisites

    async def prepare_checkout(self, query: AnnualCheckoutPreparationQuery) -> AnnualCheckoutPreparation:
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()

        return await self._operations(query.company_id).prepare_checkout(
            query, self._deferred_prerequisites(query.company_id, query.income_year),
        )

    async def withdraw_checkout_request(
        self, command: StartAnnualCheckoutCommand,
    ) -> AnnualCheckoutRequestResolution:
        if command.actor_id != self.actor_id:
            raise BillingError.forbidden()
        return await self._operations(command.company_id).withdraw_checkout_request(command)

    async def observe_checkout(self, query: AnnualCheckoutQuery) -> AnnualCheckout:
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()
        return await self._operations(query.company_id).poll_checkout(query)


class AnnualRefundRecoveryWorkflow:
    """Reconcile one persisted request under its current owner's session."""

    def __init__(self, session: AuthenticatedAnnualBillingSession, provider: AnnualBillingProvider | None):
        if session.actor_id != session.refund_recovery.actor_id:
            raise BillingError.forbidden()
        self._actor_id = session.actor_id
        self._operations = annual_refund_recovery_operations(session.refund_recovery, provider)

    @property
    def actor_id(self) -> ActorId:
        return self._actor_id

    async def recover_refund(self, query: AnnualRefundRecoveryQuery) -> AnnualRefundRecovery:
        if query.actor_id != self.actor_id:
            raise BillingError.forbidden()
        return await self._operations.recover_refund(query)
