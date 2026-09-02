from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from talli_backend.application.investments_workflow import (
    InvestmentsSession,
    LegacyInvestmentEvidence,
    LegacySharePurchase,
)
from talli_backend.modules.investments.public import (
    AccountingEntryReference,
    AcquisitionLotId,
    CorrectInvestmentCommand,
    InvestmentActivityKind,
    InvestmentAccountingClassification,
    InvestmentCorrectionId,
    InvestmentCorrectionTargetKind,
    InvestmentDocumentStatus,
    InvestmentEconomicEventId,
    InvestmentEvidence,
    InvestmentEvidenceMode,
    InvestmentFactReference,
    InvestmentKind,
    InvestmentsError,
    InvestmentTradingProfile,
    InvestmentTaxTreatment,
    InvestmentMeasurementId,
    InvestmentMeasurementRule,
    InvestmentPositionId,
    InvestmentSaleLotFact,
    InvestmentSettlementBalanceKind,
    InvestmentSettlementId,
    InvestmentSourceCapability,
    InvestmentSourceReference,
    InvestmentUnits,
    PreparedInvestmentCashSettlement,
    PreparedInvestmentMeasurementFacts,
    PreparedInvestmentYearEndMeasurement,
    PreparedEconomicEventCorrection,
    PreparedCashSettlementCorrection,
    PreparedReceivedDividendFacts,
    PreparedReceivedFundDistributionFacts,
    PreparedReceivedDividend,
    PreparedShareSaleFacts,
    PreparedSharePurchaseRecognition,
    PreparedSharePurchase,
    PreparedShareSale,
    RecognizeReceivedDividendCommand,
    RecognizeReceivedFundDistributionCommand,
    RecognizeShareSaleCommand,
    RecognizeSharePurchaseCommand,
    RecordInvestmentYearEndMeasurementCommand,
    RecordedInvestmentCashSettlement,
    RecordedInvestmentEconomicEvent,
    RecordedInvestmentYearEndMeasurement,
    RecordedShareSale,
    RecordedSharePurchase,
    RecordedReceivedDividend,
    RecordedReceivedFundDistribution,
    RecordedInvestmentCorrection,
    SettleInvestmentCashCommand,
)
from talli_backend.modules.ledger.public import (
    InvestmentCashSettlementFacts,
    InvestmentDividendFacts,
    InvestmentFundDistributionRecognitionFacts,
    InvestmentPurchaseRecognitionFacts,
    InvestmentSaleRecognitionFacts,
    InvestmentYearEndMeasurementFacts,
    LedgerEntryId,
    LedgerEntryKind,
    PostedLedgerEntry,
)
from talli_backend.shared.kernel import (
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    Money,
    Timestamp,
)

from test_investments import (
    supported_purchase,
    supported_investment_correction,
    supported_received_dividend,
    supported_received_fund_distribution,
    supported_sale,
)


POSITION_ID = InvestmentPositionId("50000000-0000-0000-0000-000000000005")
LOT_ID = AcquisitionLotId("60000000-0000-0000-0000-000000000006")
ENTRY_ID = LedgerEntryId("70000000-0000-0000-0000-000000000007")
ORIGINAL_ENTRY_ID = AccountingEntryReference(
    "70000000-0000-0000-0000-000000000017"
)
NOW = Timestamp(datetime(2026, 8, 31, tzinfo=UTC))


def lifecycle_purchase() -> RecognizeSharePurchaseCommand:
    legacy = supported_purchase()
    return RecognizeSharePurchaseCommand(
        company_id=legacy.company_id,
        actor_id=legacy.actor_id,
        correlation_id=legacy.correlation_id,
        idempotency_key=IdempotencyKey("investment-recognition-0001"),
        income_year=legacy.income_year,
        event_id=InvestmentEconomicEventId(
            "90000000-0000-0000-0000-000000000001"
        ),
        investment_key=legacy.investment_key,
        investment_name=legacy.investment_name,
        investment_kind=legacy.investment_kind,
        accounting_classification=legacy.accounting_classification,
        acquisition_date=legacy.acquisition_date,
        share_count=InvestmentUnits.of("10.125000000000"),
        purchase_amount=legacy.purchase_amount,
        transaction_costs=legacy.transaction_costs,
        org_number=legacy.org_number,
        fund_equity_ratio_basis_points=legacy.fund_equity_ratio_basis_points,
        fund_tax_statement_reference=legacy.fund_tax_statement_reference,
        trading_profile=legacy.trading_profile,
        non_active_trading_confirmed=legacy.non_active_trading_confirmed,
        share_class_code=legacy.share_class_code,
        single_share_class_confirmed=legacy.single_share_class_confirmed,
        equal_share_rights_confirmed=legacy.equal_share_rights_confirmed,
        unusual_share_rights_absent_confirmed=(
            legacy.unusual_share_rights_absent_confirmed
        ),
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.LINKED_SOURCES,
            "broker contract note",
            False,
            (
                InvestmentFactReference(
                    InvestmentSourceCapability.DOCUMENTS,
                    InvestmentSourceReference(
                        "80000000-0000-0000-0000-000000000001"
                    ),
                    1,
                    "a" * 64,
                ),
            ),
            None,
        ),
    )


