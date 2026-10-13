"""Pure synthetic S0 vectors. No PostgreSQL, actual archives or runtime data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import rf1086_s0_protocol as protocol
import rf1086_sql_ledger as ledger
import rf1086_catalog_causal_capture as capture
from test_rf1086_sql_ledger import source_rows, wire_and_list, script_fixture, row
from test_rf1086_catalog_causal_capture import snapshot


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def utf8(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf8')


def io_record(stdout=49152, stderr=0):
    return dict(stdoutBytes=stdout, stderrBytes=stderr, stdoutEnd='eof', stderrEnd='eof', exitCode=0, reap='waited')


def _rows(extra_reconnect):
    rows = source_rows()
    if extra_reconnect:
        rows.insert(4, row(15, b'DATABASE PROPERTIES', b'postgres',
                          b"ALTER DATABASE postgres SET statement_timeout TO '0';\n"))
    return rows


def synthetic_inventory(*, extra_reconnect=False):
    """Inventory correlated with this module's independent synthetic TOC fixture."""
    _, listing = wire_and_list(_rows(extra_reconnect))
    return {'sha256': hashlib.sha256(listing).hexdigest(), 'total': 10+int(extra_reconnect),
            'passCounts': {'SPECIAL': 3, 'MAIN': 5+int(extra_reconnect), 'ACL': 1, 'POST_ACL': 1}, 'checkpointIds': [30, 31, 20]}


def valid_receipt_context(tmp_path, *, extra_reconnect=False):
    """Return (receipt, fsql, f2_input, metadata); synthetic_inventory() matches.

    Metadata includes all F2 INPUT_KEYS and phase keys used by validate_f2. The
    ledger is produced from synthetic bytes through its real one-pass seam.
    """
    rows = _rows(extra_reconnect); archive, listing = wire_and_list(rows); script = script_fixture(rows)
    catalog = {'serverVersion': 170006, 'schemas': [
        {'identity': ['schema', name], 'row': ['schema', name, 'owner', None],
         'defaults': '{}', 'default_grants': [], 'grants': [], 'initial': [], 'extensions': []}
        for name in ('graphql', 'graphql_public')],
        'functions': [], 'hooks': [], 'events': [], 'extensions': [['pg_net', '1.0', 'extensions', 'owner']]}
    initialized = {key: 170006 if key == 'serverVersion' else [] for key in catalog}
    fingerprint = {key: 'a'*64 for key in ('roles', 'catalog', 'auth', 'companyMemberships')}
    metadata = {'binding': {'runId': '1', 'runAttempt': '1', 'headSha': 'a'*40, 'mergeSha': 'a'*40},
        'image': 'sha256:'+'b'*64, 'source': '1'*64, 'sourceAuth': '2'*64,
        'sourceNetwork': 'synthetic', 'initSha256': '3'*64,
        'code': {key: 'f'*64 for key in protocol.CONFIG['codeFiles']},
        'files': {'archive.dump': {'bytes': len(archive), 'sha256': hashlib.sha256(archive).hexdigest()}},
        'before': fingerprint.copy(), 'failed': fingerprint, 'cleanupComplete': True,
        'identitySourcePostcheck': True, 'outerBusinessPostchecks': False, 'exportBudget': {},
        'phases': {'mismatch': {'catalog': catalog, 'catalogSha256': fingerprint['catalog']},
                   'target_initialized': {'catalog': initialized},
                   'source_pre_dump': {'catalog': catalog, 'sourceCommandSha256': 'd'*64, 'files': {}}}}
    f2_input = {key: deepcopy(item) for key, item in metadata.items() if key != 'phases'}
    fsql = {'status': 'full_sql_verified', 'stream': {'bytes': len(script), 'sha256': hashlib.sha256(script).hexdigest()},
        'tool': {'version': '17.6', 'sha256': '4'*64}, 'initializedEqualsOriginal': True, 'freshTarget': True,
        'fingerprint': fingerprint, 'catalog': catalog, 'FsqlEqualsF2': True, 'causalSnapshotEqualsF2': True,
        'recoveryAccepted': False, 'causalAttributionAccepted': False}
    result, D = ledger.observe_with_descriptor(tmp_path, script, listing, metadata, synthetic_inventory(extra_reconnect=extra_reconnect), fsql,
        time.monotonic()+21, read_private=lambda path, cap: archive)
    if result['status'] != 'verified_conditional' or D is None:
        raise RuntimeError('synthetic ledger fixture did not complete')
    fsql['ledger'] = result
    nonce = 'a'*32; exchanges = []
    # Different settings before FIXED demonstrate that anchors are baselines.
    anchor_settings = ['9s', '8s', '7s', '6s', 'UTF8', 'on', 'on', 'document', 'notice', 'on', 'public', 'space', 'heap']
    for seq, (point, offset) in enumerate(protocol.ordered_points(D, result)):
        kind, index = point; epoch = index if kind == 'anchor' else D['cuts'][index][0]
        db = 'template1' if epoch == 0 else 'postgres'; pid = 900+epoch
        settings = anchor_settings if kind == 'anchor' else protocol.CONFIG['session']['cutFirst11']+anchor_settings[-2:]
        session = [db, pid, 'supabase_admin', 'supabase_admin', *settings]
        witness = [db, str(100+epoch), pid, str(100+epoch), db, f'2026-10-13 01:02:0{epoch}+00',
                   'idle', None, None, None, protocol.probe(nonce, seq)[1][:-1].decode(),
                   'UTF8', 'UTF8', '103', 'B', 'postmaster', 'integer']
        projection = None if kind == 'anchor' else protocol.project(
            canonical(catalog), selected=result['selected'][index], reference_catalog=catalog)
        exchanges.append({'point': list(point), 'input': [offset, offset], 'session': session,
            'barrierPid': pid, 'witnesses': [deepcopy(witness) for _ in range(1 if kind == 'anchor' else 2)],
            'observer': io_record(), 'catalog': projection})
    probes = b''.join(part for seq in range(len(exchanges)) for part in protocol.probe(nonce, seq))
    receipt = {'schema': protocol.SCHEMA, 'status': 'matched',
        'bindings': {'input': digest(f2_input), 'configuration': digest(protocol.CONFIG),
                     'ledger': digest(result), 'descriptor': digest(D)},
        'target': {'id': '5'*64, 'previous': '6'*64, 'initialized': protocol.snapshot_commitment(initialized)},
        'tool': {'version': '17.6', 'sha256': '7'*64}, 'nonce': nonce,
        'references': {key: D[key] for key in ('epochs', 'cuts')}, 'exchanges': exchanges,
        'delivery': {'original': fsql['stream'].copy(), 'probes': {'bytes': len(probes), 'sha256': hashlib.sha256(probes).hexdigest()},
                     'frames': [len(exchanges)]*2, 'writer': io_record(1048576)},
        'final': {'fingerprint': fingerprint.copy(), 'enriched': protocol.snapshot_commitment(catalog)}}
    return receipt, fsql, f2_input, metadata


