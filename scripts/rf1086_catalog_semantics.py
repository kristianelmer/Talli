"""Read-only, bounded evidence for a rejected restore; never acceptance logic."""
import hashlib
import json
import os
import re
import selectors
import subprocess
import sys
import time

from psycopg import sql

from rf1086_catalog_difference import _encoded, _object, _records, _reject_constant

MAX_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024
MAX_SELECTED = 512
TAG = 'owned_identity_catalog_semantics '
QUALIFICATION = 'diagnostic-only-strict-fingerprint-unchanged'
NET_IDENTITIES = (
    ['function', 'net', 'http_get', 'url text, params jsonb, headers jsonb, timeout_milliseconds integer'],
    ['function', 'net', 'http_post', 'url text, body jsonb, params jsonb, headers jsonb, timeout_milliseconds integer'],
)
NET_TYPES = (['text', 'jsonb', 'jsonb', 'int4'], ['text', 'jsonb', 'jsonb', 'jsonb', 'int4'])
TOC_SIGNATURES = ('http_get(text, jsonb, jsonb, integer)',
                  'http_post(text, jsonb, jsonb, jsonb, integer)')


def _unavailable():
    raise ValueError('catalog_semantics_unavailable')


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        _unavailable()
    return remaining


def _command(args, deadline, *, data=None, archive=None):
    """Drain both pipes concurrently; no threads, raw errors or unbounded wait."""
    _remaining(deadline)
    process = None
    selector = None
    output = bytearray()
    error_bytes = 0
    pending = memoryview(data or b'')
    try:
        selector = selectors.DefaultSelector()
        process = subprocess.Popen(args, stdin=archive if archive is not None else subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for stream in (process.stdout, process.stderr):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        if archive is None:
            if pending:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE)
            else:
                process.stdin.close()
        while selector.get_map():
            for key, _ in selector.select(min(_remaining(deadline), 0.1)):
                stream = key.fileobj
                if stream is process.stdin:
                    written = os.write(stream.fileno(), pending[:65536])
                    pending = pending[written:]
                    if not pending:
                        selector.unregister(stream)
                        stream.close()
                    continue
                chunk = os.read(stream.fileno(), 65536)
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                elif stream is process.stdout:
                    if len(output) + len(chunk) > MAX_BYTES:
                        _unavailable()
                    output.extend(chunk)
                else:
                    error_bytes += len(chunk)
                    if error_bytes > 65536:
                        _unavailable()
        if process.wait(timeout=_remaining(deadline)):
            _unavailable()
        return bytes(output)
    finally:
        primary = sys.exception()
        cleanup_errors = []
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
            except BaseException as error:
                cleanup_errors.append(error)
            try:
                process.wait(timeout=1)
            except BaseException as error:
                cleanup_errors.append(error)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except BaseException as error:
                        cleanup_errors.append(error)
        if selector is not None:
            try:
                selector.close()
            except BaseException as error:
                cleanup_errors.append(error)
        # Never turn user cancellation into an Exception the emitter shields.
        if primary is not None and not isinstance(primary, Exception):
            raise primary
        for error in cleanup_errors:
            if not isinstance(error, Exception):
                raise error
        if cleanup_errors:
            raise cleanup_errors[0]


