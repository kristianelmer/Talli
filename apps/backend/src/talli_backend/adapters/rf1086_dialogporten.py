"""Bound RF feedback discovery; presentation URLs and free text never escape."""
from __future__ import annotations

import json
import re
from asyncio import timeout
from datetime import datetime

import httpx

from talli_backend.adapters.maskinporten import MaskinportenAccessToken, SYSTEM_USER_DIALOGPORTEN_SCOPE
from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086AuthorityError, Rf1086FeedbackDiscovery, Rf1086FeedbackTransmission, rf1086_adapter,
)

_BASE_URLS = {"test": "https://platform.tt02.altinn.no/dialogporten/api/v1/enduser/dialogs",
              "production": "https://platform.altinn.no/dialogporten/api/v1/enduser/dialogs"}
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_RESOURCE = "urn:altinn:resource:ske-innrapportering-aksjonaerregisteroppgave"
_MAX_BYTES = 2 * 1024 * 1024
_MAX_TRANSMISSIONS = 1000
_MAX_ATTACHMENTS = 1000
_TYPES = {"Information", "Acceptance", "Rejection", "Request", "Alert", "Decision", "Submission", "Correction"}


def _uuid(value: object) -> str:
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise Rf1086AuthorityError("RF1086_DIALOG_IDENTITY_INVALID", status=200)
    return value


def _complete(value: dict, field: str) -> None:
    excluded = value.get(field)
    if excluded is not None and (not isinstance(excluded, list) or excluded):
        raise Rf1086AuthorityError("RF1086_DIALOG_CONTENT_UNAVAILABLE", status=200)


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("invalid constant")


def _project(data: object, *, organization_number: str, dialog_id: str,
             forsendelse_id: str) -> tuple[Rf1086FeedbackTransmission, ...]:
    if (not isinstance(data, dict) or data.get("id") != dialog_id
            or data.get("party") != "urn:altinn:organization:identifier-no:" + organization_number
            or data.get("serviceResource") != _RESOURCE or data.get("deletedAt") is not None):
        raise Rf1086AuthorityError("RF1086_DIALOG_IDENTITY_INVALID", status=200)
    _complete(data, "excludedTransmissions")
    transmissions = data.get("transmissions")
    if not isinstance(transmissions, list) or len(transmissions) > _MAX_TRANSMISSIONS:
        raise Rf1086AuthorityError("RF1086_DIALOG_EXTENT_INVALID", status=200)
    identities = set()
    submission_found = False
    result = []
    attachment_count = 0
    for item in transmissions:
        if not isinstance(item, dict):
            raise Rf1086AuthorityError("RF1086_DIALOG_EXTENT_INVALID", status=200)
        kind = item.get("type")
        if not isinstance(kind, str) or kind not in _TYPES:
            raise Rf1086AuthorityError("RF1086_DIALOG_TYPE_INVALID", status=200)
        identifier = _uuid(item.get("id"))
        if identifier.lower() in identities:
            raise Rf1086AuthorityError("RF1086_DIALOG_EXTENT_INVALID", status=200)
        identities.add(identifier.lower())
        related = item.get("relatedTransmissionId")
        if related is not None:
            _uuid(related)
        if identifier == forsendelse_id:
            if (item.get("type") != "Submission" or item.get("isAuthorized") is not True
                    or item.get("deletedAt") is not None):
                raise Rf1086AuthorityError("RF1086_DIALOG_IDENTITY_INVALID", status=200)
            submission_found = True
        if item.get("relatedTransmissionId") != forsendelse_id:
            continue
        if item.get("isAuthorized") is not True or item.get("deletedAt") is not None:
            raise Rf1086AuthorityError("RF1086_DIALOG_CONTENT_UNAVAILABLE", status=200)
        _complete(item, "excludedAttachments")
        attachments = item.get("attachments")
        if not isinstance(attachments, list):
            raise Rf1086AuthorityError("RF1086_DIALOG_EXTENT_INVALID", status=200)
        document_ids = []
        for attachment in attachments:
            if (not isinstance(attachment, dict)
                    or ("isAuthorized" in attachment and attachment["isAuthorized"] is not True)):
                raise Rf1086AuthorityError("RF1086_DIALOG_CONTENT_UNAVAILABLE", status=200)
            document_ids.append(_uuid(attachment.get("id")))
        attachment_count += len(document_ids)
        if len({value.lower() for value in document_ids}) != len(document_ids) or attachment_count > _MAX_ATTACHMENTS:
            raise Rf1086AuthorityError("RF1086_DIALOG_EXTENT_INVALID", status=200)
        created = item.get("createdAt")
        try:
            if not isinstance(created, str) or len(created) > 40:
                raise ValueError()
            parsed = datetime.fromisoformat(created)
            if parsed.tzinfo is None:
                raise ValueError()
        except ValueError:
            raise Rf1086AuthorityError("RF1086_DIALOG_IDENTITY_INVALID", status=200) from None
        result.append(Rf1086FeedbackTransmission(dialog_id, identifier, forsendelse_id,
            parsed.isoformat(), tuple(document_ids), kind))
    if not submission_found:
        raise Rf1086AuthorityError("RF1086_DIALOG_IDENTITY_INVALID", status=200)
    return tuple(result)


