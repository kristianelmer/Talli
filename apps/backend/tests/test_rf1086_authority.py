"""Five fixed RF HTTP templates, exercised only through httpx.MockTransport."""

import asyncio
import hashlib
import json
from dataclasses import replace

import httpx
import pytest

from talli_backend.adapters.maskinporten import MaskinportenAccessToken, SYSTEM_USER_TAX_SCOPE
from talli_backend.adapters.rf1086_authority import Rf1086AuthorityAdapter, Rf1086ReadOnlyAuthorityAdapter
from talli_backend.compatibility.rf1086_authority_workflow import Rf1086AuthorityError, Rf1086DocumentReference


MAIN = "10000000-0000-4000-8000-000000000001"
DIALOG = "20000000-0000-4000-8000-000000000002"
TRANSMISSION = "30000000-0000-4000-8000-000000000003"
DOCUMENT = "40000000-0000-4000-8000-000000000004"
KEY = "50000000-0000-4000-8000-000000000005"
SECRET = "SECRET_UNIQUE_PROVIDER_TOKEN"
BASE = "https://api-test.sits.no/api/aksjonaerregister/v1"
XML = "\ufeff \n<H>Æø &amp; original</H>\r\n"


def token(**changes):
    return replace(MaskinportenAccessToken(SECRET, "Bearer", 120, SYSTEM_USER_TAX_SCOPE, "test"), **changes)


def adapter(response=None, handler=None, *, readonly=False, **changes):
    seen = []
    def respond(request):
        seen.append(request)
        return handler(request) if handler else response
    arguments = {"environment": "test", "transport": httpx.MockTransport(respond)} | changes
    return (Rf1086ReadOnlyAuthorityAdapter if readonly else Rf1086AuthorityAdapter)(token(environment=arguments["environment"]), **arguments), seen


def call(client, operation="list", **changes):
    method, arguments = {
        "main": (client.post_hovedskjema if hasattr(client, "post_hovedskjema") else None,
            {"income_year": 2025, "xml": XML, "idempotency_key": KEY}),
        "sub": (client.post_underskjema if hasattr(client, "post_underskjema") else None,
            {"income_year": 2025, "hovedskjema_id": MAIN, "xml": XML, "idempotency_key": KEY}),
        "confirm": (client.confirm if hasattr(client, "confirm") else None,
            {"income_year": 2025, "hovedskjema_id": MAIN, "underskjema_count": 2, "idempotency_key": KEY}),
        "list": (client.list_documents, {"income_year": 2025, "reference_id": TRANSMISSION}),
        "get": (client.get_document, {"income_year": 2025, "forsendelse_id": TRANSMISSION, "document_id": DOCUMENT}),
    }[operation]
    return asyncio.run(method(**(arguments | changes)))


def test_five_exact_templates_send_original_bytes_and_keys_and_fixed_headers_without_exposing_token():
    responses = [httpx.Response(201, json={"hovedskjemaId": MAIN}), httpx.Response(204),
        httpx.Response(200, json={"oppgavegiversLeveranseReferanse": "delivery", "dialogId": DIALOG, "forsendelseId": TRANSMISSION}),
        httpx.Response(200, json={"dokumenter": [{"dokumentId": DOCUMENT}]}),
        httpx.Response(200, content=b"<feedback/>", headers={"content-type": "Text/XML; charset=utf-8"})]
    client, seen = adapter(handler=lambda _: responses.pop(0))
    results = [call(client, operation) for operation in ["main", "sub", "confirm", "list", "get"]]
    assert [(request.method, str(request.url)) for request in seen] == [
        ("POST", BASE + "/2025/1086H"), ("POST", BASE + f"/2025/{MAIN}/1086U"),
        ("POST", BASE + f"/2025/{MAIN}/bekreft?antall_underskjema=2"),
        ("GET", BASE + f"/2025/forsendelser/{TRANSMISSION}/dokumenter?page=0&size=50"),
        ("GET", BASE + f"/2025/forsendelser/{TRANSMISSION}/dokumenter/{DOCUMENT}"),
    ]
    assert [request.content for request in seen] == [XML.encode(), XML.encode(), b"", b"", b""]
    assert all(request.headers["authorization"] == "Bearer " + SECRET for request in seen)
    assert all(request.headers["idempotencykey"] == KEY for request in seen[:3])
    assert all("idempotencykey" not in request.headers for request in seen[3:])
    assert seen[0].headers["content-type"] == seen[1].headers["content-type"] == "application/xml"
    assert "content-type" not in seen[2].headers
    assert all(request.headers["accept"] == "application/json" for request in seen[:4])
    assert seen[4].headers["accept"] == "application/xml, text/xml, application/pdf, text/plain, application/octet-stream"
    assert results[0].call.body_hash == results[1].call.body_hash == hashlib.sha256(XML.encode()).hexdigest()
    assert results[2].call.body_hash == results[3].call.body_hash == hashlib.sha256(b"").hexdigest()
    assert results[0].hovedskjema_id == MAIN and results[2].forsendelse_id == TRANSMISSION
    assert results[3].documents == (Rf1086DocumentReference(DOCUMENT),)
    assert results[4].bytes == b"<feedback/>" and results[4].content_type == "text/xml"
    assert SECRET not in repr(results) and SECRET not in repr(client)


