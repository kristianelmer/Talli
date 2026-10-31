"""Opt-in managed logical restore under durable quarantine.

No scheduler, app factory, provider purchase, project lifecycle or publication
authority. The operator consumes an independently verified decrypted managed
capture. Native disposition bundles keep their existing replay/identity contract.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
from uuid import uuid4

from talli_backend.adapters.hosted_recovery_access import (
    CATALOG_SQL, restore_access, restore_database_access, row_commitments, verify_custom_roles,
)
from talli_backend.adapters.hosted_recovery_capture import (
    digest, encoded, normalized_catalog, private_read, qi, require,
)
from talli_backend.adapters.hosted_recovery_sql import (
    GUC, NativeArchive, compile_program, execute_batch, execute_data,
)

CONTROL = '_talli_recovery'
MARKER = CONTROL + '.attempt'
BAN = '9999-12-31 00:00:00+00'
MAX_STATE = 256 * 1024


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
    def __init__(self, *, capture, target, work, pg_restore):
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
        self.archive = NativeArchive(capture, pg_restore=pg_restore, work=self.work)
        self.plan_body = {'version': 1, 'sourceProject': capture.source_project,
            'captureSha256': capture.commitment, 'target': target.designation.body(),
            'engineMajor': 17, 'schemas': sorted(capture.schemas),
            'customRoles': sorted(r[0] for r in capture.custom_roles),
            'tables': len(capture.rows), 'privateObjects': len(capture.objects),
            'publicationAuthorized': False, 'authQuarantine': 'all recovered users banned',
            'runtimeQuarantine': 'all captured custom logins disabled',
            'deletionJournalPublicationAuthority': False}
        self.plan_sha = digest(encoded(self.plan_body))

    @classmethod
    def for_containment(cls, *, target, work, expected_plan_sha256):
        """Contain a committed/interrupted restore even after capture scratch loss.

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
        self.plan_body, self.plan_sha = state['plan'], expected_plan_sha256
        return self

    @contextmanager
    def _lock(self):
        descriptor = os.open(self.work / 'operator.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally: os.close(descriptor)

    def _validate(self):
        # Re-read every bound member before a command, not just construction.
        if self.capture is not None:
            for name in self.capture.files: self.capture.read(name)
        return self.target.validate(source_project=self.plan_body['sourceProject'],
            captured_at=self.capture.profile.get('capturedAt') if self.capture is not None else None)

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

    def _fresh(self, db):
        capture = self.capture
        facts = db.execute("select current_setting('server_version_num')::integer,d.datlocprovider,"
            "pg_encoding_to_char(d.encoding),d.datcollate,d.datctype,"
            "coalesce(to_jsonb(d)->>'datlocale',to_jsonb(d)->>'daticulocale',''),"
            "pg_get_userbyid(d.datdba) from pg_database d where datname='postgres'").fetchone()
        require(list(facts) == capture.profile['facts'], 'hosted_database_profile_changed')
        extensions = db.execute('select e.extname,e.extversion,pg_get_userbyid(e.extowner),n.nspname '
            'from pg_extension e join pg_namespace n on n.oid=e.extnamespace order by e.extname').fetchall()
        require([list(row) for row in extensions] == capture.profile['extensions'],
            'hosted_extension_profile_changed')
        require(all(db.execute('select to_regnamespace(%s)', (name,)).fetchone()[0] is None
            for name in capture.schemas if name != 'public'), 'hosted_target_not_empty')
        require(db.execute('select count(*)from auth.users').fetchone()[0] == 0 and
            db.execute('select count(*)from storage.objects').fetchone()[0] == 0 and
            db.execute('select count(*)from storage.buckets').fetchone()[0] == 0,
            'hosted_target_not_empty')
        require(db.execute("select count(*)from pg_tables where schemaname='public'").fetchone()[0] == 0,
            'hosted_target_not_empty')
        require(db.execute('select count(*)from pg_roles where rolname=any(%s)',
            (self.plan_body['customRoles'],)).fetchone()[0] == 0, 'hosted_target_not_empty')
        current = db.execute(CATALOG_SQL).fetchone()[0]
        # Definitions and RLS must match before importing into provider tables.
        # Custom policies are intentionally restored separately, not overwritten.
        left = normalized_catalog(capture.catalog, {'auth', 'storage'})
        right = normalized_catalog(current, {'auth', 'storage'})
        for key in ('constraints', 'functions', 'indexes', 'rls'):
            require(left[key] == right[key], 'hosted_managed_schema_profile_changed')

    def _uncommitted(self, db):
        """No marker may mean rollback, never permission to reuse unrelated data."""
        require(all(db.execute('select to_regnamespace(%s)', (name,)).fetchone()[0] is None
            for name in self.plan_body['schemas'] if name != 'public') and
            db.execute('select count(*)from auth.users').fetchone()[0] == 0 and
            db.execute('select count(*)from pg_roles where rolname=any(%s)',
                (self.plan_body['customRoles'],)).fetchone()[0] == 0 and
            db.execute("select count(*)from pg_tables where schemaname='public'").fetchone()[0] == 0,
            'hosted_recovery_marker_unavailable')

    def _quarantine(self, db, metadata):
        db.execute('update auth.users set banned_until=%s where id=any(%s::uuid[])',
            (BAN, metadata['actors']))
        for name in metadata['logins']:
            db.execute('alter role ' + qi(name) + ' nologin')

    def _quarantined(self, db, metadata):
        require(metadata is not None, 'hosted_recovery_marker_unavailable')
        users = db.execute('select count(*)from auth.users where id=any(%s::uuid[]) and '
            '(banned_until is null or banned_until<%s::timestamptz)', (metadata['actors'], BAN)).fetchone()[0]
        logins = db.execute('select count(*)from pg_roles where rolname=any(%s)and rolcanlogin',
            (metadata['logins'],)).fetchone()[0]
        require(users == 0 and logins == 0, 'hosted_quarantine_changed')

    def _restore_database(self, state, program):
        with self.target.database() as db:
            require(db.execute('select pg_try_advisory_xact_lock(725128419231)').fetchone()[0],
                'hosted_recovery_target_busy')
            marker = self._marker(db, state)
            if marker is not None:
                self._quarantined(db, marker)
                return marker
            self._fresh(db)
            execute_batch(db, GUC.encode())
            db.execute("set statement_timeout='240s'")
            db.execute("set lock_timeout='10s'")
            db.execute('set session_replication_role=replica')
            execute_batch(db, program.roles)
            restore_database_access(db, self.capture.database_access)
            execute_batch(db, program.schemas)
            execute_batch(db, program.temporary_create)
            execute_batch(db, program.definitions)
            copied = execute_data(db, program.data, self.capture.rows)
            # Include managed sequence counters even though managed table/schema
            # definitions and migration history remain provider-owned.
            for (schema, name), value, called in program.sequences:
                db.execute('select pg_catalog.setval(%s::regclass,%s,%s)',
                    (schema + '.' + name, value, called))
                actual = db.execute('select last_value,is_called from ' + qi(schema) + '.' + qi(name)).fetchone()
                require(actual == (value, called), 'hosted_sequence_payload_changed')
            execute_batch(db, program.policies)
            execute_batch(db, program.remove_temporary_create)
            execute_batch(db, program.acl)
            execute_batch(db, program.extension_usage)
            # Keep temporary owner inheritance through byte verification. The
            # captured postgres membership can intentionally disable both
            # INHERIT and SET, including access to cross-owned schemas.
            repairs = restore_access(db, self.capture, b'')
            # Mutable provider migration timestamps and future uploaded Storage
            # transport identities are explicit differences, not wildcard skips.
            compared = [t for t in self.capture.profile['tables'] if '.'.join(t) in copied or
                t[0] == 'auth']
            observed = row_commitments(db, compared)
            require(observed == {'.'.join(t): self.capture.rows['.'.join(t)] for t in compared},
                'hosted_restored_table_bytes_changed')
            execute_batch(db, program.final_memberships)
            actors = [str(r[0]) for r in db.execute('select id from auth.users order by id')]
            logins = [r[0] for r in self.capture.custom_roles if r[5]]
            metadata = {'actors': actors, 'logins': logins, 'repairs': repairs,
                'tablesCompared': len(compared), 'sequenceCounters': len(program.sequences),
                'publicationAuthorized': False}
            state['quarantine'] = metadata
            self._save(state, 'database_outcome_pending')
            self._quarantine(db, metadata)
            self._quarantined(db, metadata)
            verify_custom_roles(db, self.capture)
            db.execute('create schema ' + CONTROL + ' authorization postgres')
            db.execute('revoke all on schema ' + CONTROL + ' from public')
            db.execute('create table ' + MARKER + '(id uuid primary key,plan_sha text not null,'
                'capture_sha text not null,target_ref text not null,metadata jsonb not null)')
            db.execute('revoke all on table ' + MARKER + ' from public,anon,authenticated,service_role')
            # Restored global default privileges also apply to newly created
            # control objects. Remove any inherited grants, including custom
            # runtime grants, before the authoritative marker can commit.
            for kind, identity, query in (
                ('schema', CONTROL, "select distinct case when a.grantee=0 then 'PUBLIC' else "
                 "pg_get_userbyid(a.grantee)end from pg_namespace n cross join lateral "
                 "aclexplode(n.nspacl)a where n.nspname='_talli_recovery' and a.grantee<>n.nspowner"),
                ('table', MARKER, "select distinct case when a.grantee=0 then 'PUBLIC' else "
                 "pg_get_userbyid(a.grantee)end from pg_class c cross join lateral "
                 "aclexplode(c.relacl)a where c.oid='_talli_recovery.attempt'::regclass "
                 "and a.grantee<>c.relowner"),
            ):
                for name, in db.execute(query).fetchall():
                    db.execute('revoke all on ' + kind + ' ' + identity + ' from ' +
                        ('PUBLIC' if name == 'PUBLIC' else qi(name)) + ' cascade')
            db.execute('insert into ' + MARKER + ' values(%s,%s,%s,%s,%s::jsonb)',
                (state['id'], self.plan_sha, self.capture.commitment,
                 self.target.designation.project, json.dumps(metadata)))
            db.execute('set session_replication_role=origin')
            db.commit()
            return metadata

    def restore(self, *, expected_plan_sha256):
        require(expected_plan_sha256 == self.plan_sha, 'hosted_reviewed_plan_changed')
        with self._lock():
            self._validate()
            require(self.capture.database_access is not None, 'hosted_database_acl_profile_required')
            state = self._state(create=True)
            require(state['phase'] != 'contained', 'hosted_recovery_already_contained')
            try:
                program = compile_program(self.capture, self.archive)
                self._save(state, 'database_outcome_pending')
                metadata = self._restore_database(state, program)
                self._save(state, 'database_quarantined')
                for obj in self.capture.objects:
                    self._validate()
                    with self.target.database() as db:
                        self._quarantined(db, self._marker(db, state))
                    receipt = self.target.restore_object(obj, self.capture.read(obj['file']))
                    # Reconcile even completed entries by readback on explicit
                    # resume, rather than trusting a stale local HTTP receipt.
                    state['objects'] = [r for r in state['objects'] if
                        (r['bucket'], r['name']) != (obj['bucket'], obj['name'])] + [receipt]
                    self._save(state, 'objects_quarantined')
                with self.target.database() as db:
                    self._quarantined(db, self._marker(db, state))
                state['verification'] = {'tablesCompared': metadata['tablesCompared'],
                    'sequenceCounters': metadata['sequenceCounters'], 'aclRepairs': metadata['repairs'],
                    'privateObjectsServedExact': len(state['objects']), 'authUsersBanned': len(metadata['actors']),
                    'runtimeLoginsDisabled': len(metadata['logins'])}
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
        with self._lock():
            self._validate()
            state = self._state()
            with self.target.database() as db:
                marker = self._marker(db, state)
                if marker is not None: self._quarantined(db, marker)
                else: self._uncommitted(db)
            return {**state, 'databaseMarkerPresent': marker is not None}

    def contain(self, *, expected_plan_sha256):
        require(expected_plan_sha256 == self.plan_sha, 'hosted_reviewed_plan_changed')
        with self._lock():
            self._validate()
            state = self._state()
            self._save(state, 'containment_pending')
            with self.target.database() as db:
                marker = self._marker(db, state)
                if marker is not None:
                    self._quarantine(db, marker)
                    self._quarantined(db, marker)
                else:
                    self._uncommitted(db)
                db.commit()
            self._save(state, 'contained')
            return {**state, 'providerProjectPauseOrDeletionPerformed': False,
                'ownerCaptureAndCredentialFilesRemoved': False}
