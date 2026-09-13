"""Public Company Tax settlement facts and normalization contract."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from talli_backend.shared.kernel import DomainError, ErrorCategory


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


__all__ = [
    "NormalizedTaxSettlement", "TaxSettlementDocumentStatus", "TaxSettlementInput",
    "TaxSettlementKind", "TaxSettlementValidationError", "normalize_tax_settlement",
]
