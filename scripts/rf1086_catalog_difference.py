"""Bounded catalog diagnostics; never an alternate recovery acceptance rule."""
import hashlib
import json
import sys

MAX_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 20_000
MAX_DETAILS = 32
MAX_OUTPUT_BYTES = 16 * 1024
_TAG = 'owned_identity_catalog_difference '

_LAYOUTS = {
    'schema': (2, ('owner', 'acl')),
    'relation': (3, ('kind', 'owner', 'acl', 'rls', 'force_rls')),
    'function': (4, ('owner', 'acl', 'security_definer', 'configuration')),
    'default_acl': (4, ('acl',)),
    'column_acl': (4, ('acl',)),
    'policy': (4, ('command', 'permissive', 'roles', 'using', 'with_check')),
}
_ROW_TYPES = {
    'schema': ('text', 'nullable_text'),
    'relation': ('text', 'text', 'nullable_text', 'boolean', 'boolean'),
    'function': ('text', 'nullable_text', 'boolean', 'nullable_text'),
    'default_acl': ('text',),
    'column_acl': ('text',),
    'policy': ('text', 'boolean', 'nullable_text_array', 'nullable_text', 'nullable_text'),
}
_DATABASE_FIELDS = frozenset((
    'datname', 'encoding', 'datlocprovider', 'datistemplate', 'datallowconn',
    'dathasloginevt', 'datconnlimit', 'datcollate', 'datctype', 'datlocale',
    'daticulocale', 'daticurules', 'datcollversion', 'datacl', 'owner', 'tablespace',
))
_SCHEMAS = frozenset((
    'public', 'auth', 'storage', 'extensions', 'graphql', 'graphql_public',
    'realtime', 'supabase_functions', 'net', 'vault', 'pgsodium', 'pgsodium_masks',
    'pgbouncer', 'cron', 'backend_system', 'billing', 'banking', 'documents',
    'ledger', 'governance', 'company_access', 'authority_connections',
    'shareholder_register_filing', 'company_tax', 'annual_accounts',
))


class CatalogCapture:
    """Retain only the exact, bounded bytes already used by fingerprint()."""
    def __init__(self):
        self._raw = None

    def capture(self, raw):
        self._raw = raw if type(raw) is bytes and len(raw) <= MAX_CAPTURE_BYTES else None

    def clear(self):
        self._raw = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.clear()


def _encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('catalog_diagnostic_unavailable')
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError('catalog_diagnostic_unavailable')


def _bounded_value(value, depth=0):
    if depth > 5:
        raise ValueError('catalog_diagnostic_unavailable')
    if value is None or type(value) in (bool, int):
        return
    if type(value) is str and len(value.encode('utf-8')) <= 64 * 1024:
        return
    if type(value) is list and len(value) <= MAX_RECORDS:
        for item in value:
            _bounded_value(item, depth + 1)
        return
    if type(value) is dict and len(value) <= 64:
        for key, item in value.items():
            _bounded_value(key, depth + 1)
            _bounded_value(item, depth + 1)
        return
    raise ValueError('catalog_diagnostic_unavailable')


def _typed(value, expected):
    if expected.startswith('nullable_'):
        if value is None:
            return True
        expected = expected.removeprefix('nullable_')
    if expected == 'text_array':
        return type(value) is list and all(type(item) is str for item in value)
    return type(value) is {'text': str, 'boolean': bool, 'integer': int}[expected]


