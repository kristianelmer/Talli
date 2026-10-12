"""Independent wire/HTTP attacks; synthetic sessions are not Auth or storage proof."""
import asyncio
from base64 import b64decode, b64encode
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from talli_backend.application import shareholder_register_archive as streams
from talli_backend.main import create_app
from talli_backend.modules.documents import public as documents
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.modules.shareholder_register_filing import archive_storage
from talli_backend.shared.kernel import ActorId, ActorKind, UserId
from rf1086_retained_stream_fixture import retained_stream_fixture, DocumentsFactory, ACTOR
from test_rf1086_archive_storage_v6 import forbid_fresh
from test_rf1086_archive_source import snapshot as legacy_snapshot
from test_rf1086_archive_history import history_archive, DocumentsFactory as HistoryDocuments
from test_rf1086_feedback_archive_originals import feedback_archive, DocumentsFactory as FeedbackDocuments
from test_rf1086_override_archive import override_archive
from test_rf1086_withdrawal_archive import withdrawal_archive
from test_rf1086_archive_stream import download as old_download

ROUTE = '/api/v1/shareholder-register-filings/archive-source/production-stream-v6'
MEMBER = ActorId(ActorKind.USER, UserId(str(UUID(int=99401))))


def query(archive, actor=ACTOR):
    return rf.Rf1086ArchiveQuery(archive.company_id, archive.income_year, actor)


async def prepare(archive, factory, actor=ACTOR):
    return await streams.prepare_retained_archive_stream(archive, query=query(archive, actor),
        documents_factory=factory, access_token='token', actor_id=actor)


def download(archive, originals, actor=ACTOR):
    factory = DocumentsFactory(originals, actor_id=actor)
    async def run():
        return b''.join([line async for line in await prepare(archive, factory, actor)])
    return asyncio.run(run()), factory


def verify(content, archive, **options):
    return streams.verify_retained_archive_stream(BytesIO(content), query=query(archive), **options)


def rows(content):
    return [json.loads(line) for line in content.splitlines()]


