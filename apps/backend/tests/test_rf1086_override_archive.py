"""Override history is portable, scoped and distinguishable from uncaptured history."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess
import sys
from uuid import UUID

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_archive_history import history_archive, export as legacy_export, DocumentsFactory
from test_rf1086_archive_storage import query, round_trip, tamper
from test_rf1086_year_source import ACTOR, NOW


def export(archive, originals):
    from test_rf1086_archive_stream import client
    return client(archive, DocumentsFactory(originals)).get(
        '/api/v1/shareholder-register-filings/archive-source/production-v4',
        headers={'Authorization': 'Bearer token'},
        params={'companyId': str(archive.company_id), 'incomeYear': int(archive.income_year)})


def override_archive():
    archive, originals = history_archive()
    row = rf.Rf1086OverrideRecord(str(UUID(int=980)), archive.previews[0].id,
        str(archive.company_id), int(archive.income_year), 'aksjonærregisteroppgaven',
        'review.note', 'Original æ', 'Revised ø', 'Owner recorded explanation', 'advisory',
        str(ACTOR.subject), NOW.isoformat(), str(ACTOR.subject), NOW.isoformat())
    return replace(archive, overrides=(row,)), originals


def test_override_v4_round_trip_preserves_all_fields_and_http_projection():
    archive, originals = override_archive()
    text, restored = round_trip(archive)
    assert json.loads(text)['codec'] == 'rf1086-production-archive-v4'
    assert asdict(restored.overrides[0]) == asdict(archive.overrides[0])
    response = export(archive, originals)
    assert response.status_code == 200, response.text
    row = response.json()['overrides'][0]
    assert row['reason'] == archive.overrides[0].reason
    assert row['oldValue'] == 'Original æ' and row['newValue'] == 'Revised ø'
    assert row['ownerConfirmedBy'] == str(ACTOR.subject)
    assert rf.parse_rf1086_archive(response.json()['canonicalArchive'], query=query(archive)) == archive


def test_existing_json_route_preserves_old_shape_and_codec_while_v4_captures_overrides():
    archive, originals = override_archive()
    response = legacy_export(archive, originals)
    assert response.status_code == 200, response.text
    assert 'overrides' not in response.json()
    canonical = response.json()['canonicalArchive']
    assert json.loads(canonical)['codec'] == 'rf1086-production-archive-v2'
    assert rf.parse_rf1086_archive(canonical, query=query(archive)) == replace(archive, overrides=None)
    # The transport projection leaves the authoritative snapshot intact.
    complete = export(archive, originals)
    assert complete.json()['overrides'][0]['id'] == archive.overrides[0].id
    assert rf.parse_rf1086_archive(complete.json()['canonicalArchive'], query=query(archive)) == archive


def test_existing_feedback_route_keeps_v3_after_backend_expansion():
    from test_rf1086_feedback_archive_originals import feedback_archive, export as feedback_export
    archive, original = feedback_archive()
    archive = replace(archive, overrides=())
    response = feedback_export(archive, original)
    assert response.status_code == 200, response.text
    assert 'overrides' not in response.json()
    assert json.loads(response.json()['canonicalArchive'])['codec'] == 'rf1086-production-archive-v3'


@pytest.mark.parametrize('complete', [False, True])
def test_stream_routes_preserve_old_consumers_and_offer_explicit_complete_history(complete):
    from io import BytesIO
    from test_rf1086_archive_stream import client
    from talli_backend.application.shareholder_register_archive import verify_archive_stream
    archive, originals = override_archive()
    path = '/api/v1/shareholder-register-filings/archive-source/production-stream' + ('-v4' if complete else '')
    response = client(archive, DocumentsFactory(originals)).get(path,
        headers={'Authorization': 'Bearer token'},
        params={'companyId': str(archive.company_id), 'incomeYear': int(archive.income_year)})
    assert response.status_code == 200, response.text
    restored, *_ = verify_archive_stream(BytesIO(response.content), query=query(archive))
    assert restored == (archive if complete else replace(archive, overrides=None))


@pytest.mark.parametrize('route', ['production-v4', 'production-stream-v4'])
def test_complete_routes_never_invent_capture_for_unknown_history(route):
    from test_rf1086_archive_stream import client
    archive, originals = override_archive()
    archive = replace(archive, overrides=None)
    response = client(archive, DocumentsFactory(originals)).get(
        '/api/v1/shareholder-register-filings/archive-source/' + route,
        headers={'Authorization': 'Bearer token'},
        params={'companyId': str(archive.company_id), 'incomeYear': int(archive.income_year)})
    assert response.status_code == 503


def test_known_empty_history_and_uncaptured_history_are_distinct():
    archive, _ = override_archive()
    known, _ = round_trip(replace(archive, overrides=()))
    old, restored = round_trip(replace(archive, overrides=None))
    assert json.loads(known)['codec'] == 'rf1086-production-archive-v4'
    assert json.loads(old)['codec'] == 'rf1086-production-archive-v2'
    assert restored.overrides is None
    # Older records cannot gain a completeness claim through an injected field.
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.parse_rf1086_archive(tamper(old, lambda p: p['fields'].update(overrides=[])), query=query(archive))


@pytest.mark.parametrize('instant', ['2026-09-30T12:00:00.123456Z', '2026-09-30T14:00:00.123456+02:00'])
def test_override_round_trip_preserves_timestamp_precision_and_offset(instant):
    archive, _ = override_archive()
    archive = replace(archive, overrides=(replace(archive.overrides[0], created_at=instant),))
    _, restored = round_trip(archive)
    assert restored.overrides[0].created_at == instant


@pytest.mark.parametrize('field,value', [
    ('company_id', str(UUID(int=999))), ('income_year', 2024), ('income_year', True),
    ('filing', 'company_tax'), ('preview_id', str(UUID(int=999))),
    ('id', 'bad'), ('owner_confirmed_by', None), ('created_by', 'bad'),
    ('owner_confirmed_at', '2026-09-30'), ('created_at', 'invalid'),
    ('created_at', '2026-02-30T12:00:00Z'), ('created_at', '2026-09-30T24:00:00Z'),
    ('created_at', '2026-09-30T12:00:00+00:60'), ('created_at', '20260930T120000Z'),
    ('owner_confirmed_at', '2026-09-30 12:00:00Z'),
    ('risk_level', 'unknown'), ('reason', None), ('old_value', 12), ('new_value', {}),
])
def test_invalid_override_fails_even_with_recomputed_container_checksum(field, value):
    archive, _ = override_archive()
    text = rf.serialize_rf1086_archive(archive, query=query(archive))
    changed = tamper(text, lambda p: p['fields']['overrides'][0]['fields'].update({field: value}))
    with pytest.raises(rf.Rf1086ArchiveError, match='rf1086_archive_storage_invalid'):
        rf.parse_rf1086_archive(changed, query=query(archive))


@pytest.mark.parametrize('change', [
    lambda p: p['fields'].pop('overrides'),
    lambda p: p['fields'].update(overrides=None),
    lambda p: p['fields']['overrides'].append(p['fields']['overrides'][0]),
    lambda p: p['fields']['overrides'][0]['fields'].update(unknown='hidden'),
])
def test_v4_requires_closed_override_records(change):
    archive, _ = override_archive()
    text = rf.serialize_rf1086_archive(archive, query=query(archive))
    with pytest.raises(rf.Rf1086ArchiveError):
        rf.parse_rf1086_archive(tamper(text, change), query=query(archive))


@pytest.mark.parametrize('history', ['legacy', 'empty', 'recorded'])
def test_cli_requires_explicit_override_history(tmp_path, history):
    archive, _ = override_archive()
    if history != 'recorded':
        archive = replace(archive, overrides=None if history == 'legacy' else ())
    path = tmp_path / 'archive.json'
    path.write_text(rf.serialize_rf1086_archive(archive, query=query(archive)))
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/verify_rf1086_archive.py'),
        str(path), '--company-id', str(archive.company_id), '--income-year', str(int(archive.income_year)),
        '--require-override-history'], capture_output=True, text=True)
    report = json.loads(result.stdout)
    assert result.returncode == (1 if history == 'legacy' else 0)
    if history != 'legacy':
        assert report['overrideHistoryIncluded'] is True
        assert report['overrides'] == (1 if history == 'recorded' else 0)
