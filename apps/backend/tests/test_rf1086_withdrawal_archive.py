"""V5 retains withdrawal evidence; frozen formats keep their original limits."""
from dataclasses import replace
import asyncio
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from uuid import UUID

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.modules.shareholder_register_filing.source_facts import build_source_facts, verify_source_evidence
from test_rf1086_archive_storage import query, round_trip, tamper
from test_rf1086_archive_history import history_archive, DocumentsFactory
from test_rf1086_override_archive import override_archive
from test_rf1086_year_source import ACTOR


def withdrawal_archive(*, empty=False):
    archive, originals = override_archive()
    target = archive.source_history.register_observations[-1]
    command = rf.WithdrawRf1086RegisterObservation(archive.company_id, ACTOR, archive.income_year,
        target.observation_id, target.version, target.fact_sha256, 'Originalen var feil. Ærlig historikk.\n')
    receipt = rf.prepare_rf1086_register_observation_withdrawal(command, observation=target,
        withdrawal_id=rf.Rf1086RegisterObservationWithdrawalId(str(UUID(int=990))),
        withdrawn_at=target.confirmed_at + timedelta(seconds=1, microseconds=123456))
    record = rf.Rf1086ArchiveCaptureRecord(receipt.withdrawal_id.value,
        'withdrawal:' + receipt.withdrawal_id.value, receipt.request_sha256,
        rf.serialize_rf1086_register_observation_withdrawal(receipt))
    return replace(archive, withdrawal_capture_records=() if empty else (record,)), originals


@pytest.mark.parametrize('empty', [False, True])
def test_v5_round_trip_preserves_exact_receipt_key_and_terminal_lineage(empty):
    archive, _ = withdrawal_archive(empty=empty)
    encoded, restored = round_trip(archive)
    assert json.loads(encoded)['codec'] == 'rf1086-production-archive-v5'
    assert restored.withdrawal_capture_records == archive.withdrawal_capture_records
    withdrawals = tuple(rf.parse_rf1086_register_observation_withdrawal(row.snapshot_text)
                        for row in restored.withdrawal_capture_records)
    lifecycle = rf.derive_rf1086_register_observation_lifecycle(company_id=archive.company_id,
        income_year=archive.income_year, observations=restored.source_history.register_observations,
        withdrawals=withdrawals)
    assert [row.status for row in lifecycle] == ['superseded', 'active' if empty else 'withdrawn']
    assert restored.source_approval_lineage == archive.source_approval_lineage
    assert restored.source_history == archive.source_history


@pytest.mark.parametrize('missing', ['source_history', 'overrides', 'withdrawal_capture_records'])
def test_v5_requires_all_three_captured_history_sections(missing):
    archive, _ = withdrawal_archive()
    encoded = rf.serialize_rf1086_archive(archive, query=query(archive))
    for change in (lambda p: p['fields'].pop(missing), lambda p: p['fields'].update({missing: None})):
        with pytest.raises(rf.Rf1086ArchiveError, match='^rf1086_archive_storage_invalid$'):
            rf.parse_rf1086_archive(tamper(encoded, change), query=query(archive))
    if missing != 'withdrawal_capture_records':
        with pytest.raises(rf.Rf1086ArchiveError):
            rf.serialize_rf1086_archive(replace(archive, **{missing: None}), query=query(archive))


@pytest.mark.parametrize('field,value', [
    ('record_id', str(UUID(int=991))), ('record_id', True), ('request_sha256', '0' * 64),
    ('idempotency_key', 'short'), ('idempotency_key', None), ('snapshot_text', '{}'),
    ('snapshot_text', None), ('extra', 'not-a-field'),
])
def test_v5_rejects_corrupt_withdrawal_records_with_recomputed_outer_checksum(field, value):
    archive, _ = withdrawal_archive()
    encoded = rf.serialize_rf1086_archive(archive, query=query(archive))
    changed = tamper(encoded, lambda p: p['fields']['withdrawal_capture_records'][0]['fields'].update({field: value}))
    with pytest.raises(rf.Rf1086ArchiveError, match='^rf1086_archive_storage_invalid$'):
        rf.parse_rf1086_archive(changed, query=query(archive))


