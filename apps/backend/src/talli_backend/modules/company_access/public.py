"""The only supported Python import path for the company-access capability."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from importlib.resources import files
from typing import Annotated, Literal, Protocol, TypeVar, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, field_validator


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class CompanyAccessModel(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


class CompanyAccessCommandModel(CompanyAccessModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        frozen=True,
        extra="forbid",
    )


class CompanyAccessResponseModel(CompanyAccessModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True, extra="forbid")


class CompanyContext(CompanyAccessModel):
    id: str
    org_number: str
    name: str
    entity_type: str
    address: str
    postal_code: str
    city: str
    status_text: str
    source: str
    created_by: str
    identity_confirmed_at: str | None
    identity_locked_at: str | None
    created_at: str
    role: Literal["owner"]
    resource_scope: Literal["owner_sensitive"]
    aal: Literal["aal2"]
    current_agreement_accepted: bool
    company_year_admission_id: UUID | None
    admitted_accounting_year: int | None
    current_eligibility_decision: Literal["supported", "clarify", "blocked"] | None
    eligibility_reason_explanations: list[str]
    eligibility_next_step_code: str | None
    eligibility_next_step: str | None
    consequential_operations_allowed: bool
    archive_export_available: bool


class CompanyContextResponse(CompanyAccessModel):
    selected_company: CompanyContext
    companies: list[CompanyContext]


CompanyAccessRole = Literal["owner", "reviewer", "read_only"]


class CompanyAccessRecord(CompanyAccessResponseModel):
    id: str
    org_number: str
    name: str
    entity_type: str
    address: str
    postal_code: str
    city: str
    status_text: str
    source: str
    created_by: str
    identity_confirmed_at: str | None
    identity_locked_at: str | None
    created_at: str
    role: CompanyAccessRole


class CompanyAccessRecordResponse(CompanyAccessResponseModel):
    company: CompanyAccessRecord


class OperatorContextResponse(CompanyAccessResponseModel):
    role: Literal["support", "admin"]
    active: Literal[True]


class OperatorCompanyRecord(CompanyAccessResponseModel):
    id: str
    org_number: str
    name: str
    entity_type: str
    address: str
    postal_code: str
    city: str
    status_text: str
    source: str
    created_by: str
    identity_confirmed_at: str | None
    identity_locked_at: str | None
    created_at: str


class OperatorCompanySearchResponse(CompanyAccessResponseModel):
    companies: list[OperatorCompanyRecord]


CURRENT_BUSINESS_TERMS_VERSION: Literal["2026-07-17"] = "2026-07-17"
CURRENT_BUSINESS_TERMS_EFFECTIVE_DATE: Literal["2026-07-17"] = "2026-07-17"
CURRENT_BUSINESS_TERMS_PATH: Literal["/vilkar"] = "/vilkar"
CURRENT_BUSINESS_TERMS_SHA256: Literal[
    "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543"
] = "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543"
CURRENT_DPA_VERSION: Literal["2026-07-17"] = "2026-07-17"
CURRENT_DPA_EFFECTIVE_DATE: Literal["2026-07-17"] = "2026-07-17"
CURRENT_DPA_PATH: Literal["/databehandleravtale"] = "/databehandleravtale"
CURRENT_DPA_SHA256: Literal[
    "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c"
] = "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c"
CURRENT_AUTHORITY_STATEMENT_VERSION: Literal["authority-v1"] = "authority-v1"
CURRENT_ACCEPTANCE_METHOD: Literal["in_app_clickwrap"] = "in_app_clickwrap"
CURRENT_PRIVACY_NOTICE_VERSION: Literal["2026-07-15"] = "2026-07-15"
CURRENT_PRIVACY_NOTICE_EFFECTIVE_DATE: Literal["2026-07-15"] = "2026-07-15"
CURRENT_PRIVACY_NOTICE_PATH: Literal["/personvern"] = "/personvern"
CURRENT_PRIVACY_NOTICE_SHA256: Literal[
    "4777d7b1bce8218219db06f40c255ca9ef6e0d5f1c84ccdc9b5616b75b9d472c"
] = "4777d7b1bce8218219db06f40c255ca9ef6e0d5f1c84ccdc9b5616b75b9d472c"


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _load_capability_manifest() -> tuple[Mapping[str, object], str]:
    try:
        raw = json.loads(
            files(__package__).joinpath("capability_manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        raise RuntimeError("company_access_capability_manifest_unavailable") from None
    if not isinstance(raw, Mapping):
        raise RuntimeError("company_access_capability_manifest_invalid")
    if (
        raw.get("schemaVersion") != "1.0"
        or raw.get("manifestId") != "company-year-admission"
        or raw.get("accountingYear") != 2026
        or raw.get("boundaryVersion") != "2026.1"
        or raw.get("changeKind") != "baseline"
    ):
        raise RuntimeError("company_access_capability_manifest_invalid")
    public_rules = raw.get("publicRules")
    public_reason_explanations = (
        public_rules.get("reasonExplanations")
        if isinstance(public_rules, Mapping)
        else None
    )
    if (
        not isinstance(public_reason_explanations, Mapping)
        or set(public_reason_explanations)
        != {
            "ACCOUNTING_YEAR_NOT_AVAILABLE",
            "LEGAL_FORM_NOT_SUPPORTED",
            "COMPANY_STATUS_NOT_SUPPORTED",
        }
        or not all(
            isinstance(explanation, str) and 1 <= len(explanation) <= 240
            for explanation in public_reason_explanations.values()
        )
    ):
        raise RuntimeError("company_access_capability_manifest_invalid")
    questions = raw.get("questions")
    if not isinstance(questions, list) or not questions:
        raise RuntimeError("company_access_capability_manifest_invalid")
    seen: set[str] = set()
    for question in questions:
        if not isinstance(question, Mapping):
            raise RuntimeError("company_access_capability_manifest_invalid")
        code = question.get("code")
        prompt = question.get("prompt")
        supported_answer = question.get("supportedAnswer")
        blocked_reason = question.get("blockedReasonCode")
        if (
            not isinstance(code, str)
            or not code
            or code in seen
            or not isinstance(prompt, str)
            or not prompt
            or supported_answer not in {"yes", "no"}
            or not isinstance(blocked_reason, str)
            or not blocked_reason
        ):
            raise RuntimeError("company_access_capability_manifest_invalid")
        seen.add(code)
    promise = raw.get("promise")
    if not isinstance(promise, Mapping):
        raise RuntimeError("company_access_capability_manifest_invalid")
    required_capabilities = {
        "current_year_reconstruction",
        "year_round_bookkeeping",
        "required_corporate_documents",
        "rf1086_direct_filing",
        "company_tax_direct_filing",
        "annual_accounts_direct_filing",
        "bank_connection_with_hardened_file_fallback",
        "saft_1_40",
        "company_year_archive",
        "corrections",
        "official_outcomes",
        "receipts",
    }
    capabilities = promise.get("capabilities")
    customer_claims = promise.get("customerClaims")
    if (
        promise.get("mode") != "atomic_company_year"
        or promise.get("startsOn") != "2026-01-01"
        or promise.get("endsOn") != "2026-12-31"
        or promise.get("reconstructFrom") != "2026-01-01"
        or promise.get("earlierYearsIncluded") is not False
        or promise.get("onlyAccountingAndFilingProduct") is not True
        or not isinstance(capabilities, list)
        or set(capabilities) != required_capabilities
        or not isinstance(customer_claims, list)
        or len(customer_claims) != len(required_capabilities)
        or len(set(customer_claims)) != len(customer_claims)
        or not all(
            isinstance(claim, str) and 1 <= len(claim) <= 160
            for claim in customer_claims
        )
    ):
        raise RuntimeError("company_access_capability_manifest_invalid")
    required_rechecks = {
        "public_fact_changed",
        "material_answer_changed",
        "manifest_changed",
        "before_payment",
        "before_filing",
    }
    recheck_triggers = raw.get("recheckTriggers")
    if not isinstance(recheck_triggers, list) or set(recheck_triggers) != required_rechecks:
        raise RuntimeError("company_access_capability_manifest_invalid")
    change_control = raw.get("changeControl")
    if (
        not isinstance(change_control, Mapping)
        or change_control.get("acceptedPromiseIsImmutable") is not True
        or change_control.get("newSafetyOrLegalBlocksApplyImmediately") is not True
        or change_control.get("boundaryRemovalRequires")
        != [
            "reopened_172",
            "refreshed_practical_majority_evidence",
            "approval_180",
        ]
    ):
        raise RuntimeError("company_access_capability_manifest_invalid")
    return raw, _canonical_sha256(raw)


CAPABILITY_MANIFEST, CURRENT_CAPABILITY_MANIFEST_SHA256 = _load_capability_manifest()
CURRENT_CAPABILITY_MANIFEST_VERSION: Literal["2026.1"] = "2026.1"
CURRENT_CAPABILITY_ACCOUNTING_YEAR: Literal[2026] = 2026


EligibilityAnswer = Literal["yes", "no", "unknown"]
EligibilityDecision = Literal["supported", "clarify", "blocked"]
EligibilityRecheckTrigger = Literal[
    "public_fact_changed",
    "material_answer_changed",
    "manifest_changed",
    "before_payment",
    "before_filing",
]


class EligibilityPrecheckRequest(CompanyAccessCommandModel):
    org_number: str = Field(pattern=r"^[0-9]{9}$")
    accounting_year: int = Field(ge=2000, le=2100)


class EligibilityDefinitiveRequest(EligibilityPrecheckRequest):
    expected_public_facts_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    capability_manifest_version: str = Field(min_length=1, max_length=100)
    capability_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    answers: dict[str, EligibilityAnswer]


class EligibilityPublicFacts(CompanyAccessResponseModel):
    org_number: str
    name: str
    entity_type: str
    status_text: str
    source: str


class EligibilityQuestion(CompanyAccessResponseModel):
    code: str
    prompt: str
    answer_options: tuple[Literal["yes", "no", "unknown"], ...] = (
        "yes",
        "no",
        "unknown",
    )


class CompanyYearPromise(CompanyAccessResponseModel):
    accounting_year: int
    starts_on: str
    ends_on: str
    reconstruction_required_from: str
    only_accounting_and_filing_product: Literal[True]
    customer_claims: list[str]


class EligibilityDecisionResponse(CompanyAccessResponseModel):
    decision: EligibilityDecision
    provisional: bool
    capability_manifest_version: str
    capability_manifest_sha256: str
    accounting_year: int
    public_facts: EligibilityPublicFacts
    public_facts_sha256: str
    questions: list[EligibilityQuestion]
    question_codes: list[str]
    answers: dict[str, EligibilityAnswer]
    answers_sha256: str | None
    reason_codes: list[str]
    reason_explanations: list[str]
    next_step_code: str
    next_step: str
    company_year_promise: CompanyYearPromise | None


class CompanyYearAdmissionResponse(CompanyAccessResponseModel):
    company_id: UUID
    company_year_admission_id: UUID
    accounting_year: int
    reconstruct_from: str
    capability_manifest_version: str
    capability_manifest_sha256: str
    current_agreement_accepted: Literal[True]
    replayed: bool


class CompanyYearEligibilityRecheckRequest(CompanyAccessCommandModel):
    operation_id: UUID
    trigger: EligibilityRecheckTrigger
    answers: dict[str, EligibilityAnswer] | None = None


class CompanyYearEligibilityStateResponse(CompanyAccessResponseModel):
    company_year_eligibility_assessment_id: UUID
    company_year_admission_id: UUID
    company_id: UUID
    accounting_year: int
    trigger: EligibilityRecheckTrigger
    decision: EligibilityDecision
    accepted_capability_manifest_version: str
    accepted_capability_manifest_sha256: str
    current_capability_manifest_version: str
    current_capability_manifest_sha256: str
    accepted_company_year_promise: CompanyYearPromise
    reason_codes: list[str]
    reason_explanations: list[str]
    next_step_code: str
    next_step: str
    consequential_operations_allowed: bool
    archive_export_available: Literal[True]
    replayed: bool


class CurrentAgreementRequest(CompanyAccessCommandModel):
    agreement_accepted: Literal[True]
    business_terms_version: Literal["2026-07-17"]
    business_terms_sha256: Literal[
        "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543"
    ]
    dpa_version: Literal["2026-07-17"]
    dpa_sha256: Literal[
        "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c"
    ]


class CompanyYearAdmissionRequest(CurrentAgreementRequest):
    operation_id: UUID
    org_number: str = Field(pattern=r"^[0-9]{9}$")
    accounting_year: int = Field(ge=2000, le=2100)
    expected_public_facts_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    capability_manifest_version: str = Field(min_length=1, max_length=100)
    capability_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    answers: dict[str, EligibilityAnswer]
    authority_accepted: Literal[True]
    company_year_promise_accepted: Literal[True]
    privacy_notice_version: str = Field(min_length=1, max_length=100)
    privacy_notice_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CompanyOnboardingRequest(CurrentAgreementRequest):
    org_number: str = Field(pattern=r"^[0-9]{9}$")


class CompanyAgreementAcceptanceRequest(CurrentAgreementRequest):
    company_id: UUID


class CompanyOnboardingResponse(CompanyAccessResponseModel):
    company_id: UUID
    current_agreement_accepted: Literal[True]
    replayed: bool


class CompanyAgreementAcceptanceResponse(CompanyAccessResponseModel):
    company_id: UUID
    current_agreement_accepted: Literal[True]
    replayed: bool


class CompanyRegistryIdentity(CompanyAccessCommandModel):
    org_number: str = Field(pattern=r"^[0-9]{9}$")
    name: str = Field(min_length=1)
    entity_type: str
    address: str
    postal_code: str
    city: str
    status_text: str
    source: Literal["brreg"]


class CompanyYearAdmissionGatewayCommand(CompanyAccessCommandModel):
    operation_id: UUID
    verified_actor: UUID
    verified_email: str
    company: CompanyRegistryIdentity
    accounting_year: int
    reconstruct_from: str
    public_facts_json: str
    public_facts_sha256: str
    answers_json: str
    answers_sha256: str
    capability_manifest_json: str
    company_year_promise_json: str
    company_year_promise_sha256: str
    capability_manifest_version: Literal["2026.1"] = CURRENT_CAPABILITY_MANIFEST_VERSION
    capability_manifest_sha256: str = CURRENT_CAPABILITY_MANIFEST_SHA256
    business_terms_version: Literal["2026-07-17"] = CURRENT_BUSINESS_TERMS_VERSION
    business_terms_effective_date: Literal["2026-07-17"] = CURRENT_BUSINESS_TERMS_EFFECTIVE_DATE
    business_terms_path: Literal["/vilkar"] = CURRENT_BUSINESS_TERMS_PATH
    business_terms_sha256: Literal[
        "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543"
    ] = CURRENT_BUSINESS_TERMS_SHA256
    dpa_version: Literal["2026-07-17"] = CURRENT_DPA_VERSION
    dpa_effective_date: Literal["2026-07-17"] = CURRENT_DPA_EFFECTIVE_DATE
    dpa_path: Literal["/databehandleravtale"] = CURRENT_DPA_PATH
    dpa_sha256: Literal[
        "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c"
    ] = CURRENT_DPA_SHA256
    privacy_notice_version: Literal["2026-07-15"] = CURRENT_PRIVACY_NOTICE_VERSION
    privacy_notice_effective_date: Literal[
        "2026-07-15"
    ] = CURRENT_PRIVACY_NOTICE_EFFECTIVE_DATE
    privacy_notice_path: Literal["/personvern"] = CURRENT_PRIVACY_NOTICE_PATH
    privacy_notice_sha256: Literal[
        "4777d7b1bce8218219db06f40c255ca9ef6e0d5f1c84ccdc9b5616b75b9d472c"
    ] = CURRENT_PRIVACY_NOTICE_SHA256
    authority_statement_version: Literal["authority-v1"] = CURRENT_AUTHORITY_STATEMENT_VERSION
    acceptance_method: Literal["in_app_clickwrap"] = CURRENT_ACCEPTANCE_METHOD


class CompanyYearEligibilityRecheckGatewayCommand(CompanyAccessCommandModel):
    operation_id: UUID
    verified_actor: UUID
    company_year_admission_id: UUID
    company_id: UUID
    accounting_year: int
    previous_assessment_id: UUID
    trigger: EligibilityRecheckTrigger
    decision: EligibilityDecision
    capability_manifest_json: str
    public_facts_json: str
    public_facts_sha256: str
    answers_json: str
    answers_sha256: str
    reason_codes: tuple[str, ...]
    reason_explanations: tuple[str, ...]
    next_step_code: str
    next_step: str
    consequential_operations_allowed: bool
    capability_manifest_version: Literal["2026.1"] = CURRENT_CAPABILITY_MANIFEST_VERSION
    capability_manifest_sha256: str = CURRENT_CAPABILITY_MANIFEST_SHA256
    archive_export_available: Literal[True] = True


class CompanyAgreementAcceptanceGatewayCommand(CompanyAccessCommandModel):
    operation_id: UUID
    company_id: UUID
    verified_actor: UUID
    verified_email: str
    business_terms_version: Literal["2026-07-17"] = CURRENT_BUSINESS_TERMS_VERSION
    business_terms_effective_date: Literal["2026-07-17"] = CURRENT_BUSINESS_TERMS_EFFECTIVE_DATE
    business_terms_path: Literal["/vilkar"] = CURRENT_BUSINESS_TERMS_PATH
    business_terms_sha256: Literal[
        "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543"
    ] = CURRENT_BUSINESS_TERMS_SHA256
    dpa_version: Literal["2026-07-17"] = CURRENT_DPA_VERSION
    dpa_effective_date: Literal["2026-07-17"] = CURRENT_DPA_EFFECTIVE_DATE
    dpa_path: Literal["/databehandleravtale"] = CURRENT_DPA_PATH
    dpa_sha256: Literal[
        "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c"
    ] = CURRENT_DPA_SHA256
    authority_statement_version: Literal["authority-v1"] = CURRENT_AUTHORITY_STATEMENT_VERSION
    acceptance_method: Literal["in_app_clickwrap"] = CURRENT_ACCEPTANCE_METHOD


InvitationRole = Literal["reviewer", "read_only"]
InvitationStatus = Literal["pending", "accepted", "revoked", "expired"]
MembershipState = Literal["active", "removed"]
_RFC3339_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)


def _require_rfc3339_timestamp(value: object) -> object:
    if not isinstance(value, str) or _RFC3339_TIMESTAMP.fullmatch(value) is None:
        raise ValueError("timestamp must be an RFC3339 string")
    return value


StrictAwareDatetime = Annotated[AwareDatetime, BeforeValidator(_require_rfc3339_timestamp)]


class CreateCompanyInvitationRequest(CompanyAccessCommandModel):
    operation_id: UUID
    company_id: UUID
    invited_email: str
    role: InvitationRole


class InvitationTokenRequest(CompanyAccessCommandModel):
    token: str


class AcceptCompanyInvitationRequest(CompanyAccessCommandModel):
    operation_id: UUID
    token: str


class CompanyInvitationCommandRequest(CompanyAccessCommandModel):
    operation_id: UUID
    company_id: UUID
    expected_updated_at: StrictAwareDatetime


class AdministerCompanyMembershipRequest(CompanyAccessCommandModel):
    operation_id: UUID
    company_id: UUID
    expected_role: InvitationRole
    role: InvitationRole | None = None
    state: MembershipState | None = None


CancellationStatus = Literal["export_required", "retention_hold", "deletion_approved", "deleted", "superseded"]
DeletionReviewDecision = Literal["approved", "rejected"]


class RequestCompanyCancellationRequest(CompanyAccessCommandModel):
    operation_id: UUID
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason must not be blank")
        return normalized


class ReviewCompanyDeletionRequest(CompanyAccessCommandModel):
    operation_id: UUID
    company_id: UUID
    expected_updated_at: StrictAwareDatetime
    decision: DeletionReviewDecision
    evidence_reference: str = Field(min_length=1, max_length=500)

    @field_validator("evidence_reference")
    @classmethod
    def normalize_evidence_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("evidenceReference must not be blank")
        return normalized


class FinalizeCompanyDeletionRequest(CompanyAccessCommandModel):
    operation_id: UUID
    company_id: UUID
    expected_updated_at: StrictAwareDatetime


class ResumeCompanyCancellationRequest(CompanyAccessCommandModel):
    operation_id: UUID
    company_id: UUID
    income_year: int = Field(ge=2000, le=2100)
    expected_updated_at: StrictAwareDatetime


class CreateInvitationGatewayCommand(CompanyAccessCommandModel):
    operation_id: str
    company_id: str
    invited_email: str
    role: InvitationRole
    token_hash: str
    acceptance_token: str


class InvitationIdentityGatewayCommand(CompanyAccessCommandModel):
    token_hash: str
    verified_subject: str
    verified_email: str


class AcceptInvitationGatewayCommand(InvitationIdentityGatewayCommand):
    operation_id: str


class InvitationMutationGatewayCommand(CompanyAccessCommandModel):
    operation_id: str
    company_id: str
    invitation_id: str
    expected_updated_at: str


class ResendInvitationGatewayCommand(InvitationMutationGatewayCommand):
    token_hash: str
    acceptance_token: str


class AdministerMembershipGatewayCommand(CompanyAccessCommandModel):
    operation_id: str
    company_id: str
    user_id: str
    expected_role: InvitationRole
    role: InvitationRole | None
    state: MembershipState | None


class RequestCompanyCancellationGatewayCommand(CompanyAccessCommandModel):
    operation_id: str
    company_id: str
    income_year: int
    reason: str


class ReviewCompanyDeletionGatewayCommand(CompanyAccessCommandModel):
    operation_id: str
    cancellation_id: str
    company_id: str
    expected_updated_at: str
    decision: DeletionReviewDecision
    evidence_reference: str


class ResumeCompanyCancellationGatewayCommand(CompanyAccessCommandModel):
    operation_id: str
    cancellation_id: str
    company_id: str
    income_year: int
    expected_updated_at: str


class FinalizeCompanyDeletionGatewayCommand(CompanyAccessCommandModel):
    operation_id: str
    cancellation_id: str
    company_id: str
    expected_updated_at: str


class CompanyInvitation(CompanyAccessModel):
    id: str
    company_id: str
    invited_email: str
    role: InvitationRole
    status: InvitationStatus
    expires_at: str
    created_at: str
    updated_at: str


class CompanyInvitationResponse(CompanyAccessModel):
    invitation: CompanyInvitation
    delivery_token: str | None
    delivery_subject: str | None
    delivery_body: str | None


class CompanyInvitationListResponse(CompanyAccessModel):
    invitations: list[CompanyInvitation]


class InvitationLookup(CompanyAccessModel):
    company_name: str
    role: InvitationRole
    expires_at: str


class CompanyMembership(CompanyAccessModel):
    company_id: str
    user_id: str
    role: InvitationRole
    state: MembershipState
    accepted_at: str


class CompanyMembershipResponse(CompanyAccessModel):
    membership: CompanyMembership


class CompanyMembershipListResponse(CompanyAccessModel):
    memberships: list[CompanyMembership]


class CompanyCancellationEvidence(CompanyAccessResponseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True, extra="forbid")

    archive_exported_at: AwareDatetime | None = None
    archive_income_year: int | None = Field(default=None, ge=2000, le=2100)
    archive_download_path: str | None = None
    retention_classes: list[str] = Field(default_factory=list)
    missing_document_ids: list[UUID] = Field(default_factory=list)
    legal_review_required: bool = True
    corporate_object_keys: list[str] = Field(default_factory=list)
    missing_corporate_object_keys: list[str] = Field(default_factory=list)
    corporate_evidence_complete: bool | None = None


class CompanyCancellation(CompanyAccessResponseModel):
    id: UUID
    company_id: UUID
    status: CancellationStatus
    reason: str = Field(min_length=1, max_length=1000)
    evidence: CompanyCancellationEvidence
    requested_by: UUID
    requested_at: AwareDatetime
    reviewed_by: UUID | None
    reviewed_at: AwareDatetime | None
    deleted_by: UUID | None
    deleted_at: AwareDatetime | None
    updated_at: AwareDatetime


class CompanyCancellationResponse(CompanyAccessResponseModel):
    cancellation: CompanyCancellation


class CompanyCancellationListResponse(CompanyAccessResponseModel):
    cancellations: list[CompanyCancellation]


class CompanyDeletionReview(CompanyAccessResponseModel):
    id: UUID
    cancellation_id: UUID
    company_id: UUID
    decision: DeletionReviewDecision
    evidence_reference: str = Field(min_length=1, max_length=500)
    reviewed_by: UUID
    reviewed_at: AwareDatetime
    operation_id: UUID
    cancellation_revision: AwareDatetime


class CompanyDeletionReviewResponse(CompanyAccessResponseModel):
    cancellation: CompanyCancellation
    review: CompanyDeletionReview


InvitationSideEffectCommand = Literal[
    "create_invitation", "accept_invitation", "revoke_invitation", "resend_invitation"
]


class InvitationSideEffectContinuation(CompanyAccessModel):
    operation_id: str
    command_name: InvitationSideEffectCommand
    company_id: str
    invitation: CompanyInvitation | None
    membership: CompanyMembership | None
    delivery_token: str | None
    delivery_subject: str | None
    delivery_body: str | None


class InvitationSideEffectContinuationList(CompanyAccessModel):
    continuations: list[InvitationSideEffectContinuation]


class InvitationSideEffectCompletion(CompanyAccessModel):
    operation_id: str
    completed: Literal[True]


class CompanyAccessError(Exception):
    def __init__(self, *, status: int, code: str, title: str, detail: str) -> None:
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail


class CompanyAccessGateway(Protocol):
    """Validate sessions and read company data through that session's RLS scope."""

    async def session_subject(self, access_token: str) -> str: ...

    async def session_identity(self, access_token: str) -> Mapping[str, object]: ...

    async def memberships(self, access_token: str, subject: str) -> list[Mapping[str, object]]: ...

    async def companies(self, access_token: str, company_ids: list[str]) -> list[Mapping[str, object]]: ...

    async def agreement_acceptances(
        self, access_token: str, company_ids: list[str]
    ) -> list[Mapping[str, object]]: ...

    async def company_year_access_states(
        self, access_token: str, company_ids: list[str]
    ) -> list[Mapping[str, object]]: ...

    async def support_operator(
        self, access_token: str, subject: str
    ) -> Mapping[str, object] | None: ...

    async def search_operator_companies(
        self, access_token: str, query: str
    ) -> list[Mapping[str, object]]: ...

    async def admit_company_year(
        self, access_token: str, command: CompanyYearAdmissionGatewayCommand
    ) -> Mapping[str, object]: ...

    async def company_year_admission_replay(
        self, access_token: str, operation_id: str
    ) -> Mapping[str, object] | None: ...

    async def company_year_admission_context(
        self, access_token: str, company_year_admission_id: str, operation_id: str
    ) -> Mapping[str, object] | None: ...

    async def record_company_year_eligibility_recheck(
        self, access_token: str, command: CompanyYearEligibilityRecheckGatewayCommand
    ) -> Mapping[str, object]: ...

    async def reaccept_agreement(
        self, access_token: str, command: CompanyAgreementAcceptanceGatewayCommand
    ) -> Mapping[str, object]: ...

    async def invitations(self, access_token: str, company_id: str) -> list[Mapping[str, object]]: ...

    async def create_invitation(
        self, access_token: str, command: CreateInvitationGatewayCommand
    ) -> Mapping[str, object]: ...

    async def lookup_invitation(
        self, access_token: str, command: InvitationIdentityGatewayCommand
    ) -> Mapping[str, object] | None: ...

    async def accept_invitation(
        self, access_token: str, command: AcceptInvitationGatewayCommand
    ) -> Mapping[str, object] | None: ...

    async def revoke_invitation(
        self, access_token: str, command: InvitationMutationGatewayCommand
    ) -> Mapping[str, object] | None: ...

    async def resend_invitation(
        self, access_token: str, command: ResendInvitationGatewayCommand
    ) -> Mapping[str, object] | None: ...

    async def company_memberships(
        self, access_token: str, company_id: str
    ) -> list[Mapping[str, object]]: ...

    async def administer_membership(
        self, access_token: str, command: AdministerMembershipGatewayCommand
    ) -> Mapping[str, object] | None: ...

    async def pending_invitation_side_effects(
        self, access_token: str
    ) -> list[Mapping[str, object]]: ...

    async def complete_invitation_side_effect(
        self, access_token: str, operation_id: str
    ) -> bool: ...

    async def cancellations(
        self, access_token: str, company_id: str
    ) -> list[Mapping[str, object]]: ...

    async def request_cancellation(
        self, access_token: str, command: RequestCompanyCancellationGatewayCommand
    ) -> Mapping[str, object] | None: ...

    async def review_deletion(
        self, access_token: str, command: ReviewCompanyDeletionGatewayCommand
    ) -> Mapping[str, object] | None: ...

    async def resume_cancellation(
        self, access_token: str, command: ResumeCompanyCancellationGatewayCommand
    ) -> Mapping[str, object] | None: ...

    async def finalize_deletion(
        self, access_token: str, command: FinalizeCompanyDeletionGatewayCommand
    ) -> Mapping[str, object] | None: ...


