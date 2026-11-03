"""Opt-in detached recovery guardian. No application/runtime registration.

Local enforcement requires a running host, this process, network and provider.
It cannot act during host suspension or guarantee provider recovery latency.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import multiprocessing
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time
from uuid import UUID

import httpx

from talli_backend.adapters.hosted_recovery_capture import json_bytes, private_read, require
from talli_backend.adapters.hosted_recovery_diagnostics import SafeTransportFailure, safe_failure
from talli_backend.adapters.hosted_recovery_target import HostedDesignation


STATUSES = {'ACTIVE_HEALTHY', 'INACTIVE', 'PAUSING', 'COMING_UP', 'RESTORING',
    'ACTIVE_UNHEALTHY', 'GOING_DOWN', 'INIT_FAILED', 'REMOVED', 'UNKNOWN'}


class WindowStopped(ValueError):
    pass


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


@dataclass
class Deadline:
    """Compare UTC with elapsed time in ONE process; never reuse a stored monotonic origin."""
    seconds: float
    wall: object = time.time
    monotonic: object = time.monotonic
    tolerance: float = 2.0

    def __post_init__(self):
        self.started_utc = self.wall()
        self.started_mono = self.monotonic()
        self.last_wall, self.last_mono = self.started_utc, self.started_mono
        self.at = self.started_utc + self.seconds
        self.clock_changed = False

    def remaining(self):
        wall, mono = self.wall(), self.monotonic()
        require(all(math.isfinite(v) for v in (wall, mono)), 'hosted_window_clock_invalid')
        self.clock_changed |= (wall < self.last_wall or mono < self.last_mono or
            abs((wall - self.started_utc) - (mono - self.started_mono)) > self.tolerance)
        self.last_wall, self.last_mono = wall, mono
        # A wall-clock step in either direction closes work admission. Sleep
        # detected on wake also closes admission; it cannot cause actions asleep.
        return min(self.at - wall, self.seconds - (mono - self.started_mono))

    def open(self):
        return self.remaining() > 0 and not self.clock_changed


def stop_group(process):
    """Only a currently held child handle, never a PID read from an old journal."""
    if process is None:
        return
    # Kill the whole reviewed worker group even if its leader has already exited.
    # Workers must not daemonize/escape the group; this is not a sandbox.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=2)


def bounded_process(argv, *, deadline, cwd=None):
    require(deadline.open(), 'hosted_window_deadline_closed')
    process = subprocess.Popen(argv, cwd=cwd, start_new_session=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        while process.poll() is None:
            if not deadline.open():
                raise WindowStopped('hosted_window_worker_deadline')
            time.sleep(min(.05, max(0, deadline.remaining())))
        require(deadline.open(), 'hosted_window_deadline_closed')
        return process.returncode
    finally:
        stop_group(process)


def _request(pipe, credentials, action, ref, allowed):
    """Disposable transport process. No response bodies on errors, no raw exceptions."""
    try:
        destinations = {
            'get_project': {allowed[r] for r in ('source', 'capacity', 'target', 'preserved')},
            'get_org': {allowed['organization']},
            'pause': {allowed['capacity'], allowed['target']},
            'resume': {allowed['capacity']} if allowed.get('cleanupOnly') else
                {allowed['capacity'], allowed['target']},
        }
        require(action in destinations and ref in destinations[action],
            'hosted_window_provider_action_invalid')
        token = json_bytes(private_read(credentials, 32768))['managementToken']
        require(isinstance(token, str) and len(token) >= 20, 'hosted_window_credentials_invalid')
        suffix = {'pause': '/pause', 'resume': '/restore'}.get(action, '')
        path = ('organizations/' if action == 'get_org' else 'projects/') + ref + suffix
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
            with client.stream('POST' if suffix else 'GET', 'https://api.supabase.com/v1/' + path,
                    headers={'Authorization': 'Bearer ' + token}) as response:
                response.raise_for_status()
                require(response.status_code == 200, 'hosted_window_provider_http_unexpected')
                if suffix:
                    result = {'ok': True}
                else:
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        require(len(raw) <= 65536, 'hosted_window_metadata_bound')
                    value = json.loads(raw)
                    if action == 'get_org':
                        require(value.get('id') == ref and value.get('plan') == 'free',
                            'hosted_window_free_organization_required')
                        result = {'id': ref, 'plan': 'free'}
                    else:
                        require(value.get('status') in STATUSES, 'hosted_window_status_unknown')
                        HostedDesignation(project=value.get('id'), organization=value.get('organization_id'),
                            name=value.get('name'), region=value.get('region'))
                        engine = value.get('database', {}).get('version')
                        require(isinstance(engine, str) and len(engine) <= 40,
                            'hosted_window_engine_invalid')
                        result = {k: value.get(k) for k in ('id', 'organization_id', 'name', 'region', 'status')}
                        result['engine'] = engine
        require(len(json.dumps(result)) <= 2048, 'hosted_window_metadata_bound')
        pipe.send_bytes(json.dumps({'ok': True, 'value': result}).encode())
    except BaseException as error:
        pipe.send_bytes(json.dumps({'ok': False, 'failure': safe_failure(error)}).encode())
    finally:
        pipe.close()


class Provider:
    def __init__(self, credentials, allowed):
        self.credentials, self.allowed = str(credentials), allowed

    def call(self, action, ref, *, deadline):
        ctx = multiprocessing.get_context('spawn')
        receiver, sender = ctx.Pipe(duplex=False)
        process = ctx.Process(target=_request,
            args=(sender, self.credentials, action, ref, self.allowed), daemon=True)
        process.start(); sender.close()
        try:
            # Connection.recv()/recv_bytes() can block on a PARTIAL frame even
            # after poll(). Read the bounded JSON frame incrementally instead.
            descriptor = receiver.fileno()
            os.set_blocking(descriptor, False)
            raw = bytearray(); size = None
            while size is None or len(raw) < size + 4:
                if not deadline.open():
                    raise WindowStopped('hosted_window_provider_call_deadline')
                try:
                    chunk = os.read(descriptor, 4096 + 4 - len(raw))
                except BlockingIOError:
                    time.sleep(min(.02, max(0, deadline.remaining())))
                    continue
                require(chunk, 'hosted_window_provider_call_outcome_unknown')
                raw.extend(chunk)
                if size is None and len(raw) >= 4:
                    size = struct.unpack('!i', raw[:4])[0]
                    require(0 < size <= 4096, 'hosted_window_provider_frame_invalid')
            require(deadline.open(), 'hosted_window_provider_call_deadline')
            value = json_bytes(bytes(raw[4:4 + size]))
            if value.get('ok') is not True:
                raise SafeTransportFailure(value.get('failure'))
            return value['value']
        finally:
            if process.is_alive():
                process.kill()
            process.join(timeout=2); receiver.close(); process.close()


class WindowSupervisor:
    """One lifecycle owner. Each provider call and worker is a bounded child.

    No SQL containment is assumed. Cleanup stops work, pauses only the designated
    target, then restores the capacity project without selecting an engine update.
    """
    def __init__(self, config, provider, record, *, deadline_factory=Deadline, sleep=time.sleep):
        self.config, self.provider, self.record = config, provider, record
        self.deadline_factory, self.sleep = deadline_factory, sleep
        self.work_deadline = None
        self.mutating = False
        self.cleaning = False
        self.records_available = True
        self.events = []
        self.timing = {}
        self.failure = None
        self.pending = {}
        self.cleanup_failures = {}
        self.pending_history_known = True

    def emit(self, event, **values):
        self.events = (self.events + [{'atUtc': utc(time.time()), 'event': event, **values}])[-64:]
        try:
            self.record({'version': 1, 'events': self.events, 'timing': dict(self.timing),
                'failure': self.failure, 'pendingMutations': dict(self.pending),
                'pendingHistoryKnown': self.pending_history_known,
                'cleanupFailures': dict(self.cleanup_failures), 'localHostAvailabilityRequired': True,
                'hostSuspendCovered': False, 'sqlContainmentVerified': False})
        except Exception:
            self.records_available = False
            if not self.cleaning:
                raise

    def call(self, action, ref, deadline):
        require(deadline.open(), 'hosted_window_deadline_closed')
        # Time spent inside a DNS/TLS/provider call cannot block the guardian past
        # its admission deadline. A killed POST is an UNKNOWN outcome, not failure.
        bound = self.deadline_factory(min(self.config['callSeconds'], deadline.remaining()))
        key = action + ':' + ref
        if action in ('pause', 'resume'):
            require(key not in self.pending, 'hosted_window_mutation_pending')
            self.pending[key] = {'action': action, 'project': ref,
                'goal': 'INACTIVE' if action == 'pause' else 'ACTIVE_HEALTHY',
                'atUtc': utc(time.time()), 'acknowledged': False}
        try:
            self.emit('provider.request', action=action, project=ref)
        except Exception:
            # No transport call has begun; this request is known NOT dispatched.
            if action in ('pause', 'resume'):
                del self.pending[key]
            raise
        value = self.provider.call(action, ref, deadline=bound)
        if key in self.pending:
            self.pending[key]['acknowledged'] = True
        self.emit('provider.response', action=action, project=ref)
        require(deadline.open(), 'hosted_window_deadline_closed')
        return value

    def project(self, role, deadline, *, require_engine=True):
        expected = self.config[role]
        observed = self.call('get_project', expected['project'], deadline)
        require(all(observed.get(k) == expected[v] for k, v in
            [('id', 'project'), ('organization_id', 'organization'), ('name', 'name'), ('region', 'region')]),
            'hosted_window_designation_changed')
        if require_engine:
            require(observed.get('engine') == expected['engine'], 'hosted_window_engine_changed')
        require(observed.get('status') in STATUSES, 'hosted_window_status_unknown')
        # A pre-request state proves neither rejection nor completion of a lost
        # POST. Clear an intent only on observing its requested goal.
        for key, intent in list(self.pending.items()):
            if intent['project'] == expected['project'] and intent['goal'] == observed['status']:
                del self.pending[key]
        self.emit('project.observed', role=role, status=observed['status'])
        return observed['status']

    def wait(self, role, status, deadline, *, require_engine=True):
        while deadline.open():
            try:
                if self.project(role, deadline, require_engine=require_engine) == status:
                    return True
            except Exception as error:
                # Reconcile through fresh GET after a lost response, never replay
                # the import or blindly repeat the lifecycle POST.
                self.emit('provider.observation.unavailable', role=role, failure=safe_failure(error))
            self.sleep(min(self.config['pollSeconds'], max(0, deadline.remaining())))
        return False

    def cleanup(self):
        self.cleaning = True
        self.timing['cleanupStartedAtUtc'] = utc(time.time())
        self.emit('cleanup.started')
        deadline = self.deadline_factory(self.config['cleanupSeconds'])
        target_paused = capacity_healthy = False
        # Retain time for restoration even if target metadata is unavailable.
        pause_deadline = self.deadline_factory(min(deadline.remaining() / 2, 60))
        pause_requested = False
        while pause_deadline.open():
            try:
                status = self.project('target', pause_deadline, require_engine=False)
                if status == 'INACTIVE' and not self.unresolved('target', 'resume'):
                    target_paused = True
                    break
                if status not in ('INACTIVE', 'PAUSING', 'GOING_DOWN') and not pause_requested and \
                        not self.unresolved('target', 'pause'):
                    pause_requested = True
                    try:
                        self.call('pause', self.config['target']['project'], pause_deadline)
                    except Exception as error:
                        self.cleanup_failure('target.pause', error)
                        self.emit('target.pause.outcome.unknown', failure=safe_failure(error))
            except Exception as error:
                self.cleanup_failure('target.observe', error)
                self.emit('target.pause.unverified', failure=safe_failure(error))
            self.sleep(min(self.config['pollSeconds'], max(0, pause_deadline.remaining())))
        resume_requested = False
        while deadline.open():
            try:
                status = self.project('capacity', deadline)
                if status == 'ACTIVE_HEALTHY' and not self.unresolved('capacity', 'pause'):
                    capacity_healthy = True
                    break
                # A lost pause response can leave PAUSING -> INACTIVE during
                # cleanup. Observe that transition before issuing one restore.
                if status == 'INACTIVE' and not resume_requested and not self.unresolved('capacity', 'resume'):
                    resume_requested = True
                    try:
                        self.call('resume', self.config['capacity']['project'], deadline)
                    except Exception as error:
                        self.cleanup_failure('capacity.resume', error)
                        self.emit('capacity.resume.outcome.unknown', failure=safe_failure(error))
            except Exception as error:
                self.cleanup_failure('capacity.observe', error)
                self.emit('capacity.health.unverified', failure=safe_failure(error))
            self.sleep(min(self.config['pollSeconds'], max(0, deadline.remaining())))
        boundaries_current = False
        try:
            boundaries_current = (self.project('source', deadline) == 'ACTIVE_HEALTHY' and
                self.project('preserved', deadline) == 'INACTIVE')
        except Exception as error:
            self.cleanup_failure('preserved.observe', error)
            self.emit('preserved.boundaries.unverified', failure=safe_failure(error))
        self.emit('cleanup.finished', targetPaused=target_paused, capacityHealthy=capacity_healthy,
            preservedBoundaryStatesVerified=boundaries_current)
        return {'targetPaused': target_paused, 'capacityHealthy': capacity_healthy,
            'preservedBoundaryStatesVerified': boundaries_current,
            'pendingMutations': dict(self.pending), 'cleanupFailures': dict(self.cleanup_failures),
            'pendingHistoryKnown': self.pending_history_known,
            'cleanupVerified': target_paused and capacity_healthy and boundaries_current and
                not self.pending and self.pending_history_known}

    def unresolved(self, role, action):
        return action + ':' + self.config[role]['project'] in self.pending

    def cleanup_failure(self, phase, error):
        # First safe failure per fixed cleanup boundary survives arbitrary polls.
        if phase not in self.cleanup_failures and len(self.cleanup_failures) < 8:
            self.cleanup_failures[phase] = {'atUtc': utc(time.time()), 'phase': phase,
                **safe_failure(error)}

    def restore_pending(self, prior):
        self.pending_history_known = prior.get('pendingHistoryKnown') is True
        intents = prior.get('pendingMutations')
        if not isinstance(intents, dict) or len(intents) > 4:
            self.pending_history_known = False
            return
        for key, intent in intents.items():
            require(isinstance(intent, dict) and set(intent) ==
                {'action', 'project', 'goal', 'atUtc', 'acknowledged'}, 'hosted_window_pending_invalid')
            require(intent['action'] in ('pause', 'resume') and
                intent['project'] in {self.config[r]['project'] for r in ('capacity', 'target')} and
                key == intent['action'] + ':' + intent['project'] and
                intent['goal'] == ('INACTIVE' if intent['action'] == 'pause' else 'ACTIVE_HEALTHY') and
                type(intent['acknowledged']) is bool, 'hosted_window_pending_invalid')
            when = datetime.fromisoformat(intent['atUtc'])
            require(when.tzinfo is not None, 'hosted_window_pending_invalid')
            self.pending[key] = dict(intent)

    def run(self, worker):
        preflight = self.deadline_factory(60)
        org = self.config['target']['organization']
        require(self.call('get_org', org, preflight) == {'id': org, 'plan': 'free'},
            'hosted_window_free_organization_required')
        for role, expected in [('source', 'ACTIVE_HEALTHY'), ('capacity', 'ACTIVE_HEALTHY'),
                ('target', 'INACTIVE'), ('preserved', 'INACTIVE')]:
            require(self.project(role, preflight) == expected, 'hosted_window_initial_state_changed')
        # Durable acknowledgement and deadlines precede the FIRST pause request.
        self.work_deadline = self.deadline_factory(self.config['workSeconds'])
        self.timing = {'windowStartedAtUtc': utc(self.work_deadline.started_utc),
            'cleanupAtUtc': utc(self.work_deadline.at)}
        self.emit('window.started', cleanupAtUtc=utc(self.work_deadline.at))
        worker_code = None
        try:
            self.mutating = True
            self.call('pause', self.config['capacity']['project'], self.work_deadline)
            require(self.wait('capacity', 'INACTIVE', self.work_deadline), 'hosted_window_pause_unverified')
            self.call('resume', self.config['target']['project'], self.work_deadline)
            require(self.wait('target', 'ACTIVE_HEALTHY', self.work_deadline), 'hosted_window_target_unready')
            require(self.work_deadline.open(), 'hosted_window_deadline_closed')
            self.emit('worker.started')
            worker_code = worker(self.work_deadline)
            self.emit('worker.finished', exitCode=worker_code)
        except BaseException as error:
            self.failure = safe_failure(error)
            try:
                self.emit('window.stopped', failure=self.failure)
            except Exception:
                pass  # A failed receipt must not prevent provider cleanup.
        finally:
            cleanup = self.cleanup()
        return {'workerExitCode': worker_code, **cleanup, 'hostedRecoveryAccepted': False,
            'hostSuspendCovered': False, 'providerTransitionBoundGuaranteed': False,
            'diagnosticsAvailable': self.records_available, 'timing': dict(self.timing),
            'failure': self.failure, 'clockDiscontinuityDetected': self.work_deadline.clock_changed}


def load_config(path, expected_sha, authority_path, authority_sha, *, cleanup_only=False):
    raw = private_read(path, 65536)
    require(hashlib.sha256(raw).hexdigest() == expected_sha, 'hosted_window_config_changed')
    config = json_bytes(raw)
    require(set(config) == {'version', 'work', 'credentials', 'source', 'capacity', 'target', 'preserved',
        'workSeconds', 'callSeconds', 'pollSeconds', 'cleanupSeconds', 'worker'}, 'hosted_window_config_invalid')
    require(all(type(config[k]) in (int, float) and math.isfinite(config[k]) for k in
        ('workSeconds', 'callSeconds', 'pollSeconds', 'cleanupSeconds')), 'hosted_window_bounds_invalid')
    require(config['version'] == 1 and 0 < config['workSeconds'] <= 2700 and
        0 < config['callSeconds'] <= 15 and 0 < config['pollSeconds'] <= 5 and
        0 < config['cleanupSeconds'] <= 900, 'hosted_window_bounds_invalid')
    refs = set()
    for role in ('source', 'capacity', 'target', 'preserved'):
        item = dict(config[role]); engine = item.pop('engine')
        HostedDesignation(**item)
        require(isinstance(engine, str) and engine.startswith('17.'), 'hosted_window_engine_invalid')
        refs.add(item['project'])
    require(len(refs) == 4 and len({config[r]['organization'] for r in
        ('source', 'capacity', 'target', 'preserved')}) == 1, 'hosted_window_targets_invalid')
    raw = private_read(authority_path, 32768)
    require(hashlib.sha256(raw).hexdigest() == authority_sha, 'hosted_window_authority_changed')
    authority = json_bytes(raw)
    require(set(authority) == {'version', 'windowId', 'configSha256', 'validBeforeUtc', 'maximumCharge',
        'oneAttempt', 'availabilityAcknowledgement'} and authority['version'] == 1 and
        authority['configSha256'] == expected_sha and authority['maximumCharge'] == 0 and
        authority['oneAttempt'] is True and authority['availabilityAcknowledgement'] ==
        'host-awake-only; no hard outage bound; external availability required for host-loss coverage',
        'hosted_window_new_authority_required')
    UUID(authority['windowId'])
    expiry = datetime.fromisoformat(authority['validBeforeUtc'])
    require(expiry.tzinfo is not None and (cleanup_only or time.time() < expiry.timestamp()),
        'hosted_window_authority_expired')
    if cleanup_only:
        # Exact config/authority and consumed receipt still required by main.
        # A moved checkout, expired approval or lost worker files must not block
        # cleanup; this path cannot resume the target or start a worker.
        return config, authority
    worker = config['worker']
    require(set(worker) == {'argv', 'cwd', 'head', 'tree', 'files'} and isinstance(worker['argv'], list) and
        worker['argv'] and all(isinstance(x, str) for x in worker['argv']) and
        Path(worker['argv'][0]).is_absolute() and Path(worker['cwd']).is_absolute(),
        'hosted_window_worker_invalid')
    require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=worker['cwd'], text=True).strip() == worker['head'] and
        subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=worker['cwd'], text=True).strip() == worker['tree'] and
        not subprocess.check_output(['git', 'status', '--porcelain'], cwd=worker['cwd'], text=True).strip(),
        'hosted_window_candidate_changed')
    require(worker['files'] and str(Path(worker['argv'][0]).resolve()) in worker['files'],
        'hosted_window_tools_unpinned')
    required_pins = {str(Path(sys.executable).resolve()), str(Path(__file__).resolve())}
    for module in ('hosted_recovery_diagnostics', 'hosted_recovery_capture',
            'hosted_recovery_target', 'hosted_backup_recovery'):
        required_pins.add(str(Path(importlib.util.find_spec(
            'talli_backend.adapters.' + module).origin).resolve()))
    require(required_pins <= set(worker['files']), 'hosted_window_guardian_source_unpinned')
    for name, pin in worker['files'].items():
        require(Path(name).is_absolute() and hashlib.sha256(Path(name).read_bytes()).hexdigest() == pin,
            'hosted_window_worker_file_changed')
    return config, authority


def launch_guardian(argv):
    return subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('start', 'supervise', 'cleanup'))
    parser.add_argument('--config', required=True)
    parser.add_argument('--expected-config-sha256', required=True)
    parser.add_argument('--authority', required=True)
    parser.add_argument('--expected-authority-sha256', required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    config, authority = load_config(args.config, args.expected_config_sha256,
        args.authority, args.expected_authority_sha256, cleanup_only=args.command == 'cleanup')
    work = Path(config['work'])
    require(work.is_absolute() and not any(p.is_symlink() for p in (work, *work.parents)),
        'hosted_window_work_invalid')
    # One stable authority directory serializes guardians. A receipt is consumed
    # even if launch fails: startup cannot silently authorize another attempt.
    authority_dir = Path(args.authority).absolute().parent
    require(authority_dir.stat().st_uid == os.getuid() and not authority_dir.stat().st_mode & 0o077,
        'hosted_window_authority_directory_invalid')
    used = authority_dir / (authority['windowId'] + '.used')
    if args.command == 'start':
        descriptor = os.open(used, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as f:
            json.dump({'configSha256': args.expected_config_sha256, 'authoritySha256': args.expected_authority_sha256}, f)
            f.flush(); os.fsync(f.fileno())
        directory = os.open(authority_dir, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        work.mkdir(mode=0o700)
        child = launch_guardian([sys.executable, '-B', '-m',
            'talli_backend.adapters.hosted_recovery_window', 'supervise',
            '--config', args.config, '--expected-config-sha256', args.expected_config_sha256,
            '--authority', args.authority, '--expected-authority-sha256', args.expected_authority_sha256])
        print(json.dumps({'status': 'guardian_launched_not_yet_acknowledged', 'pid': child.pid,
            'hostSuspendCovered': False, 'receipt': str(work / 'guardian.json')}))
        return 0
    require(json.loads(private_read(used, 32768)) == {'configSha256': args.expected_config_sha256,
        'authoritySha256': args.expected_authority_sha256}, 'hosted_window_authority_not_consumed')
    require(work.is_dir() and work.stat().st_uid == os.getuid() and not work.stat().st_mode & 0o077,
        'hosted_window_work_invalid')
    lock = os.open(authority_dir / 'active-guardian.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock, 'w') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(args.command == 'cleanup' or not (work / 'guardian.json').exists(),
            'hosted_window_no_guardian_resume')
        from talli_backend.adapters.hosted_backup_recovery import _atomic
        journal = work / 'guardian.json'
        prior = {}
        cleanup_sequence = None
        if args.command == 'cleanup':
            existing = sorted(work.glob('cleanup-journal-??????.json'))
            cleanup_sequence = int(existing[-1].stem.rsplit('-', 1)[1]) + 1 if existing else 1
            require(cleanup_sequence < 1_000_000, 'hosted_window_cleanup_journal_bound')
            source = existing[-1] if existing else journal
            if source.exists():
                prior = json_bytes(private_read(source, 256 * 1024))
                require(prior.get('configSha256') == args.expected_config_sha256 and
                    prior.get('authoritySha256') == args.expected_authority_sha256 and
                    prior.get('windowId') == authority['windowId'], 'hosted_window_prior_journal_changed')
            journal = work / ('cleanup-journal-' + format(cleanup_sequence, '06d') + '.json')
            require(not journal.exists(), 'hosted_window_cleanup_journal_exists')
        def record(value):
            _atomic(journal, {**value, 'configSha256': args.expected_config_sha256,
                'authoritySha256': args.expected_authority_sha256, 'windowId': authority['windowId'],
                'reviewedCandidate': config['worker']['head'], 'reviewedTree': config['worker']['tree'],
                'python': sys.version.split()[0], 'monotonicClock': time.get_clock_info('monotonic').implementation})
        supervisor = WindowSupervisor(config, Provider(config['credentials'],
            {**{r: config[r]['project'] for r in ('source', 'capacity', 'target', 'preserved')},
                'organization': config['target']['organization'], 'cleanupOnly': args.command == 'cleanup'}), record)
        def interrupted(signum, frame):
            if not supervisor.cleaning:
                raise WindowStopped('hosted_window_guardian_signal')
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        if args.command == 'cleanup':
            supervisor.restore_pending(prior)
            result = {**supervisor.cleanup(), 'hostedRecoveryAccepted': False,
                'previousWorkerTerminationVerified': False, 'hostSuspendCovered': False}
            _atomic(work / ('cleanup-only-' + format(cleanup_sequence, '06d') + '.json'), result)
        else:
            result = supervisor.run(lambda deadline: bounded_process(config['worker']['argv'],
                cwd=config['worker']['cwd'], deadline=deadline))
            _atomic(work / 'result.json', result)
        succeeded = result['cleanupVerified'] and (args.command == 'cleanup' or
            result['workerExitCode'] == 0 and result['failure'] is None)
        return 0 if succeeded else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'status': 'stopped', 'failure': safe_failure(error), 'hostedRecoveryAccepted': False}))
        raise SystemExit(1) from None
