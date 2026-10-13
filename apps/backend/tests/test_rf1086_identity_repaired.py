"""Recovery orchestration never allocates on admission failure or replays repair."""
import hashlib
import sys
import time
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from test_rf1086_identity_restore_runner import identity, DB, AUTH, ENV, SOURCE_URL
import rf1086_restore_control as control


@pytest.fixture
def repaired_model(tmp_path,monkeypatch):
    calls=[];owners=[];state={'metadata':0,'postchecks':0,'fault':None,'cleanupFault':False}
    role_raw=b'role observation'
    before=dict.fromkeys(('roles','catalog','auth','companyMemberships'),'a'*64)
    before['roles']=hashlib.sha256(role_raw).hexdigest()
    metadata=SimpleNamespace(METADATA_SQL=b'metadata',ROLE_ORDER_SQL=b'role order',
        decode_metadata=lambda *a,**kw:SimpleNamespace(),validate_role_order=lambda *a,**kw:None,
        bind_source_snapshot=lambda source,*a,**kw:source)
    monkeypatch.setitem(sys.modules,'rf1086_restore_metadata',metadata)
    monkeypatch.setattr(identity,'owned_identity_source',lambda *a:(DB,AUTH,ENV))
    def forbidden(*a,**kw):raise AssertionError('legacy diagnostic used during repaired restore')
    for name in ('CausalCapture','publish_actual_replay','emit_catalog_difference','emit_catalog_semantics'):
        monkeypatch.setattr(identity,name,forbidden)
    monkeypatch.setenv('TALLI_RF_REPLAY_DIR',str(tmp_path/'legacy-package-must-not-exist'))
    def fingerprint(container,**kwargs):
        if container==DB['Id']:
            state['postchecks']+=1
            if capture:=kwargs.get('catalog_capture'):capture.capture(b'[]\n{}\n[]\n')
            return dict(before)
        return dict(before) if state.get('recoverPass') else before|{'catalog':'b'*64}
    monkeypatch.setattr(identity,'fingerprint',fingerprint)
    monkeypatch.setattr(identity,'source_query',lambda c,s,**kw:role_raw if s==identity.ROLE_SQL else b'pg_stat_statements')
    budget=control.RecoveryBudget(time.monotonic())
    def command(args,**kwargs):
        calls.append((args,kwargs))
        if kwargs.get('data')==b'metadata':
            state['metadata']+=1
            return b'drift' if state['fault']=='source_drift' and state['metadata']==2 else b'source metadata'
        if 'pg_dumpall' in args:return b'roles'
        if 'pg_dump' in args:return b'archive'
        return b''
    monkeypatch.setattr(budget,'command',command)
    def prepare(*args,**kwargs):
        if state['fault']:raise control.RestoreUnavailable(state['fault'])
        return SimpleNamespace(roles=SimpleNamespace(bootstrap='original_bootstrap',sql=b'persistent role program'),
            tools={'bound':True},script=b'original stream',index=object(),plan=object())
    monkeypatch.setattr(control,'prepare_archive',prepare)
    monkeypatch.setattr(control,'bind_tools',lambda *a,**kw:{'bound':True})
    monkeypatch.setattr(control,'source_fixed_snapshot',lambda *a,**kw:b'fixed snapshot')
    monkeypatch.setattr(control,'stream_restore',lambda *a,**kw:({'original':'complete'},{}))
    def receipt(**kwargs):
        state['receipt']=kwargs
        return '{"schema":"fixture-safe-receipt"}'
    monkeypatch.setattr(control,'construction_receipt',receipt)
    class Owner:
        def __init__(self,nonce,*args):
            owners.append(self);self.cleaned=False;self.directory=tmp_path
            self.names={k:'rf193_identity_'+k+'_'+nonce for k in ('network','volume','init','database','auth')}
            self.names['database']='rf193_identity_db_'+nonce
        def acquire(self,kind,args,**kw):
            command(args,**kw);return {'init':'d'*64,'database':'e'*64}.get(kind,'f'*64)
        def cleanup(self):
            self.cleaned=True
            if state['cleanupFault']:raise control.RestoreUnavailable('cleanup_uncertain')
    monkeypatch.setattr(control,'ResourceOwner',Owner)
    monkeypatch.setattr(identity,'query',lambda c,s,**kw:b'supabase_admin\n' if s=='select current_user;' else role_raw)
    preparations=[]
    monkeypatch.setattr(identity,'prepare_new_target_database',lambda *a,**kw:preparations.append((a,kw)))
    return budget,state,calls,owners,preparations