def test_production_default_is_the_single_fixed_production_host_and_discard_invalidates_existing_adapter():
    seen = []
    credential = token(environment="production")
    def respond(request):
        seen.append(request)
        return httpx.Response(200, json={"dokumenter": []})
    client = Rf1086AuthorityAdapter(credential, transport=httpx.MockTransport(respond))
    call(client)
    assert str(seen[0].url).startswith("https://api.skatteetaten.no/api/aksjonaerregister/v1/")
    credential.discard()
    with pytest.raises(ValueError, match="RF1086_TOKEN_INVALID"):
        call(client)
    assert len(seen) == 1


def test_reconciliation_adapter_has_only_two_public_business_operations():
    client, seen = adapter(httpx.Response(200, json={"dokumenter": []}), readonly=True)
    assert {name for name in dir(client) if not name.startswith("_")} == {"list_documents", "get_document"}
    call(client)
    assert seen[0].method == "GET"


@pytest.mark.parametrize("changes", [{"environment": "https://other.invalid"}, {"environment": "tt02"},
    {"timeout_ms": 999}, {"timeout_ms": 120001}, {"timeout_ms": True}, {"timeout_ms": 1000.5}])
def test_invalid_transport_configuration_fails_closed(changes):
    with pytest.raises(ValueError):
        Rf1086AuthorityAdapter(token(), **({"environment": "test"} | changes))


@pytest.mark.parametrize("changes", [{"access_token": ""}, {"access_token": " secret"}, {"access_token": "secret\n"},
    {"access_token": "bad\x00token"}, {"access_token": "非ASCII"}, {"access_token": "x" * 8193},
    {"scope": "other:scope"}, {"scope": SYSTEM_USER_TAX_SCOPE + " extra"}, {"environment": "production"}, {"token_type": "Basic"}])
def test_wrong_token_scope_environment_or_opaque_value_is_rejected(changes):
    with pytest.raises(ValueError, match="RF1086_TOKEN_INVALID") as caught:
        Rf1086AuthorityAdapter(token(**changes), environment="test")
    assert SECRET not in repr(caught.value)


@pytest.mark.parametrize("operation,changes", [
    ("main", {"income_year": 1999}), ("sub", {"income_year": 2101}), ("confirm", {"income_year": 2025.5}),
    ("list", {"income_year": True}), ("get", {"income_year": "2025/other"}),
    ("main", {"xml": "not xml"}), ("sub", {"xml": " "}), ("main", {"xml": None}),
    ("main", {"idempotency_key": "not-uuid"}), ("sub", {"idempotency_key": ""}),
    ("confirm", {"idempotency_key": KEY + "?override"}), ("sub", {"hovedskjema_id": "../" + MAIN}),
    ("confirm", {"hovedskjema_id": "https://other.invalid"}), ("confirm", {"underskjema_count": 0}),
    ("confirm", {"underskjema_count": True}), ("confirm", {"underskjema_count": 1.2}),
    ("list", {"reference_id": TRANSMISSION + "/../"}), ("list", {"page": -1}), ("list", {"size": 51}),
    ("list", {"page": True}), ("list", {"size": 0}), ("get", {"forsendelse_id": DOCUMENT + "?q=x"}),
    ("get", {"document_id": DOCUMENT + "#x"}), ("get", {"document_id": None}),
])
def test_bad_template_parameters_rejected_before_network(operation, changes):
    client, seen = adapter()
    with pytest.raises(ValueError):
        call(client, operation, **changes)
    assert not seen


