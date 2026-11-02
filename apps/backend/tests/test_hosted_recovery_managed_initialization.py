"""Explicit managed initialization: exact permitted differences and closed drift."""
from dataclasses import replace
import copy
import json
from types import SimpleNamespace

import pytest

from talli_backend.adapters.hosted_recovery_capture import ManagedCapture, digest, encoded
from talli_backend.adapters.hosted_recovery_operator import execute
from talli_backend.adapters import hosted_recovery_managed_initialization as initialization_module
from talli_backend.adapters.hosted_recovery_managed_initialization import (
    BUCKET_COLUMN, CONTRACT_SHA, DARK_CONSTRAINT, ManagedInitialization, PROFILE, SCHEMAS,
    SOURCE_EXTENSIONS, TARGET_EXTENSIONS, TRANSITION_FUNCTION, TRANSITION_TRIGGER, expected_catalog,
)
from test_hosted_backup_recovery import snapshot


@pytest.fixture
def source(snapshot):
    capture = ManagedCapture.open(**snapshot)
    capture.profile['extensions'] = copy.deepcopy(SOURCE_EXTENSIONS)
    capture.catalog['constraints'] = [copy.deepcopy(DARK_CONSTRAINT)]
    capture.catalog['functions'] = [['extensions', 'digest', 'text, text', 'original body',
        'postgres', [['postgres', 'PUBLIC', 'EXECUTE', False],
            ['postgres', 'restore_owner', 'EXECUTE', False]]]]
    return capture


class Archive:
    entries = [SimpleNamespace(kind='TABLE', schema='storage', tag='buckets')]
    def sql(self, entries):
        return b"    versioning_status text DEFAULT 'DISABLED'::text NOT NULL,"


def initialization(source):
    return ManagedInitialization.from_capture(source, Archive(), PROFILE)


class TargetDB:
    def __init__(self, source, *, fresh=False):
        self.engine = 170011
        self.extensions = copy.deepcopy(TARGET_EXTENSIONS)
        self.catalog = expected_catalog(source.catalog, SCHEMAS, fresh=fresh,
            custom_roles={r[0] for r in source.custom_roles})
        self.triggers = [(TRANSITION_TRIGGER, 'O')]
        self.column = list(BUCKET_COLUMN)
        self.invalid_buckets = 0
        self.invalid_foreign_keys = 0
        self.calls = []
    def execute(self, sql):
        self.calls.append(sql)
        if "current_setting('server_version_num')" in sql: value = (self.engine,)
        elif 'from pg_extension' in sql: value = self.extensions
        elif 'jsonb_build_object' in sql: value = (self.catalog,)
        elif 'pg_get_triggerdef' in sql: value = self.triggers
        elif 'from pg_constraint k' in sql: value = (self.invalid_foreign_keys,)
        elif 'pg_attribute' in sql: value = self.column
        elif 'count(*) from storage.buckets' in sql: value = (self.invalid_buckets,)
        else: value = None
        return SimpleNamespace(fetchone=lambda: value, fetchall=lambda: value)


def test_profile_changes_comparison_only_and_preserves_original_grants(source):
    original = encoded(source.catalog)
    profile = initialization(source)
    fresh, restored = TargetDB(source, fresh=True), TargetDB(source)
    profile.verify(fresh, fresh=True)
    profile.verify(restored)
    assert encoded(source.catalog) == original
    assert fresh.catalog['constraints'] == restored.catalog['constraints'] == []
    assert TRANSITION_FUNCTION in restored.catalog['functions']
    assert profile.binding['preflightCatalogSha256'] != profile.binding['restoredCatalogSha256']
    assert all(sql.startswith(('select ', 'set local search_path=')) for sql in fresh.calls + restored.calls)


@pytest.mark.parametrize('change,code', [
    (lambda s: s.profile['extensions'][0].__setitem__(1, '1.12'), 'source_unsupported'),
    (lambda s: s.profile['extensions'][0].__setitem__(2, 'postgres'), 'source_unsupported'),
    (lambda s: s.profile['facts'].__setitem__(0, 170006), 'source_unsupported'),
    (lambda s: s.catalog['constraints'].append(copy.deepcopy(DARK_CONSTRAINT)), 'source_changed'),
    (lambda s: s.catalog['constraints'].clear(), 'source_changed'),
    (lambda s: s.catalog['functions'].append(copy.deepcopy(TRANSITION_FUNCTION)), 'source_changed'),
    (lambda s: s.profile.__setitem__('providerState', {}), 'source_unsupported'),
])
def test_source_contract_is_not_a_general_drift_whitelist(source, change, code):
    change(source)
    with pytest.raises(ValueError, match=code): initialization(source)


def test_native_or_unknown_profile_cannot_select_managed_transform(source):
    with pytest.raises(ValueError, match='source_unsupported'):
        ManagedInitialization.from_capture(replace(source, source_project='native:fixture'), Archive(), PROFILE)
    with pytest.raises(ValueError, match='source_unsupported'):
        ManagedInitialization.from_capture(source, Archive(), 'accept-any-managed-profile')


