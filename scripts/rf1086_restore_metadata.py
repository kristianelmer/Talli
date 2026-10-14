"""Private, pure backup metadata and closed restore supplementation.

No query execution, target-derived repair, or alternative catalog comparator.
The caller owns source consistency, complete emitter attribution and final strict
fingerprints. Source OIDs identify archive entries; they are never target OIDs.
"""
from dataclasses import dataclass, replace
from functools import wraps
import hashlib
import json
import math
import re
import time

from psycopg.adapt import PyFormat, Transformer
from psycopg.pq import Format

import rf1086_catalog_causal_capture as capture
import rf1086_catalog_difference as difference
import rf1086_causal_protocol as causal
import rf1086_sql_identifiers as identifiers
import rf1086_sql_lexical as lexical
import rf1086_sql_ledger as ledger
from rf1086_sql_ledger import Statement

MAX_METADATA = 8 * 1024**2
MAX_ROLES_BYTES = 1024**2
MAX_ROLES = 256
MAX_OBJECTS = 8192
MAX_ITEMS = 64
MAX_TOTAL_ITEMS = 32768
MAX_ROW = 64 * 1024
MAX_SQL = 1024**2
MAX_STATEMENTS = 4096
MAX_ROLE_STATEMENTS = 8192
MAX_EDGES = 4096
MAX_SCRIPT = 128 * 1024**2
SCHEMA = 'rf1086-restore-metadata-v1'
REASONS = frozenset(('source_binding', 'metadata_profile', 'role_profile', 'role_order',
    'archive_profile', 'suffix_profile', 'creation_profile', 'prefix_binding',
    'postcondition', 'deadline', 'limit', 'internal'))
# PG17 acl.h order, including MAINTAIN. Array position remains significant.
RIGHTS = tuple(zip('arwdDxtXUCTcsAm', ('INSERT', 'SELECT', 'UPDATE', 'DELETE',
    'TRUNCATE', 'REFERENCES', 'TRIGGER', 'EXECUTE', 'USAGE', 'CREATE',
    'TEMPORARY', 'CONNECT', 'SET', 'ALTER SYSTEM', 'MAINTAIN'), strict=True))
DOMAINS = {'r': ('INSERT', 'SELECT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES',
                 'TRIGGER', 'MAINTAIN'), 'S': ('SELECT', 'UPDATE', 'USAGE'),
           'f': ('EXECUTE',), 'T': ('USAGE',), 'n': ('USAGE', 'CREATE')}
ROLE_FLAGS = ('rolsuper', 'rolinherit', 'rolcreaterole', 'rolcreatedb', 'rolcanlogin',
              'rolreplication', 'rolbypassrls')
ROLE_WORDS = ('SUPERUSER', 'INHERIT', 'CREATEROLE', 'CREATEDB', 'LOGIN',
              'REPLICATION', 'BYPASSRLS')


class MetadataUnavailable(ValueError):
    def __init__(self, reason):
        self.reason = reason if reason in REASONS else 'internal'
        super().__init__('restore_metadata_unavailable')


def require(ok, reason='metadata_profile'):
    if not ok:
        raise MetadataUnavailable(reason)


