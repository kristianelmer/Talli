"""Complete retained sources survive export even before any review or approval."""
import asyncio
from dataclasses import fields, replace
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.modules.documents.public import (
    DocumentId, RetainedDocumentOriginalReceipt, RetainedDocumentOriginal,
    RetainedDocumentOriginalSnapshot, document_metadata_sha256,
)
from talli_backend.application.shareholder_register_archive import archive_source_originals, verify_source_originals
from talli_backend.main import create_app
from test_rf1086_archive_storage import query, round_trip
from test_rf1086_source_approval_archive import source_archive, read
from test_rf1086_register_observation import basis as observation_basis
from test_rf1086_year_source import ACTOR, NOW
from rf1086_archive_documents import CONTENT, document, evidence


def original(doc):
    receipt = RetainedDocumentOriginalReceipt(str(UUID(int=900 + int(UUID(str(doc.document_id))))),
        doc.document_id, doc.company_id, doc.income_year, document_metadata_sha256(doc), doc.content_sha256,
        doc.byte_length, NOW)
    return RetainedDocumentOriginalSnapshot(doc, RetainedDocumentOriginal(receipt, CONTENT))


def history_archive(*, approved=True, observations=True):
    archive = source_archive()
    line = archive.source_approval_lineage[0]
    first = line.source
    corrected_doc = replace(document(), name='Corrected source.pdf')
    corrected_evidence = replace(evidence(), metadata_sha256=document_metadata_sha256(corrected_doc))
    command = replace(first.command, documents=(corrected_evidence,), supersedes_source_id=first.source_id,
        supersedes_source_sha256=first.source_sha256, correction_reason='Retain corrected source metadata')
    context = rf.Rf1086VerifiedYearSourceContext(ACTOR, True, first.company_id, first.income_year,
        command.case.company, first.freshness.company_identity_sha256, command.documents,
        first.governance_receipts, True, first.freshness.governance_enumeration_sha256)
    second = rf.prepare_rf1086_year_source(command, context=context, previous=first,
        source_id=rf.Rf1086YearSourceId(str(UUID(int=901))), confirmed_at=NOW + timedelta(seconds=1))
    second_preview = replace(line.source_preview, preview_id=rf.PreviewId(str(UUID(int=902))),
        source_id=second.source_id, source_sha256=second.source_sha256, case_sha256=second.case_sha256)
    def preview_record(preview, time):
        text = rf.serialize_rf1086_source_preview(preview)
        return rf.Rf1086ArchiveSourcePreview(preview, text, sha256(text.encode()).hexdigest(), str(ACTOR.subject), time.isoformat())
    originals = [original(document()), original(corrected_doc)]
    observations_list = []
    if observations:
        command, context = observation_basis()
        docs = []
        for offset, source in enumerate(command.documents):
            doc = replace(document(), document_id=DocumentId(str(UUID(int=920 + offset))), document_type='share_register', name=f'Register {offset}.pdf')
            originals.append(original(doc))
            docs.append(replace(source, document_id=str(doc.document_id), content_sha256=doc.content_sha256,
                content_version_sha256=doc.content_sha256, byte_length=doc.byte_length, metadata_sha256=document_metadata_sha256(doc),
                integrity_status=doc.status.value, created_at=doc.created_at, source_income_year=doc.income_year))
        command = replace(command, documents=tuple(docs))
        context = replace(context, documents=tuple(docs))
        first_observation = rf.prepare_rf1086_register_observation(command, context=context,
            observation_id=rf.Rf1086RegisterObservationId(str(UUID(int=930))), confirmed_at=NOW + timedelta(seconds=2))
        corrected = replace(command, supersedes_observation_id=first_observation.observation_id,
            supersedes_observation_sha256=first_observation.fact_sha256, correction_reason='Register correction')
        next_observation = rf.prepare_rf1086_register_observation(corrected, context=context, previous=first_observation,
            observation_id=rf.Rf1086RegisterObservationId(str(UUID(int=931))), confirmed_at=NOW + timedelta(seconds=3))
        observations_list = [first_observation, next_observation]
    history = rf.Rf1086ArchiveSourceHistory((first, second),
        rf.Rf1086ArchiveYearSourceHead(second.company_id, second.income_year, second.source_id, second.version, second.source_sha256),
        tuple(observations_list), (preview_record(line.source_preview, NOW), preview_record(second_preview, NOW + timedelta(seconds=1))),
        (line.bridge,) if approved else ())
    history = with_captures(history)
    if not approved:
        archive = replace(archive, approvals=(), source_approval_lineage=(), previews=())
    return replace(archive, source_history=history), originals