@pytest.mark.parametrize("field", ["hovedskjemaId", "hovedskjemaid"])
def test_existing_main_id_aliases_remain_supported(field):
    client, _ = adapter(httpx.Response(200, json={field: MAIN}))
    assert call(client, "main").hovedskjema_id == MAIN


@pytest.mark.parametrize("operation,data", [("main", {}), ("main", {"hovedskjemaId": "unsafe-reference"}),
    ("confirm", {"dialogId": DIALOG}), ("confirm", {"dialogId": "bad", "forsendelseId": TRANSMISSION})])
def test_success_status_cannot_supply_invalid_authority_identity(operation, data):
    client, _ = adapter(httpx.Response(200, json=data))
    with pytest.raises(ValueError, match="RF1086_UUID_INVALID"):
        call(client, operation)


@pytest.mark.parametrize("data,expected_valid,count", [
    ({"dokumenter": []}, True, 0),
    ({"dokumenter": [" <inline/>", {"documentId": DOCUMENT}]}, True, 2),
    ({"dokumenter": [{"dokumentId": DOCUMENT, "extra": 1}]}, False, 0),
    ({"dokumenter": [{"href": "https://other.invalid"}]}, False, 0),
    ({"dokumenter": ["", " ", 1, None, {"dokumentId": "bad"}]}, False, 0),
    ({}, False, 0), ({"dokumenter": {}}, False, 0),
    ({"dokumenter": ["<a/>"], "totalItems": 0}, False, 1),
    ({"dokumenter": [], "currentPage": -1}, False, 0),
    ({"dokumenter": [], "totalPages": 0.5}, False, 0),
    ({"dokumenter": [], "totalItems": "Infinity"}, False, 0),
    ({"dokumenter": ["<a/>"], "totalItems": "1", "totalPages": "0x1", "currentPage": "0"}, True, 1),
])
def test_archive_projection_preserves_strict_reference_shapes_and_pagination(data, expected_valid, count):
    client, _ = adapter(httpx.Response(200, json=data))
    result = call(client)
    assert result.document_shape_valid is expected_valid and len(result.documents) == count


@pytest.mark.parametrize("status,code,retryable", [(400, "GLD_005", False), (401, "GLD_005", True),
    (408, "GLD_005", True), (425, "GLD_005", True), (429, "GLD_005", True), (500, "GLD_005", True),
    (400, "GLD_004", True), (404, "GLD_021", False)])
def test_original_http_retry_classification_and_only_safe_diagnostics(status, code, retryable):
    client, _ = adapter(httpx.Response(status, json={"kode": code, "korrelasjonsid": "corr-001",
        "melding": "original XML " + SECRET, "spesifisering": [{"kode": "GLD_1017", "melding": SECRET,
        "sti": "private.taxpayer.value", "angittVerdi": "private value"}]}))
    with pytest.raises(Rf1086AuthorityError) as caught:
        call(client)
    error = caught.value
    assert (error.code, error.status, error.retryable, error.correlation_id, error.specification_codes) == (
        code, status, retryable, "corr-001", ("GLD_1017",))
    assert str(error) == code and SECRET not in repr(vars(error)) and "private" not in repr(error)


@pytest.mark.parametrize("unsafe", [SECRET, "contains whitespace", "injected\ncorrelation", "https://private.invalid/", "x" * 501])
def test_provider_code_and_correlation_cannot_leak_raw_secrets_or_unbounded_values(unsafe):
    client, _ = adapter(httpx.Response(400, json={"kode": unsafe, "korrelasjonsid": unsafe,
        "spesifisering": [{"kode": unsafe}]}))
    with pytest.raises(Rf1086AuthorityError) as caught:
        call(client)
    assert caught.value.code == "RF1086_HTTP_400"
    assert caught.value.correlation_id is None and not caught.value.specification_codes


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("operation", ["main", "get"])
def test_redirect_is_not_followed_or_retried_and_mutation_outcome_stays_unknown(status, operation):
    client, seen = adapter(httpx.Response(status, headers={"location": "https://other.invalid/secret"}))
    with pytest.raises(Rf1086AuthorityError) as caught:
        call(client, operation)
    assert (caught.value.code, caught.value.status, caught.value.retryable) == ("RF1086_NETWORK_ERROR", None, True)
    assert len(seen) == 1 and SECRET not in str(caught.value)


