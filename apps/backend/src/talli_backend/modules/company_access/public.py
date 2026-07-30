"""The only supported Python import path for the company-access capability."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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
    role: Literal["owner", "reviewer", "read_only"]
    resource_scope: Literal["workspace", "owner", "owner_sensitive"]
    aal: Literal["aal1", "aal2"]


class CompanyContextResponse(CompanyAccessModel):
    selected_company: CompanyContext
    companies: list[CompanyContext]


class CompanyAccessError(Exception):
    def __init__(self, *, status: int, code: str, title: str, detail: str) -> None:
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail


class SupabaseGateway(Protocol):
    async def session_subject(self, access_token: str) -> str: ...

    async def memberships(self, access_token: str, subject: str) -> list[Mapping[str, object]]: ...

    async def companies(self, access_token: str, company_ids: list[str]) -> list[Mapping[str, object]]: ...


@dataclass(frozen=True)
class _SupabaseConfiguration:
    url: str
    anon_key: str


class SupabaseCompanyAccessGateway:
    """Uses a verified Supabase session for Auth and RLS-protected reads."""

    def __init__(self, configuration: _SupabaseConfiguration | None = None) -> None:
        self._configuration = configuration or _SupabaseConfiguration(
            url=os.environ.get("SUPABASE_URL", "").rstrip("/"),
            anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
        )

    def _headers(self, access_token: str) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "apikey": self._configuration.anon_key,
            "Authorization": f"Bearer {access_token}",
        }

    async def _request(self, path: str, access_token: str) -> object:
        if not self._configuration.url or not self._configuration.anon_key:
            raise CompanyAccessError(
                status=503,
                code="COMPANY_ACCESS_UNAVAILABLE",
                title="Company access unavailable",
                detail="Company access is temporarily unavailable.",
            )

        def send() -> object:
            request = Request(
                f"{self._configuration.url}{path}",
                headers=self._headers(access_token),
                method="GET",
            )
            try:
                with urlopen(request, timeout=5) as response:  # noqa: S310 - configured HTTPS endpoint
                    return json.loads(response.read())
            except HTTPError as error:
                if error.code in {401, 403}:
                    raise CompanyAccessError(
                        status=401,
                        code="AUTHENTICATION_REQUIRED",
                        title="Authentication required",
                        detail="A valid session is required.",
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
    def __init__(self, gateway: SupabaseGateway | None = None) -> None:
        self._gateway = gateway or SupabaseCompanyAccessGateway()

    async def selected_context(
        self,
        access_token: str,
        *,
        company_id: str | None,
        resource_scope: Literal["workspace", "owner", "owner_sensitive"],
    ) -> CompanyContextResponse:
        subject = await self._gateway.session_subject(access_token)
        aal = _token_aal(access_token)
        memberships = await self._gateway.memberships(access_token, subject)
        roles = {
            str(item["company_id"]): str(item["role"])
            for item in memberships
            if item.get("accepted_at") is not None
            and item.get("role") in {"owner", "reviewer", "read_only"}
        }
        allowed_ids = [company_id] if company_id else list(roles)
        companies = await self._gateway.companies(access_token, allowed_ids)
        permitted_companies = [
            company
            for company in companies
            if isinstance(company.get("id"), str)
            and company["id"] in roles
            and (resource_scope == "workspace" or roles[company["id"]] == "owner")
        ]
        if not permitted_companies:
            raise CompanyAccessError(
                status=404,
                code="COMPANY_CONTEXT_NOT_FOUND",
                title="Company context not found",
                detail="The requested company context was not found.",
            )
        selected = permitted_companies[0]
        role = roles[str(selected["id"])]
        if resource_scope == "owner_sensitive" and aal != "aal2":
            raise CompanyAccessError(
                status=403,
                code="AAL2_REQUIRED",
                title="Additional verification required",
                detail="Additional verification is required for this company context.",
            )
        def context(company: Mapping[str, object]) -> CompanyContext:
            company_role = roles[str(company["id"])]
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
                role=company_role,  # type: ignore[arg-type]
                resource_scope=resource_scope,
                aal=aal,
            )

        contexts = [context(company) for company in permitted_companies]
        return CompanyContextResponse(selected_company=contexts[0], companies=contexts)


__all__ = [
    "CompanyAccessError",
    "CompanyAccessService",
    "CompanyContext",
    "CompanyContextResponse",
]
