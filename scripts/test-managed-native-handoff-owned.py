#!/usr/bin/env python3
"""Changed seam on two private native PostgreSQL clusters; no hosted calls.

Uses actual native Documents SQL/RLS and managed restore SQL. The prior native
restore/binding, Docker identity port and Storage transport are explicit fixtures.
No Auth, hosted replay, offsite or whole-service recovery acceptance is claimed.
"""
import argparse
import asyncio
import base64
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4, uuid5

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/backend/src'))
from talli_backend.adapters.deletion_journal import LocalDeletionJournal
from talli_backend.adapters.hosted_backup_recovery import HostedBackupRecovery
from talli_backend.adapters.hosted_recovery_capture import ManagedCapture, digest, encoded
from talli_backend.adapters.hosted_recovery_target import HostedDesignation
from talli_backend.adapters.managed_disposition_binding import ManagedDispositionBinding
from talli_backend.adapters.native_disposition_preflight import _bytes, _sha, _EXPORT
from talli_backend.adapters.native_disposition_recovery import native_backup_commitment
from talli_backend.adapters.native_managed_handoff import capture_native_managed_handoff
from talli_backend.adapters.postgres_document_disposition import (
    OwnedNativeDocumentsTarget, native_document_generation,
)
from talli_backend.modules.company_access.public import (
    CompanyDispositionPlan, DispositionRecord, DispositionSession, LocalDocumentsFacts,
    authorize_local_documents_disposition,
)

FLOOR = """
alter schema public owner to postgres;
create schema auth authorization postgres; create schema storage authorization postgres;
create schema extensions authorization postgres;
create table auth.users(id uuid primary key,banned_until timestamptz);
create table auth.refresh_tokens(id bigserial primary key,token text);
create table storage.buckets(id text primary key,public boolean);
create table storage.objects(id uuid primary key,bucket_id text,name text,version uuid,metadata jsonb);
"""
APPLICATION = """
create role documents_store_owner nologin noinherit;
create role documents_executor nologin noinherit;
grant documents_store_owner,documents_executor to postgres with inherit true,set true;
create schema documents authorization documents_store_owner;
grant usage,create on schema public to documents_store_owner;
create table public.documents(id uuid primary key,company_id uuid,income_year int,storage_key text,
 byte_length int,content_sha256 text,created_at timestamptz,retention_years int,created_by uuid);
alter table public.documents owner to documents_store_owner;
revoke create on schema public from documents_store_owner;
alter table public.documents enable row level security;
alter table public.documents force row level security;
create policy doc_read on public.documents for select to documents_store_owner using(true);
create policy doc_write on public.documents for insert to documents_store_owner with check(true);
create policy doc_update on public.documents for update to documents_store_owner using(true) with check(true);
create table documents.evidence_references(document_id uuid,company_id uuid,source_capability text,source_record_id uuid);
alter table documents.evidence_references owner to documents_store_owner;
create table documents.retained_originals(document_id uuid,company_id uuid,content bytea);
alter table documents.retained_originals owner to documents_store_owner;
create function documents.has_evidence_references_v1(d uuid) returns boolean language sql
as $$select exists(select 1 from documents.evidence_references where document_id=d)$$;
alter function documents.has_evidence_references_v1(uuid) owner to documents_store_owner;
create table public.company_memberships(company_id uuid,user_id uuid,accepted boolean);
create function public.company_access_is_accepted_owner_v1(c uuid)returns boolean language sql
security definer set search_path='' as $$select exists(select 1 from public.company_memberships
 where company_id=c and accepted and user_id=nullif(current_setting('talli.verified_actor_id',true),'')::uuid)$$;
create table public.company_archive_source_generations(company_id uuid,income_year int,generation bigint,
 primary key(company_id,income_year));
create function public.company_archive_lock_company_v1(c uuid)returns void language sql
as $$select pg_advisory_xact_lock(hashtextextended(c::text,157))$$;
create function public.company_archive_track_source_write_v1()returns trigger language plpgsql
security definer set search_path='' as $$begin
 update public.company_archive_source_generations set generation=generation+1
 where company_id=old.company_id and income_year=old.income_year;return old;end$$;
create trigger company_archive_track_documents after delete on public.documents
for each row execute function public.company_archive_track_source_write_v1('year','company_id');
"""


