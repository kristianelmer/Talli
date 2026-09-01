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
    InvestmentActivityPage,
    InvestmentCorrectionPage,
    InvestmentPositionPage,
    ShareSaleAllocationPage,
    AccountingEntryReference,
    CorrectInvestmentCommand,
    InvestmentAccountingClassification,
    InvestmentsError,
    RecordReceivedDividendCommand,
    RecordReceivedFundDistributionCommand,
    RecordSharePurchaseCommand,
    RecordShareSaleCommand,
    RecordedSharePurchase,
    RecordedShareSale,
    RecordedReceivedDividend,
    RecordedReceivedFundDistribution,
    RecordedInvestmentCorrection,
)
from talli_backend.modules.investments.service import InvestmentsService
from talli_backend.modules.ledger.public import (
    InvestmentClassification,
    LedgerCommands,
    LedgerPersistence,
    LedgerSourceRecordId,
    PostInvestmentPurchaseCommand,
    PostInvestmentSaleCommand,
    PostReceivedDividendCommand,
    PostReceivedFundDistributionCommand,
)
from talli_backend.shared.kernel import CompanyId, CorrelationId


LedgerFacadeFactory = Callable[[LedgerPersistence], LedgerCommands]

_LEDGER_CLASSIFICATION = {
    InvestmentAccountingClassification.SUBSIDIARY: InvestmentClassification.SUBSIDIARY,
    InvestmentAccountingClassification.ASSOCIATE: InvestmentClassification.ASSOCIATE,
    InvestmentAccountingClassification.OTHER_LONG_TERM: InvestmentClassification.OTHER_LONG_TERM,
    InvestmentAccountingClassification.CURRENT_LISTED_SHARE: InvestmentClassification.CURRENT_LISTED_SHARE,
    InvestmentAccountingClassification.CURRENT_FUND: InvestmentClassification.CURRENT_FUND,
}


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

    async def correct_investment(
        self, command: CorrectInvestmentCommand
    ) -> RecordedInvestmentCorrection:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            investments = InvestmentsService(transaction)
            replay = await investments.get_investment_correction_replay(command)
            if replay is not None:
                return replay
            prepared = await investments.prepare_investment_correction(command)
            replacement = await self._record_replacement(
                transaction,
                command.replacement,
            )
            return await investments.complete_investment_correction(
                command,
                prepared=prepared,
                replacement=replacement,
            )

    async def _record_replacement(self, transaction, command):
        investments = InvestmentsService(transaction)
        ledger = self._ledger_facade_factory(transaction)
        if isinstance(command, RecordSharePurchaseCommand):
            prepared = await investments.prepare_share_purchase(command)
            posted = await ledger.post_investment_purchase(
                PostInvestmentPurchaseCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    action_id=LedgerSourceRecordId(str(command.action_id)),
                    investment_name=prepared.investment_name,
                    classification=_LEDGER_CLASSIFICATION[
                        prepared.accounting_classification
                    ],
                    purchase_amount=prepared.purchase_amount,
                )
            )
            return await investments.complete_share_purchase(
                command,
                prepared=prepared,
                accounting_entry_id=AccountingEntryReference(str(posted.entry_id)),
            )
        if isinstance(command, RecordShareSaleCommand):
            prepared = await investments.prepare_share_sale(command)
            posted = await ledger.post_investment_sale(
                PostInvestmentSaleCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    action_id=LedgerSourceRecordId(str(command.action_id)),
                    investment_name=prepared.investment_name,
                    classification=_LEDGER_CLASSIFICATION[
                        prepared.accounting_classification
                    ],
                    proceeds=prepared.net_proceeds,
                    fifo_cost_basis_reduction=prepared.fifo_cost_basis_reduction,
                )
            )
            return await investments.complete_share_sale(
                command,
                prepared=prepared,
                accounting_entry_id=AccountingEntryReference(str(posted.entry_id)),
            )
        if isinstance(command, RecordReceivedDividendCommand):
            prepared = await investments.prepare_received_dividend(command)
            posted = await ledger.post_received_dividend(
                PostReceivedDividendCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    action_id=LedgerSourceRecordId(str(command.action_id)),
                    paying_company_name=prepared.paying_company_name,
                    gross_amount=command.gross_amount,
                )
            )
            return await investments.complete_received_dividend(
                command,
                prepared=prepared,
                accounting_entry_id=AccountingEntryReference(str(posted.entry_id)),
            )
        if isinstance(command, RecordReceivedFundDistributionCommand):
            prepared = await investments.prepare_received_fund_distribution(command)
            posted = await ledger.post_received_fund_distribution(
                PostReceivedFundDistributionCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    action_id=LedgerSourceRecordId(str(command.action_id)),
                    fund_name=prepared.fund_name,
                    gross_amount=command.gross_amount,
                    dividend_portion=prepared.dividend_portion,
                    interest_portion=prepared.interest_portion,
                )
            )
            return await investments.complete_received_fund_distribution(
                command,
                prepared=prepared,
                accounting_entry_id=AccountingEntryReference(str(posted.entry_id)),
            )
        raise InvestmentsError.invalid_input()

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
                    classification=_LEDGER_CLASSIFICATION[
                        prepared.accounting_classification
                    ],
                    purchase_amount=prepared.purchase_amount,
                )
            )
            return await investments.complete_share_purchase(
                command,
                prepared=prepared,
                accounting_entry_id=AccountingEntryReference(str(posted.entry_id)),
            )

    async def record_received_dividend(
        self, command: RecordReceivedDividendCommand
    ) -> RecordedReceivedDividend:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            investments = InvestmentsService(transaction)
            replay = await investments.get_received_dividend_replay(command)
            if replay is not None:
                return replay
            prepared = await investments.prepare_received_dividend(command)
            posted = await self._ledger_facade_factory(
                transaction
            ).post_received_dividend(
                PostReceivedDividendCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    action_id=LedgerSourceRecordId(str(command.action_id)),
                    paying_company_name=prepared.paying_company_name,
                    gross_amount=command.gross_amount,
                )
            )
            return await investments.complete_received_dividend(
                command,
                prepared=prepared,
                accounting_entry_id=AccountingEntryReference(str(posted.entry_id)),
            )

    async def record_received_fund_distribution(
        self, command: RecordReceivedFundDistributionCommand
    ) -> RecordedReceivedFundDistribution:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            investments = InvestmentsService(transaction)
            replay = await investments.get_received_fund_distribution_replay(command)
            if replay is not None:
                return replay
            prepared = await investments.prepare_received_fund_distribution(command)
            posted = await self._ledger_facade_factory(
                transaction
            ).post_received_fund_distribution(
                PostReceivedFundDistributionCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    action_id=LedgerSourceRecordId(str(command.action_id)),
                    fund_name=prepared.fund_name,
                    gross_amount=command.gross_amount,
                    dividend_portion=prepared.dividend_portion,
                    interest_portion=prepared.interest_portion,
                )
            )
            return await investments.complete_received_fund_distribution(
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
                    classification=_LEDGER_CLASSIFICATION[
                        prepared.accounting_classification
                    ],
                    proceeds=prepared.net_proceeds,
                    fifo_cost_basis_reduction=prepared.fifo_cost_basis_reduction,
                )
            )
            return await investments.complete_share_sale(
                command,
                prepared=prepared,
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

    async def list_activity(
        self,
        *,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> InvestmentActivityPage:
        return await self._persistence.list_activity(
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

    async def list_share_sale_allocations(
        self,
        *,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> ShareSaleAllocationPage:
        return await self._persistence.list_share_sale_allocations(
            actor_id=self.actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )

    async def list_corrections(
        self,
        *,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> InvestmentCorrectionPage:
        return await self._persistence.list_corrections(
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
