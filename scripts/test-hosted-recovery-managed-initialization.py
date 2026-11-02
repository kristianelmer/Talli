#!/usr/bin/env python3
"""Opt-in real SQL proof of a synthesized managed-initialization provider fixture.

Uses one owned, cached PostgreSQL 17.11 container; no hosted calls, image pulls,
credentials or saved private captures. Provider SQL is authored independently
for source and destination, not restored from the source archive. This proves
the compatibility seam, not an independently installed managed Supabase service.
Storage HTTP is an in-process transport model; its bucket/object rows use real
SQL and the production upload/readback protocol. It is not a Storage daemon test.
"""
import argparse
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import unquote
from uuid import uuid4
from unittest.mock import patch

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/backend/src'))
spec = importlib.util.spec_from_file_location('owned_recovery_fixture',
    ROOT / 'scripts/test-hosted-recovery-owned.py')
owned = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owned)

from talli_backend.adapters.hosted_backup_recovery import HostedBackupRecovery
from talli_backend.adapters import hosted_recovery_operator as operator_command
from talli_backend.adapters.hosted_recovery_access import (
    ACCESS_SQL, DATABASE_ACCESS_SQL, normalized_catalog, row_commitments,
)
from talli_backend.adapters.hosted_recovery_capture import ManagedCapture, digest, encoded
from talli_backend.adapters.hosted_recovery_sql import CATALOG_SQL, GUC, execute_batch, execute_data
from talli_backend.adapters.hosted_recovery_target import SupabaseRecoveryTarget
from talli_backend.adapters.hosted_recovery_managed_initialization import (
    PROFILE, SOURCE_EXTENSIONS, DARK_CONSTRAINT, TRANSITION_FUNCTION, TRANSITION_TRIGGER,
)

EXPECTED_PROFILE = 'supabase-managed-17.11-storage-versioning-v1'
EXTENSIONS_SQL = """select e.extname,e.extversion,pg_get_userbyid(e.extowner),n.nspname
from pg_extension e join pg_namespace n on n.oid=e.extnamespace order by e.extname"""
TABLES_SQL = """select schemaname,tablename from pg_tables where
schemaname not in('pg_catalog','information_schema') and schemaname not like 'pg_toast%'
order by 1,2"""
TRIGGERS_SQL = """select pg_get_triggerdef(t.oid),t.tgenabled from pg_trigger t
join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace
where n.nspname in('auth','storage') and not t.tgisinternal order by 1"""
SCOPE = {'auth', 'storage', 'extensions'}
APPLICATION_SCHEMAS = ['ledger', 'public', 'supabase_migrations']
OWNER_DIFFERENCES = {'pg_stat_statements', 'pgcrypto', 'uuid-ossp'}

