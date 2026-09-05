"""Authenticated annual reads and local cancellation, with no provider dependency."""

from typing import Protocol

from talli_backend.modules.billing.public import (
    AnnualBillingReadPersistence,
    AnnualBillingSnapshot,
    AnnualBillingSnapshotQuery,
    AnnualCancellationPersistence,
    AnnualRenewalCancellation,
    BillingError,
    CancelAnnualRenewalCommand,
    annual_billing_offer,
)
from talli_backend.shared.kernel import ActorId


class AuthenticatedAnnualBillingSession(Protocol):
    @property
    def actor_id(self) -> ActorId: ...

    @property
    def reads(self) -> AnnualBillingReadPersistence: ...

    @property
    def cancellation(self) -> AnnualCancellationPersistence: ...


class AnnualBillingSessionFactory(Protocol):
    async def session(self, access_token: str) -> AuthenticatedAnnualBillingSession: ...


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

    async def cancel_renewal(self, command: CancelAnnualRenewalCommand) -> AnnualRenewalCancellation:
        if command.actor_id != self.actor_id:
            raise BillingError.forbidden()
        return await self._session.cancellation.cancel_renewal(command)
