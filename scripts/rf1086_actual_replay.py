"""One bounded same-image full replay, then inventory; never a repair/receipt.

Only a same-job, hash-bound private package may be consumed. Raw roles, archive,
writer SQL and service state never enter logs. No checkpointed replay is enabled.
"""
import argparse
import base64
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import rf1086_catalog_semantics as commands
from rf1086_catalog_causal_capture import _snapshot, _files, FILE_OUTPUT_CAP, PHASES
from rf1086_catalog_difference import CatalogCapture, _encoded, _records
from rf1086_actual_replay_package import (
    IMAGE, LIMITS, Unavailable, binding, code_hashes, digest, load_json, owner,
    package_path, prepare, private_directory, read_package, read_private, write_private,
    STATUS_TAG, report_unavailable,
)

TAG = 'owned_identity_actual_replay_v1 '
LABEL = 'talli.rf.actual.replay'
MAX_PLAINTEXT = 64 * 1024
MAX_ENVELOPE = 96 * 1024
ACTIVE_SECONDS = 416
CLEANUP_SECONDS = 58
COMMAND_SECONDS = 43  # Two seconds remain inside the reviewed 45s command cap.
MAX_SQL_BYTES = 32 * 1024**2
FSQL_RESERVE_SECONDS = 12
FSQL_HEADROOM_SECONDS = 200
PUBLIC_KEY_PATH = Path(__file__).with_name('rf1086_catalog_causal_public.pub')
FSQL_REASONS = frozenset(('insufficient_headroom', 'control_unavailable', 'summary_oversized',
    'worker_deadline', 'worker_failed', 'worker_result_invalid', 'full_sql_empty',
    'full_sql_tool_invalid', 'full_sql_cleanup_unproved', 'full_sql_target_reused',
    'full_control_mismatch', 'full_causal_control_mismatch', 'initialized_control_mismatch',
    'command_unavailable'))
F2_KEYS = frozenset(('status', 'fingerprint', 'F2EqualsF', 'causalSnapshotEqualsF', 'catalog',
    'inventory', 'schemaWriterSql', 'installedFiles', 'netSourceAttributesObserved', 'S0', 'Is', 'In',
    'reason', 'causalAttributionAccepted', 'recoveryAccepted', 'input', 'sourceCommandSha256',
    'sourceInstalledFiles'))
INPUT_KEYS = ('binding', 'image', 'source', 'sourceAuth', 'sourceNetwork', 'initSha256', 'code',
    'files', 'before', 'failed', 'cleanupComplete', 'identitySourcePostcheck',
    'outerBusinessPostchecks', 'exportBudget')
FULL_SQL_COMMAND = 'exec pg_restore --verbose --clean --if-exists --create --file=- 2>/dev/null'
TOOL_COMMAND = '''set -eu
binary=$(command -v pg_restore)
case "$binary" in /*) ;; *) exit 1;; esac
[ -f "$binary" ] && [ -x "$binary" ]
version=$("$binary" --version)
hashed=$(sha256sum "$binary")
printf '%s\\n%s\\n' "$version" "${hashed%% *}"
'''
# Finite PG17 descriptions; longest first disambiguates e.g. TABLE/TABLE DATA.
DESCRIPTIONS = tuple(sorted((
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
), key=len, reverse=True))
SPECIAL = {'ENCODING', 'STDSTRINGS', 'SEARCHPATH'}


def command(args, deadline, *, data=None, archive=None, cap=8 * 1024**2):
    # Reuse the existing concurrent bounded pipe drain and cancellation/reap.
    old = commands.MAX_BYTES
    commands.MAX_BYTES = cap
    try:
        return commands._command(args, min(deadline, time.monotonic() + COMMAND_SECONDS), data=data, archive=archive)
    except Exception:
        raise Unavailable('command_unavailable') from None
    finally:
        commands.MAX_BYTES = old


def inspect(kind, name, deadline):
    raw = command(['docker', kind, 'inspect', name], deadline, cap=64 * 1024)
    result = load_json(raw)
    if type(result) is not list or len(result) != 1 or type(result[0]) is not dict:
        raise Unavailable('resource_inspection_invalid')
    return result[0]


def resource_names(nonce):
    return {'network': 'rf193_replay_net_' + nonce, 'volume': 'rf193_replay_data_' + nonce,
            'container': 'rf193_replay_db_' + nonce, 'initializer': 'rf193_replay_init_' + nonce}


