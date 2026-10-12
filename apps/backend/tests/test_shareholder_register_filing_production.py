"""Canonical RF journal, feedback and authenticated workflow; local fakes only."""

import asyncio
import hashlib
from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from talli_backend.modules.shareholder_register_filing.public import JournaledRf1086ProductionInput, ProductionOperation, Rf1086AuthorityCall, Rf1086AuthorityDocument, Rf1086AuthorityError, Rf1086BlockedProductionOperationError, Rf1086Confirmation, Rf1086DocumentPage, Rf1086DocumentReference, Rf1086FeedbackArtifactPersistenceError, Rf1086FeedbackTransmission, Rf1086MainResponse, Rf1086PostResponse, Rf1086ReconciliationInput, Rf1086ReconciliationSnapshot, Rf1086UnknownProductionOutcomeError
from talli_backend.modules.shareholder_register_filing.feedback import RF1086_FEEDBACK_NAMESPACES, classify_rf1086_feedback, create_rf1086_feedback_artifact_persistence_error, reconcile_journaled_rf1086_production
from talli_backend.modules.shareholder_register_filing.production import execute_journaled_rf1086_production, execute_rf1086_production_release, resume_production_operation


MAIN = "10000000-0000-4000-8000-000000000001"
DIALOG = "20000000-0000-4000-8000-000000000002"
TRANSMISSION = "30000000-0000-4000-8000-000000000003"
DOCUMENT = "40000000-0000-4000-8000-000000000004"
PERSISTED_KEY = "50000000-0000-4000-8000-000000000005"
NS, DELIVERY_NS = RF1086_FEEDBACK_NAMESPACES
MAIN_XML = " \n<H>Æø &amp; original</H>\n"
SUB_XML = "<U>preserved\r\nbytes</U>"
INPUT = JournaledRf1086ProductionInput("submission", 2025, MAIN_XML, {"founder_b": "<B/>", "founder_a": SUB_XML}, ("founder_a", "founder_b"))
RECONCILIATION = Rf1086ReconciliationInput("submission", "company", 2025, TRANSMISSION, MAIN_XML, INPUT.underskjema_xml)
CALL = Rf1086AuthorityCall("GET", "https://unused.invalid/", hashlib.sha256(b"").hexdigest(), None)


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def feedback(*, namespace=NS, status="godkjent", reference=TRANSMISSION, year=2025, extra=""):
    relationship = "" if reference is None else f"<innsending><forsendelseid>{reference}</forsendelseid></innsending>"
    income_year = "" if year is None else f"<inntektsaar>{year}</inntektsaar>"
    delivery = (f"<leveranse>{income_year}</leveranse><leveranseoppsummering><leveransestatus>{status}</leveransestatus></leveranseoppsummering>"
        if namespace == DELIVERY_NS else f"<leveranse><leveransestatus>{status}</leveransestatus>{income_year}</leveranse>")
    return f'<tilbakemelding xmlns="{namespace}">{relationship}{delivery}{extra}</tilbakemelding>'


def page(documents=(), **changes):
    return replace(Rf1086DocumentPage(len(documents), 1 if documents else 0, 0, tuple(documents), True, CALL), **changes)


class OperationJournal:
    def __init__(self):
        self.operations = {}
        self.events = []

    async def prepare(self, **arguments):
        self.events.append(("prepare", arguments))
        name = arguments["name"]
        if name in self.operations:
            previous = self.operations[name]
            assert arguments["body_hash"] == previous.body_hash
            operation = resume_production_operation(previous, is_mutation=name != "list_documents")
        else:
            operation = ProductionOperation(str(uuid4()), name, "prepared", 1, arguments["body_hash"],
                arguments["idempotency_key"], None, None)
        self.operations[name] = operation
        return operation

    async def succeed(self, operation_id, authority_reference):
        name, operation = next((name, value) for name, value in self.operations.items() if value.id == operation_id)
        self.events.append(("succeed", name))
        self.operations[name] = replace(operation, state="succeeded", authority_reference=authority_reference,
                                        failure_classification=None)

    async def fail(self, operation_id, failure):
        name, operation = next((name, value) for name, value in self.operations.items() if value.id == operation_id)
        self.events.append(("fail", failure))
        self.operations[name] = replace(operation, state="failed" if failure.classification != "unknown" else "unknown",
                                        failure_classification=failure.classification)


class Authority:
    def __init__(self, *, main_error=None, archive=None):
        self.calls = []
        self.main_error = main_error
        self.archive = archive or page()

    async def post_hovedskjema(self, **arguments):
        self.calls.append(("main", arguments))
        if self.main_error:
            raise self.main_error
        return Rf1086MainResponse(MAIN, CALL)

    async def post_underskjema(self, **arguments):
        self.calls.append(("sub", arguments))
        return Rf1086PostResponse(CALL)

    async def confirm(self, **arguments):
        self.calls.append(("confirm", arguments))
        return Rf1086Confirmation("delivery", DIALOG, TRANSMISSION, CALL)

    async def list_documents(self, **arguments):
        self.calls.append(("list", arguments))
        if isinstance(self.archive, Exception):
            raise self.archive
        return self.archive


def execute(journal, authority, input=INPUT):
    return asyncio.run(execute_journaled_rf1086_production(input, journal=journal, authority_client=authority))


