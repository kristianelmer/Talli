"""Verified, bounded managed capture inputs. No credentials or hosted calls.

This is the managed logical profile used by the hosted rehearsal, not an
alternative interpretation of LocalBackupGenerations' native disposition bundle.
Both expected digests must come from independently held owner evidence.
"""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat

MAX_BUNDLE = 256 * 1024**2
MAX_FILE = 64 * 1024**2
MANAGED_SCHEMAS = frozenset({'auth', 'storage', 'extensions', 'graphql',
    'graphql_public', 'realtime', 'vault', 'pgbouncer'})
PLATFORM_ROLES = frozenset({'postgres', 'anon', 'authenticated', 'authenticator',
    'service_role', 'dashboard_user', 'pgbouncer', 'cli_login_postgres'})
REQUIRED = frozenset({'database.dump', 'roles.sql', 'contents.list',
    'source-profile.json', 'source-tables.private.json',
    'source-catalog.private.json', 'source-roles.private.json',
    'object-manifest.private.json'})


def require(condition, code):
    if not condition:
        raise ValueError(code)


def digest(raw):
    return sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', value),
        'hosted_capture_identifier_invalid')
    return value


def qi(value):
    return '"' + identifier(value) + '"'


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def private_read(path, limit=MAX_FILE):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'hosted_private_path_invalid')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as source:
        info = os.fstat(source.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
            info.st_uid == os.getuid() and not info.st_mode & 0o077 and info.st_size <= limit,
            'hosted_private_file_invalid')
        raw = source.read(limit + 1)
    require(len(raw) <= limit, 'hosted_capture_bound')
    return raw


def _pairs(values):
    result = {}
    for key, value in values:
        require(key not in result, 'hosted_capture_duplicate_key')
        result[key] = value
    return result


def json_bytes(raw):
    return json.loads(raw, object_pairs_hook=_pairs,
        parse_constant=lambda _: require(False, 'hosted_capture_json_invalid'))


def normalized_catalog(catalog, schemas):
    result = {}
    for key, values in catalog.items():
        selected = json.loads(json.dumps([row for row in values if row[0] in schemas]))
        if key == 'functions':
            for row in selected:
                row[5].sort(key=encoded)
        if key == 'policies':
            for row in selected:
                row[4].sort()
        result[key] = sorted(selected, key=encoded)
    return result


def normalized_access(access):
    result = json.loads(json.dumps(access))
    for rows in result.values():
        for row in rows:
            row[-1].sort(key=encoded)
        rows.sort(key=encoded)
    return result


