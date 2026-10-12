"""Failure location is bounded evidence, never a restore or acceptance change."""
import signal
import subprocess
import sys
import time

import pytest

from test_rf1086_full_sql_control import control
from test_rf1086_actual_replay import setup
import rf1086_actual_replay as replay
import rf1086_actual_replay_package as package
import rf1086_catalog_semantics as commands


@pytest.mark.parametrize('code,kind,out,err,exit_code', [
    ("import os;os.write(1,b'x'*33)", 'stdout_limit', 33, 0, None),
    ("import os;os.write(2,b'x'*65537)", 'stderr_limit', 0, 65537, None),
    ("import os;os.write(1,b'x'*19);os.write(2,b'x'*17);raise SystemExit(37)", 'nonzero_exit', 19, 17, 37),
    ("import os,signal;os.kill(os.getpid(),signal.SIGTERM)", 'nonzero_exit', 0, 0, -signal.SIGTERM),
    ("import time;time.sleep(10)", 'deadline', 0, 0, None),
])
def test_real_command_failures_retain_only_finite_observations(monkeypatch, capsys, code, kind, out, err, exit_code):
    children = []
    original = subprocess.Popen
    def create(*args, **kw):
        child = original(*args, **kw); children.append(child); return child
    monkeypatch.setattr(commands.subprocess, 'Popen', create)
    monkeypatch.setattr(commands, 'MAX_BYTES', 32)
    with pytest.raises(commands.CommandFailure) as caught:
        commands._command([sys.executable, '-c', code], time.monotonic()+0.5)
    assert caught.value.observation == {'kind': kind, 'stdoutBytes': out, 'stderrBytes': err,
                                       'stdoutCap': 32, 'exitCode': exit_code}
    assert str(caught.value) == 'catalog_semantics_unavailable'
    assert all(p.poll() is not None for p in children)
    assert capsys.readouterr() == ('', '')


def test_wait_timeout_stays_unclassified_and_child_is_reaped(monkeypatch):
    children = []
    original = subprocess.Popen
    def create(*args, **kw):
        child = original(*args, **kw); children.append(child); return child
    monkeypatch.setattr(commands.subprocess, 'Popen', create)
    code = 'import os,time;os.close(1);os.close(2);time.sleep(10)'
    with pytest.raises(subprocess.TimeoutExpired):
        commands._command([sys.executable, '-c', code], time.monotonic()+0.3)
    assert children[0].poll() is not None


def test_prelaunch_deadline_has_zero_observed_bytes_and_no_spawn(monkeypatch):
    monkeypatch.setattr(commands.subprocess, 'Popen', lambda *a, **kw: pytest.fail('must not spawn'))
    with pytest.raises(commands.CommandFailure) as caught:
        commands._command(['unused'], time.monotonic()-1)
    assert caught.value.observation == {'kind': 'deadline', 'stdoutBytes': 0,
        'stderrBytes': 0, 'stdoutCap': commands.MAX_BYTES, 'exitCode': None}


def test_replay_command_preserves_classification_and_restores_cap():
    before = commands.MAX_BYTES
    with pytest.raises(replay.CommandUnavailable) as caught:
        replay.command([sys.executable, '-c', 'raise SystemExit(17)'], time.monotonic()+2, cap=4096)
    assert caught.value.reason == 'command_unavailable'
    assert caught.value.observation['exitCode'] == 17
    assert caught.value.observation['stdoutCap'] == 4096
    assert commands.MAX_BYTES == before


def detail(stage, cap=None, kind='deadline'):
    tool = {'version': '17.6', 'sha256': 'f'*64}
    stream = {'bytes': 11, 'sha256': 'e'*64}
    command = None if cap is None else {'kind': kind, 'stdoutBytes': 0, 'stderrBytes': 0,
        'stdoutCap': cap, 'exitCode': None}
    if kind == 'nonzero_exit': command['exitCode'] = 1
    if kind == 'stdout_limit': command['stdoutBytes'] = cap+1
    if kind == 'stderr_limit': command['stderrBytes'] = 65537
    return {'stage': stage, 'command': command,
        'tool': None if stage in ('unobserved', 'tool_probe') else tool,
        'stream': None if stage in ('unobserved', 'tool_probe', 'full_script_generation') else stream}


