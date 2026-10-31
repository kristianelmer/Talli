"""Operator seam tests: identity, native framing, unknown outcomes and custody."""
from contextlib import contextmanager
from hashlib import sha256
import base64
import json
import shutil
from types import SimpleNamespace

import httpx
import pytest

from talli_backend.adapters import hosted_backup_recovery as recovery
from talli_backend.adapters import hosted_recovery_operator as command
from talli_backend.adapters.hosted_recovery_capture import ManagedCapture, digest, encoded
from talli_backend.adapters.hosted_recovery_sql import (
    LogicalProgram, compile_program, copy_parts, execute_data, role_program, sequence_payload, toc_entries,
)
from talli_backend.adapters.hosted_recovery_target import (
    HostedDesignation, SupabaseRecoveryTarget, connection_settings,
)

SOURCE = 'a' * 20
TARGET = 'b' * 20
ORG = 'c' * 20
EMPTY = sha256(b'').hexdigest()


def private(path, value):
    path.write_bytes(value if isinstance(value, bytes) else encoded(value))
    path.chmod(0o600)
    return path


@pytest.fixture
def snapshot(tmp_path):
    directory = tmp_path / 'capture'; directory.mkdir(mode=0o700)
    custom = ['restore_owner', False, False, False, False, False, False, False, -1, None, None]
    runtime = ['restore_runtime', False, False, False, False, True, False, False, -1, None, None]
    roles = {'roles': [['postgres', False, True, True, True, True, False, True, -1, None, None],
        custom, runtime], 'memberships': [['restore_owner', 'postgres', 'postgres', False, False, False]]}
    catalog = {'functions': [], 'constraints': [], 'indexes': [], 'policies': [], 'rls': []}
    files = {'database.dump': b'PGDMPsynthetic native bytes', 'roles.sql': b'-- no role hashes\n',
        'contents.list': b'; independently held native inventory\n',
        'source-profile.json': encoded({'projectRef': SOURCE,
            'facts': [170011, 'i', 'UTF8', 'en_US.UTF-8', 'en_US.UTF-8', 'en-US', 'postgres'],
            'tables': [['public', 'items']], 'extensions': [], 'capturedAt': '2026-10-30T00:00:00Z'}),
        'source-tables.private.json': encoded({'public.items': {'rows': 0, 'sha256': EMPTY}}),
        'source-catalog.private.json': encoded(catalog), 'source-roles.private.json': encoded(roles),
        'object-manifest.private.json': encoded([])}
    for name, value in files.items(): private(directory / name, value)
    header = private(tmp_path / 'header.json', {'format': 'talli-designated-hosted-capture-v1',
        'projectRef': SOURCE, 'pins': {name: {'bytes': len(raw), 'sha256': digest(raw)} for name, raw in files.items()}})
    access = private(tmp_path / 'access.json', {'sourceProject': SOURCE,
        'sourceCatalogStillExactToOriginal': True, 'access': {'schemas': [['public', 'postgres', []]],
            'relations': [['public', 'items', 'r', 'postgres', []]]},
        'databaseAccess': {'database': 'postgres', 'owner': 'postgres', 'grants': []}})
    arguments = {'directory': directory, 'header': header, 'header_sha256': digest(header.read_bytes()),
        'access': access, 'access_sha256': digest(access.read_bytes())}
    return arguments


def test_capture_rechecks_bound_members_and_rejects_password_hashes(snapshot):
    capture = ManagedCapture.open(**snapshot)
    assert capture.source_project == SOURCE and capture.schemas == {'public'}
    private(capture.directory / 'roles.sql', b'ALTER ROLE recovered PASSWORD \'private\';')
    with pytest.raises(ValueError, match='member_changed'): capture.read('roles.sql')
    with pytest.raises(ValueError, match='member_changed'): ManagedCapture.open(**snapshot)


def test_capture_rejects_replaced_access_or_duplicate_header_keys(snapshot):
    private(snapshot['access'], b'{}')
    with pytest.raises(ValueError, match='access_changed'): ManagedCapture.open(**snapshot)
    raw = b'{"format":1,"format":2}'
    private(snapshot['header'], raw); snapshot['header_sha256'] = digest(raw)
    with pytest.raises(ValueError, match='duplicate_key'): ManagedCapture.open(**snapshot)


