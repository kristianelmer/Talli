"""Supabase Auth and PostgREST adapter for the company-access port."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from talli_backend.modules.company_access.public import (
    AcceptInvitationGatewayCommand,
    AdministerMembershipGatewayCommand,
    CompanyAccessError,
    CompanyAccessGateway,
    CreateInvitationGatewayCommand,
    FinalizeCompanyDeletionGatewayCommand,
    InvitationIdentityGatewayCommand,
    InvitationMutationGatewayCommand,
    ResendInvitationGatewayCommand,
    RequestCompanyCancellationGatewayCommand,
    ReviewCompanyDeletionGatewayCommand,
    company_access_adapter,
)


@dataclass(frozen=True)
class SupabaseConfiguration:
    url: str
    anon_key: str


def _validated_origin(raw: str) -> str:
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        _ = parsed.port
        hostname = parsed.hostname
    except (ValueError, UnicodeError):
        raise ValueError("Supabase origin is invalid") from None
    is_loopback = hostname == "localhost"
    if hostname is not None and not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = False
    if (
        parsed.scheme not in {"http", "https"}
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or (parsed.scheme == "http" and not is_loopback)
    ):
        raise ValueError("Supabase origin is unsafe")
    return f"{parsed.scheme}://{parsed.netloc}"


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


@company_access_adapter(CompanyAccessGateway)
class SupabaseCompanyAccessAdapter:
    """Validate Supabase sessions and preserve their bearer for RLS reads."""

    def __init__(self, configuration: SupabaseConfiguration) -> None:
        self._origin = _validated_origin(configuration.url)
        self._anon_key = configuration.anon_key
        self._opener = build_opener(_RejectRedirects)

    @classmethod
    def from_environment(cls) -> "SupabaseCompanyAccessAdapter":
        return cls(SupabaseConfiguration(
            url=os.environ.get("SUPABASE_URL", ""),
            anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
        ))

    def _headers(self, access_token: str, *, content: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "apikey": self._anon_key,
            "Authorization": f"Bearer {access_token}",
        }
        if content:
            headers["Content-Type"] = "application/json"
        return headers

    async def _request(
        self,
        path: str,
        access_token: str,
        *,
        method: str = "GET",
        body: Mapping[str, object] | None = None,
    ) -> object:
        if not self._origin or not self._anon_key:
            raise CompanyAccessError(
                status=503,
                code="COMPANY_ACCESS_UNAVAILABLE",
                title="Company access unavailable",
                detail="Company access is temporarily unavailable.",
            )

        def send() -> object:
            request = Request(
                f"{self._origin}{path}",
                headers=self._headers(access_token, content=body is not None),
                data=json.dumps(body).encode() if body is not None else None,
                method=method,
            )
            try:
                with self._opener.open(request, timeout=5) as response:
                    return json.loads(response.read())
            except HTTPError as error:
                if error.code in {401, 403}:
                    raise CompanyAccessError(
                        status=401,
                        code="AUTHENTICATION_REQUIRED",
                        title="Authentication required",
                        detail="A valid session is required.",
                    ) from None
                try:
                    provider_error = json.loads(error.read())
                except json.JSONDecodeError:
                    provider_error = {}
                message = provider_error.get("message") if isinstance(provider_error, Mapping) else None
                if message in {"company_access_not_found", "invitation_not_found"}:
                    invitation = message == "invitation_not_found"
                    raise CompanyAccessError(
                        status=404,
                        code="INVITATION_NOT_FOUND" if invitation else "COMPANY_ACCESS_NOT_FOUND",
                        title="Invitation not found" if invitation else "Company access not found",
                        detail=(
                            "The requested invitation was not found or is no longer available."
                            if invitation
                            else "The requested company access resource was not found."
                        ),
                    ) from None
                if message == "company_access_invalid_request":
                    raise CompanyAccessError(
                        status=422,
                        code="REQUEST_VALIDATION_FAILED",
                        title="Request validation failed",
                        detail="The request did not satisfy the company access policy.",
                    ) from None
                if message == "company_access_conflict":
                    raise CompanyAccessError(
                        status=409,
                        code="COMPANY_ACCESS_CONFLICT",
                        title="Company access conflict",
                        detail="The company access change conflicts with existing state.",
                    ) from None
                lifecycle_errors = {
                    "cancellation_prerequisite_failed": (
                        "CANCELLATION_PREREQUISITE_FAILED",
                        "Cancellation prerequisite failed",
                        "A current complete company archive export is required.",
                    ),
                    "deletion_review_required": (
                        "DELETION_REVIEW_REQUIRED",
                        "Deletion review required",
                        "An approved deletion review is required.",
                    ),
                }
                if message in lifecycle_errors:
                    code, title, detail = lifecycle_errors[message]
                    raise CompanyAccessError(
                        status=409, code=code, title=title, detail=detail
                    ) from None
                if error.code == 409:
                    raise CompanyAccessError(
                        status=409,
                        code="COMPANY_ACCESS_CONFLICT",
                        title="Company access conflict",
                        detail="The company access change conflicts with existing state.",
                    ) from None
                raise CompanyAccessError(
                    status=503,
                    code="COMPANY_ACCESS_UNAVAILABLE",
                    title="Company access unavailable",
                    detail="Company access is temporarily unavailable.",
                ) from None
            except (URLError, TimeoutError, json.JSONDecodeError):
                raise CompanyAccessError(
                    status=503,
                    code="COMPANY_ACCESS_UNAVAILABLE",
                    title="Company access unavailable",
                    detail="Company access is temporarily unavailable.",
                ) from None

        return await asyncio.to_thread(send)

    async def session_subject(self, access_token: str) -> str:
        response = await self._request("/auth/v1/user", access_token)
        if not isinstance(response, Mapping) or not isinstance(response.get("id"), str):
            raise CompanyAccessError(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="A valid session is required.",
            )
        return response["id"]

    async def session_identity(self, access_token: str) -> Mapping[str, object]:
        response = await self._request("/auth/v1/user", access_token)
        if (
            not isinstance(response, Mapping)
            or not isinstance(response.get("id"), str)
            or not isinstance(response.get("email"), str)
        ):
            raise CompanyAccessError(
                status=401,
                code="AUTHENTICATION_REQUIRED",
                title="Authentication required",
                detail="A valid session with a verified email is required.",
            )
        return {"id": response["id"], "email": response["email"]}

    async def memberships(self, access_token: str, subject: str) -> list[Mapping[str, object]]:
        query = urlencode({
            "select": "company_id,role,accepted_at",
            "user_id": f"eq.{subject}",
            "accepted_at": "not.is.null",
        })
        response = await self._request(f"/rest/v1/company_memberships?{query}", access_token)
        return response if isinstance(response, list) else []

    async def companies(self, access_token: str, company_ids: list[str]) -> list[Mapping[str, object]]:
        if not company_ids:
            return []
        query = urlencode({
            "select": "id,org_number,name,entity_type,address,postal_code,city,status_text,source,created_by,identity_confirmed_at,identity_locked_at,created_at",
            "id": f"in.({','.join(company_ids)})",
            "order": "created_at.desc",
        }, safe="(),")
        response = await self._request(f"/rest/v1/companies?{query}", access_token)
        return response if isinstance(response, list) else []

    async def invitations(
        self, access_token: str, company_id: str
    ) -> list[Mapping[str, object]]:
        query = urlencode({
            "select": "id,company_id,invited_email,role,status,expires_at,created_at,updated_at",
            "company_id": f"eq.{company_id}",
            "order": "updated_at.desc",
        })
        response = await self._request(f"/rest/v1/company_invitations?{query}", access_token)
        return response if isinstance(response, list) else []

    async def create_invitation(
        self, access_token: str, command: CreateInvitationGatewayCommand
    ) -> Mapping[str, object]:
        return await self._rpc_row(access_token, "company_access_create_invitation", {
            "p_operation_id": command.operation_id,
            "p_company_id": command.company_id,
            "p_invited_email": command.invited_email,
            "p_role": command.role,
            "p_token_hash": command.token_hash,
            "p_acceptance_token": command.acceptance_token,
        }) or {}

    async def lookup_invitation(
        self, access_token: str, command: InvitationIdentityGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(
            access_token, "company_access_lookup_invitation", {
                "p_token_hash": command.token_hash,
                "p_verified_subject": command.verified_subject,
                "p_verified_email": command.verified_email,
            }
        )

    async def accept_invitation(
        self, access_token: str, command: AcceptInvitationGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(
            access_token, "company_access_accept_invitation", {
                "p_operation_id": command.operation_id,
                "p_token_hash": command.token_hash,
                "p_verified_subject": command.verified_subject,
                "p_verified_email": command.verified_email,
            }
        )

    async def revoke_invitation(
        self, access_token: str, command: InvitationMutationGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(access_token, "company_access_revoke_invitation", {
            "p_operation_id": command.operation_id,
            "p_company_id": command.company_id,
            "p_invitation_id": command.invitation_id,
            "p_expected_updated_at": command.expected_updated_at,
        })

    async def resend_invitation(
        self, access_token: str, command: ResendInvitationGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(access_token, "company_access_resend_invitation", {
            "p_operation_id": command.operation_id,
            "p_company_id": command.company_id,
            "p_invitation_id": command.invitation_id,
            "p_expected_updated_at": command.expected_updated_at,
            "p_token_hash": command.token_hash,
            "p_acceptance_token": command.acceptance_token,
        })

    async def company_memberships(
        self, access_token: str, company_id: str
    ) -> list[Mapping[str, object]]:
        query = urlencode({
            "select": "company_id,user_id,role,accepted_at",
            "company_id": f"eq.{company_id}",
            "role": "in.(reviewer,read_only)",
            "accepted_at": "not.is.null",
            "order": "created_at.asc",
        }, safe="(),")
        response = await self._request(f"/rest/v1/company_memberships?{query}", access_token)
        if not isinstance(response, list):
            return []
        return [{**row, "state": "active"} for row in response if isinstance(row, Mapping)]

    async def administer_membership(
        self, access_token: str, command: AdministerMembershipGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(access_token, "company_access_administer_membership", {
            "p_operation_id": command.operation_id,
            "p_company_id": command.company_id,
            "p_user_id": command.user_id,
            "p_expected_role": command.expected_role,
            "p_role": command.role,
            "p_state": command.state,
        })

    async def pending_invitation_side_effects(
        self, access_token: str
    ) -> list[Mapping[str, object]]:
        response = await self._request(
            "/rest/v1/rpc/company_access_pending_invitation_side_effects",
            access_token,
            method="POST",
            body={},
        )
        return response if isinstance(response, list) else []

    async def complete_invitation_side_effect(
        self, access_token: str, operation_id: str
    ) -> bool:
        response = await self._request(
            "/rest/v1/rpc/company_access_complete_invitation_side_effect",
            access_token,
            method="POST",
            body={"p_operation_id": operation_id},
        )
        return response is True

    async def cancellations(
        self, access_token: str, company_id: str
    ) -> list[Mapping[str, object]]:
        response = await self._request(
            "/rest/v1/rpc/company_access_list_cancellations",
            access_token,
            method="POST",
            body={"p_company_id": company_id},
        )
        return response if isinstance(response, list) else []

    async def request_cancellation(
        self, access_token: str, command: RequestCompanyCancellationGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(
            access_token,
            "company_access_request_cancellation",
            {
                "p_operation_id": command.operation_id,
                "p_company_id": command.company_id,
                "p_income_year": command.income_year,
                "p_reason": command.reason,
            },
        )

    async def review_deletion(
        self, access_token: str, command: ReviewCompanyDeletionGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(
            access_token,
            "company_access_review_deletion",
            {
                "p_operation_id": command.operation_id,
                "p_cancellation_id": command.cancellation_id,
                "p_company_id": command.company_id,
                "p_expected_updated_at": command.expected_updated_at,
                "p_decision": command.decision,
                "p_evidence_reference": command.evidence_reference,
            },
        )

    async def finalize_deletion(
        self, access_token: str, command: FinalizeCompanyDeletionGatewayCommand
    ) -> Mapping[str, object] | None:
        return await self._rpc_row(
            access_token,
            "company_access_finalize_deletion",
            {
                "p_operation_id": command.operation_id,
                "p_cancellation_id": command.cancellation_id,
                "p_company_id": command.company_id,
                "p_expected_updated_at": command.expected_updated_at,
            },
        )

    async def _rpc_row(
        self,
        access_token: str,
        function_name: str,
        body: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        path = f"/rest/v1/rpc/{function_name}"
        try:
            try:
                response = await self._request(path, access_token, method="POST", body=body)
            except CompanyAccessError as retry_error:
                if (
                    retry_error.code == "COMPANY_ACCESS_UNAVAILABLE"
                    and function_name in {
                        "company_access_request_cancellation",
                        "company_access_review_deletion",
                        "company_access_finalize_deletion",
                    }
                ):
                    reconciled = await self._reconcile_cancellation(
                        access_token, function_name, body
                    )
                    if reconciled is not None:
                        return reconciled
                raise
        except CompanyAccessError as error:
            if error.code != "COMPANY_ACCESS_UNAVAILABLE" or "p_operation_id" not in body:
                raise
            if function_name.startswith("company_access_") and function_name in {
                "company_access_request_cancellation",
                "company_access_review_deletion",
                "company_access_finalize_deletion",
            }:
                reconciled = await self._reconcile_cancellation(
                    access_token, function_name, body
                )
                if reconciled is not None:
                    return reconciled
            # A receipt is definitively absent only after reconciliation has
            # linearized behind the original actor+operation transaction.
            response = await self._request(path, access_token, method="POST", body=body)
        if not isinstance(response, list) or not response or not isinstance(response[0], Mapping):
            return None
        return response[0]

    async def _reconcile_cancellation(
        self,
        access_token: str,
        function_name: str,
        body: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        command_names = {
            "company_access_request_cancellation": "request_cancellation",
            "company_access_review_deletion": "review_deletion",
            "company_access_finalize_deletion": "finalize_deletion",
        }
        reconcile_body = dict(body)
        reconcile_body["p_command_name"] = command_names[function_name]
        response = await self._request(
            "/rest/v1/rpc/company_access_reconcile_cancellation_operation",
            access_token,
            method="POST",
            body=reconcile_body,
        )
        if not isinstance(response, list) or not response or not isinstance(response[0], Mapping):
            return None
        row = response[0]
        if row.get("found") is not True or not isinstance(row.get("result"), Mapping):
            return None
        result = row["result"]
        if function_name == "company_access_review_deletion":
            cancellation = result.get("cancellation")
            review = result.get("review")
            if not isinstance(cancellation, Mapping) or not isinstance(review, Mapping):
                return None
            return {**cancellation, "review": review}
        return result


__all__ = ["SupabaseCompanyAccessAdapter", "SupabaseConfiguration"]