def with_captures(history):
    def captures(values, key, digest, serialize):
        return tuple(rf.Rf1086ArchiveCaptureRecord(key(value), 'capture:' + key(value),
            digest(value.command), serialize(value)) for value in values)
    return replace(history,
        source_capture_records=captures(history.year_sources, lambda row: row.source_id.value,
            rf.rf1086_year_source_digest, rf.serialize_rf1086_year_source),
        observation_capture_records=captures(history.register_observations, lambda row: row.observation_id.value,
            rf.rf1086_register_observation_request_digest, rf.serialize_rf1086_register_observation))


class DocumentsFactory:
    def __init__(self, originals): self.originals = originals
    async def session(self, token):
        originals = self.originals
        class Session:
            actor_id = ACTOR
            async def read_retained_evidence(self, query):
                for original in originals:
                    r = original.original.receipt
                    if (r.document_id,r.company_id,r.source_income_year,r.metadata_sha256,r.content_sha256,r.byte_length) == (
                            query.document_id,query.company_id,query.source_income_year,query.metadata_sha256,query.content_sha256,query.byte_length):
                        return original
                raise AssertionError('Unexpected original query')
        return Session()


def export(archive, originals):
    class Session:
        actor_id = ACTOR
        async def archive_source(self, query): return archive
    class Factory:
        async def session(self, token): return Session()
    client = TestClient(create_app(shareholder_register_filing_session_factory=Factory(), documents_session_factory=DocumentsFactory(originals)))
    return client.get('/api/v1/shareholder-register-filings/archive-source/production', headers={'Authorization':'Bearer token'},
        params={'companyId':str(archive.company_id),'incomeYear':int(archive.income_year)})


@pytest.mark.parametrize('approved', [False, True])
def test_complete_history_round_trip_and_http_export_includes_unapproved_originals(approved):
    archive, originals = history_archive(approved=approved)
    assert read(archive) is archive
    text, decoded = round_trip(archive)
    assert json.loads(text)['codec'] == 'rf1086-production-archive-v2'
    assert len(decoded.source_history.year_sources) == 2
    assert len(decoded.source_history.register_observations) == 2
    response = export(archive, originals)
    assert response.status_code == 200, response.text
    wire = response.json()
    assert len(wire['sourceOriginals']) == 5
    assert len(wire['sourceHistoryDocuments']) == (9 if approved else 8)
    assert rf.parse_rf1086_archive(wire['canonicalArchive'], query=query(archive)) == archive
    assert set(verify_source_originals(archive, wire['sourceOriginals'])) == set(originals)


def test_existing_v1_fixture_remains_byte_exact_and_does_not_claim_complete_history():
    fixture = Path(__file__).resolve().parents[2]/'web/tests/fixtures/rf1086-source-submission-archive.json'
    canonical = json.loads(fixture.read_text())['canonicalArchive']
    archive = source_archive()
    parsed = rf.parse_rf1086_archive(canonical, query=query(archive))
    assert parsed.source_history is None
    assert rf.serialize_rf1086_archive(parsed, query=query(archive)) == canonical


@pytest.mark.parametrize('offset', [-1000000, -1, 0])
def test_projection_transaction_time_can_precede_bridge_wall_clock_without_rewriting_either(offset):
    archive, _ = history_archive()
    projection = replace(archive.previews[0], created_at=(NOW+timedelta(microseconds=offset)).isoformat())
    archive = replace(archive, previews=(projection,))
    assert read(archive) is archive
    _, decoded = round_trip(archive)
    assert decoded.previews[0].created_at == projection.created_at
    assert decoded.source_history.review_bridges == archive.source_history.review_bridges


def test_bridge_cannot_precede_its_projection():
    archive, _ = history_archive()
    projection = archive.previews[0]
    projection = replace(projection, created_at=(NOW+timedelta(microseconds=1)).isoformat())
    with pytest.raises(rf.Rf1086ArchiveError):
        round_trip(replace(archive, previews=(projection,)))


@pytest.mark.parametrize('change', ['missing-source', 'duplicate-source', 'stale-head', 'missing-head',
    'wrong-scope', 'missing-observation-parent', 'duplicate-observation', 'missing-preview', 'preview-hash',
    'preview-time', 'missing-bridge', 'bridge-hash', 'extra-projection',
    'missing-capture', 'duplicate-key', 'capture-bytes', 'capture-request'])
