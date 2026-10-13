"""The experiment predicts exact raw bytes; untouched source state is never copied."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time
import struct

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import rf1086_causal_catalog as causal
from rf1086_catalog_causal_capture import NET_IDENTITIES


def raw(rows, database=None, settings=None):
    return ('\n'.join(json.dumps(value, ensure_ascii=False) for value in
        (rows, {} if database is None else database,
         [] if settings is None else settings)) + '\n').encode('utf-8')


def scenario():
    failed = [
        ['schema', 'å"\\[]-PRIVATE-CANARY', 'postgres', None],
        ['schema', 'graphql', 'supabase_admin', None],
        ['schema', 'graphql_public', 'supabase_admin', None],
        *[list(identity) + ['supabase_admin', '{postgres=X/supabase_admin}', False, None]
          for identity in NET_IDENTITIES],
        ['policy', 'public', 'table', 'policy', '*', True, ['PUBLIC'],
         'text with [brackets], "quotes" and \\slashes', None],
    ]
    source = deepcopy(failed)
    source[0][2] = 'source_unrelated_owner'
    for row in source[1:3]:
        row[3] = '{supabase_admin=UC/supabase_admin,anon=U/supabase_admin}'
    for row in source[3:5]:
        row[6:8] = [True, '{search_path=net}']

    def catalog(rows):
        return {'schemas': [{'identity': row[:2], 'row': row} for row in rows[1:3]],
                'functions': [{'identity': row[:4], 'row': row} for row in rows[3:5]]}

    return source, failed, catalog(source), catalog(failed)


def prepare(kind, source=None, failed=None, *, source_raw=None, failed_raw=None):
    s, f, sc, fc = scenario()
    if source is not None:
        s = source
        sc = {'schemas': [{'identity': x[:2], 'row': x} for x in s[1:3]],
              'functions': [{'identity': x[:4], 'row': x} for x in s[3:5]]}
    if failed is not None:
        f = failed
        fc = {'schemas': [{'identity': x[:2], 'row': x} for x in f[1:3]],
              'functions': [{'identity': x[:4], 'row': x} for x in f[3:5]]}
    return causal.prepare_prediction(kind, raw(s) if source_raw is None else source_raw,
        raw(f) if failed_raw is None else failed_raw, source_catalog=sc, failed_catalog=fc,
        deadline=time.monotonic() + 10)


def expected(kind):
    source, failed, _, _ = scenario()
    if kind == 'Is':
        for i in (1, 2):
            failed[i][3] = source[i][3]
    else:
        for i in (3, 4):
            failed[i][6:8] = source[i][6:8]
    return failed


@pytest.mark.parametrize('kind', ('Is', 'In'))
def test_exact_prediction_preserves_failed_unrelated_rows_and_unicode_offsets(kind):
    prediction = prepare(kind)
    actual = raw(expected(kind))
    binding = prediction.binding
    assert binding['expected'] == {'bytes': len(actual), 'sha256': hashlib.sha256(actual).hexdigest()}
    result = prediction.compare(actual, time.monotonic() + 10)
    assert result == binding | {'actual': binding['expected']}
    with pytest.raises(causal.PredictionUnavailable, match='^causal_catalog_unavailable$'):
        prediction.compare(raw(scenario()[0]), time.monotonic() + 10)
    binding['expected']['bytes'] = 0
    assert prediction.binding['expected']['bytes'] == len(actual)
    assert 'PRIVATE-CANARY' not in repr(prediction)


@pytest.mark.parametrize('kind', ('Is', 'In'))
@pytest.mark.parametrize('change', ('unrelated', 'owner', 'target_missing', 'reorder',
                                   'extra', 'database', 'settings', 'spacing', 'terminator'))
def test_any_undeclared_final_byte_change_is_rejected(kind, change):
    rows = expected(kind)
    if change == 'unrelated': rows[0][2] = 'changed'
    if change == 'owner': rows[1 if kind == 'Is' else 3][2 if kind == 'Is' else 4] = 'changed'
    if change == 'target_missing': del rows[1 if kind == 'Is' else 3]
    if change == 'reorder': rows[0], rows[1] = rows[1], rows[0]
    if change == 'extra': rows.append(['schema', 'extra', 'postgres', None])
    actual = raw(rows, {'datname': 'changed'} if change == 'database' else None,
                 [['*', '*', ['search_path=changed']]] if change == 'settings' else None)
    if change == 'spacing': actual = actual.replace(b'[[', b'[ [', 1)
    if change == 'terminator': actual = actual[:-1]
    with pytest.raises(causal.PredictionUnavailable) as error:
        prepare(kind).compare(actual, time.monotonic() + 10)
    assert error.value.reason == 'raw_prediction_mismatch'


@pytest.mark.parametrize('kind,index,field', [('Is', 1, 2), ('Is', 2, 1),
    ('In', 3, 4), ('In', 4, 5), ('In', 3, 3)])
def test_source_row_cannot_change_an_extra_field(kind, index, field):
    source = scenario()[0]
    source[index][field] = 'unexpected'
    with pytest.raises(causal.PredictionUnavailable):
        prepare(kind, source=source)


@pytest.mark.parametrize('kind,index,field', [('Is', 1, 3), ('Is', 2, 3),
    ('In', 3, 6), ('In', 4, 7)])
def test_each_declared_difference_must_actually_exist(kind, index, field):
    source, failed, _, _ = scenario()
    source[index][field] = failed[index][field]
    with pytest.raises(causal.PredictionUnavailable):
        prepare(kind, source=source)


@pytest.mark.parametrize('kind', ('Is', 'In'))
def test_equal_decoded_unmodified_field_with_different_spelling_is_rejected(kind):
    source = raw(scenario()[0])
    # Replace owner spelling only on selected rows, retaining the decoded value.
    source = source.replace(b'"supabase_admin"', b'"\\u0073upabase_admin"')
    with pytest.raises(causal.PredictionUnavailable):
        prepare(kind, source_raw=source)


@pytest.mark.parametrize('kind', ('Is', 'In'))
def test_source_row_spacing_cannot_change_outside_declared_scalars(kind):
    source = raw(scenario()[0]).replace(b'"supabase_admin",', b'"supabase_admin" ,')
    with pytest.raises(causal.PredictionUnavailable):
        prepare(kind, source_raw=source)


@pytest.mark.parametrize('kind', ('Is', 'In'))
@pytest.mark.parametrize('variant', ('duplicate', 'trailing_comma', 'nonfinite', 'bad_utf8',
                                    'extra_line', 'wrong_type', 'not_bytes', 'oversize'))
def test_malformed_or_oversized_input_never_becomes_a_prediction(kind, variant):
    source, failed, _, _ = scenario()
    if variant == 'duplicate': failed.append(failed[1])
    if variant == 'wrong_type': failed[3][6] = 1
    bad = raw(failed)
    if variant == 'trailing_comma': bad = bad.replace(b']\n{}', b',]\n{}')
    if variant == 'nonfinite': bad = bad.replace(b'\n{}\n', b'\n{"anything":NaN}\n')
    if variant == 'bad_utf8': bad = b'\xff' + bad
    if variant == 'extra_line': bad += b'\n'
    if variant == 'not_bytes': bad = bytearray(bad)
    if variant == 'oversize': bad = b' ' * (causal.MAX_CAPTURE_BYTES + 1)
    with pytest.raises(causal.PredictionUnavailable, match='^causal_catalog_unavailable$'):
        prepare(kind, failed_raw=bad)


@pytest.mark.parametrize('kind', ('Is', 'In'))
def test_package_snapshot_row_must_match_raw_row(kind):
    source, failed, sc, fc = scenario()
    sc['schemas' if kind == 'Is' else 'functions'][0]['row'] = ['wrong']
    with pytest.raises(causal.PredictionUnavailable):
        causal.prepare_prediction(kind, raw(source), raw(failed), source_catalog=sc,
                                  failed_catalog=fc, deadline=time.monotonic() + 10)


def test_prediction_growth_is_bounded_before_construction(monkeypatch):
    source, failed, _, _ = scenario()
    source[0][1] = 'short'
    failed[0][1] = 'x' * 8000
    for row in source[1:3]: row[3] = 'x' * 1000
    monkeypatch.setattr(causal, 'MAX_CAPTURE_BYTES', len(raw(failed)) + 1000)
    with pytest.raises(causal.PredictionUnavailable):
        prepare('Is', source=source, failed=failed)


def test_deadlines_checked_before_and_during_preparation_and_comparison(monkeypatch):
    source, failed, sc, fc = scenario()
    for deadline in (True, float('nan'), float('inf'), 0):
        with pytest.raises(causal.PredictionUnavailable) as error:
            causal.prepare_prediction('Is', raw(source), raw(failed), source_catalog=sc,
                                      failed_catalog=fc, deadline=deadline)
        assert error.value.reason == 'deadline'
    prediction = prepare('Is')
    clock = iter(range(1000))
    monkeypatch.setattr(causal.time, 'monotonic', lambda: next(clock))
    with pytest.raises(causal.PredictionUnavailable) as error:
        causal.prepare_prediction('Is', raw(source), raw(failed), source_catalog=sc,
                                  failed_catalog=fc, deadline=4)
    assert error.value.reason == 'deadline'
    with pytest.raises(causal.PredictionUnavailable) as error:
        prediction.compare(raw(expected('Is')), 6)
    assert error.value.reason == 'deadline'


def test_no_other_branch_or_arbitrary_row_set():
    with pytest.raises(causal.PredictionUnavailable):
        prepare('combined')


@pytest.mark.parametrize('kind,selected', [('Is', (1, 2)), ('In', (3, 4))])
def test_outside_commitment_has_three_ordered_length_framed_gaps(kind, selected):
    _, failed, _, _ = scenario()
    baseline, gaps, at = raw(failed), [], 0
    for index in selected:
        row = json.dumps(failed[index], ensure_ascii=False).encode()
        begin = baseline.index(row, at)
        gaps.append(baseline[at:begin])
        at = begin + len(row)
    gaps.append(baseline[at:])
    oracle = b'causal-outside-v1\0' + b''.join(struct.pack('>Q', len(gap)) + gap for gap in gaps)
    assert prepare(kind).binding['outside'] == hashlib.sha256(oracle).hexdigest()


def test_comparison_crosses_chunk_boundary_without_materializing_an_overlay():
    source, failed, _, _ = scenario()
    source[0][1] = failed[0][1] = 'x' * 65536
    prediction = prepare('Is', source=source, failed=failed)
    for i in (1, 2): failed[i][3] = source[i][3]
    actual = raw(failed)
    assert prediction.compare(actual, time.monotonic() + 10)['actual']['bytes'] == len(actual)
    changed = actual[:65536] + b'y' + actual[65537:]
    with pytest.raises(causal.PredictionUnavailable) as error:
        prediction.compare(changed, time.monotonic() + 10)
    assert error.value.reason == 'raw_prediction_mismatch'
