from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date

import pytest

from talli_backend.modules.investments.public import (
    AccountingEntryReference,
    AcquisitionLotId,
    CorrectInvestmentCommand,
    InvestmentAccountingClassification,
    InvestmentActivityKind,
    InvestmentCorrectionId,
    InvestmentCorrectionTargetKind,
    InvestmentEconomicEventId,
    InvestmentEvidence,
    InvestmentEvidenceMode,
    InvestmentFactReference,
    InvestmentKind,
    InvestmentTradingProfile,
    InvestmentPositionId,
    InvestmentSaleLotFact,
    InvestmentSourceReference,
    InvestmentSourceCapability,
    InvestmentSettlementBalanceKind,
    InvestmentSettlementId,
    InvestmentUnits,
    InvestmentsError,
    InvestmentsErrorCode,
    PreparedReceivedDividendFacts,
    PreparedEconomicEventCorrection,
    PreparedCashSettlementCorrection,
    PreparedSettledInvestmentCorrection,
    PreparedSharePurchaseRecognition,
    PreparedShareSaleFacts,
    RecognizeReceivedDividendCommand,
    RecognizeReceivedFundDistributionCommand,
    RecognizeSharePurchaseCommand,
    RecognizeShareSaleCommand,
    SettleInvestmentCashCommand,
)
from talli_backend.modules.investments.service import InvestmentsService
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    Money,
    UserId,
)


POSITION_ID = InvestmentPositionId("50000000-0000-0000-0000-000000000015")
LOT_ID = AcquisitionLotId("60000000-0000-0000-0000-000000000006")
BANK_ID = InvestmentSourceReference("70000000-0000-0000-0000-000000000007")
DOCUMENT_ID = InvestmentSourceReference("80000000-0000-0000-0000-000000000008")


def prepared_purchase() -> PreparedSharePurchaseRecognition:
    return PreparedSharePurchaseRecognition(
        position_id=POSITION_ID,
        lot_id=LOT_ID,
        position_created=True,
        investment_name="Example AS",
        accounting_classification=InvestmentAccountingClassification.OTHER_LONG_TERM,
        acquisition_cost=Money.nok("125.50"),
        expected_settlement_amount=Money.nok("125.50"),
        settlement_balance_kind=InvestmentSettlementBalanceKind.PURCHASE_PAYABLE,
        evidence_digest="",
        calculation_id="",
    )


def prepared_sale_facts() -> PreparedShareSaleFacts:
    return PreparedShareSaleFacts(
        position_id=POSITION_ID,
        investment_name="Example AS",
        investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
        accounting_classification=InvestmentAccountingClassification.OTHER_LONG_TERM,
        fifo_book_cost_basis_reduction=Money.nok("50.20"),
        fifo_tax_basis_reduction=Money.nok("50.20"),
        lot_facts=(
            InvestmentSaleLotFact(
                lot_id=LOT_ID,
                allocation_order=1,
                acquisition_date=LocalDate(date(2026, 4, 15)),
                allocated_share_count=InvestmentUnits.of("4"),
                allocated_book_cost_basis=Money.nok("50.20"),
                allocated_tax_basis=Money.nok("50.20"),
                acquisition_year_fund_equity_ratio_basis_points=None,
            ),
        ),
    )


def prepared_dividend_facts() -> PreparedReceivedDividendFacts:
    return PreparedReceivedDividendFacts(
        position_id=InvestmentPositionId("50000000-0000-0000-0000-000000000025"),
        investment_name="Example AS",
        investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
    )


class InvestmentsPersistenceStub:
    def __init__(self, prepared) -> None:
        self.prepared = prepared
        self.command = None

    async def prepare_share_purchase_recognition(
        self, command, *, capitalized_cost, evidence_digest, calculation_id
    ):
        self.command = command
        assert capitalized_cost == self.prepared.acquisition_cost
        return replace(
            self.prepared,
            evidence_digest=evidence_digest,
            calculation_id=calculation_id,
        )

    async def prepare_share_sale_recognition(self, command, *, net_proceeds, evidence_digest):
        self.command = command
        assert net_proceeds == Money.nok("75.00")
        return self.prepared

    async def prepare_received_dividend_recognition(self, command, *, evidence_digest):
        self.command = command
        return self.prepared

    async def prepare_investment_correction(
        self, command, *, evidence_digest, replacement_evidence_digest
    ):
        self.command = command
        assert replacement_evidence_digest == command.replacement.evidence.digest()
        return replace(self.prepared, evidence_digest=evidence_digest)

    async def prepare_settled_investment_correction(
        self, event_command, settlement_command, **digests
    ):
        self.command = (event_command, settlement_command, digests)
        return self.prepared


