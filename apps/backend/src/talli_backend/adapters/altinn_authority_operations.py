"""The two fixed, disabled-by-default production System Register operations."""

from __future__ import annotations

import json
import os
import re
from asyncio import timeout
from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from talli_backend.adapters.maskinporten import (
    MaskinportenClient, MaskinportenConfiguration, SYSTEM_REGISTER_WRITE_SCOPE,
)
from talli_backend.modules.authority_connections.public import (
    AuthorityOperationCode as Code, AuthorityOperationCompletion, AuthorityOperationError,
    AuthorityOperationIntent, AuthorityOperationKind as Kind, AuthorityOperationStatus as Status,
    AuthorityOperationsProvider, SYSTEM_USER_SYSTEM_ID, authority_operations_provider_adapter,
)


_BASE = "https://platform.altinn.no/authentication/api/v1/systemregister/vendor"
_SYSTEM = f"{_BASE}/{SYSTEM_USER_SYSTEM_ID}"
_MAX_RESPONSE_BYTES = 65_536
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.I)
_PEM = re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----[\s\S]+-----END (?:RSA )?PRIVATE KEY-----\s*")


def _configuration(environment: Mapping[str, str]) -> MaskinportenConfiguration:
    values = []
    for key, code in (("CLIENT_ID", Code.AUTHORITY_CLIENT_ID_INVALID), ("KEY_ID", Code.AUTHORITY_KEY_ID_INVALID)):
        value = environment.get(f"TALLI_PROD_MASKINPORTEN_{key}", "")
        if not isinstance(value, str) or not _UUID.fullmatch(value):
            raise AuthorityOperationError(code)
        values.append(value)
    pem = environment.get("TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM", "")
    if (not isinstance(pem, str) or len(pem) > 16_384 or not _PEM.fullmatch(pem)
            or re.search(r"test|tt02", pem, re.I)):
        raise AuthorityOperationError(Code.AUTHORITY_PRIVATE_KEY_INVALID)
    return MaskinportenConfiguration("production", values[0], values[1], pem)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _registration_matches(actual: dict[str, object], expected: dict[str, object]) -> bool:
    # Preserve the existing registration projection (including Altinn's casing
    # alias and optional vendor authority); callback replacement is stricter.
    vendor = actual.get("vendor")
    vendor = vendor if isinstance(vendor, dict) else {}
    projected = {key: actual.get(key) for key in (
        "id", "name", "description", "rights", "accessPackages", "clientId", "isVisible",
    )}
    projected["vendor"] = {
        "authority": vendor.get("authority") if vendor.get("authority") is not None else "iso6523-actorid-upis",
        "ID": vendor.get("ID"),
    }
    projected["allowedredirecturls"] = (
        actual.get("allowedredirecturls") if actual.get("allowedredirecturls") is not None
        else actual.get("allowedRedirectUrls")
    )
    return _canonical(projected) == _canonical(expected)


def _callback_projection(actual: dict[str, object]) -> dict[str, object] | None:
    camel = "allowedRedirectUrls" in actual
    legacy = "allowedredirecturls" in actual
    callback_key = "allowedRedirectUrls" if camel else "allowedredirecturls"
    if camel == legacy or set(actual) != {
        "id", "vendor", "name", "description", "rights", "accessPackages", "clientId",
        callback_key, "isVisible", "isDeleted",
    }:
        return None
    vendor = actual["vendor"]
    if (not isinstance(vendor, dict) or set(vendor) not in ({"ID"}, {"authority", "ID"})
            or not isinstance(vendor["ID"], str)
            or ("authority" in vendor and not isinstance(vendor["authority"], str))):
        return None
    for key in ("name", "description"):
        value = actual[key]
        if not isinstance(value, dict) or set(value) != {"nb", "nn", "en"} or any(
            not isinstance(item, str) for item in value.values()
        ):
            return None
    rights = actual["rights"]
    if not isinstance(rights, list):
        return None
    for right in rights:
        if not isinstance(right, dict) or set(right) != {"resource"} or not isinstance(right["resource"], list):
            return None
        for resource in right["resource"]:
            if (not isinstance(resource, dict) or set(resource) != {"id", "value"}
                    or any(not isinstance(value, str) for value in resource.values())):
                return None
    if (actual["accessPackages"] != [] or not isinstance(actual["accessPackages"], list)
            or not isinstance(actual["clientId"], list) or any(not isinstance(value, str) for value in actual["clientId"])
            or not isinstance(actual[callback_key], list) or any(not isinstance(value, str) for value in actual[callback_key])
            or not isinstance(actual["id"], str) or type(actual["isVisible"]) is not bool
            or type(actual["isDeleted"]) is not bool):
        return None
    result = dict(actual)
    result["vendor"] = {"authority": vendor.get("authority", "iso6523-actorid-upis"), "ID": vendor["ID"]}
    result["allowedRedirectUrls"] = result.pop(callback_key)
    return result


