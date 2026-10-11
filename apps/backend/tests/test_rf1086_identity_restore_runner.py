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


@pytest.mark.parametrize('components', [
    ('roles',), ('catalog',), ('auth',), ('companyMemberships',),
    ('roles', 'catalog', 'auth', 'companyMemberships'),
])
def test_fingerprint_failure_names_only_fixed_components_without_values_or_foreign_keys(components):
    names = ('roles', 'catalog', 'auth', 'companyMemberships')
    expected = {name: 'source-private-password-hash-or-auth-row' for name in names}
    recovered = {name: 'target-private-password-hash-or-auth-row' if name in components
        else expected[name] for name in names}
    before, after = deepcopy(expected), deepcopy(recovered)
    diagnostic = identity._fingerprint_mismatch_components(expected, recovered)
    assert diagnostic == (','.join(components) or 'unclassified')
    assert 'private' not in diagnostic and 'SQL' not in diagnostic
    assert expected == before and recovered == after


@pytest.mark.parametrize('shape', ['extra-expected', 'extra-recovered', 'missing-expected',
    'missing-recovered', 'not-dict'])
def test_fingerprint_failure_with_unknown_shape_remains_finite_and_unclassified(shape):
    names = ('roles', 'catalog', 'auth', 'companyMemberships')
    expected = {name: 'source-private-password-hash-or-auth-row' for name in names}
    recovered = {name: 'target-private-password-hash-or-auth-row' for name in names}
    if shape == 'extra-expected': expected['private-key-name-or-SQL'] = 'private-key-value'
    if shape == 'extra-recovered': recovered['private-key-name-or-SQL'] = 'private-key-value'
    if shape == 'missing-expected': del expected['roles']
    if shape == 'missing-recovered': del recovered['roles']
    if shape == 'not-dict': recovered = ['private-key-name-or-SQL', 'private-key-value']
    before, after = deepcopy(expected), deepcopy(recovered)
    assert identity._fingerprint_mismatch_components(expected, recovered) == 'unclassified'
    assert expected == before and recovered == after


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


