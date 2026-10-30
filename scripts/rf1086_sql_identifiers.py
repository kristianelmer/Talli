"""Private PG17.6 spelling prerequisite; no SQL/ledger/runtime acceptance.

Profile: UTF8, default quoting, exact bytes without NUL/CR/LF. The caller
must bind producer options and apply its own cumulative/scanner gates.
"""
import codecs
import re
import time

MAX_COMPONENT = 16384
MAX_IDENTIFIER = 32770
MAX_QUALIFIED = 65541
MAX_CONNECT = 32780
CHUNK = 4096
CONT = re.compile(rb'[a-z0-9_]+')
CONNECT = re.compile(rb'[A-Za-z0-9_.]+')
SOURCE_KEYWORDS_SHA256 = '8fa117aec8410d483c9fb9e711b1fea7cefc4acc1483c13af40fd24cbd4470bf'
# All COL_NAME, TYPE_FUNC_NAME and RESERVED entries from the pinned source.
FORCE_QUOTE = frozenset((
    b'all',
    b'analyse',
    b'analyze',
    b'and',
    b'any',
    b'array',
    b'as',
    b'asc',
    b'asymmetric',
    b'authorization',
    b'between',
    b'bigint',
    b'binary',
    b'bit',
    b'boolean',
    b'both',
    b'case',
    b'cast',
    b'char',
    b'character',
    b'check',
    b'coalesce',
    b'collate',
    b'collation',
    b'column',
    b'concurrently',
    b'constraint',
    b'create',
    b'cross',
    b'current_catalog',
    b'current_date',
    b'current_role',
    b'current_schema',
    b'current_time',
    b'current_timestamp',
    b'current_user',
    b'dec',
    b'decimal',
    b'default',
    b'deferrable',
    b'desc',
    b'distinct',
    b'do',
    b'else',
    b'end',
    b'except',
    b'exists',
    b'extract',
    b'false',
    b'fetch',
    b'float',
    b'for',
    b'foreign',
    b'freeze',
    b'from',
    b'full',
    b'grant',
    b'greatest',
    b'group',
    b'grouping',
    b'having',
    b'ilike',
    b'in',
    b'initially',
    b'inner',
    b'inout',
    b'int',
    b'integer',
    b'intersect',
    b'interval',
    b'into',
    b'is',
    b'isnull',
    b'join',
    b'json',
    b'json_array',
    b'json_arrayagg',
    b'json_exists',
    b'json_object',
    b'json_objectagg',
    b'json_query',
    b'json_scalar',
    b'json_serialize',
    b'json_table',
    b'json_value',
    b'lateral',
    b'leading',
    b'least',
    b'left',
    b'like',
    b'limit',
    b'localtime',
    b'localtimestamp',
    b'merge_action',
    b'national',
    b'natural',
    b'nchar',
    b'none',
    b'normalize',
    b'not',
    b'notnull',
    b'null',
    b'nullif',
    b'numeric',
    b'offset',
    b'on',
    b'only',
    b'or',
    b'order',
    b'out',
    b'outer',
    b'overlaps',
    b'overlay',
    b'placing',
    b'position',
    b'precision',
    b'primary',
    b'real',
    b'references',
    b'returning',
    b'right',
    b'row',
    b'select',
    b'session_user',
    b'setof',
    b'similar',
    b'smallint',
    b'some',
    b'substring',
    b'symmetric',
    b'system_user',
    b'table',
    b'tablesample',
    b'then',
    b'time',
    b'timestamp',
    b'to',
    b'trailing',
    b'treat',
    b'trim',
    b'true',
    b'union',
    b'unique',
    b'user',
    b'using',
    b'values',
    b'varchar',
    b'variadic',
    b'verbose',
    b'when',
    b'where',
    b'window',
    b'with',
    b'xmlattributes',
    b'xmlconcat',
    b'xmlelement',
    b'xmlexists',
    b'xmlforest',
    b'xmlnamespaces',
    b'xmlparse',
    b'xmlpi',
    b'xmlroot',
    b'xmlserialize',
    b'xmltable',
))


class Unavailable(ValueError):
    def __init__(self):
        super().__init__('identifier_rendering_unavailable')


def require(test):
    if not test:
        raise Unavailable()


class _Renderer:
    def __init__(self, deadline):
        require(type(deadline) in (int, float))
        now = time.monotonic()
        require(now < deadline <= now + 5)
        self.deadline = deadline

    def check(self):
        require(time.monotonic() < self.deadline)

    def validate(self, raw):
        self.check()
        require(type(raw) is bytes and 0 < len(raw) <= MAX_COMPONENT)
        plain = raw[0] == 95 or 97 <= raw[0] <= 122
        decoder = codecs.getincrementaldecoder('utf-8')('strict')
        try:
            for start in range(0, len(raw), CHUNK):
                self.check()
                chunk = raw[start:start + CHUNK]
                require(b'\0' not in chunk and b'\r' not in chunk and b'\n' not in chunk)
                decoder.decode(chunk, final=False)
                plain = plain and CONT.fullmatch(chunk) is not None
                self.check()
            decoder.decode(b'', final=True)
        except UnicodeDecodeError:
            raise Unavailable() from None
        self.check()
        return plain and (len(raw) > 17 or raw not in FORCE_QUOTE)

    def format(self, raw, plain):
        self.check()
        if plain:
            return raw
        require(2 * len(raw) + 2 <= MAX_IDENTIFIER)
        output = bytearray(b'"')
        for start in range(0, len(raw), CHUNK):
            self.check()
            output.extend(raw[start:start + CHUNK].replace(b'"', b'""'))
            self.check()
        output.extend(b'"')
        require(len(output) <= MAX_IDENTIFIER)
        result = bytes(output)
        self.check()
        return result

    def component(self, raw):
        return self.format(raw, self.validate(raw))


def identifier(name, *, deadline):
    return _Renderer(deadline).component(name)


def qualified(schema_or_none, name, *, deadline):
    renderer = _Renderer(deadline)
    if schema_or_none is None:
        return renderer.component(name)
    schema = renderer.component(schema_or_none)
    rendered = renderer.component(name)
    require(len(schema) + len(rendered) + 1 <= MAX_QUALIFIED)
    renderer.check()
    result = schema + b'.' + rendered
    renderer.check()
    return result


def simple_connect(database, *, deadline):
    renderer = _Renderer(deadline)
    plain = renderer.validate(database)
    for start in range(0, len(database), CHUNK):
        renderer.check()
        require(CONNECT.fullmatch(database[start:start + CHUNK]) is not None)
        renderer.check()
    rendered = renderer.format(database, plain)
    require(len(rendered) + 10 <= MAX_CONNECT)
    renderer.check()
    result = b'\\connect ' + rendered + b'\n'
    renderer.check()
    return result