@pytest.fixture
def context(tmp_path):
    return valid_receipt_context(tmp_path)


def arguments(context):
    _, fsql, f2_input, metadata = context
    return dict(fsql=fsql, f2_input=f2_input, metadata=metadata, inventory=synthetic_inventory())


def descriptor(context):
    value, fsql, _, _ = context
    return {'schema': 's0-session-descriptor-v1', 'ledgerSha256': digest(fsql['ledger']),
            'database': 'postgres', **deepcopy(value['references'])}


def test_exact_accepted_configuration_and_templates():
    assert digest(protocol.CONFIG) == '175e7d6d253822d5f4a3d05369ddba54380f77e63bdd077c5839b8b0145e3f08'
    p, q = protocol.probe('a'*32, 5)
    assert len(p) == 953 and len(q) == 99 and q.endswith(b';\n')
    assert q == b"SELECT pg_catalog.concat('S0B/"+b'a'*32+b"/05/', pg_catalog.pg_backend_pid());\n"
    assert b'current_schemas' not in p and p.count(b'current_setting(') == 13
    assert protocol.writer_argv('b'*64) == ['docker', 'exec', '-i', 'b'*64, 'psql', '-U', 'supabase_admin', '-h', '/tmp', '-d', 'template1', '-XqAt', '-v', 'ON_ERROR_STOP=1']
    assert protocol.observer_argv('b'*64, 'postgres')[3:7] == ['-e', 'PGCLIENTENCODING=UTF8', '-e', 'PGCONNECT_TIMEOUT=2']
    assert 'command -v psql' in protocol.tool_argv('b'*64)[-1]
    w = protocol.witness_request('a'*32, 0, 'before', 123)
    assert b'WHERE a.pid = 123 ' in w and b'/00/before/' in w and w.endswith(b'ROLLBACK;\n')
    assert b"SET LOCAL TimeZone = 'UTC';" in w
    assert hashlib.sha256((Path(__file__).resolve().parents[3]/'scripts/rf1086_catalog_causal.sql').read_bytes()).hexdigest() == protocol.CONFIG['queries']['catalog']['sha256']


