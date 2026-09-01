from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from talli_backend.modules.investments.public import (
    AcquisitionLotId,
    InvestmentAccountingClassification,
    InvestmentActionId,
    InvestmentDocumentStatus,
    InvestmentEvidenceMode,
    InvestmentKind,
    InvestmentPositionId,
    InvestmentSaleLotFact,
    InvestmentSourceReference,
    InvestmentTaxTreatment,
    InvestmentUnits,
    InvestmentsError,
    PreparedReceivedDividendFacts,
    PreparedReceivedFundDistributionFacts,
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


COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")
ACTOR_ID = ActorId(
    ActorKind.USER,
    UserId("20000000-0000-0000-0000-000000000002"),
)
POSITION_ID = InvestmentPositionId("50000000-0000-0000-0000-000000000005")
LOT_ID = AcquisitionLotId("60000000-0000-0000-0000-000000000006")
BANK_ID = InvestmentSourceReference("70000000-0000-0000-0000-000000000007")
DOCUMENT_ID = InvestmentSourceReference("80000000-0000-0000-0000-000000000008")


class SupportedPatternsPersistence:
    def __init__(
        self,
        *,
        position_kind: InvestmentKind = InvestmentKind.NORWEGIAN_LISTED_SHARE,
        book_basis: str = "80.00",
        tax_basis: str = "80.00",
        acquisition_ratio: int | None = None,
    ) -> None:
        self.command = None
        self.capitalized_cost = None
        self.net_proceeds = None
        self.evidence_digest = None
        self.position_kind = position_kind
        self.book_basis = Money.nok(book_basis)
        self.tax_basis = Money.nok(tax_basis)
        self.acquisition_ratio = acquisition_ratio

    async def prepare_share_purchase(
        self,
        command: RecordSharePurchaseCommand,
        *,
        capitalized_cost: Money,
        evidence_digest: str,
        calculation_id: str,
    ) -> PreparedSharePurchase:
        self.command = command
        self.capitalized_cost = capitalized_cost
        self.evidence_digest = evidence_digest
        return PreparedSharePurchase(
            position_id=POSITION_ID,
            lot_id=LOT_ID,
            position_created=True,
            investment_name=command.investment_name,
            accounting_classification=command.accounting_classification,
            purchase_amount=capitalized_cost,
            evidence_digest=evidence_digest,
            calculation_id=calculation_id,
        )

    async def prepare_share_sale(
        self,
        command: RecordShareSaleCommand,
        *,
        net_proceeds: Money,
        evidence_digest: str,
    ) -> PreparedShareSaleFacts:
        self.command = command
        self.net_proceeds = net_proceeds
        self.evidence_digest = evidence_digest
        classification = (
            InvestmentAccountingClassification.CURRENT_FUND
            if self.position_kind is InvestmentKind.NORWEGIAN_EQUITY_FUND
            else InvestmentAccountingClassification.CURRENT_LISTED_SHARE
        )
        return PreparedShareSaleFacts(
            position_id=POSITION_ID,
            investment_name="Nordic Investment",
            investment_kind=self.position_kind,
            accounting_classification=classification,
            fifo_book_cost_basis_reduction=self.book_basis,
            fifo_tax_basis_reduction=self.tax_basis,
            lot_facts=(
                InvestmentSaleLotFact(
                    lot_id=LOT_ID,
                    allocation_order=1,
                    acquisition_date=LocalDate(date(2026, 1, 2)),
                    allocated_share_count=InvestmentUnits.of(
                        str(command.sold_share_count)
                    ),
                    allocated_book_cost_basis=self.book_basis,
                    allocated_tax_basis=self.tax_basis,
                    acquisition_year_fund_equity_ratio_basis_points=(
                        self.acquisition_ratio
                    ),
                ),
            ),
        )

    async def prepare_received_dividend(
        self,
        command: RecordReceivedDividendCommand,
        *,
        evidence_digest: str,
    ) -> PreparedReceivedDividendFacts:
        self.command = command
        self.evidence_digest = evidence_digest
        return PreparedReceivedDividendFacts(
            position_id=POSITION_ID,
            investment_name="Nordic Investment",
            investment_kind=self.position_kind,
        )

    async def prepare_received_fund_distribution(
        self,
        command: RecordReceivedFundDistributionCommand,
        *,
        evidence_digest: str,
    ) -> PreparedReceivedFundDistributionFacts:
        self.command = command
        self.evidence_digest = evidence_digest
        return PreparedReceivedFundDistributionFacts(
            position_id=POSITION_ID,
            investment_name="Nordic Fund",
            investment_kind=self.position_kind,
        )


def purchase_command(
    *,
    kind: InvestmentKind = InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
    classification: InvestmentAccountingClassification = (
        InvestmentAccountingClassification.OTHER_LONG_TERM
    ),
    investment_key: str = "private:123456789",
    org_number: str | None = "123456789",
    fund_equity_ratio_basis_points: int | None = None,
    fund_tax_statement_reference: str | None = None,
) -> RecordSharePurchaseCommand:
    return RecordSharePurchaseCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("investments-supported-pattern-purchase"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000003"),
        income_year=IncomeYear(2026),
        action_id=InvestmentActionId("40000000-0000-0000-0000-000000000004"),
        investment_key=investment_key,
        investment_name="  Nordic Investment  ",
        investment_kind=kind,
        accounting_classification=classification,
        tax_treatment=InvestmentTaxTreatment.EXEMPTION_METHOD,
        acquisition_date=LocalDate(date(2026, 4, 15)),
        share_count=10,
        purchase_amount=Money.nok("100.00"),
        transaction_costs=Money.nok("2.50"),
        org_number=org_number,
        fund_equity_ratio_basis_points=fund_equity_ratio_basis_points,
        fund_tax_statement_reference=fund_tax_statement_reference,
        evidence_mode=InvestmentEvidenceMode.LINKED_SOURCES,
        evidence_reference="  broker-note-42  ",
        owner_attested=False,
        bank_transaction_id=BANK_ID,
        document_id=DOCUMENT_ID,
        document_status=InvestmentDocumentStatus.ATTACHED,
    )


def sale_command(
    *,
    sale_ratio: int | None = None,
    tax_reference: str | None = None,
) -> RecordShareSaleCommand:
    return RecordShareSaleCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("investments-supported-pattern-sale"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000013"),
        income_year=IncomeYear(2026),
        action_id=InvestmentActionId("40000000-0000-0000-0000-000000000014"),
        position_id=POSITION_ID,
        sale_date=LocalDate(date(2026, 6, 1)),
        sold_share_count=4,
        proceeds=Money.nok("120.00"),
        transaction_costs=Money.nok("2.00"),
        sale_year_fund_equity_ratio_basis_points=sale_ratio,
        fund_tax_statement_reference=tax_reference,
        evidence_mode=InvestmentEvidenceMode.MANUAL_FALLBACK,
        evidence_reference="broker-contract-note-77",
        owner_attested=True,
        bank_transaction_id=BANK_ID,
        document_id=DOCUMENT_ID,
        document_status=InvestmentDocumentStatus.ATTACHED,
    )


def dividend_command(
    *,
    group_exception_claimed: bool = False,
    ownership: int | None = None,
    votes: int | None = None,
    group_reference: str | None = None,
) -> RecordReceivedDividendCommand:
    return RecordReceivedDividendCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("investments-supported-pattern-dividend"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000023"),
        income_year=IncomeYear(2026),
        action_id=InvestmentActionId("40000000-0000-0000-0000-000000000024"),
        position_id=POSITION_ID,
        paying_company_name="  Nordic Listed ASA  ",
        declared_date=LocalDate(date(2026, 4, 1)),
        paid_date=LocalDate(date(2026, 4, 15)),
        gross_amount=Money.nok("125.50"),
        tax_treatment=InvestmentTaxTreatment.EXEMPTION_METHOD,
        lawful_dividend_confirmed=True,
        group_exception_claimed=group_exception_claimed,
        year_end_ownership_basis_points=ownership,
        year_end_voting_basis_points=votes,
        group_evidence_reference=group_reference,
        evidence_mode=InvestmentEvidenceMode.LINKED_SOURCES,
        evidence_reference="dividend-advice-19",
        owner_attested=False,
        bank_transaction_id=BANK_ID,
        document_id=DOCUMENT_ID,
        document_status=InvestmentDocumentStatus.ATTACHED,
    )


def fund_distribution_command(ratio: int) -> RecordReceivedFundDistributionCommand:
    return RecordReceivedFundDistributionCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("investments-supported-fund-distribution"),
        idempotency_key=IdempotencyKey("30000000-0000-4000-8000-000000000033"),
        income_year=IncomeYear(2026),
        action_id=InvestmentActionId("40000000-0000-0000-0000-000000000034"),
        position_id=POSITION_ID,
        fund_name="  Nordic Fund  ",
        entitlement_date=LocalDate(date(2026, 5, 1)),
        paid_date=LocalDate(date(2026, 5, 15)),
        gross_amount=Money.nok("100.00"),
        opening_fund_equity_ratio_basis_points=ratio,
        fund_tax_statement_reference="provider-tax-statement-2026-r1",
        evidence_mode=InvestmentEvidenceMode.LINKED_SOURCES,
        evidence_reference="fund-distribution-advice-3",
        owner_attested=False,
        bank_transaction_id=BANK_ID,
        document_id=DOCUMENT_ID,
        document_status=InvestmentDocumentStatus.ATTACHED,
    )


