"""Native archive selection and COPY streaming for managed logical recovery.

Never interpret a shell script or split SQL at semicolons. PostgreSQL parses SQL
batches; only pg_dump's external COPY framing is handled by the client.
"""
from dataclasses import dataclass
from pathlib import Path
import re
import resource
import subprocess
import tempfile

from talli_backend.adapters.hosted_recovery_capture import (
    MANAGED_SCHEMAS, identifier, literal, qi, require,
)


@dataclass(frozen=True)
class Entry:
    line: str
    kind: str
    schema: str
    tag: str
    owner: str


def toc_entries(text):
    result = []
    for line in text.splitlines(keepends=True):
        if not line.strip() or line.startswith(';'):
            continue
        match = re.fullmatch(r'\d+; \d+ \d+ ([A-Z][A-Z ]*) (\S+) (.*)\n?', line)
        require(match is not None, 'hosted_archive_toc_invalid')
        kind, schema, tail = match.groups()
        tag, owner = tail.strip().rsplit(' ', 1)
        result.append(Entry(line, kind, schema, tag, owner))
    require(1 <= len(result) <= 10000, 'hosted_archive_toc_bound')
    return tuple(result)


class NativeArchive:
    def __init__(self, capture, *, pg_restore, work):
        self.capture, self.binary, self.work = capture, str(pg_restore), Path(work)
        require(Path(self.binary).is_absolute(), 'hosted_pg_restore_path_required')
        # --create matters even for inspection: otherwise database ACL entries
        # disappear from the TOC. Never execute CREATE DATABASE on a managed VM.
        self.entries = toc_entries(self._run(['--create', '--list']).decode())

    def _run(self, arguments, *, pass_fds=()):
        def bounded_output():
            resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024**2, 256 * 1024**2))
        # Anonymous files bound memory and disappear on process death. The
        # child file-size limit also prevents a compressed archive filling disk.
        with tempfile.TemporaryFile(dir=self.work) as output, tempfile.TemporaryFile(dir=self.work) as errors:
            run = subprocess.run([self.binary, *arguments], input=self.capture.read('database.dump'),
                stdout=output, stderr=errors, timeout=90, pass_fds=pass_fds, preexec_fn=bounded_output)
            require(run.returncode == 0 and output.tell() <= 256 * 1024**2,
                'hosted_archive_read_failed')
            output.seek(0)
            return output.read()

    def sql(self, entries, *, data=False):
        # An explicit full-TOC selection retains SCHEMA and SCHEMA ACL entries;
        # pg_restore --schema filters do not retain those entries themselves.
        with tempfile.TemporaryFile(dir=self.work) as selection:
            selection.write(''.join(e.line for e in entries).encode()); selection.flush()
            selection.seek(0)
            return self._run(['--data-only' if data else '--schema-only',
                '--use-list', '/dev/fd/' + str(selection.fileno()), '--file=-'],
                pass_fds=(selection.fileno(),))


def sql_without_psql_framing(raw):
    raw = re.sub(rb'(?m)^\\(?:un)?restrict [A-Za-z0-9]+\n', b'', raw)
    require(not re.search(rb'(?m)^\\(?:connect|include|i|!|copy)\b', raw),
        'hosted_archive_client_command_unsupported')
    return raw


def copy_parts(raw):
    """Yield SQL batches and native COPY bodies, including consecutive empties.

    Start the terminator search at the header's final newline: starting after it
    swallows the next table when this COPY has no rows. No SQL-semicolon parser.
    """
    raw = sql_without_psql_framing(raw)
    position = 0
    for match in re.finditer(rb'(?m)^COPY ([^\n]+) FROM stdin;\n', raw):
        if match.start() < position:
            continue
        end = raw.find(b'\n\\.\n', match.end() - 1)
        require(end >= 0, 'hosted_archive_copy_unterminated')
        yield 'sql', raw[position:match.start()]
        identity = re.fullmatch(rb'([^ ]+) \([^\n]+\)', match[1])
        require(identity is not None, 'hosted_archive_copy_invalid')
        table = '.'.join(part.strip('"') for part in identity[1].decode().split('.'))
        require(len(table.split('.')) == 2, 'hosted_archive_copy_invalid')
        for name in table.split('.'): identifier(name)
        yield 'copy', (table, match.group().strip(), raw[match.end():end + 1])
        position = end + 4
    yield 'sql', raw[position:]


