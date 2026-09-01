from __future__ import annotations

import ast
import inspect
from datetime import date
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest


def test_share_commands_are_investment_owned_and_transport_free() -> None:
    from talli_backend.modules.investments import public
    from talli_backend.modules.investments.public import (
        RecordSharePurchaseCommand,
        RecordShareSaleCommand,
        RecordReceivedDividendCommand,
        RecordReceivedFundDistributionCommand,
    )

    source = Path(inspect.getsourcefile(public) or "").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert set(RecordSharePurchaseCommand.__dataclass_fields__) == {
        "company_id",
        "actor_id",
        "correlation_id",
        "idempotency_key",
        "income_year",
        "action_id",
        "investment_key",
        "investment_name",
        "investment_kind",
        "accounting_classification",
        "tax_treatment",
        "acquisition_date",
        "share_count",
        "purchase_amount",
        "transaction_costs",
        "org_number",
        "fund_equity_ratio_basis_points",
        "fund_tax_statement_reference",
        "evidence_mode",
        "evidence_reference",
        "owner_attested",
        "bank_transaction_id",
        "document_id",
        "document_status",
    }
    assert set(RecordShareSaleCommand.__dataclass_fields__) == {
        "company_id",
        "actor_id",
        "correlation_id",
        "idempotency_key",
        "income_year",
        "action_id",
        "position_id",
        "sale_date",
        "sold_share_count",
        "proceeds",
        "transaction_costs",
        "sale_year_fund_equity_ratio_basis_points",
        "fund_tax_statement_reference",
        "evidence_mode",
        "evidence_reference",
        "owner_attested",
        "bank_transaction_id",
        "document_id",
        "document_status",
    }
    assert set(RecordReceivedDividendCommand.__dataclass_fields__) == {
        "company_id",
        "actor_id",
        "correlation_id",
        "idempotency_key",
        "income_year",
        "action_id",
        "position_id",
        "paying_company_name",
        "declared_date",
        "paid_date",
        "gross_amount",
        "tax_treatment",
        "lawful_dividend_confirmed",
        "group_exception_claimed",
        "year_end_ownership_basis_points",
        "year_end_voting_basis_points",
        "group_evidence_reference",
        "evidence_mode",
        "evidence_reference",
        "owner_attested",
        "bank_transaction_id",
        "document_id",
        "document_status",
    }
    assert set(RecordReceivedFundDistributionCommand.__dataclass_fields__) == {
        "company_id",
        "actor_id",
        "correlation_id",
        "idempotency_key",
        "income_year",
        "action_id",
        "position_id",
        "fund_name",
        "entitlement_date",
        "paid_date",
        "gross_amount",
        "opening_fund_equity_ratio_basis_points",
        "fund_tax_statement_reference",
        "evidence_mode",
        "evidence_reference",
        "owner_attested",
        "bank_transaction_id",
        "document_id",
        "document_status",
    }
    assert not ({"pydantic", "fastapi", "psycopg", "supabase"} & imports)
    assert "modules.ledger" not in source
    assert "BankDataProvider" not in source
    assert "LedgerLine" not in source


def test_canonical_commands_separate_recognition_from_cash_settlement() -> None:
    from talli_backend.modules.investments.public import (
        InvestmentEvidence,
        InvestmentFactReference,
        RecognizeReceivedDividendCommand,
        RecognizeReceivedFundDistributionCommand,
        RecognizeSharePurchaseCommand,
        RecognizeShareSaleCommand,
        SettleInvestmentCashCommand,
    )

    assert set(InvestmentFactReference.__dataclass_fields__) == {
        "capability",
        "record_id",
        "revision",
        "fact_sha256",
    }
    assert set(InvestmentEvidence.__dataclass_fields__) == {
        "mode",
        "reference",
        "owner_attested",
        "document_facts",
        "bank_fact",
    }

    recognition_contracts = {
        RecognizeSharePurchaseCommand: {
            "event_id",
            "investment_key",
            "investment_name",
            "investment_kind",
            "accounting_classification",
            "acquisition_date",
            "share_count",
            "purchase_amount",
            "transaction_costs",
            "org_number",
            "fund_equity_ratio_basis_points",
            "fund_tax_statement_reference",
            "trading_profile",
            "non_active_trading_confirmed",
            "share_class_code",
            "single_share_class_confirmed",
            "equal_share_rights_confirmed",
            "unusual_share_rights_absent_confirmed",
            "evidence",
        },
        RecognizeShareSaleCommand: {
            "event_id",
            "position_id",
            "sale_date",
            "sold_share_count",
            "proceeds",
            "transaction_costs",
            "sale_year_fund_equity_ratio_basis_points",
            "fund_tax_statement_reference",
            "evidence",
        },
        RecognizeReceivedDividendCommand: {
            "event_id",
            "position_id",
            "paying_company_name",
            "declared_date",
            "gross_amount",
            "lawful_dividend_confirmed",
            "group_exception_claimed",
            "year_end_ownership_basis_points",
            "year_end_voting_basis_points",
            "group_evidence_reference",
            "evidence",
        },
        RecognizeReceivedFundDistributionCommand: {
            "event_id",
            "position_id",
            "fund_name",
            "entitlement_date",
            "gross_amount",
            "opening_fund_equity_ratio_basis_points",
            "fund_tax_statement_reference",
            "evidence",
        },
    }
    base_fields = {
        "company_id",
        "actor_id",
        "correlation_id",
        "idempotency_key",
        "income_year",
    }
    for contract, fields in recognition_contracts.items():
        actual = set(contract.__dataclass_fields__)
        assert actual == base_fields | fields
        assert "paid_date" not in actual
        assert "bank_transaction_id" not in actual
        assert "tax_treatment" not in actual

    assert set(SettleInvestmentCashCommand.__dataclass_fields__) == base_fields | {
        "settlement_id",
        "event_id",
        "settlement_date",
        "amount",
        "evidence",
    }