def supported_purchase() -> RecognizeSharePurchaseCommand:
    return RecognizeSharePurchaseCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002")),
        correlation_id=CorrelationId("investments-supported-purchase"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000003"),
        income_year=IncomeYear(2026),
        event_id=InvestmentEconomicEventId("40000000-0000-0000-0000-000000000004"),
        investment_key="  private:123456789:ordinary  ",
        investment_name="  Example AS  ",
        investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
        accounting_classification=InvestmentAccountingClassification.OTHER_LONG_TERM,
        acquisition_date=LocalDate(date(2026, 4, 15)),
        share_count=InvestmentUnits.of("10"),
        purchase_amount=Money.nok("125.50"),
        transaction_costs=Money.nok("0.00"),
        org_number="123456789",
        fund_equity_ratio_basis_points=None,
        fund_tax_statement_reference=None,
        trading_profile=InvestmentTradingProfile.LOW_VOLUME_NON_ACTIVE,
        non_active_trading_confirmed=True,
        share_class_code="ordinary",
        single_share_class_confirmed=True,
        equal_share_rights_confirmed=True,
        unusual_share_rights_absent_confirmed=True,
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.MANUAL_FALLBACK,
            "broker-note-example-purchase",
            True,
            (InvestmentFactReference(InvestmentSourceCapability.DOCUMENTS, DOCUMENT_ID, 1, "d" * 64),),
            None,
        ),
    )


def supported_sale() -> RecognizeShareSaleCommand:
    return RecognizeShareSaleCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002")),
        correlation_id=CorrelationId("investments-supported-sale"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000013"),
        income_year=IncomeYear(2026),
        event_id=InvestmentEconomicEventId("40000000-0000-0000-0000-000000000014"),
        position_id=POSITION_ID,
        sale_date=LocalDate(date(2026, 6, 1)),
        sold_share_count=InvestmentUnits.of("4"),
        proceeds=Money.nok("75.00"),
        transaction_costs=Money.nok("0.00"),
        sale_year_fund_equity_ratio_basis_points=None,
        fund_tax_statement_reference=None,
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.MANUAL_FALLBACK,
            "broker-note-example-sale",
            True,
            (InvestmentFactReference(InvestmentSourceCapability.DOCUMENTS, DOCUMENT_ID, 1, "d" * 64),),
            None,
        ),
    )


def supported_received_dividend() -> RecognizeReceivedDividendCommand:
    return RecognizeReceivedDividendCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002")),
        correlation_id=CorrelationId("investments-supported-dividend"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000023"),
        income_year=IncomeYear(2026),
        event_id=InvestmentEconomicEventId("40000000-0000-0000-0000-000000000024"),
        position_id=InvestmentPositionId("50000000-0000-0000-0000-000000000025"),
        paying_company_name="  Example AS  ",
        declared_date=LocalDate(date(2026, 4, 1)),
        gross_amount=Money.nok("125.50"),
        lawful_dividend_confirmed=True,
        group_exception_claimed=False,
        year_end_ownership_basis_points=None,
        year_end_voting_basis_points=None,
        group_evidence_reference=None,
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.MANUAL_FALLBACK,
            "dividend-advice-example",
            True,
            (InvestmentFactReference(InvestmentSourceCapability.DOCUMENTS, DOCUMENT_ID, 1, "d" * 64),),
            None,
        ),
    )


def supported_received_fund_distribution() -> RecognizeReceivedFundDistributionCommand:
    return RecognizeReceivedFundDistributionCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002")),
        correlation_id=CorrelationId("investments-supported-fund-distribution"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000033"),
        income_year=IncomeYear(2026),
        event_id=InvestmentEconomicEventId("40000000-0000-0000-0000-000000000034"),
        position_id=InvestmentPositionId("50000000-0000-0000-0000-000000000035"),
        fund_name="  Norsk Kombinasjonsfond  ",
        entitlement_date=LocalDate(date(2026, 5, 1)),
        gross_amount=Money.nok("100.00"),
        opening_fund_equity_ratio_basis_points=5_000,
        fund_tax_statement_reference="provider-tax-statement-2026-r1",
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.MANUAL_FALLBACK,
            "fund-distribution-advice-example",
            True,
            (InvestmentFactReference(InvestmentSourceCapability.DOCUMENTS, DOCUMENT_ID, 1, "d" * 64),),
            None,
        ),
    )


