"""RF-owned immutable facts, deterministic commands and journal/provider ports."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from enum import StrEnum
import re
from typing import Literal, Protocol, TypeVar
from uuid import UUID

from talli_backend.shared.kernel import (
    ActorId,
    CompanyId,
    CorrelationId,
    DomainError,
    ErrorCategory,
    IdempotencyKey,
    IncomeYear,
    Money,
    Timestamp,
)


class ShareholderRegisterFilingErrorCode(StrEnum):
    INVALID_INPUT = "SHAREHOLDER_REGISTER_FILING_INVALID_INPUT"
    NOT_FOUND = "SHAREHOLDER_REGISTER_FILING_NOT_FOUND"
    FORBIDDEN = "SHAREHOLDER_REGISTER_FILING_FORBIDDEN"
    COMPANY_YEAR_NOT_ADMITTED = (
        "SHAREHOLDER_REGISTER_FILING_COMPANY_YEAR_NOT_ADMITTED"
    )
    OPENING_ALREADY_EXISTS = (
        "SHAREHOLDER_REGISTER_FILING_OPENING_ALREADY_EXISTS"
    )
    DEPENDENCY_UNAVAILABLE = (
        "SHAREHOLDER_REGISTER_FILING_DEPENDENCY_UNAVAILABLE"
    )


class ShareholderRegisterFilingError(DomainError):
    @classmethod
    def invalid_input(cls) -> ShareholderRegisterFilingError:
        return cls(
            code=ShareholderRegisterFilingErrorCode.INVALID_INPUT,
            category=ErrorCategory.INVALID_INPUT,
        )

    @classmethod
    def not_found(cls) -> ShareholderRegisterFilingError:
        return cls(
            code=ShareholderRegisterFilingErrorCode.NOT_FOUND,
            category=ErrorCategory.NOT_FOUND,
        )

    @classmethod
    def forbidden(cls) -> ShareholderRegisterFilingError:
        return cls(
            code=ShareholderRegisterFilingErrorCode.FORBIDDEN,
            category=ErrorCategory.FORBIDDEN,
        )

    @classmethod
    def company_year_not_admitted(cls) -> ShareholderRegisterFilingError:
        return cls(
            code=ShareholderRegisterFilingErrorCode.COMPANY_YEAR_NOT_ADMITTED,
            category=ErrorCategory.PRECONDITION_FAILED,
        )

    @classmethod
    def opening_already_exists(cls) -> ShareholderRegisterFilingError:
        return cls(
            code=ShareholderRegisterFilingErrorCode.OPENING_ALREADY_EXISTS,
            category=ErrorCategory.CONFLICT,
        )

    @classmethod
    def unavailable(cls) -> ShareholderRegisterFilingError:
        return cls(
            code=ShareholderRegisterFilingErrorCode.DEPENDENCY_UNAVAILABLE,
            category=ErrorCategory.DEPENDENCY_UNAVAILABLE,
        )


@dataclass(frozen=True, slots=True)
class OpeningSnapshotId:
    value: str

    def __post_init__(self) -> None:
        try:
            parsed = UUID(self.value)
        except (ValueError, AttributeError, TypeError):
            raise ValueError("opening snapshot id must be a UUID") from None
        object.__setattr__(self, "value", str(parsed))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OpeningShareholder:
    name: str
    shareholder_kind: Literal["norwegian_person", "norwegian_company"]
    national_id: str | None
    org_number: str | None
    share_count: int

    def __post_init__(self) -> None:
        name = self.name.strip()
        valid_identifier = (
            self.shareholder_kind == "norwegian_person"
            and re.fullmatch(r"\d{11}", self.national_id or "") is not None
        ) or (
            self.shareholder_kind == "norwegian_company"
            and re.fullmatch(r"\d{9}", self.org_number or "") is not None
        )
        if not name or len(name) > 255 or self.share_count < 0 or not valid_identifier:
            raise ShareholderRegisterFilingError.invalid_input()
        object.__setattr__(self, "name", name)


@dataclass(frozen=True, slots=True)
class RecordOpeningSnapshotCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    share_capital: Money
    share_count: int
    nominal_value: Money
    shareholders: tuple[OpeningShareholder, ...]

    def __post_init__(self) -> None:
        if (
            self.share_capital.amount < 0
            or self.share_count <= 0
            or self.nominal_value.amount <= 0
            or not 1 <= len(self.shareholders) <= 100
            or self.share_capital.amount
            != self.nominal_value.amount * self.share_count
            or sum(shareholder.share_count for shareholder in self.shareholders)
            != self.share_count
        ):
            raise ShareholderRegisterFilingError.invalid_input()


class ShareholderRegisterFilingCommands(Protocol):
    async def record_opening_snapshot(
        self, command: RecordOpeningSnapshotCommand
    ) -> OpeningSnapshotId: ...

    async def generate_preview(self, command: GenerateRf1086PreviewCommand) -> Rf1086RecordedResult: ...

    async def record_override(self, command: RecordRf1086OverrideCommand) -> Rf1086RecordedResult: ...

    async def add_review_comment(self, command: AddRf1086ReviewCommentCommand) -> Rf1086RecordedResult: ...

    async def acknowledge_review_comment(self, command: AcknowledgeRf1086ReviewCommentCommand) -> Rf1086RecordedResult: ...

    async def confirm_simulation(self, command: ConfirmRf1086SimulationCommand) -> Rf1086RecordedResult: ...

    async def confirm_filing_permission(self, command: ConfirmRf1086FilingPermissionCommand) -> Rf1086RecordedResult: ...

    async def record_test_evidence(self, command: RecordRf1086TestEvidenceCommand) -> Rf1086RecordedResult: ...

    async def approve_production(self, command: ApproveRf1086ProductionCommand) -> Rf1086RecordedResult: ...



# RF case values preserve the existing offline/statutory input vocabulary.
# Operational UUIDs and UTC timestamps are separate from civil event values.
class _ImmutableRf1086Value:
    __slots__ = ()
    def __post_init__(self) -> None:
        for item in fields(self):
            object.__setattr__(self, item.name, _freeze_rf1086_value(getattr(self, item.name)))


def _freeze_rf1086_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_rf1086_value(child) for key, child in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_rf1086_value(child) for child in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_rf1086_value(child) for child in value)
    return value


class Rf1086ShareholderKind(StrEnum):
    NORWEGIAN_PERSON = "norwegian_person"
    NORWEGIAN_COMPANY = "norwegian_company"


@dataclass(frozen=True, slots=True)
class Rf1086Company(_ImmutableRf1086Value):
    org_number: str
    name: str
    address: str
    postal_code: str
    city: str
    income_year: int
    share_type: str = "01"
    contact_email: str | None = None


@dataclass(frozen=True, slots=True)
class Rf1086ShareSnapshot(_ImmutableRf1086Value):
    previous_share_capital: float
    current_share_capital: float
    previous_nominal_value: float
    current_nominal_value: float
    previous_share_count: int
    current_share_count: int
    previous_paid_in_share_capital: float
    current_paid_in_share_capital: float
    previous_paid_in_premium: float = 0
    current_paid_in_premium: float = 0


@dataclass(frozen=True, slots=True)
class Rf1086Shareholder(_ImmutableRf1086Value):
    id: str
    kind: Rf1086ShareholderKind
    name: str
    national_id: str | None = None
    org_number: str | None = None


@dataclass(frozen=True, slots=True)
class Rf1086ShareholderSnapshot(_ImmutableRf1086Value):
    shareholder_id: str
    previous_share_count: int
    current_share_count: int


class _ImmutableRf1086Event(_ImmutableRf1086Value):
    __slots__ = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        # Readiness and XML rendering must always identify the same variant.
        # Literal annotations alone do not validate direct Python callers.
        expected_type = next(item.default for item in fields(self) if item.name == "type")
        if self.type != expected_type:
            raise ValueError("RF-1086 event type must match its public event class")


@dataclass(frozen=True, slots=True)
class Rf1086FormationAllocation(_ImmutableRf1086Value):
    shareholder_id: str
    share_count: int
    acquisition_value: float


@dataclass(frozen=True, slots=True)
class Rf1086FormationEvent(_ImmutableRf1086Event):
    timestamp: datetime
    issued_share_count: int
    share_count_after: int
    nominal_value: float
    allocations: tuple[Rf1086FormationAllocation, ...]
    premium: float = 0
    type: Literal["formation"] = "formation"


@dataclass(frozen=True, slots=True)
class Rf1086ShareSaleEvent(_ImmutableRf1086Event):
    timestamp: datetime
    seller_shareholder_id: str
    buyer_shareholder_id: str
    share_count: int
    consideration: float
    type: Literal["share_sale"] = "share_sale"


@dataclass(frozen=True, slots=True)
class Rf1086DividendAllocation(_ImmutableRf1086Value):
    shareholder_id: str
    amount: float
    share_count_basis: int


@dataclass(frozen=True, slots=True)
class Rf1086DividendEvent(_ImmutableRf1086Event):
    timestamp: datetime
    total_amount: float
    per_share_amount: float
    allocations: tuple[Rf1086DividendAllocation, ...]
    type: Literal["dividend"] = "dividend"


@dataclass(frozen=True, slots=True)
class Rf1086CashIssueEvent(_ImmutableRf1086Event):
    """Registered cash subscription; premium is the amount per new share."""
    timestamp: datetime
    issued_share_count: int
    share_count_after: int
    nominal_value: float
    allocations: tuple[Rf1086FormationAllocation, ...]
    registration_confirmed: Literal[True]
    premium: float = 0
    type: Literal["cash_issue"] = "cash_issue"


@dataclass(frozen=True, slots=True)
class Rf1086NominalIncreaseAllocation(_ImmutableRf1086Value):
    shareholder_id: str
    share_count_basis: int
    capital_increase: float
    premium: float = 0


@dataclass(frozen=True, slots=True)
class Rf1086CashNominalIncreaseEvent(_ImmutableRf1086Event):
    """Registered cash contribution, retaining all existing shares."""
    timestamp: datetime
    capital_increase: float
    nominal_value_increase: float
    nominal_value_after: float
    allocations: tuple[Rf1086NominalIncreaseAllocation, ...]
    registration_confirmed: Literal[True]
    premium: float = 0
    type: Literal["cash_nominal_increase"] = "cash_nominal_increase"


@dataclass(frozen=True, slots=True)
class Rf1086LossCoveringReductionEvent(_ImmutableRf1086Event):
    """Registered loss cover without payout; no fund-issued capital is supported."""
    timestamp: datetime
    capital_reduction: float
    nominal_value_reduction: float
    nominal_value_after: float
    registration_confirmed: Literal[True]
    fund_issued_capital_before: Literal[0]
    type: Literal["loss_covering_reduction"] = "loss_covering_reduction"


@dataclass(frozen=True, slots=True)
class Rf1086Case(_ImmutableRf1086Value):
    case_id: str
    company: Rf1086Company
    share_snapshot: Rf1086ShareSnapshot
    shareholders: tuple[Rf1086Shareholder, ...]
    shareholder_snapshots: tuple[Rf1086ShareholderSnapshot, ...]
    events: tuple[Rf1086FormationEvent | Rf1086ShareSaleEvent | Rf1086DividendEvent | Rf1086CashIssueEvent | Rf1086CashNominalIncreaseEvent | Rf1086LossCoveringReductionEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class Rf1086ReadinessIssue(_ImmutableRf1086Value):
    level: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class Rf1086ReadinessResult(_ImmutableRf1086Value):
    filing: str
    status: Literal["ready", "blocked", "warning"]
    issues: tuple[Rf1086ReadinessIssue, ...]

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True, slots=True)
class Rf1086DocumentSet(_ImmutableRf1086Value):
    hovedskjema_xml: str = field(repr=False)
    underskjema_xml: Mapping[str, str] = field(repr=False)


@dataclass(frozen=True, slots=True)
class Rf1086RenderedPreview(_ImmutableRf1086Value):
    filing: str
    status: Literal["ready", "blocked", "warning"]
    issues: tuple[Rf1086ReadinessIssue, ...]
    preview: str
    hovedskjema_xml: str | None = field(default=None, repr=False)
    underskjema_xml: Mapping[str, str] = field(default_factory=dict, repr=False)


@dataclass(frozen=True, slots=True)
class _Rf1086Id:
    value: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "value", str(UUID(self.value)))
        except (ValueError, AttributeError, TypeError):
            raise ShareholderRegisterFilingError.invalid_input() from None

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class PreviewId(_Rf1086Id):
    pass


@dataclass(frozen=True, slots=True)
class OverrideId(_Rf1086Id):
    pass


@dataclass(frozen=True, slots=True)
class ReviewCommentId(_Rf1086Id):
    pass


@dataclass(frozen=True, slots=True)
class ApprovalId(_Rf1086Id):
    pass


@dataclass(frozen=True, slots=True)
class SubmissionId(_Rf1086Id):
    pass


@dataclass(frozen=True, slots=True)
class TestEvidenceId(_Rf1086Id):
    pass


@dataclass(frozen=True, slots=True)
class Rf1086RecordedResult:
    record_id: str
    company_id: CompanyId
    income_year: IncomeYear | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_id", str(_Rf1086Id(self.record_id)))
        if not isinstance(self.company_id, CompanyId) or (
            self.income_year is not None and not isinstance(self.income_year, IncomeYear)
        ):
            raise ShareholderRegisterFilingError.invalid_input()


@dataclass(frozen=True, slots=True)
class GenerateRf1086PreviewCommand:
    company_id: CompanyId
    opening_snapshot_id: OpeningSnapshotId
    actor_id: ActorId
    correlation_id: CorrelationId


@dataclass(frozen=True, slots=True)
class RecordRf1086OverrideCommand:
    preview_id: PreviewId
    field_target: str
    old_value: str
    new_value: str
    reason: str
    risk_level: Literal["advisory", "warning", "block"]
    owner_confirmed: bool
    actor_id: ActorId
    correlation_id: CorrelationId


@dataclass(frozen=True, slots=True)
class AddRf1086ReviewCommentCommand:
    preview_id: PreviewId
    severity: Literal["advisory", "hard_block"]
    body: str
    actor_id: ActorId
    correlation_id: CorrelationId


@dataclass(frozen=True, slots=True)
class AcknowledgeRf1086ReviewCommentCommand:
    comment_id: ReviewCommentId
    actor_id: ActorId
    correlation_id: CorrelationId


@dataclass(frozen=True, slots=True)
class ConfirmRf1086SimulationCommand:
    preview_id: PreviewId
    authority_confirmed: bool
    preview_confirmed: bool
    actor_id: ActorId
    correlation_id: CorrelationId


@dataclass(frozen=True, slots=True)
class ConfirmRf1086FilingPermissionCommand:
    company_id: CompanyId
    production_enabled: bool
    actor_id: ActorId
    correlation_id: CorrelationId


@dataclass(frozen=True, slots=True)
class RecordRf1086TestEvidenceCommand:
    company_id: CompanyId
    environment: Literal["test", "manual_evidence"]
    status: Literal["accepted", "rejected", "blocked", "pending"]
    test_reference: str
    feedback_summary: str
    receipt_reference: str | None
    archive_reference: str | None
    evidence_url: str | None
    payload_hash: str | None
    actor_id: ActorId
    correlation_id: CorrelationId


@dataclass(frozen=True, slots=True)
class ApproveRf1086ProductionCommand:
    preview_id: PreviewId
    entitlement_id: str
    real_filing_confirmed: bool
    actor_id: ActorId
    correlation_id: CorrelationId


@dataclass(frozen=True, slots=True)
class SendApprovedRf1086Command:
    approval_id: ApprovalId
    actor_id: ActorId
    correlation_id: CorrelationId


@dataclass(frozen=True, slots=True)
class ReconcileRf1086FeedbackCommand:
    submission_id: SubmissionId
    actor_id: ActorId
    correlation_id: CorrelationId


@dataclass(frozen=True, slots=True)
class Rf1086WorkspaceQuery:
    company_id: CompanyId
    actor_id: ActorId
    income_year: IncomeYear | None = None


@dataclass(frozen=True, slots=True)
class Rf1086ArchiveQuery:
    company_id: CompanyId
    income_year: IncomeYear
    actor_id: ActorId

    def __post_init__(self) -> None:
        if (not isinstance(self.company_id,CompanyId) or not isinstance(self.income_year,IncomeYear)
                or not isinstance(self.actor_id,ActorId)):
            raise ShareholderRegisterFilingError.invalid_input()


@dataclass(frozen=True, slots=True)
class Rf1086SourceQuery:
    company_id: CompanyId
    income_year: IncomeYear
    actor_id: ActorId


@dataclass(frozen=True, slots=True)
class Rf1086ActionAvailability:
    action: str
    allowed: bool
    reason_code: str | None = None

# Exact predecessor DTO/port declarations for acceptance_audit to adopt.
# Source91b; public mappings/tuples must be recursively frozen without changing JSON semantics.
# Binding handles and authenticated session/factory remain application-private.


ProductionOperationState = Literal["prepared", "succeeded", "failed", "unknown"]
FailureClassification = Literal["retryable", "blocked", "unknown"]
Rf1086FeedbackClassification = Literal["accepted", "rejected", "action_required"]
Rf1086ReconciliationState = Literal["sent", "processing", "accepted", "rejected", "action_required", "unknown"]

class Rf1086AuthorityError(Exception):
    def __init__(self, code: str = "RF1086_AUTHORITY_ERROR", *, status: int | None = None,
                 correlation_id: str | None = None, specification_codes: tuple[str, ...] = (), retryable: bool = False):
        self.code = code
        self.status = status
        self.correlation_id = correlation_id
        self.specification_codes = specification_codes
        self.retryable = retryable
        # Raw authority messages, submitted values and credentials are not retained.
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Rf1086AuthorityCall(_ImmutableRf1086Value):
    method: Literal["GET", "POST"]
    endpoint: str
    body_hash: str
    idempotency_key: str | None
    status: Literal["accepted"] = "accepted"


@dataclass(frozen=True, slots=True)
class Rf1086MainResponse(_ImmutableRf1086Value):
    hovedskjema_id: str
    call: Rf1086AuthorityCall


@dataclass(frozen=True, slots=True)
class Rf1086PostResponse(_ImmutableRf1086Value):
    call: Rf1086AuthorityCall


@dataclass(frozen=True, slots=True)
class Rf1086Confirmation(_ImmutableRf1086Value):
    oppgavegivers_leveranse_referanse: str
    dialog_id: str
    forsendelse_id: str
    call: Rf1086AuthorityCall


@dataclass(frozen=True, slots=True)
class Rf1086DocumentReference(_ImmutableRf1086Value):
    reference: str


@dataclass(frozen=True, slots=True)
class Rf1086DocumentPage(_ImmutableRf1086Value):
    total_items: int | float
    total_pages: int | float
    current_page: int | float
    documents: tuple[str | Rf1086DocumentReference, ...]
    document_shape_valid: bool
    call: Rf1086AuthorityCall


@dataclass(frozen=True, slots=True)
class Rf1086AuthorityDocument(_ImmutableRf1086Value):
    reference: str
    content_type: str
    bytes: bytes = field(repr=False)


class Rf1086ReadOnlyAuthority(Protocol):
    async def list_documents(self, *, income_year: int, reference_id: str,
                             page: int = 0, size: int = 50) -> Rf1086DocumentPage: ...
    async def get_document(self, *, income_year: int, forsendelse_id: str,
                           document_id: str) -> Rf1086AuthorityDocument: ...


@dataclass(frozen=True, slots=True)
class Rf1086FeedbackTransmission(_ImmutableRf1086Value):
    dialog_id: str
    transmission_id: str
    related_forsendelse_id: str
    created_at: str
    document_ids: tuple[str, ...]
    transmission_type: str


class Rf1086FeedbackDiscovery(Protocol):
    async def read_feedback_transmissions(self, *, organization_number: str,
            dialog_id: str, forsendelse_id: str) -> tuple[Rf1086FeedbackTransmission, ...]: ...


class Rf1086MutationAuthority(Protocol):
    async def post_hovedskjema(self, *, income_year: int, xml: str, idempotency_key: str) -> Rf1086MainResponse: ...
    async def post_underskjema(self, *, income_year: int, hovedskjema_id: str,
                              xml: str, idempotency_key: str) -> Rf1086PostResponse: ...
    async def confirm(self, *, income_year: int, hovedskjema_id: str,
                       underskjema_count: int, idempotency_key: str) -> Rf1086Confirmation: ...
    async def list_documents(self, *, income_year: int, reference_id: str,
                             page: int = 0, size: int = 50) -> Rf1086DocumentPage: ...


@dataclass(frozen=True, slots=True)
class ProductionOperation(_ImmutableRf1086Value):
    id: str
    name: str
    state: ProductionOperationState
    attempt: int
    body_hash: str | None
    idempotency_key: str | None
    authority_reference: str | None
    failure_classification: FailureClassification | None


@dataclass(frozen=True, slots=True)
class ProductionOperationFailure(_ImmutableRf1086Value):
    classification: FailureClassification
    code: str
    correlation_id: str | None


class ProductionOperationJournal(Protocol):
    """Prepare commits before I/O and restores persisted body/key identity.

    Existing records use resume_production_operation, so interrupted mutations
    are unknown and the twentieth failed attempt cannot be retried.
    """
    async def prepare(self, *, submission_id: str, name: str, body_hash: str | None,
                       idempotency_key: str | None) -> ProductionOperation: ...
    async def succeed(self, operation_id: str, authority_reference: str | None) -> None: ...
    async def fail(self, operation_id: str, failure: ProductionOperationFailure) -> None: ...


@dataclass(frozen=True, slots=True)
class JournaledRf1086ProductionInput(_ImmutableRf1086Value):
    submission_id: str
    income_year: int
    hovedskjema_xml: str = field(repr=False)
    underskjema_xml: Mapping[str, str] = field(repr=False)
    document_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JournaledRf1086ProductionResult(_ImmutableRf1086Value):
    status: Literal["received", "processing"]
    hovedskjema_id: str
    dialog_id: str
    forsendelse_id: str
    document_count: int
    final_authority_decision: None = None


class Rf1086UnknownProductionOutcomeError(Exception):
    code = "rf1086_unknown_production_outcome"

    def __init__(self, operation_name: str):
        super().__init__(self.code)


class Rf1086BlockedProductionOperationError(Exception):
    code = "rf1086_blocked_production_operation"

    def __init__(self, operation_name: str):
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class Rf1086FeedbackResult(_ImmutableRf1086Value):
    classification: Rf1086FeedbackClassification
    schema: str
    transmission_id: str | None


@dataclass(frozen=True, slots=True)
class Rf1086ReconciliationSnapshot(_ImmutableRf1086Value):
    state: Rf1086ReconciliationState
    artifact_hashes: tuple[str, ...] = ()
    safe_error_code: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class Rf1086ReconciliationArtifact(_ImmutableRf1086Value):
    submission_id: str
    company_id: str
    authority_reference: str
    content_type: str
    bytes: bytes = field(repr=False)
    byte_length: int
    sha256: str
    classification: Rf1086FeedbackClassification


class Rf1086FeedbackArtifactPersistenceError(Exception):
    def __init__(self, *, retryable: bool):
        self.retryable = retryable
        super().__init__("RF1086_FEEDBACK_ARTIFACT_PERSISTENCE_ERROR")


class Rf1086ProductionJournal(Protocol):
    async def read_reconciliation_state(self) -> Rf1086ReconciliationSnapshot: ...
    async def record_artifact(self, artifact: Rf1086ReconciliationArtifact) -> str: ...
    async def append_reconciliation(self, event: Rf1086ReconciliationSnapshot) -> bool: ...


@dataclass(frozen=True, slots=True)
class Rf1086ReconciliationInput(_ImmutableRf1086Value):
    submission_id: str
    company_id: str
    income_year: int
    forsendelse_id: str
    hovedskjema_xml: str = field(repr=False)
    underskjema_xml: Mapping[str, str] = field(repr=False)

    organization_number: str | None = None
    dialog_id: str | None = None


@dataclass(frozen=True, slots=True)
class Rf1086ReconciliationResult(_ImmutableRf1086Value):
    state: Rf1086ReconciliationState
    archive_reads: int
    artifact_count: int
    artifact_hashes: tuple[str, ...]
    safe_error_code: str | None
    correlation_id: str | None
    changed: bool


class Rf1086ProductionError(Exception):
    def __init__(self, code: str):
        allowed = {"invalid_request", "authentication_required", "approval_expired", "basis_unavailable",
            "connection_unavailable", "payload_changed", "configuration_unavailable", "send_unavailable",
            "status_unavailable", "status_busy", "step_up_required"}
        self.code = code if code in allowed else "status_unavailable"
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class Rf1086Approval(_ImmutableRf1086Value):
    id: str
    entitlement_id: str
    preview_id: str
    company_id: str
    user_id: str
    income_year: int
    obligation: str
    case_profile: str
    invalidated: bool
    manifest_hash: str
    manifest: Mapping[str, object] | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class Rf1086Preview(_ImmutableRf1086Value):
    id: str
    company_id: str
    income_year: int
    filing: str
    hovedskjema_xml: str = field(repr=False)
    underskjema_xml: Mapping[str, str] = field(repr=False)
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Rf1086Submission(_ImmutableRf1086Value):
    id: str
    approval_id: str
    entitlement_id: str
    company_id: str
    user_id: str
    income_year: int
    obligation: str
    case_profile: str
    environment: str
    feedback_state: Rf1086ReconciliationState


@dataclass(frozen=True, slots=True)
class Rf1086Connection(_ImmutableRf1086Value):
    id: str
    company_id: str
    initiating_owner_user_id: str
    obligation: str
    external_ref: str = field(repr=False)
    status: str
    preflight_verified: bool


@dataclass(frozen=True, slots=True)
class Rf1086SendResult(_ImmutableRf1086Value):
    submission_id: str


@dataclass(frozen=True, slots=True)
class Rf1086OwnerReconciliationResult(_ImmutableRf1086Value):
    state: Rf1086ReconciliationState | None
    error_code: str | None = None
    requires_manual_retry: bool = False





@dataclass(frozen=True, slots=True)
class Rf1086PreviewRecord(_ImmutableRf1086Value):
    id: str
    company_id: str
    setup_id: str | None
    income_year: int
    filing: str
    status: str
    issues: tuple[Rf1086ReadinessIssue, ...]
    preview: str
    hovedskjema_xml: str | None
    underskjema_xml: Mapping[str, str]
    source: str
    created_at: str


@dataclass(frozen=True, slots=True)
class Rf1086SimulationRecord(_ImmutableRf1086Value):
    id: str
    preview_id: str | None
    authority_test_run_id: str | None
    company_id: str
    income_year: int
    filing: str
    mode: str
    adapter_mode: str
    payload_hash: str | None
    idempotency_key: str | None
    status: str
    calls: tuple[Mapping[str, object], ...]
    receipt_id: str | None
    feedback_document_ids: tuple[str, ...]
    feedback_items: tuple[Mapping[str, object], ...]
    receipt_metadata: Mapping[str, object] | None
    submitted_payload_ref: Mapping[str, object] | None
    submitted_payload: Mapping[str, object] | None
    authority_confirmed_at: str | None
    preview_confirmed_at: str | None
    created_at: str
    updated_at: str
    submitted_by: str | None


@dataclass(frozen=True, slots=True)
class Rf1086OverrideRecord(_ImmutableRf1086Value):
    id: str
    preview_id: str | None
    company_id: str
    income_year: int
    filing: str
    field_target: str
    old_value: str
    new_value: str
    reason: str
    risk_level: str
    owner_confirmed_by: str
    owner_confirmed_at: str
    created_by: str
    created_at: str


@dataclass(frozen=True, slots=True)
class Rf1086ReviewCommentRecord(_ImmutableRf1086Value):
    id: str
    preview_id: str
    company_id: str
    target: str
    severity: str
    body: str
    created_by: str
    acknowledged_by: str | None
    acknowledged_at: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class Rf1086FilingPermissionRecord(_ImmutableRf1086Value):
    id: str
    company_id: str
    obligation: str
    submitter_user_id: str
    confirmed_by: str
    confirmed_at: str
    production_enabled: bool
    updated_at: str


@dataclass(frozen=True, slots=True)
class Rf1086TestEvidenceRecord(_ImmutableRf1086Value):
    id: str
    company_id: str
    obligation: str
    environment: str
    status: str
    test_reference: str
    feedback_summary: str
    receipt_reference: str | None
    archive_reference: str | None
    evidence_url: str | None
    payload_hash: str | None
    recorded_by: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class Rf1086ApprovalRecord(_ImmutableRf1086Value):
    id: str
    entitlement_id: str
    preview_id: str
    company_id: str
    user_id: str
    income_year: int
    obligation: str
    case_profile: str
    adapter_version: str
    payload_hash: str
    manifest_hash: str
    manifest: Mapping[str, object]
    approved_by: str
    approved_at: str
    invalidated_at: str | None
    invalidation_reason: str | None


@dataclass(frozen=True, slots=True)
class Rf1086ProductionSubmissionRecord(_ImmutableRf1086Value):
    id: str
    approval_id: str
    entitlement_id: str
    company_id: str
    user_id: str
    income_year: int
    obligation: str
    case_profile: str
    payload_hash: str
    adapter_version: str
    environment: str
    status: str
    authority_references: Mapping[str, str]
    failure_class: str | None
    supersedes_submission_id: str | None
    submitted_by: str
    feedback_state: str
    feedback_artifact_count: int
    feedback_last_checked_at: str | None
    feedback_last_changed_at: str | None
    feedback_safe_error_code: str | None
    feedback_correlation_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class Rf1086FeedbackArtifactRecord(_ImmutableRf1086Value):
    id: str
    company_id: str
    submission_id: str
    document_id: str
    content_type: str
    byte_length: int
    sha256: str
    retrieved_at: str
    classification: str


@dataclass(frozen=True, slots=True)
class Rf1086WorkspaceSnapshot(_ImmutableRf1086Value):
    company_id: CompanyId
    income_year: IncomeYear | None
    previews: tuple[Rf1086PreviewRecord, ...] = ()
    simulations: tuple[Rf1086SimulationRecord, ...] = ()
    overrides: tuple[Rf1086OverrideRecord, ...] = ()
    review_comments: tuple[Rf1086ReviewCommentRecord, ...] = ()
    permissions: tuple[Rf1086FilingPermissionRecord, ...] = ()
    test_evidence: tuple[Rf1086TestEvidenceRecord, ...] = ()
    approvals: tuple[Rf1086ApprovalRecord, ...] = ()
    production_submissions: tuple[Rf1086ProductionSubmissionRecord, ...] = ()
    feedback_artifacts: tuple[Rf1086FeedbackArtifactRecord, ...] = ()
    actions: tuple[Rf1086ActionAvailability, ...] = ()


@dataclass(frozen=True, slots=True)
class Rf1086ArchiveProductionEventRecord(_ImmutableRf1086Value):
    id: str
    company_id: str
    income_year: int
    submission_id: str
    operation_name: str
    operation_state: str
    attempt: int
    body_hash: str | None
    idempotency_key: str | None
    authority_reference: str | None
    failure_class: str | None
    resulting_status: str
    artifact_hashes: tuple[str, ...]
    safe_error_code: str | None
    correlation_id: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class Rf1086ArchiveFeedbackArtifactRecord(Rf1086FeedbackArtifactRecord):
    """Documents retains original bytes; RF retains their provider attribution."""
    authority_reference: str


@dataclass(frozen=True, slots=True)
class Rf1086ArchiveSnapshot(_ImmutableRf1086Value):
    """Year-scoped filing history, original production evidence and company-wide review."""

    company_id: CompanyId
    income_year: IncomeYear
    previews: tuple[Rf1086PreviewRecord, ...] = ()
    simulations: tuple[Rf1086SimulationRecord, ...] = ()
    review_comments: tuple[Rf1086ReviewCommentRecord, ...] = ()
    permissions: tuple[Rf1086FilingPermissionRecord, ...] = ()
    test_evidence: tuple[Rf1086TestEvidenceRecord, ...] = ()

    approvals: tuple[Rf1086ApprovalRecord, ...] = ()
    production_submissions: tuple[Rf1086ProductionSubmissionRecord, ...] = ()
    production_events: tuple[Rf1086ArchiveProductionEventRecord, ...] = ()
    feedback_artifacts: tuple[Rf1086ArchiveFeedbackArtifactRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class Rf1086OpeningBasis(_ImmutableRf1086Value):
    company_id: CompanyId
    opening_snapshot_id: OpeningSnapshotId
    income_year: IncomeYear
    case: Rf1086Case
    source_digest: str


@dataclass(frozen=True, slots=True)
class Rf1086PreparedPreview(_ImmutableRf1086Value):
    basis: Rf1086OpeningBasis
    rendered: Rf1086RenderedPreview


@dataclass(frozen=True, slots=True)
class Rf1086SimulationBasis(_ImmutableRf1086Value):
    preview: Rf1086PreviewRecord
    source_digest: str
    annual_readiness_ready: bool
    hard_review_blocks: int
    blocking_override_targets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Rf1086PreparedSimulation(_ImmutableRf1086Value):
    basis: Rf1086SimulationBasis
    result: Mapping[str, object]
    payload_hash: str
    idempotency_key: str
    feedback_items: tuple[Mapping[str, object], ...]
    receipt_metadata: Mapping[str, object]
    submitted_payload_ref: Mapping[str, object]
    submitted_payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Rf1086ApprovalBasis(_ImmutableRf1086Value):
    preview: Rf1086PreviewRecord
    organization_number: str
    source_digest: str


@dataclass(frozen=True, slots=True)
class Rf1086PreparedApproval(_ImmutableRf1086Value):
    basis: Rf1086ApprovalBasis
    manifest: Mapping[str, object]
    manifest_hash: str
    adapter_version: str = "rf1086-production-v1"


@dataclass(frozen=True, slots=True)
class Rf1086MigrationInventory(_ImmutableRf1086Value):
    reference: str
    version: str
    digest: str
    company_id: CompanyId
    income_year: IncomeYear
    family_counts: Mapping[str, int]
    family_digests: Mapping[str, str]
    quarantined_count: int
    reconciled: bool
    scope: Literal["talli_recorded_rf1086"] = "talli_recorded_rf1086"


@dataclass(frozen=True, slots=True)
class Rf1086JournalEvent(_ImmutableRf1086Value):
    id: str
    submission_id: str
    sequence: int
    operation_name: str
    state: str
    body_hash: str | None
    idempotency_key: str | None
    authority_reference: str | None
    failure_classification: str | None
    safe_error_code: str | None
    created_at: str
    attempt: int
    resulting_status: str
    source_digest: str


@dataclass(frozen=True, slots=True)
class Rf1086OpeningSource(_ImmutableRf1086Value):
    """Current stored opening extent, including a non-renderable input basis."""

    company_id: CompanyId
    opening_snapshot_id: OpeningSnapshotId
    income_year: IncomeYear
    source_digest: str
    shareholder_count: int


@dataclass(frozen=True, slots=True)
class Rf1086SourceSnapshot(_ImmutableRf1086Value):
    workspace: Rf1086WorkspaceSnapshot
    inventory: Rf1086MigrationInventory | None
    journal_events: tuple[Rf1086JournalEvent, ...]
    opening_facts: tuple[Rf1086OpeningBasis, ...]
    as_of: Timestamp
    complete_enumeration: bool
    opening_sources: tuple[Rf1086OpeningSource, ...]


@dataclass(frozen=True, slots=True)
class Rf1086SourceEvidence(_ImmutableRf1086Value):
    company_id: CompanyId
    income_year: IncomeYear
    reference: str
    version: str
    digest: str
    evaluated_at: Timestamp
    obligation: Literal["aksjonaerregisteroppgaven"] = "aksjonaerregisteroppgaven"


@dataclass(frozen=True, slots=True)
class Rf1086HistoryCoverage(_ImmutableRf1086Value):
    status: Literal["complete", "incomplete", "unavailable"]
    evidence_reference: str | None
    reasons: tuple[str, ...]
    as_of: Timestamp
    event_count: int
    event_watermark: int | None
    scope: Literal["talli_recorded_rf1086"] = "talli_recorded_rf1086"


@dataclass(frozen=True, slots=True)
class Rf1086ProductionAttemptFact(_ImmutableRf1086Value):
    submission_id: str
    state: str
    feedback_state: str
    effect_status: Literal["confirmed", "unknown", "not_observed"]
    observed_at: str | None
    evidence_event_ids: tuple[str, ...]
    document_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Rf1086CorrectionLink(_ImmutableRf1086Value):
    submission_id: str
    supersedes_submission_id: str


@dataclass(frozen=True, slots=True)
class Rf1086IncidentFact(_ImmutableRf1086Value):
    event_id: str
    submission_id: str
    failure_classification: str | None
    safe_error_code: str | None
    observed_at: str
    attribution: Literal["unknown"] = "unknown"


@dataclass(frozen=True, slots=True)
class Rf1086WarningFact(_ImmutableRf1086Value):
    code: str
    message: str
    source: Literal["filing_previews", "filing_overrides"]
    source_id: str
    risk_level: str | None
    accepted: bool
    accepted_by: str | None
    accepted_at: str | None


@dataclass(frozen=True, slots=True)
class Rf1086OutcomeFact(_ImmutableRf1086Value):
    """An RF journal observation, not the authority's unobserved event time."""

    event_id: str
    submission_id: str
    resulting_status: str
    observed_at: str
    attribution: Literal["unknown"] = "unknown"