def resource_exists(kind, name, deadline):
    if kind == 'container':
        args = ['docker', 'container', 'ls', '--all', '--no-trunc', '--filter', 'name=^/' + name + '$', '--format', '{{.Names}}']
    else:
        args = ['docker', kind, 'ls', '--filter', 'name=^' + name + '$', '--format', '{{.Name}}']
    rows = command(args, deadline, cap=4096).decode().splitlines()
    if rows not in ([], [name]):
        raise Unavailable('resource_listing_invalid')
    return bool(rows)


def assert_source_absent(metadata, deadline):
    for key in ('source', 'sourceAuth'):
        value = metadata[key]
        if not re.fullmatch(r'[a-f0-9]{64}', value):
            raise Unavailable('source_binding_invalid')
        raw = command(['docker', 'container', 'ls', '--all', '--no-trunc', '--filter', 'id=' + value,
                       '--format', '{{.ID}}'], deadline, cap=4096)
        if raw.strip():
            raise Unavailable('source_teardown_unproved')
    name = metadata['sourceNetwork']
    if not re.fullmatch(r'supabase_network_[A-Za-z0-9_-]{1,80}', name):
        raise Unavailable('source_binding_invalid')
    if resource_exists('network', name, deadline):
        raise Unavailable('source_teardown_unproved')


def verify_resource(kind, name, nonce, deadline):
    value = inspect(kind, name, deadline)
    labels = value.get('Config', {}).get('Labels', {}) if kind == 'container' else value.get('Labels', {})
    expected_name = '/' + name if kind == 'container' else name
    if value.get('Name') != expected_name or (labels or {}).get(LABEL) != nonce:
        raise Unavailable('resource_ownership_mismatch')
    if kind == 'container' and value.get('Image') != IMAGE:
        raise Unavailable('resource_ownership_mismatch')
    if kind == 'network' and not value.get('Internal'):
        raise Unavailable('resource_ownership_mismatch')
    return value


def cleanup_resources(path, deadline):
    ownership = owner(path)
    nonce = ownership['nonce']
    names = resource_names(nonce)
    errors = []
    for slot in ('initializer', 'container', 'volume', 'network'):
        kind = 'container' if slot == 'initializer' else slot
        name = names[slot]
        try:
            if resource_exists(kind, name, deadline):
                verify_resource(kind, name, nonce, deadline)
                command(['docker', kind, 'rm', *(['--force'] if kind == 'container' else []), name], deadline, cap=4096)
                if resource_exists(kind, name, deadline):
                    raise Unavailable('cleanup_incomplete')
        except Exception:
            errors.append(slot)
    return not errors


def remove_package(path, *, keep_owner=False):
    owner(path)
    # No recursion or arbitrary paths; reject unexpected directories/symlinks.
    allowed = {'owner.json', 'ready.json', 'ready.pending', 'result.json', 'f2.pending', 'f2.json', *LIMITS}
    entries = list(path.iterdir())
    if len(entries) > 48 or any(p.name not in allowed for p in entries):
        raise Unavailable('cleanup_package_unexpected')
    for entry in entries:
        read_private(entry, 128 * 1024**2)
    for entry in entries:
        if entry.name != 'owner.json':
            entry.unlink()
    if not keep_owner:
        (path / 'owner.json').unlink()
        path.rmdir()


def cleanup_package(path):
    complete = False
    try:
        complete = cleanup_resources(path, time.monotonic() + CLEANUP_SECONDS)
    finally:
        # Raw archives/roles must be erased even if Docker is unavailable.
        # Keep only the nonce/binding record needed to reconcile owned resources.
        remove_package(path, keep_owner=not complete)
    if not complete:
        raise Unavailable('cleanup_incomplete')


