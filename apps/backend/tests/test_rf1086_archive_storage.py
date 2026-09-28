"""Archived RF source facts are reconstructed and checked by their Python owner."""
from dataclasses import replace
from hashlib import sha256
import json

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_archive_source import snapshot as legacy_snapshot, production_snapshot
from test_rf1086_source_submission_archive import source_submission_archive
from test_rf1086_year_source import ACTOR


def query(snapshot):
    return rf.Rf1086ArchiveQuery(snapshot.company_id, snapshot.income_year, ACTOR)


def round_trip(snapshot):
    text = rf.serialize_rf1086_archive(snapshot, query=query(snapshot))
    result = rf.parse_rf1086_archive(text, query=query(snapshot))
    assert result == snapshot
    assert rf.serialize_rf1086_archive(result, query=query(snapshot)) == text
    return text, result


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'dividend', 'cash_issue', 'loss_covering_reduction'])
@pytest.mark.parametrize('status', ['approved', 'accepted', 'rejected'])
def test_complete_source_records_round_trip_without_losing_facts_or_authority_evidence(kind, status):
    original = source_submission_archive(kind, status)
    _, result = round_trip(original)
    assert result.source_approval_lineage[0].source.governance_receipts == original.source_approval_lineage[0].source.governance_receipts
    assert result.source_approval_lineage[0].source.freshness == original.source_approval_lineage[0].source.freshness
    assert result.source_submission_claims == original.source_submission_claims
    with pytest.raises(TypeError):
        result.approvals[0].manifest['incomeYear'] = 2024


@pytest.mark.parametrize('factory', [legacy_snapshot, production_snapshot])
def test_legacy_archive_history_remains_round_trippable(factory):
    round_trip(factory())


def test_legacy_json_number_types_are_preserved_without_source_arithmetic():
    original = legacy_snapshot()
    simulation = replace(original.simulations[0], submitted_payload={'historical': 1.1})
    _, result = round_trip(replace(original, simulations=(simulation,)))
    assert type(result.simulations[0].submitted_payload['historical']) is float


def tamper(text, change):
    envelope = json.loads(text)
    payload = json.loads(envelope['snapshotText'])
    change(payload)
    # Recompute the outer checksum: owner validation must detect semantic
    # corruption independently of the container's accidental-damage checksum.
    envelope['snapshotText'] = json.dumps(payload, ensure_ascii=False)
    envelope['sha256'] = sha256(envelope['snapshotText'].encode()).hexdigest()
    return json.dumps(envelope)


@pytest.mark.parametrize('change', [
    lambda p: p.update(record='ExecutableType'),
    lambda p: p['fields'].update(unknown='unexpected'),
    lambda p: p['fields'].pop('source_approval_lineage'),
    lambda p: p['fields'].update(source_submission_claims=[]),
    lambda p: p['fields'].update(submission_head=None),
    lambda p: p['fields']['submission_head']['fields'].update(environment='test'),
    lambda p: p['fields']['source_submission_claims'][0]['fields'].update(payload_sha256='f'*64),
    lambda p: p['fields']['source_approval_lineage'][0]['fields'].update(review_text='{}'),
    lambda p: p['fields']['production_events'][0]['fields'].update(body_hash='f'*64),
    lambda p: p['fields'].update(feedback_artifacts=[]),
])
def test_changed_evidence_fails_even_with_a_recomputed_outer_checksum(change):
    original = source_submission_archive()
    text = rf.serialize_rf1086_archive(original, query=query(original))
    with pytest.raises(rf.Rf1086ArchiveError, match='^rf1086_archive_storage_invalid$'):
        rf.parse_rf1086_archive(tamper(text, change), query=query(original))


def test_changed_source_case_is_rejected_by_existing_source_integrity_policy():
    original = source_submission_archive()
    text = rf.serialize_rf1086_archive(original, query=query(original))
    def change(payload):
        source = payload['fields']['source_approval_lineage'][0]['fields']['source']
        source['fields']['command']['fields']['case']['fields']['company']['fields']['name'] = 'changed' 
    with pytest.raises(rf.Rf1086ArchiveError, match='^rf1086_archive_storage_invalid$'):
        rf.parse_rf1086_archive(tamper(text, change), query=query(original))


def test_captured_snapshot_cannot_be_retargeted_to_another_company_or_year():
    original = source_submission_archive()
    text = rf.serialize_rf1086_archive(original, query=query(original))
    for changed in [replace(query(original), company_id=rf.CompanyId('00000000-0000-0000-0000-000000000099')),
                    replace(query(original), income_year=rf.IncomeYear(2024))]:
        with pytest.raises(rf.Rf1086ArchiveError):
            rf.parse_rf1086_archive(text, query=changed)


@pytest.mark.parametrize('bad', [None, '', '{}', 'null', '[]', '{"codec":1,"codec":2}', '{"codec":NaN}'])
def test_malformed_envelope_has_closed_diagnostics(bad):
    original = source_submission_archive()
    with pytest.raises(rf.Rf1086ArchiveError, match='^rf1086_archive_storage_invalid$'):
        rf.parse_rf1086_archive(bad, query=query(original))