@pytest.mark.parametrize('nonce,seq', [('A'*32, 0), ('a'*31, 0), ('a'*32, True), ('a'*32, -1), ('a'*32, 6)])
def test_template_substitutions_are_closed(nonce, seq):
    with pytest.raises(protocol.Unavailable): protocol.probe(nonce, seq)


def test_positive_dependencies_and_failure_only_business_gate(context):
    value = context[0]
    assert context[3]['outerBusinessPostchecks'] is False
    assert protocol.validate_receipt(value, **arguments(context)) is value
    assert protocol.validate_receipt(value, **arguments(context), published=True, worker_outcome='completed', owned_cleanup=True) is value
    for kw in [dict(published=True, worker_outcome='deadline', owned_cleanup=True),
               dict(published=True, worker_outcome='completed', owned_cleanup=False), dict(published=1)]:
        with pytest.raises(protocol.Unavailable): protocol.validate_receipt(value, **arguments(context), **kw)
    for name in ('cleanupComplete', 'identitySourcePostcheck', 'outerBusinessPostchecks'):
        broken = deepcopy(context)
        broken[3][name] = not broken[3][name]
        with pytest.raises(protocol.Unavailable): protocol.validate_receipt(broken[0], **arguments(broken))


@pytest.mark.parametrize('stage,reasons', list(protocol.CONFIG['reasonStages'].items()))
def test_finite_negative_variants_before_all_dependencies(stage, reasons):
    for reason in reasons:
        point = ['cut', 0] if stage == 'transport' and reason in ('session', 'observer', 'partial_catalog') else None
        value = protocol.unavailable(reason, stage, point)
        assert protocol.validate_receipt(value, fsql=None, f2_input=None, metadata=None, published=True) is value
        for bad in (value | {'extra': 'raw'}, value | {'reason': 'raw exception'}, value | {'stage': 'unobserved'} if stage != 'unobserved' and reason != 'control_unavailable' else value | {'point': ['cut', True]}):
            with pytest.raises(protocol.Unavailable): protocol.validate_unavailable(bad)
    with pytest.raises(protocol.Unavailable): protocol.unavailable('partial_catalog', 'transport', ['anchor', 0])


@pytest.mark.parametrize('mutate', [
    lambda v: v.update(schema='s0-checkpoint-v0'),
    lambda v: v.update(extra='sql'),
    lambda v: v['bindings'].update(configuration='0'*64),
    lambda v: v['bindings'].update(input='0'*64),
    lambda v: v['bindings'].update(ledger='0'*64),
    lambda v: v['bindings'].update(descriptor='0'*64),
    lambda v: v['target'].update(id=v['target']['previous']),
    lambda v: v['target'].update(id='1'*64),
    lambda v: v['target'].update(initialized='0'*64),
    lambda v: v['tool'].update(version='17.11'),
    lambda v: v['final'].update(enriched='0'*64),
    lambda v: v['final']['fingerprint'].update(auth='0'*64),
    lambda v: v['delivery']['original'].update(bytes=1),
    lambda v: v['delivery']['probes'].update(sha256='0'*64),
    lambda v: v['delivery'].update(frames=[True, True]),
    lambda v: v['delivery']['writer'].update(stdoutBytes=1),
    lambda v: v['delivery']['writer'].update(stdoutEnd='closed'),
    lambda v: v['delivery']['writer'].update(exitCode=True),
    lambda v: v['delivery']['writer'].update(reap='unknown'),
    lambda v: v['exchanges'].pop(),
    lambda v: v['exchanges'][2]['input'].__setitem__(1, v['exchanges'][2]['input'][1]+1),
    lambda v: v['exchanges'][2].update(barrierPid=True),
    lambda v: v['exchanges'][2]['observer'].update(stderrBytes=1),
    lambda v: v['exchanges'][2]['observer'].update(stdoutBytes=49153),
    lambda v: v['exchanges'][2].update(catalog=None),
    lambda v: v['exchanges'][0].update(catalog={}),
    lambda v: v['exchanges'][2]['catalog']['extensions'].__setitem__(0, None),
    lambda v: v['exchanges'][2]['catalog']['extensions'][0].__setitem__(1, '0'*64),
    lambda v: v['exchanges'][2]['catalog'].update(usage=[]),
])
def test_forged_positive_receipts_reject(context, mutate):
    value = deepcopy(context[0]); mutate(value)
    with pytest.raises(protocol.Unavailable, match='^s0_protocol_invalid$'):
        protocol.validate_receipt(value, **arguments(context))


