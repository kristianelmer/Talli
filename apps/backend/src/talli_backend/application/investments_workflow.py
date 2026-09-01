"""Authenticated investments workflows and atomic ledger composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from talli_backend.modules.banking.public import (
    AccountingEntryReference as BankingAccountingEntryReference,
    BankTransactionId,
    ClaimBankTransactionForExternalActionCommand,
    ExternalActionReference,
)
from talli_backend.application.investments_session import (
    AuthenticatedInvestmentsSession,
    InvestmentsSessionFactory,
)
from talli_backend.modules.investments.public import (
    AcquisitionLotPage,
    InvestmentCursor,
    InvestmentActivityPage,
    InvestmentCorrectionPage,
    InvestmentLifecycleEventPage,
    InvestmentPositionPage,
    InvestmentYearEndMeasurementPage,
    ShareSaleAllocationPage,
    AccountingEntryReference,
    CorrectInvestmentCommand,
    InvestmentAccountingClassification,
    InvestmentCorrectionTargetKind,
    InvestmentFactReference,
    InvestmentSettlementBalanceKind,
    InvestmentSourceCapability,
    InvestmentsError,
    RecognizeReceivedDividendCommand,
    RecognizeReceivedFundDistributionCommand,
    RecognizeSharePurchaseCommand,
    RecognizeShareSaleCommand,
    RecordedInvestmentCashSettlement,
    RecordedInvestmentEconomicEvent,
    RecordedInvestmentCorrection,
    RecordedInvestmentYearEndMeasurement,
    PreparedCashSettlementCorrection,
    PreparedInvestmentCashSettlement,
    PreparedInvestmentYearEndMeasurement,
    RecordInvestmentYearEndMeasurementCommand,
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
    InvestmentYearEndMeasurementFacts,
    InvestmentSettlementKind,
    LedgerEntryId,
    LedgerFactReference,
    LedgerCommands,
    LedgerPersistence,
    LedgerSourceRecordId,
    LedgerSourceCapability,
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
            return await self._recognize_in_transaction(transaction, command)

    async def settle_investment_cash(
        self, command: SettleInvestmentCashCommand
    ) -> RecordedInvestmentCashSettlement:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            return await self._settle_in_transaction(transaction, command)

    async def record_year_end_measurement(
        self, command: RecordInvestmentYearEndMeasurementCommand
    ) -> RecordedInvestmentYearEndMeasurement:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            investments = InvestmentsService(transaction)
            replay = await investments.get_year_end_measurement_replay(command)
            if replay is not None:
                return replay
            prepared = await investments.prepare_year_end_measurement(command)
            entry_id = await self._post_year_end_measurement_entry(
                transaction, command, prepared
            )
            return await investments.complete_year_end_measurement(
                command,
                prepared=prepared,
                accounting_entry_id=entry_id,
            )

    async def _post_year_end_measurement_entry(
        self,
        transaction,
        command: RecordInvestmentYearEndMeasurementCommand,
        prepared: PreparedInvestmentYearEndMeasurement,
    ) -> AccountingEntryReference | None:
        if prepared.impairment_amount.amount == 0:
            return None
        posted = await self._ledger_facade_factory(
            transaction
        ).recognize_holding_action(
            RecognizeHoldingActionCommand(
                company_id=command.company_id,
                actor_id=command.actor_id,
                correlation_id=command.correlation_id,
                idempotency_key=command.idempotency_key,
                income_year=command.income_year,
                event_date=command.as_of,
                primary_source=LedgerFactReference(
                    capability=LedgerSourceCapability.INVESTMENTS,
                    record_id=LedgerSourceRecordId(str(command.measurement_id)),
                    revision=1,
                    fact_sha256=prepared.calculation_id,
                ),
                corroborating_sources=tuple(
                    _ledger_fact(fact) for fact in command.evidence.document_facts
                ),
                facts=InvestmentYearEndMeasurementFacts(
                    investment_name=prepared.investment_name,
                    classification=_LEDGER_CLASSIFICATION[
                        prepared.accounting_classification
                    ],
                    pre_measurement_book_value=prepared.pre_measurement_book_value,
                    closing_book_value=prepared.closing_book_value,
                ),
            )
        )
        return AccountingEntryReference(str(posted.entry_id))

    async def record_compatibility_action(
        self,
        recognition,
        settlement: SettleInvestmentCashCommand | None,
    ) -> tuple[
        RecordedInvestmentEconomicEvent,
        RecordedInvestmentCashSettlement | None,
    ]:
        if recognition.actor_id != self._persistence.actor_id or (
            settlement is not None
            and settlement.actor_id != self._persistence.actor_id
        ):
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            event = await self._recognize_in_transaction(transaction, recognition)
            cash = (
                await self._settle_in_transaction(transaction, settlement)
                if settlement is not None
                else None
            )
            return event, cash

    async def _settle_in_transaction(
        self,
        transaction,
        command: SettleInvestmentCashCommand,
    ) -> RecordedInvestmentCashSettlement:
        investments = InvestmentsService(transaction)
        replay = await investments.get_cash_settlement_replay(command)
        if replay is not None:
            return replay
        prepared = await investments.prepare_cash_settlement(command)
        replacement_entry_id = await self._post_cash_settlement_entry(
            transaction, command, prepared
        )
        await self._claim_bank_fact(
            transaction, command, prepared, replacement_entry_id
        )
        return await investments.complete_cash_settlement(
            command,
            prepared=prepared,
            accounting_entry_id=replacement_entry_id,
        )

    async def recognize_share_sale(
        self, command: RecognizeShareSaleCommand
    ) -> RecordedInvestmentEconomicEvent:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            return await self._recognize_in_transaction(transaction, command)

    async def recognize_received_dividend(
        self, command: RecognizeReceivedDividendCommand
    ) -> RecordedInvestmentEconomicEvent:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            return await self._recognize_in_transaction(transaction, command)

    async def recognize_received_fund_distribution(
        self, command: RecognizeReceivedFundDistributionCommand
    ) -> RecordedInvestmentEconomicEvent:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            return await self._recognize_in_transaction(transaction, command)

    async def _recognize_in_transaction(self, transaction, command):
        investments = InvestmentsService(transaction)
        if isinstance(command, RecognizeSharePurchaseCommand):
            replay = await investments.get_share_purchase_recognition_replay(command)
            if replay is not None:
                return replay
            prepared = await investments.prepare_share_purchase_recognition(command)
            event_date = command.acquisition_date
            facts = InvestmentPurchaseRecognitionFacts(
                investment_name=prepared.investment_name,
                classification=_LEDGER_CLASSIFICATION[
                    prepared.accounting_classification
                ],
                acquisition_cost=prepared.acquisition_cost,
            )
            complete = investments.complete_share_purchase_recognition
        elif isinstance(command, RecognizeShareSaleCommand):
            replay = await investments.get_share_sale_recognition_replay(command)
            if replay is not None:
                return replay
            prepared = await investments.prepare_share_sale_recognition(command)
            event_date = command.sale_date
            facts = InvestmentSaleRecognitionFacts(
                investment_name=prepared.investment_name,
                classification=_LEDGER_CLASSIFICATION[
                    prepared.accounting_classification
                ],
                net_proceeds=prepared.net_proceeds,
                carrying_amount=prepared.fifo_cost_basis_reduction,
            )
            complete = investments.complete_share_sale_recognition
        elif isinstance(command, RecognizeReceivedDividendCommand):
            replay = await investments.get_received_dividend_recognition_replay(
                command
            )
            if replay is not None:
                return replay
            prepared = await investments.prepare_received_dividend_recognition(
                command
            )
            event_date = command.declared_date
            facts = InvestmentDividendFacts(
                phase=InvestmentDividendPhase.FINAL_DECISION,
                gross_amount=command.gross_amount,
            )
            complete = investments.complete_received_dividend_recognition
        elif isinstance(command, RecognizeReceivedFundDistributionCommand):
            replay = await (
                investments.get_received_fund_distribution_recognition_replay(
                    command
                )
            )
            if replay is not None:
                return replay
            prepared = await (
                investments.prepare_received_fund_distribution_recognition(command)
            )
            event_date = command.entitlement_date
            facts = InvestmentFundDistributionRecognitionFacts(
                fund_name=prepared.fund_name,
                gross_amount=command.gross_amount,
                dividend_portion=prepared.dividend_portion,
                interest_portion=prepared.interest_portion,
            )
            complete = investments.complete_received_fund_distribution_recognition
        else:
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
                event_date=event_date,
                primary_source=LedgerFactReference(
                    capability=LedgerSourceCapability.INVESTMENTS,
                    record_id=LedgerSourceRecordId(str(command.event_id)),
                    revision=1,
                    fact_sha256=prepared.calculation_id,
                ),
                corroborating_sources=tuple(
                    _ledger_fact(fact) for fact in command.evidence.document_facts
                ),
                facts=facts,
            )
        )
        return await complete(
            command,
            prepared=prepared,
            accounting_entry_id=AccountingEntryReference(str(posted.entry_id)),
        )

    async def _post_cash_settlement_entry(self, transaction, command, prepared):
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
        return AccountingEntryReference(str(posted.entry_id))

    async def _claim_bank_fact(
        self,
        transaction,
        command: SettleInvestmentCashCommand,
        prepared: PreparedInvestmentCashSettlement,
        accounting_entry_id: AccountingEntryReference,
    ) -> None:
        bank_fact = command.evidence.bank_fact
        if bank_fact is None:
            raise InvestmentsError.invalid_input()
        signed_amount = prepared.amount
        if (
            prepared.settlement_balance_kind
            is InvestmentSettlementBalanceKind.PURCHASE_PAYABLE
        ):
            signed_amount = type(prepared.amount)(
                -prepared.amount.amount,
                prepared.amount.currency,
            )
        await transaction.claim_transaction_for_external_action(
            ClaimBankTransactionForExternalActionCommand(
                company_id=command.company_id,
                actor_id=command.actor_id,
                correlation_id=command.correlation_id,
                idempotency_key=command.idempotency_key,
                income_year=command.income_year,
                transaction_id=BankTransactionId(str(bank_fact.record_id)),
                transaction_date=command.settlement_date,
                signed_amount=signed_amount,
                source_hash=bank_fact.fact_sha256,
                action_reference=ExternalActionReference(
                    f"investment-settlement:{command.settlement_id}"
                ),
            ),
            accounting_entry_id=BankingAccountingEntryReference(
                str(accounting_entry_id)
            ),
        )

    async def correct_investment(
        self, command: CorrectInvestmentCommand
    ) -> RecordedInvestmentCorrection:
        if command.actor_id != self._persistence.actor_id:
            raise InvestmentsError.forbidden()
        command = replace(command, reason=command.reason.strip())
        async with self._persistence.transaction() as transaction:
            investments = InvestmentsService(transaction)
            replay = await investments.get_investment_correction_replay(command)
            if replay is not None:
                return replay
            prepared = await investments.prepare_investment_correction(command)
            if (
                command.target_kind
                is InvestmentCorrectionTargetKind.ECONOMIC_EVENT
            ):
                replacement = await self._recognize_in_transaction(
                    transaction, command.replacement
                )
            else:
                if (
                    not isinstance(command.replacement, SettleInvestmentCashCommand)
                    or not isinstance(prepared, PreparedCashSettlementCorrection)
                ):
                    raise InvestmentsError.invalid_input()
                replacement_prepared = PreparedInvestmentCashSettlement(
                    event_id=prepared.event_id,
                    recognition_accounting_entry_id=(
                        prepared.recognition_accounting_entry_id
                    ),
                    settlement_balance_kind=prepared.settlement_balance_kind,
                    amount=prepared.amount,
                    event_fact_sha256=prepared.event_fact_sha256,
                    evidence_digest=prepared.replacement_evidence_digest,
                )
                replacement = await self._post_cash_settlement_entry(
                    transaction,
                    command.replacement,
                    replacement_prepared,
                )
                await self._claim_bank_fact(
                    transaction,
                    command.replacement,
                    replacement_prepared,
                    replacement,
                )
            return await investments.complete_investment_correction(
                command,
                prepared=prepared,
                replacement=replacement,
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

    async def list_lifecycle_events(
        self,
        *,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> InvestmentLifecycleEventPage:
        return await self._persistence.list_lifecycle_events(
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

    async def list_year_end_measurements(
        self,
        *,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> InvestmentYearEndMeasurementPage:
        return await self._persistence.list_year_end_measurements(
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

    async def session(
        self,
        access_token: str,
    ) -> InvestmentsSession:
        return InvestmentsSession(
            await self._sessions.session(access_token),
            self._ledger_facade_factory,
        )


__all__ = [
    "InvestmentsApplication",
    "InvestmentsSession",
    "LedgerFacadeFactory",
]