@dataclass(frozen=True, slots=True)
class Rf1086SourceFacts(_ImmutableRf1086Value):
    evidence: Rf1086SourceEvidence
    readiness_status: Literal["ready", "blocked", "unavailable"]
    hard_blocks: tuple[str, ...]
    warnings: tuple[Rf1086WarningFact, ...]
    history_coverage: Rf1086HistoryCoverage
    production_attempts: tuple[Rf1086ProductionAttemptFact, ...]
    correction_links: tuple[Rf1086CorrectionLink, ...]
    incidents: tuple[Rf1086IncidentFact, ...]
    outcomes: tuple[Rf1086OutcomeFact, ...]


@dataclass(frozen=True, slots=True)
class VerifyRf1086SourceEvidenceQuery(_ImmutableRf1086Value):
    query: Rf1086SourceQuery
    evidence: Rf1086SourceEvidence


class Rf1086PreparationPersistence(Protocol):
    async def legacy_archive_source(self, query: Rf1086ArchiveQuery) -> Rf1086ArchiveSnapshot: ...
    async def archive_source(self, query: Rf1086ArchiveQuery) -> Rf1086ArchiveSnapshot: ...
    async def preview_record(self, query: ReadRf1086PreviewQuery) -> Rf1086PreviewRecord | None: ...
    async def load_opening(self, command: GenerateRf1086PreviewCommand) -> Rf1086OpeningBasis: ...
    async def record_preview(self, command: GenerateRf1086PreviewCommand, prepared: Rf1086PreparedPreview) -> Rf1086RecordedResult: ...
    async def record_override(self, command: RecordRf1086OverrideCommand) -> Rf1086RecordedResult: ...
    async def add_review_comment(self, command: AddRf1086ReviewCommentCommand) -> Rf1086RecordedResult: ...
    async def acknowledge_review_comment(self, command: AcknowledgeRf1086ReviewCommentCommand) -> Rf1086RecordedResult: ...
    async def load_simulation_basis(self, command: ConfirmRf1086SimulationCommand) -> Rf1086SimulationBasis: ...
    async def record_simulation(self, command: ConfirmRf1086SimulationCommand, prepared: Rf1086PreparedSimulation) -> Rf1086RecordedResult: ...
    async def confirm_filing_permission(self, command: ConfirmRf1086FilingPermissionCommand) -> Rf1086RecordedResult: ...
    async def record_test_evidence(self, command: RecordRf1086TestEvidenceCommand) -> Rf1086RecordedResult: ...
    async def load_approval_basis(self, command: ApproveRf1086ProductionCommand) -> Rf1086ApprovalBasis: ...
    async def record_approval(self, command: ApproveRf1086ProductionCommand, prepared: Rf1086PreparedApproval) -> Rf1086RecordedResult: ...
    async def workspace(self, query: Rf1086WorkspaceQuery) -> Rf1086WorkspaceSnapshot: ...
    async def source_snapshot(self, query: Rf1086SourceQuery) -> Rf1086SourceSnapshot: ...


