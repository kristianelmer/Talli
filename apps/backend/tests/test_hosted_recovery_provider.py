"""Provider state is an exact inert prerequisite, never a managed write waiver."""
from copy import deepcopy
from dataclasses import replace
import json
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
        'providerState': {'profile': provider.PROFILE_V1, 'structure': structure, 'sequenceState': []}}
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
    # This model explicitly selects native V1 rather than ordinary managed V5.
    instance.plan_body.pop('managedLifecycle', None)
    instance.plan_body['version'] = 1
    instance.plan_body['providerState'] = {'profile': provider.PROFILE_V1}
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


@pytest.fixture
def populated_v2(populated):
    """V2 keeps managed definitions/access, but never their mutable row state."""
    capture = deepcopy(populated)
    for name in ('supabase_admin', 'supabase_auth_admin', 'supabase_storage_admin', 'authenticated'):
        capture.roles['roles'].append([name, False, False, False, False, False,
            False, False, -1, None, None])
    state = capture.profile['providerState']
    state['profile'] = provider.PROFILE
    state['managedAccess'] = {'schemas': [
        ['auth', 'supabase_auth_admin', [['supabase_auth_admin', 'postgres', 'USAGE', False]]],
        ['storage', 'supabase_storage_admin', [['supabase_storage_admin', 'postgres', 'USAGE', False]]]],
        'relations': []}
    for schema, table, owner in (('auth', 'users', 'supabase_auth_admin'),
            ('storage', 'objects', 'supabase_storage_admin')):
        capture.profile['tables'].append([schema, table])
        capture.rows[schema + '.' + table] = {'rows': 1, 'sha256': digest(b'managed mutable row')}
        state['structure']['relations'].append([schema, table, 'r', owner, 'p', 'd',
            None, None, None, None, [['id', 'uuid', True, '', '', None, None, None, None]]])
        state['managedAccess']['relations'].append([schema, table, 'r', owner,
            [[owner, 'postgres', 'SELECT', False], [owner, 'authenticated', 'SELECT', False]]])
        capture.catalog['rls'].append([schema, table, True, False, owner])
    state['structure']['sequences'] = [
        ['net', 'http_request_queue_id_seq', 'bigint', 1, 1, 9999, 1, 1, False],
        ['auth', 'refresh_tokens_id_seq', 'bigint', 1, 1, 9999, 1, 1, False]]
    state['sequenceState'] = [['net', 'http_request_queue_id_seq', 1, False]]
    state['structure']['relations'].extend([
        ['net', 'http_request_queue_id_seq', 'S', 'supabase_admin', 'p', 'd', None, None, None, None, []],
        ['auth', 'refresh_tokens_id_seq', 'S', 'supabase_auth_admin', 'p', 'd', None, None, None, None, []]])
    state['managedAccess']['relations'].append(['auth', 'refresh_tokens_id_seq', 'S',
        'supabase_auth_admin', [['supabase_auth_admin', 'postgres', 'USAGE', False]]])
    state['structure']['triggers'] = [['storage', 'objects', 'objects_hook',
        'CREATE TRIGGER objects_hook AFTER INSERT ON storage.objects '
        'FOR EACH ROW EXECUTE FUNCTION storage.objects_hook()', 'O']]
    state['structure']['types'] = [['auth', 'mfa_status', 'e', 'supabase_auth_admin',
        '-', False, None, ['verified'], [], None]]
    capture.catalog['policies'].append(['storage', 'objects', 'original_policy', 'PERMISSIVE',
        ['authenticated'], 'SELECT', 'true', None])
    return capture


def test_v1_keeps_five_schema_contract_and_never_selects_owner_stage(populated):
    state = provider.profile(populated)
    assert state['profile'] == provider.PROFILE_V1
    assert all(set(p) == provider.SCHEMAS for p in provider.parameters(provider.PROFILE_V1))
    summary = provider.summary(populated)
    assert summary['profile'] == provider.PROFILE_V1
    assert 'version' not in summary and 'ownerPolicyStageRequired' not in summary
    assert 'managedAccess' not in state
    # Adding V2 fields cannot silently upgrade an independently pinned V1 input.
    state['managedAccess'] = {'schemas': [], 'relations': []}
    with pytest.raises(ValueError, match='provider_profile_required'):
        provider.profile(populated)


