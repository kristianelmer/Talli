"""Object restoration rejects foreign sources and cleans only its own resources."""
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
import rf1086_storage_restore as storage

SOURCE = {
    'Id': 'a' * 64, 'Name': '/supabase_storage_tallig9931', 'Image': 'sha256:' + 'b' * 64,
    'State': {'Running': True}, 'NetworkSettings': {'Networks': {'supabase_network_tallig9931': {}}},
    'Mounts': [{'Destination': '/mnt', 'Type': 'volume', 'Name': 'owned-source'}],
    'Config': {'Env': ['STORAGE_BACKEND=file', 'FILE_STORAGE_BACKEND_PATH=/mnt',
                      'DATABASE_URL=postgresql://storage:local@supabase_db_tallig9931:5432/postgres',
                      'VECTOR_DATABASE_URL=postgresql://storage:local@supabase_db_tallig9931:5432/postgres',
                      'SERVICE_KEY=local']},
}
ENV = dict(item.split('=', 1) for item in SOURCE['Config']['Env'])
CLONE = 'postgresql://postgres:local@127.0.0.1:55001/rf193_restore_' + 'c' * 32


def test_documents_snapshots_preserve_retained_bytes_and_reject_conflicting_generations():
    original = SimpleNamespace(receipt=SimpleNamespace(document_id='one'), content=b'original')
    snapshot = SimpleNamespace(document=SimpleNamespace(storage_key='one/key'), original=original)
    assert storage.ordinary_originals([snapshot, deepcopy(snapshot)]) == [original]
    changed = deepcopy(snapshot)
    changed.original.content = b'changed'
    with pytest.raises(ValueError, match='conflicting retained generations'):
        storage.ordinary_originals([snapshot, changed])


@pytest.mark.parametrize('fault', [None, 'not_running', 'network', 'image', 'mount', 'remote_db',
                                   'source_db', 'query_override', 'backend', 'remote_auth', 'missing_key', 'gateway_port'])
