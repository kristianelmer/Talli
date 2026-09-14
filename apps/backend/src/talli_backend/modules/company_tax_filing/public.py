"""Public Company Tax settlement facts and normalization contract."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from collections.abc import Callable, Mapping
from typing import Protocol, TypeVar
from types import MappingProxyType

from talli_backend.shared.kernel import (
    ActorId, CompanyId, CorrelationId, DomainError, ErrorCategory,
    IdempotencyKey, IncomeYear, LocalDate, Money,
)


class TaxSettlementKind(StrEnum):
    PAYABLE = "payable"
    PAYMENT = "payment"
    REFUND = "refund"


class TaxSettlementDocumentStatus(StrEnum):
    ATTACHED = "attached"
    MISSING_ACCEPTED_WARNING = "missing_accepted_warning"
    NOT_REQUIRED = "not_required"


class TaxSettlementValidationError(DomainError):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(code=code, category=ErrorCategory.INVALID_INPUT, message=message)


@dataclass(frozen=True, slots=True)
class TaxSettlementInput:
    settlement_date: str
    amount: float | None
    settlement_kind: str
    document_status: str
    bank_transaction_id: str | None = None
    document_id: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedTaxSettlement:
    """Preview normalization; capture separately enforces date/year and Money."""
    settlement_date: str
    amount: float
    settlement_kind: TaxSettlementKind
    document_status: TaxSettlementDocumentStatus
    bank_transaction_id: str | None
    document_id: str | None
    expected_bank_amount: float | None


def normalize_tax_settlement(value: TaxSettlementInput) -> NormalizedTaxSettlement:
    from .service import normalize

    return normalize(value)




@dataclass(frozen=True, slots=True)
class _UuidReference:
    value: str

    def __post_init__(self) -> None:
        from uuid import UUID
        object.__setattr__(self, "value", str(UUID(self.value)))

    def __str__(self) -> str:
        return self.value


class TaxSettlementId(_UuidReference):
    pass


class BankTransactionReference(_UuidReference):
    pass


class DocumentReference(_UuidReference):
    pass


class AccountingEntryReference(_UuidReference):
    pass


class CompanyTaxError(DomainError):
    @classmethod
    def hard_review_block(cls) -> CompanyTaxError:
        return cls(code="COMPANY_TAX_HARD_REVIEW_BLOCK", category=ErrorCategory.FORBIDDEN,
            message="Hard review-blokk kan ikke acknowledges som advisory.")

    @classmethod
    def evidence_persistence_rejected(cls) -> CompanyTaxError:
        return cls(code="COMPANY_TAX_EVIDENCE_PERSISTENCE_REJECTED", category=ErrorCategory.INVALID_INPUT)

    @classmethod
    def mfa_required(cls) -> CompanyTaxError:
        return cls(code="COMPANY_TAX_MFA_REQUIRED", category=ErrorCategory.FORBIDDEN)

    @classmethod
    def not_found(cls) -> CompanyTaxError:
        return cls(code="COMPANY_TAX_NOT_FOUND", category=ErrorCategory.NOT_FOUND)

    @classmethod
    def invalid_input(cls, message: str = "") -> CompanyTaxError:
        return cls(code="COMPANY_TAX_INVALID_INPUT", category=ErrorCategory.INVALID_INPUT, message=message)

    @classmethod
    def forbidden(cls) -> CompanyTaxError:
        return cls(code="COMPANY_TAX_FORBIDDEN", category=ErrorCategory.FORBIDDEN)

    @classmethod
    def unavailable(cls) -> CompanyTaxError:
        return cls(code="COMPANY_TAX_DEPENDENCY_UNAVAILABLE", category=ErrorCategory.DEPENDENCY_UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class RecordTaxSettlementCommand:
    company_id: CompanyId
    actor_id: ActorId
    correlation_id: CorrelationId
    idempotency_key: IdempotencyKey
    income_year: IncomeYear
    action_id: TaxSettlementId
    settlement_date: LocalDate
    amount: Money
    settlement_kind: TaxSettlementKind
    document_status: TaxSettlementDocumentStatus
    bank_transaction_id: BankTransactionReference | None
    document_id: DocumentReference | None


class TaxSettlementPersistence(Protocol):
    async def prepare_settlement(
        self, command: RecordTaxSettlementCommand
    ) -> Mapping[str, object] | None:
        """Authorize, claim original technical receipt and lock year; return replay."""
        ...

    async def complete_settlement(
        self, command: RecordTaxSettlementCommand, accounting_entry_id: AccountingEntryReference
    ) -> Mapping[str, object]: ...


SettlementAdapter = TypeVar("SettlementAdapter", bound=type[object])


def tax_settlement_persistence_adapter(
    contract: type[object],
) -> Callable[[SettlementAdapter], SettlementAdapter]:
    def declare(adapter: SettlementAdapter) -> SettlementAdapter:
        _ = contract
        return adapter
    return declare


def validate_new_tax_settlement(command: RecordTaxSettlementCommand) -> None:
    """Validate a fresh capture only after historical receipt/action replay."""
    from .service import validate_new
    validate_new(command)


@dataclass(frozen=True, slots=True)
class TaxSettlementArchiveQuery:
    actor_id: ActorId
    company_id: CompanyId
    income_year: IncomeYear


class TaxSettlementArchivePersistence(Protocol):
    async def archive_settlements(self, query: TaxSettlementArchiveQuery) -> tuple[Mapping[str, object], ...]:
        """Return all thirteen preserved source fields for the authorized year."""
        ...


@dataclass(frozen=True, slots=True)
class CompanyTaxWorkspaceQuery:
    actor_id: ActorId
    company_id: CompanyId
    income_year: IncomeYear | None = None


@dataclass(frozen=True, slots=True)
class CompanyTaxFilingRows:
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
                raise CompanyTaxError.unavailable()
            object.__setattr__(self, name, _freeze_return_fact(getattr(self, name)))
        from .workspace import validate_rows
        validate_rows(self)


class CompanyTaxWorkspacePersistence(Protocol):
    async def filing_workspace(self, query: CompanyTaxWorkspaceQuery) -> CompanyTaxFilingRows: ...


def _freeze_return_fact(value: object) -> object:
    # Iteration preserves valid deeply nested ignored JSON fields without using
    # Python's call stack. Only ancestor cycles are rejected; shared facts copy.
    result = [None]
    stack = [(False, value, result, 0)]
    ancestors = set()
    while stack:
        finishing, source, parent, key = stack.pop()
        if finishing:
            copied, original_id = source
            ancestors.remove(original_id)
            parent[key] = MappingProxyType(copied) if isinstance(copied, dict) else tuple(copied)
        elif isinstance(source, (Mapping, tuple, list)):
            if id(source) in ancestors:
                raise ValueError('Cyclic source facts are invalid.')
            ancestors.add(id(source))
            copied = {} if isinstance(source, Mapping) else [None] * len(source)
            stack.append((True, (copied, id(source)), parent, key))
            children = source.items() if isinstance(source, Mapping) else enumerate(source)
            stack.extend((False, child, copied, child_key) for child_key, child in reversed(list(children)))
        else:
            parent[key] = source
    return result[0]


@dataclass(frozen=True, slots=True)
class CompanyTaxReturnSource:
    """Annual/Ledger/holding facts supplied by the named application workflow.

    Taking a snapshot copies and recursively freezes nested source values. Tax
    never receives a repository handle or discovers another owner's data here.
    """
    organization_number: str
    income_year: int
    annual_data: Mapping[str, object] | None
    ledger_entries: tuple[Mapping[str, object], ...]
    holding_actions: tuple[Mapping[str, object], ...]
    party_number: str | None = None

    def __post_init__(self) -> None:
        for name in ('annual_data', 'ledger_entries', 'holding_actions'):
            object.__setattr__(self, name, _freeze_return_fact(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class CompanyTaxReturnCandidate:
    schema: Mapping[str, object]
    derived: Mapping[str, object]
    fields: tuple[Mapping[str, object], ...]
    feedback: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        for name in ('schema', 'derived', 'fields', 'feedback'):
            object.__setattr__(self, name, _freeze_return_fact(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class AnnualTaxEstimate:
    admin_costs: float
    interest_income: float
    participation_exemption_add_back: float
    taxable_share_sale_gain: float
    deductible_share_sale_loss: float
    tax_basis: float
    estimated_tax: float
    status: str


@dataclass(frozen=True, slots=True)
class CompanyTaxReturnDocuments:
    tax_return_xml: str
    business_specification_xml: str


@dataclass(frozen=True, slots=True)
class CompanyTaxEnvelopeInput:
    documents: CompanyTaxReturnDocuments
    organization_number: str
    income_year: int
    created_by: str
    current_document_reference: str | None = None


def _calculation_source(source: CompanyTaxReturnSource) -> Mapping[str, object]:
    return {'companyOrgNumber': source.organization_number, 'companyPartyNumber': source.party_number,
            'incomeYear': source.income_year, 'annualData': source.annual_data,
            'ledgerEntries': source.ledger_entries, 'holdingActions': source.holding_actions}


def build_company_tax_return(source: CompanyTaxReturnSource) -> CompanyTaxReturnCandidate:
    from .calculation import build
    return CompanyTaxReturnCandidate(**build(_calculation_source(source)))


def estimate_annual_tax(source: CompanyTaxReturnSource) -> AnnualTaxEstimate:
    from .calculation import estimate
    value = estimate(_calculation_source(source))
    return AnnualTaxEstimate(
        admin_costs=value['adminCosts'], interest_income=value['interestIncome'],
        participation_exemption_add_back=value['fritaksmetodenAddBack'],
        taxable_share_sale_gain=value['taxableShareSaleGain'], deductible_share_sale_loss=value['deductibleShareSaleLoss'],
        tax_basis=value['taxBasis'], estimated_tax=value['estimatedTax'], status=value['status'],
    )


def render_company_tax_return(candidate: CompanyTaxReturnCandidate) -> CompanyTaxReturnDocuments:
    from .rendering import render
    value = render(candidate.fields)
    return CompanyTaxReturnDocuments(value['skattemeldingXml'], value['naeringsspesifikasjonXml'])


@dataclass(frozen=True, slots=True)
class PreparedCompanyTaxReturn:
    documents: CompanyTaxReturnDocuments
    feedback: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'feedback', _freeze_return_fact(self.feedback))


def prepare_company_tax_return(source: CompanyTaxReturnSource) -> PreparedCompanyTaxReturn:
    """Retain the authority-tool blocking gate before producing sendable XML."""
    candidate = build_company_tax_return(source)
    if any(item['level'] == 'block' for item in candidate.feedback):
        raise CompanyTaxError(code='COMPANY_TAX_PAYLOAD_BLOCKED', category=ErrorCategory.PRECONDITION_FAILED)
    return PreparedCompanyTaxReturn(render_company_tax_return(candidate), candidate.feedback)


def render_company_tax_envelope(input: CompanyTaxEnvelopeInput) -> str:
    from .rendering import envelope
    value = {'skattemeldingXml': input.documents.tax_return_xml,
             'naeringsspesifikasjonXml': input.documents.business_specification_xml,
             'companyOrgNumber': input.organization_number, 'incomeYear': input.income_year,
             'createdBy': input.created_by}
    if input.current_document_reference is not None:
        value['currentDocumentReference'] = input.current_document_reference
    return envelope(value)


@dataclass(frozen=True, slots=True)
class CompanyTaxEvidenceInput:
    company_id: str
    expected_organization_number: str
    expected_income_year: int
    evidence: Mapping[str, object]
    recorded_by: str
    evidence_url: str | None = None
    recorded_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, 'evidence', _freeze_return_fact(self.evidence))


@dataclass(frozen=True, slots=True)
class CompanyTaxEvidenceProjection:
    authority_run: Mapping[str, object]
    submission: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'authority_run', _freeze_return_fact(self.authority_run))
        object.__setattr__(self, 'submission', _freeze_return_fact(self.submission))


def project_company_tax_evidence(input: CompanyTaxEvidenceInput) -> CompanyTaxEvidenceProjection:
    from .evidence import project
    source = {'companyId': input.company_id, 'expectedCompanyOrgNumber': input.expected_organization_number,
              'expectedIncomeYear': input.expected_income_year, 'evidence': input.evidence,
              'recordedBy': input.recorded_by, 'evidenceUrl': input.evidence_url}
    if input.recorded_at is not None:
        source['recordedAt'] = input.recorded_at
    result = project(source)
    return CompanyTaxEvidenceProjection(result['authorityRun'], result['submission'])


@dataclass(frozen=True, slots=True)
class CompanyTaxValidationSummary:
    result: str
    deviation_codes: tuple[str, ...]
    guidance_codes: tuple[str, ...]
    failure_reasons: tuple[str, ...]


def summarize_company_tax_validation(result_xml: str) -> CompanyTaxValidationSummary:
    from .validation import summarize
    value = summarize(result_xml)
    return CompanyTaxValidationSummary(value['result'], tuple(value['deviationCodes']),
                                       tuple(value['guidanceCodes']), tuple(value['failureReasons']))


@dataclass(frozen=True, slots=True)
class CompanyTaxCompanyIdentity:
    company_id: CompanyId
    organization_number: str


@dataclass(frozen=True, slots=True)
class ImportCompanyTaxReturnEvidence:
    actor_id: ActorId
    company_id: CompanyId
    income_year: IncomeYear
    evidence: Mapping[str, object]
    evidence_url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, 'evidence', _freeze_return_fact(self.evidence))


class TaxAuthorityEvidenceId(_UuidReference):
    pass


class TaxFilingSubmissionId(_UuidReference):
    pass


@dataclass(frozen=True, slots=True)
class ImportedCompanyTaxEvidence:
    authority_test_run_id: TaxAuthorityEvidenceId
    filing_submission_id: TaxFilingSubmissionId
    created: bool


class CompanyTaxReturnPersistence(Protocol):
    async def filing_company_identity(self, company_id: CompanyId, actor_id: ActorId) -> CompanyTaxCompanyIdentity: ...

    async def import_return_evidence(self, projection: CompanyTaxEvidenceProjection, actor_id: ActorId) -> ImportedCompanyTaxEvidence: ...


class TaxFilingRecordId(_UuidReference):
    pass


@dataclass(frozen=True, slots=True)
class CompanyTaxRecordQuery:
    actor_id: ActorId
    record_id: TaxFilingRecordId


@dataclass(frozen=True, slots=True)
class RecordCompanyTaxOverride:
    actor_id: ActorId
    preview_id: TaxFilingRecordId
    field_target: str
    old_value: str
    new_value: str
    reason: str
    risk_level: str
    owner_confirmed: bool


@dataclass(frozen=True, slots=True)
class AddCompanyTaxReviewComment:
    actor_id: ActorId
    preview_id: TaxFilingRecordId
    severity: str
    body: str


@dataclass(frozen=True, slots=True)
class ConfirmCompanyTaxPermission:
    actor_id: ActorId
    company_id: CompanyId
    production_enabled: bool


@dataclass(frozen=True, slots=True)
class RecordCompanyTaxTestEvidence:
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
class CompanyTaxRecordedResult:
    record_id: TaxFilingRecordId
    company_id: CompanyId
    income_year: IncomeYear | None


class CompanyTaxPreparationPersistence(Protocol):
    async def filing_preview(self, query: CompanyTaxRecordQuery) -> Mapping[str, object] | None: ...
    async def record_override(self, command: RecordCompanyTaxOverride) -> CompanyTaxRecordedResult: ...
    async def add_review_comment(self, command: AddCompanyTaxReviewComment) -> CompanyTaxRecordedResult: ...
    async def acknowledge_review_comment(self, query: CompanyTaxRecordQuery) -> CompanyTaxRecordedResult: ...
    async def confirm_filing_permission(self, command: ConfirmCompanyTaxPermission) -> CompanyTaxRecordedResult: ...
    async def record_test_evidence(self, command: RecordCompanyTaxTestEvidence) -> CompanyTaxRecordedResult: ...


def normalize_company_tax_override(command: RecordCompanyTaxOverride) -> RecordCompanyTaxOverride:
    from .preparation import normalize_override
    return normalize_override(command)


def normalize_company_tax_review(command: AddCompanyTaxReviewComment) -> AddCompanyTaxReviewComment:
    from .preparation import normalize_review
    return normalize_review(command)


def normalize_company_tax_test_evidence(command: RecordCompanyTaxTestEvidence) -> RecordCompanyTaxTestEvidence:
    from .preparation import normalize_test_evidence
    return normalize_test_evidence(command)


__all__ = [
    "TaxFilingRecordId", "CompanyTaxRecordQuery", "RecordCompanyTaxOverride", "AddCompanyTaxReviewComment",
    "ConfirmCompanyTaxPermission", "RecordCompanyTaxTestEvidence", "CompanyTaxRecordedResult",
    "CompanyTaxPreparationPersistence", "normalize_company_tax_override", "normalize_company_tax_review",
    "normalize_company_tax_test_evidence",
    "CompanyTaxCompanyIdentity", "ImportCompanyTaxReturnEvidence", "TaxAuthorityEvidenceId",
    "TaxFilingSubmissionId", "ImportedCompanyTaxEvidence", "CompanyTaxReturnPersistence",
    "CompanyTaxWorkspaceQuery", "CompanyTaxFilingRows", "CompanyTaxWorkspacePersistence",
    "PreparedCompanyTaxReturn", "prepare_company_tax_return",
    "CompanyTaxValidationSummary", "summarize_company_tax_validation",
    "CompanyTaxEvidenceInput", "CompanyTaxEvidenceProjection", "project_company_tax_evidence",
    "CompanyTaxReturnSource", "CompanyTaxReturnCandidate", "AnnualTaxEstimate",
    "CompanyTaxReturnDocuments", "CompanyTaxEnvelopeInput", "build_company_tax_return",
    "estimate_annual_tax", "render_company_tax_return", "render_company_tax_envelope",
    "TaxSettlementArchiveQuery", "TaxSettlementArchivePersistence",
    "NormalizedTaxSettlement",
    "TaxSettlementDocumentStatus",
    "TaxSettlementInput",
    "TaxSettlementKind",
    "TaxSettlementValidationError",
    "normalize_tax_settlement",
    "CompanyTaxError",
    "RecordTaxSettlementCommand",
    "TaxSettlementId",
    "TaxSettlementPersistence",
    "tax_settlement_persistence_adapter",
    "validate_new_tax_settlement",
    "AccountingEntryReference",
    "BankTransactionReference",
    "DocumentReference"
]