def execute_batch(db, raw):
    text = sql_without_psql_framing(raw).decode()
    if text.strip():
        cursor = db.execute(text, prepare=False)
        while cursor.nextset():
            pass


def execute_data(db, raw, expected_rows):
    seen = set()
    for kind, value in copy_parts(raw):
        if kind == 'sql':
            execute_batch(db, value)
            continue
        table, header, body = value
        require(table in expected_rows and table not in seen and
            bool(body) == (expected_rows[table]['rows'] > 0), 'hosted_archive_copy_inventory_changed')
        seen.add(table)
        # Supabase restricts direct COPY into empty managed vector tables.
        # Retain their existing empty definitions; never bypass provider guards.
        if body:
            with db.cursor().copy(header.decode()) as copy:
                copy.write(body)
    return seen


def sequence_payload(raw):
    result = []
    for name, counter, called in re.findall(
            rb"(?m)^SELECT pg_catalog.setval\('((?:[^']|'')+)', (-?\d+), (true|false)\);$", raw):
        identity = name.decode().replace("''", "'").split('.')
        require(len(identity) == 2, 'hosted_archive_sequence_invalid')
        for part in identity: identifier(part)
        result.append((identity, int(counter), called == b'true'))
    require(len(result) <= 512 and len({tuple(r[0]) for r in result}) == len(result),
        'hosted_archive_sequence_invalid')
    return tuple(result)


def role_program(capture):
    custom = {r[0] for r in capture.custom_roles}
    statements = []
    final = []
    for role in capture.custom_roles:
        name, _, inherit, _, _, _, _, _, limit, until, settings = role
        require(type(limit) is int and -1 <= limit <= 1000, 'hosted_capture_role_invalid')
        # Runtime logins stay disabled throughout the managed restore. Password
        # provisioning and human publication are deliberately separate authority.
        statements.append('create role ' + qi(name) + ' nologin nosuperuser nocreaterole '
            'nocreatedb noreplication nobypassrls ' + ('inherit' if inherit else 'noinherit') +
            ' connection limit ' + str(limit) + (' valid until ' + literal(until) if until else '') + ';')
        statements.append('grant ' + qi(name) + ' to postgres with inherit true, set true;')
        for setting in settings or []:
            key, value = setting.split('=', 1)
            require(re.fullmatch('[a-z_][a-z_0-9.]*', key), 'hosted_capture_role_setting_invalid')
            statements.append('alter role ' + qi(name) + ' set "' + key + '" to ' + literal(value) + ';')
    for parent, member, grantor, admin, inherit, can_set in capture.roles['memberships']:
        if parent not in custom and member not in custom:
            continue
        identifier(parent); identifier(member); identifier(grantor)
        require(member in custom or member == 'postgres', 'hosted_capture_membership_unsupported')
        require(all(type(v) is bool for v in (admin, inherit, can_set)),
            'hosted_capture_membership_invalid')
        if member == 'postgres' and grantor == 'supabase_admin':
            require(parent in custom and admin and not inherit and not can_set,
                'hosted_capture_membership_grantor_unsupported')
            # PostgreSQL grants the creator ADMIN via the bootstrap superuser.
            # Keep that provider grant separate from postgres's own grant row.
            continue
        require(grantor == 'postgres' and (member != 'postgres' or parent in custom and not admin),
            'hosted_capture_membership_grantor_unsupported')
        if member == 'postgres':
            # The provider already granted ADMIN from the bootstrap role. Asking
            # for ADMIN back to one's own grantor creates a forbidden cycle.
            final.append('grant ' + qi(parent) + ' to postgres with inherit ' +
                str(inherit).lower() + ', set ' + str(can_set).lower() + ';')
        else:
            statements.append('grant ' + qi(parent) + ' to ' + qi(member) + ' with admin ' +
                str(admin).lower() + ', inherit ' + str(inherit).lower() + ', set ' +
                str(can_set).lower() + ';')
    explicit_roots = {r[0] for r in capture.roles['memberships'] if
        r[1] == r[2] == 'postgres'}
    final.extend('revoke ' + qi(name) + ' from postgres granted by postgres;'
        for name in sorted(custom - explicit_roots))
    return ''.join(statements).encode(), ''.join(final).encode()