@pytest.mark.parametrize('slot,bad', [(1, True), (8, 'LATIN1'), (9, 'off'), (4, 0), (2, 'owner'), (0, 'other')])
def test_session_strict_types_and_profile_at_anchor(context, slot, bad):
    value = deepcopy(context[0]['exchanges'][0]['session']); value[slot] = bad
    with pytest.raises(protocol.Unavailable):
        protocol.parse_session(utf8(value), point=('anchor', 0), descriptor=descriptor(context))


def test_cut_expectations_are_baseline_or_exact_emitted_semantic_hash(context):
    D = descriptor(context); baseline = context[0]['exchanges'][1]['session']
    cut = deepcopy(context[0]['exchanges'][2]['session'])
    assert protocol.parse_session(utf8(cut), point=('cut', 0), descriptor=D, baseline=baseline) == cut
    cut[15] = ''
    with pytest.raises(protocol.Unavailable): protocol.parse_session(utf8(cut), point=('cut', 0), descriptor=D, baseline=baseline)
    D['cuts'][0][1] = [D['epochs'][1][1]+1, hashlib.sha256(b'').hexdigest()]
    assert protocol.parse_session(utf8(cut), point=('cut', 0), descriptor=D, baseline=baseline) == cut
    cut[4] = '9s'
    with pytest.raises(protocol.Unavailable): protocol.parse_session(utf8(cut), point=('cut', 0), descriptor=D, baseline=baseline)


@pytest.mark.parametrize('slot,bad', [(0, 'template1'), (1, '0101'), (2, True), (3, '102'),
    (5, '2026-02-30 01:02:03+00'), (5, '2026-10-13T01:02:03+00'), (6, 'active'),
    (7, '2026-10-13'), (8, '123'), (9, '4'), (10, 'SELECT 1;'), (11, 'LATIN1'),
    (12, 'LATIN1'), (13, '102'), (13, '1048577'), (13, '0103'), (13, 103), (14, 'kB'), (15, 'user'), (16, 'string')])
def test_witness_exact_query_idle_epoch_and_capacity(context, slot, bad):
    exchange = context[0]['exchanges'][2]; value = deepcopy(exchange['witnesses'][0]); value[slot] = bad
    with pytest.raises(protocol.Unavailable):
        protocol.parse_witness(utf8(value), nonce=context[0]['nonce'], sequence=2, session=exchange['session'])


def test_witness_capacity_endpoints_and_pid_reuse(context):
    for cap in ('103', '1048576'):
        w = deepcopy(context[0]['exchanges'][2]['witnesses'][0]); w[13] = cap
        protocol.parse_witness(utf8(w), nonce=context[0]['nonce'], sequence=2, session=context[0]['exchanges'][2]['session'])
    # PID reuse is legal only with a distinct backend-start; cuts remain same epoch.
    receipt = deepcopy(context[0])
    old = receipt['exchanges'][0]['session'][1]
    for exchange in receipt['exchanges'][1:]:
        exchange['session'][1] = exchange['barrierPid'] = old
        for w in exchange['witnesses']: w[2] = old
    protocol.validate_receipt(receipt, **arguments(context))
    for exchange in receipt['exchanges'][1:]:
        for w in exchange['witnesses']: w[5] = receipt['exchanges'][0]['witnesses'][0][5]
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(receipt, **arguments(context))


def test_session_raw_and_canonical_limits_no_surrogates_or_duplicate_json(context):
    session = deepcopy(context[0]['exchanges'][0]['session']); session[-1] = ''
    session[-1] = 'x'*(2000-len(canonical(session)))
    assert len(canonical(session)) == 2000
    protocol.parse_session(canonical(session), point=('anchor', 0), descriptor=descriptor(context))
    for raw in (canonical(session)+b' ', canonical(session).replace(b'xxxx', b'xxxxx', 1), b'{"a":1,"a":2}', b'[NaN]', b'["\\ud800"]'):
        with pytest.raises(protocol.Unavailable): protocol.parse_session(raw, point=('anchor', 0), descriptor=descriptor(context))
    session[-1] = '\u00e9'*400
    assert len(utf8(session)) < 2000 < len(canonical(session))
    with pytest.raises(protocol.Unavailable): protocol.parse_session(utf8(session), point=('anchor', 0), descriptor=descriptor(context))


