"""Read-only RF feedback classification and durable artifact reconciliation."""
from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from xml.parsers import expat

from .public import (
    Rf1086AuthorityError, Rf1086FeedbackArtifactPersistenceError, Rf1086FeedbackClassification,
    Rf1086FeedbackResult, Rf1086ProductionJournal, Rf1086ReadOnlyAuthority,
    Rf1086ReconciliationArtifact, Rf1086ReconciliationInput, Rf1086ReconciliationResult,
    Rf1086ReconciliationSnapshot,
)
from .production import _js_utf8_bytes, _pending_archive_error, _sha256

RF1086_MAX_FEEDBACK_BYTES = 10 * 1024 * 1024
RF1086_ARCHIVE_PAGE_SIZE = 50
# Operational scan bounds fail closed; they do not define supported company scope.
RF1086_MAX_ARCHIVE_PAGES = 100
RF1086_MAX_ARCHIVE_SCAN_BYTES = 32 * 1024 * 1024
RF1086_ARCHIVE_SCAN_TIMEOUT_SECONDS = 60
RF1086_FEEDBACK_NAMESPACES = {
    "urn:ske:fastsetting:innsamling:grunnlagsdata:tilbakemelding:innsendingstilbakemelding:v2": "innsendingstilbakemelding-v2",
    "urn:ske:fastsetting:innsamling:grunnlagsdata:tilbakemelding:leveransetilbakemelding:v2": "leveransetilbakemelding-v2",
}


def classify_rf1086_feedback(bytes_value: bytes, *, forsendelse_id: str, income_year: int) -> Rf1086FeedbackResult:
    action_required = Rf1086FeedbackResult("action_required", "unknown", None)
    if (not isinstance(bytes_value, bytes) or not 1 <= len(bytes_value) <= RF1086_MAX_FEEDBACK_BYTES
            or not forsendelse_id or type(income_year) is not int):
        return action_required
    try:
        xml = bytes_value.decode("utf-8")
    except UnicodeError:
        return action_required
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", xml, re.I):
        return action_required
    schema = "unknown"
    root_namespace = ""
    invalid = False
    stack: list[str] = []
    captures: dict[str, list[str]] = {}
    active: dict | None = None
    cdata = False

    def open_tag(name, _attributes):
        nonlocal schema, root_namespace, invalid, active
        uri, _, local = name.rpartition("|")
        if not stack:
            root_namespace = uri
            schema = RF1086_FEEDBACK_NAMESPACES.get(uri, "unknown")
            if local != "tilbakemelding" or schema == "unknown":
                invalid = True
        elif uri != root_namespace:
            invalid = True
        if active is not None:
            invalid = True
        if local in {"leveransestatus", "forsendelseid", "inntektsaar"}:
            expected = "tilbakemelding/innsending/forsendelseid" if local == "forsendelseid" else (
                "tilbakemelding/leveranse/inntektsaar" if local == "inntektsaar" else
                "tilbakemelding/leveranse/leveransestatus" if schema == "innsendingstilbakemelding-v2" else
                "tilbakemelding/leveranseoppsummering/leveransestatus")
            if schema == "unknown" or "/".join(stack + [local]) != expected:
                invalid = True
            active = {"field": local, "depth": len(stack) + 1, "text": ""}
        stack.append(local)

    def text(value):
        nonlocal invalid
        if active is not None and not cdata:
            active["text"] += value
            if len(active["text"]) > 500:
                invalid = True

    def start_cdata():
        nonlocal cdata, invalid
        cdata = True
        if active is not None:
            invalid = True

    def end_cdata():
        nonlocal cdata
        cdata = False

    def close_tag(_name):
        nonlocal active
        if active is not None and active["depth"] == len(stack):
            captures.setdefault(active["field"], []).append(active["text"].strip())
            active = None
        stack.pop()

    try:
        parser = expat.ParserCreate(namespace_separator="|")
        parser.StartElementHandler = open_tag
        parser.EndElementHandler = close_tag
        parser.CharacterDataHandler = text
        parser.StartCdataSectionHandler = start_cdata
        parser.EndCdataSectionHandler = end_cdata
        parser.ExternalEntityRefHandler = lambda *_: 0
        parser.Parse(xml, True)
    except (expat.ExpatError, ValueError, RecursionError):
        invalid = True
    statuses = captures.get("leveransestatus", [])
    transmissions = captures.get("forsendelseid", [])
    years = captures.get("inntektsaar", [])
    transmission = transmissions[0] if len(transmissions) == 1 else None
    if (invalid or schema == "unknown" or stack or len(statuses) != 1 or statuses[0] not in {"godkjent", "avvist"}
            or len(transmissions) > 1 or len(years) > 1
            or (len(transmissions) == 1 and transmission != forsendelse_id)
            or (len(years) == 1 and years[0] != str(income_year))):
        return Rf1086FeedbackResult("action_required", schema, transmission)
    return Rf1086FeedbackResult("accepted" if statuses[0] == "godkjent" else "rejected", schema, transmission)


