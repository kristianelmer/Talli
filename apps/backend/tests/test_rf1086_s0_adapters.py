"""Typed S0 publication preserves durable F2 and explicit command ownership."""
from copy import deepcopy
import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from test_rf1086_actual_replay import setup, key, aad
from test_rf1086_full_sql_control import control, completed
import rf1086_actual_replay as replay
import rf1086_actual_replay_package as package
import rf1086_catalog_causal_capture as capture
import rf1086_identity_restore as identity


def test_durable_checkpoint_keeps_literal_and_full_result_requires_typed_s0(control):
    path, metadata, f2, optional, _, _ = control
    replay.checkpoint_f2(path, metadata, f2)
    assert replay.read_f2(path, metadata) == f2 and f2['S0'] == 'unavailable'
    value = completed(f2, optional)
    assert replay.validate_control(value, metadata) is value
    assert f2['S0'] == 'unavailable'
    for corrupt in [value | {'S0': 'unavailable'}, value | {'schema': 'actual-image-control-v1'},
                    value | {'Fsql': optional | {'S0': value['S0']}}, f2 | {'Fsql': optional}]:
        with pytest.raises(package.Unavailable): replay.validate_control(corrupt, metadata)
    with pytest.raises(package.Unavailable): replay.validate_f2(value, metadata)


@pytest.mark.parametrize('reason', ['consumer_failed', 'worker_deadline', 'worker_failed', 'worker_result_invalid'])
def test_thin_control_is_closed_and_parent_redaction_is_checked(control, reason):
    _, metadata, _, _, _, _ = control
    value = replay.thin_control(reason)
    assert replay.validate_control(value, metadata) == value
    published = value | {'optionalWorkerOutcome': 'completed', 'ownedCleanupComplete': True}
    assert replay.validate_published_control(published, metadata) == published
    redacted = published | {'ownedCleanupComplete': False, 'S0': replay.s0_protocol.unavailable('parent_cleanup', 'cleanup')}
    assert replay.validate_published_control(redacted, metadata) == redacted
    for corrupt in [value | {'S0': 'unavailable'}, value | {'extra': True}, value | {'recoveryAccepted': 0},
                    value | {'reason': []}, value | {'S0': replay.s0_protocol.unavailable('dependency', 'admission')}]:
        with pytest.raises(package.Unavailable): replay.validate_control(corrupt, metadata)
    with pytest.raises(package.Unavailable): replay.validate_published_control(published | {'ownedCleanupComplete': False}, metadata)


@pytest.mark.parametrize('outcome', ['deadline', 'failed', 'result_invalid'])
def test_worker_loss_recovers_only_durable_f2_and_typed_unavailable(control, outcome):
    path, metadata, f2, optional, _, _ = control
    replay.checkpoint_f2(path, metadata, f2)
    package.write_private(path/'result.json', package._encoded(completed(f2, optional)))
    result = replay.fallback_result(path, metadata, outcome)
    expected = {'deadline': 'worker_deadline', 'failed': 'worker_failed', 'result_invalid': 'worker_result_invalid'}[outcome]
    assert result['Fsql'] == replay.unavailable_fsql(expected)
    assert result['S0'] == replay.s0_protocol.unavailable(expected, 'unobserved')
    assert replay.read_f2(path, metadata) == f2
    result.update(optionalWorkerOutcome=outcome, ownedCleanupComplete=True)
    assert replay.validate_published_control(result, metadata) == result
    with pytest.raises(package.Unavailable):
        replay.validate_published_control(result | {'Fsql': optional}, metadata)


@pytest.mark.parametrize('outcome', [None, True, 'completed-with-warning', 0])
def test_parent_outcome_is_finite_strict_and_mandatory(control, outcome):
    _, metadata, f2, optional, _, _ = control
    result = completed(f2, optional) | {'optionalWorkerOutcome': outcome, 'ownedCleanupComplete': True}
    with pytest.raises(package.Unavailable): replay.validate_published_control(result, metadata)
    with pytest.raises(package.Unavailable): replay.validate_published_control(completed(f2, optional), metadata)


