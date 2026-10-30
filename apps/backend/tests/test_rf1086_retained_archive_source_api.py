"""Additive V6 JSON source for company exports; no SQL/Auth/blob-store execution."""
from dataclasses import replace
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from talli_backend.application import shareholder_register_archive as stream
from talli_backend.main import create_app
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorKind
from rf1086_retained_stream_fixture import ACTOR, DocumentsFactory, retained_stream_fixture
from test_rf1086_archive_storage_v6 import forbid_fresh

ROUTE = "/api/v1/shareholder-register-filings/archive-source/production-v6"
OLD_ROUTE = "/api/v1/shareholder-register-filings/archive-source/production-v4"
HEADERS = {"Authorization": "Bearer synthetic-retained-json"}


def client(archive, originals, *, document_actor=ACTOR, persistence_error=None):
    calls = []

    class Session:
        actor_id = ACTOR

        async def archive_source(self, query):
            calls.append(("archive", query))
            if persistence_error is not None:
                raise persistence_error
            return archive

    class Sessions:
        async def session(self, token):
            calls.append(("session", token))
            return Session()

    documents = DocumentsFactory(originals, actor_id=document_actor)
    app = create_app(shareholder_register_filing_session_factory=Sessions(), documents_session_factory=documents)
    return TestClient(app), calls, documents


def params(archive):
    return {"companyId": str(archive.company_id), "incomeYear": int(archive.income_year)}


@pytest.mark.parametrize("status", ["accepted", "rejected", "unapproved"])
def test_current_v2_source_is_exported_by_v6_while_v4_stays_closed(status):
    archive, originals = retained_stream_fixture(amendments=1, status=status, legacy=True, independent=True)
    http, _, _ = client(archive, originals)
    response = http.get(ROUTE, params=params(archive), headers=HEADERS)
    assert response.status_code == 200, response.text
    assert http.get(OLD_ROUTE, params=params(archive), headers=HEADERS).status_code == 503
    value = response.json()
    query = rf.Rf1086ArchiveQuery(archive.company_id, archive.income_year, ACTOR)
    assert json.loads(value["canonicalArchive"])["codec"] == "rf1086-production-archive-v6"
    restored = rf.parse_rf1086_retained_archive(value["canonicalArchive"], query=query)
    assert restored == archive
    assert restored.withdrawal_capture_records == archive.withdrawal_capture_records
    assert len(restored.withdrawal_capture_records) == 1
    assert type(restored.source_history.year_sources[-1]) is rf.Rf1086YearSourceSnapshotV2
    source_originals = stream.verify_source_originals(archive, value["sourceOriginals"])
    feedback = stream.verify_feedback_originals(archive, value["feedbackOriginals"], require_complete=True)
    assert len(source_originals) + len(feedback) == len(originals)
    assert len(value["sourceHistoryDocuments"]) == len(stream.source_document_evidence(archive))
    assert len(value["sourceApprovalLineage"]) == len(archive.source_approval_lineage)
    for actual, retained in zip(value["sourceApprovalLineage"], archive.source_approval_lineage, strict=True):
        assert actual["manifestText"] == retained.manifest_text
        assert actual["manifestSha256"] == retained.manifest_sha256
        assert json.loads(actual["manifestText"])["schemaVersion"] == "production-source-approval-v3"
        command = actual["source"]["command"]
        assert command["completeYearConfirmed"] == retained.source.command.complete_year_confirmed
        assert command["supersedesSourceId"] == retained.source.command.supersedes_source_id.value
        assert actual["sourcePreview"]["renderingProfile"] == retained.source_preview.rendering_profile
    assert response.headers["cache-control"] == "no-store"


def test_v6_reads_retained_evidence_without_rebuilding_fresh_admission(monkeypatch):
    archive, originals = retained_stream_fixture(status="accepted")
    forbid_fresh(monkeypatch)
    http, calls, _ = client(archive, originals)
    response = http.get(ROUTE, params=params(archive), headers=HEADERS)
    assert response.status_code == 200, response.text
    assert [kind for kind, _ in calls] == ["session", "archive"]


def test_unauthenticated_and_invalid_scope_do_not_open_persistence_or_documents():
    archive, originals = retained_stream_fixture()
    http, calls, documents = client(archive, originals)
    assert http.get(ROUTE, params=params(archive)).status_code == 401
    assert http.get(ROUTE, params={**params(archive), "incomeYear": 1999}, headers=HEADERS).status_code == 422
    assert calls == documents.sessions == documents.reads == []


@pytest.mark.parametrize("field", ["source_history", "overrides", "withdrawal_capture_records"])
def test_missing_complete_capture_fails_before_originals(field):
    archive, originals = retained_stream_fixture()
    http, _, documents = client(replace(archive, **{field: None}), originals)
    response = http.get(ROUTE, params=params(archive), headers=HEADERS)
    assert response.status_code == 503
    assert documents.sessions == documents.reads == []
    assert "canonicalArchive" not in response.text


def test_documents_actor_mismatch_fails_before_any_original_is_read():
    archive, originals = retained_stream_fixture()
    http, _, documents = client(archive, originals, document_actor=replace(ACTOR, kind=ActorKind.SYSTEM))
    response = http.get(ROUTE, params=params(archive), headers=HEADERS)
    assert response.status_code == 503
    assert documents.sessions == ["synthetic-retained-json"] and documents.reads == []
    assert "canonicalArchive" not in response.text


def test_v6_capture_fields_are_required_even_when_their_values_can_be_empty():
    from talli_backend.main import Rf1086ProductionArchiveSourceV6Wire

    archive, originals = retained_stream_fixture(status="accepted")
    http, _, _ = client(archive, originals)
    value = http.get(ROUTE, params=params(archive), headers=HEADERS).json()
    for field in ("canonicalArchive", "sourceHistoryDocuments"):
        missing = {key: child for key, child in value.items() if key != field}
        with pytest.raises(ValidationError):
            Rf1086ProductionArchiveSourceV6Wire.model_validate(missing)
