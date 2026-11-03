"""Awake-host enforcement and explicit negative coverage for host loss/suspend."""
from copy import deepcopy
import json
import os
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone, timedelta
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from talli_backend.adapters import hosted_recovery_window as window


class Clock:
    def __init__(self):
        self.wall = 10000.0
        self.mono = 100.0

    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds

    def deadline(self, seconds):
        return window.Deadline(seconds, wall=lambda: self.wall, monotonic=lambda: self.mono)


def config():
    value = {'workSeconds': 45, 'callSeconds': 2, 'pollSeconds': .1, 'cleanupSeconds': 15}
    for role, ref in [('source', 'a'), ('capacity', 'b'), ('target', 'c'), ('preserved', 'd')]:
        value[role] = {'project': ref * 20, 'organization': 'e' * 20,
            'name': role, 'region': 'eu-west-1', 'engine': '17.11.0.011'}
    return value


class ProviderModel:
    def __init__(self, cfg, clock):
        self.cfg, self.clock = cfg, clock
        self.calls = []
        self.lost = set()
        self.fail = set()
        self.statuses = {'source': 'ACTIVE_HEALTHY', 'capacity': 'ACTIVE_HEALTHY',
            'target': 'INACTIVE', 'preserved': 'INACTIVE'}
        self.drift = None

    def call(self, action, ref, *, deadline):
        self.calls.append((action, ref))
        self.clock.advance(.01)
        if action == 'get_org':
            return {'id': ref, 'plan': 'free'}
        role = next(k for k in self.statuses if self.cfg[k]['project'] == ref)
        if (action, role) in self.fail:
            raise window.WindowStopped('hosted_window_provider_call_deadline')
        if action == 'get_project':
            item = self.cfg[role]
            return {'id': item['project'], 'organization_id': item['organization'],
                'name': item['name'], 'region': item['region'], 'engine': item['engine'],
                'status': self.statuses[role], **(self.drift or {})}
        self.statuses[role] = 'INACTIVE' if action == 'pause' else 'ACTIVE_HEALTHY'
        if (action, role) in self.lost:
            raise window.WindowStopped('hosted_window_provider_call_outcome_unknown')
        return {'ok': True}


def setup():
    cfg, clock, records = config(), Clock(), []
    provider = ProviderModel(cfg, clock)
    supervisor = window.WindowSupervisor(cfg, provider, records.append,
        deadline_factory=clock.deadline, sleep=clock.advance)
    return supervisor, provider, clock, records


def test_success_cleans_up_without_claiming_recovery_or_an_outage_guarantee():
    supervisor, provider, _, records = setup()
    result = supervisor.run(lambda deadline: 0)
    assert result['cleanupVerified'] and result['workerExitCode'] == 0
    assert result['hostSuspendCovered'] is False
    assert result['providerTransitionBoundGuaranteed'] is False
    assert result['hostedRecoveryAccepted'] is False
    assert provider.statuses == {'source': 'ACTIVE_HEALTHY', 'capacity': 'ACTIVE_HEALTHY',
        'target': 'INACTIVE', 'preserved': 'INACTIVE'}
    assert [a for a, r in provider.calls if a in ('pause', 'resume')] == ['pause', 'resume', 'pause', 'resume']
    events = records[-1]['events']
    assert next(i for i, e in enumerate(events) if e['event'] == 'window.started') < next(
        i for i, e in enumerate(events) if e['event'] == 'provider.request' and e['action'] == 'pause')


@pytest.mark.parametrize('lost', [('pause', 'capacity'), ('resume', 'target'),
    ('pause', 'target'), ('resume', 'capacity')])
def test_lost_lifecycle_response_reconciles_without_replaying_post_or_worker(lost):
    supervisor, provider, _, _ = setup()
    provider.lost.add(lost)
    starts = []
    result = supervisor.run(lambda d: starts.append(True) or 0)
    assert result['cleanupVerified']
    assert provider.calls.count((lost[0], provider.cfg[lost[1]]['project'])) == 1
    assert len(starts) <= 1