# Deliberately literal SQL: production constants are checked against PostgreSQL's
# independently deparsed fixture, never used to construct their own oracle.
MANAGED_SQL = """
alter schema public owner to postgres;
create schema auth authorization postgres;
create schema storage authorization postgres;
create table auth.users(id uuid primary key,banned_until timestamptz);
create table auth.refresh_tokens(id bigserial primary key,token text);
create table auth.schema_migrations(version text primary key);
insert into auth.schema_migrations values('synthetic-managed-auth');
create table auth.z_parent(id integer primary key,user_id uuid not null references auth.users(id),child_id integer);
create table auth.a_child(id integer primary key,parent_id integer not null references auth.z_parent(id));
create table storage.buckets(id text primary key,name text not null,public boolean not null default false,
 versioning_status text not null default 'DISABLED'::text,created_at timestamptz);
create table storage.objects(id uuid primary key,bucket_id text not null references storage.buckets(id),
 name text not null,updated_at timestamptz);
create table storage.buckets_vectors(id uuid primary key);
create table storage.migrations(id integer primary key,created_at timestamptz);
insert into storage.migrations values(1,clock_timestamp());
create function storage.update_updated_at_column() returns trigger language plpgsql
as $$begin new.updated_at=clock_timestamp();return new;end$$;
create trigger update_objects_updated_at before update on storage.objects
 for each row execute function storage.update_updated_at_column();
"""
SOURCE_STORAGE_SQL = """alter table storage.buckets add constraint buckets_versioning_dark_check
check(versioning_status='DISABLED'::text);"""
TARGET_STORAGE_SQL = """CREATE OR REPLACE FUNCTION storage.enforce_versioning_status_transition()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
BEGIN
    IF NEW.versioning_status = OLD.versioning_status THEN
        RETURN NEW;
    END IF;

    IF NEW.versioning_status = 'DISABLED' OR
       (OLD.versioning_status = 'DISABLED' AND NEW.versioning_status = 'SUSPENDED') THEN
        RAISE EXCEPTION 'Cannot transition bucket versioning status from % to %',
            OLD.versioning_status, NEW.versioning_status;
    END IF;

    RETURN NEW;
END;
$function$;
alter function storage.enforce_versioning_status_transition() owner to supabase_storage_admin;
create trigger enforce_versioning_status_transition before update of versioning_status on storage.buckets
for each row execute function storage.enforce_versioning_status_transition();
"""
CYCLE_SQL = """alter table auth.z_parent add constraint parent_cycle foreign key(child_id)
references auth.a_child(id) deferrable initially deferred;"""
COPY_TRIGGER_SQL = """create function auth.reject_copy()returns trigger language plpgsql
as $$begin raise exception 'unexpected provider COPY trigger executed';end$$;
create trigger reject_copy before insert on auth.a_child for each row execute function auth.reject_copy();"""


def docker(*arguments, **kwargs):
    return owned.run(['docker', '--context', 'default', *arguments], **kwargs)


def refused(action, *, code=None, sqlstate=None):
    try:
        action()
    except (ValueError, psycopg.Error) as error:
        if sqlstate is not None:
            assert isinstance(error, psycopg.Error) and error.sqlstate == sqlstate, str(error)
        else:
            assert isinstance(error, ValueError) and str(error).startswith('hosted_'), str(error)
            if code is not None:
                assert str(error) == code, str(error)
        return str(error) if isinstance(error, ValueError) else error.sqlstate
    raise AssertionError('unsupported initialization or payload was accepted')


class OriginCursor:
    def __init__(self, cursor, connection, target):
        self.cursor, self.connection, self.target = cursor, connection, target
    def __enter__(self):
        self.cursor.__enter__()
        return self
    def __exit__(self, *args):
        return self.cursor.__exit__(*args)
    def copy(self, header):
        assert self.connection.execute("select current_setting('session_replication_role')").fetchone() == ('origin',)
        assert not self.connection.execute("select has_parameter_privilege(current_user,'session_replication_role','SET')").fetchone()[0]
        self.target.copies.append(header)
        return self.cursor.copy(header)


class OriginConnection:
    def __init__(self, connection, target):
        self.connection, self.target = connection, target
    def __getattr__(self, name):
        return getattr(self.connection, name)
    def cursor(self, *args, **kwargs):
        return OriginCursor(self.connection.cursor(*args, **kwargs), self.connection, self.target)
    def commit(self):
        assert self.connection.execute("select current_setting('session_replication_role')").fetchone() == ('origin',)
        return self.connection.commit()


