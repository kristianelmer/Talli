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


def test_pre_target_diagnostic_keeps_original_denial_and_closed_location():
    budget = control.RecoveryBudget(time.monotonic())
    diagnostic = control.PreTargetDiagnostic(budget)
    primary = control.ledger.Unavailable('profile')
    walk = control.ledger.Budget(budget.end)
    walk.phase('metadata'); walk.phase('preparation')
    with pytest.raises(control.ledger.Unavailable) as caught:
        with diagnostic.operation('restore_ledger', walk=walk):
            raise primary
    assert caught.value is primary
    result = diagnostic.failure
    assert result['step'] == 'restore_ledger' and result['reason'] == 'profile'
    assert result['ledger']['stage'] == 'preparation'
    assert result['location']['module'] == 'control'  # The active context's yield, not this test path.
    assert control.validate_pre_target_diagnostic(result) is result


def test_pre_target_diagnostic_does_not_capture_cancel_or_inactive_failure():
    diagnostic = control.PreTargetDiagnostic(control.RecoveryBudget(time.monotonic()))
    primary = KeyboardInterrupt('private cancellation')
    with pytest.raises(KeyboardInterrupt) as caught:
        with diagnostic.operation('archive_list'):
            raise primary
    assert caught.value is primary and diagnostic.failure is None
    diagnostic.disable()
    with pytest.raises(ValueError):
        with diagnostic.operation('target_admission'):
            raise ValueError('private later failure')
    assert diagnostic.failure is None


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
    assert kw.get('allow_early_stdin_close', False) is False


@pytest.mark.parametrize('change', ['uppercase_source','short_source','nonhex_source','source_type',
    'no_list','extra_arg','different_binary','shell','tuple','no_data','archive','integer','null'])
def test_listing_option_exact_argv_and_mode_reject_before_command(monkeypatch, change):
    budget = control.RecoveryBudget(time.monotonic())
    args = ['docker','exec','-i','a'*64,'pg_restore','--list','--verbose']
    options = {'data':b'fixture','allow_early_stdin_close':True}
    if change == 'uppercase_source': args[3] = 'A'*64
    elif change == 'short_source': args[3] = 'a'*63
    elif change == 'nonhex_source': args[3] = 'g'*64
    elif change == 'source_type': args[3] = 12
    elif change == 'no_list': args[5] = '--file=-'
    elif change == 'extra_arg': args.append('--dbname=postgres')
    elif change == 'different_binary': args[4] = 'psql'
    elif change == 'shell': args[4:] = ['sh','-c','pg_restore --list --verbose']
    elif change == 'tuple': args = tuple(args)
    elif change == 'no_data': options['data'] = None
    elif change == 'archive': options['archive'] = object()
    else: options['allow_early_stdin_close'] = {'integer':1,'null':None}[change]
    monkeypatch.setattr(control.commands,'_command',lambda *a,**kw:pytest.fail('invalid command reached helper'))
    with pytest.raises(control.RestoreUnavailable): budget.command(args,**options)


def test_listing_option_preserves_shared_endpoints_caps_and_other_defaults(monkeypatch):
    monkeypatch.setattr(control.time,'monotonic',lambda:1000.0)
    budget = control.RecoveryBudget(1000.0); calls = []
    def command(args, deadline, **kw): calls.append((args,deadline,kw)); return b'generated'
    monkeypatch.setattr(control.commands,'_command',command)
    args = ['docker','exec','-i','a'*64,'pg_restore','--list','--verbose']
    payload = b'fixture'
    assert budget.command(args,data=payload,cap=2*1024**2,end=budget.end-70,
                          allow_early_stdin_close=True) == b'generated'
    _,work,options = calls[0]
    assert work == 1043 and options['reap_deadline'] == 1045
    assert options['stdout_cap'] == 2*1024**2 and options['data'] is payload
    assert options['child_owner'] is budget.context.owner and options['allow_early_stdin_close'] is True
    control.generate_sql('a'*64,payload,budget=budget,end=budget.end-70)
    budget.checked(['generated-command'],input=payload)
    assert all(call[2]['allow_early_stdin_close'] is False for call in calls[1:])
    assert budget.phase == 'construction' and budget.end == 1115


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


_OWNED_HBA_POLICY = (
    b'local all all trust\n'
    b'host all all 127.0.0.1/32 scram-sha-256\n'
    b'host all all ::1/128 scram-sha-256\n'
    b'local replication all trust\n'
    b'host replication all 127.0.0.1/32 scram-sha-256\n'
    b'host replication all ::1/128 scram-sha-256\n'
    b'host postgres supabase_auth_admin 172.28.0.0/24 scram-sha-256\n'
    b'host postgres postgres 172.28.0.1/32 scram-sha-256\n'
    b'host postgres talli_ledger_backend 172.28.0.1/32 scram-sha-256\n')


@pytest.fixture
def hba_owner(resource_model, admission_io, monkeypatch):
    """Real constructor, registration, inspect/fsync and cleanup; no daemon/child."""
    model, directory = resource_model
    budget, clock = admission_io
    state = {'reply': b't\n', 'fault': None, 'advance': 0, 'readbacks': []}
    def command(args, **kw):
        budget.remaining(end=kw.get('end'))
        if args[:3] == ['docker', 'exec', '-i']:
            state['readbacks'].append((args, kw))
            if state['fault'] is not None: raise state['fault']
            clock[0] += state['advance']
            return state['reply']  # Whole-scope post-yield check must catch late return.
        return model.command(args, **kw)
    monkeypatch.setattr(budget, 'command', command)
    owner = control.ResourceOwner('a'*32, 'c'*64, 'sha256:'+'d'*64, 'sha256:'+'e'*64, budget)
    owner.acquire('network', ['docker','network','create',owner.names['network']], end=1005.)
    network = model.values[owner.names['network']]
    network.update(Driver='bridge', Scope='local', EnableIPv6=False,
        IPAM={'Config':[{'Subnet':'172.28.0.0/24','Gateway':'172.28.0.1'}]}, Containers={})
    return owner, network, model, directory, clock, state


def test_owned_hba_binds_once_to_real_registered_empty_bridge(hba_owner):
    owner, _, model, directory, _, _ = hba_owner
    old_keys = set(json.loads(owner.record.read_bytes()))
    assert owner._hba_commitment is None
    assert owner.bind_hba(end=1005.) == _OWNED_HBA_POLICY
    assert type(owner._hba_commitment) is tuple
    assert owner._hba_commitment == ('b'*64,'172.28.0.0/24','172.28.0.1',_OWNED_HBA_POLICY)
    assert len(_OWNED_HBA_POLICY) <= 4096 and owner.attempted == ['network']
    assert set(json.loads(owner.record.read_bytes())) == old_keys
    assert owner.record.stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700
    count = len(model.calls)
    with pytest.raises(control.RestoreUnavailable): owner.bind_hba(end=1005.)
    assert len(model.calls) == count
    owner.cleanup()
    assert not model.values and not directory.exists()


@pytest.mark.parametrize('path,value', [
    (('Driver',),'overlay'), (('Scope',),'swarm'), (('EnableIPv6',),True),
    (('Containers',),{'foreign':{}}), (('Containers',),[]),
    (('IPAM','Config'),[{},{}]), (('IPAM','Config'),None),
    (('IPAM','Config',0,'Subnet'),'0.0.0.0/0'),
    (('IPAM','Config',0,'Subnet'),'192.0.2.0/24'),
    (('IPAM','Config',0,'Subnet'),'172.28.0.1/24'),
    (('IPAM','Config',0,'Subnet'),'172.28.0.0/31'),
    (('IPAM','Config',0,'Subnet'),'172.28.0.0/24\nhost all all all trust'),
    (('IPAM','Config',0,'Subnet'),'x'*4097),
    (('IPAM','Config',0,'Subnet'),True), (('IPAM','Config',0,'Subnet'),2887516160),
    (('IPAM','Config',0,'Gateway'),'172.28.0.0'),
    (('IPAM','Config',0,'Gateway'),'172.28.0.255'),
    (('IPAM','Config',0,'Gateway'),'172.29.0.1'),
    (('IPAM','Config',0,'Gateway'),'0172.28.0.1'),
    (('IPAM','Config',0,'Gateway'),'172.28.0.1 '),
    (('IPAM','Config',0,'Gateway'),2887516161),
])
def test_owned_hba_rejects_bad_prestart_profile_and_keeps_cleanup(hba_owner,path,value):
    owner, network, model, directory, _, _ = hba_owner
    target=network
    for key in path[:-1]: target=target[key]
    target[path[-1]]=value
    with pytest.raises(control.RestoreUnavailable): owner.bind_hba(end=1005.)
    assert owner._hba_commitment is None and owner.attempted==['network']
    owner.cleanup()
    assert not model.values and not directory.exists()


@pytest.mark.parametrize('attempted', [[], ['volume'], ['network','volume']])
def test_owned_hba_refuses_unregistered_or_late_binding(hba_owner,attempted):
    owner, _, model, _, _, _ = hba_owner
    owner.attempted=attempted
    count=len(model.calls)
    with pytest.raises(control.RestoreUnavailable): owner.bind_hba(end=1005.)
    assert owner._hba_commitment is None and len(model.calls)==count


def test_owned_hba_missing_network_cannot_create_a_commitment(hba_owner):
    owner, _, model, _, _, _ = hba_owner
    model.values.clear()
    with pytest.raises(control.RestoreUnavailable): owner.bind_hba(end=1005.)
    assert owner._hba_commitment is None


def test_owned_hba_record_and_policy_work_cannot_outlive_setup_end(hba_owner,monkeypatch):
    owner, _, model, directory, clock, _=hba_owner
    record=owner._record
    def late_record():
        record();clock[0]=1005.01
    monkeypatch.setattr(owner,'_record',late_record)
    with pytest.raises(control.RestoreUnavailable) as caught:owner.bind_hba(end=1005.)
    assert caught.value.reason=='deadline' and owner.attempted==['network']
    monkeypatch.setattr(owner,'_record',record)
    owner.budget.enter('cleanup');owner.cleanup()
    assert not model.values and not directory.exists()


@pytest.mark.parametrize('fault', ['record','inspect','expired'])
def test_owned_hba_binding_failure_preserves_identity_and_registered_cleanup(hba_owner,monkeypatch,fault):
    owner, _, model, directory, clock, _ = hba_owner
    primary=KeyboardInterrupt('generated acquisition cancellation')
    original = owner._record if fault=='record' else owner.inspect
    if fault=='expired':clock[0]=1005.01
    else:
        def fail(*args,**kw):raise primary
        monkeypatch.setattr(owner, '_record' if fault=='record' else 'inspect', fail)
    with pytest.raises(control.RestoreUnavailable if fault=='expired' else KeyboardInterrupt) as caught:
        owner.bind_hba(end=1005.)
    if fault!='expired':
        assert caught.value is primary
        monkeypatch.setattr(owner, '_record' if fault=='record' else 'inspect', original)
    else:assert caught.value.reason=='deadline'
    assert owner._hba_commitment is None
    owner.budget.enter('cleanup');owner.cleanup()
    assert not model.values and not directory.exists()


def _hba_host_method(policy, database, role, address):
    """Independent finite evaluator for generated literal host rules, not a PG probe."""
    from ipaddress import ip_address, ip_network
    peer=ip_address(address)
    for line in policy.decode('ascii').splitlines():
        parts=line.split()
        if parts[0]!='host':continue
        _, db, user, cidr, method=parts
        if (db in ('all',database) and user in ('all',role)
                and peer in ip_network(cidr)):
            return method
    return None


@pytest.mark.parametrize('database,role,address,allowed', [
    ('postgres','supabase_auth_admin','172.28.0.3',True),
    ('postgres','postgres','172.28.0.1',True),
    ('postgres','talli_ledger_backend','172.28.0.1',True),
    ('postgres','postgres','172.28.0.3',False),
    ('postgres','talli_ledger_backend','172.28.0.3',False),
    ('postgres','talli_company_access_backend','172.28.0.1',False),
    ('postgres','unknown','172.28.0.1',False),
    ('other','supabase_auth_admin','172.28.0.3',False),
    ('other','postgres','172.28.0.1',False),
    ('other','talli_ledger_backend','172.28.0.1',False),
    ('postgres','supabase_auth_admin','172.29.0.3',False),
    ('postgres','postgres','203.0.113.1',False),
    ('postgres','postgres','fd00::1',False),
])
def test_owned_hba_finite_remote_policy_has_only_three_role_scopes(hba_owner,database,role,address,allowed):
    owner,*_=hba_owner
    method=_hba_host_method(owner.bind_hba(end=1005.),database,role,address)
    assert method==('scram-sha-256' if allowed else None)


def test_owned_hba_target_readback_has_fixed_path_operator_cap_and_original_end(hba_owner):
    owner, _, _, _, _, state=hba_owner
    owner.bind_hba(end=1005.);owner.identities['database']='f'*64
    original_end=owner.budget.end
    owner.verify_hba(end=1007.)
    args,kw=state['readbacks'][0]
    assert args==['docker','exec','-i','f'*64,'psql','-U','supabase_admin','-h','/tmp',
                  '--dbname','postgres','-XqAt','-v','ON_ERROR_STOP=1']
    expected=("select current_setting('hba_file') = '/tmp/rf-recovery/pg_hba.owned.conf' and "
        "pg_read_binary_file('/tmp/rf-recovery/pg_hba.owned.conf',0,4097) = decode('"+
        _OWNED_HBA_POLICY.hex()+"','hex');\n").encode('ascii')
    assert kw=={'data':expected,'cap':32,'end':1007.}
    assert owner.budget.end==original_end and owner.budget.phase=='construction'


@pytest.mark.parametrize('reply',[b'',b'f\n',b't',b't\n\n',b't\nf\n',b' t\n',b't\r\n',b't\n'+b'x'*32])
def test_owned_hba_readback_refuses_any_nonexact_boolean(hba_owner,reply):
    owner, _, _, _, _, state=hba_owner
    owner.bind_hba(end=1005.);owner.identities['database']='f'*64
    state['reply']=reply
    with pytest.raises(control.RestoreUnavailable) as caught:owner.verify_hba(end=1007.)
    assert caught.value.reason=='source_binding'


@pytest.mark.parametrize('bad', [None, [], ('b'*64,), ('f'*64,'172.28.0.0/24','172.28.0.1',_OWNED_HBA_POLICY),
    ('b'*64,'172.28.0.0/24','172.28.0.1','not bytes'),
    ('b'*64,'172.28.0.0/24','172.28.0.1',b'x'*4097)])
def test_owned_hba_readback_rejects_missing_or_invalid_commitment_before_command(hba_owner,bad):
    owner, _, _, _, _, state=hba_owner
    owner._hba_commitment=bad;owner.identities['database']='f'*64
    with pytest.raises(control.RestoreUnavailable):owner.verify_hba(end=1007.)
    assert not state['readbacks']


@pytest.mark.parametrize('primary', [KeyboardInterrupt('cancel'),SystemExit(21),
    control.RestoreUnavailable('deadline'),control.RestoreUnavailable('child_failure')])
def test_owned_hba_readback_preserves_command_failure_identity(hba_owner,primary):
    owner, _, _, _, _, state=hba_owner
    owner.bind_hba(end=1005.);owner.identities['database']='f'*64;state['fault']=primary
    with pytest.raises(type(primary)) as caught:owner.verify_hba(end=1007.)
    assert caught.value is primary


@pytest.mark.parametrize('expired_before',[False,True])
def test_owned_hba_readback_cannot_refresh_exhausted_strict_window(hba_owner,expired_before):
    owner, _, _, _, clock, state=hba_owner
    owner.bind_hba(end=1005.);owner.identities['database']='f'*64
    if expired_before:clock[0]=1007.01
    else:state['advance']=7.01
    with pytest.raises(control.RestoreUnavailable) as caught:owner.verify_hba(end=1007.)
    assert caught.value.reason=='deadline'
    assert len(state['readbacks'])==(0 if expired_before else 1)


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


def postconstruction_inputs(*, business=False):
    args=safe_receipt_input();args['business_complete']=business
    names={name+'.py' for name in control.DIAGNOSTIC_MODULES.values()}
    names.update(('rf1086_s0_control.py','rf1086_s0_protocol.py','rf1086_catalog_causal.sql'))
    args['prepared'].code_binding={name:{'bytes':1,'sha256':'a'*64} for name in names}
    args['prepared'].plan.binding['script']=dict(args['prepared'].index.core.script)
    return args


def postconstruction_receipt(*, business=False):
    return control.construction_receipt(**postconstruction_inputs(business=business))


def postconstruction_value(raw, *, edge='before_yield', location=None):
    return {'schema':'rf1086-restore-post-construction-location-v1',
        'constructionSha256':hashlib.sha256(raw.encode('ascii')).hexdigest(),
        'contextEdge':edge,'location':location}


@pytest.mark.parametrize('edge,business',[
    ('before_yield',False),('yield_boundary',False),('yield_boundary',True),('after_yield',True)])
def test_postconstruction_closed_validator_binds_exact_receipt_and_structural_edge(edge,business):
    raw=postconstruction_receipt(business=business)
    value=postconstruction_value(raw,edge=edge)
    assert control.validate_post_construction_location(value,construction_raw=raw) is value
    assert control.validate_post_construction_location(value) is value


@pytest.mark.parametrize('change',[
    lambda v:v.update(schema='other'),lambda v:v.update(raw='PRIVATE'),
    lambda v:v.update(constructionSha256='A'*64),lambda v:v.update(constructionSha256='b'*64),
    lambda v:v.update(contextEdge='caller_entered'),lambda v:v.update(contextEdge=[]),
    lambda v:v.update(contextEdge='after_yield'),lambda v:v.update(location=[]),
    lambda v:v['location'].update(module='private/file.py'),
    lambda v:v['location'].update(module=[]),lambda v:v['location'].update(line=True),
    lambda v:v['location'].update(line=0),lambda v:v['location'].update(line=8193),
    lambda v:v['location'].update(depth=True),lambda v:v['location'].update(depth=3),
    lambda v:v['location'].update(edge='context'),lambda v:v['location'].update(raw='PRIVATE')])
