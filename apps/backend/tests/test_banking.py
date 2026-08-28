from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest
from talli_backend.modules.banking.public import (
    AcceptBankSuggestionCommand,
    AccountingEntryReference,
    BankStatementImportResult,
    BankSuggestionAcceptanceId,
    BankSuggestionKind,
    BankTransaction,
    BankTransactionId,
    BankingError,
    ImportBankStatementCommand,
    SupportedBankDataFormat,
)
from talli_backend.modules.banking.service import BankingService
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
INCOME_YEAR = IncomeYear(2026)


def metadata() -> dict[str, object]:
    return {
        "company_id": COMPANY_ID,
        "actor_id": ACTOR_ID,
        "correlation_id": CorrelationId("banking-test"),
        "idempotency_key": IdempotencyKey("30000000-0000-4000-8000-000000000003"),
        "income_year": INCOME_YEAR,
    }


class BankingPersistenceStub:
    def __init__(self, transaction: BankTransaction | None = None) -> None:
        self.transaction = transaction
        self.imported = ()

    async def import_transactions(self, command: object, *, transactions: tuple) -> BankStatementImportResult:
        self.imported = transactions
        return BankStatementImportResult(len(transactions), 0, (), False)

    async def get_transaction_for_acceptance(self, command: object) -> BankTransaction:
        assert self.transaction is not None
        return self.transaction


def transaction(text: str, amount: str, *, matched: bool = False) -> BankTransaction:
    return BankTransaction(
        transaction_id=BankTransactionId("40000000-0000-0000-0000-000000000004"),
        company_id=COMPANY_ID,
        income_year=INCOME_YEAR,
        transaction_date=LocalDate(date(2026, 1, 2)),
        text=text,
        amount=Money.nok(amount),
        balance=None,
        source_hash="a" * 64,
        matched_entry_id=(
            AccountingEntryReference("50000000-0000-0000-0000-000000000005")
            if matched
            else None
        ),
        matched_action_reference=None,
        warning_accepted=False,
        suggestion=None,
        created_at=Timestamp(datetime(2026, 1, 2, tzinfo=UTC)),
    )


def acceptance(kind: BankSuggestionKind) -> AcceptBankSuggestionCommand:
    return AcceptBankSuggestionCommand(
        **metadata(),
        acceptance_id=BankSuggestionAcceptanceId("60000000-0000-0000-0000-000000000006"),
        bank_transaction_id=BankTransactionId("40000000-0000-0000-0000-000000000004"),
        expected_suggestion=kind,
        expected_rule_version="2026-07-13.1",
    )


def test_csv_capture_is_deterministic_and_preserves_legacy_duplicate_identity() -> None:
    persistence = BankingPersistenceStub()
    command = ImportBankStatementCommand(
        **metadata(),
        data_format=SupportedBankDataFormat.CSV,
        statement_text='date,text,amount,balance\n2026-01-02,"Annual fee, bank",-89.005,1000\n',
    )

    result = asyncio.run(BankingService(persistence).import_statement(command))

    assert result.imported_count == 1
    assert persistence.imported[0].text == "Annual fee, bank"
    assert persistence.imported[0].amount == Money.nok("-89.005")
    assert persistence.imported[0].source_hash == "3ccdf363a397e1c7f97972b88df98d91c5711d496b8d96b85e7789f748bf856b"


@pytest.mark.parametrize(
    ("text", "amount", "kind"),
    [
        ("Årsgebyr", "-89", BankSuggestionKind.BANK_FEE),
        ("Systemabonnement Talli", "-990", BankSuggestionKind.SYSTEM_SUBSCRIPTION),
        ("Renter innskudd", "125.5", BankSuggestionKind.DEPOSIT_INTEREST),
    ],
)
def test_banking_owns_account_free_deterministic_suggestion_rules(
    text: str, amount: str, kind: BankSuggestionKind
) -> None:
    suggestion = BankingService.suggestion_for(transaction(text, amount))

    assert suggestion is not None
    assert suggestion.kind is kind
    assert suggestion.rule_version == "2026-07-13.1"
    assert not hasattr(suggestion, "lines")
    assert not hasattr(suggestion, "account")


@pytest.mark.parametrize(
    ("text", "amount"),
    [
        ("Renter lån", "-125"),
        ("Bankgebyr og renter", "125"),
        ("Overføring til eier", "-1000"),
        ("Restaurant", "125"),
        ("Bankgebyr", "0"),
    ],
)
def test_ambiguous_wrong_direction_and_unknown_rows_never_suggest(
    text: str, amount: str
) -> None:
    assert BankingService.suggestion_for(transaction(text, amount)) is None


def test_acceptance_revalidates_the_locked_source_fact_and_expected_preview() -> None:
    persistence = BankingPersistenceStub(transaction("Årsgebyr", "-89"))
    prepared = asyncio.run(
        BankingService(persistence).prepare_suggestion_acceptance(
            acceptance(BankSuggestionKind.BANK_FEE)
        )
    )
    assert prepared.suggestion.kind is BankSuggestionKind.BANK_FEE

    with pytest.raises(BankingError) as stale:
        asyncio.run(
            BankingService(persistence).prepare_suggestion_acceptance(
                acceptance(BankSuggestionKind.SYSTEM_SUBSCRIPTION)
            )
        )
    assert stale.value.code == "BANKING_SUGGESTION_STALE"

    persistence.transaction = transaction("Årsgebyr", "-89", matched=True)
    with pytest.raises(BankingError) as reconciled:
        asyncio.run(
            BankingService(persistence).prepare_suggestion_acceptance(
                acceptance(BankSuggestionKind.BANK_FEE)
            )
        )
    assert reconciled.value.code == "BANKING_TRANSACTION_ALREADY_RECONCILED"
