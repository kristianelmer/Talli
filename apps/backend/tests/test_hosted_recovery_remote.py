"""Real process separation against loopback simulations, never a hosted provider.

SIGSTOP models only coordinator scheduling loss. It is not a hardware suspend or
GitHub runner/service availability test. Synthetic keys/tokens stay in tmp_path.
"""
from datetime import datetime,timezone
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import multiprocessing
import os
from pathlib import Path
import signal
import sys
import threading
import time
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx
import pytest

from talli_backend.adapters import hosted_recovery_arming as protocol
from talli_backend.adapters import hosted_recovery_remote as remote
from talli_backend.adapters.hosted_recovery_window import Deadline


class Simulation:
    def __init__(self,config):
        self.config=config
        self.states={'source':'ACTIVE_HEALTHY','capacity':'ACTIVE_HEALTHY',
            'target':'INACTIVE','preserved':'INACTIVE'}
        self.messages=[]
        self.calls=[]
        self.running=True
        self.cleanup_auth_failure=False
        self.delay=None
        self.delay_seconds=.15
        self.arm_delay=0
        self.job_delay=0
        self.local_delays={}
        self.remote_read_delay=0
        self.drop_local_heartbeats=False
        self.mutations_with_caller=[]
        self.lock=threading.RLock()

    def handler(self):
        model=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,status,value):
                raw=json.dumps(value).encode()
                try:
                    self.send_response(status);self.send_header('Content-Length',str(len(raw)))
                    self.end_headers();self.wfile.write(raw)
                except (BrokenPipeError,ConnectionResetError):pass
            def do_GET(self):
                if self.headers.get('Authorization')!='Bearer synthetic-loopback-only':
                    self.reply(401,{});return
                if self.headers.get('X-Simulation-Caller')=='local':
                    time.sleep(model.local_delays.get(('GET',self.path),0))
                if self.path=='/mailbox':
                    if self.headers.get('X-Simulation-Caller')=='remote':time.sleep(model.remote_read_delay)
                    self.reply(200,list(model.messages));return
                if self.path=='/job':
                    time.sleep(model.job_delay);self.reply(200,{'running':model.running});return
                action,ref=self.path.strip('/').split('/')
                assert action=='get_project'
                role=next(r for r,v in model.config['projects'].items() if v['project']==ref)
                with model.lock:
                    model.calls.append((action,role,time.time()))
                    item=model.config['projects'][role]
                    self.reply(200,{'id':ref,'organization_id':item['organization'],
                        'name':item['name'],'region':item['region'],'engine':item['engine'],
                        'status':model.states[role]})
            def do_POST(self):
                if self.headers.get('Authorization')!='Bearer synthetic-loopback-only':
                    self.reply(401,{});return
                size=int(self.headers['Content-Length']);assert size<65536
                value=json.loads(self.rfile.read(size))
                if self.path=='/mailbox':
                    if value['kind']=='armed':time.sleep(model.arm_delay)
                    with model.lock:model.messages.append(value)
                    if model.drop_local_heartbeats and value['kind']=='heartbeat' and \
                            self.headers.get('X-Simulation-Caller')=='local':
                        with model.lock:model.messages.pop()
                    if self.headers.get('X-Simulation-Caller')=='local':
                        time.sleep(model.local_delays.get(('POST','/mailbox'),0))
                    self.reply(201,{});return
                action,ref=self.path.strip('/').split('/')
                role=next(r for r,v in model.config['projects'].items() if v['project']==ref)
                assert action in ('pause','resume')
                with model.lock:model.calls.append((action,role,time.time()))
                model.mutations_with_caller.append((action,role,time.time(),self.headers.get('X-Simulation-Caller')))
                if model.cleanup_auth_failure and (action,role) in (('pause','target'),('resume','capacity')):
                    self.reply(401,{'private':'not retained'});return
                def apply():
                    with model.lock:model.states[role]='INACTIVE' if action=='pause' else 'ACTIVE_HEALTHY'
                if model.delay==(action,role):
                    time.sleep(model.delay_seconds);apply()
                else:apply()
                self.reply(200,{'ok':True})
        return Handler


