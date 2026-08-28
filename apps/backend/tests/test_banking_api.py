from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from talli_backend.main import create_app
from talli_backend.modules.banking.public import (
    AcceptedBankSuggestion,
    AccountingEntryReference,
    BankStatementImportResult,
    BankSuggestion,
    BankSuggestionAcceptanceId,
    BankSuggestionKind,
    BankTransaction,
    BankTransactionId,
    BankTransactionPage,
    BankSuggestionAcceptancePage,
    BankingCursor,
    BankingPage,
)
from talli_backend.modules.ledger.public import (
    LedgerEntryId,
    LedgerEntryKind,
    PostedLedgerEntry,
)
from talli_backend.shared.kernel import (
    ActorId,
    ActorKind,
    CompanyId,
    CorrelationId,
    IncomeYear,
    LocalDate,
    Money,
    Timestamp,
    UserId,
)


ACTOR_ID = ActorId(
    ActorKind.USER,
    UserId("20000000-0000-0000-0000-000000000002"),
)


class BankingSessionStub:
    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.imported_command = None

    @property
    def actor_id(self) -> ActorId:
        return ACTOR_ID

    async def session(self, access_token: str) -> BankingSessionStub:
        self.tokens.append(access_token)
        return self

    async def import_transactions(self, command, *, transactions):
        self.imported_command = command
        return BankStatementImportResult(
            imported_count=len(transactions),
            duplicate_count=0,
            transactions=(),
            replayed=False,
        )

    async def list_transactions(
        self, *, actor_id, company_ids, correlation_id, cursor, limit
    ) -> BankTransactionPage:
        self.list_request = {
            "actor_id": actor_id,
            "company_ids": company_ids,
            "correlation_id": correlation_id,
            "cursor": cursor,
            "limit": limit,
        }
        return BankTransactionPage(
            items=(
                BankTransaction(
                    transaction_id=BankTransactionId(
                        "40000000-0000-0000-0000-000000000004"
                    ),
                    company_id=CompanyId(
                        "10000000-0000-0000-0000-000000000001"
                    ),
                    income_year=IncomeYear(2026),
                    transaction_date=LocalDate(date(2026, 1, 2)),
                    text="Annual fee",
                    amount=Money.nok("-89.00"),
                    balance=Money.nok("1000.00"),
                    source_hash="a" * 64,
                    matched_entry_id=None,
                    matched_action_reference=None,
                    warning_accepted=False,
                    suggestion=None,
                    created_at=Timestamp(datetime(2026, 1, 2, 12, tzinfo=UTC)),
                ),
            ),
            page=BankingPage(
                next_cursor=BankingCursor("opaque-next"),
                has_more=True,
            ),
        )

    @asynccontextmanager
    async def transaction(self):
        yield self

    async def get_suggestion_acceptance_replay(self, command):
        return None

    async def get_transaction_for_acceptance(self, command) -> BankTransaction:
        return BankTransaction(
            transaction_id=command.bank_transaction_id,
            company_id=command.company_id,
            income_year=command.income_year,
            transaction_date=LocalDate(date(2026, 1, 2)),
            text="Annual fee",
            amount=Money.nok("-89.00"),
            balance=Money.nok("1000.00"),
            source_hash="a" * 64,
            matched_entry_id=None,
            matched_action_reference=None,
            warning_accepted=False,
            suggestion=None,
            created_at=Timestamp(datetime(2026, 1, 2, 12, tzinfo=UTC)),
        )

    async def post_entry(self, command, **posting) -> PostedLedgerEntry:
        self.posted_command = command
        self.posting = posting
        return PostedLedgerEntry(
            entry_id=LedgerEntryId("50000000-0000-0000-0000-000000000005"),
            company_id=command.company_id,
            income_year=command.income_year,
            entry_kind=LedgerEntryKind.BANK_RULE_SUGGESTION,
            posted_at=Timestamp(datetime(2026, 1, 2, 12, 1, tzinfo=UTC)),
            replayed=False,
        )

    async def complete_suggestion_acceptance(
        self, command, *, prepared, accounting_entry_id
    ) -> AcceptedBankSuggestion:
        return AcceptedBankSuggestion(
            acceptance_id=command.acceptance_id,
            bank_transaction_id=command.bank_transaction_id,
            accounting_entry_id=accounting_entry_id,
            suggestion=prepared.suggestion,
            accepted_by=command.actor_id,
            accepted_at=Timestamp(datetime(2026, 1, 2, 12, 2, tzinfo=UTC)),
            replayed=False,
        )

    async def list_suggestion_acceptances(
        self, *, actor_id, company_ids, correlation_id, cursor, limit
    ) -> BankSuggestionAcceptancePage:
        self.acceptance_list_request = {
            "actor_id": actor_id,
            "company_ids": company_ids,
            "correlation_id": correlation_id,
            "cursor": cursor,
            "limit": limit,
        }
        return BankSuggestionAcceptancePage(
            items=(
                AcceptedBankSuggestion(
                    acceptance_id=BankSuggestionAcceptanceId(
                        "60000000-0000-4000-8000-000000000006"
                    ),
                    bank_transaction_id=BankTransactionId(
                        "40000000-0000-0000-0000-000000000004"
                    ),
                    accounting_entry_id=AccountingEntryReference(
                        "50000000-0000-0000-0000-000000000005"
                    ),
                    suggestion=BankSuggestion(
                        kind=BankSuggestionKind.BANK_FEE,
                        rule_version="2026-07-13.1",
                        reason=(
                            "Teksten beskriver et bankgebyr og beløpet er en "
                            "utbetaling."
                        ),
                    ),
                    accepted_by=ACTOR_ID,
                    accepted_at=Timestamp(
                        datetime(2026, 1, 2, 12, 2, tzinfo=UTC)
                    ),
                    replayed=False,
                ),
            ),
            page=BankingPage(next_cursor=None, has_more=False),
        )


