"""Replay an independently bound native fixture before making its managed copy.

No hosted deletion, registration, project operation or publication is performed.
The original native backup, journal and held exports stay outside the output.
"""
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import base64
import json
import os
from pathlib import Path
import tempfile

from psycopg import sql

from talli_backend.adapters.deletion_journal import LocalReplayReceipt
from talli_backend.adapters.hosted_recovery_access import ACCESS_SQL, DATABASE_ACCESS_SQL
from talli_backend.adapters.hosted_recovery_capture import MANAGED_SCHEMAS, digest, encoded, private_read, qi, require
from talli_backend.adapters.hosted_recovery_sql import CATALOG_SQL, GUC, NativeArchive, compile_program
from talli_backend.adapters.managed_disposition_binding import (
    FORMAT, TABLES, ManagedDispositionBinding, native_custody,
)
from talli_backend.adapters.native_disposition_preflight import _EXPORT
from talli_backend.adapters.postgres_document_disposition import PostgresDocumentDisposition
from talli_backend.application.company_disposition import replay_company_dispositions

FACTS_SQL = """select json_build_array(current_setting('server_version_num')::integer,d.datlocprovider,
pg_encoding_to_char(d.encoding),d.datcollate,d.datctype,
coalesce(to_jsonb(d)->>'datlocale',to_jsonb(d)->>'daticulocale',''),pg_get_userbyid(d.datdba))
from pg_database d where datname='postgres'"""
ROLES_SQL = """select jsonb_build_object('roles',(select jsonb_agg(jsonb_build_array(
rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,rolcanlogin,rolreplication,rolbypassrls,
rolconnlimit,rolvaliduntil::text,rolconfig)order by rolname)from pg_roles),
'memberships',(select coalesce(jsonb_agg(jsonb_build_array(r.rolname,u.rolname,g.rolname,
m.admin_option,m.inherit_option,m.set_option)order by r.rolname,u.rolname,g.rolname),'[]')
from pg_auth_members m join pg_roles r on r.oid=m.roleid join pg_roles u on u.oid=m.member
join pg_roles g on g.oid=m.grantor))"""


def _write(path, body):
    raw = body if isinstance(body, bytes) else encoded(body)
    with path.open('xb') as output:
        os.chmod(path, 0o600); output.write(raw); output.flush(); os.fsync(output.fileno())
    return digest(raw)


class _CurrentCutJournal:
    """Do not let the replay workflow expand an independently reviewed native cut."""
    def __init__(self, journal, minimum):
        self.journal, self.minimum = journal, minimum

    def read(self, *, minimum=None):
        head, entries = self.journal.read(minimum=minimum or self.minimum)
        require(head == self.minimum, 'hosted_disposition_current_cut_required')
        return head, entries

    def applied(self, target, sequence, record, receipt, *, compatible_receipts=()):
        self.journal.applied(target, sequence, record, receipt, compatible_receipts=compatible_receipts)


class _NativeSnapshot:
    def __init__(self, target):
        self.target = target
        self.db = target._source_connection.get()
        require(self.db is not None, 'hosted_disposition_native_fence_required')

    def __enter__(self):
        self.db.execute('set transaction isolation level repeatable read, read only')
        self.db.execute("set local statement_timeout='5s'; set local lock_timeout='3s'; "
            "set local idle_in_transaction_session_timeout='15min'")
        self.snapshot = self.db.execute('select pg_export_snapshot() as snapshot').fetchone()['snapshot']
        return self

    def __exit__(self, *error):
        self.db.rollback()

    def query(self, statement, parameters=()):
        for value in parameters:
            statement = statement.replace('%s', sql.Literal(value).as_string(), 1)
        self.target.validate()
        raw = self.target._query('begin isolation level repeatable read read only; '
            "set local statement_timeout='5s'; set local lock_timeout='3s'; "
            "set local idle_in_transaction_session_timeout='5s'; "
            'set transaction snapshot ' + sql.Literal(self.snapshot).as_string() + '; ' +
            GUC + statement + '; commit;')
        require(len(raw) <= 32 * 1024**2, 'hosted_disposition_snapshot_bound')
        return json.loads(raw)

    def dump(self):
        self.target.validate()
        # Killing only the host Docker client can leave the container process
        # alive. The owned Linux image must supply coreutils timeout; no fallback.
        # pg_dump resets statement_timeout itself, so keep a process deadline and
        # a server disconnect check instead of relying on that startup setting.
        return self.target._run('exec', '-i', '-e', 'PGOPTIONS=-c client_connection_check_interval=1s',
            self.target.database, 'timeout', '--signal=TERM', '--kill-after=1s', '8s',
            'pg_dump', '--lock-wait-timeout=3000', '-h', '/tmp', '-U', 'supabase_admin',
            '-d', 'postgres', '-Fc', '--snapshot=' + self.snapshot)


