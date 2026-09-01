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
    InvestmentActionId,
    InvestmentActivityKind,
    InvestmentCorrectionId,
    InvestmentDocumentStatus,
    InvestmentEvidenceMode,
    InvestmentKind,
    InvestmentPositionId,
    InvestmentSaleLotFact,
    InvestmentSourceReference,
    InvestmentTaxTreatment,
    InvestmentsError,
    InvestmentsErrorCode,
    PreparedReceivedDividendFacts,
    PreparedInvestmentCorrection,
    PreparedSharePurchase,
    PreparedShareSaleFacts,
    RecordReceivedDividendCommand,
    RecordReceivedFundDistributionCommand,
    RecordSharePurchaseCommand,
    RecordShareSaleCommand,
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


def prepared_purchase() -> PreparedSharePurchase:
    return PreparedSharePurchase(
        position_id=POSITION_ID,
        lot_id=LOT_ID,
        position_created=True,
        investment_name="Example AS",
        accounting_classification=InvestmentAccountingClassification.OTHER_LONG_TERM,
        purchase_amount=Money.nok("125.50"),
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
                allocated_share_count=4,
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

    async def prepare_share_purchase(
        self, command, *, capitalized_cost, evidence_digest, calculation_id
    ):
        self.command = command
        assert capitalized_cost == self.prepared.purchase_amount
        return replace(
            self.prepared,
            evidence_digest=evidence_digest,
            calculation_id=calculation_id,
        )

    async def prepare_share_sale(self, command, *, net_proceeds, evidence_digest):
        self.command = command
        assert net_proceeds == Money.nok("75.00")
        return self.prepared

    async def prepare_received_dividend(self, command, *, evidence_digest):
        self.command = command
        return self.prepared

    async def prepare_investment_correction(
        self, command, *, evidence_digest
    ):
        self.command = command
        return replace(self.prepared, evidence_digest=evidence_digest)


def supported_purchase() -> RecordSharePurchaseCommand:
    return RecordSharePurchaseCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002")),
        correlation_id=CorrelationId("investments-supported-purchase"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000003"),
        income_year=IncomeYear(2026),
        action_id=InvestmentActionId("40000000-0000-0000-0000-000000000004"),
        investment_key="  example-as  ",
        investment_name="  Example AS  ",
        investment_kind=InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
        accounting_classification=InvestmentAccountingClassification.OTHER_LONG_TERM,
        tax_treatment=InvestmentTaxTreatment.EXEMPTION_METHOD,
        acquisition_date=LocalDate(date(2026, 4, 15)),
        share_count=10,
        purchase_amount=Money.nok("125.50"),
        transaction_costs=Money.nok("0.00"),
        org_number="123456789",
        fund_equity_ratio_basis_points=None,
        fund_tax_statement_reference=None,
        evidence_mode=InvestmentEvidenceMode.MANUAL_FALLBACK,
        evidence_reference="broker-note-example-purchase",
        owner_attested=True,
        bank_transaction_id=BANK_ID,
        document_id=DOCUMENT_ID,
        document_status=InvestmentDocumentStatus.ATTACHED,
    )


def supported_sale() -> RecordShareSaleCommand:
    return RecordShareSaleCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002")),
        correlation_id=CorrelationId("investments-supported-sale"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000013"),
        income_year=IncomeYear(2026),
        action_id=InvestmentActionId("40000000-0000-0000-0000-000000000014"),
        position_id=POSITION_ID,
        sale_date=LocalDate(date(2026, 6, 1)),
        sold_share_count=4,
        proceeds=Money.nok("75.00"),
        transaction_costs=Money.nok("0.00"),
        sale_year_fund_equity_ratio_basis_points=None,
        fund_tax_statement_reference=None,
        evidence_mode=InvestmentEvidenceMode.MANUAL_FALLBACK,
        evidence_reference="broker-note-example-sale",
        owner_attested=True,
        bank_transaction_id=BANK_ID,
        document_id=DOCUMENT_ID,
        document_status=InvestmentDocumentStatus.ATTACHED,
    )


def supported_received_dividend() -> RecordReceivedDividendCommand:
    return RecordReceivedDividendCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002")),
        correlation_id=CorrelationId("investments-supported-dividend"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000023"),
        income_year=IncomeYear(2026),
        action_id=InvestmentActionId("40000000-0000-0000-0000-000000000024"),
        position_id=InvestmentPositionId("50000000-0000-0000-0000-000000000025"),
        paying_company_name="  Example AS  ",
        declared_date=LocalDate(date(2026, 4, 1)),
        paid_date=LocalDate(date(2026, 4, 15)),
        gross_amount=Money.nok("125.50"),
        tax_treatment=InvestmentTaxTreatment.EXEMPTION_METHOD,
        lawful_dividend_confirmed=True,
        group_exception_claimed=False,
        year_end_ownership_basis_points=None,
        year_end_voting_basis_points=None,
        group_evidence_reference=None,
        evidence_mode=InvestmentEvidenceMode.MANUAL_FALLBACK,
        evidence_reference="dividend-advice-example",
        owner_attested=True,
        bank_transaction_id=BANK_ID,
        document_id=DOCUMENT_ID,
        document_status=InvestmentDocumentStatus.ATTACHED,
    )


def supported_received_fund_distribution() -> RecordReceivedFundDistributionCommand:
    return RecordReceivedFundDistributionCommand(
        company_id=CompanyId("10000000-0000-0000-0000-000000000001"),
        actor_id=ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002")),
        correlation_id=CorrelationId("investments-supported-fund-distribution"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000033"),
        income_year=IncomeYear(2026),
        action_id=InvestmentActionId("40000000-0000-0000-0000-000000000034"),
        position_id=InvestmentPositionId("50000000-0000-0000-0000-000000000035"),
        fund_name="  Norsk Kombinasjonsfond  ",
        entitlement_date=LocalDate(date(2026, 5, 1)),
        paid_date=LocalDate(date(2026, 5, 15)),
        gross_amount=Money.nok("100.00"),
        opening_fund_equity_ratio_basis_points=5_000,
        fund_tax_statement_reference="provider-tax-statement-2026-r1",
        evidence_mode=InvestmentEvidenceMode.MANUAL_FALLBACK,
        evidence_reference="fund-distribution-advice-example",
        owner_attested=True,
        bank_transaction_id=BANK_ID,
        document_id=DOCUMENT_ID,
        document_status=InvestmentDocumentStatus.ATTACHED,
    )


def supported_investment_correction() -> CorrectInvestmentCommand:
    original = supported_received_dividend()
    replacement = replace(
        original,
        action_id=InvestmentActionId(
            "40000000-0000-0000-0000-000000000044"
        ),
        idempotency_key=IdempotencyKey(
            "30000000-0000-4000-8000-000000000043"
        ),
        gross_amount=Money.nok("130.00"),
        evidence_reference="corrected-dividend-advice",
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
        original_action_id=original.action_id,
        original_activity_kind=InvestmentActivityKind.DIVIDEND_RECEIVED,
        correction_date=LocalDate(date(2026, 8, 31)),
        reason="Correct gross dividend amount",
        evidence_mode=InvestmentEvidenceMode.MANUAL_FALLBACK,
        evidence_reference="correction-owner-evidence",
        owner_attested=True,
        bank_transaction_id=BANK_ID,
        document_id=DOCUMENT_ID,
        document_status=InvestmentDocumentStatus.ATTACHED,
        replacement=replacement,
    )


def test_supported_investment_correction_is_normalized_before_state_reversal() -> None:
    prepared = PreparedInvestmentCorrection(
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


def test_correction_rejects_a_different_replacement_activity_before_mutation() -> None:
    command = supported_investment_correction()
    prepared = PreparedInvestmentCorrection(
        original_accounting_entry_id=AccountingEntryReference(
            "70000000-0000-0000-0000-000000000007"
        ),
        original_position_id=supported_received_dividend().position_id,
        evidence_digest="",
    )
    persistence = InvestmentsPersistenceStub(prepared)

    with pytest.raises(InvestmentsError) as failure:
        asyncio.run(InvestmentsService(persistence).prepare_investment_correction(
            replace(command, replacement=supported_sale())
        ))

    assert failure.value.code == InvestmentsErrorCode.INVALID_INPUT.value
    assert persistence.command is None


def test_supported_received_dividend_is_normalized_and_taxed_by_investments() -> None:
    persistence = InvestmentsPersistenceStub(prepared_dividend_facts())
    result = asyncio.run(InvestmentsService(persistence).prepare_received_dividend(supported_received_dividend()))
    assert result.paying_company_name == "Example AS"
    assert result.taxable_add_back == Money.nok("3.77")
    assert len(result.evidence_digest) == 64
    assert len(result.calculation_id) == 64
    assert persistence.command.paying_company_name == "Example AS"


@pytest.mark.parametrize("changes", [
    {"paying_company_name": "  "},
    {"gross_amount": Money.nok("0")},
    {"declared_date": LocalDate(date(2025, 12, 31))},
    {"paid_date": LocalDate(date(2025, 12, 31))},
    {"tax_treatment": "outside_fritaksmetoden"},
    {"lawful_dividend_confirmed": False},
    {"document_status": "unknown"},
        {"document_status": InvestmentDocumentStatus.MISSING_ACCEPTED_WARNING},
        {"bank_transaction_id": None},
        {"document_id": None},
])
def test_invalid_received_dividend_facts_fail_before_persistence(changes) -> None:
    persistence = InvestmentsPersistenceStub(prepared_dividend_facts())
    with pytest.raises(InvestmentsError) as failure:
        asyncio.run(InvestmentsService(persistence).prepare_received_dividend(replace(supported_received_dividend(), **changes)))
    assert failure.value.code == InvestmentsErrorCode.INVALID_INPUT.value
    assert persistence.command is None


def test_supported_share_sale_is_prepared_through_investments_interface() -> None:
    persistence = InvestmentsPersistenceStub(prepared_sale_facts())
    result = asyncio.run(InvestmentsService(persistence).prepare_share_sale(supported_sale()))
    assert result.net_proceeds == Money.nok("75.00")
    assert result.fifo_cost_basis_reduction == Money.nok("50.20")
    assert result.book_gain_or_loss == Money.nok("24.80")
    assert result.exempt_gain == Money.nok("24.80")
    assert len(result.evidence_digest) == 64


@pytest.mark.parametrize("changes", [
    {"sold_share_count": 0}, {"sold_share_count": 1.5}, {"proceeds": Money.nok("0")},
    {"sale_date": LocalDate(date(2025, 12, 31))}, {"document_status": "unknown"},
        {"document_status": InvestmentDocumentStatus.MISSING_ACCEPTED_WARNING},
        {"bank_transaction_id": None},
        {"document_id": None},
])
def test_invalid_share_sale_facts_fail_before_persistence(changes) -> None:
    persistence = InvestmentsPersistenceStub(prepared_sale_facts())
    with pytest.raises(InvestmentsError) as failure:
        asyncio.run(InvestmentsService(persistence).prepare_share_sale(replace(supported_sale(), **changes)))
    assert failure.value.code == InvestmentsErrorCode.INVALID_INPUT.value
    assert persistence.command is None


def test_supported_share_purchase_is_normalized_and_prepared() -> None:
    persistence = InvestmentsPersistenceStub(prepared_purchase())
    result = asyncio.run(InvestmentsService(persistence).prepare_share_purchase(supported_purchase()))
    assert result.purchase_amount == Money.nok("125.50")
    assert len(result.evidence_digest) == 64
    assert len(result.calculation_id) == 64
    assert persistence.command.investment_key == "example-as"
    assert persistence.command.investment_name == "Example AS"


@pytest.mark.parametrize("changes", [
    {"share_count": 0}, {"share_count": 1.5}, {"purchase_amount": Money.nok("0")},
    {"acquisition_date": LocalDate(date(2025, 12, 31))}, {"investment_key": "  "},
    {"investment_name": "  "}, {"investment_kind": "simple_listed_security"},
    {"tax_treatment": "needs_accountant"}, {"org_number": "123"},
        {"document_status": "unknown"}, {"document_status": InvestmentDocumentStatus.MISSING_ACCEPTED_WARNING},
        {"bank_transaction_id": None},
        {"document_id": None},
])
def test_invalid_share_purchase_facts_fail_before_persistence(changes) -> None:
    persistence = InvestmentsPersistenceStub(prepared_purchase())
    with pytest.raises(InvestmentsError) as failure:
        asyncio.run(InvestmentsService(persistence).prepare_share_purchase(replace(supported_purchase(), **changes)))
    assert failure.value.code == InvestmentsErrorCode.INVALID_INPUT.value
    assert persistence.command is None