def test_journal_saves_original_hashes_and_per_operation_uuid_and_replay_reuses_success_without_io():
    journal, authority = OperationJournal(), Authority(archive=page([MAIN_XML]))
    result = execute(journal, authority)
    assert (result.status, result.final_authority_decision, result.document_count) == ("processing", None, 1)
    assert (result.hovedskjema_id, result.dialog_id, result.forsendelse_id) == (MAIN, DIALOG, TRANSMISSION)
    assert [name for name, _ in authority.calls] == ["main", "sub", "sub", "confirm", "list"]
    assert authority.calls[0][1]["xml"] == MAIN_XML
    assert authority.calls[1][1]["xml"] == SUB_XML
    assert authority.calls[2][1]["xml"] == "<B/>"
    assert authority.calls[-1][1] == {"income_year": 2025, "reference_id": TRANSMISSION}
    operations = journal.operations
    assert operations["post_hovedskjema"].body_hash == sha(MAIN_XML)
    assert operations["post_underskjema:founder_a"].body_hash == sha(SUB_XML)
    assert operations["confirm"].body_hash == sha(MAIN + ":2")
    keys = [operation.idempotency_key for name, operation in operations.items() if name != "list_documents"]
    assert len(set(keys)) == 4 and all(UUID(key).version == 4 for key in keys)
    assert operations["list_documents"].body_hash is None and operations["list_documents"].idempotency_key is None
    assert execute(journal, authority) == result
    assert len(authority.calls) == 5
    assert MAIN_XML not in repr(INPUT)


@pytest.mark.parametrize("code", ["GLD_021", "GLD_1017"])
def test_archive_pending_is_received_without_claiming_final_authority_success(code):
    result = execute(OperationJournal(), Authority(archive=Rf1086AuthorityError(code, status=404)))
    assert result.status == "received" and result.document_count == 0 and result.final_authority_decision is None


@pytest.mark.parametrize("stage", ["prepared", "unknown"])
def test_interrupted_or_unknown_mutation_never_replays(stage):
    journal, authority = OperationJournal(), Authority()
    journal.operations["post_hovedskjema"] = ProductionOperation("operation", "post_hovedskjema", stage, 1,
        sha(MAIN_XML), PERSISTED_KEY, None, None)
    with pytest.raises(Rf1086UnknownProductionOutcomeError):
        execute(journal, authority)
    assert not authority.calls


def test_network_unknown_is_journalled_then_repeat_stops_without_another_provider_effect():
    journal, authority = OperationJournal(), Authority(main_error=Rf1086AuthorityError("RF1086_NETWORK_ERROR", retryable=True))
    for _ in range(2):
        with pytest.raises(Rf1086UnknownProductionOutcomeError):
            execute(journal, authority)
    assert len(authority.calls) == 1
    assert journal.operations["post_hovedskjema"].state == "unknown"