def lifecycle_year_end_measurement() -> RecordInvestmentYearEndMeasurementCommand:
    purchase = supported_purchase()
    return RecordInvestmentYearEndMeasurementCommand(
        company_id=purchase.company_id,
        actor_id=purchase.actor_id,
        correlation_id=CorrelationId("investment-measurement-2026"),
        idempotency_key=IdempotencyKey("investment-measurement-2026-0001"),
        income_year=IncomeYear(2026),
        measurement_id=InvestmentMeasurementId(
            "90000000-0000-0000-0000-000000000041"
        ),
        position_id=POSITION_ID,
        as_of=LocalDate(date(2026, 12, 31)),
        observed_or_recoverable_value=Money.nok("82.50"),
        tax_value=Money.nok("97.00"),
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.LINKED_SOURCES,
            "year-end broker statement",
            False,
            (
                InvestmentFactReference(
                    InvestmentSourceCapability.DOCUMENTS,
                    InvestmentSourceReference(
                        "80000000-0000-0000-0000-000000000041"
                    ),
                    1,
                    "d" * 64,
                ),
            ),
            None,
        ),
    )


def lifecycle_settlement(
    purchase: RecognizeSharePurchaseCommand,
) -> SettleInvestmentCashCommand:
    return SettleInvestmentCashCommand(
        company_id=purchase.company_id,
        actor_id=purchase.actor_id,
        correlation_id=purchase.correlation_id,
        idempotency_key=IdempotencyKey("investment-settlement-0001"),
        income_year=purchase.income_year,
        settlement_id=InvestmentSettlementId(
            "90000000-0000-0000-0000-000000000002"
        ),
        event_id=purchase.event_id,
        settlement_date=LocalDate(purchase.acquisition_date.value),
        amount=Money.nok("125.50"),
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.LINKED_SOURCES,
            "bank transaction",
            False,
            (),
            InvestmentFactReference(
                InvestmentSourceCapability.BANKING,
                InvestmentSourceReference(
                    "70000000-0000-0000-0000-000000000001"
                ),
                1,
                "b" * 64,
            ),
        ),
    )


def lifecycle_settlement_correction() -> CorrectInvestmentCommand:
    purchase = lifecycle_purchase()
    original = lifecycle_settlement(purchase)
    replacement = replace(
        original,
        settlement_id=InvestmentSettlementId(
            "90000000-0000-0000-0000-000000000003"
        ),
        idempotency_key=IdempotencyKey("replacement-settlement-0001"),
        correlation_id=CorrelationId("replacement-settlement-correlation"),
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.LINKED_SOURCES,
            "replacement bank transaction",
            False,
            (),
            InvestmentFactReference(
                InvestmentSourceCapability.BANKING,
                InvestmentSourceReference(
                    "70000000-0000-0000-0000-000000000003"
                ),
                1,
                "f" * 64,
            ),
        ),
    )
    return CorrectInvestmentCommand(
        company_id=purchase.company_id,
        actor_id=purchase.actor_id,
        correlation_id=CorrelationId("settlement-correction-correlation"),
        idempotency_key=IdempotencyKey("settlement-correction-0001"),
        income_year=purchase.income_year,
        correction_id=InvestmentCorrectionId(
            "90000000-0000-0000-0000-000000000004"
        ),
        target_kind=InvestmentCorrectionTargetKind.CASH_SETTLEMENT,
        original_record_id=original.settlement_id,
        original_activity_kind=InvestmentActivityKind.SHARE_PURCHASE,
        correction_date=LocalDate(purchase.acquisition_date.value),
        reason="Replace settlement source facts",
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.LINKED_SOURCES,
            "settlement correction document",
            False,
            (
                InvestmentFactReference(
                    InvestmentSourceCapability.DOCUMENTS,
                    InvestmentSourceReference(
                        "80000000-0000-0000-0000-000000000004"
                    ),
                    1,
                    "e" * 64,
                ),
            ),
            None,
        ),
        replacement=replacement,
    )


def lifecycle_sale() -> RecognizeShareSaleCommand:
    legacy = supported_sale()
    return RecognizeShareSaleCommand(
        company_id=legacy.company_id,
        actor_id=legacy.actor_id,
        correlation_id=legacy.correlation_id,
        idempotency_key=IdempotencyKey("investment-sale-recognition-0001"),
        income_year=legacy.income_year,
        event_id=InvestmentEconomicEventId(
            "90000000-0000-0000-0000-000000000011"
        ),
        position_id=legacy.position_id,
        sale_date=legacy.sale_date,
        sold_share_count=InvestmentUnits.of("4.125000000000"),
        proceeds=legacy.proceeds,
        transaction_costs=legacy.transaction_costs,
        sale_year_fund_equity_ratio_basis_points=(
            legacy.sale_year_fund_equity_ratio_basis_points
        ),
        fund_tax_statement_reference=legacy.fund_tax_statement_reference,
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.LINKED_SOURCES,
            "sale agreement",
            False,
            (
                InvestmentFactReference(
                    InvestmentSourceCapability.DOCUMENTS,
                    InvestmentSourceReference(
                        "80000000-0000-0000-0000-000000000011"
                    ),
                    2,
                    "d" * 64,
                ),
            ),
            None,
        ),
    )


