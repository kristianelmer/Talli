"""Streaming archive completeness, bounded reads, authorization and byte integrity."""
import asyncio
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from talli_backend.application import shareholder_register_archive as composition
from talli_backend.main import create_app
from talli_backend.modules.documents.public import DocumentsError
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_archive_originals import DocumentsFactory, source_archive, ACTOR, CONTENT
from test_rf1086_feedback_archive_originals import feedback_archive, DocumentsFactory as FeedbackDocuments
from test_rf1086_archive_source import production_snapshot, ACTOR as FEEDBACK_ACTOR


def query(archive, actor_id=ACTOR):
    return rf.Rf1086ArchiveQuery(archive.company_id, archive.income_year, actor_id)


async def prepared(archive, factory=None, actor_id=ACTOR):
    return await composition.prepare_archive_stream(archive, query=query(archive, actor_id),
        documents_factory=factory or DocumentsFactory(), access_token='token', actor_id=actor_id)


def download(archive=None, factory=None, actor_id=ACTOR):
    archive = archive or source_archive()
    async def run():
        stream = await prepared(archive, factory, actor_id)
        return b''.join([chunk async for chunk in stream])
    return asyncio.run(run())


def verify(content, archive=None, **kwargs):
    return composition.verify_archive_stream(BytesIO(content), query=query(archive or source_archive()), **kwargs)


def reseal(rows):
    chunks = [(json.dumps(row, separators=(',', ':')) + '\n').encode() for row in rows[:-1]]
    rows[-1]['sha256'] = sha256(b''.join(chunks)).hexdigest()
    return b''.join(chunks) + (json.dumps(rows[-1]) + '\n').encode()


def test_source_stream_preserves_exact_prior_year_original_and_canonical_record():
    archive = source_archive()
    content = download(archive)
    restored, sources, feedback = verify(content, archive)
    assert restored == archive and (sources, feedback) == (1, 0)
    rows = [json.loads(line) for line in content.splitlines()]
    assert rows[1]['original']['sourceIncomeYear'] == 2024
    assert rows[-1] == {'kind': 'complete', 'sourceOriginals': 1, 'feedbackOriginals': 0,
        'sha256': sha256(b''.join(content.splitlines(keepends=True)[:-1])).hexdigest()}


def test_feedback_stream_preserves_original_binding_and_attribution():
    archive, original = feedback_archive()
    content = download(archive, FeedbackDocuments(original), FEEDBACK_ACTOR)
    assert verify(content, archive, require_feedback_originals=True) == (archive, 0, 1)


def test_legacy_feedback_cannot_be_claimed_complete():
    archive = production_snapshot()
    content = download(archive)
    assert verify(content, archive) == (archive, 0, 0)
    with pytest.raises(DocumentsError): verify(content, archive, require_feedback_originals=True)


def test_stream_bypasses_only_inline_aggregate_limit(monkeypatch):
    archive = source_archive()
    monkeypatch.setattr(composition, 'MAX_SOURCE_ORIGINAL_BYTES', len(CONTENT) - 1)
    with pytest.raises(DocumentsError): composition.source_original_queries(archive)
    assert verify(download(archive), archive)[1] == 1
    monkeypatch.setattr(composition, 'MAX_STREAM_ORIGINAL_BYTES', len(CONTENT) - 1)
    with pytest.raises(rf.ShareholderRegisterFilingError): download(archive)


@pytest.mark.parametrize('change', ['truncated-header', 'truncated-original', 'missing-footer', 'truncated-footer',
    'trailing-newline', 'trailing-data', 'digest', 'duplicate-original', 'missing-original', 'wrong-kind',
    'company', 'year', 'bytes', 'metadata', 'unknown-field', 'bool-length', 'bool-count', 'duplicate-key', 'codec'])
def test_corruption_or_incomplete_transfer_fails_even_if_resealed(change):
    content = download()
    rows = [json.loads(line) for line in content.splitlines()]
    if change == 'truncated-header': content = content[:20]
    elif change == 'truncated-original': content = content.splitlines(keepends=True)[0] + b'{"kind":'
    elif change == 'missing-footer': content = b''.join(content.splitlines(keepends=True)[:-1])
    elif change == 'truncated-footer': content = content[:-1]
    elif change == 'trailing-newline': content += b'\n'
    elif change == 'trailing-data': content += b'private garbage'
    elif change == 'digest': rows[-1]['sha256'] = '0' * 64; content = b'\n'.join(json.dumps(row).encode() for row in rows) + b'\n'
    elif change == 'duplicate-key': content = content.replace(b'{"codec":', b'{"codec":"duplicate","codec":', 1)
    else:
        if change == 'duplicate-original': rows.insert(1, rows[1])
        elif change == 'missing-original': rows.pop(1)
        elif change == 'wrong-kind': rows[1]['kind'] = 'feedbackOriginal'
        elif change == 'company': rows[1]['original']['companyId'] = '00000000-0000-0000-0000-000000000999'
        elif change == 'year': rows[1]['original']['sourceIncomeYear'] = 2025
        elif change == 'unknown-field': rows[1]['original']['ignored'] = True
        elif change == 'bool-length': rows[1]['original']['byteLength'] = True
        elif change == 'bool-count': rows[-1]['sourceOriginals'] = True
        elif change == 'codec': rows[0]['codec'] = 'other'
        elif change in ('bytes', 'metadata'):
            original = json.loads(rows[1]['original']['canonicalOriginal'])
            original['contentBase64' if change == 'bytes' else 'documentText'] = 'changed'
            rows[1]['original']['canonicalOriginal'] = json.dumps(original)
        content = reseal(rows)
    with pytest.raises(DocumentsError): verify(content)


