"""The production archive carries exact retained source versions across filing years."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from talli_backend.application.shareholder_register_archive import archive_source_originals, source_original_queries, verify_source_originals
from talli_backend.main import create_app
from talli_backend.shared.kernel import ActorKind
from talli_backend.modules.documents.public import DocumentsError
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_approval_archive import source_archive
from test_rf1086_year_source import ACTOR
from rf1086_archive_documents import CONTENT, Documents, DocumentsFactory, retained


def bundle(archive=None):
    return asyncio.run(archive_source_originals(archive or source_archive(), documents_factory=DocumentsFactory(), access_token='token', actor_id=ACTOR))


def test_source_bundle_recovers_prior_year_original_and_deduplicates_exact_versions():
    archive = source_archive()
    values = bundle(archive)
    assert len(values) == 1 and values[0]['sourceIncomeYear'] == 2024
    originals = verify_source_originals(archive, values)
    assert originals == (retained(),) and originals[0].original.content == CONTENT
    repeated = replace(archive, source_approval_lineage=archive.source_approval_lineage*2)
    assert bundle(repeated) == values


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'extra', 'scope', 'year', 'hash', 'bytes', 'metadata', 'unknown-field'])
def test_source_bundle_rejects_missing_changed_or_surplus_originals(change):
    archive = source_archive();values = bundle(archive)
    if change == 'missing': values = []
    if change in {'duplicate', 'extra'}: values += [dict(values[0])]
    if change == 'scope': values[0]['companyId'] = '00000000-0000-0000-0000-000000000999'
    if change == 'year': values[0]['sourceIncomeYear'] = 2025
    if change == 'hash': values[0]['metadataSha256'] = 'f'*64
    if change == 'unknown-field': values[0]['ignored'] = True
    if change in {'bytes', 'metadata'}:
        original = json.loads(values[0]['canonicalOriginal'])
        original['contentBase64' if change == 'bytes' else 'documentText'] = 'changed'
        values[0]['canonicalOriginal'] = json.dumps(original)
    with pytest.raises(DocumentsError): verify_source_originals(archive, values)


@pytest.mark.parametrize('failure', ['missing', 'different-actor', 'changed-metadata'])
def test_archive_http_fails_closed_when_exact_original_is_unavailable(failure):
    archive = source_archive()
    class Session:
        actor_id = ACTOR
        async def archive_source(self, query): return archive
    class Sessions:
        async def session(self, token): return Session()
    class BadDocuments(Documents):
        actor_id = replace(ACTOR, kind=ActorKind.SYSTEM) if failure == 'different-actor' else ACTOR
        async def read_retained_evidence(self, query):
            if failure == 'missing': raise DocumentsError.not_found()
            value = retained()
            return replace(value, document=replace(value.document, name='changed'))
    class Factory:
        async def session(self, token): return BadDocuments()
    client = TestClient(create_app(shareholder_register_filing_session_factory=Sessions(), documents_session_factory=Factory()))
    response = client.get('/api/v1/shareholder-register-filings/archive-source/production', headers={'Authorization': 'Bearer token'},
        params={'companyId': str(archive.company_id), 'incomeYear': int(archive.income_year)})
    assert response.status_code == 503
    assert 'contentBase64' not in response.text and 'changed' not in response.text


@pytest.mark.parametrize('wrapper', ['endpoint', 'company_download'])
def test_offline_verifier_checks_actual_exported_source_bytes(tmp_path, wrapper):
    fixture = Path(__file__).resolve().parents[2]/'web/tests/fixtures/rf1086-source-submission-archive.json'
    document = json.loads(fixture.read_text())
    value = document if wrapper == 'endpoint' else {'rf1086Production': document}
    path = tmp_path/'bundle.json';path.write_text(json.dumps(value))
    script = Path(__file__).resolve().parents[1]/'scripts/verify_rf1086_archive.py'
    command = [sys.executable, str(script), str(path), '--company-id', document['companyId'], '--income-year', str(document['incomeYear']), '--require-source-originals']
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout+result.stderr
    report = json.loads(result.stdout)
    assert report['sourceOriginalBytesVerified'] is True and report['sourceOriginals'] == 1
    assert report['databaseRestorePerformed'] is False and report['objectBytesVerified'] is False
    document['sourceOriginals'][0]['canonicalOriginal'] += 'invalid'
    path.write_text(json.dumps(value))
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 1 and 'contentBase64' not in result.stdout


@pytest.mark.parametrize('field,value', [('document_type', 'different'), ('integrity_status', 'attached')])
def test_original_metadata_must_corroborate_captured_source_labels(field, value):
    archive = source_archive();values = bundle(archive);line = archive.source_approval_lineage[0]
    source = replace(line.source, command=replace(line.source.command,
        documents=(replace(line.source.command.documents[0], **{field: value}),)))
    changed = replace(archive, source_approval_lineage=(replace(line, source=source),))
    with pytest.raises(DocumentsError): verify_source_originals(changed, values)
    with pytest.raises(rf.ShareholderRegisterFilingError): bundle(changed)
