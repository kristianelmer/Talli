"""Fixed standard RF System User endpoints; no retries or credential-bearing results."""

from __future__ import annotations

import json
import re
from asyncio import timeout
from collections.abc import Mapping
from datetime import datetime
from urllib.parse import parse_qsl, urlsplit

import httpx

from talli_backend.adapters.maskinporten import (
    MaskinportenAccessToken, MaskinportenClient, MaskinportenTokenError,
    SYSTEM_USER_CONTROL_READ_SCOPE, SYSTEM_USER_CONTROL_WRITE_SCOPE, SYSTEM_USER_TAX_SCOPE,
    _unique_object,
)
from talli_backend.modules.authority_connections.public import (
    AuthorityFailureCode as Failure, AuthorityProviderError, QueriedSystemUser,
    SYSTEM_USER_CALLBACK_URL, SYSTEM_USER_RIGHT, SYSTEM_USER_SYSTEM_ID,
    SystemUserAuthorityProvider, SystemUserIdentity, SystemUserRequestObservation,
    SystemUserRequestStatus, system_user_authority_provider_adapter,
)


_BASE_URLS = {"tt02": "https://platform.tt02.altinn.no", "production": "https://platform.altinn.no"}
_CONFIRMATION_HOSTS = {
    "tt02": frozenset({"am.ui.at22.altinn.cloud", "authn.ui.tt02.altinn.no", "am.ui.tt02.altinn.no"}),
    "production": frozenset({"am.ui.altinn.no"}),
}
_CONFIRMATION_PATH = "/accessmanagement/ui/systemuser/request"
_REQUEST_BASE = "/authentication/api/v1/systemuser/request/vendor"
_QUERY_PATH = "/authentication/api/v1/systemuser/vendor/byquery"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_EXTERNAL_REF = re.compile(r"[A-Za-z0-9_-]{43}")
_MAX_RESPONSE_BYTES = 65_536
_RIGHTS = [{"resource": [{"id": "urn:altinn:resource", "value": SYSTEM_USER_RIGHT}]}]
_REQUEST_FIELDS = frozenset({"id", "externalRef", "systemId", "partyOrgNo", "rights", "status", "redirectUrl", "confirmUrl"})
_QUERY_FIELDS = frozenset({"id", "systemId", "reporteeOrgNo", "externalRef", "userType", "isDeleted"})
# Documented descriptive fields are type/bounds checked and discarded. They can
# never replace the mandatory identity/right fields or introduce agent rights.
_QUERY_ADDITIONS = frozenset({"integrationTitle", "productName", "created", "supplierName", "supplierOrgno"})
_STATUSES = {spelling: status for status, spellings in (
    (SystemUserRequestStatus.NEW, ("new", "New")),
    (SystemUserRequestStatus.ACCEPTED, ("accepted", "Accepted")),
    (SystemUserRequestStatus.REJECTED, ("rejected", "Rejected")),
    (SystemUserRequestStatus.DENIED, ("denied", "Denied")),
    (SystemUserRequestStatus.TIMEDOUT, ("timedout", "TimedOut")),
) for spelling in spellings}


def _fail(code: Failure = Failure.RESPONSE_CONTRACT_MISMATCH) -> None:
    raise AuthorityProviderError(code)


def _request_id(value: object) -> str:
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        _fail(Failure.INVALID_REQUEST_ID)
    return value


def _identity(identity: SystemUserIdentity) -> None:
    if not isinstance(identity, SystemUserIdentity):
        _fail()
    if not isinstance(identity.organization_number, str) or not re.fullmatch(r"[0-9]{9}", identity.organization_number):
        _fail(Failure.INVALID_ORGANIZATION_NUMBER)
    if not isinstance(identity.external_reference, str) or not _EXTERNAL_REF.fullmatch(identity.external_reference):
        _fail(Failure.INVALID_EXTERNAL_REFERENCE)


def _shape(value: object, fields: frozenset[str], additions: frozenset[str] = frozenset()) -> dict:
    if not isinstance(value, dict) or not fields <= value.keys() or not value.keys() <= fields | additions:
        _fail()
    for name in value.keys() & additions:
        content = value[name]
        if not isinstance(content, str) or len(content) > 2048 or any(ord(c) < 32 or ord(c) == 127 for c in content):
            _fail()
        if name == "supplierOrgno" and content != "930835978":
            _fail()
        if name == "created":
            try:
                created = datetime.fromisoformat(content)
                if created.tzinfo is None or created.utcoffset() is None:
                    _fail()
            except (ValueError, TypeError):
                _fail()
    return value


