from __future__ import annotations

import ast
import inspect
from pathlib import Path


def test_banking_public_contract_is_framework_transport_and_account_free() -> None:
    from talli_backend.modules.banking import public

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

    assert not ({"pydantic", "fastapi", "psycopg", "supabase"} & imports)
    assert "modules.ledger" not in source
    assert "account_number" not in source
    assert "LedgerLine" not in source
    assert "access_token" not in source


def test_provider_facing_import_contract_cannot_request_a_posting() -> None:
    from talli_backend.modules.banking.public import ImportBankStatementCommand

    fields = set(ImportBankStatementCommand.__dataclass_fields__)
    assert fields == {
        "company_id",
        "actor_id",
        "correlation_id",
        "idempotency_key",
        "income_year",
        "data_format",
        "statement_text",
    }
    assert not ({"account", "lines", "memo", "ledger_entry_id"} & fields)