class ShareholderRegisterFilingQueries(Protocol):
    async def legacy_archive_source(self, query: Rf1086ArchiveQuery) -> Rf1086ArchiveSnapshot: ...
    async def archive_source(self, query: Rf1086ArchiveQuery) -> Rf1086ArchiveSnapshot: ...
    async def read_preview(self, query: ReadRf1086PreviewQuery) -> Rf1086PreviewRecord | None: ...
    async def workspace(self, query: Rf1086WorkspaceQuery) -> Rf1086WorkspaceSnapshot: ...
    async def source_facts(self, query: Rf1086SourceQuery) -> Rf1086SourceFacts: ...
    async def verify_source_evidence(self, query: VerifyRf1086SourceEvidenceQuery) -> bool: ...


def rf1086_payload_utf8_bytes(value: str) -> bytes:
    from .production import _js_utf8_bytes
    return _js_utf8_bytes(value)


def parse_rf1086_case(value: object) -> Rf1086Case:
    from .case_parser import parse_rf1086_case as parse
    return parse(value)


def generate_rf1086_documents(case: Rf1086Case) -> Rf1086DocumentSet:
    from .rendering import generate_rf1086
    return generate_rf1086(case)


def assess_rf1086_readiness(case: Rf1086Case) -> Rf1086ReadinessResult:
    from .readiness import assess_rf1086_readiness as assess
    return assess(case)