@pytest.mark.parametrize("operation", ["main", "get"])
def test_network_failure_is_unknown_and_does_not_retain_request_or_original_error(operation):
    def failed(request):
        raise httpx.ConnectError("raw token " + SECRET, request=request)
    client, seen = adapter(handler=failed)
    with pytest.raises(Rf1086AuthorityError) as caught:
        call(client, operation)
    assert (caught.value.status, caught.value.code, caught.value.retryable) == (None, "RF1086_NETWORK_ERROR", True)
    assert SECRET not in repr(caught.value) and caught.value.__cause__ is None and len(seen) == 1


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks, *, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            self.reads += 1
            yield chunk

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("operation,maximum,mime,code", [("list", 65536, "application/json", "RF1086_JSON_TOO_LARGE"),
    ("get", 10485760, "application/xml", "RF1086_DOCUMENT_TOO_LARGE")])
@pytest.mark.parametrize("stated", [False, True])
def test_decoded_response_bounds_stop_stream_and_close_it(operation, maximum, mime, code, stated):
    stream = Chunks([b"x" * maximum, b"x", b"must-not-read"])
    headers = {"content-type": mime} | ({"content-length": str(maximum + 1)} if stated else {})
    client, _ = adapter(httpx.Response(200, stream=stream, headers=headers))
    with pytest.raises(Rf1086AuthorityError) as caught:
        call(client, operation)
    assert (caught.value.code, caught.value.status, caught.value.retryable) == (code, 200, False)
    assert stream.closed and stream.reads == (0 if stated else 2)


def test_json_limit_counts_decoded_compressed_bytes_and_document_exact_limit_is_allowed():
    import gzip
    client, _ = adapter(httpx.Response(200, content=gzip.compress(b" " * 65537),
        headers={"content-encoding": "gzip", "content-type": "application/json"}))
    with pytest.raises(Rf1086AuthorityError, match="RF1086_JSON_TOO_LARGE"):
        call(client)
    client, _ = adapter(httpx.Response(200, content=b"x" * 10485760, headers={"content-type": "application/octet-stream"}))
    assert len(call(client, "get").bytes) == 10485760


def test_overall_timeout_covers_response_stream_and_closes_without_replay():
    stream = Chunks([b"{}"], delay=1.1)
    client, seen = adapter(httpx.Response(200, stream=stream, headers={"content-type": "application/json"}), timeout_ms=1000)
    with pytest.raises(Rf1086AuthorityError) as caught:
        call(client, "main")
    assert (caught.value.code, caught.value.status, caught.value.retryable) == ("RF1086_NETWORK_ERROR", None, True)
    assert stream.closed and not stream.reads and len(seen) == 1


@pytest.mark.parametrize("content,mime,code", [(b"{}", "text/html", "RF1086_JSON_CONTENT_TYPE"),
    (b"{}", "", "RF1086_JSON_CONTENT_TYPE"), (b"not json", "application/json", "RF1086_JSON_INVALID"),
    (b"\xff", "application/json", "RF1086_JSON_INVALID"), (b"NaN", "application/json", "RF1086_JSON_INVALID"),
    (b"Infinity", "application/json", "RF1086_JSON_INVALID")])
def test_invalid_json_mime_utf8_and_syntax_fail_closed(content, mime, code):
    client, _ = adapter(httpx.Response(200, content=content, headers={"content-type": mime}))
    with pytest.raises(Rf1086AuthorityError, match=code):
        call(client)


@pytest.mark.parametrize("mime", ["application/json", "application/problem+json", "Application/JSON; charset=UTF-8"])
def test_json_mime_allowlist_and_original_textdecoder_bom_handling(mime):
    client, _ = adapter(httpx.Response(200, content=b'\xef\xbb\xbf{"dokumenter":[]}', headers={"content-type": mime}))
    assert call(client).document_shape_valid


def test_empty_204_without_mime_and_malformed_error_response_keep_original_classification():
    client, _ = adapter(httpx.Response(204))
    assert call(client, "sub").call.status == "accepted"
    client, _ = adapter(httpx.Response(503, content=b"not json", headers={"content-type": "application/json"}))
    with pytest.raises(Rf1086AuthorityError) as caught:
        call(client)
    assert caught.value.code == "RF1086_HTTP_503" and caught.value.retryable