@pytest.mark.parametrize('jump', ['forward', 'backward', 'suspend'])
def test_clock_jump_stops_admission_and_cleanup_does_not_wait_for_original_deadline(jump):
    supervisor, provider, clock, _ = setup()
    def worker(deadline):
        if jump == 'forward': clock.wall += 3600
        elif jump == 'backward': clock.wall -= 3600
        else: clock.wall += 3600  # suspend model: uptime excludes elapsed sleep
        assert not deadline.open()
        raise window.WindowStopped('hosted_window_worker_deadline')
    assert supervisor.run(worker)['cleanupVerified']


def test_slow_lifecycle_call_cannot_start_worker_after_admission_deadline():
    supervisor, provider, clock, records = setup()
    call = provider.call
    def delayed(action, ref, *, deadline):
        value = call(action, ref, deadline=deadline)
        if action == 'resume' and ref == provider.cfg['target']['project']:
            clock.advance(100)
        return value
    provider.call = delayed
    assert supervisor.run(lambda d: pytest.fail('late worker'))['cleanupVerified']
    assert any(e['event'] == 'cleanup.started' for e in records[-1]['events'])


def test_unavailable_provider_never_reports_cleanup_success():
    supervisor, provider, _, _ = setup()
    def worker(deadline):
        provider.fail.update({('get_project', 'target'), ('get_project', 'capacity')})
        return 1
    result = supervisor.run(worker)
    assert result['cleanupVerified'] is False
    assert result['targetPaused'] is False and result['capacityHealthy'] is False


def test_record_failure_after_mutation_still_attempts_both_cleanup_actions():
    supervisor, provider, _, _ = setup()
    def write(value):
        if supervisor.mutating: raise OSError('private-disk-details')
    supervisor.record = write
    result = supervisor.run(lambda d: pytest.fail('no worker'))
    assert result['diagnosticsAvailable'] is False
    assert result['cleanupVerified']
    assert provider.statuses['capacity'] == 'ACTIVE_HEALTHY'


@pytest.mark.parametrize('drift', [{'name': 'other'}, {'engine': '17.12.0.000'},
    {'organization_id': 'f' * 20}, {'region': 'eu-north-1'}])
def test_wrong_target_metadata_refuses_before_mutation(drift):
    supervisor, provider, _, _ = setup(); provider.drift = drift
    with pytest.raises(ValueError): supervisor.run(lambda d: 0)
    assert not any(a in ('pause', 'resume') for a, r in provider.calls)


def test_actual_worker_hang_is_killed_without_agent_turns(tmp_path):
    marker = tmp_path / 'after-deadline'
    argv = [sys.executable, '-c',
        'import time,pathlib;time.sleep(.8);pathlib.Path(__import__("sys").argv[1]).write_text("late")', str(marker)]
    started = time.monotonic()
    with pytest.raises(window.WindowStopped):
        window.bounded_process(argv, deadline=window.Deadline(.15))
    assert time.monotonic() - started < 1
    time.sleep(.8)
    assert not marker.exists()


def hung_request(pipe, credentials, action, ref, allowed):
    time.sleep(30)


def test_actual_provider_child_hang_is_killed(monkeypatch):
    monkeypatch.setattr(window, '_request', hung_request)
    started = time.monotonic()
    with pytest.raises(window.WindowStopped):
        window.Provider('/not-read', ['a' * 20]).call('get_project', 'a' * 20,
            deadline=window.Deadline(.15))
    assert time.monotonic() - started < 2