def seal(values):
    lines = [(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
             for row in values[:-1]]
    values[-1]['sha256'] = sha256(b''.join(lines)).hexdigest()
    return b''.join(lines) + (json.dumps(values[-1], separators=(',', ':')) + '\n').encode()


@pytest.fixture
def accepted():
    return retained_stream_fixture('loss_covering_reduction', 2, 'accepted', legacy=True, independent=True)


def test_every_exact_metadata_version_and_independent_original_survives_member_export(accepted, monkeypatch):
    archive, originals = accepted
    source = archive.source_history.year_sources[-1]
    assert source.governance_projection.chain_count == 1
    assert source.governance_projection.chains[0].amendment_count == 2
    assert len(archive.withdrawal_capture_records) == 2
    assert len(archive.source_history.register_observations) == 4  # Three linked plus independent.
    expected_sources = streams.source_original_queries(archive)
    expected_feedback = streams.feedback_original_queries(archive)
    assert len({str(row.document_id) for row in expected_sources}) < len(expected_sources)
    assert any(row.source_income_year != archive.income_year for row in expected_sources)
    forbid_fresh(monkeypatch)
    content, factory = download(archive, originals, MEMBER)
    assert factory.sessions == ['token']
    assert factory.reads == [*expected_sources, *expected_feedback]
    restored, source_count, feedback_count = verify(content, archive, require_feedback_originals=True)
    assert restored == archive and (source_count, feedback_count) == (len(expected_sources), len(expected_feedback))
    parsed = rows(content)
    assert parsed[0]['codec'] == 'rf1086-production-stream-v2'
    assert parsed[0]['canonicalArchive'] == rf.serialize_rf1086_archive_v6(archive, query=query(archive))
    for row, original_query in zip(parsed[1:-1], factory.reads, strict=True):
        expected = documents.serialize_retained_document_original(originals[original_query], query=original_query)
        assert row['original']['canonicalOriginal'] == expected
        assert b64decode(json.loads(expected)['contentBase64']) == originals[original_query].original.content


def legacy_case(codec):
    if codec == 1:
        return legacy_snapshot(), DocumentsFactory({}), ACTOR
    if codec == 2:
        archive, originals = history_archive()
        return archive, HistoryDocuments(originals), ACTOR
    if codec == 3:
        archive, original = feedback_archive()
        return archive, FeedbackDocuments(original), original.document.created_by
    archive, originals = (override_archive() if codec == 4 else withdrawal_archive())
    return archive, HistoryDocuments(originals), ACTOR


@pytest.mark.parametrize('codec', [1, 2, 3, 4, 5])
def test_new_outer_label_cannot_upgrade_any_valid_legacy_inner_archive(codec):
    archive, factory, actor = legacy_case(codec)
    content = old_download(archive, factory, actor)
    values = rows(content)
    assert json.loads(values[0]['canonicalArchive'])['codec'] == f'rf1086-production-archive-v{codec}'
    values[0]['codec'] = 'rf1086-production-stream-v2'
    with pytest.raises(documents.DocumentsError):
        verify(seal(values), archive)


@pytest.mark.parametrize('verifier', ['old', 'new'])
def test_old_outer_with_v6_inner_is_never_cross_accepted(accepted, verifier):
    archive, originals = accepted
    values = rows(download(archive, originals)[0])
    values[0]['codec'] = 'rf1086-production-stream-v1'
    content = seal(values)
    with pytest.raises(documents.DocumentsError):
        if verifier == 'old':
            streams.verify_archive_stream(BytesIO(content), query=query(archive))
        else:
            verify(content, archive)


@pytest.mark.parametrize('attack', ['missing-original', 'duplicate-original', 'swapped-originals',
    'wrong-kind', 'foreign-company', 'wrong-year', 'boolean-length', 'boolean-count',
    'float-count', 'extra-header', 'extra-original-key', 'extra-footer', 'inner-nonstr',
    'inner-v5-label', 'missing-footer', 'trailing-byte'])
def test_exact_transfer_shape_is_required_even_with_a_recomputed_footer(accepted, attack):
    archive, originals = accepted
    content = download(archive, originals)[0]
    values = rows(content)
    if attack == 'missing-original': values.pop(1)
    if attack == 'duplicate-original': values.insert(1, deepcopy(values[1]))
    if attack == 'swapped-originals': values[1], values[2] = values[2], values[1]
    if attack == 'wrong-kind': values[1]['kind'] = 'feedbackOriginal'
    if attack == 'foreign-company': values[1]['original']['companyId'] = str(UUID(int=99402))
    if attack == 'wrong-year': values[1]['original']['sourceIncomeYear'] += 1
    if attack == 'boolean-length': values[1]['original']['byteLength'] = True
    if attack == 'boolean-count': values[-1]['feedbackOriginals'] = True
    if attack == 'float-count': values[-1]['sourceOriginals'] = float(values[-1]['sourceOriginals'])
    if attack == 'extra-header': values[0]['ignored'] = 'private'
    if attack == 'extra-original-key': values[1]['original']['ignored'] = 'private'
    if attack == 'extra-footer': values[-1]['ignored'] = 'private'
    if attack == 'inner-nonstr': values[0]['canonicalArchive'] = {}
    if attack == 'inner-v5-label':
        inner = json.loads(values[0]['canonicalArchive'])
        inner['codec'] = 'rf1086-production-archive-v5'
        values[0]['canonicalArchive'] = json.dumps(inner, separators=(',', ':'))
    content = seal(values)
    if attack == 'missing-footer': content = b''.join(content.splitlines(keepends=True)[:-1])
    if attack == 'trailing-byte': content += b'x'
    with pytest.raises(documents.DocumentsError): verify(content, archive)


@pytest.mark.parametrize('attack', ['raw-bytes', 'base64-space', 'metadata', 'feedback-receipt-id',
    'feedback-receipt-time', 'feedback-attribution', 'feedback-link'])
def test_document_owner_bytes_and_feedback_binding_survive_outer_rehash(accepted, attack):
    archive, originals = accepted
    values = rows(download(archive, originals)[0])
    target = next(row for row in values if row.get('kind') ==
        ('feedbackOriginal' if attack.startswith('feedback') else 'sourceOriginal'))
    wire = json.loads(target['original']['canonicalOriginal'])
    if attack == 'raw-bytes':
        content = b64decode(wire['contentBase64'])
        wire['contentBase64'] = b64encode(content[:-1] + bytes([content[-1] ^ 1])).decode()
    elif attack == 'base64-space': wire['contentBase64'] += '\n'
    elif attack == 'feedback-receipt-id': wire['receipt']['originalId'] = str(UUID(int=99403))
    elif attack == 'feedback-receipt-time': wire['receipt']['retainedAt'] = '2026-02-01T00:00:00+00:00'
    else:
        metadata = json.loads(wire['documentText'])
        if attack == 'metadata': metadata['name'] = 'Changed retained metadata'
        if attack == 'feedback-attribution': metadata['created_by']['subject']['value'] = str(UUID(int=99404))
        if attack == 'feedback-link': metadata['linked_to'] = 'production_filing_submission:' + str(UUID(int=99405))
        wire['documentText'] = json.dumps(metadata, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    target['original']['canonicalOriginal'] = json.dumps(wire, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    with pytest.raises(documents.DocumentsError): verify(seal(values), archive)


@pytest.mark.parametrize('field', ['source_history', 'overrides', 'withdrawal_capture_records'])
def test_producer_requires_capture_before_opening_documents(accepted, field):
    archive, originals = accepted
    factory = DocumentsFactory(originals)
    archive = replace(archive, **{field: None})
    with pytest.raises(rf.ShareholderRegisterFilingError): asyncio.run(prepare(archive, factory))
    assert factory.sessions == factory.reads == []


def test_actor_failure_precedes_serializer_and_documents(accepted, monkeypatch):
    archive, originals = accepted
    factory = DocumentsFactory(originals)
    def forbidden_work(*args, **kwargs): raise AssertionError('Actor must fail before serialization')
    monkeypatch.setattr(rf, 'serialize_rf1086_archive_v6', forbidden_work)
    with pytest.raises(rf.ShareholderRegisterFilingError) as caught:
        asyncio.run(streams.prepare_retained_archive_stream(archive, query=query(archive),
            documents_factory=factory, access_token='token', actor_id=MEMBER))
    assert caught.value.code == rf.ShareholderRegisterFilingErrorCode.FORBIDDEN
    assert factory.sessions == factory.reads == []


def test_shared_aggregate_budget_is_enforced_before_documents_session(accepted, monkeypatch):
    archive, originals = accepted
    sources = streams.source_original_queries(archive)
    feedback = streams.feedback_original_queries(archive)
    source_bytes, feedback_bytes = sum(x.byte_length for x in sources), sum(x.byte_length for x in feedback)
    assert source_bytes > 0 and feedback_bytes > 0
    monkeypatch.setattr(streams, 'MAX_STREAM_ORIGINAL_BYTES', source_bytes + feedback_bytes - 1)
    factory = DocumentsFactory(originals)
    with pytest.raises(rf.ShareholderRegisterFilingError): asyncio.run(prepare(archive, factory))
    assert factory.sessions == factory.reads == []


@pytest.mark.parametrize('read_one', [False, True])
def test_closing_generator_prevents_all_later_original_reads(accepted, read_one):
    archive, originals = accepted
    factory = DocumentsFactory(originals)
    async def run():
        generator = await prepare(archive, factory)
        assert factory.sessions == ['token'] and factory.reads == []
        assert json.loads(await anext(generator))['codec'] == 'rf1086-production-stream-v2'
        assert factory.reads == []
        if read_one: assert json.loads(await anext(generator))['kind'] == 'sourceOriginal'
        await generator.aclose()
        assert len(factory.reads) == int(read_one)
    asyncio.run(run())


@pytest.mark.parametrize('failure', [documents.DocumentsError.not_found(), documents.DocumentsError.forbidden(), asyncio.CancelledError()])
def test_second_read_failure_never_yields_footer_or_retries(accepted, failure):
    archive, originals = accepted
    class Failing(DocumentsFactory):
        async def read_retained_evidence(self, original_query):
            if self.reads:
                self.reads.append(original_query)
                raise failure
            return await super().read_retained_evidence(original_query)
    factory = Failing(originals)
    async def run():
        generator = await prepare(archive, factory)
        output = [await anext(generator), await anext(generator)]
        with pytest.raises(type(failure)) as caught: await anext(generator)
        assert caught.value is failure
        assert len(factory.reads) == 2
        await generator.aclose()
        return b''.join(output)
    with pytest.raises(documents.DocumentsError): verify(asyncio.run(run()), archive)


@pytest.mark.parametrize('boundary', ['header', 'record'])
def test_exact_line_boundaries_and_bounded_reads(accepted, boundary, monkeypatch):
    archive, originals = accepted
    content = download(archive, originals)[0]
    lines = content.splitlines(keepends=True)
    threshold = len(lines[0]) if boundary == 'header' else max(map(len, lines[1:]))
    monkeypatch.setattr(streams, 'MAX_STREAM_' + boundary.upper() + '_BYTES', threshold)
    class Bounded(BytesIO):
        def read(self, size=-1):
            assert size == 1
            return super().read(size)
        def readline(self, size=-1):
            assert 0 < size <= max(streams.MAX_STREAM_HEADER_BYTES, streams.MAX_STREAM_RECORD_BYTES) + 1
            return super().readline(size)
    assert streams.verify_retained_archive_stream(Bounded(content), query=query(archive))[0] == archive
    monkeypatch.setattr(streams, 'MAX_STREAM_' + boundary.upper() + '_BYTES', threshold - 1)
    with pytest.raises(documents.DocumentsError): verify(content, archive)


def test_explicit_unbound_feedback_remains_incomplete_under_new_stream():
    archive, originals = retained_stream_fixture(status='accepted', bound_feedback=False)
    assert archive.feedback_artifacts and all(row.original_id is None for row in archive.feedback_artifacts)
    content, _ = download(archive, originals)
    assert verify(content, archive)[2] == 0
    with pytest.raises(documents.DocumentsError): verify(content, archive, require_feedback_originals=True)


class Sessions:
    def __init__(self, archive, failure=None):
        self.archive, self.failure = archive, failure
        self.sessions, self.reads = [], []

    async def session(self, token):
        self.sessions.append(token)
        if self.failure is not None: raise self.failure
        owner = self
        class Session:
            actor_id = ACTOR
            async def archive_source(self, requested):
                owner.reads.append(requested)
                return owner.archive
        return Session()


def api(sessions, factory):
    return TestClient(create_app(shareholder_register_filing_session_factory=sessions,
        documents_session_factory=factory))


def get(client, archive, *, authorized=True, **scope):
    params = dict(companyId=str(archive.company_id), incomeYear=int(archive.income_year), **scope)
    return client.get(ROUTE, params=params, headers={'Authorization': 'Bearer token'} if authorized else {})


def test_actual_route_keeps_all_three_sections_and_safe_headers(accepted, monkeypatch):
    archive, originals = accepted
    sessions, factory = Sessions(archive), DocumentsFactory(originals)
    forbid_fresh(monkeypatch)
    response = get(api(sessions, factory), archive)
    assert response.status_code == 200, response.text
    assert sessions.sessions == ['token'] and sessions.reads == [query(archive)]
    assert response.headers['content-type'] == 'application/x-ndjson'
    # Existing request middleware deliberately forces the final no-store header.
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['content-disposition'] == f'attachment; filename="rf1086-{archive.company_id}-{int(archive.income_year)}.ndjson"'
    restored = verify(response.content, archive)[0]
    assert restored == archive
    assert restored.source_history and restored.overrides == () and len(restored.withdrawal_capture_records) == 2


@pytest.mark.parametrize('failure', ['unauthenticated', 'forbidden', 'malformed-scope', 'wrong-scope', 'documents-actor', 'incomplete-archive'])
def test_actual_route_fails_before_body_without_documents_content(accepted, failure):
    archive, originals = accepted
    sessions = Sessions(archive, rf.ShareholderRegisterFilingError.forbidden() if failure == 'forbidden' else None)
    factory = DocumentsFactory(originals, actor_id=MEMBER if failure == 'documents-actor' else ACTOR)
    if failure == 'incomplete-archive': sessions.archive = replace(archive, source_history=None)
    params = {'companyId': str(archive.company_id), 'incomeYear': int(archive.income_year)}
    if failure == 'malformed-scope': params['companyId'] = 'bad'
    if failure == 'wrong-scope': params['companyId'] = str(UUID(int=99406))
    response = api(sessions, factory).get(ROUTE, params=params,
        headers={} if failure == 'unauthenticated' else {'Authorization': 'Bearer token'})
    expected = {'unauthenticated': 401, 'forbidden': 403, 'malformed-scope': 422}.get(failure, 503)
    assert response.status_code == expected, response.text
    assert 'canonicalArchive' not in response.text and 'Retained original' not in response.text
    assert factory.reads == []
    if failure != 'documents-actor': assert factory.sessions == []
    if failure in ('unauthenticated', 'malformed-scope'): assert sessions.sessions == []


@pytest.mark.parametrize('field', ['source_history', 'overrides', 'withdrawal_capture_records'])
def test_rehashed_v6_inner_cannot_erase_capture_sections(accepted, field):
    archive, originals = accepted
    values = rows(download(archive, originals)[0])
    envelope = json.loads(values[0]['canonicalArchive'])
    body = json.loads(envelope['snapshotText'])
    body['fields'][field] = None
    envelope['snapshotText'] = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    envelope['sha256'] = sha256(envelope['snapshotText'].encode()).hexdigest()
    values[0]['canonicalArchive'] = json.dumps(envelope, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    with pytest.raises(documents.DocumentsError): verify(seal(values), archive)


def test_inner_duplicate_codec_is_rejected_by_owner_parse(accepted, monkeypatch):
    archive, originals = accepted
    values = rows(download(archive, originals)[0])
    original = values[0]['canonicalArchive']
    values[0]['canonicalArchive'] = '{"codec":"rf1086-production-archive-v6",' + original[1:]
    received = []
    owner_parse = rf.parse_rf1086_retained_archive
    def record_parse(text, **kwargs):
        received.append(text)
        return owner_parse(text, **kwargs)
    monkeypatch.setattr(rf, 'parse_rf1086_retained_archive', record_parse)
    with pytest.raises(documents.DocumentsError): verify(seal(values), archive)
    assert received == [values[0]['canonicalArchive']]


def test_complete_empty_export_does_not_open_documents():
    template = legacy_snapshot()
    archive = rf.Rf1086ArchiveSnapshot(template.company_id, template.income_year,
        source_history=rf.Rf1086ArchiveSourceHistory(), overrides=(), withdrawal_capture_records=())
    content, factory = download(archive, {})
    assert factory.sessions == factory.reads == []
    assert verify(content, archive) == (archive, 0, 0)


def test_owner_size_guard_precedes_inner_json_discrimination(monkeypatch):
    template = legacy_snapshot()
    archive = rf.Rf1086ArchiveSnapshot(template.company_id, template.income_year,
        source_history=rf.Rf1086ArchiveSourceHistory(), overrides=(), withdrawal_capture_records=())
    content, _ = download(archive, {})
    inner = rows(content)[0]['canonicalArchive']
    # Scale the sole owner's real bound; avoid allocating a 64 MiB test payload.
    monkeypatch.setattr(archive_storage, '_MAX_BYTES', len(inner.encode('utf-8')) - 1)
    calls, original_loads = [], json.loads
    def inspect_loads(value, *args, **kwargs):
        if type(value) is str and value == inner: calls.append(value)
        return original_loads(value, *args, **kwargs)
    monkeypatch.setattr(json, 'loads', inspect_loads)
    with pytest.raises(documents.DocumentsError): verify(content, archive)
    assert calls == []


def cli(path, archive, *extra, company=None, year=None):
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'verify_rf1086_retained_archive_stream.py'
    return subprocess.run([sys.executable, str(script), str(path),
        '--company-id', str(archive.company_id) if company is None else company,
        '--income-year', str(int(archive.income_year)) if year is None else year, *extra],
        capture_output=True, check=False)


@pytest.mark.parametrize('attack', ['malformed-company', 'foreign-company', 'foreign-year', 'truncated', 'missing-file', 'old-stream'])
def test_explicit_cli_has_closed_errors_without_fallback(accepted, tmp_path, attack):
    archive, originals = accepted
    content, _ = download(archive, originals)
    path = tmp_path / 'retained.ndjson'
    company = 'bad' if attack == 'malformed-company' else str(UUID(int=99422)) if attack == 'foreign-company' else None
    year = str(int(archive.income_year) + 1) if attack == 'foreign-year' else None
    if attack == 'truncated': content = content[:-1]
    if attack == 'old-stream':
        old_archive, factory, actor = legacy_case(2)
        content = old_download(old_archive, factory, actor)
        archive = old_archive
    if attack != 'missing-file': path.write_bytes(content)
    result = cli(path, archive, company=company, year=year)
    assert result.returncode == 1 and result.stderr == b''
    assert result.stdout == b'{"status": "invalid", "code": "rf1086_archive_verification_failed"}\n'


@pytest.mark.parametrize('bound', [False, True])
def test_explicit_cli_distinguishes_verified_bytes_from_feedback_completeness(tmp_path, bound):
    archive, originals = retained_stream_fixture('cash_issue', 1, 'accepted', bound_feedback=bound)
    content, _ = download(archive, originals)
    path = tmp_path / 'retained.ndjson'
    path.write_bytes(content)
    result = cli(path, archive)
    assert result.returncode == 0 and result.stderr == b''
    value = json.loads(result.stdout)
    assert value['status'] == 'verified_rf_retained_stream'
    assert value['archiveCodec'] == 'rf1086-production-archive-v6'
    assert value['streamCodec'] == 'rf1086-production-stream-v2'
    assert value['sourceHistoryIncluded'] is True
    assert value['overrideHistoryIncluded'] is True
    assert value['registerWithdrawalHistoryIncluded'] is True
    assert value['sourceOriginalBytesVerified'] is True
    assert value['feedbackOriginalBytesVerified'] is True
    assert value['feedbackOriginalsComplete'] is bound
    assert value['sourceOriginals'] == len(streams.source_original_queries(archive))
    assert value['feedbackOriginals'] == len(streams.feedback_original_queries(archive))
    assert (value['feedbackOriginals'] > 0) is bound
    assert value['registerObservations'] == 2 and value['registerWithdrawals'] == 1
    assert all(value[key] is False for key in (
        'databaseRestorePerformed', 'authenticatedOriginVerified', 'authoritativeEnumerationVerified'))
    strict = cli(path, archive, '--require-feedback-originals')
    assert strict.returncode == (0 if bound else 1)
    assert strict.stderr == b''
