from __future__ import annotations

from fastapi.testclient import TestClient

from talli_backend.main import create_app
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime

from talli_backend.modules.banking.public import (
    BankTransaction,
    BankTransactionId,
    BankTransactionPage,
    BankingPage,
)
from talli_backend.modules.investments.public import (
    AccountingEntryReference,
    AcquisitionLotPage,
    AcquisitionLotId,
    AcquisitionLotView,
    InvestmentAccountingClassification,
    InvestmentActionId,
    InvestmentKind,
    InvestmentActivityKind,
    InvestmentActivityPage,
    InvestmentActivityView,
    InvestmentCorrectionId,
    InvestmentCorrectionTargetKind,
    InvestmentCorrectionPage,
    InvestmentCorrectionView,
    InvestmentDocumentStatus,
    InvestmentEvidenceMode,
    InvestmentFactReference,
    InvestmentLifecycleEventPage,
    InvestmentLifecycleEventView,
    InvestmentLotHistoryStatus,
    InvestmentMeasurementRule,
    InvestmentPositionPage,
    InvestmentPositionId,
    InvestmentPositionView,
    InvestmentSaleLotFact,
    InvestmentTaxTreatment,
    InvestmentUnits,
    PreparedReceivedDividendFacts,
    PreparedReceivedFundDistributionFacts,
    PreparedEconomicEventCorrection,
    PreparedCashSettlementCorrection,
    PreparedSettledInvestmentCorrection,
    PreparedInvestmentCashSettlement,
    PreparedInvestmentMeasurementFacts,
    PreparedSharePurchaseRecognition,
    RecordedReceivedDividend,
    RecordedReceivedFundDistribution,
    RecordedInvestmentCorrection,
    RecordedInvestmentCashSettlement,
    RecordedInvestmentEconomicEvent,
    RecordedInvestmentYearEndMeasurement,
    InvestmentEconomicEventId,
    InvestmentSettlementId,
    InvestmentSettlementBalanceKind,
    InvestmentSourceCapability,
    InvestmentSourceReference,
    RecordedSharePurchase,
    PreparedSharePurchase,
    PreparedShareSaleFacts,
    RecordedShareSale,
    ShareSaleAllocationId,
    ShareSaleAllocationPage,
    ShareSaleAllocationView,
)
from talli_backend.modules.ledger.public import LedgerEntryId, LedgerEntryKind, PostedLedgerEntry
from talli_backend.shared.kernel import CompanyId, IncomeYear, LocalDate, Money, Timestamp

from test_investments import supported_purchase


