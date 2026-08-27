from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path
from typing import get_type_hints

import pytest


def test_ledger_public_contract_is_framework_and_transport_free() -> None:
    from talli_backend.modules.ledger import public

    source_path = Path(inspect.getsourcefile(public) or "")
    source = source_path.read_text(encoding="utf-8")
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

    assert not ({"pydantic", "fastapi", "psycopg", "supabase"} & imports)
    assert "BaseModel" not in source
    assert "Mapping[str, object]" not in source
    assert "access_token" not in source
    assert "status:" not in source
    assert "_LEDGER_ADAPTER_BINDINGS" not in source


def test_shared_values_are_typed_immutable_and_decimal_exact() -> None:
    from talli_backend.shared.kernel import (
        ActorId,
        ActorKind,
        CompanyId,
        CorrelationId,
        IdempotencyKey,
        IncomeYear,
        Money,
        UserId,
    )

    company_id = CompanyId("10000000-0000-0000-0000-000000000001")
    actor = ActorId(
        kind=ActorKind.USER,
        subject=UserId("20000000-0000-0000-0000-000000000002"),
    )
    money = Money.nok("100.005")

    assert str(company_id) == "10000000-0000-0000-0000-000000000001"
    assert str(actor.subject) == "20000000-0000-0000-0000-000000000002"
    assert money.amount == Decimal("100.01")
    assert IncomeYear(2026).value == 2026
    assert str(CorrelationId("ledger-contract-test")) == "ledger-contract-test"
    assert str(IdempotencyKey("30000000-0000-4000-8000-000000000003"))
    with pytest.raises(FrozenInstanceError):
        money.amount = Decimal("9")  # type: ignore[misc]


def test_ledger_commands_carry_explicit_identity_and_request_metadata() -> None:
    from talli_backend.modules.ledger.public import PostManualJournalCommand

    fields = set(PostManualJournalCommand.__dataclass_fields__)
    assert {"company_id", "actor_id", "correlation_id", "idempotency_key"} <= fields
    assert "access_token" not in fields
    assert "operation_id" not in fields


def test_ledger_public_commands_are_owned_intents_not_generic_source_postings() -> None:
    from talli_backend.modules.ledger import public

    assert not hasattr(public, "StructuredEntryRequest")
    assert not hasattr(public, "SourcePostingCommand")
    forbidden_fields = {"account", "accounts", "line", "lines", "memo", "risk_flags"}
    for name in (
        "PostBankSuggestionOutcomeCommand",
        "PostInvestmentPurchaseCommand",
        "PostInvestmentSaleCommand",
        "PostInvestmentDividendCommand",
        "PostOwnerDividendDeclaredCommand",
        "PostOwnerDividendPaymentCommand",
        "PostShareholderLoanCommand",
        "PostTaxSettlementCommand",
        "RecognizeHoldingActionCommand",
    ):
        command = getattr(public, name)
        assert name in public.__all__
        assert command.__dataclass_params__.frozen
        assert not (set(command.__dataclass_fields__) & forbidden_fields)


def test_opening_balance_contract_does_not_own_shareholder_records() -> None:
    from talli_backend.modules.ledger.public import (
        LedgerSourceCapability,
        PostOpeningBalanceCommand,
    )

    fields = set(PostOpeningBalanceCommand.__dataclass_fields__)
    assert "opening_snapshot_id" in fields
    assert (
        LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING.value
        == "SHAREHOLDER_REGISTER_FILING"
    )
    assert "shareholders" not in fields
    assert "share_count" not in fields
    assert "nominal_value" not in fields


def test_ledger_errors_use_domain_categories_not_http_statuses() -> None:
    from talli_backend.modules.ledger.public import LedgerError
    from talli_backend.shared.kernel import DomainError, ErrorCategory

    error = LedgerError.invalid_input("LEDGER_ENTRY_UNBALANCED")
    assert isinstance(error, DomainError)
    assert error.category is ErrorCategory.INVALID_INPUT
    assert not hasattr(error, "status")
    with pytest.raises(ValueError):
        LedgerError.invalid_input("LEDGER_UNDECLARED_ERROR")


def test_public_dates_and_cursors_are_owned_value_objects() -> None:
    from talli_backend.modules.ledger.public import (
        LedgerCursor,
        LedgerPage,
        PostAdministrativeCostCommand,
    )
    from talli_backend.shared.kernel import LocalDate

    administrative_cost_hints = get_type_hints(PostAdministrativeCostCommand)
    page_hints = get_type_hints(LedgerPage)

    assert administrative_cost_hints["paid_date"] is LocalDate
    assert LedgerCursor in page_hints["next_cursor"].__args__
    assert str(LedgerCursor("opaque-cursor")) == "opaque-cursor"
    with pytest.raises(ValueError):
        LedgerCursor("x" * 4097)


def test_application_depends_on_the_public_ledger_facade_not_internal_service() -> None:
    from talli_backend.application import ledger_workflow

    source_path = Path(inspect.getsourcefile(ledger_workflow) or "")
    source = source_path.read_text(encoding="utf-8")

    assert "modules.ledger.service" not in source
    assert "LedgerFacadeFactory" in source