def _statement(identities):
    """Only pg_catalog reads; live rows bind the expansion to retained bytes."""
    wanted = sql.Literal(json.dumps(identities, ensure_ascii=False)).as_string()
    return ("BEGIN READ ONLY; SET LOCAL statement_timeout='5s'; "
            "SET LOCAL lock_timeout='1s'; SET LOCAL search_path=pg_catalog;\n" + """
WITH wanted AS (SELECT value AS identity FROM jsonb_array_elements(WANTED::jsonb)),
objects AS (
 SELECT jsonb_build_array('schema',n.nspname) AS identity,
 jsonb_build_array('schema',n.nspname,pg_get_userbyid(n.nspowner),n.nspacl::text) AS row,
 n.nspowner AS owner,n.nspacl AS acl,'n'::"char" AS acltype
 FROM pg_namespace n
 UNION ALL
 SELECT jsonb_build_array('relation',n.nspname,c.relname),
 jsonb_build_array('relation',n.nspname,c.relname,c.relkind,pg_get_userbyid(c.relowner),
 c.relacl::text,c.relrowsecurity,c.relforcerowsecurity),c.relowner,c.relacl,
 CASE WHEN c.relkind IN ('r','p','v','m','f') THEN 'r'::"char"
 WHEN c.relkind='S' THEN 's'::"char" ELSE NULL END
 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
), selected AS (
 SELECT o.*, CASE WHEN acltype IS NOT NULL THEN acldefault(acltype,owner) END AS defaults
 FROM objects o JOIN wanted w USING(identity)
), acls AS (
 SELECT s.identity,s.row,s.defaults::text AS defaults,
 (SELECT coalesce(jsonb_agg(jsonb_build_array(g.rolname,a.grantee=0,r.rolname,
 a.privilege_type,a.is_grantable)),'[]'::jsonb)
 FROM aclexplode(s.defaults) a LEFT JOIN pg_roles g ON g.oid=a.grantor
 LEFT JOIN pg_roles r ON r.oid=a.grantee) AS default_grants,
 (SELECT coalesce(jsonb_agg(jsonb_build_array(g.rolname,a.grantee=0,r.rolname,
 a.privilege_type,a.is_grantable)),'[]'::jsonb)
 FROM aclexplode(coalesce(s.acl,s.defaults)) a LEFT JOIN pg_roles g ON g.oid=a.grantor
 LEFT JOIN pg_roles r ON r.oid=a.grantee) AS grants
 FROM selected s
), functions AS (
 SELECT w.identity,
 jsonb_build_array('function',n.nspname,p.proname,pg_get_function_identity_arguments(p.oid),
 pg_get_userbyid(p.proowner),p.proacl::text,p.prosecdef,p.proconfig::text) AS row,
 (SELECT coalesce(jsonb_agg(jsonb_build_array(e.extname,e.extversion,
 pg_get_userbyid(e.extowner))),'[]'::jsonb)
 FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
 WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.objsubid=0
 AND d.refclassid='pg_extension'::regclass AND d.deptype='e') AS extensions,
 (SELECT coalesce(jsonb_agg(jsonb_build_array(tn.nspname,t.typname) ORDER BY a.ordinality),'[]'::jsonb)
 FROM unnest(p.proargtypes) WITH ORDINALITY a(type_oid,ordinality)
 JOIN pg_type t ON t.oid=a.type_oid JOIN pg_namespace tn ON tn.oid=t.typnamespace) AS types,
 pg_get_functiondef(p.oid) AS definition
 FROM wanted w JOIN pg_namespace n ON n.nspname=w.identity->>1
 JOIN pg_proc p ON p.pronamespace=n.oid AND p.proname=w.identity->>2
 AND pg_get_function_identity_arguments(p.oid)=w.identity->>3
 WHERE w.identity->>0='function'
)
SELECT jsonb_build_object('serverVersion',current_setting('server_version_num')::integer,
 'acls',(SELECT coalesce(jsonb_agg(to_jsonb(a)),'[]'::jsonb) FROM acls a),
 'functions',(SELECT coalesce(jsonb_agg(to_jsonb(f)),'[]'::jsonb) FROM functions f));
ROLLBACK;
""".replace('WANTED', wanted)).encode()


def _read(container, statement, deadline, *, target=False):
    args = ['docker', 'exec', '-i', container, 'psql', '-U', 'supabase_admin']
    if target:
        args += ['-h', '/tmp']
    args += ['--dbname', 'postgres', '-XqAt', '-v', 'ON_ERROR_STOP=1']
    raw = _command(args, deadline, data=statement)
    result = json.loads(raw, object_pairs_hook=_object, parse_constant=_reject_constant)
    if (type(result) is not dict or set(result) != {'serverVersion', 'acls', 'functions'}
            or type(result['serverVersion']) is not int
            or not 100000 <= result['serverVersion'] <= 999999
            or type(result['acls']) is not list or type(result['functions']) is not list):
        _unavailable()
    return result


def _selected(source, target):
    before, after = _records(source), _records(target)
    if before.keys() != after.keys():
        _unavailable()
    selected = []
    for key, (kind, _, fields) in sorted(before.items()):
        recovered = after[key][2]
        if kind in ('schema', 'relation') and fields['acl'] is not None and recovered['acl'] is None:
            if fields['owner'] != recovered['owner']:
                _unavailable()
            selected.append(json.loads(key))
    if len(selected) > MAX_SELECTED:
        _unavailable()
    return before, after, selected


def _bound_rows(rows, expected, identities):
    result = {}
    for item in rows:
        if type(item) is not dict or 'identity' not in item or 'row' not in item:
            _unavailable()
        key = _encoded(item['identity'])
        if key not in expected or key in result:
            _unavailable()
        _, _, fields = expected[key]
        if _encoded(item['row']) != _encoded(item['identity'] + list(fields.values())):
            _unavailable()
        result[key] = item
    if set(result) != {_encoded(identity) for identity in identities}:
        _unavailable()
    return result


def _grants(value):
    if type(value) is not list or len(value) > 20000:
        _unavailable()
    for row in value:
        if (type(row) is not list or len(row) != 5 or type(row[0]) is not str
                or type(row[1]) is not bool or type(row[3]) is not str or type(row[4]) is not bool
                or (row[2] is not None if row[1] else type(row[2]) is not str)):
            _unavailable()
    # Canonical bytes preserve duplicate tuples and distinguish PUBLIC from a role named PUBLIC.
    return sorted(_encoded(row) for row in value)