@rf1086_adapter(Rf1086FeedbackDiscovery)
class Rf1086DialogportenAdapter:
    def __init__(self, token: MaskinportenAccessToken, *, environment: str = "production",
                 transport: httpx.AsyncBaseTransport | None = None):
        if (not isinstance(environment, str) or environment not in _BASE_URLS or not isinstance(token, MaskinportenAccessToken)
                or token.environment != environment or token.scope != SYSTEM_USER_DIALOGPORTEN_SCOPE
                or token.token_type != "Bearer"):
            raise ValueError("RF1086_DIALOG_TOKEN_INVALID")
        self._token, self._environment, self._transport = token, environment, transport

    async def read_feedback_transmissions(self, *, organization_number: str,
            dialog_id: str, forsendelse_id: str) -> tuple[Rf1086FeedbackTransmission, ...]:
        _uuid(dialog_id)
        _uuid(forsendelse_id)
        if not isinstance(organization_number, str) or not re.fullmatch(r"[0-9]{9}", organization_number):
            raise ValueError("RF1086_DIALOG_COMPANY_INVALID")
        token = self._token.access_token
        if (not isinstance(token, str) or not 1 <= len(token) <= 8192 or not token.isascii()
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in token)):
            raise ValueError("RF1086_DIALOG_TOKEN_INVALID")
        try:
            async with timeout(20), httpx.AsyncClient(transport=self._transport, timeout=20,
                    follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", _BASE_URLS[self._environment] + "/" + dialog_id,
                        headers={"authorization": "Bearer " + token, "accept": "application/json"}) as response:
                    if response.status_code != 200:
                        raise Rf1086AuthorityError("RF1086_DIALOG_HTTP_ERROR", status=response.status_code,
                            retryable=response.status_code in {401, 408, 425, 429} or response.status_code >= 500)
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise Rf1086AuthorityError("RF1086_DIALOG_CONTENT_TYPE", status=200)
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > _MAX_BYTES:
                            raise Rf1086AuthorityError("RF1086_DIALOG_TOO_LARGE", status=200)
                        raw.extend(chunk)
            try:
                data = json.loads(raw, object_pairs_hook=_unique_json, parse_constant=_invalid_constant)
            except (ValueError, UnicodeError, RecursionError):
                raise Rf1086AuthorityError("RF1086_DIALOG_JSON_INVALID", status=200) from None
            projected = _project(data, organization_number=organization_number,
                dialog_id=dialog_id, forsendelse_id=forsendelse_id)
            if token in repr(projected):
                raise Rf1086AuthorityError("RF1086_DIALOG_RESPONSE_SECRET", status=200)
            return projected
        except (httpx.HTTPError, TimeoutError):
            raise Rf1086AuthorityError("RF1086_DIALOG_NETWORK_ERROR", retryable=True) from None