def test_original_v1_aad_and_tag_are_not_accepted_by_new_reader(key):
    bound = aad(key)
    expected = {k:v for k,v in bound.items() if k != 'version'}
    v1aad = replay.seal({'canary': True}, bound | {'version': 1}, key.public_key())
    with pytest.raises(package.Unavailable): replay.decrypt(v1aad, key, expected)
    v2 = replay.seal({'canary': True}, bound, key.public_key())
    with pytest.raises(package.Unavailable):
        replay.decrypt(v2.replace('owned_identity_actual_replay_v2 ', 'owned_identity_actual_replay_v1 ', 1), key, expected)


def test_injected_fingerprint_keeps_query_bytes_order_and_global_checked(monkeypatch):
    original_checked = identity.checked
    calls = []
    def run(args, **kw):
        statement = kw['input'].decode()
        calls.append((args, statement))
        if statement == identity.ROLE_SQL: raw = b'roles\n'
        elif statement == identity.CATALOG_SQL: raw = b'catalog\n'
        elif 'json_agg(tablename' in statement: raw = b'["a","b"]'
        elif 'from auth."a"' in statement: raw = b'[1]\n'
        elif 'from auth."b"' in statement: raw = b'[2]\n'
        elif 'public.company_memberships' in statement: raw = b'[]\n'
        else: pytest.fail('unexpected query')
        return SimpleNamespace(stdout=raw)
    result = identity.fingerprint('owned', restored=True, bootstrap='supabase_admin', checked_call=run)
    assert result == {'roles': hashlib.sha256(b'roles\n').hexdigest(), 'catalog': hashlib.sha256(b'catalog\n').hexdigest(),
                      'auth': hashlib.sha256(b'a[1]\nb[2]\n').hexdigest(), 'companyMemberships': hashlib.sha256(b'[]\n').hexdigest()}
    assert len(calls) == 6 and identity.checked is original_checked
    assert all(args == ['docker','exec','-i','owned','psql','-U','supabase_admin','-h','/tmp','--dbname','postgres','-XAt','-v','ON_ERROR_STOP=1'] for args,_ in calls)


def test_snapshot_reuses_exact_whole_sql_and_validates_once_with_read_cap(monkeypatch):
    raw = {'serverVersion': 170006, **{k:[] for k in ['schemas','functions','hooks','events','extensions']}}
    calls, validated = [], []
    original = capture._validate_snapshot
    def check(value, retained):
        validated.append(value)
        return original(value, retained)
    def run(args, deadline, **kw):
        calls.append((args, deadline, kw)); return json.dumps(raw).encode()
    monkeypatch.setattr(capture, '_validate_snapshot', check)
    assert capture._snapshot('owned', 100, target=True, run=run) == raw
    assert len(validated) == 1 and len(calls) == 1
    assert calls[0][2] == {'data': capture._snapshot_statement(), 'cap': 32768}
    assert calls[0][2]['data'] == package.Path(capture.__file__).with_name('rf1086_catalog_causal.sql').read_bytes()
    assert calls[0][0] == ['docker','exec','-i','owned','psql','-U','supabase_admin','-h','/tmp','-d','postgres','-XqAt','-v','ON_ERROR_STOP=1']


