"""Shared untrusted-response normalization for read-only banking adapters."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol

from talli_backend.modules.banking.public import (
    BankTransactionState,
    BankingError,
    BankingErrorCode,
)
from talli_backend.shared.kernel import ErrorCategory, LocalDate, Money


class BankProviderHttpTransport(Protocol):
    async def request(self, **request: object) -> dict[str, object]: ...


def provider_error(code: BankingErrorCode = BankingErrorCode.PROVIDER_UNAVAILABLE) -> BankingError:
    category = (
        ErrorCategory.DEPENDENCY_UNAVAILABLE
        if code is BankingErrorCode.PROVIDER_UNAVAILABLE
        else ErrorCategory.INVALID_INPUT
    )
    return BankingError(code=code.value, category=category)


def response_parts(response: object) -> tuple[int, Mapping[str, object]]:
    if not isinstance(response, Mapping):
        raise provider_error(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
    status = response.get("status")
    body = response.get("body")
    if not isinstance(status, int) or not isinstance(body, Mapping):
        raise provider_error(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
    return status, body


def successful_body(response: object) -> Mapping[str, object]:
    status, body = response_parts(response)
    if status < 200 or status >= 300:
        raise provider_error()
    return body


def required_text(value: object, *, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise provider_error(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise provider_error(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
    return normalized


def optional_date(value: object) -> LocalDate | None:
    if value in (None, ""):
        return None
    try:
        return LocalDate(date.fromisoformat(required_text(value, maximum=32)[:10]))
    except ValueError:
        raise provider_error(BankingErrorCode.PROVIDER_RESPONSE_INVALID) from None


def money(value: object, *, currency: object = "NOK") -> Money:
    if required_text(currency, maximum=3).upper() != "NOK":
        raise provider_error(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
    try:
        amount = Decimal(required_text(value, maximum=80))
    except InvalidOperation:
        raise provider_error(BankingErrorCode.PROVIDER_RESPONSE_INVALID) from None
    if not amount.is_finite():
        raise provider_error(BankingErrorCode.PROVIDER_RESPONSE_INVALID)
    return Money.nok(amount)


def masked_account(value: object) -> str:
    normalized = required_text(value, maximum=256)
    suffix = re.sub(r"\W", "", normalized)[-4:]
    if len(suffix) != 4:
        suffix = hashlib.sha256(normalized.encode()).hexdigest()[-4:]
    return f"•••• {suffix}"


def transaction_state(value: object) -> BankTransactionState:
    normalized = required_text(value, maximum=40).upper()
    mapping = {
        "BOOKED": BankTransactionState.BOOKED,
        "PENDING": BankTransactionState.PENDING,
        "REVERSED": BankTransactionState.REVERSED,
        "REJECTED": BankTransactionState.REVERSED,
    }
    try:
        return mapping[normalized]
    except KeyError:
        raise provider_error(BankingErrorCode.PROVIDER_RESPONSE_INVALID) from None


__all__ = [
    "BankProviderHttpTransport",
    "masked_account",
    "money",
    "optional_date",
    "provider_error",
    "required_text",
    "response_parts",
    "successful_body",
    "transaction_state",
]