class InvestmentsSessionStub:
    def __init__(
        self,
        settlement_balance_kind: InvestmentSettlementBalanceKind = (
            InvestmentSettlementBalanceKind.FUND_DISTRIBUTION_RECEIVABLE
        ),
    ) -> None:
        self.tokens: list[str] = []
        self.commands: list[object] = []
        self.settlement_balance_kind = settlement_balance_kind

    @property
    def actor_id(self):
        return supported_purchase().actor_id

    async def session(self, access_token: str):
        self.tokens.append(access_token)
        return self

    async def recognize_share_purchase(self, command):
        self.commands.append(command)
        return RecordedInvestmentEconomicEvent(
            event_id=command.event_id,
            position_id=InvestmentPositionId(
                "50000000-0000-0000-0000-000000000005"
            ),
            recognition_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000007"
            ),
            expected_settlement_amount=Money.nok("125.50"),
            settlement_balance_kind=(
                InvestmentSettlementBalanceKind.PURCHASE_PAYABLE
            ),
            replayed=False,
        )

    async def recognize_share_sale(self, command):
        self.commands.append(command)
        return RecordedInvestmentEconomicEvent(
            event_id=command.event_id,
            position_id=command.position_id,
            recognition_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000007"
            ),
            expected_settlement_amount=Money.nok("75.00"),
            settlement_balance_kind=(
                InvestmentSettlementBalanceKind.SALE_RECEIVABLE
            ),
            replayed=False,
        )

    async def recognize_received_dividend(self, command):
        self.commands.append(command)
        return RecordedInvestmentEconomicEvent(
            event_id=command.event_id,
            position_id=command.position_id,
            recognition_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000007"
            ),
            expected_settlement_amount=command.gross_amount,
            settlement_balance_kind=(
                InvestmentSettlementBalanceKind.DIVIDEND_RECEIVABLE
            ),
            replayed=False,
        )

    async def record_year_end_measurement(self, command):
        self.commands.append(command)
        return RecordedInvestmentYearEndMeasurement(
            measurement_id=command.measurement_id,
            position_id=command.position_id,
            accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000047"
            ),
            measurement_rule=(
                InvestmentMeasurementRule.LOWER_OF_COST_AND_FAIR_VALUE
            ),
            closing_book_value=Money.nok("82.50"),
            tax_basis=Money.nok("100.00"),
            tax_value=command.tax_value,
            replayed=False,
        )

    async def recognize_received_fund_distribution(self, command):
        self.commands.append(command)
        return RecordedInvestmentEconomicEvent(
            event_id=command.event_id,
            position_id=command.position_id,
            recognition_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000007"
            ),
            expected_settlement_amount=Money.nok("100.00"),
            settlement_balance_kind=self.settlement_balance_kind,
            replayed=False,
        )

    async def settle_investment_cash(self, command):
        self.commands.append(command)
        return RecordedInvestmentCashSettlement(
            settlement_id=command.settlement_id,
            event_id=command.event_id,
            settlement_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000017"
            ),
            replayed=False,
        )

    async def correct_investment(self, command):
        self.commands.append(command)
        return RecordedInvestmentCorrection(
            correction_id=command.correction_id,
            target_kind=command.target_kind,
            original_record_id=command.original_record_id,
            replacement_record_id=command.replacement.event_id,
            reversal_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000027"
            ),
            replacement_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000037"
            ),
            replayed=False,
        )

    async def correct_settled_investment(
        self, event_command, settlement_command
    ):
        self.commands.extend((event_command, settlement_command))
        return RecordedInvestmentCorrection(
            correction_id=event_command.correction_id,
            target_kind=event_command.target_kind,
            original_record_id=event_command.original_record_id,
            replacement_record_id=event_command.replacement.event_id,
            reversal_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000027"
            ),
            replacement_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000037"
            ),
            replayed=False,
        )

    async def record_compatibility_action(self, recognition, settlement):
        if hasattr(recognition, "purchase_amount"):
            event = await self.recognize_share_purchase(recognition)
        elif hasattr(recognition, "proceeds"):
            event = await self.recognize_share_sale(recognition)
        elif hasattr(recognition, "fund_name"):
            event = await self.recognize_received_fund_distribution(recognition)
        else:
            event = await self.recognize_received_dividend(recognition)
        cash = (
            await self.settle_investment_cash(settlement)
            if settlement is not None
            else None
        )
        return event, cash

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def claim_transaction_for_external_action(
        self, command, *, accounting_entry_id
    ):
        self.commands.append(command)

    async def get_investment_correction_replay(self, command):
        return None

    async def get_share_purchase_recognition_replay(self, command):
        return None

    async def prepare_share_purchase_recognition(
        self, command, *, capitalized_cost, evidence_digest, calculation_id
    ):
        self.commands.append(command)
        return PreparedSharePurchaseRecognition(
            position_id=InvestmentPositionId(
                "50000000-0000-0000-0000-000000000005"
            ),
            lot_id=AcquisitionLotId(
                "60000000-0000-0000-0000-000000000006"
            ),
            position_created=True,
            investment_name=command.investment_name,
            accounting_classification=command.accounting_classification,
            acquisition_cost=capitalized_cost,
            expected_settlement_amount=capitalized_cost,
            settlement_balance_kind=(
                InvestmentSettlementBalanceKind.PURCHASE_PAYABLE
            ),
            evidence_digest=evidence_digest,
            calculation_id=calculation_id,
        )

    async def complete_share_purchase_recognition(
        self, command, *, prepared, accounting_entry_id
    ):
        return RecordedInvestmentEconomicEvent(
            event_id=command.event_id,
            position_id=prepared.position_id,
            recognition_accounting_entry_id=accounting_entry_id,
            expected_settlement_amount=prepared.expected_settlement_amount,
            settlement_balance_kind=prepared.settlement_balance_kind,
            replayed=False,
        )

    async def get_share_sale_recognition_replay(self, command):
        return None

    async def prepare_share_sale_recognition(
        self, command, *, net_proceeds, evidence_digest
    ):
        self.commands.append(command)
        return PreparedShareSaleFacts(
            position_id=command.position_id,
            investment_name="Example AS",
            investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
            accounting_classification=(
                InvestmentAccountingClassification.OTHER_LONG_TERM
            ),
            fifo_book_cost_basis_reduction=Money.nok("50.20"),
            fifo_tax_basis_reduction=Money.nok("50.20"),
            lot_facts=(InvestmentSaleLotFact(
                lot_id=AcquisitionLotId(
                    "60000000-0000-0000-0000-000000000006"
                ),
                allocation_order=1,
                acquisition_date=command.sale_date,
                allocated_share_count=command.sold_share_count,
                allocated_book_cost_basis=Money.nok("50.20"),
                allocated_tax_basis=Money.nok("50.20"),
                acquisition_year_fund_equity_ratio_basis_points=None,
            ),),
        )

    async def complete_share_sale_recognition(
        self, command, *, prepared, accounting_entry_id
    ):
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

    async def get_received_fund_distribution_recognition_replay(self, command):
        return None

    async def prepare_received_fund_distribution_recognition(
        self, command, *, evidence_digest
    ):
        self.commands.append(command)
        return PreparedReceivedFundDistributionFacts(
            position_id=command.position_id,
            investment_name="Norsk Kombinasjonsfond",
            investment_kind=InvestmentKind.NORWEGIAN_EQUITY_FUND,
        )

    async def complete_received_fund_distribution_recognition(
        self, command, *, prepared, accounting_entry_id
    ):
        return RecordedInvestmentEconomicEvent(
            event_id=command.event_id,
            position_id=prepared.position_id,
            recognition_accounting_entry_id=accounting_entry_id,
            expected_settlement_amount=command.gross_amount,
            settlement_balance_kind=self.settlement_balance_kind,
            replayed=False,
        )

    async def get_cash_settlement_replay(self, command):
        return None

    async def get_year_end_measurement_replay(self, command):
        return None

    async def prepare_year_end_measurement(self, command, *, evidence_digest):
        self.commands.append(command)
        return PreparedInvestmentMeasurementFacts(
            position_id=command.position_id,
            investment_name="Norsk Notert ASA",
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

    async def prepare_cash_settlement(self, command, *, evidence_digest):
        self.commands.append(command)
        return PreparedInvestmentCashSettlement(
            event_id=command.event_id,
            recognition_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000007"
            ),
            settlement_balance_kind=self.settlement_balance_kind,
            amount=command.amount,
            event_fact_sha256="e" * 64,
            evidence_digest=evidence_digest,
        )
    async def complete_cash_settlement(
        self, command, *, prepared, accounting_entry_id
    ):
        return RecordedInvestmentCashSettlement(
            settlement_id=command.settlement_id,
            event_id=command.event_id,
            settlement_accounting_entry_id=accounting_entry_id,
            replayed=False,
        )

    async def prepare_investment_correction(
        self, command, *, evidence_digest, replacement_evidence_digest
    ):
        self.commands.append(command)
        assert replacement_evidence_digest == command.replacement.evidence.digest()
        return PreparedEconomicEventCorrection(
            original_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000017"
            ),
            original_position_id=command.replacement.position_id,
            evidence_digest=evidence_digest,
        )

    async def prepare_settled_investment_correction(
        self, event_command, settlement_command, **digests
    ):
        self.commands.extend((event_command, settlement_command))
        return PreparedSettledInvestmentCorrection(
            event=PreparedEconomicEventCorrection(
                original_accounting_entry_id=AccountingEntryReference(
                    "70000000-0000-0000-0000-000000000017"
                ),
                original_position_id=event_command.replacement.position_id,
                evidence_digest=digests["event_evidence_digest"],
            ),
            settlement=PreparedCashSettlementCorrection(
                original_accounting_entry_id=AccountingEntryReference(
                    "70000000-0000-0000-0000-000000000018"
                ),
                original_settlement_id=settlement_command.original_record_id,
                event_id=event_command.replacement.event_id,
                recognition_accounting_entry_id=AccountingEntryReference(
                    "70000000-0000-0000-0000-000000000017"
                ),
                settlement_balance_kind=(
                    InvestmentSettlementBalanceKind.DIVIDEND_RECEIVABLE
                ),
                amount=settlement_command.replacement.amount,
                event_fact_sha256="f" * 64,
                replacement_evidence_digest=digests[
                    "settlement_replacement_evidence_digest"
                ],
                evidence_digest=digests["settlement_evidence_digest"],
                original_activity_kind=event_command.original_activity_kind,
            ),
        )

    async def complete_settled_investment_correction(
        self, event_command, settlement_command, **_facts
    ):
        return RecordedInvestmentCorrection(
            correction_id=event_command.correction_id,
            target_kind=event_command.target_kind,
            original_record_id=event_command.original_record_id,
            replacement_record_id=event_command.replacement.event_id,
            reversal_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000027"
            ),
            replacement_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000037"
            ),
            replayed=False,
        )

    async def complete_investment_correction(
        self, command, *, prepared, replacement_accounting_entry_id
    ):
        return RecordedInvestmentCorrection(
            correction_id=command.correction_id,
            target_kind=command.target_kind,
            original_record_id=command.original_record_id,
            replacement_record_id=command.replacement.event_id,
            reversal_accounting_entry_id=AccountingEntryReference(
                "70000000-0000-0000-0000-000000000027"
            ),
            replacement_accounting_entry_id=replacement_accounting_entry_id,
            replayed=False,
        )

    async def get_received_dividend_recognition_replay(self, command):
        return None

    async def prepare_received_dividend_recognition(
        self, command, *, evidence_digest
    ):
        self.commands.append(command)
        return PreparedReceivedDividendFacts(
            position_id=command.position_id,
            investment_name="Example AS",
            investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
        )

    async def complete_received_dividend_recognition(
        self, command, *, prepared, accounting_entry_id
    ):
        return RecordedInvestmentEconomicEvent(
            event_id=command.event_id,
            position_id=command.position_id,
            recognition_accounting_entry_id=accounting_entry_id,
            expected_settlement_amount=command.gross_amount,
            settlement_balance_kind=(
                InvestmentSettlementBalanceKind.DIVIDEND_RECEIVABLE
            ),
            replayed=False,
        )

    async def get_share_purchase_replay(self, command):
        return None

    async def prepare_share_purchase(
        self, command, *, capitalized_cost, evidence_digest, calculation_id
    ):
        self.commands.append(command)
        return PreparedSharePurchase(
            position_id=InvestmentPositionId(
                "50000000-0000-0000-0000-000000000005"
            ),
            lot_id=AcquisitionLotId("60000000-0000-0000-0000-000000000006"),
            position_created=True,
            investment_name=command.investment_name,
            accounting_classification=command.accounting_classification,
            purchase_amount=capitalized_cost,
            evidence_digest=evidence_digest,
            calculation_id=calculation_id,
        )

    async def post_entry(self, command, **_facts):
        return PostedLedgerEntry(
            entry_id=LedgerEntryId("70000000-0000-0000-0000-000000000007"),
            company_id=command.company_id,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.SHARE_PURCHASE,
            posted_at=Timestamp(datetime(2026, 8, 31, tzinfo=UTC)),
            replayed=False,
        )

    async def record_received_dividend_decision(self, command, **facts):
        return await self.post_entry(command, **facts)

    async def complete_share_purchase(
        self, command, *, prepared, accounting_entry_id
    ):
        return RecordedSharePurchase(
            action_id=command.action_id,
            position_id=prepared.position_id,
            lot_id=prepared.lot_id,
            accounting_entry_id=accounting_entry_id,
            position_created=True,
            replayed=False,
        )

    async def get_share_sale_replay(self, command):
        return None

    async def prepare_share_sale(self, command, *, net_proceeds, evidence_digest):
        self.commands.append(command)
        return PreparedShareSaleFacts(
            position_id=command.position_id,
            investment_name="Example AS",
            investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
            accounting_classification=InvestmentAccountingClassification.OTHER_LONG_TERM,
            fifo_book_cost_basis_reduction=Money.nok("50.20"),
            fifo_tax_basis_reduction=Money.nok("50.20"),
            lot_facts=(InvestmentSaleLotFact(
                lot_id=AcquisitionLotId("60000000-0000-0000-0000-000000000006"),
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
        return RecordedShareSale(
            action_id=command.action_id,
            position_id=command.position_id,
            accounting_entry_id=accounting_entry_id,
            replayed=False,
        )

    async def get_received_dividend_replay(self, command):
        return None

    async def prepare_received_dividend(
        self, command, *, evidence_digest
    ):
        self.commands.append(command)
        return PreparedReceivedDividendFacts(
            position_id=command.position_id,
            investment_name="Example AS",
            investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
        )

    async def complete_received_dividend(
        self, command, *, prepared, accounting_entry_id
    ):
        return RecordedReceivedDividend(
            action_id=command.action_id,
            position_id=command.position_id,
            accounting_entry_id=accounting_entry_id,
            taxable_add_back=prepared.taxable_add_back,
            replayed=False,
        )

    async def get_received_fund_distribution_replay(self, command):
        return None

    async def prepare_received_fund_distribution(self, command, *, evidence_digest):
        self.commands.append(command)
        return PreparedReceivedFundDistributionFacts(
            position_id=command.position_id,
            investment_name="Norsk Kombinasjonsfond",
            investment_kind=InvestmentKind.NORWEGIAN_EQUITY_FUND,
        )

    async def complete_received_fund_distribution(
        self, command, *, prepared, accounting_entry_id
    ):
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

    async def list_positions(self, **_query):
        return InvestmentPositionPage(
            items=(InvestmentPositionView(
                position_id=InvestmentPositionId("50000000-0000-0000-0000-000000000005"),
                company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
                investment_key="example-as", name="Example AS",
                kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
                accounting_classification=InvestmentAccountingClassification.OTHER_LONG_TERM,
                tax_treatment=InvestmentTaxTreatment.EXEMPTION_METHOD,
                org_number="123456789", fund_equity_ratio_basis_points=None,
                fund_tax_statement_reference=None,
                share_count=InvestmentUnits.of("10.125"),
                cost_basis=Money.nok("125.50"),
                tax_basis=Money.nok("125.50"),
                lot_history_status=InvestmentLotHistoryStatus.COMPLETE,
                movement_count=1,
                movements=({
                    "movement_type": "purchase_recognition",
                    "movement_date": "2026-04-15",
                    "share_delta": "10.125000000000",
                },),
                created_by=self.actor_id,
                created_at=Timestamp(datetime(2026, 4, 15, tzinfo=UTC)),
                updated_at=Timestamp(datetime(2026, 4, 15, tzinfo=UTC)),
            ),),
            next_cursor=None,
            has_more=False,
        )

    async def list_corrections(self, **_query):
        return InvestmentCorrectionPage(
            items=(InvestmentCorrectionView(
                correction_id=InvestmentCorrectionId(
                    "40000000-0000-0000-0000-000000000042"
                ),
                company_id=CompanyId(
                    "10000000-0000-0000-0000-000000000001"
                ),
                income_year=IncomeYear(2026),
                target_kind=InvestmentCorrectionTargetKind.ECONOMIC_EVENT,
                original_record_id=InvestmentEconomicEventId(
                    str(supported_purchase().event_id)
                ),
                original_activity_kind=InvestmentActivityKind.SHARE_PURCHASE,
                reversal_accounting_entry_id=AccountingEntryReference(
                    "70000000-0000-0000-0000-000000000027"
                ),
                replacement_record_id=InvestmentEconomicEventId(
                    "40000000-0000-0000-0000-000000000044"
                ),
                replacement_activity_kind=InvestmentActivityKind.SHARE_PURCHASE,
                replacement_accounting_entry_id=AccountingEntryReference(
                    "70000000-0000-0000-0000-000000000037"
                ),
                reason="Correct purchase amount",
                document_facts=(),
                legacy_bank_transaction_id=None,
                legacy_document_id=None,
                legacy_document_status=(
                    InvestmentDocumentStatus.MISSING_ACCEPTED_WARNING
                ),
                legacy=True,
                evidence_mode=InvestmentEvidenceMode.MANUAL_FALLBACK,
                evidence_reference="correction-owner-evidence",
                evidence_digest="c" * 64,
                owner_attested=True,
                created_by=self.actor_id,
                created_at=Timestamp(datetime(2026, 8, 31, tzinfo=UTC)),
            ),),
            next_cursor=None,
            has_more=False,
        )

    async def list_activity(self, **_query):
        return InvestmentActivityPage(
            items=(InvestmentActivityView(
                activity_id=InvestmentActionId(str(supported_purchase().event_id)),
                company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
                income_year=IncomeYear(2026),
                activity_kind=InvestmentActivityKind.DIVIDEND_RECEIVED,
                action_date=LocalDate(datetime(2026, 4, 15, tzinfo=UTC).date()),
                position_id=InvestmentPositionId("50000000-0000-0000-0000-000000000005"),
                investment_key="example-as",
                investment_name="Example AS",
                investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
                accounting_classification=InvestmentAccountingClassification.OTHER_LONG_TERM,
                tax_treatment=InvestmentTaxTreatment.EXEMPTION_METHOD,
                org_number="123456789",
                fund_equity_ratio_basis_points=None,
                fund_tax_statement_reference=None,
                acquisition_lot_id=None,
                share_count=InvestmentUnits.of("10.125"),
                purchase_amount=None,
                transaction_costs=None,
                capitalized_cost=None,
                sold_share_count=InvestmentUnits.of("4.0625"),
                proceeds=None,
                net_proceeds=None,
                fifo_cost_basis_reduction=None,
                fifo_tax_basis_reduction=None,
                remaining_share_count=InvestmentUnits.of("6.0625"),
                remaining_cost_basis=None,
                remaining_tax_basis=None,
                paying_company_name="Example AS",
                declared_date=LocalDate(datetime(2026, 4, 1, tzinfo=UTC).date()),
                gross_amount=Money.nok("125.50"),
                taxable_add_back=Money.nok("3.77"),
                gain_or_loss=None,
                book_gain_or_loss=None,
                tax_gain_or_loss=None,
                exempt_gain=None,
                taxable_gain=None,
                non_deductible_loss=None,
                deductible_loss=None,
                lawful_dividend_confirmed=True,
                group_exception_claimed=False,
                group_exception_applied=False,
                year_end_ownership_basis_points=None,
                year_end_voting_basis_points=None,
                group_evidence_reference=None,
                fund_name=None,
                entitlement_date=None,
                opening_fund_equity_ratio_basis_points=None,
                dividend_portion=None,
                interest_portion=None,
                total_taxable_income=None,
                bank_transaction_id=None,
                document_id=None,
                document_status=InvestmentDocumentStatus.MISSING_ACCEPTED_WARNING,
                evidence_mode=InvestmentEvidenceMode.MANUAL_FALLBACK,
                evidence_reference="dividend-advice-example",
                evidence_digest="a" * 64,
                calculation_id="b" * 64,
                owner_attested=True,
                accounting_entry_id=AccountingEntryReference(
                    "70000000-0000-0000-0000-000000000007"
                ),
                created_by=self.actor_id,
                created_at=Timestamp(datetime(2026, 4, 15, tzinfo=UTC)),
            ),),
            next_cursor=None,
            has_more=False,
        )

    async def list_lifecycle_events(self, **_query):
        return InvestmentLifecycleEventPage(
            items=(InvestmentLifecycleEventView(
                event_id=InvestmentEconomicEventId(
                    "40000000-0000-0000-0000-000000000024"
                ),
                company_id=CompanyId(
                    "10000000-0000-0000-0000-000000000001"
                ),
                income_year=IncomeYear(2026),
                activity_kind=InvestmentActivityKind.SHARE_PURCHASE,
                recognition_date=LocalDate(
                    datetime(2026, 4, 15, tzinfo=UTC).date()
                ),
                position_id=InvestmentPositionId(
                    "50000000-0000-0000-0000-000000000005"
                ),
                investment_key="example-as",
                investment_name="Example AS",
                investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
                accounting_classification=(
                    InvestmentAccountingClassification.OTHER_LONG_TERM
                ),
                tax_treatment=InvestmentTaxTreatment.EXEMPTION_METHOD,
                org_number="123456789",
                fund_equity_ratio_basis_points=None,
                fund_tax_statement_reference=None,
                acquisition_lot_id=AcquisitionLotId(
                    "60000000-0000-0000-0000-000000000006"
                ),
                position_created=True,
                share_count=InvestmentUnits.of("10.125"),
                purchase_amount=Money.nok("125.50"),
                transaction_costs=Money.nok("0"),
                capitalized_cost=Money.nok("125.50"),
                sold_share_count=None,
                proceeds=None,
                net_proceeds=None,
                fifo_cost_basis_reduction=None,
                fifo_tax_basis_reduction=None,
                remaining_share_count=None,
                remaining_cost_basis=None,
                remaining_tax_basis=None,
                book_gain_or_loss=None,
                tax_gain_or_loss=None,
                exempt_gain=None,
                taxable_gain=None,
                non_deductible_loss=None,
                deductible_loss=None,
                paying_company_name=None,
                lawful_dividend_confirmed=None,
                group_exception_claimed=None,
                group_exception_applied=None,
                year_end_ownership_basis_points=None,
                year_end_voting_basis_points=None,
                group_evidence_reference=None,
                fund_name=None,
                entitlement_date=None,
                opening_fund_equity_ratio_basis_points=None,
                gross_amount=None,
                taxable_add_back=None,
                dividend_portion=None,
                interest_portion=None,
                total_taxable_income=None,
                expected_settlement_amount=Money.nok("125.50"),
                settlement_balance_kind=(
                    InvestmentSettlementBalanceKind.PURCHASE_PAYABLE
                ),
                recognition_accounting_entry_id=AccountingEntryReference(
                    "70000000-0000-0000-0000-000000000007"
                ),
                document_facts=(InvestmentFactReference(
                    capability=InvestmentSourceCapability.DOCUMENTS,
                    record_id=InvestmentSourceReference(
                        "80000000-0000-0000-0000-000000000008"
                    ),
                    revision=1,
                    fact_sha256="a" * 64,
                ),),
                evidence_mode=InvestmentEvidenceMode.LINKED_SOURCES,
                evidence_reference="share-purchase-contract",
                evidence_digest="b" * 64,
                calculation_id="c" * 64,
                owner_attested=False,
                settlement_id=None,
                settlement_date=None,
                settlement_amount=None,
                bank_fact=None,
                settlement_accounting_entry_id=None,
                created_by=self.actor_id,
                created_at=Timestamp(datetime(2026, 4, 15, tzinfo=UTC)),
            ),),
            next_cursor=None,
            has_more=False,
        )

    async def list_acquisition_lots(self, **_query):
        return AcquisitionLotPage(
            items=(AcquisitionLotView(
                lot_id=AcquisitionLotId("60000000-0000-0000-0000-000000000006"),
                company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
                position_id=InvestmentPositionId("50000000-0000-0000-0000-000000000005"),
                acquisition_action_id=InvestmentActionId(str(supported_purchase().event_id)),
                acquisition_date=LocalDate(datetime(2026, 4, 15, tzinfo=UTC).date()),
                original_share_count=InvestmentUnits.of("10.125"),
                remaining_share_count=InvestmentUnits.of("6.0625"),
                original_cost_basis=Money.nok("125.50"),
                remaining_cost_basis=Money.nok("125.50"),
                original_tax_basis=Money.nok("125.50"),
                remaining_tax_basis=Money.nok("125.50"),
                acquisition_year_fund_equity_ratio_basis_points=None,
                fund_tax_statement_reference=None,
                created_by=self.actor_id,
                created_at=Timestamp(datetime(2026, 4, 15, tzinfo=UTC)),
            ),),
            next_cursor=None,
            has_more=False,
        )

    async def list_share_sale_allocations(self, **_query):
        return ShareSaleAllocationPage(
            items=(ShareSaleAllocationView(
                allocation_id=ShareSaleAllocationId(
                    "80000000-0000-0000-0000-000000000008"
                ),
                company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
                position_id=InvestmentPositionId(
                    "50000000-0000-0000-0000-000000000005"
                ),
                lot_id=AcquisitionLotId(
                    "60000000-0000-0000-0000-000000000006"
                ),
                sale_action_id=InvestmentActionId(str(supported_purchase().event_id)),
                allocation_order=1,
                acquisition_date=LocalDate(
                    datetime(2026, 4, 15, tzinfo=UTC).date()
                ),
                allocated_share_count=InvestmentUnits.of("4.0625"),
                allocated_cost_basis=Money.nok("50.20"),
                allocated_book_cost_basis=Money.nok("50.20"),
                allocated_tax_basis=Money.nok("50.20"),
                allocated_net_proceeds=Money.nok("60.00"),
                average_fund_equity_ratio_basis_points=None,
                tax_gain_or_loss=Money.nok("9.80"),
                exempt_gain=Money.nok("9.80"),
                taxable_gain=Money.nok("0"),
                non_deductible_loss=Money.nok("0"),
                deductible_loss=Money.nok("0"),
                created_by=self.actor_id,
                created_at=Timestamp(datetime(2026, 4, 15, tzinfo=UTC)),
            ),),
            next_cursor=None,
            has_more=False,
        )


class BankingSessionStub:
    def __init__(
        self,
        *,
        transaction_id: str = "70000000-0000-0000-0000-000000000007",
        transaction_date: str = "2026-05-15",
        amount: str = "100.00",
        source_hash: str = "b" * 64,
        matched: bool = False,
    ) -> None:
        self.tokens: list[str] = []
        self.transaction = BankTransaction(
            transaction_id=BankTransactionId(transaction_id),
            company_id=CompanyId(
                "10000000-0000-0000-0000-000000000001"
            ),
            income_year=IncomeYear(2026),
            transaction_date=LocalDate(date.fromisoformat(transaction_date)),
            text="Investment cash settlement",
            amount=Money.nok(amount),
            balance=None,
            source_hash=source_hash,
            matched_entry_id=(
                AccountingEntryReference(
                    "70000000-0000-0000-0000-000000000099"
                )
                if matched
                else None
            ),
            matched_action_reference=None,
            warning_accepted=False,
            suggestion=None,
            created_at=Timestamp(datetime(2026, 5, 15, tzinfo=UTC)),
        )

    @property
    def actor_id(self):
        return supported_purchase().actor_id

    async def session(self, access_token: str):
        self.tokens.append(access_token)
        return self

    async def list_transactions(self, **_query):
        return BankTransactionPage(
            items=(self.transaction,),
            page=BankingPage(next_cursor=None, has_more=False),
        )


def test_investment_mutation_http_contract_retains_deprecated_overlap_routes() -> None:
    application = create_app(investments_session_factory=InvestmentsSessionStub())
    paths = application.openapi()["paths"]

    legacy_operations = {
        "/api/v1/investments/share-purchases": "investmentsRecordSharePurchase",
        "/api/v1/investments/share-sales": "investmentsRecordShareSale",
        "/api/v1/investments/received-dividends": (
            "investmentsRecordReceivedDividend"
        ),
        "/api/v1/investments/received-fund-distributions": (
            "investmentsRecordReceivedFundDistribution"
        ),
    }
    for path, operation in legacy_operations.items():
        assert paths[path]["post"]["operationId"] == operation
        assert paths[path]["post"]["deprecated"] is True

    expected_operations = {
        "/api/v1/investments/share-purchase-recognitions": (
            "investmentsRecognizeSharePurchase"
        ),
        "/api/v1/investments/share-sale-recognitions": (
            "investmentsRecognizeShareSale"
        ),
        "/api/v1/investments/received-dividend-recognitions": (
            "investmentsRecognizeReceivedDividend"
        ),
        "/api/v1/investments/received-fund-distribution-recognitions": (
            "investmentsRecognizeReceivedFundDistribution"
        ),
        "/api/v1/investments/cash-settlements": "investmentsSettleCash",
    }
    assert {
        path: paths[path]["post"]["operationId"]
        for path in expected_operations
    } == expected_operations


def test_deprecated_share_purchase_wire_delegates_to_lifecycle_recognition() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(investments_session_factory=sessions))
    action_id = "40000000-0000-0000-0000-000000000024"

    response = client.post(
        "/api/v1/investments/share-purchases",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": "30000000-0000-4000-8000-000000000083",
            "X-Request-ID": "investments-purchase-compatibility",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "actionId": action_id,
            "investmentKey": "private:123456789:ordinary",
            "investmentName": "Example AS",
            "investmentKind": "norwegian_private_company",
            "accountingClassification": "other_long_term",
            "taxTreatment": "fritaksmetoden",
            "acquisitionDate": "2026-04-15",
            "shareCount": 10,
            "purchaseAmount": {"amount": "125.50", "currency": "NOK"},
            "transactionCosts": {"amount": "0.00", "currency": "NOK"},
            "orgNumber": "123456789",
            "fundEquityRatioBasisPoints": None,
            "fundTaxStatementReference": None,
            "tradingProfile": "low_volume_non_active",
            "nonActiveTradingConfirmed": True,
            "shareClassCode": "ordinary",
            "singleShareClassConfirmed": True,
            "equalShareRightsConfirmed": True,
            "unusualShareRightsAbsentConfirmed": True,
            "evidenceMode": "manual_fallback",
            "evidenceReference": "broker-note-example-purchase",
            "ownerAttested": True,
            "bankTransactionId": None,
            "documentId": "80000000-0000-0000-0000-000000000008",
            "documentStatus": "attached",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json() == {
        "actionId": action_id,
        "positionId": "50000000-0000-0000-0000-000000000005",
        "acquisitionLotId": "60000000-0000-0000-0000-000000000006",
        "accountingEntryId": "70000000-0000-0000-0000-000000000007",
        "positionCreated": True,
        "replayed": False,
    }
    assert sessions.tokens == ["owner-token"]
    assert len(sessions.commands) == 1
    recognition = sessions.commands[0]
    assert recognition.event_id == InvestmentEconomicEventId(action_id)
    assert recognition.share_count == InvestmentUnits.of("10")
    assert recognition.evidence.bank_fact is None


def lifecycle_document_evidence(reference: str) -> dict[str, object]:
    return {
        "evidenceMode": "linked_sources",
        "evidenceReference": reference,
        "ownerAttested": False,
        "documentFacts": [{
            "capability": "DOCUMENTS",
            "recordId": "80000000-0000-0000-0000-000000000008",
            "revision": 1,
            "factSha256": "d" * 64,
        }],
        "bankFact": None,
    }


def test_settled_wrong_amount_correction_is_one_http_operation() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(investments_session_factory=sessions))
    event_correction_id = "40000000-0000-0000-0000-000000000142"
    settlement_correction_id = "40000000-0000-0000-0000-000000000143"
    replacement_event_id = "40000000-0000-0000-0000-000000000144"
    replacement_settlement_id = "40000000-0000-0000-0000-000000000145"
    response = client.post(
        "/api/v1/investments/corrections",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": event_correction_id,
            "X-Request-ID": "settled-wrong-amount-correction",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "correctionId": event_correction_id,
            "targetKind": "economic_event",
            "originalRecordId": "40000000-0000-0000-0000-000000000140",
            "originalActivityKind": "dividend_received",
            "correctionDate": "2026-09-01",
            "reason": "Correct settled dividend amount",
            **lifecycle_document_evidence("correction evidence"),
            "replacement": {
                "replacementKind": "dividend_received",
                "companyId": "10000000-0000-0000-0000-000000000001",
                "incomeYear": 2026,
                "eventId": replacement_event_id,
                "positionId": "50000000-0000-0000-0000-000000000005",
                "payingCompanyName": "Example AS",
                "declaredDate": "2026-08-20",
                "grossAmount": {"amount": "130.00", "currency": "NOK"},
                "lawfulDividendConfirmed": True,
                "groupExceptionClaimed": False,
                "yearEndOwnershipBasisPoints": None,
                "yearEndVotingBasisPoints": None,
                "groupEvidenceReference": None,
                **lifecycle_document_evidence("replacement evidence"),
            },
            "originalSettlementId": "40000000-0000-0000-0000-000000000141",
            "settlementCorrectionId": settlement_correction_id,
            "replacementSettlement": {
                "replacementKind": "cash_settlement",
                "companyId": "10000000-0000-0000-0000-000000000001",
                "incomeYear": 2026,
                "settlementId": replacement_settlement_id,
                "eventId": replacement_event_id,
                "settlementDate": "2026-09-01",
                "amount": {"amount": "130.00", "currency": "NOK"},
                "evidenceMode": "linked_sources",
                "evidenceReference": "corrected bank fact",
                "ownerAttested": False,
                "documentFacts": [],
                "bankFact": {
                    "capability": "BANKING",
                    "recordId": "70000000-0000-0000-0000-000000000007",
                    "revision": 1,
                    "factSha256": "b" * 64,
                },
            },
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["correctionId"] == event_correction_id
    assert len(sessions.commands) >= 2
    assert sessions.commands[1].replacement.amount == Money.nok("130.00")


def assert_recognition_response(
    response, *, event_id: str, position_id: str, amount: str, balance_kind: str
) -> None:
    assert response.status_code == 201, response.text
    assert response.json() == {
        "eventId": event_id,
        "positionId": position_id,
        "recognitionAccountingEntryId": (
            "70000000-0000-0000-0000-000000000007"
        ),
        "expectedSettlementAmount": {"amount": amount, "currency": "NOK"},
        "settlementBalanceKind": balance_kind,
        "replayed": False,
    }


def test_supported_share_purchase_uses_recognition_http_contract() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(investments_session_factory=sessions))
    event_id = "40000000-0000-0000-0000-000000000004"

    response = client.post(
        "/api/v1/investments/share-purchase-recognitions",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": "30000000-0000-4000-8000-000000000003",
            "X-Request-ID": "investments-purchase-recognition",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "eventId": event_id,
            "investmentKey": "private:123456789:ordinary",
            "investmentName": "Example AS",
            "investmentKind": "norwegian_private_company",
            "accountingClassification": "other_long_term",
            "acquisitionDate": "2026-04-15",
            "shareCount": "10.125",
            "purchaseAmount": {"amount": "125.50", "currency": "NOK"},
            "transactionCosts": {"amount": "0.00", "currency": "NOK"},
            "orgNumber": "123456789",
            "fundEquityRatioBasisPoints": None,
            "fundTaxStatementReference": None,
            "tradingProfile": "low_volume_non_active",
            "nonActiveTradingConfirmed": True,
            "shareClassCode": "ordinary",
            "singleShareClassConfirmed": True,
            "equalShareRightsConfirmed": True,
            "unusualShareRightsAbsentConfirmed": True,
            **lifecycle_document_evidence("broker-note-example-purchase"),
        },
    )

    assert_recognition_response(
        response,
        event_id=event_id,
        position_id="50000000-0000-0000-0000-000000000005",
        amount="125.50",
        balance_kind="purchase_payable",
    )
    assert sessions.tokens == ["owner-token"]
    assert len(sessions.commands) == 1
    assert sessions.commands[0].investment_name == "Example AS"
    assert sessions.commands[0].share_count == InvestmentUnits.of("10.125")


def test_supported_share_sale_uses_recognition_http_contract() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(investments_session_factory=sessions))
    event_id = "40000000-0000-0000-0000-000000000014"
    position_id = "50000000-0000-0000-0000-000000000015"

    response = client.post(
        "/api/v1/investments/share-sale-recognitions",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": "30000000-0000-4000-8000-000000000013",
            "X-Request-ID": "investments-sale-recognition",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "eventId": event_id,
            "positionId": position_id,
            "saleDate": "2026-06-01",
            "soldShareCount": "4.0625",
            "proceeds": {"amount": "75.00", "currency": "NOK"},
            "transactionCosts": {"amount": "0.00", "currency": "NOK"},
            "saleYearFundEquityRatioBasisPoints": None,
            "fundTaxStatementReference": None,
            **lifecycle_document_evidence("broker-note-example-sale"),
        },
    )

    assert_recognition_response(
        response,
        event_id=event_id,
        position_id=position_id,
        amount="75.00",
        balance_kind="sale_receivable",
    )
    assert sessions.commands[0].sold_share_count == InvestmentUnits.of("4.0625")