@pytest.mark.parametrize('failure', [None, 'fingerprint', 'preload', 'tempfile', 'roles_dump', 'database_dump', 'network', 'volume', 'database_create', 'database_start', 'roles', 'restore', 'catalog', 'catalog_unavailable', 'auth_create', 'auth_start', 'body', 'source_changed'])
def test_fresh_cluster_cleanup_is_pinned_and_source_stays_untouched(tmp_path, monkeypatch, capsys, failure):
    (tmp_path / 'supabase').mkdir()
    (tmp_path / 'supabase/config.toml').write_text('project_id="tallig9931"\n')
    calls, resources = [], {}
    target, target_auth = 'e' * 64, 'f' * 64
    monkeypatch.setattr(identity, 'owned_identity_source', lambda *_: (DB, AUTH, ENV))
    monkeypatch.setattr(identity, 'verify_target_session', lambda *_: None)
    monkeypatch.setattr(identity, 'verify_target_auth', lambda *_: None)
    counts = {'source': 0}
    captures = []
    semantic_calls = []
    def semantic_capture(source_catalog, target_catalog, **kwargs):
        assert source_catalog._raw is not None and target_catalog._raw is not None
        semantic_calls.append(kwargs)
    monkeypatch.setattr(identity, 'emit_catalog_semantics', semantic_capture, raising=False)
    catalog_failure = failure in ('catalog', 'catalog_unavailable')
    early_failure = failure in ('fingerprint', 'preload', 'tempfile', 'roles_dump', 'database_dump')
    def fingerprint(container, **kwargs):
        catalog = b'[]\n{"datacl":null}\n[]\n'
        if container != DB['Id'] and catalog_failure:
            catalog = b'[]\n{"datacl":["private-acl"]}\n[]\n'
        if capture := kwargs.get('catalog_capture'):
            captures.append(capture)
            capture.capture(b'private-malformed-catalog' if failure == 'catalog_unavailable' else catalog)
            if failure == 'fingerprint': raise RuntimeError('fixture fingerprint')
        result = dict.fromkeys(('roles', 'catalog', 'auth', 'companyMemberships'), 'same')
        if container == DB['Id']:
            counts['source'] += 1
            if failure == 'source_changed' and counts['source'] > 1: result['catalog'] = 'source-changed'
        elif catalog_failure: result['catalog'] = 'different'
        return result
    monkeypatch.setattr(identity, 'fingerprint', fingerprint)
    monkeypatch.setattr(identity, 'source_query', lambda _, statement: b'invalid;preload' if failure == 'preload' else b'pg_stat_statements' if statement.startswith('show ') else b'1')
    if failure == 'tempfile':
        def broken_tempfile(): raise RuntimeError('fixture tempfile')
        monkeypatch.setattr(identity.tempfile, 'TemporaryFile', broken_tempfile)
    monkeypatch.setattr(identity, 'query', lambda *_, **__: b'2')
    def checked(args, **kwargs):
        calls.append(args)
        if ('pg_dumpall' in args and failure == 'roles_dump') or ('pg_dump' in args and failure == 'database_dump'):
            raise RuntimeError('fixture ' + failure)
        if args[1:3] == ['network', 'create']:
            if failure == 'network': raise RuntimeError('fixture network')
            resources['network'] = {'Id': '1' * 64, 'Name': args[-1], 'Internal': True, 'Labels': {identity.LABEL: args[-2].split('=')[1]}}
            return SimpleNamespace(stdout=b'1' * 64)
        if args[1:3] == ['network', 'inspect']: return SimpleNamespace(stdout=json.dumps([resources['network']]).encode())
        if args[1:3] == ['volume', 'create']:
            if failure == 'volume': raise RuntimeError('fixture volume')
            resources['volume'] = {'Name': args[-1], 'Labels': {identity.LABEL: args[-2].split('=')[1]}}
        if args[1:3] == ['volume', 'inspect']: return SimpleNamespace(stdout=json.dumps([resources['volume']]).encode())
        if args[1:3] == ['container', 'inspect']:
            assert args[-1] == target
            return SimpleNamespace(stdout=json.dumps([resources['database']]).encode())
        if 'pg_dumpall' in args: kwargs['stdout'].write(b'CREATE ROLE supabase_admin;\nALTER ROLE supabase_admin WITH SUPERUSER;\n')
        if args[1] == 'create':
            service = 'auth' if '--env-file' in args else 'database'
            if failure == service + '_create': raise RuntimeError('fixture ' + failure)
            if service == 'auth':
                path = Path(args[args.index('--env-file') + 1])
                assert path.stat().st_mode & 0o777 == 0o600
                assert 'rf193_identity_db_' in path.read_text()
            else:
                resources['database'] = {'Id': target, 'Name': '/' + args[args.index('--name') + 1],
                    'Image': DB['Image'], 'Config': {'Labels': {identity.LABEL: args[args.index('--label') + 1].split('=')[1]}},
                    'State': {'Running': True}}
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
        with pytest.raises((RuntimeError, ValueError)) as error: run()
        if catalog_failure:
            assert str(error.value) == 'Independent recovery roles, ownership, ACLs or Auth rows differ; components=catalog'
        if early_failure:
            assert str(error.value) == ('Invalid local preload configuration' if failure == 'preload' else 'fixture ' + failure)
    else: run()
    output = capsys.readouterr().err
    if catalog_failure:
        line, = output.splitlines()
        assert line.startswith('owned_identity_catalog_difference ')
        diagnostic = json.loads(line.removeprefix('owned_identity_catalog_difference '))
        assert diagnostic['status'] == ('unavailable' if failure == 'catalog_unavailable' else 'different')
        if failure == 'catalog':
            assert diagnostic['details'][0]['fields'] == [{'field': 'datacl', 'change': 'source-null'}]
        assert 'private-' not in output
    else:
        assert output == ''
    assert all(capture._raw is None for capture in captures)
    assert len(semantic_calls) == int(catalog_failure)
    if semantic_calls:
        assert semantic_calls[0]['source'] == DB['Id']
        assert semantic_calls[0]['target'] == target
        assert semantic_calls[0]['image'] == DB['Image']
    if early_failure:
        assert resources == {}
        assert all(command[1] == 'exec' and any(tool in command for tool in ('pg_dumpall', 'pg_dump')) for command in calls)
        return
    removed = [args[-1] for args in calls if args[1:3] == ['rm', '-f']]
    expected = [] if failure in ('network', 'volume', 'database_create') else [target]
    if failure not in ('network', 'volume', 'database_create', 'database_start', 'roles', 'restore', 'catalog', 'catalog_unavailable', 'auth_create'):
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


