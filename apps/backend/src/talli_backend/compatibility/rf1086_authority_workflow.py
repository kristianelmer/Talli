"""Frozen RF-owned journal/feedback behavior relocated under ADR 0013 for #150.

This is the existing RF compatibility implementation, not a filing capability or
Authority Connections policy. #151 absorbs/removes it. The approved scope is
architecture/evidence/issues/150/rf-credential-relocation-2026-09-09.md.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol, TypeVar
from uuid import uuid4
from xml.parsers import expat

from talli_backend.modules.billing.public import BillingEntitlementQuery, BillingObligation, BillingQueries, BillingSnapshotQuery
from talli_backend.modules.company_access.public import CompanyAccessRecord
from talli_backend.shared.kernel import ActorId, CompanyId, CorrelationId, IncomeYear


ProductionOperationState = Literal["prepared", "succeeded", "failed", "unknown"]
FailureClassification = Literal["retryable", "blocked", "unknown"]
Rf1086FeedbackClassification = Literal["accepted", "rejected", "action_required"]
Rf1086ReconciliationState = Literal["sent", "processing", "accepted", "rejected", "action_required", "unknown"]
RF1086_MAX_FEEDBACK_BYTES = 10 * 1024 * 1024
RF1086_FEEDBACK_NAMESPACES = {
    "urn:ske:fastsetting:innsamling:grunnlagsdata:tilbakemelding:innsendingstilbakemelding:v2": "innsendingstilbakemelding-v2",
    "urn:ske:fastsetting:innsamling:grunnlagsdata:tilbakemelding:leveransetilbakemelding:v2": "leveransetilbakemelding-v2",
}


class Rf1086AuthorityError(Exception):
    def __init__(self, code: str = "RF1086_AUTHORITY_ERROR", *, status: int | None = None,
                 correlation_id: str | None = None, specification_codes: tuple[str, ...] = (), retryable: bool = False):
        self.code = code
        self.status = status
        self.correlation_id = correlation_id
        self.specification_codes = specification_codes
        self.retryable = retryable
        # Raw authority messages, submitted values and credentials are not retained.
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class Rf1086AuthorityCall:
    method: Literal["GET", "POST"]
    endpoint: str
    body_hash: str
    idempotency_key: str | None
    status: Literal["accepted"] = "accepted"


@dataclass(frozen=True, slots=True)
class Rf1086MainResponse:
    hovedskjema_id: str
    call: Rf1086AuthorityCall


@dataclass(frozen=True, slots=True)
class Rf1086PostResponse:
    call: Rf1086AuthorityCall


@dataclass(frozen=True, slots=True)
class Rf1086Confirmation:
    oppgavegivers_leveranse_referanse: str
    dialog_id: str
    forsendelse_id: str
    call: Rf1086AuthorityCall


@dataclass(frozen=True, slots=True)
class Rf1086DocumentReference:
    reference: str


@dataclass(frozen=True, slots=True)
class Rf1086DocumentPage:
    total_items: int | float
    total_pages: int | float
    current_page: int | float
    documents: tuple[str | Rf1086DocumentReference, ...]
    document_shape_valid: bool
    call: Rf1086AuthorityCall


@dataclass(frozen=True, slots=True)
class Rf1086AuthorityDocument:
    reference: str
    content_type: str
    bytes: bytes = field(repr=False)


class Rf1086ReadOnlyAuthority(Protocol):
    async def list_documents(self, *, income_year: int, reference_id: str,
                             page: int = 0, size: int = 50) -> Rf1086DocumentPage: ...
    async def get_document(self, *, income_year: int, forsendelse_id: str,
                           document_id: str) -> Rf1086AuthorityDocument: ...


class Rf1086MutationAuthority(Protocol):
    async def post_hovedskjema(self, *, income_year: int, xml: str, idempotency_key: str) -> Rf1086MainResponse: ...
    async def post_underskjema(self, *, income_year: int, hovedskjema_id: str,
                              xml: str, idempotency_key: str) -> Rf1086PostResponse: ...
    async def confirm(self, *, income_year: int, hovedskjema_id: str,
                       underskjema_count: int, idempotency_key: str) -> Rf1086Confirmation: ...
    async def list_documents(self, *, income_year: int, reference_id: str,
                             page: int = 0, size: int = 50) -> Rf1086DocumentPage: ...


@dataclass(frozen=True, slots=True)
class ProductionOperation:
    id: str
    name: str
    state: ProductionOperationState
    attempt: int
    body_hash: str | None
    idempotency_key: str | None
    authority_reference: str | None
    failure_classification: FailureClassification | None


@dataclass(frozen=True, slots=True)
class ProductionOperationFailure:
    classification: FailureClassification
    code: str
    correlation_id: str | None


class ProductionOperationJournal(Protocol):
    """Prepare commits before I/O and restores persisted body/key identity.

    Existing records use resume_production_operation, so interrupted mutations
    are unknown and the twentieth failed attempt cannot be retried.
    """
    async def prepare(self, *, submission_id: str, name: str, body_hash: str | None,
                       idempotency_key: str | None) -> ProductionOperation: ...
    async def succeed(self, operation_id: str, authority_reference: str | None) -> None: ...
    async def fail(self, operation_id: str, failure: ProductionOperationFailure) -> None: ...


def resume_production_operation(latest: ProductionOperation, *, is_mutation: bool) -> ProductionOperation:
    """Exact latest-event normalization from createRf1086DatabaseJournal."""
    retryable = latest.state == "failed" and latest.failure_classification == "retryable"
    exhausted = retryable and latest.attempt >= 20
    state = latest.state if latest.state in {"succeeded", "failed"} or not is_mutation else "unknown"
    return replace(latest, state=state, attempt=latest.attempt + 1 if retryable and not exhausted else latest.attempt,
                   failure_classification="blocked" if exhausted else latest.failure_classification)


@dataclass(frozen=True, slots=True)
class JournaledRf1086ProductionInput:
    submission_id: str
    income_year: int
    hovedskjema_xml: str = field(repr=False)
    underskjema_xml: Mapping[str, str] = field(repr=False)
    document_order: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JournaledRf1086ProductionResult:
    status: Literal["received", "processing"]
    hovedskjema_id: str
    dialog_id: str
    forsendelse_id: str
    document_count: int
    final_authority_decision: None = None


class Rf1086UnknownProductionOutcomeError(Exception):
    code = "rf1086_unknown_production_outcome"

    def __init__(self, operation_name: str):
        super().__init__(self.code)


class Rf1086BlockedProductionOperationError(Exception):
    code = "rf1086_blocked_production_operation"

    def __init__(self, operation_name: str):
        super().__init__(self.code)


Token = TypeVar("Token")
Submission = TypeVar("Submission")


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


def _sha256(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _reference(value: str | None) -> str:
    if not value:
        raise ValueError("RF1086_JOURNAL_REFERENCE_MISSING")
    return value


_JS_TRIM = "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


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


@dataclass(frozen=True, slots=True)
class Rf1086FeedbackResult:
    classification: Rf1086FeedbackClassification
    schema: str
    transmission_id: str | None


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


@dataclass(frozen=True, slots=True)
class Rf1086ReconciliationSnapshot:
    state: Rf1086ReconciliationState
    artifact_hashes: tuple[str, ...] = ()
    safe_error_code: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class Rf1086ReconciliationArtifact:
    submission_id: str
    company_id: str
    authority_reference: str
    content_type: str
    bytes: bytes = field(repr=False)
    byte_length: int
    sha256: str
    classification: Rf1086FeedbackClassification


class Rf1086FeedbackArtifactPersistenceError(Exception):
    def __init__(self, *, retryable: bool):
        self.retryable = retryable
        super().__init__("RF1086_FEEDBACK_ARTIFACT_PERSISTENCE_ERROR")


def create_rf1086_feedback_artifact_persistence_error(cause: object, *, integrity_failure: bool = False) -> Rf1086FeedbackArtifactPersistenceError:
    code = str(getattr(cause, "code", "") or (cause.get("code", "") if isinstance(cause, Mapping) else "")).upper()
    contract_failure = code not in {"PGRST000", "PGRST001", "PGRST002", "PGRST003"} and bool(re.match(r"^(?:22|23|3F|42|P0001|PGRST)", code))
    return Rf1086FeedbackArtifactPersistenceError(retryable=not integrity_failure and not contract_failure)


class Rf1086ProductionJournal(Protocol):
    async def read_reconciliation_state(self) -> Rf1086ReconciliationSnapshot: ...
    async def record_artifact(self, artifact: Rf1086ReconciliationArtifact) -> str: ...
    async def append_reconciliation(self, event: Rf1086ReconciliationSnapshot) -> bool: ...


@dataclass(frozen=True, slots=True)
class Rf1086ReconciliationInput:
    submission_id: str
    company_id: str
    income_year: int
    forsendelse_id: str
    hovedskjema_xml: str = field(repr=False)
    underskjema_xml: Mapping[str, str] = field(repr=False)


@dataclass(frozen=True, slots=True)
class Rf1086ReconciliationResult:
    state: Rf1086ReconciliationState
    archive_reads: int
    artifact_count: int
    artifact_hashes: tuple[str, ...]
    safe_error_code: str | None
    correlation_id: str | None
    changed: bool


def _safe_reconciliation_failure(error: Exception) -> Rf1086ReconciliationSnapshot:
    if _pending_archive_error(error):
        return Rf1086ReconciliationSnapshot("processing")
    if isinstance(error, Rf1086AuthorityError):
        return Rf1086ReconciliationSnapshot("unknown" if error.status is None or error.retryable else "action_required",
                                           safe_error_code=error.code, correlation_id=error.correlation_id)
    return Rf1086ReconciliationSnapshot("unknown", safe_error_code="RF1086_RECONCILIATION_READ_ERROR")


async def _read_feedback_once(journal: Rf1086ProductionJournal, authority: Rf1086ReadOnlyAuthority,
        input: Rf1086ReconciliationInput, submitted_hashes: set[str], artifact_hashes: set[str]) -> Rf1086ReconciliationSnapshot:
    try:
        page = await authority.list_documents(income_year=input.income_year, reference_id=input.forsendelse_id, page=0, size=50)
    except Exception as error:
        return _safe_reconciliation_failure(error)
    if (not page.document_shape_valid or page.current_page != 0 or page.total_pages > 1
            or page.total_items != len(page.documents)):
        return Rf1086ReconciliationSnapshot("action_required", safe_error_code="RF1086_ARCHIVE_SHAPE_INVALID")
    if not page.documents:
        return Rf1086ReconciliationSnapshot("processing")
    classifications: list[Rf1086FeedbackClassification] = []
    for archived in page.documents:
        if isinstance(archived, str):
            bytes_value = archived.encode("utf-8")
            content_type = "application/xml"
            reference = "inline:" + _sha256(bytes_value)
        else:
            try:
                document = await authority.get_document(income_year=input.income_year,
                    forsendelse_id=input.forsendelse_id, document_id=archived.reference)
                reference, content_type, bytes_value = document.reference, document.content_type, document.bytes
            except Exception as error:
                return _safe_reconciliation_failure(error)
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
        outcome = await _read_feedback_once(journal, authority, input, submitted_hashes, artifact_hashes)
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


# The following two coordinators are the exact former production actions. They
# consume owned public facts and leave final release/lease checks to the frozen
# SQL invocation boundary. Recovery deliberately does not acquire new filing
# eligibility, invalidate expired approval, or demand fresh production MFA.

class LegacyRf1086Error(Exception):
    def __init__(self, code: str):
        allowed = {"invalid_request", "authentication_required", "approval_expired", "basis_unavailable",
            "connection_unavailable", "payload_changed", "configuration_unavailable", "send_unavailable",
            "status_unavailable", "status_busy", "step_up_required"}
        self.code = code if code in allowed else "status_unavailable"
        super().__init__(self.code)


class LegacyRf1086AuthenticationError(Exception):
    """The bearer could not be bound to a verified current session."""


@dataclass(frozen=True, slots=True)
class Rf1086Approval:
    id: str
    entitlement_id: str
    preview_id: str
    company_id: str
    user_id: str
    income_year: int
    obligation: str
    case_profile: str
    invalidated: bool
    manifest_hash: str
    manifest: Mapping[str, object] | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class Rf1086Preview:
    id: str
    company_id: str
    income_year: int
    filing: str
    hovedskjema_xml: str = field(repr=False)
    underskjema_xml: Mapping[str, str] = field(repr=False)
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Rf1086Submission:
    id: str
    approval_id: str
    entitlement_id: str
    company_id: str
    user_id: str
    income_year: int
    obligation: str
    case_profile: str
    environment: str
    feedback_state: Rf1086ReconciliationState


@dataclass(frozen=True, slots=True)
class Rf1086Connection:
    id: str
    company_id: str
    initiating_owner_user_id: str
    obligation: str
    external_ref: str = field(repr=False)
    status: str
    preflight_verified: bool


@dataclass(frozen=True, slots=True)
class Rf1086MutationBinding:
    authority: Rf1086MutationAuthority
    read_only_authority: Rf1086ReadOnlyAuthority
    discard: Callable[[], None] = field(repr=False)


@dataclass(frozen=True, slots=True)
class Rf1086ReadOnlyBinding:
    authority: Rf1086ReadOnlyAuthority
    discard: Callable[[], None] = field(repr=False)


class LegacyRf1086Session(Protocol):
    @property
    def actor_id(self) -> ActorId: ...
    @property
    def billing(self) -> BillingQueries: ...
    def require_configuration(self) -> None: ...
    async def read_approval(self, approval_id: str) -> Rf1086Approval | None: ...
    async def read_preview(self, preview_id: str) -> Rf1086Preview | None: ...
    async def read_submission(self, submission_id: str) -> Rf1086Submission | None: ...
    async def company_record(self, company_id: str) -> CompanyAccessRecord | None: ...
    async def read_connection(self, request_id: str, company_id: str) -> Rf1086Connection | None: ...
    async def require_fresh_production_owner(self, company_id: str) -> None: ...
    async def bind_mutation_authority(self, company: CompanyAccessRecord, connection: Rf1086Connection) -> Rf1086MutationBinding: ...
    async def bind_read_only_authority(self, company: CompanyAccessRecord, connection: Rf1086Connection) -> Rf1086ReadOnlyBinding: ...
    async def begin_production_filing(self, approval_id: str) -> str: ...
    def operation_journal(self, submission_id: str) -> ProductionOperationJournal: ...
    async def claim_feedback_lease(self, submission_id: str, lease_id: str) -> bool: ...
    async def read_claimed_reference(self, submission_id: str, lease_id: str) -> str: ...
    async def release_feedback_lease(self, submission_id: str, lease_id: str) -> None: ...
    def feedback_journal(self, *, submission_id: str, company_id: str, income_year: int,
                         forsendelse_id: str, lease_id: str) -> Rf1086ProductionJournal: ...


class LegacyRf1086SessionFactory(Protocol):
    async def session(self, access_token: str) -> LegacyRf1086Session: ...


@dataclass(frozen=True, slots=True)
class Rf1086SendResult:
    submission_id: str


@dataclass(frozen=True, slots=True)
class Rf1086OwnerReconciliationResult:
    state: Rf1086ReconciliationState | None
    error_code: str | None = None
    requires_manual_retry: bool = False


def _required_uuid_identity(value: str) -> str:
    from uuid import UUID
    try:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", value):
            raise ValueError()
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise LegacyRf1086Error("invalid_request") from None


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
        raise LegacyRf1086Error("payload_changed")
    return tuple(sorted(preview.underskjema_xml))


def rf1086_current_manifest(preview: Rf1086Preview, *, actor_id: str, organization_number: str,
                            approved_manifest: Mapping[str, object] | None = None) -> dict[str, object]:
    from collections import Counter
    if not re.fullmatch(r"[0-9]{9}", organization_number) or not 2000 <= preview.income_year <= 2100:
        raise LegacyRf1086Error("basis_unavailable")
    documents = {"hovedskjema": _sha256(preview.hovedskjema_xml)} | {
        "underskjema_" + name: _sha256(xml) for name, xml in preview.underskjema_xml.items()}
    expected = [(_js_trim(name), digest) for name, digest in documents.items()]
    if any(not name or len(_js_utf16_key(name)) > 400 for name, _ in expected):
        raise LegacyRf1086Error("payload_changed")
    if approved_manifest is None:
        order = ["hovedskjema", *("underskjema_" + name for name in rf1086_production_document_order(preview))]
        document_hashes = [{"name": name, "sha256": documents[name]} for name in order]
    else:
        # The original JS comparator already fixed this immutable array order.
        # Rebuild every entry from current bytes, retaining only the proven
        # approved order; do not import an ambient locale into the backend.
        entries = approved_manifest.get("documentHashes") if isinstance(approved_manifest, Mapping) else None
        if (not isinstance(entries, list) or any(not isinstance(entry, Mapping)
            or set(entry) != {"name", "sha256"} or not isinstance(entry["name"], str)
            or not isinstance(entry["sha256"], str) for entry in entries)
            or Counter((entry["name"], entry["sha256"]) for entry in entries) != Counter(expected)):
            raise LegacyRf1086Error("payload_changed")
        document_hashes = [{"name": entry["name"], "sha256": entry["sha256"]} for entry in entries]
    manifest = {"schemaVersion": "production-approval-v1", "companyId": _js_trim(preview.company_id),
        "userId": _js_trim(actor_id), "organizationNumber": organization_number, "incomeYear": preview.income_year,
        "obligation": "aksjonaerregisteroppgaven", "caseProfile": "rf1086_no_activity_v1",
        "adapterVersion": "rf1086-production-v1", "previewId": _js_trim(preview.id),
        "payloadHash": rf1086_preview_payload_hash(preview), "documentHashes": document_hashes,
        "blockers": [], "warnings": sorted({_js_trim(warning) for warning in preview.warnings if _js_trim(warning)}, key=_js_utf16_key)}
    if approved_manifest is not None and dict(approved_manifest) != manifest:
        raise LegacyRf1086Error("payload_changed")
    return manifest


def rf1086_current_manifest_hash(preview: Rf1086Preview, *, actor_id: str, organization_number: str,
                                 approved_manifest: Mapping[str, object] | None = None) -> str:
    return _sha256(_json(rf1086_current_manifest(preview, actor_id=actor_id,
        organization_number=organization_number, approved_manifest=approved_manifest)))


def _valid_connection(connection, *, company_id: str, actor_id: str, obligation: str, external_ref: str) -> bool:
    return (connection is not None and connection.company_id == company_id
        and connection.initiating_owner_user_id == actor_id and connection.obligation == obligation
        and connection.status == "accepted" and connection.preflight_verified and connection.external_ref == external_ref)


async def send_approved_rf1086_production_filing(session: LegacyRf1086Session, approval_id: str) -> Rf1086SendResult:
    approval_id = _required_uuid_identity(approval_id)
    session.require_configuration()
    actor = str(session.actor_id.subject)
    approval = await session.read_approval(approval_id)
    if approval is None or approval.invalidated:
        raise LegacyRf1086Error("approval_expired")
    await session.require_fresh_production_owner(approval.company_id)
    preview = await session.read_preview(approval.preview_id)
    correlation = CorrelationId(str(uuid4()))
    snapshot = await session.billing.snapshot(BillingSnapshotQuery((CompanyId(approval.company_id),), session.actor_id, correlation))
    decision = await session.billing.entitlement(BillingEntitlementQuery(CompanyId(approval.company_id), session.actor_id,
        correlation, IncomeYear(approval.income_year), BillingObligation.SHAREHOLDER_REGISTER, "rf1086_no_activity_v1"))
    company = await session.company_record(approval.company_id)
    entitlement = next((candidate for candidate in snapshot.pilot_entitlements if str(candidate.entitlement_id) == approval.entitlement_id), None)
    if (preview is None or entitlement is None or company is None or str(entitlement.user_id) != actor
            or not decision.allowed or str(decision.pilot_entitlement_id) != str(entitlement.entitlement_id)
            or not preview.hovedskjema_xml):
        raise LegacyRf1086Error("basis_unavailable")
    connection = await session.read_connection(str(entitlement.system_user_request_id), approval.company_id)
    if not _valid_connection(connection, company_id=approval.company_id, actor_id=actor,
                             obligation=approval.obligation, external_ref=entitlement.system_user_external_reference):
        raise LegacyRf1086Error("connection_unavailable")
    document_order = rf1086_production_document_order(preview)
    if (approval.manifest is None or not re.fullmatch(r"[a-f0-9]{64}", approval.manifest_hash)
        or rf1086_current_manifest_hash(preview, actor_id=actor, organization_number=company.org_number,
            approved_manifest=approval.manifest) != approval.manifest_hash):
        raise LegacyRf1086Error("payload_changed")
    binding = None
    try:
        binding = await session.bind_mutation_authority(company, connection)
        submission_id = await session.begin_production_filing(approval.id)
        submitted = await execute_journaled_rf1086_production(JournaledRf1086ProductionInput(
            submission_id, preview.income_year, preview.hovedskjema_xml, preview.underskjema_xml, document_order),
            journal=session.operation_journal(submission_id), authority_client=binding.authority)
        lease_id = str(uuid4())
        if await session.claim_feedback_lease(submission_id, lease_id):
            try:
                reference = await session.read_claimed_reference(submission_id, lease_id)
                if reference != submitted.forsendelse_id:
                    raise LegacyRf1086Error("send_unavailable")
                await reconcile_journaled_rf1086_production(session.feedback_journal(submission_id=submission_id,
                    company_id=approval.company_id, income_year=preview.income_year, forsendelse_id=reference, lease_id=lease_id),
                    binding.read_only_authority, Rf1086ReconciliationInput(submission_id, approval.company_id,
                        preview.income_year, reference, preview.hovedskjema_xml, preview.underskjema_xml), initial_poll=True)
            finally:
                await session.release_feedback_lease(submission_id, lease_id)
        return Rf1086SendResult(submission_id)
    except Exception:
        raise LegacyRf1086Error("send_unavailable") from None
    finally:
        if binding is not None:
            binding.discard()


async def reconcile_rf1086_production(session: LegacyRf1086Session, submission_id: str) -> Rf1086OwnerReconciliationResult:
    state = None
    binding = None
    claimed = False
    lease_id = str(uuid4())
    try:
        submission_id = _required_uuid_identity(submission_id)
        actor = str(session.actor_id.subject)
        submission = await session.read_submission(submission_id)
        if (submission is None or submission.user_id != actor or submission.obligation != "aksjonaerregisteroppgaven"
                or submission.case_profile != "rf1086_no_activity_v1" or submission.environment != "production"):
            raise LegacyRf1086Error("basis_unavailable")
        state = submission.feedback_state
        if state in {"accepted", "rejected", "action_required"}:
            return Rf1086OwnerReconciliationResult(state)
        company = await session.company_record(submission.company_id)
        approval = await session.read_approval(submission.approval_id)
        snapshot = await session.billing.snapshot(BillingSnapshotQuery((CompanyId(submission.company_id),),
            session.actor_id, CorrelationId(str(uuid4()))))
        entitlement = next((candidate for candidate in snapshot.pilot_entitlements if str(candidate.entitlement_id) == submission.entitlement_id), None)
        if (company is None or company.role != "owner" or approval is None or entitlement is None
            or approval.company_id != submission.company_id or approval.user_id != actor
            or approval.entitlement_id != str(entitlement.entitlement_id) or approval.income_year != submission.income_year
            or approval.obligation != submission.obligation or approval.case_profile != submission.case_profile
            or str(entitlement.company_id) != submission.company_id or str(entitlement.user_id) != actor
            or int(entitlement.income_year) != submission.income_year or str(entitlement.obligation) != submission.obligation
            or str(entitlement.case_profile) != submission.case_profile):
            raise LegacyRf1086Error("basis_unavailable")
        connection = await session.read_connection(str(entitlement.system_user_request_id), submission.company_id)
        preview = await session.read_preview(approval.preview_id)
        if (not _valid_connection(connection, company_id=submission.company_id, actor_id=actor,
                obligation=submission.obligation, external_ref=entitlement.system_user_external_reference)
            or preview is None or preview.company_id != submission.company_id or preview.income_year != submission.income_year
            or not preview.hovedskjema_xml):
            raise LegacyRf1086Error("connection_unavailable")
        session.require_configuration()
        claimed = await session.claim_feedback_lease(submission.id, lease_id)
        if not claimed:
            raise LegacyRf1086Error("status_busy")
        reference = await session.read_claimed_reference(submission.id, lease_id)
        binding = await session.bind_read_only_authority(company, connection)
        result = await reconcile_journaled_rf1086_production(session.feedback_journal(submission_id=submission.id,
            company_id=submission.company_id, income_year=submission.income_year, forsendelse_id=reference, lease_id=lease_id),
            binding.authority, Rf1086ReconciliationInput(submission.id, submission.company_id, submission.income_year,
                reference, preview.hovedskjema_xml, preview.underskjema_xml), initial_poll=False)
        return Rf1086OwnerReconciliationResult(result.state)
    except LegacyRf1086Error as error:
        return Rf1086OwnerReconciliationResult(state, error.code, True)
    except Exception:
        return Rf1086OwnerReconciliationResult(state, "status_unavailable", True)
    finally:
        if binding is not None:
            binding.discard()
        if claimed:
            await session.release_feedback_lease(submission_id, lease_id)