def closed(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except MetadataUnavailable:
            raise
        except (ValueError, TypeError, KeyError, IndexError, UnicodeError, OverflowError, RecursionError) as error:
            if (type(error) in (ledger.Unavailable, lexical.Unavailable)
                    and type(error.reason) is str and error.reason in ('deadline', 'limit')):
                raise
            raise MetadataUnavailable('metadata_profile') from None
    return call


class Budget:
    def __init__(self, deadline):
        require(type(deadline) in (int, float) and math.isfinite(deadline), 'deadline')
        self.deadline = deadline
        self.check()

    def check(self):
        require(time.monotonic() < self.deadline, 'deadline')

    def short(self):
        self.check()
        return min(self.deadline, time.monotonic() + 4.9)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf8')


def binding(raw, budget):
    h = hashlib.sha256()
    for start in range(0, len(raw), 65536):
        budget.check()
        h.update(memoryview(raw)[start:start + 65536])
    budget.check()
    return {'bytes': len(raw), 'sha256': h.hexdigest()}


def keys(value, names):
    require(type(value) is dict and set(value) == set(names))


def integer(value, lower, upper):
    require(type(value) is int and lower <= value <= upper)
    return value


def name(value):
    require(type(value) is str and 0 < len(value.encode('utf8')) <= 63
            and not any(c in value for c in '\x00\r\n'))
    return value


def _reject(_):
    raise MetadataUnavailable('metadata_profile')


def _json(raw, cap, budget):
    require(type(raw) is bytes and len(raw) <= cap, 'limit')
    # Bound strings/nesting before json's container allocation, not only afterward.
    depth = string = escaped = size = 0
    for i, byte in enumerate(raw):
        if i % 4096 == 0:
            budget.check()
        if string:
            size += 1
            require(size <= MAX_ROW, 'limit')
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                string = False
        elif byte == 34:
            string, size = True, 0
        elif byte in (91, 123):
            depth += 1
            require(depth <= 16, 'limit')
        elif byte in (93, 125):
            depth -= 1
            require(depth >= 0)
    def object_(pairs):
        budget.check()
        require(len(pairs) <= 64, 'limit')
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        # The outer metadata object is bounded separately; individual rows are not.
        if 'schema' not in result or result['schema'] != SCHEMA:
            require(len(canonical(result)) <= MAX_ROW, 'limit')
        return result
    value = json.loads(raw, object_pairs_hook=object_, parse_constant=_reject)
    budget.check()
    return value


def _list(value, cap):
    require(type(value) is list and len(value) <= cap, 'limit')
    return value


def _ident(value, budget):
    return identifiers.identifier(name(value).encode('utf8'), deadline=budget.short())


def _acl_name(value):
    if re.fullmatch(r'[A-Za-z0-9_]+', value):
        return value
    return '"' + value.replace('"', '""') + '"'


@dataclass(frozen=True, repr=False)
class ACLItem:
    grantee: str | None
    grantor: str
    privileges: frozenset
    options: frozenset


@dataclass(frozen=True, repr=False)
class ACL:
    raw: str
    items: tuple


def _acl_raw(items):
    values = []
    for item in items:
        rights = ''.join(letter + ('*' if right in item.options else '')
                         for letter, right in RIGHTS if right in item.privileges)
        values.append(('' if item.grantee is None else _acl_name(item.grantee)) +
                      '=' + rights + '/' + _acl_name(item.grantor))
    # PostgreSQL text[] and aclitem[] share their array quoting rules.
    return bytes(Transformer().get_dumper(values, PyFormat.TEXT).dump(values)).decode('utf8')


def _acl(value, kind, roles, budget, total):
    if value is None:
        return None
    keys(value, ('raw', 'items'))
    require(type(value['raw']) is str and len(value['raw'].encode('utf8')) <= MAX_ROW, 'limit')
    items = []
    for row in _list(value['items'], MAX_ITEMS):
        budget.check()
        total[0] += 1
        require(total[0] <= MAX_TOTAL_ITEMS, 'limit')
        keys(row, ('grantee', 'grantor', 'privileges', 'grantOptions'))
        grantee = row['grantee']
        require(grantee is None or name(grantee) in roles)
        require(name(row['grantor']) in roles)
        rights = _list(row['privileges'], len(RIGHTS))
        options = _list(row['grantOptions'], len(RIGHTS))
        require(all(type(x) is str for x in rights + options))
        require(len(set(rights)) == len(rights) and len(set(options)) == len(options))
        require(set(options) <= set(rights) <= set(DOMAINS[kind]))
        items.append(ACLItem(grantee, row['grantor'], frozenset(rights), frozenset(options)))
    require(_acl_raw(items) == value['raw'])
    # Reject odd dimensions, NULL elements and aliases even when an array loader accepts them.
    loaded = Transformer().get_loader(1009, Format.TEXT).load(value['raw'].encode())
    require(type(loaded) is list and all(type(x) is str for x in loaded))
    return ACL(value['raw'], tuple(items))


def _default(kind, owner):
    items = []
    if kind in ('f', 'T'):
        items.append(ACLItem(None, owner, frozenset(DOMAINS[kind]), frozenset()))
    items.append(ACLItem(owner, owner, frozenset(DOMAINS[kind]), frozenset()))
    return ACL(_acl_raw(items), tuple(items))


@dataclass(frozen=True, repr=False)
class Role:
    name: str
    oid: int
    superuser: bool
    login: bool


@dataclass(frozen=True, repr=False)
class Object:
    class_oid: int
    object_oid: int
    identity: tuple
    kind: str
    owner: str
    acl: ACL | None
    default: ACL
    initial: ACL | None
    initial_type: str | None
    extension: tuple
    columns: int
    argument_types: tuple
    argument_modes: tuple | None

    @property
    def acl_kind(self):
        return 'f' if self.identity[0] == 'function' else ('S' if self.kind == 'S' else 'r')


@dataclass(frozen=True, repr=False)
class DefaultACL:
    owner: str
    schema: str | None
    kind: str
    acl: ACL

    @property
    def key(self):
        return self.owner, self.schema, self.kind


@dataclass(frozen=True, repr=False)
class Metadata:
    roles: tuple
    objects: tuple
    default_acls: tuple
    system_identifier: str
    _selected: bytes
    _wire: bytes
    _binding: bytes
    _role_rows: bytes = b''
    _catalog: bytes = b''
    _roles_binding: bytes = b''
    _source_snapshot: bytes = b''

    @property
    def bootstrap(self):
        return next(r.name for r in self.roles if r.oid == 10)

    @property
    def selected_catalog(self):
        return json.loads(self._source_snapshot or self._selected)

    @property
    def snapshot_binding(self):
        require(bool(self._source_snapshot), 'source_binding')
        return {'bytes': len(self._source_snapshot),
                'sha256': hashlib.sha256(self._source_snapshot).hexdigest()}

    @property
    def binding(self):
        return json.loads(self._binding)


def _roles(rows, budget):
    found = []
    names, oids = set(), set()
    for row in _list(rows, MAX_ROLES):
        budget.check()
        keys(row, ('name', 'oid', 'superuser', 'login'))
        n = name(row['name']); oid = integer(row['oid'], 1, 2**32 - 1)
        require(type(row['superuser']) is bool and type(row['login']) is bool)
        require(n not in names and oid not in oids and (not found or found[-1].oid < oid))
        names.add(n); oids.add(oid)
        found.append(Role(n, oid, row['superuser'], row['login']))
    require(10 in oids and any(r.oid == 10 and r.superuser for r in found), 'role_profile')
    require(any(r.name == 'supabase_admin' and r.superuser and r.login for r in found), 'role_profile')
    return tuple(found)


@closed
def decode_observation(raw, *, deadline):
    budget = Budget(deadline)
    wire = _json(raw, MAX_METADATA, budget)
    keys(wire, ('schema', 'serverVersion', 'database', 'systemIdentifier', 'roles', 'objects',
                'defaultAcls', 'selectedSchemas', 'selectedFunctions'))
    require(wire['schema'] == SCHEMA and type(wire['serverVersion']) is int
            and wire['serverVersion'] == 170006 and wire['database'] == 'postgres')
    system = wire['systemIdentifier']
    require(type(system) is str and re.fullmatch(r'[1-9][0-9]{0,19}', system) is not None
            and int(system) < 2**64)
    roles = _roles(wire['roles'], budget)
    role_names = {r.name for r in roles}
    objects, total, ids, pairs = [], [0], set(), set()
    for row in _list(wire['objects'], MAX_OBJECTS):
        budget.check()
        keys(row, ('classOid', 'objectOid', 'identity', 'kind', 'owner', 'acl', 'defaultAcl',
            'initialAcl', 'initialPrivilegeType', 'extension', 'columnAclCount',
            'argumentTypes', 'argumentModes'))
        require(len(canonical(row)) <= MAX_ROW, 'limit')
        ident = _list(row['identity'], 4)
        require(len(ident) in (3, 4) and ident[0] in ('relation', 'function'))
        require(len(ident) == (3 if ident[0] == 'relation' else 4))
        name(ident[1]); name(ident[2])
        if len(ident) == 4:
            require(type(ident[3]) is str and len(ident[3].encode()) <= MAX_ROW)
        ident = tuple(ident)
        oid = integer(row['objectOid'], 1, 2**32 - 1)
        class_oid = row['classOid']
        require(type(class_oid) is int and class_oid == (1259 if ident[0] == 'relation' else 1255))
        require(ident not in ids and (class_oid, oid) not in pairs)
        ids.add(ident); pairs.add((class_oid, oid))
        kind = row['kind']
        require(type(kind) is str and kind in (('r', 'p', 'v', 'm', 'f', 'S', 'i', 'I', 't', 'c')
                if ident[0] == 'relation' else ('f', 'p', 'a', 'w')))
        owner = name(row['owner']); require(owner in role_names)
        domain = 'f' if ident[0] == 'function' else ('S' if kind == 'S' else 'r')
        current, default, initial = [_acl(row[x], domain, role_names, budget, total)
                                    for x in ('acl', 'defaultAcl', 'initialAcl')]
        require(default == _default(domain, owner))
        require(row['initialPrivilegeType'] in (None, 'i', 'e'))
        require((initial is None) == (row['initialPrivilegeType'] is None))
        extensions = _list(row['extension'], 1)
        for ext in extensions:
            require(type(ext) is list and len(ext) == 3)
            name(ext[0]); name(ext[2]); require(ext[2] in role_names)
            require(type(ext[1]) is str and re.fullmatch(r'[A-Za-z0-9_.-]{1,63}', ext[1]))
        columns = integer(row['columnAclCount'], 0, 32767)
        argtypes = _list(row['argumentTypes'], 100)
        for typ in argtypes:
            require(type(typ) is list and len(typ) == 2)
            name(typ[0]); name(typ[1])
        modes = row['argumentModes']
        if modes is not None:
            require(type(modes) is list and len(modes) <= 100
                    and all(x in ('i', 'o', 'b', 'v', 't') for x in modes))
        require(ident[0] == 'function' or not argtypes and modes is None)
        objects.append(Object(class_oid, oid, ident, kind, owner, current, default, initial,
            row['initialPrivilegeType'], tuple(tuple(x) for x in extensions), columns,
            tuple(tuple(x) for x in argtypes), None if modes is None else tuple(modes)))
    defaults, seen = [], set()
    for row in _list(wire['defaultAcls'], MAX_OBJECTS):
        budget.check(); keys(row, ('owner', 'schema', 'kind', 'acl'))
        owner = name(row['owner']); require(owner in role_names)
        schema = None if row['schema'] is None else name(row['schema'])
        require(type(row['kind']) is str and row['kind'] in DOMAINS)
        acl = _acl(row['acl'], row['kind'], role_names, budget, total); require(acl is not None)
        item = DefaultACL(owner, schema, row['kind'], acl)
        require(item.key not in seen); seen.add(item.key); defaults.append(item)
    selected = {'serverVersion': 170006, 'schemas': wire['selectedSchemas'],
        'functions': wire['selectedFunctions'], 'hooks': [], 'events': [], 'extensions': []}
    capture._validate_snapshot(selected, None)
    by_identity = {o.identity: o for o in objects}
    for function in selected['functions']:
        budget.check()
        obj = by_identity.get(tuple(function['identity']))
        require(obj is not None and obj.owner == function['row'][4]
                and (obj.acl.raw if obj.acl is not None else None) == function['row'][5]
                and obj.argument_types == tuple(tuple(x) for x in function['types'])
                and obj.extension == tuple(tuple(x) for x in function['extensions']))
    # Internal arrays are immutable; detached projections never expose internal references.
    result = Metadata(roles, tuple(objects), tuple(defaults), system, canonical(selected), raw,
                      canonical(binding(raw, budget)))
    budget.check()
    return result


def _catalog_records(raw, budget):
    require(type(raw) is bytes and len(raw) <= MAX_METADATA, 'limit')
    budget.check()
    with difference.CatalogCapture() as retained:
        retained.capture(raw)
        result = difference._records(retained)
    budget.check()
    return result


@closed
def decode_metadata(raw, *, catalog_raw, roles_raw, deadline):
    budget = Budget(deadline)
    observation = decode_observation(raw, deadline=deadline)
    require(type(roles_raw) is bytes and len(roles_raw) <= MAX_ROLES_BYTES, 'limit')
    lines = roles_raw.removesuffix(b'\n').split(b'\n'); require(len(lines) == 2, 'source_binding')
    role_rows, edges = [_json(x, MAX_ROLES_BYTES, budget) for x in lines]
    _list(role_rows, MAX_ROLES); _list(edges, MAX_EDGES)
    expected = {r.name: r for r in observation.roles}
    require(len(role_rows) == len(expected), 'source_binding')
    seen = set()
    for row in role_rows:
        budget.check()
        require(type(row) is dict and row.get('rolname') in expected and row['rolname'] not in seen, 'source_binding')
        keys(row, ('rolname', *ROLE_FLAGS, 'rolconnlimit', 'rolpassword', 'rolvaliduntil'))
        integer(row['rolconnlimit'], -1, 2**31-1)
        require(all(row[k] is None or type(row[k]) is str and len(row[k].encode()) <= MAX_ROW
                    for k in ('rolpassword', 'rolvaliduntil')), 'source_binding')
        r = expected[row['rolname']]; seen.add(r.name)
        require(row.get('rolsuper') is r.superuser and row.get('rolcanlogin') is r.login, 'source_binding')
        require(all(type(row.get(x)) is bool for x in ROLE_FLAGS), 'source_binding')
    for edge in edges:
        require(type(edge) is list and len(edge) == 6 and all(x in expected for x in edge[:3])
                and all(type(x) is bool for x in edge[3:]), 'source_binding')
    records = _catalog_records(catalog_raw, budget)
    column_counts = {}
    for key, record in records.items():
        budget.check()
        if record[0] == 'column_acl':
            identity = tuple(json.loads(key)[1:3])
            column_counts[identity] = column_counts.get(identity, 0) + 1
    observed = set()
    for obj in observation.objects:
        budget.check()
        key = canonical(obj.identity); observed.add(key)
        require(key in records, 'source_binding')
        fields = records[key][2]
        require(fields['owner'] == obj.owner and fields['acl'] == (obj.acl.raw if obj.acl else None), 'source_binding')
        if obj.identity[0] == 'relation':
            require(fields['kind'] == obj.kind, 'source_binding')
            require(column_counts.get(obj.identity[1:3], 0) == obj.columns, 'source_binding')
    require(observed == {k for k, v in records.items() if v[0] in ('relation', 'function')}, 'source_binding')
    defaults = {canonical(('default_acl', *d.key)): d.acl.raw for d in observation.default_acls}
    require(defaults == {k: v[2]['acl'] for k, v in records.items() if v[0] == 'default_acl'}, 'source_binding')
    selected = observation.selected_catalog
    for group, identities in (('schemas', capture.SCHEMAS), ('functions', capture.NET_IDENTITIES)):
        require({tuple(x['identity']) for x in selected[group]} == {tuple(x) for x in identities}, 'source_binding')
        # This metadata projection deliberately omits hooks/events. Bind every
        # selected row without claiming the omitted groups were observed empty.
        capture._bound_rows(selected[group], records, identities)
    budget.check()
    # Passwords remain only in the caller's existing protected role stream.
    # The supplement retains the attributes needed for CREATE partition checks.
    attributes = [{k: row[k] for k in ('rolname', *ROLE_FLAGS, 'rolconnlimit')} for row in role_rows]
    return replace(observation, _selected=canonical(selected), _role_rows=canonical(attributes),
                   _catalog=catalog_raw, _roles_binding=canonical(binding(roles_raw, budget)))


@closed
def bind_source_snapshot(source, raw_snapshot, *, deadline):
    """Bind a separately queried, raw fixed snapshot; never invent extension data.

    Caller checks this observation at M0/M1/final alongside Metadata.binding.
    The checked separate reads do not assert atomicity or exclude ABA changes.
    """
    budget = Budget(deadline)
    require(type(source) is Metadata and source._catalog and not source._source_snapshot, 'source_binding')
    if type(raw_snapshot) is bytes:
        snapshot = _json(raw_snapshot, MAX_METADATA, budget)
    else:
        require(type(raw_snapshot) is dict, 'source_binding')
        encoded = canonical(raw_snapshot)
        require(len(encoded) <= MAX_METADATA, 'limit')
        snapshot = _json(encoded, MAX_METADATA, budget)
    require(type(snapshot.get('serverVersion')) is int and snapshot['serverVersion'] == 170006, 'source_binding')
    with difference.CatalogCapture() as retained:
        retained.capture(source._catalog)
        snapshot = capture._validate_snapshot(snapshot, retained)
    selected = json.loads(source._selected)
    require(all(snapshot[k] == selected[k] for k in ('schemas', 'functions')), 'source_binding')
    extensions = [e for e in snapshot['extensions'] if e[0] == 'pg_net']
    require(len(extensions) == 1, 'source_binding')
    extension = extensions[0]
    for function in selected['functions']:
        require(function['extensions'] == [[extension[0], extension[1], extension[3]]], 'source_binding')
    budget.check()
    return replace(source, _source_snapshot=canonical(snapshot))


def _statements(raw, budget, *, meta=()):
    scan = lexical.scan(raw, expected_meta=meta, deadline=budget.short(), profile=lexical.PROFILE)
    token = 0
    for at in range(0, len(scan.leaves), lexical.RECORD.size):
        budget.check()
        kind, start, stop = lexical.RECORD.unpack_from(scan.leaves, at)
        if kind != lexical.SQL:
            require(kind in (lexical.TRIVIA, lexical.META), 'role_profile')
            continue
        while token < len(scan.tokens) and lexical.RECORD.unpack_from(scan.tokens, token)[2] <= start:
            token += lexical.RECORD.size
        first = token
        while token < len(scan.tokens) and lexical.RECORD.unpack_from(scan.tokens, token)[1] < stop:
            token += lexical.RECORD.size
        yield Statement(raw, scan.tokens, first, token, start, stop, budget)


def _sname(s):
    return name(s.ident().decode('utf8'))


@dataclass(frozen=True, repr=False)
class RoleProgram:
    sql: bytes
    bootstrap: str
    _binding: bytes
    _accounting: bytes

    @property
    def binding(self):
        return json.loads(self._binding)

    @property
    def accounting(self):
        return json.loads(self._accounting)


def _role_statement(s, roles, source_rows):
    if s.take(b'CREATE'):
        s.need(b'ROLE'); n = _sname(s); s.finish()
        require(n in roles and not n.startswith('pg_'), 'role_profile')
        return 'create', n
    if s.take(b'SET'):
        setting = _sname(s); s.need(b'=')
        value = s.raw[s.peek()[1]:s.peek()[2]]; s.advance(); s.finish()
        require((setting, value) in (('default_transaction_read_only', b'off'),
            ('client_encoding', b"'UTF8'"), ('standard_conforming_strings', b'on')), 'role_profile')
        return 'preamble', setting
    if s.take(b'ALTER'):
        s.need(b'ROLE'); n = _sname(s); require(n in roles, 'role_profile')
        if s.take(b'WITH'):
            row = source_rows[n]
            for field_, word in zip(ROLE_FLAGS, ROLE_WORDS, strict=True):
                s.need((word if row[field_] else 'NO' + word).encode())
            if s.take(b'CONNECTION'):
                s.need(b'LIMIT'); require(s.integer() == row.get('rolconnlimit'), 'role_profile')
            else:
                require(row.get('rolconnlimit') == -1, 'role_profile')
            if s.take(b'PASSWORD'):
                s.literal()  # Opaque password is copied, never rendered/reported.
            if s.take(b'VALID'):
                s.need(b'UNTIL'); s.literal()
            s.finish()
            return 'attributes', n
        s.need(b'SET'); _sname(s)
        while s.take(b'.'):
            _sname(s)
        s.need(b'TO'); s.literal()
        while s.take(b','):
            s.literal()
        s.finish(); return 'other', n
    if s.take(b'COMMENT'):
        s.need(b'ON', b'ROLE'); n = _sname(s); require(n in roles, 'role_profile')
        s.need(b'IS'); s.literal(); s.finish(); return 'other', n
    if s.take(b'SECURITY'):
        s.need(b'LABEL', b'FOR'); _sname(s); s.need(b'ON', b'ROLE')
        n = _sname(s); require(n in roles, 'role_profile'); s.need(b'IS'); s.literal(); s.finish()
        return 'other', n
    s.need(b'GRANT'); granted = _sname(s); s.need(b'TO'); member = _sname(s)
    require(granted in roles and member in roles, 'role_profile')
    options = set()
    if s.take(b'WITH'):
        while True:
            option = s.ident().upper(); require(option in (b'ADMIN', b'INHERIT', b'SET') and option not in options, 'role_profile')
            options.add(option)
            if s.take(b'OPTION'):
                require(option == b'ADMIN', 'role_profile')
            else:
                require(s.take(b'TRUE') or s.take(b'FALSE'), 'role_profile')
            if not s.take(b','):
                break
    s.need(b'GRANTED', b'BY'); require(_sname(s) in roles, 'role_profile'); s.finish()
    return 'membership', member


@closed
def role_program(role_sql, source, *, deadline):
    budget = Budget(deadline)
    require(type(source) is Metadata and source._role_rows, 'source_binding')
    require(type(role_sql) is bytes and 0 < len(role_sql) <= MAX_ROLES_BYTES, 'limit')
    restrict = re.findall(rb'(?m)^\\(?:un)?restrict [A-Za-z0-9]{1,128}\n', role_sql)
    require(len(restrict) == 2 and restrict[1] == restrict[0].replace(b'\\restrict ', b'\\unrestrict ', 1), 'role_profile')
    roles = {r.name: r for r in source.roles}; rows = {r['rolname']: r for r in json.loads(source._role_rows)}
    creates, attrs, count, edges, preamble, started = {}, set(), 0, 0, set(), False
    for s in _statements(role_sql, budget, meta=tuple(restrict)):
        count += 1; require(count <= MAX_ROLE_STATEMENTS, 'limit')
        kind, n = _role_statement(s, roles, rows)
        if kind == 'preamble':
            require(not started and n not in preamble, 'role_profile'); preamble.add(n)
        else:
            started = True
        if kind == 'create':
            require(n not in creates, 'role_profile'); creates[n] = (s.start, s.stop)
        if kind == 'attributes':
            require(n not in attrs, 'role_profile'); attrs.add(n)
        if kind == 'membership':
            edges += 1; require(edges <= MAX_EDGES, 'limit')
    custom = {r.name for r in source.roles if not r.name.startswith('pg_')}
    require(source.bootstrap in custom, 'role_profile')
    require(set(creates) == custom == attrs and preamble == {
        'default_transaction_read_only', 'client_encoding', 'standard_conforming_strings'}, 'role_profile')
    first = min(x[0] for x in creates.values())
    pieces = [role_sql[:first]]
    for r in source.roles:
        budget.check()
        if r.name in creates and r.name != source.bootstrap:
            a, b = creates[r.name]; pieces.append(role_sql[a:b])
    position = first
    for a, b in sorted(creates.values()):
        pieces.append(role_sql[position:a]); position = b
    pieces.append(role_sql[position:])
    require(sum(map(len, pieces)) <= MAX_ROLES_BYTES, 'limit')
    sql = b''.join(pieces)
    accounting = {'creates': len(creates), 'executedCreates': len(creates) - 1,
                  'bootstrapCreates': 1, 'statements': count, 'memberships': edges,
                  'original': binding(role_sql, budget)}
    return RoleProgram(sql, source.bootstrap, canonical(binding(sql, budget)), canonical(accounting))


@closed
def validate_role_order(source, target_role_bytes, *, deadline):
    budget = Budget(deadline)
    target = _roles(_json(target_role_bytes, MAX_ROLES_BYTES, budget), budget)
    require([r.name for r in target] == [r.name for r in source.roles], 'role_order')
    for original, actual in zip(source.roles, target, strict=True):
        budget.check()
        require((original.superuser, original.login) == (actual.superuser, actual.login), 'role_order')
        if original.oid < 16384 or original.name.startswith('pg_'):
            require(original.oid == actual.oid, 'role_order')
    require(next(r.name for r in target if r.oid == 10) == source.bootstrap, 'role_order')


@dataclass(frozen=True, repr=False)
class Operation:
    grant: bool
    rights: frozenset
    grantee: str | None
    options: bool


def _domain(obj):
    return DOMAINS[obj.acl_kind]


def _supported(obj):
    if obj.columns:
        return False
    if obj.identity[0] == 'relation':
        return obj.kind in ('r', 'p', 'v', 'm', 'f', 'S')
    return obj.kind in ('f', 'p') and obj.argument_modes in (None, tuple('i' for _ in obj.argument_types)) and all(
        not typ[1].startswith('_') for typ in obj.argument_types)


TYPE_WORDS = {'int2': (b'SMALLINT',), 'int4': (b'INTEGER',), 'int8': (b'BIGINT',),
    'float4': (b'REAL',), 'float8': (b'DOUBLE', b'PRECISION'), 'bool': (b'BOOLEAN',),
    'varchar': (b'CHARACTER', b'VARYING'), 'bpchar': (b'CHARACTER',),
    'timestamp': (b'TIMESTAMP', b'WITHOUT', b'TIME', b'ZONE'),
    'timestamptz': (b'TIMESTAMP', b'WITH', b'TIME', b'ZONE'),
    'time': (b'TIME', b'WITHOUT', b'TIME', b'ZONE'), 'timetz': (b'TIME', b'WITH', b'TIME', b'ZONE')}


def _type(s, typ):
    ns, n = typ
    if ns == 'pg_catalog' and n in TYPE_WORDS and s.is_(TYPE_WORDS[n][0]):
        s.need(*TYPE_WORDS[n]); return
    actual_ns, actual_n = s.name()
    require(actual_n.decode() == n and (actual_ns == ns.encode() or
        actual_ns is None and ns == 'pg_catalog'), 'suffix_profile')


def _argument(s, typ):
    first = s.at
    try:
        _type(s, typ)
        require(s.is_(b',') or s.is_(b')'), 'suffix_profile')
        return None
    except (MetadataUnavailable, ledger.Unavailable) as error:
        if error.reason not in ('suffix_profile', 'role'):
            raise
        s.at = first
    argument = _sname(s)
    _type(s, typ)
    require(s.is_(b',') or s.is_(b')'), 'suffix_profile')
    return argument


def _argument_names(obj, budget):
    # Parse the bound identity text as data with a closed grammar. Only qualified
    # type identifiers below are ever rendered into supplemental SQL.
    raw = b'x(' + obj.identity[3].encode('utf8') + b');\n'
    statements = list(_statements(raw, budget)); require(len(statements) == 1, 'suffix_profile')
    s = statements[0]; s.ident(b'x'); s.need(b'(')
    names = []
    for i, typ in enumerate(obj.argument_types):
        if i:
            s.need(b',')
        names.append(_argument(s, typ))
    s.need(b')'); s.finish()
    return names


def _target(s, obj):
    expected = b'SEQUENCE' if obj.kind == 'S' and obj.identity[0] == 'relation' else (
        (b'PROCEDURE' if obj.kind == 'p' else b'FUNCTION') if obj.identity[0] == 'function' else b'TABLE')
    s.need(expected)
    ns, n = s.name()
    require((ns, n) == (obj.identity[1].encode(), obj.identity[2].encode()), 'suffix_profile')
    if obj.identity[0] == 'function':
        s.need(b'(')
        names = _argument_names(obj, s.budget)
        for i, typ in enumerate(obj.argument_types):
            if i:
                s.need(b',')
            require(_argument(s, typ) == names[i], 'suffix_profile')
        s.need(b')')


def _rights(s, domain):
    if s.take(b'ALL'):
        s.take(b'PRIVILEGES')
        return frozenset(domain)
    rights = set()
    while True:
        word = s.ident().decode().upper()
        if word == 'ALTER':
            s.need(b'SYSTEM'); word = 'ALTER SYSTEM'
        require(word in domain and word not in rights, 'suffix_profile'); rights.add(word)
        if not s.take(b','):
            break
    return frozenset(rights)


def _operation_prefix(s, domain):
    if s.take(b'GRANT'):
        grant, options = True, False
    else:
        s.need(b'REVOKE'); grant = False
        options = s.take(b'GRANT')
        if options:
            s.need(b'OPTION', b'FOR')
    rights = _rights(s, domain); s.need(b'ON')
    return grant, options, rights


def _operation_ending(s, *, grant, options, roles, owners):
    s.need(b'TO' if grant else b'FROM')
    if s.take(b'PUBLIC'):
        grantee = None
    else:
        grantee = _sname(s); require(grantee in roles, 'suffix_profile')
    if grant and s.take(b'WITH'):
        s.need(b'GRANT', b'OPTION'); options = True
    if s.take(b'GRANTED'):
        s.need(b'BY')
        require(owners == {_sname(s)}, 'suffix_profile')
    if not grant:
        s.take(b'RESTRICT')
    s.finish()  # CASCADE, multiple targets/grantees and extra SQL fail here.
    require(not (grantee is None and options and grant), 'suffix_profile')
    return grantee, options


def _operation(s, *, obj=None, default_key=None, roles):
    domain = _domain(obj) if obj is not None else DOMAINS[default_key[2]]
    grant, options, rights = _operation_prefix(s, domain)
    if obj is not None:
        _target(s, obj)
    else:
        s.need({'r': b'TABLES', 'S': b'SEQUENCES', 'f': b'FUNCTIONS', 'T': b'TYPES', 'n': b'SCHEMAS'}[default_key[2]])
    grantee, options = _operation_ending(s, grant=grant, options=options, roles=roles,
        owners={obj.owner if obj is not None else default_key[0]})
    return Operation(grant, rights, grantee, options)


def _apply(acl, op, kind, owner):
    items = list((acl or _default(kind, owner)).items)
    found = next((i for i, row in enumerate(items) if (row.grantee, row.grantor) == (op.grantee, owner)), None)
    old = items[found] if found is not None else ACLItem(op.grantee, owner, frozenset(), frozenset())
    if op.grant:
        row = replace(old, privileges=old.privileges | op.rights,
                      options=old.options | (op.rights if op.options else frozenset()))
    else:
        row = replace(old, privileges=old.privileges if op.options else old.privileges - op.rights,
                      options=old.options - op.rights)
    if row.privileges:
        if found is None:
            items.append(row)
        else:
            items[found] = row
    elif found is not None:
        del items[found]
    return ACL(_acl_raw(items), tuple(items))


def _owner_profile(acl, default, owner):
    if acl is None:
        return True
    pairs = [(x.grantee, x.grantor) for x in acl.items]
    owner_item = next(x for x in default.items if x.grantee == owner)
    return (len(pairs) == len(set(pairs)) and all(x.grantor == owner and x.privileges
        and not (x.grantee is None and x.options) for x in acl.items)
        and sum(x == owner_item for x in acl.items) == 1)


def _stable(acl, operations, obj, budget):
    current = acl
    for op in operations:
        budget.check()
        pair = next((x for x in acl.items if (x.grantee, x.grantor) == (op.grantee, obj.owner)), None)
        if op.grant:
            require(pair is not None and op.rights <= pair.privileges
                    and (not op.options or op.rights <= pair.options), 'suffix_profile')
        else:
            absent = pair is None or not op.rights & (pair.options if op.options else pair.privileges)
            require(absent, 'suffix_profile')
        current = _apply(current, op, obj.acl_kind, obj.owner)
        require(current == acl, 'suffix_profile')


def _render_target(obj, budget):
    target = _ident(obj.identity[1], budget) + b'.' + _ident(obj.identity[2], budget)
    if obj.identity[0] == 'function':
        args = [_ident(ns, budget) + b'.' + _ident(n, budget) for ns, n in obj.argument_types]
        return (b'PROCEDURE ' if obj.kind == 'p' else b'FUNCTION ') + target + b'(' + b', '.join(args) + b')'
    return (b'SEQUENCE ' if obj.kind == 'S' else b'TABLE ') + target


def _recipient(value, budget):
    return b'PUBLIC' if value is None else _ident(value, budget)


def _seed_sql(obj, baseline, budget):
    target = _render_target(obj, budget)
    effective = baseline or obj.default
    statements = []
    # Erase only the closed owner-origin creation ACL, then insert each desired
    # pair in source array order. Owner retains implicit grant authority.
    for item in effective.items:
        statements.append(b'REVOKE ALL ON ' + target + b' FROM ' + _recipient(item.grantee, budget) + b' RESTRICT;\n')
    for item in obj.acl.items:
        for option in (False, True):
            rights = item.options if option else item.privileges - item.options
            if rights:
                words = [right.encode() for _, right in RIGHTS if right in rights]
                statements.append(b'GRANT ' + b', '.join(words) + b' ON ' + target + b' TO ' +
                    _recipient(item.grantee, budget) + (b' WITH GRANT OPTION' if option else b'') + b';\n')
    require(len(statements) <= MAX_STATEMENTS and sum(map(len, statements)) <= MAX_SQL, 'limit')
    return b''.join(statements), len(statements)


@dataclass(frozen=True, repr=False)
class Candidate:
    object: Object
    baseline: ACL | None
    sql: bytes
    statements: int
    materialize: bool


@dataclass(frozen=True, repr=False)
class RepairPlan:
    source: Metadata
    candidates: tuple
    pre_acl: int
    _cuts: bytes
    _counts: bytes
    _binding: bytes
    _prefixes: tuple

    @property
    def cuts(self):
        return json.loads(self._cuts)

    @property
    def counts(self):
        return json.loads(self._counts)

    @property
    def binding(self):
        return json.loads(self._binding)


@dataclass(frozen=True, repr=False)
class Mutation:
    sql: bytes
    applied: int
    noop: int
    _binding: bytes
    _identities: tuple = ()

    @property
    def binding(self):
        return json.loads(self._binding)


def _spans(spans, script, pre_acl, budget, used):
    last = pre_acl
    for span in _list(spans, MAX_STATEMENTS):
        budget.check()
        require(type(span) is list and len(span) == 2, 'archive_profile')
        a = integer(span[0], pre_acl, len(script)); b = integer(span[1], a + 1, len(script))
        require(last <= a and (a, b) not in used, 'archive_profile')
        used.add((a, b)); last = b
        require(b - a <= MAX_ROW, 'limit')
        part = script[a:b]
        statements = list(_statements(part if part.endswith(b'\n') else part + b'\n', budget))
        require(len(statements) == 1, 'suffix_profile')
        yield statements[0]


def _default_program(source, script, spans, pre_acl, budget, used):
    roles = {r.name: r.oid for r in source.roles}
    modeled = {}
    for s in _spans(spans, script, pre_acl, budget, used):
        s.need(b'ALTER', b'DEFAULT', b'PRIVILEGES', b'FOR', b'ROLE')
        owner = _sname(s); require(owner in roles, 'suffix_profile')
        schema = None
        if s.take(b'IN'):
            s.need(b'SCHEMA'); schema = _sname(s)
        # Read the ON type from the final exposed suffix, not raw substring SQL.
        probe = Statement(s.raw, s.tokens, s.at, s.end, s.start, s.stop, budget)
        if not probe.take(b'GRANT'):
            probe.need(b'REVOKE')
            if probe.take(b'GRANT'):
                probe.need(b'OPTION', b'FOR')
        while not probe.take(b'ON'):
            require(not probe.is_(b';'), 'suffix_profile'); probe.advance()
        word = probe.ident().upper()
        kinds = {b'TABLES': 'r', b'SEQUENCES': 'S', b'FUNCTIONS': 'f', b'TYPES': 'T', b'SCHEMAS': 'n'}
        require(word in kinds, 'suffix_profile'); kind = kinds[word]; key = owner, schema, kind
        op = _operation(s, default_key=key, roles=roles)
        base = modeled.get(key, _default(kind, owner) if schema is None else ACL('{}', ()))
        after = _apply(base, op, kind, owner)
        ordered = sorted(after.items, key=lambda x: (0 if x.grantee is None else roles[x.grantee], roles[x.grantor]))
        modeled[key] = ACL(_acl_raw(ordered), tuple(ordered))
    observed = {}
    for key, acl in modeled.items():
        owner, schema, kind = key
        base = _default(kind, owner) if schema is None else ACL('{}', ())
        # SetDefaultACL compares sorted hardwired defaults before normalizing absence.
        sorted_base = sorted(base.items, key=lambda x: (0 if x.grantee is None else roles[x.grantee], roles[x.grantor]))
        if acl.items != tuple(sorted_base):
            observed[key] = acl
    require(observed == {d.key: d.acl for d in source.default_acls}, 'suffix_profile')


def _prefix_programs(source, budget):
    catalog = source.selected_catalog
    _, is_sql = causal._schema_slots(catalog)
    for i in range(2):
        item = causal._function(catalog, i)
        require(item['row'][6:] == [True, '{search_path=net}'], 'prefix_binding')
    in_sql = causal.CONFIG['In']['sql'].encode('ascii')
    require(0 < len(is_sql) <= 2048 and 0 < len(in_sql) <= 2048, 'limit')
    budget.check()
    return is_sql, in_sql


@closed
def compile_plan(source, *, script, archive, index, deadline):
    budget = Budget(deadline)
    require(type(source) is Metadata and source._role_rows and source._catalog
            and source._source_snapshot, 'source_binding')
    require(type(script) is bytes and 0 < len(script) <= MAX_SCRIPT, 'limit')
    keys(index, ('schema', 'script', 'preAcl', 'cuts', 'objects', 'defaultAclSpans'))
    require(index['schema'] == 'rf1086-repair-index-v1' and index['script'] == binding(script, budget), 'archive_profile')
    hook = integer(index['preAcl'], 1, len(script) - 1)
    keys(index['cuts'], ('Is', 'In'))
    a = integer(index['cuts']['Is'], 1, hook - 1)
    b = integer(index['cuts']['In'], 1, hook - 1)
    require(a != b, 'archive_profile')
    require(type(archive.raw) is bytes and len(archive.raw) <= 64 * 1024**2, 'limit')
    archive_pairs = {}
    for entry in archive.entries:
        budget.check()
        if entry.class_oid and entry.object_oid:
            archive_pairs.setdefault((entry.class_oid, entry.object_oid), []).append(entry)
    rows, used, index_spans = {}, set(), []
    source_ids = {o.identity for o in source.objects}
    index_bytes = 0
    for row in _list(index['objects'], MAX_OBJECTS):
        budget.check()
        keys(row, ('classOid', 'objectOid', 'identity', 'owner', 'kind', 'createdEnd', 'aclSpans', 'laterMutation'))
        require(type(row['identity']) is list and len(row['identity']) in (3, 4), 'archive_profile')
        require(all(type(x) is str and len(x.encode()) <= MAX_ROW for x in row['identity']), 'archive_profile')
        ident = tuple(row['identity']); require(ident in source_ids and ident not in rows, 'archive_profile')
        integer(row['classOid'], 1, 2**32-1); integer(row['objectOid'], 1, 2**32-1)
        name(row['owner']); require(type(row['kind']) is str and len(row['kind']) == 1, 'archive_profile')
        require(type(row['laterMutation']) is bool, 'archive_profile')
        integer(row['createdEnd'], 1, hook)
        for span in _list(row['aclSpans'], MAX_STATEMENTS):
            budget.check()
            require(type(span) is list and len(span) == 2, 'archive_profile')
            integer(span[0], hook, len(script)-1); integer(span[1], span[0]+1, len(script))
            require(len(index_spans) < MAX_ROLE_STATEMENTS, 'limit')
            index_spans.append(tuple(span))
        row_size = len(canonical(row))
        require(row_size <= MAX_ROW, 'limit')
        index_bytes += row_size
        require(index_bytes <= MAX_METADATA, 'limit')
        rows[ident] = row
    for span in _list(index['defaultAclSpans'], MAX_STATEMENTS):
        budget.check()
        require(type(span) is list and len(span) == 2, 'archive_profile')
        integer(span[0], hook, len(script)-1); integer(span[1], span[0]+1, len(script))
        require(len(index_spans) < MAX_ROLE_STATEMENTS, 'limit'); index_spans.append(tuple(span))
    index_spans.sort()
    require(all(index_spans[i-1][1] <= index_spans[i][0] for i in range(1,len(index_spans))), 'archive_profile')
    candidates, unmodeled, archive_only, statements, sql_size = [], 0, 0, 0, 0
    for obj in source.objects:
        budget.check()
        row = rows.get(obj.identity)
        if row is not None:
            require((row['classOid'], row['objectOid'], row['owner'], row['kind']) ==
                    (obj.class_oid, obj.object_oid, obj.owner, obj.kind), 'archive_profile')
        if obj.acl is None or not _supported(obj) or not _owner_profile(obj.acl, obj.default, obj.owner):
            archive_only += 1; unmodeled += int(obj.acl is not None)
            continue
        # A missing lifecycle cannot be supplied by a matching comment/target result.
        if row is None:
            raise MetadataUnavailable('archive_profile')
        entries = archive_pairs.get((obj.class_oid, obj.object_oid), ())
        direct = any(e.namespace == obj.identity[1].encode() and e.owner == obj.owner.encode()
                    and (obj.identity[0] == 'function' or e.tag == obj.identity[2].encode())
                    for e in entries)
        extension = len(obj.extension) == 1 and any(e.description == b'EXTENSION'
            and e.tag == obj.extension[0][0].encode()
            and e.owner in (None, b'', obj.extension[0][2].encode()) for e in archive.entries)
        require(direct or not entries and extension, 'archive_profile')
        operations = tuple(_operation(s, obj=obj, roles={r.name for r in source.roles})
                           for s in _spans(row['aclSpans'], script, hook, budget, used))
        baseline = obj.initial
        current = baseline
        for op in operations:
            budget.check(); current = _apply(current, op, obj.acl_kind, obj.owner)
        if current == obj.acl:
            archive_only += 1
            unmodeled += int(row['laterMutation'])
            continue
        require(not row['laterMutation'] and _owner_profile(obj.acl, obj.default, obj.owner)
                and _owner_profile(baseline, obj.default, obj.owner), 'suffix_profile')
        _stable(obj.acl, operations, obj, budget)
        materialize = obj.identity[0] == 'relation' and len(obj.acl.items) == 1 and obj.acl == obj.default
        if materialize and baseline is None:
            rights = b', '.join(x.encode() for x in _domain(obj))
            sql = b'GRANT ' + rights + b' ON ' + _render_target(obj, budget) + b' TO ' + _ident(obj.owner, budget) + b';\n'
            n = 1
        else:
            sql, n = _seed_sql(obj, baseline, budget)
        statements += n; require(statements + 2 <= MAX_STATEMENTS, 'limit')
        sql_size += len(sql)
        require(sql_size + 16 <= MAX_SQL, 'limit')
        candidates.append(Candidate(obj, baseline, sql, n, materialize))
    _default_program(source, script, index['defaultAclSpans'], hook, budget, used)
    # Ensure spans of different objects cannot overlap or alias each other.
    spans = sorted(used)
    require(all(spans[i - 1][1] <= spans[i][0] for i in range(1, len(spans))), 'archive_profile')
    prefixes = _prefix_programs(source, budget)
    counts = {'objects': len(source.objects), 'candidates': len(candidates),
              'archiveOnly': archive_only, 'unmodeled': unmodeled,
              'statements': statements, 'defaultAcls': len(source.default_acls)}
    commitment = {'profile': CONFIG_SHA256, 'source': source.binding,
        'fixedSnapshot': source.snapshot_binding,
        'catalogObservation': binding(source._catalog, budget), 'roleObservation': json.loads(source._roles_binding),
        'archive': binding(archive.raw, budget), 'script': index['script'],
        'index': binding(canonical(index), budget), 'supplement': binding(b''.join(c.sql for c in candidates), budget)}
    return RepairPlan(source, tuple(candidates), hook, canonical(index['cuts']), canonical(counts),
                      canonical(commitment), prefixes)


def _object_static(obj):
    return (obj.identity, obj.kind, obj.owner, obj.default, obj.initial, obj.initial_type,
            obj.extension, obj.columns, obj.argument_types, obj.argument_modes)


def _same_target(before, after, allowed, budget):
    require(before.system_identifier == after.system_identifier and before.roles == after.roles, 'postcondition')
    require(before.default_acls == after.default_acls, 'postcondition')
    old_selected, new_selected = before.selected_catalog, after.selected_catalog
    for function in old_selected['functions']:
        if tuple(function['identity']) in allowed:
            actual = next((f for f in new_selected['functions'] if f['identity'] == function['identity']), None)
            require(actual is not None, 'postcondition')
            function['row'][5] = actual['row'][5]
    require(old_selected == new_selected, 'postcondition')
    old = {o.identity: o for o in before.objects}; new = {o.identity: o for o in after.objects}
    require(old.keys() == new.keys(), 'postcondition')
    for identity, obj in old.items():
        budget.check()
        other = new[identity]
        require(obj.class_oid == other.class_oid and obj.object_oid == other.object_oid
                and _object_static(obj) == _object_static(other), 'postcondition')
        if identity not in allowed:
            require(obj.acl == other.acl, 'postcondition')


@closed
def pre_acl(plan, target, *, deadline):
    budget = Budget(deadline)
    require(type(plan) is RepairPlan and type(target) is Metadata, 'creation_profile')
    # The original default-ACL pass has not run; creating objects cannot seed it.
    require(not target.default_acls, 'creation_profile')
    by_id = {o.identity: o for o in target.objects}
    require(by_id.keys() == {o.identity for o in plan.source.objects}, 'creation_profile')
    pieces, applied, noop, selected = [], 0, 0, []
    for candidate in plan.candidates:
        budget.check(); source = candidate.object; actual = by_id[source.identity]
        require(_object_static(source) == _object_static(actual), 'creation_profile')
        if actual.acl == source.acl:
            noop += 1
        else:
            require(actual.acl == candidate.baseline, 'creation_profile')
            pieces.append(candidate.sql); applied += 1; selected.append(source.identity)
    size = sum(map(len, pieces)) + (16 if pieces else 0)
    require(size <= MAX_SQL, 'limit')
    sql = b'BEGIN;\n' + b''.join(pieces) + b'COMMIT;\n' if pieces else b''
    return Mutation(sql, applied, noop, canonical(binding(sql, budget)), tuple(selected))


@closed
def post_acl(plan, before, after, mutation, *, deadline):
    budget = Budget(deadline)
    expected = pre_acl(plan, before, deadline=deadline)
    require(mutation == expected, 'postcondition')
    _same_target(before, after, set(expected._identities), budget)
    actual = {o.identity: o for o in after.objects}
    for c in plan.candidates:
        budget.check(); require(actual[c.object.identity].acl == c.object.acl, 'postcondition')


def _normal(catalog, budget):
    require(type(catalog) is dict and len(canonical(catalog)) <= MAX_METADATA, 'limit')
    budget.check()
    # Root observer already performed the one raw deep validation. In particular,
    # hook configuration is now a hash: never feed it through the raw parser again.
    value = json.loads(canonical(catalog))
    causal._normal(value)
    return value


def _prefix_expected(plan, kind, before, budget):
    require(kind in ('Is', 'In'), 'prefix_binding')
    source = plan.source.selected_catalog
    result = json.loads(canonical(before))
    if kind == 'Is':
        for i in range(2):
            desired = causal._schema(source, i); actual = causal._schema(before, i)
            # Only the declared privilege change is source-valued. Other prefix
            # fields (including initial privileges) remain observed and unchanged.
            causal._default_schema(actual)
            if actual['row'][3] != desired['row'][3] or actual['grants'] != desired['grants']:
                causal._default_schema(actual)
                require(actual['row'][3] in (None, actual['defaults'])
                        and actual['grants'] == actual['default_grants'], 'prefix_binding')
            target = next(x for x in result['schemas'] if x['identity'] == desired['identity'])
            target['row'][3] = desired['row'][3]; target['grants'] = desired['grants']
    else:
        for i in range(2):
            desired = causal._function(source, i); actual = causal._function(before, i)
            require(causal._definition(actual) == causal._definition(desired), 'prefix_binding')
            require(actual['row'][6:] in ([False, None], [True, '{search_path=net}']), 'prefix_binding')
            if actual['row'][6:] == desired['row'][6:]:
                require(actual['definition_sha256'] == desired['definition_sha256'], 'prefix_binding')
            target = next(x for x in result['functions'] if x['identity'] == desired['identity'])
            target['row'][6:] = desired['row'][6:]
            target['definition_sha256'] = desired['definition_sha256']
    return result


@closed
def prefix_mutation(plan, kind, target_catalog, *, deadline):
    budget = Budget(deadline)
    before = _normal(target_catalog, budget)
    expected = _prefix_expected(plan, kind, before, budget)
    noop = before == expected
    sql = b'' if noop else plan._prefixes[0 if kind == 'Is' else 1]
    require(len(sql) <= 2048, 'limit')
    return Mutation(sql, int(not noop), int(noop), canonical(binding(sql, budget)))


@closed
def prefix_postcheck(plan, kind, before_catalog, after_catalog, *, deadline):
    budget = Budget(deadline)
    before, after = _normal(before_catalog, budget), _normal(after_catalog, budget)
    require(after == _prefix_expected(plan, kind, before, budget), 'postcondition')
    budget.check()


# Fixed source query; query output remains private and bounded by the caller.
METADATA_SQL = br"""BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '3s';
SET LOCAL lock_timeout = '1s';
WITH role_rows AS MATERIALIZED (
 SELECT rolname AS name, oid::bigint AS oid, rolsuper AS superuser, rolcanlogin AS login
 FROM pg_catalog.pg_roles ORDER BY oid LIMIT 257
), object_base AS MATERIALIZED (
 SELECT c.tableoid::oid AS class_oid,c.oid AS object_oid,
 pg_catalog.jsonb_build_array('relation',n.nspname,c.relname) AS identity,
 c.relkind::text AS kind,c.relowner AS owner,c.relacl AS acl,
 pg_catalog.acldefault(CASE WHEN c.relkind='S' THEN 's' ELSE 'r' END::"char",c.relowner) AS default_acl,
 (SELECT count(*) FROM pg_catalog.pg_attribute a WHERE a.attrelid=c.oid AND a.attacl IS NOT NULL) AS columns,
 '[]'::jsonb AS argument_types,NULL::jsonb AS argument_modes
 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
 UNION ALL
 SELECT p.tableoid::oid,p.oid,
 pg_catalog.jsonb_build_array('function',n.nspname,p.proname,pg_catalog.pg_get_function_identity_arguments(p.oid)),
 p.prokind::text,p.proowner,p.proacl,pg_catalog.acldefault('f',p.proowner),0,
 (SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(tn.nspname,t.typname) ORDER BY u.ordinality),'[]'::jsonb)
  FROM pg_catalog.unnest(p.proargtypes) WITH ORDINALITY u(oid,ordinality)
  JOIN pg_catalog.pg_type t ON t.oid=u.oid JOIN pg_catalog.pg_namespace tn ON tn.oid=t.typnamespace),
 pg_catalog.to_jsonb(p.proargmodes)
 FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
 LIMIT 8193
), objects AS MATERIALIZED (
 SELECT o.*,
 (SELECT count(*) FROM pg_catalog.pg_init_privs i WHERE i.classoid=o.class_oid AND i.objoid=o.object_oid AND i.objsubid=0) AS initial_count,
 (SELECT i.initprivs FROM pg_catalog.pg_init_privs i WHERE i.classoid=o.class_oid AND i.objoid=o.object_oid AND i.objsubid=0 LIMIT 1) AS initial_acl,
 (SELECT i.privtype::text FROM pg_catalog.pg_init_privs i WHERE i.classoid=o.class_oid AND i.objoid=o.object_oid AND i.objsubid=0 LIMIT 1) AS initial_type,
 (SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(e.extname,e.extversion,pg_catalog.pg_get_userbyid(e.extowner)) ORDER BY e.extname),'[]'::jsonb)
  FROM pg_catalog.pg_depend d JOIN pg_catalog.pg_extension e ON e.oid=d.refobjid
  WHERE d.classid=o.class_oid AND d.objid=o.object_oid AND d.objsubid=0 AND d.refclassid='pg_catalog.pg_extension'::regclass AND d.deptype='e') AS extension
 FROM object_base o
), defaults AS MATERIALIZED (
 SELECT a.oid,pg_catalog.pg_get_userbyid(a.defaclrole) AS owner,n.nspname AS schema,a.defaclobjtype::text AS kind,a.defaclacl AS acl
 FROM pg_catalog.pg_default_acl a LEFT JOIN pg_catalog.pg_namespace n ON n.oid=a.defaclnamespace LIMIT 8193
), all_acls AS MATERIALIZED (
 SELECT class_oid,object_oid,'acl'::text AS label,acl FROM objects
 UNION ALL SELECT class_oid,object_oid,'default',default_acl FROM objects
 UNION ALL SELECT class_oid,object_oid,'initial',initial_acl FROM objects
 UNION ALL SELECT 826,oid,'default_row',acl FROM defaults
), guards AS MATERIALIZED (
 SELECT (SELECT count(*) FROM role_rows)<=256 AND (SELECT count(*) FROM objects)<=8192
 AND (SELECT count(*) FROM defaults)<=8192
 AND NOT EXISTS(SELECT 1 FROM objects WHERE initial_count>1 OR pg_catalog.jsonb_array_length(extension)>1 OR pg_catalog.jsonb_array_length(argument_types)>100)
 AND NOT EXISTS(SELECT 1 FROM all_acls WHERE coalesce(pg_catalog.cardinality(acl),0)>64 OR coalesce(pg_catalog.octet_length(acl::text),0)>65536 OR coalesce(pg_catalog.array_ndims(acl),1)<>1)
 AND (SELECT coalesce(sum(pg_catalog.cardinality(acl)),0) FROM all_acls)<=32768 AS ok
), bounded_acls AS MATERIALIZED (
 SELECT a.* FROM all_acls a,guards g WHERE g.ok
), acl_rows AS (
 SELECT a.class_oid,a.object_oid,a.label,
 CASE WHEN a.acl IS NULL THEN NULL ELSE pg_catalog.jsonb_build_object('raw',a.acl::text,'items',
  coalesce((SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
   'grantee',CASE WHEN v.grantee=0 THEN NULL ELSE pg_catalog.pg_get_userbyid(v.grantee) END,
   'grantor',pg_catalog.pg_get_userbyid(v.grantor),'privileges',v.privileges,'grantOptions',v.options) ORDER BY v.ordinality)
   FROM (SELECT u.ordinality,e.grantee,e.grantor,
    pg_catalog.jsonb_agg(e.privilege_type ORDER BY e.privilege_type) AS privileges,
    coalesce(pg_catalog.jsonb_agg(e.privilege_type ORDER BY e.privilege_type) FILTER(WHERE e.is_grantable),'[]'::jsonb) AS options
    FROM pg_catalog.unnest(a.acl) WITH ORDINALITY u(item,ordinality)
    CROSS JOIN LATERAL pg_catalog.aclexplode(ARRAY[u.item]) e
    GROUP BY u.ordinality,e.grantee,e.grantor) v),'[]'::jsonb)) END AS value
 FROM bounded_acls a
), object_rows AS (
 SELECT pg_catalog.jsonb_build_object('classOid',o.class_oid::bigint,'objectOid',o.object_oid::bigint,'identity',o.identity,
 'kind',o.kind,'owner',pg_catalog.pg_get_userbyid(o.owner),
 'acl',(SELECT a.value FROM acl_rows a WHERE a.class_oid=o.class_oid AND a.object_oid=o.object_oid AND a.label='acl'),
 'defaultAcl',(SELECT a.value FROM acl_rows a WHERE a.class_oid=o.class_oid AND a.object_oid=o.object_oid AND a.label='default'),
 'initialAcl',(SELECT a.value FROM acl_rows a WHERE a.class_oid=o.class_oid AND a.object_oid=o.object_oid AND a.label='initial'),
 'initialPrivilegeType',o.initial_type,'extension',o.extension,'columnAclCount',o.columns,
 'argumentTypes',o.argument_types,'argumentModes',o.argument_modes) AS row
 FROM objects o,guards g WHERE g.ok
), default_rows AS (
 SELECT pg_catalog.jsonb_build_object('owner',d.owner,'schema',d.schema,'kind',d.kind,'acl',a.value) AS row
 FROM defaults d JOIN acl_rows a ON a.class_oid=826 AND a.object_oid=d.oid AND a.label='default_row'
), schemas AS MATERIALIZED (
  SELECT n.oid, n.nspowner, n.nspacl,
    pg_catalog.jsonb_build_array('schema', n.nspname) AS identity,
    pg_catalog.jsonb_build_array('schema', n.nspname, pg_catalog.pg_get_userbyid(n.nspowner), n.nspacl::text) AS row
  FROM pg_catalog.pg_namespace n WHERE n.nspname IN ('graphql', 'graphql_public')
    AND coalesce(pg_catalog.cardinality(n.nspacl),0)<=64
    AND coalesce(pg_catalog.octet_length(n.nspacl::text),0)<=65536
    AND (SELECT count(*) FROM pg_catalog.pg_init_privs i WHERE i.classoid='pg_catalog.pg_namespace'::regclass AND i.objoid=n.oid AND i.objsubid=0)<=1
    AND NOT EXISTS(SELECT 1 FROM pg_catalog.pg_init_privs i WHERE i.classoid='pg_catalog.pg_namespace'::regclass AND i.objoid=n.oid AND i.objsubid=0 AND (pg_catalog.cardinality(i.initprivs)>64 OR pg_catalog.octet_length(i.initprivs::text)>65536))
), schema_acls AS (
  SELECT s.oid, 'grants' AS kind, coalesce(s.nspacl, pg_catalog.acldefault('n', s.nspowner)) AS acl FROM schemas s
  UNION ALL SELECT s.oid, 'defaults', pg_catalog.acldefault('n', s.nspowner) FROM schemas s
  UNION ALL SELECT s.oid, 'initial', i.initprivs FROM schemas s JOIN pg_catalog.pg_init_privs i
    ON i.classoid='pg_catalog.pg_namespace'::regclass AND i.objoid=s.oid AND i.objsubid=0
), expanded AS (
  SELECT s.oid, s.kind, coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(g.rolname, a.grantee=0,
    r.rolname, a.privilege_type, a.is_grantable) ORDER BY g.rolname, a.grantee=0,
    r.rolname, a.privilege_type, a.is_grantable) FILTER (WHERE a.grantor IS NOT NULL), '[]'::jsonb) AS grants
  FROM schema_acls s LEFT JOIN LATERAL pg_catalog.aclexplode(s.acl) a ON true
  LEFT JOIN pg_catalog.pg_roles g ON g.oid=a.grantor LEFT JOIN pg_catalog.pg_roles r ON r.oid=a.grantee
  GROUP BY s.oid, s.kind
), schema_rows AS (
  SELECT s.identity, s.row, pg_catalog.acldefault('n',s.nspowner)::text AS defaults,
    (SELECT x.grants FROM expanded x WHERE x.oid=s.oid AND x.kind='grants') AS grants,
    (SELECT x.grants FROM expanded x WHERE x.oid=s.oid AND x.kind='defaults') AS default_grants,
    (SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(i.privtype,i.initprivs::text,x.grants)
      ORDER BY i.privtype), '[]'::jsonb) FROM pg_catalog.pg_init_privs i JOIN expanded x ON x.oid=s.oid AND x.kind='initial'
      WHERE i.classoid='pg_catalog.pg_namespace'::regclass AND i.objoid=s.oid AND i.objsubid=0) AS initial,
    (SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(e.extname,e.extversion,pg_catalog.pg_get_userbyid(e.extowner))
      ORDER BY e.extname), '[]'::jsonb) FROM pg_catalog.pg_depend d JOIN pg_catalog.pg_extension e ON e.oid=d.refobjid
      WHERE d.classid='pg_catalog.pg_namespace'::regclass AND d.objid=s.oid AND d.objsubid=0
      AND d.refclassid='pg_catalog.pg_extension'::regclass AND d.deptype='e') AS extensions
  FROM schemas s
), functions AS (
  SELECT p.*, n.nspname, l.lanname FROM pg_catalog.pg_proc p
  JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace JOIN pg_catalog.pg_language l ON l.oid=p.prolang
  WHERE n.nspname='net' AND (
    (p.proname='http_get' AND pg_catalog.pg_get_function_identity_arguments(p.oid)=
      'url text, params jsonb, headers jsonb, timeout_milliseconds integer') OR
    (p.proname='http_post' AND pg_catalog.pg_get_function_identity_arguments(p.oid)=
      'url text, body jsonb, params jsonb, headers jsonb, timeout_milliseconds integer'))
), function_rows AS (
  SELECT pg_catalog.jsonb_build_array('function',p.nspname,p.proname,pg_catalog.pg_get_function_identity_arguments(p.oid)) AS identity,
    pg_catalog.jsonb_build_array('function',p.nspname,p.proname,pg_catalog.pg_get_function_identity_arguments(p.oid),
      pg_catalog.pg_get_userbyid(p.proowner),p.proacl::text,p.prosecdef,p.proconfig::text) AS row,
    pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_functiondef(p.oid),'UTF8')),'hex') AS definition_sha256,
    pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.prosrc,'UTF8')),'hex') AS body_sha256,
    pg_catalog.jsonb_build_array(p.lanname,pg_catalog.pg_get_function_result(p.oid),p.prokind,p.provolatile,p.proisstrict,
      p.proparallel,p.proleakproof,p.proretset) AS attributes,
    pg_catalog.jsonb_build_object(
      'default_count',p.pronargdefaults,
      'defaults',CASE WHEN p.proargdefaults IS NULL THEN NULL ELSE pg_catalog.jsonb_build_object(
        'bytes',pg_catalog.octet_length(pg_catalog.convert_to(pg_catalog.pg_get_expr(p.proargdefaults,0),'UTF8')),
        'sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(pg_catalog.pg_get_expr(p.proargdefaults,0),'UTF8')),'hex')) END,
      'cost',p.procost::text,'rows',p.prorows::text,
      'support',CASE WHEN p.prosupport=0 THEN NULL ELSE
        (SELECT pg_catalog.jsonb_build_array(n.nspname,s.proname,pg_catalog.pg_get_function_identity_arguments(s.oid))
         FROM pg_catalog.pg_proc s JOIN pg_catalog.pg_namespace n ON n.oid=s.pronamespace WHERE s.oid=p.prosupport) END,
      'binary',CASE WHEN p.probin IS NULL THEN NULL ELSE pg_catalog.jsonb_build_object(
        'bytes',pg_catalog.octet_length(pg_catalog.convert_to(p.probin,'UTF8')),
        'sha256',pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(p.probin,'UTF8')),'hex')) END,
      'fixed_shape',p.provariadic=0 AND p.proallargtypes IS NULL AND p.proargmodes IS NULL
        AND p.protrftypes IS NULL AND p.prosqlbody IS NULL
        AND p.proargnames=CASE p.proname WHEN 'http_get' THEN
          ARRAY['url','params','headers','timeout_milliseconds']::text[] ELSE
          ARRAY['url','body','params','headers','timeout_milliseconds']::text[] END
    ) AS definition_attributes,
    (SELECT pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(n.nspname,t.typname) ORDER BY a.ordinality)
      FROM pg_catalog.unnest(p.proargtypes) WITH ORDINALITY a(oid,ordinality)
      JOIN pg_catalog.pg_type t ON t.oid=a.oid JOIN pg_catalog.pg_namespace n ON n.oid=t.typnamespace) AS types,
    (SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_array(e.extname,e.extversion,pg_catalog.pg_get_userbyid(e.extowner))
      ORDER BY e.extname), '[]'::jsonb) FROM pg_catalog.pg_depend d JOIN pg_catalog.pg_extension e ON e.oid=d.refobjid
      WHERE d.classid='pg_catalog.pg_proc'::regclass AND d.objid=p.oid AND d.objsubid=0
      AND d.refclassid='pg_catalog.pg_extension'::regclass AND d.deptype='e') AS extensions
  FROM functions p
)
SELECT CASE WHEN (SELECT ok FROM guards) AND NOT EXISTS(SELECT 1 FROM object_rows WHERE pg_catalog.octet_length(row::text)>65536)
 THEN pg_catalog.jsonb_build_object('schema','rf1086-restore-metadata-v1',
 'serverVersion',pg_catalog.current_setting('server_version_num')::integer,'database',pg_catalog.current_database(),
 'systemIdentifier',(SELECT system_identifier::text FROM pg_catalog.pg_control_system()),
 'roles',(SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) ORDER BY oid),'[]'::jsonb) FROM role_rows r),
 'objects',(SELECT coalesce(pg_catalog.jsonb_agg(row ORDER BY row->'identity'),'[]'::jsonb) FROM object_rows),
 'defaultAcls',(SELECT coalesce(pg_catalog.jsonb_agg(row ORDER BY row),'[]'::jsonb) FROM default_rows),
 'selectedSchemas',(SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(s) ORDER BY identity),'[]'::jsonb) FROM schema_rows s),
 'selectedFunctions',(SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(f) ORDER BY identity),'[]'::jsonb) FROM function_rows f))
 ELSE NULL END;
ROLLBACK;
"""

ROLE_ORDER_SQL = br"""BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '3s';
SET LOCAL lock_timeout = '1s';
SELECT coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) ORDER BY oid),'[]'::jsonb)
FROM (SELECT rolname AS name,oid::bigint AS oid,rolsuper AS superuser,rolcanlogin AS login
FROM pg_catalog.pg_roles ORDER BY oid LIMIT 257) r;
ROLLBACK;
"""

SQL_SHA256 = hashlib.sha256(METADATA_SQL).hexdigest()
ROLE_ORDER_SQL_SHA256 = hashlib.sha256(ROLE_ORDER_SQL).hexdigest()
CONFIG = {
    'schema': SCHEMA, 'serverVersion': 170006, 'metadataBytes': MAX_METADATA,
    'rolesBytes': MAX_ROLES_BYTES, 'roles': MAX_ROLES, 'objects': MAX_OBJECTS,
    'aclItems': MAX_ITEMS, 'totalAclItems': MAX_TOTAL_ITEMS, 'rowBytes': MAX_ROW,
    'identifierBytes': 63, 'supplementBytes': MAX_SQL, 'statements': MAX_STATEMENTS,
    'roleStatements': MAX_ROLE_STATEMENTS, 'membershipEdges': MAX_EDGES,
    'scriptBytes': MAX_SCRIPT, 'prefixBytes': 2048,
    'metadataSql': SQL_SHA256, 'roleOrderSql': ROLE_ORDER_SQL_SHA256,
    'consistency': 'checked-M0-M1-final-not-atomic',
    'selection': 'source-before-target-restricted-per-operation-identity',
    'sourceOids': 'archive-only-never-target-assignment',
    'aclAttribution': 'direct-id-or-omitted-extension-semantic-v1',
    'unsupportedAclTargets': 'whole-family-or-plain-in-arity-disjoint-v1',
}
CONFIG_SHA256 = hashlib.sha256(canonical(CONFIG)).hexdigest()


@dataclass(frozen=True, repr=False)
class ACLTarget:
    exact: Object | None = None
    unmodeled: bool = False


def _statement_copy(statement, budget, first=None):
    return Statement(statement.raw, statement.tokens,
        statement.first if first is None else first, statement.end,
        statement.start, statement.stop, budget)


def _unsupported_target(statement, matches, kind, ns, n, roles, budget):
    """Bound one unsupported target, without claiming its signature/overload."""
    s = _statement_copy(statement, budget)
    domain = DOMAINS['f' if kind in (b'FUNCTION', b'PROCEDURE') else
                     'S' if kind == b'SEQUENCE' else 'r']
    grant, options, _ = _operation_prefix(s, domain)
    s.need(kind)
    require(s.name() == (ns, n), 'suffix_profile')
    if kind in (b'FUNCTION', b'PROCEDURE'):
        s.group(nonempty=False)
    owners = set()
    for obj in matches:
        budget.check()
        require(not _supported(obj), 'suffix_profile')
        owners.add(obj.owner)
    # This requires immediate TO/FROM and consumes the entire closed ending.
    _operation_ending(s, grant=grant, options=options, roles=roles, owners=owners)
    budget.check()


def _plain_in(obj):
    return obj.argument_modes in (None, ('i',) * len(obj.argument_types))


def _argument_group_span(s):
    """Original interior and structural arity, without interpreting types."""
    first = s.at
    _, _, start = s.peek()
    s.group(nonempty=False)
    closing = s.at - lexical.RECORD.size
    while True:
        s.budget.check()
        kind, stop, end = lexical.RECORD.unpack_from(s.tokens, closing)
        if kind not in (lexical.SPACE, lexical.LINE_COMMENT, lexical.BLOCK_COMMENT):
            break
        closing -= lexical.RECORD.size
    require(kind == lexical.PUNCT and end-stop == 1 and s.raw[stop:end] == b')', 'suffix_profile')
    require(0 <= stop-start <= MAX_ROW, 'limit')
    cursor = _statement_copy(s, s.budget, first)
    cursor.need(b'(')
    count, present = 0, False
    while cursor.at < closing:
        s.budget.check()
        if cursor.take(b','):
            require(present, 'suffix_profile')
            count += 1; present = False
        elif cursor.is_(b'('):
            cursor.group(nonempty=False); present = True
        else:
            cursor.advance(); present = True
    require(cursor.at == closing and (present or count == 0), 'suffix_profile')
    s.budget.check()
    return start, stop, count + int(present)


def _canonical_group_equal(raw, start, stop, identity, budget):
    budget.check()
    require(len(identity) <= MAX_ROW, 'limit')
    expected = identity.encode('utf8')
    budget.check()
    require(len(expected) <= MAX_ROW, 'limit')
    if stop-start != len(expected):
        budget.check()
        return False
    actual, canonical_group = memoryview(raw), memoryview(expected)
    for offset in range(0, len(expected), 4096):
        budget.check()
        end = min(offset + 4096, len(expected))
        equal = actual[start+offset:start+end] == canonical_group[offset:end]
        budget.check()
        if not equal:
            return False
    budget.check()
    return True


def _arity_disjoint_target(statement, matches, ns, n, roles, budget):
    """Exclude supported arities; equal source text never selects an overload."""
    budget.check()
    s = _statement_copy(statement, budget)
    grant, options, _ = _operation_prefix(s, DOMAINS['f'])
    s.need(b'FUNCTION')
    require(s.name() == (ns, n), 'suffix_profile')
    start, stop, count = _argument_group_span(s)
    require(s.is_(b'TO' if grant else b'FROM'), 'suffix_profile')
    arity = None
    for obj in matches:
        budget.check()
        if obj.kind != 'f' or _supported(obj) or not _plain_in(obj):
            continue
        if _canonical_group_equal(s.raw, start, stop, obj.identity[3], budget):
            require(arity is None and count == len(obj.argument_types), 'suffix_profile')
            arity = count
    require(arity is not None, 'suffix_profile')
    owners = set()
    for obj in matches:
        budget.check()
        if len(obj.argument_types) != arity:
            continue
        require(_plain_in(obj) and not _supported(obj), 'suffix_profile')
        if obj.kind != 'p':
            require(obj.kind in ('f', 'a', 'w'), 'suffix_profile')
            owners.add(obj.owner)
    require(owners, 'suffix_profile')
    _operation_ending(s, grant=grant, options=options, roles=roles, owners=owners)
    budget.check()


def _target_candidates(statement, candidates, budget, *, roles):
    """Locate only exposed typed ON targets; never substring/comment matching."""
    s = _statement_copy(statement, budget)
    if not (s.take(b'GRANT') or s.take(b'REVOKE')):
        return None
    if s.take(b'GRANT'):
        s.need(b'OPTION', b'FOR')
    while not s.take(b'ON'):
        require(not s.is_(b';'), 'suffix_profile')
        if s.is_(b'('):
            s.group()
        else:
            s.advance()
    at = s.at
    kind = s.ident().upper()
    if kind not in (b'TABLE', b'SEQUENCE', b'FUNCTION', b'PROCEDURE'):
        return ACLTarget()
    ns, n = s.name()
    require(ns is not None, 'suffix_profile')
    matches = candidates.get(('function' if kind in (b'FUNCTION', b'PROCEDURE') else 'relation', ns, n), ())
    require(matches, 'source_binding')
    found = []
    for obj in matches:
        budget.check()
        cursor = _statement_copy(statement, budget, at)
        try:
            _target(cursor, obj)
            require(cursor.is_(b'TO') or cursor.is_(b'FROM'), 'suffix_profile')
        except (MetadataUnavailable, ledger.Unavailable) as error:
            if error.reason not in ('suffix_profile', 'role'):
                raise
            continue
        found.append(obj)
    if not found and all(not _supported(obj) for obj in matches):
        _unsupported_target(statement, matches, kind, ns, n, roles, budget)
        return ACLTarget(unmodeled=True)
    if not found and kind == b'FUNCTION':
        _arity_disjoint_target(statement, matches, ns, n, roles, budget)
        return ACLTarget(unmodeled=True)
    require(len(found) == 1, 'suffix_profile')
    if not _supported(found[0]):
        _unsupported_target(statement, matches, kind, ns, n, roles, budget)
    budget.check()
    return ACLTarget(exact=found[0], unmodeled=not _supported(found[0]))


@closed
def restore_metadata_index(script, archive, restore_index, source, *, deadline):
    """Adapt one completed walk, examining every ACL occurrence exactly once.

    Static direct-writer attribution does not exclude trigger/extension effects.
    Runtime prefix, immediate metadata and final original fingerprints still gate.
    """
    budget = Budget(deadline)
    require(type(restore_index) is ledger.RestoreIndex and type(source) is Metadata, 'archive_profile')
    require(type(script) is bytes and len(script) <= MAX_SCRIPT, 'limit')
    core = restore_index.core
    require(core.script == binding(script, budget), 'archive_profile')
    occurrences, regions = restore_index.occurrences, restore_index.regions
    require(type(occurrences) is bytes and len(occurrences) <= ledger.MAX_OCCURRENCE_BYTES
            and len(occurrences) % ledger.OCCURRENCE.size == 0, 'archive_profile')
    require(type(regions) is bytes and len(regions) <= ledger.MAX_REGION_BYTES
            and len(regions) % ledger.REGION.size == 0, 'archive_profile')
    require(core.indexes['occurrences'] == binding(occurrences, budget)
            and core.indexes['regions'] == binding(regions, budget), 'archive_profile')
    hook = restore_index.pre_acl['cut']
    integer(hook, 1, len(script)-1)
    by_dump, archive_pairs = {}, set()
    for entry in archive.entries:
        budget.check()
        by_dump[entry.dump_id] = entry
        archive_pairs.add((entry.class_oid, entry.object_oid))
    by_pair, by_extension, emitted, full_occurrences = {}, {}, {}, []
    for at in range(0, len(occurrences), ledger.OCCURRENCE.size):
        budget.check()
        did, pass_, role, start, definition, stop = ledger.OCCURRENCE.unpack_from(occurrences, at)
        require(did in by_dump and 0 <= start <= definition <= stop <= len(script), 'archive_profile')
        require(stop <= hook if pass_ == ledger.PASSES['MAIN'] else start >= hook, 'archive_profile')
        entry = by_dump[did]; full_occurrences.append((entry, pass_, role, start, definition, stop))
        emitted.setdefault(did, []).append((pass_, stop))
        if pass_ == ledger.PASSES['MAIN'] and role == ledger.ROLES['schema']:
            if entry.description in (b'TABLE', b'SEQUENCE', b'VIEW', b'MATERIALIZED VIEW', b'FUNCTION', b'PROCEDURE'):
                key = (entry.class_oid, entry.object_oid)
                require(key not in by_pair, 'archive_profile'); by_pair[key] = (entry, stop)
            if entry.description == b'EXTENSION':
                require(entry.tag not in by_extension, 'archive_profile'); by_extension[entry.tag] = (entry, stop)
    selected = {s['kind']: s for s in core.selected}
    require(set(selected) == {'graphql_schema', 'graphql_public_schema', 'pg_net_extension'}, 'archive_profile')
    cuts = {'Is': max(selected['graphql_schema']['cut'], selected['graphql_public_schema']['cut']),
            'In': selected['pg_net_extension']['cut']}
    require(all(type(x) is int and 0 < x < hook for x in cuts.values()), 'archive_profile')
    records, targets, lifecycles, omitted = {}, {}, {}, set()
    for obj in source.objects:
        budget.check()
        targets.setdefault((obj.identity[0], obj.identity[1].encode(), obj.identity[2].encode()), []).append(obj)
        found = by_pair.get((obj.class_oid, obj.object_oid))
        if found is None and obj.extension:
            require(len(obj.extension) == 1
                    and (obj.class_oid, obj.object_oid) not in archive_pairs, 'archive_profile')
            found = by_extension.get(obj.extension[0][0].encode())
            require(found is not None and found[0].owner in
                    (None, b'', obj.extension[0][2].encode()), 'archive_profile')
            omitted.add(obj.identity)
        if found is None:
            continue
        entry, stop = found
        records[obj.identity] = {'classOid': obj.class_oid, 'objectOid': obj.object_oid,
            'identity': list(obj.identity), 'owner': obj.owner, 'kind': obj.kind,
            'createdEnd': stop, 'aclSpans': [], 'laterMutation': False}
        lifecycles[obj.identity] = entry.dump_id
    dependencies_to_objects = {}
    pairs_to_objects = {}
    for identity, did in lifecycles.items():
        budget.check()
        dependencies_to_objects.setdefault(did, []).append(identity)
        row = records[identity]
        pairs_to_objects[(row['classOid'], row['objectOid'])] = identity
    defaults, statement_count, unknown_later = [], 0, False
    roles = {r.name for r in source.roles}
    for entry, pass_, role, start, definition, stop in full_occurrences:
        budget.check()
        if entry.description not in (b'ACL', b'DEFAULT ACL'):
            if pass_ != ledger.PASSES['MAIN']:
                # Direct dependencies plus source class/object identity. DDL
                # expressions are not treated as provably effect-free.
                if not entry.dependencies:
                    unknown_later = True
                for dependency in entry.dependencies:
                    budget.check()
                    if dependency not in dependencies_to_objects:
                        unknown_later = True
                    for identity in dependencies_to_objects.get(dependency, ()):
                        budget.check(); records[identity]['laterMutation'] = True
                identity = pairs_to_objects.get((entry.class_oid, entry.object_oid))
                if identity is not None:
                    records[identity]['laterMutation'] = True
            continue
        require(pass_ == ledger.PASSES['ACL'] and entry.definition is not None, 'archive_profile')
        require(len(entry.definition) <= MAX_ROLES_BYTES
                and script[definition:definition+len(entry.definition)] == entry.definition, 'archive_profile')
        authorized = False
        auth_targets = set()
        entry_targets, semantic_targets = set(), set()
        for s in _statements(entry.definition, budget):
            statement_count += 1; require(statement_count <= MAX_ROLE_STATEMENTS, 'limit')
            a, b = definition+s.start, definition+s.stop
            require(hook <= a < b <= stop, 'archive_profile')
            if entry.description == b'DEFAULT ACL':
                require(len(defaults) < MAX_STATEMENTS, 'limit'); defaults.append([a, b]); continue
            if s.is_(b'SET'):
                s.need(b'SET', b'SESSION', b'AUTHORIZATION'); _sname(s); s.finish()
                require(not authorized, 'suffix_profile'); authorized = True; continue
            if s.is_(b'RESET'):
                s.need(b'RESET', b'SESSION', b'AUTHORIZATION'); s.finish()
                require(authorized, 'suffix_profile'); authorized = False; continue
            found = _target_candidates(s, targets, budget, roles=roles)
            require(found is not None, 'suffix_profile')
            entry_targets.add(None if found.exact is None else found.exact.identity)
            if found.exact is not None:
                obj = found.exact
                row = records.get(obj.identity)
                if row is None:
                    require(obj.acl is None or not _supported(obj), 'archive_profile'); continue
                if obj.identity in omitted:
                    if found.unmodeled:
                        continue
                    # The opaque member dump ID is not the extension lifecycle.
                    require(entry.class_oid == entry.object_oid == 0
                            and entry.namespace == obj.identity[1].encode()
                            and entry.owner == obj.owner.encode()
                            and len(entry.dependencies) == 1
                            and entry.dependencies[0] > 0
                            and entry.dependencies[0] not in by_dump, 'archive_profile')
                    _operation(_statement_copy(s, budget), obj=obj, roles=roles)
                    semantic_targets.add(obj.identity)
                else:
                    # Direct objects retain their exact numeric binding.
                    require(lifecycles[obj.identity] in entry.dependencies, 'archive_profile')
                    if found.unmodeled:
                        continue
                require(len(row['aclSpans']) < MAX_STATEMENTS, 'limit')
                row['aclSpans'].append([a,b])
                if authorized:
                    auth_targets.add(obj.identity)
        require(not authorized, 'suffix_profile')
        if semantic_targets:
            require(len(semantic_targets) == 1 and entry_targets == semantic_targets, 'archive_profile')
        for identity in auth_targets:
            records[identity]['laterMutation'] = True
    if unknown_later:
        for identity in omitted:
            budget.check()
            records[identity]['laterMutation'] = True
    result = {'schema': 'rf1086-repair-index-v1', 'script': core.script.copy(), 'preAcl': hook,
              'cuts': cuts, 'objects': list(records.values()), 'defaultAclSpans': defaults}
    require(len(canonical(result)) <= MAX_METADATA, 'limit')
    budget.check()
    return result