def test_v2_extends_structure_without_expanding_row_or_counter_prerequisites(populated_v2):
    state = provider.profile(populated_v2)
    assert all(set(p) == provider.STRUCTURE_SCHEMAS for p in provider.parameters())
    assert populated_v2.application_schemas == {'public'}
    assert {r[0] for r in state['structure']['sequences']} == {'net', 'auth'}
    assert state['sequenceState'] == [['net', 'http_request_queue_id_seq', 1, False]]
    summary = provider.summary(populated_v2)
    assert summary['profile'] == provider.PROFILE and summary['version'] == 2
    assert summary['ownerPolicyStageRequired'] is True
    assert summary['managedAccessAlreadyPresentRequired'] is True
    assert summary['managedAccessImportAuthorized'] is False
    assert set(summary['tables']) == provider.TABLES
    assert sum(r['rows'] for r in summary['tables'].values()) == 193


@pytest.mark.parametrize('fault', ['missing_access', 'extra_field', 'missing_schema',
    'duplicate_schema', 'unknown_owner', 'unknown_grantor', 'unknown_grantee',
    'wrong_privilege', 'wrong_option', 'duplicate_grant', 'missing_relation',
    'wrong_relation_kind', 'wrong_relation_owner', 'extra_relation', 'malformed_grant',
    'null_relation', 'unknown_structure_owner', 'missing_column', 'oversized_access',
    'managed_application_schema'])
def test_v2_managed_access_requires_complete_bounded_original_facts(populated_v2, fault):
    state = populated_v2.profile['providerState']
    access = state['managedAccess']
    relation = access['relations'][0]
    grant = relation[-1][0]
    if fault == 'missing_access': state.pop('managedAccess')
    elif fault == 'extra_field': access['repairOwners'] = True
    elif fault == 'missing_schema': access['schemas'].pop()
    elif fault == 'duplicate_schema': access['schemas'].append(deepcopy(access['schemas'][0]))
    elif fault == 'unknown_owner': access['schemas'][0][1] = 'unrecorded_owner'
    elif fault == 'unknown_grantor': grant[0] = 'unrecorded_grantor'
    elif fault == 'unknown_grantee': grant[1] = 'unrecorded_grantee'
    elif fault == 'wrong_privilege': grant[2] = 'EXECUTE'
    elif fault == 'wrong_option': grant[3] = 1
    elif fault == 'duplicate_grant': relation[-1].append(deepcopy(grant))
    elif fault == 'missing_relation': access['relations'].pop()
    elif fault == 'wrong_relation_kind': relation[2] = 'S'
    elif fault == 'wrong_relation_owner': relation[3] = 'postgres'
    elif fault == 'extra_relation': access['relations'].append(['auth', 'unrecorded', 'r', 'postgres', []])
    elif fault == 'malformed_grant': relation[-1] = [None]
    elif fault == 'null_relation': access['relations'] = [None]
    elif fault == 'unknown_structure_owner': state['structure']['relations'][0][3] = 'unrecorded_owner'
    elif fault == 'missing_column': state['structure']['relations'][-3][10] = [None]
    elif fault == 'oversized_access': relation[-1] = ['x' * (4 * 1024**2)]
    else: populated_v2.access['schemas'].append(['auth', 'supabase_auth_admin', []])
    with pytest.raises(ValueError, match='hosted_provider_'):
        provider.profile(populated_v2)


@pytest.mark.parametrize('fault', ['missing_table', 'extra_table', 'missing_readonly_table',
    'auth_trigger', 'provider_trigger', 'disabled_storage_trigger', 'replica_storage_trigger',
    'unknown_trigger_schema', 'auth_counter', 'missing_readonly_counter', 'duplicate_counter'])