def test_supported_received_dividend_uses_recognition_http_contract() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(investments_session_factory=sessions))
    event_id = "40000000-0000-0000-0000-000000000024"
    position_id = "50000000-0000-0000-0000-000000000025"

    response = client.post(
        "/api/v1/investments/received-dividend-recognitions",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": "30000000-0000-4000-8000-000000000023",
            "X-Request-ID": "investments-dividend-recognition",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "eventId": event_id,
            "positionId": position_id,
            "payingCompanyName": "Example AS",
            "declaredDate": "2026-04-01",
            "grossAmount": {"amount": "125.50", "currency": "NOK"},
            "lawfulDividendConfirmed": True,
            "groupExceptionClaimed": False,
            "yearEndOwnershipBasisPoints": None,
            "yearEndVotingBasisPoints": None,
            "groupEvidenceReference": None,
            **lifecycle_document_evidence("dividend-decision-example"),
        },
    )

    assert_recognition_response(
        response,
        event_id=event_id,
        position_id=position_id,
        amount="125.50",
        balance_kind="dividend_receivable",
    )
    assert sessions.commands[0].paying_company_name == "Example AS"


def test_supported_fund_distribution_uses_recognition_http_contract() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(investments_session_factory=sessions))
    event_id = "40000000-0000-0000-0000-000000000034"
    position_id = "50000000-0000-0000-0000-000000000035"

    response = client.post(
        "/api/v1/investments/received-fund-distribution-recognitions",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": "30000000-0000-4000-8000-000000000033",
            "X-Request-ID": "investments-fund-distribution-recognition",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "eventId": event_id,
            "positionId": position_id,
            "fundName": "Norsk Kombinasjonsfond",
            "entitlementDate": "2026-05-01",
            "grossAmount": {"amount": "100.00", "currency": "NOK"},
            "openingFundEquityRatioBasisPoints": 5000,
            "fundTaxStatementReference": "provider-tax-statement-2026-r1",
            **lifecycle_document_evidence("fund-entitlement-example"),
        },
    )

    assert_recognition_response(
        response,
        event_id=event_id,
        position_id=position_id,
        amount="100.00",
        balance_kind="fund_distribution_receivable",
    )


