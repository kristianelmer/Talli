"""Stable public contract for investment positions and acquisition lots."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Callable, Mapping
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
class InvestmentActionId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_uuid(self.value, "investment action id"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class InvestmentSourceReference:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_uuid(self.value, "investment source reference"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class InvestmentPositionId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_uuid(self.value, "investment position id"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class AcquisitionLotId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_uuid(self.value, "acquisition lot id"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ShareSaleAllocationId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_uuid(self.value, "share sale allocation id"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class AccountingEntryReference:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_uuid(self.value, "accounting entry reference"))

    def __str__(self) -> str:
        return self.value


class InvestmentKind(StrEnum):
    NORWEGIAN_PRIVATE_COMPANY = "norwegian_private_company"


class InvestmentTaxTreatment(StrEnum):
    EXEMPTION_METHOD = "fritaksmetoden"


class InvestmentDocumentStatus(StrEnum):
    ATTACHED = "attached"
    MISSING_ACCEPTED_WARNING = "missing_accepted_warning"
    NOT_REQUIRED = "not_required"


class InvestmentLotHistoryStatus(StrEnum):
    COMPLETE = "complete"
    NEEDS_RECONSTRUCTION = "needs_reconstruction"


class InvestmentActivityKind(StrEnum):
    SHARE_PURCHASE = "share_purchase"
    SHARE_SALE = "share_sale"
    DIVIDEND_RECEIVED = "dividend_received"


class InvestmentsErrorCode(StrEnum):
    INVALID_INPUT = "INVESTMENTS_INVALID_INPUT"
    FORBIDDEN = "INVESTMENTS_FORBIDDEN"
    IDEMPOTENCY_IN_PROGRESS = "INVESTMENTS_IDEMPOTENCY_IN_PROGRESS"
    IDEMPOTENCY_KEY_REUSED = "INVESTMENTS_IDEMPOTENCY_KEY_REUSED"
    DEPENDENCY_UNAVAILABLE = "INVESTMENTS_DEPENDENCY_UNAVAILABLE"


class InvestmentsError(DomainError):
    @classmethod
    def invalid_input(cls) -> InvestmentsError:
        return cls(
            code=InvestmentsErrorCode.INVALID_INPUT.value,
            category=ErrorCategory.INVALID_INPUT,
        )

    @classmethod
    def forbidden(cls) -> InvestmentsError:
        return cls(
            code=InvestmentsErrorCode.FORBIDDEN.value,
            category=ErrorCategory.FORBIDDEN,
        )

    @classmethod
    def unavailable(cls) -> InvestmentsError:
        return cls(
            code=InvestmentsErrorCode.DEPENDENCY_UNAVAILABLE.value,
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
        )

    @classmethod
    def conflict(cls, code: InvestmentsErrorCode | str) -> InvestmentsError:
        return cls(
            code=InvestmentsErrorCode(code).value,
            category=ErrorCategory.CONFLICT,
        )


@dataclass(frozen=True, slots=True)
class InvestmentsCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear


@dataclass(frozen=True, slots=True)
class RecordSharePurchaseCommand(InvestmentsCommand):
    action_id: InvestmentActionId
    investment_key: str
    investment_name: str
    investment_kind: InvestmentKind
    tax_treatment: InvestmentTaxTreatment
    acquisition_date: LocalDate
    share_count: int
    purchase_amount: Money
    org_number: str | None
    bank_transaction_id: InvestmentSourceReference | None
    document_id: InvestmentSourceReference | None
    document_status: InvestmentDocumentStatus


@dataclass(frozen=True, slots=True)
class RecordShareSaleCommand(InvestmentsCommand):
    action_id: InvestmentActionId
    position_id: InvestmentPositionId
    sale_date: LocalDate
    sold_share_count: int
    proceeds: Money
    bank_transaction_id: InvestmentSourceReference | None
    document_id: InvestmentSourceReference | None
    document_status: InvestmentDocumentStatus


@dataclass(frozen=True, slots=True)
class RecordReceivedDividendCommand(InvestmentsCommand):
    action_id: InvestmentActionId
    position_id: InvestmentPositionId
    paying_company_name: str
    declared_date: LocalDate
    paid_date: LocalDate
    gross_amount: Money
    tax_treatment: InvestmentTaxTreatment
    bank_transaction_id: InvestmentSourceReference | None
    document_id: InvestmentSourceReference | None
    document_status: InvestmentDocumentStatus


@dataclass(frozen=True, slots=True)
class PreparedSharePurchase:
    position_id: InvestmentPositionId
    lot_id: AcquisitionLotId
    position_created: bool
    investment_name: str
    purchase_amount: Money


@dataclass(frozen=True, slots=True)
class PreparedShareSale:
    position_id: InvestmentPositionId
    investment_name: str
    fifo_cost_basis_reduction: Money


@dataclass(frozen=True, slots=True)
class PreparedReceivedDividend:
    position_id: InvestmentPositionId
    investment_name: str
    paying_company_name: str
    taxable_add_back: Money


@dataclass(frozen=True, slots=True)
class RecordedSharePurchase:
    action_id: InvestmentActionId
    position_id: InvestmentPositionId
    lot_id: AcquisitionLotId
    accounting_entry_id: AccountingEntryReference
    position_created: bool
    replayed: bool


@dataclass(frozen=True, slots=True)
class RecordedShareSale:
    action_id: InvestmentActionId
    position_id: InvestmentPositionId
    accounting_entry_id: AccountingEntryReference
    replayed: bool


@dataclass(frozen=True, slots=True)
class RecordedReceivedDividend:
    action_id: InvestmentActionId
    position_id: InvestmentPositionId
    accounting_entry_id: AccountingEntryReference
    taxable_add_back: Money
    replayed: bool


@dataclass(frozen=True, slots=True)
class InvestmentCursor:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_uuid(self.value, "investment cursor"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class InvestmentPositionView:
    position_id: InvestmentPositionId
    company_id: CompanyId
    investment_key: str
    name: str
    kind: InvestmentKind
    tax_treatment: InvestmentTaxTreatment
    org_number: str | None
    share_count: int
    cost_basis: Money
    lot_history_status: InvestmentLotHistoryStatus
    movement_count: int
    movements: tuple[Mapping[str, object], ...]
    created_by: ActorId
    created_at: Timestamp
    updated_at: Timestamp


@dataclass(frozen=True, slots=True)
class AcquisitionLotView:
    lot_id: AcquisitionLotId
    company_id: CompanyId
    position_id: InvestmentPositionId
    acquisition_action_id: InvestmentActionId
    acquisition_date: LocalDate
    original_share_count: int
    remaining_share_count: int
    original_cost_basis: Money
    remaining_cost_basis: Money
    created_by: ActorId
    created_at: Timestamp


@dataclass(frozen=True, slots=True)
class InvestmentActivityView:
    activity_id: InvestmentActionId
    company_id: CompanyId
    income_year: IncomeYear
    activity_kind: InvestmentActivityKind
    action_date: LocalDate
    position_id: InvestmentPositionId
    investment_key: str
    investment_name: str
    investment_kind: InvestmentKind
    tax_treatment: InvestmentTaxTreatment
    org_number: str | None
    acquisition_lot_id: AcquisitionLotId | None
    share_count: int | None
    purchase_amount: Money | None
    sold_share_count: int | None
    proceeds: Money | None
    fifo_cost_basis_reduction: Money | None
    remaining_share_count: int | None
    remaining_cost_basis: Money | None
    paying_company_name: str | None
    declared_date: LocalDate | None
    gross_amount: Money | None
    taxable_add_back: Money | None
    gain_or_loss: Money | None
    bank_transaction_id: InvestmentSourceReference | None
    document_id: InvestmentSourceReference | None
    document_status: InvestmentDocumentStatus
    accounting_entry_id: AccountingEntryReference | None
    created_by: ActorId
    created_at: Timestamp


@dataclass(frozen=True, slots=True)
class ShareSaleAllocationView:
    allocation_id: ShareSaleAllocationId
    company_id: CompanyId
    position_id: InvestmentPositionId
    lot_id: AcquisitionLotId
    sale_action_id: InvestmentActionId
    allocation_order: int
    acquisition_date: LocalDate
    allocated_share_count: int
    allocated_cost_basis: Money
    created_by: ActorId
    created_at: Timestamp


@dataclass(frozen=True, slots=True)
class InvestmentPositionPage:
    items: tuple[InvestmentPositionView, ...]
    next_cursor: InvestmentCursor | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class AcquisitionLotPage:
    items: tuple[AcquisitionLotView, ...]
    next_cursor: InvestmentCursor | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class InvestmentActivityPage:
    items: tuple[InvestmentActivityView, ...]
    next_cursor: InvestmentCursor | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class ShareSaleAllocationPage:
    items: tuple[ShareSaleAllocationView, ...]
    next_cursor: InvestmentCursor | None
    has_more: bool


class InvestmentsPersistence(Protocol):
    async def get_received_dividend_replay(
        self, command: RecordReceivedDividendCommand
    ) -> RecordedReceivedDividend | None: ...

    async def prepare_received_dividend(
        self,
        command: RecordReceivedDividendCommand,
        *,
        taxable_add_back: Money,
    ) -> PreparedReceivedDividend: ...

    async def complete_received_dividend(
        self,
        command: RecordReceivedDividendCommand,
        *,
        prepared: PreparedReceivedDividend,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedReceivedDividend: ...

    async def get_share_purchase_replay(
        self, command: RecordSharePurchaseCommand
    ) -> RecordedSharePurchase | None: ...

    async def prepare_share_purchase(
        self, command: RecordSharePurchaseCommand
    ) -> PreparedSharePurchase: ...

    async def complete_share_purchase(
        self,
        command: RecordSharePurchaseCommand,
        *,
        prepared: PreparedSharePurchase,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedSharePurchase: ...

    async def prepare_share_sale(
        self, command: RecordShareSaleCommand
    ) -> PreparedShareSale: ...

    async def get_share_sale_replay(
        self, command: RecordShareSaleCommand
    ) -> RecordedShareSale | None: ...

    async def complete_share_sale(
        self,
        command: RecordShareSaleCommand,
        *,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedShareSale: ...


class InvestmentsCommands(Protocol):
    async def get_received_dividend_replay(
        self, command: RecordReceivedDividendCommand
    ) -> RecordedReceivedDividend | None: ...

    async def prepare_received_dividend(
        self,
        command: RecordReceivedDividendCommand,
        *,
        taxable_add_back: Money,
    ) -> PreparedReceivedDividend: ...

    async def complete_received_dividend(
        self,
        command: RecordReceivedDividendCommand,
        *,
        prepared: PreparedReceivedDividend,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedReceivedDividend: ...

    async def get_share_purchase_replay(
        self, command: RecordSharePurchaseCommand
    ) -> RecordedSharePurchase | None: ...

    async def prepare_share_purchase(
        self, command: RecordSharePurchaseCommand
    ) -> PreparedSharePurchase: ...

    async def complete_share_purchase(
        self,
        command: RecordSharePurchaseCommand,
        *,
        prepared: PreparedSharePurchase,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedSharePurchase: ...

    async def prepare_share_sale(
        self, command: RecordShareSaleCommand
    ) -> PreparedShareSale: ...

    async def get_share_sale_replay(
        self, command: RecordShareSaleCommand
    ) -> RecordedShareSale | None: ...

    async def complete_share_sale(
        self,
        command: RecordShareSaleCommand,
        *,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedShareSale: ...


class InvestmentsQueries(Protocol):
    async def list_share_sale_allocations(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> ShareSaleAllocationPage: ...

    async def list_activity(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> InvestmentActivityPage: ...

    async def list_positions(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> InvestmentPositionPage: ...

    async def list_acquisition_lots(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> AcquisitionLotPage: ...


InvestmentsAdapter = TypeVar("InvestmentsAdapter", bound=type[object])


def investments_persistence_adapter(
    contract: type[object],
) -> Callable[[InvestmentsAdapter], InvestmentsAdapter]:
    """Declare an infrastructure binding without registering global state."""

    def declare(adapter: InvestmentsAdapter) -> InvestmentsAdapter:
        _ = contract
        return adapter

    return declare


__all__ = [
    "AccountingEntryReference",
    "AcquisitionLotPage",
    "AcquisitionLotId",
    "AcquisitionLotView",
    "InvestmentActionId",
    "InvestmentActivityKind",
    "InvestmentActivityPage",
    "InvestmentActivityView",
    "InvestmentCursor",
    "InvestmentDocumentStatus",
    "InvestmentKind",
    "InvestmentLotHistoryStatus",
    "InvestmentPositionPage",
    "InvestmentPositionId",
    "InvestmentPositionView",
    "InvestmentSourceReference",
    "InvestmentTaxTreatment",
    "InvestmentsError",
    "InvestmentsErrorCode",
    "InvestmentsCommand",
    "InvestmentsCommands",
    "InvestmentsPersistence",
    "InvestmentsQueries",
    "PreparedSharePurchase",
    "PreparedShareSale",
    "PreparedReceivedDividend",
    "RecordReceivedDividendCommand",
    "RecordSharePurchaseCommand",
    "RecordShareSaleCommand",
    "RecordedSharePurchase",
    "RecordedShareSale",
    "RecordedReceivedDividend",
    "ShareSaleAllocationId",
    "ShareSaleAllocationPage",
    "ShareSaleAllocationView",
    "investments_persistence_adapter",
]
