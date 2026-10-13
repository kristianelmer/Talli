"""A larger bounded capture still needs complete delivery and owned cleanup."""
from copy import deepcopy
import hashlib
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from test_rf1086_actual_replay import setup, toc
from test_rf1086_full_sql_control import control, completed
import rf1086_actual_replay as replay
import rf1086_actual_replay_package as package
import rf1086_catalog_semantics as commands


def test_real_40mib_capture_and_backpressured_short_writes_preserve_every_byte(monkeypatch, capsys):
    block = bytes(range(256))*256
    expected = hashlib.sha256()
    for _ in range(640): expected.update(block)
    children, writes = [], []
    original_popen, original_write = subprocess.Popen, os.write
    def spawn(*args, **kw):
        child = original_popen(*args, **kw); children.append(child); return child
    def write(fd, data):
        if len(children) == 2 and fd == children[1].stdin.fileno():
            # Exercise unwritten suffixes across both pipe and input-block cuts.
            count = original_write(fd, data[:4093]); writes.append(count); return count
        return original_write(fd, data)
    monkeypatch.setattr(commands.subprocess, 'Popen', spawn)
    monkeypatch.setattr(commands.os, 'write', write)
    before = commands.MAX_BYTES
    producer = 'import sys; b=bytes(range(256))*256\nfor _ in range(640):sys.stdout.buffer.write(b)'
    script = replay.command([sys.executable, '-c', producer], time.monotonic()+10, cap=replay.MAX_SQL_BYTES)
    assert len(script) == 40*1024**2 and hashlib.sha256(script).hexdigest() == expected.hexdigest()
    consumer = ('import hashlib,json,os,sys\nh=hashlib.sha256();n=0\n'
                'while b:=sys.stdin.buffer.read(4093):\n h.update(b);n+=len(b);os.write(2,b".")\n'
                'print(json.dumps({"bytes":n,"sha256":h.hexdigest()}))')
    output = replay.command([sys.executable, '-c', consumer], time.monotonic()+10, data=script, cap=4096)
    assert json.loads(output) == {'bytes': len(script), 'sha256': expected.hexdigest()}
    assert sum(writes) == len(script) and len(writes) > 640
    assert len(children) == 2 and all(c.poll() == 0 for c in children)
    assert commands.MAX_BYTES == before and capsys.readouterr() == ('', '')


@pytest.mark.parametrize('extra', [-1, 0, 1, 8192, 65536])
def test_reduced_capture_boundary_retains_no_overflow_result(monkeypatch, capsys, extra):
    # Reduced bound tests capture's existing one-read detector, not measurement's +1.
    cap = 65538
    children = []
    original = subprocess.Popen
    def spawn(*args, **kw):
        child = original(*args, **kw); children.append(child); return child
    monkeypatch.setattr(commands.subprocess, 'Popen', spawn)
    before = commands.MAX_BYTES
    argv = [sys.executable, '-c', f'import sys;sys.stdout.buffer.write(b"x"*{cap+extra})']
    if extra <= 0:
        assert replay.command(argv, time.monotonic()+3, cap=cap) == b'x'*(cap+extra)
    else:
        with pytest.raises(replay.CommandUnavailable) as caught:
            replay.command(argv, time.monotonic()+3, cap=cap)
        value = caught.value.observation
        assert value['kind'] == 'stdout_limit' and cap < value['stdoutBytes'] <= cap+65536
        assert value['stdoutCap'] == cap and value['exitCode'] is None
        assert set(vars(caught.value)) == {'observation', 'reason'}
    assert all(c.poll() is not None for c in children)
    assert commands.MAX_BYTES == before and capsys.readouterr() == ('', '')


def test_successful_early_child_exit_with_unsent_sql_is_unavailable(monkeypatch):
    children = []
    original = subprocess.Popen
    def spawn(*args, **kw):
        child = original(*args, **kw); children.append(child); return child
    monkeypatch.setattr(commands.subprocess, 'Popen', spawn)
    with pytest.raises(package.Unavailable):
        replay.command([sys.executable, '-c', 'raise SystemExit(0)'], time.monotonic()+3,
                       data=b'x'*(4*1024**2), cap=4096)
    assert children[0].poll() == 0


@pytest.mark.parametrize('failure', [MemoryError, KeyboardInterrupt])
def test_generation_allocation_failure_or_cancellation_restores_cap_without_success(control, monkeypatch, failure):
    path, metadata, f2, _, _, failed = control
    before = commands.MAX_BYTES
    error = failure('synthetic')
    def command(args, *a, **kw):
        if args[-1] == replay.TOOL_COMMAND:
            return b'pg_restore (PostgreSQL) 17.6\n'+b'f'*64+b'\n'
        assert commands.MAX_BYTES == 128*1024**2
        raise error
    monkeypatch.setattr(commands, '_command', command)
    if failure is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt) as caught:
            replay.add_full_sql(path, metadata, 'owned', b'roles', failed, f2, time.monotonic()+416)
        assert caught.value is error
    else:
        result = replay.add_full_sql(path, metadata, 'owned', b'roles', failed, f2, time.monotonic()+416)
        assert result['Fsql']['status'] == 'unavailable'
        assert result['Fsql']['failure']['stage'] == 'full_script_generation'
        assert result['Fsql']['failure']['stream'] is None
    assert commands.MAX_BYTES == before and replay.read_f2(path, metadata) == f2


