"""Construction uses the entry deadline and fresh emitter facts."""
import hashlib
import json
import signal
import sys
import time
from types import SimpleNamespace

import pytest

from test_rf1086_restore_index import construction
from test_rf1086_s0_control import children
import rf1086_restore_control as control


def test_expired_entry_clock_cannot_be_restarted_at_identity_or_command(monkeypatch,children):
    monkeypatch.setattr(control.time,'monotonic',lambda:1000)
    budget=control.RecoveryBudget(800)
    with pytest.raises(control.RestoreUnavailable,match='restore_construction_unavailable'):
        budget.command([sys.executable,'-c','raise AssertionError()'])
    assert children==[] and budget.end==915


def test_cumulative_phases_never_reset_the_original_clock(monkeypatch):
    clock=[1000.0];monkeypatch.setattr(control.time,'monotonic',lambda:clock[0])
    budget=control.RecoveryBudget(1000)
    for phase,endpoint in control.PHASES.items():
        clock[0]+=1;budget.enter(phase)
        assert budget.end==min(1000+endpoint,clock[0]+control.PHASE_MAX.get(phase,115))
        end=budget.end;clock[0]+=.1;budget.enter(phase);assert budget.end==end
    with pytest.raises(control.RestoreUnavailable):budget.enter('construction')


def test_preallocation_gate_requires_all_seventy_seconds(monkeypatch):
    clock=[1000.0];monkeypatch.setattr(control.time,'monotonic',lambda:clock[0])
    budget=control.RecoveryBudget(1000)
    clock[0]=1045;budget.before_target()
    clock[0]=1045.000001
    with pytest.raises(control.RestoreUnavailable) as caught:budget.before_target()
    assert caught.value.reason=='deadline'


def test_owned_command_caps_private_output_and_reaps_on_limit(children):
    budget=control.RecoveryBudget(time.monotonic())
    with pytest.raises(control.RestoreUnavailable) as caught:
        budget.command([sys.executable,'-c','import os;os.write(1,b"x"*2000)'],cap=100)
    assert caught.value.reason=='limit' and len(children)==1 and children[0].returncode is not None
    assert all(s.process is None for s in budget.context.owner.slots)


def test_owned_command_keeps_fatal_cancellation_identity(monkeypatch,children):
    budget=control.RecoveryBudget(time.monotonic()); primary=KeyboardInterrupt()
    original=control.commands.os.set_blocking
    def cancel(*args):original(*args);raise primary
    monkeypatch.setattr(control.commands.os,'set_blocking',cancel)
    with pytest.raises(KeyboardInterrupt) as caught:
        budget.command([sys.executable,'-c','import time;time.sleep(30)'])
    assert caught.value is primary and budget.context.owner.primary is primary
    assert all(c.returncode is not None for c in children)


def test_offline_generation_is_once_fifo_only_without_database_arguments():
    calls=[]
    class Budget:
        def command(self,args,**kwargs):calls.append((args,kwargs));return b'sql'
    archive=b'archive'
    assert control.generate_sql('a'*64,archive,budget=Budget())==b'sql'
    assert len(calls)==1
    args,kw=calls[0]
    assert args==['docker','exec','-i','a'*64,'sh','-c',control.OFFLINE_RESTORE]
    assert '--dbname' not in args[-1] and '--file=-' in args[-1]
    assert args[-1].startswith('test -p /proc/self/fd/0 && exec pg_restore ')
    assert kw['data'] is archive and kw['cap']==128*1024**2


def test_schedule_uses_actual_order_even_when_net_precedes_graphql():
    index=construction();schedule=control.construction_schedule(index,deadline=time.monotonic()+2)
    assert [point for point,_ in schedule.points if point[0]=='cut']==[('cut',1),('cut',0),('cut',2)]
    assert schedule.points[-2:]==((('cut',2),index.pre_acl['cut']),(('post',2),index.pre_acl['cut']))
    assert len(schedule.points)==8
    for i,(point,offset) in enumerate(schedule.points):
        if point[0]=='cut':assert schedule.points[i+1]==(('post',point[1]),offset)


def test_ninth_probe_is_distinct_from_legacy_causal_wire_and_bounded():
    p,q=control.probe('c'*32,8)
    assert b'R1P/' in p and b'/08/' in p and b'R1B/' in q
    assert b'S0' not in p+q and b'C1' not in p+q
    with pytest.raises(control.RestoreUnavailable):control.probe('c'*32,9)
    assert b'R1O/' in control.witness_request('c'*32,8,'after',100)