def test_year_end_measurement_uses_separate_book_and_tax_value_contract() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(investments_session_factory=sessions))
    measurement_id = "40000000-0000-0000-0000-000000000044"
    position_id = "50000000-0000-0000-0000-000000000005"

    response = client.post(
        "/api/v1/investments/year-end-measurements",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": "measurement-api-contract-0001",
            "X-Request-ID": "investment-measurement-api",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "measurementId": measurement_id,
            "positionId": position_id,
            "asOf": "2026-12-31",
            "observedOrRecoverableValue": {
                "amount": "82.50", "currency": "NOK",
            },
            "taxValue": {"amount": "97.00", "currency": "NOK"},
            "evidenceMode": "manual_fallback",
            "evidenceReference": "year-end broker statement",
            "ownerAttested": True,
            "documentFacts": [{
                "capability": "DOCUMENTS",
                "recordId": "80000000-0000-0000-0000-000000000048",
                "revision": 1,
                "factSha256": "d" * 64,
            }],
            "bankFact": None,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["measurementId"] == measurement_id
    assert response.json()["closingBookValue"]["amount"] == "82.50"
    assert response.json()["taxBasis"]["amount"] == "100.00"
    assert response.json()["taxValue"]["amount"] == "97.00"
    assert sessions.commands[0].position_id == InvestmentPositionId(position_id)


def test_supported_cash_settlement_uses_independent_http_contract() -> None:
    sessions = InvestmentsSessionStub()
    banking = BankingSessionStub()
    client = TestClient(create_app(
        investments_session_factory=sessions,
        banking_session_factory=banking,
    ))
    settlement_id = "40000000-0000-0000-0000-000000000054"
    event_id = "40000000-0000-0000-0000-000000000034"

    response = client.post(
        "/api/v1/investments/cash-settlements",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": "30000000-0000-4000-8000-000000000053",
            "X-Request-ID": "investments-cash-settlement",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "settlementId": settlement_id,
            "eventId": event_id,
            "settlementDate": "2026-05-15",
            "amount": {"amount": "100.00", "currency": "NOK"},
            "evidenceMode": "linked_sources",
            "evidenceReference": "bank-payment-example",
            "ownerAttested": False,
            "documentFacts": [],
            "bankFact": {
                "capability": "BANKING",
                "recordId": "70000000-0000-0000-0000-000000000007",
                "revision": 1,
                "factSha256": "b" * 64,
            },
        },
    )

    assert response.status_code == 201, response.text
    assert response.json() == {
        "settlementId": settlement_id,
        "eventId": event_id,
        "settlementAccountingEntryId": (
            "70000000-0000-0000-0000-000000000007"
        ),
        "replayed": False,
    }
    assert sessions.commands[0].settlement_id == InvestmentSettlementId(
        settlement_id
    )
    assert banking.tokens == []