def _callback_matches(actual: dict[str, object], expected: dict[str, object]) -> bool:
    projected = _callback_projection(actual)
    return projected is not None and _canonical(projected) == _canonical(expected)


@dataclass(frozen=True, slots=True)
class _Response:
    status: int
    content_type: str
    body: bytes
    callback: bool = False


def _unique_object(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _parse(response: _Response, *, creation: bool = False) -> object:
    try:
        if "application/json" not in response.content_type.lower():
            raise ValueError("missing JSON media type")
        # Registration used Response.text() (BOM stripping); the callback
        # used Buffer.toString() (BOM retained). Both replace malformed UTF-8.
        decoded = response.body.decode("utf-8" if response.callback else "utf-8-sig", errors="replace")
        if len(decoded.encode("utf-8")) > _MAX_RESPONSE_BYTES:
            raise ValueError("decoded response too large")
        value = json.loads(decoded, object_pairs_hook=_unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON constant")))
        if creation:
            if not isinstance(value, str) or not _UUID.fullmatch(value):
                raise ValueError("invalid creation UUID")
        elif not isinstance(value, dict):
            raise ValueError("invalid authority object")
        return value
    except Exception:
        raise AuthorityOperationError(Code.AUTHORITY_RESPONSE_INVALID, response.status) from None


async def _request(
    client: httpx.AsyncClient, method: str, url: str, headers: dict[str, str], *,
    body: bytes | None = None, callback: bool = False,
) -> _Response:
    try:
        async with timeout(15):
            async with client.stream(method, url, headers=headers, content=body) as response:
                # Fetch redirect:'error' in the existing transport never follows
                # or exposes a redirect as a normal provider status.
                if 300 <= response.status_code < 400:
                    raise AuthorityOperationError(Code.AUTHORITY_NETWORK_ERROR)
                if not callback and response.status_code not in (200, 201):
                    return _Response(response.status_code, "", b"")
                try:
                    declared_length = float(response.headers.get("content-length", "0"))
                except ValueError:
                    declared_length = 0
                if declared_length > _MAX_RESPONSE_BYTES:
                    raise AuthorityOperationError(Code.AUTHORITY_RESPONSE_INVALID, response.status_code)
                chunks = bytearray()
                try:
                    async for chunk in response.aiter_bytes():
                        if len(chunks) + len(chunk) > _MAX_RESPONSE_BYTES:
                            raise ValueError("response too large")
                        chunks.extend(chunk)
                except Exception:
                    raise AuthorityOperationError(Code.AUTHORITY_RESPONSE_INVALID, response.status_code) from None
                # The original capped callback reader applied this bound
                # before branching on status, including non-success bodies.
                if callback and len(chunks.decode("utf-8", errors="replace").encode("utf-8")) > _MAX_RESPONSE_BYTES:
                    raise AuthorityOperationError(Code.AUTHORITY_RESPONSE_INVALID, response.status_code)
                return _Response(response.status_code, response.headers.get("content-type", ""), bytes(chunks), callback)
    except AuthorityOperationError:
        raise
    except Exception:
        raise AuthorityOperationError(Code.AUTHORITY_NETWORK_ERROR) from None


@authority_operations_provider_adapter(AuthorityOperationsProvider)
class AltinnAuthorityOperationsAdapter:
    """Lazy configuration, fixed production endpoint, and no caller registry JSON."""

    def __init__(
        self, configuration: MaskinportenConfiguration | None = None, *, enabled: bool = False,
        maskinporten: MaskinportenClient | None = None, transport: httpx.AsyncBaseTransport | None = None,
        configuration_environment: Mapping[str, str] | None = None,
    ) -> None:
        self._configuration = configuration
        self._enabled = enabled
        self._maskinporten = maskinporten
        self._injected_maskinporten = maskinporten is not None
        self._transport = transport
        self._configuration_environment = configuration_environment
        self._prepared: dict[Kind, tuple[AuthorityOperationIntent, MaskinportenClient]] = {}

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> AltinnAuthorityOperationsAdapter:
        return cls(configuration_environment=os.environ if environment is None else environment)

    def prepare(self, operation: Kind) -> AuthorityOperationIntent:
        environment = self._configuration_environment
        enabled = self._enabled if environment is None else environment.get("TALLI_AUTHORITY_OPS_ENABLED") == "true"
        if enabled is not True:
            raise AuthorityOperationError(Code.AUTHORITY_OPS_DISABLED)
        try:
            configuration = _configuration(environment) if environment is not None else self._configuration
            if configuration is None or configuration.environment != "production":
                raise AuthorityOperationError(Code.AUTHORITY_ENVIRONMENT_INVALID)
            # Injected production configuration must satisfy the same gate as
            # environment composition; no test credentials in the operation.
            configuration = _configuration({
                "TALLI_PROD_MASKINPORTEN_CLIENT_ID": configuration.client_id,
                "TALLI_PROD_MASKINPORTEN_KEY_ID": configuration.key_id,
                "TALLI_PROD_MASKINPORTEN_PRIVATE_KEY_PEM": configuration.private_key_pem,
            })
            intent = AuthorityOperationIntent(operation, configuration.client_id)
            if not self._injected_maskinporten:
                self._maskinporten = MaskinportenClient(configuration, transport=self._transport)
            self._configuration = configuration
            self._prepared[operation] = (intent, self._maskinporten)
            return intent
        except AuthorityOperationError:
            raise
        except Exception:
            raise AuthorityOperationError(Code.AUTHORITY_ENVIRONMENT_INVALID) from None

    async def execute(self, intent: AuthorityOperationIntent) -> AuthorityOperationCompletion:
        prepared = self._prepared.get(intent.operation)
        if prepared is None or prepared[0] != intent:
            raise AuthorityOperationError(Code.AUTHORITY_OPERATION_INVALID)
        # Capture the credential client before awaiting. The composition owns
        # one adapter shared by requests, so the other fixed operation must not
        # replace this operation's prepared configuration while its audit commits.
        maskinporten = prepared[1]
        token = None
        try:
            try:
                token = await maskinporten.request_token(SYSTEM_REGISTER_WRITE_SCOPE)
                if (token.environment != "production" or token.scope != SYSTEM_REGISTER_WRITE_SCOPE
                        or token.token_type != "Bearer" or not isinstance(token.access_token, str)
                        or not 1 <= len(token.access_token) <= 8192
                        or any(ord(char) < 33 or ord(char) > 126 for char in token.access_token)):
                    raise ValueError("invalid authority token")
            except Exception:
                raise AuthorityOperationError(Code.AUTHORITY_TOKEN_ERROR) from None
            headers = {"authorization": f"Bearer {token.access_token}", "accept": "application/json"}
            async with httpx.AsyncClient(transport=self._transport, timeout=15, follow_redirects=False, trust_env=False) as client:
                if intent.operation is Kind.REGISTER_RF1086_SYSTEM:
                    return await self._register(client, intent, headers)
                return await self._callback(client, intent, headers)
        finally:
            if token is not None:
                token.discard()

    async def _register(
        self, client: httpx.AsyncClient, intent: AuthorityOperationIntent, headers: dict[str, str],
    ) -> AuthorityOperationCompletion:
        expected = json.loads(intent.request_body)
        current = await _request(client, "GET", _SYSTEM, headers)
        if current.status == 200:
            matches = _registration_matches(_parse(current), expected)
            return AuthorityOperationCompletion(Status.SUCCEEDED if matches else Status.CONFLICT,
                Code.ALREADY_VERIFIED if matches else Code.DEFINITION_CONFLICT, current.status)
        if current.status != 404:
            raise AuthorityOperationError(Code.AUTHORITY_HTTP_ERROR, current.status)
        created = await _request(client, "POST", _BASE, {**headers, "content-type": "application/json"}, body=intent.request_body)
        if created.status not in (200, 201):
            raise AuthorityOperationError(Code.AUTHORITY_HTTP_ERROR, created.status)
        _parse(created, creation=True)
        verified = await _request(client, "GET", _SYSTEM, headers)
        if verified.status != 200:
            raise AuthorityOperationError(Code.AUTHORITY_HTTP_ERROR, verified.status)
        matches = _registration_matches(_parse(verified), expected)
        return AuthorityOperationCompletion(Status.SUCCEEDED if matches else Status.CONFLICT,
            Code.CREATED_AND_VERIFIED if matches else Code.DEFINITION_CONFLICT, verified.status)

    async def _callback(
        self, client: httpx.AsyncClient, intent: AuthorityOperationIntent, headers: dict[str, str],
    ) -> AuthorityOperationCompletion:
        expected = json.loads(intent.request_body)
        empty = {**expected, "allowedRedirectUrls": []}
        current = await _request(client, "GET", _SYSTEM, headers, callback=True)
        if current.status == 404:
            return AuthorityOperationCompletion(Status.CONFLICT, Code.DEFINITION_CONFLICT, current.status)
        if current.status != 200:
            raise AuthorityOperationError(Code.AUTHORITY_HTTP_ERROR, current.status)
        observed = _parse(current)
        if _callback_matches(observed, expected):
            return AuthorityOperationCompletion(Status.SUCCEEDED, Code.CALLBACK_ALREADY_VERIFIED, current.status)
        if not _callback_matches(observed, empty):
            return AuthorityOperationCompletion(Status.CONFLICT, Code.DEFINITION_CONFLICT, current.status)
        update_failure = None
        try:
            updated = await _request(client, "PUT", _SYSTEM, {**headers, "content-type": "application/json"},
                                     body=intent.request_body, callback=True)
            if updated.status not in (200, 204):
                raise AuthorityOperationError(Code.AUTHORITY_HTTP_ERROR, updated.status)
            if updated.status == 200:
                _parse(updated)
        except AuthorityOperationError as error:
            update_failure = error
        try:
            verified = await _request(client, "GET", _SYSTEM, headers, callback=True)
            if verified.status != 200:
                raise AuthorityOperationError(Code.AUTHORITY_HTTP_ERROR, verified.status)
            observed = _parse(verified)
        except AuthorityOperationError as error:
            raise AuthorityOperationError(Code.AUTHORITY_VERIFICATION_ERROR, error.authority_http_status) from None
        if _callback_matches(observed, expected):
            return AuthorityOperationCompletion(Status.SUCCEEDED, Code.CALLBACK_UPDATED_AND_VERIFIED, verified.status)
        if _callback_matches(observed, empty) and update_failure is not None:
            raise update_failure
        return AuthorityOperationCompletion(Status.CONFLICT, Code.DEFINITION_CONFLICT, verified.status)
