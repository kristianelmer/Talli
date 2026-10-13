"""Bounded PG17.6 emission attribution. No runtime/session or causal proof.

Source: postgres/postgres 7885b94dd81b98bbab9ed878680d156df7bf857f,
pg_backup_archiver.c, pg_backup_custom.c and pg_dump.c. The raw metadata,
identifier and lexical helpers retain their separately reviewed reject domains.
Only the production wrapper can project a three-selection production receipt.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import re
import struct
import time

import rf1086_raw_toc as raw_toc
import rf1086_sql_identifiers as identifiers
import rf1086_sql_lexical as lexical

SCHEMA = 'rf1086-sql-ledger-v2'
PROFILE = 'pg176-fifo-custom116-utf8-on-v1'
SOURCE_COMMIT = '7885b94dd81b98bbab9ed878680d156df7bf857f'
FIFO_PREDICATE = 'test -p /proc/self/fd/0'
MODULES = ('rf1086_raw_toc.py', 'rf1086_sql_identifiers.py',
           'rf1086_sql_lexical.py', 'rf1086_sql_ledger.py')
TOTAL_SECONDS = 20
PHASE_SECONDS = 5
MAX_RECEIPT = 4096
MAX_REGIONS = 262144
MAX_REGION_BYTES = 4 * 1024**2
MAX_OCCURRENCES = 16384
MAX_OCCURRENCE_BYTES = 1024**2
DECISION = struct.Struct('<IBBBB')
REGION = struct.Struct('<BIII')
OCCURRENCE = struct.Struct('<IBBIII')
PASSES = {'SPECIAL': 0, 'MAIN': 1, 'ACL': 2, 'POST_ACL': 3}
NO_OUTPUT = {'emitted': 0, 'special': 1, 'empty': 2, 'partition_root': 3, 'legacy_init': 4}
REGIONS = {'global': 1, 'clean': 2, 'prelude': 3, 'header': 4, 'definition': 5,
           'owner': 6, 'partition_am': 7, 'copy_command': 8, 'copy_data': 9,
           'copy_end': 10, 'reconnect': 11, 'footer': 12}
ROLES = {'schema': 1, 'data_callback': 2, 'data_definition': 3}
SELECTORS = (('graphql_schema', b'SCHEMA', b'graphql'),
             ('graphql_public_schema', b'SCHEMA', b'graphql_public'),
             ('pg_net_extension', b'EXTENSION', b'pg_net'))
SPECIAL = {b'ENCODING': b"SET client_encoding = 'UTF8';\n",
           b'STDSTRINGS': b"SET standard_conforming_strings = 'on';\n",
           b'SEARCHPATH': b"SELECT pg_catalog.set_config('search_path', '', false);\n"}
SUPPORTED = (
    b'DATABASE', b'DATABASE PROPERTIES', b'SCHEMA', b'EXTENSION', b'FUNCTION',
    b'PROCEDURE', b'TYPE', b'DOMAIN', b'SHELL TYPE', b'TABLE', b'TABLE DATA',
    b'TABLE ATTACH', b'DEFAULT', b'SEQUENCE', b'SEQUENCE OWNED BY', b'SEQUENCE SET',
    b'VIEW', b'MATERIALIZED VIEW', b'MATERIALIZED VIEW DATA', b'INDEX', b'INDEX ATTACH',
    b'CONSTRAINT', b'FK CONSTRAINT', b'CHECK CONSTRAINT', b'TRIGGER', b'EVENT TRIGGER',
    b'RULE', b'POLICY', b'ROW SECURITY', b'PUBLICATION', b'PUBLICATION TABLE',
    b'PUBLICATION TABLES IN SCHEMA', b'AGGREGATE', b'OPERATOR', b'OPERATOR CLASS',
    b'OPERATOR FAMILY', b'COMMENT', b'SECURITY LABEL', b'ACL', b'DEFAULT ACL')
SIMPLE_OWNERS = frozenset((b'DOMAIN', b'MATERIALIZED VIEW', b'SEQUENCE', b'TABLE',
    b'TYPE', b'VIEW', b'DATABASE', b'SCHEMA', b'EVENT TRIGGER', b'PUBLICATION'))
DECORATED_OWNERS = frozenset((b'AGGREGATE', b'FUNCTION', b'OPERATOR', b'OPERATOR CLASS',
                            b'OPERATOR FAMILY', b'PROCEDURE'))
NO_OWNERS = frozenset((b'CHECK CONSTRAINT', b'CONSTRAINT', b'DATABASE PROPERTIES',
    b'DEFAULT', b'FK CONSTRAINT', b'INDEX', b'RULE', b'TRIGGER', b'ROW SECURITY', b'POLICY'))
STAGES = ('metadata', 'preparation', 'lexical', 'emitter')
REASON_STAGES = {
    'headroom': ('admission',), 'input': ('metadata',), 'metadata': ('metadata',),
    'lexical': ('lexical',), 'emitter': ('emitter',), 'role': ('emitter',),
    'coverage': ('emitter',), 'boundary': ('emitter',), 'summary': ('summary',),
    'binding': STAGES, 'profile': STAGES, 'deadline': STAGES, 'internal': STAGES,
    'limit': (*STAGES, 'summary'),
}
CONFIG = {
    'schema': SCHEMA, 'profile': PROFILE, 'sourceCommit': SOURCE_COMMIT,
    'helperCaps': {name: {key: value for key, value in vars(module).items()
                         if key.startswith('MAX_') and type(value) is int}
                   for name, module in (('raw', raw_toc), ('identifiers', identifiers), ('lexical', lexical))},
    'ledgerCaps': {'receipt': MAX_RECEIPT, 'regions': MAX_REGIONS,
                  'regionBytes': MAX_REGION_BYTES, 'occurrences': MAX_OCCURRENCES,
                  'occurrenceBytes': MAX_OCCURRENCE_BYTES},
    'seconds': {'total': TOTAL_SECONDS, 'phases': dict.fromkeys(STAGES, PHASE_SECONDS)},
    'lexicalLimitRules': lexical.limit_rules(),
    'records': {'decisions': DECISION.format, 'regions': REGION.format, 'occurrences': OCCURRENCE.format},
    'enums': {'passes': PASSES, 'noOutput': NO_OUTPUT, 'regions': REGIONS, 'roles': ROLES},
    'selectors': [v[0] for v in SELECTORS],
    'supportedRoles': [v.decode('ascii') for v in SUPPORTED], 'fifoPredicate': FIFO_PREDICATE,
}


def canonical(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True,
                      separators=(',', ':')).encode('ascii')


def semantic_hash(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class Unavailable(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__('sql_ledger_unavailable')


def require(test, reason='binding'):
    if not test:
        raise Unavailable(reason)


def unavailable(reason, stage, context=None):
    return {'schema': SCHEMA, 'status': 'unavailable', 'reason': reason, 'stage': stage,
            'context': {'limit': None} | (context or dict.fromkeys(('rowIndex', 'dumpId', 'descriptor', 'offset')))}


class Budget:
    """Four shared phases; helpers never get a fresh allowance per row."""
    def __init__(self, deadline):
        require(type(deadline) in (int, float) and math.isfinite(deadline), 'deadline')
        self.until = min(deadline, time.monotonic() + TOTAL_SECONDS)
        self.deadline = self.until
        self.stage = 'admission'
        self.phase_index = -1
        self.context = dict.fromkeys(('rowIndex', 'dumpId', 'descriptor', 'offset'))

    def phase(self, name):
        require(STAGES.index(name) == self.phase_index + 1, 'internal')
        self.phase_index += 1
        self.stage = name
        self.context = dict.fromkeys(self.context)
        self.deadline = min(self.until, time.monotonic() + PHASE_SECONDS)
        self.check()

    def check(self):
        require(time.monotonic() < self.deadline, 'deadline')

    def digest(self, value):
        h = hashlib.sha256()
        for pos in range(0, len(value), 65536):
            self.check()
            h.update(memoryview(value)[pos:pos+65536])
        self.check()
        return {'bytes': len(value), 'sha256': h.hexdigest()}

    def locate(self, index, entry, offset=None):
        self.context = {'rowIndex': index, 'dumpId': entry.dump_id,
                        'descriptor': raw_toc.DESCRIPTOR_LABELS.get(entry.description, 'unknown'),
                        'offset': offset}


def identifier(value, budget):
    return identifiers.identifier(value, deadline=budget.deadline)


def qualified(entry, budget):
    # _getObjectDescription omits both null and empty namespace. Other source
    # call sites use fmtQualifiedId, whose profile rejects empty components.
    return identifiers.qualified(entry.namespace or None, entry.tag, deadline=budget.deadline)


def selected_semantics(catalog, selectors=SELECTORS):
    result = {}
    for kind, descriptor, name in selectors:
        text = name.decode('ascii')
        if descriptor == b'SCHEMA':
            rows = [row for row in catalog['schemas'] if row['identity'] == ['schema', text]]
            require(len(rows) == 1 and type(rows[0]['row']) is list
                    and len(rows[0]['row']) >= 3 and rows[0]['row'][:2] == ['schema', text])
            value = rows[0]['row'][2]
            domain = 'schema'
        else:
            rows = [row for row in catalog['extensions'] if row[0] == text]
            require(len(rows) == 1 and len(rows[0]) == 4)
            value = rows[0][2]
            domain = 'extension'
        require(type(value) is str and 0 < len(value.encode('utf-8')) <= identifiers.MAX_COMPONENT)
        result[kind] = (value.encode('utf-8'), semantic_hash([domain, text, value]))
    return result


@dataclass(frozen=True)
class Prepared:
    decisions: bytes
    schedule: tuple
    passes: dict
    zero_rows: int
    meta: tuple
    copies: tuple
    key: bytes
    selected: dict
    semantics: dict
    reconnects: int


def restore_pass(entry):
    desc = entry.description
    if desc in SPECIAL:
        return 'SPECIAL'
    if desc in (b'ACL', b'ACL LANGUAGE', b'DEFAULT ACL'):
        return 'ACL'
    if desc in (b'EVENT TRIGGER', b'MATERIALIZED VIEW DATA') or (
            desc == b'COMMENT' and entry.tag.startswith(b'EVENT TRIGGER ')):
        return 'POST_ACL'
    return 'MAIN'


def prepare(script, archive, selectors, catalog, budget):
    budget.phase('preparation')
    require(type(selectors) is tuple and selectors in (SELECTORS, SELECTORS[:2]), 'profile')
    require(0 < len(archive.database) <= 128, 'profile')
    connect = identifiers.simple_connect(archive.database, deadline=budget.deadline)
    opening = b'--\n-- PostgreSQL database dump\n--\n\n\\restrict '
    require(script.startswith(opening), 'profile')
    key = script[len(opening):len(opening)+63]
    require(re.fullmatch(rb'[A-Za-z0-9]{63}', key) is not None
            and script[len(opening)+63:len(opening)+65] == b'\n\n', 'profile')
    special = {key: [] for key in SPECIAL}
    decisions = bytearray()
    schedules = {key: [] for key in ('MAIN', 'ACL', 'POST_ACL')}
    passes = dict.fromkeys(PASSES, 0)
    selected, zero, databases, reconnects = {}, 0, 0, 0
    semantics = selected_semantics(catalog, selectors)
    section = 1
    for index, entry in enumerate(archive.entries):
        budget.check()
        desc = entry.description
        if entry.section != 1:  # SECTION_NONE inherits the preceding section.
            section = entry.section
        require(section in (1, 2, 3, 4), 'profile')
        phase = restore_pass(entry)
        passes[phase] += 1
        reason, reqs, roles = 0, 3, []
        if desc in SPECIAL:
            special[desc].append(entry)
            require(entry.tag == desc and entry.definition == SPECIAL[desc]
                    and not entry.had_dumper, 'profile')
            reqs, reason = 4, NO_OUTPUT['special']
        else:
            require(desc in SUPPORTED or (desc == b'<Init>' and entry.tag == b'Max OID'), 'profile')
            require(not (desc in (b'ACL', b'COMMENT', b'SECURITY LABEL')
                         and entry.tag.startswith(b'LARGE OBJECT')), 'profile')
            if desc in (b'DATABASE', b'DATABASE PROPERTIES'):
                require(entry.tag == archive.database and not entry.had_dumper, 'profile')
                databases += desc == b'DATABASE'
                reconnects += 1
                reqs = 1
            else:
                if not entry.had_dumper:
                    reqs = 2 if desc == b'SEQUENCE SET' else 1
                if not entry.definition or entry.definition.startswith(b'-- load via partition root '):
                    reqs &= ~1
                    reason = NO_OUTPUT['partition_root'] if entry.definition else NO_OUTPUT['empty']
                if desc == b'<Init>':
                    reqs, reason = 0, NO_OUTPUT['legacy_init']
            if reqs & 1:
                roles.append(ROLES['schema'])
            if reqs & 2 and entry.had_dumper:
                require(desc == b'TABLE DATA' and entry.copy, 'profile')
                roles.append(ROLES['data_callback'])
            elif reqs & 2 and not reqs & 1:
                roles.append(ROLES['data_definition'])
            if roles:
                reason = NO_OUTPUT['emitted']
            for role in roles:
                schedules[phase].append((index, entry, role))
        zero += not roles
        decisions.extend(DECISION.pack(entry.dump_id, PASSES[phase], reqs, len(roles), reason))
        for kind, selected_desc, selected_tag in selectors:
            if (desc, entry.tag) == (selected_desc, selected_tag):
                require(kind not in selected and roles == [ROLES['schema']]
                        and entry.namespace is None and entry.class_oid > 0 and entry.object_oid > 0, 'profile')
                if desc == b'SCHEMA':
                    require(entry.owner == semantics[kind][0] and entry.drop == b'DROP SCHEMA '+identifier(entry.tag, budget)+b';\n', 'profile')
                    expected = b'CREATE SCHEMA '+identifier(entry.tag, budget)+b';\n'
                else:
                    expected = (b'CREATE EXTENSION IF NOT EXISTS '+identifier(entry.tag, budget)
                                +b' WITH SCHEMA '+identifier(semantics[kind][0], budget)+b';\n')
                require(entry.definition == expected, 'profile')
                selected[kind] = entry.dump_id
    require(all(len(rows) == 1 for rows in special.values()) and databases == 1
            and 1 <= reconnects <= 2 and len(selected) == len(selectors), 'profile')
    schedule = tuple(item for phase in ('MAIN', 'ACL', 'POST_ACL') for item in schedules[phase])
    require(len(schedule) <= MAX_OCCURRENCES, 'limit')
    copies = tuple(entry.copy for _, entry, role in schedule if role == ROLES['data_callback'])
    require(sum(map(len, copies)) <= lexical.MAX_BINDINGS, 'limit')
    meta = [b'\\restrict '+key+b'\n']
    for _, entry, role in schedule:
        if role == ROLES['schema'] and entry.description in (b'DATABASE', b'DATABASE PROPERTIES'):
            meta.extend((b'\\unrestrict '+key+b'\n', connect, b'\\restrict '+key+b'\n'))
    meta.append(b'\\unrestrict '+key+b'\n')
    budget.check()
    return Prepared(bytes(decisions), schedule, passes, zero, tuple(meta), copies, key,
                    selected, semantics, reconnects)


@dataclass(frozen=True)
class CoreEvidence:
    """Internal mechanical result, deliberately not a production receipt."""
    counts: dict
    indexes: dict
    selected: tuple
    script: dict


FIXED = (b'SET statement_timeout = 0;\nSET lock_timeout = 0;\n'
         b'SET idle_in_transaction_session_timeout = 0;\nSET transaction_timeout = 0;\n'
         b"SET client_encoding = 'UTF8';\nSET standard_conforming_strings = on;\n"
         + SPECIAL[b'SEARCHPATH'] + b'SET check_function_bodies = false;\n'
         b'SET xmloption = content;\nSET client_min_messages = warning;\nSET row_security = off;\n\n')


class Emitter:
    def __init__(self, script, archive, prepared, scan, budget):
        self.raw, self.archive, self.prepared, self.scan, self.budget = script, archive, prepared, scan, budget
        self.pos = self.leaf = self.token = self.statements = 0
        self.regions, self.occurrences = bytearray(), bytearray()
        self.tablespace = self.tableam = None
        self.dump_id = 0
        self.selected = []

    def statement_spans(self, end, allow):
        while self.leaf < len(self.scan.leaves):
            self.budget.check()
            kind, start, stop = lexical.RECORD.unpack_from(self.scan.leaves, self.leaf)
            if start >= end:
                break
            require(kind == lexical.TRIVIA or stop <= end, 'coverage')
            if kind == lexical.SQL:
                require(allow == 'sql', 'coverage')
                token_start = self.token
                while self.token < len(self.scan.tokens):
                    self.budget.check()
                    _, a, b = lexical.RECORD.unpack_from(self.scan.tokens, self.token)
                    if a >= stop:
                        break
                    self.token += lexical.RECORD.size
                    if b <= start:
                        token_start = self.token
                self.statements += 1
                yield Statement(self.raw, self.scan.tokens, token_start, self.token, start, stop, self.budget)
            elif kind != lexical.TRIVIA:
                require(allow == {lexical.META: 'meta', lexical.COPY_DATA: 'copy_data', lexical.COPY_END: 'copy_end'}[kind], 'coverage')
            if stop > end:
                break  # Only trivia may cross an independently derived region.
            self.leaf += lexical.RECORD.size

    def region(self, end, name, allow='sql', validate=None):
        self.budget.check()
        require(self.pos <= end <= len(self.raw), 'coverage')
        if self.pos == end:
            return
        require(len(self.regions)//REGION.size < MAX_REGIONS
                and len(self.regions)+REGION.size <= MAX_REGION_BYTES, 'limit')
        statements = self.statement_spans(end, allow)
        if validate is None:
            for _ in statements:
                pass
        else:
            validate(statements)
        self.regions.extend(REGION.pack(REGIONS[name], self.pos, end, self.dump_id))
        self.pos = end
        self.budget.context['offset'] = self.pos

    def exact(self, expected, name, allow='sql', validate=None):
        end = self.pos+len(expected)
        require(end <= len(self.raw), 'emitter')
        for start in range(0, len(expected), 65536):
            self.budget.check()
            require(memoryview(self.raw)[self.pos+start:min(end, self.pos+start+65536)]
                    == memoryview(expected)[start:start+65536], 'emitter')
        self.region(end, name, allow, validate)

    def timestamp(self, label, name):
        prefix = b'-- '+label+b' '
        if not self.raw.startswith(prefix, self.pos):
            return
        # Bounded inert source-compatible strftime text; not a time equality claim.
        end = self.raw.find(b'\n', self.pos, self.pos+len(prefix)+64)
        require(end >= 0 and self.raw[end:end+2] == b'\n\n', 'emitter')
        payload = self.raw[self.pos+len(prefix):end]
        found = re.fullmatch(rb'([0-9]{4})-([0-9]{2})-([0-9]{2}) ([0-9]{2}):([0-9]{2}):([0-9]{2}) [\x20-\x7e]{0,43}', payload)
        require(found is not None and 1 <= int(found[1]) <= 9999 and 1 <= int(found[2]) <= 12
                and 1 <= int(found[3]) <= 31 and int(found[4]) <= 23
                and int(found[5]) <= 59 and int(found[6]) <= 60 and len(payload) <= 63, 'emitter')
        self.region(end+2, name, 'trivia')

    def fixed(self, name='global'):
        self.exact(FIXED, name)

    def header(self, entry, role):
        parts = [b'--\n', f'-- TOC entry {entry.dump_id} (class {entry.class_oid} OID {entry.object_oid})\n'.encode()]
        if entry.dependencies:
            parts.append(b'-- Dependencies:'+b''.join(b' '+str(dep).encode() for dep in entry.dependencies)+b'\n')
        parts.extend((b'-- ', b'Data for ' if role == ROLES['data_callback'] else b'',
                      b'Name: ', raw_toc.sanitize(entry.tag), b'; Type: ', entry.description,
                      b'; Schema: ', raw_toc.sanitize(entry.namespace, True),
                      b'; Owner: ', raw_toc.sanitize(entry.owner, True)))
        if entry.tablespace:
            parts.extend((b'; Tablespace: ', raw_toc.sanitize(entry.tablespace)))
        parts.append(f'\n-- Data Pos: {entry.offset}\n--\n\n'.encode())
        self.exact(b''.join(parts), 'header', 'trivia')

    def owner(self, entry):
        if not entry.owner or not entry.drop:
            return
        desc = entry.description
        if desc in SIMPLE_OWNERS:
            target = desc+b' '+qualified(entry, self.budget)
        elif desc in DECORATED_OWNERS:
            require(entry.drop.startswith(b'DROP '+desc+b' '), 'role')
            target = entry.drop[5:].rstrip(b';\n')
        else:
            require(desc in NO_OWNERS, 'role')
            return
        expected = b'ALTER '+target+b' OWNER TO '+identifier(entry.owner, self.budget)+b';\n\n'
        def validate(statements):
            statement = next(statements, None)
            require(statement is not None and next(statements, None) is None, 'role')
            statement.owner(desc, entry.owner)
        self.exact(expected, 'owner', validate=validate)

    def occurrence(self, index, entry, role):
        self.budget.locate(index, entry, self.pos)
        self.dump_id = entry.dump_id
        start = self.pos
        if entry.tablespace is not None and entry.tablespace != self.tablespace:
            value = identifier(entry.tablespace, self.budget) if entry.tablespace else b"''"
            self.exact(b'SET default_tablespace = '+value+b';\n\n', 'prelude')
            self.tablespace = entry.tablespace
        if entry.relkind != ord('p') and entry.tableam is not None and entry.tableam != self.tableam:
            self.exact(b'SET default_table_access_method = '+identifier(entry.tableam, self.budget)+b';\n\n', 'prelude')
            self.tableam = entry.tableam
        self.header(entry, role)
        definition_start = self.pos
        if entry.definition:
            self.exact(entry.definition+b'\n\n', 'definition',
                       validate=lambda statements: validate_definition(entry, statements, self.budget))
        else:
            require(entry.description == b'TABLE DATA', 'role')
        self.owner(entry)
        if entry.relkind == ord('p') and entry.tableam is not None:
            self.exact(b'ALTER TABLE '+qualified(entry, self.budget)+b' SET ACCESS METHOD '
                       +identifier(entry.tableam, self.budget)+b';\n\n', 'partition_am')
        if role == ROLES['data_callback']:
            self.exact(entry.copy, 'copy_command')
            require(self.leaf < len(self.scan.leaves), 'coverage')
            kind, a, b = lexical.RECORD.unpack_from(self.scan.leaves, self.leaf)
            require(kind == lexical.COPY_DATA and a == self.pos, 'coverage')
            if a == b:
                self.leaf += lexical.RECORD.size
            else:
                self.region(b, 'copy_data', 'copy_data')
            self.exact(b'\\.\n', 'copy_end', 'copy_end')
            self.exact(b'\n\n', 'copy_end', 'trivia')
        if role == ROLES['schema'] and entry.description in (b'DATABASE', b'DATABASE PROPERTIES'):
            self.exact(b'\\unrestrict '+self.prepared.key+b'\n', 'reconnect', 'meta')
            self.exact(identifiers.simple_connect(entry.tag, deadline=self.budget.deadline), 'reconnect', 'meta')
            self.exact(b'\\restrict '+self.prepared.key+b'\n\n', 'reconnect', 'meta')
            self.fixed('reconnect')
            self.tablespace = self.tableam = None
        require(len(self.occurrences)+OCCURRENCE.size <= MAX_OCCURRENCE_BYTES, 'limit')
        occurrence = len(self.occurrences)//OCCURRENCE.size
        self.occurrences.extend(OCCURRENCE.pack(entry.dump_id, PASSES[restore_pass(entry)], role,
                                               start, definition_start, self.pos))
        for kind, dump_id in self.prepared.selected.items():
            if dump_id == entry.dump_id:
                require(role == ROLES['schema'] and self.raw[self.pos-1:self.pos] == b'\n', 'boundary')
                self.selected.append({'kind': kind, 'dumpId': dump_id, 'classOid': entry.class_oid,
                    'objectOid': entry.object_oid, 'occurrence': occurrence, 'preludeStart': start,
                    'definitionStart': definition_start, 'entryEnd': self.pos, 'cut': self.pos,
                    'nextPreludeStart': self.pos, 'semanticSha256': self.prepared.semantics[kind][1]})

    def run(self):
        self.exact(b'--\n-- PostgreSQL database dump\n--\n\n', 'global', 'trivia')
        self.exact(b'\\restrict '+self.prepared.key+b'\n\n', 'global', 'meta')
        self.exact(b'-- Dumped from database version '+self.archive.remote_version+b'\n'
                   b'-- Dumped by pg_dump version '+self.archive.dump_version+b'\n\n', 'global', 'trivia')
        self.timestamp(b'Started on', 'global')
        self.fixed()
        for entry in reversed(self.archive.entries):
            if entry.description == b'DATABASE':
                expected = b'DROP DATABASE '+identifier(entry.tag, self.budget)+b';\n'
                require(entry.drop == expected, 'role')
                self.exact(b'DROP DATABASE IF EXISTS '+identifier(entry.tag, self.budget)+b';\n', 'clean')
            elif entry.description == b'DATABASE PROPERTIES' and entry.drop:
                self.exact(entry.drop, 'clean', validate=lambda rows: validate_database_cleanup(entry, rows, self.budget))
        for index, entry, role in self.prepared.schedule:
            self.occurrence(index, entry, role)
        self.dump_id = 0
        self.budget.context = dict.fromkeys(self.budget.context)
        self.timestamp(b'Completed on', 'footer')
        self.exact(b'--\n-- PostgreSQL database dump complete\n--\n\n', 'footer', 'trivia')
        self.exact(b'\\unrestrict '+self.prepared.key+b'\n\n', 'footer', 'meta')
        require(self.pos == len(self.raw) and self.leaf == len(self.scan.leaves), 'coverage')
        total = len(self.occurrences)//OCCURRENCE.size
        for value in self.selected:
            require(value['occurrence'] < total-1, 'boundary')
            following = OCCURRENCE.unpack_from(self.occurrences, (value['occurrence']+1)*OCCURRENCE.size)
            require(following[3] == value['cut'], 'boundary')
        receipt = json.loads(self.scan.receipt)
        require(self.statements == receipt['statements'], 'coverage')
        counts = {'rows': len(self.archive.entries), 'specialRows': 3,
            'zeroOccurrenceRows': self.prepared.zero_rows, 'occurrences': total,
            'statements': self.statements, 'copyGroups': receipt['copyGroups'],
            'metaLines': receipt['metaLines'], 'reconnects': self.prepared.reconnects,
            'regions': len(self.regions)//REGION.size, 'passRows': self.prepared.passes}
        indexes = {key: self.budget.digest(value) for key, value in (
            ('decisions', self.prepared.decisions), ('regions', self.regions), ('occurrences', self.occurrences))}
        self.budget.check()
        return CoreEvidence(counts, indexes, tuple(self.selected), receipt['input'])


def verify_core(script, archive, *, selectors, catalog, budget):
    """Caller has consumed the metadata phase. Fixture results stay internal."""
    prepared = prepare(script, archive, selectors, catalog, budget)
    budget.phase('lexical')
    scan = lexical.scan(script, expected_meta=prepared.meta, database=archive.database,
                        copy_commands=prepared.copies, deadline=budget.deadline, profile=lexical.PROFILE)
    budget.phase('emitter')
    return Emitter(script, archive, prepared, scan, budget).run()


class Statement:
    """Cursor over packed tokens for one neutral statement; no token AST/copy."""
    def __init__(self, raw, tokens, first, end, start, stop, budget):
        self.raw, self.tokens, self.at, self.end = raw, tokens, first, end
        self.first = first
        self.start, self.stop, self.budget = start, stop, budget
        self.skip()

    def skip(self):
        while self.at < self.end:
            self.budget.check()
            kind, _, _ = lexical.RECORD.unpack_from(self.tokens, self.at)
            if kind not in (lexical.SPACE, lexical.LINE_COMMENT, lexical.BLOCK_COMMENT):
                break
            self.at += lexical.RECORD.size

    def peek(self):
        self.skip()
        require(self.at < self.end, 'role')
        return lexical.RECORD.unpack_from(self.tokens, self.at)

    def is_(self, value):
        if self.at == self.end:
            return False
        kind, start, end = self.peek()
        if end-start != len(value):
            return False
        token = self.raw[start:end]
        return token.upper() == value if kind == lexical.IDENT else kind == lexical.PUNCT and token == value

    def take(self, value):
        if not self.is_(value):
            return False
        self.at += lexical.RECORD.size
        self.skip()
        return True

    def need(self, *values):
        for value in values:
            require(self.take(value), 'role')

    def advance(self):
        kind, start, end = self.peek()
        self.at += lexical.RECORD.size
        self.skip()
        return kind, start, end

    def ident(self, expected=None):
        kind, start, end = self.advance()
        require(kind in (lexical.IDENT, lexical.QUOTED_IDENT), 'role')
        raw = self.raw[start:end]
        value = raw[1:-1].replace(b'""', b'"') if kind == lexical.QUOTED_IDENT else raw
        if expected is not None:
            require(value == expected, 'role')
        return value

    def name(self, entry=None):
        first = self.ident()
        namespace, name = None, first
        if self.take(b'.'):
            namespace, name = first, self.ident()
        if entry is not None:
            require((namespace, name) == (entry.namespace or None, entry.tag), 'role')
        return namespace, name

    def integer(self):
        negative = self.take(b'-')
        kind, start, end = self.advance()
        require(kind == lexical.NUMBER and end-start <= 20
                and re.fullmatch(rb'[0-9]+', self.raw[start:end]) is not None, 'role')
        value = int(self.raw[start:end])
        return -value if negative else value

    def literal(self):
        kind, start, end = self.advance()
        require(kind in (lexical.STRING, lexical.ESCAPE), 'role')
        return start, end

    def group(self, nonempty=True):
        self.need(b'(')
        depth, count = 1, 0
        while depth:
            self.budget.check()
            require(not self.is_(b';'), 'role')
            if self.take(b'('):
                depth += 1
            elif self.take(b')'):
                depth -= 1
            else:
                self.advance()
            count += depth > 0
        require(not nonempty or count > 0, 'role')

    def interior_until(self, *terminators, nonempty=True):
        """Quoted/body/group interiors cannot masquerade as exposed keywords."""
        count = 0
        while not any(self.is_(value) for value in terminators):
            require(not self.is_(b';'), 'role')
            if self.is_(b'('):
                self.group(False)
            else:
                self.advance()
            count += 1
        require(not nonempty or count > 0, 'role')

    def finish(self):
        self.need(b';')
        require(self.at == self.end, 'role')

    def has_suffix(self, *words):
        """Match exposed final keywords, never text inside comments or literals."""
        at = self.end
        for expected in (b';', *reversed(words)):
            while at > self.first:
                self.budget.check()
                at -= lexical.RECORD.size
                kind, start, end = lexical.RECORD.unpack_from(self.tokens, at)
                if kind not in (lexical.SPACE, lexical.LINE_COMMENT, lexical.BLOCK_COMMENT):
                    break
            else:
                return False
            expected_kind = lexical.PUNCT if expected == b';' else lexical.IDENT
            if kind != expected_kind or end-start != len(expected):
                return False
            if self.raw[start:end].upper() != expected:
                return False
        return True

    def owner(self, desc, owner):
        self.need(b'ALTER', *desc.split())
        self.interior_until(b'OWNER')
        self.need(b'OWNER', b'TO')
        self.ident(owner)
        self.finish()

    def extension_dependency(self, desc):
        self.need(b'ALTER', *desc.split())
        self.interior_until(b'DEPENDS')
        self.need(b'DEPENDS', b'ON', b'EXTENSION')
        self.ident()
        self.finish()


def single(statements):
    value = next(statements, None)
    require(value is not None and next(statements, None) is None, 'role')
    return value


def database_definition(entry, statement):
    statement.need(b'CREATE', b'DATABASE')
    statement.ident(entry.tag)
    statement.need(b'WITH', b'TEMPLATE', b'=')
    statement.ident(b'template0')
    # Source order, with each optional option admitted once. This deliberately
    # excludes old-version/binary-upgrade options and unmodeled option names.
    if statement.take(b'ENCODING'):
        statement.need(b'='); statement.literal()
    statement.need(b'LOCALE_PROVIDER', b'=')
    provider = statement.ident()
    require(provider in (b'libc', b'icu', b'builtin'), 'role')
    options = (b'LOCALE', b'LC_COLLATE', b'LC_CTYPE', b'BUILTIN_LOCALE', b'ICU_LOCALE', b'ICU_RULES', b'TABLESPACE')
    for key in options:
        if statement.take(key):
            statement.need(b'=')
            if key == b'TABLESPACE':
                statement.ident()
            else:
                statement.literal()
    statement.finish()


def database_properties(entry, statements):
    order = -1
    for s in statements:
        s.need(b'ALTER')
        role = s.take(b'ROLE')
        if role:
            s.ident()
            s.need(b'IN', b'DATABASE')
        else:
            s.need(b'DATABASE')
        s.ident(entry.tag)
        if not role and s.take(b'CONNECTION'):
            require(order < 0, 'role'); order = 0
            s.need(b'LIMIT', b'='); s.integer()
        elif not role and s.take(b'IS_TEMPLATE'):
            require(order < 1, 'role'); order = 1
            s.need(b'=', b'TRUE')
        else:
            order = 2
            s.need(b'SET'); s.ident()
            while s.take(b'.'):
                s.ident()
            s.need(b'TO')
            # dump-specific GUC values are literal or comma-separated literals.
            s.literal()
            while s.take(b','):
                s.literal()
        s.finish()


def validate_database_cleanup(entry, statements, budget):
    s = single(statements)
    s.need(b'UPDATE', b'PG_CATALOG', b'.', b'PG_DATABASE', b'SET', b'DATISTEMPLATE',
           b'=', b'FALSE', b'WHERE', b'DATNAME', b'=')
    start, end = s.literal()
    require(s.raw[start:end] == b"'"+entry.tag.replace(b"'", b"''")+b"'", 'role')
    s.finish()


def relation_suffix(s, entry):
    s.need(b'ALTER', b'TABLE', b'ONLY')
    s.name(entry)
    if s.take(b'ALTER'):
        s.need(b'COLUMN'); s.ident()
        if s.take(b'SET'):
            if s.take(b'NOT'):
                s.need(b'NULL')
            elif s.take(b'STATISTICS'):
                s.integer()
            elif s.take(b'STORAGE'):
                require(s.ident().upper() in (b'PLAIN', b'EXTERNAL', b'EXTENDED', b'MAIN'), 'role')
            elif s.take(b'COMPRESSION'):
                require(s.ident() in (b'pglz', b'lz4'), 'role')
            else:
                s.group()
        else:
            raise Unavailable('role')
        result = 0
    elif s.take(b'REPLICA'):
        s.need(b'IDENTITY')
        require(s.take(b'NOTHING') or s.take(b'FULL'), 'role')
        result = 1
    else:
        s.need(b'FORCE', b'ROW', b'LEVEL', b'SECURITY')
        result = 2
    s.finish()
    return result


def function_definition(entry, statements):
    s = next(statements, None)
    require(s is not None, 'role')
    s.need(b'CREATE', entry.description)
    start = s.peek()[1]
    namespace, _ = s.name()
    stop = s.peek()[1]
    target = s.raw[start:stop].rstrip()
    require(namespace == (entry.namespace or None) and entry.drop
            and entry.drop.startswith(b'DROP '+entry.description+b' '+target+b'('), 'role')
    s.group(False)
    if entry.description == b'FUNCTION':
        s.need(b'RETURNS'); s.interior_until(b'LANGUAGE')
    s.need(b'LANGUAGE'); s.ident()
    # Source places attributes/SET clauses before AS. They stay attributed
    # to this CREATE; no unquoted SQL-standard body is admitted.
    while not s.is_(b'AS'):
        if s.take(b'TRANSFORM'):
            s.need(b'FOR', b'TYPE'); s.interior_until(b'AS', b'IMMUTABLE', b'STABLE', b'VOLATILE')
        elif any(s.take(word) for word in (b'IMMUTABLE', b'STABLE', b'VOLATILE', b'STRICT', b'LEAKPROOF', b'WINDOW')):
            pass
        elif s.take(b'CALLED'):
            s.need(b'ON', b'NULL', b'INPUT')
        elif s.take(b'RETURNS'):
            s.need(b'NULL', b'ON', b'NULL', b'INPUT')
        elif s.take(b'SECURITY'):
            require(s.take(b'DEFINER') or s.take(b'INVOKER'), 'role')
        elif s.take(b'PARALLEL'):
            require(any(s.take(word) for word in (b'SAFE', b'RESTRICTED', b'UNSAFE')), 'role')
        elif s.take(b'COST') or s.take(b'ROWS'):
            kind, _, _ = s.advance(); require(kind == lexical.NUMBER, 'role')
        elif s.take(b'SUPPORT'):
            s.name()
        elif s.take(b'SET'):
            s.ident()
            while s.take(b'.'):
                s.ident()
            s.need(b'TO'); s.literal()
            while s.take(b','):
                s.literal()
        else:
            raise Unavailable('role')
    s.need(b'AS')
    kind, _, _ = s.advance()
    require(kind in (lexical.STRING, lexical.ESCAPE, lexical.DOLLAR), 'role')
    if s.take(b','):
        kind, _, _ = s.advance()
        require(kind in (lexical.STRING, lexical.ESCAPE, lexical.DOLLAR), 'role')
    s.finish()
    for suffix in statements:
        suffix.extension_dependency(entry.description)


def acl_definition(entry, statements):
    auth, count, grants_seen, auth_grants, auth_option = False, 0, False, 0, False
    for s in statements:
        count += 1
        if s.take(b'SET'):
            require(not auth, 'role')
            s.need(b'SESSION', b'AUTHORIZATION'); s.ident(); s.finish()
            auth, grants_seen, auth_grants, auth_option = True, True, 0, False
            continue
        if s.take(b'RESET'):
            require(auth and 1 <= auth_grants <= 2, 'role')
            s.need(b'SESSION', b'AUTHORIZATION'); s.finish()
            auth = False
            continue
        if entry.description == b'DEFAULT ACL':
            s.need(b'ALTER', b'DEFAULT', b'PRIVILEGES', b'FOR', b'ROLE'); s.ident()
            if s.take(b'IN'):
                s.need(b'SCHEMA'); s.ident()
        grant = s.take(b'GRANT')
        if not grant:
            require(not grants_seen and not auth, 'role')
            s.need(b'REVOKE')
        else:
            grants_seen = True
        # Ordered privileges, with optional column lists; each is a closed word.
        while True:
            privilege = s.ident().upper()
            require(privilege in (b'ALL', b'SELECT', b'INSERT', b'UPDATE', b'DELETE', b'TRUNCATE',
                b'REFERENCES', b'TRIGGER', b'EXECUTE', b'USAGE', b'CREATE', b'CONNECT', b'TEMPORARY', b'MAINTAIN'), 'role')
            if privilege == b'ALL': s.take(b'PRIVILEGES')
            if s.take(b'('):
                s.ident()
                while s.take(b','): s.ident()
                s.need(b')')
            if not s.take(b','): break
        s.need(b'ON')
        if entry.description == b'DEFAULT ACL':
            require(s.ident().upper() in (b'TABLES', b'SEQUENCES', b'FUNCTIONS', b'TYPES', b'SCHEMAS'), 'role')
        else:
            kind = s.ident().upper()
            require(kind in (b'TABLE', b'SEQUENCE', b'FUNCTION', b'PROCEDURE', b'SCHEMA', b'DATABASE',
                             b'TYPE', b'LANGUAGE'), 'role')
            s.interior_until(b'TO' if grant else b'FROM')
        s.need(b'TO' if grant else b'FROM')
        s.ident()
        option = grant and s.take(b'WITH')
        if option: s.need(b'GRANT', b'OPTION')
        if auth:
            require(grant and auth_grants < 2 and (auth_grants == 0 or option and not auth_option), 'role')
            auth_grants += 1; auth_option = option
        s.finish()
    require(count > 0 and not auth, 'role')


def comment_definition(entry, statements):
    count = 0
    kinds = (b'SCHEMA', b'EXTENSION', b'FUNCTION', b'PROCEDURE', b'TYPE', b'DOMAIN', b'TABLE',
        b'COLUMN', b'SEQUENCE', b'VIEW', b'INDEX', b'CONSTRAINT', b'TRIGGER', b'RULE', b'POLICY',
        b'DATABASE', b'PUBLICATION', b'AGGREGATE', b'OPERATOR', b'MATERIALIZED', b'EVENT')
    for s in statements:
        count += 1
        if entry.description == b'COMMENT':
            s.need(b'COMMENT', b'ON')
        else:
            s.need(b'SECURITY', b'LABEL', b'FOR'); s.ident(); s.need(b'ON')
        kind = s.ident().upper()
        require(kind in kinds, 'role')
        if kind == b'MATERIALIZED': s.need(b'VIEW')
        if kind == b'EVENT': s.need(b'TRIGGER')
        if kind == b'OPERATOR' and (s.take(b'CLASS') or s.take(b'FAMILY')): pass
        s.interior_until(b'IS'); s.need(b'IS'); s.literal(); s.finish()
    require(count > 0 and (entry.description != b'COMMENT' or count == 1), 'role')


def validate_definition(entry, statements, budget):
    """Closed outer roles; attributed interiors never imply writer exclusion."""
    desc = entry.description
    if desc in (b'FUNCTION', b'PROCEDURE'):
        return function_definition(entry, statements)
    if desc in (b'ACL', b'DEFAULT ACL'):
        return acl_definition(entry, statements)
    if desc in (b'COMMENT', b'SECURITY LABEL'):
        return comment_definition(entry, statements)
    if desc == b'DATABASE PROPERTIES':
        return database_properties(entry, statements)
    if desc == b'TABLE DATA':
        require(entry.definition.startswith(b'-- load via partition root ') and next(statements, None) is None, 'role')
        return
    if desc == b'SCHEMA':
        if entry.definition == b'-- *not* creating schema, since initdb creates it\n':
            require(entry.tag == b'public' and next(statements, None) is None, 'role')
        else:
            s = single(statements); s.need(b'CREATE', b'SCHEMA'); s.ident(entry.tag); s.finish()
        return
    if desc == b'DATABASE':
        return database_definition(entry, single(statements))
    s = next(statements, None)
    require(s is not None, 'role')
    if desc == b'EXTENSION':
        s.need(b'CREATE', b'EXTENSION', b'IF', b'NOT', b'EXISTS'); s.ident(entry.tag)
        s.need(b'WITH', b'SCHEMA'); s.ident()
    elif desc in (b'TYPE', b'SHELL TYPE'):
        s.need(b'CREATE', b'TYPE'); s.name(entry)
        if desc == b'TYPE' and not s.is_(b';'):
            if s.take(b'AS'):
                s.take(b'ENUM') or s.take(b'RANGE')
            s.group(False)
    elif desc == b'DOMAIN':
        s.need(b'CREATE', b'DOMAIN'); s.name(entry); s.need(b'AS')
        s.interior_until(b';')
    elif desc in (b'TABLE', b'VIEW', b'MATERIALIZED VIEW'):
        s.need(b'CREATE'); unlogged = s.take(b'UNLOGGED')
        require(not unlogged or desc != b'VIEW', 'role')
        s.need(*desc.split()); s.name(entry)
        if desc == b'TABLE':
            if s.take(b'OF'):
                s.name()
            s.group(False)
            if s.take(b'INHERITS'): s.group()
            if s.take(b'PARTITION'): s.need(b'BY'); s.ident(); s.group()
            if s.take(b'USING'): s.ident()
            if s.take(b'WITH'): s.group()
        else:
            if s.take(b'WITH'): s.group()
            s.need(b'AS'); s.interior_until(b';')
            if desc == b'MATERIALIZED VIEW':
                require(s.has_suffix(b'WITH', b'NO', b'DATA'), 'role')
        s.finish()
        last = 0
        for s in statements:
            # Matview extension dependencies precede the shared column tail.
            if s.is_(b'ALTER'):
                saved = s.at; s.need(b'ALTER')
                dependency = s.take(b'MATERIALIZED')
                s.at = saved
                if dependency:
                    require(desc == b'MATERIALIZED VIEW' and last == 0, 'role')
                    s.extension_dependency(b'MATERIALIZED VIEW'); continue
            current = relation_suffix(s, entry)
            require(current >= last, 'role'); last = current
        return
    elif desc == b'MATERIALIZED VIEW DATA':
        s.need(b'REFRESH', b'MATERIALIZED', b'VIEW'); s.name(entry)
    elif desc == b'SEQUENCE':
        if s.take(b'CREATE'):
            s.take(b'UNLOGGED'); s.need(b'SEQUENCE'); s.name(entry)
        else:
            s.need(b'ALTER', b'TABLE'); s.name(); s.need(b'ALTER', b'COLUMN'); s.ident()
            s.need(b'ADD', b'GENERATED')
            if not s.take(b'ALWAYS'): s.need(b'BY', b'DEFAULT')
            s.need(b'AS', b'IDENTITY', b'(', b'SEQUENCE', b'NAME'); s.name(entry)
            sequence_options(s); s.need(b')'); s.finish()
            require(next(statements, None) is None, 'role'); return
        sequence_options(s)
    elif desc == b'SEQUENCE OWNED BY':
        s.need(b'ALTER', b'SEQUENCE'); s.name(entry); s.need(b'OWNED', b'BY')
        s.name(); s.need(b'.'); s.ident()
    elif desc == b'SEQUENCE SET':
        s.need(b'SELECT', b'PG_CATALOG', b'.', b'SETVAL', b'('); s.literal()
        s.need(b','); s.integer(); s.need(b','); require(s.take(b'TRUE') or s.take(b'FALSE'), 'role'); s.need(b')')
    elif desc == b'DEFAULT':
        s.need(b'ALTER', b'TABLE', b'ONLY'); s.name(); s.need(b'ALTER', b'COLUMN'); s.ident()
        s.need(b'SET', b'DEFAULT'); s.interior_until(b';')
    elif desc == b'ROW SECURITY':
        s.need(b'ALTER', b'TABLE'); s.name(entry); s.need(b'ENABLE', b'ROW', b'LEVEL', b'SECURITY')
    elif desc == b'INDEX ATTACH':
        s.need(b'ALTER', b'INDEX'); s.name(); s.need(b'ATTACH', b'PARTITION'); s.name()
    elif desc == b'TABLE ATTACH':
        s.need(b'ALTER', b'TABLE', b'ONLY'); s.name(); s.need(b'ATTACH', b'PARTITION'); s.name()
        if not s.take(b'DEFAULT'):
            s.need(b'FOR', b'VALUES')
            if s.take(b'IN'): s.group()
            elif s.take(b'FROM'): s.group(); s.need(b'TO'); s.group()
            else: s.need(b'WITH'); s.group()
    elif desc == b'POLICY':
        s.need(b'CREATE', b'POLICY'); s.ident(); s.need(b'ON'); s.name()
        if s.take(b'AS'): s.need(b'RESTRICTIVE')
        if s.take(b'FOR'): require(s.ident().upper() in (b'ALL', b'SELECT', b'INSERT', b'UPDATE', b'DELETE'), 'role')
        if s.take(b'TO'):
            s.ident()
            while s.take(b','): s.ident()
        if s.take(b'USING'): s.group()
        if s.take(b'WITH'): s.need(b'CHECK'); s.group()
    elif desc == b'EVENT TRIGGER':
        s.need(b'CREATE', b'EVENT', b'TRIGGER'); s.ident(entry.tag); s.need(b'ON'); s.ident()
        if s.take(b'WHEN'):
            s.need(b'TAG', b'IN', b'('); s.literal()
            while s.take(b','): s.literal()
            s.need(b')')
        s.need(b'EXECUTE', b'FUNCTION'); s.name(); s.need(b'(', b')'); s.finish()
        s = next(statements, None)
        if s is not None:
            s.need(b'ALTER', b'EVENT', b'TRIGGER'); s.ident(entry.tag); firing_mode(s); s.finish()
        require(next(statements, None) is None, 'role'); return
    elif desc == b'PUBLICATION':
        s.need(b'CREATE', b'PUBLICATION'); s.ident(entry.tag)
        if s.take(b'FOR'): s.need(b'ALL', b'TABLES')
        s.need(b'WITH', b'(', b'PUBLISH', b'='); start, end = s.literal()
        content = s.raw[start+1:end-1]
        values = content.split(b', ')
        require(values == [v for v in (b'insert', b'update', b'delete', b'truncate') if v in values], 'role')
        if s.take(b','): s.need(b'PUBLISH_VIA_PARTITION_ROOT', b'=', b'TRUE')
        s.need(b')')
    elif desc == b'PUBLICATION TABLE':
        s.need(b'ALTER', b'PUBLICATION'); s.ident(); s.need(b'ADD', b'TABLE', b'ONLY'); s.name()
        if s.take(b'('):
            s.ident()
            while s.take(b','): s.ident()
            s.need(b')')
        if s.take(b'WHERE'): s.group()
    elif desc == b'PUBLICATION TABLES IN SCHEMA':
        s.need(b'ALTER', b'PUBLICATION'); s.ident(); s.need(b'ADD', b'TABLES', b'IN', b'SCHEMA'); s.ident()
    elif desc in (b'INDEX', b'CONSTRAINT', b'FK CONSTRAINT', b'CHECK CONSTRAINT'):
        return index_or_constraint(entry, s, statements)
    elif desc in (b'TRIGGER', b'RULE'):
        return trigger_or_rule(entry, s, statements)
    elif desc in (b'AGGREGATE', b'OPERATOR', b'OPERATOR CLASS', b'OPERATOR FAMILY'):
        return aggregate_or_operator(entry, s, statements)
    else:
        raise Unavailable('role')
    s.finish()
    require(next(statements, None) is None, 'role')


def sequence_options(s):
    if s.take(b'AS'): require(s.ident() in (b'smallint', b'integer', b'bigint'), 'role')
    s.need(b'START', b'WITH'); s.integer(); s.need(b'INCREMENT', b'BY'); s.integer()
    if s.take(b'NO'): s.need(b'MINVALUE')
    else: s.need(b'MINVALUE'); s.integer()
    if s.take(b'NO'): s.need(b'MAXVALUE')
    else: s.need(b'MAXVALUE'); s.integer()
    s.need(b'CACHE'); s.integer()
    s.take(b'CYCLE')


def firing_mode(s):
    if s.take(b'ENABLE'):
        s.take(b'ALWAYS') or s.take(b'REPLICA')
    else:
        s.need(b'DISABLE')


def index_or_constraint(entry, s, statements):
    desc = entry.description
    if desc == b'INDEX':
        s.need(b'CREATE'); s.take(b'UNIQUE'); s.need(b'INDEX'); s.ident(entry.tag)
        s.need(b'ON'); s.take(b'ONLY'); s.name(); s.need(b'USING'); s.ident(); s.group()
        if s.take(b'INCLUDE'): s.group()
        if s.take(b'NULLS'): s.need(b'NOT', b'DISTINCT')
        if s.take(b'WITH'): s.group()
        if s.take(b'TABLESPACE'): s.ident()
        if s.take(b'WHERE'): s.interior_until(b';')
    else:
        s.need(b'ALTER'); domain = s.take(b'DOMAIN')
        if not domain: s.need(b'TABLE'); s.take(b'ONLY')
        s.name(); s.need(b'ADD', b'CONSTRAINT'); s.ident()
        kind = s.ident().upper()
        allowed = {b'FK CONSTRAINT': (b'FOREIGN',), b'CHECK CONSTRAINT': (b'CHECK',),
                   b'CONSTRAINT': (b'PRIMARY', b'UNIQUE', b'EXCLUDE', b'NOT', b'CHECK')}[desc]
        require(kind in allowed, 'role')
        if kind == b'FOREIGN': s.need(b'KEY'); s.group(); s.need(b'REFERENCES'); s.name(); s.group(); s.interior_until(b';', nonempty=False)
        elif kind == b'NOT': s.need(b'NULL')
        else:
            if kind == b'PRIMARY': s.need(b'KEY')
            if kind == b'UNIQUE' and s.take(b'NULLS'): s.need(b'NOT', b'DISTINCT')
            if kind == b'EXCLUDE' and s.take(b'USING'): s.ident()
            s.group(); s.interior_until(b';', nonempty=False)
    s.finish()
    order = 0
    for s in statements:
        s.need(b'ALTER')
        if s.take(b'INDEX'):
            s.name()
            if s.take(b'ALTER'):
                require(desc == b'INDEX' and order <= 1, 'role'); order = 1
                s.need(b'COLUMN'); s.integer(); s.need(b'SET', b'STATISTICS'); s.integer()
            else:
                require(order <= 2, 'role'); order = 2
                s.need(b'DEPENDS', b'ON', b'EXTENSION'); s.ident()
        else:
            s.need(b'TABLE'); only = s.take(b'ONLY'); s.name()
            if s.take(b'CLUSTER'):
                require(not only and order == 0, 'role'); s.need(b'ON'); s.ident()
            else:
                require(only and order <= 3, 'role'); order = 3
                s.need(b'REPLICA', b'IDENTITY', b'USING', b'INDEX'); s.ident()
        s.finish()


def trigger_or_rule(entry, s, statements):
    if s.take(b'CREATE'):
        if entry.description == b'TRIGGER':
            s.take(b'CONSTRAINT'); s.need(b'TRIGGER'); s.ident()
            require(s.take(b'BEFORE') or s.take(b'AFTER') or s.take(b'INSTEAD') and s.take(b'OF'), 'role')
            s.interior_until(b'ON'); s.need(b'ON'); s.name()
            s.interior_until(b'EXECUTE', nonempty=False); s.need(b'EXECUTE')
            require(s.take(b'FUNCTION') or s.take(b'PROCEDURE'), 'role')
            s.name(); s.group(False)
        elif s.take(b'OR'):
            s.need(b'REPLACE', b'VIEW'); s.name(); s.need(b'AS'); s.interior_until(b';')
        else:
            s.need(b'RULE'); s.ident(); s.need(b'AS', b'ON')
            require(s.ident().upper() in (b'SELECT', b'UPDATE', b'INSERT', b'DELETE'), 'role')
            s.need(b'TO'); s.name(); s.interior_until(b'DO', nonempty=False); s.need(b'DO')
            s.interior_until(b';')
        s.finish()
        s = next(statements, None)
    else:
        require(entry.description == b'TRIGGER' and not entry.drop, 'role')
    firing = False
    while s is not None:
        s.need(b'ALTER')
        if s.take(b'TRIGGER'):
            require(entry.description == b'TRIGGER' and not firing, 'role')
            s.interior_until(b'DEPENDS'); s.need(b'DEPENDS', b'ON', b'EXTENSION'); s.ident()
        else:
            require(not firing, 'role'); firing = True
            s.need(b'TABLE'); s.name(); firing_mode(s); s.need(entry.description); s.ident()
        s.finish(); s = next(statements, None)


def aggregate_or_operator(entry, s, statements):
    s.need(b'CREATE', *entry.description.split())
    if entry.description == b'OPERATOR':
        if entry.namespace:
            s.ident(entry.namespace); s.need(b'.')
        # Operator symbols are source bytes, not fmtId; only the closed operator alphabet.
        start = s.peek()[1]
        while not s.is_(b'('):
            kind, a, b = s.advance()
            require(kind == lexical.PUNCT and all(v in b'+-*/<>=~!@#%^&|`?' for v in s.raw[a:b]), 'role')
        require(s.raw[start:s.peek()[1]].strip() == entry.tag, 'role')
        operator_details(s)
    elif entry.description == b'AGGREGATE':
        # Full CREATE signature and identity DROP/tag intentionally differ.
        namespace, _ = s.name(); require(namespace == (entry.namespace or None), 'role')
        s.group(); aggregate_details(s)
    elif entry.description == b'OPERATOR CLASS':
        s.name(entry); s.take(b'DEFAULT'); s.need(b'FOR', b'TYPE'); s.interior_until(b'USING')
        s.need(b'USING'); s.ident()
        if s.take(b'FAMILY'): s.name()
        s.need(b'AS'); operator_members(s, storage=True)
    else:
        target = s.name(entry); s.need(b'USING'); method = s.ident(); s.finish()
        extra = next(statements, None)
        if extra is not None:
            extra.need(b'ALTER', b'OPERATOR', b'FAMILY'); require(extra.name() == target, 'role')
            extra.need(b'USING'); extra.ident(method); extra.need(b'ADD'); operator_members(extra, storage=False); extra.finish()
        require(next(statements, None) is None, 'role'); return
    s.finish(); require(next(statements, None) is None, 'role')


def details(s, ordered, flags=(), required=()):
    s.need(b'('); last = -1; seen = set()
    while True:
        name = s.ident().upper()
        require(name in ordered and ordered.index(name) > last, 'role')
        last = ordered.index(name)
        seen.add(name)
        if name not in flags:
            s.need(b'=')
            if name in (b'FINALFUNC_MODIFY', b'MFINALFUNC_MODIFY'):
                require(s.ident().upper() in (b'READ_ONLY', b'SHAREABLE', b'READ_WRITE'), 'role')
            elif name == b'PARALLEL':
                require(s.ident().upper() in (b'SAFE', b'RESTRICTED'), 'role')
            elif name in (b'INITCOND', b'MINITCOND'):
                s.literal()
            elif name in (b'SSPACE', b'MSSPACE'):
                s.integer()
            else:
                s.interior_until(b',', b')')
        if not s.take(b','): break
    s.need(b')')
    require(set(required) <= seen, 'role')


def aggregate_details(s):
    # Ordering follows dumpAgg; values/signatures are bounded attributed interiors.
    details(s, (b'SFUNC', b'STYPE', b'SSPACE', b'INITCOND', b'FINALFUNC', b'FINALFUNC_EXTRA',
        b'FINALFUNC_MODIFY', b'COMBINEFUNC', b'SERIALFUNC', b'DESERIALFUNC', b'MSFUNC', b'MINVFUNC',
        b'MSTYPE', b'MSSPACE', b'MINITCOND', b'MFINALFUNC', b'MFINALFUNC_EXTRA', b'MFINALFUNC_MODIFY',
        b'SORTOP', b'HYPOTHETICAL', b'PARALLEL'), (b'FINALFUNC_EXTRA', b'MFINALFUNC_EXTRA', b'HYPOTHETICAL'),
        (b'SFUNC', b'STYPE'))


def operator_details(s):
    details(s, (b'FUNCTION', b'LEFTARG', b'RIGHTARG', b'COMMUTATOR', b'NEGATOR', b'MERGES',
                b'HASHES', b'RESTRICT', b'JOIN'), (b'MERGES', b'HASHES'), (b'FUNCTION',))


def operator_members(s, storage):
    last, count = -1, 0
    while True:
        count += 1
        if s.take(b'STORAGE'):
            require(storage and last < 0, 'role'); last = 0
        elif s.take(b'OPERATOR'):
            require(last <= 1, 'role'); last = 1; s.integer()
        else:
            s.need(b'FUNCTION'); last = 2; s.integer()
        s.interior_until(b',', b';')
        if not s.take(b','): break
    require(count > 0, 'role')


CLAIMS = {'completeByteCoverage': True, 'completeEmitterAttribution': True,
    'selectedStaticBoundaries': True, 'lexicalProfile': lexical.PROFILE,
    'rawArchiveIdentitiesProducerAttested': True, 'runtime': False, 'S0': False,
    'causality': False, 'recovery': False}


def keys(value, expected):
    require(type(value) is dict and set(value) == set(expected))


def number(value, lower, upper):
    require(type(value) is int and lower <= value <= upper)


def hash_value(value):
    require(type(value) is str and re.fullmatch(r'[a-f0-9]{64}', value) is not None)


def sized_hash(value, lower, upper):
    keys(value, ('bytes', 'sha256'))
    number(value['bytes'], lower, upper)
    hash_value(value['sha256'])


def validate_receipt(value, *, fsql, inventory=None, archive_binding=None, code=None, catalog=None):
    """Strict offline contract; external arguments must already be authenticated.

    Numeric/index facts remain producer-attested. The three semantic digests are
    independently reconstructed from the original failed catalog by the reader.
    """
    require(type(value) is dict and value.get('schema') == SCHEMA)
    require(len(canonical(value)) <= MAX_RECEIPT, 'limit')
    if value.get('status') == 'unavailable':
        keys(value, ('schema', 'status', 'reason', 'stage', 'context'))
        reason, stage = value['reason'], value['stage']
        require(type(reason) is str and reason in REASON_STAGES
                and type(stage) is str and stage in REASON_STAGES[reason])
        context = value['context']
        keys(context, ('rowIndex', 'dumpId', 'descriptor', 'offset', 'limit'))
        present = context['rowIndex'] is not None
        require(present == (context['dumpId'] is not None) == (context['descriptor'] is not None))
        if present:
            require(stage in ('metadata', 'emitter'))
            number(context['rowIndex'], 0, raw_toc.MAX_ROWS-1)
            number(context['dumpId'], 1, 2147483647)
            require(type(context['descriptor']) is str
                    and context['descriptor'] in (*raw_toc.DESCRIPTORS, 'unknown'))
        if context['offset'] is not None:
            require(stage == 'emitter')
            number(context['offset'], 0, lexical.MAX_INPUT)
        if context['limit'] is not None:
            require(reason == 'limit' and stage == 'lexical')
            require(type(fsql) is dict and fsql.get('status') == 'full_sql_verified'
                    and fsql.get('FsqlEqualsF2') is True and type(fsql.get('stream')) is dict)
            sized_hash(fsql['stream'], 1, lexical.MAX_INPUT)
            try:
                lexical.validate_limit(context['limit'], input_bytes=fsql['stream']['bytes'])
            except lexical.Unavailable:
                raise Unavailable('binding') from None
        return value
    keys(value, ('schema', 'status', 'profile', 'configurationSha256', 'inputs', 'code',
                 'counts', 'indexes', 'selected', 'claims'))
    require(value['status'] == 'verified_conditional' and value['profile'] == PROFILE
            and value['configurationSha256'] == semantic_hash(CONFIG))
    require(type(fsql) is dict and fsql.get('status') == 'full_sql_verified'
            and fsql.get('FsqlEqualsF2') is True and fsql.get('tool', {}).get('version') == '17.6')
    inputs = value['inputs']
    keys(inputs, ('script', 'archive', 'verboseToc', 'metadata'))
    for name, cap in (('script', lexical.MAX_INPUT), ('archive', raw_toc.MAX_ARCHIVE),
                      ('verboseToc', raw_toc.MAX_LIST), ('metadata', raw_toc.MAX_METADATA)):
        sized_hash(inputs[name], 1, cap)
    require(inputs['metadata']['bytes'] <= inputs['archive']['bytes']
            and inputs['script'] == fsql['stream'] and inputs['archive'] == archive_binding
            and inputs['verboseToc']['sha256'] == inventory['sha256'])
    keys(value['code'], MODULES)
    for name in MODULES:
        hash_value(value['code'][name]); require(value['code'][name] == code[name])
    counts = value['counts']
    keys(counts, ('rows', 'specialRows', 'zeroOccurrenceRows', 'occurrences', 'statements',
                 'copyGroups', 'metaLines', 'reconnects', 'regions', 'passRows'))
    number(counts['rows'], 1, raw_toc.MAX_ROWS)
    number(counts['specialRows'], 3, 3)
    number(counts['zeroOccurrenceRows'], 3, counts['rows'])
    number(counts['occurrences'], 3, MAX_OCCURRENCES)
    emitting = counts['rows']-counts['zeroOccurrenceRows']
    require(emitting <= counts['occurrences'] <= 2*emitting)
    number(counts['statements'], 1, lexical.MAX_STATEMENTS)
    number(counts['copyGroups'], 0, min(lexical.MAX_COPY, counts['occurrences']))
    number(counts['reconnects'], 1, 2)
    number(counts['metaLines'], 2+3*counts['reconnects'], 2+3*counts['reconnects'])
    number(counts['regions'], 1, MAX_REGIONS)
    keys(counts['passRows'], PASSES)
    for count in counts['passRows'].values(): number(count, 0, counts['rows'])
    require(counts['passRows']['SPECIAL'] == 3 and sum(counts['passRows'].values()) == counts['rows']
            and counts['passRows'] == inventory['passCounts'] and counts['rows'] == inventory['total'])
    indexes = value['indexes']
    keys(indexes, ('decisions', 'regions', 'occurrences'))
    for name, count, size, cap in (
            ('decisions', counts['rows'], DECISION.size, DECISION.size*raw_toc.MAX_ROWS),
            ('regions', counts['regions'], REGION.size, MAX_REGION_BYTES),
            ('occurrences', counts['occurrences'], OCCURRENCE.size, MAX_OCCURRENCE_BYTES)):
        sized_hash(indexes[name], 1, cap)
        require(indexes[name]['bytes'] == count*size)
    selected = value['selected']
    require(type(selected) is list and len(selected) == 3)
    semantics = selected_semantics(catalog)
    require(type(inventory['checkpointIds']) is list and len(inventory['checkpointIds']) == 3)
    wanted = dict(zip((item[0] for item in SELECTORS), inventory['checkpointIds']))
    seen_ids, seen_kinds, seen_occurrences, last_cut = set(), set(), set(), -1
    for record in selected:
        keys(record, ('kind', 'dumpId', 'classOid', 'objectOid', 'occurrence', 'preludeStart',
                      'definitionStart', 'entryEnd', 'nextPreludeStart', 'cut', 'semanticSha256'))
        kind = record['kind']
        require(type(kind) is str and kind in wanted and kind not in seen_kinds)
        number(record['dumpId'], 1, 2147483647)
        for key in ('classOid', 'objectOid'): number(record[key], 1, 4294967295)
        number(record['occurrence'], 0, counts['occurrences']-2)
        require(record['dumpId'] == wanted[kind] and record['dumpId'] not in seen_ids
                and record['occurrence'] not in seen_occurrences)
        for key in ('preludeStart', 'definitionStart', 'entryEnd', 'nextPreludeStart', 'cut'):
            number(record[key], 0, inputs['script']['bytes']-1)
        require(record['preludeStart'] < record['definitionStart'] <= record['entryEnd']
                == record['cut'] == record['nextPreludeStart'] and record['cut'] > last_cut
                and record['semanticSha256'] == semantics[kind][1])
        seen_ids.add(record['dumpId']); seen_kinds.add(kind); seen_occurrences.add(record['occurrence'])
        last_cut = record['cut']
    keys(value['claims'], CLAIMS)
    for key, expected in CLAIMS.items():
        require(type(value['claims'][key]) is type(expected) and value['claims'][key] == expected)
    return value


def observe(path, script, toc, metadata, inventory, fsql, deadline, *, read_private):
    """Production entrypoint; ordinary failures preserve already verified Fsql."""
    if deadline-time.monotonic() < TOTAL_SECONDS:
        return unavailable('headroom', 'admission')
    budget = Budget(deadline)
    lexical_limit = None
    try:
        budget.phase('metadata')
        require(fsql['status'] == 'full_sql_verified' and fsql['FsqlEqualsF2'] is True
                and fsql['tool']['version'] == '17.6' and metadata['phases']['mismatch']['catalog']['serverVersion'] == 170006,
                'profile')
        require(type(script) is bytes and 0 < len(script) <= lexical.MAX_INPUT
                and type(toc) is bytes and 0 < len(toc) <= raw_toc.MAX_LIST, 'input')
        raw = read_private(path/'archive.dump', raw_toc.MAX_ARCHIVE)
        budget.check()
        archive, summary = raw_toc.inspect(raw, toc, budget.deadline)
        require(all(re.fullmatch(rb'17\.6(?: [\x20-\x7e]+)?', value) is not None
                    for value in (archive.remote_version, archive.dump_version)), 'profile')
        archive_input = {'bytes': summary['archiveBytes'], 'sha256': summary['archiveSha256']}
        require(archive.database == b'postgres' and archive_input == metadata['files']['archive.dump']
                and summary['verboseListSha256'] == inventory['sha256'])
        core = verify_core(script, archive, selectors=SELECTORS,
                           catalog=metadata['phases']['mismatch']['catalog'], budget=budget)
        receipt = {'schema': SCHEMA, 'status': 'verified_conditional', 'profile': PROFILE,
            'configurationSha256': semantic_hash(CONFIG),
            'inputs': {'script': core.script, 'archive': archive_input,
                'verboseToc': {'bytes': len(toc), 'sha256': summary['verboseListSha256']},
                'metadata': {'bytes': archive.metadata_end, 'sha256': summary['metadataSha256']}},
            'code': {name: metadata['code'][name] for name in MODULES},
            'counts': core.counts, 'indexes': core.indexes, 'selected': list(core.selected), 'claims': CLAIMS.copy()}
        validate_receipt(receipt, fsql=fsql, inventory=inventory, archive_binding=archive_input,
                         code=metadata['code'], catalog=metadata['phases']['mismatch']['catalog'])
        budget.check()
        return receipt
    except lexical.Unavailable as error:
        reason = error.reason if error.reason in ('deadline', 'limit', 'binding', 'profile') else 'lexical'
        if reason == 'limit' and budget.stage == 'lexical':
            lexical_limit = error.limit
    except raw_toc.Unavailable as error:
        reason = 'deadline' if error.reason.startswith('deadline') else 'metadata'
    except identifiers.Unavailable:
        reason = 'deadline' if time.monotonic() >= budget.deadline else 'profile'
    except Unavailable as error:
        reason = error.reason
    except Exception:
        reason = 'internal'
    # No exception text, raw descriptor, SQL or user identifier leaves this layer.
    if reason not in REASON_STAGES or budget.stage not in REASON_STAGES[reason]:
        reason = 'internal'
    return unavailable(reason, budget.stage, budget.context | {'limit': lexical_limit})
