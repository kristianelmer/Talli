"""Actual V6 route/workflow composition with explicit persistence/Documents doubles."""
from dataclasses import replace
from io import BytesIO
import json

import pytest
from fastapi.testclient import TestClient

from talli_backend.application import shareholder_register_archive as stream
from talli_backend.main import create_app
from talli_backend.shared.kernel import ActorKind
from talli_backend.modules.documents.public import DocumentsError
from talli_backend.modules.shareholder_register_filing import public as rf
from rf1086_retained_stream_fixture import ACTOR, DocumentsFactory, retained_stream_fixture
from test_rf1086_archive_storage_v6 import forbid_fresh

ROUTE = '/api/v1/shareholder-register-filings/archive-source/production-stream-v6'


def client(archive, originals, *, persistence_error=None, document_actor=ACTOR):
    traces = []
    class Session:
        actor_id = ACTOR
        async def archive_source(self, query):
            traces.append(('archive', query))
            if persistence_error is not None: raise persistence_error
            return archive
    class Sessions:
        async def session(self, token):
            traces.append(('session', token))
            return Session()
    documents = DocumentsFactory(originals, actor_id=document_actor)
    app = create_app(shareholder_register_filing_session_factory=Sessions(), documents_session_factory=documents)
    return TestClient(app), traces, documents


def params(archive):
    return {'companyId': str(archive.company_id), 'incomeYear': int(archive.income_year)}


@pytest.mark.parametrize('kind', ['cash_issue', 'loss_covering_reduction'])
@pytest.mark.parametrize('amendments', [0, 1, 2])
def test_retained_http_path_exports_all_capture_sections_and_exact_originals(kind, amendments, monkeypatch):
    archive, originals = retained_stream_fixture(kind, amendments, 'accepted', legacy=True, independent=True)
    forbid_fresh(monkeypatch)
    http, traces, documents = client(archive, originals)
    response = http.get(ROUTE, params=params(archive), headers={'Authorization': 'Bearer token'})
    assert response.status_code == 200, response.text
    query = rf.Rf1086ArchiveQuery(archive.company_id, archive.income_year, ACTOR)
    restored, sources, feedback = stream.verify_retained_archive_stream(BytesIO(response.content), query=query,
        require_feedback_originals=True)
    assert len(restored.source_history.year_sources) == 2
    assert len(restored.withdrawal_capture_records) == amendments and restored.overrides == ()
    assert sources + feedback == len(originals)
    assert traces == [('session', 'token'), ('archive', query)]
    assert documents.sessions == ['token'] and len(documents.reads) == len(originals)
    assert response.headers['content-type'] == 'application/x-ndjson'
    assert response.headers['cache-control'] == 'no-store'  # Existing RequestContextMiddleware policy.
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['content-disposition'] == f'attachment; filename="rf1086-{archive.company_id}-{int(archive.income_year)}.ndjson"'
    assert json.loads(response.content.splitlines()[0])['codec'] == stream.RETAINED_STREAM_CODEC


def test_unauthenticated_and_invalid_scope_do_not_open_persistence_or_documents():
    archive, originals = retained_stream_fixture()
    http, traces, documents = client(archive, originals)
    assert http.get(ROUTE, params=params(archive)).status_code == 401
    for changes in ({'companyId': 'invalid'}, {'incomeYear': 1999}, {'incomeYear': 2101}):
        assert http.get(ROUTE, params=params(archive) | changes, headers={'Authorization': 'Bearer token'}).status_code == 422
    assert traces == documents.sessions == documents.reads == []


@pytest.mark.parametrize('failure,status', [(rf.ShareholderRegisterFilingError.forbidden(), 403),
    (rf.ShareholderRegisterFilingError.not_found(), 404), (rf.ShareholderRegisterFilingError.unavailable(), 503)])
def test_member_access_and_dependency_errors_precede_documents_without_private_text(failure, status):
    archive, originals = retained_stream_fixture()
    http, traces, documents = client(archive, originals, persistence_error=failure)
    response = http.get(ROUTE, params=params(archive), headers={'Authorization': 'Bearer token'})
    assert response.status_code == status
    assert documents.sessions == documents.reads == []
    assert 'canonicalArchive' not in response.text and 'contentBase64' not in response.text


@pytest.mark.parametrize('field', ['source_history', 'overrides', 'withdrawal_capture_records'])
def test_missing_capture_is_unavailable_before_headers_or_documents(field):
    archive, originals = retained_stream_fixture()
    http, traces, documents = client(replace(archive, **{field: None}), originals)
    response = http.get(ROUTE, params=params(archive), headers={'Authorization': 'Bearer token'})
    assert response.status_code == 503 and 'application/problem+json' in response.headers['content-type']
    assert documents.sessions == documents.reads == []


def test_wrong_documents_actor_fails_before_stream_and_no_originals_are_read():
    archive, originals = retained_stream_fixture()
    http, traces, documents = client(archive, originals, document_actor=replace(ACTOR, kind=ActorKind.SYSTEM))
    response = http.get(ROUTE, params=params(archive), headers={'Authorization': 'Bearer token'})
    assert response.status_code == 503
    assert documents.sessions == ['token'] and documents.reads == []
