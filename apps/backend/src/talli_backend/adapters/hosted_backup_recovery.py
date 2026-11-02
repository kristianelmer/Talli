"""Opt-in managed logical restore under durable quarantine.

No scheduler, app factory, provider purchase, project lifecycle or publication
authority. The operator consumes an independently verified decrypted managed
capture. Native disposition bundles keep their existing replay/identity contract.
"""
from contextlib import contextmanager
import base64
import fcntl
import json
import os
from pathlib import Path
from uuid import UUID, uuid4
import re

from talli_backend.adapters.hosted_recovery_access import (
    ACCESS_SQL, CATALOG_SQL, DATABASE_ACCESS_SQL, restore_access, restore_database_access,
    row_commitments, verify_custom_roles,
)
from talli_backend.adapters.hosted_recovery_capture import (
    MANAGED_SCHEMAS, digest, encoded, normalized_access, normalized_catalog, private_read, qi, require,
)
from talli_backend.adapters.hosted_recovery_sql import (
    GUC, NativeArchive, compile_program, execute_batch, execute_data, verify_managed_triggers,
)
from talli_backend.adapters.hosted_recovery_provider import (
    SCHEMAS as PROVIDER_SCHEMAS,
    summary as provider_summary, verify as verify_provider_state,
    require_policy_authority,
)
from talli_backend.adapters.hosted_recovery_managed_initialization import ManagedInitialization

CONTROL = '_talli_recovery'
MARKER = CONTROL + '.attempt'
HISTORY = CONTROL + '.native_history'
BAN = '9999-12-31 00:00:00+00'
MAX_STATE = 256 * 1024
TARGET_LOCK = 725128419231
OWNER_PROFILE = 'talli-inert-native-provider-state-v2'
MANAGED_LIFECYCLE = {'version': 1, 'checkpoint': 'quarantined-rows-and-authority-v1',
    'containment': 'database-terminal-v1', 'serialization': 'session-advisory-lock-v1'}
PROVIDER_HISTORY = {('auth', 'schema_migrations'), ('storage', 'migrations'),
    ('realtime', 'schema_migrations')}


def _atomic(path, body):
    raw = encoded(body)
    require(len(raw) <= MAX_STATE, 'hosted_recovery_state_bound')
    temporary = path.parent / ('.state-' + uuid4().hex)
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


