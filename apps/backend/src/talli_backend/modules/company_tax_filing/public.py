"""Public Company Tax settlement facts and normalization contract."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Callable, Mapping
from typing import Protocol, TypeVar

from talli_backend.shared.kernel import (
    ActorId, CompanyId, CorrelationId, DomainError, ErrorCategory,
    IdempotencyKey, IncomeYear, LocalDate, Money,
)


class TaxSettlementKind(StrEnum):
    PAYABLE = "payable"
    PAYMENT = "payment"
    REFUND = "refund"


class TaxSettlementDocumentStatus(StrEnum):
    ATTACHED = "attached"
    MISSING_ACCEPTED_WARNING = "missing_accepted_warning"
    NOT_REQUIRED = "not_required"


class TaxSettlementValidationError(DomainError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(code=code, category=ErrorCategory.INVALID_INPUT, message=message)


@dataclass(frozen=True, slots=True)
class TaxSettlementInput:
    settlement_date: str
    amount: float
    settlement_kind: str
    document_status: str
    bank_transaction_id: str | None = None
    document_id: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedTaxSettlement:
    """Preview normalization; capture separately enforces date/year and Money."""
    settlement_date: str
    amount: float
    settlement_kind: TaxSettlementKind
    document_status: TaxSettlementDocumentStatus
    bank_transaction_id: str | None
    document_id: str | None
    expected_bank_amount: float | None


def normalize_tax_settlement(value: TaxSettlementInput) -> NormalizedTaxSettlement:
    from .service import normalize

    return normalize(value)




@dataclass(frozen=True, slots=True)
class _UuidReference:
    value: str

    def __post_init__(self) -> None:
        from uuid import UUID
        object.__setattr__(self, "value", str(UUID(self.value)))

    def __str__(self) -> str:
        return self.value


class TaxSettlementId(_UuidReference):
    pass


class BankTransactionReference(_UuidReference):
    pass


class DocumentReference(_UuidReference):
    pass


class AccountingEntryReference(_UuidReference):
    pass


class CompanyTaxError(DomainError):
    @classmethod
    def invalid_input(cls) -> CompanyTaxError:
        return cls(code="COMPANY_TAX_INVALID_INPUT", category=ErrorCategory.INVALID_INPUT)

    @classmethod
    def forbidden(cls) -> CompanyTaxError:
        return cls(code="COMPANY_TAX_FORBIDDEN", category=ErrorCategory.FORBIDDEN)

    @classmethod
    def unavailable(cls) -> CompanyTaxError:
        return cls(code="COMPANY_TAX_DEPENDENCY_UNAVAILABLE", category=ErrorCategory.DEPENDENCY_UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class RecordTaxSettlementCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    action_id: TaxSettlementId
    settlement_date: LocalDate
    amount: Money
    settlement_kind: TaxSettlementKind
    document_status: TaxSettlementDocumentStatus
    bank_transaction_id: BankTransactionReference | None
    document_id: DocumentReference | None


class TaxSettlementPersistence(Protocol):
    async def prepare_settlement(
        self, command: RecordTaxSettlementCommand
    ) -> Mapping[str, object] | None:
        """Authorize, claim original technical receipt and lock year; return replay."""
        ...

    async def complete_settlement(
        self, command: RecordTaxSettlementCommand, accounting_entry_id: AccountingEntryReference
    ) -> Mapping[str, object]: ...


SettlementAdapter = TypeVar("SettlementAdapter", bound=type[object])


def tax_settlement_persistence_adapter(
    contract: type[object],
) -> Callable[[SettlementAdapter], SettlementAdapter]:
    def declare(adapter: SettlementAdapter) -> SettlementAdapter:
        _ = contract
        return adapter
    return declare


def validate_new_tax_settlement(command: RecordTaxSettlementCommand) -> None:
    """Validate a fresh capture only after historical receipt/action replay."""
    from .service import validate_new
    validate_new(command)


__all__ = [
    "NormalizedTaxSettlement",
    "TaxSettlementDocumentStatus",
    "TaxSettlementInput",
    "TaxSettlementKind",
    "TaxSettlementValidationError",
    "normalize_tax_settlement",
    "CompanyTaxError",
    "RecordTaxSettlementCommand",
    "TaxSettlementId",
    "TaxSettlementPersistence",
    "tax_settlement_persistence_adapter",
    "validate_new_tax_settlement",
    "AccountingEntryReference",
    "BankTransactionReference",
    "DocumentReference"
]
