"""The only supported Python import path for the company-access capability."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Annotated, Callable, Literal, Protocol, TypeVar
from uuid import UUID

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


class CompanyContextResponse(CompanyAccessModel):
    selected_company: CompanyContext
    companies: list[CompanyContext]


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


Adapter = TypeVar("Adapter", bound=type)


def company_access_adapter(port: type[CompanyAccessGateway]) -> Callable[[Adapter], Adapter]:
    """Register a source-level outbound adapter binding for architecture verification."""

    def register(adapter: Adapter) -> Adapter:
        setattr(adapter, "__talli_port__", port)
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


class CompanyAccessService:
    def __init__(self, gateway: CompanyAccessGateway) -> None:
        self._gateway = gateway

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
        if aal != "aal2":
            raise CompanyAccessError(
                status=403,
                code="AAL2_REQUIRED",
                title="Additional verification required",
                detail="Additional verification is required for this company context.",
            )
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
        allowed_ids = [company_id] if company_id else list(roles)
        companies = await self._gateway.companies(access_token, allowed_ids)
        permitted_companies = [
            company
            for company in companies
            if isinstance(company.get("id"), str)
            and company["id"] in roles
        ]
        if not permitted_companies:
            raise CompanyAccessError(
                status=404,
                code="COMPANY_CONTEXT_NOT_FOUND",
                title="Company context not found",
                detail="The requested company context was not found.",
            )

        def context(company: Mapping[str, object]) -> CompanyContext:
            return CompanyContext(
                id=str(company["id"]),
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
            )

        contexts = [context(company) for company in permitted_companies]
        return CompanyContextResponse(selected_company=contexts[0], companies=contexts)

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
            role=str(row["role"]),
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
            review=CompanyDeletionReview(**row["review"]),
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
            row.get("company_id") == company_id
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
        if not companies or companies[0].get("id") != company_id:
            raise _company_access_not_found()
        return companies[0]

    @staticmethod
    def _invitation(row: Mapping[str, object]) -> CompanyInvitation:
        return CompanyInvitation(**row)

    @staticmethod
    def _membership(row: Mapping[str, object]) -> CompanyMembership:
        return CompanyMembership(**row)

    @staticmethod
    def _cancellation(row: Mapping[str, object]) -> CompanyCancellation:
        return CompanyCancellation(**{key: value for key, value in row.items() if key != "review"})


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
        expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    return expires_at <= datetime.now(timezone.utc)


def _require_fresh_mfa(access_token: str) -> None:
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        entries = claims.get("amr")
        timestamps = [
            item.get("timestamp")
            for item in entries
            if isinstance(item, Mapping)
            and item.get("method") in {"totp", "mfa/totp", "mfa/phone", "mfa/webauthn"}
            and isinstance(item.get("timestamp"), (int, float))
        ] if isinstance(entries, list) else []
        newest = max(timestamps) if timestamps else None
        age = datetime.now(timezone.utc).timestamp() - newest if newest is not None else None
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


def _company_access_unavailable() -> CompanyAccessError:
    return CompanyAccessError(
        status=503,
        code="COMPANY_ACCESS_UNAVAILABLE",
        title="Company access unavailable",
        detail="Company access is temporarily unavailable.",
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
    "CompanyAccessService",
    "CompanyCancellation",
    "CompanyCancellationListResponse",
    "CompanyCancellationResponse",
    "CompanyCancellationEvidence",
    "CompanyDeletionReview",
    "CompanyDeletionReviewResponse",
    "CompanyInvitation",
    "CompanyInvitationCommandRequest",
    "CompanyInvitationListResponse",
    "CompanyInvitationResponse",
    "CompanyMembership",
    "CompanyMembershipListResponse",
    "CompanyMembershipResponse",
    "CompanyContext",
    "CompanyContextResponse",
    "CreateCompanyInvitationRequest",
    "FinalizeCompanyDeletionGatewayCommand",
    "FinalizeCompanyDeletionRequest",
    "InvitationLookup",
    "InvitationSideEffectCompletion",
    "InvitationSideEffectContinuation",
    "InvitationSideEffectContinuationList",
    "InvitationTokenRequest",
    "InvitationRole",
    "MembershipState",
    "RequestCompanyCancellationGatewayCommand",
    "RequestCompanyCancellationRequest",
    "ResumeCompanyCancellationGatewayCommand",
    "ResumeCompanyCancellationRequest",
    "ReviewCompanyDeletionGatewayCommand",
    "ReviewCompanyDeletionRequest",
    "company_access_adapter",
]