class SimMailbox:
    def __init__(self,url,caller='remote'):self.url=url;self.seen=0;self.caller=caller
    def request(self,method,path,value=None,*,deadline=None):
        if deadline is not None:assert deadline.open()
        with httpx.Client(trust_env=False,timeout=max(.001,min(.4,
                deadline.remaining() if deadline is not None else .4))) as client:
            response=client.request(method,self.url+path,json=value,
                headers={'Authorization':'Bearer synthetic-loopback-only','X-Simulation-Caller':self.caller})
            response.raise_for_status();return response.json()
    def publish(self,value,*,deadline=None):self.request('POST','/mailbox',value,deadline=deadline)
    def read(self,*,deadline=None):
        values=self.request('GET','/mailbox',deadline=deadline);result=values[self.seen:];self.seen=len(values);return result
    def history(self,*,deadline=None):return self.request('GET','/mailbox',deadline=deadline)
    def verify_job(self,*,deadline=None):return self.request('GET','/job',deadline=deadline)['running']


class SimProvider:
    def __init__(self,url,caller='remote'):self.url=url;self.caller=caller
    def call(self,action,ref,*,deadline):
        assert deadline.open()
        with httpx.Client(trust_env=False,timeout=max(.01,min(.06,deadline.remaining()))) as client:
            response=client.request('GET' if action=='get_project' else 'POST',
                self.url+'/'+action+'/'+ref,json={} if action!='get_project' else None,
                headers={'Authorization':'Bearer synthetic-loopback-only','X-Simulation-Caller':self.caller})
            response.raise_for_status();return response.json()


def _run_remote(config,binding,url,work):
    remote.RemoteRunner(config,binding,SimMailbox(url),SimProvider(url),work).run()


def _run_local(config,binding,url,work,seed,actual_worker):
    arm=json.loads((Path(work).parent/'remote/arm.json').read_text())
    owner=remote.LocalCoordinator(config,binding,arm,Ed25519PrivateKey.from_private_bytes(seed),
        SimMailbox(url,caller='local'),SimProvider(url,caller='local'),work)
    def worker(coordinator):
        (Path(work)/'working').write_text('synthetic work; no SQL')
        if actual_worker:
            code='from pathlib import Path;import os,time;Path('+repr(str(Path(work)/'worker-pid'))+').write_text(str(os.getpid()));time.sleep(30)'
            return coordinator.worker([sys.executable,'-B','-c',code])
        while coordinator.deadline.open():time.sleep(.01)
        return 0
    owner.run(worker)


def _run_recovery(config,binding,url,work,arm,prior=None,expected_prior=None):
    remote.recover_cleanup(config,binding,arm,SimMailbox(url),SimProvider(url),work,
        prior_journal=prior,expected_prior_sha=expected_prior)


def until(predicate,seconds=10):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.01)
    raise AssertionError('fixture condition not reached')


@pytest.fixture
def fixture(tmp_path):
    seed=os.urandom(32);key=Ed25519PrivateKey.from_private_bytes(seed)
    now=time.time();config={'version':1,'mode':'cleanup','repository':'owner/repo',
        'workflowPath':'.github/workflows/talli-recovery-cleanup.yml','issueNumber':12,
        'commit':'a'*40,'windowId':str(uuid4()),'coordinatorPublicKey':protocol.public_key(key),
        'armNonce':str(uuid4()),'cleanupAtUtc':remote.utc(now+6),'armBeforeUtc':remote.utc(now+3),
        'callSeconds':.05,'pollSeconds':.02,'cleanupSeconds':1,'heartbeatSeconds':.1,
        'remotePythonSha256':hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest(),
        'projects':{r:{'project':c*20,'organization':'e'*20,'name':r,'region':'eu-west-1',
            'engine':'17.11.0.011'} for r,c in zip(remote.ROLES,'abcd')}}
    binding=remote.binding_for(config,'b'*64,'c'*64,run_id=1,job_id=2,attempt=1)
    model=Simulation(config);server=ThreadingHTTPServer(('127.0.0.1',0),model.handler())
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    url='http://127.0.0.1:'+str(server.server_port);children=[]
    def start(which='remote',*,actual_worker=False):
        target,args=(_run_remote,(config,binding,url,str(tmp_path/'remote'))) if which=='remote' else \
            (_run_local,(config,binding,url,str(tmp_path/'local'),seed,actual_worker))
        p=multiprocessing.get_context('spawn').Process(target=target,args=args);p.start();children.append(p);return p
    yield config,binding,model,url,tmp_path,start,children
    for p in children:
        if p.is_alive():
            os.kill(p.pid,signal.SIGCONT);p.kill()
        p.join(3);p.close()
    server.shutdown();server.server_close();thread.join(2)


