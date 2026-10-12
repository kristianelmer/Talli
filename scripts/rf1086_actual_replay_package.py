"""Private, bounded runner-local transfer of an already rejected restore.

Publication is diagnostic only, after the owner's cleanup and source postcheck.
No database work, key access or recovery acceptance occurs in this module.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time
from uuid import uuid4

from rf1086_catalog_difference import _encoded, _object, _reject_constant

IMAGE = 'sha256:2d3ac69ad5c95d81458cc93a6cc6c31a98dfa00cd28f88a0a9358d315e1c357a'
LIMITS = {'roles.sql': 2 * 1024**2, 'archive.dump': 64 * 1024**2,
          'source.catalog': 8 * 1024**2, 'failed.catalog': 8 * 1024**2,
          'metadata.json': 128 * 1024}
CODE_FILES = ('rf1086_identity_restore.py', 'rf1086_catalog_causal.sql',
              'rf1086_catalog_causal_capture.py', 'rf1086_actual_replay_package.py',
              'rf1086_actual_replay.py', 'rf1086_catalog_semantics.py',
              'rf1086_raw_toc.py', 'rf1086_sql_identifiers.py',
              'rf1086_sql_lexical.py', 'rf1086_sql_ledger.py')
_EXPORT_STARTED = None
STATUS_TAG = 'owned_identity_actual_replay_status_v1 '
STATUS_REASONS = frozenset({
    'binding_invalid', 'path_invalid', 'directory_invalid', 'file_invalid', 'owner_invalid',
    'export_budget_exhausted', 'export_oversized', 'export_deadline', 'export_budget_unknown',
    'package_not_empty', 'capture_unavailable', 'source_network_unbound', 'catalog_unavailable',
    'metadata_oversized', 'package_incomplete', 'package_hash_mismatch', 'package_binding_mismatch',
    'job_headroom_unproved', 'worker_failed', 'cleanup_incomplete', 'cleanup_package_unexpected',
    'public_key_invalid', 'summary_oversized', 'envelope_oversized',
})


class Unavailable(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__('actual_replay_unavailable')


def start_export_clock():
    global _EXPORT_STARTED
    if _EXPORT_STARTED is None:
        _EXPORT_STARTED = time.monotonic()


def report_unavailable(action, error):
    """Only finite labels; never stringify an exception or private payload."""
    action = action if action in ('publication', 'prepare', 'consume', 'cleanup') else 'operation'
    reason = 'operation_failed'
    if type(error) is Unavailable and error.reason in STATUS_REASONS:
        reason = error.reason
    elif isinstance(error, FileNotFoundError):
        reason = 'private_file_missing'
    try:
        print(STATUS_TAG + _encoded({'status': 'unavailable', 'action': action, 'reason': reason}).decode(), file=sys.stderr)
    except Exception:
        pass  # A diagnostic must not replace the original strict rejection.


def digest(data):
    return hashlib.sha256(data).hexdigest()


def binding():
    result = {name: os.environ.get(env, '') for name, env in (
        ('run', 'GITHUB_RUN_ID'), ('attempt', 'GITHUB_RUN_ATTEMPT'), ('mergeSha', 'GITHUB_SHA'))}
    if (not re.fullmatch(r'[1-9][0-9]{0,19}', result['run'])
            or not re.fullmatch(r'[1-9][0-9]{0,5}', result['attempt'])
            or not re.fullmatch(r'[a-f0-9]{40}', result['mergeSha'])):
        raise Unavailable('binding_invalid')
    return result


def code_hashes():
    return {name: digest(Path(__file__).with_name(name).read_bytes()) for name in CODE_FILES}


def package_path():
    parent = Path(os.environ['RUNNER_TEMP'])
    current = binding()
    expected = parent / ('talli-rf-replay-' + current['run'] + '-' + current['attempt'])
    if (os.environ.get('TALLI_RF_REPLAY_DIR') != str(expected)
            or not parent.is_absolute() or parent.resolve() != parent):
        raise Unavailable('path_invalid')
    return expected


def private_directory(path):
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.getuid():
        raise Unavailable('directory_invalid')


def read_private(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_size > limit):
            raise Unavailable('file_invalid')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit or len(raw) != info.st_size:
            raise Unavailable('file_invalid')
        return raw
    finally:
        os.close(fd)


def write_private(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)


def load_json(raw):
    return json.loads(raw, object_pairs_hook=_object, parse_constant=_reject_constant)


def owner(path):
    private_directory(path)
    record = load_json(read_private(path / 'owner.json', 4096))
    if (set(record) != {'version', 'binding', 'nonce'} or record['version'] != 1
            or record['binding'] != binding() or not re.fullmatch(r'[a-f0-9]{32}', record['nonce'])):
        raise Unavailable('owner_invalid')
    return record


def prepare():
    path = package_path()
    path.mkdir(mode=0o700)
    write_private(path / 'owner.json', _encoded({'version': 1, 'binding': binding(), 'nonce': uuid4().hex}))


def _check_time(deadline):
    if time.monotonic() >= deadline:
        raise Unavailable('export_budget_exhausted')


def _copy(stream, path, cap, deadline):
    position = stream.tell()
    total, hashed = 0, hashlib.sha256()
    try:
        stream.seek(0)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as output:
            while True:
                _check_time(deadline)
                block = stream.read(65536)
                if not block:
                    break
                total += len(block)
                if total > cap:
                    raise Unavailable('export_oversized')
                output.write(block)
                hashed.update(block)
        return {'bytes': total, 'sha256': hashed.hexdigest()}
    finally:
        stream.seek(position)


def publish(**inputs):
    """Hard wall bound in the single-threaded owning Python child."""
    if not os.environ.get('TALLI_RF_REPLAY_DIR') or any(signal.getitimer(signal.ITIMER_REAL)):
        return False
    previous = signal.getsignal(signal.SIGALRM)

    def expired(*_):
        raise Unavailable('export_deadline')

    try:
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, 3)
        return _publish(**inputs)
    except Exception as error:
        report_unavailable('publication', error)
        return False
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _publish(*, roles, dump, source, auth, preload, before, failed, source_raw, failed_raw, causal, init):
    """Best effort; only caller's already-completed cleanup can reach this seam."""
    if not os.environ.get('TALLI_RF_REPLAY_DIR'):
        return False
    try:
        allowance = int(os.environ.get('TALLI_RF_REPLAY_EXPORT_MS', '0')) / 1000
        if _EXPORT_STARTED is None or not 5 <= allowance <= 150:
            raise Unavailable('export_budget_unknown')
        now = time.monotonic()
        deadline = min(now + 3, _EXPORT_STARTED + allowance - 10)
        _check_time(deadline)
        path = package_path()
        ownership = owner(path)
        if set(p.name for p in path.iterdir()) != {'owner.json'}:
            raise Unavailable('package_not_empty')
        phases = getattr(causal, 'replay_snapshots', None)
        if (not phases or source['Image'] != IMAGE or set(before) != set(failed)
                or before.get('catalog') == failed.get('catalog')
                or any(before[k] != failed[k] for k in before if k != 'catalog')):
            raise Unavailable('capture_unavailable')
        networks = [name for name in source['NetworkSettings']['Networks']
                    if re.fullmatch(r'supabase_network_[A-Za-z0-9_-]{1,80}', name)]
        if len(networks) != 1:
            raise Unavailable('source_network_unbound')
        metadata = {'version': 1, 'binding': binding(), 'nonce': ownership['nonce'], 'image': IMAGE,
                    'source': source['Id'], 'sourceAuth': auth['Id'], 'sourceNetwork': networks[0],
                    'preload': preload, 'initSha256': digest(init.encode()), 'code': code_hashes(),
                    'before': before, 'failed': failed, 'phases': phases,
                    'cleanupComplete': True, 'identitySourcePostcheck': True,
                    'outerBusinessPostchecks': False, 'failure': 'catalog_only', 'files': {}}
        for name, stream in (('roles.sql', roles), ('archive.dump', dump)):
            metadata['files'][name] = _copy(stream, path / name, LIMITS[name], deadline)
        for name, raw in (('source.catalog', source_raw), ('failed.catalog', failed_raw)):
            _check_time(deadline)
            if type(raw) is not bytes or len(raw) > LIMITS[name]:
                raise Unavailable('catalog_unavailable')
            write_private(path / name, raw)
            metadata['files'][name] = {'bytes': len(raw), 'sha256': digest(raw)}
        metadata['exportBudget'] = {'allowanceSeconds': allowance, 'hardCapSeconds': 3,
            'unwindReserveSeconds': 10, 'elapsedAtStart': now - _EXPORT_STARTED,
            'copyElapsedSeconds': time.monotonic() - now,
            'remainingBeforePublication': deadline - time.monotonic()}
        raw = _encoded(metadata)
        if len(raw) > LIMITS['metadata.json']:
            raise Unavailable('metadata_oversized')
        write_private(path / 'metadata.json', raw)
        _check_time(deadline)
        ready = _encoded({'version': 1, 'metadataSha256': digest(raw)})
        write_private(path / 'ready.pending', ready)
        _check_time(deadline)
        os.rename(path / 'ready.pending', path / 'ready.json')
        return True
    except Exception as error:
        # A partial private package is handled by the workflow's always cleanup.
        # Never mask the original strict mismatch or emit sensitive exceptions.
        report_unavailable('publication', error)
        return False