def supported_investment_correction() -> CorrectInvestmentCommand:
    original = supported_received_dividend()
    replacement = RecognizeReceivedDividendCommand(
        company_id=original.company_id,
        actor_id=original.actor_id,
        correlation_id=CorrelationId("replacement-dividend-correction"),
        idempotency_key=IdempotencyKey(
            "30000000-0000-4000-8000-000000000043"
        ),
        income_year=original.income_year,
        event_id=InvestmentEconomicEventId(
            "40000000-0000-0000-0000-000000000044"
        ),
        position_id=original.position_id,
        paying_company_name=original.paying_company_name,
        declared_date=original.declared_date,
        gross_amount=Money.nok("130.00"),
        lawful_dividend_confirmed=original.lawful_dividend_confirmed,
        group_exception_claimed=original.group_exception_claimed,
        year_end_ownership_basis_points=original.year_end_ownership_basis_points,
        year_end_voting_basis_points=original.year_end_voting_basis_points,
        group_evidence_reference=original.group_evidence_reference,
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.LINKED_SOURCES,
            "corrected-dividend-advice",
            False,
            (
                InvestmentFactReference(
                    InvestmentSourceCapability.DOCUMENTS,
                    DOCUMENT_ID,
                    2,
                    "d" * 64,
                ),
            ),
            None,
        ),
    )
    return CorrectInvestmentCommand(
        company_id=original.company_id,
        actor_id=original.actor_id,
        correlation_id=CorrelationId("investments-supported-correction"),
        idempotency_key=IdempotencyKey(
            "30000000-0000-4000-8000-000000000042"
        ),
        income_year=original.income_year,
        correction_id=InvestmentCorrectionId(
            "40000000-0000-0000-0000-000000000042"
        ),
        target_kind=InvestmentCorrectionTargetKind.ECONOMIC_EVENT,
        original_record_id=original.event_id,
        original_activity_kind=InvestmentActivityKind.DIVIDEND_RECEIVED,
        correction_date=LocalDate(date(2026, 8, 31)),
        reason="Correct gross dividend amount",
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.MANUAL_FALLBACK,
            "correction-owner-evidence",
            True,
            (
                InvestmentFactReference(
                    InvestmentSourceCapability.DOCUMENTS,
                    InvestmentSourceReference(
                        "80000000-0000-0000-0000-000000000018"
                    ),
                    1,
                    "c" * 64,
                ),
            ),
            None,
        ),
        replacement=replacement,
    )


def test_supported_investment_correction_is_normalized_before_state_reversal() -> None:
    prepared = PreparedEconomicEventCorrection(
        original_accounting_entry_id=AccountingEntryReference(
            "70000000-0000-0000-0000-000000000007"
        ),
        original_position_id=supported_received_dividend().position_id,
        evidence_digest="",
    )
    persistence = InvestmentsPersistenceStub(prepared)
    result = asyncio.run(
        InvestmentsService(persistence).prepare_investment_correction(
            supported_investment_correction()
        )
    )

    assert len(result.evidence_digest) == 64
    assert persistence.command.reason == "Correct gross dividend amount"