def create_rf1086_feedback_artifact_persistence_error(cause: object, *, integrity_failure: bool = False) -> Rf1086FeedbackArtifactPersistenceError:
    code = str(getattr(cause, "code", "") or (cause.get("code", "") if isinstance(cause, Mapping) else "")).upper()
    contract_failure = code not in {"PGRST000", "PGRST001", "PGRST002", "PGRST003"} and bool(re.match(r"^(?:22|23|3F|42|P0001|PGRST)", code))
    return Rf1086FeedbackArtifactPersistenceError(retryable=not integrity_failure and not contract_failure)


def _safe_reconciliation_failure(error: Exception) -> Rf1086ReconciliationSnapshot:
    if _pending_archive_error(error):
        return Rf1086ReconciliationSnapshot("processing")
    if isinstance(error, Rf1086AuthorityError):
        return Rf1086ReconciliationSnapshot("unknown" if error.status is None or error.retryable else "action_required",
                                           safe_error_code=error.code, correlation_id=error.correlation_id)
    return Rf1086ReconciliationSnapshot("unknown", safe_error_code="RF1086_RECONCILIATION_READ_ERROR")


async def _complete_archive(authority: Rf1086ReadOnlyAuthority, input: Rf1086ReconciliationInput):
    documents = []
    seen = set()
    total_bytes = 0
    expected_extent = None
    page_index = 0
    while True:
        page = await authority.list_documents(income_year=input.income_year,
            reference_id=input.forsendelse_id, page=page_index, size=RF1086_ARCHIVE_PAGE_SIZE)
        extent = (page.total_items, page.total_pages)
        if (not page.document_shape_valid or isinstance(page.current_page, bool) or page.current_page != page_index
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) or value < 0 or value != int(value) for value in extent)
                or (expected_extent is not None and extent != expected_extent)):
            raise Rf1086AuthorityError("RF1086_ARCHIVE_SHAPE_INVALID", status=200)
        pages = int(page.total_pages)
        expected_pages = (int(page.total_items) + RF1086_ARCHIVE_PAGE_SIZE - 1) // RF1086_ARCHIVE_PAGE_SIZE
        if (pages != expected_pages and not (page.total_items == 0 and pages == 1)) or (pages == 0 and (page_index != 0 or page.documents)):
            raise Rf1086AuthorityError("RF1086_ARCHIVE_SHAPE_INVALID", status=200)
        if pages > RF1086_MAX_ARCHIVE_PAGES:
            raise Rf1086AuthorityError("RF1086_ARCHIVE_SCAN_LIMIT", status=200)
        expected_count = min(RF1086_ARCHIVE_PAGE_SIZE, int(page.total_items) - page_index * RF1086_ARCHIVE_PAGE_SIZE)
        if len(page.documents) != expected_count:
            raise Rf1086AuthorityError("RF1086_ARCHIVE_SHAPE_INVALID", status=200)
        identities = set()
        for document in page.documents:
            raw = _js_utf8_bytes(document if isinstance(document, str) else document.reference)
            identity = ("inline" if isinstance(document, str) else "reference", _sha256(raw))
            if identity in seen:
                raise Rf1086AuthorityError("RF1086_ARCHIVE_SHAPE_INVALID", status=200)
            identities.add(identity)
            total_bytes += len(raw)
            if total_bytes > RF1086_MAX_ARCHIVE_SCAN_BYTES:
                raise Rf1086AuthorityError("RF1086_ARCHIVE_SCAN_LIMIT", status=200)
        seen.update(identities)
        documents.extend(page.documents)
        if pages == 0 or page_index == pages - 1:
            return documents
        expected_extent = extent
        page_index += 1


