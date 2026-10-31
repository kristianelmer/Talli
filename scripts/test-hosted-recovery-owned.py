#!/usr/bin/env python3
"""Opt-in synthetic PostgreSQL 17 regression; creates and removes only its own container.

Needs cached image, Docker, psycopg and pg_restore >=17. No hosted credentials,
environment DSNs, project operations or image downloads are used.
"""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import argparse
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from uuid import uuid4

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/backend/src'))
from talli_backend.adapters import hosted_backup_recovery as recovery
from talli_backend.adapters.hosted_recovery_access import ACCESS_SQL, DATABASE_ACCESS_SQL, row_commitments
from talli_backend.adapters.hosted_recovery_capture import ManagedCapture, digest, encoded
from talli_backend.adapters.hosted_recovery_sql import CATALOG_SQL, GUC, execute_batch
from talli_backend.adapters.hosted_recovery_target import HostedDesignation, SupabaseRecoveryTarget

IMAGE = 'public.ecr.aws/supabase/postgres@sha256:f6be70aeb2946183fee4eb8c4fae23caf9c66f7cc4984d69d28832a975535c3d'
SOURCE, TARGET, ORG = 'a' * 20, 'b' * 20, 'c' * 20
FACTS = """select current_setting('server_version_num')::integer,d.datlocprovider,
pg_encoding_to_char(d.encoding),d.datcollate,d.datctype,
coalesce(to_jsonb(d)->>'datlocale',to_jsonb(d)->>'daticulocale',''),pg_get_userbyid(d.datdba)
from pg_database d where datname='postgres'"""
ROLES = """select jsonb_build_object('roles',(select jsonb_agg(jsonb_build_array(
rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,rolbypassrls,
rolconnlimit,rolvaliduntil::text,rolconfig)order by rolname)from pg_roles),
'memberships',(select jsonb_agg(jsonb_build_array(r.rolname,u.rolname,g.rolname,
m.admin_option,m.inherit_option,m.set_option)order by r.rolname,u.rolname,g.rolname)
from pg_auth_members m join pg_roles r on r.oid=m.roleid join pg_roles u on u.oid=m.member
join pg_roles g on g.oid=m.grantor))"""
MANAGED = """
alter schema public owner to postgres;
create schema auth authorization postgres;
create schema storage authorization postgres;
create schema extensions authorization postgres;
create table auth.users(id uuid primary key,banned_until timestamptz);
create table auth.refresh_tokens(id bigserial primary key,token text);
create table auth.schema_migrations(version text primary key);
insert into auth.schema_migrations values('synthetic-managed-auth');
create table storage.buckets(id text primary key,public boolean);
create table storage.objects(id uuid primary key,bucket_id text,name text);
create table storage.buckets_vectors(id uuid primary key);
create table storage.migrations(id integer primary key,created_at timestamptz);
insert into storage.migrations values(1,clock_timestamp());
"""
APPLICATION = """
create role restore_owner nologin;
create role restore_function_owner nologin;
create role restore_runtime login;
grant restore_owner,restore_function_owner,restore_runtime to postgres with inherit true,set true;
create schema ledger authorization restore_owner;
grant create,usage on schema ledger to restore_function_owner;
create table ledger.items(id integer primary key,payload text);
alter table ledger.items owner to restore_owner;
create function ledger.read_count()returns bigint language sql security definer
set search_path='' as $$select count(*)from ledger.items$$;
alter function ledger.read_count()owner to restore_function_owner;
grant select on ledger.items to restore_function_owner;
revoke create on schema ledger from restore_function_owner;
create function public.fixture_count()returns integer language sql as $$select 3$$;
revoke all on function public.fixture_count()from public;
grant execute on function public.fixture_count()to restore_runtime with grant option;
grant usage on schema extensions to restore_runtime;
alter table ledger.items enable row level security;
create policy owner_only on ledger.items to restore_runtime using(false);
insert into ledger.items values(1,E'body; with\nnewline and \\slash');
insert into auth.users values('00000000-0000-0000-0000-000000000001',null);
insert into auth.refresh_tokens(id,token)values(132,'synthetic-token');
select setval('auth.refresh_tokens_id_seq',132,true);
grant restore_owner,restore_function_owner,restore_runtime to postgres with inherit false,set false;
"""


