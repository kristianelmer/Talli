"""Lost CREATE responses cannot erase database acquisition ownership evidence."""
import json
import time
from types import SimpleNamespace

import pytest

from test_rf1086_owned_restore_runner import runner
import rf1086_database_clone_owner as clone_owner
import rf1086_restore_control as control


@pytest.fixture
def model(tmp_path,monkeypatch):
    directory=tmp_path/'ownership';directory.mkdir()
    monkeypatch.setattr(clone_owner.tempfile,'mkdtemp',lambda **kw:str(directory))
    budget=control.RecoveryBudget(time.monotonic());calls=[]
    state={'database':None,'failure':None,'system':'1234'}
    token=KeyboardInterrupt('created response lost')
    def checked(args,**kwargs):
        calls.append((args,kwargs,budget.phase,budget.end))
        operation=args[4]
        if operation=='psql':
            raw=json.dumps([state['system'],'postgres',state['database']]).encode()
            return SimpleNamespace(stdout=raw)
        if operation=='createdb':
            saved=json.loads((directory/'owner.json').read_bytes())
            assert saved['createAttempted'] and saved['absentBefore'] and not saved['createComplete']
            if state['failure']!='before-create':state['database']=['17000','supabase_admin',False]
            if state['failure'] in ('after-create','before-create'):
                budget.context.owner._cancel(token)
                raise token
        if operation=='dropdb':
            assert args[-1].startswith('rf193_restore_') and args[-1]!='postgres'
            state['database']=None
        return SimpleNamespace(stdout=b'')
    monkeypatch.setattr(budget,'checked',checked)
    owner=clone_owner.DatabaseCloneOwner('a'*64,'postgres','rf193_restore_'+'b'*32,budget)
    return owner,budget,state,calls,token


def test_successful_clone_creation_and_removal_are_observed_on_same_source(model):
    owner,budget,state,calls,_=model;initial_end=budget.end
    owner.create();assert owner.oid=='17000'
    assert owner.record.stat().st_mode&0o777==0o600
    with control.unwind_scope(budget):owner.cleanup()
    assert state['database'] is None and not owner.directory.exists()
    assert all(phase=='construction' and end==initial_end for _,_,phase,end in calls)
    assert [args[4] for args,_,_,_ in calls]==['psql','createdb','psql','psql','dropdb','psql']


@pytest.mark.parametrize('failure',['after-create','before-create'])
def test_lost_create_response_retains_record_even_after_present_absence(model,failure):
    owner,budget,state,calls,token=model;state['failure']=failure
    with pytest.raises(KeyboardInterrupt) as caught:
        try:owner.create()
        finally:
            with control.unwind_scope(budget):owner.cleanup()
    assert caught.value is token and state['database'] is None
    assert owner.record.exists() and not json.loads(owner.record.read_bytes())['createComplete']
    drops=[a for a,_,_,_ in calls if a[4]=='dropdb']
    assert len(drops)==int(failure=='after-create')


@pytest.mark.parametrize('change',['owner','oid','system'])
def test_changed_database_identity_never_authorizes_drop(model,change):
    owner,budget,state,calls,_=model;owner.create()
    if change=='owner':state['database'][1]='different_owner'
    if change=='oid':state['database'][0]='18000'
    if change=='system':state['system']='2345'
    with pytest.raises(control.RestoreUnavailable):owner.cleanup()
    assert owner.record.exists() and not any(a[4]=='dropdb' for a,_,_,_ in calls)


def test_preexisting_nonce_database_refuses_without_acquisition_or_deletion(model):
    owner,budget,state,calls,_=model;state['database']=['17000','supabase_admin',False]
    with pytest.raises(control.RestoreUnavailable):owner.create()
    owner.cleanup()
    assert state['database'] and not owner.directory.exists()
    assert not any(a[4] in ('createdb','dropdb') for a,_,_,_ in calls)


def test_live_command_slot_retains_owner_record_even_after_database_removed(model):
    owner,budget,state,calls,_=model;owner.create()
    owner.child_owner.slots[0].process=object()
    with pytest.raises(control.RestoreUnavailable):owner.cleanup()
    assert owner.record.exists() and state['database'] is None
    owner.child_owner.slots[0].process=None


def test_wrapper_reconciles_lost_response_and_still_checks_roles(model,monkeypatch):
    owner,budget,state,calls,token=model;state['failure']='after-create';checks=[]
    monkeypatch.setattr(clone_owner,'DatabaseCloneOwner',lambda *args:owner)
    monkeypatch.setattr(runner.boundary,'owned_source',lambda *a:('a'*64,'postgres'))
    monkeypatch.setattr(runner.boundary,'verify_source_session',lambda *a,**kw:None)
    def memberships(*a,**kw):checks.append(budget.phase);return []
    monkeypatch.setattr(runner.boundary,'role_memberships',memberships)
    with pytest.raises(KeyboardInterrupt) as caught:
        with runner.restored_database('dbname=postgres','owned',budget=budget):
            raise AssertionError('unadmitted clone yielded')
    assert caught.value is token and checks==['construction','construction']
    assert owner.record.exists() and state['database'] is None