def begin(fixture,*,actual_worker=False):
    config,binding,model,url,work,start,children=fixture
    runner=start();until(lambda:(work/'remote/arm.json').exists())
    local=start('local',actual_worker=actual_worker)
    until(lambda:(work/'local/working').exists())
    return runner,local


def lifecycle(model):return [(a,r) for a,r,_ in model.calls if a in ('pause','resume')]


@pytest.mark.parametrize('loss',['kill','stop'])
def test_independent_runner_cleans_after_local_coordinator_loss(fixture,loss):
    config,binding,model,url,work,start,children=fixture
    runner,local=begin(fixture)
    if loss=='kill':local.kill();local.join(2)
    else:os.kill(local.pid,signal.SIGSTOP)
    runner.join(10);assert runner.exitcode==0
    result=json.loads((work/'remote/result.json').read_text())
    assert result['cleanupVerified'] and result['cleanupDeadlineMet'] is True
    assert result['localCoordinatorTerminationVerified'] is False
    assert not result['hostedRecoveryAccepted'] and not result['remoteRunnerAvailabilityGuaranteed']
    assert model.states=={'source':'ACTIVE_HEALTHY','capacity':'ACTIVE_HEALTHY',
        'target':'INACTIVE','preserved':'INACTIVE'}
    assert lifecycle(model)==[('pause','capacity'),('resume','target'),('pause','target'),('resume','capacity')]
    if loss=='stop':os.kill(local.pid,signal.SIGCONT);local.join(3);assert local.exitcode==0


def test_remote_sigterm_attempts_cleanup_but_does_not_prove_local_termination(fixture):
    config,binding,model,url,work,start,children=fixture
    runner,local=begin(fixture)
    os.kill(runner.pid,signal.SIGTERM);runner.join(4);assert runner.exitcode==0
    result=json.loads((work/'remote/result.json').read_text())
    assert result['cleanupVerified'] and not result['localCoordinatorTerminationVerified']
    assert result['failure'] is not None
    assert model.states['capacity']=='ACTIVE_HEALTHY' and model.states['target']=='INACTIVE'


def test_remote_kill_stops_local_owned_worker_and_recovery_is_conservatively_unverified(fixture):
    config,binding,model,url,work,start,children=fixture
    runner,local=begin(fixture,actual_worker=True)
    until(lambda:(work/'local/worker-pid').exists())
    worker_pid=int((work/'local/worker-pid').read_text())
    runner.kill();runner.join(2);model.running=False
    local.join(7);assert local.exitcode==0
    assert not (work/'remote/result.json').exists()
    with pytest.raises(ProcessLookupError):os.kill(worker_pid,0)
    assert model.states['capacity']=='INACTIVE' and model.states['target']=='ACTIVE_HEALTHY'
    arm=json.loads((work/'remote/arm.json').read_text())
    recovery=multiprocessing.get_context('spawn').Process(target=_run_recovery,
        args=(config,binding,url,str(work/'recovery'),arm));recovery.start();children.append(recovery)
    recovery.join(5);assert recovery.exitcode==0
    result=json.loads((work/'recovery/result.json').read_text())
    assert not result['cleanupVerified'] and not result['pendingHistoryKnown']
    assert not result['mailboxHistoryCompleteProven'] and not result['previousCoordinatorTerminationVerified']
    assert result['mutationsDisallowedDueToUnknownHistory']
    assert model.states['capacity']=='INACTIVE' and model.states['target']=='ACTIVE_HEALTHY'
    assert lifecycle(model).count(('pause','capacity'))==1
    assert lifecycle(model).count(('resume','target'))==1