def lifecycle_dividend() -> RecognizeReceivedDividendCommand:
    legacy = supported_received_dividend()
    return RecognizeReceivedDividendCommand(
        company_id=legacy.company_id,
        actor_id=legacy.actor_id,
        correlation_id=legacy.correlation_id,
        idempotency_key=IdempotencyKey("investment-dividend-recognition-0001"),
        income_year=legacy.income_year,
        event_id=InvestmentEconomicEventId(
            "90000000-0000-0000-0000-000000000021"
        ),
        position_id=legacy.position_id,
        paying_company_name=legacy.paying_company_name,
        declared_date=legacy.declared_date,
        gross_amount=legacy.gross_amount,
        lawful_dividend_confirmed=legacy.lawful_dividend_confirmed,
        group_exception_claimed=legacy.group_exception_claimed,
        year_end_ownership_basis_points=legacy.year_end_ownership_basis_points,
        year_end_voting_basis_points=legacy.year_end_voting_basis_points,
        group_evidence_reference=legacy.group_evidence_reference,
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.LINKED_SOURCES,
            "dividend decision",
            False,
            (
                InvestmentFactReference(
                    InvestmentSourceCapability.DOCUMENTS,
                    InvestmentSourceReference(
                        "80000000-0000-0000-0000-000000000021"
                    ),
                    1,
                    "e" * 64,
                ),
            ),
            None,
        ),
    )


def lifecycle_fund_distribution() -> RecognizeReceivedFundDistributionCommand:
    legacy = supported_received_fund_distribution()
    return RecognizeReceivedFundDistributionCommand(
        company_id=legacy.company_id,
        actor_id=legacy.actor_id,
        correlation_id=legacy.correlation_id,
        idempotency_key=IdempotencyKey("investment-fund-recognition-0001"),
        income_year=legacy.income_year,
        event_id=InvestmentEconomicEventId(
            "90000000-0000-0000-0000-000000000031"
        ),
        position_id=legacy.position_id,
        fund_name=legacy.fund_name,
        entitlement_date=legacy.entitlement_date,
        gross_amount=legacy.gross_amount,
        opening_fund_equity_ratio_basis_points=(
            legacy.opening_fund_equity_ratio_basis_points
        ),
        fund_tax_statement_reference=legacy.fund_tax_statement_reference,
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.LINKED_SOURCES,
            "fund tax statement",
            False,
            (
                InvestmentFactReference(
                    InvestmentSourceCapability.DOCUMENTS,
                    InvestmentSourceReference(
                        "80000000-0000-0000-0000-000000000031"
                    ),
                    3,
                    "f" * 64,
                ),
            ),
            None,
        ),
    )


