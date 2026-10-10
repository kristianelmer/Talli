"""Explicit retained transport and actual portable originals, with no live storage."""
import asyncio
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys

import pytest

from talli_backend.application import shareholder_register_archive as stream
from talli_backend.modules.documents import public as documents
from talli_backend.modules.shareholder_register_filing import public as rf
from rf1086_retained_stream_fixture import ACTOR, DocumentsFactory, original_query, retained_stream_fixture
from test_rf1086_archive_storage_v6 import forbid_fresh


def query(archive):
    return rf.Rf1086ArchiveQuery(archive.company_id, archive.income_year, ACTOR)


async def prepared(archive, factory):
    return await stream.prepare_retained_archive_stream(archive, query=query(archive),
        documents_factory=factory, access_token='token', actor_id=ACTOR)


def download(archive, originals):
    factory = DocumentsFactory(originals)
    async def run():
        return b''.join([row async for row in await prepared(archive, factory)])
    return asyncio.run(run()), factory


def verified(content, archive, **kwargs):
    return stream.verify_retained_archive_stream(BytesIO(content), query=query(archive), **kwargs)


@pytest.mark.parametrize('kind', ['cash_issue', 'loss_covering_reduction'])
@pytest.mark.parametrize('amendments', [0, 1, 2])
@pytest.mark.parametrize('status', ['unapproved', 'approved', 'accepted', 'rejected'])
def test_documents_precede_actual_rf_proofs_and_every_original_is_verified(kind, amendments, status, monkeypatch):
    archive, originals = retained_stream_fixture(kind, amendments, status, legacy=True, independent=True)
    source = archive.source_history.year_sources[-1]
    assert source.governance_projection.chains[0].amendment_count == amendments
    assert len(archive.source_history.register_observations) == amendments + 2  # one independent observation
    assert len(archive.withdrawal_capture_records) == amendments
    assert [row.version for row in archive.source_history.year_sources] == [1, 2]
    forbid_fresh(monkeypatch)
    content, factory = download(archive, originals)
    restored, source_count, feedback_count = verified(content, archive, require_feedback_originals=True)
    assert rf.serialize_rf1086_archive_v6(restored, query=query(archive)) == rf.serialize_rf1086_archive_v6(archive, query=query(archive))
    sources = stream.source_original_queries(archive)
    feedback = stream.feedback_original_queries(archive)
    assert (source_count, feedback_count) == (len(sources), len(feedback))
    assert factory.sessions == ['token'] and factory.reads == list(sources + feedback)
    assert len(originals) == source_count + feedback_count
    rows = [json.loads(row) for row in content.splitlines()]
    assert rows[0]['codec'] == 'rf1086-production-stream-v2'
    assert json.loads(rows[0]['canonicalArchive'])['codec'] == 'rf1086-production-archive-v6'
    for record, expected_query in zip(rows[1:-1], sources + feedback, strict=True):
        original = documents.parse_retained_document_original(record['original']['canonicalOriginal'], query=expected_query)
        assert original == originals[expected_query]
        assert original.original.content == originals[expected_query].original.content
    assert rows[-1]['sha256'] == sha256(b''.join(content.splitlines(keepends=True)[:-1])).hexdigest()


def test_all_versions_and_shared_duplicates_use_full_identity_once():
    archive, originals = retained_stream_fixture(amendments=2, legacy=True, independent=True)
    queries = stream.source_original_queries(archive)
    same_id = {}
    for q in queries: same_id.setdefault(str(q.document_id), []).append(q)
    assert len(same_id[next(iter(same_id))]) >= 2
    assert any(len(values) == 3 for values in same_id.values())
    assert all(int(q.source_income_year) == 2024 for q in queries)
    content, factory = download(archive, originals)
    assert len(factory.reads) == len(queries) == len(set(queries))
    assert verified(content, archive)[1] == len(queries)


def test_complete_empty_archive_does_not_open_documents_session():
    populated, _ = retained_stream_fixture()
    empty = rf.Rf1086ArchiveSnapshot(populated.company_id, populated.income_year,
        source_history=rf.Rf1086ArchiveSourceHistory(), overrides=(), withdrawal_capture_records=())
    content, factory = download(empty, {})
    assert factory.sessions == factory.reads == []
    assert verified(content, empty) == (empty, 0, 0)


@pytest.mark.parametrize('omitted', ['source_history', 'overrides', 'withdrawal_capture_records'])
def test_new_producer_never_exports_unknown_capture_coverage(omitted):
    archive, originals = retained_stream_fixture()
    factory = DocumentsFactory(originals)
    with pytest.raises(rf.ShareholderRegisterFilingError):
        asyncio.run(prepared(replace(archive, **{omitted: None}), factory))
    assert factory.sessions == factory.reads == []


def test_unapproved_saved_preview_text_is_not_canonicalized_or_rendered(monkeypatch):
    from test_rf1086_source_preview import preview_source
    archive, originals = retained_stream_fixture(status='unapproved')
    preview = preview_source(archive.source_history.year_sources[-1])[0]
    preview = replace(preview, readiness_status='blocked', hovedskjema_xml=None, underskjema_xml=None)
    text = json.dumps(json.loads(rf.serialize_rf1086_source_preview(preview)), indent=2) + '\n'
    row = rf.Rf1086ArchiveSourcePreview(preview, text, sha256(text.encode()).hexdigest(), ACTOR.subject.value, archive.source_history.year_sources[-1].confirmed_at.isoformat())
    archive = replace(archive, source_history=replace(archive.source_history, source_previews=(row,)))
    forbid_fresh(monkeypatch)
    restored = verified(download(archive, originals)[0], archive)[0]
    assert restored.source_history.source_previews[0].payload_text == text


