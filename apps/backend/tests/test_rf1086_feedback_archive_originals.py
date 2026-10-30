"""Portable authority feedback keeps original attribution, metadata and exact bytes."""
import asyncio
from dataclasses import replace
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from talli_backend.main import create_app
from talli_backend.application.shareholder_register_archive import archive_feedback_originals, verify_feedback_originals
from talli_backend.modules.documents.public import (
    DocumentId, DocumentRecord, DocumentStatus, DocumentsError, RetainedDocumentOriginal,
    RetainedDocumentOriginalReceipt, RetainedDocumentOriginalSnapshot, document_metadata_sha256,
)
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_archive_source import production_snapshot, ACTOR
from test_rf1086_archive_storage import query, round_trip

CONTENT = b'<receipt>exact original feedback\x00</receipt>'


def feedback_archive():
    archive = production_snapshot()
    archive = replace(archive,
        review_comments=(replace(archive.review_comments[0], id=str(UUID(int=918)), preview_id=str(UUID(int=919))),),
        permissions=(replace(archive.permissions[0], id=str(UUID(int=920))),))
    approval = replace(archive.approvals[0], id=str(UUID(int=911)), entitlement_id=str(UUID(int=912)))
    submission = replace(archive.production_submissions[0], id=str(UUID(int=913)), approval_id=approval.id, entitlement_id=approval.entitlement_id)
    artifact = replace(archive.feedback_artifacts[0], id=str(UUID(int=914)), document_id=str(UUID(int=915)),
        submission_id=submission.id, sha256=sha256(CONTENT).hexdigest(), byte_length=len(CONTENT))
    created = datetime.fromisoformat(artifact.retrieved_at)
    document = DocumentRecord(DocumentId(artifact.document_id), archive.company_id, archive.income_year,
        'authority_feedback', 'authority-feedback-'+artifact.sha256[:12]+'.xml', 'production_filing_submission:'+submission.id,
        DocumentStatus.STORED, 10, f'{archive.company_id}/2025/{artifact.document_id}/receipt.xml', artifact.content_type,
        len(CONTENT), artifact.sha256, ACTOR, created, None, None)
    receipt = RetainedDocumentOriginalReceipt(str(UUID(int=916)), document.document_id, document.company_id,
        document.income_year, document_metadata_sha256(document), document.content_sha256, document.byte_length, created)
    artifact = replace(artifact, original_id=receipt.original_id, original_metadata_sha256=receipt.metadata_sha256,
        original_source_income_year=int(receipt.source_income_year), original_retained_at=receipt.retained_at.isoformat())
    event = replace(archive.production_events[0], id=str(UUID(int=917)), submission_id=submission.id, artifact_hashes=(artifact.sha256,))
    archive = replace(archive, approvals=(approval,), production_submissions=(submission,), feedback_artifacts=(artifact,),
        production_events=(event,), source_history=rf.Rf1086ArchiveSourceHistory())
    return archive, RetainedDocumentOriginalSnapshot(document, RetainedDocumentOriginal(receipt, CONTENT))


class DocumentsFactory:
    def __init__(self, original): self.original = original
    async def session(self, token):
        original = self.original
        class Session:
            actor_id = ACTOR
            async def read_retained_evidence(self, query): return original
        return Session()


def bundle(archive, original):
    return asyncio.run(archive_feedback_originals(archive, documents_factory=DocumentsFactory(original), access_token='token', actor_id=ACTOR))


def export(archive, original):
    class Session:
        actor_id = ACTOR
        async def archive_source(self, query): return archive
    class Factory:
        async def session(self, token): return Session()
    client = TestClient(create_app(shareholder_register_filing_session_factory=Factory(),
        documents_session_factory=DocumentsFactory(original)))
    return client.get('/api/v1/shareholder-register-filings/archive-source/production',
        headers={'Authorization': 'Bearer token'},
        params={'companyId': str(archive.company_id), 'incomeYear': int(archive.income_year)})


def test_http_export_includes_exact_retained_feedback_and_matches_web_fixture():
    archive, original = feedback_archive()
    response = export(archive, original)
    assert response.status_code == 200, response.text
    wire = response.json()
    assert rf.parse_rf1086_archive(wire['canonicalArchive'], query=query(archive)) == archive
    assert verify_feedback_originals(archive, wire['feedbackOriginals'], require_complete=True) == (original,)
    fixture = Path(__file__).resolve().parents[2]/'web/tests/fixtures/rf1086-feedback-original-archive.json'
    assert wire == json.loads(fixture.read_text())