class FixtureTarget(owned.LocalTarget):
    restore_object = SupabaseRecoveryTarget.restore_object
    def __init__(self, settings, folder, connect):
        super().__init__(settings, folder)
        self.connect = connect
        self.objects, self.copies = {}, []
        self.uploads = 0
        self.drift_after_upload = None
        self.drift_after_bucket_creation = False
    @contextmanager
    def database(self):
        with super().database() as db:
            yield OriginConnection(db, self)
    def _storage(self, method, path, *, body=None, content_type=None, json_body=None, public=False):
        # Only the Storage transport is modeled. Every bucket/object mutation is
        # subject to the actual provider constraints and origin-mode triggers.
        if public:
            return 404, b'{}'
        if path == '/bucket' and method == 'POST':
            assert json_body['public'] is False
            with self.database() as db:
                db.execute('insert into storage.buckets(id,name,public)values(%s,%s,false)',
                    (json_body['id'], json_body['name']))
                db.commit()
            if self.drift_after_bucket_creation:
                with self.connect() as db:
                    db.execute("update storage.buckets set versioning_status='ENABLED'")
            return 200, b'{}'
        if path.startswith('/bucket/') and method == 'GET':
            with self.database() as db:
                row = db.execute('select id,public from storage.buckets where id=%s',
                    (unquote(path[len('/bucket/'):]),)).fetchone()
            return (200, encoded({'id': row[0], 'public': row[1]})) if row else (404, b'{}')
        assert path.startswith('/object/') and method in ('GET', 'POST')
        bucket, name = unquote(path[len('/object/'):]).split('/', 1)
        key = bucket, name
        if method == 'POST':
            assert key not in self.objects and isinstance(body, bytes)
            with self.database() as db:
                db.execute('insert into storage.objects(id,bucket_id,name)values(%s,%s,%s)',
                    (uuid4(), bucket, name))
                db.commit()
            self.objects[key] = body
            self.uploads += 1
            if self.uploads == self.drift_after_upload:
                with self.connect() as db:
                    db.execute("update storage.buckets set versioning_status='ENABLED'")
            return 200, b'{}'
        return (200, self.objects[key]) if key in self.objects else (404, b'{}')


def snapshot(db):
    execute_batch(db, GUC.encode())
    tables = [list(row) for row in db.execute(TABLES_SQL)]
    return {'catalog': db.execute(CATALOG_SQL).fetchone()[0],
        'roles': db.execute(owned.ROLES).fetchone()[0],
        'extensions': [list(row) for row in db.execute(EXTENSIONS_SQL)],
        'databaseAccess': db.execute(DATABASE_ACCESS_SQL).fetchone()[0],
        'triggers': db.execute(TRIGGERS_SQL).fetchall(), 'rows': row_commitments(db, tables)}


def capture_source(container, connect, folder, pg_restore):
    folder.mkdir(mode=0o700)
    directory = folder / 'capture'
    directory.mkdir(mode=0o700)
    with connect() as db:
        facts = snapshot(db)
        profile = {'projectRef': owned.SOURCE, 'facts': list(db.execute(owned.FACTS).fetchone()),
            'extensions': facts['extensions'], 'tables': [list(row) for row in db.execute(TABLES_SQL)],
            'capturedAt': datetime.now(timezone.utc).isoformat()}
        access = db.execute(ACCESS_SQL, (APPLICATION_SCHEMAS,) * 2).fetchone()[0]
    raw = docker('exec', container, 'pg_dump', '-h', '/tmp', '-U', 'supabase_admin', '-d', 'postgres', '-Fc')
    objects, bodies = [], {}
    for index, body in enumerate((b'private synthetic original one', b'private synthetic original two')):
        name = 'object-' + digest(body) + '.bin'
        bodies[name] = body
        objects.append({'bucket': 'private-files', 'name': 'company/2025/original-' + str(index) + '.pdf',
            'sha256': digest(body), 'bytes': len(body), 'file': name})
    files = {'database.dump': raw, 'roles.sql': b'-- structured synthetic role facts; no passwords\n',
        'contents.list': owned.run([pg_restore, '--list'], input=raw),
        'source-profile.json': encoded(profile), 'source-tables.private.json': encoded(facts['rows']),
        'source-catalog.private.json': encoded(facts['catalog']), 'source-roles.private.json': encoded(facts['roles']),
        'object-manifest.private.json': encoded(objects), **bodies}
    for name, body in files.items():
        owned.save(directory / name, body)
    header = owned.save(folder / 'header.json', {'format': 'talli-designated-hosted-capture-v1',
        'projectRef': owned.SOURCE, 'pins': {name: {'bytes': len(body), 'sha256': digest(body)} for name, body in files.items()}})
    extra = owned.save(folder / 'access.json', {'sourceProject': owned.SOURCE,
        'sourceCatalogStillExactToOriginal': True, 'access': access, 'databaseAccess': facts['databaseAccess']})
    return ManagedCapture.open(directory=directory, header=header, header_sha256=digest(header.read_bytes()),
        access=extra, access_sha256=digest(extra.read_bytes()))