def guardian_script(tmp_path, seconds):
    # Real detached guardian + bounded worker, fully local provider model. No
    # HTTP, credentials, real project IDs or production lifecycle calls.
    script = tmp_path / 'guardian.py'
    script.write_text('''import json,pathlib,sys
from talli_backend.adapters.hosted_recovery_window import *
from test_hosted_recovery_window import config,ProviderModel,Clock
p=pathlib.Path(sys.argv[1]); c=config(); c.update(workSeconds=float(sys.argv[2]),callSeconds=.1,cleanupSeconds=.5,pollSeconds=.01)
model=ProviderModel(c,Clock())
def record(value):
 (p/'progress.json').write_text(json.dumps(value))
s=WindowSupervisor(c,model,record)
result=s.run(lambda d: bounded_process([sys.executable,'-c','import time;time.sleep(20)'],deadline=d))
(p/'result.json').write_text(json.dumps(result))
''')
    return [sys.executable, str(script), str(tmp_path), str(seconds)]


def wait_file(path, timeout=4):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if path.exists(): return json.loads(path.read_text())
        time.sleep(.02)
    pytest.fail('local guardian receipt did not arrive')


def test_guardian_survives_actual_coordinator_sigkill(tmp_path, monkeypatch):
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join(sys.path))
    argv = guardian_script(tmp_path, .4)
    coordinator = subprocess.Popen([sys.executable, '-c',
        'import sys,time,json;from talli_backend.adapters.hosted_recovery_window import launch_guardian;'
        'p=launch_guardian(json.loads(sys.argv[1]));print(p.pid,flush=True);time.sleep(20)', json.dumps(argv)],
        stdout=subprocess.PIPE, text=True)
    guardian_pid = int(coordinator.stdout.readline())
    try:
        wait_file(tmp_path / 'progress.json')
        coordinator.kill(); coordinator.wait(timeout=2)
        result = wait_file(tmp_path / 'result.json')
        assert result['cleanupVerified'] and result['workerExitCode'] is None
    finally:
        if coordinator.poll() is None: coordinator.kill(); coordinator.wait()
        coordinator.stdout.close()
        try: os.kill(guardian_pid, signal.SIGKILL)
        except ProcessLookupError: pass


def test_stopped_guardian_cannot_act_until_resumed_negative_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join(sys.path))
    child = window.launch_guardian(guardian_script(tmp_path, .25))
    try:
        wait_file(tmp_path / 'progress.json')
        os.kill(child.pid, signal.SIGSTOP)
        time.sleep(.5)
        assert not (tmp_path / 'result.json').exists()  # no enforcement while stopped
        os.kill(child.pid, signal.SIGCONT)
        result = wait_file(tmp_path / 'result.json')
        assert result['cleanupVerified'] and result['hostSuspendCovered'] is False
        child.wait(timeout=2)
    finally:
        try: os.kill(child.pid, signal.SIGCONT)
        except ProcessLookupError: pass
        if child.poll() is None: child.kill(); child.wait()