@pytest.mark.parametrize('escape', ['returned', 'unavailable', 'ordinary', 'cancel'])
def test_worker_fatal_context_precludes_result_publication_preserving_primary(control, monkeypatch, escape):
    path, metadata, f2, optional, _, _ = control
    initiating = KeyboardInterrupt() if escape == 'cancel' else RuntimeError('owned-child-uncertainty')
    state = {'fatal': False}
    def raise_if_fatal():
        if state['fatal']: raise initiating
    context = SimpleNamespace(raise_if_fatal=raise_if_fatal, result=replay.s0_protocol.unavailable('dependency','admission'))
    monkeypatch.setattr(replay.s0_control, 'new_context', lambda:context)
    monkeypatch.setattr(replay, 'read_package', lambda:(path,metadata,'a'*64))
    monkeypatch.setenv('TALLI_RF_REPLAY_ACTIVE_DEADLINE', str(time.monotonic()+100))
    def perform(*args, s0_context):
        assert s0_context is context; state['fatal'] = True
        if escape == 'unavailable': raise package.Unavailable('command_unavailable')
        if escape == 'ordinary': raise ValueError('secondary')
        if escape == 'cancel': raise initiating
        return completed(f2,optional)
    monkeypatch.setattr(replay,'replay',perform)
    with pytest.raises(type(initiating)) as caught: replay.worker()
    assert caught.value is initiating and not (path/'result.json').exists()


@pytest.mark.parametrize('error_kind', ['full_sql', 'unavailable', 'ordinary', 'returned'])
def test_optional_shield_never_hides_fatal_context(control, error_kind):
    path, metadata, f2, optional, _, _ = control
    initiating = RuntimeError('owned-child-uncertainty'); state={'fatal':False}
    def check():
        if state['fatal']: raise initiating
    context=SimpleNamespace(raise_if_fatal=check, result=replay.s0_protocol.unavailable('dependency','admission'))
    def operation(deadline):
        state['fatal']=True
        if error_kind=='full_sql': raise replay.FullSqlUnavailable('command_unavailable', None)
        if error_kind=='unavailable': raise package.Unavailable('command_unavailable')
        if error_kind=='ordinary': raise ValueError('secondary')
        return optional
    with pytest.raises(RuntimeError) as caught:
        replay.optional_observation(path,metadata,f2,time.monotonic()+416,operation,s0_context=context)
    assert caught.value is initiating
    assert replay.read_f2(path,metadata)==f2 and not (path/'result.json').exists()


def test_code_binding_contains_all_thirteen_direct_dependencies(control):
    _,metadata,_,_,_,_=control
    assert len(metadata['code']) == 13
    assert set(metadata['code']) == set(package.CODE_FILES)
    for name in ['rf1086_s0_protocol.py','rf1086_s0_control.py','rf1086_catalog_difference.py']:
        assert metadata['code'][name] == package.digest(package.Path(package.__file__).with_name(name).read_bytes())


def test_s0_receives_same_completed_stream_descriptor_and_actual_fsql_target(control, monkeypatch):
    path, metadata, f2, _, _, failed = control
    script = b'full original script\n'; descriptor = {'private': 'same-traversal-object'}
    ledger = replay.sql_ledger.unavailable('headroom', 'admission')
    events = []
    context = SimpleNamespace(raise_if_fatal=lambda:None, result=replay.s0_protocol.unavailable('dependency','admission'))
    def command(args, *a, **kw):
        if args[-1] == replay.TOOL_COMMAND: return b'pg_restore (PostgreSQL) 17.6\n'+b'f'*64+b'\n'
        assert kw['archive'].read() == b'private-archive'
        return script
    monkeypatch.setattr(replay,'command',command)
    monkeypatch.setattr(replay,'cleanup_resources',lambda *a,**kw:True)
    monkeypatch.setattr(replay,'start_target',lambda *a,**kw:'e'*64)
    monkeypatch.setattr(replay,'psql',lambda *a,**kw:None)
    monkeypatch.setattr(replay,'_snapshot',lambda *a,**kw:metadata['phases']['target_initialized']['catalog'])
    monkeypatch.setattr(replay,'failed_state',lambda *a,**kw:(metadata['failed'],metadata['phases']['mismatch']['catalog']))
    def observe(p, actual_script, toc, m, inventory, fsql, deadline, **kw):
        assert actual_script is script and fsql['FsqlEqualsF2'] is True
        events.append('ledger');return ledger,descriptor
    monkeypatch.setattr(replay.sql_ledger,'observe_with_descriptor',observe)
    def s0(**kw):
        events.append('S0')
        assert kw['script'] is script and kw['descriptor'] is descriptor
        assert kw['previous_target'] == 'e'*64 and kw['previous_target'] != 'd'*64
        assert kw['f2'] is f2 and kw['fsql']['ledger'] is ledger
        assert kw['context'] is context
        return replay.s0_protocol.unavailable('descriptor_invalid','admission')
    monkeypatch.setattr(replay.s0_control,'observe_s0',s0)
    result=replay.full_sql_control(path,metadata,'d'*64,b'roles',failed,time.monotonic()+200,
                                  s0_context=context,f2=f2,inventory=f2['inventory'])
    assert events==['ledger','S0'] and result['ledger'] is ledger
    assert context.result == replay.s0_protocol.unavailable('descriptor_invalid','admission')
    assert result['stream'] == {'bytes':len(script),'sha256':hashlib.sha256(script).hexdigest()}


