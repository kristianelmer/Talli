from __future__ import annotations

import ast
import inspect
from pathlib import Path


def test_owner_dividend_contract_is_governance_owned_and_transport_free() -> None:
    from talli_backend.modules.corporate_governance import public
    from talli_backend.modules.corporate_governance.public import (
        ApproveOwnerDividendCommand,
        FinalizeOwnerDividendCommand,
        OwnerDividendProposalCommand,
        RecordOwnerDividendPaymentCommand,
        RegisterOwnerDividendDocumentsCommand,
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

    assert set(OwnerDividendProposalCommand.__dataclass_fields__) == {
        "company_id",
        "actor_id",
        "correlation_id",
        "idempotency_key",
        "income_year",
        "decision_id",
        "document_set_id",
        "company",
        "shareholders",
        "annual_basis",
        "reviewed_facts",
        "board_meeting",
        "board_participants",
        "general_meeting",
        "shareholder_ballots",
        "one_share_class_confirmed",
        "full_board_participation_confirmed",
        "unanimous_board_confirmed",
        "supported_dividend_basis_confirmed",
        "prudent_equity_and_liquidity_confirmed",
        "dividend_amount_ore",
        "payment_date",
    }
    assert set(RegisterOwnerDividendDocumentsCommand.__dataclass_fields__) == {
        "company_id",
        "actor_id",
        "correlation_id",
        "idempotency_key",
        "decision_id",
        "document_set_id",
        "decision_hash",
        "artifacts",
    }
    assert set(ApproveOwnerDividendCommand.__dataclass_fields__) == {
        "company_id",
        "actor_id",
        "correlation_id",
        "idempotency_key",
        "decision_id",
        "document_set_id",
        "decision_hash",
        "approval_event_id",
    }
    assert set(FinalizeOwnerDividendCommand.__dataclass_fields__) == {
        "company_id",
        "actor_id",
        "correlation_id",
        "idempotency_key",
        "income_year",
        "decision_id",
        "document_set_id",
        "decision_hash",
        "finalization_id",
        "holding_action_id",
        "ledger_entry_id",
    }
    assert set(RecordOwnerDividendPaymentCommand.__dataclass_fields__) == {
        "company_id",
        "actor_id",
        "correlation_id",
        "idempotency_key",
        "income_year",
        "decision_id",
        "document_set_id",
        "decision_hash",
        "payment_event_id",
        "holding_action_id",
        "ledger_entry_id",
        "bank_transaction_id",
    }
    assert not ({"pydantic", "fastapi", "psycopg", "supabase"} & imports)
    assert "modules.ledger" not in source
    assert "modules.documents" not in source
    assert "LedgerLine" not in source
    assert "storage_key" not in source


def test_public_contract_exposes_only_opaque_cross_capability_references() -> None:
    from talli_backend.modules.corporate_governance.public import (
        AccountingEntryReference,
        BankTransactionReference,
        DocumentReference,
        OwnerDividendArtifactReference,
    )

    assert set(OwnerDividendArtifactReference.__dataclass_fields__) == {
        "artifact_id",
        "document_id",
        "artifact_kind",
        "content_sha256",
        "byte_length",
    }
    for reference in (
        AccountingEntryReference("11111111-1111-4111-8111-111111111111"),
        BankTransactionReference("22222222-2222-4222-8222-222222222222"),
        DocumentReference("33333333-3333-4333-8333-333333333333"),
    ):
        assert str(reference).count("-") == 4


def test_shareholder_loan_contract_is_governance_owned_and_policy_complete() -> None:
    from talli_backend.modules.corporate_governance.public import (
        RecordShareholderLoanCommand,
        ShareholderLoanDirection,
        ShareholderLoanDocumentStatus,
    )

    assert set(RecordShareholderLoanCommand.__dataclass_fields__) == {
        "company_id",
        "actor_id",
        "correlation_id",
        "idempotency_key",
        "income_year",
        "action_id",
        "ledger_entry_id",
        "loan_date",
        "amount",
        "direction",
        "counterparty_name",
        "document_status",
        "interest_modelled",
        "related_party_security",
        "bank_transaction_id",
        "document_id",
    }
    assert {item.value for item in ShareholderLoanDirection} == {
        "shareholder_to_company",
        "company_to_corporate_shareholder",
        "company_to_personal_shareholder",
    }
    assert {item.value for item in ShareholderLoanDocumentStatus} == {
        "attached",
        "missing_accepted_warning",
        "not_required",
    }
