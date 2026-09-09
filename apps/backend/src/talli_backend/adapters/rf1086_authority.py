"""The five frozen RF HTTP operations; credentials never cross the web boundary."""

from __future__ import annotations

import hashlib
import json
import math
import re
from asyncio import timeout

import httpx

from talli_backend.adapters.maskinporten import MaskinportenAccessToken, SYSTEM_USER_TAX_SCOPE
from talli_backend.compatibility.rf1086_authority_workflow import (
    _js_utf8_bytes,
    Rf1086AuthorityCall, Rf1086AuthorityDocument, Rf1086AuthorityError, Rf1086Confirmation,
    Rf1086DocumentPage, Rf1086DocumentReference, Rf1086MainResponse, Rf1086PostResponse,
)


_BASE_URLS = {"test": "https://api-test.sits.no/api/aksjonaerregister/v1",
              "production": "https://api.skatteetaten.no/api/aksjonaerregister/v1"}
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_MAX_JSON_BYTES = 64 * 1024
_MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
_DOCUMENT_TYPES = ("application/xml", "text/xml", "application/pdf", "text/plain", "application/octet-stream")


def _year(value: int) -> int:
    if type(value) is not int or not 2000 <= value <= 2100:
        raise ValueError("RF1086_INCOME_YEAR_INVALID")
    return value


def _uuid(value: str) -> str:
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise ValueError("RF1086_UUID_INVALID")
    return value


def _xml(value: str) -> str:
    if not isinstance(value, str) or not re.sub(r"^[\s\ufeff]+", "", value).startswith("<"):
        raise ValueError("RF1086_XML_REQUIRED")
    return value


def _safe_string(value: object, fallback: str = "") -> str:
    if not isinstance(value, str):
        return fallback
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", value)).strip()[:500]


