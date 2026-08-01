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
    CompanyAccessError,
    CompanyAccessGateway,
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

    def _headers(self, access_token: str) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "apikey": self._anon_key,
            "Authorization": f"Bearer {access_token}",
        }

    async def _request(self, path: str, access_token: str) -> object:
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
                headers=self._headers(access_token),
                method="GET",
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


__all__ = ["SupabaseCompanyAccessAdapter", "SupabaseConfiguration"]