def read_package():
    path = package_path()
    ownership = owner(path)
    if set(p.name for p in path.iterdir()) != {'owner.json', 'ready.json', *LIMITS}:
        raise Unavailable('package_incomplete')
    ready = load_json(read_private(path / 'ready.json', 1024))
    raw = read_private(path / 'metadata.json', LIMITS['metadata.json'])
    if ready != {'version': 1, 'metadataSha256': digest(raw)}:
        raise Unavailable('package_hash_mismatch')
    metadata = load_json(raw)
    if (metadata.get('version') != 1 or metadata.get('binding') != binding()
            or metadata.get('nonce') != ownership['nonce'] or metadata.get('image') != IMAGE
            or metadata.get('code') != code_hashes()
            or metadata.get('failure') != 'catalog_only'
            or metadata.get('cleanupComplete') is not True
            or metadata.get('identitySourcePostcheck') is not True
            or set(metadata.get('files', {})) != set(LIMITS) - {'metadata.json'}):
        raise Unavailable('package_binding_mismatch')
    for name, entry in metadata['files'].items():
        data = read_private(path / name, LIMITS[name])
        if entry != {'bytes': len(data), 'sha256': digest(data)}:
            raise Unavailable('package_hash_mismatch')
    return path, metadata, digest(raw)