def test_cash_settlement_defers_canonical_bank_claim_to_transaction_workflow() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(
        investments_session_factory=sessions,
        banking_session_factory=BankingSessionStub(source_hash="c" * 64),
    ))

    response = client.post(
        "/api/v1/investments/cash-settlements",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": "30000000-0000-4000-8000-000000000063",
            "X-Request-ID": "investments-cash-source-mismatch",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "settlementId": "40000000-0000-0000-0000-000000000064",
            "eventId": "40000000-0000-0000-0000-000000000034",
            "settlementDate": "2026-05-15",
            "amount": {"amount": "100.00", "currency": "NOK"},
            "evidenceMode": "linked_sources",
            "evidenceReference": "bank-payment-mismatch",
            "ownerAttested": False,
            "documentFacts": [],
            "bankFact": {
                "capability": "BANKING",
                "recordId": "70000000-0000-0000-0000-000000000007",
                "revision": 1,
                "factSha256": "b" * 64,
            },
        },
    )

    assert response.status_code == 201, response.text
    assert sessions.commands[0].evidence.bank_fact is not None
    assert sessions.commands[0].evidence.bank_fact.fact_sha256 == "b" * 64


def test_purchase_cash_direction_is_checked_by_locked_bank_claim_not_transport() -> None:
    sessions = InvestmentsSessionStub(
        InvestmentSettlementBalanceKind.PURCHASE_PAYABLE
    )
    client = TestClient(create_app(
        investments_session_factory=sessions,
        banking_session_factory=BankingSessionStub(amount="100.00"),
    ))

    response = client.post(
        "/api/v1/investments/cash-settlements",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": "30000000-0000-4000-8000-000000000073",
            "X-Request-ID": "investments-cash-direction-mismatch",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "settlementId": "40000000-0000-0000-0000-000000000074",
            "eventId": "40000000-0000-0000-0000-000000000004",
            "settlementDate": "2026-05-15",
            "amount": {"amount": "100.00", "currency": "NOK"},
            "evidenceMode": "linked_sources",
            "evidenceReference": "bank-payment-direction",
            "ownerAttested": False,
            "documentFacts": [],
            "bankFact": {
                "capability": "BANKING",
                "recordId": "70000000-0000-0000-0000-000000000007",
                "revision": 1,
                "factSha256": "b" * 64,
            },
        },
    )

    assert response.status_code == 201, response.text
    assert sessions.commands[0].evidence.bank_fact is not None


