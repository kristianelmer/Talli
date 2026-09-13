"""Validated application projection of RF opening shares and Ledger bank input.

The two capability owners publish their facts independently. The backend joins
those contracts for the existing new-year read without exposing private tables.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal
from uuid import UUID

from talli_backend.shared.kernel import (
    ActorId,
    CompanyId,
    IncomeYear,
    Money,
    Timestamp,
)


def _uuid(value: str, label: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise ValueError(f"{label} must be a UUID") from None


@dataclass(frozen=True, slots=True)
class OpeningSnapshotCursor:
    value: str

    def __post_init__(self) -> None:
        if not self.value or len(self.value) > 4096:
            raise ValueError("opening snapshot cursor is invalid")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OpeningShareholderView:
    shareholder_id: str
    setup_id: str
    company_id: CompanyId
    name: str
    shareholder_kind: Literal["norwegian_person", "norwegian_company"]
    national_id: str | None
    org_number: str | None
    share_count: int

    def __post_init__(self) -> None:
        shareholder_id = _uuid(self.shareholder_id, "opening shareholder id")
        setup_id = _uuid(self.setup_id, "opening setup id")
        name = self.name.strip()
        valid_primary_identifier = (
            self.shareholder_kind == "norwegian_person"
            and re.fullmatch(r"\d{11}", self.national_id or "") is not None
        ) or (
            self.shareholder_kind == "norwegian_company"
            and re.fullmatch(r"\d{9}", self.org_number or "") is not None
        )
        optional_identifiers_valid = (
            self.national_id is None
            or re.fullmatch(r"\d{11}", self.national_id) is not None
        ) and (
            self.org_number is None
            or re.fullmatch(r"\d{9}", self.org_number) is not None
        )
        if (
            not name
            or len(name) > 255
            or not 0 <= self.share_count <= 2_147_483_647
            or not valid_primary_identifier
            or not optional_identifiers_valid
        ):
            raise ValueError("opening shareholder facts are invalid")
        object.__setattr__(self, "shareholder_id", shareholder_id)
        object.__setattr__(self, "setup_id", setup_id)
        object.__setattr__(self, "name", name)


@dataclass(frozen=True, slots=True)
class OpeningSnapshotView:
    setup_id: str
    company_id: CompanyId
    income_year: IncomeYear
    bank_balance: Money
    share_capital: Money
    share_count: int
    nominal_value: Money
    locked_at: Timestamp
    created_at: Timestamp
    created_by: ActorId
    shareholders: tuple[OpeningShareholderView, ...]

    def __post_init__(self) -> None:
        setup_id = _uuid(self.setup_id, "opening setup id")
        if (
            self.bank_balance.amount < 0
            or self.share_capital.amount < 0
            or not 0 < self.share_count <= 2_147_483_647
            or self.nominal_value.amount <= 0
            or self.share_capital.amount
            != self.nominal_value.amount * self.share_count
            or not 1 <= len(self.shareholders) <= 100
            or sum(item.share_count for item in self.shareholders) != self.share_count
            or len({item.shareholder_id for item in self.shareholders})
            != len(self.shareholders)
            or any(item.setup_id != setup_id for item in self.shareholders)
            or any(item.company_id != self.company_id for item in self.shareholders)
        ):
            raise ValueError("opening snapshot facts are invalid")
        object.__setattr__(self, "setup_id", setup_id)


@dataclass(frozen=True, slots=True)
class OpeningSnapshotPage:
    items: tuple[OpeningSnapshotView, ...]
    next_cursor: OpeningSnapshotCursor | None
    has_more: bool

    def __post_init__(self) -> None:
        setup_ids = {item.setup_id for item in self.items}
        shareholder_ids = {
            shareholder.shareholder_id
            for item in self.items
            for shareholder in item.shareholders
        }
        shareholder_count = sum(len(item.shareholders) for item in self.items)
        if (
            len(self.items) > 100
            or len(setup_ids) != len(self.items)
            or len(shareholder_ids) != shareholder_count
            or self.has_more != (self.next_cursor is not None)
        ):
            raise ValueError("opening snapshot page is invalid")


__all__ = [
    "OpeningShareholderView",
    "OpeningSnapshotCursor",
    "OpeningSnapshotPage",
    "OpeningSnapshotView",
]
