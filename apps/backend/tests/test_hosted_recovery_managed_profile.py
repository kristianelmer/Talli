"""Managed CLI history and existing provider policy authority, not a hosted proof."""
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from talli_backend.adapters.hosted_recovery_capture import ManagedCapture, digest
from talli_backend.adapters import hosted_recovery_provider as provider
from talli_backend.adapters.hosted_recovery_sql import compile_program, toc_entries
from test_hosted_backup_recovery import operator, private, repin, snapshot


@pytest.fixture
def managed_history(snapshot):
    profile = json.loads((snapshot['directory'] / 'source-profile.json').read_bytes())
    profile['tables'].append(['supabase_migrations', 'schema_migrations'])
    repin(snapshot, 'source-profile.json', profile)
    rows = json.loads((snapshot['directory'] / 'source-tables.private.json').read_bytes())
    rows['supabase_migrations.schema_migrations'] = {'rows': 2, 'sha256': digest(b'original history')}
    repin(snapshot, 'source-tables.private.json', rows)
    access = json.loads(snapshot['access'].read_bytes())
    access['access']['schemas'].append(['supabase_migrations', 'postgres', []])
    access['access']['relations'].append(['supabase_migrations', 'schema_migrations', 'r', 'postgres', []])
    private(snapshot['access'], access)
    snapshot['access_sha256'] = digest(snapshot['access'].read_bytes())
    return snapshot


def test_managed_capture_keeps_cli_history_in_application_import(managed_history):
    capture = ManagedCapture.open(**managed_history)
    assert provider.profile(capture) is None
    assert capture.application_schemas == {'public', 'supabase_migrations'}
    selected = []
    class Archive:
        entries = toc_entries('1; 2615 1 SCHEMA - public postgres\n'
            '2; 1259 2 TABLE public items postgres\n3; 0 2 TABLE DATA public items postgres\n'
            '4; 2615 4 SCHEMA - supabase_migrations postgres\n'
            '5; 1259 5 TABLE supabase_migrations schema_migrations postgres\n'
            '6; 0 5 TABLE DATA supabase_migrations schema_migrations postgres\n')
        def sql(self, entries, **kwargs):
            selected.extend(entries)
            return b''
    program = compile_program(capture, Archive())
    assert program.preserve_provider_constraints is False
    assert any(e.kind == 'SCHEMA' and e.tag == 'supabase_migrations' for e in selected)
    assert any(e.kind == 'TABLE DATA' and e.schema == 'supabase_migrations' for e in selected)


def test_native_history_alone_still_requires_full_native_prerequisite(managed_history):
    capture = ManagedCapture.open(**managed_history)
    capture = replace(capture, source_project='native:00000000-0000-4000-8000-000000000001')
    with pytest.raises(ValueError, match='profile_required'):
        provider.profile(capture)


@pytest.mark.parametrize('namespace', sorted(provider.SCHEMAS - {'supabase_migrations'}))
def test_managed_identity_cannot_reclassify_native_provider_objects(managed_history, namespace):
    capture = ManagedCapture.open(**managed_history)
    capture.catalog['rls'].append([namespace, 'hidden', False, False, 'postgres'])
    with pytest.raises(ValueError, match='profile_required'):
        provider.profile(capture)


def test_managed_capture_cannot_claim_native_profile(managed_history):
    capture = ManagedCapture.open(**managed_history)
    capture.profile['providerState'] = {'profile': provider.PROFILE}
    with pytest.raises(ValueError, match='profile_invalid'):
        provider.profile(capture)


POLICY = {'rls': [['storage', 'objects', True, False, 'supabase_storage_admin']],
    'policies': [['storage', 'objects', 'original', 'PERMISSIVE', ['authenticated'], 'SELECT', 'true', None]]}


class PolicyDB:
    def __init__(self, *, owner=False, grants=None):
        self.owner = owner
        self.grants = grants
        self.calls = []
    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return SimpleNamespace(fetchone=lambda: (self.owner,) if sql.startswith('select rolsuper') else self.grants)


def configured_grants(value=None, *, context='sighup', pending=False, role='postgres'):
    return role, json.dumps({'postgres': ['storage.objects']} if value is None else value), context, pending


def test_existing_provider_policy_grant_needs_no_owner_membership_or_mutation():
    db = PolicyDB(grants=configured_grants())
    provider.require_policy_authority(db, SimpleNamespace(catalog=POLICY), managed_policy_grants=True)
    assert len(db.calls) == 2
    assert all(sql.startswith('select ') for sql, _ in db.calls)
    assert "pg_settings" in db.calls[1][0] and 'set ' not in db.calls[1][0]


def test_native_owner_requirement_does_not_consult_managed_grants():
    db = PolicyDB(grants=configured_grants())
    with pytest.raises(ValueError, match='policy_owner_unavailable'):
        provider.require_policy_authority(db, SimpleNamespace(catalog=POLICY))
    assert len(db.calls) == 1


def test_actual_owner_does_not_need_a_provider_extension():
    db = PolicyDB(owner=True)
    provider.require_policy_authority(db, SimpleNamespace(catalog=POLICY), managed_policy_grants=True)
    assert len(db.calls) == 1


@pytest.mark.parametrize('row,code', [
    (None, 'policy_owner_unavailable'),
    (configured_grants({'postgres': ['storage.buckets']}), 'policy_owner_unavailable'),
    (configured_grants(role='other_role'), 'policy_owner_unavailable'),
    (configured_grants(context='user'), 'policy_grants_invalid'),
    (configured_grants(pending=True), 'policy_grants_invalid'),
    (('postgres', '{}', 'sighup', False), 'policy_owner_unavailable'),
    (('postgres', '{"postgres":[],"postgres":["storage.objects"]}', 'sighup', False), 'policy_grants_invalid'),
    (configured_grants({'postgres': 'storage.objects'}), 'policy_grants_invalid'),
    (configured_grants({'postgres': ['storage.*']}), 'policy_grants_invalid'),
    (('postgres', 'x' * 65537, 'sighup', False), 'policy_grants_invalid'),
])
def test_policy_grants_refuse_unknown_or_untrusted_authority(row, code):
    db = PolicyDB(grants=row)
    with pytest.raises(ValueError, match=code):
        provider.require_policy_authority(db, SimpleNamespace(catalog=POLICY), managed_policy_grants=True)
    assert all(sql.startswith('select ') for sql, _ in db.calls)


def test_managed_owner_preflight_refuses_before_ddl_or_copy(snapshot, tmp_path, monkeypatch):
    repin(snapshot, 'source-catalog.private.json', {'functions': [], 'constraints': [], 'indexes': [], **POLICY})
    instance, target = operator(snapshot, tmp_path, monkeypatch)
    original = target.db.execute
    def execute(sql, params=None, **kwargs):
        if 'from pg_settings' in sql:
            target.db.calls.append(sql)
            return SimpleNamespace(fetchone=lambda: None)
        return original(sql, params, **kwargs)
    monkeypatch.setattr(target.db, 'execute', execute)
    with pytest.raises(ValueError, match='policy_owner_unavailable'):
        instance.restore(expected_plan_sha256=instance.plan_sha)
    assert target.db.marker is None and target.db.ddl == 0
    assert not any(sql.lower().startswith(('create ', 'alter ', 'grant ', 'revoke ', 'update ', 'copy '))
        for sql in target.db.calls)
