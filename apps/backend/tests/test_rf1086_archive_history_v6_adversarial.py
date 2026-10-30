"""Independent retained-history boundary cases; no live authority or byte-store proof."""
from dataclasses import replace
from datetime import timedelta, timezone
from decimal import Decimal
import json

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.modules.shareholder_register_filing.archive_history_v6 import validate
from test_rf1086_archive_history_v6 import (
    capture_observation, capture_source, mixed_archive, replace_projection, with_sources,
)
from test_rf1086_year_source_v2 import CONFIRMED, identity, prepare, v2_basis


ERROR = '^RF source history is inconsistent$'


def test_three_source_versions_retain_explicit_v1_to_v2_transition_and_exact_reason(monkeypatch):
    archive, context = mixed_archive('no_activity', amendments=0, legacy=True)
    first, second = archive.source_history.year_sources
    command = replace(second.command, supersedes_source_id=second.source_id,
        supersedes_source_sha256=second.source_sha256, correction_reason='  Behold årsak.\n')
    third = prepare(command, context, previous=second,
        source_id=rf.Rf1086YearSourceId(identity(7700)), confirmed_at=CONFIRMED + timedelta(seconds=1))
    archive = with_sources(archive, (first, second, third))
    before = tuple(row.snapshot_text for row in archive.source_history.source_capture_records)
    def forbidden(*args, **kwargs): raise AssertionError('Fresh builder called during history validation')
    for name in ('assert_rf1086_source_preview_matches', 'build_rf1086_source_readiness',
                 'build_rf1086_source_readiness_v2', 'build_rf1086_annual_readiness',
                 'build_rf1086_annual_readiness_v2', 'build_rf1086_source_approval_manifest',
                 'build_rf1086_source_approval_manifest_v3'):
        monkeypatch.setattr(rf, name, forbidden)
    validate(archive)
    assert tuple(row.snapshot_text for row in archive.source_history.source_capture_records) == before
    assert third.version == 3 and third.command.correction_reason == '  Behold årsak.\n'


@pytest.mark.parametrize('family', ['source', 'observation'])
@pytest.mark.parametrize('attack', ['unknown_codec', 'wrong_root_record', 'extra_root', 'duplicate_nested_key'])
def test_original_capture_wire_is_checked_before_reconstructed_values(family, attack):
    archive, _ = mixed_archive()
    field = family + '_capture_records'
    records = getattr(archive.source_history, field)
    row = records[0]
    raw = json.loads(row.snapshot_text)
    if attack == 'unknown_codec': raw['codec'] = 'rf1086-future-unrecognized-v99'
    elif attack == 'wrong_root_record': raw['snapshot']['record'] = 'Rf1086SourcePreview'
    elif attack == 'extra_root': raw['verified'] = True
    text = json.dumps(raw, sort_keys=True, separators=(',', ':'))
    if attack == 'duplicate_nested_key':
        marker = '"record":'
        assert marker in text
        text = text.replace(marker, '"record":"ignored",' + marker, 1)
    changed = replace(archive, source_history=replace(archive.source_history,
        **{field: (replace(row, snapshot_text=text), *records[1:])}))
    with pytest.raises(ValueError, match=ERROR): validate(changed)


@pytest.mark.parametrize('field', ['source_capture_records', 'observation_capture_records'])
@pytest.mark.parametrize('attack', ['id', 'request_type', 'key_type', 'raw_type'])
def test_capture_identity_and_exact_scalar_shapes_are_not_value_coerced(field, attack):
    archive, _ = mixed_archive()
    records = getattr(archive.source_history, field)
    class String(str): pass
    row = records[0]
    values = {'id': {'record_id': identity(7701)},
              'request_type': {'request_sha256': String(row.request_sha256)},
              'key_type': {'idempotency_key': String(row.idempotency_key)},
              'raw_type': {'snapshot_text': String(row.snapshot_text)}}[attack]
    changed = replace(archive, source_history=replace(archive.source_history,
        **{field: (replace(row, **values), *records[1:])}))
    with pytest.raises(ValueError, match=ERROR): validate(changed)