def test_container_digest_and_version_are_required():
    original = source_submission_archive()
    envelope = json.loads(rf.serialize_rf1086_archive(original, query=query(original)))
    for changed in [{**envelope, 'sha256': 'f'*64}, {**envelope, 'codec': 'future'}, {**envelope, 'extra': True}]:
        with pytest.raises(rf.Rf1086ArchiveError):
            rf.parse_rf1086_archive(json.dumps(changed), query=query(original))

@pytest.mark.parametrize('wrapper', ['canonical', 'endpoint', 'company_download'])
def test_local_verifier_accepts_actual_export_forms_without_database_or_provider(tmp_path, wrapper):
    import subprocess
    import sys
    from pathlib import Path
    original = source_submission_archive(status='approved')
    text = rf.serialize_rf1086_archive(original, query=query(original))
    if wrapper == 'endpoint':text = json.dumps({'canonicalArchive': text})
    if wrapper == 'company_download':text = json.dumps({'rf1086Production': {'canonicalArchive': text}})
    archive = tmp_path / 'archive.json';archive.write_text(text)
    script = Path(__file__).resolve().parents[1] / 'scripts/verify_rf1086_archive.py'
    result = subprocess.run([sys.executable, str(script), str(archive), '--company-id', str(original.company_id),
        '--income-year', str(int(original.income_year))], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['status'] == 'verified_rf_canonical_record' and report['sourceClaims'] == 1
    assert report['databaseRestorePerformed'] is False and report['objectBytesVerified'] is False


@pytest.mark.parametrize('corruption', ['missing', 'malformed', 'scope', 'facts'])
def test_local_verifier_rejects_missing_changed_or_wrong_scope_record_without_data_leak(tmp_path, corruption):
    import subprocess
    import sys
    from pathlib import Path
    original = source_submission_archive(status='approved')
    text = rf.serialize_rf1086_archive(original, query=query(original))
    if corruption == 'missing':text = '{}'
    if corruption == 'malformed':text = 'not-json-private-content'
    if corruption == 'facts':text = tamper(text, lambda p: p['fields'].update(source_submission_claims=[]))
    archive = tmp_path / 'archive.json';archive.write_text(text)
    script = Path(__file__).resolve().parents[1] / 'scripts/verify_rf1086_archive.py'
    result = subprocess.run([sys.executable, str(script), str(archive), '--company-id', str(original.company_id),
        '--income-year', '2024' if corruption == 'scope' else str(int(original.income_year))], text=True, capture_output=True)
    assert result.returncode == 1 and result.stderr == ''
    assert json.loads(result.stdout) == {'status': 'invalid', 'code': 'rf1086_archive_verification_failed'}


def test_correction_chain_and_unknown_outcome_round_trip_without_changing_submission_state():
    from uuid import UUID
    from test_rf1086_source_submission_archive import correction_archive
    from test_rf1086_full_year_correction import full_year_predecessor
    round_trip(correction_archive())
    original = source_submission_archive(status='approved')
    event = replace(full_year_predecessor().reconciliation_events[0], operation_name='post_hovedskjema',
        operation_state='unknown', resulting_status='unknown',
        body_hash=original.approvals[0].manifest['documentHashes'][0]['sha256'],
        idempotency_key=str(UUID(int=990)), authority_reference=None, artifact_hashes=(), failure_class='unknown')
    original = replace(original, production_events=(event,), production_submissions=(replace(
        original.production_submissions[0], status='unknown', failure_class='unknown'),))
    _, restored = round_trip(original)
    assert restored.production_submissions[0].status == 'unknown'
    assert restored.production_events[0].idempotency_key == event.idempotency_key


def test_duplicate_fields_nonfinite_values_and_oversize_records_fail_closed(monkeypatch):
    from talli_backend.modules.shareholder_register_filing import archive_storage
    original = source_submission_archive()
    text = rf.serialize_rf1086_archive(original, query=query(original))
    envelope = json.loads(text)
    repeated = envelope['snapshotText'].replace('"record":"Rf1086ArchiveSnapshot"',
        '"record":"Rf1086ArchiveSnapshot","record":"Rf1086ArchiveSnapshot"')
    envelope.update(snapshotText=repeated, sha256=sha256(repeated.encode()).hexdigest())
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.parse_rf1086_archive(json.dumps(envelope), query=query(original))
    corrupted = tamper(text, lambda p: p['fields'].update(production_events=float('nan')))
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.parse_rf1086_archive(corrupted, query=query(original))
    monkeypatch.setattr(archive_storage, '_MAX_BYTES', len(text.encode()) - 1)
    with pytest.raises(rf.Rf1086ArchiveError):rf.parse_rf1086_archive(text, query=query(original))
    with pytest.raises(rf.Rf1086ArchiveError):rf.serialize_rf1086_archive(original, query=query(original))