def test_owner_imports_a_supported_bank_statement_through_fastapi() -> None:
    banking = BankingSessionStub()
    client = TestClient(create_app(banking_session_factory=banking))

    response = client.post(
        "/api/v1/banking/statement-imports",
        headers={
            "Authorization": "Bearer session-token",
            "Idempotency-Key": "30000000-0000-4000-8000-000000000003",
            "X-Request-ID": "banking-import-test",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "dataFormat": "CSV",
            "statementText": (
                "date,text,amount,balance\n"
                "2026-01-02,Annual fee,-89.00,1000.00\n"
            ),
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "importedCount": 1,
        "duplicateCount": 0,
        "replayed": False,
    }
    assert response.headers["X-Request-ID"] == "banking-import-test"
    assert banking.tokens == ["session-token"]
    assert banking.imported_command.actor_id == ACTOR_ID
    assert str(banking.imported_command.correlation_id) == "banking-import-test"
    assert str(banking.imported_command.idempotency_key) == (
        "30000000-0000-4000-8000-000000000003"
    )
    assert banking.imported_command.statement_text.endswith("1000.00\n")


def test_owner_lists_tenant_scoped_bank_transactions_with_opaque_pagination() -> None:
    banking = BankingSessionStub()
    client = TestClient(create_app(banking_session_factory=banking))

    response = client.get(
        "/api/v1/banking/transactions",
        params={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "cursor": "opaque-current",
            "limit": 25,
        },
        headers={
            "Authorization": "Bearer session-token",
            "X-Request-ID": "banking-list-test",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [
            {
                "transactionId": "40000000-0000-0000-0000-000000000004",
                "companyId": "10000000-0000-0000-0000-000000000001",
                "incomeYear": 2026,
                "transactionDate": "2026-01-02",
                "text": "Annual fee",
                "amount": {"amount": "-89.00", "currency": "NOK"},
                "balance": {"amount": "1000.00", "currency": "NOK"},
                "sourceHash": "a" * 64,
                "matchedEntryId": None,
                "matchedActionReference": None,
                "warningAccepted": False,
                "suggestion": {
                    "kind": "BANK_FEE",
                    "ruleVersion": "2026-07-13.1",
                    "reason": (
                        "Teksten beskriver et bankgebyr og beløpet er en utbetaling."
                    ),
                },
                "createdAt": "2026-01-02T12:00:00Z",
            }
        ],
        "page": {"nextCursor": "opaque-next", "hasMore": True},
    }
    assert banking.list_request == {
        "actor_id": ACTOR_ID,
        "company_ids": (
            CompanyId("10000000-0000-0000-0000-000000000001"),
        ),
        "correlation_id": CorrelationId("banking-list-test"),
        "cursor": BankingCursor("opaque-current"),
        "limit": 25,
    }


def test_owner_explicitly_accepts_a_current_suggestion_atomically() -> None:
    banking = BankingSessionStub()
    client = TestClient(create_app(banking_session_factory=banking))

    response = client.post(
        "/api/v1/banking/suggestion-acceptances",
        headers={
            "Authorization": "Bearer session-token",
            "Idempotency-Key": "60000000-0000-4000-8000-000000000006",
            "X-Request-ID": "banking-accept-test",
        },
        json={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "incomeYear": 2026,
            "acceptanceId": "60000000-0000-4000-8000-000000000006",
            "bankTransactionId": "40000000-0000-0000-0000-000000000004",
            "expectedSuggestion": "BANK_FEE",
            "expectedRuleVersion": "2026-07-13.1",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "acceptanceId": "60000000-0000-4000-8000-000000000006",
        "bankTransactionId": "40000000-0000-0000-0000-000000000004",
        "accountingEntryId": "50000000-0000-0000-0000-000000000005",
        "suggestion": {
            "kind": "BANK_FEE",
            "ruleVersion": "2026-07-13.1",
            "reason": "Teksten beskriver et bankgebyr og beløpet er en utbetaling.",
        },
        "acceptedBy": "20000000-0000-0000-0000-000000000002",
        "acceptedAt": "2026-01-02T12:02:00Z",
        "replayed": False,
    }
    assert banking.posted_command.correlation_id == CorrelationId(
        "banking-accept-test"
    )
    assert str(banking.posting["source_record_id"]) == (
        "60000000-0000-4000-8000-000000000006"
    )
    assert not hasattr(banking.posted_command, "lines")


def test_owner_lists_immutable_suggestion_acceptances() -> None:
    banking = BankingSessionStub()
    client = TestClient(create_app(banking_session_factory=banking))

    response = client.get(
        "/api/v1/banking/suggestion-acceptances",
        params={
            "companyId": "10000000-0000-0000-0000-000000000001",
            "limit": 10,
        },
        headers={
            "Authorization": "Bearer session-token",
            "X-Request-ID": "banking-acceptance-list-test",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [
            {
                "acceptanceId": "60000000-0000-4000-8000-000000000006",
                "bankTransactionId": "40000000-0000-0000-0000-000000000004",
                "accountingEntryId": "50000000-0000-0000-0000-000000000005",
                "suggestion": {
                    "kind": "BANK_FEE",
                    "ruleVersion": "2026-07-13.1",
                    "reason": (
                        "Teksten beskriver et bankgebyr og beløpet er en utbetaling."
                    ),
                },
                "acceptedBy": "20000000-0000-0000-0000-000000000002",
                "acceptedAt": "2026-01-02T12:02:00Z",
                "replayed": False,
            }
        ],
        "page": {"nextCursor": None, "hasMore": False},
    }
    assert banking.acceptance_list_request["actor_id"] == ACTOR_ID
    assert banking.acceptance_list_request["company_ids"] == (
        CompanyId("10000000-0000-0000-0000-000000000001"),
    )
    assert banking.acceptance_list_request["limit"] == 10