@pytest.mark.parametrize(
    ("kind", "classification", "key", "org_number", "fund_ratio", "fund_reference"),
    [
        (InvestmentKind.NORWEGIAN_PRIVATE_COMPANY, InvestmentAccountingClassification.SUBSIDIARY, "private:123456789", "123456789", None, None),
        (InvestmentKind.NORWEGIAN_LISTED_SHARE, InvestmentAccountingClassification.CURRENT_LISTED_SHARE, "NO0000000001", "123456789", None, None),
        (InvestmentKind.NORWEGIAN_EQUITY_FUND, InvestmentAccountingClassification.CURRENT_FUND, "NO0000000002", None, 7_500, "provider-tax-statement-2026-r1"),
    ],
)
def test_supported_domestic_purchase_capitalizes_book_and_tax_cost_and_binds_evidence(
    kind, classification, key, org_number, fund_ratio, fund_reference
) -> None:
    persistence = SupportedPatternsPersistence()
    result = asyncio.run(InvestmentsService(persistence).prepare_share_purchase(
        purchase_command(kind=kind, classification=classification, investment_key=key, org_number=org_number, fund_equity_ratio_basis_points=fund_ratio, fund_tax_statement_reference=fund_reference)
    ))
    assert result.purchase_amount == Money.nok("102.50")
    assert result.accounting_classification is classification
    assert len(result.evidence_digest) == 64
    assert len(result.calculation_id) == 64
    assert persistence.command.investment_name == "Nordic Investment"