def test_canonical_units_and_evidence_preserve_fractional_facts_by_lifecycle_stage() -> None:
    from talli_backend.modules.investments.public import (
        InvestmentAccountingClassification,
        InvestmentEconomicEventId,
        InvestmentEvidence,
        InvestmentEvidenceMode,
        InvestmentFactReference,
        InvestmentKind,
        InvestmentTradingProfile,
        InvestmentSettlementId,
        InvestmentSourceCapability,
        InvestmentSourceReference,
        InvestmentUnits,
        InvestmentsError,
        RecognizeSharePurchaseCommand,
        SettleInvestmentCashCommand,
    )
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

    units = InvestmentUnits.of("0.123456789012")
    assert units.amount == Decimal("0.123456789012")
    with pytest.raises(ValueError):
        InvestmentUnits.of("0.1234567890123")

    document_fact = InvestmentFactReference(
        InvestmentSourceCapability.DOCUMENTS,
        InvestmentSourceReference("80000000-0000-0000-0000-000000000001"),
        3,
        "a" * 64,
    )
    bank_fact = InvestmentFactReference(
        InvestmentSourceCapability.BANKING,
        InvestmentSourceReference("70000000-0000-0000-0000-000000000001"),
        1,
        "b" * 64,
    )
    revised_bank_fact = InvestmentFactReference(
        InvestmentSourceCapability.BANKING,
        InvestmentSourceReference("70000000-0000-0000-0000-000000000002"),
        2,
        "c" * 64,
    )
    with pytest.raises(InvestmentsError):
        InvestmentEvidence(
            InvestmentEvidenceMode.LINKED_SOURCES,
            "empty evidence",
            False,
            (),
            None,
        )

    recognition_evidence = InvestmentEvidence(
        InvestmentEvidenceMode.LINKED_SOURCES,
        "broker note",
        False,
        (document_fact,),
        None,
    )
    settlement_evidence = InvestmentEvidence(
        InvestmentEvidenceMode.LINKED_SOURCES,
        "bank transaction",
        False,
        (),
        bank_fact,
    )
    with pytest.raises(InvestmentsError):
        InvestmentEvidence(
            InvestmentEvidenceMode.LINKED_SOURCES,
            "caller-invented bank revision",
            False,
            (),
            revised_bank_fact,
        )
    base = {
        "company_id": CompanyId("10000000-0000-0000-0000-000000000001"),
        "actor_id": ActorId(
            ActorKind.USER,
            UserId("00000000-0000-0000-0000-000000000011"),
        ),
        "correlation_id": CorrelationId("investment-lifecycle-test"),
        "idempotency_key": IdempotencyKey("investment-lifecycle-key-0001"),
        "income_year": IncomeYear(2026),
    }
    purchase = RecognizeSharePurchaseCommand(
        **base,
        event_id=InvestmentEconomicEventId(
            "90000000-0000-0000-0000-000000000001"
        ),
        investment_key="fund-1",
        investment_name="Norsk fond",
        investment_kind=InvestmentKind.NORWEGIAN_EQUITY_FUND,
        accounting_classification=InvestmentAccountingClassification.CURRENT_FUND,
        acquisition_date=LocalDate(date(2026, 3, 1)),
        share_count=units,
        purchase_amount=Money.nok("1000"),
        transaction_costs=Money.nok("10"),
        org_number=None,
        fund_equity_ratio_basis_points=8000,
        fund_tax_statement_reference="statement-2026",
        trading_profile=InvestmentTradingProfile.LOW_VOLUME_NON_ACTIVE,
        non_active_trading_confirmed=True,
        share_class_code=None,
        single_share_class_confirmed=None,
        equal_share_rights_confirmed=None,
        unusual_share_rights_absent_confirmed=None,
        evidence=recognition_evidence,
    )
    assert purchase.share_count == units
    with pytest.raises(InvestmentsError):
        replace(purchase, evidence=settlement_evidence)

    settlement = SettleInvestmentCashCommand(
        **base,
        settlement_id=InvestmentSettlementId(
            "90000000-0000-0000-0000-000000000002"
        ),
        event_id=purchase.event_id,
        settlement_date=LocalDate(date(2026, 3, 3)),
        amount=Money.nok("1010"),
        evidence=settlement_evidence,
    )
    assert settlement.evidence.bank_fact == bank_fact
    with pytest.raises(InvestmentsError):
        replace(settlement, evidence=recognition_evidence)