def test_v2_table_trigger_and_counter_scope_refuses_unsupported_state(populated_v2, fault):
    state = populated_v2.profile['providerState']
    if fault == 'missing_table': populated_v2.profile['tables'].remove(['auth', 'users'])
    elif fault == 'extra_table': populated_v2.profile['tables'].append(['storage', 'unrecorded'])
    elif fault == 'missing_readonly_table':
        populated_v2.profile['tables'].remove(['net', '_http_response'])
    elif fault == 'auth_trigger': state['structure']['triggers'][0][0] = 'auth'
    elif fault == 'provider_trigger': state['structure']['triggers'][0][0] = 'pgboss_v10'
    elif fault == 'disabled_storage_trigger': state['structure']['triggers'][0][4] = 'D'
    elif fault == 'replica_storage_trigger': state['structure']['triggers'][0][4] = 'R'
    elif fault == 'unknown_trigger_schema': state['structure']['triggers'][0][0] = 'unrecorded'
    elif fault == 'auth_counter': state['sequenceState'].append(['auth', 'refresh_tokens_id_seq', 1, False])
    elif fault == 'missing_readonly_counter': state['sequenceState'] = []
    else: state['sequenceState'].append(deepcopy(state['sequenceState'][0]))
    with pytest.raises(ValueError, match='hosted_provider_|hosted_background_provider_'):
        provider.profile(populated_v2)


@pytest.mark.parametrize('table', sorted(provider.WORK_TABLES))
def test_v2_never_turns_queued_provider_work_into_preprovisioned_history(populated_v2, table):
    populated_v2.rows[table]['rows'] = 1
    with pytest.raises(ValueError, match='background_provider_work_unsupported'):
        provider.profile(populated_v2)


class ProviderDB:
    """Read-only target facts; access/catalog/structure drift varies independently."""
    def __init__(self, capture):
        self.capture = capture
        self.structure = deepcopy(capture.profile['providerState']['structure'])
        self.managed_access = deepcopy(capture.profile['providerState'].get('managedAccess'))
        self.access = {key: [deepcopy(r) for r in rows if r[0] in provider.SCHEMAS]
            for key, rows in capture.access.items()}
        self.catalog = deepcopy(capture.catalog)
        self.roles = deepcopy(capture.roles)
        self.calls = []

    def execute(self, statement, parameters=None):
        self.calls.append((statement, parameters))
        assert statement.startswith(('select ', 'set local ')), 'provider verification cannot repair state'
        from talli_backend.adapters.hosted_recovery_access import ACCESS_SQL
        from talli_backend.adapters.hosted_recovery_sql import CATALOG_SQL
        if statement == provider.SQL: value = self.structure
        elif statement == ACCESS_SQL:
            value = self.managed_access if set(parameters[0]) == provider.MANAGED_ACCESS_SCHEMAS else self.access
        elif statement == CATALOG_SQL: value = self.catalog
        elif statement.startswith('set local '): value = None
        elif statement.startswith('select last_value,is_called'):
            assert 'auth.' not in statement and '"auth".' not in statement
            return SimpleNamespace(fetchone=lambda: (1, False))
        elif statement.startswith('select rolname,rolsuper'):
            return SimpleNamespace(fetchall=lambda: [tuple(r) for r in self.roles['roles']
                if r[0] in parameters[0]])
        elif statement == 'select rolname from pg_roles':
            return SimpleNamespace(fetchall=lambda: [(r[0],) for r in self.roles['roles']])
        elif 'from pg_auth_members' in statement:
            return SimpleNamespace(fetchall=lambda: [tuple(r) for r in self.roles['memberships']
                if r[0] in parameters[0] and r[1] in parameters[1]])
        else: raise AssertionError('unexpected provider query: ' + statement)
        return SimpleNamespace(fetchone=lambda: (value,))


@pytest.fixture
def provider_verification(monkeypatch):
    """Exercise provider verification with the real owner-policy inventory guard."""
    from talli_backend.adapters import hosted_recovery_access as access
    from talli_backend.adapters import hosted_recovery_owner_policy as owner_policy
    calls = {'policies': [], 'tables': []}
    original_policy_status = owner_policy.policy_status

    def rows(db, tables):
        calls['tables'].append(tables)
        return {'.'.join(t): db.capture.rows['.'.join(t)] for t in tables}

    def policy_status(capture, actual_catalog, *, allow_missing=False):
        calls['policies'].append((actual_catalog, allow_missing))
        return original_policy_status(capture, actual_catalog, allow_missing=allow_missing)

    monkeypatch.setattr(access, 'row_commitments', rows)
    monkeypatch.setattr(owner_policy, 'policy_status', policy_status)
    return calls


