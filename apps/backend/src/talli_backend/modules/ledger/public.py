"""Stable public contract for Talli's narrow-ledger capability."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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


class LedgerSourceCapability(StrEnum):
    LEDGER = "LEDGER"
    BANKING = "BANKING"
    INVESTMENTS = "INVESTMENTS"
    CORPORATE_GOVERNANCE = "CORPORATE_GOVERNANCE"
    SHAREHOLDER_REGISTER_FILING = "SHAREHOLDER_REGISTER_FILING"
    COMPANY_TAX_FILING = "COMPANY_TAX_FILING"


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


class BankLoanEvent(StrEnum):
    DISBURSEMENT = "DISBURSEMENT"
    PAYMENT = "PAYMENT"


class CapitalIncreasePhase(StrEnum):
    BINDING_SUBSCRIPTION = "BINDING_SUBSCRIPTION"
    RESTRICTED_PAYMENT = "RESTRICTED_PAYMENT"
    REGISTERED = "REGISTERED"


class CapitalReductionRecognition(StrEnum):
    DECIDED_NOT_REGISTERED = "DECIDED_NOT_REGISTERED"
    FIRST_RECOGNIZED_AFTER_REGISTRATION = "FIRST_RECOGNIZED_AFTER_REGISTRATION"


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
class CompanyTaxAccrualFacts:
    current_tax: Money
    deferred_tax_increase: Money


@dataclass(frozen=True, slots=True)
class OrdinaryBankLoanFacts:
    event: BankLoanEvent
    principal: Money
    interest: Money
    fee: Money


@dataclass(frozen=True, slots=True)
class CashCapitalIncreaseFacts:
    phase: CapitalIncreasePhase
    nominal_increase: Money
    share_premium: Money


@dataclass(frozen=True, slots=True)
class ApprovedLossCoverageCapitalReductionFacts:
    recognition: CapitalReductionRecognition
    nominal_reduction: Money


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
    BankInterestIncomeFacts
    | CashCapitalIncreaseFacts
    | CompanyTaxAccrualFacts
    | GroupContributionFacts
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


class LedgerRiskCode(StrEnum):
    MANUAL_JOURNAL_SENSITIVE_ACCOUNT = "MANUAL_JOURNAL_SENSITIVE_ACCOUNT"


class LedgerErrorCode(StrEnum):
    ACCOUNT_INVALID = "LEDGER_ACCOUNT_INVALID"
    ADMINISTRATIVE_COST_NOT_POSITIVE = "LEDGER_ADMINISTRATIVE_COST_NOT_POSITIVE"
    AMOUNT_NEGATIVE = "LEDGER_AMOUNT_NEGATIVE"
    COMPANY_SCOPE_INVALID = "LEDGER_COMPANY_SCOPE_INVALID"
    COMPANY_YEAR_NOT_ADMITTED = "LEDGER_COMPANY_YEAR_NOT_ADMITTED"
    CURRENCY_MISMATCH = "LEDGER_CURRENCY_MISMATCH"
    DEPENDENCY_UNAVAILABLE = "LEDGER_DEPENDENCY_UNAVAILABLE"
    DESCRIPTION_REQUIRED = "LEDGER_DESCRIPTION_REQUIRED"
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
    OPENING_BALANCE_NEGATIVE = "LEDGER_OPENING_BALANCE_NEGATIVE"
    OWNER_DIVIDEND_ACCOUNTING_POLICY_NOT_APPROVED = (
        "LEDGER_OWNER_DIVIDEND_ACCOUNTING_POLICY_NOT_APPROVED"
    )
    PAGE_LIMIT_INVALID = "LEDGER_PAGE_LIMIT_INVALID"
    PAYEE_REQUIRED = "LEDGER_PAYEE_REQUIRED"
    PERIOD_LOCKED = "LEDGER_PERIOD_LOCKED"
    WARNING_ACCEPTANCE_REQUIRED = "LEDGER_WARNING_ACCEPTANCE_REQUIRED"
    RECONSTRUCTION_EVIDENCE_INCOMPLETE = "LEDGER_RECONSTRUCTION_EVIDENCE_INCOMPLETE"
    RECONSTRUCTION_EVIDENCE_DUPLICATE = "LEDGER_RECONSTRUCTION_EVIDENCE_DUPLICATE"
    RECONSTRUCTION_COVERAGE_INVALID = "LEDGER_RECONSTRUCTION_COVERAGE_INVALID"
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
class PostOpeningBalanceCommand(LedgerCommand):
    bank_balance: Money
    share_capital_snapshot: Money
    opening_snapshot_id: LedgerSourceRecordId | None = None


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
class PostInvestmentDividendCommand(LedgerCommand):
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
    fact_sha256: str
    coverage_from: LocalDate | None = None
    coverage_through: LocalDate | None = None
    gap_code: ReconstructionGapCode | None = None

    def __post_init__(self) -> None:
        digest = self.fact_sha256.strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise LedgerError.invalid_input("LEDGER_INVALID_INPUT")
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


@dataclass(frozen=True, slots=True)
class ReconstructionAssessment:
    assessment_id: ReconstructionAssessmentId
    company_id: CompanyId
    income_year: IncomeYear
    as_of: LocalDate
    state: ReconstructionState
    gap_codes: tuple[ReconstructionGapCode, ...]
    evidence_digest: str
    recorded_at: Timestamp
    replayed: bool


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
class PostedLedgerEntry:
    entry_id: LedgerEntryId
    company_id: CompanyId
    income_year: IncomeYear
    entry_kind: LedgerEntryKind
    posted_at: Timestamp
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
    async def recognize_holding_action(
        self, command: RecognizeHoldingActionCommand
    ) -> PostedLedgerEntry: ...

    async def post_opening_balance(
        self, command: PostOpeningBalanceCommand
    ) -> PostedLedgerEntry: ...

    async def post_administrative_cost(
        self, command: PostAdministrativeCostCommand
    ) -> PostedLedgerEntry: ...

    async def post_bank_suggestion_outcome(
        self, command: PostBankSuggestionOutcomeCommand
    ) -> PostedLedgerEntry: ...

    async def post_investment_dividend(
        self, command: PostInvestmentDividendCommand
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

    async def post_manual_journal(
        self, command: PostManualJournalCommand
    ) -> PostedLedgerEntry: ...

    async def lock_period(self, command: LockPeriodCommand) -> PeriodLock: ...


class LedgerQueries(Protocol):
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
    "AdministrativeCostCategory",
    "BankInterestIncomeFacts",
    "BankLoanEvent",
    "BankSuggestionRule",
    "CashCapitalIncreaseFacts",
    "CapitalIncreasePhase",
    "CapitalReductionRecognition",
    "CompanyTaxAccrualFacts",
    "GroupContributionFacts",
    "GroupContributionPerspective",
    "GroupContributionRelationship",
    "LedgerCommands",
    "LedgerCursor",
    "LedgerEntryId",
    "LedgerEntryKind",
    "LedgerEntryPage",
    "LedgerEntryView",
    "LedgerError",
    "LedgerErrorCode",
    "LedgerFactReference",
    "LedgerLine",
    "LedgerPersistence",
    "LedgerQueries",
    "LedgerRiskCode",
    "LedgerRiskFlag",
    "LedgerSourceCapability",
    "LedgerSourceRecordId",
    "LedgerPage",
    "LockPeriodCommand",
    "ApprovedLossCoverageCapitalReductionFacts",
    "OrdinaryBankLoanFacts",
    "PeriodLock",
    "PeriodLockId",
    "PeriodLockPage",
    "PostAdministrativeCostCommand",
    "PostBankSuggestionOutcomeCommand",
    "RecordReconstructionAssessmentCommand",
    "RecognizeHoldingActionCommand",
    "ReconstructionAssessment",
    "ReconstructionAssessmentId",
    "ReconstructionEvidence",
    "ReconstructionEvidenceKind",
    "ReconstructionEvidenceIssuer",
    "ReconstructionEvidenceStatus",
    "ReconstructionGapCode",
    "ReconstructionState",
    "PostInvestmentDividendCommand",
    "PostInvestmentPurchaseCommand",
    "PostInvestmentSaleCommand",
    "PostOwnerDividendDeclaredCommand",
    "PostOwnerDividendPaymentCommand",
    "PostShareholderLoanCommand",
    "PostTaxSettlementCommand",
    "ShareholderLoanDirection",
    "TaxSettlementKind",
    "SupportedHoldingActionFacts",
    "PostedLedgerEntry",
    "PostManualJournalCommand",
    "PostOpeningBalanceCommand",
    "ledger_persistence_adapter",
]
