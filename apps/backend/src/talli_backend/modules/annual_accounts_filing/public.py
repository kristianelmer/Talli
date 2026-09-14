"""Immutable Annual Accounts calculation, rendering and readiness contracts."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Protocol, TypeVar

from talli_backend.shared.kernel import ActorId, CompanyId, DomainError, ErrorCategory, IncomeYear, Timestamp


def _freeze(value):
    # Ignored JSON metadata may be deeply nested. Copy without Python call-stack
    # recursion, while retaining input order and rejecting non-JSON cycles.
    result = [None]
    active = set()
    pending = [('visit', value, result, 0)]
    while pending:
        operation, item, parent, key = pending.pop()
        if operation == 'finish':
            original, copied = item
            parent[key] = MappingProxyType(copied) if isinstance(copied, dict) else tuple(copied)
            active.remove(id(original))
        elif isinstance(item, (Mapping, list, tuple)):
            if id(item) in active:
                raise ValueError('Annual Accounts source facts must not contain cycles.')
            active.add(id(item))
            entries = list(item.items()) if isinstance(item, Mapping) else list(enumerate(item))
            copied = {child_key: None for child_key, _ in entries} if isinstance(item, Mapping) else [None] * len(item)
            pending.append(('finish', (item, copied), parent, key))
            pending.extend(('visit', child, copied, child_key) for child_key, child in reversed(entries))
        else:
            parent[key] = item
    return result[0]


@dataclass(frozen=True, slots=True)
class AnnualAccountsSource:
    """Ordered source facts supplied by a workflow; no authorization attestation."""
    income_year: int
    annual_data: Mapping[str, object] | None
    ledger_entries: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'annual_data', _freeze(self.annual_data))
        object.__setattr__(self, 'ledger_entries', _freeze(self.ledger_entries))


@dataclass(frozen=True, slots=True)
class AnnualAccountsCandidate:
    schema_type: str
    main_form_format_id: str
    main_form_format_version: str
    accounts_format_id: str
    accounts_format_version: str
    notes: Mapping[str, object]
    fields: tuple[Mapping[str, object], ...]
    feedback: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        for name in ('notes', 'fields', 'feedback'):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class AnnualAccountsRenderInput:
    candidate: AnnualAccountsCandidate
    organization_number: str
    company_name: str
    contact_email: str
    approval_date: str
    confirming_representative: str


@dataclass(frozen=True, slots=True)
class AnnualAccountsDocuments:
    main_form_xml: str
    company_accounts_xml: str


@dataclass(frozen=True, slots=True)
class AnnualAccountsReadinessIssue:
    level: str
    code: str
    message: str
    source: str
    accepted: bool = False


@dataclass(frozen=True, slots=True)
class AnnualAccountsCorporateReadiness:
    """Corporate Governance's blockers; enabling this does not manufacture close facts."""
    enabled: bool
    blockers: tuple[AnnualAccountsReadinessIssue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'blockers', tuple(self.blockers))


def build_annual_accounts(source: AnnualAccountsSource) -> AnnualAccountsCandidate:
    from .calculation import build
    return build(source)


def render_annual_accounts(input: AnnualAccountsRenderInput) -> AnnualAccountsDocuments:
    from .rendering import render
    return render(input)


def assess_annual_accounts_readiness(
    source: AnnualAccountsSource, *, company_id: str,
    corporate: AnnualAccountsCorporateReadiness | None = None,
) -> tuple[AnnualAccountsReadinessIssue, ...]:
    """Accounts-specific issues only; Annual retains the common readiness gates."""
    from .readiness import assess
    return assess(source, company_id, corporate)


