"""Separate v2 codec and preedit v1 byte oracles; no database/owner evidence."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_production import source_case, source_for
from test_rf1086_year_source_v2 import CONFIRMED, prepare, v2_basis


GOLDENS = json.loads((Path(__file__).parent / 'fixtures/rf1086_year_source_v1_pre_v2.json').read_text())


@pytest.mark.parametrize('golden', GOLDENS['vectors'], ids=lambda row: row['kind'])
def test_all_seven_preedit_v1_sources_keep_exact_bytes_case_request_and_source_hashes(golden):
    assert GOLDENS['baseline'] == 'a6a45247804073693eb7aefb0904a82a3640670b'
    case = source_case(golden['kind'])
    if golden['kind'] == 'mixed':
        case = replace(case, share_snapshot=replace(case.share_snapshot, previous_paid_in_premium=0))
    source = source_for(case)
    serialized = rf.serialize_rf1086_year_source(source)
    assert serialized == golden['storage_text']
    assert sha256(serialized.encode()).hexdigest() == golden['storage_sha256']
    assert source.source_sha256 == golden['source_sha256']
    assert source.case_sha256 == golden['case_sha256']
    assert rf.rf1086_year_source_digest(source.command) == golden['request_sha256']
    assert sha256(golden['request_canonical_text'].encode()).hexdigest() == golden['request_sha256']
    assert sha256(golden['case_canonical_text'].encode()).hexdigest() == golden['case_sha256']
    assert rf.serialize_rf1086_year_source(rf.parse_rf1086_year_source(serialized)) == serialized


@pytest.mark.parametrize('kind', ['no_activity', 'formation', 'dividend', 'cash_issue', 'loss_covering_reduction', 'mixed'])
@pytest.mark.parametrize('amendments', [0, 1, 2])
def test_v2_closed_roundtrip_retains_all_commitments_and_exact_legacy_command(kind, amendments):
    command, context = v2_basis(kind, amendments=amendments)
    source = prepare(command, context)
    raw = rf.serialize_rf1086_year_source_v2(source)
    value = json.loads(raw)
    assert value['codec'] == 'rf1086-year-source-v2'
    restored = rf.parse_rf1086_year_source_v2(raw)
    assert type(restored) is rf.Rf1086YearSourceSnapshotV2
    assert restored == source
    assert restored.command == command
    assert restored.governance_projection == context.governance_projection
    assert rf.serialize_rf1086_year_source_v2(restored) == raw


@pytest.mark.parametrize('change', ['old_decoder', 'new_decoder', 'old_tag_new_body', 'new_tag_old_body', 'old_serializer', 'new_serializer'])
def test_v1_v2_codecs_reject_mixed_types_without_extending_old_record_registry(change):
    old = source_for(source_case('no_activity'))
    new = prepare(*v2_basis('no_activity'))
    v1, v2 = rf.serialize_rf1086_year_source(old), rf.serialize_rf1086_year_source_v2(new)
    with pytest.raises(rf.Rf1086YearSourceError):
        if change == 'old_decoder': rf.parse_rf1086_year_source(v2)
        elif change == 'new_decoder': rf.parse_rf1086_year_source_v2(v1)
        elif change == 'old_tag_new_body': rf.parse_rf1086_year_source(v2.replace('rf1086-year-source-v2', 'rf1086-year-source-v1', 1))
        elif change == 'new_tag_old_body': rf.parse_rf1086_year_source_v2(v1.replace('rf1086-year-source-v1', 'rf1086-year-source-v2', 1))
        elif change == 'old_serializer': rf.serialize_rf1086_year_source(new)
        elif change == 'new_serializer': rf.serialize_rf1086_year_source_v2(old)


def serialized():
    return json.loads(rf.serialize_rf1086_year_source_v2(prepare(*v2_basis(amendments=2))))


def records(value, name):
    if isinstance(value, dict):
        if value.get('record') == name:
            yield value['fields']
        for item in value.values():
            yield from records(item, name)
    elif isinstance(value, list):
        for item in value:
            yield from records(item, name)


@pytest.mark.parametrize('change', ['unknown_codec', 'extra_top', 'missing_top', 'unknown_record',
    'missing_field', 'extra_field', 'duplicate_top', 'duplicate_nested', 'nan', 'infinity',
    'bare_decimal', 'bad_decimal', 'executable', 'foreign_record', 'array', 'null', 'bool'])
def test_v2_storage_rejects_open_ambiguous_or_nonfinite_shapes(change):
    value = serialized()
    if change == 'unknown_codec': value['codec'] = 'rf1086-year-source-v3'
    elif change == 'extra_top': value['verified'] = True
    elif change == 'missing_top': del value['snapshot']
    elif change == 'unknown_record': value['snapshot']['record'] = 'Rf1086YearSourceSnapshotV3'
    elif change == 'missing_field': del value['snapshot']['fields']['command']
    elif change == 'extra_field': value['snapshot']['fields']['accepted_owner'] = True
    elif change in ('nan', 'infinity', 'bad_decimal', 'bare_decimal'):
        paid = next(records(value, 'Rf1086PaidInSourceFacts'))
        paid['opening_capital'] = 30000.5 if change == 'bare_decimal' else {'decimal': {'nan':'NaN', 'infinity':'Infinity', 'bad_decimal':'not decimal'}[change]}
    elif change == 'foreign_record': value['snapshot']['fields']['governance_projection']['record'] = 'CorporateGovernanceYearRegisterEvidence'
    elif change == 'executable': value['snapshot'] = {'record': 'eval', 'fields': {'code': 'raise RuntimeError()'}}
    elif change == 'array': value = []
    elif change == 'null': value = None
    elif change == 'bool': value = True
    raw = json.dumps(value, ensure_ascii=False)
    if change == 'duplicate_top': raw = raw.replace('"codec":', '"codec":"wrong","codec":', 1)
    elif change == 'duplicate_nested': raw = raw.replace('"amendment_count":', '"amendment_count":999,"amendment_count":', 1)
    with pytest.raises(rf.Rf1086YearSourceError, match='storage_invalid'):
        rf.parse_rf1086_year_source_v2(raw)


@pytest.mark.parametrize('record,field', [
    ('Rf1086YearSourceSnapshotV2', 'version'),
    ('Rf1086YearGovernanceChainV2', 'amendment_count'),
    ('Rf1086YearGovernanceHeadV2', 'revision'),
    ('Rf1086YearRegisterFactV2', 'version'),
    ('Rf1086YearGovernanceProjectionV2', 'chain_count'),
])
@pytest.mark.parametrize('invalid', [True, False, -1, 1.0, '1', None, {}, []])
def test_v2_integer_claims_never_coerce_wrong_primitives(record, field, invalid):
    value = serialized()
    next(records(value, record))[field] = invalid
    with pytest.raises(rf.Rf1086YearSourceError, match='storage_invalid'):
        rf.parse_rf1086_year_source_v2(json.dumps(value))


@pytest.mark.parametrize('record,field', [
    ('Rf1086YearSourceSnapshotV2', 'source_sha256'),
    ('Rf1086YearSourceSnapshotV2', 'case_sha256'),
    ('Rf1086YearGovernanceChainV2', 'original_finalization_sha256'),
    ('Rf1086YearGovernanceChainV2', 'original_anchor_sha256'),
    ('Rf1086YearGovernanceChainV2', 'enumeration_sha256'),
    ('Rf1086YearGovernanceHeadV2', 'amendment_sha256'),
    ('Rf1086YearRegisterFactV2', 'fact_sha256'),
    ('Rf1086YearGovernanceLinkV2', 'withdrawal_sha256'),
    ('Rf1086YearGovernanceProjectionV2', 'original_enumeration_sha256'),
    ('Rf1086YearGovernanceProjectionV2', 'chain_enumeration_sha256'),
    ('Rf1086YearGovernanceProjectionV2', 'enumeration_sha256'),
    ('Rf1086YearSourceFreshnessV2', 'governance_original_enumeration_sha256'),
    ('Rf1086YearSourceFreshnessV2', 'governance_chain_enumeration_sha256'),
    ('Rf1086YearSourceFreshnessV2', 'governance_projection_sha256'),
])
def test_every_receipt_chain_projection_and_freshness_digest_is_bound(record, field):
    value = serialized()
    next(records(value, record))[field] = 'f' * 64
    with pytest.raises(rf.Rf1086YearSourceError, match='storage_invalid'):
        rf.parse_rf1086_year_source_v2(json.dumps(value))


@pytest.mark.parametrize('record,field', [
    ('Rf1086YearGovernanceChainV2', 'receipt_id'),
    ('Rf1086YearGovernanceHeadV2', 'amendment_id'),
    ('Rf1086YearGovernanceLinkV2', 'withdrawal_id'),
])
@pytest.mark.parametrize('invalid', ['not-a-uuid', '00000000000000000000000000000001', 'AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA', '', None, 1, {}])
def test_new_evidence_identity_claims_are_exact_canonical_uuids(record, field, invalid):
    value = serialized()
    next(records(value, record))[field] = invalid
    with pytest.raises(rf.Rf1086YearSourceError, match='storage_invalid'):
        rf.parse_rf1086_year_source_v2(json.dumps(value))


@pytest.mark.parametrize('record,field', [
    ('Rf1086YearSourceSnapshotV2', 'confirmed_at'),
    ('Rf1086YearGovernanceChainV2', 'original_recorded_at'),
    ('Rf1086YearGovernanceChainV2', 'evidence_cutoff'),
    ('Rf1086YearGovernanceLinkV2', 'recorded_at'),
])
@pytest.mark.parametrize('invalid', ['2026-01-11T12:00:00', 'infinity', '2026-13-01T00:00:00Z', None, True])
def test_new_evidence_times_must_be_finite_aware_instants(record, field, invalid):
    value = serialized()
    next(records(value, record))[field] = {'datetime': invalid}
    with pytest.raises(rf.Rf1086YearSourceError, match='storage_invalid'):
        rf.parse_rf1086_year_source_v2(json.dumps(value))


def test_six_decimal_paid_in_evidence_survives_v2_without_binary64_rounding():
    command, context = v2_basis('no_activity')
    amount = Decimal('2000.123456')
    shares = replace(command.case.share_snapshot, previous_paid_in_premium=amount, current_paid_in_premium=amount)
    command = replace(command, case=replace(command.case, share_snapshot=shares),
        paid_in=replace(command.paid_in, opening_premium=amount, closing_premium=amount))
    source = prepare(command, context)
    loaded = rf.parse_rf1086_year_source_v2(rf.serialize_rf1086_year_source_v2(source))
    assert loaded.command.paid_in.opening_premium == amount
    assert loaded.source_sha256 == source.source_sha256


def test_v2_correction_codec_preserves_ordinal_and_exact_original_v1_predecessor():
    old = rf.parse_rf1086_year_source(GOLDENS['vectors'][0]['storage_text'])
    command, context = v2_basis('no_activity')
    command = replace(command, supersedes_source_id=old.source_id,
        supersedes_source_sha256=old.source_sha256, correction_reason='Årsak\nExact original correction')
    source = prepare(command, context, previous=old,
        source_id=rf.Rf1086YearSourceId('00000000-0000-0000-0000-000000000999'),
        confirmed_at=CONFIRMED + timedelta(days=1))
    raw = rf.serialize_rf1086_year_source_v2(source)
    loaded = rf.parse_rf1086_year_source_v2(raw)
    assert loaded.version == 2
    assert loaded.command.supersedes_source_sha256 == old.source_sha256
    assert loaded.command.correction_reason == command.correction_reason
    assert json.loads(raw)['codec'] == 'rf1086-year-source-v2'
    assert rf.serialize_rf1086_year_source(old) == GOLDENS['vectors'][0]['storage_text']
