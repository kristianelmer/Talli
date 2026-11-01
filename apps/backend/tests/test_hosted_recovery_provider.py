"""Provider state is an exact inert prerequisite, never a managed write waiver."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from talli_backend.adapters.hosted_backup_recovery import HostedBackupRecovery
from talli_backend.adapters.hosted_recovery_capture import ManagedCapture, digest
from talli_backend.adapters import hosted_recovery_provider as provider
from talli_backend.adapters.hosted_recovery_sql import compile_program, toc_entries
from test_hosted_backup_recovery import snapshot


@pytest.fixture
def populated(snapshot):
    base = ManagedCapture.open(**snapshot)
    tables = sorted(provider.TABLES)
    counts = {'_realtime.extensions': 1, '_realtime.schema_migrations': 31,
        '_realtime.tenants': 1, 'pgboss_v10.version': 1,
        'supabase_functions.migrations': 2, 'supabase_migrations.schema_migrations': 157}
    rows = {**base.rows, **{name: {'rows': counts.get(name, 0),
        'sha256': digest(name.encode()) if counts.get(name, 0) else digest(b'')}
        for name in tables}}
    structure = {key: [] for key in ('relations', 'types', 'triggers', 'sequences', 'defaultAcl')}
    structure['relations'] = [[*name.split('.'), 'r', 'supabase_admin', 'p', 'd',
        None, None, None, None, []] for name in tables]
    structure['extensionMembers'] = [['pg_net', 'schema', None, 'net', 'net']]
    profile = {**base.profile, 'tables': base.profile['tables'] + [t.split('.') for t in tables],
        'extensions': [['pg_net', '0.20.3', 'supabase_admin', 'extensions']],
        'providerState': {'profile': provider.PROFILE, 'structure': structure, 'sequenceState': []}}
    access = {**base.access, 'schemas': base.access['schemas'] +
        [[name, 'supabase_admin', []] for name in sorted(provider.SCHEMAS)]}
    # Direct structured contract fixture; this is not a native custody producer.
    return replace(base, source_project='native:' + str(uuid4()), rows=rows,
        profile=profile, access=access)


def test_plan_accounts_for_all_populated_provider_rows_without_import_authority(populated):
    summary = provider.summary(populated)
    assert len(summary['tables']) == 15
    assert sum(v['rows'] for v in summary['tables'].values()) == 193
    assert summary['stateAlreadyPresentRequired'] is True
    assert summary['providerStateImportAuthorized'] is False
    assert summary['providerServiceActivationAuthorized'] is False
    assert summary['providerKeyPortabilityVerified'] is False
    assert populated.application_schemas == {'public'}


@pytest.mark.parametrize('fault,code', [
    ('missing_contract', 'profile_required'), ('partial_namespaces', 'profile_required'),
    ('wrong_source', 'profile_required'), ('unexpected_table', 'table_profile_changed'),
    ('missing_extension_owner', 'extension_membership_changed'),
    ('missing_namespace_membership', 'extension_membership_changed'),
    ('wrong_extension_version', 'extension_membership_changed'),
    ('missing_counter', 'sequence_profile_changed'),
])
def test_provider_profile_refuses_unproven_inventory_and_extension_semantics(populated, fault, code):
    capture = deepcopy(populated)
    if fault == 'missing_contract': capture.profile.pop('providerState')
    elif fault == 'partial_namespaces': capture.access['schemas'].pop()
    elif fault == 'wrong_source': capture = replace(capture, source_project='a' * 20)
    elif fault == 'unexpected_table': capture.profile['tables'].append(['net', 'unrelated'])
    elif fault == 'missing_extension_owner': capture.profile['extensions'][0][2] = 'postgres'
    elif fault == 'missing_namespace_membership':
        capture.profile['providerState']['structure']['extensionMembers'] = []
    elif fault == 'wrong_extension_version': capture.profile['extensions'][0][1] = '0.20.4'
    elif fault == 'missing_counter':
        capture.profile['providerState']['structure']['sequences'] = [
            ['net', 'http_request_queue_id_seq', 'bigint', 1, 1, 9999, 1, 1, False]]
    with pytest.raises(ValueError, match=code): provider.profile(capture)


@pytest.mark.parametrize('table', sorted(provider.WORK_TABLES))
def test_work_bearing_provider_rows_never_become_passive_history(populated, table):
    populated.rows[table] = {'rows': 1, 'sha256': digest(b'pending provider operation')}
    with pytest.raises(ValueError, match='background_provider_work_unsupported'):
        provider.profile(populated)


def test_compiler_does_not_create_provider_schemas_relabel_owners_or_import_provider_rows(populated):
    selected = []
    sections = []
    class Archive:
        entries = toc_entries('1; 2615 1 SCHEMA - public postgres\n'
            '2; 1259 2 TABLE public items postgres\n3; 0 2 TABLE DATA public items postgres\n' +
            ''.join(f'{i+10}; 2615 {i+10} SCHEMA - {s} supabase_admin\n'
                for i, s in enumerate(sorted(provider.SCHEMAS - {'net'}))) +
            '20; 1259 20 TABLE _realtime tenants supabase_admin\n'
            '21; 0 20 TABLE DATA _realtime tenants supabase_admin\n'
            '22; 0 22 SEQUENCE SET net http_request_queue_id_seq supabase_admin\n')
        def sql(self, entries, **kwargs):
            selected.extend(entries)
            sections.append(kwargs.get('section'))
            return kwargs.get('section', '').encode()
    program = compile_program(populated, Archive())
    assert program.sequences == ()
    assert not any(e.schema in provider.SCHEMAS or e.kind == 'SCHEMA' and
        e.tag in provider.SCHEMAS for e in selected)
    assert any(e.kind == 'TABLE DATA' and e.schema == 'public' for e in selected)
    assert program.definitions == b'pre-data' and program.post_data == b'post-data'
    assert program.preserve_provider_constraints is True
    assert sections.count('pre-data') == sections.count('post-data') == 1


def test_ordinary_hosted_transport_refuses_before_calls_or_mutation(populated):
    called = []
    target = SimpleNamespace(validate=lambda **kwargs: called.append('provider HTTP'))
    operator = HostedBackupRecovery.__new__(HostedBackupRecovery)
    operator.plan_body = {'providerState': provider.summary(populated)}
    operator.target = target
    with pytest.raises(ValueError, match='target_composition_unsupported'):
        operator._validate(capture_required=False)
    assert called == []


def test_preprovisioned_role_program_preserves_original_nonpostgres_grantors(populated):
    from talli_backend.adapters.hosted_recovery_sql import role_program
    populated.roles['memberships'].append(['restore_owner', 'restore_runtime', 'supabase_admin',
        False, False, True])
    populated.access['relations'][0][3] = 'restore_owner'
    start, final = role_program(populated)
    assert start == b'grant "restore_owner" to postgres with inherit true,set true;'
    assert b'create role' not in start and b'alter role' not in start
    assert b'"restore_runtime"' not in start + final
    assert b'admin false,inherit false,set false' in final


class OrderedDB:
    def __init__(self, dependencies):
        self.dependencies = dependencies
        self.copied = []
        self.sql = []
    def execute(self, sql, *args, **kwargs):
        if 'from pg_constraint' in sql:
            return SimpleNamespace(fetchall=lambda: self.dependencies)
        self.sql.append(sql)
        return SimpleNamespace(nextset=lambda: False)
    def cursor(self): return self
    def copy(self, header):
        self.copied.append(header.split()[1])
        return self
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def write(self, body): pass


def test_existing_auth_foreign_keys_order_copy_without_disabling_constraints():
    from talli_backend.adapters.hosted_recovery_sql import execute_data
    raw = (b'COPY auth.identities (id) FROM stdin;\n1\n\\.\n'
        b'-- The native order need not put provider parents first.\n'
        b'COPY auth.users (id) FROM stdin;\n1\n\\.\n')
    db = OrderedDB([('auth', 'identities', 'auth', 'users')])
    seen = execute_data(db, raw, {t: {'rows': 1} for t in ('auth.users', 'auth.identities')},
        order_by_foreign_keys=True)
    assert db.copied == ['auth.users', 'auth.identities']
    assert seen == {'auth.users', 'auth.identities'}
    assert not any('session_replication_role' in sql for sql in db.sql)


@pytest.mark.parametrize('fault,code', [('cycle', 'foreign_key_cycle_unsupported'),
    ('interleaved_sql', 'ordered_data_sql_unsupported'), ('wrong_row_proof', 'copy_inventory_changed')])
def test_ordered_copy_refuses_before_any_copy_or_active_sql(fault, code):
    from talli_backend.adapters.hosted_recovery_sql import execute_data
    raw = b'COPY auth.a (id) FROM stdin;\n1\n\\.\nCOPY auth.b (id) FROM stdin;\n1\n\\.\n'
    dependencies = [('auth', 'a', 'auth', 'b'), ('auth', 'b', 'auth', 'a')] if fault == 'cycle' else []
    if fault == 'interleaved_sql': raw = raw.replace(b'COPY auth.b', b'SELECT 1;\nCOPY auth.b')
    rows = {t: {'rows': 1} for t in ('auth.a', 'auth.b')}
    if fault == 'wrong_row_proof': rows['auth.a']['rows'] = 0
    db = OrderedDB(dependencies)
    with pytest.raises(ValueError, match=code):
        execute_data(db, raw, rows, order_by_foreign_keys=True)
    assert db.copied == [] and db.sql == []


@pytest.mark.parametrize('hiding_place', ['tables', 'catalog', 'relation_access'])
def test_omitted_provider_access_cannot_bypass_transport_profile(populated, hiding_place):
    populated.profile.pop('providerState')
    populated.access['schemas'] = [r for r in populated.access['schemas'] if r[0] not in provider.SCHEMAS]
    if hiding_place != 'tables':
        populated.profile['tables'] = [t for t in populated.profile['tables'] if t[0] not in provider.SCHEMAS]
    if hiding_place == 'catalog': populated.catalog['rls'].append(['net', '_http_response', False, False, 'supabase_admin'])
    if hiding_place == 'relation_access': populated.access['relations'].append(['net', '_http_response', 'r', 'supabase_admin', []])
    with pytest.raises(ValueError, match='profile_required'): provider.profile(populated)


@pytest.mark.parametrize('field', ['relations', 'types', 'triggers', 'sequences', 'defaultAcl', 'extensionMembers'])
def test_malformed_provider_structure_has_a_bounded_capture_error(populated, field):
    populated.profile['providerState']['structure'][field] = [[]]
    with pytest.raises(ValueError, match='profile_invalid'): provider.profile(populated)


def test_original_storage_policy_owner_is_required_before_app_import(populated):
    populated.catalog['rls'].append(['storage', 'objects', True, False, 'supabase_storage_admin'])
    populated.catalog['policies'].append(['storage', 'objects', 'original_policy', 'PERMISSIVE',
        ['company_access_executor'], 'SELECT', 'true', None])
    calls = []
    class DB:
        def execute(self, sql, parameters):
            calls.append((sql, parameters))
            return SimpleNamespace(fetchone=lambda: (False,))
    with pytest.raises(ValueError, match='managed_policy_owner_unavailable'):
        provider.require_policy_authority(DB(), populated)
    assert len(calls) == 1 and calls[0][1] == ('supabase_storage_admin',)
    assert calls[0][0].startswith('select ')


def test_ordered_copy_preserves_self_references_and_empty_tables():
    from talli_backend.adapters.hosted_recovery_sql import execute_data
    db = OrderedDB([('auth', 'users', 'auth', 'users')])
    raw = b'COPY auth.users (id) FROM stdin;\n1\n\\.\nCOPY auth.empty (id) FROM stdin;\n\\.\n'
    seen = execute_data(db, raw, {'auth.users': {'rows': 1}, 'auth.empty': {'rows': 0}},
        order_by_foreign_keys=True)
    # A self-reference is checked at the end of the same COPY statement.
    assert db.copied == ['auth.users'] and seen == {'auth.users', 'auth.empty'}


def test_ordered_copy_bounds_target_dependency_edges():
    from talli_backend.adapters.hosted_recovery_sql import execute_data
    db = OrderedDB([('auth', 'a', 'auth', 'b')] * 4097)
    with pytest.raises(ValueError, match='foreign_key_bound'):
        execute_data(db, b'COPY auth.a (id) FROM stdin;\n1\n\\.\n',
            {'auth.a': {'rows': 1}}, order_by_foreign_keys=True)
    assert db.copied == []


@pytest.mark.parametrize('value', [None, 1, [None], [1], [[{}, 'sequence', 1, False]],
    [['net', [], 1, False]], [['net', 'sequence', True, False]]])
def test_sequence_state_validates_nested_types_before_hashing(populated, value):
    populated.profile['providerState']['sequenceState'] = value
    with pytest.raises(ValueError, match='provider_sequence_profile_changed'):
        provider.profile(populated)


@pytest.mark.parametrize('fault', ['null_schema', 'list_schema', 'null_columns', 'null_column',
    'bad_column_name', 'oversized_profile'])
def test_nested_structure_fields_fail_with_profile_errors(populated, fault):
    state = populated.profile['providerState'];row = state['structure']['relations'][0]
    if fault == 'null_schema': row[0] = None
    elif fault == 'list_schema': row[0] = []
    elif fault == 'null_columns': row[10] = None
    elif fault == 'null_column': row[10] = [None]
    elif fault == 'bad_column_name': row[10] = [[[], 'text', False, '', '', None, None, None, None]]
    else: state['sequenceState'] = ['x' * (4 * 1024**2)]
    with pytest.raises(ValueError, match='provider_profile_invalid'):
        provider.profile(populated)


def test_empty_actors_and_already_disabled_roles_need_no_mutating_authority():
    calls = []
    class ReadOnlyDB:
        def execute(self, sql, params):
            calls.append(sql)
            assert sql.startswith('select '), 'preprovisioned NOLOGIN must not require ALTER ROLE'
            return SimpleNamespace(fetchall=lambda: [])
    HostedBackupRecovery.__new__(HostedBackupRecovery)._quarantine(ReadOnlyDB(),
        {'actors': [], 'logins': ['unowned_preprovisioned_nologin']})
    assert len(calls) == 1


def inert_phase_model(snapshot, tmp_path, monkeypatch):
    """Fault-test orchestration; real provider admission is tested separately."""
    from test_hosted_backup_recovery import operator
    from talli_backend.adapters import hosted_backup_recovery as recovery
    from talli_backend.adapters.hosted_recovery_capture import encoded
    instance, target = operator(snapshot, tmp_path, monkeypatch)
    instance.plan_body['providerState'] = {'profile': provider.PROFILE}
    instance.plan_sha = digest(encoded(instance.plan_body))
    target.require_inert_provider_state = lambda _: None
    monkeypatch.setattr(recovery, 'verify_provider_state', lambda *args: None)
    return instance, target


@pytest.mark.parametrize('failure', ['policy_owner', 'replica_mode'])
def test_inert_preflight_refuses_before_role_acl_ddl_copy_marker_or_upload(snapshot, tmp_path, monkeypatch, failure):
    from test_hosted_backup_recovery import repin
    catalog = {'functions': [], 'constraints': [], 'indexes': [],
        'rls': [['storage', 'objects', True, False, 'supabase_storage_admin']],
        'policies': [['storage', 'objects', 'original', 'PERMISSIVE', [], 'SELECT', 'true', None]]}
    repin(snapshot, 'source-catalog.private.json', catalog)
    instance, target = inert_phase_model(snapshot, tmp_path, monkeypatch)
    if failure == 'replica_mode': target.db.replication_mode = 'replica'
    expected = 'managed_policy_owner_unavailable' if failure == 'policy_owner' else 'origin_mode_required'
    with pytest.raises(ValueError, match=expected): instance.restore(expected_plan_sha256=instance.plan_sha)
    assert target.db.marker is None and target.db.ddl == 0
    assert not any(sql.lower().startswith(('create ', 'alter ', 'grant ', 'revoke ', 'update ', 'copy '))
        for sql in target.db.calls)
    assert target.db.enabled_logins == {'restore_runtime'}


@pytest.mark.parametrize('drift', ['provider_rows', 'role_membership'])
def test_committed_marker_cannot_hide_provider_or_role_drift(snapshot, tmp_path, monkeypatch, drift):
    from talli_backend.adapters import hosted_backup_recovery as recovery
    instance, target = inert_phase_model(snapshot, tmp_path, monkeypatch)
    instance.restore(expected_plan_sha256=instance.plan_sha)
    previous_ddl = target.db.ddl
    def changed(*args): raise ValueError('hosted_' + drift + '_changed')
    monkeypatch.setattr(recovery, 'verify_provider_state' if drift == 'provider_rows' else 'verify_custom_roles', changed)
    with pytest.raises(ValueError, match=drift): instance.inspect()
    # Without capture evidence, inspection explicitly reports current verification
    # unavailable, even though the historical committed marker is still present.
    inspection = HostedBackupRecovery.from_state(target=target, work=instance.work,
        expected_plan_sha256=instance.plan_sha).inspect()
    assert inspection['databaseMarkerPresent'] is True and inspection['providerStateCurrent'] is None
    with pytest.raises(ValueError, match=drift): instance.restore(expected_plan_sha256=instance.plan_sha)
    assert target.db.ddl == previous_ddl


def test_provider_state_is_rechecked_after_last_storage_upload(snapshot, tmp_path, monkeypatch):
    from test_hosted_backup_recovery import repin
    from talli_backend.adapters import hosted_backup_recovery as recovery
    body = b'private ordinary fixture'
    obj = {'bucket': 'private-files', 'name': 'company/original.pdf', 'bytes': len(body),
        'sha256': digest(body), 'file': 'object-' + digest(body) + '.bin'}
    repin(snapshot, obj['file'], body); repin(snapshot, 'object-manifest.private.json', [obj])
    instance, target = inert_phase_model(snapshot, tmp_path, monkeypatch)
    uploaded = []
    def upload(item, raw):
        assert raw == body
        uploaded.append(item['name'])
        return {'name': item['name']}
    target.restore_object = upload
    def verify(*args):
        if uploaded: raise ValueError('hosted_provider_state_changed')
    monkeypatch.setattr(recovery, 'verify_provider_state', verify)
    with pytest.raises(ValueError, match='provider_state_changed'):
        instance.restore(expected_plan_sha256=instance.plan_sha)
    assert uploaded == ['company/original.pdf'] and target.db.marker is not None
    assert instance._state()['phase'] == 'inspection_or_containment_required'


def test_inert_orchestration_places_copy_between_sections_without_replica_set(snapshot, tmp_path, monkeypatch):
    from talli_backend.adapters import hosted_backup_recovery as recovery
    instance, target = inert_phase_model(snapshot, tmp_path, monkeypatch)
    original = recovery.compile_program(instance.capture, instance.archive)
    program = replace(original, definitions=b'CREATE PRE;', post_data=b'CREATE POST;',
        preserve_provider_constraints=True)
    monkeypatch.setattr(recovery, 'compile_program', lambda *args: program)
    phases = []
    execute = recovery.execute_batch
    def batch(db, raw):
        if raw in (b'CREATE PRE;', b'CREATE POST;'): phases.append(raw.decode())
        return execute(db, raw)
    monkeypatch.setattr(recovery, 'execute_batch', batch)
    monkeypatch.setattr(recovery, 'execute_data', lambda *args, **kwargs: phases.append('COPY') or set())
    instance.restore(expected_plan_sha256=instance.plan_sha)
    assert phases == ['CREATE PRE;', 'COPY', 'CREATE POST;']
    assert not any('set session_replication_role=' in sql for sql in target.db.calls)


def test_ordered_copy_resolves_branching_parent_dependencies():
    from talli_backend.adapters.hosted_recovery_sql import execute_data
    db = OrderedDB([('auth', 'a', 'auth', 'b'), ('auth', 'a', 'auth', 'c'),
        ('auth', 'b', 'auth', 'd'), ('auth', 'c', 'auth', 'd')])
    raw = b''.join(b'COPY auth.' + name.encode() + b' (id) FROM stdin;\n1\n\\.\n' for name in 'abcd')
    execute_data(db, raw, {'auth.' + name: {'rows': 1} for name in 'abcd'}, order_by_foreign_keys=True)
    assert db.copied == ['auth.d', 'auth.b', 'auth.c', 'auth.a']


def test_ordered_copy_rejects_duplicate_blocks_before_sql_or_copy():
    from talli_backend.adapters.hosted_recovery_sql import execute_data
    db = OrderedDB([])
    with pytest.raises(ValueError, match='copy_inventory_changed'):
        execute_data(db, b'COPY auth.a (id) FROM stdin;\n1\n\\.\n' * 2,
            {'auth.a': {'rows': 1}}, order_by_foreign_keys=True)
    assert db.sql == [] and db.copied == []


def test_type_only_application_owner_gets_original_temporary_role_access(populated):
    from talli_backend.adapters.hosted_recovery_sql import role_program
    start, final = role_program(populated, definition_owners={'restore_owner'})
    assert b'grant "restore_owner" to postgres with inherit true,set true' in start
    assert b'admin false,inherit false,set false' in final
