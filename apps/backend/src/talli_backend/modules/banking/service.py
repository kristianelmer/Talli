"""Private policy implementation for the banking capability."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation

from talli_backend.modules.banking.public import (
    AcceptBankSuggestionCommand,
    AcceptedBankSuggestion,
    AccountingEntryReference,
    BankStatementImportResult,
    BankSuggestion,
    BankSuggestionAcceptancePage,
    BankSuggestionKind,
    BankTransaction,
    BankTransactionPage,
    BankingCursor,
    BankingError,
    BankingErrorCode,
    BankingPersistence,
    CURRENT_BANK_SUGGESTION_RULE_VERSION,
    ImportBankStatementCommand,
    ImportedBankTransaction,
    PreparedBankSuggestion,
    SupportedBankDataFormat,
)
from talli_backend.shared.kernel import ActorId, CompanyId, CorrelationId, IncomeYear, LocalDate, Money


_SUGGESTION_RULES = (
    (
        BankSuggestionKind.BANK_FEE,
        "Teksten beskriver et bankgebyr og beløpet er en utbetaling.",
        ("arsgebyr", "bankgebyr", "bank fee", "annual fee"),
        "outgoing",
    ),
    (
        BankSuggestionKind.SYSTEM_SUBSCRIPTION,
        "Teksten beskriver et systemabonnement og beløpet er en utbetaling.",
        ("systemabonnement", "system subscription"),
        "outgoing",
    ),
    (
        BankSuggestionKind.DEPOSIT_INTEREST,
        "Teksten beskriver renteinntekt og beløpet er en innbetaling.",
        ("renter", "rente", "interest"),
        "incoming",
    ),
)


def _normalized_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(character for character in decomposed if not unicodedata.combining(character))
    return re.sub(r"\s+", " ", without_marks.lower()).strip()


def _source_hash(
    transaction_date: date,
    text: str,
    amount: Decimal,
    balance: Decimal | None,
) -> str:
    parts = [
        transaction_date.isoformat(),
        text,
        f"{amount:.2f}",
        "" if balance is None else f"{balance:.2f}",
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _parse_decimal(value: str, *, required: bool) -> Decimal | None:
    stripped = value.strip()
    if not stripped and not required:
        return None
    try:
        parsed = Decimal(stripped)
    except InvalidOperation:
        raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID) from None
    if not parsed.is_finite():
        raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
    return parsed


class BankingService:
    def __init__(self, persistence: BankingPersistence) -> None:
        self._persistence = persistence

    @staticmethod
    def parse_statement(command: ImportBankStatementCommand) -> tuple[ImportedBankTransaction, ...]:
        if command.data_format is not SupportedBankDataFormat.CSV:
            raise BankingError.invalid_input(BankingErrorCode.STATEMENT_FORMAT_UNSUPPORTED)
        try:
            rows = csv.DictReader(io.StringIO(command.statement_text))
            headers = tuple(header.strip().lower() for header in (rows.fieldnames or ()))
            if not {"date", "text", "amount"} <= set(headers) or len(headers) != len(set(headers)):
                raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
            parsed: list[ImportedBankTransaction] = []
            for raw in rows:
                normalized = {
                    str(key).strip().lower(): str(value or "").strip()
                    for key, value in raw.items()
                    if key is not None
                }
                transaction_date = date.fromisoformat(normalized.get("date", ""))
                if transaction_date.year != command.income_year.value:
                    raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
                text = normalized.get("text", "").strip()
                amount = _parse_decimal(normalized.get("amount", ""), required=True)
                balance = _parse_decimal(normalized.get("balance", ""), required=False)
                if not text or amount is None:
                    raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
                parsed.append(
                    ImportedBankTransaction(
                        transaction_date=LocalDate(transaction_date),
                        text=text,
                        amount=Money.nok(amount),
                        balance=Money.nok(balance) if balance is not None else None,
                        source_hash=_source_hash(transaction_date, text, amount, balance),
                    )
                )
        except (csv.Error, UnicodeError, ValueError):
            raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID) from None
        if not parsed:
            raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
        return tuple(parsed)

    @staticmethod
    def suggestion_for(transaction: BankTransaction) -> BankSuggestion | None:
        if transaction.amount.amount == 0 or transaction.matched_entry_id is not None:
            return None
        text = _normalized_text(transaction.text)
        matching = [
            (kind, reason, direction)
            for kind, reason, patterns, direction in _SUGGESTION_RULES
            if any(pattern in text for pattern in patterns)
        ]
        if len(matching) != 1:
            return None
        kind, reason, direction = matching[0]
        if not (
            (direction == "outgoing" and transaction.amount.amount < 0)
            or (direction == "incoming" and transaction.amount.amount > 0)
        ):
            return None
        return BankSuggestion(
            kind=kind,
            rule_version=CURRENT_BANK_SUGGESTION_RULE_VERSION,
            reason=reason,
        )

    async def import_statement(
        self, command: ImportBankStatementCommand
    ) -> BankStatementImportResult:
        return await self._persistence.import_transactions(
            command,
            transactions=self.parse_statement(command),
        )

    async def prepare_suggestion_acceptance(
        self, command: AcceptBankSuggestionCommand
    ) -> PreparedBankSuggestion:
        transaction = await self._persistence.get_transaction_for_acceptance(command)
        if transaction.company_id != command.company_id or transaction.income_year != command.income_year:
            raise BankingError.not_found()
        if transaction.matched_entry_id is not None:
            raise BankingError.conflict(BankingErrorCode.TRANSACTION_ALREADY_RECONCILED)
        suggestion = self.suggestion_for(transaction)
        if suggestion is None:
            raise BankingError.precondition_failed(BankingErrorCode.SUGGESTION_NOT_AVAILABLE)
        if (
            suggestion.kind is not command.expected_suggestion
            or suggestion.rule_version != command.expected_rule_version
        ):
            raise BankingError.precondition_failed(BankingErrorCode.SUGGESTION_STALE)
        return PreparedBankSuggestion(transaction=transaction, suggestion=suggestion)

    async def complete_suggestion_acceptance(
        self,
        command: AcceptBankSuggestionCommand,
        *,
        prepared: PreparedBankSuggestion,
        accounting_entry_id: AccountingEntryReference,
    ) -> AcceptedBankSuggestion:
        return await self._persistence.complete_suggestion_acceptance(
            command,
            prepared=prepared,
            accounting_entry_id=accounting_entry_id,
        )

    async def list_transactions(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: BankingCursor | None,
        limit: int,
    ) -> BankTransactionPage:
        page = await self._persistence.list_transactions(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )
        return replace(
            page,
            items=tuple(
                replace(item, suggestion=self.suggestion_for(item))
                for item in page.items
            ),
        )

    async def list_suggestion_acceptances(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: BankingCursor | None,
        limit: int,
    ) -> BankSuggestionAcceptancePage:
        return await self._persistence.list_suggestion_acceptances(
            actor_id=actor_id,
            company_ids=company_ids,
            correlation_id=correlation_id,
            cursor=cursor,
            limit=limit,
        )


__all__ = ["BankingService"]