@pytest.mark.parametrize("mime", ["application/xml", "text/xml", "application/pdf", "text/plain", "application/octet-stream"])
def test_document_bytes_are_preserved_for_every_existing_mime(mime):
    raw = b"\x00\xff original artifact"
    client, _ = adapter(httpx.Response(200, content=raw, headers={"content-type": mime}))
    document = call(client, "get")
    assert document.bytes == raw and document.content_type == mime and document.reference == DOCUMENT


@pytest.mark.parametrize("raw,mime,code", [(b"<html/>", "text/html", "RF1086_DOCUMENT_CONTENT_TYPE"),
    (b"{}", "application/json", "RF1086_DOCUMENT_CONTENT_TYPE"), (b"x", "", "RF1086_DOCUMENT_CONTENT_TYPE"),
    (b"", "application/xml", "RF1086_DOCUMENT_EMPTY")])
def test_document_disallowed_mime_and_empty_body_cannot_be_accepted(raw, mime, code):
    client, _ = adapter(httpx.Response(200, content=raw, headers={"content-type": mime}))
    with pytest.raises(Rf1086AuthorityError, match=code):
        call(client, "get")


from datetime import UTC, datetime
from types import SimpleNamespace
from talli_backend.adapters.postgres_legacy_rf1086_authority import PostgresLegacyRf1086AuthoritySession, _PersistenceError
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration, _VerifiedActor
from talli_backend.compatibility.rf1086_authority_workflow import Rf1086FeedbackArtifactPersistenceError, Rf1086ReconciliationArtifact
from talli_backend.modules.documents.public import DocumentId, DocumentRecord, DocumentStatus, DocumentUploadTransfer, DocumentsError
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId


ACTOR = ActorId(ActorKind.USER, UserId("60000000-0000-4000-8000-000000000006"))
COMPANY_ID = "70000000-0000-4000-8000-000000000007"
SUBMISSION_ID = "80000000-0000-4000-8000-000000000008"
ARTIFACT_BYTES = b"<feedback>original bytes</feedback>"
ARTIFACT = Rf1086ReconciliationArtifact(SUBMISSION_ID, COMPANY_ID, DOCUMENT, "application/xml",
    ARTIFACT_BYTES, len(ARTIFACT_BYTES), hashlib.sha256(ARTIFACT_BYTES).hexdigest(), "accepted")


class DocumentsFactory:
    actor_id = ACTOR
    def __init__(self):
        self.events = []
        self.records = {}
        self.final_hash = ARTIFACT.sha256
        self.cleanup_error = None
    async def session(self, access_token):
        assert access_token == "verified-owner-session"
        self.events.append(("session",))
        return self
    async def begin_upload(self, command):
        self.events.append(("stage", command))
        storage_key = f"{command.company_id}/{int(command.income_year)}/{command.document_id}/{command.file_name}"
        record = DocumentRecord(command.document_id, command.company_id, command.income_year,
            command.document_type, command.file_name, command.linked_to, DocumentStatus.STAGED, 5, storage_key,
            command.content_type, None, None, ACTOR, datetime(2026, 9, 9, tzinfo=UTC), None, None)
        self.records[str(command.document_id)] = record
        return DocumentUploadTransfer(record, "company-documents", storage_key, "private-signed-upload-token", "https://unused.invalid")
    async def finalize_upload(self, document_id):
        self.events.append(("finalize", str(document_id)))
        result = replace(self.records[str(document_id)], status=DocumentStatus.STORED,
            byte_length=ARTIFACT.byte_length, content_sha256=self.final_hash)
        self.records[str(document_id)] = result
        return result
    async def remove_document(self, document_id, *, reason):
        self.events.append(("remove", str(document_id), reason))
        if self.cleanup_error:
            raise self.cleanup_error
        self.records.pop(str(document_id))


def feedback_store(*, existing=(), metadata_error=None, response_status=200):
    documents, uploads, rows, identities = DocumentsFactory(), [], [], []
    def upload(request):
        uploads.append(request)
        return httpx.Response(response_status, headers={"location": "https://other.invalid"})
    session = PostgresLegacyRf1086AuthoritySession(LedgerSupabaseConfiguration("https://project.example.test", "", ""),
        _VerifiedActor(ACTOR, json.dumps({"sub": str(ACTOR.subject), "role": "authenticated"})),
        access_token="verified-owner-session", billing=None, documents=documents, company_access=None,
        storage_transport=httpx.MockTransport(upload))
    reads = list(existing)
    async def query(statement, parameters=()):
        rows.append((statement, parameters))
        if statement.startswith("select document_id,sha256"):
            result = reads.pop(0) if reads else None
            if isinstance(result, Exception):
                raise result
            return [result] if result else []
        assert statement.startswith("select id from public.record_production_feedback_artifact")
        if metadata_error:
            raise metadata_error
        return [{"id": MAIN}]
    session._rows = query
    journal = session.feedback_journal(submission_id=SUBMISSION_ID, company_id=COMPANY_ID, income_year=2025,
        forsendelse_id=TRANSMISSION, lease_id=KEY)
    original_session = journal._document_session
    async def bound_session(operation, kind):
        identities.append(operation.key)
        return await original_session(operation, kind)
    journal._document_session = bound_session
    return journal, documents, uploads, rows, identities


