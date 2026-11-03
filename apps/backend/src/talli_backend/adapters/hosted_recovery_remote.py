"""Independent cleanup preparation. No FastAPI registration or implicit deployment.

Production transports have fixed GitHub/Supabase origins. The checked-in workflow
is an inactive metadata-only template. Process tests inject loopback simulations.
"""
import argparse
from datetime import datetime, timezone
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
from uuid import uuid4
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from talli_backend.adapters.hosted_backup_recovery import _atomic
from talli_backend.adapters.hosted_recovery_capture import json_bytes, private_read, require
from talli_backend.adapters.hosted_recovery_diagnostics import safe_failure
from talli_backend.adapters.hosted_recovery_target import HostedDesignation
from talli_backend.adapters.hosted_recovery_window import (
    Deadline, Provider, WindowSupervisor, WindowStopped, _window_signals, stop_group, utc,
)
from talli_backend.adapters import hosted_recovery_arming as protocol


ROLES = ('source', 'capacity', 'target', 'preserved')
ACKNOWLEDGEMENT = ('independent runner remains required; runner/service loss and provider '
    'transition time are not guaranteed')


def timestamp(value):
    require(isinstance(value, str), 'hosted_remote_time_invalid')
    when = datetime.fromisoformat(value)
    require(when.tzinfo is not None and when.utcoffset().total_seconds() == 0,
        'hosted_remote_time_invalid')
    return when.timestamp()


def load_inputs(config_path, expected_config, authority_path, expected_authority, *, cleanup_only=False):
    raw = private_read(config_path, 65536)
    require(hashlib.sha256(raw).hexdigest() == expected_config, 'hosted_remote_config_changed')
    config = json_bytes(raw)
    require(set(config) == {'version', 'mode', 'repository', 'workflowPath', 'issueNumber', 'commit',
        'windowId', 'coordinatorPublicKey', 'armNonce', 'cleanupAtUtc', 'armBeforeUtc', 'projects',
        'callSeconds', 'pollSeconds', 'cleanupSeconds', 'heartbeatSeconds','remotePythonSha256'}, 'hosted_remote_config_invalid')
    require(type(config['version']) is int and config['version'] == 1 and config['mode'] in ('metadata-only', 'cleanup'),
        'hosted_remote_mode_invalid')
    remote_python = config['remotePythonSha256']
    require(config['mode'] == 'metadata-only' and remote_python is None or
        isinstance(remote_python,str) and re.fullmatch('[0-9a-f]{64}',remote_python),
        'hosted_remote_python_unapproved')
    require(set(config['projects']) == set(ROLES), 'hosted_remote_projects_invalid')
    for role in ROLES:
        expected = config['projects'][role]
        require(set(expected) == {'project', 'organization', 'name', 'region', 'engine'},
            'hosted_remote_projects_invalid')
        HostedDesignation(**{k:v for k,v in expected.items() if k != 'engine'})
        require(isinstance(expected['engine'], str) and expected['engine'].startswith('17.') and
            len(expected['engine']) < 40, 'hosted_remote_engine_invalid')
    require(len({config['projects'][r]['project'] for r in ROLES}) == 4 and
        len({config['projects'][r]['organization'] for r in ROLES}) == 1,
        'hosted_remote_projects_invalid')
    for key, low, high in [('callSeconds', 1, 10), ('pollSeconds', 5, 15),
            ('cleanupSeconds', 5, 300), ('heartbeatSeconds', 15, 30)]:
        require(type(config[key]) in (int,float) and math.isfinite(config[key]) and
            low <= config[key] <= high, 'hosted_remote_bounds_invalid')
    require(timestamp(config['armBeforeUtc']) < timestamp(config['cleanupAtUtc']),
        'hosted_remote_deadline_invalid')
    if not cleanup_only:
        require(time.time() < timestamp(config['armBeforeUtc']) and
            0 < timestamp(config['cleanupAtUtc']) - time.time() <= 2700,
            'hosted_remote_authority_expired')
    raw = private_read(authority_path, 32768)
    require(hashlib.sha256(raw).hexdigest() == expected_authority, 'hosted_remote_authority_changed')
    authority = json_bytes(raw)
    require(set(authority) == {'version','kind','windowId','configSha256','commit','cleanupAtUtc',
        'armBeforeUtc','mode','oneAttempt','maximumCharge','availabilityAcknowledgement'} and
        type(authority['version']) is int and authority['version'] == 1 and authority['kind'] == 'independent-cleanup' and
        authority['oneAttempt'] is True and type(authority['maximumCharge']) is int and
        authority['maximumCharge'] == 0 and authority['availabilityAcknowledgement'] == ACKNOWLEDGEMENT,
        'hosted_remote_new_authority_required')
    for key in ('windowId','commit','cleanupAtUtc','armBeforeUtc','mode'):
        require(authority[key] == config[key], 'hosted_remote_authority_binding_changed')
    require(authority['configSha256'] == expected_config, 'hosted_remote_authority_binding_changed')
    return config, authority


