"""Captured policy comparison and private handoff custody; no owner execution.

Request hashes are independently held authority, not acknowledgements from an
owner connection. Callers coordinate the prepared DB marker and target lock.
"""
import os
from pathlib import Path
import re
import stat
from uuid import UUID

from talli_backend.adapters.hosted_recovery_capture import digest, encoded, json_bytes, require
from talli_backend.adapters.hosted_recovery_sql import bounded_native_preamble, sql_without_psql_framing

FORMAT = 'talli-original-owner-policy-request-v1'
MAX_SQL = 4 * 1024**2
MAX_MANIFEST = 64 * 1024
MAX_POLICIES = 512
FILES = frozenset({'request.json', 'policies.sql'})
SCHEMAS = frozenset({'auth', 'storage'})
ERROR = 'hosted_owner_policy_'


def _check(condition, suffix='invalid'):
    require(condition, ERROR + suffix)


def _name(value):
    _check(isinstance(value, str) and re.fullmatch('[a-z_][a-z_0-9]{0,62}', value))
    return value


def _sha(value):
    _check(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value))
    return value


def _catalog(catalog):
    _check(isinstance(catalog, dict) and {'policies', 'rls'} <= set(catalog))
    result = {'policies': {}, 'rls': {}}
    for category, size in (('policies', 8), ('rls', 5)):
        rows = catalog[category]
        _check(isinstance(rows, (list, tuple)) and len(rows) <= 4096)
        for row in rows:
            _check(isinstance(row, (list, tuple)) and len(row) == size)
            _check(isinstance(row[0], str))
            if row[0] not in SCHEMAS:
                continue
            schema, table = _name(row[0]), _name(row[1])
            if category == 'policies':
                name = _name(row[2])
                _check(isinstance(row[3], str) and row[3].upper() in ('PERMISSIVE', 'RESTRICTIVE'))
                _check(isinstance(row[4], (list, tuple)) and 1 <= len(row[4]) <= 256)
                roles = [_name('public' if r == 'PUBLIC' else r) for r in row[4]]
                _check(len(set(roles)) == len(roles))
                _check(isinstance(row[5], str) and row[5].upper() in
                    ('ALL', 'SELECT', 'INSERT', 'UPDATE', 'DELETE'))
                _check(all(v is None or isinstance(v, str) and len(v.encode()) <= MAX_SQL
                    and '\x00' not in v for v in row[6:]))
                identity = (schema, table, name)
                value = [schema, table, name, row[3].upper(), sorted(roles), row[5].upper(), *row[6:]]
            else:
                _check(type(row[2]) is bool and type(row[3]) is bool)
                identity = (schema, table)
                value = [schema, table, row[2], row[3], _name(row[4])]
            _check(identity not in result[category], 'duplicate_identity')
            result[category][identity] = value
    _check(len(result['policies']) <= MAX_POLICIES)
    for identity in result['policies']:
        _check(identity[:2] in result['rls'], 'rls_required')
    return result


def policy_status(capture, actual_catalog, *, allow_missing=False):
    """Return sorted missing (schema, table, policy) tuples; every other delta refuses.

    Roles are order independent; expressions remain exact PostgreSQL deparses.
    allow_missing relaxes only policy presence, never owners or RLS flags.
    """
    _check(type(allow_missing) is bool)
    wanted, actual = _catalog(capture.catalog), _catalog(actual_catalog)
    _check(not actual['policies'].keys() - wanted['policies'].keys(), 'unexpected_policy')
    for identity, value in actual['policies'].items():
        _check(value == wanted['policies'][identity], 'definition_changed')
    for identity in {key[:2] for key in wanted['policies']}:
        _check(actual['rls'].get(identity) == wanted['rls'][identity], 'rls_or_owner_changed')
    missing = tuple(sorted(wanted['policies'].keys() - actual['policies'].keys()))
    _check(allow_missing or not missing, 'missing')
    return missing


def _token(name):
    name = re.escape(_name(name))
    return '(?:"' + name + '"|' + name + ')'


def _trim_comments(text):
    lines = text.splitlines(keepends=True)
    start, end = 0, len(lines)
    while start < end and (not lines[start].strip() or lines[start].lstrip().startswith('--')):
        start += 1
    while start < end and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith('--')):
        end -= 1
    return ''.join(lines[start:end])


def _declaration(body, row):
    # Match one complete captured declaration, not semicolon-separated SQL.
    # Escaped captured expressions permit semicolons inside SQL string literals.
    schema, table, name, permissive, roles, cmd, qual, check = row
    pattern = r'CREATE POLICY ' + _token(name) + r' ON ' + _token(schema) + r'\.' + _token(table)
    pattern += r'(?: AS PERMISSIVE)?' if permissive == 'PERMISSIVE' else r' AS RESTRICTIVE'
    pattern += r'(?: FOR ALL)?' if cmd == 'ALL' else r' FOR ' + cmd
    role = r'(?:"[a-z_][a-z_0-9]{0,62}"|[a-z_][a-z_0-9]{0,62})'
    role_list = r' TO (?P<roles>' + role + r'(?:,\s*' + role + ')*)'
    pattern += '(?:' + role_list + ')?' if roles == ['public'] else role_list
    for keyword, expression in (('USING', qual), ('WITH CHECK', check)):
        if expression is not None:
            pattern += ' ' + keyword + r' \(' + re.escape(expression) + r'\)'
    match = re.fullmatch(pattern + r';\s*', body)
    _check(match is not None, 'sql_not_captured_policy')
    actual_roles = ['public'] if match['roles'] is None else [
        part.strip().strip('"') for part in match['roles'].split(',')]
    _check(sorted(actual_roles) == roles, 'sql_not_captured_policy')


