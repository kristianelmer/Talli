"""Stable public contract for bank capture and reconciliation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Mapping, Protocol, TypeVar
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
class BankConnectionId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_uuid(self.value, "bank connection id"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class BankConnectorId:
    value: str

    def __post_init__(self) -> None:
        value = self.value.strip().lower()
        if not value or len(value) > 80 or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", value):
            raise ValueError("bank connector id is invalid")
        object.__setattr__(self, "value", value)

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
    CAMT053 = "CAMT053"


class BankSyncMode(StrEnum):
    INITIAL_BACKFILL = "INITIAL_BACKFILL"
    NIGHTLY = "NIGHTLY"
    ON_DEMAND = "ON_DEMAND"
    ANNUAL_CLOSE = "ANNUAL_CLOSE"
    RECOVERY = "RECOVERY"


class BankTransactionState(StrEnum):
    PENDING = "PENDING"
    BOOKED = "BOOKED"
    REVERSED = "REVERSED"


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
class BeginBankConsentRequest:
    connection_id: BankConnectionId
    company_id: CompanyId
    connector_id: BankConnectorId
    bank_key: str
    return_url: str

    def __post_init__(self) -> None:
        bank_key = self.bank_key.strip()
        if not bank_key or len(bank_key) > 120:
            raise BankingError.invalid_input(BankingErrorCode.INVALID_INPUT)
        if not self.return_url.startswith("https://") or len(self.return_url) > 2048:
            raise BankingError.invalid_input(BankingErrorCode.INVALID_INPUT)
        object.__setattr__(self, "bank_key", bank_key)


@dataclass(frozen=True, slots=True)
class CompleteBankConsentRequest:
    connection_id: BankConnectionId
    company_id: CompanyId
    callback_parameters: Mapping[str, str]

    def __post_init__(self) -> None:
        normalized = {
            str(key).strip(): str(value).strip()
            for key, value in self.callback_parameters.items()
        }
        if (
            not normalized
            or len(normalized) > 12
            or any(not key or not value or len(key) > 80 or len(value) > 4096 for key, value in normalized.items())
        ):
            raise BankingError.invalid_input(BankingErrorCode.CONSENT_CALLBACK_INVALID)
        object.__setattr__(self, "callback_parameters", normalized)


@dataclass(frozen=True, slots=True)
class FetchBankTransactionsRequest:
    connection_id: BankConnectionId
    company_id: CompanyId
    adapter_account_reference: str
    date_from: LocalDate
    date_to: LocalDate
    cursor: str | None
    mode: BankSyncMode
    owner_present: bool

    def __post_init__(self) -> None:
        reference = self.adapter_account_reference.strip()
        cursor = self.cursor.strip() if self.cursor is not None else None
        if (
            not reference
            or len(reference) > 1024
            or self.date_to.value < self.date_from.value
            or (cursor is not None and (not cursor or len(cursor) > 4096))
        ):
            raise BankingError.invalid_input(BankingErrorCode.INVALID_INPUT)
        object.__setattr__(self, "adapter_account_reference", reference)
        object.__setattr__(self, "cursor", cursor)


@dataclass(frozen=True, slots=True)
class RevokeBankConsentRequest:
    connection_id: BankConnectionId
    company_id: CompanyId


@dataclass(frozen=True, slots=True)
class BankConsentRedirect:
    redirect_url: str
    state: str

    def __post_init__(self) -> None:
        if not self.redirect_url.startswith("https://") or not self.state:
            raise BankingError.unavailable()


@dataclass(frozen=True, slots=True)
class BankProviderAccount:
    adapter_account_reference: str
    masked_account: str
    currency: str
    account_kind: str
    display_name: str

    def __post_init__(self) -> None:
        reference = self.adapter_account_reference.strip()
        masked = self.masked_account.strip()
        currency = self.currency.strip().upper()
        if (
            not reference
            or len(reference) > 1024
            or not masked
            or len(masked) > 80
            or currency != "NOK"
            or not self.account_kind.strip()
        ):
            raise BankingError.invalid_input(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
        object.__setattr__(self, "adapter_account_reference", reference)
        object.__setattr__(self, "masked_account", masked)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "account_kind", self.account_kind.strip())
        object.__setattr__(self, "display_name", self.display_name.strip()[:120])


@dataclass(frozen=True, slots=True)
class BankProviderConnection:
    connection_id: BankConnectionId
    connector_id: BankConnectorId
    consent_expires_on: LocalDate | None
    accounts: tuple[BankProviderAccount, ...]

    def __post_init__(self) -> None:
        if not self.accounts:
            raise BankingError.precondition_failed(BankingErrorCode.NO_SUPPORTED_ACCOUNTS)


@dataclass(frozen=True, slots=True)
class BankProviderTransaction:
    adapter_transaction_reference: str
    booking_date: LocalDate
    value_date: LocalDate | None
    text: str
    amount: Money
    balance: Money | None
    state: BankTransactionState

    def __post_init__(self) -> None:
        reference = self.adapter_transaction_reference.strip()
        text = self.text.strip()
        if not reference or len(reference) > 1024 or not text or len(text) > 500:
            raise BankingError.invalid_input(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
        object.__setattr__(self, "adapter_transaction_reference", reference)
        object.__setattr__(self, "text", text)


@dataclass(frozen=True, slots=True)
class BankProviderTransactionPage:
    transactions: tuple[BankProviderTransaction, ...]
    next_cursor: str | None

    def __post_init__(self) -> None:
        cursor = self.next_cursor.strip() if self.next_cursor is not None else None
        if cursor is not None and (not cursor or len(cursor) > 4096):
            raise BankingError.invalid_input(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
        object.__setattr__(self, "next_cursor", cursor)


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
    PROVIDER_UNAVAILABLE = "BANKING_PROVIDER_UNAVAILABLE"
    PROVIDER_RESPONSE_INVALID = "BANKING_PROVIDER_RESPONSE_INVALID"
    CONSENT_CALLBACK_INVALID = "BANKING_CONSENT_CALLBACK_INVALID"
    CONSENT_EXPIRED = "BANKING_CONSENT_EXPIRED"
    NO_SUPPORTED_ACCOUNTS = "BANKING_NO_SUPPORTED_ACCOUNTS"


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


class BankDataProvider(Protocol):
    async def begin_consent(
        self, request: BeginBankConsentRequest
    ) -> BankConsentRedirect: ...

    async def complete_consent(
        self, request: CompleteBankConsentRequest
    ) -> BankProviderConnection: ...

    async def fetch_transactions(
        self, request: FetchBankTransactionsRequest
    ) -> BankProviderTransactionPage: ...

    async def revoke_consent(self, request: RevokeBankConsentRequest) -> None: ...


BankingAdapter = TypeVar("BankingAdapter", bound=type[object])


def banking_persistence_adapter(
    contract: type[object],
) -> Callable[[BankingAdapter], BankingAdapter]:
    """Declare an infrastructure binding without registering global state."""

    def declare(adapter: BankingAdapter) -> BankingAdapter:
        _ = contract
        return adapter

    return declare


def bank_data_provider_adapter(
    contract: type[object],
) -> Callable[[BankingAdapter], BankingAdapter]:
    """Declare a read-only provider binding without registering global state."""

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
    "BankConnectionId",
    "BankConnectorId",
    "BankConsentRedirect",
    "BankDataProvider",
    "BankProviderAccount",
    "BankProviderConnection",
    "BankProviderTransaction",
    "BankProviderTransactionPage",
    "BankSyncMode",
    "BankSuggestion",
    "BankSuggestionAcceptanceId",
    "BankSuggestionAcceptancePage",
    "BankSuggestionKind",
    "BankTransaction",
    "BankTransactionId",
    "BankTransactionPage",
    "BankTransactionState",
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
    "BeginBankConsentRequest",
    "CompleteBankConsentRequest",
    "FetchBankTransactionsRequest",
    "ImportBankStatementCommand",
    "ImportedBankTransaction",
    "PreparedBankSuggestion",
    "RevokeBankConsentRequest",
    "SupportedBankDataFormat",
    "banking_persistence_adapter",
    "bank_data_provider_adapter",
]