def test_v5_rejects_duplicate_withdrawal_or_missing_retained_target():
    archive, _ = withdrawal_archive()
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.serialize_rf1086_archive(replace(archive,
            withdrawal_capture_records=archive.withdrawal_capture_records * 2), query=query(archive))
    history = archive.source_history
    changed = replace(archive, source_history=replace(history,
        register_observations=history.register_observations[:1],
        observation_capture_records=history.observation_capture_records[:1]))
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.serialize_rf1086_archive(changed, query=query(archive))


@pytest.mark.parametrize('version,digest', [
    (1, '08e98630d68d5f850134986166c0a970b344963422132583ac1103a96c5b1a8c'),
    (2, '7fb84f7d41014eb02c98a86ef3acee4a059d00ae08ccd87105ed417ea0c37734'),
    (3, 'e435bce66808c3251cfc52be862ba64f2d7950193d9f725e4ba14f2b62e37750'),
    (4, '1dd3142128cd4f00528201058822541b133bc0391bb5bc6477965963ba6c3140'),
])
def test_v1_through_v4_keep_pre_expansion_bytes_and_unknown_withdrawal_coverage(version, digest):
    # Recorded from these fixture producers before adding the optional field,
    # on commit 5660a7212eef88b3082985be0ac912435b2b6ffa.
    from test_rf1086_archive_source import snapshot as legacy
    from test_rf1086_feedback_archive_originals import feedback_archive
    archive = {1: legacy, 2: lambda: history_archive()[0], 3: lambda: feedback_archive()[0],
               4: lambda: override_archive()[0]}[version]()
    text, restored = round_trip(archive)
    assert sha256(text.encode()).hexdigest() == digest
    assert json.loads(text)['codec'] == f'rf1086-production-archive-v{version}'
    assert restored.withdrawal_capture_records is None
    for injected in ([], None):
        with pytest.raises(rf.Rf1086ArchiveError):
            rf.parse_rf1086_archive(tamper(text,
                lambda p: p['fields'].update(withdrawal_capture_records=injected)), query=query(archive))


@pytest.mark.parametrize('route', ['production', 'production-v4', 'production-stream', 'production-stream-v4'])
def test_old_routes_keep_their_codec_and_do_not_claim_withdrawal_coverage(route):
    from test_rf1086_archive_stream import client
    from talli_backend.application.shareholder_register_archive import verify_archive_stream
    archive, originals = withdrawal_archive()
    response = client(archive, DocumentsFactory(originals)).get(
        '/api/v1/shareholder-register-filings/archive-source/' + route,
        headers={'Authorization': 'Bearer token'},
        params={'companyId': str(archive.company_id), 'incomeYear': int(archive.income_year)})
    assert response.status_code == 200, response.text
    if 'stream' in route:
        restored, original_count, _ = verify_archive_stream(BytesIO(response.content), query=query(archive))
        assert original_count == 5
    else:
        canonical = response.json()['canonicalArchive']
        assert json.loads(canonical)['codec'] == ('rf1086-production-archive-v4' if route.endswith('v4') else 'rf1086-production-archive-v2')
        restored = rf.parse_rf1086_archive(canonical, query=query(archive))
    assert restored == replace(archive, withdrawal_capture_records=None,
        overrides=archive.overrides if route.endswith('v4') else None)
    assert len(archive.withdrawal_capture_records) == 1


@pytest.mark.parametrize('version,digest', [
    (1, '271387258fa335a9ede265f62f6612f762d5a83746f0dfe6adc380c3d8768a63'),
    (2, 'b4c8902a6a5d9297be3a1fb57bd82b5eed5e644bbb96fd423dc928e046be2394'),
])
def test_existing_source_evidence_digest_remains_byte_exact(version, digest):
    from test_rf1086_source_facts import snapshot as legacy
    from test_rf1086_full_year_source_facts import snapshot, query as source_query
    current = legacy() if version == 1 else snapshot()
    facts = build_source_facts(source_query(current), current)
    assert facts.evidence.version == f'rf1086-source-v{version}:{digest}'
    assert facts.evidence.digest == digest