def _acl_report(before, after, identities, source, target):
    left = _bound_rows(source['acls'], before, identities)
    right = _bound_rows(target['acls'], after, identities)
    counts = dict.fromkeys(('rawDefaultEqual', 'defaultGrantsEqual', 'targetGrantsEqual',
                           'different', 'unsupported'), 0)
    rows = []
    for key in sorted(left):
        old, new = left[key], right[key]
        digest = hashlib.sha256(key).hexdigest()
        if old.get('defaults') is None or new.get('defaults') is None:
            counts['unsupported'] += 1
            rows.append([digest, 'unsupported'])
            continue
        if type(old['defaults']) is not str or type(new['defaults']) is not str:
            _unavailable()
        raw_equal = before[key][2]['acl'] == old['defaults']
        default_equal = _grants(old['grants']) == _grants(old['default_grants'])
        target_equal = _grants(old['grants']) == _grants(new['grants'])
        # Verify the target's NULL expansion really agrees with its own default.
        if _grants(new['grants']) != _grants(new['default_grants']):
            _unavailable()
        for name, equal in zip(('rawDefaultEqual', 'defaultGrantsEqual', 'targetGrantsEqual'),
                               (raw_equal, default_equal, target_equal), strict=True):
            counts[name] += int(equal)
        counts['different'] += int(not default_equal or not target_equal)
        rows.append([digest, raw_equal, default_equal, target_equal])
    rows.sort(key=lambda row: row[0])
    return {'status': 'observed', 'selected': len(rows), 'counts': counts,
            'identitySetSha256': hashlib.sha256(_encoded([row[0] for row in rows])).hexdigest(),
            'rows': rows, 'rowFields': ['identitySha256', 'rawDefaultEqual', 'defaultGrantsEqual', 'targetGrantsEqual'],
            'scope': 'expanded-acl-grants-not-complete-authorization'}


def _net_report(before, after, source, target):
    left = _bound_rows(source['functions'], before, NET_IDENTITIES)
    right = _bound_rows(target['functions'], after, NET_IDENTITIES)
    rows = []
    for index, identity in enumerate(NET_IDENTITIES):
        key = _encoded(identity)
        item = {'identitySha256': hashlib.sha256(key).hexdigest()}
        for side, observed in [('source', left[key]), ('target', right[key])]:
            if observed.get('types') != [['pg_catalog', name] for name in NET_TYPES[index]]:
                _unavailable()
            extensions = observed.get('extensions')
            if type(extensions) is not list or len(extensions) > 1:
                _unavailable()
            version = None
            if extensions:
                ext = extensions[0]
                if (type(ext) is not list or len(ext) != 3 or ext[0] != 'pg_net'
                        or type(ext[1]) is not str or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}', ext[1])
                        or len(ext[1]) > 32 or type(ext[2]) is not str):
                    _unavailable()
                version = ext[1]
            definition = observed.get('definition')
            if type(definition) is not str or len(definition.encode()) > 65536:
                _unavailable()
            fields = (before if side == 'source' else after)[key][2]
            item[side] = {'extensionMember': bool(extensions), 'extensionVersion': version,
                          'securityDefiner': fields['security_definer'],
                          'configurationNull': fields['configuration'] is None,
                          'configurationIsSearchPathNet': fields['configuration'] == '{search_path=net}',
                          'configurationSha256': hashlib.sha256(_encoded(fields['configuration'])).hexdigest(),
                          'definitionSha256': hashlib.sha256(definition.encode()).hexdigest()}
        rows.append(item)
    return {'status': 'observed', 'observation': 'after-restore-not-proof-of-pre-dump-state', 'functions': rows}