def start_target(metadata, deadline):
    from rf1086_identity_restore import INIT
    if metadata['initSha256'] != digest(INIT.encode()):
        raise Unavailable('init_binding_mismatch')
    nonce = metadata['nonce']
    names = resource_names(nonce)
    preload = metadata['preload']
    if not re.fullmatch(r'[A-Za-z0-9_, .-]{0,256}', preload):
        raise Unavailable('preload_invalid')
    for slot, name in names.items():
        if resource_exists('container' if slot == 'initializer' else slot, name, deadline):
            raise Unavailable('resource_preexisting')
    command(['docker', 'image', 'inspect', '--format', '{{.Id}}', IMAGE], deadline, cap=4096)
    command(['docker', 'network', 'create', '--internal', '--label', LABEL + '=' + nonce, names['network']], deadline)
    verify_resource('network', names['network'], nonce, deadline)
    command(['docker', 'volume', 'create', '--label', LABEL + '=' + nonce, names['volume']], deadline)
    verify_resource('volume', names['volume'], nonce, deadline)
    command(['docker', 'run', '--rm', '--pull=never', '--name', names['initializer'], '--label', LABEL + '=' + nonce,
             '--network', 'none', '--user', '0', '--entrypoint', 'sh', '-v', names['volume'] + ':/tmp/rf-recovery',
             IMAGE, '-c', 'chown postgres:postgres /tmp/rf-recovery'], deadline)
    target = command(['docker', 'create', '--pull=never', '--name', names['container'], '--label', LABEL + '=' + nonce,
        '--network', names['network'], '--user', 'postgres', '--entrypoint', 'sh',
        '-e', 'RECOVERY_BOOTSTRAP=supabase_admin', '-e', 'RECOVERY_PRELOAD=' + preload,
        '-v', names['volume'] + ':/tmp/rf-recovery', IMAGE, '-c', INIT], deadline).decode().strip()
    value = verify_resource('container', names['container'], nonce, deadline)
    if (not re.fullmatch(r'[a-f0-9]{64}', target) or value.get('Id') != target
            or target in (metadata['source'], metadata['sourceAuth'])
            or value.get('Config', {}).get('Entrypoint') != ['sh']
            or value.get('Config', {}).get('Cmd') != ['-c', INIT]
            or value.get('HostConfig', {}).get('NetworkMode') != names['network']
            or value.get('HostConfig', {}).get('PortBindings')
            or len(value.get('Mounts', [])) != 1
            or value['Mounts'][0].get('Name') != names['volume']
            or value['Mounts'][0].get('Destination') != '/tmp/rf-recovery'):
        raise Unavailable('target_binding_invalid')
    command(['docker', 'start', target], deadline)
    for _ in range(90):
        try:
            command(['docker', 'exec', target, 'pg_isready', '-h', '/tmp', '-U', 'supabase_admin'], deadline, cap=4096)
            return target
        except Unavailable:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.25)
    raise Unavailable('target_not_ready')


def psql(target, statement, deadline, database='postgres'):
    return command(['docker', 'exec', '-i', target, 'psql', '-U', 'supabase_admin', '-h', '/tmp',
                    '-d', database, '-XqAt', '-v', 'ON_ERROR_STOP=1'], deadline, data=statement)


def toc_inventory(raw):
    if len(raw) > 2 * 1024**2:
        raise Unavailable('toc_oversized')
    headers = re.findall(rb'^;\s*TOC Entries: ([0-9]+)\s*$', raw, re.M)
    if len(headers) != 1 or not 1 <= int(headers[0]) <= 20000:
        raise Unavailable('toc_header_invalid')
    entries, ids = [], set()
    for line in raw.decode('utf-8').splitlines():
        if not line or line.startswith(';'):
            continue
        match = re.fullmatch(r'([1-9][0-9]{0,7}); ([0-9]+) ([0-9]+) (.+)', line)
        if not match or int(match[1]) in ids:
            raise Unavailable('toc_entry_invalid')
        ids.add(int(match[1]))
        description = next((d for d in DESCRIPTIONS if match[4].startswith(d + ' ')), None)
        if description is None:
            raise Unavailable('toc_description_unknown')
        rest = match[4][len(description) + 1:]
        if description in SPECIAL:
            restore_pass = 'SPECIAL'
        elif description in ('ACL', 'ACL LANGUAGE', 'DEFAULT ACL'):
            restore_pass = 'ACL'
        elif description in ('EVENT TRIGGER', 'MATERIALIZED VIEW DATA') or (
                description == 'COMMENT' and rest.startswith('- EVENT TRIGGER ')):
            restore_pass = 'POST_ACL'
        else:
            restore_pass = 'MAIN'
        entries.append({'id': int(match[1]), 'description': description, 'rest': rest, 'pass': restore_pass})
    if len(entries) != int(headers[0]):
        raise Unavailable('toc_count_mismatch')
    specials = [e for e in entries if e['pass'] == 'SPECIAL']
    if Counter(e['description'] for e in specials) != Counter(SPECIAL):
        raise Unavailable('toc_preamble_unproved')
    # No selection/filter flags in the original invocation: ordinary entries
    # eligible under --create are retained, special entries remain separate.
    schedule = [e for phase in ('MAIN', 'ACL', 'POST_ACL') for e in entries if e['pass'] == phase]
    wanted = [('SCHEMA', '- graphql supabase_admin'), ('SCHEMA', '- graphql_public supabase_admin'),
              ('EXTENSION', '- pg_net ')]
    cuts = []
    for desc, rest in wanted:
        matches = [i for i, e in enumerate(schedule) if (e['description'], e['rest']) == (desc, rest)]
        if len(matches) != 1:
            raise Unavailable('toc_checkpoint_unproved')
        cuts.append(matches[0])
    first = min(cuts)
    late_database = [e for i, e in enumerate(schedule) if i > first and (
        e['description'] in ('DATABASE', 'DATABASE PROPERTIES') or (
        e['description'] in ('ACL', 'COMMENT', 'SECURITY LABEL') and e['rest'].startswith('- DATABASE ')))]
    return {'sha256': digest(raw), 'total': len(entries), 'headerCountMatches': True,
            'passCounts': dict(Counter(e['pass'] for e in entries)),
            'specialIds': [e['id'] for e in specials],
            'scheduleSha256': digest(_encoded([e['id'] for e in schedule])),
            'checkpointIds': [schedule[i]['id'] for i in cuts],
            'lateDatabaseEntries': [{'id': e['id'], 'description': e['description']} for e in late_database[:32]],
            'lateDatabaseCount': len(late_database),
            'orderGate': 'database_metadata_after_first_cut' if late_database else 'session_boundary_unproved',
            'writerCoverageVerified': False, 'specialSessionEffectsVerified': False,
            'eligibility': 'unfiltered-create-candidate-schedule-not-executed'}