def test_capture_rejects_symlinked_member_even_with_same_bytes(snapshot, tmp_path):
    member = snapshot['directory'] / 'roles.sql'; raw = member.read_bytes(); member.unlink()
    member.symlink_to(private(tmp_path / 'outside', raw))
    with pytest.raises(ValueError, match='private_path'): ManagedCapture.open(**snapshot)


def test_native_copy_framing_keeps_consecutive_empty_tables_and_escaped_rows():
    raw = (b'\\restrict ABC\nSET search_path=\'\';\nCOPY public.empty (id) FROM stdin;\n\\.\n'
        b'COPY auth.refresh_tokens (id,token) FROM stdin;\n132\tvalue\\nnot-a-new-row\\tfield\n\\.\n'
        b'COPY storage.buckets_vectors (id) FROM stdin;\n\\.\n'
        b"SELECT pg_catalog.setval('auth.refresh_tokens_id_seq', 132, true);\n\\unrestrict ABC\n")
    parts = list(copy_parts(raw)); copies = [v for kind, v in parts if kind == 'copy']
    assert [v[0] for v in copies] == ['public.empty', 'auth.refresh_tokens', 'storage.buckets_vectors']
    assert copies[0][2] == copies[2][2] == b''
    assert copies[1][2] == b'132\tvalue\\nnot-a-new-row\\tfield\n'
    assert sequence_payload(raw) == ((['auth', 'refresh_tokens_id_seq'], 132, True),)
    with pytest.raises(ValueError, match='unterminated'):
        list(copy_parts(b'COPY public.items (id) FROM stdin;\n1\n'))


def test_empty_provider_vector_copy_is_not_sent_to_database():
    calls = []
    class DB:
        def execute(self, text, **kwargs):
            calls.append(text)
            return SimpleNamespace(nextset=lambda: False)
        def cursor(self): raise AssertionError('empty COPY must not open a provider COPY writer')
    execute_data(DB(), b'COPY storage.buckets_vectors (id) FROM stdin;\n\\.\n',
        {'storage.buckets_vectors': {'rows': 0, 'sha256': EMPTY}})
    assert not calls


def test_native_toc_retains_schema_and_schema_acl_entries():
    entries = toc_entries('1; 2615 1 SCHEMA - ledger restore_owner\n'
        '2; 0 0 ACL - SCHEMA ledger restore_owner\n'
        '3; 1255 2 FUNCTION ledger read(id uuid) restore_owner\n')
    assert [(e.kind, e.schema, e.tag) for e in entries] == [
        ('SCHEMA', '-', 'ledger'), ('ACL', '-', 'SCHEMA ledger'), ('FUNCTION', 'ledger', 'read(id uuid)')]


def test_role_setup_does_not_grant_admin_back_to_own_grantor(snapshot):
    roles, final = role_program(ManagedCapture.open(**snapshot))
    assert b'grant "restore_owner" to postgres with inherit true, set true;' in roles
    assert b'admin true' not in roles and b' nologin ' in roles
    assert b'with inherit false, set false' in final and b'admin true' not in final


def credentials(tmp_path, designation):
    payload = base64.urlsafe_b64encode(encoded({'ref': designation.project, 'role': 'service_role'})).decode().rstrip('=')
    return private(tmp_path / 'credentials.json', {'project': designation.project,
        'databaseUrl': 'postgresql://postgres.' + designation.project + ':private@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require',
        'managementToken': 'private-management-token', 'serviceRoleKey': 'header.' + payload + '.signature'})


@pytest.fixture
def provider(tmp_path):
    designation = HostedDesignation(TARGET, ORG, 'recovery-test', 'eu-west-1')
    ca = private(tmp_path / 'ca.crt', b'public official certificate fixture')
    return SupabaseRecoveryTarget(designation=designation, credentials=credentials(tmp_path, designation),
        ca=ca, ca_sha256=digest(ca.read_bytes()))


