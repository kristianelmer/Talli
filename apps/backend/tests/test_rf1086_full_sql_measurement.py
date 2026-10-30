"""A discarded complete stream is size evidence, never restore equality."""
from copy import deepcopy
import hashlib
import os
import signal
import subprocess
import sys
import time
import tracemalloc

from cryptography.hazmat.primitives import serialization
import pytest

from test_rf1086_actual_replay import setup, key, toc
from test_rf1086_full_sql_control import control, completed
import rf1086_actual_replay as replay
import rf1086_actual_replay_package as package
import rf1086_catalog_semantics as commands


def measurement(size=40 * 1024**2):
    return {'schema': 'full-sql-generation-measurement-v1', 'status': 'complete',
        'reason': None, 'stage': 'full_script_measurement',
        'tool': {'version': '17.6', 'sha256': 'f'*64},
        'stream': {'bytes': size, 'sha256': 'e'*64}, 'command': None, 'sqlApplied': False}


def optional(value=None):
    return {'status': 'unavailable', 'reason': 'measurement_only', 'FsqlEqualsF2': False,
        'causalAttributionAccepted': False, 'recoveryAccepted': False,
        'measurement': measurement() if value is None else value}


def test_large_real_stream_is_hashed_without_aggregate_retention(capsys):
    chunk = bytes(range(256))*256
    expected = hashlib.sha256()
    for _ in range(640): expected.update(chunk)
    code = 'import sys; b=bytes(range(256))*256\nfor _ in range(640):sys.stdout.buffer.write(b)'
    tracemalloc.start()
    try:
        result = commands._measure_command([sys.executable, '-c', code], time.monotonic()+5)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result == {'bytes': 40*1024**2, 'sha256': expected.hexdigest()}
    assert peak < 4*1024**2  # Includes controller/interpreter bookkeeping, not just pipe payload.
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('extra', [-1, 0, 1, 8192])
def test_measurement_ceiling_has_exact_one_byte_detection_budget(monkeypatch, extra):
    cap = 65538
    monkeypatch.setattr(commands, 'MAX_MEASUREMENT_BYTES', cap)
    original_read, original_popen = os.read, subprocess.Popen
    fd, reads, children = [], [], []
    def spawn(*args, **kw):
        child = original_popen(*args, **kw)
        children.append(child); fd.append(child.stdout.fileno()); return child
    def read(number, size):
        raw = original_read(number, size)
        if fd and number == fd[0]: reads.append((size, len(raw)))
        return raw
    monkeypatch.setattr(commands.subprocess, 'Popen', spawn)
    monkeypatch.setattr(commands.os, 'read', read)
    code = f'import sys;sys.stdout.buffer.write(b"x"*{cap+extra})'
    if extra <= 0:
        result = commands._measure_command([sys.executable, '-c', code], time.monotonic()+3)
        assert result == {'bytes': cap+extra, 'sha256': package.digest(b'x'*(cap+extra))}
        assert reads[-1][1] == 0
    else:
        with pytest.raises(commands.CommandFailure) as caught:
            commands._measure_command([sys.executable, '-c', code], time.monotonic()+3)
        assert caught.value.observation == {'kind': 'stdout_limit', 'stdoutBytes': cap+1,
            'stderrBytes': 0, 'stdoutCap': cap, 'exitCode': None}
        assert set(vars(caught.value)) == {'observation'}
    consumed = 0
    for size, count in reads:
        assert 0 < size <= min(65536, cap+1-consumed)
        consumed += count
    assert consumed <= cap+1 and all(c.poll() is not None for c in children)


@pytest.mark.parametrize('code,kind,exit_code', [
    ('import os;os.write(1,b"x"*32);os.close(1);os.close(2);raise SystemExit(7)', 'nonzero_exit', 7),
    ('import os;os.write(2,b"private-canary"*6000)', 'stderr_limit', None),
    ('import time;time.sleep(10)', 'deadline', None),
])
def test_incomplete_commands_never_return_a_digest(code, kind, exit_code, capsys):
    with pytest.raises(commands.CommandFailure) as caught:
        commands._measure_command([sys.executable, '-c', code], time.monotonic()+0.3)
    assert caught.value.observation['kind'] == kind
    assert caught.value.observation['exitCode'] == exit_code
    assert set(vars(caught.value)) == {'observation'}
    assert str(caught.value) == 'catalog_semantics_unavailable'
    assert capsys.readouterr() == ('', '')


