"""Staging phase-fault models, not real provider/SQL/owner eligibility proofs.

Provider admission, private-control SQL and prepared-fact acquisition are explicit
fixture ports. Public restore/owner/inspect/contain orchestration, marker binding,
policy inventory, private request custody and CLI projection execute normally.
Real populated PostgreSQL, Storage and Auth acceptance runs separately.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from uuid import uuid4

import pytest

from talli_backend.adapters import hosted_backup_recovery as recovery
from talli_backend.adapters import hosted_recovery_operator as command
from talli_backend.adapters.hosted_recovery_capture import digest, encoded
from talli_backend.adapters.hosted_recovery_owner_policy import policy_contract, policy_status
from test_hosted_backup_recovery import Cursor, DatabaseModel, operator, private, snapshot
from test_hosted_recovery_owner_policy import native


class StageDatabase(DatabaseModel):
    """Committed marker plus independently mutable preparation observations."""
    def __init__(self, capture):
        super().__init__(capture)
        self.catalog = deepcopy(capture.catalog)
        self.catalog['policies'] = []
        self.actor = str(uuid4())
        self.banned = False
        self.lock_owner = None
        self.lock_available = True
        self.events = []
        self.copies = []
        self.drift = None
        self.private_control = True
        self.history_current = True
        self.lose_marker_commit = False
        self.quarantine_changes_other_fields = False

    def execute(self, text, params=None, **kwargs):
        if text.startswith('select id::text,plan_sha'):
            self.calls.append(text)
            return Cursor([deepcopy(self.marker)] if self.marker else [])
        if text.startswith('update ' + recovery.MARKER):
            self.calls.append(text)
            matches = self.marker is not None and self.marker[:4] == tuple(params[1:])
            if matches:
                self.pending = (*self.marker[:4], json.loads(params[0]))
            result = Cursor()
            result.rowcount = int(matches)
            return result
        if text == recovery.CATALOG_SQL:
            self.calls.append(text)
            return Cursor([(deepcopy(self.catalog),)])
        if 'select id from auth.users order by id' in text:
            self.calls.append(text)
            return Cursor([(self.actor,)])
        if text.startswith('update auth.users set banned_until='):
            self.calls.append(text)
            self.banned = True
            self.events.append('auth_ban')
            return Cursor()
        if text.startswith('select count(*)from auth.users where id=any'):
            self.calls.append(text)
            return Cursor([(int(not self.banned),)])
        if text.startswith("select (to_jsonb(t)-'banned_until')"):
            self.calls.append(text)
            changed = self.banned and self.quarantine_changes_other_fields
            return Cursor([('changed actor' if changed else 'original actor excluding ban',)])
        if 'from pg_constraint' in text:
            self.calls.append(text)
            return Cursor()
        return super().execute(text, params, **kwargs)

    def commit(self):
        self.events.append(('commit', self.lock_owner))
        has_marker = self.pending is not None
        if has_marker:
            self.marker, self.pending = deepcopy(self.pending), None
        if has_marker and self.lose_marker_commit:
            self.lose_marker_commit = False
            raise ConnectionError('synthetic lost marker commit response')

    def rollback(self):
        self.pending = None
        self.events.append('rollback')


class StageConnection:
    def __init__(self, database):
        self.model = database
        self.token = str(uuid4())

    def execute(self, text, params=None, **kwargs):
        if text == 'select pg_try_advisory_lock(%s)':
            assert params == (recovery.TARGET_LOCK,)
            allowed = self.model.lock_available and self.model.lock_owner is None
            if allowed:
                self.model.lock_owner = self.token
                self.model.events.append('lock')
            return Cursor([(allowed,)])
        if text == 'select pg_advisory_unlock(%s)':
            assert self.model.lock_owner == self.token
            self.model.lock_owner = None
            self.model.events.append('unlock')
            return Cursor([(True,)])
        return self.model.execute(text, params, **kwargs)

    def commit(self): self.model.commit()
    def rollback(self): self.model.rollback()
    def cursor(self): return self
    def copy(self, header):
        self.model.copies.append(header)
        return self
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def write(self, body): pass


class StageTarget:
    def __init__(self, original, model):
        self.designation = original.designation
        self.db = model
        self.uploads = []
        self.upload_hook = None
        self.identity = {'kind': 'owned-local-native-v2', 'target': str(uuid4()),
            'systemIdentifier': '7348112577', 'database': 'postgres',
            'databaseImage': 'sha256:' + 'd' * 64}

    def validate(self, **kwargs): pass
    def require_inert_provider_state(self, profile): return dict(self.identity)

    @contextmanager
    def database(self):
        connection = StageConnection(self.db)
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise

    def restore_object(self, obj, raw):
        assert self.db.lock_owner is not None
        assert self.db.catalog['policies'], 'uploads require actual policy readback'
        self.uploads.append(obj['name'])
        if self.upload_hook: self.upload_hook()
        return {**obj, 'servedExact': True}


@pytest.fixture
def staged(snapshot, tmp_path, monkeypatch):
    instance, original = operator(snapshot, tmp_path, monkeypatch)
    capture = instance.capture
    capture.catalog['rls'].append(['storage', 'objects', True, False, 'supabase_storage_admin'])
    capture.catalog['policies'].append(['storage', 'objects', 'original_read', 'PERMISSIVE',
        ['restore_runtime'], 'SELECT', 'true', None])
    capture.profile['tables'].append(['auth', 'users'])
    capture.rows['auth.users'] = {'rows': 1, 'sha256': digest(b'original Auth row')}
    body = b'ordinary synthetic private object'
    file = 'object-' + digest(body) + '.bin'
    private(capture.directory / file, body)
    capture.files[file] = {'bytes': len(body), 'sha256': digest(body)}
    object_fact = {'bucket': 'private-files', 'name': 'company/original.pdf',
        'file': file, 'bytes': len(body), 'sha256': digest(body)}
    instance.capture = replace(capture, objects=(object_fact,))
    program = replace(recovery.compile_program(capture, instance.archive),
        data=b'COPY public.items (id) FROM stdin;\n\\.\nCOPY auth.users (id) FROM stdin;\n1\n\\.\n',
        policies=native('CREATE POLICY original_read ON storage.objects FOR SELECT '
            'TO restore_runtime USING (true);'), preserve_provider_constraints=True)
    model = StageDatabase(instance.capture)
    target = StageTarget(original, model)
    instance.target = target
    instance.plan_body.update(version=3, privateObjects=1,
        providerState={'profile': recovery.OWNER_PROFILE}, ownerPolicy={
            'protocol': 'original-owner-policy-v1', 'targetIdentity': dict(target.identity),
            **policy_contract(instance.capture, program)})
    instance.plan_sha = digest(encoded(instance.plan_body))
    monkeypatch.setattr(recovery, 'compile_program', lambda *args: program)
    monkeypatch.setattr(instance, '_fresh', lambda *args: model.events.append('eligibility_fixture'))
    monkeypatch.setattr(recovery, 'restore_access', lambda *args, **kwargs: {'functions': 0})
    monkeypatch.setattr(recovery, 'row_commitments', lambda db, tables:
        {'.'.join(t): deepcopy(instance.capture.rows['.'.join(t)]) for t in tables})

    def verify_provider(db, captured, *, pending_managed_policies=False):
        policy_status(captured, model.catalog, allow_missing=pending_managed_policies)

    def prepared_facts(db, selected_program, tables):
        model.events.append('prepared_read')
        facts = {'tables': tables, 'rows': {'.'.join(t): deepcopy(instance.capture.rows['.'.join(t)])
            for t in tables}, 'sequences': [], 'rolesSha256': digest(b'original roles'),
            'catalogSha256': digest(b'catalog except named policies'),
            'accessSha256': digest(b'original table privileges'),
            'structureSha256': digest(b'original structural definitions'),
            'databaseAccessSha256': digest(b'original database privileges')}
        facts['rows']['auth.users']['sha256'] = digest(encoded({'banned': model.banned}))
        if model.drift == 'rows': facts['rows']['auth.users']['sha256'] = digest(b'changed Auth row')
        elif model.drift == 'sequences': facts['sequences'] = [[['public', 'items_seq'], 19, True]]
        elif model.drift: facts[model.drift] = digest(b'changed prepared fact')
        return facts

    monkeypatch.setattr(recovery, 'verify_provider_state', verify_provider)
    monkeypatch.setattr(instance, '_prepared_facts', prepared_facts)
    monkeypatch.setattr(instance, '_seal_control', lambda *args, **kwargs: None)
    monkeypatch.setattr(instance, '_private_control_current', lambda *args, **kwargs: model.private_control)
    monkeypatch.setattr(instance, '_history_current', lambda *args, **kwargs: model.history_current)
    return SimpleNamespace(operator=instance, target=target, db=model, program=program)


def restore(staged):
    return staged.operator.restore(expected_plan_sha256=staged.operator.plan_sha)


def install_original_policies(staged):
    staged.db.catalog['policies'] = deepcopy(staged.operator.capture.catalog['policies'])


def owner_step(staged, request):
    return staged.operator.owner_policy_request(expected_plan_sha256=staged.operator.plan_sha,
        expected_request_sha256=request['manifestSha256'])


def test_pending_checkpoint_is_committed_quarantined_and_has_no_uploads(staged):
    state = restore(staged)
    assert state['phase'] == 'awaiting_original_owner_policy' and state['ownerActionRequired'] is True
    assert state['publicationAuthorized'] is False and 'verification' not in state
    metadata = staged.db.marker[4]
    stage = metadata['ownerStage']
    assert stage['status'] == 'pending_owner_policy'
    assert stage['preparedSha256'] == digest(encoded(stage['prepared']))
    assert staged.db.banned and staged.db.enabled_logins == set()
    assert staged.target.uploads == [] and staged.db.lock_owner is None
    assert not any('CREATE POLICY' in sql or 'session_replication_role=' in sql for sql in staged.db.calls)
    assert Path(state['ownerRequest']['directory']).joinpath('policies.sql').is_file()


def test_pending_retry_reuses_checkpoint_and_exact_request_without_copying_again(staged):
    first = restore(staged)
    counts = (staged.db.ddl, len(staged.db.copies))
    second = restore(staged)
    assert second['ownerRequest'] == first['ownerRequest']
    assert (staged.db.ddl, len(staged.db.copies)) == counts
    assert staged.target.uploads == [] and staged.db.lock_owner is None


def test_pending_cli_exits_nonzero_and_projects_only_safe_request_fields(staged, monkeypatch, capsys):
    monkeypatch.setattr(command, 'execute', lambda **kwargs: restore(staged))
    code = command.main(['restore', '--config', '/unused/config', '--expected-config-sha256', 'a' * 64,
        '--expected-plan-sha256', staged.operator.plan_sha])
    result = json.loads(capsys.readouterr().out)
    assert code == 2 and result['phase'] == 'awaiting_original_owner_policy'
    assert result['ownerActionRequired'] is True and result['publicationAuthorized'] is False
    assert set(result['ownerRequest']) == {'directory', 'manifestSha256', 'policySha256'}
    assert 'binding' not in result['ownerRequest'] and 'sql' not in result['ownerRequest']
    assert staged.target.uploads == []


def test_owner_step_updates_quarantine_then_restore_resumes_without_import_replay(staged):
    pending = restore(staged)
    counts = (staged.db.ddl, len(staged.db.copies))
    with owner_step(staged, pending['ownerRequest']) as request:
        assert request['alreadyInstalled'] is False and staged.db.lock_owner is not None
        install_original_policies(staged)
    state = staged.operator._state()
    assert state['ownerActionRequired'] is False
    assert state['quarantine']['ownerStage']['status'] == 'policies_verified'
    assert staged.target.uploads == []
    finished = restore(staged)
    assert finished['phase'] == 'verified_quarantined'
    assert finished['verification']['originalManagedPoliciesInstalled'] is True
    assert (staged.db.ddl, len(staged.db.copies)) == counts
    assert len(staged.target.uploads) == 1
    with owner_step(staged, pending['ownerRequest']) as request:
        assert request['alreadyInstalled'] is True
    assert staged.operator._state()['phase'] == 'verified_quarantined'


def test_lost_importer_commit_reconciles_durable_marker_without_reimport(staged):
    staged.db.lose_marker_commit = True
    with pytest.raises(ConnectionError, match='lost marker commit'): restore(staged)
    assert staged.db.marker is not None and staged.db.lock_owner is None
    assert staged.operator._state()['phase'] == 'inspection_or_containment_required'
    counts = (staged.db.ddl, len(staged.db.copies))
    assert restore(staged)['phase'] == 'awaiting_original_owner_policy'
    assert (staged.db.ddl, len(staged.db.copies)) == counts and not staged.target.uploads


def test_unknown_owner_commit_is_reconciled_by_policy_readback(staged):
    pending = restore(staged)
    with pytest.raises(ConnectionError, match='owner response lost'):
        with owner_step(staged, pending['ownerRequest']):
            install_original_policies(staged)
            raise ConnectionError('owner response lost')
    assert staged.db.marker[4]['ownerStage']['status'] == 'pending_owner_policy'
    assert staged.db.lock_owner is None and not staged.target.uploads
    assert restore(staged)['phase'] == 'verified_quarantined'
    assert staged.db.marker[4]['ownerStage']['status'] == 'policies_verified'


@pytest.mark.parametrize('drift', ['rows', 'sequences', 'rolesSha256', 'catalogSha256',
    'accessSha256', 'structureSha256', 'databaseAccessSha256'])
def test_prepared_drift_stops_resume_before_owner_step_or_upload(staged, drift):
    pending = restore(staged)
    counts = (staged.db.ddl, len(staged.db.copies))
    staged.db.drift = drift
    with pytest.raises(ValueError, match='prepared_state_changed'): restore(staged)
    with pytest.raises(ValueError, match='prepared_state_changed'):
        with owner_step(staged, pending['ownerRequest']):
            pytest.fail('drift cannot enter the owner step')
    assert not staged.target.uploads and staged.db.lock_owner is None
    assert (staged.db.ddl, len(staged.db.copies)) == counts


@pytest.mark.parametrize('guard,code', [('private_control', 'control_acl_changed'),
    ('history_current', 'history_copy_changed')])
def test_control_and_history_guards_block_committed_marker_resume(staged, guard, code):
    restore(staged)
    setattr(staged.db, guard, False)
    with pytest.raises(ValueError, match=code): restore(staged)
    assert not staged.target.uploads and staged.db.lock_owner is None


def test_database_containment_wins_over_stale_local_pending_state(staged):
    restore(staged)
    state_path = staged.operator.work / 'state.json'
    stale = state_path.read_bytes()
    staged.operator.contain(expected_plan_sha256=staged.operator.plan_sha)
    assert staged.db.marker[4]['ownerStage']['status'] == 'contained'
    private(state_path, stale)
    counts = (staged.db.ddl, len(staged.db.copies))
    with pytest.raises(ValueError, match='already_contained'): restore(staged)
    assert (staged.db.ddl, len(staged.db.copies)) == counts and not staged.target.uploads
    # Capture-free inspection must use the DB's terminal phase, not stale JSON.
    clean = recovery.HostedBackupRecovery.from_state(target=staged.target, work=staged.operator.work,
        expected_plan_sha256=staged.operator.plan_sha)
    result = clean.inspect()
    assert result['phase'] == 'contained' and result['providerStateCurrent'] is None
    assert result['originalManagedPoliciesCurrent'] is None


def test_capture_loss_keeps_inspection_and_containment_without_owner_completion(staged):
    restore(staged)
    shutil.rmtree(staged.operator.capture.directory)
    clean = recovery.HostedBackupRecovery.from_state(target=staged.target, work=staged.operator.work,
        expected_plan_sha256=staged.operator.plan_sha)
    assert clean.inspect()['providerStateCurrent'] is None
    result = clean.contain(expected_plan_sha256=staged.operator.plan_sha)
    assert result['phase'] == 'contained' and not staged.target.uploads
    assert staged.db.marker[4]['ownerStage']['status'] == 'contained'


def test_busy_session_lock_refuses_before_preparation_or_state_creation(staged):
    staged.db.lock_available = False
    with pytest.raises(ValueError, match='target_busy'): restore(staged)
    assert not (staged.operator.work / 'state.json').exists()
    assert staged.db.ddl == 0 and not staged.target.uploads


def test_session_lock_survives_commit_and_excludes_competing_containment_during_upload(staged, tmp_path):
    restore(staged)
    install_original_policies(staged)
    competing_work = tmp_path / 'competing-operator'
    competing_work.mkdir(mode=0o700)
    private(competing_work / 'state.json', (staged.operator.work / 'state.json').read_bytes())
    competitor = recovery.HostedBackupRecovery.from_state(target=staged.target, work=competing_work,
        expected_plan_sha256=staged.operator.plan_sha)
    def compete():
        with pytest.raises(ValueError, match='target_busy'):
            competitor.contain(expected_plan_sha256=staged.operator.plan_sha)
    staged.target.upload_hook = compete
    assert restore(staged)['phase'] == 'verified_quarantined'
    assert any(isinstance(event, tuple) and event[0] == 'commit' and event[1] is not None
        for event in staged.db.events)
    assert staged.db.lock_owner is None


def test_quarantine_cannot_bless_changes_outside_the_original_ban_field(staged):
    staged.db.quarantine_changes_other_fields = True
    with pytest.raises(ValueError, match='quarantine_transformation_changed'): restore(staged)
    assert staged.db.marker is None and not staged.target.uploads
    assert not (staged.operator.work / 'original-owner-request').exists()


@pytest.mark.parametrize('fault,code', [('unknown', 'unexpected_policy'), ('conflict', 'definition_changed')])
def test_owner_completion_refuses_unknown_or_changed_actual_policies(staged, fault, code):
    pending = restore(staged)
    with pytest.raises(ValueError, match=code):
        with owner_step(staged, pending['ownerRequest']):
            install_original_policies(staged)
            staged.db.catalog['policies'][0][2 if fault == 'unknown' else 6] = 'changed'
    assert not staged.target.uploads and staged.db.lock_owner is None