def _records(capture):
    raw = capture._raw
    if type(raw) is not bytes or len(raw) > MAX_CAPTURE_BYTES:
        raise ValueError('catalog_diagnostic_unavailable')
    lines = raw.decode('utf-8').removesuffix('\n').split('\n')
    if len(lines) != 3:
        raise ValueError('catalog_diagnostic_unavailable')
    rows, database, settings = [json.loads(line, object_pairs_hook=_object,
        parse_constant=_reject_constant) for line in lines]
    if (type(rows) is not list or type(database) is not dict or type(settings) is not list
            or len(rows) + len(settings) + 1 > MAX_RECORDS):
        raise ValueError('catalog_diagnostic_unavailable')
    records = {}

    def add(kind, identity, fields, schema=None):
        _bounded_value(identity)
        _bounded_value(fields)
        key = _encoded(identity)
        if key in records:
            raise ValueError('catalog_diagnostic_unavailable')
        records[key] = (kind, schema if schema in _SCHEMAS else 'unclassified', fields)

    for row in rows:
        if type(row) is not list or not row or type(row[0]) is not str or row[0] not in _LAYOUTS:
            raise ValueError('catalog_diagnostic_unavailable')
        split, names = _LAYOUTS[row[0]]
        if len(row) != split + len(names):
            raise ValueError('catalog_diagnostic_unavailable')
        for index, value in enumerate(row[1:split], 1):
            if not _typed(value, 'nullable_text' if row[0] == 'default_acl' and index == 2 else 'text'):
                raise ValueError('catalog_diagnostic_unavailable')
        if any(not _typed(value, expected) for value, expected in zip(row[split:], _ROW_TYPES[row[0]], strict=True)):
            raise ValueError('catalog_diagnostic_unavailable')
        schema = row[2] if row[0] == 'default_acl' else row[1]
        add(row[0], row[:split], dict(zip(names, row[split:], strict=True)), schema)
    for field, value in database.items():
        if field not in _DATABASE_FIELDS:
            continue
        expected = ('boolean' if field in ('datistemplate', 'datallowconn', 'dathasloginevt') else
                    'integer' if field in ('encoding', 'datconnlimit') else
                    'nullable_text_array' if field == 'datacl' else
                    'nullable_text' if field in ('datlocale', 'daticulocale', 'daticurules', 'datcollversion') else 'text')
        if not _typed(value, expected):
            raise ValueError('catalog_diagnostic_unavailable')
    add('database', ['database'], database)
    for row in settings:
        if (type(row) is not list or len(row) != 3
                or any(type(v) is not str for v in row[:2])
                or type(row[2]) is not list or any(type(v) is not str for v in row[2])):
            raise ValueError('catalog_diagnostic_unavailable')
        add('database_role_setting', ['database_role_setting', *row[:2]], {'settings': row[2]})
    return records


def _change(before, after):
    if before is None:
        return 'source-null'
    if after is None:
        return 'target-null'
    if (type(before) is list and type(after) is list
            and sorted(map(_encoded, before)) == sorted(map(_encoded, after))):
        return 'array-order-only'
    return 'value'


def catalog_difference(source, target):
    """Only closed labels/counts/identity hashes escape; all values stay private."""
    before, after = _records(source), _records(target)
    counts = {'changed': 0, 'source-only': 0, 'target-only': 0}
    details = []
    for key in sorted(before.keys() | after.keys()):
        left, right = before.get(key), after.get(key)
        kind, schema, _ = left or right
        changes = []
        if left is None:
            status = 'target-only'
        elif right is None:
            status = 'source-only'
        else:
            for name in sorted(left[2].keys() | right[2].keys()):
                old, new = left[2].get(name), right[2].get(name)
                if name in left[2] and name in right[2] and _encoded(old) == _encoded(new):
                    continue
                label = name if kind != 'database' or name in _DATABASE_FIELDS else 'unclassified'
                state = ('source-field-missing' if name not in left[2] else
                         'target-field-missing' if name not in right[2] else _change(old, new))
                changes.append({'field': label, 'change': state})
            if not changes:
                continue
            status = 'changed'
        counts[status] += 1
        if len(details) < MAX_DETAILS:
            details.append({'kind': kind, 'schema': schema,
                'identitySha256': hashlib.sha256(key).hexdigest(),
                'status': status, 'fields': changes})
    changed = sum(counts.values())
    result = {'status': 'different' if changed else 'representation-only' if source._raw != target._raw else 'equal',
        'sourceRecords': len(before), 'targetRecords': len(after), 'counts': counts,
        'details': details, 'truncated': changed > len(details),
        'qualification': 'diagnostic-only-strict-fingerprint-unchanged'}
    while len(_encoded(result)) + len(_TAG) + 1 > MAX_OUTPUT_BYTES and details:
        details.pop()
        result['truncated'] = True
    if len(_encoded(result)) + len(_TAG) + 1 > MAX_OUTPUT_BYTES:
        raise ValueError('catalog_diagnostic_unavailable')
    return result


def emit_catalog_difference(source, target):
    """Diagnostic failure must not replace the owning recovery failure."""
    try:
        try:
            result = catalog_difference(source, target)
        except Exception:
            result = {'status': 'unavailable', 'qualification': 'diagnostic-only-strict-fingerprint-unchanged'}
        try:
            print(_TAG + _encoded(result).decode('utf-8'), file=sys.stderr)
        except Exception:
            pass
    finally:
        source.clear()
        target.clear()