def _policy_bytes(capture, program):
    catalog = _catalog(capture.catalog)
    raw = program.policies
    _check(isinstance(raw, bytes) and len(raw) <= MAX_SQL, 'sql_bound')
    if not raw:
        _check(not catalog['policies'], 'sql_inventory_changed')
        return b'', catalog
    raw = sql_without_psql_framing(bounded_native_preamble(raw))
    _check(not re.search(rb'(?m)^\s*\\', raw), 'sql_not_captured_policy')
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        _check(False, 'sql_not_captured_policy')
    headers = list(re.finditer(r'(?m)^-- Name: ([^\r\n]+); Type: POLICY; Schema: (auth|storage); Owner: ([^\r\n]*)$', text))
    first = re.search(r'(?m)^-- (?:Data for )?Name: ', text)
    _check((first is None and not headers and not catalog['policies']) or
        (headers and first.start() == headers[0].start()), 'sql_inventory_changed')
    declarations, seen = [], set()
    for index, header in enumerate(headers):
        candidates = [identity for identity in catalog['policies'] if identity[0] == header[2] and
            re.fullmatch(_token(identity[1]) + ' ' + _token(identity[2]), header[1])]
        _check(len(candidates) == 1, 'sql_inventory_changed')
        identity = candidates[0]
        _check(identity not in seen, 'sql_inventory_changed')
        seen.add(identity)
        owner = catalog['rls'][identity[:2]][4]
        _check(header[3] in (owner, '-'), 'sql_owner_changed')
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        body = _trim_comments(text[header.end():end])
        _declaration(body, catalog['policies'][identity])
        declarations.append(body)
    _check(seen == set(catalog['policies']), 'sql_inventory_changed')
    return ''.join(declarations).encode(), catalog


def policy_contract(capture, program):
    """Hash framing-free original native POLICY DDL; never grant execution authority."""
    body, catalog = _policy_bytes(capture, program)
    return _contract(body, catalog)


def _contract(body, catalog):
    return {'policySha256': digest(body), 'bytes': len(body),
        'owners': sorted({catalog['rls'][key[:2]][4] for key in catalog['policies']}),
        'policyIdentities': [list(key) for key in sorted(catalog['policies'])]}


def _uuid(value):
    _check(isinstance(value, str) and len(value) == 36)
    try:
        _check(str(UUID(value)) == value)
    except (ValueError, AttributeError):
        _check(False)


def _binding(value):
    _check(isinstance(value, dict) and set(value) == {'version', 'attemptId', 'planSha256',
        'captureSha256', 'preparedSha256', 'policySha256', 'target', 'targetIdentity'})
    _check(type(value['version']) is int and value['version'] == 1)
    _uuid(value['attemptId'])
    for key in ('planSha256', 'captureSha256', 'preparedSha256', 'policySha256'):
        _sha(value[key])
    target = value['target']
    _check(isinstance(target, dict) and set(target) == {'project', 'organization', 'name', 'region'})
    _check(all(isinstance(target[k], str) and re.fullmatch('[a-z]{20}', target[k])
        for k in ('project', 'organization')))
    _check(isinstance(target['name'], str) and 1 <= len(target['name']) <= 100 and
        not any(ord(c) < 32 for c in target['name']) and
        isinstance(target['region'], str) and re.fullmatch('[a-z]{2}-[a-z]+-[0-9]', target['region']))
    identity = value['targetIdentity']
    _check(isinstance(identity, dict) and set(identity) ==
        {'kind', 'target', 'systemIdentifier', 'database', 'databaseImage'})
    _check(identity['kind'] == 'owned-local-native-v2' and identity['database'] == 'postgres')
    _uuid(identity['target'])
    _check(isinstance(identity['systemIdentifier'], str) and
        re.fullmatch('[1-9][0-9]{0,19}', identity['systemIdentifier']) and
        int(identity['systemIdentifier']) < 2**64)
    _check(isinstance(identity['databaseImage'], str) and
        re.fullmatch('sha256:[a-f0-9]{64}', identity['databaseImage']))
    _check(len(encoded(value)) <= 16384)
    return json_bytes(encoded(value))


def _path(value):
    path = Path(value).absolute()
    _check(path == path.resolve() and not any(p.is_symlink() for p in (path, *path.parents)), 'path_invalid')
    return path