def binding_for(config, config_sha, authority_sha, *, run_id, job_id, attempt):
    result = {k:config[k] for k in ('windowId','commit','repository','workflowPath','issueNumber',
        'cleanupAtUtc','armBeforeUtc','coordinatorPublicKey','mode')}
    result.update(version=1, configSha256=config_sha, authoritySha256=authority_sha,
        runId=int(run_id), jobId=int(job_id), runAttempt=int(attempt))
    protocol.validate_binding(result)
    return result


def private_directory(path, *, create=False):
    path = Path(path)
    require(path.is_absolute() and not any(p.is_symlink() for p in (path,*path.parents)),
        'hosted_remote_directory_invalid')
    if create:
        path.mkdir(mode=0o700)
    require(path.is_dir() and path.stat().st_uid == os.getuid() and not path.stat().st_mode & 0o077,
        'hosted_remote_directory_invalid')
    return path


def exclusive(path, value):
    """Fail before dispatch if an exact one-use local/remote receipt cannot persist."""
    raw = json.dumps(value, sort_keys=True, separators=(',',':'), allow_nan=False).encode()
    descriptor = os.open(path, os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    directory = os.open(Path(path).parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def provider_for(config, credentials, *, cleanup_only=True):
    allowed = {r:config['projects'][r]['project'] for r in ROLES}
    allowed.update(organization=config['projects']['source']['organization'], cleanupOnly=cleanup_only)
    return Provider(credentials, allowed)


def check_project(config, provider, role, deadline):
    value = provider.call('get_project', config['projects'][role]['project'], deadline=deadline)
    expected = config['projects'][role]
    require(all(value.get(k) == expected[v] for k,v in [('id','project'),
        ('organization_id','organization'),('name','name'),('region','region'),('engine','engine')]),
        'hosted_remote_designation_changed')
    return value['status']


def preflight(config, provider):
    # Metadata-only PAT needs Project Settings Read, not organization access.
    deadline = Deadline(min(60, max(0, timestamp(config['armBeforeUtc']) - time.time())))
    required = [('source','ACTIVE_HEALTHY')] if config['mode']=='metadata-only' else [
        ('source','ACTIVE_HEALTHY'),('capacity','ACTIVE_HEALTHY'),
        ('target','INACTIVE'),('preserved','INACTIVE')]
    for role, expected in required:
        require(check_project(config, provider, role, deadline) == expected,
            'hosted_remote_initial_state_changed')


class AbsoluteDeadline(Deadline):
    def __init__(self, at):
        super().__init__(max(0, timestamp(at) - time.time()))
        self.at = timestamp(at)


def source_pins(worker, commit):
    require(set(worker) == {'argv','cwd','head','tree','files'} and worker['head'] == commit and
        isinstance(worker['argv'], list) and worker['argv'] and
        all(isinstance(x,str) for x in worker['argv']) and Path(worker['argv'][0]).is_absolute() and
        Path(worker['cwd']).is_absolute(), 'hosted_remote_worker_invalid')
    for name,v in worker['files'].items():
        require(Path(name).is_absolute() and hashlib.sha256(Path(name).read_bytes()).hexdigest() == v,
            'hosted_remote_worker_changed')
    pins = {str(Path(sys.executable).resolve()), str(Path(__file__).resolve()),
        str(Path(protocol.__file__).resolve())}
    require(pins <= set(worker['files']) and str(Path(worker['argv'][0]).resolve()) in worker['files'],
        'hosted_remote_worker_unpinned')
    require(subprocess.check_output(['git','rev-parse','HEAD'],cwd=worker['cwd'],text=True).strip() == commit and
        subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=worker['cwd'],text=True).strip() == worker['tree'] and
        not subprocess.check_output(['git','status','--porcelain'],cwd=worker['cwd'],text=True).strip(),
        'hosted_remote_source_changed')


class RemoteRunner:
    """Separate cleanup owner. Callbacks/transports are replaceable only in tests."""
    def __init__(self, config, binding, mailbox, provider, work, *, private_key=None):
        self.config, self.binding, self.mailbox, self.provider = config, binding, mailbox, provider
        self.work = private_directory(work, create=True)
        self.key = private_key or Ed25519PrivateKey.generate()
        exclusive(self.work/'remote-key.private', {'seed':self.key.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
            serialization.NoEncryption()).hex()})
        self.deadline = AbsoluteDeadline(binding['cleanupAtUtc'])
        # Stop control I/O before cleanup admission, not at its exact cutoff.
        self.control_deadline = AbsoluteDeadline(utc(timestamp(binding['cleanupAtUtc'])-
            2*config['callSeconds']-.25))
        self.ledger = protocol.RemoteLedger(binding, self.key,
            {r:config['projects'][r]['project'] for r in ('capacity','target')},
            lambda value:_atomic(self.work/'ledger.json', value),
            lambda message:mailbox.publish(message,deadline=self.control_deadline))
        self.failure = None
        self.cleanup = WindowSupervisor({**config, **config['projects']}, provider,
            lambda value:_atomic(self.work/'cleanup-journal.json',
                {**value,'binding':binding,'remotePublicKey':protocol.public_key(self.key),
                    'acceptedActions':self.ledger.accepted}))
        self.cleanup.work_deadline = self.deadline

    def observe(self):
        if self.config['mode']=='metadata-only':
            return
        for role in ('capacity','target'):
            status = check_project(self.config, self.provider, role,
                Deadline(min(self.config['callSeconds'], max(0,self.control_deadline.remaining()))))
            self.ledger.observe(self.config['projects'][role]['project'], status)

    def run(self):
        armed = False
        with _window_signals(self.cleanup):
            try:
                require(self.mailbox.verify_job(), 'hosted_remote_job_unverified')
                preflight(self.config, self.provider)
                self.observe()
                message = self.ledger.arm(self.config['armNonce'])
                _atomic(self.work/'arm.json', {'version':1,'binding':self.binding,
                    'remotePublicKey':protocol.public_key(self.key),'arm':message,
                    'runtime':getattr(self,'runtime',{'simulated':True})})
                armed = True
                while self.control_deadline.open() and not self.ledger.admission_closed:
                    self.observe()
                    if not self.control_deadline.open():
                        break
                    for command in self.mailbox.read(deadline=self.control_deadline):
                        if command.get('kind') not in ('intent','heartbeat','finish'):
                            continue
                        try:
                            protocol.verify(command,self.binding['coordinatorPublicKey'],self.binding)
                        except ValueError:
                            continue  # Untrusted mailbox content grants no authority.
                        if command['kind']=='intent':
                            # The previous POST may reach its goal while read()
                            # is in flight. Decide against post-read metadata,
                            # not the snapshot taken before receiving this intent.
                            self.observe()
                        self.ledger.handle(command)
                        if self.ledger.admission_closed:
                            break
                    time.sleep(min(self.config['pollSeconds'],max(0,self.control_deadline.remaining())))
            except BaseException as error:
                self.failure = safe_failure(error)
            finally:
                try:
                    self.ledger.close('closed')
                except Exception as error:
                    self.failure = self.failure or safe_failure(error)
                if not armed or self.config['mode'] == 'metadata-only' or not self.ledger.accepted:
                    # Independent enforcement in runtime, in addition to protocol mode.
                    result = {'metadataOnly':self.config['mode']=='metadata-only',
                        'lifecycleAdmitted':False,'preflightOrArmingFailed':not armed,
                        'cleanupSkipReason':'not_armed' if not armed else
                            'metadata_only' if self.config['mode']=='metadata-only' else 'no_accepted_lifecycle_intent',
                        'cleanupVerified':False,'pendingMutations':self.ledger.pending}
                else:
                    self.cleanup.restore_pending({'pendingHistoryKnown':True,
                        'pendingMutations':self.ledger.pending})
                    result = self.cleanup.cleanup()
                result.update(binding=self.binding,armed=armed,failure=self.failure,
                    lifecycleAdmitted=armed and self.config['mode']=='cleanup' and bool(self.ledger.accepted),
                    hostedRecoveryAccepted=False,providerTransitionBoundGuaranteed=False,
                    remoteRunnerAvailabilityGuaranteed=False,localCoordinatorTerminationVerified=False,
                    cleanupTiming=dict(self.cleanup.timing),
                    cleanupDeadlineMet=self.cleanup.timing.get('cleanupDeadlineMet'))
                _atomic(self.work/'result.json',result)
        return result