def test_io_lower_bound_uses_utf8_not_ascii_and_not_projection_size(context):
    value = deepcopy(context[0]); writer = 0
    for seq, exchange in enumerate(value['exchanges']):
        exchange['session'][-2] = '\u00e9'
        pbytes = len(utf8(exchange['session']))
        writer += 40+2*pbytes+1+40+len(str(exchange['barrierPid']))+1
        role = ['anchor'] if exchange['point'][0] == 'anchor' else ['before', 'after']
        exchange['observer']['stdoutBytes'] = sum(len(f'S0O/{value["nonce"]}/{seq:02d}/{r}/')+2*len(utf8(w))+1 for r, w in zip(role, exchange['witnesses']))
    value['delivery']['writer']['stdoutBytes'] = writer
    protocol.validate_receipt(value, **arguments(context))
    value['delivery']['writer']['stdoutBytes'] -= 1
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(value, **arguments(context))


def test_projection_absence_unknowns_selected_binding_and_raw_acl(snapshot, context):
    catalog = deepcopy(snapshot); reference = context[1]['catalog']; selected = context[1]['ledger']['selected'][-1]
    # Owner commitments are checked independently of both supplied projection and ledger.
    for row in catalog['schemas']: row['row'][2] = 'owner'
    catalog['extensions'][0][2] = 'extensions'
    p = protocol.project(canonical(catalog), selected=selected, reference_catalog=reference)
    assert len(canonical(p)) <= 2048 and 'usage' not in p
    assert p['net'][0][2:4] == [True, 1]
    original = deepcopy(catalog); catalog['schemas'][0]['row'][3] = None
    changed = protocol.project(canonical(catalog), selected=selected, reference_catalog=reference)
    assert p['schemas'][0][1] != changed['schemas'][0][1]
    for mutate in (lambda c: c['schemas'].clear(), lambda c: c['schemas'].append(c['schemas'][0]),
                   lambda c: c['extensions'].append(['other', '1.0', 'public', 'owner']),
                   lambda c: c['schemas'][0]['row'].__setitem__(2, 'wrong'),
                   lambda c: c['functions'][0]['row'].__setitem__(7, '{search_path=other}')):
        bad = deepcopy(original); mutate(bad)
        with pytest.raises(protocol.Unavailable): protocol.project(canonical(bad), selected=selected, reference_catalog=reference)
    absent = deepcopy(original); absent['functions'].clear(); absent['hooks'].clear(); absent['events'].clear()
    assert protocol.project(canonical(absent), selected=selected, reference_catalog=reference)['net'] == [None, None]


def test_normalized_snapshot_is_never_deep_validated_twice(context, monkeypatch):
    normalized = deepcopy(context[1]['catalog'])
    normalized['hooks'] = [{'configurationEncoding': 'sha256-of-canonical-json', 'row': ['already-normalized', 'a'*64]}]
    def forbidden(*args): raise RuntimeError('second validation')
    monkeypatch.setattr(capture, '_validate_snapshot', forbidden)
    assert protocol.snapshot_commitment(normalized) == digest(['s0-partial-v1', 'snapshot', 0, normalized])


def test_maximum_is_sizing_only_and_bounds_real_receipt(context):
    maximum = protocol.maximum_receipt(**arguments(context), descriptor=descriptor(context))
    assert len(canonical(context[0])) < len(canonical(maximum)) <= 24576
    assert all(len(canonical(e['session'])) == 2000 for e in maximum['exchanges'])
    assert all(len(canonical(w)) == 288 for e in maximum['exchanges'] for w in e['witnesses'])
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(maximum, **arguments(context))
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(json.loads(canonical(maximum)), **arguments(context))