def test_bounded_hash_reports_only_complete_input():
    value=b'x'*70000
    assert control.bounded_hash(value,deadline=time.monotonic()+2,cap=70000)=={
        'bytes':len(value),'sha256':hashlib.sha256(value).hexdigest()}
    with pytest.raises(control.RestoreUnavailable):control.bounded_hash(value,deadline=time.monotonic()-1,cap=70000)
    with pytest.raises(control.RestoreUnavailable):control.bounded_hash(value,deadline=time.monotonic()+2,cap=69999)


def test_private_local_input_reader_rejects_empty_and_oversized_files(tmp_path):
    source=tmp_path/'input';source.write_bytes(b'12345')
    assert control.bounded_file(source,cap=5)==b'12345'
    with pytest.raises(control.RestoreUnavailable):control.bounded_file(source,cap=4)
    source.write_bytes(b'')
    with pytest.raises(control.RestoreUnavailable):control.bounded_file(source,cap=5)


def test_unwind_preserves_initiating_exception_and_defers_repeat_signal(children):
    budget=control.RecoveryBudget(time.monotonic());primary=KeyboardInterrupt();original=budget.context
    with pytest.raises(KeyboardInterrupt) as caught:
        try:raise primary
        finally:
            with control.unwind_scope(budget):
                budget.enter('cleanup')
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
                assert budget.command([sys.executable,'-c','print("cleaned")'])==b'cleaned\n'
                budget.enter('source_post')
                assert budget.command([sys.executable,'-c','print("checked")'])==b'checked\n'
    assert caught.value is primary and budget.context is original
    assert original.owner.cancelled and all(c.returncode==0 for c in children)


def test_unwind_failure_does_not_replace_the_original_error():
    budget=control.RecoveryBudget(time.monotonic());primary=ValueError('initiating')
    with pytest.raises(ValueError) as caught:
        try:raise primary
        finally:
            with control.unwind_scope(budget):raise control.RestoreUnavailable('cleanup_uncertain')
    assert caught.value is primary and budget.context.owner.uncertain


@pytest.fixture
def resource_model(tmp_path,monkeypatch):
    directory=tmp_path/'owner';directory.mkdir()
    monkeypatch.setattr(control.tempfile,'mkdtemp',lambda **kw:str(directory))
    class Model:
        def __init__(self):
            self.values={};self.calls=[];self.fail_create=False;self.fail_before_create=False
            self.context=SimpleNamespace(owner=control.pipes.ChildOwner())
        def command(self,args,**kw):
            self.calls.append(args)
            if args[2]=='create':
                name=args[-1]
                if self.fail_before_create:raise control.RestoreUnavailable('child_failure')
                self.values[name]={'Name':name,'Labels':{control.ResourceOwner.label:'a'*32},'Internal':True,'Id':'b'*64}
                assert json.loads((directory/'owner.json').read_bytes())['attempted']==['network']
                if self.fail_create:raise control.RestoreUnavailable('child_failure')
                return b'b'*64+b'\n'
            if args[2]=='ls':
                if args[-1].startswith('id='):
                    return b''.join((json.dumps(k)+'\n').encode() for k,v in self.values.items() if v['Id']==args[-1][3:])
                name=args[-1].removeprefix('name=')
                return (json.dumps(name)+'\n').encode() if name in self.values else b''
            if args[2]=='inspect':return json.dumps([self.values[args[-1]]]).encode()
            if args[2]=='rm':
                key=next(k for k,v in self.values.items() if v['Id']==args[-1]);del self.values[key];return b''
            raise AssertionError('unexpected model command')
    return Model(),directory


def test_failed_acquisition_is_recorded_reconciled_and_removed(resource_model):
    model,directory=resource_model;model.fail_create=True
    owner=control.ResourceOwner('a'*32,'c'*64,'sha256:'+'d'*64,'sha256:'+'e'*64,model)
    assert owner.record.stat().st_mode&0o777==0o600
    with pytest.raises(control.RestoreUnavailable):
        owner.acquire('network',['docker','network','create',owner.names['network']],end=time.monotonic()+2)
    assert owner.record.exists() and model.values
    owner.cleanup()
    assert not model.values and not directory.exists()


def test_absence_after_unseen_failed_acquisition_does_not_erase_owner_record(resource_model):
    model,_=resource_model;model.fail_before_create=True
    owner=control.ResourceOwner('a'*32,'c'*64,'sha256:'+'d'*64,'sha256:'+'e'*64,model)
    with pytest.raises(control.RestoreUnavailable):
        owner.acquire('network',['docker','network','create',owner.names['network']],end=time.monotonic()+2)
    with pytest.raises(control.RestoreUnavailable) as caught:owner.cleanup()
    assert caught.value.reason=='cleanup_uncertain' and owner.record.exists()
    assert not model.values and not any(args[2]=='rm' for args in model.calls)