def test_supported_correction_uses_linked_reversal_replacement_http_contract() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(investments_session_factory=sessions))

    response = client.post(
        "/api/v1/investments/corrections",
        headers={
            "Authorization": "Bearer owner-token",
            "Idempotency-Key": "30000000-0000-4000-8000-000000000042",
            "X-Request-ID": "investments-supported-correction",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "correctionId": "40000000-0000-0000-0000-000000000042",
            "targetKind": "economic_event",
            "originalRecordId": "40000000-0000-0000-0000-000000000024",
            "originalActivityKind": "dividend_received",
            "correctionDate": "2026-08-31",
            "reason": "Correct gross dividend amount",
            "evidenceMode": "manual_fallback",
            "evidenceReference": "correction-owner-evidence",
            "ownerAttested": True,
            "documentFacts": [{
                "capability": "DOCUMENTS",
                "recordId": "80000000-0000-0000-0000-000000000018",
                "revision": 1,
                "factSha256": "c" * 64,
            }],
            "bankFact": None,
            "replacement": {
                "replacementKind": "dividend_received",
                "companyId": "10000000-0000-0000-0000-000000000001",
                "incomeYear": 2026,
                "eventId": "40000000-0000-0000-0000-000000000044",
                "positionId": "50000000-0000-0000-0000-000000000025",
                "payingCompanyName": "Example AS",
                "declaredDate": "2026-04-01",
                "grossAmount": {"amount": "130.00", "currency": "NOK"},
                "lawfulDividendConfirmed": True,
                "groupExceptionClaimed": False,
                "yearEndOwnershipBasisPoints": None,
                "yearEndVotingBasisPoints": None,
                "groupEvidenceReference": None,
                "evidenceMode": "linked_sources",
                "evidenceReference": "corrected-dividend-advice",
                "ownerAttested": False,
                "documentFacts": [{
                    "capability": "DOCUMENTS",
                    "recordId": "80000000-0000-0000-0000-000000000008",
                    "revision": 2,
                    "factSha256": "d" * 64,
                }],
                "bankFact": None,
            },
        },
    )

    assert response.status_code == 201, response.text
    assert response.json() == {
        "correctionId": "40000000-0000-0000-0000-000000000042",
        "targetKind": "economic_event",
        "originalRecordId": "40000000-0000-0000-0000-000000000024",
        "replacementRecordId": "40000000-0000-0000-0000-000000000044",
        "reversalAccountingEntryId": "70000000-0000-0000-0000-000000000027",
        "replacementAccountingEntryId": "70000000-0000-0000-0000-000000000007",
        "replayed": False,
    }
    correction = sessions.commands[0]
    assert correction.reason == "Correct gross dividend amount"
    assert correction.replacement.gross_amount == Money.nok("130.00")
    assert str(correction.replacement.idempotency_key) == (
        "replacement:40000000-0000-0000-0000-000000000044"
    )