@dataclass(frozen=True, slots=True)
class AnnualAccountsOfflineSource:
    """Existing public-data Annual totals; deliberately distinct from live Ledger input.

    Annual's offline model retains common aggregation and common readiness policy.
    This contract owns only the Accounts projection of those immutable facts.
    """
    company_id: str
    income_year: int
    bank_balance: float
    investment_balance: float
    admin_costs: float
    financial_income: float
    financial_costs: float
    shareholder_loan_payable: float
    share_capital: float
    retained_earnings: float
    result_before_tax: float
    general_meeting_approved: bool
    common_issues: tuple[Mapping[str, object], ...] = ()
    confirmations: tuple[str, ...] = ()
    annual_full_time_equivalents: float | None = 0
    audit_required: bool = False
    small_enterprise: bool = True
    annual_report_required: bool = False
    cash_flow_statement_required: bool = False
    sustainability_reporting_required: bool = False
    fiscal_year_is_calendar_year: bool = True
    prior_year_figures_confirmed: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, 'common_issues', _freeze(self.common_issues))
        object.__setattr__(self, 'confirmations', tuple(self.confirmations))


@dataclass(frozen=True, slots=True)
class AnnualAccountsOfflineSimulation:
    filing: str
    preview: str
    readiness: Mapping[str, object]
    simulated_receipt_id: str | None
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'readiness', _freeze(self.readiness))
        object.__setattr__(self, 'payload', _freeze(self.payload))


def build_annual_accounts_offline_payload(source: AnnualAccountsOfflineSource) -> Mapping[str, object]:
    from .offline import build_payload
    return _freeze(build_payload(source))


def assess_annual_accounts_offline(source: AnnualAccountsOfflineSource) -> Mapping[str, object]:
    from .offline import assess
    return _freeze(assess(source))


def simulate_annual_accounts_offline(source: AnnualAccountsOfflineSource) -> AnnualAccountsOfflineSimulation:
    from .offline import simulate
    return simulate(source)


@dataclass(frozen=True, slots=True)
class AnnualAccountsEvidenceInput:
    """Untrusted TT02 document plus caller identity supplied by the workflow.

    The workflow supplies its clock and authenticates the actor. This pure
    projection performs neither authorization nor authority classification.
    """
    company_id: str
    expected_organization_number: str
    evidence: object
    recorded_by: str
    recorded_at: str
    evidence_url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, 'evidence', _freeze(self.evidence))


@dataclass(frozen=True, slots=True)
class AnnualAccountsEvidenceProjection:
    company_id: str
    obligation: str
    environment: str
    status: str
    test_reference: str
    feedback_summary: str
    receipt_reference: str
    archive_reference: str
    evidence_url: str | None
    payload_hash: str
    recorded_by: str
    recorded_at: str


def import_annual_accounts_evidence(input: AnnualAccountsEvidenceInput) -> AnnualAccountsEvidenceProjection:
    from .evidence import project
    return project(input)


class AnnualAccountsAuthorityError(Exception):
    """Stable sanitized authority failure; provider text is not reflected."""
    def __init__(self, message: str, *, code: str, status: int | None = None,
                 retryable: bool = False, validation_codes: list[str] | None = None):
        super().__init__(message)
        self.code, self.status, self.retryable = code, status, retryable
        self.correlation_id = None
        self.validation_codes = validation_codes or []

    def evidence(self) -> Mapping[str, object]:
        return {"code": self.code, "status": self.status, "correlationId": None,
                "retryable": self.retryable, "message": str(self), "validationCodes": self.validation_codes}


class AnnualAccountsAuthority(Protocol):
    """Test-only authority operations; a person performs signing."""
    async def create_instance(self, *, company_org_number: str) -> Mapping[str, object]: ...
    async def upload_main_form(self, *, instance_id: str, data_id: str, xml: str) -> Mapping[str, object]: ...
    async def upload_company_accounts(self, *, instance_id: str, data_id: str, xml: str) -> Mapping[str, object]: ...
    async def validate_instance(self, *, instance_id: str) -> Mapping[str, object]: ...
    async def lock_for_signing(self, *, instance_id: str) -> Mapping[str, object]: ...
    async def get_signing_handoff(self, *, instance_id: str) -> Mapping[str, object]: ...
    async def get_submission_evidence(self, *, instance_id: str) -> Mapping[str, object]: ...