def exercise(container, settings, folder, pg_restore):
    assert PROFILE == EXPECTED_PROFILE
    def connect(database='postgres', autocommit=False):
        return psycopg.connect(**{**settings, 'dbname': database, 'user': 'supabase_admin'}, autocommit=autocommit)
    with connect() as db:
        assert db.execute('show server_version_num').fetchone()[0] == '170011'
        db.execute('create role postgres login createrole createdb bypassrls; '
            'create role anon;create role authenticated;create role service_role;create role supabase_storage_admin')
        db.execute('alter database postgres owner to postgres')

    def initialize(*, source, cycle=False, trigger=False):
        with connect() as db:
            db.execute('create schema extensions authorization postgres;create schema vault')
            # Bootstrap-only fixture authorship. CREATE EXTENSION's member owners
            # match the observed source; only source extowner metadata differs.
            db.execute('alter role postgres superuser;set local role postgres')
            db.execute('create extension pg_stat_statements with schema extensions version \'1.11\'; '
                'create extension pgcrypto with schema extensions version \'1.3\'; '
                'create extension "uuid-ossp" with schema extensions version \'1.1\'')
            db.execute('reset role;alter role postgres nosuperuser')
            db.execute("create extension supabase_vault with schema vault version '0.3.1'")
            db.execute('grant usage on schema vault to postgres;grant select on vault.secrets to postgres')
            if source:
                db.execute("update pg_extension set extowner='supabase_admin'::regrole "
                    "where extname=any(%s)", (sorted(OWNER_DIFFERENCES),))
            db.execute('set local role postgres')
            execute_batch(db, MANAGED_SQL.encode())
            if not source:
                db.execute('reset role')
            execute_batch(db, (SOURCE_STORAGE_SQL if source else TARGET_STORAGE_SQL).encode())
            db.execute('set local role postgres')
            if cycle:
                execute_batch(db, CYCLE_SQL.encode())
            if trigger:
                execute_batch(db, COPY_TRIGGER_SQL.encode())
            if source:
                execute_batch(db, owned.APPLICATION.encode())
                db.execute("insert into auth.z_parent values(1,'00000000-0000-0000-0000-000000000001',null);"
                    'insert into auth.a_child values(1,1)')
                db.execute('grant execute on all functions in schema extensions to restore_runtime')
            assert not db.execute("select has_parameter_privilege('postgres','session_replication_role','SET')").fetchone()[0]

    initialize(source=True)
    capture = capture_source(container, connect, folder / 'valid-source', pg_restore)
    assert capture.profile['extensions'] == list(SOURCE_EXTENSIONS)
    source_catalog = normalized_catalog(capture.catalog, SCOPE)
    assert DARK_CONSTRAINT in source_catalog['constraints']
    extension_functions = [row for row in source_catalog['functions'] if row[0] == 'extensions']
    assert extension_functions and all(row[4] == 'postgres' for row in extension_functions)
    # Malformed native payload: rows and dump agree, but existing provider FK
    # must still reject it. Only this fixture bootstrap has replica authority.
    with connect() as db:
        db.execute('set local session_replication_role=replica;update auth.a_child set parent_id=999')
    orphan = capture_source(container, connect, folder / 'orphan-source', pg_restore)
    with connect() as db:
        db.execute('update auth.a_child set parent_id=1')
        execute_batch(db, CYCLE_SQL.encode())
        db.execute('update auth.z_parent set child_id=1')
    cyclic = capture_source(container, connect, folder / 'cyclic-source', pg_restore)
    with connect() as db:
        db.execute('alter table auth.z_parent drop constraint parent_cycle;update auth.z_parent set child_id=null')
        execute_batch(db, COPY_TRIGGER_SQL.encode())
    triggered = capture_source(container, connect, folder / 'triggered-source', pg_restore)

    def fresh(*, cycle=False, trigger=False):
        with connect('template1', True) as db:
            db.execute('drop database postgres with(force)')
            db.execute('create database postgres owner postgres')
            for role in ('restore_owner', 'restore_function_owner', 'restore_runtime'):
                db.execute('drop role if exists ' + role)
        initialize(source=False, cycle=cycle, trigger=trigger)
        return FixtureTarget(settings, folder, connect)

    def operator(target, label, source=capture, *, opt_in=True):
        work = folder / label
        work.mkdir(mode=0o700)
        return HostedBackupRecovery(capture=source, target=target, work=work, pg_restore=pg_restore,
            **({'managed_initialization': PROFILE} if opt_in else {}))

    def assert_clean_rollback(target):
        with connect() as db:
            assert db.execute("select to_regnamespace('ledger'),to_regclass('_talli_recovery.attempt')").fetchone() == (None, None)
            assert db.execute('select count(*)from auth.users').fetchone()[0] == 0
            assert db.execute("select count(*)from pg_roles where rolname='restore_runtime'").fetchone()[0] == 0
        assert target.uploads == 0

    target = fresh()
    with connect() as db:
        before = snapshot(db)
        expected_extensions = [list(row) for row in capture.profile['extensions']]
        for row in expected_extensions:
            if row[0] in OWNER_DIFFERENCES:
                row[2] = 'postgres'
        assert before['extensions'] == expected_extensions
        current = normalized_catalog(before['catalog'], SCOPE)
        expected = json.loads(json.dumps(source_catalog))
        expected['constraints'].remove(DARK_CONSTRAINT)
        # The source's custom grantee does not exist on a fresh managed target.
        for row in expected['functions']:
            if row[0] == 'extensions':
                row[5] = [grant for grant in row[5] if grant[1] != 'restore_runtime']
        expected['functions'].append(TRANSITION_FUNCTION)
        assert current == normalized_catalog(expected, SCOPE)
        assert (TRANSITION_TRIGGER, 'O') in before['triggers']
        fresh_triggers = before['triggers']
    legacy = operator(target, 'legacy-refusal', opt_in=False)
    refused(lambda: legacy.restore(expected_plan_sha256=legacy.plan_sha), code='hosted_extension_profile_changed')
    assert_clean_rollback(target)

    mutation_results = {}
    for label, sql in (
        ('wrong-extension-owner', "update pg_extension set extowner='supabase_storage_admin'::regrole where extname='pgcrypto'"),
        ('wrong-extension-version', "update pg_extension set extversion='unexpected' where extname='pgcrypto'"),
        ('disabled-transition-trigger', 'alter table storage.buckets disable trigger enforce_versioning_status_transition'),
        ('disabled-internal-fk-trigger', 'alter table auth.a_child disable trigger all'),
        ('changed-transition-body', "create or replace function storage.enforce_versioning_status_transition()returns trigger language plpgsql as $$begin return new;end$$"),
        ('changed-transition-acl', 'revoke execute on function storage.enforce_versioning_status_transition()from public'),
        ('unexpected-provider-function', 'create function storage.unexpected()returns int language sql as $$select 1$$'),
        ('unexpected-provider-constraint', 'alter table storage.objects add constraint unexpected check(name<>\'forbidden\')'),
        ('nullable-versioning-column', 'alter table storage.buckets alter column versioning_status drop not null'),
        ('nonempty-provider-table', "insert into auth.refresh_tokens(token)values('unrelated')"),
    ):
        target = fresh()
        with connect() as db:
            db.execute(sql)
        with connect() as db:
            before = snapshot(db)
        def attempt():
            op = operator(target, label)
            op.restore(expected_plan_sha256=op.plan_sha)
        mutation_results[label] = refused(attempt)
        with connect() as db:
            assert snapshot(db) == before, label + ' changed target on preflight refusal'
        assert target.uploads == 0

    for label, source, kwargs, code, sqlstate in (
        ('invalid-provider-fk', orphan, {}, None, '23503'),
        ('provider-fk-cycle', cyclic, {'cycle': True}, 'hosted_provider_foreign_key_cycle_unsupported', None),
        ('nonempty-provider-trigger', triggered, {'trigger': True}, None, None),
        ('wrong-row-commitment', replace(capture, rows={**capture.rows,
            'ledger.items': {'rows': 1, 'sha256': '0' * 64}}), {}, 'hosted_restored_table_bytes_changed', None),
    ):
        target = fresh(**kwargs)
        with connect() as db:
            before = snapshot(db)
        def attempt():
            op = operator(target, label, source)
            op.restore(expected_plan_sha256=op.plan_sha)
        mutation_results[label] = refused(attempt, code=code, sqlstate=sqlstate)
        assert_clean_rollback(target)
        with connect() as db:
            assert snapshot(db) == before, label + ' failed to roll back'

    target = fresh()
    op = operator(target, 'success')
    assert op.plan_body['managedInitialization']['profile'] == PROFILE
    assert 'providerState' not in op.plan_body and 'ownerPolicy' not in op.plan_body
    state = op.restore(expected_plan_sha256=op.plan_sha)
    assert state['phase'] == 'verified_quarantined' and len(state['objects']) == 2
    assert target.uploads == 2 and op.inspect()['databaseMarkerPresent'] is True
    copies = len(target.copies)
    resumed = op.restore(expected_plan_sha256=op.plan_sha)
    assert resumed['phase'] == 'verified_quarantined' and resumed['verification'] == state['verification']
    assert target.uploads == 2 and len(target.copies) == copies, 'committed marker replayed data or uploaded twice'
    # The local target substitutes only provider metadata/HTTP transport. Config
    # dispatch, held plan, real SQL verification and capture-loss behavior remain
    # production code; no input is reopened for inspect/contain.
    def captureless_dispatch(command, current, destination):
        config = {'version': 3, 'designation': destination.designation.body(),
            'credentials': '/unused/local-fixture', 'ca': '/unused/local-fixture',
            'caSha256': '0' * 64, 'work': str(current.work), 'pgRestore': pg_restore,
            'capture': {'directory': str(capture.directory)}, 'managedInitialization': PROFILE}
        path = folder / ('dispatch-' + current.work.name + '-' + command + '.json')
        owned.save(path, config)
        with patch.object(operator_command, 'SupabaseRecoveryTarget', return_value=destination):
            result = operator_command.execute(command=command, config=path,
                expected_config_sha256=digest(path.read_bytes()), expected_plan_sha256=current.plan_sha)
            changed = {**config, 'version': 1}
            del changed['managedInitialization']
            owned.save(path, changed)
            refused(lambda: operator_command.execute(command=command, config=path,
                expected_config_sha256=digest(path.read_bytes()), expected_plan_sha256=current.plan_sha),
                code='hosted_managed_initialization_binding_invalid')
        return result
    held = capture.directory.with_name('capture-unavailable')
    capture.directory.rename(held)
    try:
        assert captureless_dispatch('inspect', op, target)['databaseMarkerPresent']
    finally:
        held.rename(capture.directory)
    with connect() as db:
        actual = normalized_catalog(db.execute(CATALOG_SQL).fetchone()[0], SCOPE)
        expected = json.loads(json.dumps(source_catalog))
        expected['constraints'].remove(DARK_CONSTRAINT)
        expected['functions'].append(TRANSITION_FUNCTION)
        assert actual == normalized_catalog(expected, SCOPE)
        assert db.execute(TRIGGERS_SQL).fetchall() == fresh_triggers
        assert db.execute('select last_value,is_called from auth.refresh_tokens_id_seq').fetchone() == (132, True)
        assert db.execute('select count(*)from auth.a_child c join auth.z_parent p on p.id=c.parent_id join auth.users u on u.id=p.user_id').fetchone()[0] == 1
        assert db.execute('select count(*)from auth.users where banned_until is null').fetchone()[0] == 0
        assert not db.execute("select rolcanlogin from pg_roles where rolname='restore_runtime'").fetchone()[0]
        assert db.execute("select version,statements from supabase_migrations.schema_migrations order by version").fetchall() == [
            ('20261030', ['original; migration']), ('20261031', ['second migration'])]
        assert db.execute("select count(*)from storage.buckets where public or versioning_status<>'DISABLED'").fetchone()[0] == 0
    # Actual constraints reject an orphan; the shared production COPY executor
    # reorders an independently authored child-before-parent payload in origin.
    with target.database() as db:
        raw = (b'COPY auth.a_child (id,parent_id) FROM stdin;\n2\t2\n\\.\n'
            b'-- child deliberately precedes parent\n'
            b'COPY auth.z_parent (id,user_id,child_id) FROM stdin;\n2\t00000000-0000-0000-0000-000000000001\t\\N\n\\.\n')
        execute_data(db, raw, {'auth.a_child': {'rows': 1}, 'auth.z_parent': {'rows': 1}}, order_by_foreign_keys=True)
        assert 'auth.z_parent' in target.copies[-2] and 'auth.a_child' in target.copies[-1]
        assert db.execute('select count(*)from auth.a_child where id=2').fetchone()[0] == 1
        db.rollback()
    with target.database() as db:
        refused(lambda: db.execute('insert into auth.a_child values(2,999)'), sqlstate='23503')
        db.rollback()
    for initial, next_status in (('DISABLED', 'SUSPENDED'), ('ENABLED', 'DISABLED')):
        with connect() as db:
            db.execute('insert into storage.buckets(id,name,versioning_status)values(%s,%s,%s)', ('probe', 'probe', initial))
            refused(lambda: db.execute('update storage.buckets set versioning_status=%s where id=\'probe\'',
                (next_status,)), sqlstate='P0001')
            db.rollback()
    with connect() as db:
        db.execute('update storage.buckets set public=true')
    uploads = target.uploads
    refused(op.inspect, code='hosted_managed_initialization_bucket_mode_changed')
    refused(lambda: op.restore(expected_plan_sha256=op.plan_sha),
        code='hosted_managed_initialization_bucket_mode_changed')
    assert target.uploads == uploads
    with connect() as db:
        db.execute('update storage.buckets set public=false')
    with connect() as db:
        db.execute("update storage.buckets set versioning_status='ENABLED'")
    refused(op.inspect, code='hosted_managed_initialization_bucket_mode_changed')
    refused(lambda: op.restore(expected_plan_sha256=op.plan_sha),
        code='hosted_managed_initialization_bucket_mode_changed')
    assert target.uploads == uploads
    assert op.contain(expected_plan_sha256=op.plan_sha)['phase'] == 'contained'

    # A successful last transport response must not hide bucket drift. The first
    # case also proves a second private object is not uploaded after drift.
    for position in (1, 2):
        target = fresh()
        target.drift_after_upload = position
        op = operator(target, 'upload-drift-' + str(position))
        refused(lambda: op.restore(expected_plan_sha256=op.plan_sha))
        assert target.uploads == position
        assert op.contain(expected_plan_sha256=op.plan_sha)['phase'] == 'contained'
    target = fresh()
    target.drift_after_bucket_creation = True
    op = operator(target, 'bucket-created-with-drift')
    refused(lambda: op.restore(expected_plan_sha256=op.plan_sha),
        code='hosted_managed_initialization_bucket_mode_changed')
    assert target.uploads == 0, 'upload began before the new bucket mode was checked'
    assert op.contain(expected_plan_sha256=op.plan_sha)['phase'] == 'contained'
    capture.directory.rename(held)
    try:
        assert captureless_dispatch('contain', op, target)['phase'] == 'contained'
    finally:
        held.rename(capture.directory)
    return {'status': 'pass', 'scope': 'synthesized managed provider fixture; real PostgreSQL 17.11',
        'independentManagedServiceAcceptance': False, 'storageDaemonTested': False,
        'profile': PROFILE, 'extensionFunctionsVerified': len(extension_functions), 'extensionOwnerDifferences': 3,
        'privateObjectTransportReadbacks': 2, 'originOnlyNoReplicaAuthority': True,
        'committedMarkerResumeWithoutRecopy': True, 'publicBucketDriftRefused': True,
        'orderedProviderCopyAndInvalidFk': True, 'cycleAndTriggerRefusals': True,
        'preflightAndRollbackFaults': mutation_results, 'bucketResumeInspectAndUploadDriftRefused': True,
        'terminalContainment': True, 'configV3CapturelessInspectContainAndMismatchRefusal': True,
        'postBucketCreationDriftRefusedBeforeUpload': True,
        'hostedCalls': 0}