@pytest.mark.parametrize(('diagnostic', 'message'), [
    ('database_in_use', b'database "postgres" is being accessed by other users'),
    ('extension_unavailable', b'could not open extension control file "/private/extension.control"'),
    ('permission_denied', b'permission denied for schema private_schema'),
    ('missing_role', b'role "private_role" does not exist'),
    ('missing_schema', b'schema "private_schema" does not exist'),
    ('missing_relation', b'relation "private_schema.private_table" does not exist'),
    ('object_already_exists', b'relation "private_table" already exists'),
    ('unclassified', b'private-unknown-error'),
])
def test_restore_failure_has_safe_diagnostic_without_rendering_stderr(monkeypatch, diagnostic, message):
    import hashlib
    private = b'private-password-hash-or-auth-key'
    stderr = b'pg_restore: error: could not execute query: ERROR:  ' + message + b'\nCommand was: ' + private
    monkeypatch.setattr(identity.subprocess, 'run', lambda *_args, **_kwargs:
        SimpleNamespace(returncode=1, stderr=stderr))
    with pytest.raises(RuntimeError) as error:
        identity.checked(['docker', 'exec', '-i', 'owned-target', 'pg_restore', '--create'])
    rendered = str(error.value)
    assert 'pg_restore diagnostic=' + diagnostic in rendered
    assert 'stderr_bytes=' + str(len(stderr)) in rendered
    assert 'stderr_sha256=' + hashlib.sha256(stderr).hexdigest() in rendered
    assert private.decode() not in rendered and message.decode() not in rendered


@pytest.mark.parametrize('multiline', [False, True])
def test_restore_diagnostic_ignores_sql_payload_that_looks_like_an_error(monkeypatch, multiline):
    stderr = (b'pg_restore: error: could not execute query: ERROR:  private-unknown-error\n'
              b'Command was: INSERT INTO secret VALUES (\'permission denied\', '
              b'\'database "postgres" is being accessed by other users\');')
    if multiline:
        stderr = (b'pg_restore: error: could not execute query: ERROR:  private-unknown-error\n'
                  b"Command was: INSERT INTO secret VALUES ('\npg_restore: error: permission denied\n');")
    monkeypatch.setattr(identity.subprocess, 'run', lambda *_args, **_kwargs:
        SimpleNamespace(returncode=1, stderr=stderr))
    with pytest.raises(RuntimeError, match='pg_restore diagnostic=unclassified'):
        identity.checked(['docker', 'exec', '-i', 'owned-target', 'pg_restore', '--create'])


@pytest.mark.parametrize('prefix', [
    b'pg_restore: error: private-unknown-first-error\n',
    b'Command was: INSERT INTO secret VALUES (\'\n',
])
def test_restore_diagnostic_does_not_scan_past_first_error_or_sql_boundary(monkeypatch, prefix):
    stderr = prefix + b'pg_restore: error: permission denied\n'
    monkeypatch.setattr(identity.subprocess, 'run', lambda *_args, **_kwargs:
        SimpleNamespace(returncode=1, stderr=stderr))
    with pytest.raises(RuntimeError, match='pg_restore diagnostic=unclassified'):
        identity.checked(['docker', 'exec', '-i', 'owned-target', 'pg_restore', '--create'])


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