def render_rf1086_preview(case: Rf1086Case) -> Rf1086RenderedPreview:
    from .rendering import render_rf1086_preview as render
    return render(case)


def render_no_activity_rf1086_preview(value: Rf1086Case | Mapping[str, object]) -> Rf1086RenderedPreview:
    from .rendering import render_no_activity_rf1086_preview as render
    return render(value)


def create_rf1086_preparation_service(persistence: Rf1086PreparationPersistence) -> Rf1086PreparationOperations:
    from .preparation import Rf1086PreparationService
    return Rf1086PreparationService(persistence)




@dataclass(frozen=True, slots=True)
class ReadRf1086PreviewQuery(_ImmutableRf1086Value):
    preview_id: PreviewId
    actor_id: ActorId


def resume_production_operation(latest: ProductionOperation, *, is_mutation: bool) -> ProductionOperation:
    from .production import resume_production_operation as resume
    return resume(latest, is_mutation=is_mutation)


def create_rf1086_feedback_artifact_persistence_error(error: object, *, integrity_failure: bool = False):
    from .feedback import create_rf1086_feedback_artifact_persistence_error as create
    return create(error, integrity_failure=integrity_failure)


def rf1086_xml_schema(document: Literal["hovedskjema", "underskjema"]) -> bytes:
    from importlib.resources import files
    names = {"hovedskjema": "aksjonaerregisteroppgaveHovedskjema.xsd", "underskjema": "aksjonaerregisteroppgaveUnderskjema.xsd"}
    if document not in names:
        raise ShareholderRegisterFilingError.invalid_input()
    return files(__package__).joinpath("schemas", names[document]).read_bytes()