def test_source_column_is_not_implicitly_accepted(source):
    archive = Archive()
    archive.sql = lambda entries: b'    versioning_status text,'
    with pytest.raises(ValueError, match='bucket_source_unsupported'):
        ManagedInitialization.from_capture(source, archive, PROFILE)


def test_source_preexisting_transition_trigger_refuses(source, monkeypatch):
    monkeypatch.setattr(initialization_module, 'managed_trigger_definitions',
        lambda archive: (TRANSITION_TRIGGER,))
    with pytest.raises(ValueError, match='source_changed'):
        initialization(source)


@pytest.mark.parametrize('change,code', [
    (lambda d: setattr(d, 'engine', 170012), 'engine_changed'),
    (lambda d: d.extensions[0].__setitem__(1, '1.12'), 'extension_profile_changed'),
    (lambda d: d.extensions[0].__setitem__(2, 'supabase_admin'), 'extension_profile_changed'),
    (lambda d: d.extensions[0].__setitem__(3, 'public'), 'extension_profile_changed'),
    (lambda d: d.catalog['constraints'].append(copy.deepcopy(DARK_CONSTRAINT)), 'catalog_changed'),
    (lambda d: d.catalog['functions'][-1].__setitem__(3, 'different body'), 'catalog_changed'),
    (lambda d: d.catalog['functions'][-1].__setitem__(4, 'postgres'), 'catalog_changed'),
    (lambda d: d.catalog['functions'][-1][5].append(['postgres', 'anon', 'EXECUTE', False]), 'catalog_changed'),
    (lambda d: d.catalog['functions'][0][5].pop(), 'catalog_changed'),
    (lambda d: d.catalog['policies'].append(['storage', 'objects', 'open', 'PERMISSIVE', ['anon'], 'ALL', 'true', 'true']), 'catalog_changed'),
    (lambda d: d.triggers.clear(), 'trigger_profile_changed'),
    (lambda d: d.triggers.__setitem__(0, (TRANSITION_TRIGGER, 'D')), 'trigger_profile_changed'),
    (lambda d: d.triggers.append((TRANSITION_TRIGGER + ' altered', 'O')), 'trigger_profile_changed'),
    (lambda d: setattr(d, 'invalid_foreign_keys', 1), 'foreign_key_enforcement_changed'),
    (lambda d: d.column.__setitem__(0, 'character varying'), 'bucket_column_changed'),
    (lambda d: d.column.__setitem__(1, False), 'bucket_column_changed'),
    (lambda d: d.column.__setitem__(2, "'ENABLED'::text"), 'bucket_column_changed'),
    (lambda d: setattr(d, 'invalid_buckets', 1), 'bucket_mode_changed'),
])
def test_destination_changes_refuse_readonly_including_resumed_captureless_binding(source, change, code):
    original = initialization(source)
    restored = ManagedInitialization(json.loads(encoded(original.binding)))
    db = TargetDB(source)
    change(db)
    with pytest.raises(ValueError, match=code): restored.verify(db)
    assert not any(sql.startswith(('create ', 'alter ', 'drop ', 'grant ', 'revoke ')) for sql in db.calls)


def test_binding_requires_current_contract_and_exact_fields(source):
    binding = initialization(source).binding
    assert binding['contractSha256'] == CONTRACT_SHA
    for changed in [{**binding, 'contractSha256': '0' * 64}, {**binding, 'acceptUnknown': True},
            {**binding, 'preflightCatalogSha256': 'not-a-digest'}]:
        with pytest.raises(ValueError, match='binding_invalid'): ManagedInitialization(changed)


def test_source_function_grants_required_after_restoration_and_fresh_policy_inventory_closed(source):
    profile = initialization(source)
    db = TargetDB(source, fresh=True)
    with pytest.raises(ValueError, match='catalog_changed'): profile.verify(db)
    db.catalog['policies'].append(['storage', 'objects', 'unexpected', 'PERMISSIVE', ['anon'], 'SELECT', 'true', None])
    with pytest.raises(ValueError, match='catalog_changed'): profile.verify(db, fresh=True)


@pytest.mark.parametrize('requested', [None, 'accept-any-managed-profile'])
def test_config_v3_refuses_unknown_profile_before_credentials_or_target_access(tmp_path, requested):
    config = {'version': 3, 'designation': {}, 'credentials': 'must-not-read', 'ca': 'must-not-read',
        'caSha256': 'unused', 'work': 'unused', 'pgRestore': 'unused', 'capture': {},
        'managedInitialization': requested}
    path = tmp_path / 'config.json'
    path.write_bytes(encoded(config)); path.chmod(0o600)
    with pytest.raises(ValueError, match='source_unsupported'):
        execute(command='plan', config=path, expected_config_sha256=digest(path.read_bytes()))