@pytest.mark.parametrize('fault', [None, 'source_id', 'target_id', 'same_container', 'nonce', 'name',
    'image', 'bootstrap', 'observed_id', 'observed_name', 'observed_image', 'observed_nonce',
    'stopped', 'same_cluster', 'invalid_source_system', 'invalid_target_system'])
def test_default_database_preparation_requires_exact_new_owned_cluster(monkeypatch, fault):
    source, target, nonce = 'a'*64, 'e'*64, '1'*32
    name, image, bootstrap = 'rf193_identity_db_'+nonce, DB['Image'], 'supabase_admin'
    observed = dict(Id=target, Name='/'+name, Image=image,
        Config=dict(Labels={identity.LABEL:nonce}), State=dict(Running=True))
    if fault == 'source_id': source = 'invalid'
    if fault == 'target_id': target = 'invalid'
    if fault == 'same_container': target = source
    if fault == 'nonce': nonce = 'invalid'
    if fault == 'name': name = 'supabase_db_tallig9931'
    if fault == 'image': image = 'postgres:latest'
    if fault == 'bootstrap': bootstrap = 'another-role'
    if fault == 'observed_id': observed['Id'] = source
    if fault == 'observed_name': observed['Name'] = '/supabase_db_tallig9931'
    if fault == 'observed_image': observed['Image'] = 'sha256:'+'c'*64
    if fault == 'observed_nonce': observed['Config']['Labels'][identity.LABEL] = '2'*32
    if fault == 'stopped': observed['State']['Running'] = False
    mutations, reads = [], []
    monkeypatch.setattr(identity, 'inspect_resource', lambda kind, reference: observed)
    def source_query(container, statement):
        reads.append(('source',container,statement))
        return b'invalid' if fault == 'invalid_source_system' else b'1\n'
    def target_query(container, statement, *, user, database):
        assert container == 'e'*64 and user == 'supabase_admin' and database == 'template1'
        if statement == 'select system_identifier from pg_control_system();':
            reads.append(('target',container,statement))
            return b'invalid' if fault == 'invalid_target_system' else b'1\n' if fault == 'same_cluster' else b'2\n'
        mutations.append((container,statement,user,database));return b''
    monkeypatch.setattr(identity, 'source_query', source_query)
    monkeypatch.setattr(identity, 'query', target_query)
    if fault:
        with pytest.raises(ValueError): identity.prepare_new_target_database(source,target,name,nonce,image,bootstrap)
        assert mutations == []
    else:
        identity.prepare_new_target_database(source,target,name,nonce,image,bootstrap)
        assert mutations == [('e'*64,'drop database postgres with (force);','supabase_admin','template1')]
        assert [kind for kind,*_ in reads] == ['source','target']


def test_default_database_preparation_failure_propagates_without_restore_or_retry(monkeypatch):
    nonce, target = '1'*32, 'e'*64
    monkeypatch.setattr(identity, 'inspect_resource', lambda *_: dict(Id=target,Name='/rf193_identity_db_'+nonce,
        Image=DB['Image'],Config=dict(Labels={identity.LABEL:nonce}),State=dict(Running=True)))
    monkeypatch.setattr(identity, 'source_query', lambda *_: b'1')
    calls=[]
    def query(container,statement,**kwargs):
        calls.append(statement)
        if statement.startswith('select '): return b'2'
        raise RuntimeError('Owned identity recovery command failed: exec')
    monkeypatch.setattr(identity,'query',query)
    with pytest.raises(RuntimeError): identity.prepare_new_target_database('a'*64,target,'rf193_identity_db_'+nonce,nonce,DB['Image'],'supabase_admin')
    assert calls == ['select system_identifier from pg_control_system();','drop database postgres with (force);']