class OpeningSnapshotPersistence(Protocol):
    actor_id: ActorId
    async def record_opening_snapshot(self, command: RecordOpeningSnapshotCommand) -> OpeningSnapshotId: ...


class OpeningSnapshotCommands(Protocol):
    async def record_opening_snapshot(self, command: RecordOpeningSnapshotCommand) -> OpeningSnapshotId: ...


def create_opening_snapshot_service(persistence: OpeningSnapshotPersistence) -> OpeningSnapshotCommands:
    from .preparation import OpeningSnapshotService
    return OpeningSnapshotService(persistence)



async def execute_journaled_rf1086_production(input: JournaledRf1086ProductionInput, *, journal: ProductionOperationJournal, authority_client: Rf1086MutationAuthority) -> JournaledRf1086ProductionResult:
    from .production import execute_journaled_rf1086_production as execute
    return await execute(input, journal=journal, authority_client=authority_client)


def rf1086_current_manifest_hash(preview: Rf1086Preview, *, actor_id: str, organization_number: str, approved_manifest: Mapping[str, object] | None = None) -> str:
    from .production import rf1086_current_manifest_hash as digest
    return digest(preview, actor_id=actor_id, organization_number=organization_number, approved_manifest=approved_manifest)


def rf1086_production_document_order(preview: Rf1086Preview) -> tuple[str, ...]:
    from .production import rf1086_production_document_order as order
    return order(preview)


async def reconcile_journaled_rf1086_production(journal: Rf1086ProductionJournal, authority: Rf1086ReadOnlyAuthority, input: Rf1086ReconciliationInput, *, discovery: Rf1086FeedbackDiscovery | None = None, initial_poll: bool | None = None, sleep: Callable[[int], Awaitable[None]] | None = None) -> Rf1086ReconciliationResult:
    from .feedback import reconcile_journaled_rf1086_production as reconcile
    return await reconcile(journal, authority, input, discovery=discovery, initial_poll=initial_poll, sleep=sleep)



@dataclass(frozen=True, slots=True)
class Rf1086CompanyFacts(_ImmutableRf1086Value):
    company_id: CompanyId
    org_number: str
    name: str
    address: str | None
    postal_code: str | None
    city: str | None


@dataclass(frozen=True, slots=True)
class Rf1086OpeningShareholderFact(_ImmutableRf1086Value):
    id: str
    kind: Rf1086ShareholderKind
    name: str
    national_id: str | None
    org_number: str | None
    share_count: int


@dataclass(frozen=True, slots=True)
class Rf1086OpeningFacts(_ImmutableRf1086Value):
    company_id: CompanyId
    opening_snapshot_id: OpeningSnapshotId
    income_year: IncomeYear
    share_capital: float
    share_count: int
    nominal_value: float
    shareholders: tuple[Rf1086OpeningShareholderFact, ...]


def build_no_activity_rf1086_case(*, company: Rf1086CompanyFacts, opening: Rf1086OpeningFacts) -> Rf1086Case:
    from .rendering import build_no_activity_rf1086_case as build
    return build(company=company, opening=opening)



class Rf1086PreparationOperations(ShareholderRegisterFilingQueries, Protocol):
    async def generate_source_preview(self, command: GenerateRf1086SourcePreview) -> Rf1086SourcePreview: ...
    async def generate_preview(self, command: GenerateRf1086PreviewCommand) -> Rf1086RecordedResult: ...
    async def record_override(self, command: RecordRf1086OverrideCommand) -> Rf1086RecordedResult: ...
    async def add_review_comment(self, command: AddRf1086ReviewCommentCommand) -> Rf1086RecordedResult: ...
    async def acknowledge_review_comment(self, command: AcknowledgeRf1086ReviewCommentCommand) -> Rf1086RecordedResult: ...
    async def confirm_simulation(self, command: ConfirmRf1086SimulationCommand) -> Rf1086RecordedResult: ...
    async def confirm_filing_permission(self, command: ConfirmRf1086FilingPermissionCommand) -> Rf1086RecordedResult: ...
    async def record_test_evidence(self, command: RecordRf1086TestEvidenceCommand) -> Rf1086RecordedResult: ...
    async def approve_production(self, command: ApproveRf1086ProductionCommand) -> Rf1086RecordedResult: ...



Rf1086Adapter = TypeVar("Rf1086Adapter", bound=type[object])