def test_positions_and_lots_use_investments_query_contract() -> None:
    sessions = InvestmentsSessionStub()
    client = TestClient(create_app(investments_session_factory=sessions))
    headers = {"Authorization": "Bearer owner-token"}

    positions = client.get(
        "/api/v1/investments/positions?companyId=10000000-0000-0000-0000-000000000001",
        headers=headers,
    )
    lots = client.get(
        "/api/v1/investments/acquisition-lots?companyId=10000000-0000-0000-0000-000000000001",
        headers=headers,
    )
    allocations = client.get(
        "/api/v1/investments/share-sale-allocations?companyId=10000000-0000-0000-0000-000000000001",
        headers=headers,
    )
    corrections = client.get(
        "/api/v1/investments/corrections?companyId=10000000-0000-0000-0000-000000000001",
        headers=headers,
    )

    assert positions.status_code == 200, positions.text
    assert positions.json()["items"][0]["movementCount"] == 1
    assert positions.json()["items"][0]["costBasis"] == {
        "amount": "125.50", "currency": "NOK"
    }
    assert positions.json()["items"][0]["shareCount"] == "10.125000000000"
    assert positions.json()["items"][0]["movements"][0]["share_delta"] == (
        "10.125000000000"
    )
    assert lots.status_code == 200, lots.text
    assert lots.json()["items"][0]["acquisitionActionId"] == str(
        supported_purchase().event_id
    )
    assert lots.json()["items"][0]["originalShareCount"] == "10.125000000000"
    assert lots.json()["items"][0]["remainingShareCount"] == "6.062500000000"
    assert allocations.status_code == 200, allocations.text
    assert allocations.json()["items"][0]["allocatedCostBasis"] == {
        "amount": "50.20", "currency": "NOK"
    }
    assert allocations.json()["items"][0]["allocatedShareCount"] == (
        "4.062500000000"
    )
    assert corrections.status_code == 200, corrections.text
    assert corrections.json()["items"][0]["originalActivityKind"] == (
        "share_purchase"
    )
    assert corrections.json()["items"][0]["evidenceReference"] == (
        "correction-owner-evidence"
    )
    activity = client.get(
        "/api/v1/investments/activity?companyId=10000000-0000-0000-0000-000000000001",
        headers=headers,
    )
    assert activity.status_code == 200, activity.text
    assert activity.json()["items"][0]["activityKind"] == "dividend_received"
    assert activity.json()["items"][0]["taxableAddBack"] == {
        "amount": "3.77", "currency": "NOK"
    }
    assert activity.json()["items"][0]["shareCount"] == "10.125000000000"
    assert activity.json()["items"][0]["soldShareCount"] == "4.062500000000"
    assert activity.json()["items"][0]["remainingShareCount"] == (
        "6.062500000000"
    )
    economic_events = client.get(
        "/api/v1/investments/economic-events"
        "?companyId=10000000-0000-0000-0000-000000000001",
        headers=headers,
    )
    assert economic_events.status_code == 200, economic_events.text
    lifecycle_event = economic_events.json()["items"][0]
    assert lifecycle_event["activityKind"] == "share_purchase"
    assert lifecycle_event["shareCount"] == "10.125000000000"
    assert lifecycle_event["expectedSettlementAmount"] == {
        "amount": "125.50",
        "currency": "NOK",
    }
    assert lifecycle_event["settlementId"] is None
    assert lifecycle_event["documentFacts"][0]["capability"] == "DOCUMENTS"