def test_settled_wrong_amount_correction_requires_linked_replacement_settlement() -> None:
    event_command = supported_investment_correction()
    replacement_event = event_command.replacement
    assert isinstance(replacement_event, RecognizeReceivedDividendCommand)
    replacement_settlement = SettleInvestmentCashCommand(
        company_id=event_command.company_id,
        actor_id=event_command.actor_id,
        correlation_id=CorrelationId("replacement-settlement-correction"),
        idempotency_key=IdempotencyKey(
            "30000000-0000-4000-8000-000000000046"
        ),
        income_year=event_command.income_year,
        settlement_id=InvestmentSettlementId(
            "40000000-0000-0000-0000-000000000046"
        ),
        event_id=replacement_event.event_id,
        settlement_date=LocalDate(date(2026, 9, 1)),
        amount=replacement_event.gross_amount,
        evidence=InvestmentEvidence(
            InvestmentEvidenceMode.LINKED_SOURCES,
            "corrected-bank-settlement",
            False,
            (),
            InvestmentFactReference(
                InvestmentSourceCapability.BANKING,
                BANK_ID,
                1,
                "b" * 64,
            ),
        ),
    )
    settlement_command = CorrectInvestmentCommand(
        company_id=event_command.company_id,
        actor_id=event_command.actor_id,
        correlation_id=CorrelationId("settlement-correction"),
        idempotency_key=IdempotencyKey(
            "30000000-0000-4000-8000-000000000047"
        ),
        income_year=event_command.income_year,
        correction_id=InvestmentCorrectionId(
            "40000000-0000-0000-0000-000000000047"
        ),
        target_kind=InvestmentCorrectionTargetKind.CASH_SETTLEMENT,
        original_record_id=InvestmentSettlementId(
            "40000000-0000-0000-0000-000000000041"
        ),
        original_activity_kind=event_command.original_activity_kind,
        correction_date=event_command.correction_date,
        reason=event_command.reason,
        evidence=event_command.evidence,
        replacement=replacement_settlement,
    )
    prepared = PreparedSettledInvestmentCorrection(
        event=PreparedEconomicEventCorrection(
            AccountingEntryReference(
                "70000000-0000-0000-0000-000000000007"
            ),
            replacement_event.position_id,
            "e" * 64,
        ),
        settlement=PreparedCashSettlementCorrection(
            AccountingEntryReference(
                "70000000-0000-0000-0000-000000000008"
            ),
            InvestmentSettlementId(
                "40000000-0000-0000-0000-000000000041"
            ),
            replacement_event.event_id,
            AccountingEntryReference(
                "70000000-0000-0000-0000-000000000007"
            ),
            InvestmentSettlementBalanceKind.DIVIDEND_RECEIVABLE,
            replacement_event.gross_amount,
            "f" * 64,
            replacement_settlement.evidence.digest(),
            "d" * 64,
            InvestmentActivityKind.DIVIDEND_RECEIVED,
        ),
    )
    persistence = InvestmentsPersistenceStub(prepared)
    result = asyncio.run(
        InvestmentsService(persistence).prepare_settled_investment_correction(
            event_command, settlement_command
        )
    )
    assert result is prepared
    assert persistence.command[0].replacement.event_id == (
        persistence.command[1].replacement.event_id
    )

    with pytest.raises(InvestmentsError):
        asyncio.run(
            InvestmentsService(persistence).prepare_settled_investment_correction(
                event_command,
                replace(
                    settlement_command,
                    replacement=replace(
                        replacement_settlement,
                        event_id=InvestmentEconomicEventId(
                            "40000000-0000-0000-0000-000000000099"
                        ),
                    ),
                ),
            )
        )


def test_correction_rejects_a_different_replacement_activity_before_mutation() -> None:
    command = supported_investment_correction()
    prepared = PreparedEconomicEventCorrection(
        original_accounting_entry_id=AccountingEntryReference(
            "70000000-0000-0000-0000-000000000007"
        ),
        original_position_id=supported_received_dividend().position_id,
        evidence_digest="",
    )
    persistence = InvestmentsPersistenceStub(prepared)

    with pytest.raises(InvestmentsError) as failure:
        asyncio.run(InvestmentsService(persistence).prepare_investment_correction(
            replace(
                command,
                original_activity_kind=InvestmentActivityKind.SHARE_SALE,
            )
        ))

    assert failure.value.code == InvestmentsErrorCode.INVALID_INPUT.value
    assert persistence.command is None


def test_supported_received_dividend_is_normalized_and_taxed_by_investments() -> None:
    persistence = InvestmentsPersistenceStub(prepared_dividend_facts())
    result = asyncio.run(InvestmentsService(persistence).prepare_received_dividend_recognition(supported_received_dividend()))
    assert result.paying_company_name == "Example AS"
    assert result.taxable_add_back == Money.nok("3.77")
    assert len(result.evidence_digest) == 64
    assert len(result.calculation_id) == 64
    assert persistence.command.paying_company_name == "Example AS"