def test_postconstruction_validator_refuses_forged_marker(change):
    raw=postconstruction_receipt()
    value=postconstruction_value(raw,location={'module':'identity','line':600,'depth':0,'edge':'primary'})
    change(value)
    with pytest.raises(ValueError):control.validate_post_construction_location(value,construction_raw=raw)


@pytest.mark.parametrize('change',[
    lambda r:r.update(schema='other'),lambda r:r.update(status='unavailable'),
    lambda r:r.update(reason='internal'),lambda r:r.update(cleanupComplete=False),
    lambda r:r.update(identitySourcePostcheck=False),lambda r:r.update(businessComplete=0),
    lambda r:r.update(outerBusinessPostchecks=True),lambda r:r.update(configurationSha256='a'*64),
    lambda r:r['code'].pop('rf1086_identity_restore.py'),
    lambda r:r['code']['rf1086_identity_restore.py'].update(bytes=True),
    lambda r:r['code']['rf1086_identity_restore.py'].update(bytes=256*1024+1),
    lambda r:r['identities'].update(target=None),
    lambda r:r['fingerprints'].update(target=None),
    lambda r:r['fingerprints']['target'].update(catalog='c'*64),
    lambda r:r['fingerprints']['target'].update(raw='PRIVATE'),
    lambda r:r['bindings']['script'].update(bytes=True),
    lambda r:r['bindings']['archive'].update(bytes=control.MAX_ARCHIVE+1),
    lambda r:r['bindings']['roles'].update(sha256='private'),
    lambda r:r['bindings']['plan'].update(extra='PRIVATE'),
    lambda r:r['bindings']['plan']['index'].update(bytes=True),
    lambda r:r['bindings']['tools']['pg_restore'].update(version='17.5'),
    lambda r:r['bindings']['tools']['psql'].update(sha256='PRIVATE'),
    lambda r:r['counts'].update(objects=True),lambda r:r['counts'].update(raw='PRIVATE'),
    lambda r:r['hooks'].update(acl=1),lambda r:r['hooks'].update(Is=True),
    lambda r:r['mutations']['acl'].update(noop=-1),
    lambda r:r['mutations']['acl'].update(sha256='PRIVATE'),
    lambda r:r['mutations']['Is'].update(bytes=2049),
    lambda r:r['phaseElapsedSeconds'].update(actors=True),
    lambda r:r['phaseElapsedSeconds'].update(unknown=0),
    lambda r:r['phaseElapsedSeconds'].update(actors=float('inf')),
    lambda r:r['bindings']['plan']['script'].update(sha256='c'*64),
    lambda r:r['delivery']['original'].update(sha256='c'*64),
    lambda r:r['delivery']['writer'].update(stdoutEnd='open'),
    lambda r:r['delivery']['writer'].update(stderrEnd='open'),
    lambda r:r['delivery']['writer'].update(exitCode=1),
    lambda r:r['delivery']['writer'].update(exitCode=False),
    lambda r:r['delivery']['writer'].update(reap='poll'),
    lambda r:r['delivery']['writer'].update(stderrBytes=65537),
    lambda r:r['delivery']['probes'].update(bytes=16385),
    lambda r:r['delivery']['mutation']['exchanges'][0].update(point=['cut',True]),
    lambda r:r['delivery']['mutation']['exchanges'][0].update(point=['cut',1]),
    lambda r:r['delivery']['mutation'].update(raw='PRIVATE'),
    lambda r:r['delivery'].update(frames=[8,9]),
    lambda r:r['observers'].pop(),lambda r:r['observers'][0].update(reap='poll')])
def test_postconstruction_refuses_unproved_construction_and_never_writes(change,capsys):
    receipt=json.loads(postconstruction_receipt());change(receipt)
    # Include nonfinite malicious wire input; the production canonical encoder
    # rightly refuses to generate it, so do not use it to build that negative.
    raw=json.dumps(receipt,sort_keys=True,separators=(',',':'))
    value=postconstruction_value(raw)
    with pytest.raises(ValueError):control.validate_post_construction_location(value,construction_raw=raw)
    budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    control.publish_post_construction_location(budget,prepared=postconstruction_inputs()['prepared'],construction_raw=raw,
        primary=ValueError('PRIVATE'),context_edge='before_yield')
    assert capsys.readouterr()==('','')


@pytest.mark.parametrize('raw_change',[
    lambda r:' '+r,lambda r:r[:-1]+',"schema":"rf1086-restore-construction-v1"}',
    lambda r:'x'*16385,lambda r:'\u00e9',lambda r:r.encode('ascii')])
def test_postconstruction_requires_bounded_exact_canonical_ascii(raw_change,capsys):
    raw=raw_change(postconstruction_receipt())
    budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    control.publish_post_construction_location(budget,prepared=postconstruction_inputs()['prepared'],construction_raw=raw,
        primary=ValueError('PRIVATE'),context_edge='before_yield')
    assert capsys.readouterr()==('','')


@pytest.mark.parametrize('primary',[None,KeyboardInterrupt('PRIVATE'),SystemExit('PRIVATE')])
def test_postconstruction_absent_or_fatal_primary_does_not_start_observation(primary,monkeypatch,capsys):
    def forbidden(*a,**kw):pytest.fail('observation attempted')
    monkeypatch.setattr(control,'_post_construction_receipt',forbidden)
    budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    control.publish_post_construction_location(budget,prepared=postconstruction_inputs()['prepared'],construction_raw='unused',
        primary=primary,context_edge='before_yield')
    assert capsys.readouterr()==('','')


@pytest.mark.parametrize('flag',['cancelled','uncertain'])
@pytest.mark.parametrize('unwind',[False,True])
def test_postconstruction_sticky_original_owner_prevents_publication(flag,unwind,monkeypatch,capsys):
    budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    original=budget.context.owner;setattr(original,flag,True)
    if unwind:budget.context.owner=control._UnwindOwner(original,ValueError('PRIVATE'))
    monkeypatch.setattr(control,'_post_construction_receipt',lambda *a:pytest.fail('observed sticky failure'))
    control.publish_post_construction_location(budget,prepared=postconstruction_inputs()['prepared'],construction_raw='unused',
        primary=ValueError('PRIVATE'),context_edge='before_yield')
    assert capsys.readouterr()==('','')


@pytest.mark.parametrize('where',['receipt','location','validation','serialization','write','flush'])
def test_postconstruction_entire_publisher_is_clipped_and_restores_prior_alarm(where,monkeypatch,capsys):
    raw=postconstruction_receipt();budget=control.RecoveryBudget(time.monotonic())
    budget.enter('source_post');budget.end=time.monotonic()+.035
    old_handler=signal.getsignal(signal.SIGALRM);old_timer=signal.getitimer(signal.ITIMER_REAL)
    assert old_timer==(0.0,0.0)
    handler=lambda *a:None
    signal.signal(signal.SIGALRM,handler);signal.setitimer(signal.ITIMER_REAL,2)
    def blocked(*a,**kw):time.sleep(.5);pytest.fail('blocked publisher completed')
    if where in ('receipt','location','validation'):
        name={'receipt':'_post_construction_receipt','location':'_diagnostic_location',
              'validation':'validate_post_construction_location'}[where]
        monkeypatch.setattr(control,name,blocked)
    elif where=='serialization':
        canonical=control.ledger.canonical
        def encode(value):
            if isinstance(value,dict) and value.get('schema')==control.POST_CONSTRUCTION_SCHEMA:blocked()
            return canonical(value)
        monkeypatch.setattr(control.ledger,'canonical',encode)
    else:
        stderr=sys.stderr
        class Writer:
            def write(self,text):
                if where=='write':blocked()
                return stderr.write(text)
            def flush(self):
                if where=='flush':blocked()
                return stderr.flush()
        monkeypatch.setattr(sys,'stderr',Writer())
    end=budget.end;started=time.monotonic()
    try:
        control.publish_post_construction_location(budget,prepared=postconstruction_inputs()['prepared'],construction_raw=raw,
            primary=ValueError('PRIVATE'),context_edge='before_yield')
        assert time.monotonic()-started<.25 and budget.end==end and budget.phase=='source_post'
        assert signal.getsignal(signal.SIGALRM) is handler
        assert 0<signal.getitimer(signal.ITIMER_REAL)[0]<2
        output=capsys.readouterr();assert output.out=='' and 'PRIVATE' not in output.err
        if where!='flush':assert output.err==''
    finally:
        if where in ('write','flush'):monkeypatch.setattr(sys,'stderr',stderr)
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old_handler)


def test_postconstruction_timeout_swallowed_by_classifier_stops_before_validation(monkeypatch,capsys):
    from contextlib import contextmanager
    raw=postconstruction_receipt();budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    real=control.io_deadline;endpoints=[]
    @contextmanager
    def scope(value,*,end):
        endpoints.append(end)
        with real(value,end=end):yield
    monkeypatch.setattr(control,'io_deadline',scope)
    def location(*a):
        # Same ordinary timeout-to-null behavior as the existing classifier.
        try:time.sleep(1)
        except control.RestoreUnavailable:return None
    monkeypatch.setattr(control,'_diagnostic_location',location)
    monkeypatch.setattr(control,'validate_post_construction_location',lambda *a,**kw:pytest.fail('validated after expiry'))
    start=time.monotonic();parent_end=budget.end
    control.publish_post_construction_location(budget,prepared=postconstruction_inputs()['prepared'],construction_raw=raw,
        primary=ValueError('PRIVATE'),context_edge='before_yield')
    assert .2<time.monotonic()-start<.6
    assert start<endpoints[0]<=start+.251 and budget.end==parent_end
    assert capsys.readouterr()==('','') and signal.getitimer(signal.ITIMER_REAL)[0]==0


@pytest.mark.parametrize('secondary',[RuntimeError('PRIVATE'),KeyboardInterrupt('PRIVATE'),SystemExit('PRIVATE')])
def test_postconstruction_secondary_fault_keeps_initiating_primary(secondary,monkeypatch,capsys):
    raw=postconstruction_receipt();budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    primary=ValueError('ORIGINAL PRIVATE')
    def fail(*a,**kw):raise secondary
    monkeypatch.setattr(control,'validate_post_construction_location',fail)
    control.publish_post_construction_location(budget,prepared=postconstruction_inputs()['prepared'],construction_raw=raw,
        primary=primary,context_edge='before_yield')
    if not isinstance(secondary,Exception):
        assert budget.context.owner.cancelled and budget.context.owner.primary is primary
        with pytest.raises(ValueError) as caught:budget.context.raise_if_fatal()
        assert caught.value is primary
    assert capsys.readouterr()==('','')


def test_postconstruction_closed_marker_preserves_only_structural_suppressed_context(monkeypatch,capsys):
    namespace={}
    exec(compile('def fail():\n secret="PRIVATE locals"\n raise ValueError("PRIVATE inner")\n',
                 str(control.Path(control.__file__).with_name('rf1086_identity_restore.py')),'exec'),namespace)
    try:
        try:namespace['fail']()
        except ValueError:raise RuntimeError('PRIVATE outer') from None
    except RuntimeError as error:primary=error
    raw=postconstruction_receipt();budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    control.publish_post_construction_location(budget,prepared=postconstruction_inputs()['prepared'],construction_raw=raw,primary=primary,context_edge='yield_boundary')
    output=capsys.readouterr();assert output.out=='' and 'PRIVATE' not in output.err
    value=json.loads(output.err[len(control.POST_CONSTRUCTION_PREFIX):])
    assert value['location']=={'module':'identity','line':3,'depth':1,'edge':'suppressed_context'}
    assert control.validate_post_construction_location(value,construction_raw=raw) is value


@pytest.mark.parametrize('fault',['unknown_trace','expired','wrong_phase','marker_cap'])
def test_postconstruction_unknown_location_is_null_but_ineligible_publication_is_absent(fault,monkeypatch,capsys):
    raw=postconstruction_receipt();budget=control.RecoveryBudget(time.monotonic())
    if fault!='wrong_phase':budget.enter('source_post')
    if fault=='expired':budget.end=time.monotonic()-1
    if fault=='marker_cap':monkeypatch.setattr(control,'POST_CONSTRUCTION_CAP',100)
    try:raise ValueError('PRIVATE test-only trace')
    except ValueError as error:primary=error
    control.publish_post_construction_location(budget,prepared=postconstruction_inputs()['prepared'],construction_raw=raw,
        primary=primary,context_edge='before_yield')
    output=capsys.readouterr();assert output.out=='' and 'PRIVATE' not in output.err
    if fault=='unknown_trace':
        value=json.loads(output.err[len(control.POST_CONSTRUCTION_PREFIX):])
        assert value['location'] is None
    else:assert output.err==''


def test_postconstruction_publication_has_post_yield_check_without_new_time(monkeypatch,capsys):
    raw=postconstruction_receipt();clock=[time.monotonic()]
    monkeypatch.setattr(control.time,'monotonic',lambda:clock[0])
    budget=control.RecoveryBudget(clock[0]);budget.enter('source_post')
    end=budget.end;stderr=sys.stderr;checks=[];remaining=budget.remaining
    def check(**kwargs):
        checks.append((clock[0],kwargs))
        return remaining(**kwargs)
    monkeypatch.setattr(budget,'remaining',check)
    class Writer:
        def write(self,text):return stderr.write(text)
        def flush(self):clock[0]+=.3
    monkeypatch.setattr(sys,'stderr',Writer())
    control.publish_post_construction_location(budget,prepared=postconstruction_inputs()['prepared'],construction_raw=raw,
        primary=ValueError('PRIVATE'),context_edge='before_yield')
    monkeypatch.setattr(sys,'stderr',stderr)
    assert checks[-1][1]['end']<checks[-1][0] and budget.end==end
    assert budget.phase=='source_post' and signal.getitimer(signal.ITIMER_REAL)[0]==0
    # A completed write cannot be withdrawn if a later flush/post-yield check
    # fails; the marker itself makes no publication/completion success claim.
    assert 'PRIVATE' not in capsys.readouterr().err


@pytest.mark.parametrize('secondary',[RuntimeError('PRIVATE'),KeyboardInterrupt('PRIVATE'),SystemExit('PRIVATE')])
def test_postconstruction_handler_restoration_uncertainty_keeps_original(secondary,monkeypatch,capsys):
    raw=postconstruction_receipt();budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    primary=ValueError('ORIGINAL PRIVATE');real_signal=signal.signal
    original={number:signal.getsignal(number) for number in (signal.SIGINT,signal.SIGTERM,signal.SIGALRM)}
    once=[]
    def signal_call(number,handler):
        if number==signal.SIGINT and handler is original[number] and not once:
            once.append(True);raise secondary
        return real_signal(number,handler)
    monkeypatch.setattr(signal,'signal',signal_call)
    try:
        control.publish_post_construction_location(budget,prepared=postconstruction_inputs()['prepared'],construction_raw=raw,
            primary=primary,context_edge='before_yield')
        assert once and budget.context.owner.uncertain and budget.context.owner.primary is primary
        with pytest.raises(ValueError) as caught:budget.context.raise_if_fatal()
        assert caught.value is primary
    finally:
        for number,handler in original.items():real_signal(number,handler)
        signal.setitimer(signal.ITIMER_REAL,0)
    assert 'PRIVATE' not in capsys.readouterr().err


@pytest.mark.parametrize('field',['code','archive','roles','script','plan','tools','counts','hooks','missing'])
def test_postconstruction_retained_admission_bindings_must_match(field,capsys):
    raw=postconstruction_receipt();prepared=postconstruction_inputs()['prepared']
    if field=='code':prepared.code_binding['rf1086_identity_restore.py']['sha256']='c'*64
    if field=='archive':prepared.archive_binding['sha256']='c'*64
    if field=='roles':prepared.roles_binding['sha256']='c'*64
    if field=='script':prepared.index.core.script['sha256']='c'*64
    if field=='plan':prepared.plan.binding['profile']='c'*64
    if field=='tools':prepared.tools['psql']['sha256']='c'*64
    if field=='counts':prepared.plan.counts['objects']=1
    if field=='hooks':prepared.plan.pre_acl=400
    if field=='missing':prepared=None
    budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    control.publish_post_construction_location(budget,prepared=prepared,construction_raw=raw,
        primary=ValueError('PRIVATE'),context_edge='before_yield')
    assert capsys.readouterr()==('','')


@pytest.mark.parametrize('secondary',[RuntimeError('PRIVATE'),KeyboardInterrupt('PRIVATE'),SystemExit('PRIVATE')])
def test_postconstruction_cancel_bookkeeping_fault_cannot_escape_first_error(secondary,monkeypatch,capsys):
    raw=postconstruction_receipt();prepared=postconstruction_inputs()['prepared']
    budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    primary=ValueError('ORIGINAL PRIVATE')
    def interrupt():raise KeyboardInterrupt('PRIVATE first secondary')
    def broken_bookkeeping(*a):raise secondary
    monkeypatch.setattr(control.time,'monotonic',interrupt)
    monkeypatch.setattr(control,'_diagnostic_cancel',broken_bookkeeping)
    control.publish_post_construction_location(budget,prepared=prepared,construction_raw=raw,
        primary=primary,context_edge='before_yield')
    assert budget.context.owner.uncertain and budget.context.owner.primary is primary
    with pytest.raises(ValueError) as caught:budget.context.raise_if_fatal()
    assert caught.value is primary and capsys.readouterr()==('','')


# Direct generated integration: the only replaced production boundary is command.
from pathlib import Path
import socket
import subprocess
import unittest
from unittest.mock import patch
from copy import deepcopy
import test_rf1086_restore_metadata as fixtures
import test_rf1086_sql_ledger as ledger_fixtures
import rf1086_restore_metadata as metadata
ROOT = Path(__file__).resolve().parents[3]

def forbidden_prepare_io(*args, **kwargs):
    raise AssertionError('process/network forbidden in generated preparation')

