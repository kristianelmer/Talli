"""Recovery orchestration never allocates on admission failure or replays repair."""
import hashlib
import json
import signal
import sys
import time
from copy import deepcopy
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from test_rf1086_identity_restore_runner import identity, DB, AUTH, ENV, SOURCE_URL
import rf1086_restore_control as control


@pytest.fixture
def repaired_model(tmp_path,monkeypatch):
    calls=[];owners=[];state={'metadata':0,'postchecks':0,'fault':None,'cleanupFault':False}
    role_raw=b'role observation'
    state['sourceCatalog']=b'[]\n{"datconnlimit":-1}\n[]\n'
    state['targetCatalog']=b'[]\n{"datconnlimit":10}\n[]\n'
    before=dict.fromkeys(('roles','catalog','auth','companyMemberships'),'a'*64)
    before['roles']=hashlib.sha256(role_raw).hexdigest()
    before['catalog']=hashlib.sha256(state['sourceCatalog']).hexdigest()
    metadata=SimpleNamespace(METADATA_SQL=b'metadata',ROLE_ORDER_SQL=b'role order',
        decode_metadata=lambda *a,**kw:SimpleNamespace(_catalog=state['sourceCatalog']),validate_role_order=lambda *a,**kw:None,
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
            if capture:=kwargs.get('catalog_capture'):capture.capture(state['sourceCatalog'])
            return dict(before)
        raw=state['sourceCatalog'] if state.get('recoverPass') else state['targetCatalog']
        if capture:=kwargs.get('catalog_capture'):
            capture.capture(raw);state['targetCapture']=capture
        return before|{'catalog':hashlib.sha256(raw).hexdigest()}
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
        state['receiptCalls']=state.get('receiptCalls',0)+1
        if state.get('diagnosticReceipt'):
            return json.dumps({'schema':control.SCHEMA,'status':'unavailable',
                'fingerprints':{'source':kwargs['before'],'target':kwargs['recovered']}},
                sort_keys=True,separators=(',',':'))
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
    captured=capsys.readouterr()
    assert captured.out==''
    lines=captured.err.splitlines()
    assert lines[:2]==[
        'owned_identity_restore_profile repair_profile_not_legacy_replay',
        'owned_identity_restore_construction {"schema":"fixture-safe-receipt"}']
    assert len(lines)==3 and lines[2].startswith(control.DIAGNOSTIC_PREFIX)
    observation=json.loads(lines[2][len(control.DIAGNOSTIC_PREFIX):])
    control.validate_pre_target_diagnostic(observation)
    assert observation['step']==('source_recheck' if fault=='source_drift' else 'unclassified')
    assert observation['reason']==fault and observation['inputs']['source']==state['receipt']['before']
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


def test_constructed_context_yields_same_budget_then_cleans_and_checks_source(repaired_model,tmp_path,monkeypatch,capsys):
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
    expected={'status':'fixture_wrapper_complete'}
    print(json.dumps(expected))
    captured=capsys.readouterr()
    assert json.loads(captured.out)==expected
    assert captured.out==json.dumps(expected)+'\n'
    assert captured.err.splitlines()==[
        'owned_identity_restore_profile repair_profile_not_legacy_replay',
        'owned_identity_restore_construction {"schema":"fixture-safe-receipt"}']


@pytest.mark.parametrize('step',[
    'source_fingerprint','source_roles','source_metadata_query','source_metadata_decode',
    'source_snapshot','source_snapshot_bind','source_preload','source_roles_dump',
    'source_archive_dump','source_recheck','target_admission',
])
def test_diagnostic_reports_only_the_actual_active_caller(repaired_model,tmp_path,monkeypatch,capsys,step):
    budget,state,calls,owners,_=repaired_model
    primary=ValueError('private source URL, SQL and error details')
    def fail(*args,**kwargs):raise primary
    module=sys.modules['rf1086_restore_metadata']
    if step=='source_fingerprint':monkeypatch.setattr(identity,'fingerprint',fail)
    elif step in ('source_roles','source_preload'):
        original=identity.source_query
        def source_query(container,statement,**kwargs):
            if (statement==identity.ROLE_SQL)==(step=='source_roles'):raise primary
            return original(container,statement,**kwargs)
        monkeypatch.setattr(identity,'source_query',source_query)
    elif step=='source_metadata_decode':monkeypatch.setattr(module,'decode_metadata',fail)
    elif step=='source_snapshot_bind':monkeypatch.setattr(module,'bind_source_snapshot',fail)
    elif step=='source_snapshot':monkeypatch.setattr(control,'source_fixed_snapshot',fail)
    elif step=='target_admission':monkeypatch.setattr(budget,'before_target',fail)
    else:
        original=budget.command
        metadata_calls=0
        def command(args,**kwargs):
            nonlocal metadata_calls
            if kwargs.get('data')==b'metadata':metadata_calls+=1
            if (step=='source_metadata_query' and metadata_calls==1
                or step=='source_recheck' and kwargs.get('data')==b'metadata' and metadata_calls==2
                or step=='source_roles_dump' and 'pg_dumpall' in args
                or step=='source_archive_dump' and 'pg_dump' in args):raise primary
            return original(args,**kwargs)
        monkeypatch.setattr(budget,'command',command)
    with pytest.raises(ValueError) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('unadmitted yield')
    assert caught.value is primary and not owners
    output=capsys.readouterr()
    assert output.out=='' and 'private source' not in output.err
    lines=[line for line in output.err.splitlines() if line.startswith(control.DIAGNOSTIC_PREFIX)]
    assert len(lines)==1
    value=json.loads(lines[0][len(control.DIAGNOSTIC_PREFIX):])
    assert value['step']==step and value['component']=='unknown' and value['reason']=='internal'
    assert state['receipt']['cleanup_complete']
    assert value['inputs']['source'] is None if step=='source_fingerprint' else value['inputs']['source'] is not None


def test_capture_is_disabled_before_uuid_or_any_target_setup(repaired_model,tmp_path,monkeypatch,capsys):
    budget,state,calls,owners,_=repaired_model
    primary=ValueError('later uuid error')
    def fail():raise primary
    monkeypatch.setattr(identity,'uuid4',fail)
    with pytest.raises(ValueError) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('unadmitted yield')
    assert caught.value is primary and not owners
    assert control.DIAGNOSTIC_PREFIX not in capsys.readouterr().err


def test_caller_cancellation_never_becomes_diagnostic_or_resource_admission(repaired_model,tmp_path,monkeypatch,capsys):
    budget,state,calls,owners,_=repaired_model
    primary=KeyboardInterrupt('private')
    original=budget.command
    def command(args,**kwargs):
        if 'pg_dump' in args:raise primary
        return original(args,**kwargs)
    monkeypatch.setattr(budget,'command',command)
    with pytest.raises(KeyboardInterrupt) as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('unadmitted yield')
    assert caught.value is primary and not owners
    assert state['receipt']['cleanup_complete'] and state['receipt']['source_postcheck']
    assert control.DIAGNOSTIC_PREFIX not in capsys.readouterr().err


def test_final_catalog_diagnostic_commits_exact_once_emitted_receipt_after_cleanup(repaired_model,tmp_path,capsys):
    budget,state,_,owners,_=repaired_model;state['diagnosticReceipt']=True
    with pytest.raises(ValueError,match='components=catalog'):
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('strict mismatch waived')
    output=capsys.readouterr();assert output.out==''
    receipt_line=next(line for line in output.err.splitlines() if line.startswith('owned_identity_restore_construction '))
    diagnostic_lines=[line for line in output.err.splitlines() if line.startswith('owned_identity_restore_catalog_diagnostic ')]
    assert len(diagnostic_lines)==1
    value=json.loads(diagnostic_lines[0].split(' ',1)[1])
    assert value['schema']=='rf1086-restore-catalog-diagnostic-v1' and value['status']=='observed'
    assert value['constructionSha256']==hashlib.sha256(receipt_line.split(' ',1)[1].encode()).hexdigest()
    assert value['source']=={'bytes':len(state['sourceCatalog']),'sha256':state['receipt']['before']['catalog']}
    assert value['target']=={'bytes':len(state['targetCatalog']),'sha256':state['receipt']['recovered']['catalog']}
    assert value['difference']['summary']==[{'kind':'database','status':'changed','records':1,
        'fields':[{'field':'datconnlimit','change':'value','count':1}]}]
    assert state['receiptCalls']==1 and owners[0].cleaned and state['receipt']['source_postcheck']
    assert budget.phase=='source_post' and state['targetCapture']._raw is None
    assert len(diagnostic_lines[0].encode())+1<=20*1024


def _catalog_receipt(source,target):
    fingerprints={key:dict.fromkeys(('roles','catalog','auth','companyMemberships'),'a'*64)
                  for key in ('source','target')}
    for key,raw in (('source',source),('target',target)):
        fingerprints[key]['catalog']=hashlib.sha256(raw).hexdigest()
    return control.ledger.canonical({'schema':control.SCHEMA,'status':'unavailable',
                                    'fingerprints':fingerprints}).decode('ascii')


def _publish_catalog(source,target,*,receipt=None,budget=None):
    receipt=receipt or _catalog_receipt(source,target)
    if budget is None:
        budget=control.RecoveryBudget(time.monotonic());budget.enter('source_post')
    control.publish_catalog_postcondition(budget,construction_raw=receipt,
        source_metadata=SimpleNamespace(_catalog=source),target_capture=SimpleNamespace(_raw=target),
        primary=ValueError('private primary'))
    return receipt,budget


def _catalog_line(capsys):
    output=capsys.readouterr();assert output.out==''
    lines=output.err.splitlines()
    assert len(lines)==1 and lines[0].startswith(control.CATALOG_DIAGNOSTIC_PREFIX)
    assert len(output.err.encode())<=20*1024 and 'private-' not in output.err
    return json.loads(lines[0][len(control.CATALOG_DIAGNOSTIC_PREFIX):])


@pytest.mark.parametrize('kind',['schema','relation','function','default_acl','column_acl',
    'policy','database','unknown_database_fields','settings','representation','truncated'])
def test_catalog_projection_preserves_classifier_vocabulary_and_raw_hashes(kind,capsys):
    from test_rf1086_catalog_difference import raw,ROWS
    source=raw();rows=deepcopy(ROWS)
    if kind=='database':target=raw(database={'datconnlimit':10})
    elif kind=='unknown_database_fields':
        source=raw(database={'private-a':1,'private-b':2})
        target=raw(database={'private-a':3,'private-b':4})
    elif kind=='settings':target=raw(settings=[])
    elif kind=='representation':target=raw(list(reversed(rows)))
    elif kind=='truncated':
        source=raw(rows=[['schema',f'private-{i}','owner',None] for i in range(80)])
        target=raw(rows=[])
    else:
        target=raw(rows=[row for row in ROWS if row[0]!=kind])
    receipt,budget=_publish_catalog(source,target)
    value=_catalog_line(capsys)
    assert value['status']=='observed' and budget.phase=='source_post'
    control.validate_catalog_postcondition(value,construction_raw=receipt)
    assert value['source']['sha256']==hashlib.sha256(source).hexdigest()
    assert value['target']['sha256']==hashlib.sha256(target).hexdigest()
    if kind=='representation':assert value['difference']['status']=='representation-only'
    if kind=='truncated':assert value['difference']['truncated'] and len(value['difference']['details'])==32


@pytest.fixture
def observed_catalog_diagnostic(capsys):
    source=b'[]\n{"datconnlimit":-1}\n[]\n';target=b'[]\n{"datconnlimit":10}\n[]\n'
    receipt,_=_publish_catalog(source,target)
    return _catalog_line(capsys),receipt


@pytest.mark.parametrize('mutation',[
    lambda v:v.update(extra='private-raw'),
    lambda v:v.update(constructionSha256='f'*64),
    lambda v:v['source'].update(bytes=True),
    lambda v:v['target'].update(bytes=8*1024*1024+1),
    lambda v:v['target'].update(sha256=v['source']['sha256']),
    lambda v:v['difference'].update(status='equal'),
    lambda v:v['difference'].update(qualification='accepted'),
    lambda v:v['difference']['counts'].update(changed=True),
    lambda v:v['difference'].update(sourceRecords=v['difference']['sourceRecords']+1),
    lambda v:v['difference']['summary'][0].update(records=2),
    lambda v:v['difference']['summary'][0].update(kind='private-kind'),
    lambda v:v['difference']['details'][0].update(schema='private-schema'),
    lambda v:v['difference']['details'][0].update(kind=[]),
    lambda v:v['difference']['details'][0].update(raw='private-raw'),
    lambda v:v['difference']['details'][0]['fields'][0].update(field='private-field'),
    lambda v:v['difference']['details'][0]['fields'][0].update(change='private-change'),
    lambda v:v['difference']['details'].append(deepcopy(v['difference']['details'][0])),
    lambda v:v['difference'].update(truncated=True),
    lambda v:v.update(status='unavailable',reason='input'),
])
def test_catalog_reader_rejects_malformed_or_unbound_projection(observed_catalog_diagnostic,mutation):
    value,receipt=observed_catalog_diagnostic;mutation(value)
    with pytest.raises(ValueError):control.validate_catalog_postcondition(value,construction_raw=receipt)


@pytest.mark.parametrize(('fault','reason'),[
    ('missing','input'),('oversize','input'),('hash','binding'),('raw','classifier'),('classifier','classifier')])
def test_catalog_diagnostic_invalid_inputs_and_classifier_never_reflect_values(fault,reason,monkeypatch,capsys):
    source=b'[]\n{}\n[]\n';target=b'[]\n{"datconnlimit":10}\n[]\n'
    if fault=='raw':source=b'private-invalid-catalog'
    receipt=_catalog_receipt(source,target)
    if fault=='missing':source=None
    if fault=='oversize':source=b'x'*(8*1024*1024+1)
    if fault=='hash':source=b'private-different-value'
    if fault=='classifier':
        monkeypatch.setattr(control.difference,'catalog_difference',lambda *a:{'raw':'private-catalog'})
    _publish_catalog(source,target,receipt=receipt)
    value=_catalog_line(capsys)
    assert value['status']=='unavailable' and value['reason']==reason
    assert value['source'] is value['target'] is value['difference'] is None
    control.validate_catalog_postcondition(value,construction_raw=receipt)


@pytest.mark.parametrize('fault',['classifier','cancel_classifier','cancel_write','broken_write',
    'expired','blocked_write','cleanup','source_post','missing_retention','broken_retention','cancel_retention'])
def test_catalog_diagnostic_failure_preserves_primary_cleanup_and_clears_capture(
        repaired_model,tmp_path,monkeypatch,capsys,fault):
    budget,state,_,owners,_=repaired_model;state['diagnosticReceipt']=True
    if fault=='cleanup':state['cleanupFault']=True
    original_publish=control.publish_catalog_postcondition;seen=[]
    def publish(value,**kwargs):
        seen.append(kwargs['primary'])
        assert owners[0].cleaned and value.phase=='source_post' and state['metadata']==3
        if fault=='expired':value.end=time.monotonic()-1
        if fault=='blocked_write':value.end=time.monotonic()+.03
        if fault.endswith('retention'):
            if fault=='missing_retention':kwargs['source_metadata']=object()
            else:
                class Broken:
                    @property
                    def _catalog(self):
                        if fault=='cancel_retention':raise KeyboardInterrupt('private-retention')
                        raise RuntimeError('private-retention')
                kwargs['source_metadata']=Broken()
        return original_publish(value,**kwargs)
    monkeypatch.setattr(control,'publish_catalog_postcondition',publish)
    if fault in ('classifier','cancel_classifier'):
        def fail(*a):
            if fault=='cancel_classifier':raise KeyboardInterrupt('private-classifier')
            raise ValueError('private-classifier')
        monkeypatch.setattr(control.difference,'catalog_difference',fail)
    if fault.endswith('write'):
        stderr=sys.stderr
        class Writer:
            def write(self,text):
                if text.startswith(control.CATALOG_DIAGNOSTIC_PREFIX):
                    if fault=='cancel_write':raise KeyboardInterrupt('private-write')
                    if fault=='broken_write':raise OSError('private-write')
                    time.sleep(.3)
                return stderr.write(text)
            def flush(self):return stderr.flush()
        monkeypatch.setattr(sys,'stderr',Writer())
    if fault=='source_post':
        command=budget.command
        def changed(args,**kwargs):
            raw=command(args,**kwargs)
            return b'changed' if kwargs.get('data')==b'metadata' and state['metadata']==3 else raw
        monkeypatch.setattr(budget,'command',changed)
    started=time.monotonic()
    with pytest.raises(ValueError,match='components=catalog') as caught:
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):
            raise AssertionError('strict mismatch waived')
    assert seen==[caught.value] and state['targetCapture']._raw is None
    assert owners[0].cleaned and state['postchecks']==3 and state['receiptCalls']==1
    assert budget.context.owner.cancelled is fault.startswith('cancel_')
    output=capsys.readouterr();assert output.out=='' and 'private-' not in output.err
    if fault in ('expired','blocked_write'):
        assert control.CATALOG_DIAGNOSTIC_PREFIX not in output.err
    if fault=='blocked_write':assert time.monotonic()-started<.25
    assert signal.getitimer(signal.ITIMER_REAL)[0]==0