@pytest.mark.parametrize('fault',['archive_profile','suffix_profile','role_profile','deadline','source_drift'])
def test_failed_preparation_allocates_nothing_and_preserves_source_postcheck(repaired_model,tmp_path,fault,capsys):
    budget,state,calls,owners,_=repaired_model;state['fault']=fault
    with pytest.raises(control.RestoreUnavailable) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('unadmitted yield')
    assert caught.value.reason==fault and owners==[]
    assert not any(args[1] in ('create','network','volume') for args,_ in calls)
    assert state['postchecks']>=2 and state['metadata']==3
    output=capsys.readouterr().out
    assert output.startswith('owned_identity_restore_profile repair_profile_not_legacy_replay\n')
    assert state['receipt']['cleanup_complete'] and state['receipt']['source_postcheck']
    assert not (tmp_path/'legacy-package-must-not-exist').exists()


@pytest.mark.parametrize('cleanup_fault',[False,True])
def test_strict_repaired_mismatch_never_publishes_old_replay_or_masks_original(repaired_model,tmp_path,cleanup_fault):
    budget,state,calls,owners,preparations=repaired_model;state['cleanupFault']=cleanup_fault
    with pytest.raises(ValueError,match='Independent recovery roles, ownership, ACLs or Auth rows differ; components=catalog'):
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('strict mismatch waived')
    assert len(owners)==1 and owners[0].cleaned and state['metadata']==3
    role_calls=[(args,kwargs) for args,kwargs in calls if kwargs.get('data')==b'persistent role program']
    assert len(role_calls)==1 and role_calls[0][0][role_calls[0][0].index('-U')+1]=='original_bootstrap'
    assert len(preparations)==1 and preparations[0][0][-1]=='original_bootstrap'
    assert preparations[0][1]['construction'] is True
    assert state['postchecks']==3 and not (tmp_path/'legacy-package-must-not-exist').exists()
    assert state['receipt']['cleanup_complete'] is (not cleanup_fault)
    assert state['receipt']['source_postcheck'] and not state['receipt']['business_complete']


def test_legacy_ssh_profile_refuses_before_source_or_target_work(repaired_model,tmp_path,monkeypatch):
    budget,state,calls,owners,_=repaired_model
    monkeypatch.setenv('TALLI_RF_RESTORE_SSH_CONFIG','/fixture/legacy-ssh')
    with pytest.raises(control.RestoreUnavailable) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('SSH profile admitted')
    assert caught.value.reason=='source_binding' and not calls and not owners
    assert state['postchecks']==0


@pytest.mark.parametrize('remaining',[100,4])
def test_final_fingerprints_share_ten_seconds_clipped_to_construction(repaired_model,tmp_path,monkeypatch,remaining):
    budget,state,calls,owners,_=repaired_model
    streamed=[]
    def stream(*args,**kw):
        now=time.monotonic();budget.end=now+remaining;streamed.append(now)
        return {'original':'complete'},{}
    monkeypatch.setattr(control,'stream_restore',stream)
    original=identity.fingerprint
    def fingerprint(container,**kwargs):
        if container!=DB['Id']:
            for i in range(4):kwargs['checked_call'](['strict-probe',str(i)])
        return original(container,**kwargs)
    monkeypatch.setattr(identity,'fingerprint',fingerprint)
    with pytest.raises(ValueError,match='components=catalog'):
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('strict mismatch waived')
    strict=[kw['end'] for args,kw in calls if args[0]=='strict-probe']
    assert len(strict)==4 and len(set(strict))==1
    assert streamed[0] < strict[0] <= streamed[0]+min(10.1,remaining)


def test_constructed_context_yields_same_budget_then_cleans_and_checks_source(repaired_model,tmp_path,monkeypatch):
    budget,state,calls,owners,_=repaired_model;state['recoverPass']=True
    (tmp_path/'supabase').mkdir()
    (tmp_path/'supabase/config.toml').write_text('project_id="fixture"\n')
    monkeypatch.setattr(identity,'loopback_port',lambda *args:19001)
    monkeypatch.setattr(identity,'forwarded_ports',lambda *args:nullcontext())
    monkeypatch.setattr(identity,'auth_gateway',lambda *args,**kw:nullcontext('http://127.0.0.1:19002'))
    monkeypatch.setattr(identity,'verify_target_session',lambda *args,**kw:None)
    monkeypatch.setattr(identity,'verify_target_auth',lambda *args,**kw:None)
    monkeypatch.setattr(identity.httpx,'Client',lambda **kw:nullcontext(
        SimpleNamespace(get=lambda *a,**kw:SimpleNamespace(status_code=200))))
    boundary=SimpleNamespace(inspect_container=lambda *args,**kw:{'Config':{'Env':['SERVICE_KEY=fixture-key']}})
    with identity.restored_identity(SOURCE_URL,tmp_path,boundary,budget=budget) as recovered:
        assert budget.phase=='actors' and recovered.budget is budget
        assert recovered.proof['independentClusterRestored']
        assert (tmp_path/'auth.env').exists()
    assert budget.phase=='source_post' and owners[0].cleaned
    assert not (tmp_path/'auth.env').exists()
    receipt=state['receipt']
    assert receipt['before']==receipt['recovered']
    assert receipt['cleanup_complete'] and receipt['source_postcheck'] and receipt['business_complete']
