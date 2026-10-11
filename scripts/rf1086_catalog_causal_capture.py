"""Private evidence for four rejected catalog objects; never recovery acceptance."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from uuid import uuid4

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from rf1086_catalog_difference import CatalogCapture, _encoded, _object, _records, _reject_constant
from rf1086_catalog_semantics import (
    MAX_ARCHIVE_BYTES, NET_IDENTITIES, NET_TYPES, _bound_rows, _command, _grants,
    _remaining, _toc_report,
)

TAG = 'owned_identity_catalog_causal '
MAX_PLAINTEXT = 10 * 1024
MAX_ENVELOPE = 16 * 1024
PHASES = ('source_pre_dump', 'target_initialized', 'mismatch')
SCHEMAS = (['schema', 'graphql'], ['schema', 'graphql_public'])
HOOKS = tuple(['function', 'extensions', name, ''] for name in (
    'grant_pg_net_access', 'grant_pg_graphql_access', 'set_graphql_placeholder'))
EVENTS = ('issue_pg_net_access', 'issue_pg_graphql_access', 'issue_graphql_placeholder')
HASH = re.compile(r'[a-f0-9]{64}')
VERSION = re.compile(r'[0-9]{1,3}(?:\.[0-9]{1,3}){1,2}')
NORMAL_BOOTSTRAP = '6a733d0e55a1fefdaf87d782d461d8e697289de21133f6cf22d0a3af44b8fbd9'
BACKUP_BOOTSTRAP = '6f5a9128dd10c111e2f50e499432d4af497644e3c1113918d7547b6aa5c4869d'
NET_SQL = 'a2854f625cfaed3119d05a9ff11a769d7e904615244ac2bfa74647d16ba1db19'


def _unavailable():
    raise ValueError('catalog_causal_unavailable')


def _text(value, limit=256):
    if type(value) is not str or len(value.encode()) > limit:
        _unavailable()
    return value


def _tuples(value):
    if type(value) is not list or len(value) > 64:
        _unavailable()
    for row in value:
        _grants([row])
        _text(row[0]); _text(row[2] if row[2] is not None else '')
        if row[3] not in ('CREATE', 'USAGE'):
            _unavailable()
    return [json.loads(row) for row in _grants(value)]


def _extensions(rows, width):
    if type(rows) is not list or len(rows) > (2 if width == 4 else 1):
        _unavailable()
    names = []
    for row in rows:
        if type(row) is not list or len(row) != width:
            _unavailable()
        for item in row: _text(item)
        if not VERSION.fullmatch(row[1]): _unavailable()
        names.append(row[0])
    if len(set(names)) != len(names): _unavailable()


def _snapshot(container, deadline, *, target=False, retained=None):
    statement = Path(__file__).with_name('rf1086_catalog_causal.sql').read_bytes()
    if len(statement) > 16 * 1024: _unavailable()
    args = ['docker', 'exec', '-i', container, 'psql', '-U', 'supabase_admin']
    if target: args += ['-h', '/tmp']
    raw = _command(args + ['-d', 'postgres', '-XqAt', '-v', 'ON_ERROR_STOP=1'], deadline, data=statement)
    if len(raw) > 32 * 1024: _unavailable()
    result = json.loads(raw, object_pairs_hook=_object, parse_constant=_reject_constant)
    return _validate_snapshot(result, retained)


def _validate_snapshot(result, retained):
    if (type(result) is not dict or set(result) != {'serverVersion', 'schemas', 'functions', 'hooks', 'events', 'extensions'}
            or type(result['serverVersion']) is not int or not 170000 <= result['serverVersion'] < 180000):
        _unavailable()
    expected = _records(retained) if retained is not None else None
    for group, identities in [('schemas', SCHEMAS), ('functions', NET_IDENTITIES), ('hooks', HOOKS)]:
        rows = result[group]
        if type(rows) is not list or len(rows) > len(identities): _unavailable()
        allowed = {_encoded(identity) for identity in identities}
        found = []
        for item in rows:
            if type(item) is not dict or _encoded(item.get('identity')) not in allowed: _unavailable()
            found.append(_encoded(item['identity']))
            fields = {'identity', 'row'} | ({'defaults', 'grants', 'default_grants', 'initial', 'extensions'} if group == 'schemas'
                else {'definition_sha256', 'body_sha256'} | ({'attributes', 'types', 'extensions'} if group == 'functions' else set()))
            if set(item) != fields: _unavailable()
            # Reuse the strict catalog row parser even for the initially empty target.
            with CatalogCapture() as shape:
                shape.capture(_encoded([item['row']]) + b'\n{}\n[]\n')
                parsed = _records(shape)
                _bound_rows([item], parsed, [item['identity']])
            if expected is not None: _bound_rows([item], expected, [item['identity']])
            if group == 'schemas':
                _text(item['defaults'], 8192)
                if item['row'][-1] is not None: _text(item['row'][-1], 8192)
                for name in ('grants', 'default_grants'): item[name] = _tuples(item[name])
                initial = item['initial']
                if type(initial) is not list or len(initial) > 1: _unavailable()
                for entry in initial:
                    if type(entry) is not list or len(entry) != 3 or entry[0] not in ('e', 'i'): _unavailable()
                    _text(entry[1], 8192); entry[2] = _tuples(entry[2])
            else:
                if any(not HASH.fullmatch(_text(item[name])) for name in ('definition_sha256', 'body_sha256')):
                    _unavailable()
            if group == 'functions':
                if item['row'][-1] not in (None, '{search_path=net}'): _unavailable()
                index = list(NET_IDENTITIES).index(item['identity'])
                if item['types'] != [['pg_catalog', name] for name in NET_TYPES[index]]: _unavailable()
                attrs = item['attributes']
                if (type(attrs) is not list or len(attrs) != 8 or any(type(attrs[i]) is not bool for i in (4, 6, 7))
                        or attrs[2] != 'f' or attrs[3] not in ('i', 's', 'v') or attrs[5] not in ('s', 'r', 'u')):
                    _unavailable()
                _text(attrs[0]); _text(attrs[1])
            if group == 'hooks':
                # Hook configuration values are not needed; preserve only their hash.
                item['row'][-1] = hashlib.sha256(_encoded(item['row'][-1])).hexdigest()
                item['configurationEncoding'] = 'sha256-of-canonical-json'
            if 'extensions' in item: _extensions(item['extensions'], 3)
        if len(set(found)) != len(found): _unavailable()
        required = allowed if expected is not None and group != 'hooks' else (
            allowed & expected.keys() if expected is not None else set())
        if required - set(found): _unavailable()
        result[group] = sorted(rows, key=lambda row: _encoded(row['identity']))
    events = result['events']
    if type(events) is not list or len(events) > 3: _unavailable()
    seen = set()
    for event in events:
        if (type(event) is not dict or set(event) != {'name', 'event', 'enabled', 'tags', 'owner', 'function'}
                or event['name'] not in EVENTS or event['name'] in seen
                or event['enabled'] not in ('O', 'D', 'R', 'A') or event['function'] not in HOOKS):
            _unavailable()
        seen.add(event['name']); _text(event['owner']); _text(event['event'])
        if event['tags'] is not None:
            if type(event['tags']) is not list or len(event['tags']) > 16: _unavailable()
            for tag in event['tags']: _text(tag)
    result['events'] = sorted(events, key=lambda row: row['name'])
    _extensions(result['extensions'], 4)
    result['extensions'].sort()
    return result


# Only these constant paths and validated numeric extension versions are read.
# A single bounded read supplies the hashed bytes; no file contents enter logs.
FILE_READER = """set -eu
if [ "$1" = bootstrap ]; then
  root=/etc; file=/etc/postgresql.schema.sql