def test_source_must_be_the_exact_owned_file_store(tmp_path, monkeypatch, fault):
    (tmp_path / 'supabase').mkdir()
    (tmp_path / 'supabase/config.toml').write_text('project_id="tallig9931"\n[api]\nport=55000\n')
    monkeypatch.setenv('SUPABASE_URL', 'http://127.0.0.1:55000')
    monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', 'local')
    source = deepcopy(SOURCE)
    if fault == 'not_running': source['State']['Running'] = False
    if fault == 'network': source['NetworkSettings']['Networks'] = {'other': {}}
    if fault == 'image': source['Image'] = 'mutable-tag'
    if fault == 'mount': source['Mounts'][0]['Type'] = 'bind'
    replacements = {'remote_db': ('DATABASE_URL', 'postgresql://storage:local@remote:5432/postgres'),
                    'source_db': ('VECTOR_DATABASE_URL', 'postgresql://storage:local@supabase_db_tallig9931:5432/other'),
                    'query_override': ('DATABASE_URL', ENV['DATABASE_URL'] + '?host=remote'),
                    'backend': ('STORAGE_BACKEND', 's3')}
    if fault in replacements:
        key, value = replacements[fault]
        source['Config']['Env'] = [item for item in source['Config']['Env'] if not item.startswith(key + '=')] + [key + '=' + value]
    if fault == 'remote_auth': monkeypatch.setenv('SUPABASE_URL', 'https://remote.invalid')
    if fault == 'missing_key': monkeypatch.setenv('SUPABASE_SERVICE_ROLE_KEY', '')
    gateway = {'Name': '/supabase_kong_tallig9931', 'State': {'Running': True},
               'NetworkSettings': {'Networks': {'supabase_network_tallig9931': {}},
                                   'Ports': {'8000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '55001' if fault == 'gateway_port' else '55000'}]}}}
    verified = []
    boundary = SimpleNamespace(owned_source=lambda *_: ('db-id', 'postgres'),
        verify_source_session=lambda *args: verified.append(args),
        inspect_container=lambda name: source if name.startswith('supabase_storage_') else gateway if name.startswith('supabase_kong_') else SOURCE)
    if fault:
        with pytest.raises(ValueError): storage.storage_source(tmp_path, 'owned-url', boundary)
    else:
        actual, env, network = storage.storage_source(tmp_path, 'owned-url', boundary)
        assert actual is source and env == ENV and network == 'supabase_network_tallig9931'
    assert verified == [('owned-url', 'db-id')]


def test_clone_configuration_retargets_both_databases_and_excludes_unneeded_integrations():
    env = ENV | {'JWT_JWKS': '{}', 'IMGPROXY_URL': 'https://external.invalid', 'LOG_LEVEL': 'debug',
                 'DB_MIGRATIONS_FREEZE_AT': 'fixture-version', 'VECTOR_STORE_MIGRATIONS_ENABLED': 'false'}
    actual = storage.clone_environment(env, CLONE)
    for key in ('DATABASE_URL', 'VECTOR_DATABASE_URL'):
        assert actual[key].endswith('/rf193_restore_' + 'c' * 32)
        assert 'supabase_db_tallig9931:5432' in actual[key]
    assert actual['LOG_LEVEL'] == 'fatal' and 'IMGPROXY_URL' not in actual
    assert actual['STORAGE_BACKEND'] == 'file'
    assert actual['DB_MIGRATIONS_FREEZE_AT'] == 'fixture-version'
    assert actual['VECTOR_STORE_MIGRATIONS_ENABLED'] == 'false'
    with pytest.raises(ValueError): storage.clone_environment(env, CLONE.replace('rf193_restore_', 'existing_'))
    with pytest.raises(ValueError): storage.clone_environment(env | {'SERVICE_KEY': 'a\nb'}, CLONE)


@pytest.mark.parametrize('failure', [None, 'volume', 'copy', 'attributes', 'create', 'start', 'verify', 'source_changed'])
def test_cleanup_removes_only_owned_new_volume_and_pinned_container(monkeypatch, failure):
    calls, volume_identity = [], {}
    snapshots = iter(['same', 'different' if failure == 'source_changed' else 'same'])
    monkeypatch.setattr(storage, 'snapshot', lambda container, target: next(snapshots))
    monkeypatch.setattr(storage, 'attributes', lambda _: b'[]')
    def checked(args, **kwargs):
        calls.append(args)
        stage = {'volume': 'volume', 'run': 'copy', 'create': 'create', 'start': 'start'}.get(args[1])
        if args[1:3] == ['volume', 'create']:
            volume_identity.update(Name=args[-1], Labels={'talli.rf.restore': args[-2].split('=')[1]})
        if failure is not None and stage == failure and not (args[1:3] == ['volume', 'rm']):
            raise RuntimeError('fixture ' + failure)
        if args[1] == 'create':
            path = Path(args[args.index('--env-file') + 1])
            assert path.stat().st_mode & 0o777 == 0o600
            assert '/rf193_restore_' in path.read_text()
        if args[-1] == storage.CAPTURE_ATTRIBUTES:
            return SimpleNamespace(stdout=b'changed' if failure == 'attributes' else b'[]')
        return SimpleNamespace(stdout=('d' * 64).encode())
    monkeypatch.setattr(storage, 'checked', checked)
    monkeypatch.setattr(storage.subprocess, 'check_output', lambda *_: json.dumps([volume_identity]).encode())
    @contextmanager
    def gateway(port):
        assert port == 55123
        yield 'http://127.0.0.1:55124'
    monkeypatch.setattr(storage, 'storage_gateway', gateway)
    class Client:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def get(self, _): return SimpleNamespace(status_code=200)
    monkeypatch.setattr(storage.httpx, 'Client', Client)
    boundary = SimpleNamespace(inspect_container=lambda _: {'NetworkSettings': {'Ports': {
        '5000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '55123'}]}}})
    def run():
        with storage.restored_storage(SOURCE, ENV, 'owned-network', CLONE, boundary):
            if failure == 'verify': raise RuntimeError('fixture verify')
    if failure in ('source_changed', 'attributes'):
        with pytest.raises(ValueError, match='changed source|attributes differ'): run()
    elif failure:
        with pytest.raises(RuntimeError, match='fixture'): run()
    else:
        run()
    removals = [args for args in calls if args[1] == 'rm']
    assert removals == ([] if failure in ('volume', 'copy', 'attributes', 'create') else [['docker', 'rm', '-f', 'd' * 64]])
    volumes = [args for args in calls if args[1:3] == ['volume', 'rm']]
    assert len(volumes) == (0 if failure == 'volume' else 1)
    if volumes:
        assert volumes[0][-1] == volume_identity['Name'] and volumes[0][-1] != 'owned-source'
    for command in [args for args in calls if args[1] in ('run', 'create')]:
        assert SOURCE['Image'] in command and 'owned-source:/mnt' not in command


def test_existing_volume_without_this_run_label_is_never_removed(monkeypatch):
    calls = []
    monkeypatch.setattr(storage, 'snapshot', lambda *_: 'same')
    monkeypatch.setattr(storage, 'attributes', lambda _: b'[]')
    monkeypatch.setattr(storage, 'checked', lambda args, **_: calls.append(args))
    monkeypatch.setattr(storage.subprocess, 'check_output', lambda *_: json.dumps([{'Name': 'existing', 'Labels': {}}]).encode())
    with pytest.raises(ValueError, match='ownership mismatch'):
        with storage.restored_storage(SOURCE, ENV, 'owned-network', CLONE, None):
            pytest.fail('Created service for foreign volume')
    assert len(calls) == 1 and calls[0][1:3] == ['volume', 'create']


@pytest.mark.parametrize('timeout', [False, True])
def test_command_failures_do_not_disclose_configuration_or_signed_urls(monkeypatch, timeout):
    private = 'private-config-and-signed-object-url'
    def run(args, **kwargs):
        assert kwargs['timeout'] == 30
        if timeout:
            raise subprocess.TimeoutExpired(args, 30, stderr=private)
        return SimpleNamespace(returncode=1, stderr=private)
    monkeypatch.setattr(storage.subprocess, 'run', run)
    with pytest.raises(RuntimeError) as error:
        storage.checked(['docker', 'create', private])
    assert private not in str(error.value)
