"""RF production intent, immutable payload identity and journal execution.

The preserved journal commits intent before provider I/O, reuses stored keys,
and requires explicit recovery after an ambiguous mutation.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import TypeVar
from uuid import uuid4

from .public import (
    FailureClassification, JournaledRf1086ProductionInput, JournaledRf1086ProductionResult,
    ProductionOperation, ProductionOperationFailure, ProductionOperationJournal,
    Rf1086AuthorityError, Rf1086BlockedProductionOperationError, Rf1086MutationAuthority,
    Rf1086Preview, Rf1086ProductionError, Rf1086UnknownProductionOutcomeError,
)

Token = TypeVar("Token")
Submission = TypeVar("Submission")

_JS_TRIM = "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


def resume_production_operation(latest: ProductionOperation, *, is_mutation: bool) -> ProductionOperation:
    """Exact latest-event normalization from createRf1086DatabaseJournal."""
    retryable = latest.state == "failed" and latest.failure_classification == "retryable"
    exhausted = retryable and latest.attempt >= 20
    state = latest.state if latest.state in {"succeeded", "failed"} or not is_mutation else "unknown"
    return replace(latest, state=state, attempt=latest.attempt + 1 if retryable and not exhausted else latest.attempt,
                   failure_classification="blocked" if exhausted else latest.failure_classification)


async def execute_rf1086_production_release(
    *, acquire_delegated_token: Callable[[], Awaitable[Token]],
    begin_production_filing: Callable[[], Awaitable[Submission]],
    execute_external_submission: Callable[[Token, Submission], Awaitable[None]],
    discard_token: Callable[[Token], None],
) -> Submission:
    token = await acquire_delegated_token()
    try:
        submission = await begin_production_filing()
        await execute_external_submission(token, submission)
        return submission
    finally:
        discard_token(token)


def _js_utf8_bytes(value: str) -> bytes:
    # TextEncoder/Buffer UTF-8 combines valid UTF-16 pairs and replaces each
    # unpaired surrogate with U+FFFD, rather than dropping an archive artifact.
    return value.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le", errors="replace").encode("utf-8")


def _sha256(value: str | bytes) -> str:
    return hashlib.sha256(_js_utf8_bytes(value) if isinstance(value, str) else value).hexdigest()


def _reference(value: str | None) -> str:
    if not value:
        raise ValueError("RF1086_JOURNAL_REFERENCE_MISSING")
    return value


def _js_trim(value: str) -> str:
    return value.strip(_JS_TRIM)


def _js_utf16_key(value: str) -> bytes:
    return value.encode("utf-16-be", errors="surrogatepass")


def _js_object(value):
    # JSON.stringify visits array-index properties first (0..2**32-2),
    # followed by ordinary string properties in the object's insertion order.
    if isinstance(value, Mapping):
        indices = sorted((key for key in value if isinstance(key, str)
            and re.fullmatch(r"0|[1-9][0-9]{0,9}", key) and int(key) < 2**32 - 1), key=int)
        ordered = indices + [key for key in value if key not in indices]
        return {key: _js_object(value[key]) for key in ordered}
    if isinstance(value, (list, tuple)):
        return [_js_object(item) for item in value]
    return value


def _json(value: object) -> str:
    serialized = json.dumps(_js_object(value), separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    # Well-formed JSON.stringify escapes lone UTF-16 surrogates, while a valid
    # surrogate pair is the same scalar value as an ordinary astral character.
    serialized = serialized.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le", errors="surrogatepass")
    return "".join(f"\\u{ord(char):04x}" if 0xd800 <= ord(char) <= 0xdfff else char for char in serialized)


def _failure(error: Exception) -> FailureClassification:
    if isinstance(error, Rf1086AuthorityError):
        return "unknown" if error.status is None else "retryable" if error.retryable else "blocked"
    return "blocked"


async def _mutation(journal: ProductionOperationJournal, submission_id: str, name: str, body_hash: str,
                    execute: Callable[[str], Awaitable[str]]) -> str:
    operation = await journal.prepare(submission_id=submission_id, name=name,
                                      body_hash=body_hash, idempotency_key=str(uuid4()))
    if operation.name != name or operation.body_hash != body_hash:
        raise Rf1086BlockedProductionOperationError(name)
    if operation.state == "succeeded":
        return _reference(operation.authority_reference)
    if operation.state == "unknown":
        raise Rf1086UnknownProductionOutcomeError(name)
    if operation.attempt > 20 or (operation.state == "failed" and operation.failure_classification == "blocked"):
        raise Rf1086BlockedProductionOperationError(name)
    if not operation.idempotency_key:
        raise ValueError("RF1086_JOURNAL_KEY_MISSING")
    try:
        reference = await execute(operation.idempotency_key)
        await journal.succeed(operation.id, reference)
        return reference
    except Exception as error:
        classification = _failure(error)
        await journal.fail(operation.id, ProductionOperationFailure(classification,
            error.code if isinstance(error, Rf1086AuthorityError) else "RF1086_OPERATION_ERROR",
            error.correlation_id if isinstance(error, Rf1086AuthorityError) else None))
        if classification == "unknown":
            raise Rf1086UnknownProductionOutcomeError(name) from None
        raise


async def _read_operation(journal: ProductionOperationJournal, submission_id: str, name: str,
                          execute: Callable[[], Awaitable[str]]) -> str:
    operation = await journal.prepare(submission_id=submission_id, name=name, body_hash=None, idempotency_key=None)
    if operation.state == "succeeded":
        return _reference(operation.authority_reference)
    try:
        reference = await execute()
        await journal.succeed(operation.id, reference)
        return reference
    except Exception as error:
        await journal.fail(operation.id, ProductionOperationFailure(
            "retryable" if isinstance(error, Rf1086AuthorityError) and error.retryable else "blocked",
            error.code if isinstance(error, Rf1086AuthorityError) else "RF1086_READ_ERROR",
            error.correlation_id if isinstance(error, Rf1086AuthorityError) else None))
        raise


def _pending_archive_error(error: Exception) -> bool:
    return isinstance(error, Rf1086AuthorityError) and error.code in {"GLD_021", "GLD_1017"}


async def execute_journaled_rf1086_production(input: JournaledRf1086ProductionInput, *,
        journal: ProductionOperationJournal, authority_client: Rf1086MutationAuthority) -> JournaledRf1086ProductionResult:
    if (len(input.document_order) != len(input.underskjema_xml)
            or set(input.document_order) != set(input.underskjema_xml)):
        raise ValueError("RF1086_DOCUMENT_ORDER_INVALID")
    entries = [(name, input.underskjema_xml[name]) for name in input.document_order]
    if not input.hovedskjema_xml.strip() or not entries:
        raise ValueError("RF1086_SUBMISSION_DOCUMENTS_REQUIRED")
    async def post_main(key: str) -> str:
        result = await authority_client.post_hovedskjema(income_year=input.income_year,
                                                        xml=input.hovedskjema_xml, idempotency_key=key)
        return result.hovedskjema_id
    main_id = await _mutation(journal, input.submission_id, "post_hovedskjema", _sha256(input.hovedskjema_xml), post_main)
    for document_name, xml in entries:
        async def post_sub(key: str) -> str:
            await authority_client.post_underskjema(income_year=input.income_year,
                hovedskjema_id=main_id, xml=xml, idempotency_key=key)
            return "posted"
        await _mutation(journal, input.submission_id, "post_underskjema:" + document_name, _sha256(xml), post_sub)
    async def confirm(key: str) -> str:
        result = await authority_client.confirm(income_year=input.income_year, hovedskjema_id=main_id,
                                                underskjema_count=len(entries), idempotency_key=key)
        return _json({"dialogId": result.dialog_id, "forsendelseId": result.forsendelse_id})
    confirmation = json.loads(await _mutation(journal, input.submission_id, "confirm",
                                               _sha256(f"{main_id}:{len(entries)}"), confirm))
    async def read_documents() -> str:
        try:
            result = await authority_client.list_documents(income_year=input.income_year,
                                                            reference_id=confirmation["forsendelseId"])
            return _json({"documentCount": len(result.documents)})
        except Exception as error:
            if _pending_archive_error(error):
                return _json({"documentCount": 0})
            raise
    documents = json.loads(await _read_operation(journal, input.submission_id, "list_documents", read_documents))
    count = documents["documentCount"]
    return JournaledRf1086ProductionResult("processing" if count else "received", main_id,
        confirmation["dialogId"], confirmation["forsendelseId"], count)


def rf1086_preview_payload_hash(preview: Rf1086Preview) -> str:
    # Property order and UTF-8 bytes are the existing JSON.stringify contract.
    return _sha256(_json({"filing": preview.filing, "company_id": preview.company_id,
        "income_year": preview.income_year, "hovedskjema_xml": preview.hovedskjema_xml,
        "underskjema_xml": preview.underskjema_xml}))


def rf1086_production_document_order(preview: Rf1086Preview) -> tuple[str, ...]:
    # The shipped no-activity renderer uses stored shareholders.id (PostgreSQL
    # UUID) verbatim as each subdocument key. For canonical lower-case UUIDs,
    # all hyphens occupy identical positions and localeCompare equals lexical
    # order. Arbitrary renderer inputs cannot silently choose an approximation.
    if not preview.underskjema_xml or any(not isinstance(name, str) or not re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", name)
        for name in preview.underskjema_xml):
        raise Rf1086ProductionError("payload_changed")
    return tuple(sorted(preview.underskjema_xml))


def rf1086_current_manifest(preview: Rf1086Preview, *, actor_id: str, organization_number: str,
                            approved_manifest: Mapping[str, object] | None = None) -> dict[str, object]:
    from collections import Counter
    if not re.fullmatch(r"[0-9]{9}", organization_number) or not 2000 <= preview.income_year <= 2100:
        raise Rf1086ProductionError("basis_unavailable")
    documents = {"hovedskjema": _sha256(preview.hovedskjema_xml)} | {
        "underskjema_" + name: _sha256(xml) for name, xml in preview.underskjema_xml.items()}
    expected = [(_js_trim(name), digest) for name, digest in documents.items()]
    if any(not name or len(_js_utf16_key(name)) > 400 for name, _ in expected):
        raise Rf1086ProductionError("payload_changed")
    if approved_manifest is None:
        order = ["hovedskjema", *("underskjema_" + name for name in rf1086_production_document_order(preview))]
        document_hashes = [{"name": name, "sha256": documents[name]} for name in order]
    else:
        # The original JS comparator already fixed this immutable array order.
        # Rebuild every entry from current bytes, retaining only the proven
        # approved order; do not import an ambient locale into the backend.
        entries = approved_manifest.get("documentHashes") if isinstance(approved_manifest, Mapping) else None
        if (not isinstance(entries, (list, tuple)) or any(not isinstance(entry, Mapping)
            or set(entry) != {"name", "sha256"} or not isinstance(entry["name"], str)
            or not isinstance(entry["sha256"], str) for entry in entries)
            or Counter((entry["name"], entry["sha256"]) for entry in entries) != Counter(expected)):
            raise Rf1086ProductionError("payload_changed")
        document_hashes = [{"name": entry["name"], "sha256": entry["sha256"]} for entry in entries]
    manifest = {"schemaVersion": "production-approval-v1", "companyId": _js_trim(preview.company_id),
        "userId": _js_trim(actor_id), "organizationNumber": organization_number, "incomeYear": preview.income_year,
        "obligation": "aksjonaerregisteroppgaven", "caseProfile": "rf1086_no_activity_v1",
        "adapterVersion": "rf1086-production-v1", "previewId": _js_trim(preview.id),
        "payloadHash": rf1086_preview_payload_hash(preview), "documentHashes": document_hashes,
        "blockers": [], "warnings": sorted({_js_trim(warning) for warning in preview.warnings if _js_trim(warning)}, key=_js_utf16_key)}
    if approved_manifest is not None and _js_object(approved_manifest) != manifest:
        raise Rf1086ProductionError("payload_changed")
    return manifest


def rf1086_current_manifest_hash(preview: Rf1086Preview, *, actor_id: str, organization_number: str,
                                 approved_manifest: Mapping[str, object] | None = None) -> str:
    return _sha256(_json(rf1086_current_manifest(preview, actor_id=actor_id,
        organization_number=organization_number, approved_manifest=approved_manifest)))