def test_archive_input_and_concurrent_stderr_are_opaque(tmp_path):
    raw = bytes(range(256))*16
    source = tmp_path/'source'; source.write_bytes(raw)
    code = 'import os,sys;os.write(2,b"diagnostic");sys.stdout.buffer.write(sys.stdin.buffer.read())'
    with source.open('rb') as archive:
        value = commands._measure_command([sys.executable, '-c', code], time.monotonic()+3, archive=archive)
    assert value == {'bytes': len(raw), 'sha256': package.digest(raw)}


def test_inherited_open_pipe_cannot_be_treated_as_complete(monkeypatch):
    children = []
    original = subprocess.Popen
    def spawn(*a, **kw):
        child = original(*a, **kw); children.append(child); return child
    monkeypatch.setattr(commands.subprocess, 'Popen', spawn)
    # The direct child exits immediately; a short-lived descendant holds both pipes.
    code = 'import os,time\npid=os.fork()\nif pid==0:time.sleep(0.4);os._exit(0)\nos._exit(0)'
    started = time.monotonic()
    try:
        with pytest.raises(commands.CommandFailure) as caught:
            commands._measure_command([sys.executable, '-c', code], started+0.15)
        assert caught.value.observation['kind'] == 'deadline'
        assert children[0].poll() == 0
    finally:
        # Allow this bounded fixture's descendant to finish; no persistent child.
        time.sleep(max(0, started+0.6-time.monotonic()))


@pytest.mark.parametrize('fault', ['hash_cancel', 'kill_uncertain', 'wait_uncertain', 'cancel_and_cleanup'])
def test_measurement_teardown_cannot_publish_success_or_mask_cancellation(monkeypatch, fault):
    children = []
    original_popen, original_hash = subprocess.Popen, hashlib.sha256
    primary = KeyboardInterrupt('initiating-cancellation')
    class Hash:
        def __init__(self): self.value = original_hash()
        def update(self, raw):
            if fault in ('hash_cancel', 'cancel_and_cleanup'): raise primary
            self.value.update(raw)
        def hexdigest(self): return self.value.hexdigest()
    monkeypatch.setattr(commands.hashlib, 'sha256', Hash)
    def spawn(*args, **kw):
        child = original_popen(*args, **kw); children.append(child)
        kill, wait = child.kill, child.wait
        def uncertain_kill():
            kill()
            raise RuntimeError('kill-uncertain')
        def uncertain_wait(*a, **kw):
            result = wait(*a, **kw)
            if fault in ('wait_uncertain', 'cancel_and_cleanup'): raise RuntimeError('wait-uncertain')
            return result
        if fault == 'kill_uncertain': child.kill = uncertain_kill
        child.wait = uncertain_wait
        return child
    monkeypatch.setattr(commands.subprocess, 'Popen', spawn)
    code = 'import os,time;os.write(1,b"x");time.sleep(10)'
    with pytest.raises(KeyboardInterrupt if fault in ('hash_cancel', 'cancel_and_cleanup') else RuntimeError) as caught:
        commands._measure_command([sys.executable, '-c', code], time.monotonic()+0.2)
    if fault in ('hash_cancel', 'cancel_and_cleanup'): assert caught.value is primary
    assert all(c.poll() is not None for c in children)