def run(args, **kwargs):
    p = subprocess.run([str(x) for x in args], capture_output=True,
        timeout=kwargs.pop('timeout', 30), **kwargs)
    if p.returncode: raise RuntimeError(p.stderr.decode(errors='replace')[-2000:])
    return p.stdout


def write(path, raw):
    path.write_bytes(raw if isinstance(raw, bytes) else encoded(raw)); path.chmod(0o600)
    return path


class Cluster:
    def __init__(self, root, binaries):
        self.root, self.bin = root, binaries
        root.mkdir(mode=0o700); self.socket = root / 'socket'; self.socket.mkdir(mode=0o700)
        run([binaries / 'initdb', '-D', root / 'db', '-U', 'supabase_admin',
            '--auth-local=trust', '--no-locale', '--encoding=UTF8'])
        try:
            run([binaries / 'pg_ctl', '-D', root / 'db', '-l', root / 'server.log',
                '-o', f"-k {self.socket} -c listen_addresses='' -p 55441", '-w', 'start'])
            self.settings = dict(host=str(self.socket), port=55441, dbname='postgres', user='supabase_admin')
            with self.connect(True) as db:
                db.execute('create role postgres login createrole createdb bypassrls; '
                    'alter database postgres owner to postgres; '
                    'grant set on parameter session_replication_role to postgres')
                for name in ('anon', 'authenticated', 'service_role'): db.execute('create role ' + name)
            with self.connect() as db:
                db.execute('set role postgres'); db.execute(FLOOR, prepare=False)
        except BaseException:
            if (root / 'db/postmaster.pid').exists(): self.stop()
            raise

    def connect(self, autocommit=False, **settings):
        return psycopg.connect(**{**self.settings, **settings}, autocommit=autocommit)

    def stop(self): run([self.bin / 'pg_ctl', '-D', self.root / 'db', '-m', 'fast', '-w', 'stop'])

    def query(self, statement, parameters=None):
        output = []
        with self.connect() as db:
            cur = db.execute(statement, parameters, prepare=False)
            while True:
                if cur.description:
                    for row in cur.fetchall():
                        value = row[0]
                        output.append(json.dumps(value, default=str, ensure_ascii=False)
                            if isinstance(value, (dict, list)) else str(value))
                if not cur.nextset(): break
        return '\n'.join(output).encode()

    def dump(self, snapshot=None, *, bounded=False):
        return run([self.bin / 'pg_dump', '-h', self.socket, '-p', '55441', '-U',
            'supabase_admin', '-d', 'postgres', '-Fc', '--lock-wait-timeout=3000',
            *(['--snapshot=' + snapshot] if snapshot else [])],
            timeout=8 if bounded else 30,
            env={**os.environ, 'PGOPTIONS': '-c client_connection_check_interval=1s'})


class NativeFixture:
    connection = OwnedNativeDocumentsTarget.connection
    source_fence = OwnedNativeDocumentsTarget.source_fence

    def __init__(self, cluster, files, login):
        self.cluster, self.files, self.login = cluster, files, login
        self.system = cluster.query('select system_identifier::text from pg_control_system()').decode()
        self.target = str(uuid4()); self.database = 'fixture-only-native-db'; self.storage = 'fixture-only-storage'
        self.database_url = make_conninfo(**{**cluster.settings, 'user': login, 'password': 'synthetic'})
        self._source_connection = ContextVar('fixture_checked_native_connection', default=None)
        self.lose_delete = False; self.deletes = 0

    def validate(self):
        assert self.cluster.socket.is_dir()
        assert self.cluster.query('select system_identifier::text from pg_control_system()').decode() == self.system

    def _query(self, statement): return self.cluster.query(statement)

    def manifest(self):
        return [{'path': str(p.relative_to(self.files)), 'bytes': p.stat().st_size,
            'sha256': digest(p.read_bytes())} for p in sorted(self.files.rglob('*')) if p.is_file()]

    def objects(self, **request):
        action = request['action']
        if action == 'manifest': return self.manifest()
        if action == 'inventory':
            values = {}
            with self.cluster.connect() as db:
                for key in request['keys']:
                    row = db.execute('select version::text from storage.objects where name=%s', (key,)).fetchone()
                    values[key] = {'status': 200, 'body': json.dumps({'version': row[0]})} if row else {
                        'status': 400, 'body': json.dumps({'statusCode': '404', 'error': 'not_found',
                            'message': 'Object not found'})}
            return {'files': self.manifest(), 'objects': values}
        if action == 'http':
            assert request['method'] == 'DELETE' and request['path'] == '/object/company-documents'
            with self.cluster.connect() as db:
                for key in request['body']['prefixes']: db.execute('delete from storage.objects where name=%s', (key,))
            self.deletes += 1
            if self.lose_delete:
                self.lose_delete = False
                raise ConnectionError('synthetic lost Storage retirement response')
            return {'status': 200, 'body': '{}'}
        assert action == 'gc'
        approved = {f['path']: f for f in request['files']}
        for item in self.manifest():
            if item['path'].startswith(request['prefix']):
                assert approved[item['path']] == item
                (self.files / item['path']).unlink()
        return {}

    def _run(self, *args, data=None):
        if 'pg_dump' in args:
            assert 'timeout' in args and '--kill-after=1s' in args and '8s' in args
            return self.cluster.dump(next(x.split('=', 1)[1] for x in args if x.startswith('--snapshot=')), bounded=True)
        assert args[:4] == ('exec', '-i', self.storage, 'node') and args[-1] == _EXPORT
        result = []
        for item in json.loads(data)['files']:
            raw = (self.files / item['path']).read_bytes()
            assert len(raw) == item['bytes'] and digest(raw) == item['sha256']
            result.append({**item, 'base64': base64.b64encode(raw).decode()})
        return encoded(result)