@dataclass(frozen=True)
class LogicalProgram:
    roles: bytes
    schemas: bytes
    temporary_create: bytes
    definitions: bytes
    data: bytes
    policies: bytes
    acl: bytes
    remove_temporary_create: bytes
    final_memberships: bytes
    extension_usage: bytes
    sequences: tuple


def compile_program(capture, archive):
    entries = archive.entries
    require(not any(e.kind in ('PROCEDURE', 'MATERIALIZED VIEW DATA') and
        e.schema in capture.schemas for e in entries), 'hosted_archive_object_kind_unsupported')
    require(not any(e.kind == 'TRIGGER' and e.schema in ('auth', 'storage') and
        not e.owner.startswith('supabase_') for e in entries),
        'hosted_managed_custom_trigger_unsupported')
    require(not any(row[0] in capture.schemas and
        re.search(r'REFERENCES\s+"?storage"?\."?objects"?\b', row[3], re.I)
        for row in capture.catalog['constraints']),
        'hosted_storage_transport_identity_dependency_unsupported')
    def application(entry):
        return entry.schema in capture.schemas or entry.kind in ('SCHEMA', 'ACL', 'COMMENT') and \
            entry.schema == '-' and (entry.tag.split()[0] if entry.kind == 'SCHEMA' else
                entry.tag.split()[1] if entry.tag.startswith('SCHEMA ') else None) in capture.schemas
    app = [e for e in entries if application(e)]
    creates = [e for e in app if e.kind == 'SCHEMA']
    require({e.tag for e in creates} | {'public'} == set(capture.schemas),
        'hosted_capture_schema_inventory_changed')
    definitions = [e for e in app if e.kind not in ('SCHEMA', 'ACL', 'DEFAULT ACL', 'TABLE DATA', 'SEQUENCE SET')]
    acls = [e for e in app if e.kind in ('ACL', 'DEFAULT ACL') and e.owner != 'supabase_admin']
    acls.sort(key=lambda e: e.schema == '-' and e.tag.startswith('SCHEMA '))
    owners = {(e.schema, e.owner) for e in definitions if e.kind in
        ('FUNCTION', 'TABLE', 'VIEW', 'MATERIALIZED VIEW', 'SEQUENCE', 'TYPE') and e.owner != 'postgres'}
    custom = {r[0] for r in capture.custom_roles}
    require(all(schema in capture.schemas and owner in custom for schema, owner in owners),
        'hosted_capture_owner_unsupported')
    temporary = ''.join('grant create on schema ' + qi(schema) + ' to ' + qi(owner) + ';'
        for schema, owner in sorted(owners)).encode()
    remove = ''.join('revoke create on schema ' + qi(schema) + ' from ' + qi(owner) + ';'
        for schema, owner in sorted(owners)).encode()
    # Leave managed definitions and migration rows to the provider. Restore the
    # source-owned custom policies separately after application definitions.
    policies = [e for e in entries if e.kind == 'POLICY' and e.schema in ('auth', 'storage')]
    data = [e for e in entries if e.kind == 'TABLE DATA' and
        (e.schema in capture.schemas or e.schema in ('auth', 'storage') and
         e.tag not in ('schema_migrations', 'migrations', 'buckets', 'objects'))]
    require({e.schema + '.' + e.tag for e in data} == {name for name in capture.rows
        if name.split('.')[0] in capture.schemas or name.split('.')[0] in ('auth', 'storage') and
        name.split('.')[1] not in ('schema_migrations', 'migrations', 'buckets', 'objects')},
        'hosted_capture_data_inventory_changed')
    all_data = archive.sql([e for e in entries if e.kind == 'SEQUENCE SET'], data=True)
    sequences = sequence_payload(all_data)
    require(len(sequences) == sum(e.kind == 'SEQUENCE SET' for e in entries),
        'hosted_capture_sequence_inventory_changed')
    managed_acls = archive.sql([e for e in entries if e.kind == 'ACL' and
        (e.schema in MANAGED_SCHEMAS or e.schema == '-' and e.tag.startswith('SCHEMA ') and
         e.tag.split()[1] in MANAGED_SCHEMAS)])
    grants = []
    for line in managed_acls.decode().splitlines():
        match = re.fullmatch(r'GRANT [^\n]+ TO ([a-z_][a-z_0-9]*)( WITH GRANT OPTION)?;', line)
        if match and match[1] in custom:
            grants.append(line)
    roles, final = role_program(capture)
    return LogicalProgram(roles, archive.sql(creates), temporary, archive.sql(definitions),
        archive.sql(data, data=True), archive.sql(policies), archive.sql(acls), remove, final,
        '\n'.join(grants).encode(), sequences)