class CompanyRegistryGateway(Protocol):
    """Resolve a public Norwegian organization identity without owning support policy."""

    async def lookup_company(self, org_number: str) -> Mapping[str, object]: ...


Adapter = TypeVar("Adapter", bound=type)


def company_access_adapter(port: type[object]) -> Callable[[Adapter], Adapter]:
    """Register a source-level outbound adapter binding for architecture verification."""

    def register(adapter: Adapter) -> Adapter:
        setattr(adapter, "__talli_port__", port)  # noqa: B010
        return adapter

    return register


def company_registry_adapter(port: type[object]) -> Callable[[Adapter], Adapter]:
    """Register the public-company-registry adapter used by onboarding."""

    def register(adapter: Adapter) -> Adapter:
        setattr(adapter, "__talli_port__", port)  # noqa: B010
        return adapter

    return register


def _token_aal(access_token: str) -> Literal["aal1", "aal2"]:
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise CompanyAccessError(
            status=401,
            code="AUTHENTICATION_REQUIRED",
            title="Authentication required",
            detail="A valid session is required.",
        ) from None
    return "aal2" if claims.get("aal") == "aal2" else "aal1"


def _manifest_mapping(key: str) -> Mapping[str, object]:
    value = CAPABILITY_MANIFEST.get(key)
    if not isinstance(value, Mapping):
        raise RuntimeError("company_access_capability_manifest_invalid")
    return value