def installed_files(target, snapshots, deadline):
    return _files(target, snapshots['extensions'], deadline, run=lambda args, shared_deadline:
        command(args, min(shared_deadline, time.monotonic() + 5), cap=FILE_OUTPUT_CAP))


def failed_state(target, metadata, failed_raw, deadline):
    import rf1086_identity_restore as identity
    original_checked = identity.checked
    identity.checked = lambda args, **kw: SimpleNamespace(stdout=command(args, deadline,
        data=kw.get('input'), archive=kw.get('stdin')))
    try:
        with CatalogCapture() as captured:
            result = identity.fingerprint(target, restored=True, bootstrap='supabase_admin', catalog_capture=captured)
            if result != metadata['failed'] or captured._raw != failed_raw:
                raise Unavailable('full_control_mismatch')
            snapshot = _snapshot(target, min(deadline, time.monotonic() + COMMAND_SECONDS), target=True, retained=captured)
            if snapshot != metadata['phases']['mismatch']['catalog']:
                raise Unavailable('full_causal_control_mismatch')
            return result, snapshot
    finally:
        identity.checked = original_checked


def unavailable_fsql(reason):
    return {'status': 'unavailable', 'reason': reason if reason in FSQL_REASONS else 'control_unavailable',
            'FsqlEqualsF2': False, 'recoveryAccepted': False, 'causalAttributionAccepted': False}


def validate_f2(result, metadata):
    phases = metadata['phases']
    if (type(result) is not dict or set(result) != F2_KEYS
            or result['status'] != 'full_control_verified'
            or result['F2EqualsF'] is not True or result['causalSnapshotEqualsF'] is not True
            or result['recoveryAccepted'] is not False or result['causalAttributionAccepted'] is not False
            or result['fingerprint'] != metadata['failed']
            or metadata['failed']['catalog'] != phases['mismatch']['catalogSha256']
            or result['catalog'] != phases['mismatch']['catalog']
            or result['input'] != {key: metadata[key] for key in INPUT_KEYS}
            or result['sourceCommandSha256'] != phases['source_pre_dump']['sourceCommandSha256']
            or result['sourceInstalledFiles'] != phases['source_pre_dump']['files']
            or result['netSourceAttributesObserved'] is not True
            or result['S0'] != 'unavailable' or result['Is'] != 'unavailable'
            or result['In'] != 'archive_function_equivalence_unproved'):
        raise Unavailable('checkpoint_invalid')
    return result