GUC = "set search_path=''; set timezone='UTC'; set datestyle='ISO,YMD'; set intervalstyle='postgres'; set bytea_output='hex'; set extra_float_digits=3; "

CATALOG_SQL = "select jsonb_build_object('functions',(\nselect coalesce(jsonb_agg(jsonb_build_array(n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),pg_get_functiondef(p.oid),pg_get_userbyid(p.proowner),\n(select coalesce(jsonb_agg(jsonb_build_array(pg_get_userbyid(a.grantor),case when a.grantee=0 then 'PUBLIC' else pg_get_userbyid(a.grantee) end,a.privilege_type,a.is_grantable) order by a.grantor::regrole::text,a.grantee::regrole::text,a.privilege_type),'[]') from aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a)) order by n.nspname,p.proname,pg_get_function_identity_arguments(p.oid)),'[]')\nfrom pg_proc p join pg_namespace n on n.oid=p.pronamespace where p.prokind in ('f','p') and n.nspname not in ('pg_catalog','information_schema') and n.nspname not like 'pg_toast%'),\n'constraints',(select coalesce(jsonb_agg(jsonb_build_array(n.nspname,c.relname,k.conname,pg_get_constraintdef(k.oid,true)) order by n.nspname,c.relname,k.conname),'[]') from pg_constraint k join pg_class c on c.oid=k.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname not in ('pg_catalog','information_schema') and n.nspname not like 'pg_toast%'),\n'indexes',(select coalesce(jsonb_agg(jsonb_build_array(schemaname,tablename,indexname,indexdef) order by schemaname,tablename,indexname),'[]') from pg_indexes where schemaname not in ('pg_catalog','information_schema') and schemaname not like 'pg_toast%'),\n'policies',(select coalesce(jsonb_agg(jsonb_build_array(schemaname,tablename,policyname,permissive,roles,cmd,qual,with_check) order by schemaname,tablename,policyname),'[]') from pg_policies),\n'rls',(select coalesce(jsonb_agg(jsonb_build_array(n.nspname,c.relname,c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner)) order by n.nspname,c.relname),'[]') from pg_class c join pg_namespace n on n.oid=c.relnamespace where c.relkind in ('r','p') and n.nspname not in ('pg_catalog','information_schema') and n.nspname not like 'pg_toast%'))"