class TestPrepareArchive(unittest.TestCase):
    def fixture(self, *, extension=False, ordered=True, walk_options=None,
                wire_change=None, compile_expected=True, column_rows=()):
        wire=fixtures.fixture(ordered=ordered)
        if ordered:
            wire['objects'][0]['acl']=fixtures.acl([fixtures.item('reader',('SELECT',)),fixtures.item()])
        if extension: wire['objects'][0]['extension']=[['pg_net','0.20.3',fixtures.OWNER]]
        if wire_change is not None: wire_change(wire)
        source=fixtures.source(wire,column_rows=column_rows)
        generated={}
        original_wire=ledger_fixtures.wire_and_list
        def capture_wire(rows):
            generated['raw'],generated['list']=original_wire(rows)
            return generated['raw'],generated['list']
        with patch.object(ledger_fixtures,'wire_and_list',capture_wire):
            options=dict(extension_created=extension,
                acl_sql=b'GRANT SELECT ON TABLE public.t TO reader;\n' if ordered else None)
            options.update(walk_options or {})
            script,archive,walk=fixtures.complete_walk(wire,**options)
        self.assertEqual(archive.raw,generated['raw'])
        plan=None
        if compile_expected:
            repair_index=metadata.restore_metadata_index(script,archive,walk,source,deadline=fixtures.end())
            plan=metadata.compile_plan(source,script=script,archive=archive,index=repair_index,deadline=fixtures.end())
        return dict(generated,script=script,source=source,walk=walk,plan=plan,roles=fixtures.role_sql(wire))

    def invoke(self,f,*,budget=None,script=None,cancel=None):
        source_id='1'*64
        self.calls=[]
        self.diagnostic = None
        def command(b,args,*,data=None,archive=None,cap=1024**2,end=None,allow_early_stdin_close=False):
            b.remaining(end=end)
            self.assertIsNone(archive)
            self.assertEqual(end,b.end-70)
            self.calls.append(tuple(args))
            for name in ('pg_restore','psql'):
                if args==['docker','exec',source_id,'sh','-c',control.TOOL_COMMAND.replace('@TOOL@',name)]:
                    self.assertIsNone(data);self.assertEqual(cap,4096)
                    self.assertIs(allow_early_stdin_close,False)
                    return (name+' (PostgreSQL) 17.6\n'+'a'*64+'\n').encode()
            if args==['docker','exec','-i',source_id,'pg_restore','--list','--verbose']:
                self.assertEqual(data,f['raw']);self.assertEqual(cap,2*1024**2)
                self.assertIs(allow_early_stdin_close,True)
                return f['list']
            if args==['docker','exec','-i',source_id,'sh','-c',control.OFFLINE_RESTORE]:
                self.assertEqual(data,f['raw']);self.assertEqual(cap,control.MAX_SCRIPT)
                self.assertIs(allow_early_stdin_close,False)
                if cancel is not None:raise cancel
                return f['script'] if script is None else script
            self.fail('unexpected external boundary')
        budget=control.RecoveryBudget(time.monotonic()) if budget is None else budget
        self.diagnostic = control.PreTargetDiagnostic(budget)
        with patch.object(control.RecoveryBudget,'command',command), patch.object(subprocess,'Popen',forbidden_prepare_io), patch.object(socket.socket,'connect',forbidden_prepare_io):
            result=control.prepare_archive(source_id,archive=f['raw'],roles=f['roles'],
                                           metadata=f['source'],budget=budget,diagnostic=self.diagnostic)
        return result,budget

    def positive(self,**options):
        f=self.fixture(**options);result,budget=self.invoke(f)
        self.assertIsInstance(result,control.PreparedRestore)
        self.assertEqual(result.script,f['script']);self.assertEqual(result.index,f['walk'])
        self.assertEqual(result.plan,f['plan'])
        self.assertEqual(result.roles,metadata.role_program(f['roles'],f['source'],deadline=fixtures.end()))
        for got,data in ((result.archive_binding,f['raw']),(result.roles_binding,f['roles'])):
            self.assertEqual(got,dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        self.assertEqual(len(result.code_binding),13)
        self.assertIsNone(self.diagnostic.failure)
        self.assertEqual(self.diagnostic.inputs['script'],result.index.core.script)
        for name,bound in result.code_binding.items():
            raw=(ROOT/'scripts'/name).read_bytes()
            self.assertEqual(bound,dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
        self.assertEqual(len(self.calls),4);self.assertEqual(budget.phase,'construction')
        self.assertGreaterEqual(budget.remaining(),70)
        self.assertEqual(result.plan.cuts['In']<result.plan.cuts['Is']<result.plan.pre_acl,True)

    def test_complete_ordinary_ordered_acl(self):self.positive()
    def test_complete_extension_owned_object(self):self.positive(extension=True)
    def test_complete_explicit_default_acl(self):self.positive(ordered=False)

    def test_pg_catalog_empty_family_through_real_preparation(self):
        def pg_namespace(rows):
            row=next(row for row in rows if row['id']==52)
            row.update(namespace=b'pg_catalog',tag=b'FUNCTION current_database()')
        f=self.fixture(compile_expected=False,walk_options={
            'acl_sql':b'GRANT EXECUTE ON FUNCTION pg_catalog.current_database() TO reader;\n',
            'acl_deps':(420,), 'rows_change':pg_namespace})
        result,budget=self.invoke(f)
        self.assertEqual(result.script,f['script'])
        self.assertEqual(result.index,f['walk'])
        self.assertEqual(result.archive_binding,dict(bytes=len(f['raw']),sha256=hashlib.sha256(f['raw']).hexdigest()))
        self.assertEqual([c.object.identity for c in result.plan.candidates],[('relation','public','t')])
        index=metadata.restore_metadata_index(f['script'],
            control.raw_toc.inspect(f['raw'],f['list'],fixtures.end())[0],
            result.index,f['source'],deadline=fixtures.end())
        self.assertTrue(all(row['identity'][1]!='pg_catalog' and not row['aclSpans'] for row in index['objects']))
        self.assertNotIn(b'pg_catalog',b''.join(c.sql for c in result.plan.candidates))
        self.assertEqual(result.plan.counts['objects'],len(f['source'].objects))
        self.assertIsNone(self.diagnostic.failure)
        self.assertEqual(len(self.calls),4)
        self.assertGreaterEqual(budget.remaining(),70)

    def column_fixture(self, *, empty_family, sql=None, deps=None):
        namespace, target = (b'pg_catalog', b'pg_class') if empty_family else (b'public', b'column_table')
        sql = b'GRANT SELECT (id) ON TABLE '+namespace+b'.'+target+b' TO reader;\n' if sql is None else sql
        def change(wire):
            if not empty_family:
                obj=deepcopy(wire['objects'][0])
                obj.update(objectOid=20001,identity=['relation','public','column_table'],columnAclCount=1)
                wire['objects'].append(obj)
        def rows_change(rows):
            acl=next(row for row in rows if row['id']==52)
            acl.update(namespace=namespace,tag=b'TABLE '+target)
            if not empty_family:
                table=ledger_fixtures.row(43,b'TABLE',target,b'CREATE TABLE public.column_table (id integer);\n',
                    class_oid=b'1259',oid=b'20001',namespace=namespace,owner=fixtures.OWNER.encode(),
                    drop=b'DROP TABLE public.column_table;\n')
                rows.insert(next(i for i,row in enumerate(rows) if row['id']==42),table)
        columns=() if empty_family else (['column_acl','public','column_table','id','{reader=r/supabase_admin}'],)
        return self.fixture(compile_expected=False,wire_change=change,column_rows=columns,
            walk_options={'acl_sql':sql,'acl_deps':(420,) if empty_family else (43,) if deps is None else deps,
                          'rows_change':rows_change})

    def assert_column_preparation(self, *, empty_family):
        f=self.column_fixture(empty_family=empty_family)
        try:
            result,budget=self.invoke(f)
        except metadata.MetadataUnavailable as error:
            error.add_note('Generated preparation diagnostic: '+json.dumps(self.diagnostic.failure))
            raise
        self.assertEqual(result.script,f['script'])
        self.assertEqual(result.index,f['walk'])
        self.assertEqual(result.archive_binding,dict(bytes=len(f['raw']),sha256=hashlib.sha256(f['raw']).hexdigest()))
        self.assertEqual(result.index.core.script,dict(bytes=len(f['script']),sha256=hashlib.sha256(f['script']).hexdigest()))
        expected=[('relation','public','t')]
        if not empty_family:expected.append(('relation','public','column_table'))
        self.assertEqual([c.object.identity for c in result.plan.candidates],expected)
        archive=control.raw_toc.inspect(f['raw'],f['list'],fixtures.end())[0]
        index=metadata.restore_metadata_index(f['script'],archive,result.index,f['source'],deadline=fixtures.end())
        self.assertTrue(all(not row['aclSpans'] for row in index['objects']))
        self.assertTrue(all(row['identity'][1]!='pg_catalog' for row in index['objects']))
        supplement=b''.join(c.sql for c in result.plan.candidates)
        self.assertNotIn(b'(id)',supplement)
        if empty_family:self.assertNotIn(b'column_table',supplement)
        else:self.assertIn(b'ON TABLE public.column_table',supplement)
        self.assertEqual(result.plan.counts['objects'],len(f['source'].objects))
        self.assertIsNone(self.diagnostic.failure)
        self.assertEqual(len(self.calls),4)
        self.assertGreaterEqual(budget.remaining(),70)

    def test_source_table_acl_seed_keeps_column_statements_original_through_real_preparation(self):
        self.assert_column_preparation(empty_family=False)

    def test_missing_owner_column_table_through_real_preparation(self):
        def change(wire):
            obj=wire['objects'][0];obj['columnAclCount']=1
            obj['acl']=fixtures.acl([fixtures.item('writer',('SELECT',)),fixtures.item('reader',('SELECT',))])
        sql=(b'REVOKE ALL ON TABLE public.t FROM supabase_admin;\n'
             b'GRANT SELECT ON TABLE public.t TO reader;\n'
             b'GRANT SELECT ON TABLE public.t TO writer;\n'
             b'GRANT SELECT(id) ON TABLE public.t TO reader;\n')
        self.positive(wire_change=change,column_rows=(['column_acl','public','t','id',
            '{reader=r/supabase_admin}'],),walk_options={'acl_sql':sql})

    def test_column_table_owner_middle_reset_through_real_preparation(self):
        def change(wire):
            obj=wire['objects'][0];obj['columnAclCount']=1
            obj['acl']=fixtures.acl([fixtures.item('writer',('UPDATE',)),
                fixtures.item(fixtures.OWNER,('SELECT','UPDATE'),('SELECT',)), fixtures.item('reader',('SELECT',))])
        sql=(b'REVOKE ALL ON TABLE public.t FROM supabase_admin;\n'
             b'GRANT UPDATE ON TABLE public.t TO supabase_admin;\n'
             b'GRANT SELECT ON TABLE public.t TO supabase_admin WITH GRANT OPTION;\n'
             b'GRANT SELECT ON TABLE public.t TO reader;\n'
             b'GRANT UPDATE ON TABLE public.t TO writer;\n'
             b'GRANT SELECT(id) ON TABLE public.t TO reader;\n')
        f=self.fixture(compile_expected=False,wire_change=change,column_rows=(['column_acl','public','t','id',
            '{reader=r/supabase_admin}'],),walk_options={'acl_sql':sql})
        result,budget=self.invoke(f)
        self.assertEqual(result.script,f['script']);self.assertEqual(result.index,f['walk'])
        self.assertEqual(len(result.plan.candidates),1)
        candidate=result.plan.candidates[0]
        self.assertEqual(candidate.object,f['source'].objects[0])
        self.assertEqual(candidate.seed_acl.raw,'{writer=w/supabase_admin}')
        self.assertEqual(candidate.sql,b'REVOKE ALL ON TABLE public.t FROM supabase_admin RESTRICT;\n'
            b'GRANT UPDATE ON TABLE public.t TO writer;\n')
        self.assertIsNone(self.diagnostic.failure)
        self.assertEqual(len(self.calls),4);self.assertGreaterEqual(budget.remaining(),70)

    def test_unmodeled_pg_catalog_column_acl_through_real_preparation(self):
        self.assert_column_preparation(empty_family=True)

    def test_column_denials_and_direct_dependency_precede_target_admission(self):
        for empty in (False,True):
            table=b'pg_catalog.pg_class' if empty else b'public.column_table'
            for rights in (b'SELECT(id,other)',b'SELECT("C"),UPDATE(C)',b'SELECT(id),UPDATE(other)'):
                with self.subTest(empty=empty,rights=rights):
                    f=self.column_fixture(empty_family=empty,sql=b'GRANT '+rights+b' ON TABLE '+table+b' TO reader;\n')
                    with patch.object(control.RecoveryBudget,'before_target',side_effect=AssertionError('admission reached')) as admission:
                        with self.assertRaises((metadata.MetadataUnavailable,metadata.ledger.Unavailable)):
                            self.invoke(f)
                    admission.assert_not_called()
        f=self.column_fixture(empty_family=False,deps=(42,))
        with patch.object(control.RecoveryBudget,'before_target',side_effect=AssertionError('admission reached')) as admission:
            with self.assertRaises(metadata.MetadataUnavailable) as caught:self.invoke(f)
        self.assertEqual(caught.exception.reason,'archive_profile');admission.assert_not_called()
        f=self.fixture(compile_expected=False,walk_options={'acl_sql':b'GRANT SELECT(id) ON TABLE public.t TO reader;\n'})
        with patch.object(control.RecoveryBudget,'before_target',side_effect=AssertionError('admission reached')) as admission:
            with self.assertRaises(metadata.MetadataUnavailable):self.invoke(f)
        self.assertEqual(self.diagnostic.failure['step'],'acl_compile');admission.assert_not_called()

    def test_column_statement_cannot_hide_extra_sql(self):
        rows=[]
        # Rebuild a genuine generated archive, not an unbound script mutation.
        f=self.fixture(compile_expected=False,walk_options={
            'acl_sql':b'GRANT SELECT(id) ON TABLE pg_catalog.pg_class TO reader;\n',
            'acl_deps':(420,), 'rows_change':lambda values:rows.extend(deepcopy(values))})
        next(row for row in rows if row['id']==52)['definition']+=b'SELECT 1;\n'
        f['raw'],f['list']=ledger_fixtures.wire_and_list(rows)
        f['script']=ledger_fixtures.script_fixture(rows)
        with patch.object(control.RecoveryBudget,'before_target',side_effect=AssertionError('admission reached')) as admission:
            with self.assertRaises(control.ledger.Unavailable):self.invoke(f)
        admission.assert_not_called();self.assertEqual(self.diagnostic.failure['step'],'restore_ledger')

    def test_column_fallback_resource_and_cancel_identity_before_admission(self):
        import inspect
        for empty in (False,True):
            table=b'pg_catalog.pg_class' if empty else b'public.column_table'
            for seam in ('prefix','column','ending'):
                rights=b'SELECT' if seam=='prefix' else b'SELECT(id)'
                sql=b'GRANT '+rights+b' ON TABLE '+table+b' TO reader;\n'
                f=self.column_fixture(empty_family=empty,sql=sql)
                for token in (metadata.MetadataUnavailable('deadline'),metadata.ledger.Unavailable('deadline'),
                              metadata.ledger.Unavailable('limit'),metadata.lexical.Unavailable('deadline'),
                              metadata.lexical.Unavailable('limit'),KeyboardInterrupt('generated'),SystemExit('generated'),None):
                    with self.subTest(empty=empty,seam=seam,kind=type(token).__name__):
                        name={'prefix':'_operation_prefix','column':'_sname','ending':'_operation_ending'}[seam]
                        original=getattr(metadata,name);hits=[]
                        caller=metadata._unsupported_target if seam=='ending' else metadata._unmodeled_table_prefix
                        def stop(s,*args,**kwargs):
                            result=original(s,*args,**kwargs)
                            if s.raw==sql and inspect.currentframe().f_back.f_code is caller.__code__:
                                hits.append(True)
                                if token is not None:raise token
                                s.budget.deadline=-1
                            return result
                        with patch.object(metadata,name,stop), patch.object(
                            control.RecoveryBudget,'before_target',side_effect=AssertionError('admission reached')) as admission:
                            with self.assertRaises(type(token) if token is not None else metadata.MetadataUnavailable) as caught:
                                self.invoke(f)
                        self.assertEqual(hits,[True]);admission.assert_not_called()
                        if token is not None:self.assertIs(caught.exception,token)
                        else:self.assertEqual(caught.exception.reason,'deadline')
                        self.assertEqual(len(self.calls),4)

    def test_pg_catalog_denials_precede_target_admission(self):
        for sql in (
            b'GRANT EXECUTE ON FUNCTION public.missing() TO reader;\n',
            b'GRANT EXECUTE ON FUNCTION pg_toast.missing() TO reader;\n',
            b'GRANT EXECUTE ON FUNCTION information_schema.missing() TO reader;\n',
            b'GRANT EXECUTE ON FUNCTION pg_catalog.f() TO reader GRANTED BY supabase_admin;\n',
            b'GRANT SELECT (oid, relname) ON TABLE pg_catalog.pg_class TO reader;\n',
            b'GRANT EXECUTE ON FUNCTION pg_catalog.f(), net.http_get(text) TO reader;\n',
            b'REVOKE EXECUTE ON FUNCTION pg_catalog.f(), net.http_get(text) FROM reader;\n',
        ):
            with self.subTest(sql=sql):
                rows=[]
                f=self.fixture(extension=True,compile_expected=False,walk_options={
                    'acl_sql':b'GRANT EXECUTE ON FUNCTION pg_catalog.current_database() TO reader;\n',
                    'acl_deps':(420,), 'rows_change':lambda values:rows.extend(deepcopy(values))})
                next(row for row in rows if row['id']==52)['definition']=sql
                f['raw'],f['list']=ledger_fixtures.wire_and_list(rows)
                f['script']=ledger_fixtures.script_fixture(rows)
                with patch.object(control.RecoveryBudget,'before_target',side_effect=AssertionError('admission reached')) as admission:
                    with self.assertRaises((metadata.MetadataUnavailable,metadata.ledger.Unavailable)):
                        self.invoke(f)
                admission.assert_not_called()
                self.assertEqual(len(self.calls),4)

    def test_pg_catalog_extra_statement_still_fails_whole_ledger(self):
        rows=[]
        f=self.fixture(extension=True,compile_expected=False,walk_options={
            'acl_sql':b'GRANT EXECUTE ON FUNCTION pg_catalog.current_database() TO reader;\n',
            'acl_deps':(420,), 'rows_change':lambda values:rows.extend(deepcopy(values))})
        next(row for row in rows if row['id']==52)['definition']+=b'SELECT 1;\n'
        f['raw'],f['list']=ledger_fixtures.wire_and_list(rows)
        f['script']=ledger_fixtures.script_fixture(rows)
        with patch.object(control.RecoveryBudget,'before_target',side_effect=AssertionError('admission reached')) as admission:
            with self.assertRaises(control.ledger.Unavailable):self.invoke(f)
        admission.assert_not_called()
        self.assertEqual(self.diagnostic.failure['step'],'restore_ledger')

    def test_pg_catalog_resource_and_cancel_failures_precede_admission(self):
        import inspect
        sql=b'GRANT EXECUTE ON FUNCTION pg_catalog.current_database() TO reader;\n'
        f=self.fixture(compile_expected=False,walk_options={'acl_sql':sql,'acl_deps':(420,)})
        for seam in ('group','ending'):
            for token in (metadata.MetadataUnavailable('deadline'),metadata.ledger.Unavailable('deadline'),
                          metadata.ledger.Unavailable('limit'),metadata.lexical.Unavailable('deadline'),
                          metadata.lexical.Unavailable('limit'),KeyboardInterrupt('generated'),
                          SystemExit('generated'),None):
                with self.subTest(seam=seam,kind=type(token).__name__):
                    owner=metadata.Statement if seam=='group' else metadata
                    name='group' if seam=='group' else '_operation_ending'
                    original=getattr(owner,name)
                    hits=[]
                    def stop(s,*args,**kwargs):
                        result=original(s,*args,**kwargs)
                        if (s.raw==sql and inspect.currentframe().f_back.f_code is
                                metadata._unsupported_target.__code__):
                            hits.append(True)
                            if token is not None:raise token
                            s.budget.deadline=-1
                        return result
                    with patch.object(owner,name,stop), patch.object(
                        control.RecoveryBudget,'before_target',side_effect=AssertionError('admission reached')) as admission:
                        with self.assertRaises(type(token) if token is not None else metadata.MetadataUnavailable) as caught:
                            self.invoke(f)
                    self.assertEqual(hits,[True]); admission.assert_not_called()
                    if token is not None:self.assertIs(caught.exception,token)
                    else:self.assertEqual(caught.exception.reason,'deadline')
                    self.assertEqual(len(self.calls),4)
                    if isinstance(token,(KeyboardInterrupt,SystemExit)):
                        self.assertIsNone(self.diagnostic.failure)
                    else:self.assertEqual(self.diagnostic.failure['step'],'metadata_index')
                    if type(token) in (metadata.ledger.Unavailable,metadata.lexical.Unavailable):
                        self.assertEqual(self.diagnostic.failure['component'],'unknown')
                        self.assertEqual(self.diagnostic.failure['reason'],'internal')

    def test_omitted_member_without_acl_gets_real_seed_before_target(self):
        self.positive(extension=True,walk_options={'acl_sql':None})

    def test_unsupported_routine_stays_unmodeled_through_real_preparation(self):
        def change(wire): wire['objects'][1]['argumentModes']=['v']
        def acl_namespace(rows):
            next(r for r in rows if r['id']==52)['namespace']=b'net'
        f=self.fixture(extension=True,wire_change=change,walk_options={
            'acl_sql':b'GRANT EXECUTE ON FUNCTION net.http_get(url text[], params jsonb) TO reader;\n',
            'rows_change':acl_namespace})
        result,_=self.invoke(f)
        self.assertEqual(result.plan,f['plan'])
        self.assertEqual(len(result.plan.candidates),1)  # Only the unrelated table seed.
        self.assertEqual(result.plan.candidates[0].object.identity,('relation','public','t'))

    def test_arity_disjoint_family_through_real_preparation(self):
        for verb, direction in (('GRANT','TO'), ('REVOKE','FROM')):
            for modes in (None, ['i']*3):
                with self.subTest(verb=verb,modes=modes):
                    def change(wire): fixtures.arity_family(wire,modes=modes)
                    sql=f'{verb} EXECUTE ON FUNCTION public.fixture_armor(bytea, text[], text[]) {direction} reader;\n'.encode()
                    f=self.fixture(wire_change=change,compile_expected=False,
                        walk_options={'acl_sql':sql,'acl_deps':(420,)})
                    result,budget=self.invoke(f)
                    self.assertEqual(result.script,f['script'])
                    self.assertEqual([c.object.identity for c in result.plan.candidates],
                                     [('relation','public','t')])
                    self.assertEqual(result.plan.counts['unmodeled'],1)
                    self.assertEqual(result.plan.counts['archiveOnly'],4)
                    self.assertEqual(len(result.code_binding),13)
                    for name,bound in result.code_binding.items():
                        raw=(ROOT/'scripts'/name).read_bytes()
                        self.assertEqual(bound,dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()))
                    self.assertIsNone(self.diagnostic.failure)
                    self.assertEqual(len(self.calls),4)
                    self.assertGreaterEqual(budget.remaining(),70)

    def test_arity_disjoint_denials_precede_real_target_admission(self):
        for case in ('supported','mode','grant_tail','revoke_tail','qualification'):
            with self.subTest(case=case):
                def change(wire):
                    fixtures.arity_family(wire)
                    if case in ('supported','mode'):
                        other=deepcopy(wire['objects'][-1]); other['objectOid']=23000
                        other['identity'][3]='a bytea, b text[], c text[]'
                        if case=='supported':
                            other['identity'][3]='bytea, text, text'
                            other['argumentTypes']=[['pg_catalog',t] for t in ('bytea','text','text')]
                        else:other['argumentModes']=['o','i','i']
                        wire['objects'].append(other)
                target='public.fixture_armor(bytea, text[], text[])'
                if case in ('grant_tail','revoke_tail'):target+=', public.fixture_armor(bytea)'
                if case=='qualification':target=target.replace('text[]','pg_catalog.text[]',1)
                verb,direction=('REVOKE','FROM') if case=='revoke_tail' else ('GRANT','TO')
                sql=f'{verb} EXECUTE ON FUNCTION {target} {direction} reader;\n'.encode()
                f=self.fixture(wire_change=change,compile_expected=False,
                    walk_options={'acl_sql':sql,'acl_deps':(420,)})
                with patch.object(control.RecoveryBudget,'before_target',side_effect=AssertionError('admission reached')) as admission:
                    with self.assertRaises((metadata.MetadataUnavailable,control.ledger.Unavailable)):
                        self.invoke(f)
                admission.assert_not_called()
                self.assertEqual(len(self.calls),4)

    def test_extra_statement_after_arity_acl_is_rejected_by_real_ledger(self):
        rows=[]
        f=self.fixture(extension=True,wire_change=fixtures.arity_family,compile_expected=False,walk_options={
            'acl_sql':b'GRANT EXECUTE ON FUNCTION public.fixture_armor(bytea, text[], text[]) TO reader;\n',
            'acl_deps':(420,), 'rows_change':lambda values:rows.extend(deepcopy(values))})
        next(row for row in rows if row['id']==52)['definition']+=b'SELECT 1;\n'
        f['raw'],f['list']=ledger_fixtures.wire_and_list(rows)
        f['script']=ledger_fixtures.script_fixture(rows)
        with patch.object(control.RecoveryBudget,'before_target',side_effect=AssertionError('admission reached')) as admission:
            with self.assertRaises(control.ledger.Unavailable):self.invoke(f)
        admission.assert_not_called()
        self.assertEqual(self.diagnostic.failure['step'],'restore_ledger')
        self.assertEqual(len(self.calls),4)

    def test_arity_final_check_cannot_swallow_expiry_or_cancel_before_target(self):
        f=self.fixture(wire_change=fixtures.arity_family,compile_expected=False,walk_options={
            'acl_sql':b'GRANT EXECUTE ON FUNCTION public.fixture_armor(bytea, text[], text[]) TO reader;\n',
            'acl_deps':(420,)})
        for token in (metadata.MetadataUnavailable('deadline'),metadata.ledger.Unavailable('deadline'),
                      metadata.ledger.Unavailable('limit'),metadata.lexical.Unavailable('deadline'),
                      metadata.lexical.Unavailable('limit'),
                      KeyboardInterrupt('generated'),SystemExit('generated'),None):
            with self.subTest(kind=type(token).__name__):
                original=metadata._operation_ending
                def ending(*args,**kwargs):
                    original(*args,**kwargs)
                    if token is not None:raise token
                    args[0].budget.deadline=-1  # Existing real final deadline check.
                with patch.object(metadata,'_operation_ending',ending), patch.object(
                    control.RecoveryBudget,'before_target',side_effect=AssertionError('admission reached')) as admission:
                    with self.assertRaises(type(token) if token is not None else metadata.MetadataUnavailable) as caught:
                        self.invoke(f)
                if token is not None:self.assertIs(caught.exception,token)
                else:self.assertEqual(caught.exception.reason,'deadline')
                admission.assert_not_called()
                self.assertEqual(len(self.calls),4)
                if type(token) in (metadata.ledger.Unavailable,metadata.lexical.Unavailable):
                    self.assertEqual(self.diagnostic.failure['step'],'metadata_index')
                    self.assertEqual(self.diagnostic.failure['component'],'unknown')
                    self.assertEqual(self.diagnostic.failure['reason'],'internal')
                    self.assertIsNone(self.diagnostic.failure['ledger'])
                    self.assertIsNone(self.diagnostic.failure['lexicalLimit'])
                    control.validate_pre_target_diagnostic(self.diagnostic.failure)

    def test_metadata_lexical_resource_denial_preserves_identity_before_target(self):
        import inspect
        sql=b'GRANT EXECUTE ON FUNCTION public.fixture_armor(bytea, text[], text[]) TO reader;\n'
        f=self.fixture(wire_change=fixtures.arity_family,compile_expected=False,
                       walk_options={'acl_sql':sql,'acl_deps':(420,)})
        for reason in ('deadline','limit'):
            with self.subTest(reason=reason):
                token=metadata.lexical.Unavailable(reason)
                original=metadata.lexical.scan
                hits=[]
                def scan(raw,*args,**kwargs):
                    if raw==sql and inspect.currentframe().f_back.f_code is metadata._statements.__code__:
                        hits.append(True)
                        raise token
                    return original(raw,*args,**kwargs)
                with patch.object(metadata.lexical,'scan',scan), patch.object(
                    control.RecoveryBudget,'before_target',side_effect=AssertionError('admission reached')) as admission:
                    with self.assertRaises(metadata.lexical.Unavailable) as caught:self.invoke(f)
                self.assertIs(caught.exception,token)
                self.assertEqual(hits,[True]); admission.assert_not_called()
                self.assertEqual(len(self.calls),4)
                self.assertEqual(self.diagnostic.failure['step'],'metadata_index')
                self.assertEqual(self.diagnostic.failure['component'],'unknown')
                self.assertEqual(self.diagnostic.failure['reason'],'internal')
                self.assertIsNone(self.diagnostic.failure['ledger'])
                self.assertIsNone(self.diagnostic.failure['lexicalLimit'])
                control.validate_pre_target_diagnostic(self.diagnostic.failure)

    def test_metadata_admission_and_unsupported_tail_refuse_before_target(self):
        event=ledger_fixtures.source_rows()[-1]
        cases=[
            ({'acl_deps':(20,)},None,'metadata_index'),
            ({'post_rows':(event,)},None,'acl_compile'),
            ({'acl_sql':None,'post_rows':(event,)},None,'acl_compile'),
        ]
        def unsupported(wire):wire['objects'][1]['argumentModes']=['v']
        for verb,direction in ((b'GRANT',b'TO'),(b'REVOKE',b'FROM')):
            cases.append(({'acl_sql':verb+b' EXECUTE ON FUNCTION net.http_get(url text[]), '
                b'net.http_post(text) '+direction+b' reader;\n'},unsupported,'metadata_index'))
        for options,change,step in cases:
            with self.subTest(options=options):
                f=self.fixture(extension=True,walk_options=options,wire_change=change,compile_expected=False)
                with patch.object(control.RecoveryBudget,'before_target',side_effect=AssertionError('allocation reached')) as admission:
                    with self.assertRaises((metadata.MetadataUnavailable,control.ledger.Unavailable)):
                        self.invoke(f)
                admission.assert_not_called()
                self.assertEqual(self.diagnostic.failure['step'],step)
                self.assertEqual(len(self.calls),4)

    def test_fallback_deadline_and_cancel_cannot_become_success_or_admission(self):
        def unsupported(wire):wire['objects'][1]['argumentModes']=['v']
        f=self.fixture(extension=True,wire_change=unsupported,compile_expected=False,walk_options={
            'acl_sql':b'GRANT EXECUTE ON FUNCTION net.http_get(url text[]) TO reader;\n'})
        for primary in (metadata.MetadataUnavailable('deadline'),KeyboardInterrupt('synthetic cancel')):
            with self.subTest(kind=type(primary).__name__):
                original=metadata._unsupported_target
                def fail_ending(*args,**kwargs):
                    # Real structural parsing succeeds first; then the final check
                    # must propagate the exact initiating failure, never continue.
                    original(*args,**kwargs)
                    raise primary
                with patch.object(metadata,'_unsupported_target',fail_ending), patch.object(
                    control.RecoveryBudget,'before_target',side_effect=AssertionError('allocation reached')) as admission:
                    with self.assertRaises(type(primary)) as caught:self.invoke(f)
                self.assertIs(caught.exception,primary)
                admission.assert_not_called()
                self.assertEqual(len(self.calls),4)
                if isinstance(primary,KeyboardInterrupt):self.assertIsNone(self.diagnostic.failure)
                else:self.assertEqual(self.diagnostic.failure['reason'],'deadline')

    def test_truncated_listing_is_rejected_before_prepared_restore(self):
        f=self.fixture(); f['list']=f['list'][:40]
        with self.assertRaises(control.raw_toc.Unavailable): self.invoke(f)
        self.assertEqual(self.diagnostic.failure['step'],'raw_metadata')
        self.assertEqual(len(self.calls),4)

    def test_mismatched_listing_is_rejected_before_prepared_restore(self):
        f=self.fixture(); f['list']=f['list'].replace(b'TABLE public t ',b'TABLE public wrong ',1)
        self.assertIn(b'TABLE public wrong ',f['list'])
        with self.assertRaises(control.raw_toc.Unavailable): self.invoke(f)
        self.assertEqual(self.diagnostic.failure['step'],'raw_metadata')
        self.assertEqual(len(self.calls),4)

    def test_insufficient_original_headroom_stops_before_external_boundary(self):
        f=self.fixture();budget=control.RecoveryBudget(time.monotonic()-46)
        with self.assertRaises(control.RestoreUnavailable) as caught:self.invoke(f,budget=budget)
        self.assertEqual(caught.exception.reason,'deadline');self.assertEqual(self.calls,[])
        self.assertEqual(self.diagnostic.failure['step'],'prepare_headroom')

    def test_generation_cancellation_propagates_original_identity(self):
        f=self.fixture();token=KeyboardInterrupt('generated cancellation')
        with self.assertRaises(KeyboardInterrupt) as caught:self.invoke(f,cancel=token)
        self.assertIs(caught.exception,token);self.assertEqual(len(self.calls),4)
        self.assertIsNone(self.diagnostic.failure)

    def test_profile_refusal_is_not_a_prepared_target_and_receipt_is_internal(self):
        f=self.fixture();budget=control.RecoveryBudget(time.monotonic())
        with self.assertRaises(control.ledger.Unavailable) as caught:
            self.invoke(f,budget=budget,script=b'unsupported header\n'+f['script'])
        self.assertEqual(caught.exception.reason,'profile')
        observed=self.diagnostic.failure
        self.assertEqual(observed['component'],'ledger')
        self.assertEqual(observed['step'],'restore_ledger')
        self.assertEqual(observed['ledger']['stage'],'preparation')
        self.assertEqual(observed['location']['module'],'ledger')
        self.assertIsNone(observed['inputs']['script'])
        self.assertEqual(observed['inputs']['scriptBytes'],len(f['script'])+len(b'unsupported header\n'))
        self.assertEqual(len(self.calls),4)
        fingerprint=dict.fromkeys(('roles','catalog','auth','companyMemberships'),'a'*64)
        raw=control.construction_receipt(budget=budget,prepared=None,delivery=None,mutations=None,
            source='1'*64,target=None,image='sha256:'+'2'*64,before=fingerprint,recovered=None,
            cleanup_complete=True,source_postcheck=True,business_complete=False,
            reason=caught.exception.reason)
        record=json.loads(raw)
        self.assertEqual(record['status'],'unavailable');self.assertEqual(record['reason'],'internal')
        self.assertIsNone(record['bindings']);self.assertIsNone(record['identities']['target'])



def diagnostic_failure(*, error=None, step='archive_list', walk=None):
    diagnostic=control.PreTargetDiagnostic(control.RecoveryBudget(time.monotonic()))
    primary=ValueError('secret SQL/role/identifier') if error is None else error
    with pytest.raises(type(primary)) as caught:
        with diagnostic.operation(step,walk=walk):raise primary
    assert caught.value is primary
    return diagnostic


@pytest.mark.parametrize('step',sorted(control.DIAGNOSTIC_STEPS))
def test_every_closed_step_captures_first_denial_without_overwrite(step):
    diagnostic=diagnostic_failure(step=step)
    original=deepcopy(diagnostic.failure)
    with pytest.raises(RuntimeError):
        with diagnostic.operation('unclassified'):raise RuntimeError('cleanup private text')
    assert diagnostic.failure==original
    assert original['step']==step and original['component']=='unknown'
    assert 'secret' not in json.dumps(original) and 'cleanup private text' not in json.dumps(original)


@pytest.mark.parametrize('kind,reason,step,expected',[
    ('control','source_drift','source_recheck',('control','source_drift')),
    ('metadata','metadata_profile','source_metadata_decode',('metadata','metadata_profile')),
    ('metadata','metadata_profile','archive_list',('unknown','internal')),
    ('raw','deadline_invalid','raw_metadata',('raw_toc','deadline')),
    ('raw','deadline_exhausted','raw_metadata',('raw_toc','deadline')),
    ('raw','metadata_truncated','raw_metadata',('raw_toc','metadata')),
    ('raw','secret_field','raw_metadata',('unknown','internal')),
    ('ledger','profile','restore_ledger',('ledger','profile')),
    ('lexical','unfinished','restore_ledger',('lexical','lexical')),
    ('identifiers',None,'restore_ledger',('identifiers','profile')),
])
def test_exact_typed_reason_mapping(kind,reason,step,expected):
    classes={'control':control.RestoreUnavailable,'metadata':metadata.MetadataUnavailable,
        'raw':control.raw_toc.Unavailable,'ledger':control.ledger.Unavailable,
        'lexical':control.ledger.lexical.Unavailable,'identifiers':control.ledger.identifiers.Unavailable}
    error=classes[kind]() if reason is None else classes[kind](reason)
    result=diagnostic_failure(error=error,step=step).failure
    assert (result['component'],result['reason'])==expected


def test_exception_properties_subclasses_messages_are_not_read():
    class PrivateError(control.ledger.Unavailable):
        def __getattribute__(self,name):
            if name in ('reason','args','__dict__','__traceback__','__context__','__cause__'):
                raise AssertionError('arbitrary exception access')
            return super().__getattribute__(name)
        def __str__(self):raise AssertionError('message read')
        def __repr__(self):raise AssertionError('repr read')
    error=PrivateError('profile')
    result=diagnostic_failure(error=error,step='restore_ledger').failure
    assert result['component']=='unknown' and result['reason']=='internal'


def test_binding_progress_lexical_limit_and_context_are_separate():
    lexical=control.ledger.lexical
    budget=control.RecoveryBudget(time.monotonic());diagnostic=control.PreTargetDiagnostic(budget)
    diagnostic.remember('source',dict.fromkeys(('roles','catalog','auth','companyMemberships'),'a'*64))
    diagnostic.remember('archive',{'bytes':123,'sha256':'b'*64})
    diagnostic.remember('roles',{'bytes':7,'sha256':'c'*64})
    diagnostic.remember('scriptBytes',600000)
    diagnostic.remember('archiveRows',12)
    walk=control.ledger.Budget(budget.end)
    for name in ('metadata','preparation','lexical'):walk.phase(name)
    detail={'site':'token_records','ceiling':262144,'observed':262145,'unit':'records','offset':520000}
    token=lexical.Unavailable('limit',detail)
    with pytest.raises(lexical.Unavailable) as caught:
        with diagnostic.operation('restore_ledger',walk=walk):raise token
    assert caught.value is token
    result=diagnostic.failure
    assert result['lexicalLimit']==detail and result['ledger']['context']['limit'] is None
    assert result['inputs']['script'] is None
    control.validate_pre_target_diagnostic(result)
    control.ledger.validate_receipt(result['ledger'],fsql=None)
    bad=deepcopy(result);bad['lexicalLimit']['offset']=600001
    with pytest.raises(ValueError):control.validate_pre_target_diagnostic(bad)
    bad=deepcopy(result);bad['ledger']['context']['limit']=detail
    with pytest.raises(ValueError):control.validate_pre_target_diagnostic(bad)


@pytest.mark.parametrize('bad_context',[
    {'rowIndex':1,'dumpId':1,'descriptor':'SCHEMA','offset':None},
    {'rowIndex':0,'dumpId':1,'descriptor':'secret-name','offset':None},
    {'rowIndex':None,'dumpId':None,'descriptor':None,'offset':101},
    {'rowIndex':False,'dumpId':1,'descriptor':'SCHEMA','offset':None},
])
def test_bad_ledger_context_is_closed_fallback_and_not_a_new_refusal(bad_context):
    budget=control.RecoveryBudget(time.monotonic());diagnostic=control.PreTargetDiagnostic(budget)
    diagnostic.remember('scriptBytes',100);diagnostic.remember('archiveRows',1)
    walk=control.ledger.Budget(budget.end)
    for name in control.ledger.STAGES:walk.phase(name)
    walk.context=bad_context
    token=control.ledger.Unavailable('profile')
    with pytest.raises(control.ledger.Unavailable) as caught:
        with diagnostic.operation('restore_ledger',walk=walk):raise token
    assert caught.value is token
    assert diagnostic.failure['component']=='unknown'
    assert diagnostic.failure['ledger'] is None and diagnostic.failure['lexicalLimit'] is None
    control.validate_pre_target_diagnostic(diagnostic.failure)


@pytest.mark.parametrize('path,value',[
    (('schema',),'other'),(('step',),'private-path'),(('component',),'unbounded'),(('reason',),'private'),
    (('inputs','source'),{'roles':'a'*64}), (('inputs','archive'),{'bytes':True,'sha256':'a'*64}),
    (('inputs','archive'),{'bytes':control.MAX_ARCHIVE+1,'sha256':'a'*64}),
    (('inputs','roles'),{'bytes':1,'sha256':'A'*64}), (('inputs','scriptBytes'),float('inf')),
    (('inputs','archiveRows'),0), (('inputs','script'),{'bytes':1,'sha256':'a'*64}),
    (('location',),{'module':'control','line':True,'depth':0,'edge':'primary'}),
    (('location',),{'module':'control','line':8193,'depth':0,'edge':'primary'}),
    (('location',),{'module':'control','line':1,'depth':3,'edge':'cause'}),
    (('location',),{'module':'control','line':1,'depth':0,'edge':'context'}),
    (('location',),{'module':'secret','line':1,'depth':0,'edge':'primary'}),
    (('ledger',),{'status':'verified_conditional'}),
])
def test_closed_validator_rejects_invalid_fields(path,value):
    record=diagnostic_failure().failure;target=record
    for name in path[:-1]:target=target[name]
    target[path[-1]]=value
    with pytest.raises(ValueError):control.validate_pre_target_diagnostic(record)


def test_unknown_keys_and_bad_remember_values_do_not_leak():
    diagnostic=diagnostic_failure();value=diagnostic.failure
    for obj in (value,value['inputs'],value['location']):
        bad=deepcopy(value)
        selected=bad if obj is value else bad['inputs'] if obj is value['inputs'] else bad['location']
        selected['secret']='private'
        with pytest.raises(ValueError):control.validate_pre_target_diagnostic(bad)
    original=deepcopy(diagnostic.inputs)
    for name,value in [('raw',b'secret'),('roles',{'bytes':1,'sha256':'bad'}),('source',{'secret':'data'})]:
        diagnostic.remember(name,value)
    assert diagnostic.inputs==original


def owned_error(module='metadata',*,body="raise ValueError('private payload')",prefix=''):
    filename=str(Path(control.__file__).with_name(control.DIAGNOSTIC_MODULES[module]+'.py'))
    namespace={'ValueError':ValueError}
    exec(compile(prefix+'def generated():\n    '+body+'\n',filename,'exec'),namespace)
    try:namespace['generated']()
    except ValueError as error:return error
    raise AssertionError('fixture did not fail')


def test_location_exact_paths_and_only_require_code_identity(monkeypatch):
    budget=control.RecoveryBudget(time.monotonic())
    error=owned_error()
    result=control._diagnostic_location(error,budget)
    assert result=={'module':'metadata','line':2,'depth':0,'edge':'primary'}
    try:control.require(False,'internal')
    except control.RestoreUnavailable as primary:
        assert control._diagnostic_location(primary,budget) is None  # Test path excluded, require skipped.
    for filename in ('rf1086_restore_metadata.py','/other/rf1086_restore_metadata.py',
                     str(Path(control.__file__).parent/'prefix-rf1086_restore_metadata.py')):
        fn=(lambda:None).__code__
        namespace={}
        exec(compile("def require():\n    raise ValueError('secret')\n",filename,'exec'),namespace)
        try:namespace['require']()
        except ValueError as primary:assert control._diagnostic_location(primary,budget) is None
    monkeypatch.setattr(budget,'end',time.monotonic()-1)
    assert control._diagnostic_location(error,budget) is None


def test_location_suppressed_context_and_cause_precedence():
    budget=control.RecoveryBudget(time.monotonic())
    inner=owned_error('metadata')
    outer=owned_error('control');outer.__context__=inner;outer.__suppress_context__=True
    assert control._diagnostic_location(outer,budget)=={'module':'metadata','line':2,'depth':1,'edge':'suppressed_context'}
    cause=owned_error('lexical');outer.__cause__=cause
    assert control._diagnostic_location(outer,budget)=={'module':'lexical','line':2,'depth':1,'edge':'cause'}
    # Actual metadata.closed hides a typed message but retains the structural context.
    @metadata.closed
    def wrapped():raise inner
    try:wrapped()
    except metadata.MetadataUnavailable as error:
        result=control._diagnostic_location(error,budget)
    assert result['module']=='metadata' and result['depth']==1 and result['edge']=='suppressed_context'


def test_location_cycles_fourth_exception_and_65_frames_are_unavailable():
    budget=control.RecoveryBudget(time.monotonic())
    first=owned_error();second=owned_error('ledger')
    first.__cause__=second;second.__cause__=first
    assert control._diagnostic_location(first,budget) is None
    first=owned_error();current=first
    for i in range(3):current.__cause__=owned_error();current=current.__cause__
    assert control._diagnostic_location(first,budget) is None
    namespace={}
    source="def recurse(n):\n    if n: return recurse(n-1)\n    raise ValueError('secret')\n"
    exec(compile(source,str(Path(control.__file__).with_name('rf1086_sql_ledger.py')),'exec'),namespace)
    for depth in (62,64):
        try:namespace['recurse'](depth)
        except ValueError as error:
            result=control._diagnostic_location(error,budget)
        assert (result is None)==(depth==64)


def test_projection_faults_and_repeated_termination_preserve_primary(monkeypatch):
    for secondary in (ValueError('bad projector'),KeyboardInterrupt('second termination')):
        budget=control.RecoveryBudget(time.monotonic());diagnostic=control.PreTargetDiagnostic(budget)
        primary=ValueError('initial')
        def fail(*args):raise secondary
        with monkeypatch.context() as local:
            local.setattr(control,'_diagnostic_classify',fail)
            with pytest.raises(ValueError) as caught:
                with diagnostic.operation('archive_list'):raise primary
        assert caught.value is primary
        assert diagnostic.failure['component']=='unknown'
        assert budget.context.owner.cancelled is isinstance(secondary,KeyboardInterrupt)
        if isinstance(secondary,KeyboardInterrupt):assert budget.context.owner.primary is primary


@pytest.mark.parametrize('fault',['serialize','write','flush','cancel','expired','fatal','none'])
def test_publication_is_once_bounded_stderr_and_never_replaces_failure(monkeypatch,fault):
    diagnostic=diagnostic_failure();primary=ValueError('initial')
    writes=[];flushes=[];saved=signal.getsignal(signal.SIGALRM)
    class Output:
        def write(self,value):
            if fault=='write':raise OSError('private')
            if fault=='cancel':raise KeyboardInterrupt('second termination')
            writes.append(value)
        def flush(self):
            flushes.append(True)
            if fault=='flush':raise OSError('private')
    monkeypatch.setattr(sys,'stderr',Output())
    if fault=='serialize':monkeypatch.setattr(control.ledger,'canonical',lambda v:(_ for _ in ()).throw(ValueError('secret')))
    if fault=='expired':diagnostic.budget.end=time.monotonic()-1
    if fault=='fatal':diagnostic.budget.context.owner._uncertain('fixture',primary,primary)
    diagnostic.publish(primary=primary);diagnostic.publish(primary=primary)
    assert len(writes)<=1 and len(flushes)<=1 and diagnostic.attempted
    assert signal.getsignal(signal.SIGALRM) is saved
    if fault=='none':
        assert len(writes)==len(flushes)==1 and len(writes[0].encode('ascii'))<=4096
        assert writes[0].startswith(control.DIAGNOSTIC_PREFIX) and writes[0].endswith('\n')
    if fault in ('serialize','write','cancel','expired','fatal'):assert not writes
    if fault=='cancel':
        assert diagnostic.budget.context.owner.cancelled and diagnostic.budget.context.owner.primary is primary


def test_maximum_closed_diagnostic_including_location_fits_wire_cap():
    budget=control.RecoveryBudget(time.monotonic());d=control.PreTargetDiagnostic(budget)
    d.remember('source',dict.fromkeys(('roles','catalog','auth','companyMemberships'),'f'*64))
    for name,cap in (('archive',control.MAX_ARCHIVE),('roles',control.MAX_ROLES)):
        d.remember(name,{'bytes':cap,'sha256':'f'*64})
    d.remember('scriptBytes',control.MAX_SCRIPT);d.remember('script',{'bytes':control.MAX_SCRIPT,'sha256':'f'*64})
    d.remember('archiveRows',control.raw_toc.MAX_ROWS)
    for step in control.DIAGNOSTIC_STEPS:
        for component,reasons in (('control',control.REASONS),('metadata',metadata.REASONS),
            ('ledger',control.ledger.REASON_STAGES),('lexical',('limit',)),('unknown',('internal',))):
            for reason in reasons:
                if not control._diagnostic_reason(component,reason,step):continue
                value={'schema':control.DIAGNOSTIC_SCHEMA,'step':step,'component':component,'reason':reason,
                    'inputs':deepcopy(d.inputs),'ledger':None,'lexicalLimit':None,
                    'location':{'module':'identifiers','line':8192,'depth':2,'edge':'suppressed_context'}}
                if step=='restore_ledger':
                    stage='lexical' if component=='lexical' else 'emitter'
                    mapped=reason if reason in control.ledger.REASON_STAGES and stage in control.ledger.REASON_STAGES[reason] else 'internal'
                    context=None if stage=='lexical' else {'rowIndex':8191,'dumpId':2147483647,
                        'descriptor':max(control.raw_toc.DESCRIPTORS,key=len),'offset':control.MAX_SCRIPT}
                    value['ledger']=control.ledger.unavailable(mapped,stage,context)
                    if component=='lexical':
                        value['lexicalLimit']={'site':'dollar_tag_prefix_bytes','ceiling':129,'observed':130,
                                              'unit':'bytes','offset':control.MAX_SCRIPT}
                control.validate_pre_target_diagnostic(value)
                assert len(control.DIAGNOSTIC_PREFIX)+len(control.ledger.canonical(value))+1<=4096


@pytest.mark.parametrize('step',[
    'archive_hash','roles_hash','role_program','tool_probe','archive_list','sql_generation',
    'raw_metadata','archive_profile','restore_ledger','metadata_index','acl_compile',
    'code_bindings','target_admission',
])
def test_generated_prepare_routes_each_real_boundary_to_its_label(monkeypatch,step):
    from dataclasses import replace
    case=TestPrepareArchive();fixture=case.fixture();primary=ValueError('private payload')
    def fail(*args,**kwargs):raise primary
    if step in ('archive_hash','roles_hash'):
        original=control.bounded_hash
        def bounded(value,**kwargs):
            if value is fixture['raw' if step=='archive_hash' else 'roles']:raise primary
            return original(value,**kwargs)
        monkeypatch.setattr(control,'bounded_hash',bounded)
    elif step=='role_program':monkeypatch.setattr(metadata,'role_program',fail)
    elif step=='tool_probe':monkeypatch.setattr(control,'bind_tools',fail)
    elif step=='archive_list':
        # Only the existing command seam is altered: listing failure before generation.
        original=control.RecoveryBudget.remaining
        checks=[]
        def remaining(budget,**kwargs):
            if kwargs.get('end')==budget.end-70:
                checks.append(True)
                if len(checks)==4:raise primary  # Initial, two tool commands, then list.
            return original(budget,**kwargs)
        monkeypatch.setattr(control.RecoveryBudget,'remaining',remaining)
    elif step=='sql_generation':monkeypatch.setattr(control,'generate_sql',fail)
    elif step=='raw_metadata':monkeypatch.setattr(control.raw_toc,'inspect',fail)
    elif step=='archive_profile':
        original=control.raw_toc.inspect
        def inspect(*args):
            archive,summary=original(*args)
            return replace(archive,remote_version=b'unsupported'),summary
        monkeypatch.setattr(control.raw_toc,'inspect',inspect)
        primary=None
    elif step=='restore_ledger':monkeypatch.setattr(control.ledger,'verify_restore_core',fail)
    elif step=='metadata_index':monkeypatch.setattr(metadata,'restore_metadata_index',fail)
    elif step=='acl_compile':monkeypatch.setattr(metadata,'compile_plan',fail)
    elif step=='code_bindings':monkeypatch.setattr(control,'bounded_file',fail)
    elif step=='target_admission':monkeypatch.setattr(control.RecoveryBudget,'before_target',fail)
    with pytest.raises(ValueError) as caught:case.invoke(fixture)
    if primary is not None:assert caught.value is primary
    result=case.diagnostic.failure
    assert result['step']==step
    assert result['ledger'] is None if step not in ('raw_metadata','restore_ledger') else True
    if step in ('metadata_index','acl_compile','code_bindings','target_admission'):
        assert result['inputs']['script']['bytes']==len(fixture['script'])
    control.validate_pre_target_diagnostic(result)


def test_diagnostic_projection_real_signal_is_sticky_with_original_primary(monkeypatch):
    import os
    budget=control.RecoveryBudget(time.monotonic());d=control.PreTargetDiagnostic(budget)
    original=control._diagnostic_classify
    primary=ValueError('initiating')
    def classify(*args):
        os.kill(os.getpid(),signal.SIGTERM)
        return original(*args)
    monkeypatch.setattr(control,'_diagnostic_classify',classify)
    previous=signal.getsignal(signal.SIGTERM)
    with pytest.raises(ValueError) as caught:
        with d.operation('archive_list'):raise primary
    assert caught.value is primary and budget.context.owner.cancelled
    assert budget.context.owner.primary is primary and signal.getsignal(signal.SIGTERM) is previous
    d.publish(primary=primary)
    assert d.attempted


def test_location_skips_identity_not_a_function_named_require():
    namespace={}
    exec(compile("def require():\n    raise ValueError('secret')\n",
        str(Path(control.__file__).with_name('rf1086_restore_metadata.py')),'exec'),namespace)
    try:namespace['require']()
    except ValueError as error:
        location=control._diagnostic_location(error,control.RecoveryBudget(time.monotonic()))
    assert location=={'module':'metadata','line':2,'depth':0,'edge':'primary'}


def test_lexical_observation_is_copied_not_retained_from_exception():
    budget=control.RecoveryBudget(time.monotonic());d=control.PreTargetDiagnostic(budget)
    d.remember('scriptBytes',10)
    walk=control.ledger.Budget(budget.end)
    for name in ('metadata','preparation','lexical'):walk.phase(name)
    detail={'site':'token_records','ceiling':262144,'observed':262145,'unit':'records','offset':9}
    error=control.ledger.lexical.Unavailable('limit',detail)
    with pytest.raises(control.ledger.lexical.Unavailable):
        with d.operation('restore_ledger',walk=walk):raise error
    detail['secret']='private'
    assert 'secret' not in d.failure['lexicalLimit']
    control.validate_pre_target_diagnostic(d.failure)


@pytest.mark.parametrize('step,stage,reason',[
    ('raw_metadata','emitter','internal'),('raw_metadata','preparation','internal'),
    ('raw_metadata','lexical','internal'),('restore_ledger','admission','headroom'),
    ('restore_ledger','summary','summary'),
])
def test_nested_stage_must_be_reachable_from_its_exact_active_step(step,stage,reason):
    value=diagnostic_failure(step=step).failure
    value['ledger']=control.ledger.unavailable(reason,stage)
    # This is a valid standalone unavailable ledger; it is impossible at this call site.
    control.ledger.validate_receipt(value['ledger'],fsql=None)
    with pytest.raises(ValueError):control.validate_pre_target_diagnostic(value)


def test_raw_metadata_context_allows_null_optional_commitments():
    value=diagnostic_failure(step='raw_metadata').failure
    value['ledger']=control.ledger.unavailable('internal','metadata')
    assert all(v is None for v in value['inputs'].values())
    control.validate_pre_target_diagnostic(value)


# SPEC-authored admission checks: all Docker output is generated; no socket,
# daemon or child is acquired. Relay mechanics are tested in the deadline file.
_ADMISSION_OVERRIDES = ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY',
    'DOCKER_CERT_PATH', 'TALLI_RF_RESTORE_SSH_CONFIG', 'TALLI_RF_RESTORE_SSH_HOST')