@dataclass(frozen=True)
class ManagedCapture:
    directory: Path
    commitment: str
    source_project: str
    files: dict
    profile: dict
    rows: dict
    catalog: dict
    roles: dict
    objects: tuple
    access: dict
    database_access: dict | None

    @classmethod
    def open(cls, *, directory, header, header_sha256, access, access_sha256):
        directory = Path(directory).absolute()
        require(directory.is_dir() and not directory.is_symlink() and
            directory.stat().st_uid == os.getuid() and not directory.stat().st_mode & 0o077,
            'hosted_capture_directory_invalid')
        raw = private_read(header, 65536)
        require(digest(raw) == header_sha256, 'hosted_capture_header_changed')
        envelope = json_bytes(raw)
        require(envelope.get('format') == 'talli-designated-hosted-capture-v1' and
            re.fullmatch('[a-z]{20}', envelope.get('projectRef', '')),
            'hosted_capture_format_invalid')
        pins = envelope['pins']
        require(8 <= len(pins) <= 40 and REQUIRED <= set(pins) and
            set(pins) == {p.name for p in directory.iterdir()}, 'hosted_capture_inventory_changed')
        contents = {}
        for name, pin in pins.items():
            require(re.fullmatch('[a-zA-Z0-9_.-]{1,100}', name) and name not in ('.', '..') and
                set(pin) == {'bytes', 'sha256'} and type(pin['bytes']) is int and
                0 <= pin['bytes'] <= MAX_FILE, 'hosted_capture_pin_invalid')
            body = private_read(directory / name)
            require(len(body) == pin['bytes'] and digest(body) == pin['sha256'],
                'hosted_capture_member_changed')
            contents[name] = body
        require(sum(len(v) for v in contents.values()) <= MAX_BUNDLE and
            contents['database.dump'].startswith(b'PGDMP') and
            not re.search(rb'\bPASSWORD\b', contents['roles.sql'], re.I), 'hosted_capture_profile_invalid')
        profile = json_bytes(contents['source-profile.json'])
        rows = json_bytes(contents['source-tables.private.json'])
        catalog = json_bytes(contents['source-catalog.private.json'])
        roles = json_bytes(contents['source-roles.private.json'])
        objects = json_bytes(contents['object-manifest.private.json'])
        require(profile['projectRef'] == envelope['projectRef'] and
            len(profile['facts']) == 7 and profile['facts'][0] // 10000 == 17 and
            profile['facts'][6] == 'postgres',
            'hosted_capture_database_profile_invalid')
        captured = datetime.fromisoformat(profile['capturedAt'].replace('Z', '+00:00'))
        require(captured.tzinfo is not None and isinstance(profile.get('extensions'), list),
            'hosted_capture_database_profile_invalid')
        tables = profile['tables']
        require(1 <= len(tables) <= 512 and len({tuple(t) for t in tables}) == len(tables) and
            set(rows) == {'.'.join(t) for t in tables}, 'hosted_capture_table_inventory_invalid')
        for schema, table in tables:
            identifier(schema); identifier(table)
            fact = rows[schema + '.' + table]
            require(set(fact) == {'rows', 'sha256'} and type(fact['rows']) is int and
                fact['rows'] >= 0 and re.fullmatch('[a-f0-9]{64}', fact['sha256']),
                'hosted_capture_table_fact_invalid')
        require(set(catalog) == {'functions', 'constraints', 'indexes', 'policies', 'rls'} and
            all(isinstance(v, list) and len(v) <= 4096 for v in catalog.values()) and
            1 <= len(roles['roles']) <= 512 and len(roles['memberships']) <= 4096,
            'hosted_capture_catalog_bound')
        role_names = set()
        for role in roles['roles']:
            require(len(role) == 11, 'hosted_capture_role_invalid')
            identifier(role[0]); require(role[0] not in role_names, 'hosted_capture_role_invalid')
            role_names.add(role[0])
            require(all(type(v) is bool for v in role[1:8]), 'hosted_capture_role_invalid')
        custom = {r[0] for r in roles['roles'] if r[0] not in PLATFORM_ROLES and
            not r[0].startswith(('pg_', 'supabase_'))}
        require(all(not any((r[1], r[3], r[4], r[6], r[7])) for r in roles['roles'] if r[0] in custom),
            'hosted_privileged_custom_role_unsupported')
        require(len(objects) <= 32 and len({(o['bucket'], o['name']) for o in objects}) == len(objects),
            'hosted_capture_object_inventory_invalid')
        for obj in objects:
            require(re.fullmatch('[a-z0-9][a-z0-9_-]{0,62}', obj['bucket']) and
                isinstance(obj['name'], str) and 0 < len(obj['name']) <= 1024 and
                all(part not in ('', '.', '..') for part in obj['name'].split('/')) and
                '\\' not in obj['name'] and not any(ord(c) < 32 for c in obj['name']) and
                obj['file'] == 'object-' + obj['sha256'] + '.bin' and
                0 <= obj['bytes'] <= 8 * 1024**2 and obj['file'] in contents,
                'hosted_capture_object_invalid')
            require(obj.get('contentType') is None or isinstance(obj['contentType'], str) and
                len(obj['contentType']) <= 256 and '\r' not in obj['contentType'] and
                '\n' not in obj['contentType'], 'hosted_capture_object_invalid')
            require(len(contents[obj['file']]) == obj['bytes'] and
                digest(contents[obj['file']]) == obj['sha256'], 'hosted_capture_object_changed')
        require(rows.get('vault.secrets', {'rows': 0})['rows'] == 0 and
            rows.get('pgsodium.key', {'rows': 0})['rows'] == 0,
            'hosted_managed_key_transfer_required')
        require(not any(rows.get(name, {'rows': 0})['rows'] for name in
            ('cron.job', 'net.http_request_queue', 'supabase_functions.hooks')),
            'hosted_background_provider_work_unsupported')
        require(not any(v['rows'] for k, v in rows.items() if k.startswith('documents.local_native_disposition_')),
            'hosted_disposition_replay_adapter_required')
        require(rows.get('auth.users', {'rows': 0})['rows'] <= 256,
            'hosted_recovery_actor_bound')
        extra = private_read(access, 16 * 1024**2)
        require(digest(extra) == access_sha256, 'hosted_capture_access_changed')
        supplement = json_bytes(extra)
        require(supplement.get('sourceProject') == envelope['projectRef'] and
            supplement.get('sourceCatalogStillExactToOriginal') is True,
            'hosted_capture_access_binding_invalid')
        values = supplement['access']
        require(set(values) == {'schemas', 'relations'} and len(values['schemas']) <= 64 and
            len(values['relations']) <= 1024, 'hosted_capture_access_invalid')
        for kind, entries in values.items():
            identities = []
            for row in entries:
                require(len(row) == (3 if kind == 'schemas' else 5), 'hosted_capture_access_invalid')
                for name in row[:1 if kind == 'schemas' else 2]: identifier(name)
                require(row[-2] in role_names, 'hosted_capture_access_role_invalid')
                identities.append(tuple(row[:1 if kind == 'schemas' else 2]))
                for grantor, grantee, privilege, option in row[-1]:
                    require(grantor == row[-2] and grantee in role_names | {'PUBLIC'} and
                        privilege in {'USAGE', 'CREATE', 'SELECT', 'INSERT', 'UPDATE', 'DELETE',
                            'TRUNCATE', 'REFERENCES', 'TRIGGER', 'MAINTAIN'} and type(option) is bool,
                        'hosted_capture_access_grant_invalid')
            require(len(identities) == len(set(identities)), 'hosted_capture_access_duplicate')
        database_access = supplement.get('databaseAccess')
        if database_access is not None:
            require(database_access.get('database') == 'postgres' and
                database_access.get('owner') == 'postgres' and
                isinstance(database_access.get('grants'), list), 'hosted_capture_database_access_invalid')
            for grantor, grantee, privilege, option in database_access['grants']:
                require(grantor == 'postgres' and grantee in role_names | {None, 'PUBLIC'} and
                    privilege in {'CONNECT', 'CREATE', 'TEMPORARY'} and type(option) is bool,
                    'hosted_capture_database_access_invalid')
        commitment = digest(encoded({'headerSha256': header_sha256, 'accessSha256': access_sha256}))
        return cls(directory, commitment, envelope['projectRef'], pins, profile, rows,
            catalog, roles, tuple(objects), values, database_access)

    def read(self, name):
        require(name in self.files, 'hosted_capture_member_unavailable')
        raw = private_read(self.directory / name)
        require(len(raw) == self.files[name]['bytes'] and digest(raw) == self.files[name]['sha256'],
            'hosted_capture_member_changed')
        return raw

    @property
    def schemas(self):
        return frozenset(row[0] for row in self.access['schemas'])

    @property
    def custom_roles(self):
        return tuple(r for r in self.roles['roles'] if r[0] not in PLATFORM_ROLES and
            not r[0].startswith(('pg_', 'supabase_')))
