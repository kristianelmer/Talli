"""Authority bytes and bootstrap provenance, with no provider/GitHub connection."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import time
from types import SimpleNamespace
from uuid import uuid4
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from talli_backend.adapters import hosted_recovery_arming as protocol
from talli_backend.adapters import hosted_recovery_remote as remote


@pytest.fixture
def inputs(tmp_path):
    key=Ed25519PrivateKey.generate()
    cfg={'version':1,'mode':'metadata-only','repository':'owner/repo',
        'workflowPath':'.github/workflows/talli-recovery-cleanup.yml','issueNumber':2,'commit':'a'*40,
        'windowId':str(uuid4()),'coordinatorPublicKey':protocol.public_key(key),'armNonce':str(uuid4()),
        'armBeforeUtc':remote.utc(time.time()+30),'cleanupAtUtc':remote.utc(time.time()+120),
        'remotePythonSha256':None,'callSeconds':1,'pollSeconds':5,'cleanupSeconds':5,'heartbeatSeconds':15,
        'projects':{r:{'project':c*20,'organization':'e'*20,'name':r,'region':'eu-west-1',
            'engine':'17.11.0.011'} for r,c in zip(remote.ROLES,'abcd')}}
    def write(config=None,authority_change=None):
        config=config or cfg
        raw=protocol.canonical(config);config_sha=sha256(raw).hexdigest()
        authority={k:config[k] for k in ('windowId','commit','cleanupAtUtc','armBeforeUtc','mode')}
        authority.update(version=1,kind='independent-cleanup',configSha256=config_sha,
            oneAttempt=True,maximumCharge=0,availabilityAcknowledgement=remote.ACKNOWLEDGEMENT)
        authority.update(authority_change or {})
        authority_raw=protocol.canonical(authority)
        p=tmp_path/'config.json';p.write_bytes(raw);p.chmod(0o600)
        q=tmp_path/'authority.json';q.write_bytes(authority_raw);q.chmod(0o600)
        return p,config_sha,q,sha256(authority_raw).hexdigest()
    return cfg,write,tmp_path


def test_loader_accepts_new_metadata_only_authority_and_expired_cleanup_readback(inputs):
    cfg,write,_=inputs
    args=write();assert remote.load_inputs(*args)[0]==cfg
    expired=deepcopy(cfg);expired['armBeforeUtc']=remote.utc(time.time()-20)
    expired['cleanupAtUtc']=remote.utc(time.time()-10)
    args=write(expired)
    with pytest.raises(ValueError):remote.load_inputs(*args)
    assert remote.load_inputs(*args,cleanup_only=True)[0]==expired


@pytest.mark.parametrize('change',[{'version':True},{'oneAttempt':False},{'maximumCharge':True},
    {'maximumCharge':1},{'kind':'old-window'},{'mode':'cleanup'},
    {'availabilityAcknowledgement':'host-awake-only'},{'commit':'b'*40}])
def test_owner_authority_contract_cannot_be_relaxed(inputs,change):
    cfg,write,_=inputs
    with pytest.raises(ValueError):remote.load_inputs(*write(authority_change=change))


@pytest.mark.parametrize('field,value',[('version',True),('callSeconds',0),('pollSeconds',.1),
    ('cleanupSeconds',301),('heartbeatSeconds',float('inf')),('remotePythonSha256','not-a-hash')])
def test_public_config_bounds_fail_before_provider_use(inputs,field,value):
    cfg,write,_=inputs;cfg=deepcopy(cfg);cfg[field]=value
    if value==float('inf'):
        with pytest.raises(ValueError):write(cfg)
    else:
        with pytest.raises(ValueError):remote.load_inputs(*write(cfg))


def test_changed_input_bytes_and_cleanup_python_bytes_are_rejected(inputs):
    cfg,write,_=inputs;p,h,q,a=write()
    with pytest.raises(ValueError):remote.load_inputs(p,'0'*64,q,a)
    cfg=deepcopy(cfg);cfg['mode']='cleanup'
    with pytest.raises(ValueError):remote.load_inputs(*write(cfg))


def archive(inputs,*,mode='metadata-only',runtime_change=None,extra=False):
    cfg,write,root=inputs;cfg=deepcopy(cfg);cfg['mode']=mode
    binding=remote.binding_for(cfg,'b'*64,'c'*64,run_id=4,job_id=5,attempt=1)
    server=Ed25519PrivateKey.generate();ledger=protocol.RemoteLedger(binding,server,
        {r:cfg['projects'][r]['project'] for r in ('capacity','target')},lambda s:None,lambda m:None)
    runtime={'gitHead':binding['commit'],'gitTree':'f'*40,'worktreeClean':True,
        'pythonSha256':'d'*64,'pythonBytesPreapproved':mode=='cleanup'}
    runtime.update(runtime_change or {})
    arm={'version':1,'binding':binding,'remotePublicKey':protocol.public_key(server),
        'arm':ledger.arm(cfg['armNonce']),'runtime':runtime}
    path=root/'arm.zip'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('arm.json',protocol.canonical(arm))
        if extra:z.writestr('private-key','must be rejected')
    metadata={'digest':'sha256:'+sha256(path.read_bytes()).hexdigest()}
    return path,binding,arm,SimpleNamespace(artifact_metadata=lambda identifier:metadata)


def test_arm_zip_digest_member_and_runtime_are_verified(inputs):
    path,binding,arm,mailbox=archive(inputs)
    assert remote.verify_arm_archive(path,9,mailbox,binding)==arm
    path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='digest'):remote.verify_arm_archive(path,9,mailbox,binding)


@pytest.mark.parametrize('runtime',[{'gitHead':'b'*40},{'worktreeClean':False}])
def test_runtime_claims_must_match_approved_commit(inputs,runtime):
    path,binding,arm,mailbox=archive(inputs,runtime_change=runtime)
    with pytest.raises(ValueError):remote.verify_arm_archive(path,9,mailbox,binding)


def test_artifact_cannot_smuggle_extra_members_or_unapproved_python(inputs):
    path,binding,arm,mailbox=archive(inputs,extra=True)
    with pytest.raises(ValueError,match='members'):remote.verify_arm_archive(path,9,mailbox,binding)
    path,binding,arm,mailbox=archive(inputs,mode='cleanup')
    with pytest.raises(ValueError,match='python'):remote.verify_arm_archive(path,9,mailbox,binding)
    assert remote.verify_arm_archive(path,9,mailbox,binding,expected_python_sha='d'*64)==arm


def test_changed_binding_prevents_artifact_bootstrap(inputs):
    path,binding,arm,mailbox=archive(inputs)
    changed=deepcopy(binding);changed['jobId']=44
    with pytest.raises(ValueError):remote.verify_arm_archive(path,9,mailbox,changed)


@pytest.mark.parametrize('defect',['digest','binding'])
def test_prior_cleanup_journal_requires_exact_independent_digest_and_binding(inputs,defect):
    cfg,write,root=inputs
    binding=remote.binding_for(cfg,'b'*64,'c'*64,run_id=4,job_id=5,attempt=1)
    prior={'binding':deepcopy(binding),'pendingMutations':{},'acceptedActions':[]}
    if defect=='binding':prior['binding']['jobId']=99
    p=root/'prior.json';p.write_bytes(protocol.canonical(prior));p.chmod(0o600)
    raw=p.read_bytes();expected='0'*64 if defect=='digest' else sha256(raw).hexdigest()
    with pytest.raises(ValueError,match='prior_journal_changed'):
        remote.recover_cleanup(cfg,binding,{},SimpleNamespace(history=lambda:[]),object(),
            str(root/'new-recovery'),prior_journal=p,expected_prior_sha=expected)
    assert p.read_bytes()==raw
