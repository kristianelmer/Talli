"""Authenticated investments workflows and atomic ledger composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from talli_backend.modules.banking.public import (
    AccountingEntryReference as BankingAccountingEntryReference,
    BankTransaction,
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
    InvestmentLifecycleEventView,
    InvestmentPositionPage,
    InvestmentYearEndMeasurementPage,
    ShareSaleAllocationPage,
    AccountingEntryReference,
    CorrectInvestmentCommand,
    InvestmentAccountingClassification,
    InvestmentCorrectionTargetKind,
    InvestmentDocumentStatus,
    InvestmentEconomicEventId,
    InvestmentEvidence,
    InvestmentEvidenceMode,
    InvestmentFactReference,
    InvestmentKind,
    InvestmentTradingProfile,
    InvestmentPositionId,
    InvestmentSettlementId,
    InvestmentSettlementBalanceKind,
    InvestmentSourceReference,
    InvestmentSourceCapability,
    InvestmentTaxTreatment,
    InvestmentUnits,
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
from talli_backend.shared.kernel import (
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    Money,
)


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


@dataclass(frozen=True, slots=True)
class LegacyInvestmentEvidence:
    mode: InvestmentEvidenceMode
    reference: str
    owner_attested: bool
    document_id: InvestmentSourceReference | None
    document_status: InvestmentDocumentStatus


@dataclass(frozen=True, slots=True)
class LegacySharePurchase:
    company_id: CompanyId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    event_id: InvestmentEconomicEventId
    investment_key: str
    investment_name: str
    investment_kind: InvestmentKind
    accounting_classification: InvestmentAccountingClassification
    tax_treatment: InvestmentTaxTreatment
    acquisition_date: LocalDate
    share_count: InvestmentUnits
    purchase_amount: Money
    transaction_costs: Money
    org_number: str | None
    fund_equity_ratio_basis_points: int | None
    fund_tax_statement_reference: str | None
    trading_profile: InvestmentTradingProfile
    non_active_trading_confirmed: bool
    share_class_code: str | None
    single_share_class_confirmed: bool | None
    equal_share_rights_confirmed: bool | None
    unusual_share_rights_absent_confirmed: bool | None
    evidence: LegacyInvestmentEvidence


@dataclass(frozen=True, slots=True)
class LegacyShareSale:
    company_id: CompanyId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    event_id: InvestmentEconomicEventId
    position_id: InvestmentPositionId
    sale_date: LocalDate
    sold_share_count: InvestmentUnits
    proceeds: Money
    transaction_costs: Money
    sale_year_fund_equity_ratio_basis_points: int | None
    fund_tax_statement_reference: str | None
    evidence: LegacyInvestmentEvidence


@dataclass(frozen=True, slots=True)
class LegacyReceivedDividend:
    company_id: CompanyId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    event_id: InvestmentEconomicEventId
    position_id: InvestmentPositionId
    paying_company_name: str
    declared_date: LocalDate
    paid_date: LocalDate
    gross_amount: Money
    tax_treatment: InvestmentTaxTreatment
    lawful_dividend_confirmed: bool
    group_exception_claimed: bool
    year_end_ownership_basis_points: int | None
    year_end_voting_basis_points: int | None
    group_evidence_reference: str | None
    evidence: LegacyInvestmentEvidence


@dataclass(frozen=True, slots=True)
class LegacyReceivedFundDistribution:
    company_id: CompanyId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    event_id: InvestmentEconomicEventId
    position_id: InvestmentPositionId
    fund_name: str
    entitlement_date: LocalDate
    paid_date: LocalDate
    gross_amount: Money
    opening_fund_equity_ratio_basis_points: int
    fund_tax_statement_reference: str
    evidence: LegacyInvestmentEvidence


@dataclass(frozen=True, slots=True)
class LegacyInvestmentResult:
    event: RecordedInvestmentEconomicEvent
    settlement: RecordedInvestmentCashSettlement | None
    lifecycle: object


LegacyInvestmentRequest = (
    LegacySharePurchase
    | LegacyShareSale
    | LegacyReceivedDividend
    | LegacyReceivedFundDistribution
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
        if (
            prepared.impairment_amount.amount == 0
            and prepared.reversal_amount.amount == 0
        ):
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

    def _legacy_document_evidence(
        self,
        request: LegacyInvestmentRequest,
    ) -> InvestmentEvidence:
        evidence = request.evidence
        if (
            evidence.mode is not InvestmentEvidenceMode.MANUAL_FALLBACK
            or not evidence.owner_attested
            or evidence.document_status is not InvestmentDocumentStatus.ATTACHED
            or evidence.document_id is None
        ):
            raise InvestmentsError.invalid_input()
        identity = "\n".join(
            (
                "talli:owner-attested-investment-compatibility:v2",
                f"company={request.company_id}",
                f"income-year={request.income_year.value}",
                f"action={request.event_id}",
                f"document={evidence.document_id}",
                f"status={evidence.document_status.value}",
                f"reference={evidence.reference.strip()}",
            )
        )
        return InvestmentEvidence(
            mode=evidence.mode,
            reference=evidence.reference,
            owner_attested=evidence.owner_attested,
            document_facts=(
                InvestmentFactReference(
                    capability=InvestmentSourceCapability.DOCUMENTS,
                    record_id=evidence.document_id,
                    revision=1,
                    fact_sha256=sha256(identity.encode("utf-8")).hexdigest(),
                ),
            ),
            bank_fact=None,
        )

    def _legacy_cash_settlement(
        self,
        *,
        request: LegacyInvestmentRequest,
        transaction: BankTransaction,
        amount: Money,
    ) -> SettleInvestmentCashCommand:
        settlement_id = uuid5(
            NAMESPACE_URL,
            f"https://talli.no/investments/compatibility-settlement/{request.event_id}",
        )
        settlement_idempotency = "compat-settlement-" + sha256(
            f"{request.idempotency_key}:{request.event_id}".encode("utf-8")
        ).hexdigest()
        return SettleInvestmentCashCommand(
            company_id=request.company_id,
            actor_id=self.actor_id,
            correlation_id=request.correlation_id,
            idempotency_key=IdempotencyKey(settlement_idempotency),
            income_year=request.income_year,
            settlement_id=InvestmentSettlementId(str(settlement_id)),
            event_id=request.event_id,
            settlement_date=transaction.transaction_date,
            amount=amount,
            evidence=InvestmentEvidence(
                mode=InvestmentEvidenceMode.LINKED_SOURCES,
                reference=(
                    f"Canonical bank transaction {transaction.transaction_id} "
                    "revision 1"
                ),
                owner_attested=False,
                document_facts=(),
                bank_fact=InvestmentFactReference(
                    capability=InvestmentSourceCapability.BANKING,
                    record_id=InvestmentSourceReference(str(transaction.transaction_id)),
                    revision=1,
                    fact_sha256=transaction.source_hash,
                ),
            ),
        )

    async def _legacy_lifecycle_event(
        self,
        *,
        company_id: CompanyId,
        correlation_id: CorrelationId,
        event_id: InvestmentEconomicEventId,
    ) -> InvestmentLifecycleEventView:
        cursor: InvestmentCursor | None = None
        seen_cursors: set[str] = set()
        while True:
            page = await self.list_lifecycle_events(
                company_ids=(company_id,),
                correlation_id=correlation_id,
                cursor=cursor,
                limit=100,
            )
            event = next((item for item in page.items if item.event_id == event_id), None)
            if event is not None:
                return event
            if page.next_cursor is None or str(page.next_cursor) in seen_cursors:
                raise InvestmentsError.unavailable()
            seen_cursors.add(str(page.next_cursor))
            cursor = page.next_cursor

    async def record_legacy_action(
        self,
        request: LegacyInvestmentRequest,
        bank_transaction: BankTransaction | None,
    ) -> LegacyInvestmentResult:
        evidence = self._legacy_document_evidence(request)
        if isinstance(request, LegacySharePurchase):
            if request.tax_treatment is not InvestmentTaxTreatment.EXEMPTION_METHOD:
                raise InvestmentsError.invalid_input()
            recognition = RecognizeSharePurchaseCommand(
                company_id=request.company_id,
                actor_id=self.actor_id,
                correlation_id=request.correlation_id,
                idempotency_key=request.idempotency_key,
                income_year=request.income_year,
                event_id=request.event_id,
                investment_key=request.investment_key,
                investment_name=request.investment_name,
                investment_kind=request.investment_kind,
                accounting_classification=request.accounting_classification,
                acquisition_date=request.acquisition_date,
                share_count=request.share_count,
                purchase_amount=request.purchase_amount,
                transaction_costs=request.transaction_costs,
                org_number=request.org_number,
                fund_equity_ratio_basis_points=request.fund_equity_ratio_basis_points,
                fund_tax_statement_reference=request.fund_tax_statement_reference,
                trading_profile=request.trading_profile,
                non_active_trading_confirmed=request.non_active_trading_confirmed,
                share_class_code=request.share_class_code,
                single_share_class_confirmed=request.single_share_class_confirmed,
                equal_share_rights_confirmed=request.equal_share_rights_confirmed,
                unusual_share_rights_absent_confirmed=(
                    request.unusual_share_rights_absent_confirmed
                ),
                evidence=evidence,
            )
            amount = Money.nok(
                request.purchase_amount.amount + request.transaction_costs.amount
            )
        elif isinstance(request, LegacyShareSale):
            recognition = RecognizeShareSaleCommand(
                company_id=request.company_id,
                actor_id=self.actor_id,
                correlation_id=request.correlation_id,
                idempotency_key=request.idempotency_key,
                income_year=request.income_year,
                event_id=request.event_id,
                position_id=request.position_id,
                sale_date=request.sale_date,
                sold_share_count=request.sold_share_count,
                proceeds=request.proceeds,
                transaction_costs=request.transaction_costs,
                sale_year_fund_equity_ratio_basis_points=(
                    request.sale_year_fund_equity_ratio_basis_points
                ),
                fund_tax_statement_reference=request.fund_tax_statement_reference,
                evidence=evidence,
            )
            amount = Money.nok(
                request.proceeds.amount - request.transaction_costs.amount
            )
        elif isinstance(request, LegacyReceivedDividend):
            if request.tax_treatment is not InvestmentTaxTreatment.EXEMPTION_METHOD:
                raise InvestmentsError.invalid_input()
            recognition = RecognizeReceivedDividendCommand(
                company_id=request.company_id,
                actor_id=self.actor_id,
                correlation_id=request.correlation_id,
                idempotency_key=request.idempotency_key,
                income_year=request.income_year,
                event_id=request.event_id,
                position_id=request.position_id,
                paying_company_name=request.paying_company_name,
                declared_date=request.declared_date,
                gross_amount=request.gross_amount,
                lawful_dividend_confirmed=request.lawful_dividend_confirmed,
                group_exception_claimed=request.group_exception_claimed,
                year_end_ownership_basis_points=request.year_end_ownership_basis_points,
                year_end_voting_basis_points=request.year_end_voting_basis_points,
                group_evidence_reference=request.group_evidence_reference,
                evidence=evidence,
            )
            amount = request.gross_amount
            if (
                bank_transaction is not None
                and bank_transaction.transaction_date != request.paid_date
            ):
                raise InvestmentsError.invalid_input()
        else:
            recognition = RecognizeReceivedFundDistributionCommand(
                company_id=request.company_id,
                actor_id=self.actor_id,
                correlation_id=request.correlation_id,
                idempotency_key=request.idempotency_key,
                income_year=request.income_year,
                event_id=request.event_id,
                position_id=request.position_id,
                fund_name=request.fund_name,
                entitlement_date=request.entitlement_date,
                gross_amount=request.gross_amount,
                opening_fund_equity_ratio_basis_points=(
                    request.opening_fund_equity_ratio_basis_points
                ),
                fund_tax_statement_reference=request.fund_tax_statement_reference,
                evidence=evidence,
            )
            amount = request.gross_amount
            if (
                bank_transaction is not None
                and bank_transaction.transaction_date != request.paid_date
            ):
                raise InvestmentsError.invalid_input()
        settlement = (
            self._legacy_cash_settlement(
                request=request,
                transaction=bank_transaction,
                amount=amount,
            )
            if bank_transaction is not None
            else None
        )
        event, cash = await self.record_compatibility_action(recognition, settlement)
        lifecycle = await self._legacy_lifecycle_event(
            company_id=request.company_id,
            correlation_id=request.correlation_id,
            event_id=request.event_id,
        )
        return LegacyInvestmentResult(event=event, settlement=cash, lifecycle=lifecycle)

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

    async def correct_settled_investment(
        self,
        event_command: CorrectInvestmentCommand,
        settlement_command: CorrectInvestmentCommand,
    ) -> RecordedInvestmentCorrection:
        if (
            event_command.actor_id != self._persistence.actor_id
            or settlement_command.actor_id != self._persistence.actor_id
        ):
            raise InvestmentsError.forbidden()
        async with self._persistence.transaction() as transaction:
            investments = InvestmentsService(transaction)
            replay = await investments.get_investment_correction_replay(
                event_command
            )
            if replay is not None:
                return replay
            prepared = await investments.prepare_settled_investment_correction(
                event_command, settlement_command
            )
            if isinstance(event_command.replacement, SettleInvestmentCashCommand):
                raise InvestmentsError.invalid_input()
            replacement_event = await self._recognize_in_transaction(
                transaction, event_command.replacement
            )
            if not isinstance(
                settlement_command.replacement, SettleInvestmentCashCommand
            ):
                raise InvestmentsError.invalid_input()
            replacement_settlement = await self._settle_in_transaction(
                transaction, settlement_command.replacement
            )
            return await investments.complete_settled_investment_correction(
                event_command,
                settlement_command,
                prepared=prepared,
                replacement_event=replacement_event,
                replacement_settlement=replacement_settlement,
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
    "LegacyInvestmentEvidence",
    "LegacyInvestmentResult",
    "LegacyReceivedDividend",
    "LegacyReceivedFundDistribution",
    "LegacySharePurchase",
    "LegacyShareSale",
    "LedgerFacadeFactory",
]