def _row_facts(snapshot, tables):
    result = {}; total = 0
    for schema, table in tables:
        rows = snapshot.query('select coalesce(json_agg(body order by body collate "C"),\'[]\') '
            'from(select row_to_json(t)::text body from ' + qi(schema) + '.' + qi(table) + ' t)q')
        commitment = sha256()
        for row in rows:
            raw = row.encode(); total += len(raw)
            require(total <= 64 * 1024**2, 'hosted_row_comparison_bound')
            commitment.update(len(raw).to_bytes(8, 'big')); commitment.update(raw)
        result[schema + '.' + table] = {'rows': len(rows), 'sha256': commitment.hexdigest()}
    return result


def _objects(snapshot, held):
    target = snapshot.target
    buckets = snapshot.query("select coalesce(json_agg(json_build_array(id,public)), '[]')from storage.buckets")
    require(all(row == ['company-documents', False] for row in buckets),
        'hosted_disposition_native_bucket_profile_unsupported')
    objects = snapshot.query("select coalesce(json_agg(json_build_array(name,version::text,metadata->>'mimetype')order by name),'[]')"
        "from storage.objects where bucket_id='company-documents'")
    require(len(objects) <= 32 and len({row[0] for row in objects}) == len(objects),
        'hosted_disposition_native_object_profile_unsupported')
    require(snapshot.query('select count(*)from storage.objects') == len(objects),
        'hosted_disposition_native_object_profile_unsupported')
    inventory = target.objects(action='inventory', keys=[row[0] for row in objects]) if objects else {
        'files': target.objects(action='manifest'), 'objects': {}}
    expected = []; historical = []
    for key, version, content_type in objects:
        require(isinstance(content_type, str) and 0 < len(content_type) <= 256 and
            '\r' not in content_type and '\n' not in content_type,
            'hosted_disposition_native_object_profile_unsupported')
        response = inventory['objects'][key]
        require(response['status'] == 200 and json.loads(response['body'])['version'] == version,
            'hosted_disposition_native_object_changed')
        path = 'stub/stub/company-documents/' + key + '/' + version
        files = [f for f in inventory['files'] if f['path'].startswith(
            'stub/stub/company-documents/' + key + '/')]
        require(any(f['path'] == path for f in files), 'hosted_disposition_native_object_changed')
        for item in files:
            if item['path'] != path:
                require(held.get(item['path']) == item, 'hosted_disposition_unattributed_native_object')
                historical.append(item)
        expected.extend(files)
    require(sorted(expected, key=lambda f: f['path']) == sorted(inventory['files'], key=lambda f: f['path']),
        'hosted_disposition_unattributed_native_object')
    raw = target._run('exec', '-i', target.storage, 'node', '-e', _EXPORT,
        data=encoded({'files': expected}))
    exported = json.loads(raw)
    require([{k: f[k] for k in ('path', 'bytes', 'sha256')} for f in exported] == expected,
        'hosted_disposition_native_object_changed')
    by_path = {item['path']: item for item in exported}
    manifest = []; contents = {}; history = []
    require(len(historical) <= 256, 'hosted_disposition_history_inventory_invalid')
    for key, version, content_type in objects:
        item = by_path['stub/stub/company-documents/' + key + '/' + version]
        body = base64.b64decode(item['base64'], validate=True)
        require(len(body) == item['bytes'] <= 8 * 1024**2 and digest(body) == item['sha256'],
            'hosted_disposition_native_object_changed')
        name = 'object-' + digest(body) + '.bin'; contents[name] = body
        manifest.append({'bucket': 'company-documents', 'name': key, 'file': name,
            'bytes': len(body), 'sha256': digest(body), 'contentType': content_type,
            'nativeCurrentVersion': version})
    for item in sorted(historical, key=lambda f: f['path']):
        exported_item = by_path[item['path']]
        body = base64.b64decode(exported_item['base64'], validate=True)
        require(len(body) == item['bytes'] <= 8 * 1024**2 and digest(body) == item['sha256'],
            'hosted_disposition_native_object_changed')
        history.append(exported_item)
    require(target.objects(action='manifest') == inventory['files'],
        'hosted_disposition_native_object_changed')
    return manifest, contents, history