@pytest.mark.parametrize('attack', ['missing_head', 'bool_version', 'foreign_company', 'foreign_year', 'stale_source'])
def test_current_retained_head_is_exact_without_claiming_live_currentness(attack):
    archive, _ = mixed_archive(legacy=True)
    history = archive.source_history
    head = history.year_source_head
    if attack == 'missing_head': head = None
    elif attack == 'bool_version': head = replace(head, version=True)
    elif attack == 'foreign_company': head = replace(head, company_id=rf.CompanyId(identity(7702)))
    elif attack == 'foreign_year': head = replace(head, income_year=rf.IncomeYear(2024))
    else: head = replace(head, source_id=history.year_sources[0].source_id)
    with pytest.raises(ValueError, match=ERROR):
        validate(replace(archive, source_history=replace(history, year_source_head=head)))


@pytest.mark.parametrize('which', ['original', 'intermediate'])
def test_rehashed_compact_fact_hash_still_requires_exact_retained_observation(which):
    archive, context = mixed_archive()
    chain = context.governance_projection.chains[0]
    if which == 'original':
        fact = replace(chain.original_register_fact, fact_sha256='e' * 64)
        chain = replace(chain, original_register_fact=fact,
            amendments=(replace(chain.amendments[0], target=fact), chain.amendments[1]))
        wrapped = context.governance_receipts[0]
        context = replace(context, governance_receipts=(replace(wrapped,
            original=replace(wrapped.original, register_observation_sha256=fact.fact_sha256)),))
    else:
        fact = replace(chain.amendments[0].replacement, fact_sha256='e' * 64)
        chain = replace(chain, amendments=(replace(chain.amendments[0], replacement=fact),
            replace(chain.amendments[1], target=fact)))
    changed = replace_projection(archive, context, (chain,))
    rf.assert_rf1086_year_source_integrity_v2(changed.source_history.year_sources[0])
    with pytest.raises(ValueError, match=ERROR): validate(changed)


@pytest.mark.parametrize('attack', ['missing_receipt', 'empty_receipts', 'duplicate_receipt', 'wrong_recovery_key'])
def test_withdrawals_preserve_exact_recovery_identity_and_do_not_invent_empty_coverage(attack):
    archive, _ = mixed_archive()
    records = archive.withdrawal_capture_records
    if attack == 'missing_receipt': records = None
    elif attack == 'empty_receipts': records = ()
    elif attack == 'duplicate_receipt': records = (*records, records[0])
    else: records = (replace(records[0], idempotency_key='invalid'), *records[1:])
    with pytest.raises(ValueError, match=ERROR): validate(replace(archive, withdrawal_capture_records=records))


@pytest.mark.parametrize('coverage', [None, ()])
def test_off_year_chains_are_preserved_without_local_observation_or_withdrawal_invention(coverage):
    archive, context = mixed_archive('no_activity', amendments=0)
    _, capital = v2_basis(amendments=2)
    chain = replace(capital.governance_projection.chains[0], income_year=rf.IncomeYear(2024))
    archive = replace_projection(archive, context, (chain,))
    archive = replace(archive, withdrawal_capture_records=coverage)
    raw = archive.source_history.source_capture_records[0].snapshot_text
    validate(archive)
    assert archive.source_history.register_observations == ()
    assert archive.withdrawal_capture_records is coverage
    assert archive.source_history.source_capture_records[0].snapshot_text == raw


def test_effective_body_cannot_change_offset_representation_behind_equal_dataclass_values():
    archive, _ = mixed_archive(amendments=0)
    history = archive.source_history
    embedded = history.year_sources[0].governance_receipts[0].register_observation
    altered = replace(history.register_observations[0],
        confirmed_at=embedded.confirmed_at.astimezone(timezone(timedelta(hours=1))))
    assert altered == embedded
    assert rf.serialize_rf1086_register_observation(altered) != rf.serialize_rf1086_register_observation(embedded)
    changed = replace(archive, source_history=replace(history, register_observations=(altered,),
        observation_capture_records=(capture_observation(altered),)))
    with pytest.raises(ValueError, match=ERROR): validate(changed)


