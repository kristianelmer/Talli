"""Private policy implementation for the banking capability."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation

from talli_backend.modules.banking.public import (
    AcceptBankSuggestionCommand,
    AcceptedBankSuggestion,
    AccountingEntryReference,
    BankFilePreview,
    BankFilePreviewCommand,
    BankProviderTransaction,
    BankStatementImportResult,
    BankSuggestion,
    BankSuggestionAcceptancePage,
    BankSuggestionKind,
    BankTransaction,
    BankTransactionPage,
    BankTransactionState,
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


def _stable_source_hash(
    *,
    account_id: object,
    booking_date: date,
    value_date: date | None,
    text: str,
    amount: Decimal,
    reference: str,
    occurrence: int,
) -> str:
    normalized_text = _normalized_text(text)
    parts = (
        "bank-fact-v2",
        str(account_id),
        booking_date.isoformat(),
        value_date.isoformat() if value_date is not None else "",
        f"{amount:.2f}",
        "NOK",
        normalized_text,
        reference.strip(),
        str(occurrence),
    )
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _xml_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_children(element: ET.Element, name: str) -> tuple[ET.Element, ...]:
    return tuple(child for child in element.iter() if _xml_name(child.tag) == name)


def _xml_text(element: ET.Element, name: str, *, required: bool = True) -> str | None:
    matches = _xml_children(element, name)
    value = (matches[0].text or "").strip() if matches else ""
    if required and not value:
        raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
    return value or None


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
    def preview_file(command: BankFilePreviewCommand) -> BankFilePreview:
        if command.data_format is SupportedBankDataFormat.CSV:
            return BankingService._preview_csv(command)
        if command.data_format is SupportedBankDataFormat.CAMT053:
            return BankingService._preview_camt053(command)
        raise BankingError.invalid_input(BankingErrorCode.STATEMENT_FORMAT_UNSUPPORTED)

    @staticmethod
    def normalize_provider_transactions(
        account_id: object,
        transactions: tuple[BankProviderTransaction, ...],
    ) -> tuple[ImportedBankTransaction, ...]:
        occurrences: dict[tuple[object, ...], int] = {}
        normalized: list[ImportedBankTransaction] = []
        for transaction in transactions:
            reference = transaction.bank_reference or ""
            identity = (
                transaction.booking_date.value,
                transaction.value_date.value if transaction.value_date else None,
                _normalized_text(transaction.text),
                f"{transaction.amount.amount:.2f}",
                reference,
            )
            occurrence = occurrences.get(identity, 0)
            occurrences[identity] = occurrence + 1
            normalized.append(
                ImportedBankTransaction(
                    transaction_date=transaction.booking_date,
                    value_date=transaction.value_date,
                    text=transaction.text,
                    amount=transaction.amount,
                    balance=transaction.balance,
                    source_hash=_stable_source_hash(
                        account_id=account_id,
                        booking_date=transaction.booking_date.value,
                        value_date=(
                            transaction.value_date.value
                            if transaction.value_date is not None
                            else None
                        ),
                        text=transaction.text,
                        amount=transaction.amount.amount,
                        reference=reference,
                        occurrence=occurrence,
                    ),
                    state=transaction.state,
                    adapter_transaction_reference=transaction.adapter_transaction_reference,
                )
            )
        return tuple(normalized)

    @staticmethod
    def _preview_csv(command: BankFilePreviewCommand) -> BankFilePreview:
        mapping = command.column_mapping
        if mapping is None:
            raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
        try:
            reader = csv.DictReader(io.StringIO(command.content))
            headers = tuple(str(header).strip().lower() for header in (reader.fieldnames or ()))
            required_headers = {mapping.booking_date, mapping.text, mapping.amount}
            mapped_headers = {
                value
                for value in (
                    mapping.value_date,
                    mapping.balance,
                    mapping.reference,
                    mapping.state,
                )
                if value is not None
            } | required_headers
            if (
                not required_headers <= set(headers)
                or not mapped_headers <= set(headers)
                or len(headers) != len(set(headers))
            ):
                raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
            transactions: list[ImportedBankTransaction] = []
            ignored = 0
            correction_count = 0
            occurrences: dict[tuple[object, ...], int] = {}
            first_balance: Decimal | None = None
            last_balance: Decimal | None = None
            for raw in reader:
                normalized = {
                    str(key).strip().lower(): str(value or "").strip()
                    for key, value in raw.items()
                    if key is not None
                }
                if not any(normalized.values()):
                    ignored += 1
                    continue
                booking_date = date.fromisoformat(normalized[mapping.booking_date])
                if booking_date.year != command.income_year.value:
                    raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
                value_date = (
                    date.fromisoformat(normalized[mapping.value_date])
                    if mapping.value_date and normalized.get(mapping.value_date)
                    else None
                )
                text = normalized.get(mapping.text, "").strip()
                amount = _parse_decimal(normalized.get(mapping.amount, ""), required=True)
                balance = (
                    _parse_decimal(normalized.get(mapping.balance, ""), required=False)
                    if mapping.balance
                    else None
                )
                if not text or amount is None:
                    raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
                reference = (
                    normalized.get(mapping.reference, "") if mapping.reference else ""
                ) or hashlib.sha256(f"{booking_date}|{text}|{amount:.2f}".encode()).hexdigest()
                state_value = normalized.get(mapping.state, "booked") if mapping.state else "booked"
                state_map = {
                    "booked": BankTransactionState.BOOKED,
                    "book": BankTransactionState.BOOKED,
                    "pending": BankTransactionState.PENDING,
                    "pdng": BankTransactionState.PENDING,
                    "reversed": BankTransactionState.REVERSED,
                    "rvsl": BankTransactionState.REVERSED,
                }
                state = state_map.get(state_value.lower())
                if state is None:
                    raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
                identity = (
                    booking_date,
                    value_date,
                    _normalized_text(text),
                    f"{amount:.2f}",
                    reference,
                )
                occurrence = occurrences.get(identity, 0)
                occurrences[identity] = occurrence + 1
                transactions.append(
                    ImportedBankTransaction(
                        transaction_date=LocalDate(booking_date),
                        value_date=LocalDate(value_date) if value_date else None,
                        text=text,
                        amount=Money.nok(amount),
                        balance=Money.nok(balance) if balance is not None else None,
                        source_hash=_stable_source_hash(
                            account_id=command.account_id,
                            booking_date=booking_date,
                            value_date=value_date,
                            text=text,
                            amount=amount,
                            reference=reference,
                            occurrence=occurrence,
                        ),
                        state=state,
                        adapter_transaction_reference=reference,
                    )
                )
                if state is BankTransactionState.REVERSED:
                    correction_count += 1
                if balance is not None:
                    if first_balance is None:
                        first_balance = balance - amount
                    last_balance = balance
        except (csv.Error, UnicodeError, ValueError, KeyError):
            raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID) from None
        return BankingService._file_preview(
            command,
            transactions=tuple(transactions),
            account_mask=None,
            opening_balance=first_balance,
            closing_balance=last_balance,
            correction_count=correction_count,
            ignored_count=ignored,
        )

    @staticmethod
    def _preview_camt053(command: BankFilePreviewCommand) -> BankFilePreview:
        upper = command.content.upper()
        if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
            raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
        try:
            root = ET.fromstring(command.content)
            statements = _xml_children(root, "Stmt")
            if len(statements) != 1:
                raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
            statement = statements[0]
            account_nodes = _xml_children(statement, "Acct")
            if len(account_nodes) != 1:
                raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
            account = account_nodes[0]
            iban = _xml_text(account, "IBAN")
            currency = (_xml_text(account, "Ccy") or "").upper()
            if currency != "NOK":
                raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
            opening_balance: Decimal | None = None
            closing_balance: Decimal | None = None
            for balance_node in _xml_children(statement, "Bal"):
                code = (_xml_text(balance_node, "Cd") or "").upper()
                amount_node = _xml_children(balance_node, "Amt")
                if len(amount_node) != 1 or amount_node[0].attrib.get("Ccy", "").upper() != "NOK":
                    raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
                parsed_balance = _parse_decimal(amount_node[0].text or "", required=True)
                if code in {"OPBD", "PRCD"}:
                    opening_balance = parsed_balance
                if code in {"CLBD", "ITBD"}:
                    closing_balance = parsed_balance
            transactions: list[ImportedBankTransaction] = []
            correction_count = 0
            occurrences: dict[tuple[object, ...], int] = {}
            for entry in _xml_children(statement, "Ntry"):
                amount_nodes = tuple(
                    child for child in entry if _xml_name(child.tag) == "Amt"
                )
                if len(amount_nodes) != 1 or amount_nodes[0].attrib.get("Ccy", "").upper() != "NOK":
                    raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
                parsed_amount = _parse_decimal(amount_nodes[0].text or "", required=True)
                if parsed_amount is None:
                    raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
                direction = (_xml_text(entry, "CdtDbtInd") or "").upper()
                if direction == "DBIT":
                    parsed_amount = -abs(parsed_amount)
                elif direction == "CRDT":
                    parsed_amount = abs(parsed_amount)
                else:
                    raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
                booking_nodes = _xml_children(entry, "BookgDt")
                if len(booking_nodes) != 1:
                    raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
                booking_date = date.fromisoformat(_xml_text(booking_nodes[0], "Dt") or "")
                if booking_date.year != command.income_year.value:
                    raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
                value_nodes = _xml_children(entry, "ValDt")
                value_date = (
                    date.fromisoformat(_xml_text(value_nodes[0], "Dt") or "")
                    if value_nodes
                    else None
                )
                status_nodes = _xml_children(entry, "Sts")
                status_value = (_xml_text(status_nodes[0], "Cd") if status_nodes else "BOOK") or "BOOK"
                state_map = {
                    "BOOK": BankTransactionState.BOOKED,
                    "BOOKED": BankTransactionState.BOOKED,
                    "PDNG": BankTransactionState.PENDING,
                    "PENDING": BankTransactionState.PENDING,
                    "RVSL": BankTransactionState.REVERSED,
                    "REVERSED": BankTransactionState.REVERSED,
                }
                state = state_map.get(status_value.upper())
                if state is None:
                    raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
                references = _xml_children(entry, "AcctSvcrRef") or _xml_children(entry, "NtryRef")
                reference = required_reference = (
                    (references[0].text or "").strip() if references else ""
                )
                text_parts = tuple(
                    (node.text or "").strip()
                    for node in _xml_children(entry, "Ustrd")
                    if (node.text or "").strip()
                )
                text = " ".join(text_parts) or reference
                if not text:
                    raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
                if not reference:
                    reference = hashlib.sha256(
                        f"{booking_date}|{text}|{parsed_amount:.2f}".encode()
                    ).hexdigest()
                identity = (
                    booking_date,
                    value_date,
                    _normalized_text(text),
                    f"{parsed_amount:.2f}",
                    reference,
                )
                occurrence = occurrences.get(identity, 0)
                occurrences[identity] = occurrence + 1
                transactions.append(
                    ImportedBankTransaction(
                        transaction_date=LocalDate(booking_date),
                        value_date=LocalDate(value_date) if value_date else None,
                        text=text,
                        amount=Money.nok(parsed_amount),
                        balance=None,
                        source_hash=_stable_source_hash(
                            account_id=command.account_id,
                            booking_date=booking_date,
                            value_date=value_date,
                            text=text,
                            amount=parsed_amount,
                            reference=reference,
                            occurrence=occurrence,
                        ),
                        state=state,
                        adapter_transaction_reference=required_reference or reference,
                    )
                )
                if state is BankTransactionState.REVERSED:
                    correction_count += 1
        except (ET.ParseError, UnicodeError, ValueError, IndexError):
            raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID) from None
        return BankingService._file_preview(
            command,
            transactions=tuple(transactions),
            account_mask=f"•••• {''.join(character for character in iban if character.isalnum())[-4:]}",
            opening_balance=opening_balance,
            closing_balance=closing_balance,
            correction_count=correction_count,
            ignored_count=0,
        )

    @staticmethod
    def _file_preview(
        command: BankFilePreviewCommand,
        *,
        transactions: tuple[ImportedBankTransaction, ...],
        account_mask: str | None,
        opening_balance: Decimal | None,
        closing_balance: Decimal | None,
        correction_count: int,
        ignored_count: int,
    ) -> BankFilePreview:
        if not transactions:
            raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
        dates = tuple(item.transaction_date.value for item in transactions)
        hashes = tuple(item.source_hash for item in transactions)
        return BankFilePreview(
            account_id=command.account_id,
            filename=command.filename,
            data_format=command.data_format,
            document_sha256=hashlib.sha256(command.content.encode()).hexdigest(),
            account_mask=account_mask,
            interval_start=LocalDate(min(dates)),
            interval_end=LocalDate(max(dates)),
            currency="NOK",
            opening_balance=Money.nok(opening_balance) if opening_balance is not None else None,
            closing_balance=Money.nok(closing_balance) if closing_balance is not None else None,
            transaction_count=len(transactions),
            duplicate_count=len(hashes) - len(set(hashes)),
            correction_count=correction_count,
            ignored_count=ignored_count,
            transactions=transactions,
        )

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

    async def get_suggestion_acceptance_replay(
        self, command: AcceptBankSuggestionCommand
    ) -> AcceptedBankSuggestion | None:
        return await self._persistence.get_suggestion_acceptance_replay(command)

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
