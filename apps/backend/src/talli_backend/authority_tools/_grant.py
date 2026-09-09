"""Private CLI grant compatibility, separate from the four-scope web provider port.

Only the four approved standalone authority tools may call this helper. Its
configured scope and optional external reference preserve the original CLI RAR.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
from asyncio import timeout
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from talli_backend.adapters.maskinporten import (
    MASKINPORTEN_JWT_BEARER_GRANT_TYPE, MaskinportenAccessToken,
    MaskinportenTokenError, sign_maskinporten_grant,
)

_ISSUERS = {"test": "https://test.maskinporten.no/", "production": "https://maskinporten.no/"}
_MAX_RESPONSE_BYTES = 65_536


def _reject_json_constant(_value: str) -> None:
    raise ValueError("Invalid JSON constant.")


def required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required.")
    return value


def _identifier(value: str) -> str:
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("Maskinporten identifier is invalid.")
    return value


@dataclass(frozen=True, slots=True)
class CliGrantConfiguration:
    environment: str
    client_id: str = field(repr=False)
    key_id: str = field(repr=False)
    private_key_pem: str = field(repr=False)
    scope: str
    system_user_org_number: str
    system_user_external_ref: str | None = field(default=None, repr=False)

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> CliGrantConfiguration:
        values = os.environ if environment is None else environment
        selected = required(values, "TALLI_MASKINPORTEN_ENVIRONMENT")
        if selected not in _ISSUERS:
            raise ValueError("TALLI_MASKINPORTEN_ENVIRONMENT must be test or production.")
        key_path = Path(required(values, "TALLI_MASKINPORTEN_PRIVATE_KEY_PATH"))
        try:
            # Check the actual opened file before reading, avoiding a stat/read race.
            descriptor = os.open(key_path, os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                    raise ValueError("Maskinporten private-key file must be a mode-0600 regular file.")
                pem = source.read(16_385).decode("utf-8")
        except (OSError, UnicodeError):
            raise ValueError("Maskinporten private-key file could not be read.") from None
        return cls(selected, required(values, "TALLI_MASKINPORTEN_CLIENT_ID"),
                   required(values, "TALLI_MASKINPORTEN_KEY_ID"), pem,
                   required(values, "TALLI_MASKINPORTEN_SCOPE"),
                   required(values, "TALLI_MASKINPORTEN_SYSTEM_USER_ORG"),
                   values.get("TALLI_MASKINPORTEN_SYSTEM_USER_EXTERNAL_REF", "").strip() or None)


def build_cli_grant(configuration: CliGrantConfiguration, *, now: datetime | None = None,
                    jti: str | None = None) -> tuple[dict, dict]:
    if configuration.environment not in _ISSUERS:
        raise ValueError("Maskinporten environment must be test or production.")
    scope = configuration.scope
    if (not isinstance(scope, str) or not scope or scope != scope.strip()
            or any(c in scope for c in "\r\n\t\x00") or any(not part for part in scope.split(" "))):
        raise ValueError("Maskinporten scope is invalid.")
    organization = configuration.system_user_org_number.strip()
    if not re.fullmatch(r"[0-9]{9}", organization):
        raise ValueError("Maskinporten system-user organization number must contain 9 digits.")
    observed = now or datetime.now(UTC)
    if observed.tzinfo is None:
        raise ValueError("Maskinporten grant time is invalid.")
    issued_at = math.floor(observed.timestamp())
    detail = {"type": "urn:altinn:systemuser", "systemuser_org": {
        "authority": "iso6523-actorid-upis", "ID": f"0192:{organization}"}}
    if configuration.system_user_external_ref is not None:
        detail["externalRef"] = _identifier(configuration.system_user_external_ref)
    client_id = _identifier(configuration.client_id)
    return {"alg": "RS256", "kid": _identifier(configuration.key_id), "typ": "JWT"}, {
        "aud": _ISSUERS[configuration.environment], "iss": client_id,
        "iat": issued_at, "exp": issued_at + 119, "jti": _identifier(str(uuid4()) if jti is None else jti),
        "scope": scope, "sub": client_id, "authorization_details": [detail],
    }


async def request_token(configuration: CliGrantConfiguration, *,
                        transport: httpx.AsyncBaseTransport | None = None,
                        now: datetime | None = None, jti: str | None = None) -> MaskinportenAccessToken:
    header, claims = build_cli_grant(configuration, now=now, jti=jti)
    assertion = sign_maskinporten_grant(header, claims, configuration.private_key_pem)
    status = None
    try:
        async with timeout(15), httpx.AsyncClient(transport=transport, timeout=15,
                                                 follow_redirects=False, trust_env=False) as client:
            async with client.stream("POST", _ISSUERS[configuration.environment] + "token",
                    data={"grant_type": MASKINPORTEN_JWT_BEARER_GRANT_TYPE, "assertion": assertion}) as response:
                status = response.status_code
                if not response.is_success:
                    raise MaskinportenTokenError("maskinporten_http_error", status=status)
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > _MAX_RESPONSE_BYTES:
                        raise ValueError()
                    raw.extend(chunk)
        data = json.loads(raw.decode("utf-8-sig", errors="replace"), parse_constant=_reject_json_constant)
        if not isinstance(data, dict):
            raise ValueError()
        access_token = data.get("access_token")
        if (not isinstance(access_token, str) or not 1 <= len(access_token) <= 8192
                or not access_token.isascii()
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in access_token)):
            raise ValueError()
        expires_in = float(data.get("expires_in"))
        if not math.isfinite(expires_in) or expires_in <= 0:
            raise ValueError()
        if "scope" in data and data["scope"] != configuration.scope:
            raise ValueError()
        # Never reflect an arbitrary provider string through token-smoke stdout.
        if data.get("token_type", "Bearer").lower() != "bearer":
            raise ValueError()
        return MaskinportenAccessToken(access_token, "Bearer", expires_in,
                                      configuration.scope, configuration.environment)
    except (httpx.HTTPError, TimeoutError):
        raise MaskinportenTokenError("maskinporten_network_error") from None
    except (ValueError, TypeError, AttributeError, UnicodeError, RecursionError, OverflowError):
        raise MaskinportenTokenError("maskinporten_response_invalid", status=status) from None


def token_summary(token: MaskinportenAccessToken) -> dict:
    return {"environment": token.environment, "scope": token.scope, "tokenType": token.token_type,
            "expiresIn": token.expires_in, "accessTokenPresent": bool(token.access_token)}
