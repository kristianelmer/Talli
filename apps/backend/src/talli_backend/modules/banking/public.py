"""Stable public contract for bank capture and reconciliation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar
from uuid import UUID

from talli_backend.shared.kernel import (
    ActorId,
    CompanyId,
    CorrelationId,
    DomainError,
    ErrorCategory,
    IdempotencyKey,
    IncomeYear,
    LocalDate,
    Money,
    Timestamp,
)


def _opaque_uuid(value: str, label: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"{label} must be a UUID") from None
    return str(parsed)


@dataclass(frozen=True, slots=True)
class BankTransactionId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_uuid(self.value, "bank transaction id"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class BankSuggestionAcceptanceId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "value",
            _opaque_uuid(self.value, "bank suggestion acceptance id"),
        )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class AccountingEntryReference:
    """Opaque correlation to an entry owned by the ledger capability."""

    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_uuid(self.value, "accounting entry reference"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ExternalActionReference:
    """Opaque correlation to a reconciliation action owned elsewhere."""

    value: str

    def __post_init__(self) -> None:
        value = self.value.strip()
        if not value or len(value) > 255:
            raise ValueError("external action reference is invalid")
        object.__setattr__(self, "value", value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class BankingCursor:
    value: str

    def __post_init__(self) -> None:
        if not self.value or len(self.value) > 4096:
            raise ValueError("banking cursor is invalid")

    def __str__(self) -> str:
        return self.value


class SupportedBankDataFormat(StrEnum):
    CSV = "CSV"


class BankSuggestionKind(StrEnum):
    BANK_FEE = "BANK_FEE"
    SYSTEM_SUBSCRIPTION = "SYSTEM_SUBSCRIPTION"
    DEPOSIT_INTEREST = "DEPOSIT_INTEREST"


CURRENT_BANK_SUGGESTION_RULE_VERSION = "2026-07-13.1"


@dataclass(frozen=True, slots=True)
class BankingCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear


@dataclass(frozen=True, slots=True)
class ImportBankStatementCommand(BankingCommand):
    data_format: SupportedBankDataFormat
    statement_text: str

    def __post_init__(self) -> None:
        if not self.statement_text or len(self.statement_text.encode("utf-8")) > 5_000_000:
            raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)


@dataclass(frozen=True, slots=True)
class AcceptBankSuggestionCommand(BankingCommand):
    acceptance_id: BankSuggestionAcceptanceId
    bank_transaction_id: BankTransactionId
    expected_suggestion: BankSuggestionKind
    expected_rule_version: str

    def __post_init__(self) -> None:
        if not self.expected_rule_version or len(self.expected_rule_version) > 80:
            raise BankingError.invalid_input(BankingErrorCode.INVALID_INPUT)


@dataclass(frozen=True, slots=True)
class ImportedBankTransaction:
    transaction_date: LocalDate
    text: str
    amount: Money
    balance: Money | None
    source_hash: str

    def __post_init__(self) -> None:
        text = self.text.strip()
        digest = self.source_hash.strip().lower()
        if (
            not text
            or len(text) > 500
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise BankingError.invalid_input(BankingErrorCode.STATEMENT_INVALID)
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "source_hash", digest)


@dataclass(frozen=True, slots=True)
class BankSuggestion:
    kind: BankSuggestionKind
    rule_version: str
    reason: str


@dataclass(frozen=True, slots=True)
class BankTransaction:
    transaction_id: BankTransactionId
    company_id: CompanyId
    income_year: IncomeYear
    transaction_date: LocalDate
    text: str
    amount: Money
    balance: Money | None
    source_hash: str
    matched_entry_id: AccountingEntryReference | None
    matched_action_reference: ExternalActionReference | None
    warning_accepted: bool
    suggestion: BankSuggestion | None
    created_at: Timestamp


@dataclass(frozen=True, slots=True)
class PreparedBankSuggestion:
    transaction: BankTransaction
    suggestion: BankSuggestion


@dataclass(frozen=True, slots=True)
class AcceptedBankSuggestion:
    acceptance_id: BankSuggestionAcceptanceId
    bank_transaction_id: BankTransactionId
    accounting_entry_id: AccountingEntryReference
    suggestion: BankSuggestion
    accepted_by: ActorId
    accepted_at: Timestamp
    replayed: bool


@dataclass(frozen=True, slots=True)
class BankStatementImportResult:
    imported_count: int
    duplicate_count: int
    transactions: tuple[BankTransaction, ...]
    replayed: bool

    def __post_init__(self) -> None:
        if self.imported_count < 0 or self.duplicate_count < 0:
            raise ValueError("bank statement counts cannot be negative")


@dataclass(frozen=True, slots=True)
class BankingPage:
    next_cursor: BankingCursor | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class BankTransactionPage:
    items: tuple[BankTransaction, ...]
    page: BankingPage


@dataclass(frozen=True, slots=True)
class BankSuggestionAcceptancePage:
    items: tuple[AcceptedBankSuggestion, ...]
    page: BankingPage


class BankingErrorCode(StrEnum):
    INVALID_INPUT = "BANKING_INVALID_INPUT"
    INVALID_CURSOR = "BANKING_INVALID_CURSOR"
    STATEMENT_INVALID = "BANKING_STATEMENT_INVALID"
    STATEMENT_FORMAT_UNSUPPORTED = "BANKING_STATEMENT_FORMAT_UNSUPPORTED"
    COMPANY_YEAR_NOT_ADMITTED = "BANKING_COMPANY_YEAR_NOT_ADMITTED"
    IDEMPOTENCY_IN_PROGRESS = "BANKING_IDEMPOTENCY_IN_PROGRESS"
    IDEMPOTENCY_KEY_REUSED = "BANKING_IDEMPOTENCY_KEY_REUSED"
    TRANSACTION_NOT_FOUND = "BANKING_TRANSACTION_NOT_FOUND"
    TRANSACTION_ALREADY_RECONCILED = "BANKING_TRANSACTION_ALREADY_RECONCILED"
    SUGGESTION_ACCEPTANCE_CONFLICT = "BANKING_SUGGESTION_ACCEPTANCE_CONFLICT"
    SUGGESTION_NOT_AVAILABLE = "BANKING_SUGGESTION_NOT_AVAILABLE"
    SUGGESTION_STALE = "BANKING_SUGGESTION_STALE"
    FORBIDDEN = "BANKING_FORBIDDEN"
    DEPENDENCY_UNAVAILABLE = "BANKING_DEPENDENCY_UNAVAILABLE"


class BankingError(DomainError):
    @staticmethod
    def _declared(code: BankingErrorCode | str) -> str:
        return BankingErrorCode(code).value

    @classmethod
    def invalid_input(cls, code: BankingErrorCode | str) -> BankingError:
        return cls(code=cls._declared(code), category=ErrorCategory.INVALID_INPUT)

    @classmethod
    def conflict(cls, code: BankingErrorCode | str) -> BankingError:
        return cls(code=cls._declared(code), category=ErrorCategory.CONFLICT)

    @classmethod
    def precondition_failed(cls, code: BankingErrorCode | str) -> BankingError:
        return cls(code=cls._declared(code), category=ErrorCategory.PRECONDITION_FAILED)

    @classmethod
    def not_found(cls) -> BankingError:
        return cls(
            code=BankingErrorCode.TRANSACTION_NOT_FOUND.value,
            category=ErrorCategory.NOT_FOUND,
        )

    @classmethod
    def forbidden(cls) -> BankingError:
        return cls(code=BankingErrorCode.FORBIDDEN.value, category=ErrorCategory.FORBIDDEN)

    @classmethod
    def unavailable(cls) -> BankingError:
        return cls(
            code=BankingErrorCode.DEPENDENCY_UNAVAILABLE.value,
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
        )


class BankingPersistence(Protocol):
    async def import_transactions(
        self,
        command: ImportBankStatementCommand,
        *,
        transactions: tuple[ImportedBankTransaction, ...],
    ) -> BankStatementImportResult: ...

    async def get_transaction_for_acceptance(
        self, command: AcceptBankSuggestionCommand
    ) -> BankTransaction: ...

    async def get_suggestion_acceptance_replay(
        self, command: AcceptBankSuggestionCommand
    ) -> AcceptedBankSuggestion | None: ...

    async def complete_suggestion_acceptance(
        self,
        command: AcceptBankSuggestionCommand,
        *,
        prepared: PreparedBankSuggestion,
        accounting_entry_id: AccountingEntryReference,
    ) -> AcceptedBankSuggestion: ...

    async def list_transactions(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: BankingCursor | None,
        limit: int,
    ) -> BankTransactionPage: ...

    async def list_suggestion_acceptances(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: BankingCursor | None,
        limit: int,
    ) -> BankSuggestionAcceptancePage: ...


BankingAdapter = TypeVar("BankingAdapter", bound=type[object])


def banking_persistence_adapter(
    contract: type[object],
) -> Callable[[BankingAdapter], BankingAdapter]:
    """Declare an infrastructure binding without registering global state."""

    def declare(adapter: BankingAdapter) -> BankingAdapter:
        _ = contract
        return adapter

    return declare


class BankingCommands(Protocol):
    async def import_statement(
        self, command: ImportBankStatementCommand
    ) -> BankStatementImportResult: ...

    async def prepare_suggestion_acceptance(
        self, command: AcceptBankSuggestionCommand
    ) -> PreparedBankSuggestion: ...

    async def get_suggestion_acceptance_replay(
        self, command: AcceptBankSuggestionCommand
    ) -> AcceptedBankSuggestion | None: ...

    async def complete_suggestion_acceptance(
        self,
        command: AcceptBankSuggestionCommand,
        *,
        prepared: PreparedBankSuggestion,
        accounting_entry_id: AccountingEntryReference,
    ) -> AcceptedBankSuggestion: ...


class BankingQueries(Protocol):
    async def list_transactions(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: BankingCursor | None,
        limit: int,
    ) -> BankTransactionPage: ...

    async def list_suggestion_acceptances(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: BankingCursor | None,
        limit: int,
    ) -> BankSuggestionAcceptancePage: ...


__all__ = [
    "AcceptBankSuggestionCommand",
    "AcceptedBankSuggestion",
    "AccountingEntryReference",
    "BankStatementImportResult",
    "BankSuggestion",
    "BankSuggestionAcceptanceId",
    "BankSuggestionAcceptancePage",
    "BankSuggestionKind",
    "BankTransaction",
    "BankTransactionId",
    "BankTransactionPage",
    "BankingCommand",
    "BankingCommands",
    "BankingCursor",
    "BankingError",
    "BankingErrorCode",
    "BankingPage",
    "BankingPersistence",
    "BankingQueries",
    "CURRENT_BANK_SUGGESTION_RULE_VERSION",
    "ExternalActionReference",
    "ImportBankStatementCommand",
    "ImportedBankTransaction",
    "PreparedBankSuggestion",
    "SupportedBankDataFormat",
    "banking_persistence_adapter",
]
