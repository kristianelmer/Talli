"""Independent recovery proves its source boundary and removes only new targets."""
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
import rf1086_identity_restore as identity

DB = {'Id': 'a' * 64, 'Image': 'sha256:' + 'b' * 64,
      'NetworkSettings': {'Networks': {'supabase_network_tallig9931': {}}}}
AUTH = {'Id': 'c' * 64, 'Name': '/supabase_auth_tallig9931', 'Image': 'sha256:' + 'd' * 64,
        'State': {'Running': True}, 'NetworkSettings': DB['NetworkSettings'],
        'Config': {'Env': ['GOTRUE_DB_DATABASE_URL=postgresql://supabase_auth_admin:local@supabase_db_tallig9931:5432/postgres',
                           'GOTRUE_JWT_SECRET=local-only', 'GOTRUE_JWT_KEYS=[]']}}
ENV = dict(item.split('=', 1) for item in AUTH['Config']['Env'])
SOURCE_URL = 'postgresql://postgres:local@127.0.0.1:55001/postgres'


@pytest.mark.parametrize('fault', [None, 'foreign_database', 'foreign_auth', 'foreign_auth_database',
                                  'foreign_gateway', 'mutable_image', 'network', 'query_override'])
def test_only_exact_local_owned_identity_sources(tmp_path, monkeypatch, fault):
    (tmp_path / 'supabase').mkdir()
    (tmp_path / 'supabase/config.toml').write_text('project_id="tallig9931"\n[api]\nport=55000\n')
    monkeypatch.setenv('SUPABASE_URL', 'http://127.0.0.1:55000')
    db, auth = deepcopy(DB), deepcopy(AUTH)
    gateway = {'Name': '/supabase_kong_tallig9931', 'State': {'Running': True}, 'NetworkSettings': {
        'Networks': {'supabase_network_tallig9931': {}},
        'Ports': {'8000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '55000'}]}}}
    if fault == 'foreign_database': db['Id'] = 'e' * 64
    if fault == 'foreign_auth': auth['Name'] = '/another-auth'
    if fault == 'foreign_auth_database': auth['Config']['Env'][0] = auth['Config']['Env'][0].replace('supabase_db_tallig9931', 'hosted.example')
    if fault == 'foreign_gateway': gateway['NetworkSettings']['Ports']['8000/tcp'][0]['HostPort'] = '55002'
    if fault == 'mutable_image': db['Image'] = 'postgres:latest'
    if fault == 'network': auth['NetworkSettings']['Networks'] = {'some-other-network': {}}
    if fault == 'query_override': auth['Config']['Env'][0] += '?host=remote'
    observed = []
    boundary = SimpleNamespace(owned_source=lambda *_: ('a' * 64, 'postgres'),
        verify_source_session=lambda *args: observed.append(args),
        inspect_container=lambda name: auth if name.startswith('supabase_auth') else gateway if name.startswith('supabase_kong') else db)
    if fault:
        with pytest.raises(ValueError): identity.owned_identity_source(tmp_path, SOURCE_URL, boundary)
    else:
        assert identity.owned_identity_source(tmp_path, SOURCE_URL, boundary) == (db, auth, ENV)
    assert observed == [(SOURCE_URL, 'a' * 64)]


def test_auth_target_copies_signing_configuration_but_cannot_reach_provider_hooks():
    source = ENV | {'GOTRUE_HOOK_SEND_EMAIL_URI': 'https://paid.invalid', 'GOTRUE_SMTP_HOST': 'external.invalid'}
    host = 'rf193_identity_db_' + 'e' * 32
    env = identity.auth_environment(source, host)
    assert env['GOTRUE_DB_DATABASE_URL'] == 'postgresql://supabase_auth_admin:local@' + host + ':5432/postgres'
    assert env['GOTRUE_JWT_SECRET'] == source['GOTRUE_JWT_SECRET']
    assert env['GOTRUE_DISABLE_SIGNUP'] == 'true'
    assert not any('HOOK' in key or 'SMTP' in key for key in env)
    with pytest.raises(ValueError): identity.auth_environment(source, 'source')
    with pytest.raises(ValueError): identity.auth_environment(source | {'GOTRUE_JWT_SECRET': 'secret\nextra=value'}, host)


@pytest.mark.parametrize('failure', [None, 'network', 'volume', 'database_create', 'database_start', 'roles', 'restore', 'catalog', 'auth_create', 'auth_start', 'body', 'source_changed'])
def test_fresh_cluster_cleanup_is_pinned_and_source_stays_untouched(tmp_path, monkeypatch, failure):
    (tmp_path / 'supabase').mkdir()
    (tmp_path / 'supabase/config.toml').write_text('project_id="tallig9931"\n')
    calls, resources = [], {}
    target, target_auth = 'e' * 64, 'f' * 64
    monkeypatch.setattr(identity, 'owned_identity_source', lambda *_: (DB, AUTH, ENV))
    monkeypatch.setattr(identity, 'verify_target_session', lambda *_: None)
    monkeypatch.setattr(identity, 'verify_target_auth', lambda *_: None)
    counts = {'source': 0}
    def fingerprint(container, **kwargs):
        if container == DB['Id']:
            counts['source'] += 1
            return {'same': counts['source']} if failure == 'source_changed' else {'same': 1}
        return {'same': 2 if failure == 'catalog' else 1}
    monkeypatch.setattr(identity, 'fingerprint', fingerprint)
    monkeypatch.setattr(identity, 'source_query', lambda _, statement: b'pg_stat_statements' if statement.startswith('show ') else b'1')
    monkeypatch.setattr(identity, 'query', lambda *_, **__: b'2')
    def checked(args, **kwargs):
        calls.append(args)
        if args[1:3] == ['network', 'create']:
            if failure == 'network': raise RuntimeError('fixture network')
            resources['network'] = {'Id': '1' * 64, 'Name': args[-1], 'Internal': True, 'Labels': {identity.LABEL: args[-2].split('=')[1]}}
            return SimpleNamespace(stdout=b'1' * 64)
        if args[1:3] == ['network', 'inspect']: return SimpleNamespace(stdout=json.dumps([resources['network']]).encode())
        if args[1:3] == ['volume', 'create']:
            if failure == 'volume': raise RuntimeError('fixture volume')
            resources['volume'] = {'Name': args[-1], 'Labels': {identity.LABEL: args[-2].split('=')[1]}}
        if args[1:3] == ['volume', 'inspect']: return SimpleNamespace(stdout=json.dumps([resources['volume']]).encode())
        if 'pg_dumpall' in args: kwargs['stdout'].write(b'CREATE ROLE supabase_admin;\nALTER ROLE supabase_admin WITH SUPERUSER;\n')
        if args[1] == 'create':
            service = 'auth' if '--env-file' in args else 'database'
            if failure == service + '_create': raise RuntimeError('fixture ' + failure)
            if service == 'auth':
                path = Path(args[args.index('--env-file') + 1])
                assert path.stat().st_mode & 0o777 == 0o600
                assert 'rf193_identity_db_' in path.read_text()
            return SimpleNamespace(stdout=(target_auth if service == 'auth' else target).encode())
        if args[1] == 'start' and failure == ('auth_start' if args[-1] == target_auth else 'database_start'):
            raise RuntimeError('fixture ' + failure)
        if args[1] == 'exec' and 'psql' in args:
            assert b'CREATE ROLE supabase_admin;' not in kwargs['input']
            assert b'ALTER ROLE supabase_admin WITH SUPERUSER;' in kwargs['input']
            if failure == 'roles': raise RuntimeError('fixture roles')
        if args[1] == 'exec' and 'pg_restore' in args:
            assert args[3] == target and '--no-owner' not in args and '--no-acl' not in args
            assert '--create' in args and args[-1] == 'template1'
            if failure == 'restore': raise RuntimeError('fixture restore')
        return SimpleNamespace(stdout=b'')
    monkeypatch.setattr(identity, 'checked', checked)
    monkeypatch.setattr(identity.subprocess, 'run', lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
    @contextmanager
    def gateway(port):
        assert port == 55102
        yield 'http://127.0.0.1:55103'
    monkeypatch.setattr(identity, 'auth_gateway', gateway)
    class Client:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def get(self, _): return SimpleNamespace(status_code=200)
    monkeypatch.setattr(identity.httpx, 'Client', Client)
    def inspect(container):
        if container.startswith('supabase_storage_'): return {'Config': {'Env': ['SERVICE_KEY=private-local-service']}}
        port = '5432' if container == target else '9999'
        return {'NetworkSettings': {'Ports': {port + '/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '55101' if container == target else '55102'}]}}}
    boundary = SimpleNamespace(inspect_container=inspect)
    def run():
        with identity.restored_identity(SOURCE_URL, tmp_path, boundary) as result:
            assert result.auth_url == 'http://127.0.0.1:55103'
            assert 'port=55101' in result.database_url
            assert result.proof['independentClusterRestored']
            if failure == 'body': raise RuntimeError('fixture body')
    if failure:
        with pytest.raises((RuntimeError, ValueError)): run()
    else: run()
    removed = [args[-1] for args in calls if args[1:3] == ['rm', '-f']]
    expected = [] if failure in ('network', 'volume', 'database_create') else [target]
    if failure not in ('network', 'volume', 'database_create', 'database_start', 'roles', 'restore', 'catalog', 'auth_create'):
        expected.insert(0, target_auth)
    assert removed == expected
    assert all(DB['Id'] not in command for command in calls if command[1] in ('rm', 'start', 'create'))
    assert [args[-1] for args in calls if args[1:3] == ['volume', 'rm']] == ([] if failure in ('network', 'volume') else [resources['volume']['Name']])
    assert [args[-1] for args in calls if args[1:3] == ['network', 'rm']] == ([] if failure == 'network' else ['1' * 64])


@pytest.mark.parametrize('timeout', [False, True])
def test_private_configuration_never_escapes_command_failure(monkeypatch, timeout):
    private = 'private-password-hash-or-auth-key'
    def fail(*args, **kwargs):
        if timeout: raise subprocess.TimeoutExpired(args[0], 90, stderr=private.encode())
        return SimpleNamespace(returncode=1, stderr=private.encode())
    monkeypatch.setattr(identity.subprocess, 'run', fail)
    with pytest.raises(RuntimeError) as error: identity.checked(['docker', 'exec', private])
    assert private not in str(error.value)


@pytest.mark.parametrize('port', ['22', '65536', '123\nsecret', 'abc'])
def test_explicit_tunnel_ports_fail_closed(monkeypatch, port):
    monkeypatch.setenv('TALLI_RF_IDENTITY_AUTH_PORT', port)
    with pytest.raises(ValueError): identity.published_port('AUTH', 9999)


@pytest.mark.parametrize('observed', [b'1\n', b'0\n'])
def test_recovered_host_connection_must_be_visible_inside_pinned_target(monkeypatch, observed):
    from contextlib import contextmanager
    markers = []
    @contextmanager
    def connect(url, application_name):
        assert url == 'owned-target-url'
        markers.append(application_name)
        yield SimpleNamespace(execute=lambda _: SimpleNamespace(fetchone=lambda: (12345,)))
    monkeypatch.setattr(identity.psycopg, 'connect', connect)
    def query(container, statement, user):
        assert container == 'pinned-new-target' and user == 'supabase_admin'
        assert 'pid=12345' in statement and markers[0] in statement
        return observed
    monkeypatch.setattr(identity, 'query', query)
    if observed.strip() == b'1': identity.verify_target_session('owned-target-url', 'pinned-new-target', 'supabase_admin')
    else:
        with pytest.raises(ValueError, match='newly created target'):
            identity.verify_target_session('owned-target-url', 'pinned-new-target', 'supabase_admin')


@pytest.mark.parametrize('correct_target', [True, False])
def test_auth_http_endpoint_must_return_nonce_from_exact_new_database_and_probe_is_restored(monkeypatch, correct_target):
    from contextlib import contextmanager
    import base64
    actor = '11111111-1111-4111-8111-111111111111'
    payload = base64.urlsafe_b64encode(json.dumps({'sub': actor}).encode()).decode().rstrip('=')
    token = 'header.' + payload + '.signature'
    monkeypatch.setenv('TALLI_RF_RESTORE_OWNER_TOKEN', token)
    original, current, writes = {'provider': 'email'}, {'provider': 'email'}, []
    def execute(statement, parameters):
        if statement.startswith('select '): return SimpleNamespace(fetchone=lambda: (original,))
        assert parameters[1] == actor
        current.clear()
        current.update(json.loads(parameters[0]))
        writes.append(dict(current))
    @contextmanager
    def connect(url):
        assert url == 'exact-new-target'
        yield SimpleNamespace(execute=execute)
    monkeypatch.setattr(identity.psycopg, 'connect', connect)
    class Client:
        def __init__(self, **_): pass
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def get(self, url, headers):
            assert url == 'http://127.0.0.1:55103/auth/v1/user' and headers == {'Authorization': 'Bearer ' + token}
            return SimpleNamespace(status_code=200, json=lambda: {'id': actor, 'app_metadata': dict(current) if correct_target else original})
    monkeypatch.setattr(identity.httpx, 'Client', Client)
    if correct_target: identity.verify_target_auth('exact-new-target', 'http://127.0.0.1:55103')
    else:
        with pytest.raises(ValueError, match='new target database'):
            identity.verify_target_auth('exact-new-target', 'http://127.0.0.1:55103')
    assert current == original and len(writes) == 2
    assert writes[0]['rf193_identity_recovery_probe'] and writes[1] == original
