"""Bounded PG custom1.16 metadata only; no SQL, suffix or ledger validation."""
from dataclasses import dataclass
import hashlib
import math
import re
import time

MAX_ARCHIVE = 64 * 1024**2
MAX_METADATA = 16 * 1024**2
MAX_DEFINITION = 1024**2
MAX_STRING = 16 * 1024
MAX_HEADER_STRING = 4096
MAX_ROWS = 8192
MAX_DEPS = 4096
MAX_TOTAL_DEPS = 65536
MAX_LIST = 2 * 1024**2
COMPRESSION = (b'none', b'gzip', b'lz4', b'zstd')
DESCRIPTORS = (
    'ENCODING', 'STDSTRINGS', 'SEARCHPATH', 'DATABASE', 'DATABASE PROPERTIES', 'SCHEMA',
    'EXTENSION', 'COMMENT', 'SECURITY LABEL', 'ACL', 'ACL LANGUAGE', 'DEFAULT ACL',
    'FUNCTION', 'PROCEDURE', 'AGGREGATE', 'TYPE', 'SHELL TYPE', 'DOMAIN', 'DOMAIN CONSTRAINT',
    'TABLE', 'TABLE DATA', 'TABLE ATTACH', 'SEQUENCE', 'SEQUENCE SET', 'SEQUENCE OWNED BY',
    'VIEW', 'MATERIALIZED VIEW', 'MATERIALIZED VIEW DATA', 'INDEX', 'INDEX ATTACH',
    'CONSTRAINT', 'CHECK CONSTRAINT', 'FK CONSTRAINT', 'TRIGGER', 'EVENT TRIGGER', 'RULE',
    'POLICY', 'ROW SECURITY', 'PUBLICATION', 'PUBLICATION TABLE', 'PUBLICATION TABLES IN SCHEMA',
    'SUBSCRIPTION', 'SUBSCRIPTION TABLE', 'CAST', 'COLLATION', 'CONVERSION', 'OPERATOR',
    'OPERATOR CLASS', 'OPERATOR FAMILY', 'TRANSFORM', 'TEXT SEARCH PARSER',
    'TEXT SEARCH TEMPLATE', 'TEXT SEARCH DICTIONARY', 'TEXT SEARCH CONFIGURATION',
    'PROCEDURAL LANGUAGE', 'FOREIGN DATA WRAPPER', 'SERVER', 'USER MAPPING', 'FOREIGN TABLE',
    'DEFAULT', 'STATISTICS', 'BLOB', 'BLOBS', 'BLOB METADATA', 'ACL LARGE OBJECTS',
    'BLOB COMMENTS', 'TABLESPACE', 'ACCESS METHOD', 'PRE-DATA BOUNDARY', 'POST-DATA BOUNDARY',
)
DESCRIPTOR_LABELS = {label.encode(): label for label in DESCRIPTORS}
NULLABLE_FIELDS = ('definition', 'drop', 'copy', 'namespace', 'tablespace', 'tableam', 'owner')