def test_manual_fallback_keeps_authoritative_sources_and_adds_owner_attestation() -> None:
    persistence = SupportedPatternsPersistence()
    command = replace(
        purchase_command(),
        evidence_mode=InvestmentEvidenceMode.MANUAL_FALLBACK,
        owner_attested=True,
    )

    result = asyncio.run(InvestmentsService(persistence).prepare_share_purchase(command))

    assert result.purchase_amount == Money.nok("102.50")
    assert persistence.command.bank_transaction_id == BANK_ID
    assert persistence.command.document_id == DOCUMENT_ID
    assert persistence.command.document_status is InvestmentDocumentStatus.ATTACHED
    assert persistence.command.owner_attested is True


def test_share_sale_keeps_book_and_tax_results_separate() -> None:
    persistence = SupportedPatternsPersistence(book_basis="80.00", tax_basis="82.00")
    result = asyncio.run(InvestmentsService(persistence).prepare_share_sale(sale_command()))
    assert result.net_proceeds == Money.nok("118.00")
    assert result.book_gain_or_loss == Money.nok("38.00")
    assert result.tax_gain_or_loss == Money.nok("36.00")
    assert result.exempt_gain == Money.nok("36.00")
    assert result.taxable_gain == Money.nok("0.00")
    assert result.lot_calculations[0].tax_gain_or_loss == Money.nok("36.00")


def test_fund_redemption_averages_acquisition_and_sale_year_ratios() -> None:
    persistence = SupportedPatternsPersistence(
        position_kind=InvestmentKind.NORWEGIAN_EQUITY_FUND,
        book_basis="100.00",
        tax_basis="100.00",
        acquisition_ratio=6_000,
    )
    result = asyncio.run(InvestmentsService(persistence).prepare_share_sale(
        sale_command(sale_ratio=8_000, tax_reference="provider-tax-statement-2026-r2")
    ))
    allocation = result.lot_calculations[0]
    assert result.tax_gain_or_loss == Money.nok("18.00")
    assert allocation.average_fund_equity_ratio_basis_points == Decimal("7000")
    assert result.exempt_gain == Money.nok("12.60")
    assert result.taxable_gain == Money.nok("5.40")