def test_v1_verification_does_not_call_owner_policy_or_read_managed_access(populated, provider_verification):
    db = ProviderDB(populated)
    provider.verify(db, populated)
    assert provider_verification['policies'] == []
    assert {'.'.join(t) for t in provider_verification['tables'][0]} == provider.TABLES
    assert db.calls[1][1] == provider.parameters(provider.PROFILE_V1)
    with pytest.raises(ValueError, match='provider_profile_required'):
        provider.verify(db, populated, pending_managed_policies=True)


def test_v2_verification_guards_policies_before_excluding_only_managed_policy_rows(populated_v2, provider_verification):
    db = ProviderDB(populated_v2)
    db.catalog['policies'] = []
    with pytest.raises(ValueError, match='owner_policy_missing'):
        provider.verify(db, populated_v2)
    provider.verify(db, populated_v2, pending_managed_policies=True)
    assert provider_verification['policies'][-1] == (db.catalog, True)
    assert {'.'.join(t) for t in provider_verification['tables'][-1]} == provider.TABLES
    assert db.calls[1][1] == provider.parameters(provider.PROFILE)
    db.catalog['policies'] = deepcopy(populated_v2.catalog['policies'])
    provider.verify(db, populated_v2)
    assert provider_verification['policies'][-1] == (db.catalog, False)


@pytest.mark.parametrize('fault,code', [('column', 'structure_changed'), ('column_acl', 'structure_changed'),
    ('type_acl', 'structure_changed'), ('trigger', 'structure_changed'), ('managed_acl', 'managed_access_changed'),
    ('managed_owner', 'managed_access_changed'), ('catalog_owner', 'catalog_changed'),
    ('unknown_policy', 'owner_policy_unexpected_policy'),
    ('conflicting_policy', 'owner_policy_definition_changed'),
    ('readonly_policy', 'catalog_changed')])
def test_v2_verification_refuses_extended_definition_access_and_policy_drift(populated_v2, provider_verification, fault, code):
    db = ProviderDB(populated_v2)
    auth = next(r for r in db.structure['relations'] if r[:2] == ['auth', 'users'])
    if fault == 'column': auth[10][0][1] = 'text'
    elif fault == 'column_acl': auth[10][0][6] = '{authenticated=r/supabase_auth_admin}'
    elif fault == 'type_acl': db.structure['types'][0][9] = '{authenticated=U/supabase_auth_admin}'
    elif fault == 'trigger': db.structure['triggers'][0][3] += ' altered'
    elif fault == 'managed_acl': db.managed_access['relations'][0][-1][0][3] = True
    elif fault == 'managed_owner': db.managed_access['schemas'][0][1] = 'postgres'
    elif fault == 'catalog_owner': db.catalog['rls'][0][4] = 'postgres'
    elif fault == 'unknown_policy': db.catalog['policies'][0][2] = 'unrecorded_policy'
    elif fault == 'conflicting_policy': db.catalog['policies'][0][6] = 'false'
    else: db.catalog['policies'].append(['pgboss_v10', 'job', 'unrecorded_policy',
        'PERMISSIVE', ['postgres'], 'SELECT', 'true', None])
    with pytest.raises(ValueError, match=code):
        provider.verify(db, populated_v2, pending_managed_policies=True)


def test_v2_keeps_original_grantor_chains_and_grant_options_verbatim(populated_v2):
    state = populated_v2.profile['providerState']
    state['managedAccess']['relations'][0][-1].append(['postgres', 'restore_runtime', 'SELECT', True])
    before = deepcopy(state)
    assert provider.profile(populated_v2) == before
    assert state == before


@pytest.mark.parametrize('fault,code', [('provider_role', 'provider_roles_changed'),
    ('provider_grantor', 'provider_memberships_changed'), ('extra_role', 'provider_role_inventory_changed')])