def test_stopped_remote_runner_cannot_act_until_resumed_and_reports_missed_cutoff(fixture):
    config,binding,model,url,work,start,children=fixture
    runner,local=begin(fixture)
    os.kill(runner.pid,signal.SIGSTOP)
    until(lambda:time.time()>remote.timestamp(binding['cleanupAtUtc'])+.1)
    assert model.states['capacity']=='INACTIVE' and model.states['target']=='ACTIVE_HEALTHY'
    assert not (work/'remote/result.json').exists()
    os.kill(runner.pid,signal.SIGCONT);runner.join(5);assert runner.exitcode==0
    result=json.loads((work/'remote/result.json').read_text())
    assert result['cleanupDeadlineMet'] is False
    assert not result['remoteRunnerAvailabilityGuaranteed']


def test_metadata_only_signed_arm_close_never_dispatches_provider_lifecycle(fixture):
    config,binding,model,url,work,start,children=fixture
    config['mode']=binding['mode']='metadata-only'
    runner=start();until(lambda:(work/'remote/arm.json').exists())
    local=start('local');local.join(5);runner.join(5)
    assert local.exitcode==runner.exitcode==0
    result=json.loads((work/'remote/result.json').read_text())
    assert result['metadataOnly'] and not result['lifecycleAdmitted'] and not result['cleanupVerified']
    assert lifecycle(model)==[]
    assert [m['kind'] for m in model.messages]==['armed','heartbeat','heartbeat_ack','finish','finish_ack']


def test_cleanup_auth_failure_is_retained_and_never_converted_to_success(fixture):
    config,binding,model,url,work,start,children=fixture
    runner,local=begin(fixture);model.cleanup_auth_failure=True
    os.kill(runner.pid,signal.SIGTERM);runner.join(5);assert runner.exitcode==0
    result=json.loads((work/'remote/result.json').read_text())
    assert not result['cleanupVerified'] and result['pendingMutations']
    assert result['cleanupFailures']
    assert any(v.get('httpStatus')==401 for v in result['cleanupFailures'].values())
    assert 'not retained' not in (work/'remote/result.json').read_text()
    assert lifecycle(model).count(('pause','target'))==1
    assert lifecycle(model).count(('resume','capacity'))==1


@pytest.mark.parametrize('delayed',[('pause','capacity'),('resume','target')])
def test_deferred_post_preserves_intent_until_goal_and_never_replays(fixture,delayed):
    config,binding,model,url,work,start,children=fixture
    model.delay=delayed
    runner=start();until(lambda:(work/'remote/arm.json').exists())
    local=start('local');local.join(6);runner.join(8)
    assert local.exitcode==runner.exitcode==0
    result=json.loads((work/'remote/result.json').read_text())
    assert result['cleanupVerified'] and not result['pendingMutations']
    assert lifecycle(model).count(delayed)==1
    assert model.states['capacity']=='ACTIVE_HEALTHY' and model.states['target']=='INACTIVE'


def test_delayed_arm_delivery_expires_before_any_local_provider_admission(fixture):
    config,binding,model,url,work,start,children=fixture
    config['armBeforeUtc']=binding['armBeforeUtc']=remote.utc(time.time()+.5)
    model.arm_delay=.7
    runner=start();until(lambda:(work/'remote/result.json').exists() or (work/'remote/arm.json').exists())
    if (work/'remote/arm.json').exists():
        local=start('local');local.join(5);assert local.exitcode==0
        result=json.loads((work/'local/local-result.json').read_text());assert result['failure']
    runner.join(8);assert runner.exitcode==0
    assert lifecycle(model)==[]