def reviewed_config(tmp_path):
    tmp_path.chmod(0o700)
    cwd = tmp_path / 'checkout'; cwd.mkdir()
    script = cwd / 'worker.py'; script.write_text('pass\n')
    subprocess.run(['git', 'init', '-q', str(cwd)], check=True)
    subprocess.run(['git', '-C', str(cwd), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(cwd), '-c', 'user.name=Test', '-c',
        'user.email=test@invalid.example', 'commit', '-qm', 'fixture'], check=True)
    def revision(name):
        return subprocess.check_output(['git', '-C', str(cwd), 'rev-parse', name], text=True).strip()
    binary = str(Path(sys.executable).resolve())
    cfg = {**config(), 'version': 1, 'work': str(tmp_path / 'window'),
        'credentials': str(tmp_path / 'never-read-credentials.json'),
        'worker': {'argv': [binary, str(script)], 'cwd': str(cwd), 'head': revision('HEAD'),
            'tree': revision('HEAD^{tree}'), 'files': {binary: sha256(Path(binary).read_bytes()).hexdigest(),
                str(script): sha256(script.read_bytes()).hexdigest()}}}
    def save(path, value):
        path.write_text(json.dumps(value)); path.chmod(0o600)
        return sha256(path.read_bytes()).hexdigest()
    cfg_path = tmp_path / 'config.json'; cfg_sha = save(cfg_path, cfg)
    authority = {'version': 1, 'windowId': str(uuid4()), 'configSha256': cfg_sha,
        'validBeforeUtc': (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        'maximumCharge': 0, 'oneAttempt': True, 'availabilityAcknowledgement':
        'host-awake-only; no hard outage bound; external availability required for host-loss coverage'}
    auth_path = tmp_path / 'authority.json'; auth_sha = save(auth_path, authority)
    return cfg, cfg_path, cfg_sha, authority, auth_path, auth_sha, save


def test_launcher_consumes_authority_once_and_uses_importable_detached_module(tmp_path, monkeypatch):
    cfg, path, pin, auth, auth_path, auth_pin, _ = reviewed_config(tmp_path)
    captured = []
    monkeypatch.setattr(window, 'launch_guardian', lambda argv: captured.append(argv) or SimpleNamespace(pid=123))
    args = ['start', '--config', str(path), '--expected-config-sha256', pin,
        '--authority', str(auth_path), '--expected-authority-sha256', auth_pin]
    assert window.main(args) == 0
    assert captured[0][captured[0].index('-m') + 1] == 'talli_backend.adapters.hosted_recovery_window'
    with pytest.raises(FileExistsError): window.main(args)
    assert len(captured) == 1


def test_consumed_old_window_receipt_is_not_new_authority(tmp_path):
    cfg, path, pin, auth, auth_path, auth_pin, save = reviewed_config(tmp_path)
    old = {'schema': 'talli-direct-human-hosted-window-authority-v2', 'scope': {'one_new_window': True}}
    auth_pin = save(auth_path, old)
    with pytest.raises(ValueError, match='new_authority_required'):
        window.load_config(path, pin, auth_path, auth_pin)


def test_cleanup_only_allows_expired_consumed_authority_with_missing_worker(tmp_path, monkeypatch):
    cfg, path, pin, auth, auth_path, _, save = reviewed_config(tmp_path)
    auth['validBeforeUtc'] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    auth_pin = save(auth_path, auth)
    save(tmp_path / (auth['windowId'] + '.used'), {'configSha256': pin, 'authoritySha256': auth_pin})
    Path(cfg['work']).mkdir(mode=0o700)
    Path(cfg['worker']['argv'][1]).unlink()
    provider = ProviderModel(cfg, Clock())
    provider.statuses.update(target='ACTIVE_HEALTHY', capacity='INACTIVE')
    monkeypatch.setattr(window, 'Provider', lambda *args: provider)
    monkeypatch.setattr(window, 'bounded_process', lambda *args, **kwargs: pytest.fail('no worker in cleanup'))
    assert window.main(['cleanup', '--config', str(path), '--expected-config-sha256', pin,
        '--authority', str(auth_path), '--expected-authority-sha256', auth_pin]) == 0
    assert [a for a, r in provider.calls if a in ('pause', 'resume')] == ['pause', 'resume']
    assert not any(a == 'resume' and r == cfg['target']['project'] for a, r in provider.calls)


@pytest.mark.parametrize('action,role', [('pause', 'source'), ('resume', 'source'),
    ('pause', 'preserved'), ('resume', 'preserved'), ('resume', 'target')])
def test_cleanup_transport_refuses_source_preserved_and_target_resume_before_credentials(action, role, monkeypatch):
    cfg = config()
    bindings = {**{r: cfg[r]['project'] for r in ('source', 'capacity', 'target', 'preserved')},
        'organization': cfg['target']['organization'], 'cleanupOnly': True}
    records = []
    pipe = SimpleNamespace(send=records.append, close=lambda: None)
    reads = []
    monkeypatch.setattr(window, 'private_read', lambda *args: reads.append(args) or b'{}')
    window._request(pipe, '/not-read', action, cfg[role]['project'], bindings)
    assert records[-1]['ok'] is False
    assert not reads
