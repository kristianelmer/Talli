"""Stable public contract for Talli's narrow-ledger capability."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Protocol, TypeAlias, TypeVar
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
class LedgerEntryId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_uuid(self.value, "ledger entry id"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class PeriodLockId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _opaque_uuid(self.value, "period lock id"))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ReconstructionAssessmentId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "value", _opaque_uuid(self.value, "reconstruction assessment id")
        )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class CompanyYearCloseAssessmentId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "value", _opaque_uuid(self.value, "company-year close assessment id")
        )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class CompanyYearCloseLockId:
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "value", _opaque_uuid(self.value, "company-year close lock id")
        )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class LedgerCursor:
    value: str

    def __post_init__(self) -> None:
        if not self.value or len(self.value) > 4096:
            raise ValueError("ledger cursor is invalid")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class LedgerSourceRecordId:
    """Ledger-owned immutable correlation to a source capability record."""

    value: str

    def __post_init__(self) -> None:
        value = self.value.strip()
        if not value or len(value) > 255:
            raise ValueError("ledger source record id is invalid")
        object.__setattr__(self, "value", value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class BankLoanReferenceId:
    """Ledger-owned stable identity for one ordinary bank-loan lifecycle."""

    value: str

    def __post_init__(self) -> None:
        value = self.value.strip()
        if not value or len(value) > 255:
            raise ValueError("bank-loan reference id is invalid")
        object.__setattr__(self, "value", value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class CapitalIncreaseReferenceId:
    """Ledger-owned stable identity for one cash-capital-increase lifecycle."""

    value: str

    def __post_init__(self) -> None:
        value = self.value.strip()
        if not value or len(value) > 255:
            raise ValueError("capital-increase reference id is invalid")
        object.__setattr__(self, "value", value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class CapitalReductionReferenceId:
    """Ledger-owned stable identity for one loss-coverage reduction lifecycle."""

    value: str

    def __post_init__(self) -> None:
        value = self.value.strip()
        if not value or len(value) > 255:
            raise ValueError("capital-reduction reference id is invalid")
        object.__setattr__(self, "value", value)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class DividendDecisionReferenceId:
    """Stable identity for one declared dividend that remains unsettled."""

    value: str

    def __post_init__(self) -> None:
        value = self.value.strip()
        if not value or len(value) > 255:
            raise ValueError("dividend-decision reference id is invalid")
        object.__setattr__(self, "value", value)

    def __str__(self) -> str:
        return self.value


class LedgerSourceCapability(StrEnum):
    LEDGER = "LEDGER"
    BANKING = "BANKING"
    INVESTMENTS = "INVESTMENTS"
    CORPORATE_GOVERNANCE = "CORPORATE_GOVERNANCE"
    SHAREHOLDER_REGISTER_FILING = "SHAREHOLDER_REGISTER_FILING"
    COMPANY_TAX_FILING = "COMPANY_TAX_FILING"
    ANNUAL_ACCOUNTS_FILING = "ANNUAL_ACCOUNTS_FILING"
    DOCUMENTS = "DOCUMENTS"


class LedgerFactRole(StrEnum):
    PRIMARY = "PRIMARY"
    CORROBORATING = "CORROBORATING"


@dataclass(frozen=True, slots=True)
class LedgerFactReference:
    capability: LedgerSourceCapability
    record_id: LedgerSourceRecordId
    revision: int
    fact_sha256: str

    def __post_init__(self) -> None:
        digest = self.fact_sha256.strip().lower()
        if self.revision < 1 or len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        object.__setattr__(self, "fact_sha256", digest)


class AdministrativeCostCategory(StrEnum):
    BANK_FEE = "BANK_FEE"
    ACCOUNTING_FEE = "ACCOUNTING_FEE"
    SOFTWARE = "SOFTWARE"
    PUBLIC_FEE = "PUBLIC_FEE"
    LEGAL_ADVISORY = "LEGAL_ADVISORY"
    OTHER_ADMIN_COST = "OTHER_ADMIN_COST"


class AdministrativeCostBlock(StrEnum):
    VAT_BEARING_DOCUMENT = "VAT_BEARING_DOCUMENT"
    PAYROLL = "PAYROLL"
    CUSTOMER_INVOICING = "CUSTOMER_INVOICING"
    INVENTORY_PROPERTY_OR_OPERATING_PURCHASE = (
        "INVENTORY_PROPERTY_OR_OPERATING_PURCHASE"
    )
    PRIVATE_OR_MIXED_PURPOSE = "PRIVATE_OR_MIXED_PURPOSE"
    CAPITALIZABLE_COST = "CAPITALIZABLE_COST"
    SHARE_ACQUISITION_OR_REALIZATION_COST = (
        "SHARE_ACQUISITION_OR_REALIZATION_COST"
    )
    FOREIGN_CURRENCY = "FOREIGN_CURRENCY"
    TAX_CLASSIFICATION_AMBIGUOUS = "TAX_CLASSIFICATION_AMBIGUOUS"


class AdministrativeCostCorrectionScope(StrEnum):
    CURRENT_COMPANY_YEAR = "CURRENT_COMPANY_YEAR"
    PRIOR_YEAR_ERROR = "PRIOR_YEAR_ERROR"


class BankSuggestionRule(StrEnum):
    BANK_FEE = "BANK_FEE"
    SYSTEM_SUBSCRIPTION = "SYSTEM_SUBSCRIPTION"
    DEPOSIT_INTEREST = "DEPOSIT_INTEREST"


class ShareholderLoanDirection(StrEnum):
    SHAREHOLDER_TO_COMPANY = "SHAREHOLDER_TO_COMPANY"
    COMPANY_TO_CORPORATE_SHAREHOLDER = "COMPANY_TO_CORPORATE_SHAREHOLDER"


class TaxSettlementKind(StrEnum):
    PAYABLE = "payable"
    PAYMENT = "payment"
    REFUND = "refund"


class ReconstructionEvidenceKind(StrEnum):
    PRIOR_CLOSING_OPENING = "PRIOR_CLOSING_OPENING"
    BANK_MOVEMENTS = "BANK_MOVEMENTS"
    BANK_RECONCILIATION = "BANK_RECONCILIATION"
    INVESTMENTS = "INVESTMENTS"
    SHAREHOLDERS = "SHAREHOLDERS"
    LOANS = "LOANS"
    EQUITY = "EQUITY"
    TAX_HISTORY = "TAX_HISTORY"
    CURRENT_YEAR_ACTIVITY = "CURRENT_YEAR_ACTIVITY"
    DOCUMENTS = "DOCUMENTS"
    UNSUPPORTED_ACTIVITY_CHECK = "UNSUPPORTED_ACTIVITY_CHECK"


class ReconstructionEvidenceStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    GAP = "GAP"
    UNKNOWN = "UNKNOWN"


class ReconstructionEvidenceIssuer(StrEnum):
    COMPANY_ACCESS = "COMPANY_ACCESS"
    LEDGER = "LEDGER"
    BANKING = "BANKING"
    INVESTMENTS = "INVESTMENTS"
    DOCUMENTS = "DOCUMENTS"
    CORPORATE_GOVERNANCE = "CORPORATE_GOVERNANCE"
    SHAREHOLDER_REGISTER_FILING = "SHAREHOLDER_REGISTER_FILING"
    COMPANY_TAX_FILING = "COMPANY_TAX_FILING"


class ReconstructionGapCode(StrEnum):
    PRIOR_CLOSING_MISMATCH = "PRIOR_CLOSING_MISMATCH"
    BANK_MOVEMENTS_INCOMPLETE = "BANK_MOVEMENTS_INCOMPLETE"
    BANK_NOT_RECONCILED = "BANK_NOT_RECONCILED"
    INVESTMENTS_UNCONFIRMED = "INVESTMENTS_UNCONFIRMED"
    SHAREHOLDERS_UNCONFIRMED = "SHAREHOLDERS_UNCONFIRMED"
    LOANS_UNCONFIRMED = "LOANS_UNCONFIRMED"
    EQUITY_UNCONFIRMED = "EQUITY_UNCONFIRMED"
    TAX_HISTORY_UNCONFIRMED = "TAX_HISTORY_UNCONFIRMED"
    CURRENT_ACTIVITY_INCOMPLETE = "CURRENT_ACTIVITY_INCOMPLETE"
    DOCUMENTS_INCOMPLETE = "DOCUMENTS_INCOMPLETE"
    UNSUPPORTED_ACTIVITY_FOUND = "UNSUPPORTED_ACTIVITY_FOUND"


class ReconstructionState(StrEnum):
    BLOCKED = "BLOCKED"
    READY = "READY"


class OpeningBalanceCategory(StrEnum):
    SUBSIDIARY_LOAN_RECEIVABLE = "SUBSIDIARY_LOAN_RECEIVABLE"
    GROUP_COMPANY_LOAN_RECEIVABLE = "GROUP_COMPANY_LOAN_RECEIVABLE"
    CORPORATE_SHAREHOLDER_LOAN_RECEIVABLE = "CORPORATE_SHAREHOLDER_LOAN_RECEIVABLE"
    BANK = "BANK"
    RESTRICTED_BANK = "RESTRICTED_BANK"
    SUBSIDIARY_INVESTMENT = "SUBSIDIARY_INVESTMENT"
    ASSOCIATE_INVESTMENT = "ASSOCIATE_INVESTMENT"
    OTHER_LONG_TERM_INVESTMENT = "OTHER_LONG_TERM_INVESTMENT"
    CURRENT_LISTED_SHARE_INVESTMENT = "CURRENT_LISTED_SHARE_INVESTMENT"
    CURRENT_FUND_INVESTMENT = "CURRENT_FUND_INVESTMENT"
    SUBSCRIPTION_RECEIVABLE = "SUBSCRIPTION_RECEIVABLE"
    DIVIDEND_RECEIVABLE = "DIVIDEND_RECEIVABLE"
    GROUP_CONTRIBUTION_RECEIVABLE = "GROUP_CONTRIBUTION_RECEIVABLE"
    TAX_RECEIVABLE = "TAX_RECEIVABLE"
    ACCRUED_INTEREST_RECEIVABLE = "ACCRUED_INTEREST_RECEIVABLE"
    DEFERRED_TAX_ASSET = "DEFERRED_TAX_ASSET"
    REGISTERED_SHARE_CAPITAL = "REGISTERED_SHARE_CAPITAL"
    SHARE_PREMIUM = "SHARE_PREMIUM"
    UNREGISTERED_CAPITAL_INCREASE = "UNREGISTERED_CAPITAL_INCREASE"
    UNREGISTERED_CAPITAL_REDUCTION = "UNREGISTERED_CAPITAL_REDUCTION"
    OTHER_PAID_IN_EQUITY = "OTHER_PAID_IN_EQUITY"
    RETAINED_EARNINGS = "RETAINED_EARNINGS"
    UNCOVERED_LOSS = "UNCOVERED_LOSS"
    OTHER_EQUITY = "OTHER_EQUITY"
    LONG_TERM_BANK_LOAN_PAYABLE = "LONG_TERM_BANK_LOAN_PAYABLE"
    SHORT_TERM_BANK_LOAN_PAYABLE = "SHORT_TERM_BANK_LOAN_PAYABLE"
    OWNER_LOAN_PAYABLE = "OWNER_LOAN_PAYABLE"
    INTERCOMPANY_LOAN_PAYABLE = "INTERCOMPANY_LOAN_PAYABLE"
    SUPPLIER_PAYABLE = "SUPPLIER_PAYABLE"
    CURRENT_TAX_PAYABLE = "CURRENT_TAX_PAYABLE"
    DEFERRED_TAX_LIABILITY = "DEFERRED_TAX_LIABILITY"
    ACCRUED_INTEREST_PAYABLE = "ACCRUED_INTEREST_PAYABLE"
    DIVIDEND_PAYABLE = "DIVIDEND_PAYABLE"
    GROUP_CONTRIBUTION_PAYABLE = "GROUP_CONTRIBUTION_PAYABLE"


class OpeningPositionMode(StrEnum):
    NEW_COMPANY = "NEW_COMPANY"
    PRIOR_CLOSE_RECONSTRUCTION = "PRIOR_CLOSE_RECONSTRUCTION"


class BankLoanMaturity(StrEnum):
    LONG_TERM = "LONG_TERM"
    SHORT_TERM = "SHORT_TERM"


class InvestmentClassification(StrEnum):
    SUBSIDIARY = "SUBSIDIARY"
    ASSOCIATE = "ASSOCIATE"
    OTHER_LONG_TERM = "OTHER_LONG_TERM"
    CURRENT_LISTED_SHARE = "CURRENT_LISTED_SHARE"
    CURRENT_FUND = "CURRENT_FUND"


class CompanyYearCloseEvidenceKind(StrEnum):
    BANK_ROWS_RESOLVED = "BANK_ROWS_RESOLVED"
    MATERIAL_BALANCES_DOCUMENTED = "MATERIAL_BALANCES_DOCUMENTED"
    REPORTING_RECONCILED = "REPORTING_RECONCILED"


class CompanyYearCloseOutputKind(StrEnum):
    INVESTMENTS = "INVESTMENTS"
    CORPORATE_GOVERNANCE = "CORPORATE_GOVERNANCE"
    SHAREHOLDER_REGISTER_FILING = "SHAREHOLDER_REGISTER_FILING"
    COMPANY_TAX_FILING = "COMPANY_TAX_FILING"
    ANNUAL_ACCOUNTS_FILING = "ANNUAL_ACCOUNTS_FILING"
    SAF_T = "SAF_T"
    COMPANY_ARCHIVE = "COMPANY_ARCHIVE"


class CompanyYearCloseGapCode(StrEnum):
    SOURCE_INCOMPLETE = "SOURCE_INCOMPLETE"
    JOURNAL_UNBALANCED = "JOURNAL_UNBALANCED"
    DUPLICATE_POSTING_FOUND = "DUPLICATE_POSTING_FOUND"
    UNSUPPORTED_TRANSACTION = "UNSUPPORTED_TRANSACTION"
    BANK_NOT_RECONCILED = "BANK_NOT_RECONCILED"
    UNRESOLVED_BANK_ROW = "UNRESOLVED_BANK_ROW"
    MATERIAL_BALANCE_UNDOCUMENTED = "MATERIAL_BALANCE_UNDOCUMENTED"
    REPORTING_NOT_RECONCILED = "REPORTING_NOT_RECONCILED"
    CHECK_EVIDENCE_INCOMPLETE = "CHECK_EVIDENCE_INCOMPLETE"
    PERIOD_END_UNSUPPORTED = "PERIOD_END_UNSUPPORTED"


class CompanyYearCloseState(StrEnum):
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"


class BankLoanEvent(StrEnum):
    DISBURSEMENT = "DISBURSEMENT"
    PAYMENT = "PAYMENT"


class InvestmentDividendPhase(StrEnum):
    FINAL_DECISION = "FINAL_DECISION"
    PAYMENT = "PAYMENT"


class CapitalIncreasePhase(StrEnum):
    BINDING_SUBSCRIPTION = "BINDING_SUBSCRIPTION"
    RESTRICTED_PAYMENT = "RESTRICTED_PAYMENT"
    REGISTERED = "REGISTERED"


class CapitalReductionRecognition(StrEnum):
    DECIDED_NOT_REGISTERED = "DECIDED_NOT_REGISTERED"
    REGISTERED = "REGISTERED"
    FIRST_RECOGNIZED_AFTER_REGISTRATION = "FIRST_RECOGNIZED_AFTER_REGISTRATION"


class IntercompanyLoanPerspective(StrEnum):
    LENDER = "LENDER"
    BORROWER = "BORROWER"


class IntercompanyLoanRelationship(StrEnum):
    PARENT_TO_SUBSIDIARY = "PARENT_TO_SUBSIDIARY"
    OTHER_SAME_GROUP = "OTHER_SAME_GROUP"


class GroupContributionRelationship(StrEnum):
    SUBSIDIARY_TO_PARENT = "SUBSIDIARY_TO_PARENT"
    PARENT_TO_SUBSIDIARY = "PARENT_TO_SUBSIDIARY"
    SISTER_TO_SISTER = "SISTER_TO_SISTER"


class GroupContributionPerspective(StrEnum):
    GIVER = "GIVER"
    RECIPIENT = "RECIPIENT"


@dataclass(frozen=True, slots=True)
class BankInterestIncomeFacts:
    amount: Money


@dataclass(frozen=True, slots=True)
class InvestmentDividendFacts:
    phase: InvestmentDividendPhase
    gross_amount: Money
    decision_entry_id: LedgerEntryId | None = None
    decision_reference_id: DividendDecisionReferenceId | None = None


@dataclass(frozen=True, slots=True)
class AdministrativeCostCorrectionFacts:
    category: AdministrativeCostCategory
    supplier_name: str
    document_date: LocalDate
    delivery_date: LocalDate
    description: str
    business_purpose: str
    amount: Money
    payment_confirmed: bool
    correction_scope: AdministrativeCostCorrectionScope
    blocks: tuple[AdministrativeCostBlock, ...]


@dataclass(frozen=True, slots=True)
class CompanyTaxAccrualFacts:
    current_tax: Money
    deferred_tax_increase: Money


@dataclass(frozen=True, slots=True)
class OrdinaryBankLoanFacts:
    event: BankLoanEvent
    loan_reference_id: BankLoanReferenceId
    principal: Money
    interest: Money
    fee: Money


@dataclass(frozen=True, slots=True)
class CashCapitalIncreaseFacts:
    phase: CapitalIncreasePhase
    capital_increase_reference_id: CapitalIncreaseReferenceId
    nominal_increase: Money
    share_premium: Money


@dataclass(frozen=True, slots=True)
class ApprovedLossCoverageCapitalReductionFacts:
    recognition: CapitalReductionRecognition
    capital_reduction_reference_id: CapitalReductionReferenceId
    nominal_reduction: Money


@dataclass(frozen=True, slots=True)
class ApprovedOwnerLoanFundingFacts:
    principal: Money


@dataclass(frozen=True, slots=True)
class ApprovedOneSidedIntercompanyLoanFundingFacts:
    perspective: IntercompanyLoanPerspective
    relationship: IntercompanyLoanRelationship
    principal: Money


@dataclass(frozen=True, slots=True)
class GroupContributionFacts:
    relationship: GroupContributionRelationship
    perspective: GroupContributionPerspective
    gross_tax_amount: Money
    related_tax: Money
    after_tax_accounting_amount: Money
    post_acquisition_income_proved: bool
    impairment_cleared: bool


SupportedHoldingActionFacts: TypeAlias = (
    ApprovedOneSidedIntercompanyLoanFundingFacts
    | ApprovedOwnerLoanFundingFacts
    | BankInterestIncomeFacts
    | CashCapitalIncreaseFacts
    | CompanyTaxAccrualFacts
    | GroupContributionFacts
    | InvestmentDividendFacts
    | ApprovedLossCoverageCapitalReductionFacts
    | OrdinaryBankLoanFacts
)


class LedgerEntryKind(StrEnum):
    OPENING_BALANCE = "OPENING_BALANCE"
    ADMINISTRATIVE_COST = "ADMINISTRATIVE_COST"
    MANUAL_JOURNAL = "MANUAL_JOURNAL"
    BANK_RULE_SUGGESTION = "BANK_RULE_SUGGESTION"
    DIVIDEND_RECEIVED = "DIVIDEND_RECEIVED"
    OWNER_DIVIDEND_DECLARED = "OWNER_DIVIDEND_DECLARED"
    OWNER_DIVIDEND_PAYMENT = "OWNER_DIVIDEND_PAYMENT"
    SHARE_PURCHASE = "SHARE_PURCHASE"
    SHARE_SALE = "SHARE_SALE"
    SHAREHOLDER_LOAN = "SHAREHOLDER_LOAN"
    TAX_SETTLEMENT = "TAX_SETTLEMENT"
    BANK_INTEREST = "BANK_INTEREST"
    BANK_LOAN = "BANK_LOAN"
    CAPITAL_INCREASE = "CAPITAL_INCREASE"
    CAPITAL_REDUCTION = "CAPITAL_REDUCTION"
    COMPANY_TAX_ACCRUAL = "COMPANY_TAX_ACCRUAL"
    GROUP_CONTRIBUTION = "GROUP_CONTRIBUTION"
    INTERCOMPANY_LOAN = "INTERCOMPANY_LOAN"
    CORRECTION_REVERSAL = "CORRECTION_REVERSAL"


class LedgerRiskCode(StrEnum):
    MANUAL_JOURNAL_SENSITIVE_ACCOUNT = "MANUAL_JOURNAL_SENSITIVE_ACCOUNT"


class LedgerErrorCode(StrEnum):
    ACCOUNT_INVALID = "LEDGER_ACCOUNT_INVALID"
    ADMINISTRATIVE_COST_NOT_POSITIVE = "LEDGER_ADMINISTRATIVE_COST_NOT_POSITIVE"
    ADMINISTRATIVE_COST_EVIDENCE_INCOMPLETE = (
        "LEDGER_ADMINISTRATIVE_COST_EVIDENCE_INCOMPLETE"
    )
    ADMINISTRATIVE_COST_UNSUPPORTED = "LEDGER_ADMINISTRATIVE_COST_UNSUPPORTED"
    AMOUNT_NEGATIVE = "LEDGER_AMOUNT_NEGATIVE"
    COMPANY_SCOPE_INVALID = "LEDGER_COMPANY_SCOPE_INVALID"
    COMPANY_YEAR_NOT_ADMITTED = "LEDGER_COMPANY_YEAR_NOT_ADMITTED"
    COMPANY_YEAR_CLOSE_EVIDENCE_INVALID = (
        "LEDGER_COMPANY_YEAR_CLOSE_EVIDENCE_INVALID"
    )
    COMPANY_YEAR_CLOSE_RECONSTRUCTION_STALE = (
        "LEDGER_COMPANY_YEAR_CLOSE_RECONSTRUCTION_STALE"
    )
    CORRECTION_ORIGINAL_KIND_UNSUPPORTED = (
        "LEDGER_CORRECTION_ORIGINAL_KIND_UNSUPPORTED"
    )
    CURRENCY_MISMATCH = "LEDGER_CURRENCY_MISMATCH"
    DEPENDENCY_UNAVAILABLE = "LEDGER_DEPENDENCY_UNAVAILABLE"
    DESCRIPTION_REQUIRED = "LEDGER_DESCRIPTION_REQUIRED"
    ENTRY_ALREADY_CORRECTED = "LEDGER_ENTRY_ALREADY_CORRECTED"
    ENTRY_REQUIRES_TWO_LINES = "LEDGER_ENTRY_REQUIRES_TWO_LINES"
    ENTRY_UNBALANCED = "LEDGER_ENTRY_UNBALANCED"
    FORBIDDEN = "LEDGER_FORBIDDEN"
    IDEMPOTENCY_IN_PROGRESS = "LEDGER_IDEMPOTENCY_IN_PROGRESS"
    IDEMPOTENCY_KEY_REUSED = "LEDGER_IDEMPOTENCY_KEY_REUSED"
    INVALID_CURSOR = "LEDGER_INVALID_CURSOR"
    INVALID_INPUT = "LEDGER_INVALID_INPUT"
    LINE_NOT_ONE_SIDED = "LEDGER_LINE_NOT_ONE_SIDED"
    LINE_ZERO = "LEDGER_LINE_ZERO"
    LOCK_REASON_REQUIRED = "LEDGER_LOCK_REASON_REQUIRED"
    MEMO_REQUIRED = "LEDGER_MEMO_REQUIRED"
    NOT_FOUND = "LEDGER_NOT_FOUND"
    OPENING_ALREADY_EXISTS = "LEDGER_OPENING_ALREADY_EXISTS"
    OPENING_BALANCE_INVALID = "LEDGER_OPENING_BALANCE_INVALID"
    OPENING_BALANCE_NEGATIVE = "LEDGER_OPENING_BALANCE_NEGATIVE"
    OPENING_EVIDENCE_INVALID = "LEDGER_OPENING_EVIDENCE_INVALID"
    OPENING_SOURCE_OVERLAP = "LEDGER_OPENING_SOURCE_OVERLAP"
    OWNER_DIVIDEND_ACCOUNTING_POLICY_NOT_APPROVED = (
        "LEDGER_OWNER_DIVIDEND_ACCOUNTING_POLICY_NOT_APPROVED"
    )
    PAGE_LIMIT_INVALID = "LEDGER_PAGE_LIMIT_INVALID"
    PAYEE_REQUIRED = "LEDGER_PAYEE_REQUIRED"
    PERIOD_LOCKED = "LEDGER_PERIOD_LOCKED"
    PRIOR_YEAR_CORRECTION_POLICY_UNRESOLVED = (
        "LEDGER_PRIOR_YEAR_CORRECTION_POLICY_UNRESOLVED"
    )
    WARNING_ACCEPTANCE_REQUIRED = "LEDGER_WARNING_ACCEPTANCE_REQUIRED"
    RECONSTRUCTION_EVIDENCE_INCOMPLETE = "LEDGER_RECONSTRUCTION_EVIDENCE_INCOMPLETE"
    RECONSTRUCTION_EVIDENCE_DUPLICATE = "LEDGER_RECONSTRUCTION_EVIDENCE_DUPLICATE"
    RECONSTRUCTION_COVERAGE_INVALID = "LEDGER_RECONSTRUCTION_COVERAGE_INVALID"
    RECONSTRUCTION_SOURCE_EVIDENCE_INVALID = (
        "LEDGER_RECONSTRUCTION_SOURCE_EVIDENCE_INVALID"
    )
    RECONSTRUCTION_ECONOMIC_FACTS_INVALID = (
        "LEDGER_RECONSTRUCTION_ECONOMIC_FACTS_INVALID"
    )
    RECONSTRUCTION_STALE = "LEDGER_RECONSTRUCTION_STALE"
    BANK_LOAN_ALREADY_EXISTS = "LEDGER_BANK_LOAN_ALREADY_EXISTS"
    BANK_LOAN_EVENT_INVALID = "LEDGER_BANK_LOAN_EVENT_INVALID"
    OPENING_LOAN_ANCHOR_MISSING = "LEDGER_OPENING_LOAN_ANCHOR_MISSING"
    BANK_LOAN_PRINCIPAL_EXCEEDED = "LEDGER_BANK_LOAN_PRINCIPAL_EXCEEDED"
    CASH_CAPITAL_INCREASE_PHASE_INVALID = (
        "LEDGER_CASH_CAPITAL_INCREASE_PHASE_INVALID"
    )
    CASH_CAPITAL_INCREASE_PHASE_MISSING = (
        "LEDGER_CASH_CAPITAL_INCREASE_PHASE_MISSING"
    )
    CASH_CAPITAL_INCREASE_AMOUNT_MISMATCH = (
        "LEDGER_CASH_CAPITAL_INCREASE_AMOUNT_MISMATCH"
    )
    CASH_CAPITAL_INCREASE_PHASE_ALREADY_RECORDED = (
        "LEDGER_CASH_CAPITAL_INCREASE_PHASE_ALREADY_RECORDED"
    )
    OPENING_CAPITAL_INCREASE_ANCHOR_MISSING = (
        "LEDGER_OPENING_CAPITAL_INCREASE_ANCHOR_MISSING"
    )
    LOSS_COVERAGE_CAPITAL_REDUCTION_PHASE_INVALID = (
        "LEDGER_LOSS_COVERAGE_CAPITAL_REDUCTION_PHASE_INVALID"
    )
    LOSS_COVERAGE_CAPITAL_REDUCTION_AMOUNT_MISMATCH = (
        "LEDGER_LOSS_COVERAGE_CAPITAL_REDUCTION_AMOUNT_MISMATCH"
    )
    LOSS_COVERAGE_CAPITAL_REDUCTION_PHASE_ALREADY_RECORDED = (
        "LEDGER_LOSS_COVERAGE_CAPITAL_REDUCTION_PHASE_ALREADY_RECORDED"
    )
    OPENING_CAPITAL_REDUCTION_ANCHOR_MISSING = (
        "LEDGER_OPENING_CAPITAL_REDUCTION_ANCHOR_MISSING"
    )
    RECEIVED_DIVIDEND_ALREADY_SETTLED = "LEDGER_RECEIVED_DIVIDEND_ALREADY_SETTLED"
    RECEIVED_DIVIDEND_DECISION_INVALID = "LEDGER_RECEIVED_DIVIDEND_DECISION_INVALID"
    SOURCE_CAPABILITY_MISMATCH = "LEDGER_SOURCE_CAPABILITY_MISMATCH"


@dataclass(frozen=True, slots=True)
class LedgerRiskFlag:
    code: LedgerRiskCode
    account: str


@dataclass(frozen=True, slots=True)
class LedgerLine:
    account: str
    description: str
    debit: Money
    credit: Money

    def __post_init__(self) -> None:
        description = self.description.strip()
        if len(self.account) != 4 or not self.account.isdigit():
            raise LedgerError.invalid_input("LEDGER_ACCOUNT_INVALID")
        if not description or len(description) > 500:
            raise LedgerError.invalid_input("LEDGER_DESCRIPTION_REQUIRED")
        if self.debit.currency != self.credit.currency:
            raise LedgerError.invalid_input("LEDGER_CURRENCY_MISMATCH")
        if self.debit.amount < 0 or self.credit.amount < 0:
            raise LedgerError.invalid_input("LEDGER_AMOUNT_NEGATIVE")
        if self.debit.amount > 0 and self.credit.amount > 0:
            raise LedgerError.invalid_input("LEDGER_LINE_NOT_ONE_SIDED")
        object.__setattr__(self, "description", description)


@dataclass(frozen=True, slots=True)
class LedgerCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear


@dataclass(frozen=True, slots=True)
class RecognizeHoldingActionCommand(LedgerCommand):
    event_date: LocalDate
    primary_source: LedgerFactReference
    corroborating_sources: tuple[LedgerFactReference, ...]
    facts: SupportedHoldingActionFacts


@dataclass(frozen=True, slots=True)
class CorrectHoldingActionCommand(LedgerCommand):
    event_date: LocalDate
    original_entry_id: LedgerEntryId
    reason: str
    primary_source: LedgerFactReference
    corroborating_sources: tuple[LedgerFactReference, ...]
    replacement: AdministrativeCostCorrectionFacts

    def __post_init__(self) -> None:
        reason = self.reason.strip()
        if not reason or len(reason) > 500:
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True, slots=True)
class PostAdministrativeCostCommand(LedgerCommand):
    bank_transaction_id: LedgerSourceRecordId
    category: AdministrativeCostCategory
    payee: str
    amount: Money
    paid_date: LocalDate
    document_id: LedgerSourceRecordId | None = None

    def __post_init__(self) -> None:
        if not self.payee.strip() or len(self.payee) > 255:
            raise LedgerError.invalid_input("LEDGER_PAYEE_REQUIRED")


@dataclass(frozen=True, slots=True)
class PostBankSuggestionOutcomeCommand(LedgerCommand):
    acceptance_id: LedgerSourceRecordId
    rule: BankSuggestionRule
    amount: Money
    transaction_text: str

    def __post_init__(self) -> None:
        text = self.transaction_text.strip()
        if not text or len(text) > 500:
            raise LedgerError.invalid_input("LEDGER_DESCRIPTION_REQUIRED")
        object.__setattr__(self, "transaction_text", text)


@dataclass(frozen=True, slots=True)
class PostReceivedDividendCommand(LedgerCommand):
    action_id: LedgerSourceRecordId
    paying_company_name: str
    gross_amount: Money

    def __post_init__(self) -> None:
        name = self.paying_company_name.strip()
        if not name or len(name) > 255:
            raise LedgerError.invalid_input("LEDGER_DESCRIPTION_REQUIRED")
        object.__setattr__(self, "paying_company_name", name)


@dataclass(frozen=True, slots=True)
class PostInvestmentPurchaseCommand(LedgerCommand):
    action_id: LedgerSourceRecordId
    investment_name: str
    purchase_amount: Money

    def __post_init__(self) -> None:
        name = self.investment_name.strip()
        if not name or len(name) > 255:
            raise LedgerError.invalid_input("LEDGER_DESCRIPTION_REQUIRED")
        object.__setattr__(self, "investment_name", name)


@dataclass(frozen=True, slots=True)
class PostInvestmentSaleCommand(LedgerCommand):
    action_id: LedgerSourceRecordId
    investment_name: str
    proceeds: Money
    fifo_cost_basis_reduction: Money

    def __post_init__(self) -> None:
        name = self.investment_name.strip()
        if not name or len(name) > 255:
            raise LedgerError.invalid_input("LEDGER_DESCRIPTION_REQUIRED")
        object.__setattr__(self, "investment_name", name)


@dataclass(frozen=True, slots=True)
class PostOwnerDividendDeclaredCommand(LedgerCommand):
    finalization_id: LedgerSourceRecordId
    declared_amount: Money
    declaration_debit_account: str
    dividend_payable_account: str
    accounting_policy_version: str
    ledger_entry_id: LedgerEntryId


@dataclass(frozen=True, slots=True)
class PostOwnerDividendPaymentCommand(LedgerCommand):
    payment_event_id: LedgerSourceRecordId
    payment_amount: Money
    dividend_payable_account: str
    bank_account: str
    accounting_policy_version: str
    ledger_entry_id: LedgerEntryId


@dataclass(frozen=True, slots=True)
class PostShareholderLoanCommand(LedgerCommand):
    action_id: LedgerSourceRecordId
    counterparty_name: str
    direction: ShareholderLoanDirection
    amount: Money

    def __post_init__(self) -> None:
        name = self.counterparty_name.strip()
        if not name or len(name) > 255:
            raise LedgerError.invalid_input("LEDGER_DESCRIPTION_REQUIRED")
        object.__setattr__(self, "counterparty_name", name)


@dataclass(frozen=True, slots=True)
class PostTaxSettlementCommand(LedgerCommand):
    settlement_id: LedgerSourceRecordId
    settlement_kind: TaxSettlementKind
    amount: Money


@dataclass(frozen=True, slots=True)
class ReconstructionEvidence:
    kind: ReconstructionEvidenceKind
    confirmation: ReconstructionEvidenceStatus
    issuer: ReconstructionEvidenceIssuer
    source_record_id: LedgerSourceRecordId
    source_revision: int
    fact_sha256: str
    coverage_from: LocalDate | None = None
    coverage_through: LocalDate | None = None
    gap_code: ReconstructionGapCode | None = None

    def __post_init__(self) -> None:
        digest = self.fact_sha256.strip().lower()
        if (
            self.source_revision < 1
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise LedgerError.invalid_input(
                "LEDGER_RECONSTRUCTION_SOURCE_EVIDENCE_INVALID"
            )
        gap = self.gap_code
        if self.confirmation is ReconstructionEvidenceStatus.CONFIRMED and gap is not None:
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        if self.confirmation is not ReconstructionEvidenceStatus.CONFIRMED and not gap:
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        if (self.coverage_from is None) is not (self.coverage_through is None):
            raise LedgerError.invalid_input("LEDGER_RECONSTRUCTION_COVERAGE_INVALID")
        object.__setattr__(self, "fact_sha256", digest)
        object.__setattr__(self, "gap_code", gap)


@dataclass(frozen=True, slots=True)
class RecordReconstructionAssessmentCommand(LedgerCommand):
    as_of: LocalDate
    evidence: tuple[ReconstructionEvidence, ...]
    economic_fact_entry_ids: tuple[LedgerEntryId, ...]


@dataclass(frozen=True, slots=True)
class OpeningBalanceComponent:
    """A non-lifecycle balance whose accounting class is selected by Python."""

    category: OpeningBalanceCategory
    reference_id: LedgerSourceRecordId
    amount: Money
    primary_source: LedgerFactReference
    corroborating_sources: tuple[LedgerFactReference, ...]

    def __post_init__(self) -> None:
        if self.category in {
            OpeningBalanceCategory.UNREGISTERED_CAPITAL_INCREASE,
            OpeningBalanceCategory.UNREGISTERED_CAPITAL_REDUCTION,
            OpeningBalanceCategory.DIVIDEND_RECEIVABLE,
            OpeningBalanceCategory.DIVIDEND_PAYABLE,
            OpeningBalanceCategory.LONG_TERM_BANK_LOAN_PAYABLE,
            OpeningBalanceCategory.SHORT_TERM_BANK_LOAN_PAYABLE,
            OpeningBalanceCategory.SUBSIDIARY_INVESTMENT,
            OpeningBalanceCategory.ASSOCIATE_INVESTMENT,
            OpeningBalanceCategory.OTHER_LONG_TERM_INVESTMENT,
            OpeningBalanceCategory.CURRENT_LISTED_SHARE_INVESTMENT,
            OpeningBalanceCategory.CURRENT_FUND_INVESTMENT,
        }:
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        _validate_opening_amount_and_sources(
            self.amount, self.primary_source, self.corroborating_sources
        )


def _validate_opening_amount_and_sources(
    amount: Money,
    primary_source: LedgerFactReference,
    corroborating_sources: tuple[LedgerFactReference, ...],
) -> None:
    if amount.currency != "NOK" or amount.amount <= 0 or not corroborating_sources:
        raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
    sources = (primary_source, *corroborating_sources)
    identities = {
        (source.capability, str(source.record_id), source.revision) for source in sources
    }
    if len(identities) != len(sources):
        raise LedgerError.invalid_input("LEDGER_OPENING_SOURCE_OVERLAP")


@dataclass(frozen=True, slots=True)
class OpeningBankLoanComponent:
    loan_reference_id: BankLoanReferenceId
    maturity: BankLoanMaturity
    amount: Money
    primary_source: LedgerFactReference
    corroborating_sources: tuple[LedgerFactReference, ...]

    def __post_init__(self) -> None:
        _validate_opening_amount_and_sources(
            self.amount, self.primary_source, self.corroborating_sources
        )

    @property
    def category(self) -> OpeningBalanceCategory:
        return (
            OpeningBalanceCategory.LONG_TERM_BANK_LOAN_PAYABLE
            if self.maturity is BankLoanMaturity.LONG_TERM
            else OpeningBalanceCategory.SHORT_TERM_BANK_LOAN_PAYABLE
        )

    @property
    def reference_id(self) -> BankLoanReferenceId:
        return self.loan_reference_id


@dataclass(frozen=True, slots=True)
class OpeningInvestmentComponent:
    investment_reference_id: LedgerSourceRecordId
    classification: InvestmentClassification
    amount: Money
    primary_source: LedgerFactReference
    corroborating_sources: tuple[LedgerFactReference, ...]

    def __post_init__(self) -> None:
        _validate_opening_amount_and_sources(
            self.amount, self.primary_source, self.corroborating_sources
        )

    @property
    def category(self) -> OpeningBalanceCategory:
        return {
            InvestmentClassification.SUBSIDIARY: OpeningBalanceCategory.SUBSIDIARY_INVESTMENT,
            InvestmentClassification.ASSOCIATE: OpeningBalanceCategory.ASSOCIATE_INVESTMENT,
            InvestmentClassification.OTHER_LONG_TERM: OpeningBalanceCategory.OTHER_LONG_TERM_INVESTMENT,
            InvestmentClassification.CURRENT_LISTED_SHARE: OpeningBalanceCategory.CURRENT_LISTED_SHARE_INVESTMENT,
            InvestmentClassification.CURRENT_FUND: OpeningBalanceCategory.CURRENT_FUND_INVESTMENT,
        }[self.classification]

    @property
    def reference_id(self) -> LedgerSourceRecordId:
        return self.investment_reference_id


@dataclass(frozen=True, slots=True)
class OpeningCapitalIncreaseComponent:
    capital_increase_reference_id: CapitalIncreaseReferenceId
    phase: CapitalIncreasePhase
    nominal_increase: Money
    share_premium: Money
    primary_source: LedgerFactReference
    corroborating_sources: tuple[LedgerFactReference, ...]

    def __post_init__(self) -> None:
        if self.phase is CapitalIncreasePhase.REGISTERED:
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        if (
            self.nominal_increase.currency != "NOK"
            or self.share_premium.currency != "NOK"
            or self.nominal_increase.amount <= 0
            or self.share_premium.amount < 0
        ):
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        _validate_opening_amount_and_sources(
            Money.nok(self.nominal_increase.amount + self.share_premium.amount),
            self.primary_source,
            self.corroborating_sources,
        )


@dataclass(frozen=True, slots=True)
class OpeningCapitalReductionComponent:
    capital_reduction_reference_id: CapitalReductionReferenceId
    recognition: CapitalReductionRecognition
    nominal_reduction: Money
    primary_source: LedgerFactReference
    corroborating_sources: tuple[LedgerFactReference, ...]

    def __post_init__(self) -> None:
        if self.recognition is not CapitalReductionRecognition.DECIDED_NOT_REGISTERED:
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        _validate_opening_amount_and_sources(
            self.nominal_reduction, self.primary_source, self.corroborating_sources
        )


@dataclass(frozen=True, slots=True)
class OpeningDividendReceivableComponent:
    decision_reference_id: DividendDecisionReferenceId
    amount: Money
    primary_source: LedgerFactReference
    corroborating_sources: tuple[LedgerFactReference, ...]

    def __post_init__(self) -> None:
        _validate_opening_amount_and_sources(
            self.amount, self.primary_source, self.corroborating_sources
        )

    @property
    def category(self) -> OpeningBalanceCategory:
        return OpeningBalanceCategory.DIVIDEND_RECEIVABLE

    @property
    def reference_id(self) -> DividendDecisionReferenceId:
        return self.decision_reference_id


@dataclass(frozen=True, slots=True)
class OpeningDividendPayableComponent:
    decision_reference_id: DividendDecisionReferenceId
    amount: Money
    primary_source: LedgerFactReference
    corroborating_sources: tuple[LedgerFactReference, ...]

    def __post_init__(self) -> None:
        _validate_opening_amount_and_sources(
            self.amount, self.primary_source, self.corroborating_sources
        )

    @property
    def category(self) -> OpeningBalanceCategory:
        return OpeningBalanceCategory.DIVIDEND_PAYABLE

    @property
    def reference_id(self) -> DividendDecisionReferenceId:
        return self.decision_reference_id


type OpeningPositionComponent = (
    OpeningBalanceComponent
    | OpeningBankLoanComponent
    | OpeningInvestmentComponent
    | OpeningCapitalIncreaseComponent
    | OpeningCapitalReductionComponent
    | OpeningDividendReceivableComponent
    | OpeningDividendPayableComponent
)


@dataclass(frozen=True, slots=True)
class CompiledOpeningPositionComponent:
    component_kind: str
    category: OpeningBalanceCategory
    reference_id: str
    lifecycle_phase: str | None
    amount: Money
    account: str
    description: str
    is_debit: bool
    primary_source: LedgerFactReference
    corroborating_sources: tuple[LedgerFactReference, ...]
    nominal_increase: Money | None = None
    share_premium: Money | None = None
    nominal_reduction: Money | None = None


@dataclass(frozen=True, slots=True)
class RebuildCompanyYearOpeningCommand(LedgerCommand):
    """Atomically record one classified and evidenced Jan-1 opening increment."""

    opening_date: LocalDate
    mode: OpeningPositionMode
    opening_basis: LedgerFactReference
    components: tuple[OpeningPositionComponent, ...]

    def __post_init__(self) -> None:
        if self.opening_date.value != date(int(self.income_year), 1, 1):
            raise LedgerError.invalid_input("LEDGER_RECONSTRUCTION_COVERAGE_INVALID")
        if not self.components:
            raise LedgerError.invalid_input("LEDGER_OPENING_BALANCE_INVALID")
        expected_basis = (
            LedgerSourceCapability.ANNUAL_ACCOUNTS_FILING
            if self.mode is OpeningPositionMode.PRIOR_CLOSE_RECONSTRUCTION
            else LedgerSourceCapability.SHAREHOLDER_REGISTER_FILING
        )
        if self.opening_basis.capability is not expected_basis:
            raise LedgerError.precondition_failed("LEDGER_OPENING_EVIDENCE_INVALID")


@dataclass(frozen=True, slots=True)
class ReconstructionAssessment:
    assessment_id: ReconstructionAssessmentId
    company_id: CompanyId
    income_year: IncomeYear
    as_of: LocalDate
    state: ReconstructionState
    gap_codes: tuple[ReconstructionGapCode, ...]
    evidence_digest: str
    ledger_state_digest: str | None
    recorded_at: Timestamp
    replayed: bool
    economic_facts_digest: str | None = None
    economic_fact_count: int | None = None
    source_evidence_digest: str | None = None
    source_evidence_count: int | None = None

    def __post_init__(self) -> None:
        digest = self.economic_facts_digest
        count = self.economic_fact_count
        if (digest is None) is not (count is None) or (
            digest is not None
            and (
                len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                or count is None
                or count < 0
            )
        ):
            raise ValueError("reconstruction economic fact binding is invalid")
        source_digest = self.source_evidence_digest
        source_count = self.source_evidence_count
        if (source_digest is None) is not (source_count is None) or (
            source_digest is not None
            and (
                len(source_digest) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in source_digest
                )
                or source_count != 13
            )
        ):
            raise ValueError("reconstruction source evidence binding is invalid")


@dataclass(frozen=True, slots=True)
class ReconstructionEconomicFactCandidates:
    company_id: CompanyId
    income_year: IncomeYear
    as_of: LocalDate
    entry_ids: tuple[LedgerEntryId, ...]
    facts_digest: str

    def __post_init__(self) -> None:
        digest = self.facts_digest.strip().lower()
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ) or len({entry_id.value for entry_id in self.entry_ids}) != len(
            self.entry_ids
        ):
            raise ValueError("reconstruction economic facts are invalid")
        object.__setattr__(self, "facts_digest", digest)


@dataclass(frozen=True, slots=True)
class ReconstructionEconomicFactSource:
    role: LedgerFactRole
    capability: LedgerSourceCapability
    record_id: LedgerSourceRecordId
    revision: int | None
    fact_sha256: str | None

    def __post_init__(self) -> None:
        if (self.revision is None) is not (self.fact_sha256 is None):
            raise ValueError("economic fact source binding is invalid")
        if self.revision is not None and (
            self.revision < 1
            or self.fact_sha256 is None
            or len(self.fact_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.fact_sha256
            )
        ):
            raise ValueError("economic fact source binding is invalid")


@dataclass(frozen=True, slots=True)
class ReconstructionEconomicFactCorrection:
    original_entry_id: LedgerEntryId
    reversal_entry_id: LedgerEntryId
    replacement_entry_id: LedgerEntryId
    reason: str
    corrected_by: ActorId
    corrected_at: Timestamp


@dataclass(frozen=True, slots=True)
class ReconstructionEconomicFact:
    entry_id: LedgerEntryId
    event_date: LocalDate
    entry_kind: LedgerEntryKind
    memo: str
    lines: tuple[LedgerLine, ...]
    correlation_id: CorrelationId
    rule_version: str | None
    sources: tuple[ReconstructionEconomicFactSource, ...]
    corrections: tuple[ReconstructionEconomicFactCorrection, ...]
    posted_by: ActorId
    posted_at: Timestamp


@dataclass(frozen=True, slots=True)
class ReconstructionEconomicFactSnapshot:
    assessment_id: ReconstructionAssessmentId
    company_id: CompanyId
    income_year: IncomeYear
    as_of: LocalDate
    facts_digest: str
    facts: tuple[ReconstructionEconomicFact, ...]

    def __post_init__(self) -> None:
        if len(self.facts_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.facts_digest
        ):
            raise ValueError("reconstruction economic fact snapshot is invalid")


@dataclass(frozen=True, slots=True)
class CompanyYearCloseOutputReference:
    kind: CompanyYearCloseOutputKind
    source_record_id: LedgerSourceRecordId
    revision: int
    fact_sha256: str
    economic_facts_digest: str

    def __post_init__(self) -> None:
        digest = self.fact_sha256.strip().lower()
        economic_facts_digest = self.economic_facts_digest.strip().lower()
        if (
            self.revision < 1
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or len(economic_facts_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in economic_facts_digest
            )
        ):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        object.__setattr__(self, "fact_sha256", digest)
        object.__setattr__(self, "economic_facts_digest", economic_facts_digest)


@dataclass(frozen=True, slots=True)
class CompanyYearCloseEvidence:
    kind: CompanyYearCloseEvidenceKind
    issuer: LedgerSourceCapability
    source_record_id: LedgerSourceRecordId
    revision: int
    fact_sha256: str
    ledger_state_digest: str
    coverage_through: LocalDate
    confirmation: ReconstructionEvidenceStatus
    gap_code: CompanyYearCloseGapCode | None = None
    outputs: tuple[CompanyYearCloseOutputReference, ...] = ()

    def __post_init__(self) -> None:
        digest = self.fact_sha256.strip().lower()
        state_digest = self.ledger_state_digest.strip().lower()
        if (
            self.revision < 1
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or len(state_digest) != 64
            or any(
                character not in "0123456789abcdef" for character in state_digest
            )
            or len(self.outputs) > len(CompanyYearCloseOutputKind)
        ):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        if (
            self.confirmation is ReconstructionEvidenceStatus.CONFIRMED
            and self.gap_code is not None
        ) or (
            self.confirmation is not ReconstructionEvidenceStatus.CONFIRMED
            and self.gap_code is None
        ):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        object.__setattr__(self, "fact_sha256", digest)
        object.__setattr__(self, "ledger_state_digest", state_digest)


@dataclass(frozen=True, slots=True)
class PostManualJournalCommand(LedgerCommand):
    memo: str
    lines: tuple[LedgerLine, ...]
    warning_accepted: bool

    def __post_init__(self) -> None:
        if not self.memo.strip() or len(self.memo) > 500:
            raise LedgerError.invalid_input("LEDGER_MEMO_REQUIRED")
        if not 2 <= len(self.lines) <= 100:
            raise LedgerError.invalid_input("LEDGER_ENTRY_REQUIRES_TWO_LINES")


@dataclass(frozen=True, slots=True)
class LockPeriodCommand(LedgerCommand):
    reason: str

    def __post_init__(self) -> None:
        if not self.reason.strip() or len(self.reason) > 500:
            raise LedgerError.invalid_input("LEDGER_LOCK_REASON_REQUIRED")


@dataclass(frozen=True, slots=True)
class CloseCompanyYearCommand(LedgerCommand):
    period_end: LocalDate
    reason: str
    reconstruction_assessment_id: ReconstructionAssessmentId
    reconstruction_evidence_digest: str
    evidence: tuple[CompanyYearCloseEvidence, ...]

    def __post_init__(self) -> None:
        reason = self.reason.strip()
        digest = self.reconstruction_evidence_digest.strip().lower()
        if not reason or len(reason) > 500:
            raise LedgerError.invalid_input("LEDGER_LOCK_REASON_REQUIRED")
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        if len(self.evidence) > 100:
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "reconstruction_evidence_digest", digest)


@dataclass(frozen=True, slots=True)
class PostedLedgerEntry:
    entry_id: LedgerEntryId
    company_id: CompanyId
    income_year: IncomeYear
    entry_kind: LedgerEntryKind
    posted_at: Timestamp
    replayed: bool


@dataclass(frozen=True, slots=True)
class CorrectedLedgerEntries:
    reversal_entry_id: LedgerEntryId
    replacement_entry_id: LedgerEntryId
    company_id: CompanyId
    income_year: IncomeYear
    corrected_at: Timestamp
    replayed: bool


@dataclass(frozen=True, slots=True)
class PeriodLock:
    period_lock_id: PeriodLockId
    company_id: CompanyId
    income_year: IncomeYear
    reason: str
    locked_by: ActorId
    locked_at: Timestamp
    replayed: bool


@dataclass(frozen=True, slots=True)
class CompanyYearCloseAssessment:
    assessment_id: CompanyYearCloseAssessmentId
    close_lock_id: CompanyYearCloseLockId | None
    reconstruction_assessment_id: ReconstructionAssessmentId
    company_id: CompanyId
    income_year: IncomeYear
    period_end: LocalDate
    state: CompanyYearCloseState
    gap_codes: tuple[CompanyYearCloseGapCode, ...]
    evidence_digest: str
    ledger_state_digest: str
    recorded_at: Timestamp
    is_current: bool
    replayed: bool


@dataclass(frozen=True, slots=True)
class LedgerEntryView:
    entry_id: LedgerEntryId
    company_id: CompanyId
    income_year: IncomeYear
    entry_kind: LedgerEntryKind
    source_capability: LedgerSourceCapability | None
    source_record_id: LedgerSourceRecordId | None
    created_at: Timestamp | None
    memo: str
    lines: tuple[LedgerLine, ...]
    risk_flags: tuple[LedgerRiskFlag, ...]
    warning_accepted_by: ActorId | None
    warning_accepted_at: Timestamp | None
    posted_by: ActorId
    posted_at: Timestamp

    def __post_init__(self) -> None:
        archive_facts = (
            self.source_capability,
            self.source_record_id,
            self.created_at,
        )
        if any(value is None for value in archive_facts) and not all(
            value is None for value in archive_facts
        ):
            raise ValueError("ledger source identity must be complete")


@dataclass(frozen=True, slots=True)
class LedgerPage:
    next_cursor: LedgerCursor | None
    has_more: bool


@dataclass(frozen=True, slots=True)
class LedgerEntryPage:
    items: tuple[LedgerEntryView, ...]
    page: LedgerPage


@dataclass(frozen=True, slots=True)
class PeriodLockPage:
    items: tuple[PeriodLock, ...]
    page: LedgerPage


class LedgerError(DomainError):
    @staticmethod
    def _declared(code: LedgerErrorCode | str) -> str:
        return LedgerErrorCode(code).value

    @classmethod
    def invalid_input(
        cls, code: LedgerErrorCode | str, message: str = ""
    ) -> LedgerError:
        return cls(
            code=cls._declared(code),
            category=ErrorCategory.INVALID_INPUT,
            message=message,
        )

    @classmethod
    def conflict(cls, code: LedgerErrorCode | str, message: str = "") -> LedgerError:
        return cls(
            code=cls._declared(code),
            category=ErrorCategory.CONFLICT,
            message=message,
        )

    @classmethod
    def forbidden(
        cls, code: LedgerErrorCode | str = LedgerErrorCode.FORBIDDEN
    ) -> LedgerError:
        return cls(code=cls._declared(code), category=ErrorCategory.FORBIDDEN)

    @classmethod
    def not_found(
        cls, code: LedgerErrorCode | str = LedgerErrorCode.NOT_FOUND
    ) -> LedgerError:
        return cls(code=cls._declared(code), category=ErrorCategory.NOT_FOUND)

    @classmethod
    def precondition_failed(
        cls, code: LedgerErrorCode | str, message: str = ""
    ) -> LedgerError:
        return cls(
            code=cls._declared(code),
            category=ErrorCategory.PRECONDITION_FAILED,
            message=message,
        )

    @classmethod
    def unavailable(cls) -> LedgerError:
        return cls(
            code=LedgerErrorCode.DEPENDENCY_UNAVAILABLE.value,
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
        )


class LedgerPersistence(Protocol):
    async def get_company_year_close_assessment(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        correlation_id: CorrelationId,
    ) -> CompanyYearCloseAssessment: ...

    async def get_company_year_close_replay(
        self,
        command: CloseCompanyYearCommand,
        *,
        evidence: tuple[CompanyYearCloseEvidence, ...],
    ) -> CompanyYearCloseAssessment | None: ...

    async def record_company_year_close(
        self,
        command: CloseCompanyYearCommand,
        *,
        evidence: tuple[CompanyYearCloseEvidence, ...],
        state: CompanyYearCloseState,
        gap_codes: tuple[CompanyYearCloseGapCode, ...],
    ) -> CompanyYearCloseAssessment: ...

    async def record_bank_loan_disbursement(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        loan_reference_id: BankLoanReferenceId,
        principal: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry: ...

    async def record_bank_loan_payment(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        loan_reference_id: BankLoanReferenceId,
        principal: Money,
        interest: Money,
        fee: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry: ...

    async def record_cash_capital_increase_subscription(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        capital_increase_reference_id: CapitalIncreaseReferenceId,
        nominal_increase: Money,
        share_premium: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry: ...

    async def record_cash_capital_increase_restricted_payment(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        capital_increase_reference_id: CapitalIncreaseReferenceId,
        nominal_increase: Money,
        share_premium: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry: ...

    async def record_cash_capital_increase_registration(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        capital_increase_reference_id: CapitalIncreaseReferenceId,
        nominal_increase: Money,
        share_premium: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry: ...

    async def record_loss_coverage_capital_reduction_decision(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        capital_reduction_reference_id: CapitalReductionReferenceId,
        nominal_reduction: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry: ...

    async def record_loss_coverage_capital_reduction_registration(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        capital_reduction_reference_id: CapitalReductionReferenceId,
        nominal_reduction: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry: ...

    async def record_loss_coverage_capital_reduction_direct_registration(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        capital_reduction_reference_id: CapitalReductionReferenceId,
        nominal_reduction: Money,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry: ...

    async def record_received_dividend_decision(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry: ...

    async def record_received_dividend_payment(
        self,
        command: RecognizeHoldingActionCommand,
        *,
        decision_reference: LedgerEntryId | DividendDecisionReferenceId,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> PostedLedgerEntry: ...

    async def correct_entry(
        self,
        command: CorrectHoldingActionCommand,
        *,
        entry_kind: LedgerEntryKind,
        memo: str,
        lines: tuple[LedgerLine, ...],
    ) -> CorrectedLedgerEntries: ...

    async def post_entry(
        self,
        command: LedgerCommand,
        *,
        entry_kind: LedgerEntryKind,
        memo: str,
        lines: tuple[LedgerLine, ...],
        risk_flags: tuple[LedgerRiskFlag, ...],
        warning_accepted: bool,
        source_capability: LedgerSourceCapability,
        source_record_id: LedgerSourceRecordId,
        requested_entry_id: LedgerEntryId | None = None,
    ) -> PostedLedgerEntry: ...

    async def lock_period(self, command: LockPeriodCommand) -> PeriodLock: ...

    async def record_reconstruction_assessment(
        self,
        command: RecordReconstructionAssessmentCommand,
        *,
        evidence: tuple[ReconstructionEvidence, ...],
        state: ReconstructionState,
        gap_codes: tuple[ReconstructionGapCode, ...],
    ) -> ReconstructionAssessment: ...

    async def get_reconstruction_economic_fact_candidates(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        as_of: LocalDate,
        correlation_id: CorrelationId,
    ) -> ReconstructionEconomicFactCandidates: ...

    async def get_reconstruction_economic_facts(
        self,
        *,
        actor_id: ActorId,
        assessment_id: ReconstructionAssessmentId,
        correlation_id: CorrelationId,
    ) -> ReconstructionEconomicFactSnapshot: ...

    async def rebuild_company_year_opening(
        self,
        command: RebuildCompanyYearOpeningCommand,
        *,
        components: tuple[CompiledOpeningPositionComponent, ...],
        lines: tuple[LedgerLine, ...],
        entry_sources: tuple[LedgerFactReference, ...],
    ) -> PostedLedgerEntry: ...

    async def get_reconstruction_assessment(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        correlation_id: CorrelationId,
    ) -> ReconstructionAssessment: ...

    async def list_entries(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> LedgerEntryPage: ...

    async def list_period_locks(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> PeriodLockPage: ...


LedgerAdapter = TypeVar("LedgerAdapter", bound=type[object])


def ledger_persistence_adapter(
    contract: type[object],
) -> Callable[[LedgerAdapter], LedgerAdapter]:
    """Declare an infrastructure binding without registering global state."""

    def declare(adapter: LedgerAdapter) -> LedgerAdapter:
        _ = contract
        return adapter

    return declare


class LedgerCommands(Protocol):
    async def close_company_year(
        self, command: CloseCompanyYearCommand
    ) -> CompanyYearCloseAssessment: ...

    async def correct_holding_action(
        self, command: CorrectHoldingActionCommand
    ) -> CorrectedLedgerEntries: ...

    async def recognize_holding_action(
        self, command: RecognizeHoldingActionCommand
    ) -> PostedLedgerEntry: ...

    async def post_administrative_cost(
        self, command: PostAdministrativeCostCommand
    ) -> PostedLedgerEntry: ...

    async def post_bank_suggestion_outcome(
        self, command: PostBankSuggestionOutcomeCommand
    ) -> PostedLedgerEntry: ...

    async def post_received_dividend(
        self, command: PostReceivedDividendCommand
    ) -> PostedLedgerEntry: ...

    async def post_investment_purchase(
        self, command: PostInvestmentPurchaseCommand
    ) -> PostedLedgerEntry: ...

    async def post_investment_sale(
        self, command: PostInvestmentSaleCommand
    ) -> PostedLedgerEntry: ...

    async def post_owner_dividend_declared(
        self, command: PostOwnerDividendDeclaredCommand
    ) -> PostedLedgerEntry: ...

    async def post_owner_dividend_payment(
        self, command: PostOwnerDividendPaymentCommand
    ) -> PostedLedgerEntry: ...

    async def post_shareholder_loan(
        self, command: PostShareholderLoanCommand
    ) -> PostedLedgerEntry: ...

    async def post_tax_settlement(
        self, command: PostTaxSettlementCommand
    ) -> PostedLedgerEntry: ...

    async def record_reconstruction_assessment(
        self, command: RecordReconstructionAssessmentCommand
    ) -> ReconstructionAssessment: ...

    async def rebuild_company_year_opening(
        self, command: RebuildCompanyYearOpeningCommand
    ) -> PostedLedgerEntry: ...

    async def post_manual_journal(
        self, command: PostManualJournalCommand
    ) -> PostedLedgerEntry: ...

    async def lock_period(self, command: LockPeriodCommand) -> PeriodLock: ...


class LedgerQueries(Protocol):
    async def get_reconstruction_economic_facts(
        self,
        *,
        actor_id: ActorId,
        assessment_id: ReconstructionAssessmentId,
        correlation_id: CorrelationId,
    ) -> ReconstructionEconomicFactSnapshot: ...

    async def get_reconstruction_economic_fact_candidates(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        as_of: LocalDate,
        correlation_id: CorrelationId,
    ) -> ReconstructionEconomicFactCandidates: ...

    async def get_company_year_close_assessment(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        correlation_id: CorrelationId,
    ) -> CompanyYearCloseAssessment: ...

    async def get_reconstruction_assessment(
        self,
        *,
        actor_id: ActorId,
        company_id: CompanyId,
        income_year: IncomeYear,
        correlation_id: CorrelationId,
    ) -> ReconstructionAssessment: ...

    async def list_entries(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> LedgerEntryPage: ...

    async def list_period_locks(
        self,
        *,
        actor_id: ActorId,
        company_ids: tuple[CompanyId, ...],
        correlation_id: CorrelationId,
        cursor: LedgerCursor | None,
        limit: int,
    ) -> PeriodLockPage: ...


__all__ = [
    "AdministrativeCostBlock",
    "AdministrativeCostCategory",
    "AdministrativeCostCorrectionFacts",
    "AdministrativeCostCorrectionScope",
    "ApprovedLossCoverageCapitalReductionFacts",
    "ApprovedOneSidedIntercompanyLoanFundingFacts",
    "ApprovedOwnerLoanFundingFacts",
    "BankInterestIncomeFacts",
    "BankLoanEvent",
    "BankLoanMaturity",
    "BankLoanReferenceId",
    "BankSuggestionRule",
    "CapitalIncreasePhase",
    "CapitalIncreaseReferenceId",
    "CapitalReductionRecognition",
    "CapitalReductionReferenceId",
    "CashCapitalIncreaseFacts",
    "CloseCompanyYearCommand",
    "CompanyTaxAccrualFacts",
    "CompanyYearCloseAssessment",
    "CompanyYearCloseAssessmentId",
    "CompanyYearCloseEvidence",
    "CompanyYearCloseEvidenceKind",
    "CompanyYearCloseGapCode",
    "CompanyYearCloseLockId",
    "CompanyYearCloseOutputKind",
    "CompanyYearCloseOutputReference",
    "CompanyYearCloseState",
    "CompiledOpeningPositionComponent",
    "CorrectHoldingActionCommand",
    "CorrectedLedgerEntries",
    "DividendDecisionReferenceId",
    "GroupContributionFacts",
    "GroupContributionPerspective",
    "GroupContributionRelationship",
    "IntercompanyLoanPerspective",
    "IntercompanyLoanRelationship",
    "InvestmentClassification",
    "InvestmentDividendFacts",
    "InvestmentDividendPhase",
    "LedgerCommands",
    "LedgerCursor",
    "LedgerEntryId",
    "LedgerEntryKind",
    "LedgerEntryPage",
    "LedgerEntryView",
    "LedgerError",
    "LedgerErrorCode",
    "LedgerFactReference",
    "LedgerFactRole",
    "LedgerLine",
    "LedgerPage",
    "LedgerPersistence",
    "LedgerQueries",
    "LedgerRiskCode",
    "LedgerRiskFlag",
    "LedgerSourceCapability",
    "LedgerSourceRecordId",
    "LockPeriodCommand",
    "OpeningBalanceCategory",
    "OpeningBalanceComponent",
    "OpeningBankLoanComponent",
    "OpeningCapitalIncreaseComponent",
    "OpeningCapitalReductionComponent",
    "OpeningDividendPayableComponent",
    "OpeningDividendReceivableComponent",
    "OpeningInvestmentComponent",
    "OpeningPositionComponent",
    "OpeningPositionMode",
    "OrdinaryBankLoanFacts",
    "PeriodLock",
    "PeriodLockId",
    "PeriodLockPage",
    "PostAdministrativeCostCommand",
    "PostBankSuggestionOutcomeCommand",
    "PostReceivedDividendCommand",
    "PostInvestmentPurchaseCommand",
    "PostInvestmentSaleCommand",
    "PostManualJournalCommand",
    "PostOwnerDividendDeclaredCommand",
    "PostOwnerDividendPaymentCommand",
    "PostShareholderLoanCommand",
    "PostTaxSettlementCommand",
    "PostedLedgerEntry",
    "RebuildCompanyYearOpeningCommand",
    "RecognizeHoldingActionCommand",
    "ReconstructionAssessment",
    "ReconstructionAssessmentId",
    "ReconstructionEconomicFactCandidates",
    "ReconstructionEconomicFact",
    "ReconstructionEconomicFactCorrection",
    "ReconstructionEconomicFactSnapshot",
    "ReconstructionEconomicFactSource",
    "ReconstructionEvidence",
    "ReconstructionEvidenceIssuer",
    "ReconstructionEvidenceKind",
    "ReconstructionEvidenceStatus",
    "ReconstructionGapCode",
    "ReconstructionState",
    "RecordReconstructionAssessmentCommand",
    "ShareholderLoanDirection",
    "SupportedHoldingActionFacts",
    "TaxSettlementKind",
    "ledger_persistence_adapter",
]