def test_cumulative_slow_heartbeat_io_does_not_hold_worker_past_its_cutoff(fixture):
    config,binding,model,url,work,start,children=fixture
    runner,local=begin(fixture,actual_worker=True)
    until(lambda:(work/'local/worker-pid').exists())
    pid=int((work/'local/worker-pid').read_text())
    stop_at=remote.timestamp(binding['cleanupAtUtc'])-2*config['callSeconds']-2
    until(lambda:time.time()>stop_at-.25)
    model.local_delays={('POST','/mailbox'):.15,('GET','/mailbox'):.15,('GET','/job'):.25}
    def gone():
        try:os.kill(pid,0);return False
        except ProcessLookupError:return True
    until(gone,seconds=2)
    assert time.time()<stop_at+.2
    local.join(4);runner.join(8)
    assert local.exitcode==runner.exitcode==0
    assert json.loads((work/'local/local-result.json').read_text())['failure']
    local_mutations=[(a,r,at) for a,r,at,caller in model.mutations_with_caller if caller=='local']
    assert [(a,r) for a,r,_ in local_mutations]==[('pause','capacity'),('resume','target')]
    assert all(at<stop_at for _,_,at in local_mutations)


def test_lost_cleanup_post_and_repeated_recovery_preserve_intent_without_redispatch(fixture):
    config,binding,model,url,work,start,children=fixture
    runner,local=begin(fixture)
    model.delay=('pause','target');model.delay_seconds=3
    os.kill(runner.pid,signal.SIGTERM)
    until(lambda:('pause','target') in lifecycle(model))
    runner.kill();runner.join(2);model.running=False
    original=work/'remote/cleanup-journal.json';original_bytes=original.read_bytes()
    assert 'pause:'+config['projects']['target']['project'] in json.loads(original_bytes)['pendingMutations']
    arm=json.loads((work/'remote/arm.json').read_text())
    prior=original
    for number in range(3):
        if number==2:until(lambda:model.states['target']=='INACTIVE')
        destination=work/('observe-recovery-'+str(number))
        p=multiprocessing.get_context('spawn').Process(target=_run_recovery,
            args=(config,binding,url,str(destination),arm,str(prior),hashlib.sha256(prior.read_bytes()).hexdigest()))
        p.start();children.append(p);p.join(4);assert p.exitcode==0
        result=json.loads((destination/'result.json').read_text())
        assert not result['cleanupVerified'] and result['mutationsDisallowedDueToUnknownHistory']
        assert result['acceptedActions']
        prior=destination/'cleanup-journal.json'
    assert original.read_bytes()==original_bytes
    assert lifecycle(model).count(('pause','target'))==1
    assert lifecycle(model).count(('resume','capacity'))==0


def test_changed_preflight_state_never_triggers_unadmitted_cleanup_mutations(fixture):
    config,binding,model,url,work,start,children=fixture
    model.states['capacity']='INACTIVE'
    runner=start();runner.join(4);assert runner.exitcode==0
    result=json.loads((work/'remote/result.json').read_text())
    assert result['preflightOrArmingFailed'] and not result['armed'] and result['failure']
    assert lifecycle(model)==[] and model.states['capacity']=='INACTIVE'


def test_capacity_goal_arriving_during_mailbox_read_is_reobserved_before_next_intent(fixture):
    config,binding,model,url,work,start,children=fixture
    config['callSeconds']=.2
    model.remote_read_delay=.1
    runner,local=begin(fixture)
    os.kill(local.pid,signal.SIGTERM)
    local.join(5);runner.join(6)
    assert local.exitcode==runner.exitcode==0
    result=json.loads((work/'remote/result.json').read_text())
    assert result['cleanupVerified'] and result['failure'] is None
    assert lifecycle(model)==[('pause','capacity'),('resume','target'),('pause','target'),('resume','capacity')]


def test_missing_heartbeat_stops_worker_on_ack_budget_not_remaining_window(fixture):
    config,binding,model,url,work,start,children=fixture
    runner,local=begin(fixture,actual_worker=True)
    until(lambda:(work/'local/worker-pid').exists())
    pid=int((work/'local/worker-pid').read_text())
    model.drop_local_heartbeats=True
    started=time.monotonic()
    def gone():
        try:os.kill(pid,0);return False
        except ProcessLookupError:return True
    until(gone,seconds=.8)
    assert time.monotonic()-started<.8
    assert time.time()<remote.timestamp(binding['cleanupAtUtc'])-1
    local.join(4);runner.join(8)
    assert local.exitcode==runner.exitcode==0
    assert json.loads((work/'local/local-result.json').read_text())['failure']