def test_non_catalog_mismatch_does_not_publish_catalog_diagnostic(repaired_model,tmp_path,monkeypatch,capsys):
    budget,state,_,_,_=repaired_model;state['recoverPass']=True
    original=identity.fingerprint
    def fingerprint(container,**kwargs):
        value=original(container,**kwargs)
        return value if container==DB['Id'] else value|{'auth':'f'*64}
    monkeypatch.setattr(identity,'fingerprint',fingerprint)
    with pytest.raises(ValueError,match='components=auth'):
        with identity.restored_identity(SOURCE_URL,tmp_path,None,budget=budget):pass
    assert control.CATALOG_DIAGNOSTIC_PREFIX not in capsys.readouterr().err
    assert state['targetCapture']._raw is None


def test_classifier_and_publication_share_one_end_no_write_after_elapsed(monkeypatch,capsys):
    source=b'[]\n{}\n[]\n';target=b'[]\n{"datconnlimit":10}\n[]\n'
    value=control.RecoveryBudget(time.monotonic());value.enter('source_post');end=value.end
    now=time.monotonic();clock=[now]
    original=control.difference.catalog_difference
    def classify(*args):
        assert 0<signal.getitimer(signal.ITIMER_REAL)[0]<=1
        result=original(*args);clock[0]=now+1.1;return result
    monkeypatch.setattr(control.difference,'catalog_difference',classify)
    monkeypatch.setattr(control.time,'monotonic',lambda:clock[0])
    _publish_catalog(source,target,budget=value)
    assert capsys.readouterr().err=='' and value.phase=='source_post' and value.end==end
    assert signal.getitimer(signal.ITIMER_REAL)[0]==0