def test_resource_callbacks_propagate_owned_runner_without_global_patch(control, monkeypatch):
    path,metadata,f2,optional,_,failed=control
    calls=[]; runner=object(); pause=object()
    def invoke(name, result):
        def callback(*args, **kwargs):
            assert kwargs['run'] is runner
            calls.append((name,args,kwargs))
            return result
        return callback
    monkeypatch.setattr(replay,'cleanup_resources',invoke('cleanup',True))
    monkeypatch.setattr(replay,'start_target',invoke('start','e'*64))
    monkeypatch.setattr(replay,'psql',invoke('psql',None))
    monkeypatch.setattr(replay,'_snapshot',invoke('snapshot',metadata['phases']['target_initialized']['catalog']))
    monkeypatch.setattr(replay,'failed_state',invoke('final',(metadata['failed'],metadata['phases']['mismatch']['catalog'])))
    resources=replay._s0_resources(path,metadata,b'original roles',failed,f2,optional)
    assert resources.cleanup(100,run=runner)
    assert resources.start(101,run=runner,pause=pause)=='e'*64
    resources.apply_roles('e'*64,102,run=runner)
    resources.initialized('e'*64,103,run=runner)
    resources.drop_default('e'*64,104,run=runner)
    resources.final_state('e'*64,105,run=runner)
    assert [x[0] for x in calls]==['cleanup','start','psql','snapshot','psql','final']
    assert calls[1][2]['pause'] is pause
    assert calls[2][1][1]==b'original roles'
    assert calls[4][1][1]==b'drop database postgres with (force);' and calls[4][2]['database']=='template1'
    assert calls[5][1][1:3] == (metadata,failed)
    assert resources.summary_fits(replay.s0_protocol.unavailable('dependency','admission'))


@pytest.fixture(params=[False, True], ids=['five-exchanges', 'six-exchanges'])
def matched_control(tmp_path, control, request):
    from test_rf1086_s0_protocol import valid_receipt_context, synthetic_inventory
    s0, fsql, f2_input, metadata = valid_receipt_context(tmp_path, extra_reconnect=request.param)
    f2 = deepcopy(control[2])
    f2.update(fingerprint=metadata['failed'], catalog=metadata['phases']['mismatch']['catalog'],
              input=f2_input, inventory=synthetic_inventory(extra_reconnect=request.param),
              sourceCommandSha256=metadata['phases']['source_pre_dump']['sourceCommandSha256'],
              sourceInstalledFiles=metadata['phases']['source_pre_dump']['files'])
    return completed(f2, fsql) | {'S0': s0}, f2, metadata