@pytest.mark.parametrize("changes", [
    {"paying_company_name": "  "},
    {"gross_amount": Money.nok("0")},
    {"lawful_dividend_confirmed": False},
])
def test_invalid_received_dividend_facts_fail_before_persistence(changes) -> None:
    persistence = InvestmentsPersistenceStub(prepared_dividend_facts())
    with pytest.raises(InvestmentsError) as failure:
        asyncio.run(InvestmentsService(persistence).prepare_received_dividend_recognition(replace(supported_received_dividend(), **changes)))
    assert failure.value.code == InvestmentsErrorCode.INVALID_INPUT.value
    assert persistence.command is None


def test_supported_share_sale_is_prepared_through_investments_interface() -> None:
    persistence = InvestmentsPersistenceStub(prepared_sale_facts())
    result = asyncio.run(InvestmentsService(persistence).prepare_share_sale_recognition(supported_sale()))
    assert result.net_proceeds == Money.nok("75.00")
    assert result.fifo_cost_basis_reduction == Money.nok("50.20")
    assert result.book_gain_or_loss == Money.nok("24.80")
    assert result.exempt_gain == Money.nok("24.80")
    assert len(result.evidence_digest) == 64


@pytest.mark.parametrize("changes", [
    {"proceeds": Money.nok("0")},
])
def test_invalid_share_sale_facts_fail_before_persistence(changes) -> None:
    persistence = InvestmentsPersistenceStub(prepared_sale_facts())
    with pytest.raises(InvestmentsError) as failure:
        asyncio.run(InvestmentsService(persistence).prepare_share_sale_recognition(replace(supported_sale(), **changes)))
    assert failure.value.code == InvestmentsErrorCode.INVALID_INPUT.value
    assert persistence.command is None


def test_supported_share_purchase_is_normalized_and_prepared() -> None:
    persistence = InvestmentsPersistenceStub(prepared_purchase())
    result = asyncio.run(InvestmentsService(persistence).prepare_share_purchase_recognition(supported_purchase()))
    assert result.acquisition_cost == Money.nok("125.50")
    assert len(result.evidence_digest) == 64
    assert len(result.calculation_id) == 64
    assert persistence.command.investment_key == "private:123456789:ordinary"
    assert persistence.command.investment_name == "Example AS"


@pytest.mark.parametrize("changes", [
    {"purchase_amount": Money.nok("0")}, {"investment_key": "  "},
    {"investment_name": "  "}, {"investment_kind": "simple_listed_security"},
    {"org_number": "123"},
])
def test_invalid_share_purchase_facts_fail_before_persistence(changes) -> None:
    persistence = InvestmentsPersistenceStub(prepared_purchase())
    with pytest.raises(InvestmentsError) as failure:
        asyncio.run(InvestmentsService(persistence).prepare_share_purchase_recognition(replace(supported_purchase(), **changes)))
    assert failure.value.code == InvestmentsErrorCode.INVALID_INPUT.value
    assert persistence.command is None


@pytest.mark.parametrize("changes", [
    {"trading_profile": InvestmentTradingProfile.ACTIVE_OR_HIGH_VOLUME},
    {"trading_profile": InvestmentTradingProfile.UNKNOWN},
    {"non_active_trading_confirmed": False},
])
def test_active_or_unconfirmed_trading_is_rejected_before_persistence(changes) -> None:
    persistence = InvestmentsPersistenceStub(prepared_purchase())
    with pytest.raises(InvestmentsError) as failure:
        asyncio.run(
            InvestmentsService(persistence).prepare_share_purchase_recognition(
                replace(supported_purchase(), **changes)
            )
        )
    assert failure.value.code == InvestmentsErrorCode.ACTIVE_TRADING_UNSUPPORTED.value
    assert persistence.command is None


@pytest.mark.parametrize("changes", [
    {"investment_key": "private:123456789"},
    {"share_class_code": "class-a"},
    {"single_share_class_confirmed": False},
    {"equal_share_rights_confirmed": False},
    {"unusual_share_rights_absent_confirmed": False},
])
def test_unclear_private_share_identity_or_rights_is_rejected(changes) -> None:
    persistence = InvestmentsPersistenceStub(prepared_purchase())
    with pytest.raises(InvestmentsError) as failure:
        asyncio.run(
            InvestmentsService(persistence).prepare_share_purchase_recognition(
                replace(supported_purchase(), **changes)
            )
        )
    assert failure.value.code == InvestmentsErrorCode.OWNERSHIP_OR_RIGHTS_UNCLEAR.value
    assert persistence.command is None