@pytest.mark.parametrize('fault', [None, 'tool_invalid', 'empty', 'typed', 'unknown', 'cancel'])
def test_one_generator_after_checkpoint_with_no_sql_application(control, monkeypatch, fault):
    path, metadata, f2, _, _, _ = control
    calls = []
    deadline = time.monotonic()+416
    def probe(args, until, **kw):
        assert replay.read_f2(path, metadata) == f2
        assert until == deadline-12 and kw == {'cap': 4096}
        assert args == ['docker', 'exec', 'owned', 'sh', '-c', replay.TOOL_COMMAND]
        calls.append('tool')
        return b'invalid' if fault == 'tool_invalid' else b'pg_restore (PostgreSQL) 17.6\n'+b'f'*64+b'\n'
    def meter(args, until, *, archive):
        assert args == ['docker', 'exec', '-i', 'owned', 'sh', '-c', replay.FULL_SQL_COMMAND]
        assert archive.read() == (path/'archive.dump').read_bytes()
        assert 0 < until-time.monotonic() <= 43
        calls.append('meter')
        if fault == 'typed': raise commands.CommandFailure('stdout_limit', commands.MAX_MEASUREMENT_BYTES+1, 0, commands.MAX_MEASUREMENT_BYTES)
        if fault == 'unknown': raise RuntimeError('private-canary')
        if fault == 'cancel': raise KeyboardInterrupt()
        return {'bytes': 0 if fault == 'empty' else 40*1024**2, 'sha256': 'e'*64}
    monkeypatch.setattr(replay, 'command', probe)
    monkeypatch.setattr(commands, '_measure_command', meter)
    for name in ('start_target', 'psql', 'cleanup_resources', 'full_sql_control'):
        monkeypatch.setattr(replay, name, lambda *a, **k: pytest.fail('measurement must not apply or replace target'))
    if fault == 'cancel':
        with pytest.raises(KeyboardInterrupt): replay.add_full_sql_measurement(path, metadata, 'owned', f2, deadline)
        return
    value = replay.add_full_sql_measurement(path, metadata, 'owned', f2, deadline)['Fsql']
    assert replay.validate_fsql(value, metadata) == value
    assert value['FsqlEqualsF2'] is False and value['reason'] == 'measurement_only'
    measured = value['measurement']
    assert measured['status'] == ('complete' if fault is None else 'unavailable')
    if fault is not None: assert measured['stream'] is None
    assert b'private-canary' not in package._encoded(value)
    assert calls == (['tool'] if fault == 'tool_invalid' else ['tool', 'meter'])


@pytest.mark.parametrize('size', [1, 33554432, 33554433, 134217728])
def test_measurement_and_materialized_stream_validators_have_independent_budgets(monkeypatch, size):
    # Deliberately distinct fixture budgets even when production caps coincide.
    monkeypatch.setattr(replay, 'MAX_SQL_BYTES', 32 * 1024**2)
    replay.validate_fsql(optional(measurement(size)), {})
    if size > replay.MAX_SQL_BYTES:
        with pytest.raises(package.Unavailable): replay.validate_stream(measurement(size)['stream'])
    else: replay.validate_stream(measurement(size)['stream'])