def test_original_observation_capture_must_match_retained_effective_body_representation():
    archive, _ = mixed_archive(amendments=0)
    history = archive.source_history
    original = history.register_observations[0]
    altered = replace(original, confirmed_at=original.confirmed_at.astimezone(timezone(timedelta(hours=1))))
    assert altered == original
    # Only the original recovery text changes. Re-serializing the typed row before
    # validation would hide this retained-wire disagreement.
    changed = replace(archive, source_history=replace(history,
        observation_capture_records=(capture_observation(altered),)))
    with pytest.raises(ValueError, match=ERROR): validate(changed)


def test_consistent_original_offset_representation_remains_available():
    archive, context = mixed_archive(amendments=0)
    history = archive.source_history
    original = history.register_observations[0]
    altered = replace(original, confirmed_at=original.confirmed_at.astimezone(timezone(timedelta(hours=1))))
    wrapped = context.governance_receipts[0]
    context = replace(context, governance_receipts=(replace(wrapped, register_observation=altered),))
    source = prepare(history.year_sources[0].command, context, source_id=history.year_sources[0].source_id)
    changed = with_sources(archive, (source,))
    changed = replace(changed, source_history=replace(changed.source_history,
        register_observations=(altered,), observation_capture_records=(capture_observation(altered),)))
    validate(changed)
    assert '+01:00' in changed.source_history.observation_capture_records[0].snapshot_text
    assert changed.source_history.year_sources[0].governance_receipts[0].register_observation is altered


def test_source_capture_cannot_substitute_equal_numeric_values_with_different_original_scale():
    archive, _ = mixed_archive('no_activity', amendments=0)
    history = archive.source_history
    source = history.year_sources[0]
    changed_paid_in = replace(source.command.paid_in,
        opening_capital=Decimal(str(source.command.paid_in.opening_capital)).quantize(Decimal('0.00')))
    altered = replace(source, command=replace(source.command, paid_in=changed_paid_in))
    assert altered == source
    assert rf.serialize_rf1086_year_source_v2(altered) != rf.serialize_rf1086_year_source_v2(source)
    changed = replace(archive, source_history=replace(history,
        source_capture_records=(capture_source(altered),)))
    with pytest.raises(ValueError, match=ERROR): validate(changed)


def test_consistent_original_numeric_scale_remains_available():
    archive, _ = mixed_archive('no_activity', amendments=0)
    source = archive.source_history.year_sources[0]
    paid_in = replace(source.command.paid_in,
        opening_capital=Decimal(str(source.command.paid_in.opening_capital)).quantize(Decimal('0.00')))
    altered = replace(source, command=replace(source.command, paid_in=paid_in))
    archive = with_sources(archive, (altered,))
    validate(archive)
    assert '30000.00' in archive.source_history.source_capture_records[0].snapshot_text


def test_new_history_lineage_rejects_equal_value_but_different_source_representation():
    from test_rf1086_archive_history import history_archive
    from talli_backend.modules.shareholder_register_filing.archive_history import validate as legacy_validate
    archive, _ = history_archive()
    line = archive.source_approval_lineage[0]
    altered = replace(line.source,
        confirmed_at=line.source.confirmed_at.astimezone(timezone(timedelta(hours=1))))
    assert altered == line.source
    changed = replace(archive, source_approval_lineage=(replace(line, source=altered),))
    # This is existing history-helper behavior; do not change the frozen reader.
    legacy_validate(changed)
    with pytest.raises(rf.Rf1086YearSourceError): rf.assert_rf1086_year_source_integrity(altered)
    with pytest.raises(ValueError, match=ERROR): validate(changed)