def test_catalog_envelope_limit_is_total_line_and_unavailable_is_closed(monkeypatch,capsys):
    source=b'[]\n{}\n[]\n';target=b'[]\n{"datconnlimit":10}\n[]\n'
    fields=sorted(control.difference._DATABASE_FIELDS)
    changes=[{'field':field,'change':'value'} for field in fields]
    oversized={'status':'different','sourceRecords':32,'targetRecords':32,
        'counts':{'changed':32,'source-only':0,'target-only':0},
        'summary':[{'kind':'database','status':'changed','records':32,
                    'fields':[item|{'count':32} for item in changes]}],
        'details':[{'kind':'database','schema':'unclassified',
                    'identitySha256':hashlib.sha256(str(i).encode()).hexdigest(),
                    'status':'changed','fields':deepcopy(changes)} for i in range(32)],
        'truncated':False,'qualification':'diagnostic-only-strict-fingerprint-unchanged'}
    assert len(control.ledger.canonical(oversized))>20*1024
    monkeypatch.setattr(control.difference,'catalog_difference',lambda *a:oversized)
    receipt,_=_publish_catalog(source,target)
    value=_catalog_line(capsys)
    assert value['status']=='unavailable' and value['reason']=='limit'
    control.validate_catalog_postcondition(value,construction_raw=receipt)
