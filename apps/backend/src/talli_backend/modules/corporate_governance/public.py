"""Stable public contract for corporate decisions and owner distributions."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, time
from enum import StrEnum
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
)


@dataclass(frozen=True, slots=True)
class _UuidReference:
    value: str

    def __post_init__(self) -> None:
        try:
            canonical = str(UUID(self.value))
        except (ValueError, AttributeError, TypeError):
            raise ValueError("reference must be a UUID") from None
        object.__setattr__(self, "value", canonical)

    def __str__(self) -> str:
        return self.value


class CorporateDecisionId(_UuidReference):
    pass


class CorporateDocumentSetId(_UuidReference):
    pass


class CorporateArtifactId(_UuidReference):
    pass


class CorporateEventId(_UuidReference):
    pass


class CorporateFinalizationId(_UuidReference):
    pass


class CorporateSourceReference(_UuidReference):
    pass


class AccountingEntryReference(_UuidReference):
    pass


class BankTransactionReference(_UuidReference):
    pass


class DocumentReference(_UuidReference):
    pass


class BoardTreatmentMethod(StrEnum):
    PHYSICAL = "physical"
    VIDEO = "video"
    WRITTEN = "written"


class MeetingForm(StrEnum):
    PHYSICAL = "physical"
    VIDEO = "video"


class BoardRole(StrEnum):
    CHAIR = "chair"
    MEMBER = "member"


class ShareholderVote(StrEnum):
    FOR = "for"
    AGAINST = "against"
    ABSTAIN = "abstain"


class CorporateArtifactKind(StrEnum):
    DIVIDEND_BOARD_PROPOSAL = "dividend_board_proposal"
    DIVIDEND_GENERAL_MEETING_MINUTES = "dividend_general_meeting_minutes"
    ANNUAL_BOARD_MINUTES = "annual_board_minutes"
    ANNUAL_GENERAL_MEETING_MINUTES = "annual_general_meeting_minutes"


class CorporateDecisionKind(StrEnum):
    OWNER_DIVIDEND = "owner_dividend"
    ANNUAL_CLOSE = "annual_close"


class CorporateArtifactVariant(StrEnum):
    UNSIGNED = "unsigned"
    SIGNED_OWNER_ATTESTED = "signed_owner_attested"


class OwnerDividendState(StrEnum):
    PROPOSED = "proposed"
    DOCUMENTS_REGISTERED = "documents_registered"
    FACTS_APPROVED = "facts_approved"
    SIGNING_REQUESTED = "signing_requested"
    SIGNED_OWNER_ATTESTED = "signed_owner_attested"
    FINALIZED = "finalized"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class AnnualCloseEventKind(StrEnum):
    SIGNING_REQUESTED = "signing_requested"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class OwnerDividendEventKind(StrEnum):
    SIGNING_REQUESTED = "signing_requested"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ShareholderLoanDirection(StrEnum):
    SHAREHOLDER_TO_COMPANY = "shareholder_to_company"
    COMPANY_TO_CORPORATE_SHAREHOLDER = "company_to_corporate_shareholder"
    COMPANY_TO_PERSONAL_SHAREHOLDER = "company_to_personal_shareholder"


class ShareholderLoanDocumentStatus(StrEnum):
    ATTACHED = "attached"
    MISSING_ACCEPTED_WARNING = "missing_accepted_warning"
    NOT_REQUIRED = "not_required"


class CorporateGovernanceErrorCode(StrEnum):
    INVALID_INPUT = "corporate_documents_invalid_persisted_facts"
    INVALID_MEETING_FACTS = "corporate_documents_invalid_meeting_facts"
    LATEST_ANNUAL_ACCOUNTS_REQUIRED = "corporate_documents_latest_annual_accounts_required"
    REVIEWED_FACTS_CHANGED = "corporate_documents_reviewed_facts_changed"
    SHAREHOLDER_FACTS_MISMATCH = "corporate_documents_shareholder_facts_mismatch"
    UNSUPPORTED_DIVIDEND_BASIS = "corporate_documents_unsupported_dividend_basis"
    INCOMPLETE_BOARD = "corporate_documents_incomplete_board"
    INCOMPLETE_SHARE_REPRESENTATION = "corporate_documents_incomplete_share_representation"
    NON_UNANIMOUS = "corporate_documents_non_unanimous"
    ZERO_ALLOCATION = "corporate_documents_zero_allocation"
    ALLOCATION_MISMATCH = "corporate_documents_allocation_mismatch"
    EQUITY_OR_LIQUIDITY_FAILED = "corporate_documents_equity_or_liquidity_failed"
    ANNUAL_RESULT_MISMATCH = "corporate_documents_annual_result_mismatch"
    FORBIDDEN = "corporate_governance_forbidden"
    NOT_FOUND = "corporate_governance_not_found"
    CONFLICT = "corporate_documents_idempotency_conflict"
    FINALIZED_DECLARATION_REQUIRED = "corporate_documents_finalized_declaration_required"
    PAYMENT_EXCEEDS_PAYABLE = "corporate_documents_payment_exceeds_payable"
    BANK_TRANSACTION_ALREADY_MATCHED = "corporate_documents_bank_transaction_already_matched"
    ACCOUNTING_POLICY_NOT_APPROVED = (
        "corporate_documents_accounting_policy_disabled"
    )
    MISSING_SIGNED_ARTIFACTS = "corporate_documents_missing_signed_artifacts"
    PERSONAL_SHAREHOLDER_LOAN_BLOCKED = "personal_shareholder_loan_blocked"
    RELATED_PARTY_SECURITY_BLOCKED = "related_party_security_blocked"
    DEPENDENCY_UNAVAILABLE = "corporate_governance_dependency_unavailable"


class CorporateGovernanceError(DomainError):
    @classmethod
    def invalid(
        cls,
        code: CorporateGovernanceErrorCode,
        message: str,
    ) -> CorporateGovernanceError:
        return cls(code=code, category=ErrorCategory.INVALID_INPUT, message=message)

    @classmethod
    def forbidden(cls) -> CorporateGovernanceError:
        return cls(
            code=CorporateGovernanceErrorCode.FORBIDDEN,
            category=ErrorCategory.FORBIDDEN,
            message="Corporate-governance access is not allowed.",
        )

    @classmethod
    def not_found(cls) -> CorporateGovernanceError:
        return cls(
            code=CorporateGovernanceErrorCode.NOT_FOUND,
            category=ErrorCategory.NOT_FOUND,
            message="Corporate decision was not found.",
        )

    @classmethod
    def conflict(cls) -> CorporateGovernanceError:
        return cls(
            code=CorporateGovernanceErrorCode.CONFLICT,
            category=ErrorCategory.CONFLICT,
            message="Corporate decision conflicts with an existing request.",
        )

    @classmethod
    def precondition(
        cls,
        code: CorporateGovernanceErrorCode,
        message: str,
    ) -> CorporateGovernanceError:
        return cls(code=code, category=ErrorCategory.PRECONDITION_FAILED, message=message)

    @classmethod
    def unavailable(cls) -> CorporateGovernanceError:
        return cls(
            code=CorporateGovernanceErrorCode.DEPENDENCY_UNAVAILABLE,
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
            message="Corporate-governance persistence is unavailable.",
        )


@dataclass(frozen=True, slots=True)
class PersistedCompanyFacts:
    company_id: CompanyId
    organization_number: str
    legal_name: str


@dataclass(frozen=True, slots=True)
class PersistedShareholderFacts:
    shareholder_id: str
    name: str
    share_count: int
    order: int


@dataclass(frozen=True, slots=True)
class ApprovedAnnualBasis:
    source_id: CorporateSourceReference
    income_year: IncomeYear
    latest_approved: bool
    annual_data_sha256: str
    annual_accounts_payload_sha256: str
    result_after_tax_ore: int
    equity_ore: int
    available_distribution_ore: int
    cash_ore: int


@dataclass(frozen=True, slots=True)
class AnnualDataSourceFacts:
    source_id: CorporateSourceReference
    company_id: CompanyId
    income_year: IncomeYear
    answers: Mapping[str, object]
    confirmations: tuple[str, ...]
    no_activity_confirmed: bool
    annual_full_time_equivalents: int | float
    completed_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class CorporateDecisionFactSources:
    company: PersistedCompanyFacts
    shareholders: tuple[PersistedShareholderFacts, ...]
    annual_data: tuple[AnnualDataSourceFacts, ...]


@dataclass(frozen=True, slots=True)
class CorporateAccountMovementFacts:
    income_year: IncomeYear
    account: str
    debit_ore: int
    credit_ore: int


@dataclass(frozen=True, slots=True)
class DerivedCorporateDecisionFacts:
    company: PersistedCompanyFacts
    shareholders: tuple[PersistedShareholderFacts, ...]
    annual_basis: ApprovedAnnualBasis
    reviewed_facts: ReviewedOwnerDividendFacts


@dataclass(frozen=True, slots=True)
class CorporateReadinessSource:
    source_id: CorporateSourceReference
    annual_data_sha256: str
    annual_accounts_payload_sha256: str


@dataclass(frozen=True, slots=True)
class ReviewedShareholderFacts:
    shareholder_id: str
    name: str
    share_count: int


@dataclass(frozen=True, slots=True)
class ReviewedOwnerDividendFacts:
    organization_number: str
    legal_name: str
    shareholders: tuple[ReviewedShareholderFacts, ...]
    total_company_shares: int
    available_distribution_ore: int
    annual_data_sha256: str
    annual_accounts_payload_sha256: str


@dataclass(frozen=True, slots=True)
class BoardMeeting:
    meeting_date: LocalDate
    meeting_time: time
    place: str
    treatment_method: BoardTreatmentMethod


@dataclass(frozen=True, slots=True)
class BoardParticipant:
    participant_id: str
    name: str
    role: BoardRole
    order: int


@dataclass(frozen=True, slots=True)
class GeneralMeeting:
    meeting_date: LocalDate
    meeting_time: time
    place: str
    meeting_form: MeetingForm
    chair_name: str
    co_signer_name: str


@dataclass(frozen=True, slots=True)
class ShareholderBallot:
    shareholder_id: str
    represented_share_count: int
    vote: ShareholderVote


@dataclass(frozen=True, slots=True)
class OwnerDividendProposalCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    company: PersistedCompanyFacts
    shareholders: tuple[PersistedShareholderFacts, ...]
    annual_basis: ApprovedAnnualBasis
    reviewed_facts: ReviewedOwnerDividendFacts
    board_meeting: BoardMeeting
    board_participants: tuple[BoardParticipant, ...]
    general_meeting: GeneralMeeting
    shareholder_ballots: tuple[ShareholderBallot, ...]
    one_share_class_confirmed: bool
    full_board_participation_confirmed: bool
    unanimous_board_confirmed: bool
    supported_dividend_basis_confirmed: bool
    prudent_equity_and_liquidity_confirmed: bool
    dividend_amount_ore: int
    payment_date: LocalDate


@dataclass(frozen=True, slots=True)
class AnnualCloseProposalCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    company: PersistedCompanyFacts
    shareholders: tuple[PersistedShareholderFacts, ...]
    annual_basis: ApprovedAnnualBasis
    reviewed_facts: ReviewedOwnerDividendFacts
    board_meeting: BoardMeeting
    board_participants: tuple[BoardParticipant, ...]
    general_meeting: GeneralMeeting
    shareholder_ballots: tuple[ShareholderBallot, ...]
    one_share_class_confirmed: bool
    full_board_participation_confirmed: bool
    unanimous_board_confirmed: bool
    supported_dividend_basis_confirmed: bool
    prudent_equity_and_liquidity_confirmed: bool
    annual_result_allocation_ore: int


@dataclass(frozen=True, slots=True)
class CanonicalBoardParticipant:
    participant_id: str
    name: str
    role: BoardRole


@dataclass(frozen=True, slots=True)
class CanonicalDecisionShareholder:
    shareholder_id: str
    name: str
    share_count: int
    represented_share_count: int
    vote: ShareholderVote


@dataclass(frozen=True, slots=True)
class OwnerDividendFinancialTotals:
    result_after_tax_ore: int
    equity_ore: int
    available_distribution_ore: int
    cash_ore: int


@dataclass(frozen=True, slots=True)
class OwnerDividendAllocation:
    shareholder_id: str
    amount_ore: int


@dataclass(frozen=True, slots=True)
class OwnerDividendFacts:
    amount_ore: int
    payment_date: LocalDate
    liquidity_after_payment_ore: int
    allocations: tuple[OwnerDividendAllocation, ...]


@dataclass(frozen=True, slots=True)
class OwnerDividendConfirmations:
    latest_approved_annual_accounts: bool
    supported_dividend_basis: bool
    full_board_participation: bool
    full_share_representation: bool
    unanimous_board: bool
    unanimous_shareholders: bool
    proportional_allocation: bool
    prudent_equity_and_liquidity: bool


@dataclass(frozen=True, slots=True)
class CanonicalOwnerDividendDecision:
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    company_id: CompanyId
    organization_number: str
    legal_name: str
    income_year: IncomeYear
    annual_close_source_id: CorporateSourceReference
    source_hash: str
    template_family: str
    template_version: str
    annual_basis_year: IncomeYear
    financial_totals: OwnerDividendFinancialTotals
    board_meeting: BoardMeeting
    board_participants: tuple[CanonicalBoardParticipant, ...]
    general_meeting: GeneralMeeting
    shareholders: tuple[CanonicalDecisionShareholder, ...]
    total_company_shares: int
    one_share_class_confirmed: bool
    dividend: OwnerDividendFacts
    annual_result_allocation_ore: int
    confirmations: OwnerDividendConfirmations
    decision_hash: str


@dataclass(frozen=True, slots=True)
class CanonicalAnnualCloseDecision:
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    company_id: CompanyId
    organization_number: str
    legal_name: str
    income_year: IncomeYear
    annual_close_source_id: CorporateSourceReference
    source_hash: str
    template_family: str
    template_version: str
    annual_basis_year: IncomeYear
    financial_totals: OwnerDividendFinancialTotals
    board_meeting: BoardMeeting
    board_participants: tuple[CanonicalBoardParticipant, ...]
    general_meeting: GeneralMeeting
    shareholders: tuple[CanonicalDecisionShareholder, ...]
    total_company_shares: int
    one_share_class_confirmed: bool
    dividend: None
    annual_result_allocation_ore: int
    confirmations: OwnerDividendConfirmations
    decision_hash: str


@dataclass(frozen=True, slots=True)
class ProposedOwnerDividend:
    decision: CanonicalOwnerDividendDecision
    state: OwnerDividendState
    replayed: bool
    artifacts: tuple[RenderedCorporateArtifact, ...] = ()


@dataclass(frozen=True, slots=True)
class ProposedAnnualClose:
    decision: CanonicalAnnualCloseDecision
    state: OwnerDividendState
    replayed: bool
    artifacts: tuple[RenderedCorporateArtifact, ...] = ()


@dataclass(frozen=True, slots=True)
class OwnerDividendLifecycle:
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    company_id: CompanyId
    income_year: IncomeYear
    decision_hash: str
    state: OwnerDividendState
    declared_amount_ore: int
    paid_amount_ore: int
    remaining_amount_ore: int
    finalization_id: CorporateFinalizationId | None
    accounting_entry_id: AccountingEntryReference | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class AnnualCloseLifecycle:
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    company_id: CompanyId
    income_year: IncomeYear
    decision_hash: str
    state: OwnerDividendState
    generated_artifact_hashes: dict[str, str]
    signed_artifact_hashes: dict[str, str]
    finalization_id: CorporateFinalizationId | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class CorporateDecisionRecord:
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    company_id: CompanyId
    income_year: IncomeYear
    decision_kind: CorporateDecisionKind
    annual_close_source_id: CorporateSourceReference
    source_hash: str
    canonical_input: Mapping[str, object]
    decision_hash: str
    created_by: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CorporateDocumentSetRecord:
    document_set_id: CorporateDocumentSetId
    company_id: CompanyId
    income_year: IncomeYear
    decision_id: CorporateDecisionId
    template_family: str
    template_version: str
    decision_hash: str
    created_by: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CorporateArtifactRecord:
    artifact_id: CorporateArtifactId
    company_id: CompanyId
    income_year: IncomeYear
    document_set_id: CorporateDocumentSetId
    artifact_kind: CorporateArtifactKind
    variant: CorporateArtifactVariant
    document_id: DocumentReference
    content_sha256: str
    byte_length: int
    supersedes_artifact_id: CorporateArtifactId | None
    created_by: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CorporateEventRecord:
    event_id: CorporateEventId
    company_id: CompanyId
    income_year: IncomeYear
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    artifact_id: CorporateArtifactId | None
    event_kind: str
    actor_id: str
    occurred_at: datetime
    decision_hash: str
    content_sha256: str | None
    metadata: Mapping[str, object]
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CorporateFinalizationRecord:
    finalization_id: CorporateFinalizationId
    company_id: CompanyId
    income_year: IncomeYear
    decision_id: CorporateDecisionId
    finalization_kind: str
    holding_action_id: CorporateEventId | None
    accounting_entry_id: AccountingEntryReference | None
    annual_close_source_id: CorporateSourceReference | None
    decision_hash: str
    signed_artifact_hashes: Mapping[str, str]
    accounting_policy_version: str | None
    created_by: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CorporateDocumentReadinessBlocker:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class CorporateDocumentReadiness:
    company_id: CompanyId
    income_year: IncomeYear
    decision_kind: CorporateDecisionKind
    decision_id: CorporateDecisionId | None
    document_set_id: CorporateDocumentSetId | None
    decision_hash: str | None
    source_hash: str | None
    current_source_hash: str | None
    state: OwnerDividendState | None
    current_source_matches: bool | None
    ready_for_signing: bool
    finalized: bool
    annual_submission_ready: bool
    generated_artifact_hashes: Mapping[str, str]
    signed_artifact_hashes: Mapping[str, str]
    required_signers: Mapping[str, tuple[str, ...]]
    declared_amount_ore: int | None
    paid_amount_ore: int | None
    remaining_amount_ore: int | None
    finalization_id: CorporateFinalizationId | None
    accounting_policy_version: str | None
    blockers: tuple[CorporateDocumentReadinessBlocker, ...]


@dataclass(frozen=True, slots=True)
class CorporateLifecycleSnapshot:
    decisions: tuple[CorporateDecisionRecord, ...]
    document_sets: tuple[CorporateDocumentSetRecord, ...]
    artifacts: tuple[CorporateArtifactRecord, ...]
    events: tuple[CorporateEventRecord, ...]
    finalizations: tuple[CorporateFinalizationRecord, ...]


@dataclass(frozen=True, slots=True)
class PreparedOwnerDividendFinalization:
    declared_amount_ore: int
    accounting_policy_version: str
    declaration_debit_account: str
    dividend_payable_account: str
    signed_artifact_hashes: dict[str, str]
    replay: OwnerDividendLifecycle | None


@dataclass(frozen=True, slots=True)
class PreparedOwnerDividendPayment:
    payment_amount_ore: int
    bank_transaction_date: LocalDate
    bank_signed_amount: Money
    bank_source_sha256: str
    accounting_policy_version: str
    dividend_payable_account: str
    bank_account: str
    replay: OwnerDividendLifecycle | None


@dataclass(frozen=True, slots=True)
class OwnerDividendArtifactReference:
    artifact_id: CorporateArtifactId
    document_id: DocumentReference
    artifact_kind: CorporateArtifactKind
    content_sha256: str
    byte_length: int


@dataclass(frozen=True, slots=True)
class RenderedCorporateArtifact:
    artifact_kind: CorporateArtifactKind
    filename: str
    template_version: str
    decision_hash: str
    content_sha256: str
    byte_length: int
    pdf_bytes: bytes


@dataclass(frozen=True, slots=True)
class RegisterOwnerDividendDocumentsCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    decision_hash: str
    artifacts: tuple[OwnerDividendArtifactReference, ...]


@dataclass(frozen=True, slots=True)
class RegisterAnnualCloseDocumentsCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    decision_hash: str
    artifacts: tuple[OwnerDividendArtifactReference, ...]


@dataclass(frozen=True, slots=True)
class ApproveOwnerDividendCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    decision_hash: str
    approval_event_id: CorporateEventId


@dataclass(frozen=True, slots=True)
class ApproveAnnualCloseCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    decision_hash: str
    approval_event_id: CorporateEventId


@dataclass(frozen=True, slots=True)
class RecordAnnualCloseEventCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    decision_hash: str
    event_id: CorporateEventId
    event_kind: AnnualCloseEventKind
    metadata: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class FinalizeAnnualCloseCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    decision_hash: str
    finalization_id: CorporateFinalizationId


@dataclass(frozen=True, slots=True)
class AttestAnnualCloseSignedArtifactCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    decision_hash: str
    unsigned_artifact_id: CorporateArtifactId
    signed_artifact_id: CorporateArtifactId
    signed_document_id: DocumentReference
    artifact_kind: CorporateArtifactKind
    filename: str
    content_sha256: str
    byte_length: int
    signers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RecordOwnerDividendEventCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    decision_hash: str
    event_id: CorporateEventId
    event_kind: OwnerDividendEventKind
    metadata: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class AttestOwnerDividendSignedArtifactCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    decision_hash: str
    unsigned_artifact_id: CorporateArtifactId
    signed_artifact_id: CorporateArtifactId
    signed_document_id: DocumentReference
    artifact_kind: CorporateArtifactKind
    filename: str
    content_sha256: str
    byte_length: int
    signers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FinalizeOwnerDividendCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    decision_hash: str
    finalization_id: CorporateFinalizationId
    holding_action_id: CorporateEventId
    ledger_entry_id: AccountingEntryReference


@dataclass(frozen=True, slots=True)
class RecordOwnerDividendPaymentCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    decision_id: CorporateDecisionId
    document_set_id: CorporateDocumentSetId
    decision_hash: str
    payment_event_id: CorporateEventId
    holding_action_id: CorporateEventId
    ledger_entry_id: AccountingEntryReference
    bank_transaction_id: BankTransactionReference


@dataclass(frozen=True, slots=True)
class RecordShareholderLoanCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    action_id: CorporateEventId
    ledger_entry_id: AccountingEntryReference
    loan_date: LocalDate
    amount: Money
    direction: ShareholderLoanDirection
    counterparty_name: str
    document_status: ShareholderLoanDocumentStatus
    interest_modelled: bool
    related_party_security: bool
    bank_transaction_id: BankTransactionReference | None
    document_id: DocumentReference | None


@dataclass(frozen=True, slots=True)
class CanonicalShareholderLoan:
    action_id: CorporateEventId
    company_id: CompanyId
    income_year: IncomeYear
    loan_date: LocalDate
    amount_ore: int
    direction: ShareholderLoanDirection
    counterparty_name: str
    document_status: ShareholderLoanDocumentStatus
    interest_modelled: bool
    related_party_security: bool
    bank_transaction_id: BankTransactionReference | None
    document_id: DocumentReference | None


@dataclass(frozen=True, slots=True)
class RecordedShareholderLoan:
    loan: CanonicalShareholderLoan
    accounting_entry_id: AccountingEntryReference
    replayed: bool


@dataclass(frozen=True, slots=True)
class PreparedShareholderLoan:
    loan: CanonicalShareholderLoan
    bank_transaction_date: LocalDate | None
    bank_signed_amount: Money | None
    bank_source_sha256: str | None
    replay: RecordedShareholderLoan | None


class CorporateGovernancePersistence(Protocol):
    async def read_decision_fact_sources(
        self,
        company_id: CompanyId,
        income_year: IncomeYear,
        decision_kind: CorporateDecisionKind,
    ) -> CorporateDecisionFactSources: ...

    @property
    def actor_id(self) -> ActorId: ...

    async def actor_role(self, company_id: CompanyId) -> str | None: ...

    async def list_lifecycle(
        self,
        company_ids: tuple[CompanyId, ...],
    ) -> CorporateLifecycleSnapshot: ...

    async def read_lifecycle(
        self,
        decision_id: CorporateDecisionId,
    ) -> CorporateLifecycleSnapshot: ...

    async def propose_owner_dividend(
        self,
        command: OwnerDividendProposalCommand,
        decision: CanonicalOwnerDividendDecision,
        canonical_input: Mapping[str, object],
    ) -> ProposedOwnerDividend: ...

    async def propose_annual_close(
        self,
        command: AnnualCloseProposalCommand,
        decision: CanonicalAnnualCloseDecision,
        canonical_input: Mapping[str, object],
        artifacts: tuple[RenderedCorporateArtifact, ...],
    ) -> ProposedAnnualClose: ...

    async def register_owner_dividend_documents(
        self,
        command: RegisterOwnerDividendDocumentsCommand,
    ) -> OwnerDividendLifecycle: ...

    async def register_annual_close_documents(
        self,
        command: RegisterAnnualCloseDocumentsCommand,
    ) -> AnnualCloseLifecycle: ...

    async def approve_owner_dividend(
        self,
        command: ApproveOwnerDividendCommand,
    ) -> OwnerDividendLifecycle: ...

    async def approve_annual_close(
        self,
        command: ApproveAnnualCloseCommand,
    ) -> AnnualCloseLifecycle: ...

    async def record_annual_close_event(
        self,
        command: RecordAnnualCloseEventCommand,
    ) -> AnnualCloseLifecycle: ...

    async def finalize_annual_close(
        self,
        command: FinalizeAnnualCloseCommand,
    ) -> AnnualCloseLifecycle: ...

    async def attest_annual_close_signed_artifact(
        self,
        command: AttestAnnualCloseSignedArtifactCommand,
    ) -> AnnualCloseLifecycle: ...

    async def record_owner_dividend_event(
        self,
        command: RecordOwnerDividendEventCommand,
    ) -> OwnerDividendLifecycle: ...

    async def attest_owner_dividend_signed_artifact(
        self,
        command: AttestOwnerDividendSignedArtifactCommand,
    ) -> OwnerDividendLifecycle: ...

    async def prepare_owner_dividend_finalization(
        self,
        command: FinalizeOwnerDividendCommand,
    ) -> PreparedOwnerDividendFinalization: ...

    async def complete_owner_dividend_finalization(
        self,
        command: FinalizeOwnerDividendCommand,
        accounting_entry_id: AccountingEntryReference,
        prepared: PreparedOwnerDividendFinalization,
    ) -> OwnerDividendLifecycle: ...

    async def prepare_owner_dividend_payment(
        self,
        command: RecordOwnerDividendPaymentCommand,
    ) -> PreparedOwnerDividendPayment: ...

    async def complete_owner_dividend_payment(
        self,
        command: RecordOwnerDividendPaymentCommand,
        accounting_entry_id: AccountingEntryReference,
        prepared: PreparedOwnerDividendPayment,
    ) -> OwnerDividendLifecycle: ...

    async def prepare_shareholder_loan(
        self,
        command: RecordShareholderLoanCommand,
        loan: CanonicalShareholderLoan,
    ) -> PreparedShareholderLoan: ...

    async def complete_shareholder_loan(
        self,
        command: RecordShareholderLoanCommand,
        accounting_entry_id: AccountingEntryReference,
        prepared: PreparedShareholderLoan,
    ) -> RecordedShareholderLoan: ...


CorporateGovernanceAdapter = TypeVar(
    "CorporateGovernanceAdapter", bound=type[object]
)


def corporate_governance_persistence_adapter(
    contract: type[object],
) -> Callable[[CorporateGovernanceAdapter], CorporateGovernanceAdapter]:
    """Declare a governance persistence adapter without global registration."""

    def decorate(adapter: CorporateGovernanceAdapter) -> CorporateGovernanceAdapter:
        adapter.__talli_adapter_contract__ = contract
        return adapter

    return decorate


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


__all__ = [
    "SHA256_PATTERN",
    "AccountingEntryReference",
    "AnnualCloseEventKind",
    "AnnualCloseLifecycle",
    "AnnualCloseProposalCommand",
    "AnnualDataSourceFacts",
    "ApproveAnnualCloseCommand",
    "ApproveOwnerDividendCommand",
    "ApprovedAnnualBasis",
    "AttestAnnualCloseSignedArtifactCommand",
    "AttestOwnerDividendSignedArtifactCommand",
    "BankTransactionReference",
    "BoardMeeting",
    "BoardParticipant",
    "BoardRole",
    "BoardTreatmentMethod",
    "CanonicalAnnualCloseDecision",
    "CanonicalBoardParticipant",
    "CanonicalDecisionShareholder",
    "CanonicalOwnerDividendDecision",
    "CanonicalShareholderLoan",
    "CorporateAccountMovementFacts",
    "CorporateArtifactId",
    "CorporateArtifactKind",
    "CorporateArtifactRecord",
    "CorporateArtifactVariant",
    "CorporateDecisionFactSources",
    "CorporateDecisionId",
    "CorporateDecisionKind",
    "CorporateDecisionRecord",
    "CorporateDocumentReadiness",
    "CorporateDocumentReadinessBlocker",
    "CorporateDocumentSetId",
    "CorporateDocumentSetRecord",
    "CorporateEventId",
    "CorporateEventRecord",
    "CorporateFinalizationId",
    "CorporateFinalizationRecord",
    "CorporateGovernanceError",
    "CorporateGovernanceErrorCode",
    "CorporateGovernancePersistence",
    "CorporateLifecycleSnapshot",
    "CorporateReadinessSource",
    "CorporateSourceReference",
    "DerivedCorporateDecisionFacts",
    "DocumentReference",
    "FinalizeAnnualCloseCommand",
    "FinalizeOwnerDividendCommand",
    "GeneralMeeting",
    "MeetingForm",
    "OwnerDividendAllocation",
    "OwnerDividendArtifactReference",
    "OwnerDividendConfirmations",
    "OwnerDividendEventKind",
    "OwnerDividendFacts",
    "OwnerDividendFinancialTotals",
    "OwnerDividendLifecycle",
    "OwnerDividendProposalCommand",
    "OwnerDividendState",
    "PersistedCompanyFacts",
    "PersistedShareholderFacts",
    "PreparedOwnerDividendFinalization",
    "PreparedOwnerDividendPayment",
    "PreparedShareholderLoan",
    "ProposedAnnualClose",
    "ProposedOwnerDividend",
    "RecordAnnualCloseEventCommand",
    "RecordOwnerDividendEventCommand",
    "RecordOwnerDividendPaymentCommand",
    "RecordShareholderLoanCommand",
    "RecordedShareholderLoan",
    "RegisterAnnualCloseDocumentsCommand",
    "RegisterOwnerDividendDocumentsCommand",
    "RenderedCorporateArtifact",
    "ReviewedOwnerDividendFacts",
    "ReviewedShareholderFacts",
    "ShareholderBallot",
    "ShareholderLoanDirection",
    "ShareholderLoanDocumentStatus",
    "ShareholderVote",
    "corporate_governance_persistence_adapter",
]
