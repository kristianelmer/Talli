from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field, model_validator


CENT = Decimal("0.01")


class FifoLotError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class AcquisitionLot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    acquisition_date: date
    original_share_count: int = Field(gt=0)
    remaining_share_count: int = Field(ge=0)
    original_cost_basis: float = Field(gt=0)
    remaining_cost_basis: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_residual(self) -> "AcquisitionLot":
        if self.remaining_share_count > self.original_share_count:
            raise ValueError("remaining shares cannot exceed original shares")
        if _money(self.remaining_cost_basis) > _money(self.original_cost_basis):
            raise ValueError("remaining cost cannot exceed original cost")
        if self.remaining_share_count == 0 and _money(self.remaining_cost_basis) != 0:
            raise ValueError("an empty lot cannot retain cost basis")
        _money(self.original_cost_basis)
        return self


class LotAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lot_id: str
    acquisition_date: date
    share_count: int = Field(gt=0)
    cost_basis: float = Field(ge=0)


class FifoShareSaleAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allocations: tuple[LotAllocation, ...]
    updated_lots: tuple[AcquisitionLot, ...]
    cost_basis_reduction: float = Field(ge=0)
    remaining_share_count: int = Field(ge=0)
    remaining_cost_basis: float = Field(ge=0)


def allocate_fifo_share_sale(
    *,
    lots: tuple[AcquisitionLot, ...],
    sale_date: date,
    sold_share_count: int,
) -> FifoShareSaleAllocation:
    if not isinstance(sold_share_count, int) or isinstance(sold_share_count, bool) or sold_share_count <= 0:
        raise FifoLotError("invalid_sold_share_count", "sold share count must be a positive integer")
    if not lots:
        raise FifoLotError("missing_acquisition_lots", "the position has no acquisition lots")
    if len({lot.id for lot in lots}) != len(lots):
        raise FifoLotError("invalid_lot_id", "acquisition lot ids must be unique")
    if any(lot.acquisition_date > sale_date for lot in lots):
        raise FifoLotError("future_acquisition_lot", "an acquisition lot is dated after the sale")

    ordered_lots = tuple(sorted(lots, key=lambda lot: (lot.acquisition_date, lot.id)))
    available_shares = sum(lot.remaining_share_count for lot in ordered_lots)
    if sold_share_count > available_shares:
        raise FifoLotError("sale_exceeds_lots", "sale exceeds the shares remaining in acquisition lots")

    shares_to_allocate = sold_share_count
    allocated_cost = Decimal(0)
    allocations: list[LotAllocation] = []
    updated_lots: list[AcquisitionLot] = []
    for lot in ordered_lots:
        if shares_to_allocate == 0 or lot.remaining_share_count == 0:
            updated_lots.append(lot)
            continue
        allocated_shares = min(shares_to_allocate, lot.remaining_share_count)
        remaining_cost = _money(lot.remaining_cost_basis)
        if allocated_shares == lot.remaining_share_count:
            lot_cost = remaining_cost
        else:
            lot_cost = (
                remaining_cost * Decimal(allocated_shares) / Decimal(lot.remaining_share_count)
            ).quantize(CENT, rounding=ROUND_HALF_UP)
        allocated_cost += lot_cost
        shares_to_allocate -= allocated_shares
        allocations.append(
            LotAllocation(
                lot_id=lot.id,
                acquisition_date=lot.acquisition_date,
                share_count=allocated_shares,
                cost_basis=float(lot_cost),
            )
        )
        updated_lots.append(
            lot.model_copy(
                update={
                    "remaining_share_count": lot.remaining_share_count - allocated_shares,
                    "remaining_cost_basis": float(remaining_cost - lot_cost),
                }
            )
        )

    remaining_cost = sum((_money(lot.remaining_cost_basis) for lot in updated_lots), Decimal(0))
    return FifoShareSaleAllocation(
        allocations=tuple(allocations),
        updated_lots=tuple(updated_lots),
        cost_basis_reduction=float(allocated_cost),
        remaining_share_count=sum(lot.remaining_share_count for lot in updated_lots),
        remaining_cost_basis=float(remaining_cost),
    )


def _money(value: float) -> Decimal:
    amount = Decimal(str(value))
    rounded = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    if amount != rounded:
        raise ValueError("money values can have at most two decimals")
    return rounded