AuthorityAdapter = TypeVar("AuthorityAdapter", bound=type[object])


def annual_accounts_authority_adapter(contract: type[object]) -> Callable[[AuthorityAdapter], AuthorityAdapter]:
    def declare(adapter: AuthorityAdapter) -> AuthorityAdapter:
        _ = contract
        return adapter
    return declare


@dataclass(frozen=True, slots=True)
class AnnualAccountsRehearsalConfiguration:
    """Nonsecret CLI declarations; the workflow preserves ordered validation."""
    approved_test_write: str = ""
    authority_environment: str = ""
    scope: str = ""
    system_user_org: str = ""
    external_reference: str = ""
    system_user_request_id: str = ""
    contact_email: str = ""
    approval_date: str = ""
    confirming_representative: str = ""


class AnnualAccountsRehearsalIO(Protocol):
    """Local file, clock, document and credential mechanisms for the workflow."""
    def load_case(self) -> Mapping[str, object]: ...
    def load_evidence(self) -> dict[str, object] | None: ...
    def save_evidence(self, evidence: Mapping[str, object]) -> None: ...
    def evidence_filename(self) -> str: ...
    def case_filename(self) -> str: ...
    def revision(self) -> str: ...
    def timestamp(self) -> str: ...
    async def connect(self, evidence: Mapping[str, object]) -> AnnualAccountsAuthority: ...
    def generate(self, operation: str, values: Mapping[str, object]) -> Mapping[str, object]: ...
    def validate_documents(self, documents: Mapping[str, str]) -> None: ...


async def rehearse_annual_accounts(
    configuration: AnnualAccountsRehearsalConfiguration, io: AnnualAccountsRehearsalIO,
) -> Mapping[str, object]:
    from .rehearsal import run
    return _freeze(await run(configuration, io))


async def prepare_annual_accounts_for_signing(
    client: AnnualAccountsAuthority, *, company_org_number: str,
    main_form_xml: str, company_accounts_xml: str,
) -> Mapping[str, object]:
    from .authority_workflow import prepare
    return _freeze(await prepare(client, company_org_number=company_org_number,
        main_form_xml=main_form_xml, company_accounts_xml=company_accounts_xml))