class SessionPersistence:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.posted_command = None

    @property
    def actor_id(self):
        return supported_purchase().actor_id

    @asynccontextmanager
    async def transaction(self):
        self.events.append("transaction:begin")
        yield self
        self.events.append("transaction:commit")

    async def get_year_end_measurement_replay(self, command):
        self.events.append("investments:measurement-replay")
        return None

    async def prepare_year_end_measurement(
        self, command, *, evidence_digest
    ):
        self.events.append("investments:measurement-prepare")
        return PreparedInvestmentMeasurementFacts(
            position_id=command.position_id,
            investment_name="Example ASA",
            investment_kind=InvestmentKind.NORWEGIAN_LISTED_SHARE,
            accounting_classification=(
                InvestmentAccountingClassification.CURRENT_LISTED_SHARE
            ),
            quantity=InvestmentUnits.of("10"),
            source_book_cost=Money.nok("100.00"),
            pre_measurement_book_value=Money.nok("100.00"),
            tax_basis=Money.nok("100.00"),
        )

    async def complete_year_end_measurement(
        self, command, *, prepared, accounting_entry_id
    ):
        self.events.append("investments:measurement-complete")
        return RecordedInvestmentYearEndMeasurement(
            measurement_id=command.measurement_id,
            position_id=command.position_id,
            accounting_entry_id=accounting_entry_id,
            measurement_rule=prepared.measurement_rule,
            closing_book_value=prepared.closing_book_value,
            tax_basis=prepared.tax_basis,
            tax_value=prepared.tax_value,
            replayed=False,
        )

    async def get_share_purchase_recognition_replay(self, command):
        self.events.append("investments:recognition-replay")
        return None

    async def prepare_share_purchase_recognition(
        self, command, *, capitalized_cost, evidence_digest, calculation_id
    ):
        self.events.append("investments:recognition-prepare")
        return PreparedSharePurchaseRecognition(
            position_id=POSITION_ID,
            lot_id=LOT_ID,
            position_created=True,
            investment_name="Example AS",
            accounting_classification=InvestmentAccountingClassification.OTHER_LONG_TERM,
            acquisition_cost=capitalized_cost,
            expected_settlement_amount=capitalized_cost,
            settlement_balance_kind=InvestmentSettlementBalanceKind.PURCHASE_PAYABLE,
            evidence_digest=evidence_digest,
            calculation_id=calculation_id,
        )

    async def complete_share_purchase_recognition(
        self, command, *, prepared, accounting_entry_id
    ):
        self.events.append("investments:recognition-complete")
        return RecordedInvestmentEconomicEvent(
            event_id=command.event_id,
            position_id=prepared.position_id,
            recognition_accounting_entry_id=accounting_entry_id,
            expected_settlement_amount=prepared.expected_settlement_amount,
            settlement_balance_kind=prepared.settlement_balance_kind,
            replayed=False,
        )

    async def get_share_sale_recognition_replay(self, command):
        self.events.append("investments:sale-recognition-replay")
        return None

    async def prepare_share_sale_recognition(
        self, command, *, net_proceeds, evidence_digest
    ):
        self.events.append("investments:sale-recognition-prepare")
        return PreparedShareSaleFacts(
            position_id=command.position_id,
            investment_name="Example AS",
            investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
            accounting_classification=(
                InvestmentAccountingClassification.OTHER_LONG_TERM
            ),
            fifo_book_cost_basis_reduction=Money.nok("50.20"),
            fifo_tax_basis_reduction=Money.nok("50.20"),
            lot_facts=(
                InvestmentSaleLotFact(
                    lot_id=LOT_ID,
                    allocation_order=1,
                    acquisition_date=command.sale_date,
                    allocated_share_count=command.sold_share_count,
                    allocated_book_cost_basis=Money.nok("50.20"),
                    allocated_tax_basis=Money.nok("50.20"),
                    acquisition_year_fund_equity_ratio_basis_points=None,
                ),
            ),
        )

    async def complete_share_sale_recognition(
        self, command, *, prepared, accounting_entry_id
    ):
        self.events.append("investments:sale-recognition-complete")
        return RecordedInvestmentEconomicEvent(
            event_id=command.event_id,
            position_id=prepared.position_id,
            recognition_accounting_entry_id=accounting_entry_id,
            expected_settlement_amount=prepared.net_proceeds,
            settlement_balance_kind=(
                InvestmentSettlementBalanceKind.SALE_RECEIVABLE
            ),
            replayed=False,
        )

    async def get_received_dividend_recognition_replay(self, command):
        self.events.append("investments:dividend-recognition-replay")
        return None

    async def prepare_received_dividend_recognition(
        self, command, *, evidence_digest
    ):
        self.events.append("investments:dividend-recognition-prepare")
        return PreparedReceivedDividendFacts(
            position_id=command.position_id,
            investment_name="Example AS",
            investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
        )

    async def complete_received_dividend_recognition(
        self, command, *, prepared, accounting_entry_id
    ):
        self.events.append("investments:dividend-recognition-complete")
        return RecordedInvestmentEconomicEvent(
            event_id=command.event_id,
            position_id=prepared.position_id,
            recognition_accounting_entry_id=accounting_entry_id,
            expected_settlement_amount=command.gross_amount,
            settlement_balance_kind=(
                InvestmentSettlementBalanceKind.DIVIDEND_RECEIVABLE
            ),
            replayed=False,
        )

    async def get_received_fund_distribution_recognition_replay(self, command):
        self.events.append("investments:fund-recognition-replay")
        return None

    async def prepare_received_fund_distribution_recognition(
        self, command, *, evidence_digest
    ):
        self.events.append("investments:fund-recognition-prepare")
        return PreparedReceivedFundDistributionFacts(
            position_id=command.position_id,
            investment_name="Norsk Kombinasjonsfond",
            investment_kind=InvestmentKind.NORWEGIAN_EQUITY_FUND,
        )

    async def complete_received_fund_distribution_recognition(
        self, command, *, prepared, accounting_entry_id
    ):
        self.events.append("investments:fund-recognition-complete")
        return RecordedInvestmentEconomicEvent(
            event_id=command.event_id,
            position_id=prepared.position_id,
            recognition_accounting_entry_id=accounting_entry_id,
            expected_settlement_amount=command.gross_amount,
            settlement_balance_kind=(
                InvestmentSettlementBalanceKind.FUND_DISTRIBUTION_RECEIVABLE
            ),
            replayed=False,
        )

    async def get_cash_settlement_replay(self, command):
        self.events.append("investments:settlement-replay")
        return None

    async def prepare_cash_settlement(self, command, *, evidence_digest):
        self.events.append("investments:settlement-prepare")
        return PreparedInvestmentCashSettlement(
            event_id=command.event_id,
            recognition_accounting_entry_id=ORIGINAL_ENTRY_ID,
            settlement_balance_kind=InvestmentSettlementBalanceKind.PURCHASE_PAYABLE,
            amount=command.amount,
            event_fact_sha256="c" * 64,
            evidence_digest=evidence_digest,
        )

    async def complete_cash_settlement(
        self, command, *, prepared, accounting_entry_id
    ):
        self.events.append("investments:settlement-complete")
        return RecordedInvestmentCashSettlement(
            settlement_id=command.settlement_id,
            event_id=command.event_id,
            settlement_accounting_entry_id=accounting_entry_id,
            replayed=False,
        )

    async def claim_transaction_for_external_action(
        self, command, *, accounting_entry_id
    ):
        self.events.append("banking:claim-settlement-fact")
        assert str(command.transaction_id) == str(
            lifecycle_settlement(lifecycle_purchase()).evidence.bank_fact.record_id
        ) or str(command.transaction_id) == str(
            lifecycle_settlement_correction().replacement.evidence.bank_fact.record_id
        )
        assert accounting_entry_id.value == str(ENTRY_ID)

    async def get_investment_correction_replay(self, command):
        self.events.append("investments:correction-replay")
        return None

    async def prepare_investment_correction(
        self, command, *, evidence_digest, replacement_evidence_digest
    ):
        self.events.append("investments:correction-prepare")
        assert replacement_evidence_digest == command.replacement.evidence.digest()
        if command.target_kind is InvestmentCorrectionTargetKind.CASH_SETTLEMENT:
            return PreparedCashSettlementCorrection(
                original_accounting_entry_id=ORIGINAL_ENTRY_ID,
                original_settlement_id=command.original_record_id,
                event_id=command.replacement.event_id,
                recognition_accounting_entry_id=AccountingEntryReference(
                    "70000000-0000-0000-0000-000000000018"
                ),
                settlement_balance_kind=(
                    InvestmentSettlementBalanceKind.PURCHASE_PAYABLE
                ),
                amount=command.replacement.amount,
                event_fact_sha256="f" * 64,
                replacement_evidence_digest=replacement_evidence_digest,
                evidence_digest=evidence_digest,
                original_activity_kind=InvestmentActivityKind.SHARE_PURCHASE,
            )
        return PreparedEconomicEventCorrection(
            original_accounting_entry_id=ORIGINAL_ENTRY_ID,
            original_position_id=command.replacement.position_id,
            evidence_digest=evidence_digest,
        )

    async def complete_investment_correction(
        self, command, *, prepared, replacement_accounting_entry_id
    ):
        self.events.append("investments:correction-complete")
        assert prepared.original_accounting_entry_id == ORIGINAL_ENTRY_ID
        assert replacement_accounting_entry_id == AccountingEntryReference(
            str(ENTRY_ID)
        )
        return RecordedInvestmentCorrection(
            correction_id=command.correction_id,
            target_kind=command.target_kind,
            original_record_id=command.original_record_id,
            replacement_record_id=(
                command.replacement.settlement_id
                if isinstance(command.replacement, SettleInvestmentCashCommand)
                else command.replacement.event_id
            ),
            reversal_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000027"
            ),
            replacement_accounting_entry_id=replacement_accounting_entry_id,
            replayed=False,
        )

    async def get_share_purchase_replay(self, command):
        self.events.append("investments:replay")
        return None

    async def prepare_share_purchase(
        self, command, *, capitalized_cost, evidence_digest, calculation_id
    ):
        self.events.append("investments:prepare")
        return PreparedSharePurchase(
            POSITION_ID,
            LOT_ID,
            True,
            "Example AS",
            InvestmentAccountingClassification.OTHER_LONG_TERM,
            capitalized_cost,
            evidence_digest,
            calculation_id,
        )

    async def complete_share_purchase(
        self, command, *, prepared, accounting_entry_id
    ):
        self.events.append("investments:complete")
        assert prepared == PreparedSharePurchase(
            POSITION_ID,
            LOT_ID,
            True,
            "Example AS",
            InvestmentAccountingClassification.OTHER_LONG_TERM,
            Money.nok("125.50"),
            prepared.evidence_digest,
            prepared.calculation_id,
        )
        assert accounting_entry_id == AccountingEntryReference(str(ENTRY_ID))
        return RecordedSharePurchase(
            action_id=command.action_id,
            position_id=prepared.position_id,
            lot_id=prepared.lot_id,
            accounting_entry_id=accounting_entry_id,
            position_created=prepared.position_created,
            replayed=False,
        )

    async def get_share_sale_replay(self, command):
        self.events.append("investments:sale-replay")
        return None

    async def prepare_share_sale(self, command, *, net_proceeds, evidence_digest):
        self.events.append("investments:sale-prepare")
        return PreparedShareSaleFacts(
            position_id=POSITION_ID,
            investment_name="Example AS",
            investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
            accounting_classification=InvestmentAccountingClassification.OTHER_LONG_TERM,
            fifo_book_cost_basis_reduction=Money.nok("50.20"),
            fifo_tax_basis_reduction=Money.nok("50.20"),
            lot_facts=(InvestmentSaleLotFact(
                lot_id=LOT_ID,
                allocation_order=1,
                acquisition_date=command.sale_date,
                allocated_share_count=InvestmentUnits.of(
                    str(command.sold_share_count)
                ),
                allocated_book_cost_basis=Money.nok("50.20"),
                allocated_tax_basis=Money.nok("50.20"),
                acquisition_year_fund_equity_ratio_basis_points=None,
            ),),
        )

    async def complete_share_sale(self, command, *, prepared, accounting_entry_id):
        self.events.append("investments:sale-complete")
        assert accounting_entry_id == AccountingEntryReference(str(ENTRY_ID))
        return RecordedShareSale(
            action_id=command.action_id,
            position_id=command.position_id,
            accounting_entry_id=accounting_entry_id,
            replayed=False,
        )

    async def get_received_dividend_replay(self, command):
        self.events.append("investments:dividend-replay")
        return None

    async def prepare_received_dividend(
        self, command, *, evidence_digest
    ):
        self.events.append("investments:dividend-prepare")
        return PreparedReceivedDividendFacts(
            position_id=command.position_id,
            investment_name="Example AS",
            investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
        )

    async def complete_received_dividend(
        self, command, *, prepared, accounting_entry_id
    ):
        self.events.append("investments:dividend-complete")
        return RecordedReceivedDividend(
            action_id=command.action_id,
            position_id=command.position_id,
            accounting_entry_id=accounting_entry_id,
            taxable_add_back=prepared.taxable_add_back,
            replayed=False,
        )

    async def get_received_fund_distribution_replay(self, command):
        self.events.append("investments:fund-distribution-replay")
        return None

    async def prepare_received_fund_distribution(self, command, *, evidence_digest):
        self.events.append("investments:fund-distribution-prepare")
        return PreparedReceivedFundDistributionFacts(
            position_id=command.position_id,
            investment_name="Norsk Kombinasjonsfond",
            investment_kind=InvestmentKind.NORWEGIAN_EQUITY_FUND,
        )

    async def complete_received_fund_distribution(
        self, command, *, prepared, accounting_entry_id
    ):
        self.events.append("investments:fund-distribution-complete")
        return RecordedReceivedFundDistribution(
            action_id=command.action_id,
            position_id=command.position_id,
            accounting_entry_id=accounting_entry_id,
            dividend_portion=prepared.dividend_portion,
            interest_portion=prepared.interest_portion,
            taxable_add_back=prepared.taxable_add_back,
            total_taxable_income=prepared.total_taxable_income,
            replayed=False,
        )