def test_cancellation_after_provider_effect_leaves_prepared_and_retry_stops():
    journal, authority = OperationJournal(), Authority(main_error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        execute(journal, authority)
    assert journal.operations["post_hovedskjema"].state == "prepared"
    with pytest.raises(Rf1086UnknownProductionOutcomeError):
        execute(journal, authority)
    assert len(authority.calls) == 1


def test_failed_retry_uses_persisted_key_and_attempt_twenty_blocks():
    journal, authority = OperationJournal(), Authority(main_error=Rf1086AuthorityError("GLD_004", status=429, retryable=True))
    journal.operations["post_hovedskjema"] = ProductionOperation("operation", "post_hovedskjema", "failed", 18,
        sha(MAIN_XML), PERSISTED_KEY, None, "retryable")
    for attempt in [19, 20]:
        with pytest.raises(Rf1086AuthorityError):
            execute(journal, authority)
        assert journal.operations["post_hovedskjema"].attempt == attempt
        assert authority.calls[-1][1]["idempotency_key"] == PERSISTED_KEY
    with pytest.raises(Rf1086BlockedProductionOperationError):
        execute(journal, authority)
    assert len(authority.calls) == 2 and journal.operations["post_hovedskjema"].attempt == 20


@pytest.mark.parametrize("error,classification,code", [
    (Rf1086AuthorityError("GLD_005", status=400, correlation_id="correlation"), "blocked", "GLD_005"),
    (ValueError("sensitive original body"), "blocked", "RF1086_OPERATION_ERROR"),
])
def test_conclusive_mutation_failure_has_safe_journal_diagnostics(error, classification, code):
    journal, authority = OperationJournal(), Authority(main_error=error)
    with pytest.raises(type(error)):
        execute(journal, authority)
    failure = journal.events[-1][1]
    assert (failure.classification, failure.code) == (classification, code)
    assert "sensitive" not in repr(failure)
    with pytest.raises(Rf1086BlockedProductionOperationError):
        execute(journal, authority)
    assert len(authority.calls) == 1


@pytest.mark.parametrize("field,value", [("body_hash", "0" * 64), ("name", "different_operation")])
def test_mismatched_persisted_mutation_identity_is_rejected_before_post(field, value):
    class MismatchedJournal(OperationJournal):
        async def prepare(self, **arguments):
            return replace(await super().prepare(**arguments), **{field: value})
    authority = Authority()
    with pytest.raises(Rf1086BlockedProductionOperationError):
        execute(MismatchedJournal(), authority)
    assert not authority.calls


@pytest.mark.parametrize("failure_stage", [None, "acquire", "begin", "execute"])
def test_release_acquires_before_begin_and_discards_on_every_post_acquisition_exit(failure_stage):
    events, token, submission = [], object(), object()
    async def acquire():
        events.append("acquire")
        if failure_stage == "acquire":
            raise RuntimeError()
        return token
    async def begin():
        events.append("begin")
        if failure_stage == "begin":
            raise RuntimeError()
        return submission
    async def submit(received_token, received_submission):
        events.append("execute")
        assert received_token is token and received_submission is submission
        if failure_stage == "execute":
            raise RuntimeError()
    def discard(received):
        assert received is token
        events.append("discard")
    async def run():
        return await execute_rf1086_production_release(acquire_delegated_token=acquire,
            begin_production_filing=begin, execute_external_submission=submit, discard_token=discard)
    if failure_stage:
        with pytest.raises(RuntimeError):
            asyncio.run(run())
    else:
        assert asyncio.run(run()) is submission
    assert events == {None: ["acquire", "begin", "execute", "discard"], "acquire": ["acquire"],
        "begin": ["acquire", "begin", "discard"], "execute": ["acquire", "begin", "execute", "discard"]}[failure_stage]


@pytest.mark.parametrize("namespace", [NS, DELIVERY_NS])
@pytest.mark.parametrize("status,expected", [("godkjent", "accepted"), ("avvist", "rejected")])
def test_official_feedback_schema_status_year_and_transmission_preserved(namespace, status, expected):
    result = classify_rf1086_feedback(feedback(namespace=namespace, status=status).encode(), forsendelse_id=TRANSMISSION, income_year=2025)
    assert (result.classification, result.schema, result.transmission_id) == (expected, RF1086_FEEDBACK_NAMESPACES[namespace], TRANSMISSION)


def test_optional_relationship_fields_remain_optional_and_namespace_prefix_and_xml_entities_work():
    # The frozen classifier permits absent optional fields; this is not a new
    # schema/jurisdiction decision made by the relocation.
    xml = feedback(reference=None, year=None).replace("godkjent", "godkj&#101;nt")
    assert classify_rf1086_feedback(xml.encode(), forsendelse_id=TRANSMISSION, income_year=2025).classification == "accepted"
    import re
    prefixed = re.sub(r"<(\/?)(\w+)", r"<\1rf:\2", feedback()).replace('xmlns="', 'xmlns:rf="')
    assert classify_rf1086_feedback(prefixed.encode(), forsendelse_id=TRANSMISSION, income_year=2025).classification == "accepted"


@pytest.mark.parametrize("xml", [
    feedback(namespace="urn:unknown"), feedback(status="ukjent"), feedback(reference=DOCUMENT), feedback(year=2024),
    feedback(extra="<leveransestatus>godkjent</leveransestatus>"),
    feedback(extra=f"<innsending><forsendelseid>{TRANSMISSION}</forsendelseid></innsending>"),
    feedback(extra="<leveranse><inntektsaar>2025</inntektsaar></leveranse>"),
    feedback().replace("<leveranse>", "<wrapper><leveranse>").replace("</leveranse>", "</leveranse></wrapper>"),
    feedback().replace("<leveransestatus>", '<leveransestatus xmlns="urn:foreign">'),
    feedback().replace("godkjent", "<![CDATA[godkjent]]>"),
    feedback().replace("godkjent", "<nested>godkjent</nested>"),
    feedback().replace("godkjent", " " * 501 + "godkjent"),
    feedback().replace("<leveransestatus>godkjent</leveransestatus>", ""),
    feedback().replace("</tilbakemelding>", ""),
    '<!DOCTYPE x [<!ENTITY steal SYSTEM "file:///does-not-exist">]>' + feedback().replace("godkjent", "&steal;"),
    feedback(extra='<other xmlns="urn:foreign"/>'),
    feedback().replace("tilbakemelding", "wrongroot"),
])
def test_ambiguous_malformed_or_unrelated_feedback_never_accepts(xml):
    assert classify_rf1086_feedback(xml.encode(), forsendelse_id=TRANSMISSION, income_year=2025).classification == "action_required"


@pytest.mark.parametrize("data,reference,year", [(b"", TRANSMISSION, 2025), (b"\xff", TRANSMISSION, 2025),
    (b"x" * (10 * 1024 * 1024 + 1), TRANSMISSION, 2025), (feedback().encode(), "", 2025),
    (feedback().encode(), TRANSMISSION, 2025.5)], ids=["empty", "invalid-utf8", "oversize", "missing-reference", "invalid-year"])
def test_feedback_byte_and_context_bounds(data, reference, year):
    result = classify_rf1086_feedback(data, forsendelse_id=reference, income_year=year)
    assert (result.classification, result.schema, result.transmission_id) == ("action_required", "unknown", None)


class FeedbackJournal:
    def __init__(self, state="sent", failure=None):
        self.snapshot = Rf1086ReconciliationSnapshot(state)
        self.artifacts = {}
        self.events = []
        self.failure = failure

    async def read_reconciliation_state(self):
        return self.snapshot

    async def record_artifact(self, artifact):
        if self.failure:
            raise self.failure
        assert artifact.byte_length == len(artifact.bytes) and artifact.sha256 == sha(artifact.bytes)
        self.artifacts.setdefault(artifact.sha256, artifact)
        return artifact.sha256

    async def append_reconciliation(self, event):
        changed = event != self.snapshot
        if changed:
            self.events.append(event)
            self.snapshot = event
        return changed


class ReadOnlyArchive:
    """Deliberately has no mutation methods, even as test stubs."""
    def __init__(self, pages=(), documents=None):
        self.pages = list(pages) or [page()]
        self.documents = documents or {}
        self.calls = []

    async def list_documents(self, **arguments):
        self.calls.append(("list", arguments))
        result = self.pages.pop(0) if len(self.pages) > 1 else self.pages[0]
        if isinstance(result, Exception):
            raise result
        return result

    async def get_document(self, **arguments):
        self.calls.append(("get", arguments))
        result = self.documents[arguments["document_id"]]
        if isinstance(result, Exception):
            raise result
        return result


def reconcile(journal, authority, **options):
    sleeps = []
    async def sleep(milliseconds):
        sleeps.append(milliseconds)
    result = asyncio.run(reconcile_journaled_rf1086_production(journal, authority, RECONCILIATION, sleep=sleep, **options))
    return result, sleeps


def test_initial_poll_is_five_iterations_with_two_second_delays_and_owner_retry_is_one_read():
    journal, authority = FeedbackJournal(), ReadOnlyArchive()
    result, sleeps = reconcile(journal, authority)
    assert (result.state, result.archive_reads, result.artifact_count, result.changed) == ("processing", 5, 0, True)
    assert sleeps == [2000] * 4
    retry, sleeps = reconcile(journal, authority)
    assert (retry.state, retry.archive_reads, retry.changed) == ("processing", 1, False)
    assert len(authority.calls) == 6 and sleeps == [] and len(journal.events) == 1


def test_poll_iteration_includes_all_document_gets_and_filters_only_exact_submitted_bytes():
    accepted = feedback().encode()
    documents = {DOCUMENT: Rf1086AuthorityDocument(DOCUMENT, "application/xml", MAIN_XML.encode()),
                 DIALOG: Rf1086AuthorityDocument(DIALOG, "text/xml", accepted)}
    # Two empty iterations, then two per-document GETs: GET count exceeds poll count.
    authority = ReadOnlyArchive([page(), page(), page([Rf1086DocumentReference(DOCUMENT), Rf1086DocumentReference(DIALOG)])], documents)
    journal = FeedbackJournal()
    result, sleeps = reconcile(journal, authority)
    assert (result.state, result.archive_reads, result.artifact_count) == ("accepted", 3, 1)
    assert sleeps == [2000, 2000] and [kind for kind, _ in authority.calls] == ["list", "list", "list", "get", "get"]
    assert all(call[1].get("forsendelse_id", call[1].get("reference_id")) == TRANSMISSION for call in authority.calls)
    artifact = next(iter(journal.artifacts.values()))
    assert artifact.bytes == accepted and artifact.authority_reference == DIALOG
    assert artifact.company_id == "company" and artifact.submission_id == "submission"
    assert accepted.decode() not in repr(artifact)
    repeated, _ = reconcile(journal, authority, initial_poll=False)
    assert repeated.artifact_hashes == (sha(accepted),) and not repeated.changed
    assert len(journal.artifacts) == 1 and len(journal.events) == 1


@pytest.mark.parametrize("documents,state,code", [
    ([feedback()], "accepted", "RF1086_FEEDBACK_ACCEPTED"),
    ([feedback(status="avvist")], "rejected", "RF1086_FEEDBACK_REJECTED"),
    ([feedback(), feedback(status="avvist")], "action_required", "RF1086_FEEDBACK_CONFLICT"),
    ([feedback(), "<unknown/>"], "action_required", "RF1086_FEEDBACK_ACTION_REQUIRED"),
    ([MAIN_XML, SUB_XML, "<B/>"], "processing", None),
])
def test_archive_classification_combines_all_feedback_without_confusing_submitted_xml(documents, state, code):
    result, _ = reconcile(FeedbackJournal("processing"), ReadOnlyArchive([page(documents)]))
    assert (result.state, result.safe_error_code) == (state, code)
    assert result.artifact_count == len({sha(doc) for doc in documents} - {sha(MAIN_XML), sha(SUB_XML), sha("<B/>")})


@pytest.mark.parametrize("changes", [{"document_shape_valid": False}, {"current_page": 1}, {"total_pages": 2}, {"total_items": 2}])
def test_incomplete_or_invalid_archive_page_stops_before_document_get_or_persistence(changes):
    journal, authority = FeedbackJournal(), ReadOnlyArchive([page([Rf1086DocumentReference(DOCUMENT)], **changes)])
    result, sleeps = reconcile(journal, authority)
    assert (result.state, result.safe_error_code, result.archive_reads) == ("action_required", "RF1086_ARCHIVE_SHAPE_INVALID", 1)
    assert not journal.artifacts and len(authority.calls) == 1 and not sleeps


@pytest.mark.parametrize("error,state,code", [
    (Rf1086AuthorityError("GLD_021", status=404), "processing", None),
    (Rf1086AuthorityError("GLD_1017", status=404), "processing", None),
    (Rf1086AuthorityError("RF1086_NETWORK_ERROR", retryable=True), "unknown", "RF1086_NETWORK_ERROR"),
    (Rf1086AuthorityError("GLD_004", status=503, retryable=True), "unknown", "GLD_004"),
    (Rf1086AuthorityError("GLD_005", status=403), "action_required", "GLD_005"),
    (RuntimeError("raw private response"), "unknown", "RF1086_RECONCILIATION_READ_ERROR"),
])
@pytest.mark.parametrize("operation", ["list", "get"])
def test_read_failure_classification_is_safe_and_cannot_mutate_provider(error, state, code, operation):
    archive = (ReadOnlyArchive([error]) if operation == "list" else
        ReadOnlyArchive([page([Rf1086DocumentReference(DOCUMENT)])], {DOCUMENT: error}))
    result, sleeps = reconcile(FeedbackJournal("processing"), archive)
    assert (result.state, result.safe_error_code, result.archive_reads) == (state, code, 1)
    assert "raw private" not in repr(result) and not sleeps


@pytest.mark.parametrize("failure,state,code", [
    (Rf1086FeedbackArtifactPersistenceError(retryable=True), "unknown", "RF1086_FEEDBACK_ARTIFACT_PERSIST_RETRY"),
    (Rf1086FeedbackArtifactPersistenceError(retryable=False), "action_required", "RF1086_FEEDBACK_ARTIFACT_PERSIST_FAILED"),
    (RuntimeError("raw storage details"), "action_required", "RF1086_FEEDBACK_ARTIFACT_PERSIST_FAILED"),
])
def test_feedback_must_be_persisted_before_it_can_become_final(failure, state, code):
    result, _ = reconcile(FeedbackJournal(failure=failure), ReadOnlyArchive([page([feedback()])]))
    assert (result.state, result.safe_error_code, result.artifact_count) == (state, code, 0)


@pytest.mark.parametrize("code,retryable", [(None, True), ("08006", True), ("PGRST000", True), ("PGRST001", True),
    ("PGRST002", True), ("PGRST003", True), ("pgrst116", False), ("23505", False), ("22000", False),
    ("3F000", False), ("42P01", False), ("P0001", False)])
def test_frozen_storage_error_classification(code, retryable):
    assert create_rf1086_feedback_artifact_persistence_error({"code": code}).retryable is retryable
    assert not create_rf1086_feedback_artifact_persistence_error({"code": code}, integrity_failure=True).retryable


def test_non_xml_document_is_retained_and_requires_action():
    authority = ReadOnlyArchive([page([Rf1086DocumentReference(DOCUMENT)])],
        {DOCUMENT: Rf1086AuthorityDocument(DOCUMENT, "application/pdf", b"%PDF private artifact")})
    journal = FeedbackJournal()
    result, _ = reconcile(journal, authority)
    assert result.state == "action_required" and result.artifact_count == 1
    assert next(iter(journal.artifacts.values())).content_type == "application/pdf"


def test_extra_xml_root_is_action_required_without_using_parser_diagnostic_as_a_filing_decision():
    # Saxes continues after a malformed second root; Expat stops at it. Their
    # diagnostic schema labels differ, but neither permits acceptance. Only
    # classification is consumed by the frozen journal, never schema metadata.
    result = classify_rf1086_feedback((feedback() + "<second/>").encode(), forsendelse_id=TRANSMISSION, income_year=2025)
    assert result.classification == "action_required"


from datetime import UTC, datetime, timedelta
from talli_backend.modules.shareholder_register_filing.public import Rf1086ProductionError, Rf1086Approval, Rf1086Connection, Rf1086Preview, Rf1086Submission
from talli_backend.application.shareholder_register_filing_session import Rf1086MutationBinding, Rf1086ReadOnlyBinding
from talli_backend.application.shareholder_register_filing_workflow import reconcile_rf1086_production, send_approved_rf1086_production_filing
from talli_backend.modules.shareholder_register_filing.production import rf1086_current_manifest, rf1086_current_manifest_hash, rf1086_preview_payload_hash
from talli_backend.modules.billing.public import (
    BillingEntitlementDecision, BillingObligation, BillingPilotCaseProfile, BillingSnapshot, BillingStatus,
    ProductionPilotEntitlement, ProductionPilotEntitlementId, ProductionPilotStatus, SystemUserRequestReference,
)
from talli_backend.modules.company_access.public import CompanyAccessRecord
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, Timestamp, UserId


OWNER = "60000000-0000-4000-8000-000000000006"
COMPANY = "70000000-0000-4000-8000-000000000007"
APPROVAL = "80000000-0000-4000-8000-000000000008"
ENTITLEMENT = "90000000-0000-4000-8000-000000000009"
PREVIEW = "a0000000-0000-4000-8000-00000000000a"
REQUEST = "b0000000-0000-4000-8000-00000000000b"
SUBMISSION = "c0000000-0000-4000-8000-00000000000c"
NOW = datetime(2026, 9, 9, 12, tzinfo=UTC)


class BillingQueries:
    def __init__(self, events):
        self.events = events
        self.pilot = ProductionPilotEntitlement(ProductionPilotEntitlementId(ENTITLEMENT), CompanyId(COMPANY), UserId(OWNER),
            IncomeYear(2025), BillingObligation.SHAREHOLDER_REGISTER, BillingPilotCaseProfile.RF1086_NO_ACTIVITY_V1,
            ProductionPilotStatus.ACTIVE, True, SystemUserRequestReference(REQUEST), "A" * 43,
            Timestamp(NOW - timedelta(days=1)), Timestamp(NOW + timedelta(days=1)), "approved-test-evidence", UserId(OWNER), Timestamp(NOW), Timestamp(NOW))
        self.decision = BillingEntitlementDecision(CompanyId(COMPANY), IncomeYear(2025), BillingObligation.SHAREHOLDER_REGISTER,
            BillingStatus.PILOT_ENTITLEMENT_ACTIVE, True, False, True, True, "", ProductionPilotEntitlementId(ENTITLEMENT))

    async def snapshot(self, query):
        self.events.append("billing_snapshot")
        assert query.company_ids == (CompanyId(COMPANY),) and str(query.actor_id.subject) == OWNER
        return BillingSnapshot((), (), (self.pilot,))

    async def entitlement(self, query):
        self.events.append("billing_entitlement")
        assert query.company_id == CompanyId(COMPANY) and int(query.income_year) == 2025
        assert query.obligation == BillingObligation.SHAREHOLDER_REGISTER and query.case_profile == "rf1086_no_activity_v1"
        return self.decision


class CoordinatorDiscovery:
    async def read_feedback_transmissions(self, *, organization_number, dialog_id, forsendelse_id):
        assert (organization_number, dialog_id, forsendelse_id) == ("310279617", DIALOG, TRANSMISSION)
        return (Rf1086FeedbackTransmission(DIALOG, DOCUMENT, TRANSMISSION, NOW.isoformat(), (DOCUMENT,), "Acceptance"),)


class CoordinatorSession:
    def __init__(self):
        self.events = []
        self.actor_id = ActorId(ActorKind.USER, UserId(OWNER))
        self.billing = BillingQueries(self.events)
        self.preview = Rf1086Preview(PREVIEW, COMPANY, 2025, "aksjonaerregisteroppgaven", MAIN_XML, {MAIN: SUB_XML, DOCUMENT: "<B/>"}, ("Advarsel ø",))
        self.company = CompanyAccessRecord(id=COMPANY, org_number="310279617", name="Fixture AS", entity_type="AS",
            address="Test", postal_code="0150", city="Oslo", status_text="aktiv", source="test", created_by=OWNER,
            identity_confirmed_at=None, identity_locked_at=None, created_at=NOW.isoformat(), role="owner")
        self.approval = Rf1086Approval(APPROVAL, ENTITLEMENT, PREVIEW, COMPANY, OWNER, 2025,
            "aksjonaerregisteroppgaven", "rf1086_no_activity_v1", False,
            rf1086_current_manifest_hash(self.preview, actor_id=OWNER, organization_number=self.company.org_number),
            rf1086_current_manifest(self.preview, actor_id=OWNER, organization_number=self.company.org_number))
        self.submission = Rf1086Submission(SUBMISSION, APPROVAL, ENTITLEMENT, COMPANY, OWNER, 2025,
            "aksjonaerregisteroppgaven", "rf1086_no_activity_v1", "production", "processing")
        self.connection = Rf1086Connection(REQUEST, COMPANY, OWNER, "aksjonaerregisteroppgaven", "A" * 43, "accepted", True)
        self.operations = OperationJournal()
        self.journal = FeedbackJournal()
        self.mutation_authority = Authority()
        self.read_only_authority = ReadOnlyArchive([page([feedback()])],
            {DOCUMENT: Rf1086AuthorityDocument(DOCUMENT, "application/xml", feedback().encode())})
        self.discovery = CoordinatorDiscovery()
        self.failure = None
        self.busy = False
        self.reference = TRANSMISSION

    def event(self, name):
        self.events.append(name)
        if self.failure == name:
            raise Rf1086ProductionError("configuration_unavailable" if name == "configuration" else "status_unavailable")

    def require_configuration(self): self.event("configuration")
    async def read_approval(self, value):
        self.event("approval")
        assert value == APPROVAL
        return self.approval
    async def read_preview(self, value):
        self.event("preview")
        assert value == PREVIEW
        return self.preview
    async def read_submission(self, value):
        self.event("submission")
        assert value == SUBMISSION
        return self.submission
    async def company_record(self, value):
        self.event("company")
        assert value == COMPANY
        return self.company
    async def read_connection(self, request_id, company_id):
        self.event("connection")
        assert request_id == REQUEST and company_id == COMPANY
        return self.connection
    async def require_fresh_production_owner(self, value):
        self.event("fresh_mfa")
        assert value == COMPANY
    def discard(self): self.events.append("discard")
    async def bind_mutation_authority(self, company, connection):
        self.event("mutation_token")
        assert company == self.company and connection == self.connection
        return Rf1086MutationBinding(self.mutation_authority, self.read_only_authority, self.discard, self.discovery)
    async def bind_read_only_authority(self, company, connection):
        self.event("recovery_token")
        return Rf1086ReadOnlyBinding(self.read_only_authority, self.discard, self.discovery)
    async def begin_production_filing(self, value):
        self.event("begin")
        assert value == APPROVAL
        return SUBMISSION
    def operation_journal(self, value):
        self.event("operation_journal")
        assert value == SUBMISSION
        return self.operations
    async def claim_feedback_lease(self, submission_id, lease_id):
        self.event("claim")
        self.lease = lease_id
        assert submission_id == SUBMISSION and UUID(lease_id).version == 4
        return not self.busy
    async def read_claimed_reference(self, submission_id, lease_id):
        self.event("reference")
        assert submission_id == SUBMISSION and lease_id == self.lease
        return self.reference
    async def read_claimed_dialog_id(self, submission_id, lease_id):
        self.event("dialog")
        assert submission_id == SUBMISSION and lease_id == self.lease
        return DIALOG
    async def release_feedback_lease(self, submission_id, lease_id):
        self.event("release")
        assert submission_id == SUBMISSION and lease_id == self.lease
    def feedback_journal(self, **arguments):
        self.event("feedback_journal")
        assert arguments == dict(submission_id=SUBMISSION, company_id=COMPANY, income_year=2025,
            forsendelse_id=TRANSMISSION, lease_id=self.lease)
        return self.journal


def send(session):
    return asyncio.run(send_approved_rf1086_production_filing(session, APPROVAL))


def recover(session):
    return asyncio.run(reconcile_rf1086_production(session, SUBMISSION))


def test_authenticated_send_preserves_gate_order_token_before_begin_and_finally_discard():
    session = CoordinatorSession()
    result = send(session)
    assert result.submission_id == SUBMISSION
    assert session.events == ["configuration", "approval", "fresh_mfa", "preview", "billing_snapshot", "billing_entitlement",
        "company", "connection", "mutation_token", "begin", "operation_journal", "claim", "reference", "feedback_journal", "release", "discard"]
    assert session.mutation_authority.calls[0][1]["xml"] == MAIN_XML
    assert session.journal.snapshot.state == "accepted"


@pytest.mark.parametrize("stage", ["configuration", "fresh_mfa", "mutation_token", "begin", "reference", "feedback_journal"])
def test_send_failures_stop_at_expected_gate_and_release_resources(stage):
    session = CoordinatorSession()
    session.failure = stage
    with pytest.raises(Rf1086ProductionError):
        send(session)
    if stage in {"configuration", "fresh_mfa", "mutation_token"}:
        assert "begin" not in session.events and not session.mutation_authority.calls
    if stage in {"begin", "reference", "feedback_journal"}:
        assert session.events[-1] == "discard"
    if stage in {"reference", "feedback_journal"}:
        assert "release" in session.events


def test_repeated_owner_send_uses_original_journal_and_never_reposts_unknown_mutation():
    session = CoordinatorSession()
    session.mutation_authority.main_error = Rf1086AuthorityError("RF1086_NETWORK_ERROR", retryable=True)
    for _ in range(2):
        with pytest.raises(Rf1086ProductionError, match="send_unavailable"):
            send(session)
    assert len(session.mutation_authority.calls) == 1
    assert session.events.count("begin") == 2 and session.events.count("discard") == 2


@pytest.mark.parametrize("change,code", [
    (lambda s: setattr(s, "approval", replace(s.approval, invalidated=True)), "approval_expired"),
    (lambda s: setattr(s.billing, "decision", replace(s.billing.decision, allowed=False)), "basis_unavailable"),
    (lambda s: setattr(s.billing, "decision", replace(s.billing.decision, pilot_entitlement_id=ProductionPilotEntitlementId(DOCUMENT))), "basis_unavailable"),
    (lambda s: setattr(s, "connection", replace(s.connection, external_ref="B" * 43)), "connection_unavailable"),
    (lambda s: setattr(s, "connection", replace(s.connection, status="rejected")), "connection_unavailable"),
    (lambda s: setattr(s, "connection", replace(s.connection, preflight_verified=False)), "connection_unavailable"),
    (lambda s: setattr(s, "preview", replace(s.preview, hovedskjema_xml=MAIN_XML + " ")), "payload_changed"),
])
def test_send_rejects_invalid_basis_before_any_token_or_submission(change, code):
    session = CoordinatorSession()
    change(session)
    with pytest.raises(Rf1086ProductionError, match=code):
        send(session)
    assert "mutation_token" not in session.events and "begin" not in session.events


def test_recovery_preserves_expired_entitlement_invalidated_approval_without_new_mfa_or_release_gate():
    session = CoordinatorSession()
    session.approval = replace(session.approval, invalidated=True)
    session.billing.pilot = replace(session.billing.pilot, expires_at=Timestamp(NOW-timedelta(days=1)), status=ProductionPilotStatus.REVOKED)
    session.billing.decision = replace(session.billing.decision, allowed=False)
    result = recover(session)
    assert result.state == "accepted" and result.error_code is None and not result.requires_manual_retry
    assert session.events == ["submission", "company", "approval", "billing_snapshot", "connection", "preview", "configuration",
        "claim", "reference", "dialog", "recovery_token", "feedback_journal", "discard", "release"]
    assert not session.mutation_authority.calls


@pytest.mark.parametrize("state", ["accepted", "rejected"])
def test_terminal_recovery_returns_stored_state_before_configuration_or_new_eligibility(state):
    session = CoordinatorSession()
    session.submission = replace(session.submission, feedback_state=state)
    session.failure = "configuration"
    result = recover(session)
    assert result.state == state and not result.requires_manual_retry and result.error_code is None
    assert session.events == ["submission"]


def test_busy_recovery_lease_performs_no_provider_call_or_release_of_another_lease():
    session = CoordinatorSession()
    session.busy = True
    result = recover(session)
    assert (result.state, result.error_code, result.requires_manual_retry) == ("processing", "status_busy", True)
    assert "recovery_token" not in session.events and "release" not in session.events


@pytest.mark.parametrize("stage", ["reference", "recovery_token", "feedback_journal"])
def test_recovery_failure_always_releases_only_claimed_lease_and_discards_acquired_token(stage):
    session = CoordinatorSession()
    session.failure = stage
    result = recover(session)
    assert result.error_code == "status_unavailable" and result.requires_manual_retry
    assert session.events[-1] == "release"
    assert ("discard" in session.events) is (stage == "feedback_journal")
    assert not session.mutation_authority.calls


@pytest.mark.parametrize("change,code", [
    (lambda s: setattr(s, "submission", replace(s.submission, user_id=DOCUMENT)), "basis_unavailable"),
    (lambda s: setattr(s, "submission", replace(s.submission, environment="test")), "basis_unavailable"),
    (lambda s: setattr(s, "approval", replace(s.approval, company_id=DOCUMENT)), "basis_unavailable"),
    (lambda s: setattr(s, "approval", replace(s.approval, income_year=2024)), "basis_unavailable"),
    (lambda s: setattr(s, "approval", replace(s.approval, entitlement_id=DOCUMENT)), "basis_unavailable"),
    (lambda s: setattr(s.billing, "pilot", replace(s.billing.pilot, user_id=UserId(DOCUMENT))), "basis_unavailable"),
    (lambda s: setattr(s, "company", s.company.model_copy(update={"role": "reviewer"})), "basis_unavailable"),
    (lambda s: setattr(s, "connection", replace(s.connection, initiating_owner_user_id=DOCUMENT)), "connection_unavailable"),
    (lambda s: setattr(s, "connection", replace(s.connection, external_ref="B" * 43)), "connection_unavailable"),
    (lambda s: setattr(s, "connection", replace(s.connection, preflight_verified=False)), "connection_unavailable"),
    (lambda s: setattr(s, "preview", replace(s.preview, company_id=DOCUMENT)), "connection_unavailable"),
    (lambda s: setattr(s, "preview", replace(s.preview, income_year=2024)), "connection_unavailable"),
])
@pytest.mark.parametrize("state", ["processing", "action_required"])
def test_recovery_exact_relationship_mismatch_is_rejected_before_claim_or_token(change, code, state):
    session = CoordinatorSession()
    session.submission = replace(session.submission, feedback_state=state)
    change(session)
    result = recover(session)
    assert result.error_code == code and result.requires_manual_retry
    assert "claim" not in session.events and "recovery_token" not in session.events


def test_original_confirmed_reference_cannot_be_replaced_during_initial_reconciliation():
    session = CoordinatorSession()
    session.reference = DOCUMENT
    with pytest.raises(Rf1086ProductionError, match="send_unavailable"):
        send(session)
    assert not session.read_only_authority.calls
    assert session.events[-2:] == ["release", "discard"]


def test_js_json_and_immutable_approval_order_match_original_source_across_character_sets():
    import json
    from pathlib import Path
    from talli_backend.modules.shareholder_register_filing.production import _json, rf1086_production_document_order
    golden = json.loads((Path(__file__).parent / "fixtures/rf1086-production-91b.json").read_text())
    assert golden["source_commit"] == "91b178c281bcc5fb887a6257d2f72e380199f3e6"
    previews = [Rf1086Preview(**{key: value for key, value in row.items() if key != "actor_id"})
                for row in golden["inputs"]]
    expected = golden["expected"]
    for preview, vector in zip(previews, expected, strict=True):
        assert rf1086_preview_payload_hash(preview) == vector["payloadHash"]
        assert rf1086_current_manifest_hash(preview, actor_id=OWNER, organization_number="310279617",
            approved_manifest=vector["manifest"]) == vector["hash"]
        authority = Authority()
        execute(OperationJournal(), authority, JournaledRf1086ProductionInput("explicit-test-order", 2025,
            preview.hovedskjema_xml, preview.underskjema_xml, tuple(vector["order"])))
        assert [arguments["xml"] for name, arguments in authority.calls if name == "sub"] == [
            preview.underskjema_xml[name] for name in vector["order"]]
    assert list(previews[3].underskjema_xml) != expected[3]["order"]
    assert rf1086_production_document_order(previews[-1]) == tuple(expected[-1]["order"])
    assert _json({"unpaired": "\ud800", "paired": "\ud83d\ude00"}) == '{"unpaired":"\\ud800","paired":"😀"}'


@pytest.mark.parametrize("names", [("a",), (" A ",), ("é", "e\u0301"), ("😀",), ("10", "2"),
    (MAIN.upper().replace("000000000001", "00000000000A"),)],
    ids=["arbitrary-id", "trimmed-name", "unicode", "astral", "numeric", "uppercase-uuid"])
def test_noncanonical_stored_production_keys_fail_before_token_begin_or_provider_effect(names):
    session = CoordinatorSession()
    session.preview = replace(session.preview, underskjema_xml={name: SUB_XML for name in names})
    with pytest.raises(Rf1086ProductionError) as caught:
        asyncio.run(send_approved_rf1086_production_filing(session, APPROVAL))
    assert caught.value.code == "payload_changed"
    assert "mutation_token" not in session.events and "begin" not in session.events
    assert not session.mutation_authority.calls


@pytest.mark.parametrize("change", ["identity", "warning", "missing-document", "duplicate-document", "digest", "extra-field", "missing-manifest"])
def test_current_payload_cannot_reuse_a_changed_or_incomplete_approval_manifest(change):
    from talli_backend.modules.shareholder_register_filing.production import _js_object
    session = CoordinatorSession()
    manifest = _js_object(session.approval.manifest)
    if change == "identity": manifest["companyId"] = str(uuid4())
    elif change == "warning": manifest["warnings"] = []
    elif change == "missing-document": manifest["documentHashes"].pop()
    elif change == "duplicate-document": manifest["documentHashes"][1] = manifest["documentHashes"][0]
    elif change == "digest": manifest["documentHashes"][0]["sha256"] = "0" * 64
    elif change == "extra-field": manifest["injected"] = True
    elif change == "missing-manifest": manifest = None
    session.approval = replace(session.approval, manifest=manifest)
    with pytest.raises(Rf1086ProductionError) as caught:
        asyncio.run(send_approved_rf1086_production_filing(session, APPROVAL))
    assert caught.value.code == "payload_changed"
    assert "mutation_token" not in session.events and "begin" not in session.events
    assert not session.mutation_authority.calls


@pytest.mark.parametrize("order", [("founder_a",), ("founder_a", "founder_a"), ("founder_a", "extra")])
def test_generic_journal_requires_explicit_complete_unique_order_before_any_effect(order):
    journal, authority = OperationJournal(), Authority()
    with pytest.raises(ValueError, match="RF1086_DOCUMENT_ORDER_INVALID"):
        execute(journal, authority, replace(INPUT, document_order=order))
    assert not authority.calls and not journal.events


@pytest.mark.parametrize("text,expected", [
    ("<archive>\ud800</archive>", "<archive>\ufffd</archive>"),
    ("<archive>\udc00</archive>", "<archive>\ufffd</archive>"),
    ("<archive>\ud83d\ude00</archive>", "<archive>😀</archive>"),
], ids=["unpaired-high", "unpaired-low", "valid-pair"])
def test_inline_archive_textencoder_replacement_is_stored_before_unknown_schema_decision(text, expected):
    journal = FeedbackJournal()
    result, _ = reconcile(journal, ReadOnlyArchive([page([text])]))
    assert result.state == "action_required" and result.artifact_count == 1
    assert len(journal.artifacts) == 1 and len(journal.events) == 1
    artifact = next(iter(journal.artifacts.values()))
    assert artifact.bytes == expected.encode('utf-8') and artifact.sha256 == sha(expected)
    assert artifact.authority_reference == "inline:" + artifact.sha256


@pytest.mark.parametrize("operation", ["send", "reconcile"])
def test_authenticated_workflow_rejects_another_actor_before_any_read_or_effect(operation):
    from talli_backend.application.shareholder_register_filing_workflow import ShareholderRegisterFilingWorkflow
    from talli_backend.modules.shareholder_register_filing.public import (
        ApprovalId, ReconcileRf1086FeedbackCommand, SendApprovedRf1086Command, SubmissionId,
    )
    from talli_backend.shared.kernel import CorrelationId
    session = CoordinatorSession()
    other = ActorId(ActorKind.USER, UserId(str(uuid4())))
    workflow = ShareholderRegisterFilingWorkflow(session)
    command = (SendApprovedRf1086Command(ApprovalId(APPROVAL), other, CorrelationId(str(uuid4())))
        if operation == "send" else ReconcileRf1086FeedbackCommand(SubmissionId(SUBMISSION), other, CorrelationId(str(uuid4()))))
    with pytest.raises(Rf1086ProductionError, match="authentication_required"):
        asyncio.run(workflow.send_approved_filing(command) if operation == "send" else workflow.reconcile_feedback(command))
    assert not session.events and not session.mutation_authority.calls
    assert workflow.actor_id == session.actor_id


def test_approved_payload_is_recursively_immutable_without_changing_original_hash():
    session = CoordinatorSession()
    manifest = session.approval.manifest
    assert isinstance(manifest["documentHashes"], tuple)
    with pytest.raises(TypeError):
        manifest["documentHashes"][0]["sha256"] = "0" * 64
    with pytest.raises(TypeError):
        session.preview.underskjema_xml[MAIN] = "<changed/>"
    assert rf1086_current_manifest_hash(session.preview, actor_id=OWNER, organization_number="310279617",
        approved_manifest=manifest) == session.approval.manifest_hash


def test_action_required_recovers_only_by_reading_original_confirmation():
    session = CoordinatorSession()
    session.submission = replace(session.submission, feedback_state="action_required")
    session.journal.snapshot = Rf1086ReconciliationSnapshot("action_required", safe_error_code="GLD_005")
    session.approval = replace(session.approval, invalidated=True)
    session.billing.pilot = replace(session.billing.pilot, status=ProductionPilotStatus.REVOKED)
    result = recover(session)
    assert result.state == "accepted" and result.error_code is None
    assert "reference" in session.events and "dialog" in session.events
    assert "recovery_token" in session.events and "mutation_token" not in session.events
    assert "begin" not in session.events and not session.mutation_authority.calls
    assert session.events[-2:] == ["discard", "release"]


def test_action_required_recovery_failure_preserves_status_and_manual_retry():
    session = CoordinatorSession()
    session.submission = replace(session.submission, feedback_state="action_required")
    session.failure = "configuration"
    result = recover(session)
    assert (result.state, result.error_code, result.requires_manual_retry) == (
        "action_required", "configuration_unavailable", True)
    assert "claim" not in session.events and not session.mutation_authority.calls
