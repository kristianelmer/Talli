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