def _capture(target, directory, *, binding_sha256, pg_restore, held):
    capture = directory / 'capture'; capture.mkdir(mode=0o700)
    captured_at = datetime.now(timezone.utc).isoformat()
    with _NativeSnapshot(target) as snapshot:
        require(snapshot.query('select count(*)from pg_largeobject_metadata') == 0,
            'hosted_disposition_large_objects_unsupported')
        tables = snapshot.query("select json_agg(json_build_array(schemaname,tablename)order by schemaname,tablename)"
            "from pg_tables where schemaname not in('pg_catalog','information_schema')"
            "and schemaname not like 'pg_toast%'")
        require(1 <= len(tables) <= 512, 'hosted_capture_table_inventory_invalid')
        schemas = snapshot.query("select json_agg(nspname order by nspname)from pg_namespace "
            "where nspname !~ '^pg_' and nspname<>'information_schema' and nspname<>all(%s)",
            (sorted(MANAGED_SCHEMAS),))
        facts = snapshot.query(FACTS_SQL)
        extensions = snapshot.query("select coalesce(json_agg(json_build_array(e.extname,e.extversion,"
            "pg_get_userbyid(e.extowner),n.nspname)order by e.extname),'[]')from pg_extension e "
            'join pg_namespace n on n.oid=e.extnamespace')
        catalog = snapshot.query(CATALOG_SQL); roles = snapshot.query(ROLES_SQL)
        access = snapshot.query(ACCESS_SQL, (schemas, schemas))
        database_access = snapshot.query(DATABASE_ACCESS_SQL)
        rows = _row_facts(snapshot, tables)
        objects, contents, history = _objects(snapshot, held)
        dump = snapshot.dump()
    class DumpInput:
        def read(self, name):
            require(name == 'database.dump', 'hosted_capture_member_unavailable')
            return dump
    inventory = NativeArchive(DumpInput(), pg_restore=pg_restore, work=directory)
    origin = {'target': target.target, 'systemIdentifier': target.system,
        'nativeBindingSha256': binding_sha256}
    contents.update({'database.dump': dump,
        'roles.sql': b'-- Passwords omitted; structured role facts are authoritative.\n',
        'contents.list': ''.join(entry.line for entry in inventory.entries).encode(),
        'source-profile.json': encoded({'sourceNativeTarget': target.target, 'nativeOrigin': origin,
            'facts': facts, 'extensions': extensions, 'tables': tables,
            'capturedAt': captured_at}),
        'source-tables.private.json': encoded(rows), 'source-catalog.private.json': encoded(catalog),
        'source-roles.private.json': encoded(roles), 'object-manifest.private.json': encoded(objects)})
    contents['native-held-history.private.json'] = encoded(history)
    for name, raw in contents.items(): _write(capture / name, raw)
    header_sha = _write(directory / 'header.json', {'format': FORMAT,
        'sourceNativeTarget': target.target,
        'pins': {name: {'bytes': len(raw), 'sha256': digest(raw)} for name, raw in contents.items()}})
    access_sha = _write(directory / 'access.json', {'sourceNativeTarget': target.target,
        'sourceCatalogStillExactToOriginal': True, 'access': access, 'databaseAccess': database_access})
    return header_sha, access_sha, rows, history