@pytest.mark.parametrize('mutate', [
    lambda d, s: d.update(ledgerSha256='0'*64),
    lambda d, s: d.update(database='template1'),
    lambda d, s: d['epochs'].pop(),
    lambda d, s: d['epochs'][0].__setitem__(0, True),
    lambda d, s: d['epochs'][1].__setitem__(1, d['epochs'][1][1]+1),
    lambda d, s: d['cuts'][0].__setitem__(0, 0),
    lambda d, s: d['cuts'][0].__setitem__(1, [d['epochs'][1][1], 'a'*64]),
    lambda d, s: d['cuts'][0].__setitem__(1, [s['selected'][0]['cut']+1, 'a'*64]),
    lambda d, s: d['cuts'][0].__setitem__(1, [d['epochs'][1][1]+1, 'a'*64]),  # Later null would forget SET.
    lambda d, s: d['epochs'].append(d['epochs'][1]),
])
def test_descriptor_relationships_reject(context, mutate):
    D = descriptor(context); current = context[1]['ledger']; mutate(D, current)
    with pytest.raises(protocol.Unavailable): protocol.validate_descriptor(D, current, context[1]['stream'])


def test_descriptor_assignments_cannot_move_back_or_change_same_offset(context):
    D = descriptor(context); value = context[1]['ledger']; end = D['epochs'][1][1]+1
    for cut in D['cuts']: cut[1] = [end, 'a'*64]
    protocol.validate_descriptor(D, value, context[1]['stream'])
    for ref in ([end-1, 'a'*64], [end, 'b'*64], None):
        changed = deepcopy(D); changed['cuts'][1][1] = ref
        with pytest.raises(protocol.Unavailable): protocol.validate_descriptor(changed, value, context[1]['stream'])
    D['cuts'][1][1] = D['cuts'][2][1] = [value['selected'][0]['cut']+1, 'b'*64]
    protocol.validate_descriptor(D, value, context[1]['stream'])


@pytest.mark.parametrize('inventory', [None, {}, {'sha256': '0'*64}])
def test_positive_requires_actual_inventory(context, inventory):
    args = arguments(context) | {'inventory': inventory}
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(context[0], **args)
    with pytest.raises(protocol.Unavailable): protocol.maximum_receipt(**args, descriptor=descriptor(context))


@pytest.mark.parametrize('field', ['sha256', 'passCounts', 'checkpointIds'])
def test_stale_inventory_still_rejects_even_with_valid_s0_commitments(context, field):
    inventory = synthetic_inventory()
    inventory[field] = {'sha256': '0'*64, 'passCounts': {'SPECIAL': 3, 'MAIN': 4, 'ACL': 2, 'POST_ACL': 1}, 'checkpointIds': [31, 30, 20]}[field]
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(context[0], **(arguments(context) | {'inventory': inventory}))


@pytest.mark.parametrize('mutate', [
    lambda c: c[1].update(status='unavailable'),
    lambda c: c[1].update(FsqlEqualsF2=False),
    lambda c: c[1].update(causalSnapshotEqualsF2=False),
    lambda c: c[1]['ledger'].update(schema='rf1086-sql-ledger-v4'),
    lambda c: c[1]['ledger']['selected'][0].update(semanticSha256='0'*64),
    lambda c: c[3]['code'].pop('rf1086_catalog_difference.py'),
    lambda c: c[3]['code'].update(unknown='a'*64),
    lambda c: c[3]['code'].update(rf1086_s0_protocol='a'*64),
])
def test_dependency_and_code_binding_rejects(context, mutate):
    changed = deepcopy(context); mutate(changed)
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(changed[0], **arguments(changed))


def test_projection_hashes_hooks_once_and_keeps_raw_grant_commitments(context, monkeypatch):
    raw = deepcopy(context[1]['catalog'])
    identity = capture.HOOKS[0]
    hook = {'identity': identity, 'row': identity+['owner', None, True, '{search_path=public}'],
            'body_sha256': 'd'*64, 'definition_sha256': 'e'*64}
    raw['hooks'] = [hook]
    raw['events'] = [{'name': capture.EVENTS[0], 'event': 'ddl_command_end', 'enabled': 'O',
                      'tags': None, 'owner': 'owner', 'function': identity}]
    raw['schemas'][0]['grants'] = [['owner', False, 'reader', 'USAGE', False]]*2
    selected = context[1]['ledger']['selected'][-1]
    expected_hook = deepcopy(hook)
    expected_hook['row'][-1] = hashlib.sha256(canonical('{search_path=public}')).hexdigest()
    expected_hook['configurationEncoding'] = 'sha256-of-canonical-json'
    validate = capture._validate_snapshot; calls = []
    def once(value, retained): calls.append(retained); return validate(value, retained)
    monkeypatch.setattr(capture, '_validate_snapshot', once)
    value = protocol.project(canonical(raw), selected=selected, reference_catalog=context[1]['catalog'])
    assert calls == [None]
    assert value['hooks'][0] == digest(['s0-partial-v1', 'hook', 0, expected_hook])
    assert value['events'][0][:2] == ['O', 0]
    assert value['schemas'][0][2] == digest(['s0-partial-v1', 'schema-grants', 0, raw['schemas'][0]['grants']])
    raw['schemas'][0]['grants'].pop()
    changed = protocol.project(canonical(raw), selected=selected, reference_catalog=context[1]['catalog'])
    assert changed['schemas'][0][2] != value['schemas'][0][2]
    raw['hooks'] = []
    with pytest.raises(protocol.Unavailable): protocol.project(canonical(raw), selected=selected, reference_catalog=context[1]['catalog'])