def test_partial_or_conflicting_history_fails_closed(change):
    archive, _ = history_archive()
    h = archive.source_history
    if change == 'missing-capture': h = replace(h, source_capture_records=())
    if change == 'duplicate-key': h = replace(h, source_capture_records=(h.source_capture_records[0], replace(h.source_capture_records[1], idempotency_key=h.source_capture_records[0].idempotency_key)))
    if change == 'capture-bytes': h = replace(h, observation_capture_records=(replace(h.observation_capture_records[0], snapshot_text='{}'), *h.observation_capture_records[1:]))
    if change == 'capture-request': h = replace(h, source_capture_records=(replace(h.source_capture_records[0], request_sha256='f'*64), *h.source_capture_records[1:]))
    if change == 'missing-source': h = replace(h, year_sources=h.year_sources[1:])
    if change == 'duplicate-source': h = replace(h, year_sources=h.year_sources*2)
    if change == 'stale-head': h = replace(h, year_source_head=replace(h.year_source_head, source_id=h.year_sources[0].source_id))
    if change == 'missing-head': h = replace(h, year_source_head=None)
    if change == 'wrong-scope': h = replace(h, year_source_head=replace(h.year_source_head, income_year=rf.IncomeYear(2024)))
    if change == 'missing-observation-parent': h = replace(h, register_observations=h.register_observations[1:])
    if change == 'duplicate-observation': h = replace(h, register_observations=h.register_observations*2)
    if change == 'missing-preview': h = replace(h, source_previews=h.source_previews[1:])
    if change == 'preview-hash': h = replace(h, source_previews=(replace(h.source_previews[0], payload_sha256='f'*64), *h.source_previews[1:]))
    if change == 'preview-time': h = replace(h, source_previews=(replace(h.source_previews[0], created_at=(NOW-timedelta(days=1)).isoformat()), *h.source_previews[1:]))
    if change == 'missing-bridge': h = replace(h, review_bridges=())
    if change == 'bridge-hash': h = replace(h, review_bridges=(replace(h.review_bridges[0], payload_sha256='f'*64),))
    if change == 'extra-projection': archive = replace(archive, previews=archive.previews+(replace(archive.previews[0], id=str(UUID(int=999))),))
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.serialize_rf1086_archive(replace(archive, source_history=h), query=query(archive))


def test_version_cannot_claim_history_that_is_missing_or_null():
    archive = source_archive()
    envelope = json.loads(rf.serialize_rf1086_archive(archive, query=query(archive)))
    envelope['codec'] = 'rf1086-production-archive-v2'
    with pytest.raises(rf.Rf1086ArchiveError): rf.parse_rf1086_archive(json.dumps(envelope), query=query(archive))
    archive = replace(archive, approvals=(), source_approval_lineage=(), previews=(), source_history=rf.Rf1086ArchiveSourceHistory())
    text, _ = round_trip(archive)
    envelope = json.loads(text);envelope['codec'] = 'rf1086-production-archive-v1'
    with pytest.raises(rf.Rf1086ArchiveError): rf.parse_rf1086_archive(json.dumps(envelope), query=query(archive))


def test_blocked_unapproved_preview_retains_its_original_empty_xml():
    archive, _ = history_archive(approved=False)
    record = archive.source_history.source_previews[1]
    blocked = replace(
        record.preview, readiness_status='blocked', hovedskjema_xml=None, underskjema_xml=None)
    text = rf.serialize_rf1086_source_preview(blocked)
    history = replace(archive.source_history, source_previews=(replace(record, preview=blocked,
        payload_text=text, payload_sha256=sha256(text.encode()).hexdigest()),))
    _, decoded = round_trip(replace(archive, source_history=history))
    assert decoded.source_history.source_previews[0].preview.underskjema_xml is None


def test_offline_verifier_requires_history_and_exact_unapproved_originals(tmp_path):
    import subprocess
    import sys
    archive, originals = history_archive(approved=False)
    wire = export(archive, originals).json()
    path = tmp_path/'archive.json';path.write_text(json.dumps(wire))
    script = Path(__file__).resolve().parents[1]/'scripts/verify_rf1086_archive.py'
    command = [sys.executable, str(script), str(path), '--company-id',str(archive.company_id),
        '--income-year',str(int(archive.income_year)),'--require-source-history','--require-source-originals']
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report['sourceHistoryIncluded'] is True and report['sourceVersions'] == 2
    assert report['registerObservations'] == 2 and report['sourceOriginals'] == 5
    assert report['sourceApprovals'] == 0 and report['databaseRestorePerformed'] is False
    wire['sourceOriginals'].pop()
    path.write_text(json.dumps(wire))
    assert subprocess.run(command, text=True, capture_output=True).returncode == 1
    wire['canonicalArchive'] = rf.serialize_rf1086_archive(source_archive(), query=query(archive))
    path.write_text(json.dumps(wire))
    assert subprocess.run(command, text=True, capture_output=True).returncode == 1


