"""Bounded Brønnøysundregistrene adapter for company-access onboarding."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from talli_backend.modules.company_access.public import (
    CompanyAccessError,
    CompanyRegistryGateway,
    company_registry_adapter,
)


@dataclass(frozen=True)
class BrregCompanyRegistryConfiguration:
    origin: str = "https://data.brreg.no"
    timeout_seconds: float = 5.0


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


def _validated_origin(raw: str) -> str:
    try:
        parsed = urlsplit(raw)
        _ = parsed.port
        hostname = parsed.hostname
    except (ValueError, UnicodeError):
        raise ValueError("Company registry origin is invalid") from None
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
        raise ValueError("Company registry origin is unsafe")
    if hostname != "data.brreg.no" and not is_loopback:
        raise ValueError("Company registry origin is not an approved provider")
    return f"{parsed.scheme}://{parsed.netloc}"


def _unavailable() -> CompanyAccessError:
    return CompanyAccessError(
        status=503,
        code="COMPANY_REGISTRY_UNAVAILABLE",
        title="Company registry unavailable",
        detail="The public company registry is temporarily unavailable.",
    )


def _required_string(
    value: object, *, maximum: int, pattern: str | None = None
) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _unavailable()
    if pattern is not None and re.fullmatch(pattern, value) is None:
        raise _unavailable()
    return value


def _optional_string(
    value: object, *, maximum: int, pattern: str | None = None
) -> str:
    if value is None:
        return ""
    return _required_string(value, maximum=maximum, pattern=pattern)


def _optional_boolean(value: object) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise _unavailable()
    return value


def _address(payload: Mapping[str, object]) -> tuple[str, str, str]:
    candidate = payload.get("forretningsadresse") or payload.get("postadresse") or {}
    if not isinstance(candidate, Mapping):
        raise _unavailable()
    raw_lines = candidate.get("adresse", [])
    if (
        not isinstance(raw_lines, list)
        or len(raw_lines) > 8
        or not all(isinstance(line, str) and len(line) <= 128 for line in raw_lines)
    ):
        raise _unavailable()
    rendered = ", ".join(raw_lines)
    if len(rendered) > 512:
        raise _unavailable()
    return (
        rendered,
        _optional_string(candidate.get("postnummer"), maximum=4, pattern=r"\d{4}"),
        _optional_string(candidate.get("poststed"), maximum=128),
    )


_MAX_RESPONSE_BYTES = 64 * 1024


@company_registry_adapter(CompanyRegistryGateway)
class BrregCompanyRegistryAdapter:
    def __init__(self, configuration: BrregCompanyRegistryConfiguration | None = None) -> None:
        settings = configuration or BrregCompanyRegistryConfiguration()
        if settings.timeout_seconds <= 0 or settings.timeout_seconds > 10:
            raise ValueError("Company registry timeout must be between zero and ten seconds")
        self._origin = _validated_origin(settings.origin)
        self._timeout_seconds = settings.timeout_seconds
        self._opener = build_opener(_RejectRedirects)

    @classmethod
    def from_environment(cls) -> BrregCompanyRegistryAdapter:
        raw_timeout = os.environ.get("BRREG_TIMEOUT_SECONDS", "5")
        try:
            timeout = float(raw_timeout)
        except ValueError:
            raise ValueError("Company registry timeout is invalid") from None
        return cls(
            BrregCompanyRegistryConfiguration(
                origin=os.environ.get("BRREG_BASE_URL", "https://data.brreg.no"),
                timeout_seconds=timeout,
            )
        )

    async def lookup_company(self, org_number: str) -> Mapping[str, object]:
        if re.fullmatch(r"[0-9]{9}", org_number) is None:
            raise CompanyAccessError(
                status=422,
                code="REQUEST_VALIDATION_FAILED",
                title="Request validation failed",
                detail="The organization number must contain nine digits.",
            )

        def send() -> Mapping[str, object]:
            request = Request(
                f"{self._origin}/enhetsregisteret/api/enheter/{org_number}",
                headers={"Accept": "application/json"},
                method="GET",
            )
            try:
                with self._opener.open(request, timeout=self._timeout_seconds) as response:
                    if response.headers.get_content_type() != "application/json":
                        raise _unavailable()
                    declared_length = response.headers.get("Content-Length")
                    if declared_length is not None:
                        try:
                            if int(declared_length) > _MAX_RESPONSE_BYTES:
                                raise _unavailable()
                        except ValueError:
                            raise _unavailable() from None
                    payload = response.read(_MAX_RESPONSE_BYTES + 1)
                    if len(payload) > _MAX_RESPONSE_BYTES:
                        raise _unavailable()
                    raw = json.loads(payload)
            except HTTPError as error:
                if error.code == 404:
                    raise CompanyAccessError(
                        status=404,
                        code="COMPANY_REGISTRY_NOT_FOUND",
                        title="Company not found",
                        detail="The organization number was not found in the public company registry.",
                    ) from None
                raise _unavailable() from None
            except (URLError, TimeoutError, json.JSONDecodeError, OSError):
                raise _unavailable() from None
            if not isinstance(raw, Mapping):
                raise _unavailable()
            returned_org_number = _required_string(
                raw.get("organisasjonsnummer"), maximum=9, pattern=r"\d{9}"
            )
            if returned_org_number != org_number:
                raise _unavailable()
            name = _required_string(raw.get("navn"), maximum=256)
            entity = raw.get("organisasjonsform")
            if not isinstance(entity, Mapping):
                raise _unavailable()
            entity_type = _required_string(entity.get("kode"), maximum=32)
            address, postal_code, city = _address(raw)
            deleted_at = _optional_string(raw.get("slettedato"), maximum=32)
            under_bankruptcy = _optional_boolean(raw.get("underKonkursbehandling"))
            under_liquidation = _optional_boolean(raw.get("underAvvikling"))
            status_text = (
                "slettet"
                if deleted_at
                else "under konkursbehandling"
                if under_bankruptcy
                else "under avvikling"
                if under_liquidation
                else "aktiv"
            )
            return {
                "org_number": returned_org_number,
                "name": name,
                "entity_type": entity_type,
                "address": address,
                "postal_code": postal_code,
                "city": city,
                "status_text": status_text,
                "source": "brreg",
            }

        return await asyncio.to_thread(send)


__all__ = ["BrregCompanyRegistryAdapter", "BrregCompanyRegistryConfiguration"]