def test_receipt_uses_owned_documents_stage_signed_upload_finalize_and_original_operation_keys():
    journal, documents, uploads, rows, identities = feedback_store()
    assert asyncio.run(journal.record_artifact(ARTIFACT)) == ARTIFACT.sha256
    stage = next(event[1] for event in documents.events if event[0] == "stage")
    document_id = str(stage.document_id)
    assert stage.company_id == CompanyId(COMPANY_ID) and int(stage.income_year) == 2025
    assert stage.document_type == "authority_feedback" and stage.final_status is DocumentStatus.STORED
    assert stage.linked_to == "production_filing_submission:" + SUBMISSION_ID
    assert stage.file_name == "authority-feedback-" + ARTIFACT.sha256[:12] + ".xml"
    assert stage.header == ARTIFACT_BYTES[:5] and stage.byte_length == len(ARTIFACT_BYTES)
    assert identities == ["rf1086-feedback-stage:" + document_id, "rf1086-feedback-finalize:" + document_id]
    assert len(uploads) == 1 and uploads[0].method == "PUT" and uploads[0].content == ARTIFACT_BYTES
    assert str(uploads[0].url).startswith(f"https://project.example.test/storage/v1/object/upload/sign/company-documents/{COMPANY_ID}/2025/{document_id}/")
    assert uploads[0].url.params["token"] == "private-signed-upload-token"
    assert uploads[0].headers["x-upsert"] == "false" and "authorization" not in uploads[0].headers
    assert rows[-1][1] == (COMPANY_ID, SUBMISSION_ID, document_id, DOCUMENT, "application/xml", len(ARTIFACT_BYTES), ARTIFACT.sha256, "accepted")
    assert documents.records[document_id].status is DocumentStatus.STORED


def test_existing_canonical_artifact_is_reused_without_another_document_or_upload():
    journal, documents, uploads, _, _ = feedback_store(existing=[{"document_id": DOCUMENT, "sha256": ARTIFACT.sha256}])
    assert asyncio.run(journal.record_artifact(ARTIFACT)) == ARTIFACT.sha256
    assert not documents.events and not uploads


def test_ambiguous_metadata_readback_retains_uploaded_receipt_for_safe_retry():
    journal, documents, uploads, _, _ = feedback_store(existing=[None, _PersistenceError("08006")], metadata_error=_PersistenceError("08006"))
    with pytest.raises(Rf1086FeedbackArtifactPersistenceError) as caught:
        asyncio.run(journal.record_artifact(ARTIFACT))
    assert caught.value.retryable and len(uploads) == 1 and len(documents.records) == 1
    assert not any(event[0] == "remove" for event in documents.events)


@pytest.mark.parametrize("canonical_matches", [False, True])
def test_metadata_commit_readback_preserves_canonical_receipt_and_cleans_only_losing_attempt(canonical_matches):
    journal, documents, _, _, identities = feedback_store(metadata_error=_PersistenceError("08006"))
    count = 0
    async def existing(_):
        nonlocal count
        count += 1
        if count == 1:
            return None
        created_id = next(iter(documents.records))
        return {"document_id": created_id if canonical_matches else DOCUMENT, "sha256": ARTIFACT.sha256}
    journal._existing = existing
    assert asyncio.run(journal.record_artifact(ARTIFACT)) == ARTIFACT.sha256
    removals = [event for event in documents.events if event[0] == "remove"]
    assert len(removals) == (0 if canonical_matches else 1)
    if removals:
        assert removals[0][1] != DOCUMENT and removals[0][2] == "producer_rollback"
        assert identities[-1] == "rf1086-feedback-cleanup:" + removals[0][1]