def rf1086_adapter(contract: type[object]) -> Callable[[Rf1086Adapter], Rf1086Adapter]:
    """Declare an RF outbound binding without runtime registration/global state."""
    def declare(adapter: Rf1086Adapter) -> Rf1086Adapter:
        _ = contract
        return adapter
    return declare



@dataclass(frozen=True, slots=True)
class Rf1086OfflineSimulationInput(_ImmutableRf1086Value):
    filing: str
    company_id: str
    income_year: int
    user_id: str
    preview_id: str
    hovedskjema_xml: str = field(repr=False)
    underskjema_xml: Mapping[str, str] = field(repr=False)


@dataclass(frozen=True, slots=True)
class Rf1086OfflineSimulationCall(_ImmutableRf1086Value):
    endpoint: str
    body_hash: str
    idempotency_key: str
    status: Literal["prepared"]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Rf1086OfflineSimulationResult(_ImmutableRf1086Value):
    filing: str
    company_id: str
    income_year: int
    status: Literal["receipt_stored"]
    authority_confirmed_by: str
    authority_confirmed_at: datetime
    preview_confirmed_by: str
    preview_confirmed_at: datetime
    calls: tuple[Rf1086OfflineSimulationCall, ...]
    receipt_id: str
    feedback_document_ids: tuple[str, ...]
    failure_code: None = None
    failure_message: None = None


@dataclass(frozen=True, slots=True)
class Rf1086ValidationInput(_ImmutableRf1086Value):
    case_path: str
    contents: str | None
    read_error: str | None = None


@dataclass(frozen=True, slots=True)
class Rf1086ValidationCaseResult(_ImmutableRf1086Value):
    case_path: str
    case_id: str | None
    outcome: Literal["pass", "warning", "blocked"]
    assumptions: tuple[str, ...]
    issues: tuple[str, ...]
    generated_documents: int


@dataclass(frozen=True, slots=True)
class Rf1086ValidationReport(_ImmutableRf1086Value):
    filing: str
    source: str
    limitations: tuple[str, ...]
    cases: tuple[Rf1086ValidationCaseResult, ...]


class Rf1086CodeVerificationStatus(StrEnum):
    VERIFIED = "verified"
    REJECTED = "rejected"
    STILL_BLOCKED = "still_blocked"
    EXCLUDED_FROM_LIVE_SCOPE = "excluded_from_live_scope"


@dataclass(frozen=True, slots=True)
class Rf1086CodeDecision(_ImmutableRf1086Value):
    event: str
    field_name: str
    code_value: str
    public_label: str
    verification_status: Rf1086CodeVerificationStatus
    production_blocker: bool
    authority_note: str
    sources: tuple[str, ...]


def parse_rf1086_offline_simulation_input(value: Mapping[str, object]) -> Rf1086OfflineSimulationInput:
    from .offline import parse_offline_simulation_input
    return parse_offline_simulation_input(value)


def simulate_rf1086_offline_submission(input: Rf1086OfflineSimulationInput, *, clock: Callable[[], datetime] | None = None) -> Rf1086OfflineSimulationResult:
    from .offline import simulate_offline_submission
    return simulate_offline_submission(input, clock=clock)


def validate_rf1086_cases(inputs: tuple[Rf1086ValidationInput, ...], *, source: str = "public/synthetic") -> Rf1086ValidationReport:
    from .validation import validate_cases
    return validate_cases(inputs, source=source)


def format_rf1086_readiness_report(result: Rf1086ReadinessResult) -> str:
    from .readiness import format_readiness_report
    return format_readiness_report(result)


def rf1086_code_decisions() -> tuple[Rf1086CodeDecision, ...]:
    from .codes import rf1086_code_decisions as decisions
    return decisions()


def rf1086_code_decisions_for_case(case: Rf1086Case) -> tuple[Rf1086CodeDecision, ...]:
    from .codes import rf1086_code_decisions_for_case as decisions
    return decisions(case)


def rf1086_production_code_blockers(case: Rf1086Case | None = None) -> tuple[Rf1086CodeDecision, ...]:
    from .codes import production_code_blockers, production_code_blockers_for_case
    return production_code_blockers() if case is None else production_code_blockers_for_case(case)


def rf1086_production_scope_exclusions(case: Rf1086Case | None = None) -> tuple[Rf1086CodeDecision, ...]:
    from .codes import production_scope_exclusions, production_scope_exclusions_for_case
    return production_scope_exclusions() if case is None else production_scope_exclusions_for_case(case)

class Rf1086YearSourceError(ValueError):
    """Closed diagnostics: never include shareholder identifiers or source data."""


@dataclass(frozen=True, slots=True)
class Rf1086YearSourceId:
    value: str

    def __post_init__(self):
        from .year_source import _decimal, _require, _sha, _uuid
        _uuid(self.value)


@dataclass(frozen=True, slots=True)
class Rf1086PaidInSourceFacts:
    """All four values are required, even when zero; they are never inferred."""

    opening_capital: Decimal
    closing_capital: Decimal
    opening_premium: Decimal
    closing_premium: Decimal

    def __post_init__(self):
        from .year_source import _decimal, _require, _sha, _uuid
        for field in fields(self):
            object.__setattr__(self, field.name, _decimal(getattr(self, field.name)))


@dataclass(frozen=True, slots=True)
class Rf1086YearDocumentEvidence:
    document_id: str
    company_id: CompanyId
    content_version_sha256: str
    content_sha256: str
    document_type: str
    integrity_status: str
    byte_length: int
    created_at: datetime
    metadata_sha256: str
    source_income_year: IncomeYear | None = None

    def __post_init__(self):
        from .year_source import _decimal, _require, _sha, _uuid
        _uuid(self.document_id)
        _sha(self.content_sha256)
        _sha(self.content_version_sha256)
        _sha(self.metadata_sha256)
        _require(self.content_version_sha256 == self.content_sha256
                 and isinstance(self.document_type, str) and bool(self.document_type.strip())
                 and self.integrity_status in {"attached", "generated_unsigned", "signed_owner_attested", "stored"}
                 and type(self.byte_length) is int and self.byte_length > 0
                 and isinstance(self.created_at, datetime) and self.created_at.tzinfo is not None,
                 "rf1086_source_document_version_invalid")


@dataclass(frozen=True, slots=True)
class Rf1086YearEventEvidence:
    event_index: int
    event_sha256: str
    document_ids: tuple[str, ...]
    governance_receipt_id: str | None = None

    def __post_init__(self):
        from .year_source import _decimal, _require, _sha, _uuid
        object.__setattr__(self, "document_ids", tuple(self.document_ids))
        _require(type(self.event_index) is int and self.event_index >= 0,
                 "rf1086_source_event_index_invalid")
        _sha(self.event_sha256)
        for reference in self.document_ids:
            _uuid(reference)
        if self.governance_receipt_id is not None:
            _uuid(self.governance_receipt_id)


@dataclass(frozen=True, slots=True)
class Rf1086YearGovernanceReceipt:
    """Projection of a final owner receipt; never constructed from HTTP input.

    economic_sha256 covers independently read governance facts in the normalized
    shape returned by rf1086_governance_economic_facts. Register evidence must
    predate, and be independent of, the full-year source referencing this receipt.
    """

    receipt_id: str
    company_id: CompanyId
    income_year: IncomeYear
    event_type: str
    economic_sha256: str
    finalization_sha256: str
    signed_document_hashes: tuple[str, ...]
    active: bool
    register_observation_id: str | None = None
    register_observation_sha256: str | None = None

    def __post_init__(self):
        from .year_source import _decimal, _require, _sha, _uuid
        object.__setattr__(self, "signed_document_hashes", tuple(self.signed_document_hashes))
        _uuid(self.receipt_id)
        _sha(self.economic_sha256)
        _sha(self.finalization_sha256)
        for value in self.signed_document_hashes:
            _sha(value)
        if self.register_observation_id is not None:
            _uuid(self.register_observation_id)
        if self.register_observation_sha256 is not None:
            _sha(self.register_observation_sha256)


@dataclass(frozen=True, slots=True)
class Rf1086VerifiedYearSourceContext:
    """Trusted workflow-only input; no transport deserialization is permitted.

    complete_governance_enumeration means all relevant finalized dividends and
    registered capital events for this company/year, not merely selected IDs.
    An adapter must attest this with its public query contract before use.
    """

    actor_id: ActorId
    accepted_owner: bool
    company_id: CompanyId
    income_year: IncomeYear
    company: Rf1086Company
    company_identity_sha256: str
    documents: tuple[Rf1086YearDocumentEvidence, ...]
    governance_receipts: tuple[Rf1086YearGovernanceReceipt, ...]
    complete_governance_enumeration: bool
    governance_enumeration_sha256: str

    def __post_init__(self):
        from .year_source import _decimal, _require, _sha, _uuid
        object.__setattr__(self, "documents", tuple(self.documents))
        object.__setattr__(self, "governance_receipts", tuple(self.governance_receipts))
        _sha(self.company_identity_sha256)
        _sha(self.governance_enumeration_sha256)


