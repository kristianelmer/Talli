from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime

from talli_backend.application.banking_workflow import BankingSession
from talli_backend.modules.banking.public import (
    AcceptBankSuggestionCommand,
    AcceptedBankSuggestion,
    AccountingEntryReference,
    BankSuggestion,
    BankSuggestionAcceptanceId,
    BankSuggestionKind,
    BankTransaction,
    BankTransactionId,
)
from talli_backend.modules.ledger.public import (
    BankSuggestionRule,
    LedgerEntryId,
    LedgerEntryKind,
    PostedLedgerEntry,
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
    Timestamp,
    UserId,
)


COMPANY_ID = CompanyId("10000000-0000-0000-0000-000000000001")
ACTOR_ID = ActorId(ActorKind.USER, UserId("20000000-0000-0000-0000-000000000002"))
TRANSACTION_ID = BankTransactionId("30000000-0000-0000-0000-000000000003")
ACCEPTANCE_ID = BankSuggestionAcceptanceId("40000000-0000-0000-0000-000000000004")
ENTRY_ID = LedgerEntryId("50000000-0000-0000-0000-000000000005")
NOW = Timestamp(datetime(2026, 8, 28, tzinfo=UTC))


class WorkflowTransaction:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.posted_command = None

    @property
    def actor_id(self):
        return ACTOR_ID

    async def get_transaction_for_acceptance(self, command):
        self.events.append("banking:prepare")
        return BankTransaction(
            transaction_id=TRANSACTION_ID,
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            transaction_date=LocalDate(date(2026, 8, 28)),
            text="Årsgebyr",
            amount=Money.nok("-89"),
            balance=None,
            source_hash="a" * 64,
            matched_entry_id=None,
            matched_action_reference=None,
            warning_accepted=False,
            suggestion=None,
            created_at=NOW,
        )

    async def get_suggestion_acceptance_replay(self, command):
        self.events.append("banking:replay")
        return None

    async def complete_suggestion_acceptance(
        self, command, *, prepared, accounting_entry_id
    ):
        self.events.append("banking:complete")
        assert accounting_entry_id == AccountingEntryReference(str(ENTRY_ID))
        return AcceptedBankSuggestion(
            acceptance_id=ACCEPTANCE_ID,
            bank_transaction_id=TRANSACTION_ID,
            accounting_entry_id=accounting_entry_id,
            suggestion=prepared.suggestion,
            accepted_by=ACTOR_ID,
            accepted_at=NOW,
            replayed=False,
        )


class SessionPersistence(WorkflowTransaction):
    @asynccontextmanager
    async def transaction(self):
        self.events.append("transaction:begin")
        yield self
        self.events.append("transaction:commit")


class LedgerFacade:
    def __init__(self, transaction: WorkflowTransaction) -> None:
        self.transaction = transaction

    async def post_bank_suggestion_outcome(self, command):
        self.transaction.events.append("ledger:post")
        self.transaction.posted_command = command
        return PostedLedgerEntry(
            entry_id=ENTRY_ID,
            company_id=COMPANY_ID,
            income_year=IncomeYear(2026),
            entry_kind=LedgerEntryKind.BANK_RULE_SUGGESTION,
            posted_at=NOW,
            replayed=False,
        )


def test_acceptance_composes_banking_and_ledger_public_interfaces_atomically() -> None:
    persistence = SessionPersistence()
    session = BankingSession(persistence, LedgerFacade)
    command = AcceptBankSuggestionCommand(
        company_id=COMPANY_ID,
        actor_id=ACTOR_ID,
        correlation_id=CorrelationId("banking-workflow-test"),
        idempotency_key=IdempotencyKey("60000000-0000-4000-8000-000000000006"),
        income_year=IncomeYear(2026),
        acceptance_id=ACCEPTANCE_ID,
        bank_transaction_id=TRANSACTION_ID,
        expected_suggestion=BankSuggestionKind.BANK_FEE,
        expected_rule_version="2026-07-13.1",
    )

    result = asyncio.run(session.accept_suggestion(command))

    assert result.accounting_entry_id == AccountingEntryReference(str(ENTRY_ID))
    assert persistence.events == [
        "transaction:begin",
        "banking:replay",
        "banking:prepare",
        "ledger:post",
        "banking:complete",
        "transaction:commit",
    ]
    assert persistence.posted_command.rule is BankSuggestionRule.BANK_FEE
    assert persistence.posted_command.amount == Money.nok("89")
    assert persistence.posted_command.transaction_text == "Årsgebyr"
    assert not hasattr(persistence.posted_command, "lines")
