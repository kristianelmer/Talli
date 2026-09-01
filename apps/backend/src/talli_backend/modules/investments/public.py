"""Stable public contract for investment positions and acquisition lots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from hashlib import sha256
import json
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
class InvestmentEconomicEventId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "value",
            _opaque_uuid(self.value, "investment economic event id"),
        )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class InvestmentSettlementId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "value",
            _opaque_uuid(self.value, "investment settlement id"),
        )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class InvestmentUnits:
    amount: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("investment units must be Decimal")
        if not self.amount.is_finite() or self.amount < 0:
            raise ValueError("investment units must be finite and non-negative")
        try:
            normalized = self.amount.quantize(Decimal("0.000000000001"))
        except InvalidOperation:
            raise ValueError("investment units exceed the supported precision") from None
        if normalized != self.amount or normalized >= Decimal("1e26"):
            raise ValueError("investment units exceed the supported precision")
        object.__setattr__(self, "amount", normalized)

    @classmethod
    def of(cls, amount: str | Decimal) -> InvestmentUnits:
        try:
            decimal_amount = amount if isinstance(amount, Decimal) else Decimal(amount)
        except (InvalidOperation, ValueError):
            raise ValueError("investment units must be a decimal string") from None
        return cls(decimal_amount)


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
class InvestmentMeasurementId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_uuid(self.value, "investment measurement id"))

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


class InvestmentMeasurementRule(StrEnum):
    LOWER_OF_COST_AND_FAIR_VALUE = "lower_of_cost_and_fair_value"
    COST_WITH_EVIDENCED_IMPAIRMENT = "cost_with_evidenced_impairment"


class InvestmentTaxTreatment(StrEnum):
    EXEMPTION_METHOD = "fritaksmetoden"


class InvestmentPolicyVersion(StrEnum):
    DOMESTIC_2026_V1 = "domestic_2026_v1"
    DOMESTIC_2026_V2 = "domestic_2026_v2"


class InvestmentDocumentStatus(StrEnum):
    ATTACHED = "attached"
    MISSING_ACCEPTED_WARNING = "missing_accepted_warning"
    NOT_REQUIRED = "not_required"


class InvestmentEvidenceMode(StrEnum):
    LINKED_SOURCES = "linked_sources"
    MANUAL_FALLBACK = "manual_fallback"


class InvestmentSourceCapability(StrEnum):
    BANKING = "BANKING"
    DOCUMENTS = "DOCUMENTS"


class InvestmentSettlementBalanceKind(StrEnum):
    PURCHASE_PAYABLE = "purchase_payable"
    SALE_RECEIVABLE = "sale_receivable"
    DIVIDEND_RECEIVABLE = "dividend_receivable"
    FUND_DISTRIBUTION_RECEIVABLE = "fund_distribution_receivable"


@dataclass(frozen=True, slots=True)
class InvestmentFactReference:
    capability: InvestmentSourceCapability
    record_id: InvestmentSourceReference
    revision: int
    fact_sha256: str

    def __post_init__(self) -> None:
        digest = self.fact_sha256.strip().lower()
        if self.revision < 1 or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise InvestmentsError.invalid_input()
        object.__setattr__(self, "fact_sha256", digest)


@dataclass(frozen=True, slots=True)
class InvestmentEvidence:
    mode: InvestmentEvidenceMode
    reference: str
    owner_attested: bool
    document_facts: tuple[InvestmentFactReference, ...]
    bank_fact: InvestmentFactReference | None

    def __post_init__(self) -> None:
        reference = self.reference.strip()
        if not reference or len(reference) > 500:
            raise InvestmentsError.invalid_input()
        facts = (*self.document_facts, *((self.bank_fact,) if self.bank_fact else ()))
        if not facts or len(facts) > 50:
            raise InvestmentsError.invalid_input()
        identities = {
            (fact.capability, fact.record_id.value, fact.revision) for fact in facts
        }
        if len(identities) != len(facts):
            raise InvestmentsError.invalid_input()
        if any(
            fact.capability is not InvestmentSourceCapability.DOCUMENTS
            for fact in self.document_facts
        ) or (
            self.bank_fact is not None
            and (
                self.bank_fact.capability is not InvestmentSourceCapability.BANKING
                or self.bank_fact.revision != 1
            )
        ):
            raise InvestmentsError.invalid_input()
        if (
            self.mode is InvestmentEvidenceMode.LINKED_SOURCES
            and self.owner_attested
        ) or (
            self.mode is InvestmentEvidenceMode.MANUAL_FALLBACK
            and not self.owner_attested
        ):
            raise InvestmentsError.invalid_input()
        object.__setattr__(self, "reference", reference)

    def digest(self) -> str:
        return sha256(
            json.dumps(
                {
                    "bankFact": (
                        {
                            "capability": self.bank_fact.capability.value,
                            "recordId": str(self.bank_fact.record_id),
                            "revision": self.bank_fact.revision,
                            "factSha256": self.bank_fact.fact_sha256,
                        }
                        if self.bank_fact is not None
                        else None
                    ),
                    "documentFacts": [
                        {
                            "capability": fact.capability.value,
                            "recordId": str(fact.record_id),
                            "revision": fact.revision,
                            "factSha256": fact.fact_sha256,
                        }
                        for fact in self.document_facts
                    ],
                    "evidenceMode": self.mode.value,
                    "evidenceReference": self.reference,
                    "ownerAttested": self.owner_attested,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()


def _require_recognition_evidence(evidence: InvestmentEvidence) -> None:
    if not evidence.document_facts or evidence.bank_fact is not None:
        raise InvestmentsError.invalid_input()


def _require_settlement_evidence(evidence: InvestmentEvidence) -> None:
    if evidence.document_facts or evidence.bank_fact is None:
        raise InvestmentsError.invalid_input()


def _require_positive_units(units: InvestmentUnits) -> None:
    if units.amount <= 0:
        raise InvestmentsError.invalid_input()


def _require_2026_recognition(
    income_year: IncomeYear,
    recognition_date: LocalDate,
) -> None:
    if income_year.value != 2026 or recognition_date.value.year != income_year.value:
        raise InvestmentsError.invalid_input()


class InvestmentLotHistoryStatus(StrEnum):
    COMPLETE = "complete"
    NEEDS_RECONSTRUCTION = "needs_reconstruction"


class InvestmentActivityKind(StrEnum):
    SHARE_PURCHASE = "share_purchase"
    SHARE_SALE = "share_sale"
    DIVIDEND_RECEIVED = "dividend_received"
    FUND_DISTRIBUTION_RECEIVED = "fund_distribution_received"


class InvestmentCorrectionTargetKind(StrEnum):
    ECONOMIC_EVENT = "economic_event"
    CASH_SETTLEMENT = "cash_settlement"


class InvestmentsErrorCode(StrEnum):
    INVALID_INPUT = "INVESTMENTS_INVALID_INPUT"
    FORBIDDEN = "INVESTMENTS_FORBIDDEN"
    IDEMPOTENCY_IN_PROGRESS = "INVESTMENTS_IDEMPOTENCY_IN_PROGRESS"
    IDEMPOTENCY_KEY_REUSED = "INVESTMENTS_IDEMPOTENCY_KEY_REUSED"
    DEPENDENCY_UNAVAILABLE = "INVESTMENTS_DEPENDENCY_UNAVAILABLE"
    BANK_FACT_ALREADY_CLAIMED = "INVESTMENTS_BANK_FACT_ALREADY_CLAIMED"


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
class RecognizeSharePurchaseCommand(InvestmentsCommand):
    event_id: InvestmentEconomicEventId
    investment_key: str
    investment_name: str
    investment_kind: InvestmentKind
    accounting_classification: InvestmentAccountingClassification
    acquisition_date: LocalDate
    share_count: InvestmentUnits
    purchase_amount: Money
    transaction_costs: Money
    org_number: str | None
    fund_equity_ratio_basis_points: int | None
    fund_tax_statement_reference: str | None
    evidence: InvestmentEvidence

    def __post_init__(self) -> None:
        _require_2026_recognition(self.income_year, self.acquisition_date)
        _require_positive_units(self.share_count)
        _require_recognition_evidence(self.evidence)


@dataclass(frozen=True, slots=True)
class RecognizeShareSaleCommand(InvestmentsCommand):
    event_id: InvestmentEconomicEventId
    position_id: InvestmentPositionId
    sale_date: LocalDate
    sold_share_count: InvestmentUnits
    proceeds: Money
    transaction_costs: Money
    sale_year_fund_equity_ratio_basis_points: int | None
    fund_tax_statement_reference: str | None
    evidence: InvestmentEvidence

    def __post_init__(self) -> None:
        _require_2026_recognition(self.income_year, self.sale_date)
        _require_positive_units(self.sold_share_count)
        _require_recognition_evidence(self.evidence)


@dataclass(frozen=True, slots=True)
class RecognizeReceivedDividendCommand(InvestmentsCommand):
    event_id: InvestmentEconomicEventId
    position_id: InvestmentPositionId
    paying_company_name: str
    declared_date: LocalDate
    gross_amount: Money
    lawful_dividend_confirmed: bool
    group_exception_claimed: bool
    year_end_ownership_basis_points: int | None
    year_end_voting_basis_points: int | None
    group_evidence_reference: str | None
    evidence: InvestmentEvidence

    def __post_init__(self) -> None:
        _require_2026_recognition(self.income_year, self.declared_date)
        _require_recognition_evidence(self.evidence)


@dataclass(frozen=True, slots=True)
class RecognizeReceivedFundDistributionCommand(InvestmentsCommand):
    event_id: InvestmentEconomicEventId
    position_id: InvestmentPositionId
    fund_name: str
    entitlement_date: LocalDate
    gross_amount: Money
    opening_fund_equity_ratio_basis_points: int
    fund_tax_statement_reference: str
    evidence: InvestmentEvidence

    def __post_init__(self) -> None:
        _require_2026_recognition(self.income_year, self.entitlement_date)
        _require_recognition_evidence(self.evidence)


@dataclass(frozen=True, slots=True)
class SettleInvestmentCashCommand(InvestmentsCommand):
    settlement_id: InvestmentSettlementId
    event_id: InvestmentEconomicEventId
    settlement_date: LocalDate
    amount: Money
    evidence: InvestmentEvidence

    def __post_init__(self) -> None:
        if self.settlement_date.value.year != self.income_year.value:
            raise InvestmentsError.invalid_input()
        _require_settlement_evidence(self.evidence)


@dataclass(frozen=True, slots=True)
class RecordInvestmentYearEndMeasurementCommand(InvestmentsCommand):
    measurement_id: InvestmentMeasurementId
    position_id: InvestmentPositionId
    as_of: LocalDate
    observed_or_recoverable_value: Money
    tax_value: Money
    evidence: InvestmentEvidence

    def __post_init__(self) -> None:
        if (
            self.income_year.value != 2026
            or self.as_of.value != date(self.income_year.value, 12, 31)
            or self.observed_or_recoverable_value.amount < 0
            or self.tax_value.amount < 0
        ):
            raise InvestmentsError.invalid_input()
        _require_recognition_evidence(self.evidence)


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
    RecognizeSharePurchaseCommand
    | RecognizeShareSaleCommand
    | RecognizeReceivedDividendCommand
    | RecognizeReceivedFundDistributionCommand
    | SettleInvestmentCashCommand
)


@dataclass(frozen=True, slots=True)
class CorrectInvestmentCommand(InvestmentsCommand):
    correction_id: InvestmentCorrectionId
    target_kind: InvestmentCorrectionTargetKind
    original_record_id: InvestmentEconomicEventId | InvestmentSettlementId
    original_activity_kind: InvestmentActivityKind
    correction_date: LocalDate
    reason: str
    evidence: InvestmentEvidence
    replacement: InvestmentReplacementCommand

    def __post_init__(self) -> None:
        _require_2026_recognition(self.income_year, self.correction_date)
        _require_recognition_evidence(self.evidence)
        if (
            self.target_kind is InvestmentCorrectionTargetKind.ECONOMIC_EVENT
            and not isinstance(self.original_record_id, InvestmentEconomicEventId)
        ) or (
            self.target_kind is InvestmentCorrectionTargetKind.CASH_SETTLEMENT
            and not isinstance(self.original_record_id, InvestmentSettlementId)
        ):
            raise InvestmentsError.invalid_input()


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
class PreparedSharePurchaseRecognition:
    position_id: InvestmentPositionId
    lot_id: AcquisitionLotId
    position_created: bool
    investment_name: str
    accounting_classification: InvestmentAccountingClassification
    acquisition_cost: Money
    expected_settlement_amount: Money
    settlement_balance_kind: InvestmentSettlementBalanceKind
    evidence_digest: str
    calculation_id: str


@dataclass(frozen=True, slots=True)
class PreparedInvestmentCashSettlement:
    event_id: InvestmentEconomicEventId
    recognition_accounting_entry_id: AccountingEntryReference
    settlement_balance_kind: InvestmentSettlementBalanceKind
    amount: Money
    event_fact_sha256: str
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class PreparedInvestmentMeasurementFacts:
    position_id: InvestmentPositionId
    investment_name: str
    investment_kind: InvestmentKind
    accounting_classification: InvestmentAccountingClassification
    quantity: InvestmentUnits
    source_book_cost: Money
    pre_measurement_book_value: Money
    tax_basis: Money


@dataclass(frozen=True, slots=True)
class PreparedInvestmentYearEndMeasurement:
    position_id: InvestmentPositionId
    investment_name: str
    accounting_classification: InvestmentAccountingClassification
    measurement_rule: InvestmentMeasurementRule
    quantity: InvestmentUnits
    source_book_cost: Money
    pre_measurement_book_value: Money
    observed_or_recoverable_value: Money
    impairment_amount: Money
    reversal_amount: Money
    closing_book_value: Money
    tax_basis: Money
    tax_value: Money
    evidence_digest: str
    calculation_id: str


@dataclass(frozen=True, slots=True)
class InvestmentSaleLotFact:
    lot_id: AcquisitionLotId
    allocation_order: int
    acquisition_date: LocalDate
    allocated_share_count: InvestmentUnits
    allocated_book_cost_basis: Money
    allocated_tax_basis: Money
    acquisition_year_fund_equity_ratio_basis_points: int | None


@dataclass(frozen=True, slots=True)
class InvestmentSaleLotCalculation:
    lot_id: AcquisitionLotId
    allocation_order: int
    allocated_share_count: InvestmentUnits
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
class PreparedEconomicEventCorrection:
    original_accounting_entry_id: AccountingEntryReference
    original_position_id: InvestmentPositionId
    evidence_digest: str


@dataclass(frozen=True, slots=True)
class PreparedCashSettlementCorrection:
    original_accounting_entry_id: AccountingEntryReference
    original_settlement_id: InvestmentSettlementId
    event_id: InvestmentEconomicEventId
    recognition_accounting_entry_id: AccountingEntryReference
    settlement_balance_kind: InvestmentSettlementBalanceKind
    amount: Money
    event_fact_sha256: str
    replacement_evidence_digest: str
    evidence_digest: str
    original_activity_kind: InvestmentActivityKind


PreparedInvestmentCorrection = (
    PreparedEconomicEventCorrection | PreparedCashSettlementCorrection
)


@dataclass(frozen=True, slots=True)
class RecordedSharePurchase:
    action_id: InvestmentActionId
    position_id: InvestmentPositionId
    lot_id: AcquisitionLotId
    accounting_entry_id: AccountingEntryReference
    position_created: bool
    replayed: bool


@dataclass(frozen=True, slots=True)
class RecordedInvestmentEconomicEvent:
    event_id: InvestmentEconomicEventId
    position_id: InvestmentPositionId
    recognition_accounting_entry_id: AccountingEntryReference
    expected_settlement_amount: Money
    settlement_balance_kind: InvestmentSettlementBalanceKind
    replayed: bool


@dataclass(frozen=True, slots=True)
class RecordedInvestmentCashSettlement:
    settlement_id: InvestmentSettlementId
    event_id: InvestmentEconomicEventId
    settlement_accounting_entry_id: AccountingEntryReference
    replayed: bool


@dataclass(frozen=True, slots=True)
class RecordedInvestmentYearEndMeasurement:
    measurement_id: InvestmentMeasurementId
    position_id: InvestmentPositionId
    accounting_entry_id: AccountingEntryReference | None
    measurement_rule: InvestmentMeasurementRule
    closing_book_value: Money
    tax_basis: Money
    tax_value: Money
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
    target_kind: InvestmentCorrectionTargetKind
    original_record_id: InvestmentEconomicEventId | InvestmentSettlementId
    replacement_record_id: InvestmentEconomicEventId | InvestmentSettlementId
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
    share_count: InvestmentUnits
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
    original_share_count: InvestmentUnits
    remaining_share_count: InvestmentUnits
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
    share_count: InvestmentUnits | None
    purchase_amount: Money | None
    transaction_costs: Money | None
    capitalized_cost: Money | None
    sold_share_count: InvestmentUnits | None
    proceeds: Money | None
    net_proceeds: Money | None
    fifo_cost_basis_reduction: Money | None
    fifo_tax_basis_reduction: Money | None
    remaining_share_count: InvestmentUnits | None
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
class InvestmentLifecycleEventView:
    event_id: InvestmentEconomicEventId
    company_id: CompanyId
    income_year: IncomeYear
    activity_kind: InvestmentActivityKind
    recognition_date: LocalDate
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
    position_created: bool | None
    share_count: InvestmentUnits | None
    purchase_amount: Money | None
    transaction_costs: Money | None
    capitalized_cost: Money | None
    sold_share_count: InvestmentUnits | None
    proceeds: Money | None
    net_proceeds: Money | None
    fifo_cost_basis_reduction: Money | None
    fifo_tax_basis_reduction: Money | None
    remaining_share_count: InvestmentUnits | None
    remaining_cost_basis: Money | None
    remaining_tax_basis: Money | None
    book_gain_or_loss: Money | None
    tax_gain_or_loss: Money | None
    exempt_gain: Money | None
    taxable_gain: Money | None
    non_deductible_loss: Money | None
    deductible_loss: Money | None
    paying_company_name: str | None
    lawful_dividend_confirmed: bool | None
    group_exception_claimed: bool | None
    group_exception_applied: bool | None
    year_end_ownership_basis_points: int | None
    year_end_voting_basis_points: int | None
    group_evidence_reference: str | None
    fund_name: str | None
    entitlement_date: LocalDate | None
    opening_fund_equity_ratio_basis_points: int | None
    gross_amount: Money | None
    taxable_add_back: Money | None
    dividend_portion: Money | None
    interest_portion: Money | None
    total_taxable_income: Money | None
    expected_settlement_amount: Money
    settlement_balance_kind: InvestmentSettlementBalanceKind
    recognition_accounting_entry_id: AccountingEntryReference
    document_facts: tuple[InvestmentFactReference, ...]
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str
    evidence_digest: str
    calculation_id: str
    owner_attested: bool
    settlement_id: InvestmentSettlementId | None
    settlement_date: LocalDate | None
    settlement_amount: Money | None
    bank_fact: InvestmentFactReference | None
    settlement_accounting_entry_id: AccountingEntryReference | None
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
    allocated_share_count: InvestmentUnits
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
    target_kind: InvestmentCorrectionTargetKind
    original_record_id: InvestmentEconomicEventId | InvestmentSettlementId
    original_activity_kind: InvestmentActivityKind
    reversal_accounting_entry_id: AccountingEntryReference
    replacement_record_id: InvestmentEconomicEventId | InvestmentSettlementId
    replacement_activity_kind: InvestmentActivityKind
    replacement_accounting_entry_id: AccountingEntryReference
    reason: str
    document_facts: tuple[InvestmentFactReference, ...]
    legacy_bank_transaction_id: InvestmentSourceReference | None
    legacy_document_id: InvestmentSourceReference | None
    legacy_document_status: InvestmentDocumentStatus | None
    legacy: bool
    evidence_mode: InvestmentEvidenceMode
    evidence_reference: str
    evidence_digest: str
    owner_attested: bool
    created_by: ActorId
    created_at: Timestamp


@dataclass(frozen=True, slots=True)
class InvestmentYearEndMeasurementView:
    measurement_id: InvestmentMeasurementId
    company_id: CompanyId
    income_year: IncomeYear
    position_id: InvestmentPositionId
    as_of: LocalDate
    measurement_rule: InvestmentMeasurementRule
    quantity: InvestmentUnits
    source_book_cost: Money
    pre_measurement_book_value: Money
    observed_or_recoverable_value: Money
    impairment_amount: Money
    reversal_amount: Money
    closing_book_value: Money
    tax_basis: Money
    tax_value: Money
    evidence_digest: str
    calculation_id: str
    accounting_entry_id: AccountingEntryReference | None
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
class InvestmentLifecycleEventPage:
    items: tuple[InvestmentLifecycleEventView, ...]
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


@dataclass(frozen=True, slots=True)
class InvestmentYearEndMeasurementPage:
    items: tuple[InvestmentYearEndMeasurementView, ...]
    next_cursor: InvestmentCursor | None
    has_more: bool


class InvestmentsPersistence(Protocol):
    async def get_year_end_measurement_replay(
        self, command: RecordInvestmentYearEndMeasurementCommand
    ) -> RecordedInvestmentYearEndMeasurement | None: ...

    async def prepare_year_end_measurement(
        self,
        command: RecordInvestmentYearEndMeasurementCommand,
        *,
        evidence_digest: str,
    ) -> PreparedInvestmentMeasurementFacts: ...

    async def complete_year_end_measurement(
        self,
        command: RecordInvestmentYearEndMeasurementCommand,
        *,
        prepared: PreparedInvestmentYearEndMeasurement,
        accounting_entry_id: AccountingEntryReference | None,
    ) -> RecordedInvestmentYearEndMeasurement: ...

    async def get_share_purchase_recognition_replay(
        self, command: RecognizeSharePurchaseCommand
    ) -> RecordedInvestmentEconomicEvent | None: ...

    async def prepare_share_purchase_recognition(
        self,
        command: RecognizeSharePurchaseCommand,
        *,
        capitalized_cost: Money,
        evidence_digest: str,
        calculation_id: str,
    ) -> PreparedSharePurchaseRecognition: ...

    async def complete_share_purchase_recognition(
        self,
        command: RecognizeSharePurchaseCommand,
        *,
        prepared: PreparedSharePurchaseRecognition,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedInvestmentEconomicEvent: ...

    async def get_share_sale_recognition_replay(
        self, command: RecognizeShareSaleCommand
    ) -> RecordedInvestmentEconomicEvent | None: ...

    async def prepare_share_sale_recognition(
        self,
        command: RecognizeShareSaleCommand,
        *,
        net_proceeds: Money,
        evidence_digest: str,
    ) -> PreparedShareSaleFacts: ...

    async def complete_share_sale_recognition(
        self,
        command: RecognizeShareSaleCommand,
        *,
        prepared: PreparedShareSale,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedInvestmentEconomicEvent: ...

    async def get_received_dividend_recognition_replay(
        self, command: RecognizeReceivedDividendCommand
    ) -> RecordedInvestmentEconomicEvent | None: ...

    async def prepare_received_dividend_recognition(
        self,
        command: RecognizeReceivedDividendCommand,
        *,
        evidence_digest: str,
    ) -> PreparedReceivedDividendFacts: ...

    async def complete_received_dividend_recognition(
        self,
        command: RecognizeReceivedDividendCommand,
        *,
        prepared: PreparedReceivedDividend,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedInvestmentEconomicEvent: ...

    async def get_received_fund_distribution_recognition_replay(
        self, command: RecognizeReceivedFundDistributionCommand
    ) -> RecordedInvestmentEconomicEvent | None: ...

    async def prepare_received_fund_distribution_recognition(
        self,
        command: RecognizeReceivedFundDistributionCommand,
        *,
        evidence_digest: str,
    ) -> PreparedReceivedFundDistributionFacts: ...

    async def complete_received_fund_distribution_recognition(
        self,
        command: RecognizeReceivedFundDistributionCommand,
        *,
        prepared: PreparedReceivedFundDistribution,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedInvestmentEconomicEvent: ...

    async def get_cash_settlement_replay(
        self, command: SettleInvestmentCashCommand
    ) -> RecordedInvestmentCashSettlement | None: ...

    async def prepare_cash_settlement(
        self,
        command: SettleInvestmentCashCommand,
        *,
        evidence_digest: str,
    ) -> PreparedInvestmentCashSettlement: ...

    async def complete_cash_settlement(
        self,
        command: SettleInvestmentCashCommand,
        *,
        prepared: PreparedInvestmentCashSettlement,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedInvestmentCashSettlement: ...

    async def get_investment_correction_replay(
        self, command: CorrectInvestmentCommand
    ) -> RecordedInvestmentCorrection | None: ...

    async def prepare_investment_correction(
        self,
        command: CorrectInvestmentCommand,
        *,
        evidence_digest: str,
        replacement_evidence_digest: str,
    ) -> PreparedInvestmentCorrection: ...

    async def complete_investment_correction(
        self,
        command: CorrectInvestmentCommand,
        *,
        prepared: PreparedInvestmentCorrection,
        replacement_accounting_entry_id: AccountingEntryReference,
    ) -> RecordedInvestmentCorrection: ...


class InvestmentsCommands(Protocol):
    async def get_year_end_measurement_replay(
        self, command: RecordInvestmentYearEndMeasurementCommand
    ) -> RecordedInvestmentYearEndMeasurement | None: ...

    async def prepare_year_end_measurement(
        self, command: RecordInvestmentYearEndMeasurementCommand
    ) -> PreparedInvestmentYearEndMeasurement: ...

    async def complete_year_end_measurement(
        self,
        command: RecordInvestmentYearEndMeasurementCommand,
        *,
        prepared: PreparedInvestmentYearEndMeasurement,
        accounting_entry_id: AccountingEntryReference | None,
    ) -> RecordedInvestmentYearEndMeasurement: ...

    async def get_share_purchase_recognition_replay(
        self, command: RecognizeSharePurchaseCommand
    ) -> RecordedInvestmentEconomicEvent | None: ...

    async def prepare_share_purchase_recognition(
        self,
        command: RecognizeSharePurchaseCommand,
    ) -> PreparedSharePurchaseRecognition: ...

    async def complete_share_purchase_recognition(
        self,
        command: RecognizeSharePurchaseCommand,
        *,
        prepared: PreparedSharePurchaseRecognition,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedInvestmentEconomicEvent: ...

    async def get_share_sale_recognition_replay(
        self, command: RecognizeShareSaleCommand
    ) -> RecordedInvestmentEconomicEvent | None: ...

    async def prepare_share_sale_recognition(
        self, command: RecognizeShareSaleCommand
    ) -> PreparedShareSale: ...

    async def complete_share_sale_recognition(
        self,
        command: RecognizeShareSaleCommand,
        *,
        prepared: PreparedShareSale,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedInvestmentEconomicEvent: ...

    async def get_received_dividend_recognition_replay(
        self, command: RecognizeReceivedDividendCommand
    ) -> RecordedInvestmentEconomicEvent | None: ...

    async def prepare_received_dividend_recognition(
        self, command: RecognizeReceivedDividendCommand
    ) -> PreparedReceivedDividend: ...

    async def complete_received_dividend_recognition(
        self,
        command: RecognizeReceivedDividendCommand,
        *,
        prepared: PreparedReceivedDividend,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedInvestmentEconomicEvent: ...

    async def get_received_fund_distribution_recognition_replay(
        self, command: RecognizeReceivedFundDistributionCommand
    ) -> RecordedInvestmentEconomicEvent | None: ...

    async def prepare_received_fund_distribution_recognition(
        self, command: RecognizeReceivedFundDistributionCommand
    ) -> PreparedReceivedFundDistribution: ...

    async def complete_received_fund_distribution_recognition(
        self,
        command: RecognizeReceivedFundDistributionCommand,
        *,
        prepared: PreparedReceivedFundDistribution,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedInvestmentEconomicEvent: ...

    async def get_cash_settlement_replay(
        self, command: SettleInvestmentCashCommand
    ) -> RecordedInvestmentCashSettlement | None: ...

    async def prepare_cash_settlement(
        self,
        command: SettleInvestmentCashCommand,
    ) -> PreparedInvestmentCashSettlement: ...

    async def complete_cash_settlement(
        self,
        command: SettleInvestmentCashCommand,
        *,
        prepared: PreparedInvestmentCashSettlement,
        accounting_entry_id: AccountingEntryReference,
    ) -> RecordedInvestmentCashSettlement: ...

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
        replacement: RecordedInvestmentEconomicEvent | AccountingEntryReference,
    ) -> RecordedInvestmentCorrection: ...


class InvestmentsQueries(Protocol):
    async def list_year_end_measurements(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> InvestmentYearEndMeasurementPage: ...

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

    async def list_lifecycle_events(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: InvestmentCursor | None,
        limit: int,
    ) -> InvestmentLifecycleEventPage: ...

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
    "InvestmentCorrectionTargetKind",
    "InvestmentCorrectionPage",
    "InvestmentCorrectionView",
    "InvestmentDocumentStatus",
    "InvestmentEvidenceMode",
    "InvestmentEvidence",
    "InvestmentEconomicEventId",
    "InvestmentFactReference",
    "InvestmentKind",
    "InvestmentMeasurementId",
    "InvestmentMeasurementRule",
    "InvestmentLotHistoryStatus",
    "InvestmentLifecycleEventPage",
    "InvestmentLifecycleEventView",
    "InvestmentPolicyVersion",
    "InvestmentPositionPage",
    "InvestmentPositionId",
    "InvestmentPositionView",
    "InvestmentYearEndMeasurementPage",
    "InvestmentYearEndMeasurementView",
    "InvestmentSourceReference",
    "InvestmentSourceCapability",
    "InvestmentSettlementId",
    "InvestmentSettlementBalanceKind",
    "InvestmentTaxTreatment",
    "InvestmentUnits",
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
    "PreparedEconomicEventCorrection",
    "PreparedCashSettlementCorrection",
    "PreparedInvestmentCashSettlement",
    "PreparedInvestmentMeasurementFacts",
    "PreparedInvestmentYearEndMeasurement",
    "PreparedSharePurchaseRecognition",
    "RecognizeReceivedDividendCommand",
    "RecognizeReceivedFundDistributionCommand",
    "RecognizeSharePurchaseCommand",
    "RecognizeShareSaleCommand",
    "RecordReceivedDividendCommand",
    "RecordReceivedFundDistributionCommand",
    "RecordSharePurchaseCommand",
    "RecordShareSaleCommand",
    "RecordInvestmentYearEndMeasurementCommand",
    "RecordedSharePurchase",
    "RecordedShareSale",
    "RecordedReceivedDividend",
    "RecordedReceivedFundDistribution",
    "RecordedInvestmentCorrection",
    "RecordedInvestmentCashSettlement",
    "RecordedInvestmentEconomicEvent",
    "RecordedInvestmentYearEndMeasurement",
    "SettleInvestmentCashCommand",
    "ShareSaleAllocationId",
    "ShareSaleAllocationPage",
    "ShareSaleAllocationView",
    "investments_persistence_adapter",
]
