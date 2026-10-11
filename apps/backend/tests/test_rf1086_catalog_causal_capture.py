"""Four-object diagnosis remains private, bounded and outside acceptance."""
import base64
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import rf1086_catalog_causal_capture as causal
from rf1086_catalog_difference import CatalogCapture, _encoded


def retained(snapshot):
    result = CatalogCapture()
    rows = [item['row'] for key in ('schemas', 'functions', 'hooks') for item in snapshot[key]]
    result.capture(_encoded(rows) + b'\n{}\n[]\n')
    return result


@pytest.fixture
def snapshot():
    grants = [['private-owner', False, 'private-reader', 'USAGE', True], ['private-owner', True, None, 'USAGE', False]]
    schemas = [{'identity': identity, 'row': identity + ['private-owner', '{private-acl}'],
        'defaults': '{private-owner=UC/private-owner}', 'default_grants': [], 'grants': deepcopy(grants),
        'initial': [['e', '{private-acl}', deepcopy(grants)]], 'extensions': []} for identity in causal.SCHEMAS]
    functions = [{'identity': identity, 'row': identity + ['private-owner', None, True, '{search_path=net}'],
        'definition_sha256': 'c' * 64, 'body_sha256': 'd' * 64,
        'attributes': ['plpgsql', 'bigint', 'f', 'v', False, 'u', False, False],
        'types': [['pg_catalog', name] for name in causal.NET_TYPES[i]],
        'extensions': [['pg_net', '0.20.3', 'private-owner']]} for i, identity in enumerate(causal.NET_IDENTITIES)]
    return {'serverVersion': 170006, 'schemas': schemas, 'functions': functions, 'hooks': [], 'events': [],
        'extensions': [['pg_net', '0.20.3', 'net', 'private-owner']]}


def test_exact_predump_binding_preserves_public_and_grant_options(snapshot):
    value = causal._validate_snapshot(deepcopy(snapshot), retained(snapshot))
    assert value['schemas'][0]['grants'] == snapshot['schemas'][0]['grants']
    assert value['schemas'][0]['initial'][0][2][0][-1] is True
    assert value['functions'][0]['body_sha256'] == 'd' * 64


@pytest.mark.parametrize('fault', ['drift', 'extra', 'missing', 'duplicate', 'dangling', 'public_role', 'long_principal',
    'bad_privilege', 'duplicate_initial', 'bad_initial', 'bad_types', 'unexpected_config', 'extra_metadata'])
def test_malformed_or_unbound_snapshot_is_unavailable(snapshot, fault):
    original = retained(snapshot)
    row = snapshot['schemas'][0]
    if fault == 'drift': row['row'][-1] = None
    elif fault == 'extra': row['identity'] = ['schema', 'private-extra']
    elif fault == 'missing': snapshot['functions'].pop()
    elif fault == 'duplicate': snapshot['schemas'][1] = deepcopy(row)
    elif fault == 'dangling': row['grants'][0][0] = None
    elif fault == 'public_role': row['grants'][1][2] = 'PUBLIC'
    elif fault == 'long_principal': row['grants'][0][0] = 'x' * 257
    elif fault == 'bad_privilege': row['grants'][0][3] = 'SELECT'
    elif fault == 'duplicate_initial': row['initial'].append(deepcopy(row['initial'][0]))
    elif fault == 'bad_initial': row['initial'][0][0] = 'x'
    elif fault == 'bad_types': snapshot['functions'][0]['types'][0][0] = 'private-schema'
    elif fault == 'unexpected_config': snapshot['functions'][0]['row'][-1] = '{private-secret=canary}'
    else: row['password'] = 'private-secret'
    with pytest.raises((ValueError, TypeError)): causal._validate_snapshot(snapshot, original)


@pytest.mark.parametrize('privtype', ['e', 'i', None])
def test_initial_privileges_absent_or_extension_or_initdb_remain_distinct(snapshot, privtype):
    row = snapshot['schemas'][0]
    row['initial'] = [] if privtype is None else [[privtype, '{}', []]]
    assert causal._validate_snapshot(deepcopy(snapshot), retained(snapshot))['schemas'][0]['initial'] == row['initial']