def test_witness_raw_cap_and_no_query_lf_or_trailing_whitespace(context):
    e = context[0]['exchanges'][2]; w = deepcopy(e['witnesses'][0])
    args = dict(nonce=context[0]['nonce'], sequence=2, session=e['session'])
    payload = utf8(w)
    assert protocol.parse_witness(payload+b' '*(2000-len(payload)), **args) == w
    with pytest.raises(protocol.Unavailable): protocol.parse_witness(payload+b' '*(2001-len(payload)), **args)
    for suffix in ('\n', ' '):
        wrong = deepcopy(w); wrong[10] += suffix
        with pytest.raises(protocol.Unavailable): protocol.parse_witness(utf8(wrong), **args)
    for slot, bad in ((1, '4294967296'), (5, '2026-10-13 01:02:03.1234567+00'), (5, '2026-10-13 01:02:03+01')):
        wrong = deepcopy(w); wrong[slot] = bad
        with pytest.raises(protocol.Unavailable): protocol.parse_witness(utf8(wrong), **args)


def test_cancellation_not_converted_to_negative_protocol_result(context, monkeypatch):
    cancellation = KeyboardInterrupt('synthetic')
    def cancelled(*a, **kw): raise cancellation
    monkeypatch.setattr(ledger, 'validate_receipt', cancelled)
    with pytest.raises(KeyboardInterrupt) as caught: protocol.validate_receipt(context[0], **arguments(context))
    assert caught.value is cancellation


def test_six_exchange_widest_vectors_fit_conservative_preflight(tmp_path):
    context = valid_receipt_context(tmp_path, extra_reconnect=True)
    args = arguments(context) | {'inventory': synthetic_inventory(extra_reconnect=True)}
    receipt = deepcopy(context[0]); D = descriptor(context)
    maximum = protocol.maximum_receipt(**args, descriptor=D)
    assert len(receipt['exchanges']) == 6 and len(D['epochs']) == 3
    protocol.validate_receipt(receipt, **args)
    # Build widest legal vectors independently. Every baseline/cut uses the same
    # textual last two settings within its epoch; all opaque commitments are64hex.
    for seq, exchange in enumerate(receipt['exchanges']):
        session = exchange['session']
        session[1] = exchange['barrierPid'] = 2147483647
        session[4:] = protocol.CONFIG['session']['cutFirst11']+['', '']
        session[-1] = 'x'*(2000-len(canonical(session)))
        for w in exchange['witnesses']:
            w[1] = w[3] = '4294967295'; w[2] = 2147483647
            epoch = exchange['point'][1] if exchange['point'][0] == 'anchor' else D['cuts'][exchange['point'][1]][0]
            w[5] = f'9999-12-31 23:59:5{epoch}.999999+00'; w[13] = '1048576'
        if exchange['catalog'] is not None:
            maximum_projection = deepcopy(maximum['exchanges'][seq]['catalog'])
            selected = args['fsql']['ledger']['selected'][exchange['point'][1]]
            kind = selected['kind']
            if kind == 'pg_net_extension': maximum_projection['extensions'][0][1] = selected['semanticSha256']
            else: maximum_projection['schemas'][0 if kind == 'graphql_schema' else 1][0] = selected['semanticSha256']
            exchange['catalog'] = maximum_projection
    protocol.validate_receipt(receipt, **args)
    assert len(canonical(receipt)) <= len(canonical(maximum)) <= 24576
    # Whole-envelope fit remains a caller check against real F2/Fsql sizes.
    assert all(len(canonical(e['session'])) == 2000 for e in receipt['exchanges'])
    receipt['delivery']['writer']['stderrBytes'] = 65536
    protocol.validate_receipt(receipt, **args)
    receipt['delivery']['writer']['stderrBytes'] += 1
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(receipt, **args)