def _directory(path):
    info = path.lstat()
    _check(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and
        stat.S_IMODE(info.st_mode) == 0o700, 'directory_invalid')
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _same_directory(path, fd)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _same_directory(path, fd):
    before, after = os.fstat(fd), path.lstat()
    _check(stat.S_ISDIR(after.st_mode) and (before.st_dev, before.st_ino) == (after.st_dev, after.st_ino)
        and after.st_uid == os.getuid() and stat.S_IMODE(after.st_mode) == 0o700 and
        not any(p.is_symlink() for p in (path, *path.parents)), 'directory_changed')


def _read(fd, name, limit):
    member = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(member, 'rb') as source:
        info = os.fstat(source.fileno())
        _check(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= limit, 'file_invalid')
        raw = source.read(limit + 1)
        after = os.fstat(source.fileno())
        _check(len(raw) == info.st_size and len(raw) <= limit and
            (info.st_size, info.st_mtime_ns, info.st_ctime_ns) ==
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'file_changed')
        current = os.stat(name, dir_fd=fd, follow_symlinks=False)
        _check((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino), 'file_changed')
    return raw


def export_request(capture, program, prepared_binding, destination):
    """Create request.json + policies.sql once; return manifest, directory and pins.

    An existing complete exact request is read back against source-derived pins.
    Failures may leave a partial directory; it is never reused or overwritten.
    No private credential, owner executor or acknowledgement enters the request.
    """
    binding = _binding(prepared_binding)
    body, catalog = _policy_bytes(capture, program)
    contract = _contract(body, catalog)
    _check(binding['captureSha256'] == capture.commitment and
        binding['policySha256'] == contract['policySha256'], 'binding_changed')
    manifest = {'format': FORMAT, 'binding': binding, 'contract': contract,
        'policySha256': contract['policySha256']}
    raw = encoded(manifest)
    _check(len(raw) <= MAX_MANIFEST, 'manifest_bound')
    path = _path(destination)
    result = {**manifest, 'directory': str(path), 'manifestSha256': digest(raw),
        'requestSha256': digest(raw)}
    parent = _directory(path.parent)
    try:
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent)
        except FileExistsError:
            # Never learn the expected hash from the existing directory itself.
            pass
        else:
            fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                _same_directory(path.parent, parent)
                _same_directory(path, fd)
                for name, data in (('policies.sql', body), ('request.json', raw)):
                    member = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
                    with os.fdopen(member, 'wb') as output:
                        os.fchmod(output.fileno(), 0o600)
                        output.write(data); output.flush(); os.fsync(output.fileno())
                os.fsync(fd)
                _same_directory(path, fd)
                _same_directory(path.parent, parent)
            finally:
                os.close(fd)
            os.fsync(parent)
        actual, actual_body = read_request(path, result['manifestSha256'], binding=binding)
        _check(encoded(actual) == raw and actual_body == body, 'request_changed')
        _same_directory(path.parent, parent)
        return result
    finally:
        os.close(parent)


def read_request(directory, expected_sha256, *, binding):
    """Read exact private inventory against independently supplied request/binding pins."""
    expected = _binding(binding)
    _sha(expected_sha256)
    path = _path(directory)
    fd = _directory(path)
    try:
        _check(set(os.listdir(fd)) == FILES, 'inventory_changed')
        raw = _read(fd, 'request.json', MAX_MANIFEST)
        _check(digest(raw) == expected_sha256, 'request_changed')
        manifest = json_bytes(raw)
        _check(isinstance(manifest, dict) and set(manifest) == {'format', 'binding', 'contract', 'policySha256'}
            and manifest['format'] == FORMAT and encoded(manifest) == raw, 'manifest_invalid')
        _check(_binding(manifest['binding']) == expected, 'binding_changed')
        _check(manifest['policySha256'] == expected['policySha256'], 'binding_changed')
        contract = manifest['contract']
        _check(isinstance(contract, dict) and set(contract) ==
            {'policySha256', 'bytes', 'owners', 'policyIdentities'}, 'manifest_invalid')
        _sha(contract['policySha256'])
        _check(type(contract['bytes']) is int and 0 <= contract['bytes'] <= MAX_SQL and
            isinstance(contract['owners'], list) and isinstance(contract['policyIdentities'], list) and
            len(contract['owners']) <= MAX_POLICIES and len(contract['policyIdentities']) <= MAX_POLICIES,
            'manifest_invalid')
        for owner in contract['owners']:
            _name(owner)
        for identity in contract['policyIdentities']:
            _check(isinstance(identity, list) and len(identity) == 3, 'manifest_invalid')
            for name in identity:
                _name(name)
            _check(identity[0] in SCHEMAS, 'manifest_invalid')
        _check(contract['owners'] == sorted(set(contract['owners'])) and
            contract['policyIdentities'] == [list(i) for i in sorted({tuple(i) for i in contract['policyIdentities']})],
            'manifest_invalid')
        body = _read(fd, 'policies.sql', MAX_SQL)
        _check(len(body) == contract['bytes'] and digest(body) == contract['policySha256'] ==
            expected['policySha256'], 'sql_changed')
        _check(set(os.listdir(fd)) == FILES, 'inventory_changed')
        _same_directory(path, fd)
        return manifest, body
    finally:
        os.close(fd)