async def _read_feedback_once(journal: Rf1086ProductionJournal, authority: Rf1086ReadOnlyAuthority,
        input: Rf1086ReconciliationInput, submitted_hashes: set[str], artifact_hashes: set[str]) -> Rf1086ReconciliationSnapshot:
    try:
        documents = await _complete_archive(authority, input)
    except Exception as error:
        return _safe_reconciliation_failure(error)
    if not documents:
        return Rf1086ReconciliationSnapshot("processing")
    classifications: list[Rf1086FeedbackClassification] = []
    processed_bytes = 0
    for archived in documents:
        if isinstance(archived, str):
            bytes_value = _js_utf8_bytes(archived)
            content_type = "application/xml"
            reference = "inline:" + _sha256(bytes_value)
        else:
            try:
                document = await authority.get_document(income_year=input.income_year,
                    forsendelse_id=input.forsendelse_id, document_id=archived.reference)
                reference, content_type, bytes_value = document.reference, document.content_type, document.bytes
            except Exception as error:
                return _safe_reconciliation_failure(error)
        processed_bytes += len(bytes_value)
        if processed_bytes > RF1086_MAX_ARCHIVE_SCAN_BYTES:
            return Rf1086ReconciliationSnapshot("action_required", safe_error_code="RF1086_ARCHIVE_SCAN_LIMIT")
        digest = _sha256(bytes_value)
        if digest in submitted_hashes:
            continue
        feedback = (classify_rf1086_feedback(bytes_value, forsendelse_id=input.forsendelse_id, income_year=input.income_year)
            if content_type in {"application/xml", "text/xml"} else Rf1086FeedbackResult("action_required", "unknown", None))
        classifications.append(feedback.classification)
        try:
            persisted = await journal.record_artifact(Rf1086ReconciliationArtifact(input.submission_id,
                input.company_id, reference, content_type, bytes_value, len(bytes_value), digest, feedback.classification))
            artifact_hashes.add(persisted)
        except Exception as error:
            retryable = isinstance(error, Rf1086FeedbackArtifactPersistenceError) and error.retryable
            return Rf1086ReconciliationSnapshot("unknown" if retryable else "action_required", safe_error_code=(
                "RF1086_FEEDBACK_ARTIFACT_PERSIST_RETRY" if retryable else "RF1086_FEEDBACK_ARTIFACT_PERSIST_FAILED"))
    if not classifications:
        return Rf1086ReconciliationSnapshot("processing")
    if "action_required" in classifications:
        return Rf1086ReconciliationSnapshot("action_required", safe_error_code="RF1086_FEEDBACK_ACTION_REQUIRED")
    if len(set(classifications)) != 1:
        return Rf1086ReconciliationSnapshot("action_required", safe_error_code="RF1086_FEEDBACK_CONFLICT")
    state = classifications[0]
    return Rf1086ReconciliationSnapshot(state, safe_error_code="RF1086_FEEDBACK_ACCEPTED" if state == "accepted" else "RF1086_FEEDBACK_REJECTED")


async def reconcile_journaled_rf1086_production(journal: Rf1086ProductionJournal,
        authority: Rf1086ReadOnlyAuthority, input: Rf1086ReconciliationInput, *,
        initial_poll: bool | None = None, sleep: Callable[[int], Awaitable[None]] | None = None) -> Rf1086ReconciliationResult:
    if (not input.submission_id or not input.company_id or not input.forsendelse_id or type(input.income_year) is not int
            or not input.hovedskjema_xml.strip() or not input.underskjema_xml):
        raise ValueError("RF1086_RECONCILIATION_RELATIONSHIP_REQUIRED")
    snapshot = await journal.read_reconciliation_state()
    artifact_hashes = set(snapshot.artifact_hashes)
    submitted_hashes = {_sha256(input.hovedskjema_xml), *(_sha256(xml) for xml in input.underskjema_xml.values())}
    maximum_reads = 5 if (snapshot.state == "sent" if initial_poll is None else initial_poll) else 1
    archive_reads = 0
    outcome = Rf1086ReconciliationSnapshot("processing")
    for attempt in range(1, maximum_reads + 1):
        archive_reads += 1
        try:
            async with asyncio.timeout(RF1086_ARCHIVE_SCAN_TIMEOUT_SECONDS):
                outcome = await _read_feedback_once(journal, authority, input, submitted_hashes, artifact_hashes)
        except TimeoutError:
            outcome = Rf1086ReconciliationSnapshot("unknown", safe_error_code="RF1086_ARCHIVE_SCAN_TIMEOUT")
        if outcome.state != "processing" or attempt == maximum_reads:
            break
        if sleep is not None:
            await sleep(2000)
        else:
            await asyncio.sleep(2)
    hashes = tuple(sorted(artifact_hashes))
    changed = await journal.append_reconciliation(replace(outcome, artifact_hashes=hashes))
    return Rf1086ReconciliationResult(outcome.state, archive_reads, len(hashes), hashes,
                                       outcome.safe_error_code, outcome.correlation_id, changed)