@pytest.mark.parametrize('field,value', [('net', ['a'*64, 'b'*64, True, True, 'c'*64]),
    ('net', ['a'*64, 'b'*64, 1, 0, 'c'*64]), ('events', ['O', True, 'c'*64]),
    ('extensions', ['17', 'a'*64, 'b'*64]), ('extensions', ['1.2', 'a'*63, 'b'*64])])
def test_projection_slot_types_do_not_accept_boolean_integers(context, field, value):
    receipt = deepcopy(context[0]); receipt['exchanges'][2]['catalog'][field][0] = value
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(receipt, **arguments(context))


def test_descriptor_missing_on_incomplete_ledger_cannot_validate(context):
    for bad in (None, {}, descriptor(context) | {'schema': 'old'}):
        with pytest.raises(protocol.Unavailable): protocol.validate_descriptor(bad, context[1]['ledger'], context[1]['stream'])
    old = deepcopy(context[1]['ledger']); old['schema'] = 'rf1086-sql-ledger-v4'
    with pytest.raises(protocol.Unavailable): protocol.validate_descriptor(descriptor(context), old, context[1]['stream'])


def test_v2_profile_binds_all_sixteen_files_and_rejects_old_receipt(context):
    assert protocol.CONFIG['schema'] == 's0-config-v2'
    assert protocol.SCHEMA == 's0-checkpoint-v2'
    assert len(protocol.CONFIG['codeFiles']) == 16
    old = deepcopy(context[0]); old['schema'] = 's0-checkpoint-v1'
    with pytest.raises(protocol.Unavailable):
        protocol.validate_receipt(old, **arguments(context))


def test_v2_profile_is_single_family():
    assert protocol.CONFIG['completedControl'] == 'actual-image-control-v3'
    assert protocol.CONFIG['replay']['tag'] == 'owned_identity_actual_replay_v3 '
    assert protocol.CONFIG['replay']['aadVersion'] == 3


@pytest.mark.parametrize('name', ['rf1086_causal_protocol.py', 'rf1086_causal_control.py', 'rf1086_causal_catalog.py'])
def test_every_new_bound_file_is_required_for_positive_and_maximum(context, name):
    changed = deepcopy(context)
    changed[2]['code'].pop(name); changed[3]['code'].pop(name)
    for call in (lambda: protocol.validate_receipt(changed[0], **arguments(changed)),
                 lambda: protocol.maximum_receipt(**arguments(changed), descriptor=descriptor(changed))):
        with pytest.raises(protocol.Unavailable): call()


def test_optional_reference_seam_validates_once_preserves_normalized_hooks_and_detaches(context, monkeypatch):
    raw = deepcopy(context[1]['catalog']); identity = capture.HOOKS[0]
    raw['hooks'] = [{'identity': identity, 'row': identity+['owner', None, True, '{search_path=public}'],
                     'body_sha256': 'd'*64, 'definition_sha256': 'e'*64}]
    encoded = canonical(raw); selected = context[1]['ledger']['selected'][-1]
    validator = capture._validate_snapshot; calls = []
    def counted(value, retained): calls.append(retained); return validator(value, retained)
    monkeypatch.setattr(capture, '_validate_snapshot', counted)
    projection, normalized = protocol.project_with_reference(encoded, selected=selected, reference_catalog=context[1]['catalog'])
    assert calls == [None]
    assert normalized['hooks'][0]['configurationEncoding'] == 'sha256-of-canonical-json'
    assert normalized['hooks'][0]['row'][-1] == hashlib.sha256(canonical('{search_path=public}')).hexdigest()
    assert protocol.project_normalized(normalized, selected=selected, reference_catalog=context[1]['catalog']) == projection
    assert calls == [None] and canonical(raw) == encoded
    normalized['hooks'][0]['row'][-1] = 'f'*64
    assert projection['hooks'][0] != protocol.project_normalized(normalized,
        selected=selected, reference_catalog=context[1]['catalog'])['hooks'][0]
    assert projection['snapshot'] != protocol.snapshot_commitment(normalized)
