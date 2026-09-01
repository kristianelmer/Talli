"""Stable public contract for investment positions and acquisition lots."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
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
class InvestmentCorrectionId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_uuid(self.value, "investment correction id"))

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
    NORWEGIAN_LISTED_SHARE = "norwegian_listed_share"
    NORWEGIAN_EQUITY_FUND = "norwegian_equity_fund"


class InvestmentAccountingClassification(StrEnum):
    SUBSIDIARY = "subsidiary"
    ASSOCIATE = "associate"
    OTHER_LONG_TERM = "other_long_term"
    CURRENT_LISTED_SHARE = "current_listed_share"
    CURRENT_FUND = "current_fund"


class InvestmentTaxTreatment(StrEnum):
    EXEMPTION_METHOD = "fritaksmetoden"


class InvestmentPolicyVersion(StrEnum):
    DOMESTIC_2026_V1 = "domestic_2026_v1"


class InvestmentDocumentStatus(StrEnum):
    ATTACHED = "attached"
    MISSING_ACCEPTED_WARNING = "missing_accepted_warning"
    NOT_REQUIRED = "not_required"


class InvestmentEvidenceMode(StrEnum):
    LINKED_SOURCES = "linked_sources"
    MANUAL_FALLBACK = "manual_fallback"


class InvestmentLotHistoryStatus(StrEnum):
    COMPLETE = "complete"
    NEEDS_RECONSTRUCTION = "needs_reconstruction"


class InvestmentActivityKind(StrEnum):
    SHARE_PURCHASE = "share_purchase"
    SHARE_SALE = "share_sale"
    DIVIDEND_RECEIVED = "dividend_received"
    FUND_DISTRIBUTION_RECEIVED = "fund_distribution_received"


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
    accounting_classification: InvestmentAccountingClassification
    tax_treatment: InvestmentTaxTreatment
    acquisition_date: LocalDate
    share_count: int
    purchase_amount: Money
    transaction_costs: Money
    org_number: str | None
    fund_equity_ratio_basis_points: int | None
    fund_tax_statement_reference: str | None
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str
    owner_attested: bool
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
    transaction_costs: Money
    sale_year_fund_equity_ratio_basis_points: int | None
    fund_tax_statement_reference: str | None
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str
    owner_attested: bool
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
    lawful_dividend_confirmed: bool
    group_exception_claimed: bool
    year_end_ownership_basis_points: int | None
    year_end_voting_basis_points: int | None
    group_evidence_reference: str | None
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str
    owner_attested: bool
    bank_transaction_id: InvestmentSourceReference | None
    document_id: InvestmentSourceReference | None
    document_status: InvestmentDocumentStatus


@dataclass(frozen=True, slots=True)
class RecordReceivedFundDistributionCommand(InvestmentsCommand):
    action_id: InvestmentActionId
    position_id: InvestmentPositionId
    fund_name: str
    entitlement_date: LocalDate
    paid_date: LocalDate
    gross_amount: Money
    opening_fund_equity_ratio_basis_points: int
    fund_tax_statement_reference: str
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str
    owner_attested: bool
    bank_transaction_id: InvestmentSourceReference | None
    document_id: InvestmentSourceReference | None
    document_status: InvestmentDocumentStatus


InvestmentReplacementCommand = (
    RecordSharePurchaseCommand
    | RecordShareSaleCommand
    | RecordReceivedDividendCommand
    | RecordReceivedFundDistributionCommand
)


@dataclass(frozen=True, slots=True)
class CorrectInvestmentCommand(InvestmentsCommand):
    correction_id: InvestmentCorrectionId
    original_action_id: InvestmentActionId
    original_activity_kind: InvestmentActivityKind
    correction_date: LocalDate
    reason: str
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str
    owner_attested: bool
    bank_transaction_id: InvestmentSourceReference | None
    document_id: InvestmentSourceReference | None
    document_status: InvestmentDocumentStatus
    replacement: InvestmentReplacementCommand


@dataclass(frozen=True, slots=True)
class PreparedSharePurchase:
    position_id: InvestmentPositionId
    lot_id: AcquisitionLotId
    position_created: bool
    investment_name: str
    accounting_classification: InvestmentAccountingClassification
    purchase_amount: Money
    evidence_digest: str
    calculation_id: str


@dataclass(frozen=True, slots=True)
class InvestmentSaleLotFact:
    lot_id: AcquisitionLotId
    allocation_order: int
    acquisition_date: LocalDate
    allocated_share_count: int
    allocated_book_cost_basis: Money
    allocated_tax_basis: Money
    acquisition_year_fund_equity_ratio_basis_points: int | None


@dataclass(frozen=True, slots=True)
class InvestmentSaleLotCalculation:
    lot_id: AcquisitionLotId
    allocation_order: int
    allocated_share_count: int
    allocated_net_proceeds: Money
    allocated_book_cost_basis: Money
    allocated_tax_basis: Money
    tax_gain_or_loss: Money
    average_fund_equity_ratio_basis_points: Decimal | None
    exempt_gain: Money
    taxable_gain: Money
    non_deductible_loss: Money
    deductible_loss: Money


@dataclass(frozen=True, slots=True)
class PreparedShareSaleFacts:
    position_id: InvestmentPositionId
    investment_name: str
    investment_kind: InvestmentKind
    accounting_classification: InvestmentAccountingClassification
    fifo_book_cost_basis_reduction: Money
    fifo_tax_basis_reduction: Money
    lot_facts: tuple[InvestmentSaleLotFact, ...]


@dataclass(frozen=True, slots=True)
class PreparedShareSale:
    position_id: InvestmentPositionId
    investment_name: str
    accounting_classification: InvestmentAccountingClassification
    investment_kind: InvestmentKind
    net_proceeds: Money
    fifo_cost_basis_reduction: Money
    fifo_tax_basis_reduction: Money
    book_gain_or_loss: Money
    tax_gain_or_loss: Money
    exempt_gain: Money
    taxable_gain: Money
    non_deductible_loss: Money
    deductible_loss: Money
    lot_calculations: tuple[InvestmentSaleLotCalculation, ...]
    evidence_digest: str
    calculation_id: str


@dataclass(frozen=True, slots=True)
class PreparedReceivedDividendFacts:
    position_id: InvestmentPositionId
    investment_name: str
    investment_kind: InvestmentKind


@dataclass(frozen=True, slots=True)
class PreparedReceivedDividend:
    position_id: InvestmentPositionId
    investment_name: str
    paying_company_name: str
    taxable_add_back: Money
    group_exception_applied: bool
    evidence_digest: str
    calculation_id: str


@dataclass(frozen=True, slots=True)
class PreparedReceivedFundDistributionFacts:
    position_id: InvestmentPositionId
    investment_name: str
    investment_kind: InvestmentKind


@dataclass(frozen=True, slots=True)
class PreparedReceivedFundDistribution:
    position_id: InvestmentPositionId
    investment_name: str
    fund_name: str
    dividend_portion: Money
    interest_portion: Money
    taxable_add_back: Money
    total_taxable_income: Money
    evidence_digest: str
    calculation_id: str


@dataclass(frozen=True, slots=True)
class PreparedInvestmentCorrection:
    original_accounting_entry_id: AccountingEntryReference
    original_position_id: InvestmentPositionId
    evidence_digest: str


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
class RecordedReceivedFundDistribution:
    action_id: InvestmentActionId
    position_id: InvestmentPositionId
    accounting_entry_id: AccountingEntryReference
    dividend_portion: Money
    interest_portion: Money
    taxable_add_back: Money
    total_taxable_income: Money
    replayed: bool


@dataclass(frozen=True, slots=True)
class RecordedInvestmentCorrection:
    correction_id: InvestmentCorrectionId
    original_action_id: InvestmentActionId
    replacement_action_id: InvestmentActionId
    reversal_accounting_entry_id: AccountingEntryReference
    replacement_accounting_entry_id: AccountingEntryReference
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
    accounting_classification: InvestmentAccountingClassification
    tax_treatment: InvestmentTaxTreatment
    org_number: str | None
    fund_equity_ratio_basis_points: int | None
    fund_tax_statement_reference: str | None
    share_count: int
    cost_basis: Money
    tax_basis: Money
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
    original_tax_basis: Money
    remaining_tax_basis: Money
    acquisition_year_fund_equity_ratio_basis_points: int | None
    fund_tax_statement_reference: str | None
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
    accounting_classification: InvestmentAccountingClassification
    tax_treatment: InvestmentTaxTreatment
    org_number: str | None
    fund_equity_ratio_basis_points: int | None
    fund_tax_statement_reference: str | None
    acquisition_lot_id: AcquisitionLotId | None
    share_count: int | None
    purchase_amount: Money | None
    transaction_costs: Money | None
    capitalized_cost: Money | None
    sold_share_count: int | None
    proceeds: Money | None
    net_proceeds: Money | None
    fifo_cost_basis_reduction: Money | None
    fifo_tax_basis_reduction: Money | None
    remaining_share_count: int | None
    remaining_cost_basis: Money | None
    remaining_tax_basis: Money | None
    paying_company_name: str | None
    declared_date: LocalDate | None
    gross_amount: Money | None
    taxable_add_back: Money | None
    gain_or_loss: Money | None
    book_gain_or_loss: Money | None
    tax_gain_or_loss: Money | None
    exempt_gain: Money | None
    taxable_gain: Money | None
    non_deductible_loss: Money | None
    deductible_loss: Money | None
    lawful_dividend_confirmed: bool | None
    group_exception_claimed: bool | None
    group_exception_applied: bool | None
    year_end_ownership_basis_points: int | None
    year_end_voting_basis_points: int | None
    group_evidence_reference: str | None
    fund_name: str | None
    entitlement_date: LocalDate | None
    opening_fund_equity_ratio_basis_points: int | None
    dividend_portion: Money | None
    interest_portion: Money | None
    total_taxable_income: Money | None
    bank_transaction_id: InvestmentSourceReference | None
    document_id: InvestmentSourceReference | None
    document_status: InvestmentDocumentStatus
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str
    evidence_digest: str
    calculation_id: str
    owner_attested: bool
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
    allocated_book_cost_basis: Money
    allocated_tax_basis: Money
    allocated_net_proceeds: Money
    average_fund_equity_ratio_basis_points: Decimal | None
    tax_gain_or_loss: Money
    exempt_gain: Money
    taxable_gain: Money
    non_deductible_loss: Money
    deductible_loss: Money
    created_by: ActorId
    created_at: Timestamp


@dataclass(frozen=True, slots=True)
class InvestmentCorrectionView:
    correction_id: InvestmentCorrectionId
    company_id: CompanyId
    income_year: IncomeYear
    original_action_id: InvestmentActionId
    original_activity_kind: InvestmentActivityKind
    reversal_accounting_entry_id: AccountingEntryReference
    replacement_action_id: InvestmentActionId
    replacement_activity_kind: InvestmentActivityKind
    replacement_accounting_entry_id: AccountingEntryReference
    reason: str
    bank_transaction_id: InvestmentSourceReference | None
    document_id: InvestmentSourceReference | None
    document_status: InvestmentDocumentStatus
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str
    evidence_digest: str
    owner_attested: bool
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


@dataclass(frozen=True, slots=True)
class InvestmentCorrectionPage:
    items: tuple[InvestmentCorrectionView, ...]
    next_cursor: InvestmentCursor | None
    has_more: bool


class InvestmentsPersistence(Protocol):
    async def get_investment_correction_replay(
        self, command: CorrectInvestmentCommand
    ) -> RecordedInvestmentCorrection | None: ...

    async def prepare_investment_correction(
        self,
        command: CorrectInvestmentCommand,
        *,
        evidence_digest: str,
    ) -> PreparedInvestmentCorrection: ...

    async def complete_investment_correction(
        self,
        command: CorrectInvestmentCommand,
        *,
        prepared: PreparedInvestmentCorrection,
        replacement: RecordedSharePurchase | RecordedShareSale
        | RecordedReceivedDividend | RecordedReceivedFundDistribution,
    ) -> RecordedInvestmentCorrection: ...

    async def get_received_fund_distribution_replay(
        self, command: RecordReceivedFundDistributionCommand
    ) -> RecordedReceivedFundDistribution | None: ...

    async def prepare_received_fund_distribution(
        self,
        command: RecordReceivedFundDistributionCommand,
        *,
        evidence_digest: str,
    ) -> PreparedReceivedFundDistributionFacts: ...

    async def complete_received_fund_distribution(
        self,
        command: RecordReceivedFundDistributionCommand,
        *,
        prepared: PreparedReceivedFundDistribution,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedReceivedFundDistribution: ...

    async def get_received_dividend_replay(
        self, command: RecordReceivedDividendCommand
    ) -> RecordedReceivedDividend | None: ...

    async def prepare_received_dividend(
        self,
        command: RecordReceivedDividendCommand,
        *,
        evidence_digest: str,
    ) -> PreparedReceivedDividendFacts: ...

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
        self,
        command: RecordSharePurchaseCommand,
        *,
        capitalized_cost: Money,
        evidence_digest: str,
        calculation_id: str,
    ) -> PreparedSharePurchase: ...

    async def complete_share_purchase(
        self,
        command: RecordSharePurchaseCommand,
        *,
        prepared: PreparedSharePurchase,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedSharePurchase: ...

    async def prepare_share_sale(
        self,
        command: RecordShareSaleCommand,
        *,
        net_proceeds: Money,
        evidence_digest: str,
    ) -> PreparedShareSaleFacts: ...

    async def get_share_sale_replay(
        self, command: RecordShareSaleCommand
    ) -> RecordedShareSale | None: ...

    async def complete_share_sale(
        self,
        command: RecordShareSaleCommand,
        *,
        prepared: PreparedShareSale,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedShareSale: ...


class InvestmentsCommands(Protocol):
    async def get_investment_correction_replay(
        self, command: CorrectInvestmentCommand
    ) -> RecordedInvestmentCorrection | None: ...

    async def prepare_investment_correction(
        self, command: CorrectInvestmentCommand
    ) -> PreparedInvestmentCorrection: ...

    async def complete_investment_correction(
        self,
        command: CorrectInvestmentCommand,
        *,
        prepared: PreparedInvestmentCorrection,
        replacement: RecordedSharePurchase | RecordedShareSale
        | RecordedReceivedDividend | RecordedReceivedFundDistribution,
    ) -> RecordedInvestmentCorrection: ...

    async def get_received_fund_distribution_replay(
        self, command: RecordReceivedFundDistributionCommand
    ) -> RecordedReceivedFundDistribution | None: ...

    async def prepare_received_fund_distribution(
        self, command: RecordReceivedFundDistributionCommand
    ) -> PreparedReceivedFundDistribution: ...

    async def complete_received_fund_distribution(
        self,
        command: RecordReceivedFundDistributionCommand,
        *,
        prepared: PreparedReceivedFundDistribution,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedReceivedFundDistribution: ...

    async def get_received_dividend_replay(
        self, command: RecordReceivedDividendCommand
    ) -> RecordedReceivedDividend | None: ...

    async def prepare_received_dividend(
        self,
        command: RecordReceivedDividendCommand,
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
        self,
        command: RecordSharePurchaseCommand,
    ) -> PreparedSharePurchase: ...

    async def complete_share_purchase(
        self,
        command: RecordSharePurchaseCommand,
        *,
        prepared: PreparedSharePurchase,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedSharePurchase: ...

    async def prepare_share_sale(
        self,
        command: RecordShareSaleCommand,
    ) -> PreparedShareSale: ...

    async def get_share_sale_replay(
        self, command: RecordShareSaleCommand
    ) -> RecordedShareSale | None: ...

    async def complete_share_sale(
        self,
        command: RecordShareSaleCommand,
        *,
        prepared: PreparedShareSale,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedShareSale: ...


class InvestmentsQueries(Protocol):
    async def list_corrections(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> InvestmentCorrectionPage: ...

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
    "CorrectInvestmentCommand",
    "InvestmentActionId",
    "InvestmentAccountingClassification",
    "InvestmentActivityKind",
    "InvestmentActivityPage",
    "InvestmentActivityView",
    "InvestmentCursor",
    "InvestmentCorrectionId",
    "InvestmentCorrectionPage",
    "InvestmentCorrectionView",
    "InvestmentDocumentStatus",
    "InvestmentEvidenceMode",
    "InvestmentKind",
    "InvestmentLotHistoryStatus",
    "InvestmentPolicyVersion",
    "InvestmentPositionPage",
    "InvestmentPositionId",
    "InvestmentPositionView",
    "InvestmentSourceReference",
    "InvestmentTaxTreatment",
    "InvestmentSaleLotCalculation",
    "InvestmentSaleLotFact",
    "InvestmentReplacementCommand",
    "InvestmentsError",
    "InvestmentsErrorCode",
    "InvestmentsCommand",
    "InvestmentsCommands",
    "InvestmentsPersistence",
    "InvestmentsQueries",
    "PreparedSharePurchase",
    "PreparedShareSale",
    "PreparedShareSaleFacts",
    "PreparedReceivedDividend",
    "PreparedReceivedDividendFacts",
    "PreparedReceivedFundDistribution",
    "PreparedReceivedFundDistributionFacts",
    "PreparedInvestmentCorrection",
    "RecordReceivedDividendCommand",
    "RecordReceivedFundDistributionCommand",
    "RecordSharePurchaseCommand",
    "RecordShareSaleCommand",
    "RecordedSharePurchase",
    "RecordedShareSale",
    "RecordedReceivedDividend",
    "RecordedReceivedFundDistribution",
    "RecordedInvestmentCorrection",
    "ShareSaleAllocationId",
    "ShareSaleAllocationPage",
    "ShareSaleAllocationView",
    "investments_persistence_adapter",
]