def test_matched_control_requires_full_f2_fsql_inventory_and_parent_facts(matched_control):
    value, f2, metadata = matched_control
    assert replay.validate_control(value, metadata) is value
    published = value | {'optionalWorkerOutcome':'completed', 'ownedCleanupComplete':True}
    assert replay.validate_published_control(published, metadata) is published
    for change in [{'optionalWorkerOutcome':'failed'}, {'optionalWorkerOutcome':'deadline'},
                   {'optionalWorkerOutcome':'result_invalid'}, {'ownedCleanupComplete':False}]:
        with pytest.raises(package.Unavailable): replay.validate_published_control(published | change, metadata)
    for key, wrong in [('checkpointIds', [999,31,20]), ('sha256', '0'*64), ('total', value['inventory']['total']+1),
                       ('passCounts', {'SPECIAL':3,'MAIN':4,'ACL':2,'POST_ACL':1})]:
        altered = deepcopy(value); altered['inventory'][key] = wrong
        with pytest.raises(package.Unavailable): replay.validate_control(altered, metadata)
    assert f2['S0'] == 'unavailable'


def test_sizing_discards_s0_before_retaining_complete_fsql_and_ledger(matched_control, monkeypatch):
    value, f2, metadata = matched_control
    expected = completed(f2, value['Fsql'], reason='summary_oversized', stage='composition')
    maximum_parent = {'optionalWorkerOutcome':'result_invalid','ownedCleanupComplete':False}
    monkeypatch.setattr(replay,'MAX_PLAINTEXT',len(package._encoded(expected | maximum_parent)))
    result = replay.fit_optional(f2,value['Fsql'],metadata,s0=value['S0'])
    assert result == expected
    assert result['Fsql']['ledger']['status'] == 'verified_conditional'
    assert result['Fsql']['stream'] == value['S0']['delivery']['original']


def test_ledger_reduction_cannot_retain_positive_s0(matched_control, monkeypatch):
    value, f2, metadata = matched_control
    fsql = value['Fsql'] | {'ledger':replay.sql_ledger.unavailable('summary','summary')}
    expected = completed(f2,fsql,reason='summary_oversized',stage='composition')
    monkeypatch.setattr(replay,'MAX_PLAINTEXT',len(package._encoded(expected | {
        'optionalWorkerOutcome':'result_invalid','ownedCleanupComplete':False})))
    result = replay.fit_optional(f2,value['Fsql'],metadata,s0=value['S0'])
    assert result == expected and result['Fsql']['FsqlEqualsF2'] is True
    with pytest.raises(package.Unavailable):
        replay.validate_control(result | {'S0':value['S0']},metadata)


def test_sizing_only_maximum_can_never_be_published_as_evidence(matched_control):
    value,f2,metadata=matched_control
    ledger=value['Fsql']['ledger']
    descriptor={'schema':'s0-session-descriptor-v1', 'ledgerSha256':replay.sql_ledger.semantic_hash(ledger),
                'database':'postgres', **value['S0']['references']}
    maximum=replay.s0_protocol.maximum_receipt(fsql=value['Fsql'],f2_input=f2['input'],metadata=metadata,
                                               descriptor=descriptor,inventory=f2['inventory'])
    assert len(package._encoded(maximum)) <= 24576
    assert replay.summary_fits(value | {'S0':maximum},metadata)
    for candidate in [maximum, json.loads(package._encoded(maximum))]:
        with pytest.raises(package.Unavailable): replay.validate_control(value | {'S0':candidate},metadata)


@pytest.mark.parametrize('database', ['postgres','template1'])
def test_sequential_and_persistent_psql_share_argv_without_new_writer_settings(database):
    calls=[]
    replay.psql('e'*64,b'SELECT 1;',100,database=database,
                run=lambda args,deadline,**kw:calls.append((args,deadline,kw)))
    expected=replay.s0_protocol.writer_argv('e'*64)
    expected[expected.index('-d')+1]=database
    assert calls==[(expected,100,{'data':b'SELECT 1;'})]
    assert not any('PGCLIENTENCODING' in value or 'PGOPTIONS' in value for value in expected)