class LedgerFacade:
    def __init__(self, transaction: SessionPersistence) -> None:
        self.transaction = transaction

    async def recognize_holding_action(self, command):
        if isinstance(command.facts, InvestmentPurchaseRecognitionFacts):
            self.transaction.events.append("ledger:recognize-purchase")
            entry_kind = LedgerEntryKind.SHARE_PURCHASE
        elif isinstance(command.facts, InvestmentSaleRecognitionFacts):
            self.transaction.events.append("ledger:recognize-sale")
            entry_kind = LedgerEntryKind.SHARE_SALE
        elif isinstance(command.facts, InvestmentDividendFacts):
            self.transaction.events.append("ledger:recognize-dividend")
            entry_kind = LedgerEntryKind.DIVIDEND_RECEIVED
        elif isinstance(command.facts, InvestmentFundDistributionRecognitionFacts):
            self.transaction.events.append("ledger:recognize-fund-distribution")
            entry_kind = LedgerEntryKind.DIVIDEND_RECEIVED
        elif isinstance(command.facts, InvestmentCashSettlementFacts):
            self.transaction.events.append("ledger:settle-cash")
            entry_kind = LedgerEntryKind.SHARE_PURCHASE
        elif isinstance(command.facts, InvestmentYearEndMeasurementFacts):
            self.transaction.events.append("ledger:measure-investment")
            entry_kind = LedgerEntryKind.INVESTMENT_MEASUREMENT
        else:
            raise AssertionError("unexpected lifecycle facts")
        self.transaction.posted_command = command
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=command.company_id,
            income_year=command.income_year,
            entry_kind=entry_kind,
            posted_at=NOW,
            replayed=False,
        )

    async def post_investment_purchase(self, command):
        self.transaction.events.append("ledger:post")
        self.transaction.posted_command = command
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=command.company_id,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.SHARE_PURCHASE,
            posted_at=NOW,
            replayed=False,
        )

    async def post_investment_sale(self, command):
        self.transaction.events.append("ledger:sale-post")
        self.transaction.posted_command = command
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=command.company_id,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.SHARE_SALE,
            posted_at=NOW,
            replayed=False,
        )

    async def post_received_dividend(self, command):
        self.transaction.events.append("ledger:dividend-post")
        self.transaction.posted_command = command
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=command.company_id,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.DIVIDEND_RECEIVED,
            posted_at=NOW,
            replayed=False,
        )

    async def post_received_fund_distribution(self, command):
        self.transaction.events.append("ledger:fund-distribution-post")
        self.transaction.posted_command = command
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=command.company_id,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.DIVIDEND_RECEIVED,
            posted_at=NOW,
            replayed=False,
        )


