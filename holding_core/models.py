from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]


class ShareholderKind(StrEnum):
    NORWEGIAN_PERSON = "norwegian_person"
    NORWEGIAN_COMPANY = "norwegian_company"


class Company(BaseModel):
    model_config = ConfigDict(extra="forbid")

    org_number: str = Field(pattern=r"^\d{9}$")
    name: str
    address: str
    postal_code: str = Field(pattern=r"^\d{4}$")
    city: str
    income_year: int = Field(ge=2000, le=2100)
    share_type: str = "01"
    contact_email: str | None = None


class ShareSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_share_capital: NonNegativeFloat
    current_share_capital: NonNegativeFloat
    previous_nominal_value: NonNegativeFloat
    current_nominal_value: NonNegativeFloat
    previous_share_count: NonNegativeInt
    current_share_count: NonNegativeInt
    previous_paid_in_share_capital: NonNegativeFloat
    current_paid_in_share_capital: NonNegativeFloat
    previous_paid_in_premium: NonNegativeFloat = 0
    current_paid_in_premium: NonNegativeFloat = 0


class Shareholder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: ShareholderKind
    name: str
    national_id: str | None = Field(default=None, pattern=r"^\d{11}$")
    org_number: str | None = Field(default=None, pattern=r"^\d{9}$")

    @model_validator(mode="after")
    def validate_identifier(self) -> "Shareholder":
        if self.kind == ShareholderKind.NORWEGIAN_PERSON and not self.national_id:
            raise ValueError("Norwegian personal shareholder requires national_id")
        if self.kind == ShareholderKind.NORWEGIAN_COMPANY and not self.org_number:
            raise ValueError("Norwegian corporate shareholder requires org_number")
        return self


class ShareholderSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shareholder_id: str
    previous_share_count: NonNegativeInt
    current_share_count: NonNegativeInt


class FormationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["formation"] = "formation"
    timestamp: datetime
    issued_share_count: NonNegativeInt
    share_count_after: NonNegativeInt
    nominal_value: NonNegativeFloat
    premium: NonNegativeFloat = 0
    allocations: list["FormationAllocation"]


class FormationAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shareholder_id: str
    share_count: NonNegativeInt
    acquisition_value: NonNegativeFloat


class ShareSaleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["share_sale"] = "share_sale"
    timestamp: datetime
    seller_shareholder_id: str
    buyer_shareholder_id: str
    share_count: NonNegativeInt
    consideration: NonNegativeFloat


class DividendAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shareholder_id: str
    amount: NonNegativeFloat
    share_count_basis: NonNegativeInt


class DividendEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["dividend"] = "dividend"
    timestamp: datetime
    total_amount: NonNegativeFloat
    per_share_amount: NonNegativeFloat
    allocations: list[DividendAllocation]


class FilingCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    company: Company
    share_snapshot: ShareSnapshot
    shareholders: list[Shareholder]
    shareholder_snapshots: list[ShareholderSnapshot]
    events: list[FormationEvent | ShareSaleEvent | DividendEvent] = []

    @classmethod
    def from_json_file(cls, path: str | Path) -> "FilingCase":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    @model_validator(mode="after")
    def validate_case(self) -> "FilingCase":
        shareholder_ids = {shareholder.id for shareholder in self.shareholders}
        snapshot_ids = {snapshot.shareholder_id for snapshot in self.shareholder_snapshots}
        if shareholder_ids != snapshot_ids:
            raise ValueError("shareholders and shareholder_snapshots must contain the same shareholder ids")

        previous_total = sum(snapshot.previous_share_count for snapshot in self.shareholder_snapshots)
        current_total = sum(snapshot.current_share_count for snapshot in self.shareholder_snapshots)
        if previous_total != self.share_snapshot.previous_share_count:
            raise ValueError("sum of previous shareholder shares must equal company previous share count")
        if current_total != self.share_snapshot.current_share_count:
            raise ValueError("sum of current shareholder shares must equal company current share count")

        for event in self.events:
            if isinstance(event, FormationEvent):
                allocated_shares = sum(allocation.share_count for allocation in event.allocations)
                if allocated_shares != event.issued_share_count:
                    raise ValueError("formation allocations must equal issued share count")
                for allocation in event.allocations:
                    if allocation.shareholder_id not in shareholder_ids:
                        raise ValueError("formation allocation shareholder must exist")
            if isinstance(event, ShareSaleEvent):
                if event.seller_shareholder_id not in shareholder_ids:
                    raise ValueError("share sale seller must be an existing shareholder")
                if event.buyer_shareholder_id not in shareholder_ids:
                    raise ValueError("share sale buyer must be an existing shareholder")
            if isinstance(event, DividendEvent):
                allocation_total = sum(allocation.amount for allocation in event.allocations)
                if round(allocation_total, 2) != round(event.total_amount, 2):
                    raise ValueError("dividend allocations must equal total dividend")
                for allocation in event.allocations:
                    if allocation.shareholder_id not in shareholder_ids:
                        raise ValueError("dividend allocation shareholder must exist")
        return self