class AnnualAccountsError(DomainError):
    @classmethod
    def hard_review_block(cls) -> AnnualAccountsError:
        return cls(code="ANNUAL_ACCOUNTS_HARD_REVIEW_BLOCK", category=ErrorCategory.FORBIDDEN,
            message="Hard review-blokk kan ikke acknowledges som advisory.")

    @classmethod
    def evidence_persistence_rejected(cls) -> AnnualAccountsError:
        return cls(code="ANNUAL_ACCOUNTS_EVIDENCE_PERSISTENCE_REJECTED", category=ErrorCategory.INVALID_INPUT)

    @classmethod
    def mfa_required(cls) -> AnnualAccountsError:
        return cls(code="ANNUAL_ACCOUNTS_MFA_REQUIRED", category=ErrorCategory.FORBIDDEN)

    @classmethod
    def not_found(cls) -> AnnualAccountsError:
        return cls(code="ANNUAL_ACCOUNTS_NOT_FOUND", category=ErrorCategory.NOT_FOUND)

    @classmethod
    def invalid_input(cls, message: str = "") -> AnnualAccountsError:
        return cls(code="ANNUAL_ACCOUNTS_INVALID_INPUT", category=ErrorCategory.INVALID_INPUT, message=message)

    @classmethod
    def forbidden(cls) -> AnnualAccountsError:
        return cls(code="ANNUAL_ACCOUNTS_FORBIDDEN", category=ErrorCategory.FORBIDDEN)

    @classmethod
    def unavailable(cls) -> AnnualAccountsError:
        return cls(code="ANNUAL_ACCOUNTS_DEPENDENCY_UNAVAILABLE", category=ErrorCategory.DEPENDENCY_UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class AnnualAccountsWorkspaceQuery:
    actor_id: ActorId
    company_id: CompanyId
    income_year: IncomeYear | None = None


@dataclass(frozen=True, slots=True)
class AnnualAccountsFilingRows:
    """Complete immutable predecessor row projections, scoped to one company.

    Permissions and authority test evidence are company-wide in the predecessor;
    their lack of an income year must not be interpreted as year completeness.
    """
    company_id: CompanyId
    income_year: IncomeYear | None
    previews: tuple[Mapping[str, object], ...]
    submissions: tuple[Mapping[str, object], ...]
    overrides: tuple[Mapping[str, object], ...]
    review_comments: tuple[Mapping[str, object], ...]
    permissions: tuple[Mapping[str, object], ...]
    test_evidence: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        for name in ('previews', 'submissions', 'overrides', 'review_comments', 'permissions', 'test_evidence'):
            if not isinstance(getattr(self, name), (list, tuple)):
                raise AnnualAccountsError.unavailable()
            object.__setattr__(self, name, _freeze(getattr(self, name)))
        from .workspace import validate_rows
        validate_rows(self)


class AnnualAccountsWorkspacePersistence(Protocol):
    async def filing_workspace(self, query: AnnualAccountsWorkspaceQuery) -> AnnualAccountsFilingRows: ...


PersistenceAdapter = TypeVar("PersistenceAdapter", bound=type[object])


def annual_accounts_persistence_adapter(contract: type[object]) -> Callable[[PersistenceAdapter], PersistenceAdapter]:
    def declare(adapter: PersistenceAdapter) -> PersistenceAdapter:
        _ = contract
        return adapter
    return declare


@dataclass(frozen=True, slots=True)
class AnnualAccountsRecordId:
    value: str

    def __post_init__(self) -> None:
        from uuid import UUID
        object.__setattr__(self, 'value', str(UUID(self.value)))

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class AnnualAccountsRecordQuery:
    actor_id: ActorId
    record_id: AnnualAccountsRecordId


@dataclass(frozen=True, slots=True)
class RecordAnnualAccountsOverride:
    actor_id: ActorId
    preview_id: AnnualAccountsRecordId
    field_target: str
    old_value: str
    new_value: str
    reason: str
    risk_level: str
    owner_confirmed: bool


@dataclass(frozen=True, slots=True)
class AddAnnualAccountsReviewComment:
    actor_id: ActorId
    preview_id: AnnualAccountsRecordId
    severity: str
    body: str


@dataclass(frozen=True, slots=True)
class ConfirmAnnualAccountsPermission:
    actor_id: ActorId
    company_id: CompanyId
    production_enabled: bool


@dataclass(frozen=True, slots=True)
class RecordAnnualAccountsTestEvidence:
    actor_id: ActorId
    company_id: CompanyId
    environment: str
    status: str
    test_reference: str
    feedback_summary: str
    receipt_reference: str | None = None
    archive_reference: str | None = None
    evidence_url: str | None = None
    payload_hash: str | None = None


@dataclass(frozen=True, slots=True)
class AnnualAccountsRecordedResult:
    record_id: AnnualAccountsRecordId
    company_id: CompanyId
    income_year: IncomeYear | None


class AnnualAccountsPreparationPersistence(Protocol):
    async def filing_preview(self, query: AnnualAccountsRecordQuery) -> Mapping[str, object] | None: ...
    async def record_override(self, command: RecordAnnualAccountsOverride) -> AnnualAccountsRecordedResult: ...
    async def add_review_comment(self, command: AddAnnualAccountsReviewComment) -> AnnualAccountsRecordedResult: ...
    async def acknowledge_review_comment(self, query: AnnualAccountsRecordQuery) -> AnnualAccountsRecordedResult: ...
    async def confirm_filing_permission(self, command: ConfirmAnnualAccountsPermission) -> AnnualAccountsRecordedResult: ...
    async def record_test_evidence(self, command: RecordAnnualAccountsTestEvidence) -> AnnualAccountsRecordedResult: ...


def normalize_annual_accounts_override(command: RecordAnnualAccountsOverride) -> RecordAnnualAccountsOverride:
    from .preparation import normalize_override
    return normalize_override(command)


def normalize_annual_accounts_review(command: AddAnnualAccountsReviewComment) -> AddAnnualAccountsReviewComment:
    from .preparation import normalize_review
    return normalize_review(command)


def normalize_annual_accounts_test_evidence(command: RecordAnnualAccountsTestEvidence) -> RecordAnnualAccountsTestEvidence:
    from .preparation import normalize_test_evidence
    return normalize_test_evidence(command)


@dataclass(frozen=True, slots=True)
class ImportAnnualAccountsEvidence:
    actor_id: ActorId
    company_id: CompanyId
    evidence: object
    evidence_url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, 'evidence', _freeze(self.evidence))