def _confirmation_url(value: object, environment: str, request_id: str) -> str | None:
    if value is None:
        return None
    if (not isinstance(value, str) or len(value) > 2048
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value):
        _fail(Failure.INVALID_CONFIRMATION_URL)
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.netloc not in _CONFIRMATION_HOSTS[environment]
                or parsed.path != _CONFIRMATION_PATH or parsed.fragment
                or parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True) != [("id", request_id)]):
            _fail(Failure.INVALID_CONFIRMATION_URL)
    except (ValueError, KeyError):
        _fail(Failure.INVALID_CONFIRMATION_URL)
    return value


def validate_system_user_response(value: object, identity: SystemUserIdentity, *, environment: str,
                                  provider_request_id: str | None = None) -> SystemUserRequestObservation:
    _identity(identity)
    if environment not in _BASE_URLS:
        _fail(Failure.INVALID_ENVIRONMENT)
    data = _shape(value, _REQUEST_FIELDS, frozenset({"created"}))
    if (not isinstance(data["id"], str) or not _UUID.fullmatch(data["id"])
            or (provider_request_id is not None and data["id"].lower() != provider_request_id.lower())
            or data["externalRef"] != identity.external_reference or data["systemId"] != SYSTEM_USER_SYSTEM_ID
            or data["partyOrgNo"] != identity.organization_number or data["rights"] != _RIGHTS
            or data["redirectUrl"] != SYSTEM_USER_CALLBACK_URL
            or not isinstance(data["status"], str) or data["status"] not in _STATUSES):
        _fail()
    status = _STATUSES[data["status"]]
    confirmation = _confirmation_url(data["confirmUrl"], environment, data["id"])
    if status is SystemUserRequestStatus.NEW and confirmation is None:
        _fail()
    return SystemUserRequestObservation(data["id"], identity.external_reference, identity.organization_number,
        SYSTEM_USER_SYSTEM_ID, SYSTEM_USER_RIGHT, SYSTEM_USER_CALLBACK_URL, status, confirmation)


def validate_queried_system_user(value: object, identity: SystemUserIdentity) -> QueriedSystemUser:
    _identity(identity)
    data = _shape(value, _QUERY_FIELDS, _QUERY_ADDITIONS)
    if (not isinstance(data["id"], str) or not _UUID.fullmatch(data["id"])
            or data["systemId"] != SYSTEM_USER_SYSTEM_ID or data["reporteeOrgNo"] != identity.organization_number
            or data["externalRef"] != identity.external_reference or data["userType"] != "standard"
            or data["isDeleted"] is not False):
        _fail()
    return QueriedSystemUser(data["id"], SYSTEM_USER_SYSTEM_ID, identity.organization_number,
                            identity.external_reference, "standard", False)