def test_v2_verification_preserves_original_provider_role_graph(populated_v2, provider_verification, fault, code):
    populated_v2.roles['memberships'].append(['supabase_storage_admin', 'postgres', 'supabase_admin',
        False, False, True])
    db = ProviderDB(populated_v2)
    if fault == 'provider_role':
        next(r for r in db.roles['roles'] if r[0] == 'supabase_storage_admin')[2] = True
    elif fault == 'provider_grantor': db.roles['memberships'][-1][2] = 'postgres'
    else: db.roles['roles'].append(['unrecorded_role', False, False, False, False, False,
        False, False, -1, None, None])
    with pytest.raises(ValueError, match=code): provider.verify(db, populated_v2)


def test_v2_cannot_be_downgraded_by_relabelling_its_structure_as_v1(populated_v2):
    state = populated_v2.profile['providerState']
    state['profile'] = provider.PROFILE_V1
    state.pop('managedAccess')
    with pytest.raises(ValueError, match='provider_profile_invalid'):
        provider.profile(populated_v2)


def test_native_capture_defaults_to_v2_access_and_readonly_counters_in_one_snapshot(populated_v2, tmp_path, monkeypatch):
    from talli_backend.adapters import native_managed_handoff as handoff
    from talli_backend.adapters.hosted_recovery_access import ACCESS_SQL
    from talli_backend.adapters.hosted_recovery_sql import CATALOG_SQL
    capture = populated_v2
    calls = []
    active = []

    class Snapshot:
        def __init__(self, target): pass
        def __enter__(self):
            active.append(True)
            return self
        def __exit__(self, *args): active.pop()
        def query(self, statement, parameters=()):
            assert active, 'all source facts must use the same native snapshot'
            calls.append((statement, parameters))
            if statement == provider.SQL:
                assert parameters == provider.parameters(provider.PROFILE)
                return deepcopy(capture.profile['providerState']['structure'])
            if statement == ACCESS_SQL:
                if set(parameters[0]) == provider.MANAGED_ACCESS_SCHEMAS:
                    return deepcopy(capture.profile['providerState']['managedAccess'])
                assert not set(parameters[0]) & provider.MANAGED_ACCESS_SCHEMAS
                return deepcopy(capture.access)
            if statement == CATALOG_SQL: return deepcopy(capture.catalog)
            if statement == handoff.ROLES_SQL: return deepcopy(capture.roles)
            if statement == handoff.FACTS_SQL: return capture.profile['facts']
            if 'from pg_largeobject_metadata' in statement: return 0
            if 'from pg_tables' in statement: return capture.profile['tables']
            if 'from pg_namespace' in statement:
                assert set(parameters[0]) == handoff.MANAGED_SCHEMAS
                return sorted(capture.schemas)
            if 'from pg_extension' in statement: return capture.profile['extensions']
            if statement == handoff.DATABASE_ACCESS_SQL: return capture.database_access
            if statement.startswith('select jsonb_build_array('):
                assert 'from "net"."http_request_queue_id_seq"' in statement
                return ['net', 'http_request_queue_id_seq', 1, False]
            raise AssertionError('unexpected native snapshot query: ' + statement)
        def dump(self):
            assert active
            return b'PGDMPsnapshot-test'

    monkeypatch.setattr(handoff, '_NativeSnapshot', Snapshot)
    monkeypatch.setattr(handoff, '_row_facts', lambda *args: capture.rows)
    monkeypatch.setattr(handoff, '_objects', lambda *args: ([], {}, []))
    monkeypatch.setattr(handoff, 'NativeArchive', lambda *args, **kwargs: SimpleNamespace(entries=[]))
    destination = tmp_path / 'native-handoff'
    destination.mkdir(mode=0o700)
    handoff._capture(SimpleNamespace(target='native-target', system='independent-system'), destination,
        binding_sha256='a' * 64, pg_restore='/unused/pg_restore', held=[])
    result = json.loads((destination / 'capture/source-profile.json').read_bytes())
    state = result['providerState']
    assert state['profile'] == provider.PROFILE
    assert state['managedAccess'] == capture.profile['providerState']['managedAccess']
    assert state['sequenceState'] == [['net', 'http_request_queue_id_seq', 1, False]]
    access = json.loads((destination / 'access.json').read_bytes())['access']
    assert {r[0] for r in access['schemas']} == capture.schemas
    assert sum(statement == ACCESS_SQL for statement, _ in calls) == 2