def _manifest_question_definitions() -> list[Mapping[str, object]]:
    value = CAPABILITY_MANIFEST.get("questions")
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise RuntimeError("company_access_capability_manifest_invalid")
    return cast(list[Mapping[str, object]], value)


def _eligibility_questions(
    definitions: list[Mapping[str, object]],
) -> list[EligibilityQuestion]:
    return [
        EligibilityQuestion(code=str(item["code"]), prompt=str(item["prompt"]))
        for item in definitions
    ]


def _registry_identity(raw: Mapping[str, object], *, expected_org_number: str) -> CompanyRegistryIdentity:
    try:
        company = CompanyRegistryIdentity.model_validate(raw)
    except ValueError:
        raise _company_registry_unavailable() from None
    if company.org_number != expected_org_number:
        raise _company_registry_unavailable()
    return company


def _eligibility_public_facts(company: CompanyRegistryIdentity) -> EligibilityPublicFacts:
    return EligibilityPublicFacts(
        org_number=company.org_number,
        name=company.name,
        entity_type=company.entity_type,
        status_text=company.status_text,
        source=company.source,
    )


def _public_fact_block_reasons(
    company: CompanyRegistryIdentity, *, accounting_year: int
) -> list[str]:
    if accounting_year != CURRENT_CAPABILITY_ACCOUNTING_YEAR:
        return ["ACCOUNTING_YEAR_NOT_AVAILABLE"]
    rules = _manifest_mapping("publicRules")
    entity_types = rules.get("supportedEntityTypes")
    statuses = rules.get("supportedStatusTexts")
    if not isinstance(entity_types, list) or company.entity_type not in entity_types:
        return [str(rules["legalFormBlockReasonCode"])]
    if not isinstance(statuses, list) or company.status_text not in statuses:
        return [str(rules["statusBlockReasonCode"])]
    return []