def _safe_object(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _invalid_json_constant(_value: str):
    raise ValueError("RF1086_JSON_INVALID")


def _number(value: object) -> int | float:
    # JSON pagination historically uses JavaScript Number coercion. Preserve
    # that projection; document_shape_valid separately requires finite integers.
    if isinstance(value, list):
        value = "" if not value else str(value[0]) if len(value) == 1 else "invalid"
    if value is None:
        return 0
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return 0
        if re.fullmatch(r"0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+", value):
            return int(value, 0)
    try:
        number = float(value)
        return int(number) if math.isfinite(number) and number.is_integer() else number
    except (ValueError, TypeError, OverflowError):
        return float("nan")


def _integer(value: int | float) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value == math.floor(value)


class Rf1086ReadOnlyAuthorityAdapter:
    """Recovery receives this two-method interface, which has no filing POSTs."""

    def __init__(self, token: MaskinportenAccessToken, *, environment: str = "production",
                 transport: httpx.AsyncBaseTransport | None = None, timeout_ms: int = 20_000):
        if not isinstance(environment, str) or environment not in _BASE_URLS:
            raise ValueError("RF1086_ENVIRONMENT_INVALID")
        if type(timeout_ms) is not int or not 1000 <= timeout_ms <= 120_000:
            raise ValueError("RF1086_TIMEOUT_INVALID")
        if (not isinstance(token, MaskinportenAccessToken) or token.environment != environment
                or token.scope != SYSTEM_USER_TAX_SCOPE or token.token_type != "Bearer"):
            raise ValueError("RF1086_TOKEN_INVALID")
        self._token = token
        self._environment = environment
        self._transport = transport
        self._timeout = timeout_ms / 1000
        self._headers()

    def _headers(self) -> dict[str, str]:
        value = self._token.access_token
        if (not isinstance(value, str) or not 1 <= len(value) <= 8192 or not value.isascii()
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("RF1086_TOKEN_INVALID")
        return {"authorization": "Bearer " + value}

    def _http_error(self, status: int, parsed: object) -> Rf1086AuthorityError:
        data = _safe_object(parsed)
        secret = self._token.access_token
        def safe_code(value, fallback=""):
            text = _safe_string(value, fallback)
            return text if re.fullmatch(r"[A-Z0-9_]{1,100}", text) and secret not in text else fallback
        code = safe_code(data.get("kode"), f"RF1086_HTTP_{status}")
        correlation = _safe_string(data.get("korrelasjonsid"))
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", correlation) or secret in correlation:
            correlation = None
        specifications = data.get("spesifisering", [])
        codes = tuple(filter(None, (safe_code(_safe_object(value).get("kode")) for value in specifications[:5]))) if isinstance(specifications, list) else ()
        return Rf1086AuthorityError(code, status=status, correlation_id=correlation,
            specification_codes=codes, retryable=status in {401, 408, 425, 429} or status >= 500 or code == "GLD_004")

    async def _bounded(self, response: httpx.Response, maximum: int, code: str) -> bytes:
        stated = _number(response.headers.get("content-length"))
        if math.isfinite(stated) and stated > maximum:
            raise Rf1086AuthorityError(code, status=response.status_code)
        raw = bytearray()
        async for chunk in response.aiter_bytes():
            if len(raw) + len(chunk) > maximum:
                raise Rf1086AuthorityError(code, status=response.status_code)
            raw.extend(chunk)
        return bytes(raw)

    async def _json_response(self, response: httpx.Response) -> object:
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type and not (content_type == "application/json" or
                                (content_type.startswith("application/") and content_type.endswith("+json"))):
            raise Rf1086AuthorityError("RF1086_JSON_CONTENT_TYPE", status=response.status_code)
        raw = await self._bounded(response, _MAX_JSON_BYTES, "RF1086_JSON_TOO_LARGE")
        if not raw:
            return {}
        if not content_type:
            raise Rf1086AuthorityError("RF1086_JSON_CONTENT_TYPE", status=response.status_code)
        try:
            # TextDecoder in the original client removes a leading UTF-8 BOM.
            return json.loads(raw.decode("utf-8-sig"), parse_constant=_invalid_json_constant)
        except (ValueError, UnicodeError, RecursionError):
            if not response.is_success:
                return {}
            raise Rf1086AuthorityError("RF1086_JSON_INVALID", status=response.status_code) from None

    async def _json_request(self, method: str, path: str, *, body: str | None = None,
                             idempotency_key: str | None = None, xml: bool = False) -> tuple[dict, Rf1086AuthorityCall]:
        headers = self._headers() | {"accept": "application/json"}
        if xml:
            headers["content-type"] = "application/xml"
        if idempotency_key is not None:
            headers["idempotencyKey"] = _uuid(idempotency_key)
        endpoint = _BASE_URLS[self._environment] + path
        try:
            async with timeout(self._timeout), httpx.AsyncClient(transport=self._transport,
                    timeout=self._timeout, follow_redirects=False, trust_env=False) as client:
                async with client.stream(method, endpoint, headers=headers,
                        content=_js_utf8_bytes(body) if body is not None else None) as response:
                    # fetch redirect:error classified redirects as an unknown
                    # network outcome; preserve that stop for mutation recovery.
                    if response.is_redirect:
                        raise Rf1086AuthorityError("RF1086_NETWORK_ERROR", retryable=True)
                    parsed = await self._json_response(response)
                    if not response.is_success:
                        raise self._http_error(response.status_code, parsed)
                    # Successful references also reach evidence and summaries.
                    # Never retain credentials reflected by a provider response.
                    serialized = json.dumps(parsed, ensure_ascii=False)
                    if (self._token.access_token in serialized
                            or re.search(r"-----BEGIN (?:RSA )?PRIVATE KEY-----", serialized)
                            or re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", serialized)
                            or re.search(r"(?i)Bearer\s+\S+", serialized)):
                        raise Rf1086AuthorityError("RF1086_RESPONSE_SECRET", status=response.status_code)
            return _safe_object(parsed), Rf1086AuthorityCall(method, endpoint,
                hashlib.sha256(_js_utf8_bytes(body or "")).hexdigest(), idempotency_key)
        except (httpx.HTTPError, TimeoutError):
            raise Rf1086AuthorityError("RF1086_NETWORK_ERROR", retryable=True) from None

    async def list_documents(self, *, income_year: int, reference_id: str,
                             page: int = 0, size: int = 50) -> Rf1086DocumentPage:
        year, reference = _year(income_year), _uuid(reference_id)
        if type(page) is not int or page < 0 or type(size) is not int or not 1 <= size <= 50:
            raise ValueError("RF1086_PAGINATION_INVALID")
        data, call = await self._json_request("GET", f"/{year}/forsendelser/{reference}/dokumenter?page={page}&size={size}")
        raw_documents = data.get("dokumenter")
        documents: list[str | Rf1086DocumentReference] = []
        valid = isinstance(raw_documents, list)
        if isinstance(raw_documents, list):
            for value in raw_documents:
                if isinstance(value, str) and value.strip():
                    documents.append(value)
                elif (isinstance(value, dict) and len(value) == 1
                        and next(iter(value)) in {"dokumentId", "documentId"}
                        and isinstance(next(iter(value.values())), str)
                        and _UUID.fullmatch(next(iter(value.values())))):
                    documents.append(Rf1086DocumentReference(next(iter(value.values()))))
                else:
                    valid = False
        def number(name, default):
            return _number(default if data.get(name) is None else data[name])
        total_items = number("totalItems", len(documents))
        total_pages = number("totalPages", 1 if documents else 0)
        current_page = number("currentPage", page)
        valid = (valid and _integer(total_items) and total_items >= len(documents)
            and _integer(total_pages) and total_pages >= 0 and _integer(current_page) and current_page >= 0)
        return Rf1086DocumentPage(total_items, total_pages, current_page, tuple(documents), valid, call)

    async def get_document(self, *, income_year: int, forsendelse_id: str,
                           document_id: str) -> Rf1086AuthorityDocument:
        year, transmission, document = _year(income_year), _uuid(forsendelse_id), _uuid(document_id)
        headers = self._headers() | {"accept": ", ".join(_DOCUMENT_TYPES)}
        try:
            async with timeout(self._timeout), httpx.AsyncClient(transport=self._transport,
                    timeout=self._timeout, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", f"{_BASE_URLS[self._environment]}/{year}/forsendelser/{transmission}/dokumenter/{document}",
                                         headers=headers) as response:
                    if response.is_redirect:
                        raise Rf1086AuthorityError("RF1086_NETWORK_ERROR", retryable=True)
                    if not response.is_success:
                        raise self._http_error(response.status_code, await self._json_response(response))
                    raw = await self._bounded(response, _MAX_DOCUMENT_BYTES, "RF1086_DOCUMENT_TOO_LARGE")
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type not in _DOCUMENT_TYPES:
                        raise Rf1086AuthorityError("RF1086_DOCUMENT_CONTENT_TYPE", status=response.status_code)
                    if not raw:
                        raise Rf1086AuthorityError("RF1086_DOCUMENT_EMPTY", status=response.status_code)
            return Rf1086AuthorityDocument(document, content_type, raw)
        except (httpx.HTTPError, TimeoutError):
            raise Rf1086AuthorityError("RF1086_NETWORK_ERROR", retryable=True) from None


class Rf1086AuthorityAdapter(Rf1086ReadOnlyAuthorityAdapter):
    async def post_hovedskjema(self, *, income_year: int, xml: str, idempotency_key: str) -> Rf1086MainResponse:
        data, call = await self._json_request("POST", f"/{_year(income_year)}/1086H",
            body=_xml(xml), idempotency_key=_uuid(idempotency_key), xml=True)
        return Rf1086MainResponse(_uuid(_safe_string(data.get("hovedskjemaId") or data.get("hovedskjemaid"))), call)

    async def post_underskjema(self, *, income_year: int, hovedskjema_id: str,
                              xml: str, idempotency_key: str) -> Rf1086PostResponse:
        _, call = await self._json_request("POST", f"/{_year(income_year)}/{_uuid(hovedskjema_id)}/1086U",
            body=_xml(xml), idempotency_key=_uuid(idempotency_key), xml=True)
        return Rf1086PostResponse(call)

    async def confirm(self, *, income_year: int, hovedskjema_id: str,
                       underskjema_count: int, idempotency_key: str) -> Rf1086Confirmation:
        if type(underskjema_count) is not int or underskjema_count < 1:
            raise ValueError("RF1086_UNDERSKJEMA_COUNT_INVALID")
        data, call = await self._json_request("POST",
            f"/{_year(income_year)}/{_uuid(hovedskjema_id)}/bekreft?antall_underskjema={underskjema_count}",
            idempotency_key=_uuid(idempotency_key))
        return Rf1086Confirmation(_safe_string(data.get("oppgavegiversLeveranseReferanse")),
                                  _uuid(_safe_string(data.get("dialogId"))),
                                  _uuid(_safe_string(data.get("forsendelseId"))), call)


__all__ = ["Rf1086AuthorityAdapter", "Rf1086ReadOnlyAuthorityAdapter"]
