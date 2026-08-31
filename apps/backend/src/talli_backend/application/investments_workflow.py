"""Authenticated investments workflows and atomic ledger composition."""

from __future__ import annotations

from collections.abc import Callable

from talli_backend.application.investments_session import (
    AuthenticatedInvestmentsSession,
    InvestmentsSessionFactory,
)
from talli_backend.modules.investments.public import (
    AcquisitionLotPage,
    InvestmentCursor,
    InvestmentPositionPage,
    AccountingEntryReference,
    InvestmentsError,
    RecordSharePurchaseCommand,
    RecordShareSaleCommand,
    RecordedSharePurchase,
    RecordedShareSale,
)
from talli_backend.modules.investments.service import InvestmentsService
from talli_backend.modules.ledger.public import (
    LedgerCommands,
    LedgerPersistence,
    LedgerSourceRecordId,
    PostInvestmentPurchaseCommand,
    PostInvestmentSaleCommand,
)
from talli_backend.shared.kernel import CompanyId, CorrelationId


LedgerFacadeFactory = Callable[[LedgerPersistence], LedgerCommands]


class InvestmentsSession:
    def __init__(
        self,
        persistence: AuthenticatedInvestmentsSession,
        ledger_facade_factory: LedgerFacadeFactory,
    ) -> None:
        self._persistence = persistence
        self._ledger_facade_factory = ledger_facade_factory

    @property
    def actor_id(self):
        return self._persistence.actor_id

    async def record_share_purchase(
        self, command: RecordSharePurchaseCommand
    ) -> RecordedSharePurchase:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            investments = InvestmentsService(transaction)
            replay = await investments.get_share_purchase_replay(command)
            if replay is not None:
                return replay
            prepared = await investments.prepare_share_purchase(command)
            posted = await self._ledger_facade_factory(
                transaction
            ).post_investment_purchase(
                PostInvestmentPurchaseCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    action_id=LedgerSourceRecordId(str(command.action_id)),
                    investment_name=prepared.investment_name,
                    purchase_amount=prepared.purchase_amount,
                )
            )
            return await investments.complete_share_purchase(
                command,
                prepared=prepared,
                accounting_entry_id=AccountingEntryReference(str(posted.entry_id)),
            )

    async def record_share_sale(
        self, command: RecordShareSaleCommand
    ) -> RecordedShareSale:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            investments = InvestmentsService(transaction)
            replay = await investments.get_share_sale_replay(command)
            if replay is not None:
                return replay
            prepared = await investments.prepare_share_sale(command)
            posted = await self._ledger_facade_factory(
                transaction
            ).post_investment_sale(
                PostInvestmentSaleCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    action_id=LedgerSourceRecordId(str(command.action_id)),
                    investment_name=prepared.investment_name,
                    proceeds=command.proceeds,
                    fifo_cost_basis_reduction=prepared.fifo_cost_basis_reduction,
                )
            )
            return await investments.complete_share_sale(
                command,
                accounting_entry_id=AccountingEntryReference(str(posted.entry_id)),
            )

    async def list_positions(
        self,
        *,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> InvestmentPositionPage:
        return await self._persistence.list_positions(
            actor_id=self.actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )

    async def list_acquisition_lots(
        self,
        *,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> AcquisitionLotPage:
        return await self._persistence.list_acquisition_lots(
            actor_id=self.actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )


class InvestmentsApplication:
    def __init__(
        self,
        sessions: InvestmentsSessionFactory,
        ledger_facade_factory: LedgerFacadeFactory,
    ) -> None:
        self._sessions = sessions
        self._ledger_facade_factory = ledger_facade_factory

    async def session(self, access_token: str) -> InvestmentsSession:
        return InvestmentsSession(
            await self._sessions.session(access_token),
            self._ledger_facade_factory,
        )


__all__ = ["InvestmentsApplication", "InvestmentsSession", "LedgerFacadeFactory"]