def test_correction_composes_reversal_and_same_policy_replacement_atomically() -> None:
    persistence = SessionPersistence()
    command = supported_investment_correction()

    result = asyncio.run(
        InvestmentsSession(persistence, LedgerFacade).correct_investment(command)
    )

    assert result.correction_id == command.correction_id
    assert result.original_record_id == command.original_record_id
    assert result.replacement_record_id == command.replacement.event_id
    assert result.replacement_accounting_entry_id == AccountingEntryReference(
        str(ENTRY_ID)
    )
    assert persistence.events == [
        "transaction:begin",
        "investments:correction-replay",
        "investments:correction-prepare",
        "investments:dividend-recognition-replay",
        "investments:dividend-recognition-prepare",
        "ledger:recognize-dividend",
        "investments:dividend-recognition-complete",
        "investments:correction-complete",
        "transaction:commit",
    ]


def test_settlement_correction_posts_replacement_before_append_only_completion() -> None:
    persistence = SessionPersistence()
    command = lifecycle_settlement_correction()

    result = asyncio.run(
        InvestmentsSession(persistence, LedgerFacade).correct_investment(command)
    )

    assert result.target_kind is InvestmentCorrectionTargetKind.CASH_SETTLEMENT
    assert result.original_record_id == command.original_record_id
    assert result.replacement_record_id == command.replacement.settlement_id
    assert persistence.events == [
        "transaction:begin",
        "investments:correction-replay",
        "investments:correction-prepare",
        "ledger:settle-cash",
        "banking:claim-settlement-fact",
        "investments:correction-complete",
        "transaction:commit",
    ]
    assert "investments:settlement-complete" not in persistence.events