@pytest.mark.parametrize('stage', list(replay.FSQL_STAGE_CAPS)[1:])
@pytest.mark.parametrize('typed', [False, True])
def test_each_failure_stage_retains_only_prior_validated_milestones(control, monkeypatch, stage, typed):
    path, metadata, f2, _, _, failed = control
    script = b'full script'
    tool = b'pg_restore (PostgreSQL) 17.6\n'+b'f'*64+b'\n'
    def hit(current):
        if current != stage: return
        if typed and replay.FSQL_STAGE_CAPS[current]:
            observation = detail(current, replay.FSQL_STAGE_CAPS[current][0])['command']
            if current == 'initialized_snapshot':
                raise commands.CommandFailure('deadline', 0, 0, observation['stdoutCap'])
            raise replay.CommandUnavailable(observation)
        raise RuntimeError('private-canary-must-not-leak')
    def command(args, *a, **kw):
        current = 'tool_probe' if args[-1] == replay.TOOL_COMMAND else 'full_script_generation'
        hit(current); return tool if current == 'tool_probe' else script
    def cleanup(*args): hit('f2_cleanup'); return True
    def start(*args): hit('fresh_target_start'); return 'new'
    def psql(target, statement, *args, **kw):
        hit('roles_apply' if statement == b'roles' else 'full_script_apply' if statement == script else 'default_database_drop')
    def snapshot(*args, **kw): hit('initialized_snapshot'); return metadata['phases']['target_initialized']['catalog']
    def final(*args): hit('final_observation'); return metadata['failed'], metadata['phases']['mismatch']['catalog']
    for name, fn in [('command', command), ('cleanup_resources', cleanup), ('start_target', start),
                     ('psql', psql), ('_snapshot', snapshot), ('failed_state', final)]:
        monkeypatch.setattr(replay, name, fn)
    value = replay.add_full_sql(path, metadata, 'old', b'roles', failed, f2, time.monotonic()+416)['Fsql']
    assert replay.read_f2(path, metadata) == f2
    assert replay.validate_fsql(value, metadata) == value
    failure = value['failure']; assert failure['stage'] == stage
    expected = detail(stage, replay.FSQL_STAGE_CAPS[stage][0] if typed and replay.FSQL_STAGE_CAPS[stage] else None)
    if expected['stream'] is not None: expected['stream'] = {'bytes': len(script), 'sha256': package.digest(script)}
    assert failure == expected
    assert b'private-canary' not in package._encoded(value)
    assert value['FsqlEqualsF2'] is value['recoveryAccepted'] is value['causalAttributionAccepted'] is False


@pytest.mark.parametrize('stage,cap', [(stage, cap) for stage, caps in replay.FSQL_STAGE_CAPS.items() for cap in caps])
@pytest.mark.parametrize('kind', ['deadline', 'stdout_limit', 'stderr_limit', 'nonzero_exit'])
def test_exact_stage_caps_and_outcome_boundaries_are_valid(stage, cap, kind):
    failure = detail(stage, cap, kind)
    outcome = failure['command']
    outcome['stdoutBytes'] = cap+(65536 if kind == 'stdout_limit' else 0)
    outcome['stderrBytes'] = 131072 if kind == 'stderr_limit' else 65536
    replay.validate_failure(failure, 'command_unavailable')


