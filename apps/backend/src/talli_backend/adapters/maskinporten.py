"""Backend-only, bounded RS256 Maskinporten transport for the existing RF scopes."""

from __future__ import annotations

import base64
import json
import math
import os
import re
from asyncio import timeout
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import httpx
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


SYSTEM_USER_CONTROL_WRITE_SCOPE = "altinn:authentication/systemuser.request.write"
SYSTEM_USER_CONTROL_READ_SCOPE = "altinn:authentication/systemuser.request.read"
SYSTEM_REGISTER_WRITE_SCOPE = "altinn:authentication/systemregister.write"
SYSTEM_USER_TAX_SCOPE = "skatteetaten:innrapporteringaksjonaerregisteroppgave"
MASKINPORTEN_JWT_BEARER_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"
_SCOPES = frozenset({SYSTEM_USER_CONTROL_WRITE_SCOPE, SYSTEM_USER_CONTROL_READ_SCOPE,
                     SYSTEM_REGISTER_WRITE_SCOPE, SYSTEM_USER_TAX_SCOPE})
_ISSUERS = {"test": "https://test.maskinporten.no/", "production": "https://maskinporten.no/"}
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.I)
_EXTERNAL_REF = re.compile(r"[A-Za-z0-9_-]{43}")
_PEM = re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----[\s\S]+-----END (?:RSA )?PRIVATE KEY-----\s*")
_MAX_RESPONSE_BYTES = 65_536
MaskinportenEnvironment = Literal["test", "production"]


class MaskinportenTokenError(Exception):
    """Closed diagnostics: never retain a provider body, request, grant or key."""

    def __init__(self, code: str = "maskinporten_token_error", *, status: int | None = None):
        allowed = {"maskinporten_token_error", "maskinporten_grant_signing_failed",
                   "maskinporten_network_error", "maskinporten_http_error", "maskinporten_response_invalid"}
        self.code = code if code in allowed else "maskinporten_token_error"
        self.status = status
        super().__init__(self.code)


def _identifier(value: object, *, maximum: int = 256) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= maximum
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)):
        raise MaskinportenTokenError()
    return value


@dataclass(frozen=True, slots=True)
class MaskinportenConfiguration:
    environment: MaskinportenEnvironment
    client_id: str = field(repr=False)
    key_id: str = field(repr=False)
    private_key_pem: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.environment, str) or self.environment not in _ISSUERS:
            raise MaskinportenTokenError()
        _identifier(self.client_id)
        _identifier(self.key_id)
        if (not isinstance(self.private_key_pem, str) or len(self.private_key_pem) > 16_384
                or not _PEM.fullmatch(self.private_key_pem)):
            raise MaskinportenTokenError("maskinporten_grant_signing_failed")
        if self.environment == "production" and (
            not _UUID.fullmatch(self.client_id) or not _UUID.fullmatch(self.key_id)
        ):
            raise MaskinportenTokenError()

    @classmethod
    def production(cls, environment: Mapping[str, str]) -> MaskinportenConfiguration:
        return cls("production", environment.get("TALLI_PROD_MASKINPORTEN_CLIENT_ID", ""),
                   environment.get("TALLI_PROD_MASKINPORTEN_KEY_ID", ""),
                   environment.get("TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM", ""))


@dataclass(slots=True)
class MaskinportenAccessToken:
    access_token: str = field(repr=False)
    token_type: str
    expires_in: float
    scope: str
    environment: MaskinportenEnvironment

    def discard(self) -> None:
        self.access_token = ""