def test_initial_target_can_prove_absence_but_source_cannot(snapshot):
    empty = {'serverVersion': 170006, **{key: [] for key in ('schemas', 'functions', 'hooks', 'events', 'extensions')}}
    assert causal._validate_snapshot(deepcopy(empty), None) == empty
    with pytest.raises(ValueError): causal._validate_snapshot(empty, retained(snapshot))


@pytest.fixture(scope='module')
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


@pytest.fixture
def binding(key):
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return {'version': 1, 'run': '12345', 'attempt': '1', 'mergeSha': 'a' * 40, 'image': 'sha256:' + 'b' * 64,
        'capture': 'c' * 32, 'publicKeySha256': hashlib.sha256(public).hexdigest()}


def decode(lines, key, binding):
    expected = {name: binding[name] for name in ('run', 'attempt', 'mergeSha', 'image', 'publicKeySha256')}
    loaded = serialization.load_pem_private_key(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()), password=None)
    return causal.decrypt_capsules('\n'.join(lines), loaded, expected)


def test_capsules_encrypt_private_metadata_and_deduplicate_complete_ci_replays(key, binding):
    payload = {'grants': [['private-canary', True, None, 'USAGE', True]], 'sql': 'GRANT USAGE ON SCHEMA graphql TO "private-canary";'}
    lines = [causal._seal(payload, binding | {'phase': phase}, key.public_key()) for phase in causal.PHASES]
    assert 'private-canary' not in '\n'.join(lines)
    assert all(len(line.encode()) < causal.MAX_ENVELOPE for line in lines)
    replay = ['2026-10-11T20:31:20.8975240Z   ' + line for line in reversed(lines)]
    replay += lines + ['2026-10-11T20:31:20.8975240Z stderr: ' + lines[0][:100]]
    assert decode(replay, key, binding) == dict.fromkeys(causal.PHASES, payload)


@pytest.mark.parametrize('fault', ['aad', 'tag', 'truncated', 'missing', 'conflicting', 'capture', 'nonce', 'wrong_key'])
def test_capsule_tamper_or_incomplete_groups_never_count_as_evidence(key, binding, fault):
    lines = [causal._seal({'private': 'canary'}, binding | {'phase': phase}, key.public_key()) for phase in causal.PHASES]
    item = json.loads(lines[0].removeprefix(causal.TAG))
    if fault == 'aad': item['aad']['run'] = '9876'
    elif fault == 'tag': item['ciphertext'] = base64.b64encode(b'bad' * 12).decode()
    elif fault == 'capture': item['aad']['capture'] = 'e' * 32
    elif fault == 'nonce': item['nonce'] = json.loads(lines[1].removeprefix(causal.TAG))['nonce']
    elif fault == 'missing': lines.pop()
    elif fault == 'truncated': lines[1] = lines[1][:90]
    elif fault == 'conflicting': lines.append(causal._seal({'different': True}, binding | {'phase': causal.PHASES[0]}, key.public_key()))
    elif fault == 'wrong_key': key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    lines[0] = causal.TAG + _encoded(item).decode()
    with pytest.raises((ValueError, InvalidTag)): decode(lines, key, binding)


def test_max_plaintext_and_representative_four_objects_plus_sql_fit(snapshot, key, binding):
    payload = {'catalog': snapshot, 'archive': {'sql': 'x' * (6 * 1024)}}
    assert len(_encoded(payload)) <= causal.MAX_PLAINTEXT
    assert len(causal._seal(payload, binding | {'phase': 'mismatch'}, key.public_key()).encode()) < causal.MAX_ENVELOPE
    exact = {'data': 'x' * (causal.MAX_PLAINTEXT - len(_encoded({'data': ''})))}
    assert len(_encoded(exact)) == causal.MAX_PLAINTEXT
    causal._seal(exact, binding, key.public_key())
    exact['data'] += 'x'
    with pytest.raises(ValueError): causal._seal(exact, binding, key.public_key())


@pytest.mark.parametrize('ids', [[], ['1', '1'], ['0'], ['-1'], ['100000000'], ['1;touch bad'], ['1\n2'], ['$(whoami)'], list(map(str, range(1, 34)))])
def test_toc_selection_has_only_bounded_numeric_ids(ids):
    with pytest.raises(ValueError): causal._selection_script(ids)