def run(arguments, **kwargs):
    result = subprocess.run(arguments, capture_output=True, timeout=90, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')[-2000:])
    return result.stdout


def save(path, value):
    path.write_bytes(value if isinstance(value, bytes) else encoded(value))
    path.chmod(0o600)
    return path


class CheckedConnection:
    def __init__(self, db, *, lose_commit): self.db, self.lose_commit = db, lose_commit
    def __getattr__(self, key): return getattr(self.db, key)
    def commit(self):
        limits = dict(self.db.execute("select name,setting::int from pg_settings where "
            "name in('statement_timeout','lock_timeout')").fetchall())
        assert all(0 < value <= 240000 for value in limits.values()), 'native replay removed SQL deadlines'
        self.db.commit()
        if self.lose_commit:
            raise ConnectionError('synthetic lost commit acknowledgement')


class LocalTarget(SupabaseRecoveryTarget):
    def __init__(self, settings, folder):
        # Only the provider metadata/Storage port is replaced. SQL uses the
        # production transport's identity, CA-file and connection deadline path.
        ca = save(folder / 'local-transport-ca.fixture', b'local no-TLS fixture')
        self.settings = {**settings, 'sslmode': 'disable', 'sslrootcert': str(ca)}
        self._ca_sha256 = digest(ca.read_bytes())
        self.designation = HostedDesignation(TARGET, ORG, 'synthetic-recovery', 'eu-west-1')
        self.lose_commit = False
    def validate(self, **kwargs):
        assert kwargs['source_project'] == SOURCE
    @contextmanager
    def database(self):
        with super().database() as db:
            lost, self.lose_commit = self.lose_commit, False
            yield CheckedConnection(db, lose_commit=lost)
    def restore_object(self, obj, raw):
        assert digest(raw) == obj['sha256']
        return {**obj, 'servedExact': True, 'publicRouteDenied': True}


def exercise(container, settings, folder, pg_restore):
    def connect(database='postgres', autocommit=False):
        return psycopg.connect(**{**settings, 'dbname': database, 'user': 'supabase_admin'}, autocommit=autocommit)
    with connect(autocommit=True) as db:
        db.execute('create role postgres login createrole createdb bypassrls')
        db.execute('alter database postgres owner to postgres')
        db.execute('grant set on parameter session_replication_role to postgres')
        for role in ('anon', 'authenticated', 'service_role'):
            db.execute('create role ' + role)
    with connect() as db:
        db.execute('set role postgres')
        execute_batch(db, (MANAGED + APPLICATION).encode())
    capture_dir = folder / 'capture'; capture_dir.mkdir(mode=0o700)
    with connect() as db:
        execute_batch(db, GUC.encode())
        tables = [list(r) for r in db.execute("select schemaname,tablename from pg_tables where schemaname in('ledger','public','auth','storage')order by 1,2")]
        facts = list(db.execute(FACTS).fetchone())
        extensions = [list(r) for r in db.execute('select e.extname,e.extversion,pg_get_userbyid(e.extowner),n.nspname from pg_extension e join pg_namespace n on n.oid=e.extnamespace order by e.extname')]
        catalog = db.execute(CATALOG_SQL).fetchone()[0]
        roles = db.execute(ROLES).fetchone()[0]
        access = db.execute(ACCESS_SQL, (['public', 'ledger'], ['public', 'ledger'])).fetchone()[0]
        database_access = db.execute(DATABASE_ACCESS_SQL).fetchone()[0]
        rows = row_commitments(db, tables)
    dump = run(['docker', 'exec', container, 'pg_dump', '-h', '/tmp', '-U', 'supabase_admin', '-d', 'postgres', '-Fc'])
    body = b'private synthetic original'
    obj = {'bucket': 'private-files', 'name': 'company/2025/original.pdf',
        'sha256': digest(body), 'bytes': len(body), 'file': 'object-' + digest(body) + '.bin'}
    files = {'database.dump': dump, 'roles.sql': b'-- no passwords; structured role facts are authoritative\n',
        'contents.list': run([pg_restore, '--list'], input=dump),
        'source-profile.json': encoded({'projectRef': SOURCE, 'facts': facts, 'extensions': extensions,
            'tables': tables, 'capturedAt': datetime.now(timezone.utc).isoformat()}),
        'source-tables.private.json': encoded(rows), 'source-catalog.private.json': encoded(catalog),
        'source-roles.private.json': encoded(roles), 'object-manifest.private.json': encoded([obj]), obj['file']: body}
    for name, raw in files.items(): save(capture_dir / name, raw)
    header = save(folder / 'header.json', {'format': 'talli-designated-hosted-capture-v1',
        'projectRef': SOURCE, 'pins': {n: {'bytes': len(b), 'sha256': digest(b)} for n, b in files.items()}})
    access_file = save(folder / 'access.json', {'sourceProject': SOURCE,
        'sourceCatalogStillExactToOriginal': True, 'access': access, 'databaseAccess': database_access})
    capture = ManagedCapture.open(directory=capture_dir, header=header,
        header_sha256=digest(header.read_bytes()), access=access_file, access_sha256=digest(access_file.read_bytes()))
    def fresh():
        with connect('template1', True) as db:
            db.execute('drop database postgres with(force)')
            db.execute('create database postgres owner postgres')
            for name in ('restore_owner', 'restore_function_owner', 'restore_runtime'):
                db.execute('drop role ' + name)
        with connect() as db:
            db.execute('set role postgres')
            execute_batch(db, MANAGED.encode())
            # Fresh managed projects can introduce extra privileges not revoked
            # by native ACL delta statements.
            db.execute('alter default privileges in schema public grant execute on functions to anon,authenticated')
    fresh()
    target = LocalTarget(settings, folder)
    with connect() as db:
        original_auth_history = db.execute('select version from auth.schema_migrations').fetchall()
        original_storage_history = db.execute('select id,created_at from storage.migrations').fetchall()
    for case in ('unrelated-managed-table', 'occupied-managed-table'):
        with connect() as db:
            if case == 'unrelated-managed-table':
                db.execute('create table extensions.unrelated_customer_data(payload text)')
                db.execute("insert into extensions.unrelated_customer_data values('unrelated')")
            else:
                db.execute("insert into auth.refresh_tokens(token)values('unrelated')")
            original_access = db.execute(DATABASE_ACCESS_SQL).fetchone()[0]
        rejected_work = folder / case; rejected_work.mkdir(mode=0o700)
        rejected = recovery.HostedBackupRecovery(capture=capture, target=target,
            work=rejected_work, pg_restore=pg_restore)
        try:
            rejected.restore(expected_plan_sha256=rejected.plan_sha)
            raise AssertionError('nonempty provider namespace accepted')
        except ValueError as error:
            assert str(error) == 'hosted_target_not_empty'
        try:
            rejected.contain(expected_plan_sha256=rejected.plan_sha)
            raise AssertionError('nonempty provider namespace classified as rollback')
        except ValueError as error:
            assert str(error) == 'hosted_recovery_marker_unavailable'
        with connect() as db:
            assert db.execute(DATABASE_ACCESS_SQL).fetchone()[0] == original_access
            if case == 'unrelated-managed-table':
                assert db.execute('select payload from extensions.unrelated_customer_data').fetchone()[0] == 'unrelated'
                db.execute('drop table extensions.unrelated_customer_data')
            else:
                assert db.execute('select token from auth.refresh_tokens').fetchone()[0] == 'unrelated'
                db.execute('truncate auth.refresh_tokens restart identity')
    # A native dump inconsistent with its independently captured row proof must
    # roll back roles, schemas, data and marker, with containment still usable.
    wrong_rows = {**capture.rows, 'ledger.items': {'rows': 1, 'sha256': '0' * 64}}
    failure_work = folder / 'failed-work'; failure_work.mkdir(mode=0o700)
    failed = recovery.HostedBackupRecovery(capture=replace(capture, rows=wrong_rows),
        target=target, work=failure_work, pg_restore=pg_restore)
    try:
        failed.restore(expected_plan_sha256=failed.plan_sha)
        raise AssertionError('inconsistent row proof accepted')
    except ValueError as error:
        assert str(error) == 'hosted_restored_table_bytes_changed'
    with target.database() as db:
        assert db.execute("select to_regnamespace('ledger')").fetchone()[0] is None
        assert db.execute('select count(*)from auth.users').fetchone()[0] == 0
        assert db.execute("select count(*)from pg_roles where rolname='restore_runtime'").fetchone()[0] == 0
        assert db.execute("select to_regclass('_talli_recovery.attempt')").fetchone()[0] is None
    assert failed.contain(expected_plan_sha256=failed.plan_sha)['phase'] == 'contained'
    work = folder / 'work'; work.mkdir(mode=0o700)
    operator = recovery.HostedBackupRecovery(capture=capture, target=target, work=work, pg_restore=pg_restore)
    operator.plan()
    target.lose_commit = True
    try:
        operator.restore(expected_plan_sha256=operator.plan_sha)
        raise AssertionError('commit acknowledgement failure not injected')
    except ConnectionError:
        pass
    state = operator.restore(expected_plan_sha256=operator.plan_sha)
    assert state['phase'] == 'verified_quarantined'
    with target.database() as db:
        assert db.execute('select last_value,is_called from auth.refresh_tokens_id_seq').fetchone() == (132, True)
        assert db.execute('select count(*)from auth.users where banned_until is null').fetchone()[0] == 0
        assert not db.execute("select rolcanlogin from pg_roles where rolname='restore_runtime'").fetchone()[0]
        assert not db.execute("select has_function_privilege('anon','public.fixture_count()','execute')").fetchone()[0]
        assert db.execute("select has_schema_privilege('restore_runtime','extensions','usage')").fetchone()[0]
        assert db.execute("select pg_get_userbyid(proowner)from pg_proc where proname='read_count'").fetchone()[0] == 'restore_function_owner'
        assert db.execute('select version from auth.schema_migrations').fetchall() == original_auth_history
        assert db.execute('select id,created_at from storage.migrations').fetchall() == original_storage_history
    shutil.rmtree(capture_dir)
    clean = recovery.HostedBackupRecovery.from_state(target=target, work=work, expected_plan_sha256=operator.plan_sha)
    assert clean.inspect()['databaseMarkerPresent'] is True
    with connect() as blocker:
        blocker.execute('select id from auth.users for update')
        # A watchdog makes the old unbounded implementation fail deterministically
        # instead of hanging this owned regression forever.
        watchdog = threading.Timer(12, blocker.rollback)
        watchdog.daemon = True
        watchdog.start()
        started = time.monotonic()
        try:
            try:
                clean.contain(expected_plan_sha256=operator.plan_sha)
                raise AssertionError('containment waited for watchdog instead of its SQL deadline')
            except psycopg.errors.LockNotAvailable:
                assert time.monotonic() - started < 12
        finally:
            watchdog.cancel()
            blocker.rollback()
    assert clean.contain(expected_plan_sha256=operator.plan_sha)['phase'] == 'contained'
    assert clean.contain(expected_plan_sha256=operator.plan_sha)['phase'] == 'contained'
    return {'status': 'pass', 'scope': 'synthetic local PostgreSQL, no hosted replay',
        'tablesCompared': state['verification']['tablesCompared'], 'sequence132': True,
        'crossSchemaOwner': True, 'defaultAclRepair': True, 'managedCustomUsage': True,
        'lostCommitResume': True, 'rollbackBeforeCommit': True, 'customRoleGrantorsAndOptions': True,
        'authAndRuntimeQuarantine': True, 'repeatableContainment': True,
        'containmentRowLockDeadline': True, 'nonemptyManagedNamespaceRefused': True,
        'providerMigrationRowsPreserved': True, 'inspectAfterCaptureLoss': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-restore', required=True, type=Path)
    args = parser.parse_args()
    pg_restore = str(args.pg_restore.resolve(strict=True))
    name = 'talli-recovery-regression-' + uuid4().hex[:12]
    label = 'talli.recovery-regression=' + name
    identity = None
    try:
        identity = run(['docker', 'run', '-d', '--pull=never', '--name', name, '--label', label,
            '--cap-drop=ALL', '--security-opt=no-new-privileges', '--read-only', '--user', '100:101',
            '--pids-limit', '128', '--memory', '1g', '--cpus', '2', '--tmpfs',
            '/var/lib/postgresql/data:rw,nosuid,nodev,uid=100,gid=101,mode=0700,size=512m',
            '--tmpfs', '/tmp:rw,nosuid,nodev,uid=100,gid=101,mode=0700,size=32m',
            '-p', '127.0.0.1::5432', '--entrypoint', '/bin/sh', '--no-healthcheck', IMAGE, '-c',
            'initdb -D /var/lib/postgresql/data -U supabase_admin --locale=C.UTF-8 -A trust >/tmp/init.log && echo "host all all 0.0.0.0/0 trust" >>/var/lib/postgresql/data/pg_hba.conf && exec postgres -D /var/lib/postgresql/data -h "*" -k /tmp']).decode().strip()
        info = json.loads(run(['docker', 'inspect', identity]))[0]
        port = int(info['NetworkSettings']['Ports']['5432/tcp'][0]['HostPort'])
        settings = {'host': '127.0.0.1', 'port': port, 'dbname': 'postgres',
            'user': 'supabase_admin', 'connect_timeout': 2}
        deadline = time.monotonic() + 25
        while True:
            try:
                with psycopg.connect(**settings): break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline: raise
                time.sleep(.2)
        with tempfile.TemporaryDirectory(prefix='talli-recovery-regression-') as directory:
            result = exercise(identity, settings, Path(directory).resolve(), pg_restore)
    finally:
        if identity:
            info = json.loads(run(['docker', 'inspect', identity]))[0]
            assert info['Id'] == identity and info['Config']['Labels'].get('talli.recovery-regression') == name
            run(['docker', 'rm', '-f', identity])
    print(json.dumps({**result, 'ownedContainerRemoved': True}, sort_keys=True))


if __name__ == '__main__':
    main()