@dataclass(frozen=True, slots=True)
class AnnualAccountsCompanyIdentity:
    company_id: CompanyId
    organization_number: str


@dataclass(frozen=True, slots=True)
class ImportedAnnualAccountsEvidence:
    record_id: AnnualAccountsRecordId
    test_reference: str


class AnnualAccountsEvidencePersistence(Protocol):
    async def filing_company_identity(self, company_id: CompanyId, actor_id: ActorId) -> AnnualAccountsCompanyIdentity: ...
    async def import_tt02_evidence(self, projection: AnnualAccountsEvidenceProjection, actor_id: ActorId) -> AnnualAccountsRecordId: ...


@dataclass(frozen=True, slots=True)
class AnnualAccountsSourceQuery:
    company_id: CompanyId
    income_year: IncomeYear
    actor_id: ActorId


@dataclass(frozen=True, slots=True)
class AnnualAccountsSourceSnapshot:
    """One authorized repeatable snapshot of the declared recorded Accounts extent."""
    rows: AnnualAccountsFilingRows
    coverage: Mapping[str, object] | None
    as_of: Timestamp
    complete_enumeration: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "coverage", _freeze(self.coverage))


@dataclass(frozen=True, slots=True)
class AnnualAccountsSourceEvidence:
    company_id: CompanyId
    income_year: IncomeYear
    reference: str
    version: str
    digest: str
    evaluated_at: Timestamp
    obligation: str = "aarsregnskap"
    scope: str = "talli_recorded_annual_accounts"


@dataclass(frozen=True, slots=True)
class AnnualAccountsHistoryCoverage:
    status: str
    reasons: tuple[str, ...]
    evidence_reference: str | None
    as_of: Timestamp
    submission_count: int
    scope: str = "talli_recorded_annual_accounts"


@dataclass(frozen=True, slots=True)
class AnnualAccountsSubmissionFact:
    source_id: str
    source_mode: str
    adapter_mode: str
    state: str
    effect_status: str
    observed_at: str | None
    created_by: str | None
    submitted_by: str | None
    authority_confirmed_by: str | None
    authority_confirmed_at: str | None
    preview_confirmed_by: str | None
    preview_confirmed_at: str | None
    payload_hash: str | None
    receipt_reference: str | None
    feedback_document_ids: tuple[str, ...]
    source_digest: str


@dataclass(frozen=True, slots=True)
class AnnualAccountsIncidentFact:
    source_id: str
    source_mode: str
    adapter_mode: str
    failure_code: str | None
    observed_at: str | None
    actor_id: str | None
    source_digest: str
    attribution: str = "unknown"


@dataclass(frozen=True, slots=True)
class AnnualAccountsOutcomeFact:
    source_id: str
    source_mode: str
    adapter_mode: str
    recorded_state: str
    outcome: str
    observed_at: str | None
    source_digest: str
    attribution: str = "unknown"


