"""Stable opening-snapshot contract for the future shareholder-register stage."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Literal, Protocol
from uuid import UUID

from talli_backend.shared.kernel import (
    ActorId,
    CompanyId,
    CorrelationId,
    DomainError,
    ErrorCategory,
    IdempotencyKey,
    IncomeYear,
    Money,
)


class ShareholderRegisterFilingErrorCode(StrEnum):
    INVALID_INPUT = "SHAREHOLDER_REGISTER_FILING_INVALID_INPUT"
    NOT_FOUND = "SHAREHOLDER_REGISTER_FILING_NOT_FOUND"
    FORBIDDEN = "SHAREHOLDER_REGISTER_FILING_FORBIDDEN"
    COMPANY_YEAR_NOT_ADMITTED = (
        "SHAREHOLDER_REGISTER_FILING_COMPANY_YEAR_NOT_ADMITTED"
    )
    OPENING_ALREADY_EXISTS = (
        "SHAREHOLDER_REGISTER_FILING_OPENING_ALREADY_EXISTS"
    )
    DEPENDENCY_UNAVAILABLE = (
        "SHAREHOLDER_REGISTER_FILING_DEPENDENCY_UNAVAILABLE"
    )


class ShareholderRegisterFilingError(DomainError):
    @classmethod
    def invalid_input(cls) -> ShareholderRegisterFilingError:
        return cls(
            code=ShareholderRegisterFilingErrorCode.INVALID_INPUT,
            category=ErrorCategory.INVALID_INPUT,
        )

    @classmethod
    def not_found(cls) -> ShareholderRegisterFilingError:
        return cls(
            code=ShareholderRegisterFilingErrorCode.NOT_FOUND,
            category=ErrorCategory.NOT_FOUND,
        )

    @classmethod
    def forbidden(cls) -> ShareholderRegisterFilingError:
        return cls(
            code=ShareholderRegisterFilingErrorCode.FORBIDDEN,
            category=ErrorCategory.FORBIDDEN,
        )

    @classmethod
    def company_year_not_admitted(cls) -> ShareholderRegisterFilingError:
        return cls(
            code=ShareholderRegisterFilingErrorCode.COMPANY_YEAR_NOT_ADMITTED,
            category=ErrorCategory.PRECONDITION_FAILED,
        )

    @classmethod
    def opening_already_exists(cls) -> ShareholderRegisterFilingError:
        return cls(
            code=ShareholderRegisterFilingErrorCode.OPENING_ALREADY_EXISTS,
            category=ErrorCategory.CONFLICT,
        )

    @classmethod
    def unavailable(cls) -> ShareholderRegisterFilingError:
        return cls(
            code=ShareholderRegisterFilingErrorCode.DEPENDENCY_UNAVAILABLE,
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
        )


@dataclass(frozen=True, slots=True)
class OpeningSnapshotId:
    value: str

    def __post_init__(self) -> None:
        try:
            parsed = UUID(self.value)
        except (ValueError, AttributeError, TypeError):
            raise ValueError("opening snapshot id must be a UUID") from None
        object.__setattr__(self, "value", str(parsed))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OpeningShareholder:
    name: str
    shareholder_kind: Literal["norwegian_person", "norwegian_company"]
    national_id: str | None
    org_number: str | None
    share_count: int

    def __post_init__(self) -> None:
        name = self.name.strip()
        valid_identifier = (
            self.shareholder_kind == "norwegian_person"
            and re.fullmatch(r"\d{11}", self.national_id or "") is not None
        ) or (
            self.shareholder_kind == "norwegian_company"
            and re.fullmatch(r"\d{9}", self.org_number or "") is not None
        )
        if not name or len(name) > 255 or self.share_count < 0 or not valid_identifier:
            raise ShareholderRegisterFilingError.invalid_input()
        object.__setattr__(self, "name", name)


@dataclass(frozen=True, slots=True)
class RecordOpeningSnapshotCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    share_capital: Money
    share_count: int
    nominal_value: Money
    shareholders: tuple[OpeningShareholder, ...]

    def __post_init__(self) -> None:
        if (
            self.share_capital.amount < 0
            or self.share_count <= 0
            or self.nominal_value.amount <= 0
            or not 1 <= len(self.shareholders) <= 100
            or self.share_capital.amount
            != self.nominal_value.amount * self.share_count
            or sum(shareholder.share_count for shareholder in self.shareholders)
            != self.share_count
        ):
            raise ShareholderRegisterFilingError.invalid_input()


class ShareholderRegisterFilingCommands(Protocol):
    async def record_opening_snapshot(
        self, command: RecordOpeningSnapshotCommand
    ) -> OpeningSnapshotId: ...


__all__ = [
    "OpeningShareholder",
    "OpeningSnapshotId",
    "RecordOpeningSnapshotCommand",
    "ShareholderRegisterFilingCommands",
    "ShareholderRegisterFilingError",
    "ShareholderRegisterFilingErrorCode",
]
