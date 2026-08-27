"""The deliberately small set of values shared by backend capabilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import StrEnum
from typing import Protocol
from uuid import UUID


def _canonical_uuid(value: str, label: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"{label} must be a UUID") from None
    return str(parsed)


@dataclass(frozen=True, slots=True)
class CompanyId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _canonical_uuid(self.value, "company id"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class UserId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _canonical_uuid(self.value, "user id"))

    def __str__(self) -> str:
        return self.value


class ActorKind(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    SUPPORT_OPERATOR = "SUPPORT_OPERATOR"


@dataclass(frozen=True, slots=True)
class ActorId:
    kind: ActorKind
    subject: UserId


_CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


@dataclass(frozen=True, slots=True)
class CorrelationId:
    value: str

    def __post_init__(self) -> None:
        if not _CORRELATION_PATTERN.fullmatch(self.value):
            raise ValueError("correlation id is invalid")

    def __str__(self) -> str:
        return self.value


_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,255}$")


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    value: str

    def __post_init__(self) -> None:
        if not _IDEMPOTENCY_PATTERN.fullmatch(self.value):
            raise ValueError("idempotency key must be an opaque high-entropy token")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class IncomeYear:
    value: int

    def __post_init__(self) -> None:
        if not 2000 <= self.value <= 2100:
            raise ValueError("income year is outside the supported storage range")

    def __int__(self) -> int:
        return self.value


class Currency(StrEnum):
    NOK = "NOK"


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: Currency = Currency.NOK

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("money amount must be Decimal")
        if not self.amount.is_finite():
            raise ValueError("money amount must be finite")
        try:
            normalized = self.amount.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        except InvalidOperation:
            raise ValueError("money amount exceeds the supported precision") from None
        object.__setattr__(self, "amount", normalized)

    @classmethod
    def nok(cls, amount: str | Decimal) -> Money:
        try:
            decimal_amount = amount if isinstance(amount, Decimal) else Decimal(amount)
        except (InvalidOperation, ValueError):
            raise ValueError("money amount must be a decimal string") from None
        return cls(decimal_amount, Currency.NOK)


@dataclass(frozen=True, slots=True)
class LocalDate:
    value: date


@dataclass(frozen=True, slots=True)
class Timestamp:
    value: datetime

    def __post_init__(self) -> None:
        if self.value.tzinfo is None or self.value.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        object.__setattr__(self, "value", self.value.astimezone(UTC))


class RiskResponse(StrEnum):
    HARD_BLOCK = "HARD_BLOCK"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"
    EXPLICIT_WARNING = "EXPLICIT_WARNING"


class ErrorCategory(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    FORBIDDEN = "FORBIDDEN"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ErrorContext:
    key: str
    value: str


class DomainError(Exception):
    """Expected, sanitized capability failure; transports map its category."""

    def __init__(
        self,
        *,
        code: str,
        category: ErrorCategory,
        message: str = "",
        context: tuple[ErrorContext, ...] = (),
    ) -> None:
        self.code = code
        self.category = category
        self.message = message
        self.context = context
        super().__init__(message or code)


class Clock(Protocol):
    def now(self) -> Timestamp: ...


class IdGenerator(Protocol):
    def new_uuid(self) -> str: ...


__all__ = [
    "ActorId",
    "ActorKind",
    "Clock",
    "CompanyId",
    "CorrelationId",
    "Currency",
    "DomainError",
    "ErrorCategory",
    "ErrorContext",
    "IdGenerator",
    "IdempotencyKey",
    "IncomeYear",
    "LocalDate",
    "Money",
    "RiskResponse",
    "Timestamp",
    "UserId",
]