class LocalCoordinator:
    """Local work owner; it never performs cleanup provider mutations."""
    def __init__(self, config, binding, arm, private_key, mailbox, provider, work):
        self.config,self.binding,self.arm = config,binding,arm
        self.key,self.mailbox,self.provider = private_key,mailbox,provider
        require(protocol.public_key(private_key) == binding['coordinatorPublicKey'],
            'hosted_remote_coordinator_key_changed')
        self.work = private_directory(work,create=True)
        private_directory(self.work.parent)
        self.deadline = AbsoluteDeadline(binding['cleanupAtUtc'])
        self.sequence = 0
        self.armed = self.closed = False
        self.admission = protocol.LocalAdmission(binding,arm['remotePublicKey'],
            lambda command,ack:exclusive(self.work/('intent-'+command['nonce']+'.used'),
                {'command':command,'ack':ack}))

    def admit(self):
        # One coordinator directory is owner custody, never copied across hosts.
        # Consume even a failed admission; restarting does not repeat the attempt.
        exclusive(self.work.parent/(self.binding['windowId']+'.coordinator.used'),
            {'binding':self.binding})
        require(self.arm['binding'] == self.binding, 'hosted_remote_arm_changed')
        state = self.admission.accept_arm(self.arm['arm'],self.config['armNonce'],self.mailbox.verify_job())
        require(state['projects'] == {r:self.config['projects'][r]['project'] for r in ('capacity','target')},
            'hosted_remote_arm_projects_changed')
        self.armed = True
        _atomic(self.work/'admitted.json',{'binding':self.binding,'atUtc':utc(time.time()),
            'actualAcknowledgementVerified':True,'hostedRecoveryAccepted':False})

    def exchange(self, kind, *, deadline=None, **values):
        require(self.armed and not self.closed and self.deadline.open(), 'hosted_remote_closed')
        seconds = min(30,self.config['callSeconds']*3+self.config['pollSeconds'],
            max(0,self.deadline.remaining()))
        if deadline is not None:
            require(deadline.open(),'hosted_remote_closed')
            seconds = min(seconds,max(0,deadline.remaining()))
        # Preserve both limits: a missing heartbeat cannot consume the whole
        # remaining worker window, and a late exchange cannot reset its cutoff.
        wait = Deadline(seconds)
        require(wait.open(),'hosted_remote_closed')
        self.sequence += 1
        nonce = str(uuid4())
        command = protocol.sign(self.key,self.binding,kind,nonce,
            {'commandSeq':self.sequence,**values})
        exclusive(self.work/('command-'+format(self.sequence,'04d')+'.json'),command)
        publish_failure = None
        try:
            self.mailbox.publish(command,deadline=wait)
        except Exception as error:
            # A timed-out comment POST may have arrived. Reconcile the exact nonce;
            # never send another provider request or invent a second command.
            publish_failure = safe_failure(error)
        while wait.open() and self.deadline.open():
            if min(wait.remaining(),self.deadline.remaining()) <= self.config['callSeconds']:
                break
            for ack in self.mailbox.read(deadline=wait):
                require(wait.open() and self.deadline.open(),'hosted_remote_closed')
                if ack.get('kind') != kind+'_ack' or ack.get('nonce') != nonce:
                    continue
                try:
                    protocol.verify(ack,self.arm['remotePublicKey'],self.binding)
                except ValueError:
                    continue
                verified = self.mailbox.verify_job(deadline=wait)
                require(wait.open() and self.deadline.open(),'hosted_remote_closed')
                if kind == 'intent':
                    result = self.admission.consume(command,ack,verified)
                else:
                    result = self.admission.accept_reply(command,ack,verified)
                if kind == 'finish':
                    self.closed = True
                return result
            time.sleep(min(self.config['pollSeconds'],max(0,wait.remaining())))
        _atomic(self.work/'ack-unavailable.json',{'nonce':nonce,'kind':kind,
            'publishFailure':publish_failure,'providerDispatchAdmitted':False})
        raise WindowStopped('hosted_remote_ack_unavailable')

    def mutation(self, action, role):
        require((action,role) in (('pause','capacity'),('resume','target')),
            'hosted_remote_action_invalid')
        require(self.deadline.remaining() > 2*self.config['callSeconds']+2,
            'hosted_remote_dispatch_cutoff')
        permitted = self.exchange('intent',action=action,role=role)
        require(permitted == {'action':action,'project':self.config['projects'][role]['project']},
            'hosted_remote_intent_changed')
        require(self.deadline.open() and self.deadline.remaining() > self.config['callSeconds'],
            'hosted_remote_dispatch_cutoff')
        return self.provider.call(action,permitted['project'],deadline=Deadline(
            min(self.config['callSeconds'],self.deadline.remaining())))

    def wait(self, role, status):
        while self.deadline.open() and self.deadline.remaining() > self.config['callSeconds']:
            if check_project(self.config,self.provider,role,
                    Deadline(min(self.config['callSeconds'],self.deadline.remaining()))) == status:
                return
            time.sleep(self.config['pollSeconds'])
        raise WindowStopped('hosted_remote_provider_goal_unverified')

    def worker(self, argv, cwd=None):
        # Stop local work before the remote cleanup cutoff, leaving IPC/kill margin.
        stop_at = timestamp(self.binding['cleanupAtUtc'])-2*self.config['callSeconds']-2
        worker_deadline = AbsoluteDeadline(utc(stop_at))
        self.exchange('heartbeat',deadline=worker_deadline)
        require(time.time() < stop_at, 'hosted_remote_worker_cutoff')
        process = subprocess.Popen(argv,cwd=cwd,start_new_session=True,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        next_heartbeat = time.monotonic()+self.config['heartbeatSeconds']
        try:
            while process.poll() is None:
                require(self.deadline.open() and time.time() < stop_at,'hosted_remote_worker_cutoff')
                if time.monotonic() >= next_heartbeat:
                    self.exchange('heartbeat',deadline=worker_deadline)
                    next_heartbeat = time.monotonic()+self.config['heartbeatSeconds']
                time.sleep(.05)
            return process.returncode
        finally:
            stop_group(process)

    def run(self, worker=None):
        failure = None
        worker_code = None
        remote_cleanup_requested = False
        # Reuse scoped command signal ownership, but no local lifecycle cleanup.
        policy = type('LocalPolicy',(),{'cleaning':False})()
        with _window_signals(policy):
            try:
                self.admit()
                if self.binding['mode'] == 'cleanup':
                    require(callable(worker), 'hosted_remote_worker_required')
                    preflight(self.config,self.provider)
                    self.mutation('pause','capacity'); self.wait('capacity','INACTIVE')
                    self.mutation('resume','target'); self.wait('target','ACTIVE_HEALTHY')
                    worker_code = worker(self)
                else:
                    self.exchange('heartbeat')
                    worker_code = 0
            except BaseException as error:
                failure = safe_failure(error)
            finally:
                policy.cleaning = True
                if self.armed and not self.closed and self.deadline.open():
                    try:
                        self.exchange('finish')
                        remote_cleanup_requested = True
                    except Exception as error:
                        failure = failure or safe_failure(error)
        result = {'binding':self.binding,'workerExitCode':worker_code,'failure':failure,
            'remoteCleanupRequested':remote_cleanup_requested,'cleanupVerified':False,
            'hostedRecoveryAccepted':False,'remoteRunnerAvailabilityGuaranteed':False}
        _atomic(self.work/'local-result.json',result)
        return result


def recover_cleanup(config,binding,arm,mailbox,provider,work, *, prior_journal=None,
        expected_prior_sha=None):
    """A new cleanup-only invocation. Mutable mailbox history cannot prove a full tail."""
    work = private_directory(work,create=True)
    pending = {}
    latest = None
    messages = mailbox.history()
    for message in messages:
        try:
            old = timestamp(message['issuedAtUtc'])
            public = (binding['coordinatorPublicKey'] if message['kind'] == 'intent'
                else arm['remotePublicKey'])
            protocol.verify(message,public,binding,max_age=max(0,time.time()-old)+1,
                allow_expired_cleanup=True)
        except (ValueError,KeyError,TypeError):
            continue
        if message['kind'] in ('armed','intent_ack','heartbeat_ack','finish_ack'):
            state = message['payload'].get('state',{})
            if state.get('binding') == binding and isinstance(state.get('commandSeq'),int) and \
                    (latest is None or state['commandSeq'] >= latest['commandSeq']):
                latest = state
    if latest is not None:
        pending = latest['pendingMutations']
    accepted = list(latest.get('acceptedActions',[])) if latest is not None else []
    # Include any local intent after the last authenticated state: an ACK may have
    # been lost or deleted. Do not infer absence from this mutable transport.
    for message in messages:
        if message.get('kind') != 'intent':
            continue
        try:
            protocol.verify(message,binding['coordinatorPublicKey'],binding,
                max_age=max(0,time.time()-timestamp(message['issuedAtUtc']))+1,
                allow_expired_cleanup=True)
            payload = message['payload']
            if latest is not None and payload['commandSeq'] <= latest['commandSeq']:
                continue
            ref = config['projects'][payload['role']]['project']
            pending[payload['action']+':'+ref] = {'action':payload['action'],'project':ref,
                'goal':'INACTIVE' if payload['action']=='pause' else 'ACTIVE_HEALTHY',
                'atUtc':message['issuedAtUtc'],'acknowledged':False}
        except (ValueError,KeyError,TypeError):
            continue
    require((prior_journal is None) == (expected_prior_sha is None),
        'hosted_remote_prior_journal_required')
    if prior_journal is not None:
        raw = private_read(prior_journal,256*1024)
        require(hashlib.sha256(raw).hexdigest()==expected_prior_sha,'hosted_remote_prior_journal_changed')
        prior = json_bytes(raw)
        require(prior.get('binding')==binding,'hosted_remote_prior_journal_changed')
        for item in prior.get('acceptedActions',[]):
            matching=[old for old in accepted if old['nonce']==item['nonce']]
            require(not matching or matching==[item],'hosted_remote_prior_journal_changed')
            if not matching:accepted.append(item)
        for key,value in prior.get('pendingMutations',{}).items():
            require(key not in pending or pending[key]==value,'hosted_remote_prior_journal_changed')
            pending[key]=value
    supervisor = WindowSupervisor({**config,**config['projects']},provider,
        lambda value:_atomic(work/'cleanup-journal.json',
            {**value,'binding':binding,'acceptedActions':accepted}))
    supervisor.restore_pending({'pendingHistoryKnown':False,'pendingMutations':pending})
    # A missing tail may contain a previously dispatched cleanup POST. Fresh
    # unchanged metadata does not establish that request was rejected. Until a
    # complete independently trusted history is available, recovery may observe
    # and reconcile known goals, but MUST NOT dispatch any lifecycle request.
    supervisor.cleaning=True
    statuses={}
    deadline=Deadline(config['cleanupSeconds'])
    with _window_signals(supervisor):
        supervisor.emit('recovery.observation.started')
        for role in ROLES:
            try:
                statuses[role]=supervisor.project(role,deadline,require_engine=role!='target')
            except Exception as error:
                supervisor.cleanup_failure('recovery.'+role+'.observe',error)
        supervisor.emit('recovery.observation.finished',statuses=statuses)
    result={'binding':binding,'cleanupVerified':False,'pendingHistoryKnown':False,
        'acceptedActions':accepted,
        'pendingMutations':dict(supervisor.pending),'cleanupFailures':dict(supervisor.cleanup_failures),
        'targetPaused':statuses.get('target')=='INACTIVE' and not supervisor.unresolved('target','resume'),
        'capacityHealthy':statuses.get('capacity')=='ACTIVE_HEALTHY' and not supervisor.unresolved('capacity','pause'),
        'preservedBoundaryStatesVerified':statuses.get('source')=='ACTIVE_HEALTHY' and
            statuses.get('preserved')=='INACTIVE','mailboxHistoryCompleteProven':False,
        'previousCoordinatorTerminationVerified':False,'hostedRecoveryAccepted':False,
        'mutationsDisallowedDueToUnknownHistory':True,'priorJournalSha256':expected_prior_sha}
    _atomic(work/'result.json',result)
    return result


def verify_arm_archive(path, artifact_id, mailbox, binding, *, cleanup_only=False,
        expected_python_sha=None):
    require(Path(path).stat().st_size <= 65536,'hosted_remote_artifact_bound')
    raw = Path(path).read_bytes()
    require(0 < len(raw) <= 65536, 'hosted_remote_artifact_bound')
    metadata = mailbox.artifact_metadata(artifact_id)
    require(metadata.get('digest') == 'sha256:'+hashlib.sha256(raw).hexdigest(),
        'hosted_remote_artifact_digest_changed')
    with zipfile.ZipFile(path) as archive:
        require(archive.namelist() == ['arm.json'], 'hosted_remote_artifact_members_invalid')
        member = archive.getinfo('arm.json')
        require(member.file_size <= 32768 and not member.is_dir(), 'hosted_remote_artifact_bound')
        arm = json_bytes(archive.read(member))
    require(set(arm) == {'version','binding','remotePublicKey','arm','runtime'} and
        arm['version'] == 1 and arm['binding'] == binding,'hosted_remote_arm_changed')
    protocol.verify(arm['arm'],arm['remotePublicKey'],binding,
        max_age=max(0,time.time()-timestamp(arm['arm']['issuedAtUtc']))+1 if cleanup_only else 30,
        allow_expired_cleanup=cleanup_only)
    runtime = arm['runtime']
    require(runtime['gitHead'] == binding['commit'] and runtime['worktreeClean'] is True,
        'hosted_remote_runtime_changed')
    if binding['mode']=='cleanup':
        require(isinstance(expected_python_sha,str) and
            re.fullmatch('[0-9a-f]{64}',expected_python_sha) and
            runtime['pythonSha256']==expected_python_sha and runtime['pythonBytesPreapproved'] is True,
            'hosted_remote_python_unapproved')
    return arm


def runtime_identity(config):
    head = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    tree = subprocess.check_output(['git','rev-parse','HEAD^{tree}'],text=True).strip()
    require(head == config['commit'] and not subprocess.check_output(['git','status','--porcelain']).strip(),
        'hosted_remote_source_changed')
    expected = config.get('remotePythonSha256')
    python_sha = hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()
    require(config['mode'] == 'metadata-only' and expected is None or expected == python_sha,
        'hosted_remote_python_unapproved')
    root = Path(subprocess.check_output(['git','rev-parse','--show-toplevel'],text=True).strip()).resolve()
    modules = (Path(__file__),Path(protocol.__file__),Path(__file__).with_name('hosted_recovery_window.py'),
        Path(__file__).with_name('hosted_recovery_mailbox.py'))
    for module in modules:
        relative = 'apps/backend/src/talli_backend/adapters/'+module.name
        require(module.resolve() == root/relative and module.read_bytes() ==
            subprocess.check_output(['git','show',head+':'+relative]),'hosted_remote_source_changed')
    return {'gitHead':head,'gitTree':tree,'worktreeClean':True,'pythonVersion':sys.version.split()[0],
        'pythonSha256':python_sha,'pythonBytesPreapproved':expected == python_sha,
        'moduleSha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in modules}}


def main(argv=None):
    require((3,12) <= sys.version_info[:2] < (3,14),'hosted_remote_python_unsupported')
    from talli_backend.adapters.hosted_recovery_mailbox import GitHubMailbox, resolve_job
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('serve','coordinate','recover'))
    for name in ('config','expected-config-sha256','authority','expected-authority-sha256','credentials','work'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--run-id',type=int)
    parser.add_argument('--job-id',type=int)
    parser.add_argument('--artifact-id',type=int)
    parser.add_argument('--arm-archive')
    parser.add_argument('--coordinator-key')
    parser.add_argument('--worker-config')
    parser.add_argument('--metadata-only',action='store_true')
    parser.add_argument('--prior-journal')
    parser.add_argument('--expected-prior-journal-sha256')
    args = parser.parse_args(argv)
    os.umask(0o077)
    config,authority = load_inputs(args.config,args.expected_config_sha256,args.authority,
        args.expected_authority_sha256,cleanup_only=args.command=='recover')
    require(not args.metadata_only or config['mode']=='metadata-only','hosted_remote_mode_denied')
    run_id = args.run_id or int(os.environ.get('GITHUB_RUN_ID','0'))
    attempt = int(os.environ.get('GITHUB_RUN_ATTEMPT','1'))
    partial = {k:config[k] for k in ('windowId','commit','repository','workflowPath','issueNumber',
        'cleanupAtUtc','armBeforeUtc','coordinatorPublicKey','mode')}
    partial.update(version=1,configSha256=args.expected_config_sha256,
        authoritySha256=args.expected_authority_sha256,runId=run_id,runAttempt=attempt)
    job_id = args.job_id
    if args.command == 'serve':
        require(os.environ.get('GITHUB_REPOSITORY') == config['repository'] and
            os.environ.get('GITHUB_SHA') == config['commit'] and
            os.environ.get('GITHUB_WORKFLOW_SHA') == config['commit'], 'hosted_remote_workflow_changed')
        identity = runtime_identity(config)
        job_id = job_id or resolve_job(partial,credentials_path=args.credentials,
            call_seconds=config['callSeconds'])
    require(type(job_id) is int and type(run_id) is int, 'hosted_remote_run_unverified')
    binding = {**partial,'jobId':job_id}
    protocol.validate_binding(binding,allow_expired_cleanup=args.command=='recover')
    mailbox = GitHubMailbox(binding,args.credentials,config['callSeconds'])
    if args.command == 'serve':
        remote = RemoteRunner(config,binding,mailbox,provider_for(config,args.credentials),args.work)
        remote.runtime = identity
        result = remote.run()
        return 0 if result['failure'] is None and (config['mode']=='metadata-only' or
            result['cleanupVerified'] and result['cleanupDeadlineMet'] is True) else 1
    require(args.arm_archive and args.artifact_id, 'hosted_remote_artifact_required')
    arm = verify_arm_archive(args.arm_archive,args.artifact_id,mailbox,binding,
        cleanup_only=args.command=='recover',expected_python_sha=config['remotePythonSha256'])
    if args.command == 'recover':
        require(config['mode']=='cleanup','hosted_remote_mode_denied')
        result = recover_cleanup(config,binding,arm,mailbox,provider_for(config,args.credentials),args.work,
            prior_journal=args.prior_journal,expected_prior_sha=args.expected_prior_journal_sha256)
        return 0 if result['cleanupVerified'] else 1
    require(args.coordinator_key, 'hosted_remote_coordinator_key_required')
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(json_bytes(
        private_read(args.coordinator_key,4096))['seed']))
    coordinator = LocalCoordinator(config,binding,arm,key,mailbox,
        provider_for(config,args.credentials,cleanup_only=False),args.work)
    worker = None
    if config['mode']=='cleanup':
        require(args.worker_config,'hosted_remote_worker_required')
        value = json_bytes(private_read(args.worker_config,65536));source_pins(value,config['commit'])
        worker = lambda owner:owner.worker(value['argv'],value['cwd'])
    result = coordinator.run(worker)
    return 0 if result['failure'] is None and result['workerExitCode']==0 else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'status':'refused','failure':safe_failure(error),
            'hostedRecoveryAccepted':False}),file=sys.stderr)
        raise SystemExit(1)