def summary_fits(result, metadata):
    # Include the longest finite consumer outcome and cleanup field before work.
    raw = _encoded(result | {'optionalWorkerOutcome': 'result_invalid', 'ownedCleanupComplete': False})
    aad = {'version': 1, **metadata['binding'], 'image': IMAGE,
           'packageSha256': 'f' * 64, 'publicKeySha256': 'f' * 64}
    # RSA3072, 12-byte nonce, AES-GCM tag, exact JSON/base64 framing overhead.
    framed = TAG.encode() + _encoded({'aad': aad, 'key': 'A' * 512, 'nonce': 'A' * 16,
                                     'ciphertext': 'A' * (4 * ((len(raw) + 16 + 2) // 3))})
    return len(raw) <= MAX_PLAINTEXT and len(framed) <= MAX_ENVELOPE


def fit_optional(f2, optional, metadata):
    result = f2 | {'Fsql': optional}
    if not summary_fits(result, metadata):
        result['Fsql'] = unavailable_fsql('summary_oversized')
    if not summary_fits(result, metadata):
        raise Unavailable('summary_oversized')
    return result


def checkpoint_f2(path, metadata, f2):
    validate_f2(f2, metadata)
    # Reserve the largest finite fallback before allocating another target.
    for reason in FSQL_REASONS:
        if not summary_fits(f2 | {'Fsql': unavailable_fsql(reason)}, metadata):
            raise Unavailable('summary_oversized')
    if owner(path)['nonce'] != metadata['nonce'] or (path / 'f2.json').exists() or (path / 'f2.json').is_symlink():
        raise Unavailable('checkpoint_invalid')
    write_private(path / 'f2.pending', _encoded(f2))
    os.rename(path / 'f2.pending', path / 'f2.json')


def read_f2(path, metadata):
    if owner(path)['nonce'] != metadata['nonce']:
        raise Unavailable('checkpoint_invalid')
    return validate_f2(load_json(read_private(path / 'f2.json', MAX_PLAINTEXT)), metadata)


def full_sql_control(path, metadata, previous_target, roles, failed_raw, deadline):
    tool_raw = command(['docker', 'exec', previous_target, 'sh', '-c', TOOL_COMMAND], deadline, cap=4096)
    tool = re.fullmatch(rb'pg_restore \(PostgreSQL\) (17\.6)\n([a-f0-9]{64})\n', tool_raw)
    if tool is None:
        raise Unavailable('full_sql_tool_invalid')
    with (path / 'archive.dump').open('rb') as archive:
        script = command(['docker', 'exec', '-i', previous_target, 'sh', '-c', FULL_SQL_COMMAND],
                         deadline, archive=archive, cap=MAX_SQL_BYTES)
    if not script:
        raise Unavailable('full_sql_empty')
    stream = {'bytes': len(script), 'sha256': digest(script)}
    if not cleanup_resources(path, deadline):
        raise Unavailable('full_sql_cleanup_unproved')
    target = start_target(metadata, deadline)
    if target == previous_target:
        raise Unavailable('full_sql_target_reused')
    psql(target, roles, deadline)
    if _snapshot(target, min(deadline, time.monotonic() + COMMAND_SECONDS), target=True) != metadata['phases']['target_initialized']['catalog']:
        raise Unavailable('initialized_control_mismatch')
    psql(target, b'drop database postgres with (force);', deadline, database='template1')
    psql(target, script, deadline, database='template1')
    fingerprint, catalog = failed_state(target, metadata, failed_raw, deadline)
    return {'status': 'full_sql_verified', 'stream': stream,
            'tool': {'version': tool[1].decode(), 'sha256': tool[2].decode()},
            'initializedEqualsOriginal': True, 'freshTarget': True,
            'fingerprint': fingerprint, 'catalog': catalog, 'FsqlEqualsF2': True,
            'causalSnapshotEqualsF2': True, 'recoveryAccepted': False, 'causalAttributionAccepted': False}


def add_full_sql(path, metadata, target, roles, failed_raw, f2, deadline):
    checkpoint_f2(path, metadata, f2)
    optional_deadline = deadline - FSQL_RESERVE_SECONDS
    if optional_deadline - time.monotonic() < FSQL_HEADROOM_SECONDS:
        return fit_optional(f2, unavailable_fsql('insufficient_headroom'), metadata)
    try:
        optional = full_sql_control(path, metadata, target, roles, failed_raw, optional_deadline)
    except Unavailable as error:
        optional = unavailable_fsql(error.reason)
    except Exception:
        optional = unavailable_fsql('control_unavailable')
    return fit_optional(f2, optional, metadata)


def replay(path, metadata, deadline):
    import rf1086_identity_restore as identity
    assert_source_absent(metadata, deadline)
    source_raw = read_private(path / 'source.catalog', LIMITS['source.catalog'])
    failed_raw = read_private(path / 'failed.catalog', LIMITS['failed.catalog'])
    if (digest(source_raw) != metadata['before']['catalog']
            or digest(failed_raw) != metadata['failed']['catalog']
            or set(metadata['phases']) != set(PHASES)):
        raise Unavailable('catalog_binding_mismatch')
    phases = metadata['phases']
    if (phases['source_pre_dump']['catalogSha256'] != digest(source_raw)
            or phases['mismatch']['catalogSha256'] != digest(failed_raw)
            or phases['source_pre_dump']['catalog']['serverVersion'] != 170006
            or phases['mismatch']['catalog']['serverVersion'] != 170006
            or phases['target_initialized']['initSha256'] != metadata['initSha256']
            or phases['mismatch']['archive'].get('status') != 'observed'):
        raise Unavailable('causal_binding_mismatch')
    archive_binding = phases['mismatch']['archive']['value']
    if any(archive_binding[k] != metadata['files']['archive.dump'][k] for k in ('bytes', 'sha256')):
        raise Unavailable('archive_binding_mismatch')
    target = start_target(metadata, deadline)
    roles = read_private(path / 'roles.sql', LIMITS['roles.sql'])
    created = b'CREATE ROLE supabase_admin;\n'
    if roles.count(created) != 1:
        raise Unavailable('bootstrap_role_invalid')
    roles = roles.replace(created, b'', 1)
    psql(target, roles, deadline)
    initial = _snapshot(target, min(deadline, time.monotonic() + COMMAND_SECONDS), target=True)
    if initial != phases['target_initialized']['catalog']:
        raise Unavailable('initialized_control_mismatch')
    psql(target, b'drop database postgres with (force);', deadline, database='template1')
    with (path / 'archive.dump').open('rb') as archive:
        command(['docker', 'exec', '-i', target, 'pg_restore', '-U', 'supabase_admin', '-h', '/tmp',
                 '--exit-on-error', '--clean', '--if-exists', '--create', '--dbname', 'template1'], deadline, archive=archive)
    # Reuse the actual acceptance query bytes, under this consumer's tighter
    # command/overall deadlines. The patch is process-local, never production.
    result, snapshot = failed_state(target, metadata, failed_raw, deadline)
    with (path / 'archive.dump').open('rb') as archive:
        toc = command(['docker', 'exec', '-i', target, 'pg_restore', '--list', '--verbose'], deadline, archive=archive, cap=2 * 1024**2)
    inventory = toc_inventory(toc)
    with (path / 'archive.dump').open('rb') as archive:
        writers = command(['docker', 'exec', '-i', target, 'pg_restore', '--schema-only', '--create',
                           '--clean', '--if-exists', '--file=-'], deadline, archive=archive)
    files = installed_files(target, snapshot, deadline)
    f2 = {'status': 'full_control_verified', 'fingerprint': result, 'F2EqualsF': True,
            'causalSnapshotEqualsF': True, 'catalog': snapshot, 'inventory': inventory,
            'schemaWriterSql': {'bytes': len(writers), 'sha256': digest(writers), 'coverage': 'schema-only-not-complete-writer-proof'},
            'installedFiles': files, 'netSourceAttributesObserved': True,
            'S0': 'unavailable', 'Is': 'unavailable', 'In': 'archive_function_equivalence_unproved',
            'reason': inventory['orderGate'], 'causalAttributionAccepted': False, 'recoveryAccepted': False,
            'input': {key: metadata[key] for key in INPUT_KEYS},
            'sourceCommandSha256': phases['source_pre_dump']['sourceCommandSha256'],
            'sourceInstalledFiles': phases['source_pre_dump']['files']}
    return add_full_sql(path, metadata, target, roles, failed_raw, f2, deadline)


def seal(payload, aad, public_key):
    raw = _encoded(payload)
    if len(raw) > MAX_PLAINTEXT:
        raise Unavailable('summary_oversized')
    key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, raw, _encoded(aad))
    wrapped = public_key.encrypt(key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    line = TAG + _encoded({'aad': aad, **{k: base64.b64encode(v).decode() for k, v in
        (('key', wrapped), ('nonce', nonce), ('ciphertext', ciphertext))}}).decode()
    if len(line.encode()) > MAX_ENVELOPE:
        raise Unavailable('envelope_oversized')
    return line


def decrypt(log, private_key, expected):
    if type(log) is not str or len(log.encode()) > 8 * 1024**2:
        raise Unavailable('log_oversized')
    public = private_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    if set(expected) != {'run', 'attempt', 'mergeSha', 'image', 'packageSha256', 'publicKeySha256'} or expected['publicKeySha256'] != digest(public):
        raise Unavailable('reader_binding_invalid')
    lines = []
    prefix = re.compile(r'^(?:[0-9]{4}-[0-9T:.-]+Z[ \t]*)?' + re.escape(TAG) + r'(.+)$')
    for line in log.splitlines():
        match = prefix.fullmatch(line.strip())
        if match:
            if len(line.encode()) > MAX_ENVELOPE + 64:
                raise Unavailable('envelope_oversized')
            lines.append(match[1])
    if len(lines) != 1:
        raise Unavailable('envelope_count_invalid')
    value = load_json(lines[0])
    if set(value) != {'aad', 'key', 'nonce', 'ciphertext'} or value['aad'] != {'version': 1, **expected}:
        raise Unavailable('envelope_binding_invalid')
    wrapped, nonce, ciphertext = [base64.b64decode(value[k], validate=True) for k in ('key', 'nonce', 'ciphertext')]
    if len(wrapped) != 384 or len(nonce) != 12 or len(ciphertext) > MAX_PLAINTEXT + 16:
        raise Unavailable('envelope_invalid')
    key = private_key.decrypt(wrapped, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    return load_json(AESGCM(key).decrypt(nonce, ciphertext, _encoded(value['aad'])))


def cancelled(*_):
    raise KeyboardInterrupt


def validate_fsql(value, metadata):
    if type(value) is not dict or value.get('recoveryAccepted') is not False or value.get('causalAttributionAccepted') is not False:
        raise Unavailable('optional_result_invalid')
    if value.get('status') == 'unavailable':
        if (set(value) != {'status', 'reason', 'FsqlEqualsF2', 'recoveryAccepted', 'causalAttributionAccepted'}
                or value['reason'] not in FSQL_REASONS or value['FsqlEqualsF2'] is not False):
            raise Unavailable('optional_result_invalid')
        return value
    fields = {'status', 'stream', 'tool', 'initializedEqualsOriginal', 'freshTarget', 'fingerprint',
              'catalog', 'FsqlEqualsF2', 'causalSnapshotEqualsF2', 'recoveryAccepted', 'causalAttributionAccepted'}
    if (set(value) != fields or value['status'] != 'full_sql_verified'
            or any(value[k] is not True for k in ('initializedEqualsOriginal', 'freshTarget', 'FsqlEqualsF2', 'causalSnapshotEqualsF2'))
            or value['fingerprint'] != metadata['failed'] or value['catalog'] != metadata['phases']['mismatch']['catalog']):
        raise Unavailable('optional_result_invalid')
    stream, tool = value['stream'], value['tool']
    if (type(stream) is not dict or set(stream) != {'bytes', 'sha256'}
            or type(stream['bytes']) is not int or not 0 < stream['bytes'] <= MAX_SQL_BYTES
            or type(stream['sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', stream['sha256'])
            or type(tool) is not dict or set(tool) != {'version', 'sha256'} or tool['version'] != '17.6'
            or type(tool['sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', tool['sha256'])):
        raise Unavailable('optional_result_invalid')
    return value


def completed_result(path, metadata):
    result = load_json(read_private(path / 'result.json', MAX_PLAINTEXT))
    if type(result) is dict and result.get('status') == 'unavailable':
        if set(result) != {'status', 'reason', 'recoveryAccepted'} or result['recoveryAccepted'] is not False:
            raise Unavailable('optional_result_invalid')
        return result
    if type(result) is not dict or set(result) != F2_KEYS | {'Fsql'}:
        raise Unavailable('optional_result_invalid')
    f2 = validate_f2({key: result[key] for key in F2_KEYS}, metadata)
    return fit_optional(f2, validate_fsql(result['Fsql'], metadata), metadata)


def fallback_result(path, metadata, outcome):
    reason = {'deadline': 'worker_deadline', 'failed': 'worker_failed', 'result_invalid': 'worker_result_invalid'}[outcome]
    try:
        return fit_optional(read_f2(path, metadata), unavailable_fsql(reason), metadata)
    except Exception:
        return {'status': 'unavailable', 'reason': reason, 'recoveryAccepted': False}


def worker():
    path, metadata, _ = read_package()
    deadline = float(os.environ['TALLI_RF_REPLAY_ACTIVE_DEADLINE'])
    if not math.isfinite(deadline) or not 0 < deadline - time.monotonic() <= ACTIVE_SECONDS:
        raise Unavailable('worker_deadline_invalid')
    try:
        result = replay(path, metadata, deadline)
    except Unavailable as error:
        result = {'status': 'unavailable', 'reason': error.reason, 'recoveryAccepted': False}
    except Exception:
        result = {'status': 'unavailable', 'reason': 'consumer_failed', 'recoveryAccepted': False}
    raw = _encoded(result)
    if len(raw) > MAX_PLAINTEXT:
        raise Unavailable('summary_oversized')
    write_private(path / 'result.json', raw)


def stop_worker(process, deadline):
    """Attempt every owned-child teardown step, keeping uncertainty explicit."""
    errors = []
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except BaseException as error:
        errors.append(error)
    try:
        if process.poll() is None:
            process.kill()
    except BaseException as error:
        errors.append(error)
    try:
        process.wait(timeout=max(0, deadline - time.monotonic()))
    except BaseException as error:
        errors.append(error)
    try:
        if process.poll() is None:
            errors.append(Unavailable('worker_cleanup_unproved'))
    except BaseException as error:
        errors.append(error)
    return errors


def consume():
    path, metadata, package_hash = read_package()
    started = float(os.environ.get('TALLI_RF_REPLAY_JOB_STARTED', 'nan'))
    elapsed = time.monotonic() - started
    if not 0 <= elapsed <= 90 * 60 - (600 + 120 + 120):
        raise Unavailable('job_headroom_unproved')
    process = None
    result = {'status': 'unavailable', 'reason': 'consumer_cancelled', 'recoveryAccepted': False}
    outcome = 'completed'
    deadline = time.monotonic() + ACTIVE_SECONDS
    try:
        process = subprocess.Popen([sys.executable, __file__, 'worker'], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True,
                                   env={**os.environ, 'TALLI_RF_REPLAY_ACTIVE_DEADLINE': repr(deadline)})
        process.wait(timeout=max(0, deadline - time.monotonic()))
        if process.returncode:
            outcome = 'failed'
    except subprocess.TimeoutExpired:
        outcome = 'deadline'
    except Exception:
        outcome = 'failed'
    finally:
        primary = sys.exception()
        teardown_errors = []
        try:
            if process is not None and (outcome != 'completed' or primary is not None):
                teardown_errors = stop_worker(process, time.monotonic() + 2)
            cancellation = next((e for e in teardown_errors if not isinstance(e, Exception)), None)
            if primary is not None:
                raise primary
            if cancellation is not None:
                raise cancellation
            if teardown_errors:
                raise Unavailable('worker_cleanup_unproved')
            # Never inspect an optional result from an interrupted/live worker.
            # Cancellation still propagates through cleanup without an envelope.
            if outcome == 'completed':
                try:
                    result = completed_result(path, metadata)
                except Exception:
                    outcome = 'result_invalid'
            if outcome != 'completed':
                result = fallback_result(path, metadata, outcome)
            result['optionalWorkerOutcome'] = outcome
        finally:
            active_failure = primary if primary is not None else sys.exception()
            # Permit the parent's cleanup window after its worker deadline/cancel.
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            try:
                result['ownedCleanupComplete'] = cleanup_resources(path, time.monotonic() + CLEANUP_SECONDS)
            finally:
                if active_failure is not None:
                    raise active_failure
    public_bytes = PUBLIC_KEY_PATH.read_bytes()
    public = serialization.load_pem_public_key(public_bytes)
    if not isinstance(public, rsa.RSAPublicKey) or public.key_size != 3072:
        raise Unavailable('public_key_invalid')
    aad = {'version': 1, **binding(), 'image': IMAGE, 'packageSha256': package_hash, 'publicKeySha256': digest(public_bytes)}
    print(seal(result, aad, public), flush=True)
    if not result['ownedCleanupComplete']:
        raise Unavailable('cleanup_incomplete')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'consume', 'worker', 'cleanup'))
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    try:
        if args.action == 'prepare':
            prepare()
        elif args.action == 'worker':
            worker()
        elif args.action == 'consume':
            consume()
        else:
            path = package_path()
            if path.exists():
                cleanup_package(path)
        return 0
    except BaseException as error:
        # No traceback, path, subprocess stderr or private metadata reaches CI.
        if args.action != 'worker':
            report_unavailable(args.action, error)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