@pytest.mark.parametrize('size,valid', [(33554433, True), (134217728, True), (134217729, False), (True, False)])
def test_complete_capture_metadata_uses_the_explicit_new_limit(size, valid):
    stream = {'bytes': size, 'sha256': 'a'*64}
    if valid: replay.validate_stream(stream)
    else:
        with pytest.raises(package.Unavailable): replay.validate_stream(stream)


@pytest.mark.parametrize('cap,slack,valid', [(134217728, 1, True), (134217728, 65536, True),
    (134217728, 65537, False), (33554432, 1, False)])
def test_generation_failure_rejects_old_cap_and_extra_detection_bytes(cap, slack, valid):
    failure = {'stage': 'full_script_generation', 'tool': {'version': '17.6', 'sha256': 'a'*64},
        'stream': None, 'command': {'kind': 'stdout_limit', 'stdoutBytes': cap+slack,
            'stderrBytes': 0, 'stdoutCap': cap, 'exitCode': None}}
    if valid: replay.validate_failure(failure, 'command_unavailable')
    else:
        with pytest.raises(package.Unavailable): replay.validate_failure(failure, 'command_unavailable')


@pytest.mark.parametrize('cleanup', ['complete', 'incomplete', 'exception', 'cancel'])
def test_parent_requires_final_cleanup_before_full_sql_success(control, monkeypatch, capsys, cleanup):
    path, _, f2, optional, _, _ = control
    monkeypatch.setenv('TALLI_RF_REPLAY_JOB_STARTED', str(time.monotonic()))
    class Child:
        returncode = 0
        def __init__(self): package.write_private(path/'result.json', package._encoded(completed(f2, optional)))
        def wait(self, **kw): return 0
    monkeypatch.setattr(replay.subprocess, 'Popen', lambda *a, **kw: Child())
    failure = KeyboardInterrupt() if cleanup == 'cancel' else RuntimeError('cleanup unproved')
    def clean(*args):
        if cleanup in ('exception', 'cancel'): raise failure
        return cleanup == 'complete'
    monkeypatch.setattr(replay, 'cleanup_resources', clean)
    seen = []
    monkeypatch.setattr(replay, 'seal', lambda result, *a: seen.append(deepcopy(result)) or 'sealed')
    handlers = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        if cleanup == 'complete': replay.consume()
        elif cleanup == 'incomplete':
            with pytest.raises(package.Unavailable) as caught: replay.consume()
            assert caught.value.reason == 'cleanup_incomplete'
        else:
            with pytest.raises(type(failure)) as caught: replay.consume()
            assert caught.value is failure
    finally:
        for sig, handler in handlers.items(): signal.signal(sig, handler)
    if cleanup in ('exception', 'cancel'):
        assert not seen and capsys.readouterr() == ('', '')
        return
    assert capsys.readouterr().out == 'sealed\n'
    assert seen[0]['Fsql'] == (optional if cleanup == 'complete' else replay.unavailable_fsql('full_sql_final_cleanup_unproved'))
    assert seen[0]['optionalWorkerOutcome'] == 'completed'
    assert seen[0]['ownedCleanupComplete'] is (cleanup == 'complete')


def test_actual_replay_selects_one_full_control_after_verified_f2(control, monkeypatch):
    import rf1086_identity_restore as identity
    path, metadata, _, optional, _, failed = control
    calls = []
    monkeypatch.setattr(replay, 'assert_source_absent', lambda *a: None)
    monkeypatch.setattr(replay, 'start_target', lambda *a: calls.append('start') or 'owned')
    monkeypatch.setattr(replay, 'installed_files', lambda *a: {})
    monkeypatch.setattr(replay, 'psql', lambda *a, **kw: calls.append('psql'))
    monkeypatch.setattr(replay, '_snapshot', lambda *a, **kw: metadata['phases']['mismatch']['catalog'])
    monkeypatch.setattr(commands, '_measure_command', lambda *a, **kw: pytest.fail('measurement is not selected'))
    def fingerprint(*a, catalog_capture, **kw):
        catalog_capture.capture(failed); return metadata['failed']
    monkeypatch.setattr(identity, 'fingerprint', fingerprint)
    monkeypatch.setattr(replay, 'command', lambda args, *a, **kw: toc() if '--list' in args else b'schema-only-writer-output')
    def capture(p, m, target, roles, raw, until, *, toc, inventory):
        assert replay.read_f2(p, m)['F2EqualsF'] is True
        assert target == 'owned' and raw == failed and b'CREATE ROLE supabase_admin;' not in roles
        assert inventory['sha256'] == package.digest(toc)
        calls.append('full-control'); return optional
    monkeypatch.setattr(replay, 'full_sql_control', capture)
    result = replay.replay(path, metadata, time.monotonic()+416)
    assert calls == ['start', 'psql', 'psql', 'full-control']
    assert result['F2EqualsF'] and result['Fsql'] == optional
    assert result['S0'] == replay.s0_protocol.unavailable('dependency', 'admission')
    assert result['Is'] == 'unavailable'