def test_foreign_label_or_replaced_identity_is_never_removed(resource_model):
    model,directory=resource_model
    owner=control.ResourceOwner('a'*32,'c'*64,'sha256:'+'d'*64,'sha256:'+'e'*64,model)
    owner.acquire('network',['docker','network','create',owner.names['network']],end=time.monotonic()+2)
    model.values[owner.names['network']]['Labels'][owner.label]='foreign'
    with pytest.raises(control.RestoreUnavailable):owner.cleanup()
    assert owner.record.exists() and not any(args[2]=='rm' for args in model.calls)


def test_renamed_known_resource_does_not_count_as_removed(resource_model):
    model,_=resource_model
    owner=control.ResourceOwner('a'*32,'c'*64,'sha256:'+'d'*64,'sha256:'+'e'*64,model)
    owner.acquire('network',['docker','network','create',owner.names['network']],end=time.monotonic()+2)
    resource=model.values.pop(owner.names['network']);resource['Name']='renamed';model.values['renamed']=resource
    with pytest.raises(control.RestoreUnavailable):owner.cleanup()
    assert owner.record.exists() and not any(args[2]=='rm' for args in model.calls)


def test_uncertain_child_acquisition_keeps_owner_record_even_after_absence(resource_model):
    model,_=resource_model
    owner=control.ResourceOwner('a'*32,'c'*64,'sha256:'+'d'*64,'sha256:'+'e'*64,model)
    model.context.owner.uncertain=True
    with pytest.raises(control.RestoreUnavailable):owner.cleanup()
    assert owner.record.exists()


def safe_receipt_input():
    def binding(n):return {'bytes':n,'sha256':'a'*64}
    io={'stdoutBytes':1,'stderrBytes':0,'stdoutEnd':'eof','stderrEnd':'eof','exitCode':0,'reap':'waited'}
    counts=dict.fromkeys(('objects','candidates','archiveOnly','unmodeled','statements','defaultAcls'),0)
    plan=SimpleNamespace(counts=counts,cuts={'Is':100,'In':200},pre_acl=300,
        binding={'profile':'a'*64,**{k:binding(1) for k in ('source','fixedSnapshot','catalogObservation','roleObservation','archive','script','index','supplement')}})
    prepared=SimpleNamespace(plan=plan,code_binding={'rf1086_s0_control.py':binding(100)},
        tools={k:{'version':'17.6','sha256':'a'*64} for k in ('pg_restore','psql')},
        archive_binding=binding(100),roles_binding=binding(100),index=SimpleNamespace(core=SimpleNamespace(script=binding(500))))
    delivery={'exchanges':[{'observer':dict(io),'catalog':'PRIVATE ACL/ROLE/SQL',
        'witnesses':['PRIVATE SESSION']} for _ in range(8)],
        'delivery':{'original':binding(500),'probes':binding(200),'frames':[8,8],'writer':dict(io),
            'mutation':{**binding(3),'exchanges':[{'point':['cut',i],**binding(1)} for i in range(3)]}}}
    fingerprints=dict.fromkeys(('roles','catalog','auth','companyMemberships'),'b'*64)
    return dict(budget=control.RecoveryBudget(time.monotonic()),prepared=prepared,delivery=delivery,
        mutations={k:SimpleNamespace(sql=b'PRIVATE SQL',applied=0,noop=1) for k in ('Is','In','acl')},
        source='c'*64,target='d'*64,image='sha256:'+'e'*64,before=fingerprints,recovered=fingerprints,
        cleanup_complete=True,source_postcheck=True,business_complete=False)


def test_safe_receipt_contains_no_catalog_sql_session_or_raw_resource_identity():
    args=safe_receipt_input();raw=control.construction_receipt(**args);value=json.loads(raw)
    assert len(raw)<16384 and 'PRIVATE' not in raw and args['source'] not in raw and args['target'] not in raw
    assert value['status']=='constructed' and value['businessComplete'] is False
    assert value['outerBusinessPostchecks'] is None and value['cleanupComplete'] is True


def test_safe_receipt_never_claims_construction_if_cleanup_is_unproved():
    args=safe_receipt_input();args.update(cleanup_complete=False,reason='cleanup_uncertain')
    value=json.loads(control.construction_receipt(**args))
    assert value['status']=='unavailable' and value['reason']=='cleanup_uncertain'


def test_safe_receipt_rejects_unmodeled_fields_in_observer_receipt():
    args=safe_receipt_input();args['delivery']['exchanges'][0]['observer']['raw']='PRIVATE'
    with pytest.raises(control.RestoreUnavailable):control.construction_receipt(**args)
