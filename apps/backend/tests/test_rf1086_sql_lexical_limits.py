"""Finite rejection diagnostics use synthetic inputs, never retained CI data."""
from copy import deepcopy
import hashlib
import json
import time
import tracemalloc

import pytest

from test_rf1086_sql_ledger import ledger, lexical, receipt_context
from test_rf1086_actual_replay import setup, key
from test_rf1086_full_sql_control import control, replay

COPY = b'COPY public.fixture (value) FROM stdin;\n'
META = (b'\\restrict key\n', b'\\unrestrict key\n', b'\\connect postgres\n',
        b'\\restrict key\n', b'\\unrestrict key\n')


def scan(raw, **kw):
    return lexical.scan(raw, deadline=time.monotonic()+5, profile=lexical.PROFILE, **kw)


@pytest.mark.parametrize('bound', [8, 262144])
def test_trivia_does_not_consume_the_retained_token_bound(monkeypatch, bound):
    monkeypatch.setattr(lexical, 'MAX_RECORDS', bound)
    prefix = b' \t-- discard\n' * (bound//2+1)
    raw = prefix+b'SELECT 1;\n'
    result = scan(raw)
    start = len(prefix)
    assert list(lexical.RECORD.iter_unpack(result.tokens)) == [
        (lexical.IDENT, start, start+6),
        (lexical.NUMBER, start+7, start+8),
        (lexical.PUNCT, start+8, start+9),
    ]
    assert list(lexical.RECORD.iter_unpack(result.leaves)) == [
        (lexical.TRIVIA, 0, start), (lexical.SQL, start, start+9),
        (lexical.TRIVIA, start+9, len(raw)),
    ]
    receipt = json.loads(result.receipt)
    assert receipt['input'] == {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    assert receipt['statements'] == 1 and receipt['tokens']['bytes'] == 3*lexical.RECORD.size


@pytest.mark.parametrize('wrapper', [lambda n: b' '*n,
    lambda n: b'--'+b'x'*(n-3)+b'\n', lambda n: b'/*'+b'x'*(n-4)+b'*/'])
def test_omitted_trivia_still_obeys_exact_token_length_bound(monkeypatch, wrapper):
    monkeypatch.setattr(lexical, 'MAX_TOKEN', 64)
    scan(wrapper(64)+b'SELECT 1;\n')
    with pytest.raises(lexical.Unavailable) as caught:
        scan(wrapper(65)+b'SELECT 1;\n')
    assert caught.value.limit == {'site': 'token_bytes', 'ceiling': 64,
        'observed': 65, 'unit': 'bytes', 'offset': 65}


def test_significant_token_guard_keeps_its_exact_boundary_and_original_offset(monkeypatch):
    monkeypatch.setattr(lexical, 'MAX_RECORDS', 3)
    prefix = b'-- prefix\n'*10
    assert len(scan(prefix+b'SELECT 1;\n').tokens) == 3*lexical.RECORD.size
    with pytest.raises(lexical.Unavailable) as caught:
        scan(prefix+b'SELECT 1,2;\n')
    assert caught.value.limit == {'site': 'token_records', 'ceiling': 3,
        'observed': 4, 'unit': 'records', 'offset': len(prefix)+10}


def test_leaf_and_aggregate_index_guards_still_include_trivia_leaves(monkeypatch):
    monkeypatch.setattr(lexical, 'MAX_RECORDS', 3)
    raw = META[0]+b'-- middle\n'+META[-1]+b'-- suffix\n'
    with pytest.raises(lexical.Unavailable) as caught:
        scan(raw, expected_meta=(META[0], META[-1]))
    assert caught.value.limit == {'site': 'leaf_records', 'ceiling': 3,
        'observed': 4, 'unit': 'records', 'offset': len(raw)}
    monkeypatch.setattr(lexical, 'MAX_INDEX', 35)
    with pytest.raises(lexical.Unavailable) as caught:
        scan(b'SELECT 1;\n')
    assert caught.value.limit == {'site': 'index_bytes', 'ceiling': 35,
        'observed': 36, 'unit': 'bytes', 'offset': 9}


@pytest.mark.parametrize('token_limit,line_bytes', [(1048576, 2*1024**2), (64, 65)])
def test_copy_row_length_is_independent_of_sql_token_limit(monkeypatch, token_limit, line_bytes):
    monkeypatch.setattr(lexical, 'MAX_TOKEN', token_limit)
    payload = b'x'*line_bytes+b'\n'
    raw = COPY+payload+b'\\.\nSELECT 1;\n'
    result = scan(raw, copy_commands=(COPY,))
    leaves = list(lexical.RECORD.iter_unpack(result.leaves))
    assert [(a, z) for kind, a, z in leaves if kind == lexical.COPY_DATA] == [(len(COPY), len(COPY)+len(payload))]
    assert [(a, z) for kind, a, z in leaves if kind == lexical.COPY_END] == [(len(COPY)+len(payload), len(COPY)+len(payload)+3)]
    assert leaves[0][1] == 0 and leaves[-1][2] == len(raw)
    assert all(left[2] == right[1] for left, right in zip(leaves, leaves[1:]))
    receipt = json.loads(result.receipt)
    assert receipt['statements'] == 2
    assert receipt['input'] == {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


@pytest.mark.parametrize('cap,ceiling,site', [
    # Allow the header/meta leaves, then reject the first SET's fifth token.
    ('MAX_RECORDS', 4, 'token_records'),
    ('MAX_STATEMENTS', 1, 'statements'),
])
def test_observation_identifies_the_first_rejected_guard(tmp_path, monkeypatch, cap, ceiling, site):
    monkeypatch.setattr(lexical, cap, ceiling)
    value, args = receipt_context(tmp_path)
    assert (value['status'], value['reason'], value['stage']) == ('unavailable', 'limit', 'lexical')
    detail = value['context']['limit']
    assert detail['site'] == site
    assert detail['ceiling'] == ceiling and detail['observed'] == ceiling + 1
    assert 0 <= detail['offset'] <= args['fsql']['stream']['bytes']
    assert ledger.validate_receipt(value, **args) is value


@pytest.mark.parametrize('caps,raw,kwargs,site,unit,position', [
    ({'MAX_BINDINGS': 8}, COPY+b'\\.\n', {'copy_commands': (COPY,)}, 'binding_bytes', 'bytes', False),
    ({'MAX_RECORDS': 1}, b'SELECT 1;\n', {}, 'token_records', 'records', True),
    ({'MAX_RECORDS': 1}, b''.join(META), {'expected_meta': META}, 'leaf_records', 'records', True),
    ({'MAX_INDEX': 8}, b'SELECT 1;\n', {}, 'index_bytes', 'bytes', True),
    ({'MAX_TOKEN': 8}, b"'0123456789';\n", {}, 'token_bytes', 'bytes', True),
    ({'MAX_IDENTIFIER': 3}, b'SELECT 1;\n', {}, 'identifier_bytes', 'bytes', True),
    ({'MAX_IDENTIFIER': 8}, b'"0123456789";\n', {}, 'identifier_bytes', 'bytes', True),
    ({'MAX_IDENTIFIER': 3}, COPY+b'\\.\n', {'copy_commands': (COPY,)}, 'identifier_bytes', 'bytes', False),
    ({'MAX_TAG': 2}, b'SELECT $long$x$long$;\n', {}, 'dollar_tag_prefix_bytes', 'bytes', True),
    ({'MAX_TOKEN': 8}, b'SELECT $$0123456789$$;\n', {}, 'dollar_body_bytes', 'bytes', True),
    ({'MAX_STATEMENTS': 1}, b'SELECT 1;SELECT 2;\n', {}, 'statements', 'statements', True),
    ({'MAX_RECEIPT': 8}, b'SELECT 1;\n', {}, 'receipt_bytes', 'bytes', False),
])
def test_actual_rejection_sites_emit_closed_counts(monkeypatch, caps, raw, kwargs, site, unit, position):
    for name, value in caps.items():
        monkeypatch.setattr(lexical, name, value)
    with pytest.raises(lexical.Unavailable) as caught:
        scan(raw, **kwargs)
    error = caught.value
    assert error.reason == 'limit' and str(error) == 'sql_lexical_unavailable'
    detail = error.limit
    assert set(detail) == {'site', 'ceiling', 'observed', 'unit', 'offset'}
    assert detail['site'] == site and detail['unit'] == unit
    assert detail['observed'] > detail['ceiling']
    assert (detail['offset'] is not None) is position
    assert lexical.validate_limit(detail, input_bytes=len(raw)) is detail
    assert 'SELECT' not in json.dumps(detail) and '0123456789' not in json.dumps(detail)


def test_copy_count_guard_remains_distinct_from_constructor_binding(monkeypatch):
    raw = COPY+b'\\.\n'
    scanner = lexical.Scanner(raw, (), b'postgres', (COPY,), time.monotonic()+5, lexical.PROFILE)
    # Constructor normally makes this guard redundant. Inject only after that
    # check to exercise the existing counter guard without changing production.
    monkeypatch.setattr(lexical, 'MAX_COPY', 0)
    with pytest.raises(lexical.Unavailable) as caught:
        scanner.run()
    assert caught.value.limit == {'site': 'copy_groups', 'ceiling': 0, 'observed': 1,
                                  'unit': 'groups', 'offset': len(COPY)}


def test_first_guard_precedence_is_preserved(monkeypatch):
    monkeypatch.setattr(lexical, 'MAX_RECORDS', 0)
    monkeypatch.setattr(lexical, 'MAX_INDEX', 0)
    with pytest.raises(lexical.Unavailable) as caught:
        scan(b'SELECT 1;\n')
    assert caught.value.limit['site'] == 'token_records'
    monkeypatch.setattr(lexical, 'MAX_TOKEN', 4)
    with pytest.raises(lexical.Unavailable) as caught:
        scan(b"'abcdef';\n")
    assert caught.value.limit['site'] == 'token_bytes'


@pytest.mark.parametrize('shift', range(-3, 4))
def test_long_copy_line_suffix_cannot_impersonate_standalone_end(shift):
    payload = b'x'*(1048576+shift)+b'\\.\n\\\\.\nSELECT 99; \\connect hidden -- TOC entry\n\n'
    raw = COPY+payload+b'\\.\n'+COPY+b'last\n\\.\nSELECT 1;\n'
    result = scan(raw, copy_commands=(COPY, COPY))
    payloads = [(a, z) for kind, a, z in lexical.RECORD.iter_unpack(result.leaves) if kind == lexical.COPY_DATA]
    first_end = len(COPY)+len(payload)
    second_start = first_end+3+len(COPY)
    assert payloads == [(len(COPY), first_end), (second_start, second_start+5)]
    assert json.loads(result.receipt)['statements'] == 3


@pytest.mark.parametrize('tail', [b'\n', b'\\.\n', b'\n\\.extra\n', b'\n \\.\n', b'\n\\\\.\n'])
def test_long_copy_row_still_requires_its_complete_standalone_terminator(tail):
    with pytest.raises(lexical.Unavailable) as caught:
        scan(COPY+b'x'*(2*1024**2)+tail, copy_commands=(COPY,))
    assert caught.value.reason == 'unfinished' and caught.value.limit is None


@pytest.mark.parametrize('bad', [b'\r', b'\0', b'\xff'])
def test_long_copy_row_does_not_bypass_global_encoding_profile(bad):
    with pytest.raises(lexical.Unavailable) as caught:
        scan(COPY+b'x'*(2*1024**2)+bad+b'\n\\.\n', copy_commands=(COPY,))
    assert caught.value.reason == 'encoding'


def test_long_copy_row_still_obeys_complete_input_bound(monkeypatch):
    raw = COPY+b'x'*(2*1024**2)+b'\n\\.\n'
    monkeypatch.setattr(lexical, 'MAX_INPUT', len(raw))
    assert json.loads(scan(raw, copy_commands=(COPY,)).receipt)['input']['bytes'] == len(raw)
    monkeypatch.setattr(lexical, 'MAX_INPUT', len(raw)-1)
    with pytest.raises(lexical.Unavailable) as caught:
        scan(raw, copy_commands=(COPY,))
    assert caught.value.reason == 'input'


def test_copy_scanner_additional_allocation_does_not_grow_with_row_size():
    peaks = []
    for size in (2*1024**2, 8*1024**2):
        # Fixture/input allocation is deliberately outside the measured scope.
        raw = COPY+b'x'*size+b'\n\\.\n'
        tracemalloc.start()
        try:
            result = scan(raw, copy_commands=(COPY,))
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
        assert json.loads(result.receipt)['copyGroups'] == 1
    assert max(peaks) < 512*1024
    assert peaks[1] <= peaks[0]+256*1024


def test_ordinary_progress_guard_reports_only_the_scanned_prefix():
    raw = b"'" + b'x'*(lexical.MAX_TOKEN+4) + b"';\n"
    with pytest.raises(lexical.Unavailable) as caught:
        scan(raw)
    assert caught.value.limit == {'site': 'token_bytes', 'ceiling': 1048576,
        'observed': 1048577, 'unit': 'bytes', 'offset': 1048577}


def limit_receipt():
    detail = {'site': 'token_records', 'ceiling': 262144, 'observed': 262145,
              'unit': 'records', 'offset': 3}
    return ledger.unavailable('limit', 'lexical', {
        'rowIndex': None, 'dumpId': None, 'descriptor': None, 'offset': None, 'limit': detail})


def test_removed_copy_line_diagnostic_is_rejected_by_current_contract():
    detail = {'site': 'copy_line_bytes', 'ceiling': 1048576, 'observed': 1052672,
              'unit': 'bytes', 'offset': 14677748}
    with pytest.raises(lexical.Unavailable):
        lexical.validate_limit(detail)
    value = limit_receipt()
    value['context']['limit'] = detail
    with pytest.raises(ledger.Unavailable):
        ledger.validate_receipt(value, fsql={'status': 'full_sql_verified', 'FsqlEqualsF2': True,
            'stream': {'bytes': 134217728, 'sha256': 'a'*64}})


@pytest.mark.parametrize('field,value', [
    ('site', 'SELECT secret'), ('site', []), ('ceiling', True), ('ceiling', 262143),
    ('observed', True), ('observed', 262144), ('observed', 262146), ('observed', float('inf')),
    ('unit', 'bytes'), ('unit', None), ('offset', True), ('offset', -1),
    ('offset', 134217729), ('offset', None), ('extra', 'raw SQL'),
])
def test_reader_rejects_forged_limit_detail(tmp_path, field, value):
    _, args = receipt_context(tmp_path)
    bad = limit_receipt()
    bad['context']['limit'][field] = value
    with pytest.raises(lexical.Unavailable):
        lexical.validate_limit(bad['context']['limit'])
    # The existing JSON encoder rejects nonfinite values before detail checks.
    with pytest.raises(ValueError):
        ledger.validate_receipt(bad, **args)


def test_limit_receipt_requires_correct_reason_stage_stream_and_schema(tmp_path):
    success, args = receipt_context(tmp_path)
    value = limit_receipt()
    assert ledger.validate_receipt(value, **args) is value
    changes = [value | {'reason': 'deadline'}, value | {'stage': 'emitter'},
               value | {'schema': 'rf1086-sql-ledger-v1'}, value | {'schema': 'rf1086-sql-ledger-v2'},
               value | {'schema': 'rf1086-sql-ledger-v3'},
               success | {'limit': value['context']['limit']}]
    for bad in changes:
        with pytest.raises(ledger.Unavailable):
            ledger.validate_receipt(bad, **args)
    for stream in ({'bytes': 2, 'sha256': 'a'*64}, {'bytes': True, 'sha256': 'a'*64}, {}):
        changed = args | {'fsql': args['fsql'] | {'stream': stream}}
        with pytest.raises(ledger.Unavailable):
            ledger.validate_receipt(value, **changed)
    with pytest.raises(ledger.Unavailable):
        ledger.validate_receipt(value, fsql={})
    malformed = deepcopy(value)
    del malformed['context']['limit']['observed']
    with pytest.raises(ledger.Unavailable):
        ledger.validate_receipt(malformed, **args)


def test_span_count_cannot_exceed_its_script_position():
    for site, ceiling in [('token_bytes', 1048576), ('identifier_bytes', 16384),
                          ('dollar_tag_prefix_bytes', 129), ('dollar_body_bytes', 1048576)]:
        with pytest.raises(lexical.Unavailable):
            lexical.validate_limit({'site': site, 'ceiling': ceiling, 'observed': ceiling+1,
                                    'unit': 'bytes', 'offset': ceiling})


def test_nonlimit_and_cancellation_never_gain_limit_metadata(monkeypatch):
    with pytest.raises(lexical.Unavailable) as caught:
        scan(b"SELECT 'unfinished\n")
    assert caught.value.reason == 'unfinished' and caught.value.limit is None
    cancelled = KeyboardInterrupt()
    def cancel(*args):
        raise cancelled
    monkeypatch.setattr(lexical.Scanner, 'check', cancel)
    with pytest.raises(KeyboardInterrupt) as caught:
        scan(b'SELECT 1;\n')
    assert caught.value is cancelled


def test_maximum_diagnostic_fits_without_summarizing_input():
    value = limit_receipt()
    value['context']['limit'] = {'site': 'dollar_tag_prefix_bytes', 'ceiling': 129,
        'observed': 130, 'unit': 'bytes', 'offset': 134217728}
    fsql = {'status': 'full_sql_verified', 'FsqlEqualsF2': True,
            'stream': {'bytes': 134217728, 'sha256': 'a'*64}}
    ledger.validate_receipt(value, fsql=fsql)
    assert len(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()) < 512 < ledger.MAX_RECEIPT


def test_maximum_finite_diagnostics_fit_existing_encrypted_envelope(control, key):
    _, metadata, f2, optional, _, _ = control
    optional = deepcopy(optional)
    optional['stream']['bytes'] = 134217728
    for site, (ceiling, maximum, unit, position, _) in lexical.limit_rules().items():
        proof = limit_receipt()
        proof['context']['limit'] = {'site': site, 'ceiling': ceiling, 'observed': maximum,
            'unit': unit, 'offset': None if position == 'none' else 134217728}
        ledger.validate_receipt(proof, fsql=optional)
        optional['ledger'] = proof
        fitted = replay.fit_optional(f2, optional, metadata)
        assert fitted['Fsql']['ledger'] == proof and replay.summary_fits(fitted, metadata)
        assert len(replay._encoded(fitted)) <= 65536
        aad = {'version': 1, **metadata['binding'], 'image': replay.IMAGE,
               'packageSha256': 'f'*64, 'publicKeySha256': 'f'*64}
        assert len(replay.seal(fitted, aad, key.public_key()).encode()) <= 98304


@pytest.mark.parametrize('site,ceiling,first_impossible,binding', [
    ('token_bytes', 1048576, 1048587, False),
    ('identifier_bytes', 16384, 1048578, False),
    ('identifier_bytes', 16384, 16387, True),
    ('dollar_body_bytes', 1048576, 1052673, False),
])
@pytest.mark.parametrize('huge', [False, True])
def test_first_guard_span_maxima_are_independent_of_total_input_size(site, ceiling, first_impossible, binding, huge):
    observed = 100*1024**2 if huge else first_impossible
    detail = {'site': site, 'ceiling': ceiling, 'observed': observed,
              'unit': 'bytes', 'offset': None if binding else observed}
    with pytest.raises(lexical.Unavailable):
        lexical.validate_limit(detail)
    value = limit_receipt()
    value['context']['limit'] = detail
    with pytest.raises(ledger.Unavailable):
        ledger.validate_receipt(value, fsql={'status': 'full_sql_verified', 'FsqlEqualsF2': True,
            'stream': {'bytes': 134217728, 'sha256': 'a'*64}})


def test_escaped_token_can_legitimately_overshoot_by_ten_bytes():
    raw = b"E'" + b'x'*(1048576-1) + b'\\U00000041' + b"';\n"
    with pytest.raises(lexical.Unavailable) as caught:
        scan(raw)
    assert caught.value.limit == {'site': 'token_bytes', 'ceiling': 1048576,
        'observed': 1048586, 'unit': 'bytes', 'offset': 1048587}


def test_quoted_script_identifier_keeps_its_existing_token_sized_progress_guard():
    raw = b'"' + b'x'*(1048576-1) + b'";\n'
    with pytest.raises(lexical.Unavailable) as caught:
        scan(raw)
    assert caught.value.limit == {'site': 'identifier_bytes', 'ceiling': 16384,
        'observed': 1048577, 'unit': 'bytes', 'offset': 1048577}


def test_binding_identifier_doubled_quote_can_overshoot_by_two(monkeypatch):
    monkeypatch.setattr(lexical, 'MAX_IDENTIFIER', 3)
    command = b'COPY "aa""b".x (y) FROM stdin;\n'
    with pytest.raises(lexical.Unavailable) as caught:
        scan(command+b'\\.\n', copy_commands=(command,))
    assert caught.value.limit == {'site': 'identifier_bytes', 'ceiling': 3,
        'observed': 5, 'unit': 'bytes', 'offset': None}