class Unavailable(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__('raw_toc_metadata_unavailable')


def require(condition, reason):
    if not condition:
        raise Unavailable(reason)


class Budget:
    def __init__(self, deadline):
        require(type(deadline) in (int, float) and math.isfinite(deadline), 'deadline_invalid')
        self.deadline = min(deadline, time.monotonic() + 5)
        self.check()

    def check(self):
        require(time.monotonic() < self.deadline, 'deadline_exhausted')

    def digest(self, raw):
        self.check()
        value = hashlib.sha256()
        for start in range(0, len(raw), 65536):
            self.check()
            value.update(memoryview(raw)[start:start + 65536])
        self.check()
        return value.hexdigest()


@dataclass(frozen=True)
class Entry:
    dump_id: int
    had_dumper: int
    class_oid: int
    object_oid: int
    tag: bytes
    description: bytes
    section: int
    definition: bytes | None
    drop: bytes | None
    copy: bytes | None
    namespace: bytes | None
    tablespace: bytes | None
    tableam: bytes | None
    relkind: int
    owner: bytes | None
    with_oids: bytes
    dependencies: tuple[int, ...]
    offset_state: int
    offset: int
    span: tuple[int, int]


@dataclass(frozen=True)
class Archive:
    raw: bytes
    timestamp: tuple[int, ...]
    database: bytes
    remote_version: bytes
    dump_version: bytes
    compression: int
    header_end: int
    metadata_end: int
    entries: tuple[Entry, ...]


class Reader:
    def __init__(self, raw, budget):
        require(type(raw) is bytes and len(raw) <= MAX_ARCHIVE, 'archive_input_invalid')
        self.raw, self.budget, self.pos = raw, budget, 0

    def take(self, size):
        self.budget.check()
        require(type(size) is int and size >= 0, 'length_invalid')
        end = self.pos + size
        require(end <= MAX_METADATA, 'metadata_oversized')
        require(end <= len(self.raw), 'metadata_truncated')
        value = self.raw[self.pos:end]
        self.pos = end
        return value

    def integer(self):
        wire = self.take(5)
        magnitude = int.from_bytes(wire[1:], 'little')
        require(wire[0] in (0, 1) and magnitude <= 2147483647
                and not (wire[0] == 1 and magnitude == 0), 'integer_invalid')
        return -magnitude if wire[0] else magnitude

    def string(self, cap=MAX_STRING, *, required=False):
        size = self.integer()
        if size == -1:
            require(not required, 'required_string_missing')
            return None
        require(0 <= size <= cap, 'string_length_invalid')
        value = self.take(size)
        require(b'\0' not in value, 'string_nul')
        try:
            value.decode('utf-8', errors='strict')
        except UnicodeError:
            raise Unavailable('string_encoding_invalid') from None
        self.budget.check()
        return value

    def decimal(self, maximum, *, zero=False, value=None):
        if value is None:
            value = self.string(required=True)
        require(len(value) <= 10 and value.isdigit()
                and (value == b'0' if value[:1] == b'0' else bool(value)), 'decimal_invalid')
        result = int(value)
        require((0 if zero else 1) <= result <= maximum, 'decimal_range_invalid')
        return result


def decode(raw, budget):
    r = Reader(raw, budget)
    header = r.take(12)
    require(header[:11] == b'PGDMP\x01\x10\x00\x04\x08\x01'
            and header[11] in range(4), 'archive_profile_unsupported')
    stamp = tuple(r.integer() for _ in range(7))
    limits = ((0, 60), (0, 59), (0, 23), (1, 31), (0, 11), (0, 9999), (-1, 1))
    require(all(lo <= value <= hi for value, (lo, hi) in zip(stamp, limits)), 'timestamp_invalid')
    database, remote, version = (r.string(MAX_HEADER_STRING, required=True) for _ in range(3))
    require(database and remote and version, 'header_string_empty')
    require(not any(x in remote + version for x in (b'\r', b'\n')), 'version_multiline')
    header_end = r.pos
    count = r.integer()
    require(0 < count <= MAX_ROWS, 'toc_count_invalid')
    entries, ids, total_deps = [], set(), 0
    for _ in range(count):
        budget.check()
        start = r.pos
        dump_id, had_dumper = r.integer(), r.integer()
        require(dump_id > 0 and dump_id not in ids and had_dumper in (0, 1), 'entry_id_or_dumper_invalid')
        ids.add(dump_id)
        class_oid, object_oid = (r.decimal(4294967295, zero=True) for _ in range(2))
        tag, description = r.string(required=True), r.string(required=True)
        require(description and b'\r' not in description and b'\n' not in description, 'description_invalid')
        section = r.integer()
        require(section in (1, 2, 3, 4), 'section_invalid')
        definition, drop, copy = (r.string(MAX_DEFINITION) for _ in range(3))
        namespace, tablespace, tableam = (r.string() for _ in range(3))
        relkind, owner = r.integer(), r.string()
        require(0 <= relkind <= 127, 'relkind_unsupported')
        with_oids = r.string(required=True)
        require(with_oids == b'false', 'with_oids_unsupported')
        deps = []
        while True:
            budget.check()
            value = r.string()
            if value is None:
                break
            require(len(deps) < MAX_DEPS and total_deps < MAX_TOTAL_DEPS, 'dependency_count_exceeded')
            deps.append(r.decimal(2147483647, value=value))
            total_deps += 1
        offset = r.take(9)
        state, position = offset[0], int.from_bytes(offset[1:], 'little')
        require(state in (1, 2, 3) and position <= 9223372036854775807, 'offset_invalid')
        entries.append(Entry(dump_id, had_dumper, class_oid, object_oid, tag, description,
                             section, definition, drop, copy, namespace, tablespace, tableam,
                             relkind, owner, with_oids, tuple(deps), state, position, (start, r.pos)))
    for entry in entries:
        budget.check()
        require(entry.offset_state != 2 or r.pos <= entry.offset < len(raw), 'offset_out_of_range')
    budget.check()
    return Archive(raw, stamp, database, remote, version, header[11], header_end, r.pos, tuple(entries))


def sanitize(value, hyphen=False):
    return (b'-' if hyphen else b'') if value is None else value.replace(b'\r', b' ').replace(b'\n', b' ')


class Output:
    def __init__(self, budget):
        self.budget, self.data = budget, bytearray()

    def append(self, raw):
        self.budget.check()
        require(len(self.data) + len(raw) <= MAX_LIST, 'rendered_list_oversized')
        self.data.extend(raw)

    def field(self, raw, *, hyphen=False):
        # Sanitization preserves length; test the cap before making its copy.
        self.budget.check()
        size = len(raw) if raw is not None else int(hyphen)
        require(len(self.data) + size <= MAX_LIST, 'rendered_list_oversized')
        self.append(sanitize(raw, hyphen))


def render_entries(archive, budget):
    out = Output(budget)
    for entry in archive.entries:
        budget.check()
        out.append(f'{entry.dump_id}; {entry.class_oid} {entry.object_oid} '.encode())
        out.field(entry.description)
        out.append(b' ')
        out.field(entry.namespace, hyphen=True)
        out.append(b' ')
        out.field(entry.tag)
        out.append(b' ')
        out.field(entry.owner)
        out.append(b'\n')
        if entry.dependencies:
            out.append(b';\tdepends on:')
            for dep in entry.dependencies:
                out.append(f' {dep}'.encode())
            out.append(b'\n')
    budget.check()
    return bytes(out.data)


class Lines:
    def __init__(self, raw, budget):
        require(type(raw) is bytes and len(raw) <= MAX_LIST, 'list_input_invalid')
        self.raw, self.budget, self.pos = raw, budget, 0

    def next(self):
        self.budget.check()
        end = self.raw.find(b'\n', self.pos, min(len(self.raw), self.pos + 16385))
        require(end >= self.pos, 'list_header_invalid')
        line, self.pos = self.raw[self.pos:end], end + 1
        return line

    def exact(self, expected):
        require(self.next() == expected, 'list_header_mismatch')


def compare_list(archive, raw, budget):
    lines = Lines(raw, budget)
    lines.exact(b';')
    timestamp = lines.next()
    require(re.fullmatch(rb'; Archive created at [\x20-\x7e]{1,128}', timestamp) is not None, 'list_timestamp_invalid')
    fields = (
        (b'dbname', sanitize(archive.database)),
        (b'TOC Entries', str(len(archive.entries)).encode()),
        (b'Compression', COMPRESSION[archive.compression]),
        (b'Dump Version', b'1.16-0'), (b'Format', b'CUSTOM'),
        (b'Integer', b'4 bytes'), (b'Offset', b'8 bytes'),
        (b'Dumped from database version', archive.remote_version),
        (b'Dumped by pg_dump version', archive.dump_version),
    )
    for name, value in fields:
        budget.check()
        lines.exact(b';     ' + name + b': ' + value)
    for value in (b';', b';', b'; Selected TOC Entries:', b';'):
        lines.exact(value)
    expected = render_entries(archive, budget)
    require(len(raw) - lines.pos == len(expected), 'list_entries_mismatch')
    for start in range(0, len(expected), 65536):
        budget.check()
        require(memoryview(raw)[lines.pos + start:lines.pos + start + 65536]
                == memoryview(expected)[start:start + 65536], 'list_entries_mismatch')
    budget.check()
    return {'verboseListEntriesBytes': len(expected), 'timestampLineSha256': budget.digest(timestamp)}


def shape_counts(archive, budget):
    budget.check()
    descriptors = dict.fromkeys(DESCRIPTORS, 0)
    fields = {name: {'null': 0, 'empty': 0, 'present': 0} for name in NULLABLE_FIELDS}
    unknown = dependencies = 0
    for entry in archive.entries:
        budget.check()
        label = DESCRIPTOR_LABELS.get(entry.description)
        if label is None:
            unknown += 1
        else:
            descriptors[label] += 1
        dependencies += len(entry.dependencies)
        for name in NULLABLE_FIELDS:
            budget.check()
            value = getattr(entry, name)
            fields[name]['null' if value is None else 'empty' if value == b'' else 'present'] += 1
    budget.check()
    return {'descriptorCounts': descriptors, 'unknownDescriptorCount': unknown,
            'nullableFieldCounts': fields, 'dependencies': dependencies}


def inspect(raw, verbose_list, deadline):
    budget = Budget(deadline)
    archive = decode(raw, budget)
    compared = compare_list(archive, verbose_list, budget)
    summary = {
        'schema': 'raw-toc-metadata-prefix-v1', 'status': 'metadata_and_list_verified',
        'archiveBytes': len(raw), 'archiveSha256': budget.digest(raw),
        'metadataBytes': archive.metadata_end,
        'metadataSha256': budget.digest(memoryview(raw)[:archive.metadata_end]),
        'inventorySha256': budget.digest(memoryview(raw)[archive.header_end:archive.metadata_end]),
        'verboseListBytes': len(verbose_list), 'verboseListSha256': budget.digest(verbose_list),
        'rows': len(archive.entries), **shape_counts(archive, budget),
        'compressionAlgorithm': archive.compression, 'headerBytes': archive.header_end,
        'metadataPrefixOnly': True, 'dataSuffixValidated': False,
        'completeLedgerAccepted': False, 'S0Accepted': False,
        'actualImageEquivalent': False, 'recoveryAccepted': False, **compared,
    }
    budget.check()
    return archive, summary