@pytest.mark.parametrize("code,retryable", [("08006", True), ("23505", False)])
def test_authoritative_metadata_absence_cleans_attempt_and_preserves_error_classification(code, retryable):
    journal, documents, _, _, _ = feedback_store(existing=[None, None], metadata_error=_PersistenceError(code))
    with pytest.raises(Rf1086FeedbackArtifactPersistenceError) as caught:
        asyncio.run(journal.record_artifact(ARTIFACT))
    assert caught.value.retryable is retryable and not documents.records
    assert [event[2] for event in documents.events if event[0] == "remove"] == ["producer_rollback"]


def test_final_document_integrity_mismatch_cleans_only_created_document_and_never_commits_metadata():
    journal, documents, _, rows, _ = feedback_store()
    documents.final_hash = "0" * 64
    with pytest.raises(Rf1086FeedbackArtifactPersistenceError) as caught:
        asyncio.run(journal.record_artifact(ARTIFACT))
    assert not caught.value.retryable and not documents.records
    assert len(rows) == 1


def test_failed_cleanup_does_not_claim_receipt_absent_or_final_success():
    journal, documents, _, _, _ = feedback_store(metadata_error=_PersistenceError("23505"))
    documents.cleanup_error = DocumentsError.storage_unavailable()
    with pytest.raises(Rf1086FeedbackArtifactPersistenceError) as caught:
        asyncio.run(journal.record_artifact(ARTIFACT))
    assert caught.value.retryable and len(documents.records) == 1


def test_signed_upload_redirect_is_not_followed_and_does_not_finalize_or_write_artifact_metadata():
    journal, documents, uploads, rows, _ = feedback_store(response_status=307)
    with pytest.raises(DocumentsError):
        asyncio.run(journal.record_artifact(ARTIFACT))
    assert len(uploads) == 1 and len(rows) == 1
    assert not any(event[0] in {"finalize", "remove"} for event in documents.events)


def test_persistence_operation_prepare_preserves_latest_key_attempt_and_exact_submission_binding():
    actor = _VerifiedActor(ACTOR, "{}")
    session = PostgresLegacyRf1086AuthoritySession(LedgerSupabaseConfiguration("", "", ""), actor,
        access_token="", billing=None, documents=None, company_access=None)
    calls = []
    async def rows(query, parameters):
        calls.append((query, parameters))
        return [{"id": MAIN, "operation_name": "post_hovedskjema", "operation_state": "failed", "attempt": 19,
            "body_hash": ARTIFACT.sha256, "idempotency_key": KEY, "authority_reference": None,
            "failure_class": "retryable", "newly_prepared": False}]
    session._rows = rows
    journal = session.operation_journal(SUBMISSION_ID)
    operation = asyncio.run(journal.prepare(submission_id=SUBMISSION_ID, name="post_hovedskjema",
        body_hash=ARTIFACT.sha256, idempotency_key=DOCUMENT))
    assert operation.idempotency_key == KEY and operation.attempt == 20 and operation.body_hash == ARTIFACT.sha256
    assert calls[0][1] == (SUBMISSION_ID, "post_hovedskjema", ARTIFACT.sha256, DOCUMENT)
    with pytest.raises(Exception, match="basis_unavailable"):
        asyncio.run(journal.prepare(submission_id=DOCUMENT, name="post_hovedskjema", body_hash=ARTIFACT.sha256, idempotency_key=KEY))
    assert len(calls) == 1


def test_shared_rf_http_keeps_fatal_textdecoder_for_invalid_utf8_inside_json_strings():
    client, seen = adapter(httpx.Response(200, content=b'{"dokumenter":[],"ignored":"\xff"}', headers={"content-type":"application/json"}))
    with pytest.raises(Rf1086AuthorityError, match="RF1086_JSON_INVALID"):
        call(client)
    assert len(seen) == 1


@pytest.mark.parametrize("xml,expected", [("<H>\ud800</H>", "<H>\ufffd</H>"), ("<H>\ud83d\ude00</H>", "<H>😀</H>")], ids=["unpaired", "paired"])
def test_outgoing_textencoder_bytes_and_call_hash_agree_on_surrogate_replacement(xml, expected):
    client, seen = adapter(httpx.Response(200, json={"hovedskjemaId": MAIN}))
    result = call(client, "main", xml=xml)
    assert seen[0].content == expected.encode("utf-8")
    assert result.call.body_hash == hashlib.sha256(seen[0].content).hexdigest()