def _toc_report(raw, owners):
    lines = raw.decode('utf-8').splitlines()
    if not raw.endswith(b'\n') or len(lines) > 40032 or any(len(line.encode()) > 65536 for line in lines):
        _unavailable()
    versions = {}
    declared_count = None
    custom_format = False
    selected = False
    counts = [0, 0]
    extensions = 0
    entries = set()
    for line in lines:
        if line.startswith(';'):
            if line == '; Selected TOC Entries:':
                if selected or declared_count is None or not custom_format or len(versions) != 2:
                    _unavailable()
                selected = True
                continue
            if selected:
                if line != ';' and not re.fullmatch(r';[ \t]*depends on:(?: [0-9]+)*', line):
                    _unavailable()
                continue
            count = re.fullmatch(r';\s+TOC Entries: ([0-9]{1,5})', line)
            if count:
                if declared_count is not None or not 1 <= int(count[1]) <= 20000:
                    _unavailable()
                declared_count = int(count[1])
                continue
            format_line = re.fullmatch(r';\s+Format: (\S+)', line)
            if format_line:
                if custom_format or format_line[1] != 'CUSTOM':
                    _unavailable()
                custom_format = True
                continue
            match = re.fullmatch(r';\s+Dumped (from database|by pg_dump) version: ([0-9]+(?:\.[0-9]+){1,2})(?: [^\r\n]*)?', line)
            if match:
                label = 'server' if match[1] == 'from database' else 'dump'
                if label in versions:
                    _unavailable()
                versions[label] = match[2]
            continue
        if not line.strip():
            continue
        match = re.fullmatch(r'([1-9][0-9]*); ([0-9]+) ([0-9]+) (.+)', line)
        if not selected or not match or match[1] in entries:
            _unavailable()
        entries.add(match[1])
        descriptor = match[4]
        if descriptor.startswith('EXTENSION - pg_net '):
            extensions += 1
        for i, signature in enumerate(TOC_SIGNATURES):
            prefix = 'FUNCTION net ' + signature + ' '
            if descriptor.startswith(prefix):
                if descriptor != prefix + owners[i] or match[2] != '1255':
                    _unavailable()
                counts[i] += 1
    if (not selected or len(entries) != declared_count or extensions > 1
            or any(count > 1 for count in counts)):
        _unavailable()
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'archiveTimeVersions': versions,
            'completeTocEntries': declared_count,
            'pgNetExtensionEntries': extensions, 'functionDefinitionEntries': counts,
            'scope': 'toc-membership-only-no-alter-absence-or-bootstrap-attribution'}


def _archive_report(archive, source, target, before, deadline):
    position = archive.tell()
    digest, total = hashlib.sha256(), 0
    try:
        archive.seek(0)
        while chunk := archive.read(65536):
            _remaining(deadline)
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES:
                _unavailable()
            digest.update(chunk)
        versions = {}
        for label, container, program in [('dump', source, 'pg_dump'), ('restore', target, 'pg_restore')]:
            raw = _command(['docker', 'exec', container, program, '--version'], deadline)
            match = re.fullmatch(rb'pg_(?:dump|restore) \(PostgreSQL\) ([0-9]+(?:\.[0-9]+){1,2})(?: [^\r\n]*)?\n?', raw)
            if not match:
                _unavailable()
            versions[label] = match[1].decode()
        owners = [before[_encoded(identity)][2]['owner'] for identity in NET_IDENTITIES]
        if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', owner) for owner in owners):
            _unavailable()
        archive.seek(0)
        # Verbose includes special/unselected records, so tocCount proves completeness.
        toc = _command(['docker', 'exec', '-i', target, 'pg_restore', '--list', '--verbose'], deadline, archive=archive)
        return {'status': 'observed', 'sha256': digest.hexdigest(), 'bytes': total,
                'observedBinaryVersions': versions, 'toc': _toc_report(toc, owners)}
    finally:
        primary = sys.exception()
        try:
            archive.seek(position)
        except Exception:
            if primary is not None and not isinstance(primary, Exception):
                raise primary
            raise


def emit_catalog_semantics(source_catalog, target_catalog, *, source, target, image, dump):
    """Best effort; existing emitter owns capture clearing and strict failure."""
    result = {'status': 'unavailable', 'qualification': QUALIFICATION}
    try:
        if (not all(re.fullmatch(r'[a-f0-9]{64}', value) for value in (source, target))
                or source == target or not re.fullmatch(r'sha256:[a-f0-9]{64}', image)):
            _unavailable()
        deadline = time.monotonic() + 15
        before, after, selected = _selected(source_catalog, target_catalog)
        functions = [identity for identity in NET_IDENTITIES if _encoded(identity) in before]
        statement = _statement(selected + functions)
        if len(statement) > MAX_BYTES:
            _unavailable()
        left = _read(source, statement, deadline)
        right = _read(target, statement, deadline, target=True)
        acl = _acl_report(before, after, selected, left, right)
        try:
            net = _net_report(before, after, left, right)
            archive = _archive_report(dump, source, target, before, deadline)
        except Exception:
            net, archive = {'status': 'unavailable'}, {'status': 'unavailable'}
        result = {'status': 'observed', 'qualification': QUALIFICATION,
                  'sourceCatalogSha256': hashlib.sha256(source_catalog._raw).hexdigest(),
                  'targetCatalogSha256': hashlib.sha256(target_catalog._raw).hexdigest(),
                  'image': image, 'serverVersionsObservedAfterRestore': [left['serverVersion'], right['serverVersion']],
                  'acl': acl, 'net': net, 'archive': archive}
        if len(_encoded(result)) + len(TAG) + 1 > MAX_OUTPUT_BYTES:
            _unavailable()
    except Exception:
        result = {'status': 'unavailable', 'qualification': QUALIFICATION}
    try:
        print(TAG + _encoded(result).decode(), file=sys.stderr)
    except Exception:
        pass