else
  root=$(realpath "$(pg_config --sharedir)/extension")
  file="$root/$2$3"
fi
resolved=$(realpath "$file")
case "$resolved" in "$root"/*) ;; *) exit 1;; esac
[ -f "$resolved" ]
exec head -c 262145 "$resolved"
"""


def _files(container, extensions, deadline, *, source=False):
    result = {}
    requests = [('bootstrap', '', '')] if source else []
    for name, version, *_ in extensions:
        if name not in ('pg_net', 'pg_graphql') or not VERSION.fullmatch(version): _unavailable()
        requests += [('extension', name, '.control'), ('extension', name, '--' + version + '.sql')]
    for mode, name, suffix in requests:
        raw = _command(['docker', 'exec', container, 'sh', '-c', FILE_READER, 'causal-file', mode, name, suffix], deadline)
        if len(raw) > 256 * 1024: _unavailable()
        digest = hashlib.sha256(raw).hexdigest()
        result[mode if mode == 'bootstrap' else name + suffix] = {'bytes': len(raw), 'sha256': digest}
        if mode == 'bootstrap':
            result['bootstrap']['knownCliTemplate'] = 'normal' if digest == NORMAL_BOOTSTRAP else 'fromBackup' if digest == BACKUP_BOOTSTRAP else 'unknown'
        if name == 'pg_net' and suffix == '--0.20.3.sql':
            result[name + suffix]['matchesUpstream0203'] = digest == NET_SQL
    return result


def _selection_script(ids):
    if (not ids or len(ids) > 32 or len(set(ids)) != len(ids)
            or any(type(value) is not str or not re.fullmatch(r'[1-9][0-9]{0,7}', value) for value in ids)):
        _unavailable()
    return "exec pg_restore --file=- --use-list=/dev/fd/3 3<<'TALLI_CAUSAL_TOC'\n" + '\n'.join(ids) + '\nTALLI_CAUSAL_TOC\n'


def _archive(archive, container, snapshot, deadline):
    position = archive.tell()
    try:
        archive.seek(0); digest = hashlib.sha256(); total = 0
        while chunk := archive.read(65536):
            _remaining(deadline); total += len(chunk)
            if total > MAX_ARCHIVE_BYTES: _unavailable()
            digest.update(chunk)
        archive.seek(0)
        toc = _command(['docker', 'exec', '-i', container, 'pg_restore', '--list', '--verbose'], deadline, archive=archive)
        owners = [row['row'][4] for row in snapshot['functions']]
        report = _toc_report(toc, owners)
        selected, hooks = [], []
        schema_descriptors = {prefix + ' ' + row['identity'][1] + ' ' + row['row'][2]
            for row in snapshot['schemas'] for prefix in ('SCHEMA -', 'ACL - SCHEMA')}
        hook_descriptors = {'FUNCTION extensions ' + row['identity'][2] + '() ' + row['row'][4]
            for row in snapshot['hooks']}
        hook_descriptors |= {'EVENT TRIGGER - ' + row['name'] + ' ' + row['owner'] for row in snapshot['events']}
        seen = set()
        for line in toc.decode().splitlines():
            match = re.fullmatch(r'([1-9][0-9]*); ([0-9]+) ([0-9]+) (.+)', line)
            if not match: continue
            descriptor = match[4]
            schema = re.fullmatch(r'(?:SCHEMA -|ACL - SCHEMA) (?:graphql|graphql_public) [^\r\n]+', descriptor)
            extension = re.fullmatch(r'EXTENSION - (pg_net|pg_graphql)(?: [^\r\n]*)?', descriptor)
            hook = (re.fullmatch(r'FUNCTION extensions (?:grant_pg_net_access|grant_pg_graphql_access|set_graphql_placeholder)\(\) [^\r\n]+', descriptor)
                    or re.fullmatch(r'EVENT TRIGGER - (?:issue_pg_net_access|issue_pg_graphql_access|issue_graphql_placeholder) [^\r\n]+', descriptor))
            if schema and descriptor not in schema_descriptors: _unavailable()
            if hook and descriptor not in hook_descriptors: _unavailable()
            if schema or extension or hook:
                identity = extension[1] if extension else descriptor
                if identity in seen: _unavailable()
                seen.add(identity)
            if schema or extension:
                selected.append([match[1], descriptor])
            if hook:
                hooks.append([match[1], descriptor])
        def extract(rows):
            archive.seek(0)
            return _command(['docker', 'exec', '-i', container, 'sh', '-c',
                             _selection_script([row[0] for row in rows])], deadline, archive=archive)
        raw = extract(selected)
        if len(raw) > 6 * 1024: _unavailable()
        hook_raw = extract(hooks) if hooks else b''
        if len(hook_raw) > 64 * 1024: _unavailable()
        return {'sha256': digest.hexdigest(), 'bytes': total, 'toc': report, 'selected': selected,
                'sql': raw.decode(), 'sqlSha256': hashlib.sha256(raw).hexdigest(), 'hooks': hooks,
                'hookSqlSha256': hashlib.sha256(hook_raw).hexdigest(), 'hookSqlBytes': len(hook_raw),
                'writerInventoryComplete': False}
    finally:
        primary = sys.exception()
        try: archive.seek(position)
        except Exception:
            if primary is not None and not isinstance(primary, Exception): raise primary
            raise


def _seal(payload, aad, public_key):
    plaintext = _encoded(payload)
    if len(plaintext) > MAX_PLAINTEXT: _unavailable()
    key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _encoded(aad))
    wrapped = public_key.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    envelope = {'aad': aad, **{name: base64.b64encode(value).decode() for name, value in (
        ('key', wrapped), ('nonce', nonce), ('ciphertext', ciphertext))}}
    line = TAG + _encoded(envelope).decode()
    if len(line.encode()) + 1 > MAX_ENVELOPE: _unavailable()
    return line


def decrypt_capsules(log, private_key, expected):
    """Offline, exact-run reader; identical CI replay lines count only once."""
    if type(log) is not str or len(log.encode()) > 8 * 1024 * 1024: _unavailable()
    public = private_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    required = {'run', 'attempt', 'mergeSha', 'image', 'publicKeySha256'}
    if set(expected) != required or expected['publicKeySha256'] != hashlib.sha256(public).hexdigest(): _unavailable()
    result, copies, nonces, captures = {}, set(), set(), set()
    prefix = re.compile(r'^(?:[0-9]{4}-[0-9T:.-]+Z[ \t]*)?' + re.escape(TAG) + r'(.+)$')
    # Leading indentation occurs when Node repeats the original diagnostic.
    for line in log.splitlines():
        match = prefix.fullmatch(line.strip())
        if not match: continue
        body = match[1]
        if len(TAG.encode()) + len(body.encode()) + 1 > MAX_ENVELOPE: _unavailable()
        if body in copies: continue
        copies.add(body)
        if len(copies) > 3: _unavailable()
        envelope = json.loads(body, object_pairs_hook=_object, parse_constant=_reject_constant)
        if type(envelope) is not dict or set(envelope) != {'aad', 'key', 'nonce', 'ciphertext'}: _unavailable()
        aad = envelope['aad']
        if (type(aad) is not dict or set(aad) != required | {'version', 'capture', 'phase'}
                or type(aad['version']) is not int or aad['version'] != 1
                or any(aad[name] != value for name, value in expected.items())
                or aad['phase'] not in PHASES or aad['phase'] in result
                or not re.fullmatch(r'[a-f0-9]{32}', _text(aad['capture']))): _unavailable()
        nonce, wrapped, ciphertext = [base64.b64decode(envelope[name], validate=True) for name in ('nonce', 'key', 'ciphertext')]
        if len(nonce) != 12 or nonce in nonces or len(wrapped) != 384 or len(ciphertext) > MAX_PLAINTEXT + 16: _unavailable()
        key = private_key.decrypt(wrapped, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        if len(key) != 32: _unavailable()
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, _encoded(aad))
        result[aad['phase']] = json.loads(plaintext, object_pairs_hook=_object, parse_constant=_reject_constant)
        captures.add(aad['capture']); nonces.add(nonce)
    if set(result) != set(PHASES) or len(captures) != 1: _unavailable()
    return result


class CausalCapture:
    """Three bounded read checkpoints, buffered until the strict catalog failure."""
    def __init__(self, source, init):
        self.source = source['Id']; self.image = source['Image']; self.init = init
        config = source.get('Config', {})
        self.source_command_hash = hashlib.sha256(_encoded([config.get('Entrypoint'), config.get('Cmd')])).hexdigest()
        command = (config.get('Entrypoint') or []) + (config.get('Cmd') or [])
        self.source_bootstrap_configured = any(type(part) is str and "cat <<'EOF' > /etc/postgresql.schema.sql" in part for part in command)
        self.remaining = 15.0; self.failed = False; self.snapshots = {}; self.binding = None; self.public_key = None

    def __enter__(self):
        def initialize(_):
            if not HASH.fullmatch(self.source) or not re.fullmatch(r'sha256:[a-f0-9]{64}', self.image): _unavailable()
            values = {name: os.environ.get(name, '') for name in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_SHA')}
            if (not re.fullmatch(r'[1-9][0-9]{0,19}', values['GITHUB_RUN_ID'])
                    or not re.fullmatch(r'[1-9][0-9]{0,5}', values['GITHUB_RUN_ATTEMPT'])
                    or not re.fullmatch(r'[a-f0-9]{40}', values['GITHUB_SHA'])): _unavailable()
            public = Path(__file__).with_name('rf1086_catalog_causal_public.pub').read_bytes()
            if len(public) > 1024: _unavailable()
            self.public_key = serialization.load_pem_public_key(public)
            if not isinstance(self.public_key, rsa.RSAPublicKey) or self.public_key.key_size != 3072: _unavailable()
            self.binding = {'version': 1, 'run': values['GITHUB_RUN_ID'], 'attempt': values['GITHUB_RUN_ATTEMPT'],
                'mergeSha': values['GITHUB_SHA'], 'image': self.image, 'capture': uuid4().hex,
                'publicKeySha256': hashlib.sha256(public).hexdigest()}
        self._attempt(initialize)
        return self

    def __exit__(self, *_):
        self.snapshots.clear(); self.binding = None; self.public_key = None

    def _attempt(self, action):
        start = time.monotonic()
        try:
            if self.failed or self.remaining <= 0: _unavailable()
            action(start + self.remaining)
            _remaining(start + self.remaining)
        except Exception:
            self.failed = True; self.snapshots.clear()
        finally:
            self.remaining = max(0, self.remaining - (time.monotonic() - start))

    def source_pre_dump(self, retained):
        def capture(deadline):
            snapshot = _snapshot(self.source, deadline, retained=retained)
            self.snapshots[PHASES[0]] = {'catalog': snapshot, 'catalogSha256': hashlib.sha256(retained._raw).hexdigest(),
                'files': self._group(lambda: _files(self.source, snapshot['extensions'], deadline, source=True), deadline),
                'sourceCommandSha256': self.source_command_hash, 'bootstrapFileConfigured': self.source_bootstrap_configured,
                'bootstrapExecutionProved': False}
        self._attempt(capture)

    @staticmethod
    def _group(action, deadline):
        # Auxiliary availability cannot erase a separately bound catalog. The
        # shared deadline and cancellation still invalidate the whole capture.
        _remaining(deadline)
        try:
            result = {'status': 'observed', 'value': action()}
        except Exception:
            result = {'status': 'unavailable'}
        _remaining(deadline)
        return result

    def target_initialized(self, target, name, nonce, network):
        def capture(deadline):
            if (not HASH.fullmatch(target) or target == self.source or not re.fullmatch(r'[a-f0-9]{32}', nonce)
                    or name != 'rf193_identity_db_' + nonce or network != 'rf193_identity_net_' + nonce): _unavailable()
            # No Env or source command is fetched. The expected target command is fixed INIT.
            projection = '{{json .Id}}|{{json .Image}}|{{json .Name}}|{{json (index .Config.Labels "talli.rf.identity.restore")}}|{{json .Config.Entrypoint}}|{{json .Config.Cmd}}|{{json .HostConfig.NetworkMode}}'
            raw = _command(['docker', 'inspect', '--format', projection, target], deadline)
            parts = raw.decode().strip().split('|')
            if len(parts) != 7: _unavailable()
            values = [json.loads(part, object_pairs_hook=_object) for part in parts]
            if values != [target, self.image, '/' + name, nonce, ['sh'], ['-c', self.init], network]:
                _unavailable()
            self.snapshots[PHASES[1]] = {'catalog': _snapshot(target, deadline, target=True),
                'files': self._group(lambda: _files(target, self.snapshots[PHASES[0]]['catalog']['extensions'], deadline), deadline),
                'target': target, 'initSha256': hashlib.sha256(self.init.encode()).hexdigest(),
                'ownedInitMatches': True, 'scope': 'initial-postgres-before-drop-and-archive-recreation'}
        self._attempt(capture)

    def mismatch(self, source_catalog, target_catalog, target, dump):
        lines = []
        def capture(deadline):
            left = _snapshot(self.source, deadline, retained=source_catalog)
            if _encoded(left) != _encoded(self.snapshots[PHASES[0]]['catalog']): _unavailable()
            if target != self.snapshots[PHASES[1]]['target']: _unavailable()
            right = _snapshot(target, deadline, target=True, retained=target_catalog)
            self.snapshots[PHASES[2]] = {'catalog': right, 'catalogSha256': hashlib.sha256(target_catalog._raw).hexdigest(),
                'sourceSupplementalUnchanged': True, 'sourceSupplementalSha256': hashlib.sha256(_encoded(left)).hexdigest(),
                'archive': self._group(lambda: _archive(dump, target, left, deadline), deadline)}
            complete = all(self.snapshots[phase][group]['status'] == 'observed'
                for phase, group in zip(PHASES, ('files', 'files', 'archive')))
            for phase in PHASES:
                self.snapshots[phase]['captureGroupsComplete'] = complete
                lines.append(_seal(self.snapshots[phase], self.binding | {'phase': phase}, self.public_key))
        self._attempt(capture)
        try:
            if self.failed:
                print(TAG + '{"status":"unavailable"}', file=sys.stderr)
            else:
                for line in lines: print(line, file=sys.stderr)
        except Exception:
            pass
        finally:
            self.snapshots.clear()
