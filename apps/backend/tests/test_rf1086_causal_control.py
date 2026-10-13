"""Sequence, cache and failure ownership tests with synthetic closed policies."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import rf1086_causal_control as control
import rf1086_s0_control as runtime
import rf1086_s0_protocol as s0
from test_rf1086_s0_control import children, lifecycle


def snapshot(index):
    return {'serverVersion':170006,'schemas':[],'functions':[],
            'hooks':[{'slot':index,'configurationEncoding':'sha256-of-canonical-json','value':'a'*64}],
            'events':[],'extensions':[]}


def staged(cache, index):
    value = snapshot(index)
    projection = {'snapshot': s0.snapshot_commitment(value)}
    cache.stage(index, projection, value)
    exchange = {'point': ['cut', index], 'catalog': projection}
    cache.complete(exchange)
    return exchange, value


def sealed_cache():
    cache = control.ReferenceCache()
    exchanges = [staged(cache, i)[0] for i in range(3)]
    receipt = {'status': 'matched', 'exchanges': exchanges, 'nonce': 'a'*32}
    cache.seal(receipt)
    return cache, receipt


def test_cache_seals_only_three_confirmed_observations_and_detaches_aliases():
    cache = control.ReferenceCache(); exchanges = []
    for i in range(3):
        exchange, original = staged(cache, i); exchanges.append(exchange)
        original['hooks'][0]['value'] = 'changed caller alias'
    receipt = {'status': 'matched', 'exchanges': exchanges}
    cache.seal(receipt)
    copy = cache.reference(0, receipt); copy['hooks'][0]['value'] = 'changed consumer alias'
    assert cache.reference(0, receipt) == snapshot(0)
    with pytest.raises(runtime.ControlFailure):cache.reference(0, receipt | {'extra': True})
    cache.clear()
    assert not cache.ready and cache._entries == {} and cache._pending is None
    with pytest.raises(runtime.ControlFailure):cache.reference(0, receipt)


@pytest.mark.parametrize('bad', ['partial', 'unconfirmed', 'wrong_projection', 'duplicate', 'oversized'])
def test_cache_never_seals_partial_oversized_or_mismatched_observation(bad):
    cache=control.ReferenceCache(); exchanges=[]
    if bad == 'oversized':
        value=snapshot(0); value['hooks'][0]['value']='x'*32768
        with pytest.raises(runtime.ControlFailure):cache.stage(0,{'snapshot':s0.snapshot_commitment(value)},value)
    else:
        exchanges=[staged(cache,i)[0] for i in range(2)]
        value=snapshot(2); projection={'snapshot':s0.snapshot_commitment(value)}
        if bad=='unconfirmed':cache.stage(2,projection,value)
        elif bad=='wrong_projection':
            cache.stage(2,projection,value)
            with pytest.raises(runtime.ControlFailure):cache.complete({'point':['cut',2],'catalog':{'snapshot':'f'*64}})
        elif bad=='duplicate':
            with pytest.raises(runtime.ControlFailure):staged(cache,0)
    with pytest.raises(runtime.ControlFailure):cache.seal({'status':'matched','exchanges':exchanges})
    assert not cache.ready


def test_optin_cache_failure_does_not_erase_valid_s0(lifecycle):
    args, _, _, expected = lifecycle
    # The mocked default lifecycle has no raw observations: no fabricated cache.
    cache=control.ReferenceCache()
    assert runtime.observe_s0(**args,reference_sink=cache)==expected
    assert not cache.ready and cache._entries=={}


def test_shared_admission_start_is_inside_s0_phase_allocation(lifecycle):
    args, clock, events, _ = lifecycle
    clock[0]=1005.0
    value=runtime.observe_s0(**args, control_started=1000.0)
    assert value['status']=='unavailable' and events==[]


@pytest.fixture
def sequence(monkeypatch):
    # Deliberately minimal fixture receipts/policies. Real wire and owner tests
    # live beside these; this fixture cannot mint production evidence.
    clock=[1000.0]; events=[]; targets=iter(['a'*64,'b'*64,'c'*64])
    monkeypatch.setattr(control.time,'monotonic',lambda:clock[0])
    counter=iter(['1'*32,'2'*32]); monkeypatch.setattr(control.secrets,'token_hex',lambda n:next(counter))
    script=b'original bytes'; stream=dict(bytes=len(script),sha256=hashlib.sha256(script).hexdigest())
    phases={'source_pre_dump':{'catalog':snapshot(4)},'mismatch':{'catalog':snapshot(5)},
            'target_initialized':{'catalog':snapshot(6)}}
    metadata={'source':'e'*64,'sourceAuth':'f'*64,'phases':phases,
              'failed':dict.fromkeys(('roles','catalog','auth','companyMemberships'),'4'*64)}
    points=((('anchor',0),0),(('anchor',1),1),(('cut',0),2),(('cut',1),3),(('cut',2),4))
    fsql={'status':'full_sql_verified','stream':stream,'ledger':{'status':'verified_conditional','selected':[{}, {}, {}]}}
    def unavailable(kind,reason,stage,point=None):return dict(schema='fixture',kind=kind,status='unavailable',reason=reason,stage=stage,point=point)
    protocol=SimpleNamespace(SCHEMA='fixture',unavailable=unavailable,CONFIG={
        'catalogQuery':{'bytes':1,'sha256':hashlib.sha256(b'q').hexdigest()},
        'reasonStages':{stage:['control_unavailable','command','deadline','source_profile','headroom',
            'raw_prediction','raw_prediction_mismatch','fingerprint_mismatch','enriched_prediction_mismatch',
            'initialized_mismatch','ownership','binding','tool','nonce_collision']
            for stage in ('admission','setup','transport','final','cleanup','composition')}})
    protocol.Unavailable=runtime.ControlFailure
    protocol.commitment=runtime._hash
    protocol.maximum_receipt=lambda kind,**kw:{'maximum':kind}
    def prepare(kind,**kw):
        events.append(('prepare',kind,kw['deadline']))
        return SimpleNamespace(kind=kind,point=('cut',1 if kind=='Is' else 2),
            sql=b'BEGIN;\nSELECT 1;\nCOMMIT;\n',expected_final=snapshot(7 if kind=='Is' else 8))
    protocol.prepare_policy=prepare
    def ordered(policy,*_):
        out=[]
        for point,offset in points:
            out.append((point,offset))
            if point==policy.point:out.append((('post',point[1]),offset))
        return tuple(out)
    protocol.ordered_points=ordered
    protocol.parse_session=lambda raw,**kw:json.loads(raw)
    protocol.parse_witness=lambda raw,**kw:json.loads(raw)
    protocol.witness_request=lambda *a:b'w'
    protocol.probe=lambda nonce,seq:(b'p',b'q')
    protocol.admit_mutation=lambda policy,actual,reference:{'controlSnapshot':s0.snapshot_commitment(reference)}
    protocol.factor_catalog=lambda policy,actual,reference,**kw:{'mode':'ref'}
    protocol.expectation=lambda policy,**kw:{'expected':policy.kind}
    protocol.validate_receipt=lambda value,**kw:value
    monkeypatch.setattr(control,'_protocol',lambda:protocol)
    monkeypatch.setattr(s0,'maximum_receipt',lambda **kw:{'maximum':'S0'})
    import rf1086_catalog_causal_capture as capture
    monkeypatch.setattr(capture,'_snapshot_statement',lambda:b'q')
    monkeypatch.setattr(s0,'project_with_reference',lambda raw,**kw:({'snapshot':s0.snapshot_commitment(json.loads(raw))},json.loads(raw)))
    prediction=SimpleNamespace(binding={'expected':{'bytes':12,'sha256':'5'*64},'outside':'6'*64})
    def start(*a,**kw):
        target=next(targets);events.append(('start',target,kw['run'].end));return target
    def cleanup(deadline,**kw):events.append(('cleanup',deadline,kw['run'].end));return True
    def final(target,deadline,*,run,branch_policy,references):
        events.append(('final',branch_policy.kind,deadline))
        assert references.prediction is prediction
        return dict(fingerprint=metadata['failed']|{'catalog':'5'*64},
            enriched=s0.snapshot_commitment(branch_policy.expected_final),
            raw=prediction.binding|{'actual':prediction.binding['expected']})
    resources=SimpleNamespace(start=start,cleanup=cleanup,apply_roles=lambda *a,**kw:None,
        initialized=lambda *a,**kw:phases['target_initialized']['catalog'],
        drop_default=lambda *a,**kw:None,final_state=lambda *a,**kw:None,
        raw_prediction=lambda kind,deadline:prediction,branch_final_state=final,
        summary_fits_sequence=lambda *a,**kw:True)
    context=control.new_context()
    context.acquired_targets={'7'*64}
    def matched(**kw):
        events.append(('s0',kw['control_started'],kw['optional_deadline']))
        target=kw['resources'].start(1043,run=runtime.S0Runner(context,1045),pause=lambda *_:None)
        exchanges=[]
        for point,offset in points:
            e=dict(point=list(point),input=[offset,offset],session=['db',123,'user'],catalog=None)
            if point[0]=='cut':
                e['catalog']={'snapshot':s0.snapshot_commitment(snapshot(point[1]))}
                kw['reference_sink'].stage(point[1],e['catalog'],snapshot(point[1]));kw['reference_sink'].complete(e)
            exchanges.append(e)
        context.result=dict(status='matched',nonce='0'*32,exchanges=exchanges,target={'id':target})
        kw['reference_sink'].seal(context.result)
        kw['resources'].cleanup(1116,run=runtime.S0Runner(context,1118))
        clock[0]+=1
        return context.result
    monkeypatch.setattr(runtime,'observe_s0',matched)
    monkeypatch.setattr(runtime.S0Runner,'__call__',lambda *a,**kw:b'psql (PostgreSQL) 17.6\n'+b'9'*64+b'\n')
    def transport(script,descriptor,ledger,**kw):
        events.append(('transport',kw['mutation_policy'].kind,kw['work_end'],kw['reap_end']))
        exchanges=[]
        for seq,(point,offset) in enumerate(kw['points']):
            kw['observer_request'](point,seq,456)
            projection=None if point[0]=='anchor' else kw['project'](json.dumps(snapshot(point[1])).encode(),{})
            e=dict(point=list(point),input=[offset,offset],session=['db',456,'user'],barrierPid=456,
                witnesses=[['db','1',456,'1','db','start',None,None,None,None,None,None,None,'103']],
                observer={'fixture':True},catalog=projection)
            kw['exchange_complete'](e);exchanges.append(e)
        sql=kw['mutation_policy'].sql
        return dict(exchanges=exchanges,delivery={'original':stream,
            'probes':{'bytes':12,'sha256':'a'*64},'frames':[len(exchanges)]*2,
            'mutation':{'bytes':len(sql),'sha256':hashlib.sha256(sql).hexdigest()},'writer':{'fixture':True}})
    monkeypatch.setattr(runtime,'transport',transport)
    args=dict(context=context,script=script,descriptor={'cuts':[[1],[1],[1]]},
        f2={'input':{},'inventory':{}},fsql=fsql,metadata=metadata,previous_target='8'*64,
        optional_deadline=1400.0,resources=resources)
    return args,clock,events,protocol


def test_sequence_uses_three_distinct_targets_and_same_generation_references(sequence):
    args,clock,events,protocol=sequence
    result=control.observe_causal_sequence(**args)
    assert result['S0']['status']=='matched'
    assert [result[k]['status'] for k in ('Is','In')]==['prediction_matched']*2
    assert result['Is']['target']['previous']=='a'*64 and result['In']['target']['previous']=='b'*64
    assert args['context'].acquired_targets=={'7'*64,'8'*64,'a'*64,'b'*64,'c'*64}
    assert [e[1] for e in events if e[0]=='start']==['a'*64,'b'*64,'c'*64]
    assert [e[1] for e in events if e[0]=='transport']==['Is','In']
    assert all(e[2]<=e[3]-2 for e in events if e[0]=='transport')


@pytest.mark.parametrize('deadline',[None,True,float('inf'),float('nan'),1359.999])
def test_upfront_full360_or_no_targets(sequence,deadline):
    args,_,events,_=sequence;args['optional_deadline']=deadline
    result=control.observe_causal_sequence(**args)
    assert all(result[k]['status']=='unavailable' for k in ('S0','Is','In')) and events==[]


def test_maximum_envelope_refusal_precedes_every_target(sequence):
    args,_,events,_=sequence;args['resources'].summary_fits_sequence=lambda *a,**kw:False
    result=control.observe_causal_sequence(**args)
    assert result['Is']['reason']=='summary_oversized' and events==[]


def test_cancel_during_pure_admission_is_sticky_without_acquisition(sequence):
    args,_,events,_=sequence;primary=KeyboardInterrupt()
    def cancel(*a,**kw):raise primary
    args['resources'].summary_fits_sequence=cancel
    with pytest.raises(KeyboardInterrupt) as caught:control.observe_causal_sequence(**args)
    assert caught.value is primary and events==[] and args['context'].owner.cancelled
    with pytest.raises(KeyboardInterrupt) as repeated:args['context'].raise_if_fatal()
    assert repeated.value is primary


@pytest.mark.parametrize('where',['admission','transport','final'])
def test_known_negative_is_can_continue_independent_in(sequence,monkeypatch,where):
    args,_,events,p=sequence
    if where=='admission':
        original=p.prepare_policy
        def prepare(kind,**kw):
            if kind=='Is':raise runtime.ControlFailure('source_profile')
            return original(kind,**kw)
        p.prepare_policy=prepare
    elif where=='transport':
        original=runtime.transport
        def transport(*a,**kw):
            if kw['mutation_policy'].kind=='Is':raise runtime.ControlFailure('source_profile',('cut',1))
            return original(*a,**kw)
        monkeypatch.setattr(runtime,'transport',transport)
    else:
        original=args['resources'].branch_final_state
        def final(*a,**kw):
            if kw['branch_policy'].kind=='Is':raise runtime.ControlFailure('raw_prediction_mismatch')
            return original(*a,**kw)
        args['resources'].branch_final_state=final
    result=control.observe_causal_sequence(**args)
    assert result['S0']['status']=='matched' and result['Is']['status']=='unavailable'
    assert result['In']['status']=='prediction_matched'
    assert result['In']['target']['previous']==('a' if where=='admission' else 'b')*64


def test_local_cleanup_uncertainty_stops_later_branch_but_keeps_s0(sequence):
    args,_,events,_=sequence;original=args['resources'].cleanup
    def cleanup(*a,**kw):
        answer=original(*a,**kw)
        return False if any(e[:2]==('final','Is') for e in events) else answer
    args['resources'].cleanup=cleanup
    result=control.observe_causal_sequence(**args)
    assert result['S0']['status']=='matched' and result['Is']['reason']=='cleanup_unproved'
    assert result['In']['status']=='unavailable'
    assert [e[1] for e in events if e[0]=='start']==['a'*64,'b'*64]


def test_expired_admission_cannot_borrow_setup_time(sequence):
    args,clock,events,p=sequence;original=p.prepare_policy
    def prepare(kind,**kw):
        value=original(kind,**kw)
        if kind=='Is':clock[0]=kw['deadline']
        return value
    p.prepare_policy=prepare
    result=control.observe_causal_sequence(**args)
    assert result['Is']['reason']=='headroom'
    assert result['In']['status']=='prediction_matched'


def test_fatal_cancel_reaps_known_child_stops_all_and_preserves_identity(sequence,children,monkeypatch):
    args,_,events,_=sequence;primary=KeyboardInterrupt()
    def cancel(*a,**kw):
        args['context'].owner.launch([sys.executable,'-c','import time;time.sleep(30)'])
        raise primary
    monkeypatch.setattr(runtime,'transport',cancel)
    with pytest.raises(KeyboardInterrupt) as caught:control.observe_causal_sequence(**args)
    assert caught.value is primary and args['context'].owner.primary is primary
    assert len(children)==1 and children[0].returncode is not None
    assert not any(e[:2]==('prepare','In') for e in events)


@pytest.mark.parametrize('where',['validation','composition','final','cleanup'])
def test_late_ordinary_exception_stays_typed_and_preserves_fsql_s0(sequence,where):
    args,clock,events,p=sequence;before=deepcopy(args['fsql'])
    def fail(*a,**kw):raise ValueError('private synthetic text')
    if where=='validation':p.validate_receipt=fail
    elif where=='composition':
        original=args['resources'].summary_fits_sequence
        args['resources'].summary_fits_sequence=lambda *a,**kw:fail() if any(e[0]=='final' for e in events) else original(*a,**kw)
    elif where=='final':args['resources'].branch_final_state=fail
    else:
        original=args['resources'].cleanup
        args['resources'].cleanup=lambda *a,**kw:fail() if any(e[0]=='final' for e in events) else original(*a,**kw)
    result=control.observe_causal_sequence(**args)
    assert result['S0']['status']=='matched' and result['Is']['status']=='unavailable'
    assert args['fsql']==before and 'private synthetic text' not in repr(result)


@pytest.mark.parametrize('kind',['Is','In'])
@pytest.mark.parametrize('extra_reconnect',[False,True])
def test_controller_composition_matches_real_closed_protocol(tmp_path,monkeypatch,kind,extra_reconnect):
    from test_rf1086_causal_protocol import valid_branch_context
    import rf1086_causal_protocol as protocol
    expected, args, policy, descriptor, snapshots=valid_branch_context(tmp_path,kind,extra_reconnect=extra_reconnect)
    s0_receipt=args['s0_receipt']; cache=control.ReferenceCache()
    for exchange in s0_receipt['exchanges']:
        if exchange['point'][0]=='cut':
            index=exchange['point'][1]
            cache.stage(index,exchange['catalog'],snapshots[index]);cache.complete(exchange)
    cache.seal(s0_receipt); context=control.new_context(); context.result=s0_receipt
    # This isolates command/transport I/O, not catalog or protocol validation.
    # Real pipes and byte accounting are exercised in the transport tests.
    monkeypatch.setattr(control,'_script_nonce',lambda *a:expected['nonce'])
    monkeypatch.setattr(runtime.S0Runner,'__call__',lambda *a,**kw:b'psql (PostgreSQL) 17.6\n'+b'7'*64+b'\n')
    source=args['metadata']['phases']['source_pre_dump']['catalog']
    controls={tuple(e['point']):e for e in s0_receipt['exchanges']}
    def transport(*a,**kw):
        exchanges=[]; after=False
        for seq,(point,offset) in enumerate(kw['points']):
            ref=expected['exchanges'][seq]
            mapped=('cut',point[1]) if point[0]=='post' else point
            session=deepcopy(controls[mapped]['session']);session[1]=ref['pid']
            kw['observer_request'](point,seq,ref['pid'])
            if point[0]=='post':after=True
            catalog=None
            if point[0]!='anchor':
                actual=protocol.expected_catalog(kind,snapshots[point[1]],source) if after else snapshots[point[1]]
                catalog=kw['project'](json.dumps(actual).encode()+b'\n',args['fsql']['ledger']['selected'][point[1]])
            witnesses=[]
            for db,start,capacity in ref['witnesses']:
                witness=[session[0],db,session[1],db,session[0],start,'idle',None,None,None,
                    protocol.probe(expected['nonce'],seq)[1][:-1].decode(),'UTF8','UTF8',capacity,'B','postmaster','integer']
                witnesses.append(protocol.parse_witness(json.dumps(witness).encode(),nonce=expected['nonce'],sequence=seq,session=session))
            exchange=dict(point=list(point),input=[offset,offset],session=session,barrierPid=session[1],
                witnesses=witnesses,observer=deepcopy(ref['observer']),catalog=catalog)
            kw['exchange_complete'](exchange);exchanges.append(exchange)
        return dict(exchanges=exchanges,delivery=deepcopy(expected['delivery']))
    monkeypatch.setattr(runtime,'transport',transport)
    prediction=SimpleNamespace(binding={key:expected['final']['raw'][key] for key in ('expected','outside')})
    resources=SimpleNamespace(cleanup=lambda *a,**kw:True,start=lambda *a,**kw:expected['target']['id'],
        apply_roles=lambda *a,**kw:None,initialized=lambda *a,**kw:args['metadata']['phases']['target_initialized']['catalog'],
        drop_default=lambda *a,**kw:None,raw_prediction=lambda *a:prediction,
        branch_final_state=lambda *a,**kw:deepcopy(expected['final']),summary_fits_sequence=lambda *a:True)
    start=control.time.monotonic()
    result,previous,cleaned=control._observe_branch(kind,context=context,script=b'fixture',descriptor=descriptor,
        f2={'input':args['f2_input'],'inventory':args['inventory']},fsql=args['fsql'],metadata=args['metadata'],
        previous_target=s0_receipt['target']['id'],started=start,hard_end=start+120,resources=resources,
        references=SimpleNamespace(cache=cache,s0=s0_receipt),seen_targets={s0_receipt['target']['id']},nonces={s0_receipt['nonce']})
    assert result==expected and cleaned and previous==expected['target']['id']
    assert protocol.validate_receipt(result,**args)==result
    assert cache.ready
    cache.clear()


@pytest.mark.parametrize('kind',['Is','In'])
def test_whole_catalog_rejection_keeps_finite_protocol_reason(sequence,monkeypatch,kind):
    args,_,events,p=sequence
    original=p.factor_catalog
    def factor(policy,actual,reference,**kw):
        if policy.kind==kind:raise p.Unavailable('prefix_mismatch')
        return original(policy,actual,reference,**kw)
    p.CONFIG['reasonStages']['transport'].append('prefix_mismatch')
    p.factor_catalog=factor
    result=control.observe_causal_sequence(**args)
    assert (result[kind]['reason'],result[kind]['stage'],tuple(result[kind]['point']))==('prefix_mismatch','transport',('cut',0))
    assert result['S0']['status']=='matched'


@pytest.mark.parametrize('reused',['7','8','a','e','f'])
def test_branch_target_must_exclude_every_prior_acquired_and_source_id(sequence,reused):
    args,_,events,p=sequence;start=args['resources'].start
    def reused_start(*a,**kw):
        target=start(*a,**kw)
        return reused*64 if target=='b'*64 else target
    args['resources'].start=reused_start
    result=control.observe_causal_sequence(**args)
    assert result['Is']['status']=='unavailable' and result['Is']['reason']=='ownership'
    assert not any(e[:2]==('transport','Is') for e in events)
    assert not any(e[:2]==('prepare','In') for e in events)


def test_start_failure_without_returned_id_stops_later_target_even_after_cleanup(sequence):
    args,_,events,p=sequence;start=args['resources'].start
    def missing_id(*a,**kw):
        target=start(*a,**kw)
        if target=='b'*64:raise ValueError('simulated readiness failure after creation')
        return target
    args['resources'].start=missing_id
    result=control.observe_causal_sequence(**args)
    assert result['S0']['status']=='matched' and result['Is']['status']=='unavailable'
    assert events[-1][0]=='cleanup'
    assert not any(e[:2]==('prepare','In') for e in events)


def test_all_later_equal_offset_points_are_post_mutation(sequence):
    args,_,_,p=sequence; original=p.ordered_points; seen=[]
    def ordered(policy,*a):
        points=original(policy,*a)
        # Distinct ordered cuts can be modeled at one byte offset. The mutation
        # state follows completed exchanges, never an inferred offset inequality.
        cut=next(o for point,o in points if point==policy.point)
        return tuple((point,cut if point==('cut',2) and policy.kind=='Is' else offset) for point,offset in points)
    p.ordered_points=ordered
    p.factor_catalog=lambda policy,*a,**kw:seen.append((policy.kind,kw['after'])) or {'mode':'ref'}
    result=control.observe_causal_sequence(**args)
    assert result['Is']['status']=='prediction_matched'
    assert [after for kind,after in seen if kind=='Is']==[False,False,True,True]


@pytest.mark.parametrize('outcome',['positive','negative','cancel'])
def test_sequence_always_releases_normalized_cache(sequence,monkeypatch,outcome):
    args,_,events,p=sequence; caches=[]; cache_type=control.ReferenceCache
    def make():
        value=cache_type();caches.append(value);return value
    monkeypatch.setattr(control,'ReferenceCache',make)
    primary=KeyboardInterrupt()
    if outcome!='positive':
        def fail(*a,**kw):
            if outcome=='cancel':raise primary
            raise ValueError('synthetic private failure')
        args['resources'].branch_final_state=fail
    if outcome=='cancel':
        with pytest.raises(KeyboardInterrupt) as caught:control.observe_causal_sequence(**args)
        assert caught.value is primary
    else:control.observe_causal_sequence(**args)
    assert len(caches)==1 and not caches[0].ready and caches[0]._entries=={} and caches[0]._pending is None


@pytest.mark.parametrize('phase',['setup','transport','final','cleanup','composition'])
def test_each_phase_retains_its_own_deadline_and_full_in_headroom(sequence,monkeypatch,phase):
    args,clock,events,p=sequence
    if phase=='setup':
        original=args['resources'].drop_default
        def drop(*a,**kw):
            original(*a,**kw);clock[0]=kw['run'].end
        args['resources'].drop_default=drop
    elif phase=='transport':
        original=runtime.transport
        def transport(*a,**kw):
            value=original(*a,**kw);clock[0]=kw['reap_end'];raise runtime.ControlFailure('deadline')
        monkeypatch.setattr(runtime,'transport',transport)
    elif phase=='final':
        original=args['resources'].branch_final_state
        def final(*a,**kw):
            value=original(*a,**kw);clock[0]=kw['run'].end;return value
        args['resources'].branch_final_state=final
    elif phase=='cleanup':
        original=args['resources'].cleanup
        def cleanup(*a,**kw):
            value=original(*a,**kw)
            if any(e[0]=='final' for e in events):clock[0]=kw['run'].end
            return value
        args['resources'].cleanup=cleanup
    else:
        original=p.validate_receipt
        def validate(*a,**kw):
            original(*a,**kw);clock[0]+=2
        p.validate_receipt=validate
    result=control.observe_causal_sequence(**args)
    assert result['S0']['status']=='matched' and result['Is']['status']=='unavailable'
    if phase=='cleanup':assert result['In']['status']=='unavailable' and not any(e[:2]==('prepare','In') for e in events)
    assert all(e[2]<=e[3]-2 for e in events if e[0]=='transport')


@pytest.mark.parametrize('bad',['hash','length','collision','reuse'])
def test_nonce_binding_refuses_changed_script_and_cross_chunk_collision(monkeypatch,bad):
    nonce='1'*32;script=b'x'*65530+nonce.encode()+b'z'*20 if bad=='collision' else b'fixture'
    monkeypatch.setattr(control.secrets,'token_hex',lambda n:nonce)
    stream=dict(bytes=len(script),sha256=hashlib.sha256(script).hexdigest())
    if bad=='hash':stream['sha256']='f'*64
    if bad=='length':stream['bytes']+=1
    with pytest.raises(runtime.ControlFailure) as caught:
        control._script_nonce(runtime.new_context(),script,stream,control.time.monotonic()+5,{nonce} if bad=='reuse' else set())
    assert caught.value.reason==('nonce_collision' if bad in ('collision','reuse') else 'binding')