def test_canonical_v3_and_original_bundle_round_trip_preserve_exact_feedback():
    archive, original = feedback_archive()
    text, reconstructed = round_trip(archive)
    assert json.loads(text)['codec'] == 'rf1086-production-archive-v3'
    values = bundle(reconstructed, original)
    assert verify_feedback_originals(reconstructed, values, require_complete=True) == (original,)
    assert verify_feedback_originals(reconstructed, values)[0].original.content == CONTENT


@pytest.mark.parametrize('field,value', [('original_id', None), ('original_metadata_sha256', 'bad'),
    ('original_source_income_year', 2024), ('original_source_income_year', True), ('original_retained_at', '2026-01-01')])
def test_incomplete_or_mis_scoped_bindings_fail_canonical_validation(field, value):
    archive, _ = feedback_archive()
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.serialize_rf1086_archive(replace(archive, feedback_artifacts=(replace(archive.feedback_artifacts[0], **{field: value}),)), query=query(archive))


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'extra', 'bytes', 'metadata', 'original-id', 'retained-time'])
def test_incomplete_or_corrupt_feedback_originals_fail_closed(change):
    archive, original = feedback_archive(); values = bundle(archive, original)
    if change == 'missing': values = []
    elif change in {'duplicate', 'extra'}: values.append(dict(values[0]))
    else:
        envelope = json.loads(values[0]['canonicalOriginal'])
        if change == 'bytes': envelope['contentBase64'] = 'AA=='
        if change == 'metadata': envelope['documentText'] += ' '
        if change == 'original-id': envelope['receipt']['originalId'] = str(UUID(int=999))
        if change == 'retained-time': envelope['receipt']['retainedAt'] = '2020-01-01T00:00:00+00:00'
        values[0]['canonicalOriginal'] = json.dumps(envelope)
    with pytest.raises(DocumentsError): verify_feedback_originals(archive, values, require_complete=True)


def test_legacy_feedback_remains_partial_and_cannot_claim_complete_originals():
    archive = production_snapshot()
    _, reconstructed = round_trip(archive)
    assert reconstructed.feedback_artifacts[0].original_id is None
    assert verify_feedback_originals(reconstructed, []) == ()
    with pytest.raises(DocumentsError): verify_feedback_originals(reconstructed, [], require_complete=True)


def test_v3_cannot_be_relabelled_as_an_older_archive_codec():
    archive, _ = feedback_archive(); text, _ = round_trip(archive)
    envelope = json.loads(text)
    envelope['codec'] = 'rf1086-production-archive-v2'
    with pytest.raises(rf.Rf1086ArchiveError): rf.parse_rf1086_archive(json.dumps(envelope), query=query(archive))


def test_offline_verifier_requires_feedback_bytes_without_claiming_restoration(tmp_path):
    archive, original = feedback_archive(); text, _ = round_trip(archive)
    value = {'canonicalArchive': text, 'feedbackOriginals': bundle(archive, original)}
    path = tmp_path/'feedback.json'; path.write_text(json.dumps(value))
    script = Path(__file__).resolve().parents[1]/'scripts/verify_rf1086_archive.py'
    command = [sys.executable, str(script), str(path), '--company-id', str(archive.company_id), '--income-year', str(int(archive.income_year)), '--require-feedback-originals']
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout+result.stderr
    report = json.loads(result.stdout)
    assert report['feedbackOriginalBytesVerified'] and report['feedbackOriginalsComplete'] and report['feedbackOriginals'] == 1
    assert report['databaseRestorePerformed'] is False and report['objectBytesVerified'] is False
    value['feedbackOriginals'] = []; path.write_text(json.dumps(value))
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 1 and 'contentBase64' not in result.stdout


@pytest.mark.parametrize('change', [
    {'linked_to': 'production_filing_submission:another-submission'},
    {'document_type': 'accounting_document'},
    {'content_type': 'text/plain'},
])
def test_valid_original_bytes_cannot_replace_feedback_attribution(change):
    archive, original = feedback_archive()
    document = replace(original.document, **change)
    receipt = replace(original.original.receipt, metadata_sha256=document_metadata_sha256(document))
    original = replace(original, document=document, original=replace(original.original, receipt=receipt))
    archive = replace(archive, feedback_artifacts=(replace(archive.feedback_artifacts[0], original_metadata_sha256=receipt.metadata_sha256),))
    response = export(archive, original)
    assert response.status_code == 503
    assert 'canonicalOriginal' not in response.text and 'contentBase64' not in response.text


def test_source_and_feedback_share_one_inline_byte_budget(monkeypatch):
    from talli_backend.application import shareholder_register_archive as composition
    archive, original = feedback_archive()
    monkeypatch.setattr(composition, 'MAX_SOURCE_ORIGINAL_BYTES', len(CONTENT)-1)
    assert export(archive, original).status_code == 503
    with pytest.raises(DocumentsError):
        verify_feedback_originals(archive, [])