@pytest.mark.parametrize('fault', [
    'extra_optional', 'failure_field', 'accepted', 'recovery', 'causal', 'extra_measurement',
    'schema', 'status', 'stage', 'applied', 'tool_version', 'tool_hash', 'stream_extra',
    'bytes_bool', 'bytes_zero', 'bytes_over', 'hash', 'reason_complete', 'command_complete',
    'complete_probe', 'missing_tool', 'incomplete_stream', 'unknown_reason', 'empty_probe',
    'tool_reason_generation', 'noncommand_details', 'probe_milestone', 'outcome_extra',
    'outcome_kind', 'out_bool', 'cap_bool', 'cap_wrong', 'out_over', 'out_under',
    'err_over', 'err_under', 'exit_zero', 'exit_bool', 'exit_high', 'deadline_exit',
])
def test_measurement_forgeries_are_rejected(fault):
    value = optional(); m = value['measurement']; stream = m['stream']
    outcome = {'kind': 'stdout_limit', 'stdoutBytes': commands.MAX_MEASUREMENT_BYTES+1,
               'stderrBytes': 0, 'stdoutCap': commands.MAX_MEASUREMENT_BYTES, 'exitCode': None}
    if fault == 'extra_optional': value['extra'] = 1
    elif fault == 'failure_field': value['failure'] = {}
    elif fault == 'accepted': value['FsqlEqualsF2'] = True
    elif fault == 'recovery': value['recoveryAccepted'] = True
    elif fault == 'causal': value['causalAttributionAccepted'] = True
    elif fault == 'extra_measurement': m['extra'] = 1
    elif fault == 'schema': m['schema'] = 'unknown'
    elif fault == 'status': m['status'] = []
    elif fault == 'stage': m['stage'] = []
    elif fault == 'applied': m['sqlApplied'] = 0
    elif fault == 'tool_version': m['tool']['version'] = '17.11'
    elif fault == 'tool_hash': m['tool']['sha256'] = 'raw'
    elif fault == 'stream_extra': stream['extra'] = 1
    elif fault == 'bytes_bool': stream['bytes'] = True
    elif fault == 'bytes_zero': stream['bytes'] = 0
    elif fault == 'bytes_over': stream['bytes'] = commands.MAX_MEASUREMENT_BYTES+1
    elif fault == 'hash': stream['sha256'] = 'raw'
    elif fault == 'reason_complete': m['reason'] = 'empty'
    elif fault == 'command_complete': m['command'] = outcome
    elif fault == 'complete_probe': m.update(stage='tool_probe', tool=None)
    elif fault == 'missing_tool': m['tool'] = None
    else:
        m.update(status='unavailable', reason='command_unavailable', stream=None, command=outcome)
        if fault == 'incomplete_stream': m['stream'] = stream
        elif fault == 'unknown_reason': m['reason'] = 'raw'
        elif fault == 'empty_probe': m.update(reason='empty', stage='tool_probe', tool=None, command=None)
        elif fault == 'tool_reason_generation': m.update(reason='tool_invalid', command=None)
        elif fault == 'noncommand_details': m['reason'] = 'control_unavailable'
        elif fault == 'probe_milestone': m.update(stage='tool_probe')
        elif fault == 'outcome_extra': outcome['raw'] = 'canary'
        elif fault == 'outcome_kind': outcome['kind'] = []
        elif fault == 'out_bool': outcome['stdoutBytes'] = True
        elif fault == 'cap_bool': outcome['stdoutCap'] = True
        elif fault == 'cap_wrong': outcome['stdoutCap'] = commands.MAX_MEASUREMENT_BYTES - 1
        elif fault == 'out_over': outcome['stdoutBytes'] += 1
        elif fault == 'out_under': outcome['stdoutBytes'] -= 1
        elif fault == 'err_over': outcome['stderrBytes'] = 131073
        elif fault == 'err_under': outcome.update(kind='stderr_limit', stdoutBytes=0)
        elif fault.startswith('exit_'): outcome.update(kind='nonzero_exit', stdoutBytes=0, exitCode={'exit_zero':0,'exit_bool':True,'exit_high':256}[fault])
        elif fault == 'deadline_exit': outcome.update(kind='deadline', stdoutBytes=0, exitCode=1)
    with pytest.raises(package.Unavailable): replay.validate_fsql(value, {})