async def capture_native_managed_handoff(*, target, journal, minimum, receipt, native_binding,
        native_binding_sha256, backup, backup_sha256, exports, destination, pg_restore):
    """Compose an already bound native recovery with a finite managed capture.

    Caller first completes NativeDispositionRecovery.bind[_prefix] on this exact
    isolated target. Retrying this composition reconciles existing owner prefixes;
    it never rebinds or executes SQL against a hosted target.
    """
    destination = Path(destination).absolute()
    require(not destination.exists() and destination == destination.resolve() and
        not any(p.is_symlink() for p in destination.parents),
        'hosted_disposition_destination_exists')
    require(destination.parent.is_dir() and destination.parent.stat().st_uid == os.getuid() and
        not destination.parent.stat().st_mode & 0o077, 'hosted_disposition_destination_private_required')
    target.validate()
    binding, _, _ = native_custody(journal=journal, minimum=minimum, native_binding=native_binding,
        native_binding_sha256=native_binding_sha256, backup=backup,
        backup_sha256=backup_sha256, exports=exports)
    require(binding['target'] == target.target and binding['systemIdentifier'] == target.system and
        binding['operatorLogin'] == target.login and binding['journal'] == asdict(minimum) and
        binding['backupSha256'] == backup_sha256, 'hosted_disposition_native_binding_changed')
    external = dict(journal=str(journal.path), minimum=asdict(minimum), receipt=str(receipt),
        native_binding=str(native_binding), native_binding_sha256=native_binding_sha256,
        backup=str(backup), backup_sha256=backup_sha256, exports=list(map(str, exports)))
    for path in (journal.path, Path(receipt), Path(native_binding), Path(backup), *map(Path, exports)):
        require(path.is_absolute() and path == path.resolve() and not path.is_relative_to(destination) and
            not any(p.is_symlink() for p in (path, *path.parents)),
            'hosted_disposition_custody_overlap')
    receipt = Path(receipt)
    require(receipt not in {journal.path, Path(native_binding), *map(Path, exports)} and
        not receipt.is_relative_to(Path(backup)) and receipt.parent.is_dir() and
        receipt.parent.stat().st_uid == os.getuid() and not receipt.parent.stat().st_mode & 0o077,
        'hosted_disposition_custody_overlap')
    if receipt.exists(): private_read(receipt, 4096)
    with tempfile.TemporaryDirectory(prefix='.native-managed-', dir=destination.parent) as scratch:
        staging = Path(scratch)
        class CaptureReceipt(LocalReplayReceipt):
            def publish(self, identity, head):
                super().publish(identity, head)
                require(head == minimum, 'hosted_disposition_current_cut_required')
                native_custody(journal=journal, minimum=minimum, native_binding=native_binding,
                    native_binding_sha256=native_binding_sha256, backup=backup,
                    backup_sha256=backup_sha256, exports=exports)
                held = {}
                from talli_backend.adapters.native_disposition_recovery import NativeDispositionRecovery
                for permit, path in zip(journal.read(minimum=head)[1], exports):
                    archive = NativeDispositionRecovery._export(permit, path)
                    for item in archive['files']:
                        fact = {k: item[k] for k in ('path', 'bytes', 'sha256')}
                        require(item['path'] not in held or held[item['path']] == fact,
                            'hosted_disposition_history_inventory_invalid')
                        held[item['path']] = fact
                header_sha, access_sha, rows, history = _capture(target, staging,
                    binding_sha256=native_binding_sha256, pg_restore=pg_restore, held=held)
                proof = {'version': 1, 'profile': FORMAT, 'nativeTarget': target.target,
                    'nativeSystemIdentifier': target.system, 'operatorLogin': target.login,
                    'journal': asdict(head), 'nativeBindingSha256': native_binding_sha256,
                    'nativeBackupSha256': backup_sha256,
                    'exportSha256': [p.facts.documents_export_sha256 for p in journal.read(minimum=head)[1]],
                    'headerSha256': header_sha, 'accessSha256': access_sha,
                    'nativeTables': {k: v for k, v in rows.items() if k in TABLES},
                    'nativeHistoryFiles': len(history), 'nativeHistoryBytes': sum(f['bytes'] for f in history),
                    'publicationAuthorized': False}
                proof_sha = _write(staging / 'disposition-proof.json', proof)
                custody = ManagedDispositionBinding(proof=staging / 'disposition-proof.json',
                    proof_sha256=proof_sha, customer_root=staging / 'capture', **external)
                from talli_backend.adapters.hosted_recovery_capture import ManagedCapture
                capture = ManagedCapture.open(directory=staging / 'capture', header=staging / 'header.json',
                    header_sha256=header_sha, access=staging / 'access.json', access_sha256=access_sha,
                    disposition=custody)
                compile_program(capture, NativeArchive(capture, pg_restore=pg_restore, work=staging))
                custody.check_current()
                _write(staging / 'handoff.json', {'capture': {'directory': str(destination / 'capture'),
                    'header': str(destination / 'header.json'), 'header_sha256': header_sha,
                    'access': str(destination / 'access.json'), 'access_sha256': access_sha},
                    'disposition': {'proof': str(destination / 'disposition-proof.json'),
                        'proof_sha256': proof_sha, **external}, 'publicationAuthorized': False})
        await replay_company_dispositions(journal=_CurrentCutJournal(journal, minimum), target=target.target,
            receipt=CaptureReceipt(Path(receipt)), minimum=minimum,
            stores={'documents': PostgresDocumentDisposition(target)})
        for path in (staging / 'capture', staging):
            descriptor = os.open(path, os.O_RDONLY)
            try: os.fsync(descriptor)
            finally: os.close(descriptor)
        os.rename(staging, destination)
        parent = os.open(destination.parent, os.O_RDONLY)
        try: os.fsync(parent)
        finally: os.close(parent)
    return json.loads(private_read(destination / 'handoff.json', 32768))