@pytest.mark.parametrize('fault', [
    'extra_failure', 'stage_list', 'stage_unknown', 'unobserved_details', 'premature_tool',
    'premature_stream', 'missing_tool', 'missing_stream', 'tool_version', 'tool_hash', 'stream_size',
    'extra_command', 'kind_list', 'kind_unknown', 'out_bool', 'err_bool', 'cap_bool', 'out_negative',
    'err_negative', 'cap_mismatch', 'probe_cap_mismatch', 'snapshot_cap_mismatch', 'cleanup_command',
    'out_overflow', 'err_overflow', 'stdout_below_limit', 'stderr_below_limit', 'deadline_out_over',
    'deadline_err_over', 'nonzero_zero', 'nonzero_bool', 'nonzero_high', 'nonzero_low',
    'deadline_exit', 'reason_stage', 'noncommand_outcome', 'observed_parent_fallback',
])
def test_forged_or_inconsistent_failure_is_rejected(fault):
    failure = detail('full_script_generation', replay.MAX_SQL_BYTES)
    reason = 'command_unavailable'; command = failure['command']
    if fault == 'extra_failure': failure['raw'] = 'private-canary'
    elif fault == 'stage_list': failure['stage'] = []
    elif fault == 'stage_unknown': failure['stage'] = 'private-canary'
    elif fault == 'unobserved_details': failure['stage'] = 'unobserved'
    elif fault == 'premature_tool': failure = detail('tool_probe', 4096); failure['tool'] = detail('full_script_generation')['tool']
    elif fault == 'premature_stream': failure['stream'] = detail('f2_cleanup')['stream']
    elif fault == 'missing_tool': failure['tool'] = None
    elif fault == 'missing_stream': failure = detail('roles_apply', 8*1024**2); failure['stream'] = None
    elif fault == 'tool_version': failure['tool']['version'] = '17.11'
    elif fault == 'tool_hash': failure['tool']['sha256'] = 'private-canary'
    elif fault == 'stream_size': failure = detail('roles_apply'); failure['stream']['bytes'] = True
    elif fault == 'extra_command': command['raw'] = 'private-canary'
    elif fault == 'kind_list': command['kind'] = []
    elif fault == 'kind_unknown': command['kind'] = 'private-canary'
    elif fault == 'out_bool': command['stdoutBytes'] = True
    elif fault == 'err_bool': command['stderrBytes'] = True
    elif fault == 'cap_bool': command['stdoutCap'] = True
    elif fault == 'out_negative': command['stdoutBytes'] = -1
    elif fault == 'err_negative': command['stderrBytes'] = -1
    elif fault == 'cap_mismatch': command.update(kind='stdout_limit', stdoutCap=4096, stdoutBytes=4097)
    elif fault == 'probe_cap_mismatch': failure = detail('tool_probe', replay.MAX_SQL_BYTES)
    elif fault == 'snapshot_cap_mismatch': failure = detail('initialized_snapshot', 8*1024**2)
    elif fault == 'cleanup_command': failure = detail('f2_cleanup', 4096)
    elif fault == 'out_overflow': command.update(kind='stdout_limit', stdoutBytes=replay.MAX_SQL_BYTES+65537)
    elif fault == 'err_overflow': command.update(kind='stderr_limit', stderrBytes=131073)
    elif fault == 'stdout_below_limit': command['kind'] = 'stdout_limit'
    elif fault == 'stderr_below_limit': command['kind'] = 'stderr_limit'
    elif fault == 'deadline_out_over': command['stdoutBytes'] = replay.MAX_SQL_BYTES+1
    elif fault == 'deadline_err_over': command['stderrBytes'] = 65537
    elif fault.startswith('nonzero_'):
        command.update(kind='nonzero_exit', exitCode={'nonzero_zero':0,'nonzero_bool':True,'nonzero_high':256,'nonzero_low':-128}[fault])
    elif fault == 'deadline_exit': command['exitCode'] = 1
    elif fault == 'reason_stage': reason = 'full_sql_tool_invalid'; failure['command'] = None
    elif fault == 'noncommand_outcome': reason = 'full_sql_empty'
    elif fault == 'observed_parent_fallback': reason = 'worker_deadline'
    with pytest.raises(package.Unavailable): replay.validate_failure(failure, reason)


@pytest.mark.parametrize('reason,stage', list(replay.FSQL_REASON_STAGES.items()))
def test_noncommand_rejections_keep_their_distinct_reasons(reason, stage):
    failure = detail(stage)
    replay.validate_failure(failure, reason)
    assert replay.unavailable_fsql(reason, failure)['reason'] == reason


@pytest.mark.parametrize('reason', sorted(replay.FSQL_REASONS))
def test_unobserved_fallback_cannot_claim_a_stage_specific_rejection(reason):
    value = replay.unavailable_fsql(reason)
    replay.validate_fsql(value, {})
    assert value['failure'] == detail('unobserved')
    if reason in replay.FSQL_REASON_STAGES:
        assert value['reason'] == 'control_unavailable'
        value['reason'] = reason  # Forged contradictory stage-specific reason.
        with pytest.raises(package.Unavailable): replay.validate_fsql(value, {})
    else:
        assert value['reason'] == reason


def test_new_helper_is_in_exact_code_binding_and_unavailable_details_reset(control, monkeypatch):
    _, metadata, f2, _, _, _ = control
    assert set(metadata['code']) == set(package.CODE_FILES)
    assert metadata['code']['rf1086_catalog_semantics.py'] == package.digest(package.Path(commands.__file__).read_bytes())
    detailed = replay.unavailable_fsql('command_unavailable', detail('full_script_apply', 8*1024**2))
    fallback = replay.unavailable_fsql('summary_oversized')
    limit = len(package._encoded(f2 | {'Fsql': fallback, 'optionalWorkerOutcome':'result_invalid','ownedCleanupComplete':False}))
    monkeypatch.setattr(replay, 'MAX_PLAINTEXT', limit)
    result = replay.fit_optional(f2, detailed, metadata)
    assert result['Fsql'] == fallback
    assert result['F2EqualsF'] is True