def history_rows(history):
    versions = []
    for value in history.year_sources:
        c = value.command
        versions.append(dict(id=value.source_id.value, company_id=str(value.company_id), income_year=int(value.income_year),
            version=value.version, source_sha256=value.source_sha256, actor_id=str(value.confirmed_by.subject),
            confirmed_at=value.confirmed_at, predecessor_id=c.supersedes_source_id.value if c.supersedes_source_id else None,
            predecessor_sha256=c.supersedes_source_sha256, correction_reason=c.correction_reason,
            request_sha256=rf.rf1086_year_source_digest(c), snapshot_text=rf.serialize_rf1086_year_source(value)))
    observations = []
    for value in history.register_observations:
        c = value.command
        observations.append(dict(id=value.observation_id.value, company_id=str(c.company_id), income_year=int(c.income_year),
            version=value.version, fact_sha256=value.fact_sha256, actor_id=str(c.actor_id.subject), confirmed_at=value.confirmed_at,
            predecessor_id=c.supersedes_observation_id.value if c.supersedes_observation_id else None,
            predecessor_sha256=c.supersedes_observation_sha256, correction_reason=c.correction_reason,
            request_sha256=rf.rf1086_register_observation_request_digest(c), snapshot_text=rf.serialize_rf1086_register_observation(value)))
    previews = []
    for value in history.source_previews:
        p = value.preview
        previews.append(dict(id=p.preview_id.value, company_id=str(p.company_id), income_year=int(p.income_year),
            source_id=p.source_id.value, source_sha256=p.source_sha256, case_sha256=p.case_sha256,
            profile=p.rendering_profile, payload_text=value.payload_text, payload_sha256=value.payload_sha256,
            created_by=value.created_by, created_at=value.created_at))
    h = history.year_source_head
    heads = [] if h is None else [dict(company_id=str(h.company_id),income_year=int(h.income_year),
        source_id=h.source_id.value,source_sha256=h.source_sha256,version=h.version)]
    for values, captures in ((versions, history.source_capture_records), (observations, history.observation_capture_records)):
        for row, capture in zip(values, captures): row['idempotency_key'] = capture.idempotency_key
    return dict(year_source_versions=versions,year_source_heads=heads,register_observations=observations,
        source_previews=previews,source_review_bridges=[{f.name:getattr(value,f.name) for f in fields(value)} for value in history.review_bridges])


@pytest.mark.parametrize('corrupt', [False, True])
def test_adapter_reads_all_unapproved_history_on_one_repeatable_snapshot(corrupt):
    from contextlib import asynccontextmanager
    from test_postgres_shareholder_register_filing import session
    archive, _ = history_archive(approved=False)
    rows = history_rows(archive.source_history)
    if corrupt: rows['register_observations'][0]['request_sha256'] = 'f'*64
    calls = []
    class Cursor:
        def __init__(self, rows): self.rows = rows
        async def fetchall(self): return self.rows
    class Connection:
        async def execute(self, sql, args):
            assert not any(name in sql for name in ('admission', 'for update', 'documents.', 'billing.', 'authority_connections.'))
            for table, values in rows.items():
                if f'from shareholder_register_filing.{table} ' in sql:
                    assert args == (str(archive.company_id), int(archive.income_year))
                    assert 'where company_id=%s::uuid and income_year=%s order by' in sql
                    calls.append(table)
                    return Cursor(values)
            return Cursor([])
    store = session({});transaction_calls = []
    @asynccontextmanager
    async def transaction(*, snapshot):
        assert snapshot is True
        transaction_calls.append(snapshot)
        yield Connection()
    store._transaction = transaction
    async def read_archive(): return await rf.create_rf1086_preparation_service(store).archive_source(replace(query(archive), actor_id=store.actor_id))
    if corrupt:
        with pytest.raises(rf.ShareholderRegisterFilingError): asyncio.run(read_archive())
    else:
        result = asyncio.run(read_archive())
        assert result.source_history == archive.source_history
        assert result.approvals == () and result.source_approval_lineage == ()
    assert transaction_calls == [True] and set(calls) == set(rows)


def test_independent_observation_roots_survive_but_correction_forks_do_not():
    archive, _ = history_archive(approved=False)
    h = archive.source_history
    first, second = h.register_observations
    context = rf.Rf1086VerifiedRegisterObservationContext(ACTOR, True, first.command.company_id,
        first.command.income_year, first.command.documents, True)
    root = rf.prepare_rf1086_register_observation(first.command, context=context,
        observation_id=rf.Rf1086RegisterObservationId(str(UUID(int=950))), confirmed_at=NOW + timedelta(seconds=4))
    round_trip(replace(archive, source_history=with_captures(replace(h, register_observations=(*h.register_observations, root)))))
    fork = rf.prepare_rf1086_register_observation(second.command, context=context, previous=first,
        observation_id=rf.Rf1086RegisterObservationId(str(UUID(int=951))), confirmed_at=NOW + timedelta(seconds=4))
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.serialize_rf1086_archive(replace(archive, source_history=with_captures(replace(h,
            register_observations=(*h.register_observations, fork)))), query=query(archive))