def test_purchase_recognition_posts_without_cash_and_preserves_fractional_units() -> None:
    persistence = SessionPersistence()
    command = lifecycle_purchase()

    result = asyncio.run(
        InvestmentsSession(persistence, LedgerFacade).recognize_share_purchase(command)
    )

    assert result.event_id == command.event_id
    assert result.expected_settlement_amount == Money.nok("125.50")
    assert persistence.events == [
        "transaction:begin",
        "investments:recognition-replay",
        "investments:recognition-prepare",
        "ledger:recognize-purchase",
        "investments:recognition-complete",
        "transaction:commit",
    ]
    assert isinstance(
        persistence.posted_command.facts,
        InvestmentPurchaseRecognitionFacts,
    )
    assert persistence.posted_command.facts.acquisition_cost == Money.nok("125.50")
    assert persistence.posted_command.primary_source.record_id.value == str(
        command.event_id
    )
    assert command.share_count.amount == Decimal("10.125000000000")


def test_purchase_cash_settlement_posts_independently_against_recognition() -> None:
    persistence = SessionPersistence()
    command = lifecycle_settlement(lifecycle_purchase())

    result = asyncio.run(
        InvestmentsSession(persistence, LedgerFacade).settle_investment_cash(command)
    )

    assert result.settlement_id == command.settlement_id
    assert persistence.events == [
        "transaction:begin",
        "investments:settlement-replay",
        "investments:settlement-prepare",
        "ledger:settle-cash",
        "banking:claim-settlement-fact",
        "investments:settlement-complete",
        "transaction:commit",
    ]
    assert isinstance(persistence.posted_command.facts, InvestmentCashSettlementFacts)
    assert persistence.posted_command.facts.amount == Money.nok("125.50")
    assert persistence.posted_command.facts.recognition_entry_id == LedgerEntryId(
        str(ORIGINAL_ENTRY_ID)
    )
    assert persistence.posted_command.primary_source.record_id.value == str(
        command.settlement_id
    )


def test_deprecated_overlap_composes_recognition_and_settlement_atomically() -> None:
    persistence = SessionPersistence()
    recognition = lifecycle_purchase()
    settlement = lifecycle_settlement(recognition)

    event, cash = asyncio.run(
        InvestmentsSession(persistence, LedgerFacade).record_compatibility_action(
            recognition, settlement
        )
    )

    assert event.event_id == recognition.event_id
    assert cash is not None and cash.settlement_id == settlement.settlement_id
    assert persistence.events == [
        "transaction:begin",
        "investments:recognition-replay",
        "investments:recognition-prepare",
        "ledger:recognize-purchase",
        "investments:recognition-complete",
        "investments:settlement-replay",
        "investments:settlement-prepare",
        "ledger:settle-cash",
        "banking:claim-settlement-fact",
        "investments:settlement-complete",
        "transaction:commit",
    ]


