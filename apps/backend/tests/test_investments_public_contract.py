from __future__ import annotations

import ast
import inspect
from pathlib import Path


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