@pytest.mark.parametrize('cleanup', [True, False])
def test_actual_parent_redacts_measurement_when_owned_cleanup_is_unproved(control, monkeypatch, capsys, cleanup):
    path, metadata, f2, _, _, _ = control
    monkeypatch.setenv('TALLI_RF_REPLAY_JOB_STARTED', str(time.monotonic()))
    class Child:
        returncode = 0
        def __init__(self):
            package.write_private(path/'result.json', package._encoded(completed(f2, optional())))
        def wait(self, **kw): return 0
    monkeypatch.setattr(replay.subprocess, 'Popen', lambda *a, **kw: Child())
    monkeypatch.setattr(replay, 'cleanup_resources', lambda *a: cleanup)
    seen = []
    monkeypatch.setattr(replay, 'seal', lambda result, *a: seen.append(deepcopy(result)) or 'sealed')
    handlers = {s:signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        if cleanup: replay.consume()
        else:
            with pytest.raises(package.Unavailable) as caught: replay.consume()
            assert caught.value.reason == 'cleanup_incomplete'
    finally:
        for sig, handler in handlers.items(): signal.signal(sig, handler)
    assert capsys.readouterr().out == 'sealed\n'
    assert seen[0]['Fsql'] == (optional() if cleanup else replay.unavailable_fsql('measurement_cleanup_unproved'))
    assert seen[0]['optionalWorkerOutcome'] == 'completed'
    assert seen[0]['ownedCleanupComplete'] is cleanup


def test_oversized_optional_measurement_preserves_f2(control, monkeypatch):
    _, metadata, f2, _, _, _ = control
    fallback = replay.unavailable_fsql('summary_oversized')
    size = len(package._encoded(completed(f2, fallback, reason='summary_oversized', stage='composition') | {'optionalWorkerOutcome':'result_invalid', 'ownedCleanupComplete':False}))
    monkeypatch.setattr(replay, 'MAX_PLAINTEXT', size)
    assert replay.fit_optional(f2, optional(), metadata) == completed(f2, fallback, reason='summary_oversized', stage='composition')


@pytest.mark.parametrize('stage', ['tool_probe', 'full_script_measurement'])
@pytest.mark.parametrize('kind', ['deadline', 'stdout_limit', 'stderr_limit', 'nonzero_exit'])
def test_measurement_command_outcome_exact_bounds(stage, kind):
    value = measurement()
    cap, slack = (4096, 65536) if stage == 'tool_probe' else (commands.MAX_MEASUREMENT_BYTES, 1)
    value.update(status='unavailable', reason='command_unavailable', stage=stage, stream=None,
        command={'kind': kind, 'stdoutBytes': cap+(slack if kind == 'stdout_limit' else 0),
                 'stderrBytes': 131072 if kind == 'stderr_limit' else 65536,
                 'stdoutCap': cap, 'exitCode': -127 if kind == 'nonzero_exit' else None})
    if stage == 'tool_probe': value['tool'] = None
    assert replay.validate_measurement(value) == value


def test_measurement_encryption_limits_and_fallback(control, monkeypatch, key):
    _, metadata, f2, _, _, _ = control
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    aad = {'version': 3, **metadata['binding'], 'image': package.IMAGE,
           'packageSha256': 'a'*64, 'publicKeySha256': package.digest(public)}
    result = replay.fit_optional(f2, optional(), metadata)
    result.update(optionalWorkerOutcome='completed', ownedCleanupComplete=True)
    raw = package._encoded(result)
    monkeypatch.setattr(replay, 'MAX_PLAINTEXT', len(raw))
    line = replay.seal(result, aad, key.public_key())
    assert len(line.encode()) <= 96*1024
    assert replay.decrypt(line, key, {k:v for k,v in aad.items() if k!='version'}) == result
    monkeypatch.setattr(replay, 'MAX_PLAINTEXT', len(raw)-1)
    with pytest.raises(package.Unavailable): replay.seal(result, aad, key.public_key())
    monkeypatch.setattr(replay, 'MAX_PLAINTEXT', 64*1024)
    monkeypatch.setattr(replay, 'MAX_ENVELOPE', len(line.encode())+1)
    assert replay.seal(result, aad, key.public_key())
    monkeypatch.setattr(replay, 'MAX_ENVELOPE', len(line.encode()))
    with pytest.raises(package.Unavailable): replay.seal(result, aad, key.public_key())


@pytest.mark.parametrize('outcome', ['deadline', 'failed', 'result_invalid'])
def test_parent_fallback_discards_even_a_complete_measurement(control, outcome):
    path, metadata, f2, _, _, _ = control
    replay.checkpoint_f2(path, metadata, f2)
    package.write_private(path/'result.json', package._encoded(completed(f2, optional())))
    result = replay.fallback_result(path, metadata, outcome)
    assert result['F2EqualsF'] is True
    assert result['Fsql']['status'] == 'unavailable' and 'measurement' not in result['Fsql']