def test_selection_executes_output_only_restore_with_independent_fd():
    script = causal._selection_script(['4', '2'])
    assert script == "exec pg_restore --file=- --use-list=/dev/fd/3 3<<'TALLI_CAUSAL_TOC'\n4\n2\nTALLI_CAUSAL_TOC\n"
    assert not any(value in script for value in ('--dbname', '--create', '--clean', '--data-only'))


@pytest.fixture
def capture(monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID', '12345'); monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '1'); monkeypatch.setenv('GITHUB_SHA', 'a' * 40)
    with causal.CausalCapture({'Id': 'a' * 64, 'Image': 'sha256:' + 'b' * 64, 'Config': {'Cmd': ['private-command-canary']}}, 'fixed init') as capture:
        yield capture


def test_capture_silently_buffers_and_clears_on_success_or_early_error(capture, snapshot, monkeypatch, capsys):
    monkeypatch.setattr(causal, '_snapshot', lambda *a, **k: deepcopy(snapshot))
    monkeypatch.setattr(causal, '_files', lambda *a, **k: {})
    capture.source_pre_dump(retained(snapshot))
    assert set(capture.snapshots) == {'source_pre_dump'}
    assert capsys.readouterr().err == ''
    capture.__exit__(None, None, None)
    assert capture.snapshots == {} and capture.public_key is None


@pytest.mark.parametrize('failure', [RuntimeError('private-canary'), KeyboardInterrupt('private-cancel')])
def test_failure_is_quiet_cancellation_propagates_and_budget_is_charged(capture, monkeypatch, capsys, failure):
    ticks = iter([10.0, 12.0]); monkeypatch.setattr(causal.time, 'monotonic', lambda: next(ticks))
    old_budget = capture.remaining
    def fail(_): raise failure
    if isinstance(failure, Exception): capture._attempt(fail)
    else:
        with pytest.raises(KeyboardInterrupt): capture._attempt(fail)
    assert capture.remaining == old_budget - 2
    assert capsys.readouterr().err == ''


def test_missing_ci_binding_never_reads_source_and_only_fixed_unavailable_on_mismatch(monkeypatch, capsys):
    monkeypatch.delenv('GITHUB_RUN_ID', raising=False)
    monkeypatch.setattr(causal, '_command', lambda *a, **k: pytest.fail('no diagnostic commands without CI binding'))
    with causal.CausalCapture({'Id': 'a' * 64, 'Image': 'sha256:' + 'b' * 64}, 'init') as capture:
        capture.source_pre_dump(None); capture.mismatch(None, None, 'e' * 64, io.BytesIO())
    assert capsys.readouterr().err == causal.TAG + '{"status":"unavailable"}\n'


def toc(entries):
    return ('; TOC Entries: ' + str(len(entries)) + '\n; Format: CUSTOM\n'
        '; Dumped from database version: 17.6\n; Dumped by pg_dump version: 17.6\n'
        '; Selected TOC Entries:\n' + '\n'.join(entries) + '\n').encode()


@pytest.mark.parametrize('fault', [None, 'wrong_owner', 'duplicate_schema', 'oversize_sql', 'cancel'])
def test_archive_selection_keeps_order_and_sql_without_body_data_and_restores_position(snapshot, monkeypatch, fault):
    archive = io.BytesIO(b'private-custom-archive'); archive.seek(7)
    entries = ['1; 2615 10 SCHEMA - graphql private-owner', '2; 0 0 ACL - SCHEMA graphql private-owner',
        '3; 0 0 TABLE DATA private business private-owner', '4; 3079 20 EXTENSION - pg_net ']
    if fault == 'wrong_owner': entries[0] = entries[0].replace('private-owner', 'wrong-owner')
    if fault == 'duplicate_schema': entries.append('5; 2615 10 SCHEMA - graphql private-owner')
    observed = []
    def command(args, deadline, **kwargs):
        assert kwargs['archive'] is archive and archive.tell() == 0
        if '--list' in args: return toc(entries)
        if fault == 'cancel': raise KeyboardInterrupt()
        observed.append(args)
        return b'x' * (6 * 1024 + 1) if fault == 'oversize_sql' else b'SET SESSION AUTHORIZATION "private-owner";\nGRANT USAGE ON SCHEMA graphql TO PUBLIC;\n'
    monkeypatch.setattr(causal, '_command', command)
    if fault:
        with pytest.raises(KeyboardInterrupt if fault == 'cancel' else ValueError):
            causal._archive(archive, 'e' * 64, snapshot, causal.time.monotonic() + 5)
    else:
        result = causal._archive(archive, 'e' * 64, snapshot, causal.time.monotonic() + 5)
        assert [row[0] for row in result['selected']] == ['1', '2', '4']
        assert result['sql'].startswith('SET SESSION AUTHORIZATION')
        assert result['writerInventoryComplete'] is False
        assert observed[0][-1] == causal._selection_script(['1', '2', '4'])
        assert 'TABLE DATA' not in json.dumps(result)
    assert archive.tell() == 7 and not archive.closed


@pytest.mark.parametrize('fault', [None, 'source_drift', 'overflow', 'encryption', 'cancel'])
def test_all_phases_are_prepared_before_printing_or_fixed_failure(capture, snapshot, monkeypatch, capsys, fault):
    capture.snapshots = {'source_pre_dump': {'catalog': deepcopy(snapshot), 'files': {'status': 'observed', 'value': {}}},
        'target_initialized': {'target': 'e' * 64, 'files': {'status': 'observed', 'value': {}}}}
    def read(*args, **kwargs):
        if fault == 'cancel': raise KeyboardInterrupt()
        result = deepcopy(snapshot)
        if fault == 'source_drift': result['functions'][0]['body_sha256'] = 'f' * 64
        return result
    monkeypatch.setattr(causal, '_snapshot', read)
    monkeypatch.setattr(causal, '_archive', lambda *args: {'sql': 'x' * (causal.MAX_PLAINTEXT if fault == 'overflow' else 10)})
    original = causal._seal; calls = []
    def seal(*args):
        assert capsys.readouterr().err == ''
        calls.append(args[1]['phase'])
        if fault == 'encryption' and len(calls) == 2: raise ValueError('private-canary')
        return original(*args)
    monkeypatch.setattr(causal, '_seal', seal)
    if fault == 'cancel':
        with pytest.raises(KeyboardInterrupt): capture.mismatch(retained(snapshot), retained(snapshot), 'e' * 64, io.BytesIO())
        assert capsys.readouterr().err == ''
        return
    capture.mismatch(retained(snapshot), retained(snapshot), 'e' * 64, io.BytesIO())
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == (3 if fault is None else 1)
    if fault: assert lines == [causal.TAG + '{"status":"unavailable"}']
    else: assert calls == list(causal.PHASES)
    assert capture.snapshots == {}


@pytest.mark.parametrize('fault', [None, 'image', 'name', 'nonce', 'command', 'network'])
def test_initial_target_capture_binds_owned_container_and_direct_init(capture, snapshot, monkeypatch, fault):
    capture.snapshots = {'source_pre_dump': {'catalog': snapshot}}
    target, nonce = 'e' * 64, 'f' * 32
    name, network = 'rf193_identity_db_' + nonce, 'rf193_identity_net_' + nonce
    values = [target, capture.image, '/' + name, nonce, ['sh'], ['-c', 'fixed init'], network]
    index = {'image': 1, 'name': 2, 'nonce': 3, 'command': 5, 'network': 6}.get(fault)
    if index is not None: values[index] = 'private-wrong-value'
    def command(args, *_):
        assert args[:3] == ['docker', 'inspect', '--format'] and args[-1] == target
        assert '.Env' not in args[3] and '.Config.Labels' in args[3]
        return '|'.join(json.dumps(x) for x in values).encode() + b'\n'
    monkeypatch.setattr(causal, '_command', command)
    monkeypatch.setattr(causal, '_snapshot', lambda *a, **k: {'schemas': [], 'functions': []})
    monkeypatch.setattr(causal, '_files', lambda *a, **k: {})
    capture.target_initialized(target, name, nonce, network)
    assert capture.failed == (fault is not None)
    if fault is None: assert capture.snapshots['target_initialized']['ownedInitMatches']
    else: assert capture.snapshots == {}


@pytest.mark.parametrize('fault', [None, 'version_traversal', 'extension_traversal', 'oversize'])
def test_installed_files_use_closed_paths_and_only_return_byte_hashes(monkeypatch, fault):
    extensions = [['pg_net', '0.20.3', 'net', 'private-owner']]
    if fault == 'version_traversal': extensions[0][1] = '../secret'
    if fault == 'extension_traversal': extensions[0][0] = '../../secret'
    calls = []
    def command(args, *_):
        calls.append(args)
        assert args[5] == causal.FILE_READER and 'head -c 262145' in args[5]
        return b'x' * (256 * 1024 + 1) if fault == 'oversize' else b'private-file-canary'
    monkeypatch.setattr(causal, '_command', command)
    if fault:
        with pytest.raises(ValueError): causal._files('a' * 64, extensions, 10)
        if 'traversal' in fault: assert calls == []
    else:
        result = causal._files('a' * 64, extensions, 10)
        assert set(result) == {'pg_net.control', 'pg_net--0.20.3.sql'}
        assert all(value['sha256'] == hashlib.sha256(b'private-file-canary').hexdigest() for value in result.values())
        assert 'private-file-canary' not in json.dumps(result)


def test_three_capture_calls_share_one_active_budget_without_charging_intervening_restore(capture, monkeypatch):
    ticks = iter([10, 11, 12, 100, 102, 103, 1000, 1001, 1002])
    monkeypatch.setattr(causal.time, 'monotonic', lambda: next(ticks))
    capture.remaining = 15
    deadlines = []
    for _ in range(3): capture._attempt(deadlines.append)
    assert deadlines == [25, 113, 1010]
    assert capture.remaining == 8


def test_exhausted_budget_does_not_run_action_or_extend_deadline(capture, monkeypatch):
    capture.remaining = 0
    capture._attempt(lambda _: pytest.fail('budget exhausted'))
    assert capture.failed and capture.snapshots == {}


@pytest.mark.parametrize('fault', [None, 'source_files', 'target_files', 'archive'])
def test_auxiliary_group_failure_preserves_bound_catalogs(capture, snapshot, key, binding, monkeypatch, capsys, fault):
    capture.public_key = key.public_key(); capture.binding = binding
    target, nonce = 'e' * 64, 'f' * 32
    name, network = 'rf193_identity_db_' + nonce, 'rf193_identity_net_' + nonce
    values = [target, capture.image, '/' + name, nonce, ['sh'], ['-c', 'fixed init'], network]
    monkeypatch.setattr(causal, '_command', lambda *a, **k: '|'.join(json.dumps(x) for x in values).encode())
    monkeypatch.setattr(causal, '_snapshot', lambda *a, **k: deepcopy(snapshot))
    def files(*args, **kwargs):
        group = 'source_files' if kwargs.get('source') else 'target_files'
        if fault == group: raise FileNotFoundError('private-file-canary')
        return {'file': {'sha256': 'd' * 64}}
    def archive(*args):
        if fault == 'archive': raise ValueError('private-archive-canary')
        return {'sql': 'private-sql-canary', 'writerInventoryComplete': False}
    monkeypatch.setattr(causal, '_files', files); monkeypatch.setattr(causal, '_archive', archive)
    capture.source_pre_dump(retained(snapshot))
    capture.target_initialized(target, name, nonce, network)
    assert capsys.readouterr().err == ''
    capture.mismatch(retained(snapshot), retained(snapshot), target, io.BytesIO())
    output = capsys.readouterr().err
    assert 'private-' not in output
    decoded = decode(output.splitlines(), key, binding)
    for phase, group, label in zip(causal.PHASES, ('files', 'files', 'archive'), ('source_files', 'target_files', 'archive')):
        assert decoded[phase]['catalog'] == snapshot
        assert decoded[phase][group]['status'] == ('unavailable' if fault == label else 'observed')
        if fault == label: assert decoded[phase][group] == {'status': 'unavailable'}
        else: assert 'value' in decoded[phase][group]
        assert decoded[phase]['captureGroupsComplete'] == (fault is None)
    assert capture.snapshots == {} and not capture.failed


@pytest.mark.parametrize('fault', ['deadline', 'cancel'])
def test_auxiliary_group_does_not_swallow_deadline_or_cancellation(capture, monkeypatch, fault):
    ticks = iter([10, 12]); monkeypatch.setattr(causal.time, 'monotonic', lambda: next(ticks))
    def action():
        if fault == 'cancel': raise KeyboardInterrupt('private-canary')
        raise FileNotFoundError('private-canary')
    with pytest.raises(KeyboardInterrupt if fault == 'cancel' else ValueError):
        capture._group(action, 11)