@dataclass(frozen=True, slots=True)
class AnnualAccountsCorrectionLink:
    source_id: str
    supersedes_source_id: str


@dataclass(frozen=True, slots=True)
class AnnualAccountsSourceFacts:
    evidence: AnnualAccountsSourceEvidence
    readiness_status: str
    hard_blocks: tuple[str, ...]
    history_coverage: AnnualAccountsHistoryCoverage
    recorded_submissions: tuple[AnnualAccountsSubmissionFact, ...]
    production_attempts: tuple[AnnualAccountsSubmissionFact, ...]
    correction_links: tuple[AnnualAccountsCorrectionLink, ...]
    incidents: tuple[AnnualAccountsIncidentFact, ...]
    outcomes: tuple[AnnualAccountsOutcomeFact, ...]


class AnnualAccountsSourcePersistence(Protocol):
    async def filing_source_snapshot(self, query: AnnualAccountsSourceQuery) -> AnnualAccountsSourceSnapshot: ...


def project_annual_accounts_source(query: AnnualAccountsSourceQuery, snapshot: AnnualAccountsSourceSnapshot) -> AnnualAccountsSourceFacts:
    from .source_facts import project
    return project(query, snapshot)


def verify_annual_accounts_source(
    query: AnnualAccountsSourceQuery, evidence: AnnualAccountsSourceEvidence, snapshot: AnnualAccountsSourceSnapshot,
) -> bool:
    from .source_facts import verify
    return verify(query, evidence, snapshot)


__all__ = [
    "AnnualAccountsSourceQuery",
    "AnnualAccountsSourceSnapshot",
    "AnnualAccountsSourceEvidence",
    "AnnualAccountsHistoryCoverage",
    "AnnualAccountsSubmissionFact",
    "AnnualAccountsIncidentFact",
    "AnnualAccountsOutcomeFact",
    "AnnualAccountsCorrectionLink",
    "AnnualAccountsSourceFacts",
    "AnnualAccountsSourcePersistence",
    "project_annual_accounts_source",
    "verify_annual_accounts_source",

    "ImportAnnualAccountsEvidence", "AnnualAccountsCompanyIdentity", "ImportedAnnualAccountsEvidence",
    "AnnualAccountsEvidencePersistence",
    'AnnualAccountsSource', 'AnnualAccountsCandidate', 'AnnualAccountsRenderInput',
    'AnnualAccountsDocuments', 'AnnualAccountsReadinessIssue', 'AnnualAccountsCorporateReadiness',
    'build_annual_accounts', 'render_annual_accounts', 'assess_annual_accounts_readiness',
    'AnnualAccountsOfflineSource', 'AnnualAccountsOfflineSimulation',
    'build_annual_accounts_offline_payload', 'assess_annual_accounts_offline', 'simulate_annual_accounts_offline',
    'AnnualAccountsEvidenceInput', 'AnnualAccountsEvidenceProjection', 'import_annual_accounts_evidence',
    'AnnualAccountsAuthorityError', 'AnnualAccountsAuthority', 'annual_accounts_authority_adapter',
    'AnnualAccountsRehearsalConfiguration', 'AnnualAccountsRehearsalIO', 'rehearse_annual_accounts',
    'prepare_annual_accounts_for_signing',
    'AnnualAccountsRecordId', 'AnnualAccountsRecordQuery', 'RecordAnnualAccountsOverride',
    'AddAnnualAccountsReviewComment', 'ConfirmAnnualAccountsPermission', 'RecordAnnualAccountsTestEvidence',
    'AnnualAccountsRecordedResult', 'AnnualAccountsPreparationPersistence', 'normalize_annual_accounts_override',
    'normalize_annual_accounts_review', 'normalize_annual_accounts_test_evidence',
    'AnnualAccountsError', 'AnnualAccountsWorkspaceQuery', 'AnnualAccountsFilingRows',
    'AnnualAccountsWorkspacePersistence', 'annual_accounts_persistence_adapter',
]