@system_user_authority_provider_adapter(SystemUserAuthorityProvider)
class AltinnSystemUserAdapter:
    def __init__(self, maskinporten: MaskinportenClient, *, environment: str = "production",
                 transport: httpx.AsyncBaseTransport | None = None, timeout_ms: int = 15_000):
        if (not isinstance(environment, str) or environment not in _BASE_URLS
                or maskinporten.environment != ("test" if environment == "tt02" else "production")):
            _fail(Failure.INVALID_ENVIRONMENT)
        if type(timeout_ms) is not int or not 1000 <= timeout_ms <= 120_000:
            _fail(Failure.INVALID_TIMEOUT)
        self._maskinporten = maskinporten
        self._environment = environment
        self._transport = transport
        self._timeout = timeout_ms / 1000

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> AltinnSystemUserAdapter:
        """Provider credentials remain unread until an authorized operation."""
        return cls(MaskinportenClient.from_environment(environment))

    async def _token(self, scope: str, identity: SystemUserIdentity | None = None) -> MaskinportenAccessToken:
        try:
            kwargs = {} if identity is None else {"system_user_org_number": identity.organization_number,
                                                 "system_user_external_ref": identity.external_reference}
            token = await self._maskinporten.request_token(scope, **kwargs)
        except MaskinportenTokenError as error:
            raise AuthorityProviderError(Failure(error.code), status=error.status) from None
        if not isinstance(token, MaskinportenAccessToken):
            _fail(Failure.MASKINPORTEN_RESPONSE_INVALID)
        if token.scope != scope or token.environment != self._maskinporten.environment:
            token.discard()
            _fail(Failure.MASKINPORTEN_RESPONSE_INVALID)
        value = token.access_token
        if (not isinstance(value, str) or not 1 <= len(value) <= 8192
                or not value.isascii()
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)):
            token.discard()
            _fail(Failure.INVALID_BEARER_TOKEN)
        return token

    async def _request(self, method: str, path: str, scope: str, *, body=None, params=None):
        token = await self._token(scope)
        try:
            async with timeout(self._timeout), httpx.AsyncClient(transport=self._transport,
                    timeout=self._timeout, follow_redirects=False, trust_env=False) as client:
                async with client.stream(method, _BASE_URLS[self._environment] + path,
                        headers={"accept": "application/json", "authorization": "Bearer " + token.access_token,
                                 "cache-control": "no-store"}, json=body, params=params) as response:
                    status = response.status_code
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > _MAX_RESPONSE_BYTES:
                            _fail(Failure.RESPONSE_TOO_LARGE)
                        raw.extend(chunk)
            parsed = None
            try:
                parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
            except (ValueError, UnicodeError, RecursionError):
                if 200 <= status < 300:
                    _fail()
            if not 200 <= status < 300:
                duplicate = isinstance(parsed, dict) and any(parsed.get(name) == "AUTH-00007" for name in ("code", "errorCode", "error"))
                raise AuthorityProviderError(
                    Failure.DUPLICATE_SYSTEM_USER_REQUEST if duplicate else Failure.AUTHORITY_HTTP_ERROR,
                    status=status, retryable=status in (408, 425, 429) or status >= 500,
                )
            if parsed is None:
                _fail()
            return parsed
        except (httpx.HTTPError, TimeoutError):
            raise AuthorityProviderError(Failure.NETWORK_ERROR) from None
        finally:
            token.discard()

    async def create_request(self, identity: SystemUserIdentity) -> SystemUserRequestObservation:
        _identity(identity)
        data = await self._request("POST", _REQUEST_BASE, SYSTEM_USER_CONTROL_WRITE_SCOPE, body={
            "externalRef": identity.external_reference, "systemId": SYSTEM_USER_SYSTEM_ID,
            "partyOrgNo": identity.organization_number, "rights": _RIGHTS, "redirectUrl": SYSTEM_USER_CALLBACK_URL,
        })
        return validate_system_user_response(data, identity, environment=self._environment)

    async def get_request(self, identity: SystemUserIdentity, provider_request_id: str) -> SystemUserRequestObservation:
        _identity(identity)
        request_id = _request_id(provider_request_id)
        data = await self._request("GET", _REQUEST_BASE + "/" + request_id, SYSTEM_USER_CONTROL_READ_SCOPE)
        return validate_system_user_response(data, identity, environment=self._environment, provider_request_id=request_id)

    async def find_request(self, identity: SystemUserIdentity) -> SystemUserRequestObservation:
        _identity(identity)
        path = f"{_REQUEST_BASE}/byexternalref/{SYSTEM_USER_SYSTEM_ID}/{identity.organization_number}/{identity.external_reference}"
        data = await self._request("GET", path, SYSTEM_USER_CONTROL_READ_SCOPE)
        return validate_system_user_response(data, identity, environment=self._environment)

    async def query_system_user(self, identity: SystemUserIdentity) -> QueriedSystemUser:
        _identity(identity)
        data = await self._request("GET", _QUERY_PATH, SYSTEM_USER_CONTROL_WRITE_SCOPE, params={
            "system-id": SYSTEM_USER_SYSTEM_ID, "orgno": identity.organization_number,
            "external-ref": identity.external_reference,
        })
        return validate_queried_system_user(data, identity)

    async def verify_delegation(self, identity: SystemUserIdentity) -> None:
        _identity(identity)
        token = await self._token(SYSTEM_USER_TAX_SCOPE, identity)
        token.discard()


__all__ = ["AltinnSystemUserAdapter", "validate_queried_system_user", "validate_system_user_response"]