@dataclass(frozen=True, slots=True)
class RecordRf1086YearSource:
    company_id: CompanyId
    actor_id: ActorId
    income_year: IncomeYear
    case: Rf1086Case
    paid_in: Rf1086PaidInSourceFacts
    documents: tuple[Rf1086YearDocumentEvidence, ...]
    opening_document_ids: tuple[str, ...]
    closing_document_ids: tuple[str, ...]
    paid_in_document_ids: tuple[str, ...]
    event_evidence: tuple[Rf1086YearEventEvidence, ...]
    identities_reviewed: bool
    complete_year_confirmed: bool
    paid_in_reviewed: bool
    no_activity_confirmed: bool
    supersedes_source_id: Rf1086YearSourceId | None = None
    supersedes_source_sha256: str | None = None
    correction_reason: str | None = None

    def __post_init__(self):
        from .year_source import _decimal, _require, _sha, _uuid
        for name in ("documents", "opening_document_ids", "closing_document_ids",
                     "paid_in_document_ids", "event_evidence"):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class Rf1086YearSourceFreshness:
    source_id: Rf1086YearSourceId
    source_sha256: str
    company_identity_sha256: str
    documents_sha256: str
    governance_receipts_sha256: str
    governance_enumeration_sha256: str


@dataclass(frozen=True, slots=True)
class Rf1086YearSourceSnapshot(_ImmutableRf1086Value):
    source_id: Rf1086YearSourceId
    version: int
    company_id: CompanyId
    income_year: IncomeYear
    command: RecordRf1086YearSource
    confirmed_by: ActorId
    confirmed_at: datetime
    governance_receipts: tuple[Rf1086YearGovernanceReceipt, ...]
    source_sha256: str
    case_sha256: str
    freshness: Rf1086YearSourceFreshness


class Rf1086YearSourcePersistence(Protocol):
    """Authenticated RF storage; verified context comes only from the workflow."""

    async def record_year_source(self, command: RecordRf1086YearSource, *,
            context: Rf1086VerifiedYearSourceContext,
            idempotency_key: IdempotencyKey) -> Rf1086YearSourceSnapshot: ...

    async def read_current_year_source(self, query: Rf1086SourceQuery) -> Rf1086YearSourceSnapshot | None: ...

    async def read_year_source(self, query: Rf1086SourceQuery,
            source_id: Rf1086YearSourceId) -> Rf1086YearSourceSnapshot | None: ...


def serialize_rf1086_year_source(snapshot: Rf1086YearSourceSnapshot) -> str:
    from .year_source_storage import serialize
    return serialize(snapshot)


def parse_rf1086_year_source(value: str) -> Rf1086YearSourceSnapshot:
    from .year_source_storage import parse
    return parse(value)


def prepare_rf1086_year_source(command: RecordRf1086YearSource, *,
        context: Rf1086VerifiedYearSourceContext, source_id: Rf1086YearSourceId,
        confirmed_at: datetime, previous: Rf1086YearSourceSnapshot | None = None) -> Rf1086YearSourceSnapshot:
    from .year_source import prepare_rf1086_year_source as prepare
    return prepare(command, context=context, source_id=source_id, confirmed_at=confirmed_at, previous=previous)


def assert_rf1086_year_source_fresh(snapshot: Rf1086YearSourceSnapshot, *,
        current_source_id: Rf1086YearSourceId, current_source_sha256: str,
        context: Rf1086VerifiedYearSourceContext) -> None:
    from .year_source import assert_rf1086_year_source_fresh as validate
    validate(snapshot, current_source_id=current_source_id, current_source_sha256=current_source_sha256, context=context)


def assert_rf1086_year_source_integrity(snapshot: Rf1086YearSourceSnapshot) -> None:
    from .year_source import assert_rf1086_year_source_integrity as validate
    validate(snapshot)


def assert_rf1086_year_source_replay(snapshot: Rf1086YearSourceSnapshot, command: RecordRf1086YearSource) -> None:
    from .year_source import assert_rf1086_year_source_replay as validate
    validate(snapshot, command)


def rf1086_year_source_digest(value: object) -> str:
    from .year_source import rf1086_year_source_digest as digest
    return digest(value)


def rf1086_event_register_states(case: Rf1086Case, event_index: int) -> tuple[Rf1086RegisteredShareState, Rf1086RegisteredShareState]:
    """Exact capital-event states from the same full-case readiness replay."""
    from .readiness import event_register_states
    return event_register_states(case, event_index)


def rf1086_governance_economic_facts(event: Rf1086DividendEvent | Rf1086CashIssueEvent |
        Rf1086CashNominalIncreaseEvent | Rf1086LossCoveringReductionEvent) -> Mapping[str, object]:
    from .year_source import rf1086_governance_economic_facts as normalize
    return _freeze_rf1086_value(normalize(event))


class Rf1086RegisterObservationError(ValueError):
    """Closed diagnostics for independent registered-share observations."""


@dataclass(frozen=True, slots=True)
class Rf1086RegisterObservationId:
    value: str

    def __post_init__(self):
        from .register_observation import validate_identity
        validate_identity(self.value)


@dataclass(frozen=True, slots=True)
class Rf1086RegisterHolding:
    shareholder_id: str
    name: str
    kind: Literal["norwegian_person", "norwegian_company"]
    identifier: str
    share_count: int


@dataclass(frozen=True, slots=True)
class Rf1086RegisteredShareState(_ImmutableRf1086Value):
    """Complete one-class register state; tax paid-in balances are separate."""

    share_capital: Decimal
    share_count: int
    nominal_value: Decimal
    holdings: tuple[Rf1086RegisterHolding, ...]


@dataclass(frozen=True, slots=True)
class Rf1086RegisterDocumentEvidence:
    """Original independent document bytes verified by the Documents owner.

    role describes owner-reviewed content, not a claim of automated extraction
    or signedness. Filing-generated or Governance-derived documents cannot be
    attested as independent evidence by the trusted capture workflow.
    """

    document_id: str
    company_id: CompanyId
    content_version_sha256: str
    content_sha256: str
    byte_length: int
    document_type: str
    integrity_status: str
    created_at: datetime
    metadata_sha256: str
    role: Literal["register_before", "register_after", "registration"]
    source_income_year: IncomeYear | None = None


@dataclass(frozen=True, slots=True)
class RecordRf1086RegisterObservation(_ImmutableRf1086Value):
    company_id: CompanyId
    actor_id: ActorId
    income_year: IncomeYear
    effective_at: datetime
    event_kind: Literal["cash_issue", "cash_nominal_increase", "loss_covering_reduction"]
    before: Rf1086RegisteredShareState
    after: Rf1086RegisteredShareState
    documents: tuple[Rf1086RegisterDocumentEvidence, ...]
    complete_register_confirmed: bool
    registration_confirmed: bool
    single_share_class_confirmed: bool
    supersedes_observation_id: Rf1086RegisterObservationId | None = None
    supersedes_observation_sha256: str | None = None
    correction_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Rf1086VerifiedRegisterObservationContext(_ImmutableRf1086Value):
    """Internal workflow attestation; never accept from HTTP input.

    Independent originals and accepted owner must be checked at capture. This
    value does not create a cross-capability lease or prove document semantics.
    """

    actor_id: ActorId
    accepted_owner: bool
    company_id: CompanyId
    income_year: IncomeYear
    documents: tuple[Rf1086RegisterDocumentEvidence, ...]
    independent_originals_verified: bool


@dataclass(frozen=True, slots=True)
class Rf1086RegisterObservationSnapshot:
    observation_id: Rf1086RegisterObservationId
    version: int
    command: RecordRf1086RegisterObservation
    confirmed_at: datetime
    fact_sha256: str


@dataclass(frozen=True, slots=True)
class Rf1086RegisterObservationMatchQuery:
    observation_id: Rf1086RegisterObservationId
    revision: int
    fact_sha256: str
    company_id: CompanyId
    income_year: IncomeYear
    effective_at: datetime
    event_kind: str
    before: Rf1086RegisteredShareState
    after: Rf1086RegisteredShareState


def prepare_rf1086_register_observation(command: RecordRf1086RegisterObservation, *,
        context: Rf1086VerifiedRegisterObservationContext,
        observation_id: Rf1086RegisterObservationId, confirmed_at: datetime,
        previous: Rf1086RegisterObservationSnapshot | None = None) -> Rf1086RegisterObservationSnapshot:
    from .register_observation import prepare
    return prepare(command, context=context, observation_id=observation_id,
                   confirmed_at=confirmed_at, previous=previous)


def assert_rf1086_register_observation_integrity(snapshot: Rf1086RegisterObservationSnapshot) -> None:
    from .register_observation import assert_integrity
    assert_integrity(snapshot)


def verify_rf1086_register_observation(snapshot: Rf1086RegisterObservationSnapshot,
        query: Rf1086RegisterObservationMatchQuery) -> Rf1086RegisterObservationSnapshot:
    """Match an exact persisted observation; does not establish live currentness."""
    from .register_observation import verify
    return verify(snapshot, query)


def rf1086_register_observation_request_digest(command: RecordRf1086RegisterObservation) -> str:
    from .register_observation import request_digest
    return request_digest(command)


class Rf1086RegisterObservationPersistence(Protocol):
    """RF-owned immutable observations, with exact current-lineage reads."""

    async def record_register_observation(self, command: RecordRf1086RegisterObservation, *,
            context: Rf1086VerifiedRegisterObservationContext,
            idempotency_key: IdempotencyKey) -> Rf1086RegisterObservationSnapshot: ...

    async def read_register_observation(self, query: Rf1086SourceQuery,
            observation_id: Rf1086RegisterObservationId) -> Rf1086RegisterObservationSnapshot | None: ...

    async def read_current_register_observation(self, query: Rf1086SourceQuery,
            observation_id: Rf1086RegisterObservationId) -> Rf1086RegisterObservationSnapshot | None: ...


def serialize_rf1086_register_observation(snapshot: Rf1086RegisterObservationSnapshot) -> str:
    from .year_source_storage import serialize_observation
    return serialize_observation(snapshot)


def parse_rf1086_register_observation(value: str) -> Rf1086RegisterObservationSnapshot:
    from .year_source_storage import parse_observation
    return parse_observation(value)