@pytest.mark.parametrize('changed', [
    'postgresql://postgres.' + SOURCE + ':private@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require',
    'postgresql://postgres:private@db.' + SOURCE + '.supabase.co:5432/postgres?sslmode=require',
    'postgresql://postgres.' + TARGET + ':private@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require&host=elsewhere',
    'postgresql://postgres.' + TARGET + ':private@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=disable',
])
def test_dsn_cannot_substitute_source_host_user_tls_or_override(provider, tmp_path, changed):
    ca = private(tmp_path / 'certificate', b'fixture')
    with pytest.raises(ValueError, match='destination_mismatch'):
        connection_settings(changed, provider.designation, ca=ca, ca_sha256=digest(ca.read_bytes()))


def http_model(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr('talli_backend.adapters.hosted_recovery_target.httpx.Client',
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def test_provider_metadata_must_match_exact_designation_before_mutations(provider, monkeypatch):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={'id': TARGET, 'organization_id': 'd' * 20,
            'name': 'recovery-test', 'region': 'eu-west-1', 'status': 'ACTIVE_HEALTHY'})
    http_model(monkeypatch, handler)
    with pytest.raises(ValueError, match='designation_changed'): provider.validate(source_project=SOURCE)
    assert len(seen) == 1 and seen[0].method == 'GET'
    assert str(seen[0].url) == 'https://api.supabase.com/v1/projects/' + TARGET


def test_unknown_upload_outcome_resumes_by_readback_without_duplicate_post(provider, monkeypatch):
    body = b'private original'; stored = {}; posts = []
    def handler(request):
        path = request.url.path
        if path.startswith('/storage/v1/bucket/'):
            return httpx.Response(200, json={'id': 'company-documents', 'public': False})
        if '/object/public/' in path:
            assert 'authorization' not in request.headers
            return httpx.Response(404)
        if request.method == 'POST':
            assert request.headers['x-upsert'] == 'false'
            posts.append(path); stored[path] = request.content
            raise httpx.ReadTimeout('private transport diagnostic must not be printed')
        return httpx.Response(200, content=stored[path]) if path in stored else httpx.Response(404)
    http_model(monkeypatch, handler)
    obj = {'bucket': 'company-documents', 'name': 'company/2025/original.pdf',
        'bytes': len(body), 'sha256': digest(body), 'contentType': 'application/pdf'}
    with pytest.raises(httpx.ReadTimeout): provider.restore_object(obj, body)
    assert provider.restore_object(obj, body)['servedExact'] and len(posts) == 1


@pytest.mark.parametrize('public,existing', [(True, b'original'), (False, b'wrong bytes')])
def test_public_bucket_or_different_existing_object_never_overwrites(provider, monkeypatch, public, existing):
    calls = []
    def handler(request):
        calls.append(request.method)
        if '/bucket/' in request.url.path:
            return httpx.Response(200, json={'id': 'company-documents', 'public': public})
        return httpx.Response(200, content=existing)
    http_model(monkeypatch, handler)
    obj = {'bucket': 'company-documents', 'name': 'original', 'bytes': 8, 'sha256': digest(b'original')}
    with pytest.raises(ValueError): provider.restore_object(obj, b'original')
    assert 'POST' not in calls


class Cursor:
    def __init__(self, rows=()): self.rows = rows
    def fetchone(self): return self.rows[0]
    def fetchall(self): return list(self.rows)
    def __iter__(self): return iter(self.rows)
    def nextset(self): return False


class DatabaseModel:
    """Transaction/marker fault model; real SQL regressions run separately."""
    def __init__(self, capture):
        self.capture, self.marker, self.pending = capture, None, None
        self.lose_commit_response = False; self.ddl = 0; self.calls = []
    def execute(self, text, params=None, **kwargs):
        self.calls.append(text)
        if 'pg_try_advisory' in text: return Cursor([(True,)])
        if 'to_regclass' in text: return Cursor([('marker' if self.marker else None,)])
        if text.startswith('select id::text,plan_sha'): return Cursor([self.marker] if self.marker else [])
        if 'to_regnamespace' in text: return Cursor([(None,)])
        if text.startswith("select current_setting('server_version_num')"):
            return Cursor([tuple(self.capture.profile['facts'])])
        if text.startswith('select e.extname'): return Cursor([])
        if text.startswith('select 1 from pg_constraint'): return Cursor([])
        if 'jsonb_build_object' in text and "'functions'" in text: return Cursor([(self.capture.catalog,)])
        if text.startswith('insert into _talli_recovery.attempt'):
            self.pending = (*params[:4], json.loads(params[4])); return Cursor()
        if 'select id from auth.users' in text: return Cursor([])
        if text.startswith('select row_to_json'): return Cursor([])
        if 'count(*)' in text: return Cursor([(0,)])
        if text == 'create original ddl;': self.ddl += 1
        return Cursor()
    def commit(self):
        if self.pending is not None: self.marker = self.pending; self.pending = None
        if self.lose_commit_response:
            self.lose_commit_response = False
            raise ConnectionError('private database URL must not be recorded')


class TargetModel:
    def __init__(self, capture):
        self.designation = HostedDesignation(TARGET, ORG, 'recovery-test', 'eu-west-1')
        self.db = DatabaseModel(capture); self.validations = 0
    def validate(self, **kwargs): self.validations += 1
    @contextmanager
    def database(self):
        try: yield self.db
        except BaseException:
            self.db.pending = None
            raise
    def restore_object(self, obj, raw): raise AssertionError('no objects in this fixture')


def operator(snapshot, tmp_path, monkeypatch):
    capture = ManagedCapture.open(**snapshot); target = TargetModel(capture)
    work = tmp_path / 'operator'; work.mkdir(mode=0o700)
    monkeypatch.setattr(recovery, 'NativeArchive', lambda *args, **kwargs: object())
    program = LogicalProgram(b'', b'', b'', b'create original ddl;', b'', b'', b'', b'', b'', b'', ())
    monkeypatch.setattr(recovery, 'compile_program', lambda *args: program)
    monkeypatch.setattr(recovery, 'restore_database_access', lambda *args: None)
    monkeypatch.setattr(recovery, 'restore_access', lambda *args: {'functions': 0})
    monkeypatch.setattr(recovery, 'verify_custom_roles', lambda *args: None)
    instance = recovery.HostedBackupRecovery(capture=capture, target=target, work=work, pg_restore='/pg_restore')
    return instance, target


def test_wrong_reviewed_plan_prevents_even_provider_validation(snapshot, tmp_path, monkeypatch):
    instance, target = operator(snapshot, tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='reviewed_plan'): instance.restore(expected_plan_sha256='0' * 64)
    assert target.validations == 0 and not target.db.calls


def test_lost_commit_response_is_reconciled_without_replaying_ddl(snapshot, tmp_path, monkeypatch):
    instance, target = operator(snapshot, tmp_path, monkeypatch); target.db.lose_commit_response = True
    with pytest.raises(ConnectionError): instance.restore(expected_plan_sha256=instance.plan_sha)
    assert target.db.marker is not None and target.db.ddl == 1
    state = instance.restore(expected_plan_sha256=instance.plan_sha)
    assert state['phase'] == 'verified_quarantined' and state['publicationAuthorized'] is False
    assert target.db.ddl == 1 and 'private database URL' not in (instance.work / 'state.json').read_text()


def test_containment_survives_capture_loss_and_is_repeatable(snapshot, tmp_path, monkeypatch):
    instance, target = operator(snapshot, tmp_path, monkeypatch)
    instance.restore(expected_plan_sha256=instance.plan_sha)
    shutil.rmtree(instance.capture.directory)
    clean = recovery.HostedBackupRecovery.for_containment(target=target, work=instance.work,
        expected_plan_sha256=instance.plan_sha)
    assert clean.contain(expected_plan_sha256=instance.plan_sha)['phase'] == 'contained'
    assert clean.contain(expected_plan_sha256=instance.plan_sha)['publicationAuthorized'] is False
    assert any('alter role "restore_runtime" nologin' in q for q in target.db.calls)


def test_swapped_marker_never_authorizes_reimport_or_cleanup(snapshot, tmp_path, monkeypatch):
    instance, target = operator(snapshot, tmp_path, monkeypatch)
    instance.restore(expected_plan_sha256=instance.plan_sha)
    target.db.marker = ('other-id', *target.db.marker[1:])
    with pytest.raises(ValueError, match='marker_changed'): instance.restore(expected_plan_sha256=instance.plan_sha)
    with pytest.raises(ValueError, match='marker_changed'): instance.contain(expected_plan_sha256=instance.plan_sha)
    assert target.db.ddl == 1


def test_cli_never_prints_transport_exception_secrets(monkeypatch, capsys):
    def failed(**kwargs): raise RuntimeError('postgresql://user:secret@host secret-service-key')
    monkeypatch.setattr(command, 'execute', failed)
    assert command.main(['inspect', '--config', '/private/config', '--expected-config-sha256', 'a' * 64]) == 1
    wire = capsys.readouterr().out
    assert 'secret' not in wire and json.loads(wire)['publicationAuthorized'] is False


def repin(snapshot, name, value):
    private(snapshot['directory'] / name, value)
    envelope = json.loads(snapshot['header'].read_bytes())
    raw = (snapshot['directory'] / name).read_bytes()
    envelope['pins'][name] = {'bytes': len(raw), 'sha256': digest(raw)}
    private(snapshot['header'], envelope)
    snapshot['header_sha256'] = digest(snapshot['header'].read_bytes())


@pytest.mark.parametrize('table,code', [
    ('vault.secrets', 'managed_key_transfer_required'),
    ('pgsodium.key', 'managed_key_transfer_required'),
    ('cron.job', 'background_provider_work_unsupported'),
    ('documents.local_native_disposition_targets', 'disposition_replay_adapter_required'),
])
def test_capture_obligations_cannot_be_reclassified_as_empty(snapshot, table, code):
    profile = json.loads((snapshot['directory'] / 'source-profile.json').read_bytes())
    profile['tables'].append(table.split('.'))
    rows = json.loads((snapshot['directory'] / 'source-tables.private.json').read_bytes())
    rows[table] = {'rows': 1, 'sha256': digest(b'captured original obligation')}
    repin(snapshot, 'source-profile.json', profile)
    repin(snapshot, 'source-tables.private.json', rows)
    with pytest.raises(ValueError, match=code):
        ManagedCapture.open(**snapshot)


def test_naive_capture_time_cannot_skip_fresh_destination_requirement(snapshot):
    profile = json.loads((snapshot['directory'] / 'source-profile.json').read_bytes())
    profile['capturedAt'] = '2026-10-30T00:00:00'
    repin(snapshot, 'source-profile.json', profile)
    with pytest.raises(ValueError, match='database_profile_invalid'):
        ManagedCapture.open(**snapshot)


@pytest.mark.parametrize('line,code', [
    ('1; 1255 1 PROCEDURE public execute_work() postgres\n', 'object_kind_unsupported'),
    ('1; 2620 1 TRIGGER auth users custom_hook postgres\n', 'managed_custom_trigger_unsupported'),
])
def test_unsupported_objects_stop_before_extracting_sql(snapshot, line, code):
    capture = ManagedCapture.open(**snapshot)
    archive = SimpleNamespace(entries=toc_entries(line))
    with pytest.raises(ValueError, match=code): compile_program(capture, archive)


def test_storage_transport_id_dependency_is_not_silently_adapted(snapshot):
    catalog = json.loads((snapshot['directory'] / 'source-catalog.private.json').read_bytes())
    catalog['constraints'] = [['public', 'items', 'object_fk',
        'FOREIGN KEY (id) REFERENCES storage.objects(id)']]
    repin(snapshot, 'source-catalog.private.json', catalog)
    capture = ManagedCapture.open(**snapshot)
    archive = SimpleNamespace(entries=toc_entries('1; 2615 1 SCHEMA - public postgres\n'))
    with pytest.raises(ValueError, match='transport_identity_dependency'):
        compile_program(capture, archive)


def test_provider_rejects_project_older_than_capture(provider, monkeypatch):
    def handler(request):
        return httpx.Response(200, json={'id': TARGET, 'organization_id': ORG,
            'name': 'recovery-test', 'region': 'eu-west-1', 'status': 'ACTIVE_HEALTHY',
            'created_at': '2026-10-29T00:00:00Z'})
    http_model(monkeypatch, handler)
    with pytest.raises(ValueError, match='fresh_project_required'):
        provider.validate(source_project=SOURCE, captured_at='2026-10-30T00:00:00Z')