@pytest.mark.parametrize('read_count', [0, 1])
def test_generator_close_does_not_read_remaining_originals(read_count):
    archive, originals = retained_stream_fixture(amendments=2)
    factory = DocumentsFactory(originals)
    async def run():
        generator = await prepared(archive, factory)
        assert factory.reads == []
        await anext(generator)
        assert factory.reads == []
        for _ in range(read_count): await anext(generator)
        await generator.aclose()
    asyncio.run(run())
    assert len(factory.reads) == read_count


@pytest.mark.parametrize('failure', [documents.DocumentsError.not_found(), documents.DocumentsError.forbidden(),
    documents.DocumentsError.integrity_failed(), asyncio.CancelledError()])
def test_original_failure_or_cancellation_cannot_emit_footer_or_retry(failure):
    archive, originals = retained_stream_fixture(amendments=1)
    factory = DocumentsFactory(originals, failure=failure)
    async def run():
        generator = await prepared(archive, factory)
        header = await anext(generator)
        with pytest.raises(type(failure)) as caught: await anext(generator)
        assert caught.value is failure
        with pytest.raises(StopAsyncIteration): await anext(generator)
        return header
    prefix = asyncio.run(run())
    assert len(factory.reads) == 1
    with pytest.raises(documents.DocumentsError): verified(prefix, archive)


def test_shared_source_and_feedback_budget_is_checked_before_session(monkeypatch):
    archive, originals = retained_stream_fixture(status='accepted')
    source_bytes = sum(q.byte_length for q in stream.source_original_queries(archive))
    feedback_bytes = sum(q.byte_length for q in stream.feedback_original_queries(archive))
    assert source_bytes > 0 and feedback_bytes > 0
    monkeypatch.setattr(stream, 'MAX_STREAM_ORIGINAL_BYTES', source_bytes + feedback_bytes)
    content, _ = download(archive, originals)
    assert verified(content, archive)[2] > 0
    monkeypatch.setattr(stream, 'MAX_STREAM_ORIGINAL_BYTES', source_bytes + feedback_bytes - 1)
    factory = DocumentsFactory(originals)
    with pytest.raises(rf.ShareholderRegisterFilingError): asyncio.run(prepared(archive, factory))
    assert factory.sessions == []
    with pytest.raises(documents.DocumentsError): verified(content, archive)


@pytest.mark.parametrize('boundary', ['header', 'record'])
def test_exact_line_limit_passes_and_one_byte_less_fails(boundary, monkeypatch):
    archive, originals = retained_stream_fixture()
    content, _ = download(archive, originals)
    lines = content.splitlines(keepends=True)
    length = len(lines[0]) if boundary == 'header' else max(map(len, lines[1:]))
    attr = 'MAX_STREAM_' + boundary.upper() + '_BYTES'
    monkeypatch.setattr(stream, attr, length)
    assert download(archive, originals)[0] == content
    assert verified(content, archive)[1] > 0
    monkeypatch.setattr(stream, attr, length - 1)
    with pytest.raises(documents.DocumentsError): verified(content, archive)


def test_stream_verifier_only_uses_bounded_line_reads():
    archive, originals = retained_stream_fixture()
    class Bounded(BytesIO):
        def readline(self, size=-1):
            assert 0 < size <= stream.MAX_STREAM_HEADER_BYTES + 1
            return super().readline(size)
        def read(self, size=-1):
            assert size == 1
            return super().read(size)
    result = stream.verify_retained_archive_stream(Bounded(download(archive, originals)[0]), query=query(archive))
    assert result[1] == len(originals)


@pytest.mark.parametrize('bound', [False, True])
def test_new_cli_reports_exact_bytes_and_distinguishes_legacy_feedback_unknown(tmp_path, bound):
    archive, originals = retained_stream_fixture(status='accepted', bound_feedback=bound)
    path = tmp_path / 'retained.ndjson'
    content, _ = download(archive, originals)
    path.write_bytes(content)
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/verify_rf1086_retained_archive_stream.py'),
        str(path), '--company-id', str(archive.company_id), '--income-year', str(int(archive.income_year))]
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == 'verified_rf_retained_stream'
    assert report['sourceOriginalBytesVerified'] and report['feedbackOriginalBytesVerified']
    assert report['feedbackOriginalsComplete'] is bound
    assert not report['databaseRestorePerformed'] and not report['authenticatedOriginVerified']
    assert not report['authoritativeEnumerationVerified']
    strict = subprocess.run([*command, '--require-feedback-originals'], text=True, capture_output=True)
    assert strict.returncode == (0 if bound else 1)
    path.write_bytes(content[:-1])
    broken = subprocess.run(command, text=True, capture_output=True)
    assert broken.returncode == 1
    assert json.loads(broken.stdout) == {'status': 'invalid', 'code': 'rf1086_archive_verification_failed'}