@pytest.fixture
def admission_io(monkeypatch):
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError('admission tests must not acquire sockets or children')
    monkeypatch.setattr(control.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(control.sys, 'platform', 'linux')
    for key in _ADMISSION_OVERRIDES:
        monkeypatch.delenv(key, raising=False)
    clock = [1000.0]
    monkeypatch.setattr(control.time, 'monotonic', lambda: clock[0])
    budget = control.RecoveryBudget(clock[0])
    return budget, clock


@pytest.fixture
def local_docker_model(admission_io, monkeypatch):
    budget, clock = admission_io
    state = {'show': b'default\n', 'inspect': json.dumps([{'Name': 'default',
        'Endpoints': {'docker': {'Host': 'unix:///var/run/docker.sock'}}}]).encode(),
        'calls': [], 'fault': None, 'advance': 0.0}
    def command(args, *, end, cap):
        budget.remaining(end=end)
        state['calls'].append((args, end, cap))
        if state['fault'] is not None:
            raise state['fault']
        if args == ['docker', 'context', 'show']:
            clock[0] += state['advance']
            budget.remaining(end=end)
            return state['show']
        assert args == ['docker', 'context', 'inspect', 'default']
        return state['inspect']
    monkeypatch.setattr(budget, 'command', command)
    return budget, clock, state


@pytest.mark.parametrize('remaining', [115, 3])
def test_local_docker_admission_shares_one_clipped_five_second_end(local_docker_model, remaining):
    budget, clock, state = local_docker_model
    budget.end = clock[0] + remaining
    state['advance'] = 1.0
    original_end = budget.end
    control.require_local_docker(budget)
    assert [args for args, _, _ in state['calls']] == [
        ['docker', 'context', 'show'], ['docker', 'context', 'inspect', 'default']]
    assert [end for _, end, _ in state['calls']] == [min(1005.0, original_end)] * 2
    assert all(cap == 4096 for _, _, cap in state['calls'])
    assert budget.end == original_end and budget.phase == 'construction'


@pytest.mark.parametrize('fault', ['darwin', 'win32', *_ADMISSION_OVERRIDES])
def test_local_docker_admission_refuses_host_or_forwarding_overrides_before_commands(local_docker_model, monkeypatch, fault):
    budget, _, state = local_docker_model
    if fault in ('darwin', 'win32'):
        monkeypatch.setattr(control.sys, 'platform', fault)
    else:
        monkeypatch.setenv(fault, 'private-override')
    with pytest.raises(control.RestoreUnavailable) as caught:
        control.require_local_docker(budget)
    assert caught.value.reason == 'source_binding' and not state['calls']
    assert 'private-override' not in str(caught.value)


@pytest.mark.parametrize('shown', [b'remote\n', b'default\nremote\n', b''])
def test_local_docker_admission_never_uses_inspected_default_for_another_effective_context(local_docker_model, shown):
    budget, _, state = local_docker_model
    state['show'] = shown
    with pytest.raises(control.RestoreUnavailable):
        control.require_local_docker(budget)
    assert len(state['calls']) == 1


@pytest.mark.parametrize('raw', [b'not-json', b'\xff', b'null', b'{}', b'[]', b'[{},{}]',
    b'[{"Name":"foreign","Endpoints":{"docker":{"Host":"unix:///var/run/docker.sock"}}}]',
    b'[{"Name":"default","Endpoints":null}]',
    b'[{"Name":"default","Endpoints":{"docker":{"Host":"tcp://127.0.0.1:2375"}}}]',
    b'[{"Name":"default","Endpoints":{"docker":{"Host":"ssh://host"}}}]',
    b'[{"Name":"default","Endpoints":{"docker":{"Host":"unix:///tmp/other.sock"}}}]'])
def test_local_docker_admission_requires_one_exact_local_default_endpoint(local_docker_model, raw):
    budget, _, state = local_docker_model
    state['inspect'] = raw
    with pytest.raises(control.RestoreUnavailable) as caught:
        control.require_local_docker(budget)
    assert caught.value.reason == 'source_binding' and len(state['calls']) == 2


@pytest.mark.parametrize('primary', [KeyboardInterrupt('owned cancel'), SystemExit(23),
    control.RestoreUnavailable('deadline')])
def test_local_docker_admission_preserves_command_failure_identity(local_docker_model, primary):
    budget, _, state = local_docker_model
    state['fault'] = primary
    with pytest.raises(type(primary)) as caught:
        control.require_local_docker(budget)
    assert caught.value is primary and len(state['calls']) == 1


def test_local_docker_admission_does_not_restart_expired_shared_subdeadline(local_docker_model):
    budget, _, state = local_docker_model
    state['advance'] = 5.001
    with pytest.raises(control.RestoreUnavailable) as caught:
        control.require_local_docker(budget)
    assert caught.value.reason == 'deadline' and len(state['calls']) == 1


@pytest.fixture
def internal_endpoint_model(admission_io, monkeypatch):
    budget, _ = admission_io
    owner = object.__new__(control.ResourceOwner)
    owner.nonce, owner.source, owner.budget = 'a'*32, 'e'*64, budget
    owner.child_owner = budget.context.owner
    owner.names = {'network': 'rf193_identity_net_' + owner.nonce,
        'database': 'rf193_identity_db_' + owner.nonce, 'auth': 'rf193_identity_auth_' + owner.nonce}
    owner.identities = {'network': 'b'*64, 'database': 'c'*64, 'auth': 'd'*64}
    owner._hba_commitment = ('b'*64, '172.28.0.0/24', '172.28.0.1', b'fixture-policy')
    owner.images = {'database': 'sha256:'+'1'*64, 'auth': 'sha256:'+'2'*64}
    owner.attempted = ['network', 'database', 'auth']
    labels = {owner.label: owner.nonce}
    network = {'Id': owner.identities['network'], 'Name': owner.names['network'],
        'Labels': dict(labels), 'Internal': True, 'Driver': 'bridge', 'Scope': 'local',
        'EnableIPv6': False, 'IPAM': {'Config': [{'Subnet': '172.28.0.0/24', 'Gateway': '172.28.0.1'}]},
        'Containers': {}}
    rows = {'network': network}
    for kind, ip, endpoint_id, port in (('database', '172.28.0.2', '3'*64, 5432),
                                       ('auth', '172.28.0.3', '4'*64, 9999)):
        network['Containers'][owner.identities[kind]] = {'Name': owner.names[kind],
            'EndpointID': endpoint_id, 'IPv4Address': ip+'/24', 'IPv6Address': ''}
        rows[kind] = {'Id': owner.identities[kind], 'Name': '/'+owner.names[kind],
            'Image': owner.images[kind], 'Config': {'Labels': dict(labels)},
            'State': {'Running': True, 'Restarting': False, 'Dead': False, 'Paused': False},
            'HostConfig': {'NetworkMode': owner.names['network'], 'PortBindings': {}, 'PublishAllPorts': False},
            'NetworkSettings': {'Ports': {str(port)+'/tcp': None}, 'Networks': {owner.names['network']: {
                'NetworkID': owner.identities['network'], 'EndpointID': endpoint_id,
                'IPAddress': ip, 'IPPrefixLen': 24, 'Gateway': '172.28.0.1',
                'GlobalIPv6Address': '', 'IPv6Gateway': ''}}}}
    state = {'calls': [], 'records': 0}
    def record(): state['records'] += 1
    monkeypatch.setattr(owner, '_record', record)
    def command(args, **kwargs):
        budget.remaining(end=kwargs.get('end'))
        state['calls'].append((args, kwargs))
        assert args[:2] in (['docker', 'network'], ['docker', 'container'])
        assert args[2] in ('ls', 'inspect')  # Exercise real inspect; no acquisition/removal allowed.
        if args[2] == 'ls':
            name = args[-1].removeprefix('name=')
            assert name in owner.names.values()
            return (json.dumps(name)+'\n').encode()
        kind = next(kind for kind, name in owner.names.items() if name == args[-1])
        return json.dumps([rows[kind]]).encode()
    monkeypatch.setattr(budget, 'command', command)
    return owner, rows, state


@pytest.mark.parametrize('ports', [None, [], 'empty'])
def test_internal_endpoint_admission_uses_real_owner_and_reciprocal_ip_not_published_port(internal_endpoint_model, ports):
    owner, rows, state = internal_endpoint_model
    for kind, port in (('database', 5432), ('auth', 9999)):
        rows[kind]['NetworkSettings']['Ports'] = {} if ports == 'empty' else {str(port)+'/tcp': ports}
    assert owner.internal_endpoints() == (('172.28.0.2', 5432), ('172.28.0.3', 9999))
    assert state['records'] == 3 and len(state['calls']) == 6
    assert all(0 < kwargs['cap'] <= 1024**2 for _, kwargs in state['calls'])


@pytest.mark.parametrize('fault',['missing','network','subnet','gateway'])
def test_owned_hba_live_admission_cannot_drop_or_drift_prestart_commitment(internal_endpoint_model,fault):
    owner, _, state=internal_endpoint_model
    if fault=='missing':del owner._hba_commitment
    else:
        bound=list(owner._hba_commitment)
        at={'network':0,'subnet':1,'gateway':2}[fault]
        bound[at]={'network':'9'*64,'subnet':'172.28.0.0/25','gateway':'172.28.0.254'}[fault]
        owner._hba_commitment=tuple(bound)
    with pytest.raises(control.RestoreUnavailable) as caught:owner.internal_endpoints()
    assert caught.value.reason=='source_binding'
    assert len(state['calls'])==2  # No service predicate/capture if network binding failed.


@pytest.mark.parametrize('path,value', [
    (('Id',), '9'*64), (('Name',), 'foreign'), (('Labels', control.ResourceOwner.label), 'foreign'),
    (('Internal',), False), (('Driver',), 'overlay'), (('Scope',), 'swarm'), (('EnableIPv6',), True),
    (('IPAM', 'Config'), []), (('IPAM', 'Config'), [{}, {}]),
    (('IPAM', 'Config', 0, 'Subnet'), '192.0.2.0/24'),
    (('IPAM', 'Config', 0, 'Subnet'), '127.0.0.0/24'),
    (('IPAM', 'Config', 0, 'Subnet'), '172.28.0.0/31'),
    (('IPAM', 'Config', 0, 'Gateway'), '172.29.0.1'),
    (('IPAM', 'Config', 0, 'Gateway'), 'not-an-address'),
    (('Containers',), {}), (('Containers', 'f'*64), {})])
def test_internal_endpoint_admission_rejects_foreign_or_unsupported_network(internal_endpoint_model, path, value):
    owner, rows, _ = internal_endpoint_model
    target = rows['network']
    for key in path[:-1]: target = target[key]
    target[path[-1]] = value
    with pytest.raises(control.RestoreUnavailable): owner.internal_endpoints()


@pytest.mark.parametrize('kind', ['database', 'auth'])
@pytest.mark.parametrize('fault', ['identity', 'image', 'label', 'stopped', 'restarting', 'dead', 'paused', 'paused-missing',
    'network-mode', 'extra-network', 'network-id', 'endpoint-id', 'prefix-type', 'prefix-value',
    'ipv6', 'outside', 'gateway', 'broadcast', 'network-address', 'publication-request',
    'publish-all', 'publication-binding', 'member-name', 'member-endpoint', 'member-prefix', 'member-ipv6'])
def test_internal_endpoint_admission_rejects_mismatched_service(internal_endpoint_model, kind, fault):
    owner, rows, _ = internal_endpoint_model
    row = rows[kind]
    settings = row['NetworkSettings']; endpoint = settings['Networks'][owner.names['network']]
    member = rows['network']['Containers'][owner.identities[kind]]
    if fault == 'identity': row['Id'] = owner.source
    elif fault == 'image': row['Image'] = 'sha256:'+'9'*64
    elif fault == 'label': row['Config']['Labels'][owner.label] = 'foreign'
    elif fault == 'stopped': row['State']['Running'] = False
    elif fault == 'restarting': row['State']['Restarting'] = True
    elif fault == 'dead': row['State']['Dead'] = True
    elif fault == 'paused': row['State']['Paused'] = True
    elif fault == 'paused-missing': del row['State']['Paused']
    elif fault == 'network-mode': row['HostConfig']['NetworkMode'] = 'host'
    elif fault == 'extra-network': settings['Networks']['other'] = dict(endpoint)
    elif fault == 'network-id': endpoint['NetworkID'] = '9'*64
    elif fault == 'endpoint-id': endpoint['EndpointID'] = 'not-an-id'
    elif fault == 'prefix-type': endpoint['IPPrefixLen'] = '24'
    elif fault == 'prefix-value': endpoint['IPPrefixLen'] = 23
    elif fault == 'ipv6': endpoint['GlobalIPv6Address'] = 'fd00::2'
    elif fault == 'outside': endpoint['IPAddress'] = '172.29.0.2'
    elif fault == 'gateway': endpoint['IPAddress'] = '172.28.0.1'
    elif fault == 'broadcast': endpoint['IPAddress'] = '172.28.0.255'
    elif fault == 'network-address': endpoint['IPAddress'] = '172.28.0.0'
    elif fault == 'publication-request': row['HostConfig']['PortBindings'] = {'5432/tcp': [{'HostIp': '127.0.0.1', 'HostPort': ''}]}
    elif fault == 'publish-all': row['HostConfig']['PublishAllPorts'] = True
    elif fault == 'publication-binding': settings['Ports'] = {'9999/tcp': [{'HostIp': '0.0.0.0', 'HostPort': '12345'}]}
    elif fault == 'member-name': member['Name'] = 'foreign'
    elif fault == 'member-endpoint': member['EndpointID'] = '9'*64
    elif fault == 'member-prefix': member['IPv4Address'] = endpoint['IPAddress']+'/23'
    elif fault == 'member-ipv6': member['IPv6Address'] = 'fd00::2/64'
    else: raise AssertionError(fault)
    with pytest.raises(control.RestoreUnavailable): owner.internal_endpoints()


def test_internal_endpoint_admission_rejects_duplicate_ipv4_even_with_matching_members(internal_endpoint_model):
    owner, rows, _ = internal_endpoint_model
    rows['auth']['NetworkSettings']['Networks'][owner.names['network']]['IPAddress'] = '172.28.0.2'
    rows['network']['Containers'][owner.identities['auth']]['IPv4Address'] = '172.28.0.2/24'
    with pytest.raises(control.RestoreUnavailable): owner.internal_endpoints()


@pytest.mark.parametrize('primary', [KeyboardInterrupt('inspect cancelled'), SystemExit(17),
    control.RestoreUnavailable('deadline')])
def test_internal_endpoint_admission_preserves_inspection_failure_identity(internal_endpoint_model, monkeypatch, primary):
    owner, _, state = internal_endpoint_model
    original = owner.inspect
    def inspect(kind, **kwargs):
        if kind == 'auth': raise primary
        return original(kind, **kwargs)
    monkeypatch.setattr(owner, 'inspect', inspect)
    with pytest.raises(type(primary)) as caught: owner.internal_endpoints()
    assert caught.value is primary and state['records'] == 2


@pytest.mark.parametrize('database_bindings', [None, {}], ids=['null', 'empty-dict'])
@pytest.mark.parametrize('auth_bindings', [None, {}], ids=['null', 'empty-dict'])
def test_internal_endpoint_admission_accepts_only_explicit_absent_publication_forms(
        internal_endpoint_model, database_bindings, auth_bindings):
    owner, rows, state = internal_endpoint_model
    rows['database']['HostConfig']['PortBindings'] = database_bindings
    rows['auth']['HostConfig']['PortBindings'] = auth_bindings
    assert owner.internal_endpoints() == (('172.28.0.2', 5432), ('172.28.0.3', 9999))
    assert state['records'] == 3 and len(state['calls']) == 6


@pytest.mark.parametrize('kind', ['database', 'auth'])
@pytest.mark.parametrize('bindings', [[], '', False, 0], ids=['list', 'string', 'bool', 'integer'])
def test_internal_endpoint_admission_rejects_falsey_malformed_port_bindings(
        internal_endpoint_model, kind, bindings):
    owner, rows, _ = internal_endpoint_model
    rows[kind]['HostConfig']['PortBindings'] = bindings
    with pytest.raises(control.RestoreUnavailable) as caught:
        owner.internal_endpoints()
    assert caught.value.reason == 'source_binding'


@pytest.mark.parametrize('kind', ['database', 'auth'])
def test_internal_endpoint_admission_requires_port_bindings_key(internal_endpoint_model, kind):
    owner, rows, _ = internal_endpoint_model
    del rows[kind]['HostConfig']['PortBindings']
    with pytest.raises(control.RestoreUnavailable) as caught:
        owner.internal_endpoints()
    assert caught.value.reason == 'source_binding'


@pytest.mark.parametrize('field,value', [
    ('Subnet', int.from_bytes(bytes([172, 28, 0, 0]), 'big')),
    ('Subnet', True), ('Subnet', None),
    ('Subnet', ' 172.28.0.0/24'), ('Subnet', '172.28.0.0/24 '),
    ('Subnet', '172.28.0.0/255.255.255.0'), ('Subnet', '172.28.0.0/024'),
    ('Subnet', '172.028.0.0/24'),
    ('Gateway', int.from_bytes(bytes([172, 28, 0, 1]), 'big')),
    ('Gateway', True), ('Gateway', None),
    ('Gateway', ' 172.28.0.1'), ('Gateway', '172.28.0.1 '),
    ('Gateway', '172.028.0.1'), ('Gateway', '172.28.0.01'),
    ('Gateway', '172.28.0.1/24')])
def test_internal_endpoint_admission_requires_canonical_ipam_strings(internal_endpoint_model, field, value):
    owner, rows, _ = internal_endpoint_model
    rows['network']['IPAM']['Config'][0][field] = value
    with pytest.raises(control.RestoreUnavailable) as caught:
        owner.internal_endpoints()
    assert caught.value.reason == 'source_binding'


@pytest.mark.parametrize('kind', ['database', 'auth'])
@pytest.mark.parametrize('form', ['integer', 'bool', 'null', 'leading-space', 'trailing-space',
    'zero-padded-octet', 'zero-padded-last-octet', 'cidr'])
def test_internal_endpoint_admission_requires_canonical_endpoint_ip_string(internal_endpoint_model, kind, form):
    owner, rows, _ = internal_endpoint_model
    endpoint = rows[kind]['NetworkSettings']['Networks'][owner.names['network']]
    original = endpoint['IPAddress']
    # Integer form denotes the same address; reciprocal member data stays valid.
    forms = {'integer': int.from_bytes(bytes(map(int, original.split('.'))), 'big'),
        'bool': True, 'null': None, 'leading-space': ' '+original,
        'trailing-space': original+' ', 'zero-padded-octet': original.replace('.28.', '.028.'),
        'zero-padded-last-octet': original[:-1]+'0'+original[-1], 'cidr': original+'/24'}
    endpoint['IPAddress'] = forms[form]
    with pytest.raises(control.RestoreUnavailable) as caught:
        owner.internal_endpoints()
    assert caught.value.reason == 'source_binding'


def test_endpoint_admission_classifies_first_service_running_refusal(internal_endpoint_model):
    owner, rows, state = internal_endpoint_model
    rows['database']['State']['Running'] = False
    with pytest.raises(control.RestoreUnavailable) as caught:
        owner.internal_endpoints()
    assert type(caught.value).__name__ == 'EndpointAdmissionFailure'
    assert caught.value.service == 'database' and caught.value.predicate == 'running'
    assert caught.value.reason == 'source_binding' and len(state['calls']) == 4


@pytest.mark.parametrize('kind', ['database', 'auth'])
@pytest.mark.parametrize('predicate', ['exists', 'running', 'paused', 'restarting', 'dead',
    'network_mode', 'publish_all_ports', 'port_bindings'])
def test_endpoint_admission_first_false_guard_is_lazy_closed_and_same_order(
        internal_endpoint_model, monkeypatch, kind, predicate):
    owner, rows, _ = internal_endpoint_model
    row = rows[kind]
    original = owner.inspect
    inspections = []
    def inspect(which, **kwargs):
        inspections.append(which)
        if which == kind and predicate == 'exists': return None
        return original(which, **kwargs)
    monkeypatch.setattr(owner, 'inspect', inspect)
    if predicate in ('running', 'paused', 'restarting', 'dead'):
        row['State'][predicate.title()] = predicate != 'running'
        # Later guards would raise TypeError if evaluated eagerly.
        row['HostConfig'] = None
    elif predicate == 'network_mode':
        row['HostConfig']['NetworkMode'] = 'private-wrong-network'
        del row['HostConfig']['PortBindings']
    elif predicate == 'publish_all_ports':
        row['HostConfig']['PublishAllPorts'] = True
        del row['HostConfig']['PortBindings']
    elif predicate == 'port_bindings':
        row['HostConfig']['PortBindings'] = []
        row['NetworkSettings'] = None
    with pytest.raises(control.EndpointAdmissionFailure) as caught:
        owner.internal_endpoints()
    error = caught.value
    assert type(error) is control.EndpointAdmissionFailure
    assert vars(error) == {'reason':'source_binding', 'service':kind, 'predicate':predicate}
    assert str(error) == 'restore_construction_unavailable'
    assert inspections == (['network', 'database'] if kind == 'database'
                           else ['network', 'database', 'auth'])


@pytest.mark.parametrize('kind', ['database', 'auth'])
@pytest.mark.parametrize('fault', ['state-null', 'state-list', 'running-missing',
    'host-null', 'mode-missing', 'bindings-missing'])
def test_endpoint_admission_malformed_access_remains_generic(internal_endpoint_model, kind, fault):
    owner, rows, _ = internal_endpoint_model
    row = rows[kind]
    if fault == 'state-null': row['State'] = None
    elif fault == 'state-list': row['State'] = []
    elif fault == 'running-missing': del row['State']['Running']
    elif fault == 'host-null': row['HostConfig'] = None
    elif fault == 'mode-missing': del row['HostConfig']['NetworkMode']
    elif fault == 'bindings-missing': del row['HostConfig']['PortBindings']
    with pytest.raises(control.RestoreUnavailable) as caught:
        owner.internal_endpoints()
    assert type(caught.value) is control.RestoreUnavailable
    assert vars(caught.value) == {'reason':'source_binding'}


@pytest.mark.parametrize('field,value', [('service', 'private-service'), ('service', False),
    ('service', ['database']), ('predicate', 'private-predicate'), ('predicate', 1),
    ('predicate', None)])
def test_endpoint_admission_exception_constructor_refuses_nonenum_inputs(field, value):
    args = {'service':'database', 'predicate':'exists'}
    args[field] = value
    with pytest.raises(control.RestoreUnavailable) as caught:
        control.EndpointAdmissionFailure(**args)
    assert type(caught.value) is control.RestoreUnavailable
    assert vars(caught.value) == {'reason':'source_binding'} and 'private-' not in str(caught.value)


@pytest.mark.parametrize('field', ['service', 'predicate'])
def test_endpoint_admission_exception_constructor_requires_exact_strings(field):
    class Text(str): pass
    args = {'service':'auth', 'predicate':'paused'}
    args[field] = Text(args[field])
    with pytest.raises(control.RestoreUnavailable) as caught:
        control.EndpointAdmissionFailure(**args)
    assert type(caught.value) is control.RestoreUnavailable


def auth_startup_record(message, **extra):
    return (json.dumps({'time':'2026-01-01T00:00:00Z', 'level':'fatal',
                        'msg':message, **extra})+'\n').encode()


@pytest.fixture
def auth_startup_model(internal_endpoint_model, monkeypatch):
    owner, rows, inspected = internal_endpoint_model
    owner.budget.enter('actors')
    rows['auth']['State'].update(Running=False, Status='exited', ExitCode=1, OOMKilled=False)
    model = {'raw':auth_startup_record('unable to load config', error='private-error-canary'),
             'calls':[], 'error':None, 'active':None}
    original = owner.budget.command
    def command(args, **kw):
        if args[0] != '/bin/sh': return original(args, **kw)
        model['calls'].append((args,kw)); model['active'] = sys.exception()
        if model['error'] is not None: raise model['error']
        return model['raw']
    monkeypatch.setattr(owner.budget, 'command', command)
    return owner, rows, inspected, model


def test_auth_startup_capture_preserves_active_primary_and_exact_owned_command(auth_startup_model):
    owner, rows, inspected, model = auth_startup_model
    old_end = owner.budget.end
    with pytest.raises(control.EndpointAdmissionFailure) as caught: owner.internal_endpoints()
    primary = caught.value
    assert model['active'] is primary and (primary.service,primary.predicate)==('auth','running')
    assert len(model['calls']) == 1 and len(inspected['calls']) == 6
    args,kw = model['calls'][0]
    assert args == ['/bin/sh','-c','exec docker logs --tail 128 "$1" 2>&1','auth-startup','d'*64]
    assert kw == {'cap':65536, 'end':1004.0}
    value = primary.auth_startup
    assert value['classification'] == {'stage':'serve_config','reportedSQLSTATE':None}
    assert value['state'] == {'status':'exited','exitCode':1,'oomKilled':False}
    assert value['tail'] == {'bytes':len(model['raw']), 'sha256':hashlib.sha256(model['raw']).hexdigest(),
                             'records':1,'fatalRecords':1}
    assert control.validate_auth_startup(value) is value
    assert 'private-error-canary' not in json.dumps(value)
    assert owner.budget.end == old_end and owner.budget.phase == 'actors'


def auth_startup_wrapped(cause='private-cause', label='checking database connection', line=74,
                         *, architecture='amd64', prefix='/go/src/'):
    return (cause+'\n'+label+'\ngithub.com/supabase/auth/cmd.migrate\n\t'+prefix+
            'github.com/supabase/auth/cmd/migrate_cmd.go:'+str(line)+
            '\nruntime.goexit\n\t/go/src/runtime/asm_'+architecture+'.s:100')


def auth_startup_observe(model, raw):
    owner, _, _, state = model; state['raw'] = raw
    with pytest.raises(control.EndpointAdmissionFailure) as caught: owner.internal_endpoints()
    assert state['active'] is caught.value
    return caught.value.auth_startup


def test_auth_startup_migration_transaction_reports_canonical_code(auth_startup_model):
    message = ("running db migrations: Migrator: problem creating schema migrations: "
               "couldn't start a new transaction: could not create new transaction: "
               "FATAL: private-migration-canary (SQLSTATE 28P01)")
    value = auth_startup_observe(auth_startup_model, auth_startup_record(message))
    assert value['classification'] == {'stage':'migration_apply', 'reportedSQLSTATE':'28P01'}
    assert 'private-migration-canary' not in json.dumps(value)


AUTH_STARTUP_MIGRATION_CHAINS = (
    "running db migrations: Migrator: problem creating schema migrations: "
    "couldn't start a new transaction: could not create new transaction: ",
    "running db migrations: couldn't start a new transaction: "
    "could not create new transaction: ")


@pytest.mark.parametrize('chain', AUTH_STARTUP_MIGRATION_CHAINS)
@pytest.mark.parametrize('layout', ['direct','server error','failed SASL auth'])
@pytest.mark.parametrize('code', ['28P01','28000','3D000','42501'])
@pytest.mark.parametrize('severity', ['FATAL','ERROR'])
def test_auth_startup_migration_exact_chains_report_only_finite_code(
        auth_startup_model, chain, layout, code, severity):
    cause = severity+': private-migration-canary (SQLSTATE '+code+')'
    if layout != 'direct':
        cause = 'failed to connect to `host=private-host user=private-user database=private-db`: '+layout+' ('+cause+')'
    value = auth_startup_observe(auth_startup_model, auth_startup_record(chain+cause))
    assert value['schema'] == 'rf1086-auth-startup-tail-v2'
    assert value['evidence'] == 'source-pattern-compatible-only'
    assert value['classification'] == {'stage':'migration_apply','reportedSQLSTATE':code}
    assert control.validate_auth_startup(value) is value
    assert 'private-' not in json.dumps(value)


@pytest.mark.parametrize('chain', AUTH_STARTUP_MIGRATION_CHAINS)
@pytest.mark.parametrize('fault', ['first-wrapper','second-wrapper','both-wrappers',
    'reorder','duplicate','outer-wrapper','sql-prefix','path-prefix','fake-wrapper',
    'severity','code','extra-eof','nested-code','lf','cr','nul','tab','c0','del','c1',
    'unicode-message','message-empty','message-large','parentheses','backtick',
    'connection-stage','atom-empty','atom-large','atom-space','atom-unicode',
    'atom-delimiter','duplicate-cause'])
def test_auth_startup_migration_unsupported_message_keeps_stage_without_code(
        auth_startup_model, chain, fault):
    cause = 'FATAL: private-canary (SQLSTATE 28P01)'
    if fault == 'first-wrapper': chain = chain.replace("couldn't start a new transaction: ", '')
    elif fault == 'second-wrapper': chain = chain.replace('could not create new transaction: ', '')
    elif fault == 'both-wrappers': chain = 'running db migrations: '
    elif fault == 'reorder': chain = chain.replace(
        "couldn't start a new transaction: could not create new transaction: ",
        "could not create new transaction: couldn't start a new transaction: ")
    elif fault == 'duplicate': chain += 'could not create new transaction: '
    elif fault == 'outer-wrapper': chain = 'running db migrations: private-wrapper: '+chain
    elif fault == 'sql-prefix': chain += 'could not execute SELECT private: '
    elif fault == 'path-prefix': chain += 'error executing private.sql, sql: SELECT private: '
    elif fault == 'fake-wrapper': chain = chain.replace('could not create', 'could not Create')
    elif fault == 'severity': cause = cause.replace('FATAL:', 'PANIC:')
    elif fault == 'code': cause = cause.replace('28P01', 'XX999')
    elif fault == 'extra-eof': cause += ' private-trailing'
    elif fault == 'nested-code': cause = cause.replace('private-canary', 'private (SQLSTATE 42501)')
    elif fault in ('lf','cr','nul','tab','c0','del','c1'):
        cause = cause.replace('private-canary', 'private'+{
            'lf':'\n','cr':'\r','nul':'\0','tab':'\t','c0':'\x01','del':'\x7f','c1':'\x85'}[fault]+'canary')
    elif fault == 'unicode-message': cause = cause.replace('private-canary', 'private-ø')
    elif fault == 'message-empty': cause = cause.replace('private-canary', '')
    elif fault == 'message-large': cause = cause.replace('private-canary', 'x'*1025)
    elif fault == 'parentheses': cause = cause.replace('private-canary', 'private(nested)')
    elif fault == 'backtick': cause = cause.replace('private-canary', 'private`canary')
    elif fault == 'duplicate-cause': cause += ' '+cause
    else:
        atom = {'atom-empty':'','atom-large':'x'*257,'atom-space':'private value',
            'atom-unicode':'privaté','atom-delimiter':'private`'}
        stage = 'unknown' if fault == 'connection-stage' else 'server error'
        cause = ('failed to connect to `host='+atom.get(fault,'private')+
                 ' user=private database=private`: '+stage+' ('+cause+')')
    value = auth_startup_observe(auth_startup_model, auth_startup_record(chain+cause))
    assert value['classification'] == {'stage':'migration_apply','reportedSQLSTATE':None}
    assert 'private' not in json.dumps(value)


@pytest.mark.parametrize('leader', ['prefix ', ' ', '\n'])
def test_auth_startup_migration_chain_cannot_be_found_inside_other_text(auth_startup_model, leader):
    message = leader+AUTH_STARTUP_MIGRATION_CHAINS[0]+'FATAL: private (SQLSTATE 28P01)'
    value = auth_startup_observe(auth_startup_model, auth_startup_record(message))
    assert value['classification'] is None


@pytest.mark.parametrize('layout', ['direct','server error','failed SASL auth'])
def test_auth_startup_migration_private_atoms_at_exact_bounds(auth_startup_model, layout):
    cause = 'ERROR: '+('x'*1024)+' (SQLSTATE 42501)'
    if layout != 'direct':
        cause = ('failed to connect to `host='+('h'*256)+' user='+('u'*256)+
                 ' database='+('d'*256)+'`: '+layout+' ('+cause+')')
    value = auth_startup_observe(auth_startup_model, auth_startup_record(AUTH_STARTUP_MIGRATION_CHAINS[1]+cause))
    assert value['classification'] == {'stage':'migration_apply','reportedSQLSTATE':'42501'}


@pytest.mark.parametrize('error', [control.RestoreUnavailable('deadline'),
    KeyboardInterrupt('private-cancel'), SystemExit('private-exit')])
def test_auth_startup_migration_parser_failure_preserves_primary_and_cancellation(
        auth_startup_model, monkeypatch, error):
    owner, _, _, model = auth_startup_model
    prior = signal.getsignal(signal.SIGALRM)
    def fail(cause): raise error
    monkeypatch.setattr(control, '_auth_startup_sqlstate', fail)
    value = auth_startup_observe(auth_startup_model, auth_startup_record(
        AUTH_STARTUP_MIGRATION_CHAINS[0]+'FATAL: private (SQLSTATE 28P01)'))
    assert value is None and owner.budget.context.owner.primary is model['active']
    assert owner.budget.context.owner.cancelled == (not isinstance(error, Exception))
    assert signal.getsignal(signal.SIGALRM) is prior and signal.getitimer(signal.ITIMER_REAL) == (0,0)


@pytest.mark.parametrize('message,stage', [
    ('unable to load config','serve_config'), ('http server listen failed','http_listen'),
    ('http server serve failed','http_serve'), ('Failed to load configuration: private','initial_config'),
    ('Failed to parse log level: private','logging_level'), ('error opening database: private','serve_database'),
    ('running db migrations: private','migration_apply'),
    *[(auth_startup_wrapped(label=label,line=line),stage) for label,line,stage in [
      ('parsing db connection url',27,'migration_database_url'),
      ('opening db connection',69,'migration_connection_open'),
      ('checking database connection',74,'migration_connection_check'),
      ('creating db migrator',80,'migration_setup'),
      ('migration status',90,'migration_status'),('migration status',109,'migration_status')]]])
def test_auth_startup_closed_twelve_stages_from_complete_fatal_record(auth_startup_model, message, stage):
    result = auth_startup_observe(auth_startup_model, auth_startup_record(message))
    assert result['classification'] == {'stage':stage,'reportedSQLSTATE':None}
    assert 'private' not in json.dumps(result)


@pytest.mark.parametrize('architecture,prefix', [('amd64','/go/src/'),('arm64','')])
def test_auth_startup_terminal_runtime_assembly_and_nested_cause(auth_startup_model, architecture, prefix):
    message = auth_startup_wrapped('private-cause\nprivate.wrapper\n\t/module/source.go:12',
                                   architecture=architecture,prefix=prefix)
    assert auth_startup_observe(auth_startup_model, auth_startup_record(message))['classification'] == {
        'stage':'migration_connection_check','reportedSQLSTATE':None}


@pytest.mark.parametrize('frames', [1,32])
def test_auth_startup_accepts_bounded_frames_without_requiring_goexit(auth_startup_model, frames):
    message = auth_startup_wrapped().rsplit('\nruntime.goexit',1)[0]
    message += '\nmodule.fn\n\t/go/src/module/file.go:1'*(frames-1)
    assert auth_startup_observe(auth_startup_model, auth_startup_record(message))['classification']['stage'] == 'migration_connection_check'


@pytest.mark.parametrize('code', ['28P01','28000','3D000','42501'])
@pytest.mark.parametrize('layout', ['direct','server error','failed SASL auth'])
@pytest.mark.parametrize('label,line,stage', [
    ('parsing db connection url',27,'migration_database_url'),
    ('opening db connection',69,'migration_connection_open'),
    ('checking database connection',74,'migration_connection_check'),
    ('creating db migrator',80,'migration_setup'),
    ('migration status',90,'migration_status'),('migration status',109,'migration_status')])
def test_auth_startup_sqlstate_requires_whole_canonical_cause(auth_startup_model, code, layout, label, line, stage):
    cause = 'FATAL: private authentication failure (SQLSTATE '+code+')'
    if layout != 'direct': cause = 'failed to connect to `host=private user=private database=private`: '+layout+' ('+cause+')'
    result = auth_startup_observe(auth_startup_model, auth_startup_record(auth_startup_wrapped(cause,label,line)))
    assert result['classification'] == {'stage':stage,'reportedSQLSTATE':code}
    assert 'private' not in json.dumps(result)


@pytest.mark.parametrize('cause', [
    'FATAL: private (SQLSTATE 28P01)\nextra',
    'FATAL: private (SQLSTATE 28P01)\nmodule.fn\n\t/module/private.go:12',
    'FATAL: private (SQLSTATE 28P01)\nFATAL: private (SQLSTATE 42501)',
    'outer: FATAL: private (SQLSTATE 28P01)', 'FATAL: private (SQLSTATE ZZ999)',
    'FATAL: private (nested) (SQLSTATE 28P01)', 'FATAL: private`value (SQLSTATE 28P01)',
    'FATAL: private (SQLSTATE 28P01) trailing',
    'FATAL: fake (SQLSTATE 42501) (SQLSTATE 28P01)',
    'failed to connect to `host=private user=private database=private`: other (FATAL: private (SQLSTATE 28P01))'])
def test_auth_startup_multiline_or_unsupported_cause_preserves_stage_without_code(auth_startup_model, cause):
    result = auth_startup_observe(auth_startup_model, auth_startup_record(auth_startup_wrapped(cause)))
    assert result['classification'] == {'stage':'migration_connection_check','reportedSQLSTATE':None}


@pytest.mark.parametrize('fault', ['function','path','line','wrong-label-line','duplicate-label',
    'trailing-lf','trailing-text','missing-tab','odd','unknown','assembly-function','assembly-directory',
    'assembly-architecture','nonfinal-assembly','repeated-assembly','dotdot','zero-line','large-line',
    '33frames','long-component','long-cause','many-lines','cr','nul','control','fake-prefix'])
def test_auth_startup_malformed_wrapped_layout_stays_unclassified(auth_startup_model, fault):
    message = auth_startup_wrapped()
    if fault=='function': message=message.replace('cmd.migrate','cmd.serve')
    elif fault=='path': message=message.replace('/cmd/migrate_cmd.go','/other/migrate_cmd.go')
    elif fault=='line': message=message.replace('.go:74','.go:75')
    elif fault=='wrong-label-line': message=message.replace('checking database connection','opening db connection')
    elif fault=='duplicate-label': message='checking database connection\n'+message
    elif fault=='trailing-lf': message+='\n'
    elif fault=='trailing-text': message+='\nprivate-extra'
    elif fault=='missing-tab': message=message.replace('\n\t','\n',1)
    elif fault=='odd': message+='\nmodule.fn'
    elif fault=='unknown': message=message.replace('/cmd/migrate_cmd.go','/cmd/unknown')
    elif fault=='assembly-function': message=message.replace('runtime.goexit','runtime.other')
    elif fault=='assembly-directory': message=message.replace('/runtime/asm_','/other/asm_')
    elif fault=='assembly-architecture': message=message.replace('asm_amd64.s','asm_386.s')
    elif fault=='nonfinal-assembly': message+='\nmodule.fn\n\t/module/file.go:1'
    elif fault=='repeated-assembly': message+='\nruntime.goexit\n\t/runtime/asm_amd64.s:1'
    elif fault=='dotdot': message=message.replace('/cmd/','/../cmd/')
    elif fault=='zero-line': message=message.replace('.s:100','.s:0')
    elif fault=='large-line': message=message.replace('.s:100','.s:1000000')
    elif fault=='33frames': message=message.rsplit('\nruntime.goexit',1)[0]+'\nmodule.fn\n\t/module/file.go:1'*32
    elif fault=='long-component': message=message.replace('/cmd/', '/'+('x'*1024)+'/cmd/')
    elif fault=='long-cause': message=message.replace('private-cause','x'*2049)
    elif fault=='many-lines': message=message.replace('private-cause','x\n'*160)
    elif fault=='cr': message=message.replace('private-cause','private\rvalue')
    elif fault=='nul': message=message.replace('private-cause','private\0value')
    elif fault=='control': message=message.replace('private-cause','private\x01value')
    elif fault=='fake-prefix': message='contains checking database connection only'
    assert auth_startup_observe(auth_startup_model, auth_startup_record(message))['classification'] is None


@pytest.mark.parametrize('character', ['\x7f', '\x80', '\x85', '\x9f'])
def test_auth_startup_del_and_c1_in_opaque_cause_decline_classification(auth_startup_model, character):
    message = auth_startup_wrapped('private'+character+'cause')
    value = auth_startup_observe(auth_startup_model, auth_startup_record(message))
    assert value['classification'] is None and value['tail']['fatalRecords'] == 1


@pytest.mark.parametrize('raw', [b'\n',b'{}',b'{}\n',b'[]\n',b'null\n',b'\xff\n',
    b'{"time":"x","level":"fatal","msg":"unable to load config","msg":"other"}\n',
    b'{"time":"x","level":"fatal","msg":"unable to load config","count":true}\n',
    b'{"time":"x","level":"fatal","msg":"unable to load config","count":NaN}\n',
    b'{"time":"x","level":"fatal","msg":"unable to load config","extra":"private"}\n',
    b'{"time":"x","level":"fatal","msg":"unable to load config","error":{}}\n',
    b'{"time":"x","level":"fatal","msg":"\\ud800"}\n',
    auth_startup_record('x').replace(b'\n',b'\r\n'), auth_startup_record('x')+b'bad',
    auth_startup_record('x'*16384),auth_startup_record('x')*129,b'x'*65537])
def test_auth_startup_invalid_or_over_limit_tail_is_entirely_unavailable(auth_startup_model, raw):
    assert auth_startup_observe(auth_startup_model,raw) is None


@pytest.mark.parametrize('raw,records,fatals', [(b'',0,0),
    (auth_startup_record('private',level='info'),1,0),
    (auth_startup_record('unable to load config')*2,2,2),
    (auth_startup_record('private',level='info')*128,128,0)])
def test_auth_startup_empty_or_ambiguous_tail_never_claims_absence(auth_startup_model,raw,records,fatals):
    value=auth_startup_observe(auth_startup_model,raw)
    assert value['classification'] is None and value['tail']['records']==records
    assert value['tail']['fatalRecords']==fatals


@pytest.mark.parametrize('field,value', [('Running',0),('Paused',None),('Restarting',True),
    ('Dead',None),('Dead',True),('OOMKilled',None),('Status','running'),('Status',None),
    ('ExitCode',True),('ExitCode',-1),('ExitCode',256)])
def test_auth_startup_malformed_same_state_skips_command(auth_startup_model,field,value):
    owner,rows,_,model=auth_startup_model;rows['auth']['State'][field]=value
    with pytest.raises(control.EndpointAdmissionFailure) as caught:owner.internal_endpoints()
    assert caught.value.auth_startup is None and not model['calls']


@pytest.mark.parametrize('phase,remaining', [('construction',35),('actors',4.25),('actors',4),('cleanup',15)])
def test_auth_startup_only_actors_with_full_headroom_capture(auth_startup_model,phase,remaining):
    owner,_,_,model=auth_startup_model;owner.budget.phase=phase;owner.budget.end=1000+remaining
    with pytest.raises(control.EndpointAdmissionFailure) as caught:owner.internal_endpoints()
    assert getattr(caught.value,'auth_startup',None) is None and not model['calls']


@pytest.mark.parametrize('error', [ValueError('private-error'),control.RestoreUnavailable('deadline'),
    KeyboardInterrupt('private-cancel'),SystemExit('private-exit')])
def test_auth_startup_capture_fault_keeps_original_primary_and_fatal_state(auth_startup_model,error):
    owner,_,_,model=auth_startup_model;model['error']=error
    with pytest.raises(control.EndpointAdmissionFailure) as caught:owner.internal_endpoints()
    assert caught.value is model['active'] and caught.value.auth_startup is None
    assert owner.budget.context.owner.primary is caught.value
    assert owner.budget.context.owner.cancelled == (not isinstance(error,Exception))
    events=[]
    try:raise caught.value
    except control.EndpointAdmissionFailure:
        with pytest.raises(control.EndpointAdmissionFailure) if not isinstance(error,Exception) else control.nullcontext():
            with control.unwind_scope(owner.budget):
                owner.budget.enter('cleanup');events.append('cleanup')
                owner.budget.enter('source_post');events.append('source_post')
    assert events==['cleanup','source_post']


def test_auth_startup_once_and_uncertain_child_cannot_publish(auth_startup_model,monkeypatch):
    owner,rows,_,model=auth_startup_model
    primary=control.EndpointAdmissionFailure('auth','running')
    def command(*args,**kw):
        owner.budget.context.owner._uncertain('wait',OSError('private'),ValueError('secondary'))
        return model['raw']
    monkeypatch.setattr(owner.budget,'command',command)
    try:raise primary
    except control.EndpointAdmissionFailure:
        control._capture_auth_startup(owner,rows['auth'],primary)
    assert primary.auth_startup is None and owner.budget.context.owner.primary is primary
    monkeypatch.setattr(owner.budget,'command',lambda *a,**kw:pytest.fail('repeated capture'))
    control._capture_auth_startup(owner,rows['auth'],primary)


@pytest.mark.parametrize('where', ['command','parse'])
def test_auth_startup_expiry_during_capture_discards_value_and_restores_alarm(auth_startup_model,monkeypatch,where):
    owner,_,_,model=auth_startup_model; prior=signal.getsignal(signal.SIGALRM)
    def expired(*a,**kw):
        monkeypatch.setattr(control.time,'monotonic',lambda:1005)
        return (dict(bytes=0,sha256=hashlib.sha256(b'').hexdigest(),records=0,fatalRecords=0),None) if where=='parse' else model['raw']
    if where=='parse':monkeypatch.setattr(control,'_auth_startup_tail',expired)
    else:
        original=owner.budget.command
        monkeypatch.setattr(owner.budget,'command',lambda args,**kw:expired() if args[0]=='/bin/sh' else original(args,**kw))
    with pytest.raises(control.EndpointAdmissionFailure) as caught:owner.internal_endpoints()
    assert caught.value.auth_startup is None and signal.getsignal(signal.SIGALRM) is prior
    assert signal.getitimer(signal.ITIMER_REAL)==(0,0)


@pytest.mark.parametrize('fault', ['source-short','source-bool','database-missing','auth-uppercase',
    'same-identity','image-short','image-missing'])
def test_auth_startup_unbound_identity_or_image_skips_tail(auth_startup_model, fault):
    owner, _, _, model = auth_startup_model
    if fault == 'source-short': owner.source = 'a'*63
    elif fault == 'source-bool': owner.source = True
    elif fault == 'database-missing': del owner.identities['database']
    elif fault == 'auth-uppercase': owner.identities['auth'] = 'D'*64
    elif fault == 'same-identity': owner.source = owner.identities['database']
    elif fault == 'image-short': owner.images['auth'] = 'sha256:123'
    else: del owner.images['auth']
    primary = control.EndpointAdmissionFailure('auth','running')
    # Test capture's independent binding check, without weakening earlier inspect checks.
    control._capture_auth_startup(owner, {'State':dict(Running=False, Paused=False,
        Restarting=False, Dead=False, OOMKilled=False, Status='exited', ExitCode=1)}, primary)
    assert primary.auth_startup is None and not model['calls']


@pytest.mark.parametrize('kind', ['database','other-predicate','subclass','chain'])
def test_auth_startup_capture_does_not_follow_ineligible_primary(auth_startup_model, kind):
    owner, rows, _, model = auth_startup_model
    class Child(control.EndpointAdmissionFailure): pass
    primary = (Child('auth','running') if kind == 'subclass' else
        control.EndpointAdmissionFailure('database' if kind == 'database' else 'auth',
                                        'dead' if kind == 'other-predicate' else 'running'))
    if kind == 'chain':
        outer = ValueError('private-outer'); outer.__cause__ = primary; primary = outer
    control._capture_auth_startup(owner, rows['auth'], primary)
    assert not model['calls'] and not hasattr(primary,'auth_startup')


@pytest.mark.parametrize('mode', ['complete','nonzero','cap','partial','acquire-cancel','drain-cancel'])
def test_auth_startup_generated_owned_pipe_merges_drains_refuses_and_reaps(monkeypatch,children,mode):
    # Substitute only the command boundary with a generated local Python child.
    # No Docker, service, network or actual log is involved.
    import socket
    monkeypatch.setattr(socket,'create_connection',lambda *a,**kw:pytest.fail('network forbidden'))
    owner = object.__new__(control.ResourceOwner)
    owner.source = 'a'*64; owner.identities = {'database':'b'*64,'auth':'c'*64}
    owner.images = {'auth':'sha256:'+'d'*64}
    owner.budget = control.RecoveryBudget(time.monotonic()); owner.budget.enter('actors')
    state = {'State':dict(Running=False,Paused=False,Restarting=False,Dead=False,
                         OOMKilled=False,Status='exited',ExitCode=1)}
    primary = control.EndpointAdmissionFailure('auth','running'); cancellation = KeyboardInterrupt('private-token')
    first = auth_startup_record('private-info',level='info')
    second = auth_startup_record(auth_startup_wrapped('FATAL: private (SQLSTATE 28P01)'))
    if mode == 'cap': second = b'x'*65537
    if mode == 'partial': second = second[:-1]
    program = f'import os;os.write(1,{first!r});os.write(2,{second!r});raise SystemExit({7 if mode=="nonzero" else 0})'
    command = control.commands._command; observed = []
    def generated(args, deadline, **options):
        assert args == ['/bin/sh','-c','exec docker logs --tail 128 "$1" 2>&1','auth-startup','c'*64]
        assert sys.exception() is primary
        assert options['reap_deadline']-deadline == 2 and options['stdout_cap'] == 65536
        assert options['child_owner'] is owner.budget.context.owner
        observed.append(args)
        return command(['/bin/sh','-c','exec "$1" -B -c "$2" 2>&1',
                        'generated-auth-tail',sys.executable,program],deadline,**options)
    monkeypatch.setattr(control.commands,'_command',generated)
    if mode == 'acquire-cancel':
        start = control.subprocess.Popen
        def cancel_start(*args,**kw):
            child = start(*args,**kw)
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
            return child
        monkeypatch.setattr(control.subprocess,'Popen',cancel_start)
    elif mode == 'drain-cancel':
        read = control.commands.os.read
        def cancel_read(fd, size):
            if children and fd in (children[0].stdout.fileno(),children[0].stderr.fileno()):
                raise cancellation
            return read(fd,size)
        monkeypatch.setattr(control.commands.os,'read',cancel_read)
    old_handler = signal.getsignal(signal.SIGALRM); old_alarm = signal.getitimer(signal.ITIMER_REAL)
    try:
        signal.setitimer(signal.ITIMER_REAL,.75)
        try: raise primary
        except control.EndpointAdmissionFailure:
            control._capture_auth_startup(owner,state,primary)
        assert signal.getsignal(signal.SIGALRM) is old_handler
        assert 0 < signal.getitimer(signal.ITIMER_REAL)[0] <= .75
    finally:
        signal.setitimer(signal.ITIMER_REAL,*old_alarm)
    assert len(observed)==1 and len(children)==1 and children[0].returncode is not None
    assert all(slot.process is None for slot in owner.budget.context.owner.slots)
    assert owner.budget.context.owner.primary is primary
    if mode == 'complete':
        assert primary.auth_startup['tail']['sha256'] == hashlib.sha256(first+second).hexdigest()
        assert primary.auth_startup['tail']['records'] == 2
        assert primary.auth_startup['classification'] == {'stage':'migration_connection_check','reportedSQLSTATE':'28P01'}
    else: assert primary.auth_startup is None
    assert owner.budget.context.owner.cancelled == mode.endswith('cancel')