@pytest.mark.parametrize('empty', [False, True])
def test_source_v3_requires_independent_withdrawal_count_and_binds_recovery_identity(empty):
    from test_rf1086_full_year_source_facts import snapshot, query as source_query
    archive, _ = withdrawal_archive(empty=empty)
    current = snapshot(archive)
    # The existing fixture has no overrides in its workspace: match the actual
    # selected archive, while retaining the legacy source-fact scope rules.
    current = replace(current, workspace=replace(current.workspace, overrides=archive.overrides),
        full_year_family_counts={**current.full_year_family_counts,
            'register_observation_withdrawals': len(archive.withdrawal_capture_records)})
    q = source_query(current)
    facts = build_source_facts(q, current)
    assert facts.evidence.version.startswith('rf1086-source-v3:')
    assert facts.history_coverage.status == 'complete', facts.history_coverage.reasons
    assert verify_source_evidence(rf.VerifyRf1086SourceEvidenceQuery(q, facts.evidence), current)
    for overrides in ((), (replace(archive.overrides[0], reason='Different retained reason'),)):
        changed = replace(current, workspace=replace(current.workspace, overrides=overrides))
        assert build_source_facts(q, changed).history_coverage.status == 'incomplete'
    with pytest.raises(rf.ShareholderRegisterFilingError):
        build_source_facts(q, replace(current,
            workspace=replace(current.workspace, overrides=archive.overrides * 2)))
    for count in (None, True, len(archive.withdrawal_capture_records) + 1):
        counts = dict(current.full_year_family_counts)
        if count is None: counts.pop('register_observation_withdrawals')
        else: counts['register_observation_withdrawals'] = count
        invalid = build_source_facts(q, replace(current, full_year_family_counts=counts))
        assert invalid.history_coverage.status == 'incomplete'
    missing = replace(current, full_year_archive=replace(archive, withdrawal_capture_records=None))
    assert 'register_withdrawal_history_missing' in build_source_facts(q, missing).history_coverage.reasons
    if not empty:
        original = archive.withdrawal_capture_records[0]
        changed = replace(current, full_year_archive=replace(archive,
            withdrawal_capture_records=(replace(original, idempotency_key='different-original-key'),)))
        assert build_source_facts(q, changed).history_coverage.status == 'complete'
        assert not verify_source_evidence(rf.VerifyRf1086SourceEvidenceQuery(q, facts.evidence), changed)


@pytest.mark.parametrize('coverage', ['unknown', 'empty', 'recorded'])
@pytest.mark.parametrize('stream', [False, True])
def test_cli_explicitly_requires_captured_withdrawal_history(tmp_path, coverage, stream):
    archive, originals = withdrawal_archive(empty=coverage == 'empty')
    if coverage == 'unknown': archive = replace(archive, withdrawal_capture_records=None)
    path = tmp_path / 'archive.json'
    if stream:
        from talli_backend.application.shareholder_register_archive import prepare_archive_stream
        async def content():
            chunks = await prepare_archive_stream(archive, query=query(archive),
                documents_factory=DocumentsFactory(originals), access_token='synthetic', actor_id=ACTOR)
            return b''.join([chunk async for chunk in chunks])
        path.write_bytes(asyncio.run(content()))
    else:
        path.write_text(rf.serialize_rf1086_archive(archive, query=query(archive)))
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/verify_rf1086_archive.py'),
        str(path), '--company-id', str(archive.company_id), '--income-year', str(int(archive.income_year)),
        '--require-register-withdrawal-history', *(['--stream'] if stream else [])], capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert result.returncode == (1 if coverage == 'unknown' else 0)
    if coverage != 'unknown':
        assert report['registerWithdrawalHistoryIncluded'] is True
        assert report['registerWithdrawals'] == (0 if coverage == 'empty' else 1)
        assert report['databaseRestorePerformed'] is False
        if stream: assert report['sourceOriginals'] == 5
