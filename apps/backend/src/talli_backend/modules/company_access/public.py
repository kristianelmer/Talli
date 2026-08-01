"""The only supported Python import path for the company-access capability."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Callable, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class CompanyAccessModel(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


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
        self, access_token: str, invitation: Mapping[str, object]
    ) -> Mapping[str, object]: ...

    async def lookup_invitation(
        self, access_token: str, token_hash: str
    ) -> Mapping[str, object] | None: ...

    async def accept_invitation(
        self, access_token: str, token_hash: str
    ) -> Mapping[str, object] | None: ...

    async def revoke_invitation(
        self, access_token: str, company_id: str, invitation_id: str
    ) -> Mapping[str, object] | None: ...

    async def resend_invitation(
        self, access_token: str, command: Mapping[str, object]
    ) -> Mapping[str, object] | None: ...

    async def company_memberships(
        self, access_token: str, company_id: str
    ) -> list[Mapping[str, object]]: ...

    async def administer_membership(
        self, access_token: str, command: Mapping[str, object]
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
        *,
        company_id: str,
        invited_email: str,
        role: InvitationRole,
    ) -> CompanyInvitationResponse:
        identity = await self._authorize_owner(access_token, company_id)
        company = await self._company(access_token, company_id)
        normalized_email = _normalize_email(invited_email)
        acceptance_token = secrets.token_urlsafe(32)
        row = await self._gateway.create_invitation(
            access_token,
            {
                "company_id": company_id,
                "invited_email": normalized_email,
                "role": role,
                "token_hash": _token_hash(acceptance_token),
                "acceptance_token": acceptance_token,
                "invited_by": str(identity["id"]),
            },
        )
        return CompanyInvitationResponse(
            invitation=self._invitation(row),
            delivery_token=acceptance_token,
            delivery_subject=f"Invitasjon til Talli: {company['name']}",
            delivery_body=_invitation_body(
                company_name=str(company["name"]),
                role=role,
                acceptance_token=acceptance_token,
            ),
        )

    async def lookup_invitation(
        self, access_token: str, *, token: str
    ) -> InvitationLookup:
        identity = await self._gateway.session_identity(access_token)
        email = _identity_email(identity)
        row = await self._gateway.lookup_invitation(access_token, _required_token_hash(token))
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
        self, access_token: str, *, token: str
    ) -> CompanyMembershipResponse:
        identity = await self._gateway.session_identity(access_token)
        _identity_email(identity)
        row = await self._gateway.accept_invitation(access_token, _required_token_hash(token))
        if row is None:
            raise _invitation_not_found()
        return CompanyMembershipResponse(membership=self._membership(row))

    async def revoke_invitation(
        self, access_token: str, *, company_id: str, invitation_id: str
    ) -> CompanyInvitationResponse:
        await self._authorize_owner(access_token, company_id)
        row = await self._gateway.revoke_invitation(access_token, company_id, invitation_id)
        if row is None:
            raise _company_access_not_found()
        return CompanyInvitationResponse(
            invitation=self._invitation(row),
            delivery_token=None,
            delivery_subject=None,
            delivery_body=None,
        )

    async def resend_invitation(
        self, access_token: str, *, company_id: str, invitation_id: str
    ) -> CompanyInvitationResponse:
        identity = await self._authorize_owner(access_token, company_id)
        company = await self._company(access_token, company_id)
        acceptance_token = secrets.token_urlsafe(32)
        row = await self._gateway.resend_invitation(
            access_token,
            {
                "company_id": company_id,
                "invitation_id": invitation_id,
                "token_hash": _token_hash(acceptance_token),
                "acceptance_token": acceptance_token,
                "actor_id": str(identity["id"]),
            },
        )
        if row is None:
            raise _company_access_not_found()
        return CompanyInvitationResponse(
            invitation=self._invitation(row),
            delivery_token=acceptance_token,
            delivery_subject=f"Invitasjon til Talli: {company['name']}",
            delivery_body=_invitation_body(
                company_name=str(company["name"]),
                role=str(row["role"]),
                acceptance_token=acceptance_token,
            ),
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
        *,
        company_id: str,
        user_id: str,
        role: InvitationRole | None,
        state: MembershipState | None,
    ) -> CompanyMembershipResponse:
        if role is None and state is None:
            raise CompanyAccessError(
                status=422,
                code="REQUEST_VALIDATION_FAILED",
                title="Request validation failed",
                detail="A membership role or state change is required.",
            )
        identity = await self._authorize_owner(access_token, company_id)
        if user_id == identity["id"]:
            raise _company_access_not_found()
        row = await self._gateway.administer_membership(
            access_token,
            {
                "company_id": company_id,
                "user_id": user_id,
                "role": role,
                "state": state,
                "actor_id": str(identity["id"]),
            },
        )
        if row is None or row.get("role") == "owner":
            raise _company_access_not_found()
        return CompanyMembershipResponse(membership=self._membership(row))

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


def _invitation_not_found() -> CompanyAccessError:
    return CompanyAccessError(
        status=404,
        code="INVITATION_NOT_FOUND",
        title="Invitation not found",
        detail="The requested invitation was not found or is no longer available.",
    )


__all__ = [
    "CompanyAccessError",
    "CompanyAccessGateway",
    "CompanyAccessService",
    "CompanyInvitation",
    "CompanyInvitationListResponse",
    "CompanyInvitationResponse",
    "CompanyMembership",
    "CompanyMembershipListResponse",
    "CompanyMembershipResponse",
    "CompanyContext",
    "CompanyContextResponse",
    "InvitationLookup",
    "InvitationRole",
    "MembershipState",
    "company_access_adapter",
]