def main():
    if not __debug__:
        raise RuntimeError('optimized_regression_unsupported')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-restore', required=True, type=Path)
    args = parser.parse_args()
    pg_restore = str(args.pg_restore.resolve(strict=True))
    os.umask(0o077)
    name = 'talli-managed-init-regression-' + uuid4().hex[:12]
    identity = None
    try:
        identity = docker('run', '-d', '--pull=never', '--name', name,
            '--label', 'talli.managed-init-regression=' + name, '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--read-only', '--user', '100:101',
            '--pids-limit', '128', '--memory', '1g', '--cpus', '2',
            '--tmpfs', '/var/lib/postgresql/data:rw,nosuid,nodev,uid=100,gid=101,mode=0700,size=512m',
            '--tmpfs', '/tmp:rw,nosuid,nodev,uid=100,gid=101,mode=0700,size=32m',
            '--tmpfs', '/etc/postgresql-custom:rw,nosuid,nodev,noexec,uid=100,gid=101,mode=0700,size=1m',
            '-p', '127.0.0.1::5432', '--entrypoint', '/bin/sh', '--no-healthcheck', owned.IMAGE, '-c',
            'initdb -D /var/lib/postgresql/data -U supabase_admin --locale=C.UTF-8 -A trust && '
            'echo "host all all 0.0.0.0/0 trust" >> /var/lib/postgresql/data/pg_hba.conf && '
            'exec postgres -D /var/lib/postgresql/data -h "*" -k /tmp '
            '-c shared_preload_libraries=pg_stat_statements,supabase_vault -c cron.launch_active_jobs=off '
            '-c logging_collector=off -c log_destination=stderr').decode().strip()
        info = json.loads(docker('inspect', identity))[0]
        assert info['Image'] == owned.IMAGE.split('@')[1]
        ports = info['NetworkSettings']['Ports']['5432/tcp']
        assert len(ports) == 1 and ports[0]['HostIp'] == '127.0.0.1'
        settings = {'host': '127.0.0.1', 'port': int(ports[0]['HostPort']),
            'dbname': 'postgres', 'user': 'supabase_admin', 'connect_timeout': 2}
        deadline = time.monotonic() + 25
        while True:
            try:
                with psycopg.connect(**settings):
                    break
            except psycopg.OperationalError:
                if not json.loads(docker('inspect', identity))[0]['State']['Running']:
                    logs = subprocess.run(['docker', '--context', 'default', 'logs', identity],
                        capture_output=True, timeout=10, check=True)
                    raise RuntimeError((logs.stdout + logs.stderr).decode(errors='replace')[-2000:])
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.2)
        with tempfile.TemporaryDirectory(prefix='talli-managed-init-regression-') as directory:
            result = exercise(identity, settings, Path(directory).resolve(), pg_restore)
    finally:
        if identity:
            info = json.loads(docker('inspect', identity))[0]
            assert info['Id'] == identity and info['Config']['Labels']['talli.managed-init-regression'] == name
            assert info['Image'] == owned.IMAGE.split('@')[1]
            docker('rm', '-f', identity)
    print(json.dumps({**result, 'ownedContainerRemoved': True}, sort_keys=True))


if __name__ == '__main__':
    main()