def _company_year_promise(accounting_year: int) -> CompanyYearPromise:
    promise = _manifest_mapping("promise")
    return CompanyYearPromise(
        accounting_year=accounting_year,
        starts_on=str(promise["startsOn"]),
        ends_on=str(promise["endsOn"]),
        reconstruction_required_from=str(promise["reconstructFrom"]),
        only_accounting_and_filing_product=True,
        customer_claims=cast(list[str], promise["customerClaims"]),
    )


def _eligibility_decision_response(
    *,
    company: CompanyRegistryIdentity,
    accounting_year: int,
    decision: EligibilityDecision,
    provisional: bool,
    question_definitions: list[Mapping[str, object]],
    answers: Mapping[str, EligibilityAnswer],
    reason_codes: list[str],
) -> EligibilityDecisionResponse:
    outcomes = _manifest_mapping("outcomes")
    if decision == "supported":
        next_step_code = str(outcomes["supportedNextStepCode"])
        next_step = str(outcomes["supportedNextStep"])
    elif decision == "clarify" and provisional:
        next_step_code = str(outcomes["precheckNextStepCode"])
        next_step = str(outcomes["precheckNextStep"])
    elif decision == "clarify":
        next_step_code = str(outcomes["clarifyNextStepCode"])
        next_step = str(outcomes["clarifyNextStep"])
    else:
        next_step_code = str(outcomes["blockedNextStepCode"])
        next_step = str(outcomes["blockedNextStep"])
    public_facts = _eligibility_public_facts(company)
    public_facts_payload = public_facts.model_dump(mode="json", by_alias=True)
    normalized_answers = dict(sorted(answers.items()))
    public_reason_explanations = _manifest_mapping("publicRules").get(
        "reasonExplanations"
    )
    if not isinstance(public_reason_explanations, Mapping):
        raise RuntimeError("company_access_capability_manifest_invalid")
    reason_explanations = [
        str(public_reason_explanations[code])
        for code in reason_codes
        if code in public_reason_explanations
    ]
    if decision in ("blocked", "clarify"):
        prefix = (
            "Dette svaret er utenfor grensen:"
            if decision == "blocked"
            else "Dette må avklares:"
        )
        reason_explanations.extend(
            f"{prefix} {definition['prompt']}" for definition in question_definitions
        )
    return EligibilityDecisionResponse(
        decision=decision,
        provisional=provisional,
        capability_manifest_version=CURRENT_CAPABILITY_MANIFEST_VERSION,
        capability_manifest_sha256=CURRENT_CAPABILITY_MANIFEST_SHA256,
        accounting_year=accounting_year,
        public_facts=public_facts,
        public_facts_sha256=_canonical_sha256(public_facts_payload),
        questions=_eligibility_questions(question_definitions),
        question_codes=[str(item["code"]) for item in question_definitions],
        answers=normalized_answers,
        answers_sha256=(
            _canonical_sha256(normalized_answers) if normalized_answers else None
        ),
        reason_codes=reason_codes,
        reason_explanations=reason_explanations,
        next_step_code=next_step_code,
        next_step=next_step,
        company_year_promise=(
            _company_year_promise(accounting_year) if decision == "supported" else None
        ),
    )


def _assert_current_capability_manifest(*, version: str, sha256: str) -> None:
    if (
        version != CURRENT_CAPABILITY_MANIFEST_VERSION
        or sha256 != CURRENT_CAPABILITY_MANIFEST_SHA256
    ):
        raise CompanyAccessError(
            status=409,
            code="ELIGIBILITY_MANIFEST_CHANGED",
            title="Eligibility rules changed",
            detail="The eligibility rules changed. Start a new free company check.",
        )


def _assert_current_privacy_notice(*, version: str, sha256: str) -> None:
    if version != CURRENT_PRIVACY_NOTICE_VERSION or sha256 != CURRENT_PRIVACY_NOTICE_SHA256:
        raise CompanyAccessError(
            status=409,
            code="ADMISSION_EVIDENCE_CHANGED",
            title="Admission evidence changed",
            detail="The privacy notice changed. Read it and accept the company year again.",
        )


