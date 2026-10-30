"""Independent synthetic branch references; no actual catalog or PostgreSQL."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import rf1086_causal_protocol as protocol
import rf1086_s0_protocol as s0
import rf1086_sql_ledger as ledger
import rf1086_catalog_causal_capture as capture
from test_rf1086_s0_protocol import canonical, digest, utf8, io_record
from test_rf1086_sql_ledger import source_rows, row, wire_and_list, script_fixture


OWNER = 'supabase_admin'


def catalogs():
    """Complete fixed synthetic profile with explicit default and source ACL order."""
    grants = [[OWNER, False, OWNER, right, False] for right in ('CREATE', 'USAGE')]
    source = {'serverVersion': 170006, 'schemas': [], 'functions': [], 'hooks': [], 'events': [],
              'extensions': [['pg_net', '0.20.3', 'extensions', OWNER]]}
    for name in ('graphql', 'graphql_public'):
        source['schemas'].append({'identity': ['schema', name],
            'row': ['schema', name, OWNER, '{supabase_admin=UC/supabase_admin,=U/supabase_admin,'
                    'reader=U/supabase_admin,writer=U*/supabase_admin,PUBLIC=U/supabase_admin}'],
            'defaults': '{supabase_admin=UC/supabase_admin}', 'default_grants': deepcopy(grants),
            'grants': sorted(grants+[[OWNER, True, None, 'USAGE', False],
                [OWNER, False, 'reader', 'USAGE', False], [OWNER, False, 'writer', 'USAGE', True],
                [OWNER, False, 'PUBLIC', 'USAGE', False]], key=canonical),
            'initial': [['e', '{source-initial}', []]], 'extensions': []})
    for i, identity in enumerate(capture.NET_IDENTITIES):
        source['functions'].append({'identity': identity.copy(),
            'row': identity+[OWNER, None, True, '{search_path=net}'],
            'definition_sha256': str(i+3)*64, 'body_sha256': str(i+5)*64,
            'attributes': ['plpgsql', 'bigint', 'f', 'v', False, 'u', False, False],
            'definition_attributes': {'default_count': (3, 4)[i], 'defaults': {'bytes': 41, 'sha256': 'e'*64},
                'cost': '100', 'rows': '0', 'support': None, 'binary': None, 'fixed_shape': True},
            'types': [['pg_catalog', name] for name in capture.NET_TYPES[i]],
            'extensions': [['pg_net', '0.20.3', OWNER]]})
    source = capture._validate_snapshot(source, None)
    failed = deepcopy(source)
    for schema in failed['schemas']:
        schema['row'][3] = None; schema['grants'] = deepcopy(grants)
        schema['initial'] = []  # Unrelated source differences must stay failed-valued.
    for i, function in enumerate(failed['functions']):
        function['row'][6:] = [False, None]; function['definition_sha256'] = str(i+7)*64
    return source, failed


def control_context(tmp_path, *, extra_reconnect=False):
    """Return (matched S0, validator arguments, descriptor, normalized cut cache)."""
    rows = source_rows()
    for item in rows:
        if item['owner']: item['owner'] = OWNER.encode()
    # Additional ordinary MAIN emissions make the conservative pre-ACL bound
    # useful without changing selected order (net, graphql_public, graphql).
    for i in range(4):
        rows.insert(-2, row(70+i, b'SEQUENCE SET', f'fixture_extra_{i}'.encode(),
            f"SELECT pg_catalog.setval('public.fixture_extra_{i}', 1, true);\n".encode(), namespace=b'public'))
    if extra_reconnect:
        rows.insert(4, row(15, b'DATABASE PROPERTIES', b'postgres',
                          b"ALTER DATABASE postgres SET statement_timeout TO '0';\n"))
    archive, listing = wire_and_list(rows); script = script_fixture(rows)
    inventory = {'sha256': hashlib.sha256(listing).hexdigest(), 'total': len(rows),
        'passCounts': {'SPECIAL': 3, 'MAIN': len(rows)-5, 'ACL': 1, 'POST_ACL': 1}, 'checkpointIds': [30, 31, 20]}
    source, failed = catalogs(); initialized = {k: 170006 if k == 'serverVersion' else [] for k in source}
    fingerprint = {key: 'a'*64 for key in ('roles', 'catalog', 'auth', 'companyMemberships')}
    metadata = {'binding': {'runId': '1', 'runAttempt': '1', 'headSha': 'a'*40, 'mergeSha': 'a'*40},
        'image': 'sha256:'+'b'*64, 'source': '1'*64, 'sourceAuth': '2'*64,
        'sourceNetwork': 'synthetic', 'initSha256': '3'*64,
        'code': {key: 'f'*64 for key in s0.CONFIG['codeFiles']},
        'files': {'archive.dump': {'bytes': len(archive), 'sha256': hashlib.sha256(archive).hexdigest()}},
        'before': fingerprint | {'catalog': 'b'*64}, 'failed': fingerprint,
        'cleanupComplete': True, 'identitySourcePostcheck': True, 'outerBusinessPostchecks': False, 'exportBudget': {},
        'phases': {'source_pre_dump': {'catalog': source, 'sourceCommandSha256': 'd'*64, 'files': {}},
            'mismatch': {'catalog': failed, 'catalogSha256': fingerprint['catalog']},
            'target_initialized': {'catalog': initialized}}}
    f2_input = {k: deepcopy(v) for k, v in metadata.items() if k != 'phases'}
    fsql = {'status': 'full_sql_verified', 'stream': {'bytes': len(script), 'sha256': hashlib.sha256(script).hexdigest()},
        'tool': {'version': '17.6', 'sha256': '4'*64}, 'initializedEqualsOriginal': True, 'freshTarget': True,
        'fingerprint': fingerprint, 'catalog': failed, 'FsqlEqualsF2': True, 'causalSnapshotEqualsF2': True,
        'recoveryAccepted': False, 'causalAttributionAccepted': False}
    value, D = ledger.observe_with_descriptor(tmp_path, script, listing, metadata, inventory, fsql,
        time.monotonic()+21, read_private=lambda path, cap: archive)
    if value['status'] != 'verified_conditional' or D is None:
        raise RuntimeError('independent synthetic ledger failed')
    fsql['ledger'] = value
    cache = {i: deepcopy(failed) for i in range(3)}
    for index, selected in enumerate(value['selected']):
        if selected['kind'] == 'pg_net_extension':
            for function in cache[index]['functions']:
                function['row'][5] = '{prefix=U/supabase_admin}'
    nonce = 'a'*32; exchanges = []
    anchor = ['9s', '8s', '7s', '6s', 'UTF8', 'on', 'on', 'document', 'notice', 'on', 'public', 'space', 'heap']
    for seq, (point, offset) in enumerate(s0.ordered_points(D, value)):
        kind, index = point; epoch = index if kind == 'anchor' else D['cuts'][index][0]
        db = 'template1' if epoch == 0 else 'postgres'; pid = 900+epoch
        session = [db, pid, OWNER, OWNER, *(anchor if kind == 'anchor' else s0.CONFIG['session']['cutFirst11']+anchor[-2:])]
        witness = [db, str(100+epoch), pid, str(100+epoch), db, f'2026-10-13 01:02:0{epoch}+00',
            'idle', None, None, None, s0.probe(nonce, seq)[1][:-1].decode(),
            'UTF8', 'UTF8', '103', 'B', 'postmaster', 'integer']
        projection = None if kind == 'anchor' else s0.project_normalized(cache[index],
            selected=value['selected'][index], reference_catalog=failed)
        exchanges.append({'point': list(point), 'input': [offset, offset], 'session': session, 'barrierPid': pid,
            'witnesses': [deepcopy(witness) for _ in range(1 if kind == 'anchor' else 2)],
            'observer': io_record(), 'catalog': projection})
    probes = b''.join(part for seq in range(len(exchanges)) for part in s0.probe(nonce, seq))
    receipt = {'schema': s0.SCHEMA, 'status': 'matched',
        'bindings': {'input': digest(f2_input), 'configuration': digest(s0.CONFIG),
            'ledger': digest(value), 'descriptor': digest(D)},
        'target': {'id': '5'*64, 'previous': '6'*64, 'initialized': s0.snapshot_commitment(initialized)},
        'tool': {'version': '17.6', 'sha256': '7'*64}, 'nonce': nonce,
        'references': {k: deepcopy(D[k]) for k in ('epochs', 'cuts')}, 'exchanges': exchanges,
        'delivery': {'original': fsql['stream'].copy(), 'probes': {'bytes': len(probes), 'sha256': hashlib.sha256(probes).hexdigest()},
            'frames': [len(exchanges)]*2, 'writer': io_record(1048576)},
        'final': {'fingerprint': fingerprint.copy(), 'enriched': s0.snapshot_commitment(failed)}}
    args = dict(fsql=fsql, f2_input=f2_input, metadata=metadata, inventory=inventory)
    s0.validate_receipt(receipt, **args)
    return receipt, args, D, cache


def valid_branch_context(tmp_path, kind='Is', *, extra_reconnect=False):
    """Return (receipt, validator kwargs, policy, descriptor, normalized cut cache)."""
    control, args, D, cache = control_context(tmp_path, extra_reconnect=extra_reconnect)
    source = args['metadata']['phases']['source_pre_dump']['catalog']; failed = args['fsql']['catalog']
    raw = {'expected': {'bytes': 12345, 'sha256': 'e'*64}, 'outside': 'f'*64}
    policy = protocol.prepare_policy(kind, source_catalog=source, failed_catalog=failed,
        ledger=args['fsql']['ledger'], raw_binding=raw, deadline=time.monotonic()+5)
    nonce = ('b' if kind == 'Is' else 'c')*32
    controls = {tuple(v['point']): v for v in control['exchanges']}
    exchanges = []; after = False
    for seq, (point, offset) in enumerate(protocol.ordered_points(policy, D, args['fsql']['ledger'])):
        tag, index = point; mapped = ('cut', index) if tag == 'post' else point
        epoch = index if tag == 'anchor' else D['cuts'][index][0]; pid = 1000+epoch
        observed = controls[mapped]
        if tag == 'post': after = True
        catalog = None
        if tag != 'anchor':
            fresh = protocol.expected_catalog(kind, cache[index], source) if after else deepcopy(cache[index])
            catalog = protocol.factor_catalog(policy, fresh, cache[index], after=after,
                                              selected=args['fsql']['ledger']['selected'][index])
        exchanges.append({'point': list(point), 'input': [offset, offset], 'pid': pid,
            'witnesses': [[str(200+epoch), f'2026-10-13 01:03:0{epoch}+00', '103']
                          for _ in range(1 if tag == 'anchor' else 2)],
            'observer': io_record(), 'catalog': catalog})
    probes = b''.join(part for seq in range(len(exchanges)) for part in protocol.probe(nonce, seq))
    mutation = {'bytes': len(policy.sql), 'sha256': hashlib.sha256(policy.sql).hexdigest()}
    receipt = {'schema': protocol.SCHEMA, 'kind': kind, 'status': 'prediction_matched',
        'bindings': {'s0': digest(control), 'configuration': digest(protocol.CONFIG),
            'expectation': digest(protocol.expectation(policy, s0_receipt=control, f2_input=args['f2_input']))},
        'target': {'id': ('8' if kind == 'Is' else '9')*64, 'previous': '5'*64,
                   'initialized': control['target']['initialized']},
        'tool': {'version': '17.6', 'sha256': '7'*64}, 'nonce': nonce,
        'mutation': {'point': list(policy.point), 'sql': mutation.copy()},
        'admission': protocol.admit_mutation(policy, cache[policy.point[1]], cache[policy.point[1]]),
        'exchanges': exchanges, 'delivery': {'original': args['fsql']['stream'].copy(),
            'probes': {'bytes': len(probes), 'sha256': hashlib.sha256(probes).hexdigest()},
            'mutation': mutation, 'frames': [len(exchanges)]*2, 'writer': io_record(1048576)},
        'final': {'fingerprint': args['metadata']['failed'] | {'catalog': raw['expected']['sha256']},
            'enriched': s0.snapshot_commitment(policy.expected_final),
            'raw': dict(raw, actual=raw['expected'].copy())},
        'cleanup': {'children': 'reaped', 'resources': 'removed'}}
    return receipt, dict(args, s0_receipt=control), policy, D, cache


@pytest.fixture(params=['Is', 'In'])
def context(tmp_path, request):
    return valid_branch_context(tmp_path, request.param)


def test_exact_compiled_configs_and_wire():
    assert len(canonical(protocol.CONFIG)) == 14692
    assert digest(protocol.CONFIG) == '2cd8ab3740f50e6c878651248062c9ca611724d190803cce54b6a1d2d4c5a41b'
    assert digest(s0.CONFIG) == '175e7d6d253822d5f4a3d05369ddba54380f77e63bdd077c5839b8b0145e3f08'
    for name in ('P', 'Q', 'W'):
        raw = protocol.CONFIG['queries'][name].encode('ascii')
        assert {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} == protocol.CONFIG['queryPins'][name]
    p, q = protocol.probe('a'*32, 6)
    assert len(p) == 953 and len(q) == 99 and q.endswith(b';\n') and b'C1B/' in q
    assert b'current_schemas' not in p and b'current_setting(' in p
    assert protocol.CONFIG['In']['sqlBytes'] == 607
    assert hashlib.sha256(protocol.CONFIG['In']['sql'].encode()).hexdigest() == protocol.CONFIG['In']['sqlSha256']


@pytest.mark.parametrize('extra', [False, True])
@pytest.mark.parametrize('kind', ['Is', 'In'])
def test_positive_complete_reconstructed_receipts(tmp_path, extra, kind):
    value, args, policy, D, cache = valid_branch_context(tmp_path, kind, extra_reconnect=extra)
    assert protocol.validate_receipt(value, **args) is value
    assert protocol.validate_receipt(value, **args, published=True, worker_outcome='completed', owned_cleanup=True) is value
    assert len(value['exchanges']) == 6+int(extra)
    assert value['mutation']['point'] == list(policy.point)
    post = next(v for v in value['exchanges'] if v['point'][0] == 'post')
    assert post['input'] == next(v for v in value['exchanges'] if v['point'] == ['cut', policy.point[1]])['input']
    maximum = protocol.maximum_receipt(kind, **{k: v for k, v in args.items() if k != 's0_receipt'}, descriptor=D)
    assert len(canonical(value)) <= len(canonical(maximum)) <= 10240
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(maximum, **args)
    if kind == 'Is':
        assert policy.selected['kind'] == 'graphql_schema' and policy.point[1] == 2
        assert policy.sql.count(b'GRANT USAGE') == 8
        assert b'TO PUBLIC;' in policy.sql and b'TO "PUBLIC";' in policy.sql and b'WITH GRANT OPTION' in policy.sql
    else:
        assert policy.point[1] == 0  # Never assume the schema index is the first cut.
        assert cache[0]['functions'][0]['row'][5] != policy.source_catalog['functions'][0]['row'][5]


def test_mutation_targets_and_catalogs_do_not_alias(context):
    value, args, policy, D, cache = context
    before = deepcopy((args, cache)); changed = policy.expected_final
    changed['schemas'][0]['row'][2] = 'raw-canary'
    source = policy.source_catalog; source['functions'][0]['row'][4] = 'raw-canary'
    assert (args, cache) == before and 'raw-canary' not in repr(policy)
    assert 'BEGIN' not in repr(policy) and 'supabase_admin' not in repr(policy)
    assert protocol.validate_receipt(value, **args) is value


def policy_args(context):
    _, args, policy, _, _ = context
    return dict(source_catalog=deepcopy(args['metadata']['phases']['source_pre_dump']['catalog']),
        failed_catalog=deepcopy(args['fsql']['catalog']), ledger=deepcopy(args['fsql']['ledger']),
        raw_binding=policy.raw_binding, deadline=time.monotonic()+5)


@pytest.mark.parametrize('change', ['owner', 'acl_owner', 'grantor', 'duplicate', 'extra', 'missing',
    'public_option', 'unsafe', 'nonascii', 'length', 'rights', 'default', 'expanded', 'false_public'])
def test_source_schema_profile_is_closed_before_rendering(tmp_path, change):
    ctx = valid_branch_context(tmp_path); args = policy_args(ctx); schema = args['source_catalog']['schemas'][0]
    if change == 'owner': schema['row'][2] = 'other'
    elif change == 'acl_owner': schema['row'][3] = schema['row'][3].replace('supabase_admin=UC', 'supabase_admin=U')
    elif change == 'grantor': schema['row'][3] = schema['row'][3].replace('reader=U/supabase_admin', 'reader=U/other')
    elif change == 'duplicate': schema['row'][3] = schema['row'][3].replace('PUBLIC=U/', 'reader=U/')
    elif change == 'extra': schema['row'][3] = schema['row'][3][:-1]+',extra=U/supabase_admin}'
    elif change == 'missing': schema['row'][3] = schema['row'][3].replace(',reader=U/supabase_admin', '')
    elif change == 'public_option': schema['row'][3] = schema['row'][3].replace(',=U/', ',=U*/')
    elif change == 'unsafe': schema['row'][3] = schema['row'][3].replace('reader=', 'a";SELECT 1;--=')
    elif change == 'nonascii': schema['row'][3] = schema['row'][3].replace('reader=', 'røle=')
    elif change == 'length': schema['row'][3] = schema['row'][3].replace('reader=', 'x'*64+'=')
    elif change == 'rights': schema['row'][3] = schema['row'][3].replace('reader=U/', 'reader=UC/')
    elif change == 'default': schema['default_grants'] = []
    elif change == 'expanded': schema['grants'].pop()
    elif change == 'false_public':
        next(v for v in schema['grants'] if v[1])[:3] = [OWNER, False, 'PUBLIC']
    with pytest.raises(protocol.Unavailable) as error:
        protocol.prepare_policy('Is', **args)
    assert str(error.value) in ('source_profile', 'protocol_invalid')
    assert 'SELECT' not in str(error.value)


@pytest.mark.parametrize('change', ['null', 'default', 'nondefault', 'acl', 'grant', 'snapshot', 'owner'])
def test_is_admission_requires_exact_entire_control_and_default_prestate(tmp_path, change):
    _, _, policy, _, cache = valid_branch_context(tmp_path)
    control = deepcopy(cache[policy.point[1]])
    if change == 'null': control['schemas'][0]['row'][3] = '{}'
    elif change == 'default': control['schemas'][0]['defaults'] = '{}'
    elif change == 'nondefault': control['schemas'][0]['default_grants'].pop()
    elif change == 'acl': control['schemas'][0]['grants'].append([OWNER, True, None, 'USAGE', False])
    elif change == 'grant': control['schemas'][0]['grants'][0][4] = True
    elif change == 'owner': control['schemas'][0]['row'][2] = 'other'
    fresh = deepcopy(control)
    if change == 'snapshot': fresh['schemas'][0]['initial'] = [['e', 'raw-canary', []]]
    with pytest.raises(protocol.Unavailable): protocol.admit_mutation(policy, fresh, control)


@pytest.mark.parametrize('change', ['owner', 'body', 'identity', 'types', 'attrs', 'cost', 'rows',
    'defaults', 'default_count', 'language', 'support', 'binary', 'membership', 'extra',
    'config', 'secdef', 'extension', 'function_absent', 'extension_absent'])
def test_in_source_definition_every_non_acl_field_is_checked_at_cut(tmp_path, change):
    _, _, policy, _, cache = valid_branch_context(tmp_path, 'In')
    control = deepcopy(cache[policy.point[1]]); f = control['functions'][0]
    if change == 'owner': f['row'][4] = 'other'
    elif change == 'body': f['body_sha256'] = 'f'*64
    elif change == 'identity': f['identity'][2] = 'other'
    elif change == 'types': f['types'][0][1] = 'int4'
    elif change == 'attrs': f['attributes'][4] = True
    elif change in ('cost', 'rows'): f['definition_attributes'][change] = '123'
    elif change == 'defaults': f['definition_attributes']['defaults']['sha256'] = 'f'*64
    elif change == 'default_count': f['definition_attributes']['default_count'] = 2
    elif change == 'language': f['attributes'][0] = 'sql'
    elif change == 'support': f['definition_attributes']['support'] = ['pg_catalog', 'support', 'internal']
    elif change == 'binary': f['definition_attributes']['binary'] = {'bytes': 1, 'sha256': 'f'*64}
    elif change == 'membership': f['extensions'][0][1] = '0.20.4'
    elif change == 'extra': f['extra'] = 'raw-canary'
    elif change == 'config': f['row'][7] = '{search_path=net}'
    elif change == 'secdef': f['row'][6] = True
    elif change == 'extension': control['extensions'][0][2] = 'net'
    elif change == 'function_absent': control['functions'].pop()
    elif change == 'extension_absent': control['extensions'] = []
    with pytest.raises(protocol.Unavailable): protocol.admit_mutation(policy, control, control)


def test_in_stage_acl_difference_admitted_but_final_source_acl_difference_rejected(tmp_path):
    ctx = valid_branch_context(tmp_path, 'In'); _, args, policy, _, cache = ctx
    control = cache[policy.point[1]]
    admission = protocol.admit_mutation(policy, control, deepcopy(control))
    assert admission['definition'] == [digest(['causal-net-definition-v1', i,
        {**{k: deepcopy(v) for k, v in item.items() if k not in ('row', 'definition_sha256')},
         'row': item['row'][:5]}]) for i, item in enumerate(policy.source_catalog['functions'])]
    assert admission['prefixAcl'] == [digest(['causal-net-acl-v1', i, item['row'][5]])
                                     for i, item in enumerate(control['functions'])]
    fresh = deepcopy(control); fresh['functions'][0]['row'][5] = '{other=X/other}'
    with pytest.raises(protocol.Unavailable, match='prefix_mismatch'):
        protocol.admit_mutation(policy, fresh, control)
    cfg = policy_args(ctx); cfg['failed_catalog']['functions'][0]['row'][5] = '{different=X/owner}'
    with pytest.raises(protocol.Unavailable): protocol.prepare_policy('In', **cfg)


@pytest.mark.parametrize('change', ['M_zero', 'M_minus_Z_zero', 'boundary', 'negative', 'reversed', 'duplicate'])
def test_pre_acl_conservative_bound_and_order_are_mandatory(tmp_path, change):
    ctx = valid_branch_context(tmp_path); args = policy_args(ctx); value = args['ledger']
    schemas = [r for r in value['selected'] if r['kind'] != 'pg_net_extension']
    if change == 'M_zero': value['counts']['passRows']['MAIN'] = 0
    elif change == 'M_minus_Z_zero': value['counts']['zeroOccurrenceRows'] = value['counts']['passRows']['MAIN']
    elif change == 'boundary': schemas[-1]['occurrence'] = value['counts']['passRows']['MAIN']-value['counts']['zeroOccurrenceRows']
    elif change == 'negative': schemas[-1]['occurrence'] = -1
    elif change == 'reversed': schemas[0]['occurrence'], schemas[1]['occurrence'] = schemas[1]['occurrence'], schemas[0]['occurrence']
    elif change == 'duplicate': schemas[0]['occurrence'] = schemas[1]['occurrence']
    with pytest.raises(protocol.Unavailable): protocol.prepare_policy('Is', **args)


@pytest.mark.parametrize('after', [False, True])
@pytest.mark.parametrize('drift', ['schema_acl', 'schema_initial', 'net_acl', 'body', 'attrs', 'extra_event', 'absent', 'partial'])
def test_factorization_never_hides_undeclared_or_partial_snapshot_drift(context, after, drift):
    _, _, policy, _, cache = context; control = cache[policy.point[1]]
    fresh = protocol.expected_catalog(policy.kind, control, policy.source_catalog) if after else deepcopy(control)
    if drift == 'schema_acl': fresh['schemas'][0]['row'][3] = '{unexpected=U/owner}'
    elif drift == 'schema_initial': fresh['schemas'][0]['initial'] = [['e', '{}', []]]
    elif drift == 'net_acl': fresh['functions'][0]['row'][5] = '{unexpected=X/owner}'
    elif drift == 'body': fresh['functions'][0]['body_sha256'] = 'f'*64
    elif drift == 'attrs': fresh['functions'][0]['attributes'][4] = True
    elif drift == 'extra_event': fresh['events'] = [{'unexpected': 'raw-canary'}]
    elif drift == 'absent': fresh['schemas'].pop()
    elif drift == 'partial':
        group = 'schemas' if policy.kind == 'Is' else 'functions'
        fresh[group][1] = deepcopy(control[group][1])
        if not after: fresh[group][1]['row'][-1] = 'unexpected'
    with pytest.raises(protocol.Unavailable):
        protocol.factor_catalog(policy, fresh, control, after=after, selected=policy.selected)


def _post(value):
    return next(e for e in value['exchanges'] if e['point'][0] == 'post')


MUTATIONS = [
    lambda v: v.update(schema='causal-branch-v0'),
    lambda v: v.update(status='matched'),
    lambda v: v.update(kind='combined'),
    lambda v: v.update(raw='raw-canary'),
    lambda v: v['bindings'].update(s0='0'*64),
    lambda v: v['bindings'].update(configuration='0'*64),
    lambda v: v['bindings'].update(expectation='0'*64),
    lambda v: v['target'].update(id='5'*64),
    lambda v: v['target'].update(id='6'*64),
    lambda v: v['target'].update(id='1'*64),
    lambda v: v['target'].update(id=v['target']['previous']),
    lambda v: v['target'].update(previous='2'*64),
    lambda v: v['target'].update(initialized='0'*64),
    lambda v: v.update(nonce='a'*32),
    lambda v: v.update(nonce='B'*32),
    lambda v: v['tool'].update(version='17.11'),
    lambda v: v['tool'].update(sha256='A'*64),
    lambda v: v['mutation'].update(point=['cut', True]),
    lambda v: v['mutation']['sql'].update(bytes=True),
    lambda v: v['mutation']['sql'].update(sha256='0'*64),
    lambda v: v['admission'].update(controlSnapshot='0'*64),
    lambda v: v['admission'].update(raw='raw-canary'),
    lambda v: v['exchanges'].pop(),
    lambda v: _post(v)['point'].__setitem__(0, 'cut'),
    lambda v: _post(v)['input'].__setitem__(1, _post(v)['input'][0]+1),
    lambda v: _post(v)['input'].__setitem__(0, True),
    lambda v: _post(v).update(pid=True),
    lambda v: _post(v).update(pid=1111),
    lambda v: _post(v)['witnesses'][0].__setitem__(0, '0123'),
    lambda v: _post(v)['witnesses'][0].__setitem__(1, '2026-01-01 00:00:00+00'),
    lambda v: _post(v)['witnesses'][0].__setitem__(2, '102'),
    lambda v: _post(v)['witnesses'][0].__setitem__(2, '1048577'),
    lambda v: _post(v)['witnesses'][0].append('raw-canary'),
    lambda v: _post(v)['witnesses'].pop(),
    lambda v: _post(v)['observer'].update(stdoutBytes=0),
    lambda v: _post(v)['observer'].update(stderrBytes=1),
    lambda v: _post(v)['observer'].update(stdoutEnd='partial'),
    lambda v: _post(v)['observer'].update(reap='unknown'),
    lambda v: _post(v)['observer'].update(exitCode=True),
    lambda v: _post(v).update(catalog={'mode': 'ref'}),
    lambda v: _post(v)['catalog']['values'][0].__setitem__(0, '0'*64),
    lambda v: _post(v)['catalog'].update(snapshot='raw-canary'),
    lambda v: v['exchanges'][0].update(catalog={'mode': 'ref'}),
    lambda v: v['delivery']['original'].update(bytes=0),
    lambda v: v['delivery']['probes'].update(bytes=1),
    lambda v: v['delivery']['mutation'].update(sha256='0'*64),
    lambda v: v['delivery'].update(frames=[True, True]),
    lambda v: v['delivery']['writer'].update(stdoutBytes=1),
    lambda v: v['delivery']['writer'].update(stderrBytes=65537),
    lambda v: v['delivery']['writer'].update(stderrEnd='closed'),
    lambda v: v['delivery']['writer'].update(exitCode=1),
    lambda v: v['delivery']['writer'].update(reap='poll'),
    lambda v: v['final']['raw']['actual'].update(sha256='0'*64),
    lambda v: v['final']['raw']['actual'].update(bytes=True),
    lambda v: v['final']['raw'].update(outside='0'*64),
    lambda v: v['final']['fingerprint'].update(auth='0'*64),
    lambda v: v['final']['fingerprint'].update(roles='0'*64),
    lambda v: v['final']['fingerprint'].update(companyMemberships='0'*64),
    lambda v: v['final']['fingerprint'].update(catalog='0'*64),
    lambda v: v['final'].update(enriched='0'*64),
    lambda v: v['cleanup'].update(children='unknown'),
    lambda v: v['cleanup'].update(resources='retained'),
]


@pytest.mark.parametrize('mutate', MUTATIONS)
def test_public_receipt_forgery_is_never_positive(context, mutate):
    value, args, _, _, _ = context; value = deepcopy(value); mutate(value)
    with pytest.raises(protocol.Unavailable) as error:
        protocol.validate_receipt(value, **args)
    assert 'raw-canary' not in str(error.value)


@pytest.mark.parametrize('fault', ['missing_inventory', 'stale_inventory', 'missing_code', 'extra_code',
    'S0unavailable', 'S0old', 'S0hash', 'sourcecleanup', 'sourcepostcheck', 'outerbusiness', 'Fsqlunavailable', 'ledgernegative'])
def test_positive_dependencies_revalidated_not_assumed(context, fault):
    value, args, _, _, _ = context; args = deepcopy(args)
    if fault == 'missing_inventory': args['inventory'] = None
    elif fault == 'stale_inventory': args['inventory']['checkpointIds'][0] += 1
    elif fault == 'missing_code': args['metadata']['code'].pop('rf1086_causal_catalog.py')
    elif fault == 'extra_code': args['metadata']['code']['extra.py'] = 'f'*64
    elif fault == 'S0unavailable': args['s0_receipt'] = s0.unavailable('headroom', 'admission')
    elif fault == 'S0old': args['s0_receipt']['schema'] = 's0-checkpoint-v1'
    elif fault == 'S0hash': args['s0_receipt']['bindings']['configuration'] = '0'*64
    elif fault in ('sourcecleanup', 'sourcepostcheck', 'outerbusiness'):
        key = {'sourcecleanup': 'cleanupComplete', 'sourcepostcheck': 'identitySourcePostcheck', 'outerbusiness': 'outerBusinessPostchecks'}[fault]
        args['metadata'][key] = not args['metadata'][key]
    elif fault == 'Fsqlunavailable': args['fsql'] = {'status': 'unavailable'}
    elif fault == 'ledgernegative': args['fsql']['ledger']['status'] = 'unavailable'
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(value, **args)


@pytest.mark.parametrize('extra', [dict(published=1), dict(published=True, worker_outcome='deadline', owned_cleanup=True),
    dict(published=True, worker_outcome='completed', owned_cleanup=False),
    dict(published=True, worker_outcome='completed', owned_cleanup=1), dict(worker_outcome='completed')])
def test_positive_parent_gates_remain_conjunctive(context, extra):
    value, args, _, _, _ = context
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(value, **args, **extra)


@pytest.mark.parametrize('stage,reasons', list(protocol.CONFIG['reasonStages'].items()))
def test_unavailable_closed_before_dependencies(stage, reasons):
    for kind in ('Is', 'In'):
        for reason in reasons:
            point = ['post', 2] if stage == 'transport' else None
            value = protocol.unavailable(kind, reason, stage, point)
            assert protocol.validate_receipt(value, s0_receipt=None, fsql=None, f2_input=None, metadata=None) is value
            assert protocol.validate_unavailable(value, kind=kind) is value
            for bad in (value | {'raw': 'canary'}, value | {'reason': 'raw error'}, value | {'schema': 'causal-branch-v0'},
                        value | {'point': ['cut', True]}, value | {'kind': 'combined'}):
                with pytest.raises(protocol.Unavailable): protocol.validate_unavailable(bad)
            with pytest.raises(protocol.Unavailable): protocol.validate_unavailable(value, kind='In' if kind == 'Is' else 'Is')


def test_same_generation_siblings_visible_ids_nonces_and_chain(tmp_path):
    is_value, args, *_ = valid_branch_context(tmp_path, 'Is')
    in_value, in_args, *_ = valid_branch_context(tmp_path, 'In')
    in_value['target']['previous'] = is_value['target']['id']
    assert args == in_args
    protocol.validate_receipt(is_value, **args, other=in_value)
    protocol.validate_receipt(in_value, **args, other=is_value)
    for bad in ('id', 'nonce', 'chain'):
        broken = deepcopy(in_value)
        if bad == 'id': broken['target']['id'] = is_value['target']['id']
        elif bad == 'nonce': broken['nonce'] = is_value['nonce']
        else: broken['target']['previous'] = '0'*64
        with pytest.raises(protocol.Unavailable): protocol.validate_receipt(is_value, **args, other=broken)
    # A hidden failed sibling's actual acquired target is not invented by reader.
    in_value['target']['previous'] = 'c'*64
    protocol.validate_receipt(in_value, **args, other=protocol.unavailable('Is', 'command', 'setup'))


def test_prefix_acl_hash_is_attested_but_definition_expectation_independent(tmp_path):
    value, args, *_ = valid_branch_context(tmp_path, 'In')
    value['admission']['prefixAcl'] = ['f'*64, 'e'*64]
    protocol.validate_receipt(value, **args)  # Cannot invert S0.net-other to rediscover ACL.
    value['admission']['definition'][0] = 'f'*64
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(value, **args)


def test_exact_in_tuple_types_and_no_phase_choice(tmp_path):
    value, args, *_ = valid_branch_context(tmp_path, 'In')
    for index, item in [(1, 1), (2, True), (1, False), (2, 0)]:
        bad = deepcopy(value); _post(bad)['catalog']['values'][0][index] = item
        with pytest.raises(protocol.Unavailable): protocol.validate_receipt(bad, **args)
    before = next(e for e in value['exchanges'] if e['point'] == value['mutation']['point'])
    before['catalog'] = deepcopy(_post(value)['catalog'])
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(value, **args)


def test_deadline_and_fatal_identity_no_private_error_text(context, monkeypatch):
    args = policy_args(context); kind = context[2].kind
    for deadline in (False, float('inf'), float('nan'), 0):
        with pytest.raises(protocol.Unavailable): protocol.prepare_policy(kind, **(args | {'deadline': deadline}))
    clock = iter((0, 10))
    monkeypatch.setattr(protocol.time, 'monotonic', lambda: next(clock))
    with pytest.raises(protocol.Unavailable, match='deadline'):
        protocol.prepare_policy(kind, **(args | {'deadline': 5}))
    fatal = KeyboardInterrupt('original')
    def fail(): raise fatal
    monkeypatch.setattr(protocol.time, 'monotonic', fail)
    with pytest.raises(KeyboardInterrupt) as error: protocol.prepare_policy(kind, **args)
    assert error.value is fatal


def test_branch_wire_only_fixed_sequence_namespace_and_s0_is_unchanged(tmp_path):
    value, args, policy, D, cache = valid_branch_context(tmp_path)
    session = deepcopy(args['s0_receipt']['exchanges'][0]['session'])
    assert protocol.parse_session(utf8(session), point=('anchor', 0), descriptor=D) == session
    witness = deepcopy(args['s0_receipt']['exchanges'][0]['witnesses'][0])
    with pytest.raises(protocol.Unavailable):
        protocol.parse_witness(utf8(witness), nonce='a'*32, sequence=0, session=session)
    witness[10] = protocol.probe('a'*32, 0)[1][:-1].decode()
    assert protocol.parse_witness(utf8(witness), nonce='a'*32, sequence=0, session=session) == witness
    with pytest.raises(s0.Unavailable): s0.parse_witness(utf8(witness), nonce='a'*32, sequence=0, session=session)
    for nonce, seq in [('A'*32, 0), ('a'*31, 0), ('a'*32, True), ('a'*32, -1), ('a'*32, 7)]:
        with pytest.raises(protocol.Unavailable): protocol.probe(nonce, seq)
    with pytest.raises(s0.Unavailable): s0.probe('a'*32, 6)


def test_utf8_reconstruction_wire_minimum_not_ascii_catalog_length(context):
    value, args, policy, _, _ = context
    value, args = deepcopy((value, args)); control = args['s0_receipt']
    # A nonASCII same-epoch baseline is permitted; the server's raw UTF8 frame
    # does not have the larger ensure_ascii canonical-commitment byte length.
    writer = 0
    for sequence, exchange in enumerate(control['exchanges']):
        exchange['session'][-2] = '\u00e9'
        writer += 40+2*len(utf8(exchange['session']))+1+40+len(str(exchange['barrierPid']))+1
        roles = ['anchor'] if exchange['point'][0] == 'anchor' else ['before', 'after']
        exchange['observer']['stdoutBytes'] = sum(len(f'S0O/{control["nonce"]}/{sequence:02d}/{role}/')+2*len(utf8(w))+1
            for role, w in zip(roles, exchange['witnesses'], strict=True))
    control['delivery']['writer']['stdoutBytes'] = writer
    value['bindings']['s0'] = digest(control)
    controls = {tuple(e['point']): e for e in control['exchanges']}; writer = 0
    for sequence, exchange in enumerate(value['exchanges']):
        point = tuple(exchange['point']); mapped = ('cut', point[1]) if point[0] == 'post' else point
        session = deepcopy(controls[mapped]['session']); session[1] = exchange['pid']
        writer += 40+2*len(utf8(session))+1+40+len(str(session[1]))+1
        roles = ['anchor'] if point[0] == 'anchor' else ['before', 'after']
        minimum = 0
        for role, dynamic in zip(roles, exchange['witnesses'], strict=True):
            oid, started, capacity = dynamic
            w = [session[0], oid, session[1], oid, session[0], started, 'idle', None, None, None,
                 protocol.probe(value['nonce'], sequence)[1][:-1].decode(), 'UTF8', 'UTF8', capacity, 'B', 'postmaster', 'integer']
            minimum += len(f'C1O/{value["nonce"]}/{sequence:02d}/{role}/')+2*len(utf8(w))+1
        exchange['observer']['stdoutBytes'] = minimum
    value['delivery']['writer']['stdoutBytes'] = writer
    protocol.validate_receipt(value, **args)
    value['delivery']['writer']['stdoutBytes'] -= 1
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(value, **args)
    value['delivery']['writer']['stdoutBytes'] += 1
    _post(value)['observer']['stdoutBytes'] -= 1
    with pytest.raises(protocol.Unavailable): protocol.validate_receipt(value, **args)


def test_selected_binding_and_absent_components_still_reject_after_rebinding(context):
    value, args, policy, _, _ = context
    for change in ('selected', 'absent', 'snapshot'):
        v, a = deepcopy((value, args)); before = next(e for e in a['s0_receipt']['exchanges'] if tuple(e['point']) == policy.point)
        if change == 'selected':
            if policy.kind == 'Is': before['catalog']['schemas'][0][0] = '0'*64
            else: before['catalog']['extensions'][0][1] = '0'*64
        elif change == 'absent':
            # Keep the selected object valid; the branch still needs both of its targets.
            if policy.kind == 'Is': before['catalog']['schemas'][1] = None
            else: before['catalog']['net'][1] = None
        else: before['catalog']['snapshot'] = '0'*64
        v['bindings']['s0'] = digest(a['s0_receipt'])
        with pytest.raises(protocol.Unavailable): protocol.validate_receipt(v, **a)


def test_maximum_covers_largest_permitted_dynamic_fields_and_negatives(tmp_path):
    for kind in ('Is', 'In'):
        value, args, policy, D, cache = valid_branch_context(tmp_path, kind, extra_reconnect=True)
        for exchange in value['exchanges']:
            exchange['pid'] = 2147483647
            epoch = exchange['point'][1] if exchange['point'][0] == 'anchor' else D['cuts'][exchange['point'][1]][0]
            for witness in exchange['witnesses']:
                witness[:] = ['4294967295', f'9999-12-31 23:59:5{epoch}.999999+00', '1048576']
        value['delivery']['writer']['stderrBytes'] = 65536
        protocol.validate_receipt(value, **args)
        maximum = protocol.maximum_receipt(kind, **{k: v for k, v in args.items() if k != 's0_receipt'}, descriptor=D)
        size = len(canonical(maximum)); assert len(canonical(value)) <= size <= 10240
        for stage, reasons in protocol.CONFIG['reasonStages'].items():
            for reason in reasons:
                assert len(canonical(protocol.unavailable(kind, reason, stage,
                    ['post', 2] if stage == 'transport' else None))) <= size


def test_final_prediction_preserves_every_nonintervened_normalized_field(context):
    _, args, policy, _, _ = context
    failed = args['fsql']['catalog']; expected = policy.expected_final
    other = 'functions' if policy.kind == 'Is' else 'schemas'
    assert expected[other] == failed[other]
    assert expected['hooks'] == failed['hooks'] and expected['events'] == failed['events']
    assert expected['extensions'] == failed['extensions']
    for i in range(2):
        if policy.kind == 'Is':
            assert expected['schemas'][i]['initial'] == []
            assert policy.source_catalog['schemas'][i]['initial'] != []
        else:
            assert expected['functions'][i]['row'][5] == failed['functions'][i]['row'][5]
            assert expected['functions'][i]['body_sha256'] == failed['functions'][i]['body_sha256']