def test_ordinary_and_proved_group_dividends_use_distinct_inclusion() -> None:
    persistence = SupportedPatternsPersistence()
    ordinary = asyncio.run(InvestmentsService(persistence).prepare_received_dividend(dividend_command()))
    group = asyncio.run(InvestmentsService(persistence).prepare_received_dividend(
        dividend_command(group_exception_claimed=True, ownership=9_001, votes=9_001, group_reference="year-end-group-proof")
    ))
    assert ordinary.taxable_add_back == Money.nok("3.77")
    assert ordinary.group_exception_applied is False
    assert group.taxable_add_back == Money.nok("0.00")
    assert group.group_exception_applied is True


@pytest.mark.parametrize(
    ("ratio", "dividend", "interest", "add_back", "taxable"),
    [
        (8_001, "100.00", "0.00", "3.00", "3.00"),
        (1_999, "0.00", "100.00", "0.00", "100.00"),
        (5_000, "50.00", "50.00", "1.50", "51.50"),
        (2_000, "20.00", "80.00", "0.60", "80.60"),
        (8_000, "80.00", "20.00", "2.40", "22.40"),
    ],
)
def test_fund_distribution_applies_statutory_thresholds(
    ratio, dividend, interest, add_back, taxable
) -> None:
    persistence = SupportedPatternsPersistence(position_kind=InvestmentKind.NORWEGIAN_EQUITY_FUND)
    result = asyncio.run(InvestmentsService(persistence).prepare_received_fund_distribution(fund_distribution_command(ratio)))
    assert result.dividend_portion == Money.nok(dividend)
    assert result.interest_portion == Money.nok(interest)
    assert result.taxable_add_back == Money.nok(add_back)
    assert result.total_taxable_income == Money.nok(taxable)


@pytest.mark.parametrize(
    "command",
    [
        replace(purchase_command(), investment_kind="foreign_share"),
        purchase_command(kind=InvestmentKind.NORWEGIAN_EQUITY_FUND, classification=InvestmentAccountingClassification.CURRENT_FUND, investment_key="NO0000000002", org_number=None, fund_equity_ratio_basis_points=7_500),
        replace(purchase_command(), accounting_classification=InvestmentAccountingClassification.CURRENT_LISTED_SHARE),
        replace(purchase_command(), evidence_mode=InvestmentEvidenceMode.MANUAL_FALLBACK, owner_attested=True, bank_transaction_id=None, document_id=None, document_status=InvestmentDocumentStatus.MISSING_ACCEPTED_WARNING),
        replace(purchase_command(), transaction_costs=Money.nok("-0.01")),
    ],
)
def test_unsupported_or_incomplete_purchase_fails_before_persistence(command) -> None:
    persistence = SupportedPatternsPersistence()
    with pytest.raises(InvestmentsError):
        asyncio.run(InvestmentsService(persistence).prepare_share_purchase(command))
    assert persistence.command is None


@pytest.mark.parametrize(
    "command",
    [
        dividend_command(group_exception_claimed=True, ownership=9_000, votes=10_000, group_reference="proof"),
        replace(dividend_command(), lawful_dividend_confirmed=False),
        replace(dividend_command(), group_evidence_reference="contradictory-proof"),
    ],
)
def test_unclear_dividend_tax_or_lawfulness_fails_before_persistence(command) -> None:
    persistence = SupportedPatternsPersistence()
    with pytest.raises(InvestmentsError):
        asyncio.run(InvestmentsService(persistence).prepare_received_dividend(command))
    assert persistence.command is None


def test_fund_tax_data_and_position_kind_mismatches_hard_block() -> None:
    missing_sale_data = SupportedPatternsPersistence(position_kind=InvestmentKind.NORWEGIAN_EQUITY_FUND, acquisition_ratio=6_000)
    with pytest.raises(InvestmentsError):
        asyncio.run(InvestmentsService(missing_sale_data).prepare_share_sale(sale_command()))

    share_position = SupportedPatternsPersistence(position_kind=InvestmentKind.NORWEGIAN_LISTED_SHARE)
    with pytest.raises(InvestmentsError):
        asyncio.run(InvestmentsService(share_position).prepare_received_fund_distribution(fund_distribution_command(5_000)))

    fund_position = SupportedPatternsPersistence(position_kind=InvestmentKind.NORWEGIAN_EQUITY_FUND)
    with pytest.raises(InvestmentsError):
        asyncio.run(InvestmentsService(fund_position).prepare_received_dividend(dividend_command()))