def test_original_reads_are_lazy_and_cancellation_does_not_fetch_more():
    calls = []
    class Factory(DocumentsFactory):
        async def session(self, token):
            session = await super().session(token)
            class Wrapped:
                actor_id = ACTOR
                async def read_retained_evidence(self, original_query):
                    calls.append(original_query)
                    return await session.read_retained_evidence(original_query)
            return Wrapped()
    archive = source_archive()
    async def run():
        stream = await prepared(archive, Factory())
        assert calls == []
        assert json.loads(await anext(stream))['codec'] == composition.STREAM_CODEC
        assert calls == []
        await stream.aclose()
        assert calls == []
    asyncio.run(run())


def test_storage_failure_after_header_never_emits_completion():
    class Factory:
        async def session(self, token):
            class Session:
                actor_id = ACTOR
                async def read_retained_evidence(self, original_query): raise DocumentsError.not_found()
            return Session()
    archive = source_archive()
    async def run():
        stream = await prepared(archive, Factory())
        first = await anext(stream)
        with pytest.raises(DocumentsError): await anext(stream)
        with pytest.raises(DocumentsError): verify(first, archive)
    asyncio.run(run())


def test_verifier_uses_bounded_line_reads_and_never_reads_the_entire_file():
    class Bounded(BytesIO):
        def read(self, size=-1):
            assert size == 1
            return super().read(size)
        def readline(self, size=-1):
            assert 0 < size <= composition.MAX_STREAM_HEADER_BYTES + 1
            return super().readline(size)
    archive = source_archive()
    assert composition.verify_archive_stream(Bounded(download(archive)), query=query(archive))[1] == 1


@pytest.mark.parametrize('bound', ['header', 'record'])
def test_oversized_line_is_rejected_before_json_parsing(monkeypatch, bound):
    content = download()
    monkeypatch.setattr(composition, 'MAX_STREAM_' + bound.upper() + '_BYTES', 20)
    with pytest.raises(DocumentsError): verify(content)


def client(archive, factory=None):
    class Session:
        actor_id = ACTOR
        async def archive_source(self, requested):
            assert requested == query(archive)
            return archive
    class Sessions:
        async def session(self, token):
            assert token == 'token'
            return Session()
    return TestClient(create_app(shareholder_register_filing_session_factory=Sessions(),
        documents_session_factory=factory or DocumentsFactory()))


def test_authenticated_download_has_private_headers_and_verifiable_body():
    archive = source_archive()
    route = '/api/v1/shareholder-register-filings/archive-source/production-stream'
    params = {'companyId': str(archive.company_id), 'incomeYear': int(archive.income_year)}
    http = client(archive)
    assert http.get(route, params=params).status_code == 401
    response = http.get(route, params=params, headers={'Authorization': 'Bearer token'})
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'application/x-ndjson'
    assert 'no-store' in response.headers['cache-control']
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert '.ndjson' in response.headers['content-disposition']
    assert verify(response.content, archive)[0] == archive


def test_document_actor_mismatch_fails_before_http_body_starts():
    class Factory:
        async def session(self, token):
            class Session: actor_id = replace(ACTOR, kind=type(ACTOR.kind).SYSTEM)
            return Session()
    archive = source_archive()
    response = client(archive, Factory()).get('/api/v1/shareholder-register-filings/archive-source/production-stream',
        params={'companyId': str(archive.company_id), 'incomeYear': int(archive.income_year)},
        headers={'Authorization': 'Bearer token'})
    assert response.status_code == 503
    assert 'canonicalArchive' not in response.text


def test_offline_stream_command_reports_byte_checks_without_claiming_restore(tmp_path):
    archive = source_archive()
    path = tmp_path / 'archive.ndjson'
    path.write_bytes(download(archive))
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/verify_rf1086_archive.py'),
        str(path), '--stream', '--company-id', str(archive.company_id), '--income-year', str(int(archive.income_year)),
        '--require-source-originals']
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['sourceOriginalBytesVerified'] and report['sourceOriginals'] == 1
    assert report['databaseRestorePerformed'] is False
    path.write_bytes(path.read_bytes()[:-20])
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {'status': 'invalid', 'code': 'rf1086_archive_verification_failed'}