def test_deprecated_overlap_rejects_inexact_document_evidence_before_mutation() -> None:
    persistence = SessionPersistence()
    purchase = supported_purchase()
    request = LegacySharePurchase(
        company_id=purchase.company_id,
        correlation_id=purchase.correlation_id,
        idempotency_key=purchase.idempotency_key,
        income_year=purchase.income_year,
        event_id=InvestmentEconomicEventId(
            "90000000-0000-0000-0000-000000000091"
        ),
        investment_key=purchase.investment_key,
        investment_name=purchase.investment_name,
        investment_kind=purchase.investment_kind,
        accounting_classification=purchase.accounting_classification,
        tax_treatment=InvestmentTaxTreatment.EXEMPTION_METHOD,
        acquisition_date=purchase.acquisition_date,
        share_count=purchase.share_count,
        purchase_amount=purchase.purchase_amount,
        transaction_costs=purchase.transaction_costs,
        org_number=purchase.org_number,
        fund_equity_ratio_basis_points=purchase.fund_equity_ratio_basis_points,
        fund_tax_statement_reference=purchase.fund_tax_statement_reference,
        trading_profile=purchase.trading_profile,
        non_active_trading_confirmed=purchase.non_active_trading_confirmed,
        share_class_code=purchase.share_class_code,
        single_share_class_confirmed=purchase.single_share_class_confirmed,
        equal_share_rights_confirmed=purchase.equal_share_rights_confirmed,
        unusual_share_rights_absent_confirmed=(
            purchase.unusual_share_rights_absent_confirmed
        ),
        evidence=LegacyInvestmentEvidence(
            mode=InvestmentEvidenceMode.MANUAL_FALLBACK,
            reference="owner-provided purchase document",
            owner_attested=False,
            document_id=InvestmentSourceReference(
                "80000000-0000-0000-0000-000000000091"
            ),
            document_status=InvestmentDocumentStatus.ATTACHED,
        ),
    )

    try:
        asyncio.run(
            InvestmentsSession(persistence, LedgerFacade).record_legacy_action(
                request, None
            )
        )
    except InvestmentsError as error:
        assert error.code == "INVESTMENTS_INVALID_INPUT"
    else:
        raise AssertionError("inexact compatibility evidence must fail closed")

    assert persistence.events == []


def test_share_sale_recognition_posts_receivable_with_fractional_fifo() -> None:
    persistence = SessionPersistence()
    command = lifecycle_sale()

    result = asyncio.run(
        InvestmentsSession(persistence, LedgerFacade).recognize_share_sale(command)
    )

    assert result.event_id == command.event_id
    assert result.settlement_balance_kind is (
        InvestmentSettlementBalanceKind.SALE_RECEIVABLE
    )
    assert persistence.events == [
        "transaction:begin",
        "investments:sale-recognition-replay",
        "investments:sale-recognition-prepare",
        "ledger:recognize-sale",
        "investments:sale-recognition-complete",
        "transaction:commit",
    ]
    assert isinstance(persistence.posted_command.facts, InvestmentSaleRecognitionFacts)
    assert persistence.posted_command.facts.net_proceeds == Money.nok("75.00")
    assert persistence.posted_command.facts.carrying_amount == Money.nok("50.20")
    assert command.sold_share_count.amount == Decimal("4.125000000000")


def test_dividend_recognition_posts_receivable_on_declaration_date() -> None:
    persistence = SessionPersistence()
    command = lifecycle_dividend()

    result = asyncio.run(
        InvestmentsSession(persistence, LedgerFacade)
        .recognize_received_dividend(command)
    )

    assert result.settlement_balance_kind is (
        InvestmentSettlementBalanceKind.DIVIDEND_RECEIVABLE
    )
    assert persistence.events == [
        "transaction:begin",
        "investments:dividend-recognition-replay",
        "investments:dividend-recognition-prepare",
        "ledger:recognize-dividend",
        "investments:dividend-recognition-complete",
        "transaction:commit",
    ]
    assert isinstance(persistence.posted_command.facts, InvestmentDividendFacts)
    assert persistence.posted_command.event_date == command.declared_date


def test_fund_distribution_recognition_posts_split_receivable() -> None:
    persistence = SessionPersistence()
    command = lifecycle_fund_distribution()

    result = asyncio.run(
        InvestmentsSession(persistence, LedgerFacade)
        .recognize_received_fund_distribution(command)
    )

    assert result.settlement_balance_kind is (
        InvestmentSettlementBalanceKind.FUND_DISTRIBUTION_RECEIVABLE
    )
    assert persistence.events == [
        "transaction:begin",
        "investments:fund-recognition-replay",
        "investments:fund-recognition-prepare",
        "ledger:recognize-fund-distribution",
        "investments:fund-recognition-complete",
        "transaction:commit",
    ]
    assert isinstance(
        persistence.posted_command.facts,
        InvestmentFundDistributionRecognitionFacts,
    )
    assert persistence.posted_command.facts.dividend_portion == Money.nok("50")
    assert persistence.posted_command.facts.interest_portion == Money.nok("50")


def test_year_end_measurement_posts_impairment_and_completes_atomically() -> None:
    persistence = SessionPersistence()
    command = lifecycle_year_end_measurement()

    result = asyncio.run(
        InvestmentsSession(persistence, LedgerFacade)
        .record_year_end_measurement(command)
    )

    assert result.measurement_id == command.measurement_id
    assert result.closing_book_value == Money.nok("82.50")
    assert result.tax_basis == Money.nok("100.00")
    assert result.tax_value == Money.nok("97.00")
    assert persistence.events == [
        "transaction:begin",
        "investments:measurement-replay",
        "investments:measurement-prepare",
        "ledger:measure-investment",
        "investments:measurement-complete",
        "transaction:commit",
    ]
    assert isinstance(
        persistence.posted_command.facts,
        InvestmentYearEndMeasurementFacts,
    )
    assert persistence.posted_command.primary_source.record_id.value == str(
        command.measurement_id
    )
    assert persistence.posted_command.facts.pre_measurement_book_value == Money.nok(
        "100.00"
    )