def build_maskinporten_grant(
    configuration: MaskinportenConfiguration, scope: str, *,
    system_user_org_number: str | None = None, system_user_external_ref: str | None = None,
    now: datetime | None = None, jti: str | None = None,
) -> tuple[dict[str, str], dict[str, object]]:
    if not isinstance(scope, str) or scope not in _SCOPES:
        raise MaskinportenTokenError()
    observed = now if now is not None else datetime.now(UTC)
    if not isinstance(observed, datetime) or observed.tzinfo is None or observed.utcoffset() is None:
        raise MaskinportenTokenError()
    issued_at = math.floor(observed.timestamp())
    claims: dict[str, object] = {
        "aud": _ISSUERS[configuration.environment], "iss": configuration.client_id,
        "iat": issued_at, "exp": issued_at + 119, "jti": _identifier(jti if jti is not None else str(uuid4())),
        "scope": scope,
    }
    if scope == SYSTEM_USER_TAX_SCOPE:
        if (not isinstance(system_user_org_number, str)
                or not re.fullmatch(r"[0-9]{9}", system_user_org_number)
                or not isinstance(system_user_external_ref, str)
                or not _EXTERNAL_REF.fullmatch(system_user_external_ref)):
            raise MaskinportenTokenError()
        claims["sub"] = configuration.client_id
        claims["authorization_details"] = [{
            "type": "urn:altinn:systemuser",
            "systemuser_org": {"authority": "iso6523-actorid-upis", "ID": f"0192:{system_user_org_number}"},
            "externalRef": system_user_external_ref,
        }]
    elif system_user_org_number is not None or system_user_external_ref is not None:
        raise MaskinportenTokenError()
    return {"alg": "RS256", "kid": configuration.key_id, "typ": "JWT"}, claims


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def sign_maskinporten_grant(
    header: Mapping[str, object], claims: Mapping[str, object], private_key_pem: str,
) -> str:
    try:
        if not isinstance(private_key_pem, str) or len(private_key_pem) > 16_384:
            raise ValueError()
        if dict(header).keys() != {"alg", "kid", "typ"} or header["alg"] != "RS256" or header["typ"] != "JWT":
            raise ValueError()
        _identifier(header["kid"])
        key = serialization.load_pem_private_key(private_key_pem.encode("ascii"), password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise ValueError()
        signing_input = ".".join(_base64url(json.dumps(value, separators=(",", ":"), ensure_ascii=False,
                                                      allow_nan=False).encode("utf-8"))
                                 for value in (header, claims)).encode("ascii")
        signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return signing_input.decode("ascii") + "." + _base64url(signature)
    except (ValueError, TypeError, UnicodeError, UnsupportedAlgorithm, MaskinportenTokenError):
        raise MaskinportenTokenError("maskinporten_grant_signing_failed") from None


def _invalid_json_constant(_value: str):
    # JSON.parse rejects these non-JSON Python extensions even in unused fields.
    raise ValueError("invalid JSON constant")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


class MaskinportenClient:
    def __init__(self, configuration: MaskinportenConfiguration | None = None, *,
                 configuration_environment: Mapping[str, str] | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 now: Callable[[], datetime] | None = None, jti: Callable[[], str] | None = None):
        self._configuration = configuration
        self._configuration_environment = configuration_environment
        self._transport = transport
        self._now = now or (lambda: datetime.now(UTC))
        self._jti = jti or (lambda: str(uuid4()))

    @property
    def environment(self) -> MaskinportenEnvironment:
        return self._configuration.environment if self._configuration is not None else "production"

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> MaskinportenClient:
        """Construction performs no credential reads, signing or provider I/O."""
        return cls(configuration_environment=environment)

    async def request_token(self, scope: str, *, system_user_org_number: str | None = None,
                            system_user_external_ref: str | None = None) -> MaskinportenAccessToken:
        configuration = self._configuration
        if configuration is None:
            configuration = MaskinportenConfiguration.production(
                os.environ if self._configuration_environment is None else self._configuration_environment,
            )
        header, claims = build_maskinporten_grant(
            configuration, scope, system_user_org_number=system_user_org_number,
            system_user_external_ref=system_user_external_ref, now=self._now(), jti=self._jti(),
        )
        assertion = sign_maskinporten_grant(header, claims, configuration.private_key_pem)
        status = None
        try:
            async with timeout(15), httpx.AsyncClient(transport=self._transport, timeout=15,
                                                     follow_redirects=False, trust_env=False) as client:
                async with client.stream("POST", _ISSUERS[self.environment] + "token",
                                         data={"grant_type": MASKINPORTEN_JWT_BEARER_GRANT_TYPE,
                                               "assertion": assertion},
                                         headers={"accept": "application/json"}) as response:
                    status = response.status_code
                    if not 200 <= status < 300:
                        raise MaskinportenTokenError("maskinporten_http_error", status=status)
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > _MAX_RESPONSE_BYTES:
                            raise MaskinportenTokenError("maskinporten_response_invalid", status=status)
                        raw.extend(chunk)
            # Fetch Response.json() uses UTF-8 replacement decoding and strips
            # its leading BOM; field validation still rejects malformed tokens.
            data = json.loads(raw.decode("utf-8-sig", errors="replace"), object_pairs_hook=_unique_object,
                              parse_constant=_invalid_json_constant)
            if not isinstance(data, dict):
                raise ValueError()
            access_token = _identifier(data.get("access_token"), maximum=8192)
            if not access_token.isascii():
                raise ValueError()
            expires = data.get("expires_in")
            if isinstance(expires, bool) or not isinstance(expires, (str, int, float)):
                raise ValueError()
            expires_in = float(expires)
            if not math.isfinite(expires_in) or expires_in <= 0:
                raise ValueError()
            if "scope" in data and data["scope"] != scope:
                raise ValueError()
            token_type = data.get("token_type", "Bearer")
            if not isinstance(token_type, str) or token_type.lower() != "bearer":
                raise ValueError()
            return MaskinportenAccessToken(access_token, "Bearer", expires_in, scope, self.environment)
        except (httpx.HTTPError, TimeoutError):
            raise MaskinportenTokenError("maskinporten_network_error") from None
        except MaskinportenTokenError as error:
            if error.code == "maskinporten_token_error":
                raise MaskinportenTokenError("maskinporten_response_invalid", status=status) from None
            raise
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            raise MaskinportenTokenError("maskinporten_response_invalid", status=status) from None


__all__ = ["MaskinportenAccessToken", "MaskinportenClient", "MaskinportenConfiguration",
           "MaskinportenTokenError", "SYSTEM_REGISTER_WRITE_SCOPE", "SYSTEM_USER_CONTROL_READ_SCOPE",
           "SYSTEM_USER_CONTROL_WRITE_SCOPE", "SYSTEM_USER_TAX_SCOPE", "build_maskinporten_grant",
           "sign_maskinporten_grant"]