class HostedBackupRecovery:
    """Small operator interface: plan, restore/resume, inspect, contain.

    A durable DB marker commits atomically with imported data and Auth bans. A
    lost commit response is reconciled against that marker; native DDL is never
    replayed speculatively. Object uploads resume by exact hash readback.
    """
    def __init__(self, *, capture, target, work, pg_restore, managed_initialization=None):
        self.capture, self.target = capture, target
        self.work = Path(work).absolute()
        require(self.work.is_dir() and not self.work.is_symlink() and
            self.work.stat().st_uid == os.getuid() and not self.work.stat().st_mode & 0o077 and
            not any(p.is_symlink() for p in self.work.parents), 'hosted_work_directory_invalid')
        require(not (self.work.is_relative_to(capture.directory) or
            capture.directory.is_relative_to(self.work)), 'hosted_work_capture_overlap')
        credentials = getattr(target, 'credential_path', None)
        require(credentials is None or not Path(credentials).is_relative_to(self.work),
            'hosted_work_credentials_overlap')
        require(capture.source_project != target.designation.project and CONTROL not in capture.schemas,
            'hosted_source_target_same')
        self.disposition = capture.disposition
        if self.disposition is not None: self.disposition.require_external(self.work)
        self.archive = NativeArchive(capture, pg_restore=pg_restore, work=self.work)
        self.initialization = ManagedInitialization.from_capture(capture, self.archive,
            managed_initialization) if managed_initialization is not None else None
        self.plan_body = {'version': 1, 'sourceProject': capture.source_project,
            'captureSha256': capture.commitment, 'target': target.designation.body(),
            'engineMajor': 17, 'schemas': sorted(capture.schemas),
            'customRoles': sorted(r[0] for r in capture.custom_roles),
            'managedTables': sorted(t for t in capture.profile['tables'] if t[0] in MANAGED_SCHEMAS),
            'tables': len(capture.rows), 'privateObjects': len(capture.objects),
            'publicationAuthorized': False, 'authQuarantine': 'all recovered users banned',
            'runtimeQuarantine': 'all captured custom logins disabled',
            'deletionJournalPublicationAuthority': False}
        if self.disposition is not None:
            self.plan_body.update(version=2, sourceOrigin='owned-native-replayed',
                disposition=self.disposition.summary())
        provider = provider_summary(capture)
        if provider is not None:
            self.plan_body['providerState'] = provider
        if self.initialization is not None:
            require(provider is None and self.disposition is None,
                'hosted_managed_initialization_source_unsupported')
            self.plan_body.update(version=4, managedInitialization=self.initialization.binding)
        if provider is None and self.disposition is None and re.fullmatch('[a-z]{20}', capture.source_project):
            self.plan_body.update(version=5, managedLifecycle=dict(MANAGED_LIFECYCLE))
        if provider is not None and provider['profile'] == OWNER_PROFILE:
            from talli_backend.adapters.hosted_recovery_owner_policy import policy_contract
            capability = getattr(target, 'require_inert_provider_state', None)
            require(callable(capability), 'hosted_provider_target_composition_unsupported')
            identity = self._physical_identity(capability(provider))
            self.plan_body.update(version=3, ownerPolicy={
                'protocol': 'original-owner-policy-v1', 'targetIdentity': identity,
                **policy_contract(capture, compile_program(capture, self.archive))})
        self.plan_sha = digest(encoded(self.plan_body))

    @property
    def _owner_staged(self):
        return 'ownerPolicy' in self.plan_body

    @property
    def _managed_lifecycle(self):
        return 'managedLifecycle' in self.plan_body

    @property
    def _checkpointed(self):
        return self._owner_staged or self._managed_lifecycle

    @staticmethod
    def _physical_identity(value):
        require(isinstance(value, dict) and set(value) ==
            {'kind', 'target', 'systemIdentifier', 'database', 'databaseImage'} and
            value['kind'] == 'owned-local-native-v2' and value['database'] == 'postgres' and
            isinstance(value['systemIdentifier'], str) and
            re.fullmatch('[1-9][0-9]{0,19}', value['systemIdentifier']) and
            int(value['systemIdentifier']) < 2**64 and
            isinstance(value['databaseImage'], str) and
            re.fullmatch('sha256:[a-f0-9]{64}', value['databaseImage']),
            'hosted_owner_target_identity_required')
        try:
            valid_target = isinstance(value['target'], str) and str(UUID(value['target'])) == value['target']
        except ValueError:
            valid_target = False
        require(valid_target, 'hosted_owner_target_identity_required')
        return dict(value)

    @classmethod
    def from_state(cls, *, target, work, expected_plan_sha256, disposition=None):
        """Inspect/contain an attempt even after capture scratch loss.

        The independently held reviewed plan digest authenticates the private
        state plan; the target DB marker must match that same binding. Fresh
        rotated credentials may be supplied, but never a different destination.
        """
        self = cls.__new__(cls)
        self.work = Path(work).absolute()
        require(self.work.is_dir() and not self.work.is_symlink() and
            self.work.stat().st_uid == os.getuid() and not self.work.stat().st_mode & 0o077 and
            not any(p.is_symlink() for p in self.work.parents), 'hosted_work_directory_invalid')
        state = json.loads(private_read(self.work / 'state.json', MAX_STATE))
        require(digest(encoded(state['plan'])) == expected_plan_sha256 and
            state['plan']['target'] == target.designation.body(), 'hosted_reviewed_plan_changed')
        self.capture, self.target = None, target
        self.disposition = disposition
        self.plan_body, self.plan_sha = state['plan'], expected_plan_sha256
        binding = self.plan_body.get('managedInitialization')
        self.initialization = ManagedInitialization(binding) if binding is not None else None
        require(binding is None or 'providerState' not in self.plan_body and
            'disposition' not in self.plan_body and self.plan_body.get('version') in (4, 5),
            'hosted_managed_initialization_binding_invalid')
        lifecycle = self.plan_body.get('managedLifecycle')
        require((lifecycle is None and self.plan_body.get('version') != 5) or
            lifecycle == MANAGED_LIFECYCLE and 'providerState' not in self.plan_body and
            'disposition' not in self.plan_body and self.plan_body.get('version') == 5 and
            re.fullmatch('[a-z]{20}', self.plan_body['sourceProject']),
            'hosted_managed_lifecycle_binding_invalid')
        return self

    @contextmanager
    def _lock(self):
        descriptor = os.open(self.work / 'operator.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally: os.close(descriptor)

    @contextmanager
    def _target_command_lock(self):
        """Serialize the owner handoff, uploads and terminal containment.

        A session lock survives commits and fresh snapshots. The owner connects
        separately while this original importer connection holds the lock; no
        owner credential or privileged executor enters the importer.
        """
        if not self._checkpointed:
            yield
            return
        self._validate(capture_required=False)
        with self.target.database() as db:
            require(db.execute('select pg_try_advisory_lock(%s)', (TARGET_LOCK,)).fetchone()[0],
                'hosted_recovery_target_busy')
            db.commit()
            try:
                yield
            finally:
                db.rollback()
                db.execute('select pg_advisory_unlock(%s)', (TARGET_LOCK,))
                db.commit()

    def _verify_provider(self, db, *, pending=False, fresh=False):
        if self._owner_staged:
            verify_provider_state(db, self.capture, pending_managed_policies=pending)
        else:
            verify_provider_state(db, self.capture)
        if self.initialization is not None:
            self.initialization.verify(db, fresh=fresh)

    def _validate(self, *, capture_required=True):
        if 'providerState' in self.plan_body:
            # An ordinary managed connection cannot attest service isolation or
            # transfer provider keys. Only an explicitly owned inert transport
            # can supply this capability; absence refuses before hosted calls.
            isolation = getattr(self.target, 'require_inert_provider_state', None)
            require(callable(isolation), 'hosted_provider_target_composition_unsupported')
            identity = isolation(self.plan_body['providerState'])
            if self._owner_staged:
                require(self._physical_identity(identity) == self.plan_body['ownerPolicy']['targetIdentity'],
                    'hosted_owner_target_identity_changed')
        # Re-read every bound member before a command, not just construction.
        if capture_required and self.capture is not None:
            for name in self.capture.files: self.capture.read(name)
            if self.disposition is not None: self.disposition.check_current()
        return self.target.validate(source_project=self.plan_body['sourceProject'],
            captured_at=self.capture.profile.get('capturedAt')
                if capture_required and self.capture is not None else None)

    def plan(self):
        self._validate()
        require(self.capture.database_access is not None, 'hosted_database_acl_profile_required')
        return {**self.plan_body, 'planSha256': self.plan_sha,
            'sourceAccessObservationIsSeparate': True,
            'authority': 'review this digest; restore requires its explicit value'}

    def _state(self, *, create=False):
        path = self.work / 'state.json'
        if not path.exists():
            require(create, 'hosted_recovery_state_unavailable')
            state = {'version': 1, 'id': str(uuid4()), 'planSha256': self.plan_sha,
                'captureSha256': self.capture.commitment, 'target': self.target.designation.body(),
                'plan': self.plan_body, 'phase': 'prepared', 'objects': [], 'publicationAuthorized': False}
            _atomic(path, state)
        state = json.loads(private_read(path, MAX_STATE))
        require(state['version'] == 1 and state['planSha256'] == self.plan_sha and
            state['captureSha256'] == self.plan_body['captureSha256'] and
            state['plan'] == self.plan_body and digest(encoded(state['plan'])) == self.plan_sha and
            state['target'] == self.target.designation.body() and state['publicationAuthorized'] is False,
            'hosted_recovery_state_binding_changed')
        return state

    def _save(self, state, phase):
        state['phase'] = phase
        _atomic(self.work / 'state.json', state)

    def _marker(self, db, state):
        if db.execute('select to_regclass(%s)', (MARKER,)).fetchone()[0] is None:
            return None
        rows = db.execute('select id::text,plan_sha,capture_sha,target_ref,metadata from ' + MARKER).fetchall()
        require(len(rows) == 1 and rows[0][:4] == (state['id'], self.plan_sha,
            self.plan_body['captureSha256'], self.target.designation.project), 'hosted_recovery_marker_changed')
        return rows[0][4]

    def _update_marker(self, db, state, metadata):
        require(len(encoded(metadata)) <= MAX_STATE, 'hosted_recovery_state_bound')
        changed = db.execute('update ' + MARKER + ' set metadata=%s::jsonb where id=%s and '
            'plan_sha=%s and capture_sha=%s and target_ref=%s', (json.dumps(metadata), state['id'],
                self.plan_sha, self.plan_body['captureSha256'], self.target.designation.project))
        require(changed.rowcount == 1, 'hosted_recovery_marker_changed')

    def _owner_binding(self, state, metadata):
        require(self._owner_staged and metadata.get('ownerStage', {}).get('version') == 1,
            'hosted_owner_stage_invalid')
        stage = metadata['ownerStage']
        require(stage.get('status') in ('pending_owner_policy', 'policies_verified', 'contained') and
            digest(encoded(stage['prepared'])) == stage['preparedSha256'], 'hosted_owner_stage_invalid')
        return {'version': 1, 'attemptId': state['id'], 'planSha256': self.plan_sha,
            'captureSha256': self.plan_body['captureSha256'],
            'preparedSha256': stage['preparedSha256'],
            'policySha256': self.plan_body['ownerPolicy']['policySha256'],
            'target': self.plan_body['target'],
            'targetIdentity': self.plan_body['ownerPolicy']['targetIdentity']}

    @staticmethod
    def _auth_projection(db):
        # The original full rows were checked first. Only banned_until may
        # change while making the checkpoint; a trigger cannot hide extra work.
        rows = [r[0] for r in db.execute("select (to_jsonb(t)-'banned_until')::text from auth.users t "
            "order by (to_jsonb(t)-'banned_until')::text collate \"C\"")]
        require(len(rows) <= 256 and sum(len(r.encode()) for r in rows) <= 64 * 1024**2,
            'hosted_recovery_actor_bound')
        return digest(encoded(rows))

    def _prepared_facts(self, db, program, tables):
        """Recompute the quarantine checkpoint without retaining extra access."""
        from talli_backend.adapters.native_managed_handoff import ROLES_SQL
        from talli_backend.adapters.hosted_recovery_provider import SQL as STRUCTURE_SQL
        from talli_backend.adapters.hosted_recovery_owner_policy import policy_status
        execute_batch(db, GUC.encode())
        verify_custom_roles(db, self.capture)
        self._verify_provider(db, pending=True)
        roles = self._checkpoint_roles(db, ROLES_SQL)
        role_sha = digest(encoded(roles))
        database_access = db.execute(DATABASE_ACCESS_SQL).fetchone()[0]
        database_access['grants'] = sorted(database_access['grants'], key=encoded)
        expected_database_access = {**self.capture.database_access,
            'grants': sorted(self.capture.database_access['grants'], key=encoded)}
        require(database_access == expected_database_access, 'hosted_database_acl_changed')
        scope = sorted(self.capture.schemas | {'auth', 'storage'})
        catalog = db.execute(CATALOG_SQL).fetchone()[0]
        catalog = normalized_catalog(catalog, set(scope))
        if self._owner_staged:
            policy_status(self.capture, catalog, allow_missing=True)
            # Only these inventoried policies vary at the native owner seam.
            catalog['policies'] = [r for r in catalog['policies'] if r[0] not in ('auth', 'storage')]
        access = normalized_access(db.execute(ACCESS_SQL, (scope, scope)).fetchone()[0])
        structure = db.execute(STRUCTURE_SQL, (scope,) * 5).fetchone()[0]
        # Original ADMIN authority may be needed to read cross-owned rows. The
        # same bounded role program already used for import is restored before
        # returning, and its original grantor/options are verified again.
        with db.transaction():
            if self._managed_lifecycle:
                # Managed roles already exist. Replaying CREATE ROLE would
                # fail; borrow only the original creator's bounded ADMIN grant.
                roles_to_read = ','.join(qi(role[0]) for role in self.capture.custom_roles)
                if roles_to_read:
                    db.execute('grant ' + roles_to_read + ' to postgres with inherit true,set true')
            else:
                execute_batch(db, program.roles)
            rows = row_commitments(db, tables)
            sequences = [[names, *db.execute('select last_value,is_called from ' +
                qi(names[0]) + '.' + qi(names[1])).fetchone()] for names, _, _ in program.sequences]
            execute_batch(db, program.final_memberships)
        verify_custom_roles(db, self.capture)
        require(digest(encoded(self._checkpoint_roles(db, ROLES_SQL))) == role_sha,
            'hosted_owner_role_graph_changed')
        return {'tables': tables, 'rows': rows, 'sequences': sequences,
            'rolesSha256': role_sha, 'catalogSha256': digest(encoded(catalog)),
            'accessSha256': digest(encoded(access)), 'structureSha256': digest(encoded(structure)),
            'databaseAccessSha256': digest(encoded(database_access))}

    def _checkpoint_roles(self, db, query):
        roles = db.execute(query).fetchone()[0]
        if self._managed_lifecycle:
            # The designated CLI login can be renewed while recovering. Only
            # its expiry is credential custody; flags and every membership stay
            # bound. Password material is never part of this catalog.
            for row in roles['roles']:
                if row[0] == 'cli_login_postgres':
                    row[9] = 'rotatable-target-cli-expiry'
        return roles

    def _checkpoint_stage(self, state, metadata):
        if self._owner_staged:
            self._owner_binding(state, metadata)
            return metadata['ownerStage']
        require(self._managed_lifecycle and isinstance(metadata, dict),
            'hosted_managed_checkpoint_invalid')
        stage = metadata.get('managedStage')
        require(isinstance(stage, dict) and set(stage) ==
            {'version', 'status', 'prepared', 'preparedSha256'} and stage['version'] == 1 and
            stage['status'] in ('quarantined', 'contained') and
            digest(encoded(stage['prepared'])) == stage['preparedSha256'],
            'hosted_managed_checkpoint_invalid')
        return stage

    def _verify_prepared(self, db, state, metadata, program):
        stage = self._checkpoint_stage(state, metadata)
        require(stage['status'] != 'contained', 'hosted_recovery_already_contained')
        require(self._private_control_current(db), 'hosted_control_acl_changed')
        require(self._history_current(db, metadata), 'hosted_disposition_history_copy_changed')
        prepared = stage['prepared']
        from talli_backend.adapters.hosted_recovery_sql import copy_parts
        copied = {value[0] for kind, value in copy_parts(program.data) if kind == 'copy'}
        expected_tables = [t for t in self.capture.profile['tables'] if '.'.join(t) in copied or t[0] == 'auth']
        require(prepared['tables'] == expected_tables and len(expected_tables) == metadata['tablesCompared'],
            'hosted_owner_prepared_inventory_changed')
        require(self._prepared_facts(db, program, expected_tables) == prepared,
            'hosted_owner_prepared_state_changed')

    def _policy_ready(self, state, program):
        """Read actual owner work; a private receipt never authorizes uploads."""
        from talli_backend.adapters.hosted_recovery_owner_policy import policy_status
        with self.target.database() as db:
            metadata = self._marker(db, state)
            require(metadata is not None, 'hosted_recovery_marker_unavailable')
            self._quarantined(db, metadata)
            self._verify_prepared(db, state, metadata, program)
            require(self._history_current(db, metadata), 'hosted_disposition_history_copy_changed')
            missing = policy_status(self.capture, db.execute(CATALOG_SQL).fetchone()[0], allow_missing=True)
            if missing:
                require(metadata['ownerStage']['status'] == 'pending_owner_policy',
                    'hosted_owner_policy_inventory_changed')
                return False, metadata
            self._verify_provider(db)
            metadata['ownerStage']['status'] = 'policies_verified'
            self._update_marker(db, state, metadata)
            db.commit()
            return True, metadata

    @contextmanager
    def owner_policy_request(self, *, expected_plan_sha256, expected_request_sha256):
        """Guard a separate original owner's step without receiving its credential.

        Caller performs only the exported policy SQL on its independently bound
        owner connection. The original importer serializes this interval against
        restore/contain and verifies fresh database facts after the caller exits.
        """
        require(expected_plan_sha256 == self.plan_sha and self._owner_staged,
            'hosted_reviewed_plan_changed')
        from talli_backend.adapters.hosted_recovery_owner_policy import read_request, policy_status
        with self._lock(), self._target_command_lock():
            self._validate()
            state = self._state()
            require(state['phase'] != 'contained', 'hosted_recovery_already_contained')
            program = compile_program(self.capture, self.archive)
            with self.target.database() as db:
                metadata = self._marker(db, state)
                require(metadata is not None, 'hosted_recovery_marker_unavailable')
                self._verify_prepared(db, state, metadata, program)
                self._quarantined(db, metadata)
                binding = self._owner_binding(state, metadata)
                missing = policy_status(self.capture, db.execute(CATALOG_SQL).fetchone()[0], allow_missing=True)
            request = state.get('ownerRequest')
            require(isinstance(request, dict) and request.get('manifestSha256') == expected_request_sha256 and
                Path(request['directory']) == self.work / 'original-owner-request',
                'hosted_owner_request_changed')
            manifest, raw = read_request(Path(request['directory']), expected_request_sha256, binding=binding)
            yield {'manifest': manifest, 'sql': raw, 'alreadyInstalled': not missing}
            self._validate()
            ready, metadata = self._policy_ready(state, program)
            require(ready, 'hosted_owner_policy_required')
            state['quarantine'] = metadata
            state['ownerActionRequired'] = False
            self._save(state, 'verified_quarantined' if state['phase'] == 'verified_quarantined'
                else 'database_quarantined')

    def _fresh(self, db, program):
        capture = self.capture
        require(self._empty_namespace(db), 'hosted_target_not_empty')
        facts = db.execute("select current_setting('server_version_num')::integer,d.datlocprovider,"
            "pg_encoding_to_char(d.encoding),d.datcollate,d.datctype,"
            "coalesce(to_jsonb(d)->>'datlocale',to_jsonb(d)->>'daticulocale',''),"
            "pg_get_userbyid(d.datdba) from pg_database d where datname='postgres'").fetchone()
        require(list(facts) == capture.profile['facts'], 'hosted_database_profile_changed')
        extensions = db.execute('select e.extname,e.extversion,pg_get_userbyid(e.extowner),n.nspname '
            'from pg_extension e join pg_namespace n on n.oid=e.extnamespace order by e.extname').fetchall()
        if self.initialization is None:
            require([list(row) for row in extensions] == capture.profile['extensions'],
                'hosted_extension_profile_changed')
        self._verify_provider(db, pending=self._owner_staged, fresh=True)
        if 'providerState' in self.plan_body or self.initialization is not None:
            require(db.execute("select current_setting('session_replication_role')").fetchone()[0] == 'origin',
                'hosted_provider_origin_mode_required')
        if self.initialization is not None:
            require(program.preserve_provider_constraints, 'hosted_provider_origin_mode_required')
        if not self._owner_staged:
            require_policy_authority(db, capture,
                managed_policy_grants='providerState' not in self.plan_body)
        require(all(db.execute('select to_regnamespace(%s)', (name,)).fetchone()[0] is None
            for name in capture.application_schemas if name != 'public'), 'hosted_target_not_empty')
        require(db.execute('select count(*)from auth.users').fetchone()[0] == 0 and
            db.execute('select count(*)from storage.objects').fetchone()[0] == 0 and
            db.execute('select count(*)from storage.buckets').fetchone()[0] == 0,
            'hosted_target_not_empty')
        require(db.execute("select count(*)from pg_tables where schemaname='public'").fetchone()[0] == 0,
            'hosted_target_not_empty')
        if 'providerState' in self.plan_body:
            verify_custom_roles(db, capture)
        else:
            require(db.execute('select count(*)from pg_roles where rolname=any(%s)',
                (self.plan_body['customRoles'],)).fetchone()[0] == 0, 'hosted_target_not_empty')
        current = db.execute(CATALOG_SQL).fetchone()[0]
        # Definitions and RLS must match before importing into provider tables.
        # Custom policies are intentionally restored separately, not overwritten.
        left = normalized_catalog(capture.catalog, {'auth', 'storage'})
        right = normalized_catalog(current, {'auth', 'storage'})
        if self.initialization is None:
            for key in ('constraints', 'functions', 'indexes', 'rls'):
                require(left[key] == right[key], 'hosted_managed_schema_profile_changed')
            verify_managed_triggers(db, program.managed_triggers)

    def _uncommitted(self, db):
        """No marker may mean rollback, never permission to reuse unrelated data."""
        require(self._empty_namespace(db) and
            db.execute('select count(*)from storage.objects').fetchone()[0] == 0 and
            db.execute('select count(*)from storage.buckets').fetchone()[0] == 0 and
            all(db.execute('select to_regnamespace(%s)', (name,)).fetchone()[0] is None
            for name in self.plan_body['schemas'] if name != 'public' and
                (name not in PROVIDER_SCHEMAS or 'providerState' not in self.plan_body)) and
            db.execute('select count(*)from auth.users').fetchone()[0] == 0 and
            db.execute('select count(*)from pg_roles where rolname=any(%s)',
                (self.plan_body['customRoles'],)).fetchone()[0] ==
                (len(self.plan_body['customRoles']) if 'providerState' in self.plan_body else 0) and
            db.execute("select count(*)from pg_tables where schemaname='public'").fetchone()[0] == 0,
            'hosted_recovery_marker_unavailable')

    def _empty_namespace(self, db):
        # A new project containing an unrelated schema is not an empty target.
        # Database ACL changes affect the whole database, beyond captured names.
        provider = self.plan_body.get('providerState')
        allowed = MANAGED_SCHEMAS | {'public'} | (PROVIDER_SCHEMAS if provider else set())
        foreign = db.execute("select count(*)from pg_namespace where nspname !~ '^pg_' "
            "and nspname<>'information_schema' and nspname<>all(%s)",
            (sorted(allowed),)).fetchone()[0]
        public = db.execute("select (select count(*)from pg_class c join pg_namespace n "
            "on n.oid=c.relnamespace where n.nspname='public')+"
            "(select count(*)from pg_proc p join pg_namespace n on n.oid=p.pronamespace "
            "where n.nspname='public')+(select count(*)from pg_type t join pg_namespace n "
            "on n.oid=t.typnamespace where n.nspname='public')").fetchone()[0]
        if foreign or public:
            return False
        if provider:
            # Markerless reconciliation must enforce the same original state,
            # including when the capture scratch has been lost. Do not call an
            # unrelated populated provider namespace an empty rollback.
            if self.capture is None:
                return False
            self._verify_provider(db, pending=self._owner_staged)
            verify_custom_roles(db, self.capture)
        expected = self.plan_body.get('managedTables')
        require(expected is not None, 'hosted_recovery_plan_profile_unsupported')
        managed = db.execute('select n.nspname,c.relname from pg_class c join pg_namespace n '
            "on n.oid=c.relnamespace where n.nspname=any(%s)and c.relkind in('r','p','f','m')",
            (sorted(MANAGED_SCHEMAS),)).fetchall()
        if {tuple(t) for t in expected} != set(managed):
            return False
        # Provider-owned migration rows are preserved. Every other managed
        # table, including Vault and extensions, must be empty before import or
        # before a markerless attempt can be classified as rolled back.
        for schema, table in managed:
            if (schema, table) not in PROVIDER_HISTORY and db.execute(
                    'select exists(select 1 from ' + qi(schema) + '.' + qi(table) + ' limit 1)').fetchone()[0]:
                return False
        return True

    def _quarantine(self, db, metadata):
        if metadata['actors']:
            db.execute('update auth.users set banned_until=%s where id=any(%s::uuid[])',
                (BAN, metadata['actors']))
        # Exact NOLOGIN prerequisites need no ALTER ROLE authority. Containment
        # changes only roles which have actually become enabled.
        enabled = db.execute('select rolname from pg_roles where rolname=any(%s)and rolcanlogin',
            (metadata['logins'],)).fetchall()
        for name, in enabled:
            db.execute('alter role ' + qi(name) + ' nologin')

    def _quarantined(self, db, metadata):
        require(metadata is not None, 'hosted_recovery_marker_unavailable')
        users = db.execute('select count(*)from auth.users where id=any(%s::uuid[]) and '
            '(banned_until is null or banned_until<%s::timestamptz)', (metadata['actors'], BAN)).fetchone()[0]
        logins = db.execute('select count(*)from pg_roles where rolname=any(%s)and rolcanlogin',
            (metadata['logins'],)).fetchone()[0]
        require(users == 0 and logins == 0, 'hosted_quarantine_changed')

    @staticmethod
    def _history_facts(rows):
        facts = []; total = 0
        for path, body in rows:
            raw = bytes(body); total += len(raw)
            require(len(facts) < 256 and total <= 16 * 1024**2,
                'hosted_disposition_history_inventory_invalid')
            facts.append({'path': path, 'bytes': len(raw), 'sha256': digest(raw)})
        facts.sort(key=lambda f: f['path'])
        return {'nativeHistoryFiles': len(facts), 'nativeHistorySha256': digest(encoded(facts))}

    def _control_objects(self):
        objects = [('schema', CONTROL)] + [('table', MARKER)]
        if 'disposition' in self.plan_body:
            objects.append(('table', HISTORY))
        return objects

    def _control_acl(self, kind, identity):
        if kind == 'schema':
            return ("select nspowner,nspacl from pg_namespace where nspname='" + identity + "'")
        return ("select relowner,relacl from pg_class where oid='" + identity + "'::regclass")

    def _private_control_current(self, db, *, allow_missing_history=False):
        for kind, identity in self._control_objects():
            if identity == HISTORY and db.execute('select to_regclass(%s)', (HISTORY,)).fetchone()[0] is None:
                if allow_missing_history: continue
                return False
            query = self._control_acl(kind, identity)
            if db.execute("select count(*)from (" + query + ")o(owner,acl) where "
                    "owner<>'postgres'::regrole or exists(select 1 from aclexplode(acl)a "
                    "where a.grantee<>owner)").fetchone()[0]:
                return False
            if kind == 'table' and db.execute("select count(*)from pg_attribute where attrelid='" +
                    identity + "'::regclass and attacl is not null and exists(select 1 from "
                    "aclexplode(attacl)a where a.grantee<>'postgres'::regrole)").fetchone()[0]:
                return False
        return True

    def _seal_control(self, db, *, allow_missing_history=False):
        # Containment uses only pinned state and fixed control identities. It
        # remains available after capture, journal or proof loss.
        for kind, identity in self._control_objects():
            if identity == HISTORY and allow_missing_history and db.execute(
                    'select to_regclass(%s)', (HISTORY,)).fetchone()[0] is None:
                continue
            db.execute('alter ' + kind + ' ' + identity + ' owner to postgres')
            query = self._control_acl(kind, identity)
            grants = db.execute("select distinct case when a.grantee=0 then 'PUBLIC' else "
                "pg_get_userbyid(a.grantee)end from (" + query + ")o(owner,acl) cross join lateral "
                "aclexplode(acl)a where a.grantee<>owner").fetchall()
            for name, in grants:
                db.execute('revoke all on ' + kind + ' ' + identity + ' from ' +
                    ('PUBLIC' if name == 'PUBLIC' else qi(name)) + ' cascade')
            if kind == 'table':
                grants = db.execute("select distinct attname,case when a.grantee=0 then 'PUBLIC' "
                    "else pg_get_userbyid(a.grantee)end from pg_attribute cross join lateral "
                    "aclexplode(attacl)a where attrelid='" + identity + "'::regclass "
                    "and a.grantee<>'postgres'::regrole").fetchall()
                for column, name in grants:
                    db.execute('revoke all(' + qi(column) + ')on table ' + identity + ' from ' +
                        ('PUBLIC' if name == 'PUBLIC' else qi(name)) + ' cascade')

    def _history_current(self, db, metadata):
        if 'nativeHistorySha256' not in metadata:
            return 'disposition' not in self.plan_body
        if not self._private_control_current(db):
            return False
        count, size, largest, path_size = db.execute('select count(*),coalesce(sum(octet_length(payload)),0),'
            'coalesce(max(octet_length(payload)),0),coalesce(max(octet_length(path)),0)from ' + HISTORY).fetchone()
        if count > 256 or size > 16 * 1024**2 or largest > 8 * 1024**2 or path_size > 2048:
            return False
        rows = db.execute('select path,payload from ' + HISTORY +
            ' order by path collate "C" limit 257').fetchall()
        return self._history_facts(rows) == {k: metadata[k] for k in
            ('nativeHistoryFiles', 'nativeHistorySha256')}

    def _restore_database(self, state, program):
        with self.target.database() as db:
            if not self._checkpointed:
                require(db.execute('select pg_try_advisory_xact_lock(725128419231)').fetchone()[0],
                    'hosted_recovery_target_busy')
            marker = self._marker(db, state)
            if marker is not None:
                if self._checkpointed:
                    self._verify_prepared(db, state, marker, program)
                self._verify_provider(db, pending=self._owner_staged)
                if 'providerState' in self.plan_body:
                    verify_custom_roles(db, self.capture)
                self._quarantined(db, marker)
                require(self._history_current(db, marker), 'hosted_disposition_history_copy_changed')
                state['quarantine'] = marker
                return marker
            self._fresh(db, program)
            execute_batch(db, GUC.encode())
            if not program.preserve_provider_constraints:
                db.execute('set session_replication_role=replica')
            execute_batch(db, program.roles)
            restore_database_access(db, self.capture.database_access)
            execute_batch(db, program.schemas)
            execute_batch(db, program.temporary_create)
            execute_batch(db, program.definitions)
            copied = execute_data(db, program.data, self.capture.rows,
                order_by_foreign_keys=program.preserve_provider_constraints)
            execute_batch(db, program.post_data)
            # Include managed sequence counters even though managed table/schema
            # definitions and migration history remain provider-owned.
            for (schema, name), value, called in program.sequences:
                db.execute('select pg_catalog.setval(%s::regclass,%s,%s)',
                    (schema + '.' + name, value, called))
                actual = db.execute('select last_value,is_called from ' + qi(schema) + '.' + qi(name)).fetchone()
                require(actual == (value, called), 'hosted_sequence_payload_changed')
            if not self._owner_staged:
                execute_batch(db, program.policies)
            execute_batch(db, program.remove_temporary_create)
            execute_batch(db, program.acl)
            if not self._owner_staged:
                execute_batch(db, program.extension_usage)
            # Keep temporary owner inheritance through byte verification. The
            # captured postgres membership can intentionally disable both
            # INHERIT and SET, including access to cross-owned schemas.
            if self._owner_staged:
                repairs = restore_access(db, self.capture, b'', pending_managed_policies=True)
            elif self.initialization is not None:
                repairs = restore_access(db, self.capture, b'', managed_initialization=self.initialization)
            else:
                repairs = restore_access(db, self.capture, b'')
            self._verify_provider(db, pending=self._owner_staged)
            # Mutable provider migration timestamps and future uploaded Storage
            # transport identities are explicit differences, not wildcard skips.
            compared = [t for t in self.capture.profile['tables'] if '.'.join(t) in copied or
                t[0] == 'auth']
            observed = row_commitments(db, compared)
            require(observed == {'.'.join(t): self.capture.rows['.'.join(t)] for t in compared},
                'hosted_restored_table_bytes_changed')
            execute_batch(db, program.final_memberships)
            actors = [str(r[0]) for r in db.execute('select id from auth.users order by id')]
            logins = [r[0] for r in self.capture.custom_roles
                if r[5] or 'providerState' in self.plan_body]
            metadata = {'actors': actors, 'logins': logins, 'repairs': repairs,
                'tablesCompared': len(compared), 'sequenceCounters': len(program.sequences),
                'publicationAuthorized': False}
            state['quarantine'] = metadata
            self._save(state, 'database_outcome_pending')
            auth_before = self._auth_projection(db) if self._checkpointed else None
            self._quarantine(db, metadata)
            self._quarantined(db, metadata)
            if self._checkpointed:
                require(self._auth_projection(db) == auth_before, 'hosted_owner_quarantine_transformation_changed')
            verify_custom_roles(db, self.capture)
            db.execute('create schema ' + CONTROL + ' authorization postgres')
            db.execute('revoke all on schema ' + CONTROL + ' from public')
            if self.disposition is not None:
                db.execute('create table ' + HISTORY + '(path text primary key,payload bytea not null)')
                native_rows = [(item['path'], base64.b64decode(item['base64'], validate=True))
                    for item in self.capture.native_history]
                for row in native_rows:
                    db.execute('insert into ' + HISTORY + ' values(%s,%s)', row)
                metadata.update(self._history_facts(native_rows))
            db.execute('create table ' + MARKER + '(id uuid primary key,plan_sha text not null,'
                'capture_sha text not null,target_ref text not null,metadata jsonb not null)')
            db.execute('revoke all on table ' + MARKER + ' from public,anon,authenticated,service_role')
            self._seal_control(db)
            require(self._history_current(db, metadata), 'hosted_disposition_history_copy_changed')
            if self._checkpointed:
                prepared = self._prepared_facts(db, program, compared)
                key = 'ownerStage' if self._owner_staged else 'managedStage'
                metadata[key] = {'version': 1,
                    'status': 'pending_owner_policy' if self._owner_staged else 'quarantined',
                    'prepared': prepared, 'preparedSha256': digest(encoded(prepared))}
                state['quarantine'] = metadata
                self._save(state, 'database_outcome_pending')
            db.execute('insert into ' + MARKER + ' values(%s,%s,%s,%s,%s::jsonb)',
                (state['id'], self.plan_sha, self.capture.commitment,
                 self.target.designation.project, json.dumps(metadata)))
            if not program.preserve_provider_constraints:
                db.execute('set session_replication_role=origin')
            db.commit()
            return metadata

    def restore(self, *, expected_plan_sha256):
        require(expected_plan_sha256 == self.plan_sha, 'hosted_reviewed_plan_changed')
        with self._lock(), self._target_command_lock():
            self._validate()
            require(self.capture.database_access is not None, 'hosted_database_acl_profile_required')
            state = self._state(create=True)
            require(state['phase'] != 'contained', 'hosted_recovery_already_contained')
            try:
                program = compile_program(self.capture, self.archive,
                    preserve_managed_constraints=True) if self.initialization is not None else \
                    compile_program(self.capture, self.archive)
                self._save(state, 'database_outcome_pending')
                metadata = self._restore_database(state, program)
                if self._owner_staged:
                    ready, metadata = self._policy_ready(state, program)
                    if not ready:
                        from talli_backend.adapters.hosted_recovery_owner_policy import export_request
                        binding = self._owner_binding(state, metadata)
                        request = export_request(self.capture, program, binding,
                            self.work / 'original-owner-request')
                        state['quarantine'] = metadata
                        state['ownerRequest'] = request
                        state['ownerActionRequired'] = True
                        self._save(state, 'awaiting_original_owner_policy')
                        return state
                    state['ownerActionRequired'] = False
                    state['quarantine'] = metadata
                self._save(state, 'database_quarantined')
                for obj in self.capture.objects:
                    self._validate()
                    with self.target.database() as db:
                        current = self._marker(db, state)
                        self._quarantined(db, current)
                        if self._checkpointed:
                            self._verify_prepared(db, state, current, program)
                            self._verify_provider(db)
                    if self.initialization is not None:
                        self.target.ensure_private_bucket(obj['bucket'])
                        with self.target.database() as db:
                            self.initialization.verify(db)
                    receipt = self.target.restore_object(obj, self.capture.read(obj['file']))
                    # Reconcile even completed entries by readback on explicit
                    # resume, rather than trusting a stale local HTTP receipt.
                    state['objects'] = [r for r in state['objects'] if
                        (r['bucket'], r['name']) != (obj['bucket'], obj['name'])] + [receipt]
                    self._save(state, 'objects_quarantined')
                    if self.initialization is not None:
                        with self.target.database() as db:
                            self.initialization.verify(db)
                if self.disposition is not None: self.disposition.check_current()
                with self.target.database() as db:
                    current = self._marker(db, state)
                    self._quarantined(db, current)
                    if self._checkpointed:
                        self._verify_prepared(db, state, current, program)
                    self._verify_provider(db)
                    if 'providerState' in self.plan_body:
                        verify_custom_roles(db, self.capture)
                state['verification'] = {'tablesCompared': metadata['tablesCompared'],
                    'sequenceCounters': metadata['sequenceCounters'], 'aclRepairs': metadata['repairs'],
                    'privateObjectsServedExact': len(state['objects']), 'authUsersBanned': len(metadata['actors']),
                    'runtimeLoginsDisabled': len(metadata['logins'])}
                if self.disposition is not None:
                    self.disposition.check_current()
                    state['verification']['dispositionReplayCurrent'] = True
                    state['verification']['nativeHistoryFilesCopiedExact'] = metadata['nativeHistoryFiles']
                if self._owner_staged:
                    state['verification']['originalManagedPoliciesInstalled'] = True
                if self._checkpointed:
                    state['verification']['preparedQuarantineCheckpointCurrent'] = True
                self._save(state, 'verified_quarantined')
                return state
            except BaseException as error:
                # Never assert that an unknown commit/upload rolled back. A
                # subsequent restore reads the durable marker and exact objects;
                # contain remains available without replaying native DDL.
                state['lastFailure'] = {'class': type(error).__name__,
                    'sqlState': getattr(error, 'sqlstate', None), 'phase': state['phase']}
                self._save(state, 'inspection_or_containment_required')
                raise

    def inspect(self):
        with self._lock(), self._target_command_lock():
            self._validate(capture_required=False)
            state = self._state()
            with self.target.database() as db:
                marker = self._marker(db, state)
                if marker is not None: self._quarantined(db, marker)
                else: self._uncommitted(db)
                if self.initialization is not None:
                    self.initialization.verify(db, fresh=marker is None)
                checkpoint_current = None
                checkpoint_stage = None
                if self._managed_lifecycle and marker is not None:
                    checkpoint_stage = self._checkpoint_stage(state, marker)
                    require(self._private_control_current(db), 'hosted_control_acl_changed')
                    if self.capture is not None and checkpoint_stage['status'] != 'contained':
                        program = compile_program(self.capture, self.archive,
                            preserve_managed_constraints=True) if self.initialization is not None else \
                            compile_program(self.capture, self.archive)
                        # Inspection records drift without turning it into a
                        # fresh accepted baseline. Containment stays available.
                        try:
                            with db.transaction():
                                self._verify_prepared(db, state, marker, program)
                            checkpoint_current = True
                        except Exception:
                            checkpoint_current = False
                owner_policies_current = None
                provider_current = None
                if 'providerState' in self.plan_body and self.capture is not None:
                    pending = self._owner_staged and marker is not None and \
                        marker.get('ownerStage', {}).get('status') == 'pending_owner_policy'
                    self._verify_provider(db, pending=pending or marker is None and self._owner_staged)
                    verify_custom_roles(db, self.capture)
                    provider_current = True
                    if self._owner_staged:
                        from talli_backend.adapters.hosted_recovery_owner_policy import policy_status
                        owner_policies_current = not policy_status(self.capture,
                            db.execute(CATALOG_SQL).fetchone()[0], allow_missing=True)
                history_current = False
                try:
                    if marker is not None: history_current = self._history_current(db, marker)
                except Exception:
                    pass
            result = {**state, 'databaseMarkerPresent': marker is not None}
            if self._managed_lifecycle:
                result['preparedQuarantineCheckpointCurrent'] = checkpoint_current
                if 'verification' in result:
                    result['verification'] = {**result['verification'],
                        'preparedQuarantineCheckpointCurrent': checkpoint_current}
                if checkpoint_stage is not None and checkpoint_stage['status'] == 'contained':
                    result['phase'] = 'contained'
            if 'providerState' in self.plan_body:
                result['providerStateCurrent'] = provider_current
            if self._owner_staged:
                result['originalManagedPoliciesCurrent'] = owner_policies_current
                if marker is not None and marker.get('ownerStage', {}).get('status') == 'contained':
                    result['phase'] = 'contained'
            if 'disposition' in self.plan_body:
                current = False
                try:
                    if self.disposition is not None and self.disposition.summary() == self.plan_body['disposition']:
                        self.disposition.require_external(self.work)
                        self.disposition.check_current()
                        current = history_current
                except Exception:
                    pass
                result['dispositionReplayCurrent'] = current
            return result

    def contain(self, *, expected_plan_sha256):
        require(expected_plan_sha256 == self.plan_sha, 'hosted_reviewed_plan_changed')
        with self._lock(), self._target_command_lock():
            self._validate(capture_required=False)
            state = self._state()
            self._save(state, 'containment_pending')
            with self.target.database() as db:
                marker = self._marker(db, state)
                if marker is not None:
                    self._quarantine(db, marker)
                    self._seal_control(db, allow_missing_history=True)
                    require(self._private_control_current(db, allow_missing_history=True),
                        'hosted_control_acl_changed')
                    self._quarantined(db, marker)
                    if self._owner_staged:
                        self._owner_binding(state, marker)
                        marker['ownerStage']['status'] = 'contained'
                        self._update_marker(db, state, marker)
                    elif self._managed_lifecycle:
                        self._checkpoint_stage(state, marker)['status'] = 'contained'
                        self._update_marker(db, state, marker)
                else:
                    self._uncommitted(db)
                db.commit()
            self._save(state, 'contained')
            result = {**state, 'providerProjectPauseOrDeletionPerformed': False,
                'ownerCaptureAndCredentialFilesRemoved': False}
            if self._managed_lifecycle:
                # Containment does not validate or rebaseline drifted data.
                result['preparedQuarantineCheckpointCurrent'] = None
                if 'verification' in result:
                    result['verification'] = {**result['verification'],
                        'preparedQuarantineCheckpointCurrent': None}
            return result