class ManagedFixture:
    def __init__(self, cluster):
        self.cluster = cluster
        self.designation = HostedDesignation('b'*20, 'c'*20, 'synthetic-managed-handoff', 'eu-west-1')
        self.objects = {}
    def validate(self, **values): assert values['source_project'].startswith('native:')
    @contextmanager
    def database(self):
        with self.cluster.connect(options='-c statement_timeout=240000 -c lock_timeout=10000') as db:
            db.execute('set role postgres'); yield db
    def restore_object(self, obj, raw):
        assert digest(raw) == obj['sha256']
        key = (obj['bucket'], obj['name'])
        if key in self.objects: assert self.objects[key] == raw
        else:
            self.objects[key] = raw
            with self.cluster.connect() as db:
                db.execute('insert into storage.buckets values(%s,false)on conflict do nothing', (obj['bucket'],))
                db.execute('insert into storage.objects values(%s,%s,%s,%s,%s)',
                    (uuid4(), *key, uuid4(), Jsonb({'mimetype': obj['contentType']})))
        return {**obj, 'servedExact': True, 'publicRouteDenied': True}


def setup_source(cluster, folder):
    with cluster.connect() as db:
        db.execute('set role postgres'); db.execute(APPLICATION, prepare=False)
    migration = ROOT / 'supabase/migrations/20261028042019_documents_local_native_disposition.sql'
    cluster.query('set role postgres;' + migration.read_text())
    login = 'talli_native_disposition_' + uuid4().hex[:16]
    cluster.query('set role postgres; create role ' + login + ' login noinherit; '
        'grant documents_disposition_executor to ' + login + ' with set true,inherit false')
    files = folder / 'native-files'; files.mkdir(mode=0o700)
    target = NativeFixture(cluster, files, login)
    original = uuid4(); company = uuid5(original, 'local-documents-disposition-fixture-v1')
    owner, reviewer = uuid4(), uuid4(); rows = {}; objects = {}; records = []; held = []
    now = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    with cluster.connect() as db:
        db.execute('insert into auth.users values(%s,null)', (owner,))
        db.execute("insert into storage.buckets values('company-documents',false)")
        db.execute('insert into public.company_memberships values(%s,%s,true)', (company, owner))
        for year, action in ((2010, 'erase'), (2025, 'retain')):
            record = uuid4(); key = f'{company}/{year}/{record}/fixture.pdf'; version = uuid4()
            body = b'%PDF-1.7\nSynthetic native handoff ' + str(record).encode()
            db.execute('insert into public.documents values(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (record, company, year, key, len(body), digest(body),
                 datetime(2010 if action == 'erase' else 2025, 1, 1, tzinfo=timezone.utc),
                 1 if action == 'erase' else 20, owner))
            db.execute('insert into public.company_archive_source_generations values(%s,%s,0)', (company, year))
            db.execute('insert into storage.objects values(%s,%s,%s,%s,%s)',
                (uuid4(), 'company-documents', key, version, Jsonb({'mimetype': 'application/pdf'})))
            row = db.execute('select row_to_json(t)from public.documents t where id=%s', (record,)).fetchone()[0]
            versions = []
            for selected_version in ([uuid4(), version] if action == 'erase' else [uuid4(), uuid4(), version]):
                path = 'stub/stub/company-documents/' + key + '/' + str(selected_version)
                file = files / path; file.parent.mkdir(parents=True, exist_ok=True); write(file, body)
                item = {'path': path, 'bytes': len(body), 'sha256': digest(body)}; versions.append(item)
                held.append({**item, 'base64': base64.b64encode(body).decode()})
            versions.sort(key=lambda f: f['path'])
            rows[str(record)] = row; objects[str(record)] = {
                'storageKey': key, 'currentVersion': str(version), 'files': versions}
            records.append(DispositionRecord(owner='documents', record_id=record, income_year=year,
                generation=native_document_generation(row, versions), content_sha256=digest(body),
                action=action, retention_until=now+timedelta(days=-1 if action == 'erase' else 3650)))
            if action == 'retain':
                db.execute('insert into documents.retained_originals values(%s,%s,%s)', (record, company, body))
                db.execute('insert into documents.evidence_references values(%s,%s,%s,%s)',
                    (record, company, 'synthetic-retained-owner', uuid4()))
    generations = ((2010, 0), (2025, 0))
    generation = _sha({'generations': generations, 'snapshot': rows, 'objects': objects})
    plan = CompanyDispositionPlan(operation_id=uuid4(), company_id=company, choice='delete',
        years=(2010, 2025), generation=generation, records=tuple(records), inventory_sha256='0'*64,
        support_case_id=uuid4())
    plan = plan.model_copy(update={'inventory_sha256': plan.inventory_digest()})
    with cluster.connect() as db:
        references = db.execute('select coalesce(json_agg(t),\'[]\')from documents.evidence_references t').fetchone()[0]
        originals = db.execute('select coalesce(json_agg(t),\'[]\')from documents.retained_originals t').fetchone()[0]
    exported = write(folder / 'held.documents-export.json', _bytes({'scope': 'synthetic-local-documents-only',
        'companyId': str(company), 'generation': generation, 'documents': rows,
        'references': references, 'originals': originals, 'files': held}))
    def session(subject, role):
        return DispositionSession(subject=subject, session_id=uuid4(), role=role, company_id=company, mfa_at=now)
    facts = LocalDocumentsFacts(target_id=original, source_sha256='a'*64, source_generations=generations,
        paid_expires_at=now-timedelta(days=400), recorded_export_until=now-timedelta(days=100),
        export_until=now-timedelta(days=100), documents_export_sha256=digest(exported.read_bytes()),
        owner=session(owner, 'owner'), reviewer=session(reviewer, 'reviewer'),
        review_plan_sha256=digest(plan.model_dump_json().encode()), support_case_id=plan.support_case_id)
    permit = authorize_local_documents_disposition(plan, facts, now=now)
    journal = LocalDeletionJournal.initialize(folder / 'journal.sqlite', customer_root=files)
    head = journal.append(permit); commitment = digest(permit.model_dump_json().encode())
    with cluster.connect() as db:
        for identity, system in ((str(original), '111'), (target.target, target.system)):
            db.execute('insert into documents.local_native_disposition_targets values(%s,%s,%s,%s)',
                (identity, system, login, 'a'*64))
        db.execute('insert into documents.local_native_disposition_plans(operation_id,company_id,plan_sha256,'
            'operator_login,approved_owner,company_generation,metadata_snapshot,object_manifest,fixture_records,'
            'authorization_evidence)values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (plan.operation_id, company, commitment, login, owner, generation, Jsonb(rows), Jsonb(objects),
             [r.record_id for r in records if r.action == 'erase'], Jsonb(json.loads(permit.model_dump_json()))))
    backup = folder / 'independent-native-backup'; backup.mkdir(mode=0o700)
    # The accepted native restore/binding is a fixture boundary here. Real row,
    # role, object and owner replay behavior begins at the registered source.
    for name in ('database.dump', 'roles.sql', 'storage_vectors.dump', 'objects.tar',
            'object-manifest.json', 'object-attributes.json', 'bindings.private.json'):
        write(backup / name, cluster.dump() if name == 'database.dump' else b'Independent native prerequisite fixture')
    backup_sha = native_backup_commitment(backup)
    native = write(folder / 'independent-native-binding.json', {'version': 1, 'sourceTarget': str(original),
        'target': target.target, 'sourceSystemIdentifier': '111', 'systemIdentifier': target.system,
        'operatorLogin': login, 'backupSha256': backup_sha, 'journal': asdict(head),
        'authorizationSha256': commitment, 'nativeProfile': {'fixture': 'prior accepted native restore/binding'}})
    return target, dict(journal=journal, minimum=head, receipt=folder / 'replay.json', native_binding=native,
        native_binding_sha256=digest(native.read_bytes()), backup=backup, backup_sha256=backup_sha,
        exports=[exported]), permit