class CompanyAccessService:
    def __init__(
        self,
        gateway: CompanyAccessGateway,
        company_registry: CompanyRegistryGateway | None = None,
    ) -> None:
        self._gateway = gateway
        self._company_registry = company_registry

    async def selected_context(
        self,
        access_token: str,
        *,
        company_id: str | None,
    ) -> CompanyContextResponse:
        subject = await self._gateway.session_subject(access_token)
        aal = _token_aal(access_token)
        # This operation deliberately has one server-owned policy. A caller may
        # choose a company they own, but may never lower its owner-sensitive
        # scope or AAL2 requirement.
        memberships = await self._gateway.memberships(access_token, subject)
        roles = {
            str(item["company_id"]): str(item["role"])
            for item in memberships
            if item.get("accepted_at") is not None
            and item.get("role") == "owner"
        }
        if company_id is not None and company_id not in roles:
            raise CompanyAccessError(
                status=404,
                code="COMPANY_CONTEXT_NOT_FOUND",
                title="Company context not found",
                detail="The requested company context was not found.",
            )
        if not roles:
            raise CompanyAccessError(
                status=404,
                code="COMPANY_CONTEXT_NOT_FOUND",
                title="Company context not found",
                detail="The requested company context was not found.",
            )
        if aal != "aal2":
            raise CompanyAccessError(
                status=403,
                code="AAL2_REQUIRED",
                title="Additional verification required",
                detail="Additional verification is required for this company context.",
            )
        allowed_ids = [company_id] if company_id else list(roles)
        companies = await self._gateway.companies(access_token, allowed_ids)

        def is_permitted_company(company: Mapping[str, object]) -> bool:
            persisted_id = company.get("id")
            return isinstance(persisted_id, (str, UUID)) and str(persisted_id) in roles

        permitted_companies = [
            company
            for company in companies
            if is_permitted_company(company)
        ]
        if not permitted_companies:
            raise CompanyAccessError(
                status=404,
                code="COMPANY_CONTEXT_NOT_FOUND",
                title="Company context not found",
                detail="The requested company context was not found.",
            )

        agreement_rows = await self._gateway.agreement_acceptances(
            access_token,
            [str(company["id"]) for company in permitted_companies],
        )
        current_agreement_company_ids = {
            str(row.get("company_id"))
            for row in agreement_rows
            if _is_current_agreement(row)
        }
        company_year_rows = await self._gateway.company_year_access_states(
            access_token, [str(company["id"]) for company in permitted_companies]
        )
        company_year_states: dict[str, Mapping[str, object]] = {}
        for row in company_year_rows:
            state_company_id = str(row.get("company_id"))
            if state_company_id not in roles or state_company_id in company_year_states:
                raise _company_access_unavailable()
            try:
                UUID(str(row["company_year_admission_id"]))
                admitted_year = int(str(row["admitted_accounting_year"]))
            except (KeyError, TypeError, ValueError):
                raise _company_access_unavailable() from None
            decision = row.get("current_eligibility_decision")
            latest_manifest_version = row.get("latest_capability_manifest_version")
            latest_manifest_sha256 = row.get("latest_capability_manifest_sha256")
            reason_explanations = row.get("eligibility_reason_explanations")
            next_step_code = row.get("eligibility_next_step_code")
            next_step = row.get("eligibility_next_step")
            allowed = row.get("consequential_operations_allowed")
            archive_available = row.get("archive_export_available")
            if (
                admitted_year != CURRENT_CAPABILITY_ACCOUNTING_YEAR
                or decision not in ("supported", "clarify", "blocked")
                or not isinstance(latest_manifest_version, str)
                or not latest_manifest_version
                or not isinstance(latest_manifest_sha256, str)
                or not re.fullmatch(r"[a-f0-9]{64}", latest_manifest_sha256)
                or not isinstance(reason_explanations, list)
                or not all(
                    isinstance(explanation, str) and explanation
                    for explanation in reason_explanations
                )
                or not isinstance(next_step_code, str)
                or not next_step_code
                or not isinstance(next_step, str)
                or not next_step
                or not isinstance(allowed, bool)
                or archive_available is not True
                or (decision == "supported" and not allowed)
                or (decision != "supported" and allowed)
            ):
                raise _company_access_unavailable()
            normalized_state = dict(row)
            if (
                latest_manifest_version != CURRENT_CAPABILITY_MANIFEST_VERSION
                or latest_manifest_sha256 != CURRENT_CAPABILITY_MANIFEST_SHA256
            ):
                normalized_state.update(
                    {
                        "current_eligibility_decision": "clarify",
                        "eligibility_reason_explanations": [
                            "Talli-grensen er oppdatert og må kontrolleres på nytt."
                        ],
                        "eligibility_next_step_code": "RECHECK_REQUIRED",
                        "eligibility_next_step": (
                            "Kontroller selskapsgrensen på nytt før betaling eller innsending. "
                            "Lese- og eksporttilgang er fortsatt åpen."
                        ),
                        "consequential_operations_allowed": False,
                    }
                )
            company_year_states[state_company_id] = normalized_state

        def context(company: Mapping[str, object]) -> CompanyContext:
            company_id_value = str(company["id"])
            company_year_state = company_year_states.get(company_id_value)
            return CompanyContext(
                id=company_id_value,
                org_number=str(company["org_number"]),
                name=str(company["name"]),
                entity_type=str(company["entity_type"]),
                address=str(company["address"]),
                postal_code=str(company["postal_code"]),
                city=str(company["city"]),
                status_text=str(company["status_text"]),
                source=str(company["source"]),
                created_by=str(company["created_by"]),
                identity_confirmed_at=(
                    str(company["identity_confirmed_at"])
                    if company.get("identity_confirmed_at") is not None
                    else None
                ),
                identity_locked_at=(
                    str(company["identity_locked_at"])
                    if company.get("identity_locked_at") is not None
                    else None
                ),
                created_at=str(company["created_at"]),
                role="owner",
                resource_scope="owner_sensitive",
                aal="aal2",
                current_agreement_accepted=company_id_value
                in current_agreement_company_ids,
                company_year_admission_id=(
                    UUID(str(company_year_state["company_year_admission_id"]))
                    if company_year_state is not None
                    else None
                ),
                admitted_accounting_year=(
                    int(str(company_year_state["admitted_accounting_year"]))
                    if company_year_state is not None
                    else None
                ),
                current_eligibility_decision=(
                    cast(
                        Literal["supported", "clarify", "blocked"],
                        company_year_state["current_eligibility_decision"],
                    )
                    if company_year_state is not None
                    else None
                ),
                eligibility_reason_explanations=(
                    cast(list[str], company_year_state["eligibility_reason_explanations"])
                    if company_year_state is not None
                    else []
                ),
                eligibility_next_step_code=(
                    str(company_year_state["eligibility_next_step_code"])
                    if company_year_state is not None
                    else None
                ),
                eligibility_next_step=(
                    str(company_year_state["eligibility_next_step"])
                    if company_year_state is not None
                    else None
                ),
                consequential_operations_allowed=(
                    bool(company_year_state["consequential_operations_allowed"])
                    if company_year_state is not None
                    else False
                ),
                archive_export_available=(company_year_state is not None),
            )

        contexts = [context(company) for company in permitted_companies]
        return CompanyContextResponse(selected_company=contexts[0], companies=contexts)

    async def company_record(
        self, access_token: str, *, company_id: str
    ) -> CompanyAccessRecordResponse:
        subject = await self._gateway.session_subject(access_token)
        memberships = await self._gateway.memberships(access_token, subject)
        membership = next(
            (
                row
                for row in memberships
                if str(row.get("company_id")) == company_id
                and row.get("accepted_at") is not None
                and row.get("role") in {"owner", "reviewer", "read_only"}
            ),
            None,
        )
        if membership is None:
            raise _company_access_not_found()
        companies = await self._gateway.companies(access_token, [company_id])
        company = next(
            (row for row in companies if str(row.get("id")) == company_id),
            None,
        )
        if company is None:
            raise _company_access_not_found()
        return CompanyAccessRecordResponse(
            company=_company_access_record(company, role=str(membership["role"]))
        )

    async def operator_context(self, access_token: str) -> OperatorContextResponse:
        subject = await self._gateway.session_subject(access_token)
        operator = await self._gateway.support_operator(access_token, subject)
        role = (
            str(operator.get("role"))
            if operator is not None
            and operator.get("active") is True
            and operator.get("role") in {"support", "admin"}
            else None
        )
        if role is None:
            raise CompanyAccessError(
                status=403,
                code="OPERATOR_ACCESS_REQUIRED",
                title="Operator access required",
                detail="An active support operator grant is required.",
            )
        return OperatorContextResponse(
            role=cast(Literal["support", "admin"], role), active=True
        )

    async def search_operator_companies(
        self, access_token: str, *, query: str
    ) -> OperatorCompanySearchResponse:
        normalized = query.strip()
        if len(normalized) < 2 or len(normalized) > 100:
            raise CompanyAccessError(
                status=422,
                code="REQUEST_VALIDATION_FAILED",
                title="Request validation failed",
                detail="The operator search must contain between two and one hundred characters.",
            )
        await self.operator_context(access_token)
        rows = await self._gateway.search_operator_companies(access_token, normalized)
        return OperatorCompanySearchResponse(
            companies=[_operator_company_record(row) for row in rows]
        )

    async def eligibility_precheck(
        self, command: EligibilityPrecheckRequest
    ) -> EligibilityDecisionResponse:
        if self._company_registry is None:
            raise _company_access_unavailable()
        raw_company = await self._company_registry.lookup_company(command.org_number)
        company = _registry_identity(raw_company, expected_org_number=command.org_number)
        public_blocks = _public_fact_block_reasons(
            company, accounting_year=command.accounting_year
        )
        if public_blocks:
            return _eligibility_decision_response(
                company=company,
                accounting_year=command.accounting_year,
                decision="blocked",
                provisional=True,
                question_definitions=[],
                answers={},
                reason_codes=public_blocks,
            )
        return _eligibility_decision_response(
            company=company,
            accounting_year=command.accounting_year,
            decision="clarify",
            provisional=True,
            question_definitions=_manifest_question_definitions(),
            answers={},
            reason_codes=[str(_manifest_mapping("outcomes")["precheckReasonCode"])],
        )

    async def eligibility_definitive(
        self, command: EligibilityDefinitiveRequest
    ) -> EligibilityDecisionResponse:
        _assert_current_capability_manifest(
            version=command.capability_manifest_version,
            sha256=command.capability_manifest_sha256,
        )
        return await self._definitive_eligibility(command)

    async def _definitive_eligibility(
        self, command: EligibilityDefinitiveRequest
    ) -> EligibilityDecisionResponse:
        if self._company_registry is None:
            raise _company_access_unavailable()
        raw_company = await self._company_registry.lookup_company(command.org_number)
        company = _registry_identity(raw_company, expected_org_number=command.org_number)
        return self._evaluate_definitive(company, command)

    def _evaluate_definitive(
        self,
        company: CompanyRegistryIdentity,
        command: EligibilityDefinitiveRequest,
    ) -> EligibilityDecisionResponse:
        public_facts = _eligibility_public_facts(company)
        current_public_facts_sha256 = _canonical_sha256(
            public_facts.model_dump(mode="json", by_alias=True)
        )
        if current_public_facts_sha256 != command.expected_public_facts_sha256:
            raise CompanyAccessError(
                status=409,
                code="ELIGIBILITY_FACTS_CHANGED",
                title="Company facts changed",
                detail="The public company facts changed. Start a new free company check.",
            )
        definitions = _manifest_question_definitions()
        expected_codes = {str(item["code"]) for item in definitions}
        if set(command.answers) != expected_codes:
            raise CompanyAccessError(
                status=422,
                code="ELIGIBILITY_ANSWERS_INVALID",
                title="Eligibility answers invalid",
                detail="Answer exactly the material questions returned by the free company check.",
            )
        public_blocks = _public_fact_block_reasons(
            company, accounting_year=command.accounting_year
        )
        blocked_reasons = list(public_blocks)
        blocked_definitions: list[Mapping[str, object]] = []
        unknown_definitions: list[Mapping[str, object]] = []
        for definition in definitions:
            code = str(definition["code"])
            answer = command.answers[code]
            if answer == "unknown":
                unknown_definitions.append(definition)
            elif answer != definition["supportedAnswer"]:
                blocked_reasons.append(str(definition["blockedReasonCode"]))
                blocked_definitions.append(definition)
        if blocked_reasons:
            return _eligibility_decision_response(
                company=company,
                accounting_year=command.accounting_year,
                decision="blocked",
                provisional=False,
                question_definitions=blocked_definitions,
                answers=command.answers,
                reason_codes=list(dict.fromkeys(blocked_reasons)),
            )
        if unknown_definitions:
            return _eligibility_decision_response(
                company=company,
                accounting_year=command.accounting_year,
                decision="clarify",
                provisional=False,
                question_definitions=unknown_definitions,
                answers=command.answers,
                reason_codes=[str(_manifest_mapping("outcomes")["clarifyReasonCode"])],
            )
        return _eligibility_decision_response(
            company=company,
            accounting_year=command.accounting_year,
            decision="supported",
            provisional=False,
            question_definitions=[],
            answers=command.answers,
            reason_codes=[],
        )

    async def admit_company_year(
        self,
        access_token: str,
        command: CompanyYearAdmissionRequest,
    ) -> CompanyYearAdmissionResponse:
        identity = await self._gateway.session_identity(access_token)
        actor, email = _verified_identity(identity)
        replay = await self._gateway.company_year_admission_replay(
            access_token, str(command.operation_id)
        )
        if replay is not None:
            replay_answers = replay.get("answers")
            if (
                replay.get("org_number") != command.org_number
                or replay.get("accounting_year") != command.accounting_year
                or replay.get("public_facts_sha256")
                != command.expected_public_facts_sha256
                or replay.get("capability_manifest_version")
                != command.capability_manifest_version
                or replay.get("capability_manifest_sha256")
                != command.capability_manifest_sha256
                or not isinstance(replay_answers, Mapping)
                or dict(replay_answers) != dict(command.answers)
                or replay.get("business_terms_version")
                != command.business_terms_version
                or replay.get("business_terms_sha256")
                != command.business_terms_sha256
                or replay.get("dpa_version") != command.dpa_version
                or replay.get("dpa_sha256") != command.dpa_sha256
                or replay.get("privacy_notice_version")
                != command.privacy_notice_version
                or replay.get("privacy_notice_sha256")
                != command.privacy_notice_sha256
            ):
                raise _company_access_conflict()
            return _company_year_admission_response(
                {
                    "company_id": replay.get("company_id"),
                    "company_year_admission_id": replay.get(
                        "company_year_admission_id"
                    ),
                    "accounting_year": replay.get("accounting_year"),
                    "reconstruct_from": replay.get("reconstruct_from"),
                    "capability_manifest_version": replay.get(
                        "capability_manifest_version"
                    ),
                    "capability_manifest_sha256": replay.get(
                        "capability_manifest_sha256"
                    ),
                    "current_agreement_accepted": True,
                    "replayed": True,
                }
            )
        _assert_current_capability_manifest(
            version=command.capability_manifest_version,
            sha256=command.capability_manifest_sha256,
        )
        _assert_current_privacy_notice(
            version=command.privacy_notice_version,
            sha256=command.privacy_notice_sha256,
        )
        definitive_command = EligibilityDefinitiveRequest(
            org_number=command.org_number,
            accounting_year=command.accounting_year,
            expected_public_facts_sha256=command.expected_public_facts_sha256,
            capability_manifest_version=command.capability_manifest_version,
            capability_manifest_sha256=command.capability_manifest_sha256,
            answers=command.answers,
        )
        if self._company_registry is None:
            raise _company_access_unavailable()
        raw_company = await self._company_registry.lookup_company(command.org_number)
        company = _registry_identity(raw_company, expected_org_number=command.org_number)
        eligibility = self._evaluate_definitive(company, definitive_command)
        if eligibility.decision != "supported" or eligibility.company_year_promise is None:
            raise CompanyAccessError(
                status=422,
                code="COMPANY_YEAR_NOT_ELIGIBLE",
                title="Company year not eligible",
                detail="The company year cannot be admitted. Follow the eligibility next step.",
            )
        answers_payload = dict(sorted(command.answers.items()))
        public_facts_payload = eligibility.public_facts.model_dump(mode="json", by_alias=True)
        promise_payload = eligibility.company_year_promise.model_dump(mode="json", by_alias=True)
        row = await self._gateway.admit_company_year(
            access_token,
            CompanyYearAdmissionGatewayCommand(
                operation_id=command.operation_id,
                verified_actor=UUID(actor),
                verified_email=email,
                company=company,
                accounting_year=command.accounting_year,
                reconstruct_from=eligibility.company_year_promise.reconstruction_required_from,
                public_facts_json=json.dumps(
                    public_facts_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                public_facts_sha256=eligibility.public_facts_sha256,
                answers_json=json.dumps(
                    answers_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                answers_sha256=cast(str, eligibility.answers_sha256),
                capability_manifest_json=json.dumps(
                    CAPABILITY_MANIFEST,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                company_year_promise_json=json.dumps(
                    promise_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                company_year_promise_sha256=_canonical_sha256(promise_payload),
            ),
        )
        return _company_year_admission_response(row)

    async def recheck_company_year_eligibility(
        self,
        access_token: str,
        company_year_admission_id: UUID,
        command: CompanyYearEligibilityRecheckRequest,
    ) -> CompanyYearEligibilityStateResponse:
        raw_context = await self._gateway.company_year_admission_context(
            access_token, str(company_year_admission_id), str(command.operation_id)
        )
        if raw_context is None:
            raise _company_access_not_found()
        try:
            context_admission_id = UUID(str(raw_context["company_year_admission_id"]))
            company_id = UUID(str(raw_context["company_id"]))
            accounting_year = int(str(raw_context["accounting_year"]))
            org_number = str(raw_context["org_number"])
            accepted_manifest_version = str(
                raw_context["accepted_capability_manifest_version"]
            )
            accepted_manifest_sha256 = str(
                raw_context["accepted_capability_manifest_sha256"]
            )
            previous_assessment_id = UUID(str(raw_context["latest_assessment_id"]))
            latest_answers = raw_context["latest_answers"]
            accepted_promise = CompanyYearPromise.model_validate(
                raw_context["accepted_company_year_promise"]
            )
        except (KeyError, TypeError, ValueError):
            raise _company_access_unavailable() from None
        if not isinstance(latest_answers, Mapping):
            raise _company_access_unavailable()
        if command.trigger == "material_answer_changed" and command.answers is None:
            raise CompanyAccessError(
                status=422,
                code="ELIGIBILITY_ANSWERS_INVALID",
                title="Eligibility answers invalid",
                detail="Updated material answers are required for this recheck.",
            )
        effective_answers = (
            dict(command.answers) if command.answers is not None else dict(latest_answers)
        )
        if (
            context_admission_id != company_year_admission_id
            or accounting_year != CURRENT_CAPABILITY_ACCOUNTING_YEAR
            or not re.fullmatch(r"[0-9]{9}", org_number)
            or not re.fullmatch(r"[a-f0-9]{64}", accepted_manifest_sha256)
            or accepted_promise.accounting_year != accounting_year
        ):
            raise _company_access_unavailable()
        if raw_context.get("replay_assessment_id") is not None:
            try:
                replay_assessment_id = UUID(str(raw_context["replay_assessment_id"]))
                replay_trigger = str(raw_context["replay_trigger"])
                replay_decision = str(raw_context["replay_decision"])
                replay_manifest_version = str(
                    raw_context["replay_capability_manifest_version"]
                )
                replay_manifest_sha256 = str(
                    raw_context["replay_capability_manifest_sha256"]
                )
                replay_answers = raw_context["replay_answers"]
                replay_reason_codes = raw_context["replay_reason_codes"]
                replay_reason_explanations = raw_context[
                    "replay_reason_explanations"
                ]
                replay_next_step_code = raw_context["replay_next_step_code"]
                replay_next_step = raw_context["replay_next_step"]
                replay_allowed = raw_context[
                    "replay_consequential_operations_allowed"
                ]
                replay_archive_available = raw_context[
                    "replay_archive_export_available"
                ]
            except (KeyError, TypeError, ValueError):
                raise _company_access_unavailable() from None
            if (
                replay_trigger != command.trigger
                or not isinstance(replay_answers, Mapping)
                or (
                    command.answers is not None
                    and dict(replay_answers) != dict(command.answers)
                )
            ):
                raise _company_access_conflict()
            if (
                replay_decision not in ("supported", "clarify", "blocked")
                or not replay_manifest_version
                or not re.fullmatch(r"[a-f0-9]{64}", replay_manifest_sha256)
                or not isinstance(replay_reason_codes, list)
                or not all(isinstance(code, str) for code in replay_reason_codes)
                or not isinstance(replay_reason_explanations, list)
                or not all(
                    isinstance(explanation, str) and explanation
                    for explanation in replay_reason_explanations
                )
                or not isinstance(replay_next_step_code, str)
                or not replay_next_step_code
                or not isinstance(replay_next_step, str)
                or not replay_next_step
                or not isinstance(replay_allowed, bool)
                or replay_archive_available is not True
                or (replay_decision == "supported" and not replay_allowed)
                or (replay_decision != "supported" and replay_allowed)
            ):
                raise _company_access_unavailable()
            return CompanyYearEligibilityStateResponse(
                company_year_eligibility_assessment_id=replay_assessment_id,
                company_year_admission_id=company_year_admission_id,
                company_id=company_id,
                accounting_year=accounting_year,
                trigger=cast(EligibilityRecheckTrigger, replay_trigger),
                decision=cast(EligibilityDecision, replay_decision),
                accepted_capability_manifest_version=accepted_manifest_version,
                accepted_capability_manifest_sha256=accepted_manifest_sha256,
                current_capability_manifest_version=replay_manifest_version,
                current_capability_manifest_sha256=replay_manifest_sha256,
                accepted_company_year_promise=accepted_promise,
                reason_codes=cast(list[str], replay_reason_codes),
                reason_explanations=cast(
                    list[str], replay_reason_explanations
                ),
                next_step_code=replay_next_step_code,
                next_step=replay_next_step,
                consequential_operations_allowed=replay_allowed,
                archive_export_available=True,
                replayed=True,
            )
        if self._company_registry is None:
            raise _company_access_unavailable()
        raw_company = await self._company_registry.lookup_company(org_number)
        company = _registry_identity(raw_company, expected_org_number=org_number)
        public_facts = _eligibility_public_facts(company)
        public_facts_payload = public_facts.model_dump(mode="json", by_alias=True)
        definitive_command = EligibilityDefinitiveRequest(
            org_number=org_number,
            accounting_year=accounting_year,
            expected_public_facts_sha256=_canonical_sha256(public_facts_payload),
            capability_manifest_version=CURRENT_CAPABILITY_MANIFEST_VERSION,
            capability_manifest_sha256=CURRENT_CAPABILITY_MANIFEST_SHA256,
            answers=cast(dict[str, EligibilityAnswer], effective_answers),
        )
        eligibility = self._evaluate_definitive(company, definitive_command)
        outcomes = _manifest_mapping("outcomes")
        if eligibility.decision == "supported":
            next_step_code = str(outcomes["recheckSupportedNextStepCode"])
            next_step = str(outcomes["recheckSupportedNextStep"])
            consequential_operations_allowed = True
        elif eligibility.decision == "clarify":
            next_step_code = str(outcomes["recheckClarifyNextStepCode"])
            next_step = str(outcomes["recheckClarifyNextStep"])
            consequential_operations_allowed = False
        else:
            next_step_code = str(outcomes["recheckBlockedNextStepCode"])
            next_step = str(outcomes["recheckBlockedNextStep"])
            consequential_operations_allowed = False
        identity = await self._gateway.session_identity(access_token)
        actor, _email = _verified_identity(identity)
        answers_payload = dict(sorted(effective_answers.items()))
        row = await self._gateway.record_company_year_eligibility_recheck(
            access_token,
            CompanyYearEligibilityRecheckGatewayCommand(
                operation_id=command.operation_id,
                verified_actor=UUID(actor),
                company_year_admission_id=company_year_admission_id,
                company_id=company_id,
                accounting_year=accounting_year,
                previous_assessment_id=previous_assessment_id,
                trigger=command.trigger,
                decision=eligibility.decision,
                capability_manifest_json=json.dumps(
                    CAPABILITY_MANIFEST,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                public_facts_json=json.dumps(
                    public_facts_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                public_facts_sha256=eligibility.public_facts_sha256,
                answers_json=json.dumps(
                    answers_payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                answers_sha256=cast(str, eligibility.answers_sha256),
                reason_codes=tuple(eligibility.reason_codes),
                reason_explanations=tuple(eligibility.reason_explanations),
                next_step_code=next_step_code,
                next_step=next_step,
                consequential_operations_allowed=consequential_operations_allowed,
            ),
        )
        try:
            assessment_id = UUID(str(row["company_year_eligibility_assessment_id"]))
        except (KeyError, ValueError):
            raise _company_access_unavailable() from None
        if not isinstance(row.get("replayed"), bool):
            raise _company_access_unavailable()
        return CompanyYearEligibilityStateResponse(
            company_year_eligibility_assessment_id=assessment_id,
            company_year_admission_id=company_year_admission_id,
            company_id=company_id,
            accounting_year=accounting_year,
            trigger=command.trigger,
            decision=eligibility.decision,
            accepted_capability_manifest_version=accepted_manifest_version,
            accepted_capability_manifest_sha256=accepted_manifest_sha256,
            current_capability_manifest_version=CURRENT_CAPABILITY_MANIFEST_VERSION,
            current_capability_manifest_sha256=CURRENT_CAPABILITY_MANIFEST_SHA256,
            accepted_company_year_promise=accepted_promise,
            reason_codes=eligibility.reason_codes,
            reason_explanations=eligibility.reason_explanations,
            next_step_code=next_step_code,
            next_step=next_step,
            consequential_operations_allowed=consequential_operations_allowed,
            archive_export_available=True,
            replayed=bool(row["replayed"]),
        )

    async def onboard_company(
        self,
        access_token: str,
        command: CompanyOnboardingRequest,
    ) -> CompanyOnboardingResponse:
        del access_token, command
        raise CompanyAccessError(
            status=409,
            code="DEFINITIVE_ELIGIBILITY_REQUIRED",
            title="Definitive eligibility required",
            detail="Complete the free eligibility interview before admitting a company year.",
        )

    async def reaccept_agreement(
        self,
        access_token: str,
        command: CompanyAgreementAcceptanceRequest,
    ) -> CompanyAgreementAcceptanceResponse:
        identity = await self._gateway.session_identity(access_token)
        actor, email = _verified_identity(identity)
        company_id = str(command.company_id)
        memberships = await self._gateway.memberships(access_token, actor)
        if not any(
            str(row.get("company_id")) == company_id
            and row.get("role") == "owner"
            and row.get("accepted_at") is not None
            for row in memberships
        ):
            raise _company_access_not_found()
        operation_id = uuid5(
            NAMESPACE_URL,
            (
                f"talli:company-access:reaccept:{actor}:{company_id}:"
                f"{CURRENT_BUSINESS_TERMS_SHA256}:{CURRENT_DPA_SHA256}"
            ),
        )
        row = await self._gateway.reaccept_agreement(
            access_token,
            CompanyAgreementAcceptanceGatewayCommand(
                operation_id=operation_id,
                company_id=command.company_id,
                verified_actor=UUID(actor),
                verified_email=email,
            ),
        )
        response = _company_agreement_response(row)
        return CompanyAgreementAcceptanceResponse(**response.model_dump())

    async def list_invitations(
        self, access_token: str, *, company_id: str
    ) -> CompanyInvitationListResponse:
        await self._authorize_owner(access_token, company_id)
        invitations = await self._gateway.invitations(access_token, company_id)
        return CompanyInvitationListResponse(
            invitations=[self._invitation(item) for item in invitations]
        )

    async def invite(
        self,
        access_token: str,
        command: CreateCompanyInvitationRequest,
    ) -> CompanyInvitationResponse:
        company_id = str(command.company_id)
        await self._authorize_owner(access_token, company_id)
        await self._company(access_token, company_id)
        normalized_email = _normalize_email(command.invited_email)
        acceptance_token = secrets.token_urlsafe(32)
        row = await self._gateway.create_invitation(
            access_token,
            CreateInvitationGatewayCommand(
                operation_id=str(command.operation_id),
                company_id=company_id,
                invited_email=normalized_email,
                role=command.role,
                token_hash=_token_hash(acceptance_token),
                acceptance_token=acceptance_token,
            ),
        )
        delivery_token = str(row.get("delivery_token", ""))
        delivery_company_name = str(row.get("delivery_company_name", ""))
        if not delivery_token or not delivery_company_name:
            raise _company_access_unavailable()
        delivery_subject = f"Invitasjon til Talli: {delivery_company_name}"
        delivery_body = _invitation_body(
            company_name=delivery_company_name,
            role=str(row.get("role", "")),
            acceptance_token=delivery_token,
        )
        return CompanyInvitationResponse(
            invitation=self._invitation(row),
            delivery_token=delivery_token,
            delivery_subject=delivery_subject,
            delivery_body=delivery_body,
        )

    async def pending_invitation_side_effects(
        self, access_token: str
    ) -> InvitationSideEffectContinuationList:
        rows = await self._gateway.pending_invitation_side_effects(access_token)
        continuations: list[InvitationSideEffectContinuation] = []
        for row in rows:
            result = row.get("result")
            command_name = row.get("command_name")
            if not isinstance(result, Mapping) or command_name not in {
                "create_invitation", "accept_invitation", "revoke_invitation", "resend_invitation"
            }:
                raise _company_access_unavailable()
            invitation = None
            membership = None
            if command_name == "accept_invitation":
                membership = self._membership(result)
            else:
                invitation = self._invitation(result)
            delivery_token = (
                str(row["delivery_token"])
                if row.get("delivery_token") is not None else None
            )
            delivery_company_name = str(result.get("delivery_company_name", ""))
            has_delivery = bool(delivery_token and delivery_company_name and invitation)
            continuations.append(InvitationSideEffectContinuation(
                operation_id=str(row.get("operation_id", "")),
                command_name=command_name,
                company_id=str(row.get("company_id", "")),
                invitation=invitation,
                membership=membership,
                delivery_token=delivery_token if has_delivery else None,
                delivery_subject=(
                    f"Invitasjon til Talli: {delivery_company_name}" if has_delivery else None
                ),
                delivery_body=(
                    _invitation_body(
                        company_name=delivery_company_name,
                        role=str(result.get("role", "")),
                        acceptance_token=delivery_token or "",
                    ) if has_delivery else None
                ),
            ))
        return InvitationSideEffectContinuationList(continuations=continuations)

    async def complete_invitation_side_effect(
        self, access_token: str, operation_id: UUID
    ) -> InvitationSideEffectCompletion:
        completed = await self._gateway.complete_invitation_side_effect(
            access_token, str(operation_id)
        )
        if not completed:
            raise _company_access_unavailable()
        return InvitationSideEffectCompletion(
            operation_id=str(operation_id), completed=True
        )

    async def lookup_invitation(
        self, access_token: str, *, token: str
    ) -> InvitationLookup:
        identity = await self._gateway.session_identity(access_token)
        email = _identity_email(identity)
        row = await self._gateway.lookup_invitation(
            access_token,
            InvitationIdentityGatewayCommand(
                token_hash=_required_token_hash(token),
                verified_subject=str(identity["id"]),
                verified_email=email,
            ),
        )
        if row is None or _normalize_email(str(row.get("invited_email", ""))) != email:
            raise _invitation_not_found()
        if row.get("status") != "pending" or _is_expired(str(row.get("expires_at", ""))):
            raise _invitation_not_found()
        return InvitationLookup(
            company_name=str(row["company_name"]),
            role=cast(InvitationRole, row["role"]),
            expires_at=str(row["expires_at"]),
        )

    async def accept_invitation(
        self, access_token: str, command: AcceptCompanyInvitationRequest
    ) -> CompanyMembershipResponse:
        identity = await self._gateway.session_identity(access_token)
        email = _identity_email(identity)
        row = await self._gateway.accept_invitation(
            access_token,
            AcceptInvitationGatewayCommand(
                operation_id=str(command.operation_id),
                token_hash=_required_token_hash(command.token),
                verified_subject=str(identity["id"]),
                verified_email=email,
            ),
        )
        if row is None:
            raise _invitation_not_found()
        return CompanyMembershipResponse(membership=self._membership(row))

    async def revoke_invitation(
        self, access_token: str, invitation_id: UUID, command: CompanyInvitationCommandRequest
    ) -> CompanyInvitationResponse:
        company_id = str(command.company_id)
        await self._authorize_owner(access_token, company_id)
        row = await self._gateway.revoke_invitation(
            access_token,
            InvitationMutationGatewayCommand(
                operation_id=str(command.operation_id),
                company_id=company_id,
                invitation_id=str(invitation_id),
                expected_updated_at=command.expected_updated_at.isoformat(),
            ),
        )
        if row is None:
            raise _company_access_not_found()
        return CompanyInvitationResponse(
            invitation=self._invitation(row),
            delivery_token=None,
            delivery_subject=None,
            delivery_body=None,
        )

    async def resend_invitation(
        self, access_token: str, invitation_id: UUID, command: CompanyInvitationCommandRequest
    ) -> CompanyInvitationResponse:
        company_id = str(command.company_id)
        await self._authorize_owner(access_token, company_id)
        await self._company(access_token, company_id)
        existing_invitations = await self._gateway.invitations(access_token, company_id)
        existing = next(
            (item for item in existing_invitations if str(item.get("id")) == str(invitation_id)),
            None,
        )
        if existing is None:
            raise _company_access_not_found()
        acceptance_token = secrets.token_urlsafe(32)
        row = await self._gateway.resend_invitation(
            access_token,
            ResendInvitationGatewayCommand(
                operation_id=str(command.operation_id),
                company_id=company_id,
                invitation_id=str(invitation_id),
                expected_updated_at=command.expected_updated_at.isoformat(),
                token_hash=_token_hash(acceptance_token),
                acceptance_token=acceptance_token,
            ),
        )
        if row is None:
            raise _company_access_not_found()
        delivery_token = str(row.get("delivery_token", ""))
        delivery_company_name = str(row.get("delivery_company_name", ""))
        if not delivery_token or not delivery_company_name:
            raise _company_access_unavailable()
        delivery_subject = f"Invitasjon til Talli: {delivery_company_name}"
        delivery_body = _invitation_body(
            company_name=delivery_company_name,
            role=str(row.get("role", "")),
            acceptance_token=delivery_token,
        )
        return CompanyInvitationResponse(
            invitation=self._invitation(row),
            delivery_token=delivery_token,
            delivery_subject=delivery_subject,
            delivery_body=delivery_body,
        )

    async def list_memberships(
        self, access_token: str, *, company_id: str
    ) -> CompanyMembershipListResponse:
        await self._authorize_owner(access_token, company_id)
        rows = await self._gateway.company_memberships(access_token, company_id)
        return CompanyMembershipListResponse(
            memberships=[self._membership(row) for row in rows if row.get("role") != "owner"]
        )

    async def administer_membership(
        self,
        access_token: str,
        user_id: UUID,
        command: AdministerCompanyMembershipRequest,
    ) -> CompanyMembershipResponse:
        if command.role is None and command.state is None:
            raise CompanyAccessError(
                status=422,
                code="REQUEST_VALIDATION_FAILED",
                title="Request validation failed",
                detail="A membership role or state change is required.",
            )
        company_id = str(command.company_id)
        target_user_id = str(user_id)
        identity = await self._authorize_owner(access_token, company_id)
        if target_user_id == identity["id"]:
            raise _company_access_not_found()
        row = await self._gateway.administer_membership(
            access_token,
            AdministerMembershipGatewayCommand(
                operation_id=str(command.operation_id),
                company_id=company_id,
                user_id=target_user_id,
                expected_role=command.expected_role,
                role=command.role,
                state=command.state,
            ),
        )
        if row is None or row.get("role") == "owner":
            raise _company_access_not_found()
        return CompanyMembershipResponse(membership=self._membership(row))

    async def list_cancellations(
        self, access_token: str, *, company_id: str
    ) -> CompanyCancellationListResponse:
        await self._gateway.session_subject(access_token)
        rows = await self._gateway.cancellations(access_token, company_id)
        return CompanyCancellationListResponse(
            cancellations=[self._cancellation(row) for row in rows]
        )

    async def request_cancellation(
        self,
        access_token: str,
        command: RequestCompanyCancellationRequest,
    ) -> CompanyCancellationResponse:
        company_id = str(command.company_id)
        await self._authorize_lifecycle_owner(access_token, company_id)
        await self._company(access_token, company_id)
        row = await self._gateway.request_cancellation(
            access_token,
            RequestCompanyCancellationGatewayCommand(
                operation_id=str(command.operation_id),
                company_id=company_id,
                income_year=command.income_year,
                reason=command.reason,
            ),
        )
        if row is None:
            raise _company_access_not_found()
        return CompanyCancellationResponse(cancellation=self._cancellation(row))

    async def review_deletion(
        self,
        access_token: str,
        cancellation_id: UUID,
        command: ReviewCompanyDeletionRequest,
    ) -> CompanyDeletionReviewResponse:
        await self._gateway.session_subject(access_token)
        _require_fresh_mfa(access_token)
        row = await self._gateway.review_deletion(
            access_token,
            ReviewCompanyDeletionGatewayCommand(
                operation_id=str(command.operation_id),
                cancellation_id=str(cancellation_id),
                company_id=str(command.company_id),
                expected_updated_at=command.expected_updated_at.isoformat(),
                decision=command.decision,
                evidence_reference=command.evidence_reference,
            ),
        )
        if row is None or not isinstance(row.get("review"), Mapping):
            raise _company_access_not_found()
        return CompanyDeletionReviewResponse(
            cancellation=self._cancellation(row),
            review=CompanyDeletionReview.model_validate(row["review"]),
        )

    async def resume_cancellation(
        self,
        access_token: str,
        cancellation_id: UUID,
        command: ResumeCompanyCancellationRequest,
    ) -> CompanyCancellationResponse:
        company_id = str(command.company_id)
        await self._authorize_lifecycle_owner(access_token, company_id)
        row = await self._gateway.resume_cancellation(
            access_token,
            ResumeCompanyCancellationGatewayCommand(
                operation_id=str(command.operation_id),
                cancellation_id=str(cancellation_id),
                company_id=company_id,
                income_year=command.income_year,
                expected_updated_at=command.expected_updated_at.isoformat(),
            ),
        )
        if row is None:
            raise _company_access_not_found()
        return CompanyCancellationResponse(cancellation=self._cancellation(row))

    async def finalize_deletion(
        self,
        access_token: str,
        cancellation_id: UUID,
        command: FinalizeCompanyDeletionRequest,
    ) -> CompanyCancellationResponse:
        company_id = str(command.company_id)
        await self._authorize_lifecycle_owner(access_token, company_id)
        row = await self._gateway.finalize_deletion(
            access_token,
            FinalizeCompanyDeletionGatewayCommand(
                operation_id=str(command.operation_id),
                cancellation_id=str(cancellation_id),
                company_id=company_id,
                expected_updated_at=command.expected_updated_at.isoformat(),
            ),
        )
        if row is None:
            raise _company_access_not_found()
        return CompanyCancellationResponse(cancellation=self._cancellation(row))

    async def _authorize_lifecycle_owner(
        self, access_token: str, company_id: str
    ) -> Mapping[str, object]:
        identity = await self._authorize_owner(access_token, company_id)
        _require_fresh_mfa(access_token)
        return identity

    async def _authorize_owner(
        self, access_token: str, company_id: str
    ) -> Mapping[str, object]:
        identity = await self._gateway.session_identity(access_token)
        if _token_aal(access_token) != "aal2":
            raise CompanyAccessError(
                status=403,
                code="AAL2_REQUIRED",
                title="Additional verification required",
                detail="Additional verification is required for membership administration.",
            )
        memberships = await self._gateway.memberships(access_token, str(identity["id"]))
        if not any(
            str(row.get("company_id")) == company_id
            and row.get("role") == "owner"
            and row.get("accepted_at") is not None
            for row in memberships
        ):
            raise _company_access_not_found()
        return identity

    async def _company(
        self, access_token: str, company_id: str
    ) -> Mapping[str, object]:
        companies = await self._gateway.companies(access_token, [company_id])
        if not companies or str(companies[0].get("id")) != company_id:
            raise _company_access_not_found()
        return companies[0]

    @staticmethod
    def _invitation(row: Mapping[str, object]) -> CompanyInvitation:
        return CompanyInvitation.model_validate(row)

    @staticmethod
    def _membership(row: Mapping[str, object]) -> CompanyMembership:
        return CompanyMembership.model_validate(row)

    @staticmethod
    def _cancellation(row: Mapping[str, object]) -> CompanyCancellation:
        return CompanyCancellation.model_validate(
            {key: value for key, value in row.items() if key != "review"}
        )


def _is_current_agreement(row: Mapping[str, object]) -> bool:
    return (
        row.get("business_terms_version") == CURRENT_BUSINESS_TERMS_VERSION
        and str(row.get("business_terms_effective_date"))
        == CURRENT_BUSINESS_TERMS_EFFECTIVE_DATE
        and row.get("business_terms_path") == CURRENT_BUSINESS_TERMS_PATH
        and row.get("business_terms_sha256") == CURRENT_BUSINESS_TERMS_SHA256
        and row.get("dpa_version") == CURRENT_DPA_VERSION
        and str(row.get("dpa_effective_date")) == CURRENT_DPA_EFFECTIVE_DATE
        and row.get("dpa_path") == CURRENT_DPA_PATH
        and row.get("dpa_sha256") == CURRENT_DPA_SHA256
        and row.get("authority_statement_version") == CURRENT_AUTHORITY_STATEMENT_VERSION
        and row.get("acceptance_method") == CURRENT_ACCEPTANCE_METHOD
    )


def _verified_identity(identity: Mapping[str, object]) -> tuple[str, str]:
    subject = identity.get("id")
    if not isinstance(subject, str):
        raise _authentication_required()
    try:
        UUID(subject)
    except ValueError:
        raise _authentication_required() from None
    return subject, _identity_email(identity)


def _company_agreement_response(row: Mapping[str, object]) -> CompanyOnboardingResponse:
    try:
        company_id = UUID(str(row["company_id"]))
    except (KeyError, ValueError):
        raise _company_access_unavailable() from None
    if row.get("current_agreement_accepted") is not True or not isinstance(
        row.get("replayed"), bool
    ):
        raise _company_access_unavailable()
    return CompanyOnboardingResponse(
        company_id=company_id,
        current_agreement_accepted=True,
        replayed=bool(row["replayed"]),
    )


def _company_year_admission_response(
    row: Mapping[str, object],
) -> CompanyYearAdmissionResponse:
    required = (
        "company_id",
        "company_year_admission_id",
        "accounting_year",
        "reconstruct_from",
        "capability_manifest_version",
        "capability_manifest_sha256",
        "current_agreement_accepted",
        "replayed",
    )
    if any(key not in row for key in required) or row.get("current_agreement_accepted") is not True:
        raise _company_access_unavailable()
    try:
        return CompanyYearAdmissionResponse.model_validate(row)
    except ValueError:
        raise _company_access_unavailable() from None


def _company_record_values(row: Mapping[str, object]) -> dict[str, object]:
    required = (
        "id",
        "org_number",
        "name",
        "entity_type",
        "address",
        "postal_code",
        "city",
        "status_text",
        "source",
        "created_by",
        "created_at",
    )
    if any(not isinstance(row.get(key), str) for key in required):
        raise _company_access_unavailable()
    return {
        key: row.get(key)
        for key in (
            *required,
            "identity_confirmed_at",
            "identity_locked_at",
        )
    }


def _company_access_record(
    row: Mapping[str, object], *, role: str
) -> CompanyAccessRecord:
    if role not in {"owner", "reviewer", "read_only"}:
        raise _company_access_unavailable()
    return CompanyAccessRecord.model_validate(
        {**_company_record_values(row), "role": cast(CompanyAccessRole, role)}
    )


def _operator_company_record(row: Mapping[str, object]) -> OperatorCompanyRecord:
    return OperatorCompanyRecord.model_validate(_company_record_values(row))


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise CompanyAccessError(
            status=422,
            code="REQUEST_VALIDATION_FAILED",
            title="Request validation failed",
            detail="The invitation email is invalid.",
        )
    return normalized


def _identity_email(identity: Mapping[str, object]) -> str:
    if not isinstance(identity.get("id"), str) or not isinstance(identity.get("email"), str):
        raise CompanyAccessError(
            status=401,
            code="AUTHENTICATION_REQUIRED",
            title="Authentication required",
            detail="A verified session email is required.",
        )
    return _normalize_email(str(identity["email"]))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _required_token_hash(token: str) -> str:
    if not token or len(token) > 512:
        raise _invitation_not_found()
    return _token_hash(token)


def _is_expired(value: str) -> bool:
    try:
        expires_at = datetime.fromisoformat(value)
    except ValueError:
        return True
    return expires_at <= datetime.now(UTC)


def _require_fresh_mfa(access_token: str) -> None:
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        entries = claims.get("amr")
        timestamps: list[float] = [
            float(item["timestamp"])
            for item in entries
            if isinstance(item, Mapping)
            and item.get("method") in {"totp", "mfa/totp", "mfa/phone", "mfa/webauthn"}
            and isinstance(item.get("timestamp"), (int, float))
        ] if isinstance(entries, list) else []
        newest = max(timestamps) if timestamps else None
        age = datetime.now(UTC).timestamp() - newest if newest is not None else None
    except (IndexError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        age = None
    if _token_aal(access_token) != "aal2" or age is None or age < 0 or age > 15 * 60:
        raise CompanyAccessError(
            status=403,
            code="FRESH_MFA_REQUIRED",
            title="Fresh verification required",
            detail="Fresh multi-factor verification is required for this lifecycle transition.",
        )


def _invitation_body(
    *, company_name: str, role: InvitationRole | str, acceptance_token: str
) -> str:
    role_label = "reviewer" if role == "reviewer" else "read-only"
    return (
        f"Du er invitert som {role_label} i Talli for {company_name}. "
        f"Godta invitasjonen: /invite/accept?token={acceptance_token}"
    )


def _company_access_not_found() -> CompanyAccessError:
    return CompanyAccessError(
        status=404,
        code="COMPANY_ACCESS_NOT_FOUND",
        title="Company access not found",
        detail="The requested company access resource was not found.",
    )


def _company_access_conflict() -> CompanyAccessError:
    return CompanyAccessError(
        status=409,
        code="COMPANY_ACCESS_CONFLICT",
        title="Company access conflict",
        detail="The operation identifier was already used for different company access evidence.",
    )


def _company_access_unavailable() -> CompanyAccessError:
    return CompanyAccessError(
        status=503,
        code="COMPANY_ACCESS_UNAVAILABLE",
        title="Company access unavailable",
        detail="Company access is temporarily unavailable.",
    )


def _company_registry_unavailable() -> CompanyAccessError:
    return CompanyAccessError(
        status=503,
        code="COMPANY_REGISTRY_UNAVAILABLE",
        title="Company registry unavailable",
        detail="The public company registry is temporarily unavailable.",
    )


def _authentication_required() -> CompanyAccessError:
    return CompanyAccessError(
        status=401,
        code="AUTHENTICATION_REQUIRED",
        title="Authentication required",
        detail="A valid session is required.",
    )


def _invitation_not_found() -> CompanyAccessError:
    return CompanyAccessError(
        status=404,
        code="INVITATION_NOT_FOUND",
        title="Invitation not found",
        detail="The requested invitation was not found or is no longer available.",
    )


__all__ = [
    "AcceptCompanyInvitationRequest",
    "AdministerCompanyMembershipRequest",
    "CompanyAccessError",
    "CompanyAccessGateway",
    "CompanyAccessRecord",
    "CompanyAccessRecordResponse",
    "CompanyAccessService",
    "CompanyAgreementAcceptanceGatewayCommand",
    "CompanyAgreementAcceptanceRequest",
    "CompanyAgreementAcceptanceResponse",
    "CompanyCancellation",
    "CompanyCancellationEvidence",
    "CompanyCancellationListResponse",
    "CompanyCancellationResponse",
    "CompanyContext",
    "CompanyContextResponse",
    "CompanyYearAdmissionGatewayCommand",
    "CompanyYearAdmissionRequest",
    "CompanyYearAdmissionResponse",
    "CompanyYearEligibilityRecheckGatewayCommand",
    "CompanyYearEligibilityRecheckRequest",
    "CompanyYearEligibilityStateResponse",
    "CompanyYearPromise",
    "CompanyDeletionReview",
    "CompanyDeletionReviewResponse",
    "CompanyInvitation",
    "CompanyInvitationCommandRequest",
    "CompanyInvitationListResponse",
    "CompanyInvitationResponse",
    "CompanyMembership",
    "CompanyMembershipListResponse",
    "CompanyMembershipResponse",
    "CompanyOnboardingRequest",
    "CompanyOnboardingResponse",
    "CompanyRegistryGateway",
    "CompanyRegistryIdentity",
    "CreateCompanyInvitationRequest",
    "EligibilityAnswer",
    "EligibilityDecisionResponse",
    "EligibilityDecision",
    "EligibilityDefinitiveRequest",
    "EligibilityPrecheckRequest",
    "EligibilityPublicFacts",
    "EligibilityQuestion",
    "EligibilityRecheckTrigger",
    "FinalizeCompanyDeletionGatewayCommand",
    "FinalizeCompanyDeletionRequest",
    "InvitationLookup",
    "InvitationRole",
    "InvitationSideEffectCompletion",
    "InvitationSideEffectContinuation",
    "InvitationSideEffectContinuationList",
    "InvitationTokenRequest",
    "MembershipState",
    "OperatorCompanyRecord",
    "OperatorCompanySearchResponse",
    "OperatorContextResponse",
    "RequestCompanyCancellationGatewayCommand",
    "RequestCompanyCancellationRequest",
    "ResumeCompanyCancellationGatewayCommand",
    "ResumeCompanyCancellationRequest",
    "ReviewCompanyDeletionGatewayCommand",
    "ReviewCompanyDeletionRequest",
    "company_access_adapter",
    "company_registry_adapter",
]
