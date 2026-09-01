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
    InvestmentFactReference,
    InvestmentSettlementBalanceKind,
    InvestmentSourceCapability,
    InvestmentsError,
    RecordReceivedDividendCommand,
    RecordReceivedFundDistributionCommand,
    RecordSharePurchaseCommand,
    RecordShareSaleCommand,
    RecognizeReceivedDividendCommand,
    RecognizeReceivedFundDistributionCommand,
    RecognizeSharePurchaseCommand,
    RecognizeShareSaleCommand,
    RecordedInvestmentCashSettlement,
    RecordedInvestmentEconomicEvent,
    RecordedSharePurchase,
    RecordedShareSale,
    RecordedReceivedDividend,
    RecordedReceivedFundDistribution,
    RecordedInvestmentCorrection,
    SettleInvestmentCashCommand,
)
from talli_backend.modules.investments.service import InvestmentsService
from talli_backend.modules.ledger.public import (
    InvestmentClassification,
    InvestmentCashSettlementFacts,
    InvestmentDividendFacts,
    InvestmentDividendPhase,
    InvestmentFundDistributionRecognitionFacts,
    InvestmentPurchaseRecognitionFacts,
    InvestmentSaleRecognitionFacts,
    InvestmentSettlementKind,
    LedgerEntryId,
    LedgerFactReference,
    LedgerCommands,
    LedgerPersistence,
    LedgerSourceRecordId,
    LedgerSourceCapability,
    PostInvestmentPurchaseCommand,
    PostInvestmentSaleCommand,
    PostReceivedDividendCommand,
    PostReceivedFundDistributionCommand,
    RecognizeHoldingActionCommand,
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

_LEDGER_SOURCE_CAPABILITY = {
    InvestmentSourceCapability.BANKING: LedgerSourceCapability.BANKING,
    InvestmentSourceCapability.DOCUMENTS: LedgerSourceCapability.DOCUMENTS,
}

_LEDGER_SETTLEMENT_KIND = {
    InvestmentSettlementBalanceKind.PURCHASE_PAYABLE: (
        InvestmentSettlementKind.PURCHASE_PAYABLE
    ),
    InvestmentSettlementBalanceKind.SALE_RECEIVABLE: (
        InvestmentSettlementKind.SALE_RECEIVABLE
    ),
    InvestmentSettlementBalanceKind.DIVIDEND_RECEIVABLE: (
        InvestmentSettlementKind.DIVIDEND_RECEIVABLE
    ),
    InvestmentSettlementBalanceKind.FUND_DISTRIBUTION_RECEIVABLE: (
        InvestmentSettlementKind.FUND_DISTRIBUTION_RECEIVABLE
    ),
}


def _ledger_fact(reference: InvestmentFactReference) -> LedgerFactReference:
    return LedgerFactReference(
        capability=_LEDGER_SOURCE_CAPABILITY[reference.capability],
        record_id=LedgerSourceRecordId(str(reference.record_id)),
        revision=reference.revision,
        fact_sha256=reference.fact_sha256,
    )


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

    async def recognize_share_purchase(
        self, command: RecognizeSharePurchaseCommand
    ) -> RecordedInvestmentEconomicEvent:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            investments = InvestmentsService(transaction)
            replay = await investments.get_share_purchase_recognition_replay(command)
            if replay is not None:
                return replay
            prepared = await investments.prepare_share_purchase_recognition(command)
            posted = await self._ledger_facade_factory(
                transaction
            ).recognize_holding_action(
                RecognizeHoldingActionCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    event_date=command.acquisition_date,
                    primary_source=LedgerFactReference(
                        capability=LedgerSourceCapability.INVESTMENTS,
                        record_id=LedgerSourceRecordId(str(command.event_id)),
                        revision=1,
                        fact_sha256=prepared.calculation_id,
                    ),
                    corroborating_sources=tuple(
                        _ledger_fact(fact) for fact in command.evidence.document_facts
                    ),
                    facts=InvestmentPurchaseRecognitionFacts(
                        investment_name=prepared.investment_name,
                        classification=_LEDGER_CLASSIFICATION[
                            prepared.accounting_classification
                        ],
                        acquisition_cost=prepared.acquisition_cost,
                    ),
                )
            )
            return await investments.complete_share_purchase_recognition(
                command,
                prepared=prepared,
                accounting_entry_id=AccountingEntryReference(str(posted.entry_id)),
            )

    async def settle_investment_cash(
        self, command: SettleInvestmentCashCommand
    ) -> RecordedInvestmentCashSettlement:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            investments = InvestmentsService(transaction)
            replay = await investments.get_cash_settlement_replay(command)
            if replay is not None:
                return replay
            prepared = await investments.prepare_cash_settlement(command)
            bank_fact = command.evidence.bank_fact
            if bank_fact is None:
                raise InvestmentsError.invalid_input()
            posted = await self._ledger_facade_factory(
                transaction
            ).recognize_holding_action(
                RecognizeHoldingActionCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    event_date=command.settlement_date,
                    primary_source=LedgerFactReference(
                        capability=LedgerSourceCapability.INVESTMENTS,
                        record_id=LedgerSourceRecordId(str(command.settlement_id)),
                        revision=1,
                        fact_sha256=prepared.event_fact_sha256,
                    ),
                    corroborating_sources=(_ledger_fact(bank_fact),),
                    facts=InvestmentCashSettlementFacts(
                        kind=_LEDGER_SETTLEMENT_KIND[
                            prepared.settlement_balance_kind
                        ],
                        amount=prepared.amount,
                        recognition_entry_id=LedgerEntryId(
                            str(prepared.recognition_accounting_entry_id)
                        ),
                    ),
                )
            )
            return await investments.complete_cash_settlement(
                command,
                prepared=prepared,
                accounting_entry_id=AccountingEntryReference(str(posted.entry_id)),
            )

    async def recognize_share_sale(
        self, command: RecognizeShareSaleCommand
    ) -> RecordedInvestmentEconomicEvent:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            investments = InvestmentsService(transaction)
            replay = await investments.get_share_sale_recognition_replay(command)
            if replay is not None:
                return replay
            prepared = await investments.prepare_share_sale_recognition(command)
            posted = await self._ledger_facade_factory(
                transaction
            ).recognize_holding_action(
                RecognizeHoldingActionCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    event_date=command.sale_date,
                    primary_source=LedgerFactReference(
                        capability=LedgerSourceCapability.INVESTMENTS,
                        record_id=LedgerSourceRecordId(str(command.event_id)),
                        revision=1,
                        fact_sha256=prepared.calculation_id,
                    ),
                    corroborating_sources=tuple(
                        _ledger_fact(fact) for fact in command.evidence.document_facts
                    ),
                    facts=InvestmentSaleRecognitionFacts(
                        investment_name=prepared.investment_name,
                        classification=_LEDGER_CLASSIFICATION[
                            prepared.accounting_classification
                        ],
                        net_proceeds=prepared.net_proceeds,
                        carrying_amount=prepared.fifo_cost_basis_reduction,
                    ),
                )
            )
            return await investments.complete_share_sale_recognition(
                command,
                prepared=prepared,
                accounting_entry_id=AccountingEntryReference(str(posted.entry_id)),
            )

    async def recognize_received_dividend(
        self, command: RecognizeReceivedDividendCommand
    ) -> RecordedInvestmentEconomicEvent:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            investments = InvestmentsService(transaction)
            replay = await (
                investments.get_received_dividend_recognition_replay(command)
            )
            if replay is not None:
                return replay
            prepared = await investments.prepare_received_dividend_recognition(
                command
            )
            posted = await self._ledger_facade_factory(
                transaction
            ).recognize_holding_action(
                RecognizeHoldingActionCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    event_date=command.declared_date,
                    primary_source=LedgerFactReference(
                        capability=LedgerSourceCapability.INVESTMENTS,
                        record_id=LedgerSourceRecordId(str(command.event_id)),
                        revision=1,
                        fact_sha256=prepared.calculation_id,
                    ),
                    corroborating_sources=tuple(
                        _ledger_fact(fact) for fact in command.evidence.document_facts
                    ),
                    facts=InvestmentDividendFacts(
                        phase=InvestmentDividendPhase.FINAL_DECISION,
                        gross_amount=command.gross_amount,
                    ),
                )
            )
            return await investments.complete_received_dividend_recognition(
                command,
                prepared=prepared,
                accounting_entry_id=AccountingEntryReference(str(posted.entry_id)),
            )

    async def recognize_received_fund_distribution(
        self, command: RecognizeReceivedFundDistributionCommand
    ) -> RecordedInvestmentEconomicEvent:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            investments = InvestmentsService(transaction)
            replay = await (
                investments.get_received_fund_distribution_recognition_replay(
                    command
                )
            )
            if replay is not None:
                return replay
            prepared = await (
                investments.prepare_received_fund_distribution_recognition(
                    command
                )
            )
            posted = await self._ledger_facade_factory(
                transaction
            ).recognize_holding_action(
                RecognizeHoldingActionCommand(
                    company_id=command.company_id,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    idempotency_key=command.idempotency_key,
                    income_year=command.income_year,
                    event_date=command.entitlement_date,
                    primary_source=LedgerFactReference(
                        capability=LedgerSourceCapability.INVESTMENTS,
                        record_id=LedgerSourceRecordId(str(command.event_id)),
                        revision=1,
                        fact_sha256=prepared.calculation_id,
                    ),
                    corroborating_sources=tuple(
                        _ledger_fact(fact) for fact in command.evidence.document_facts
                    ),
                    facts=InvestmentFundDistributionRecognitionFacts(
                        fund_name=prepared.fund_name,
                        gross_amount=command.gross_amount,
                        dividend_portion=prepared.dividend_portion,
                        interest_portion=prepared.interest_portion,
                    ),
                )
            )
            return await (
                investments.complete_received_fund_distribution_recognition(
                    command,
                    prepared=prepared,
                    accounting_entry_id=AccountingEntryReference(
                        str(posted.entry_id)
                    ),
                )
            )

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