def exercise(source, destination, folder, pg_restore):
    native, inputs, permit = setup_source(source, folder)
    export_before = Path(inputs['exports'][0]).read_bytes(); backup_before = native_backup_commitment(inputs['backup'])
    native.lose_delete = True
    try:
        asyncio.run(capture_native_managed_handoff(target=native, destination=folder / 'interrupted',
            pg_restore=pg_restore, **inputs))
        raise AssertionError('lost retirement response must stop capture')
    except ConnectionError:
        assert not (folder / 'interrupted').exists()
    assert json.loads(source.query('select json_agg(state)from documents.local_native_disposition_receipts')) == ['prepared']
    with source.connect(True) as blocker:
        blocker.execute('begin; lock table storage.buckets in access exclusive mode', prepare=False)
        started = time.monotonic()
        try:
            asyncio.run(capture_native_managed_handoff(target=native, destination=folder / 'blocked',
                pg_restore=pg_restore, **inputs))
            raise AssertionError('blocked snapshot must stop at its server deadline')
        except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled):
            assert time.monotonic() - started < 8
            assert not (folder / 'blocked').exists()
        finally:
            blocker.rollback()
    handoff = asyncio.run(capture_native_managed_handoff(target=native, destination=folder / 'complete',
        pg_restore=pg_restore, **inputs))
    assert native.deletes == 1, 'replay must reconcile the original Storage retirement'
    assert json.loads(source.query('select json_agg(state)from documents.local_native_disposition_receipts')) == ['erased']
    custody = ManagedDispositionBinding(customer_root=handoff['capture']['directory'], **handoff['disposition'])
    capture = ManagedCapture.open(**handoff['capture'], disposition=custody)
    target = ManagedFixture(destination)
    work = folder / 'managed-work'; work.mkdir(mode=0o700)
    operator = HostedBackupRecovery(capture=capture, target=target, work=work, pg_restore=pg_restore)
    restored = operator.restore(expected_plan_sha256=operator.plan_sha)
    assert restored['phase'] == 'verified_quarantined' and restored['verification']['dispositionReplayCurrent']
    assert capture.rows['documents.local_native_disposition_plans']['rows'] == 1
    assert capture.rows['documents.local_native_disposition_receipts']['rows'] == 1
    assert len(target.objects) == 1
    assert restored['verification']['nativeHistoryFilesCopiedExact'] == 2
    assert json.loads(destination.query('select count(*)from _talli_recovery.native_history')) == 2
    with destination.connect() as db:
        assert not db.execute("select has_table_privilege('anon','_talli_recovery.native_history','SELECT')").fetchone()[0]
        assert not db.execute("select has_schema_privilege('documents_executor','_talli_recovery','USAGE')").fetchone()[0]
    assert json.loads(destination.query('select count(*)from documents.retained_originals')) == 1
    assert json.loads(destination.query('select count(*)from documents.evidence_references')) == 1
    assert Path(inputs['exports'][0]).read_bytes() == export_before
    assert native_backup_commitment(inputs['backup']) == backup_before
    with destination.connect() as db:
        db.execute('grant usage on schema _talli_recovery to anon; '
            'grant select(payload)on _talli_recovery.native_history to anon')
    assert not operator.inspect()['dispositionReplayCurrent']
    try:
        operator.restore(expected_plan_sha256=operator.plan_sha)
        raise AssertionError('history ACL drift must close resume')
    except ValueError as error:
        assert str(error) == 'hosted_disposition_history_copy_changed'
    with destination.connect() as db:
        operator._seal_control(db)
        assert operator._private_control_current(db)
        # Check the database path bound before fetching a corrupt carrier row.
        db.execute("update _talli_recovery.native_history set path=repeat('x',2049) "
            'where path=(select min(path)from _talli_recovery.native_history)')
    assert not operator.inspect()['dispositionReplayCurrent']
    with destination.connect() as db:
        db.execute("update _talli_recovery.native_history set path=%s where path=repeat('x',2049)",
            (min(item['path'] for item in capture.native_history),))
    with destination.connect() as db:
        db.execute("update _talli_recovery.native_history set payload='changed'::bytea "
            'where path=(select min(path)from _talli_recovery.native_history)')
    assert not operator.inspect()['dispositionReplayCurrent']
    try:
        operator.restore(expected_plan_sha256=operator.plan_sha)
        raise AssertionError('changed private history must not be accepted on resume')
    except ValueError as error:
        assert str(error) == 'hosted_disposition_history_copy_changed'
    Path(inputs['journal'].path).unlink()
    assert not operator.inspect()['dispositionReplayCurrent']
    import shutil
    shutil.rmtree(capture.directory)
    reopened = HostedBackupRecovery.from_state(target=target, work=work, expected_plan_sha256=operator.plan_sha)
    assert not reopened.inspect()['dispositionReplayCurrent']
    with destination.connect() as db:
        db.execute('grant usage on schema _talli_recovery to anon; '
            'grant select(payload)on _talli_recovery.native_history to anon')
    assert reopened.contain(expected_plan_sha256=operator.plan_sha)['phase'] == 'contained'
    assert reopened.contain(expected_plan_sha256=operator.plan_sha)['phase'] == 'contained'
    with destination.connect() as db:
        assert reopened._private_control_current(db)
        db.execute('drop table _talli_recovery.native_history')
        db.execute('update auth.users set banned_until=null')
        db.execute('alter role '+native.login+' login')
    try:
        reopened.inspect()
        raise AssertionError('reopened runtime login must fail quarantine inspection')
    except ValueError as error:
        assert str(error) == 'hosted_quarantine_changed'
    assert reopened.contain(expected_plan_sha256=operator.plan_sha)['phase'] == 'contained'
    with destination.connect() as db:
        reopened._quarantined(db, reopened._state()['quarantine'])
        assert db.execute('select count(*)from auth.users where banned_until>%s::timestamptz',
            ('9998-01-01',)).fetchone()[0] == 1
        assert db.execute("select to_regclass('_talli_recovery.native_history')").fetchone()[0] is None
    return {'status': 'pass', 'scope': 'real PostgreSQL native owner/RLS and managed SQL; '
        'prior native restore/binding, Docker identity and Storage transport are fixtures',
        'lostRetirementResumedWithoutSecondDelete': True, 'eraseAndRetain': True,
        'blockedSnapshotServerDeadline': True,
        'heldExportAndBackupUnchanged': True, 'terminalNativeTablesCopiedExact': True,
        'managedPrivateObjectBytesExact': True, 'missingJournalClosesInspection': True,
        'retainedHistoricalFilesCopiedPrivateAndExact': 2,
        'historyCorruptionClosesResumeAndReadiness': True,
        'historyAclDriftClosesResumeAndCaptureLossContainmentRepairsIt': True,
        'databaseHistoryPathsBoundedBeforeFetch': True,
        'missingCarrierContainmentRepairsAuthAndLogins': True,
        'captureLossContainmentRepeated': True, 'hostedCalls': 0, 'publicationAuthorized': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', required=True, type=Path)
    parser.add_argument('--pg-restore', required=True, type=Path)
    args = parser.parse_args()
    if any(k.startswith('PG') and v for k, v in os.environ.items()):
        raise RuntimeError('inherited PostgreSQL settings unsupported')
    from contextlib import contextmanager

    @contextmanager
    def scratch():
        import shutil
        temp = tempfile.mkdtemp(prefix='talli-handoff-', dir=Path('/tmp').resolve())
        try:
            yield temp
        except BaseException:
            # Preserve owned files if shutdown failed; never remove live PGDATA.
            raise
        else:
            shutil.rmtree(temp)

    with scratch() as temp:
        folder = Path(temp); clusters = []
        try:
            for name in ('source', 'managed'):
                clusters.append(Cluster(folder / name, args.pg_bin.resolve()))
            result = exercise(*clusters, folder, str(args.pg_restore.resolve()))
        finally:
            cleanup_errors = []
            for cluster in reversed(clusters):
                try: cluster.stop()
                except Exception as error: cleanup_errors.append(error)
            if cleanup_errors:
                raise ExceptionGroup('owned cluster shutdown failed', cleanup_errors)
    print(json.dumps({**result, 'ownedClustersRemoved': True}, sort_keys=True))