@dataclass(frozen=True, slots=True)
class GenerateRf1086SourcePreview:
    """Internal command after fresh source verification by the application."""

    company_id: CompanyId
    income_year: IncomeYear
    source: Rf1086YearSourceSnapshot


@dataclass(frozen=True, slots=True)
class Rf1086PreparedSourcePreview:
    source: Rf1086YearSourceSnapshot
    rendered: Rf1086RenderedPreview


@dataclass(frozen=True, slots=True)
class Rf1086SourcePreview(_ImmutableRf1086Value):
    preview_id: PreviewId
    company_id: CompanyId
    income_year: IncomeYear
    source_id: Rf1086YearSourceId
    source_sha256: str
    case_sha256: str
    readiness_status: str
    readiness_issues: tuple[Rf1086ReadinessIssue, ...]
    preview_text: str
    hovedskjema_xml: str | None
    underskjema_xml: Mapping[str, str] | None
    rendering_profile: str = "rf1086-full-year-v1"


class Rf1086SourcePreviewPreparation(Protocol):
    """Capture immutable previews while locking the exact current source."""

    async def capture_source_preview(self, command: GenerateRf1086SourcePreview,
            prepared: Rf1086PreparedSourcePreview) -> Rf1086SourcePreview: ...

    async def source_preview(self, preview_id: PreviewId) -> Rf1086SourcePreview: ...


def assert_rf1086_source_preview_matches(preview: Rf1086SourcePreview,
        source: Rf1086YearSourceSnapshot) -> None:
    from .source_preview import assert_matches
    assert_matches(preview, source)


def serialize_rf1086_source_preview(preview: Rf1086SourcePreview) -> str:
    from .source_preview import serialize
    return serialize(preview)


def parse_rf1086_source_preview(value: str) -> Rf1086SourcePreview:
    from .source_preview import parse
    return parse(value)


__all__ = ['GenerateRf1086SourcePreview', 'Rf1086PreparedSourcePreview', 'Rf1086SourcePreview', 'Rf1086SourcePreviewPreparation', 'assert_rf1086_source_preview_matches', 'serialize_rf1086_source_preview', 'parse_rf1086_source_preview', 'rf1086_event_register_states', 'ShareholderRegisterFilingErrorCode', 'ShareholderRegisterFilingError', 'OpeningSnapshotId', 'OpeningShareholder', 'RecordOpeningSnapshotCommand', 'ShareholderRegisterFilingCommands', 'Rf1086ShareholderKind', 'Rf1086Company', 'Rf1086ShareSnapshot', 'Rf1086Shareholder', 'Rf1086ShareholderSnapshot', 'Rf1086FormationAllocation', 'Rf1086FormationEvent', 'Rf1086CashIssueEvent', 'Rf1086NominalIncreaseAllocation', 'Rf1086CashNominalIncreaseEvent', 'Rf1086LossCoveringReductionEvent', 'Rf1086ShareSaleEvent', 'Rf1086DividendAllocation', 'Rf1086DividendEvent', 'Rf1086Case', 'Rf1086ReadinessIssue', 'Rf1086ReadinessResult', 'Rf1086DocumentSet', 'Rf1086RenderedPreview', 'PreviewId', 'OverrideId', 'ReviewCommentId', 'ApprovalId', 'SubmissionId', 'TestEvidenceId', 'Rf1086RecordedResult', 'GenerateRf1086PreviewCommand', 'RecordRf1086OverrideCommand', 'AddRf1086ReviewCommentCommand', 'AcknowledgeRf1086ReviewCommentCommand', 'ConfirmRf1086SimulationCommand', 'ConfirmRf1086FilingPermissionCommand', 'RecordRf1086TestEvidenceCommand', 'ApproveRf1086ProductionCommand', 'SendApprovedRf1086Command', 'ReconcileRf1086FeedbackCommand', 'Rf1086WorkspaceQuery', 'Rf1086ArchiveQuery', 'Rf1086SourceQuery', 'Rf1086ActionAvailability', 'Rf1086AuthorityError', 'Rf1086AuthorityCall', 'Rf1086MainResponse', 'Rf1086PostResponse', 'Rf1086Confirmation', 'Rf1086DocumentReference', 'Rf1086DocumentPage', 'Rf1086AuthorityDocument', 'Rf1086ReadOnlyAuthority', 'Rf1086MutationAuthority', 'Rf1086FeedbackDiscovery', 'Rf1086FeedbackTransmission', 'ProductionOperation', 'ProductionOperationFailure', 'ProductionOperationJournal', 'JournaledRf1086ProductionInput', 'JournaledRf1086ProductionResult', 'Rf1086UnknownProductionOutcomeError', 'Rf1086BlockedProductionOperationError', 'Rf1086FeedbackResult', 'Rf1086ReconciliationSnapshot', 'Rf1086ReconciliationArtifact', 'Rf1086FeedbackArtifactPersistenceError', 'Rf1086ProductionJournal', 'Rf1086ReconciliationInput', 'Rf1086ReconciliationResult', 'Rf1086ProductionError', 'Rf1086Approval', 'Rf1086Preview', 'Rf1086Submission', 'Rf1086Connection', 'Rf1086SendResult', 'Rf1086OwnerReconciliationResult', 'Rf1086PreviewRecord', 'Rf1086SimulationRecord', 'Rf1086OverrideRecord', 'Rf1086ReviewCommentRecord', 'Rf1086FilingPermissionRecord', 'Rf1086TestEvidenceRecord', 'Rf1086ApprovalRecord', 'Rf1086ProductionSubmissionRecord', 'Rf1086FeedbackArtifactRecord', 'Rf1086WorkspaceSnapshot', 'Rf1086ArchiveProductionEventRecord', 'Rf1086ArchiveFeedbackArtifactRecord', 'Rf1086ArchiveSnapshot', 'Rf1086OpeningBasis', 'Rf1086PreparedPreview', 'Rf1086SimulationBasis', 'Rf1086PreparedSimulation', 'Rf1086ApprovalBasis', 'Rf1086PreparedApproval', 'Rf1086MigrationInventory', 'Rf1086JournalEvent', 'Rf1086SourceSnapshot', 'Rf1086OpeningSource', 'Rf1086SourceEvidence', 'Rf1086HistoryCoverage', 'Rf1086ProductionAttemptFact', 'Rf1086CorrectionLink', 'Rf1086IncidentFact', 'Rf1086WarningFact', 'Rf1086OutcomeFact', 'Rf1086SourceFacts', 'VerifyRf1086SourceEvidenceQuery', 'Rf1086PreparationPersistence', 'ShareholderRegisterFilingQueries', 'rf1086_payload_utf8_bytes', 'parse_rf1086_case', 'generate_rf1086_documents', 'assess_rf1086_readiness', 'render_rf1086_preview', 'render_no_activity_rf1086_preview', 'create_rf1086_preparation_service', 'ReadRf1086PreviewQuery', 'resume_production_operation', 'create_rf1086_feedback_artifact_persistence_error', 'rf1086_xml_schema', 'OpeningSnapshotPersistence', 'OpeningSnapshotCommands', 'create_opening_snapshot_service', 'execute_journaled_rf1086_production', 'rf1086_current_manifest_hash', 'rf1086_production_document_order', 'reconcile_journaled_rf1086_production', 'Rf1086CompanyFacts', 'Rf1086OpeningShareholderFact', 'Rf1086OpeningFacts', 'build_no_activity_rf1086_case', 'Rf1086PreparationOperations', 'rf1086_adapter', 'Rf1086OfflineSimulationInput', 'Rf1086OfflineSimulationCall', 'Rf1086OfflineSimulationResult', 'Rf1086ValidationInput', 'Rf1086ValidationCaseResult', 'Rf1086ValidationReport', 'Rf1086CodeVerificationStatus', 'Rf1086CodeDecision', 'parse_rf1086_offline_simulation_input', 'simulate_rf1086_offline_submission', 'validate_rf1086_cases', 'format_rf1086_readiness_report', 'rf1086_code_decisions', 'rf1086_code_decisions_for_case', 'rf1086_production_code_blockers', 'rf1086_production_scope_exclusions', 'ProductionOperationState', 'FailureClassification', 'Rf1086FeedbackClassification', 'Rf1086ReconciliationState', 'Rf1086YearSourceError', 'Rf1086YearSourceId', 'Rf1086PaidInSourceFacts', 'Rf1086YearDocumentEvidence', 'Rf1086YearEventEvidence', 'Rf1086YearGovernanceReceipt', 'Rf1086VerifiedYearSourceContext', 'RecordRf1086YearSource', 'Rf1086YearSourceFreshness', 'Rf1086YearSourceSnapshot', 'prepare_rf1086_year_source', 'assert_rf1086_year_source_fresh', 'assert_rf1086_year_source_integrity', 'assert_rf1086_year_source_replay', 'rf1086_year_source_digest', 'rf1086_governance_economic_facts', 'Rf1086YearSourcePersistence', 'serialize_rf1086_year_source', 'parse_rf1086_year_source', 'Rf1086RegisterObservationError', 'Rf1086RegisterObservationId', 'Rf1086RegisterHolding', 'Rf1086RegisteredShareState', 'Rf1086RegisterDocumentEvidence', 'RecordRf1086RegisterObservation', 'Rf1086VerifiedRegisterObservationContext', 'Rf1086RegisterObservationSnapshot', 'Rf1086RegisterObservationMatchQuery', 'prepare_rf1086_register_observation', 'assert_rf1086_register_observation_integrity', 'verify_rf1086_register_observation', 'rf1086_register_observation_request_digest', 'Rf1086RegisterObservationPersistence', 'serialize_rf1086_register_observation', 'parse_rf1086_register_observation']
