"""Fresh full-stream controls and durable evidence across interrupted workers."""
import io
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

from cryptography.hazmat.primitives import serialization
import pytest

from test_rf1086_actual_replay import setup, key, toc
import rf1086_actual_replay as replay
import rf1086_actual_replay_package as package


def completed(f2, optional, *, reason='dependency', stage='admission'):
    return f2 | {'schema': 'actual-image-control-v2', 'Fsql': optional,
                 'S0': {'schema': 's0-checkpoint-v1', 'status': 'unavailable',
                        'reason': reason, 'stage': stage, 'point': None}}


@pytest.fixture
def control(setup):
    import rf1086_identity_restore as identity
    catalog = {'serverVersion': 170006, **{k: [] for k in ('schemas', 'functions', 'hooks', 'events', 'extensions')}}
    setup['causal'].replay_snapshots = {
        'source_pre_dump': {'catalog': catalog, 'catalogSha256': setup['before']['catalog'],
            'sourceCommandSha256': 'c' * 64, 'files': {'status': 'unavailable'}},
        'target_initialized': {'catalog': catalog, 'initSha256': package.digest(identity.INIT.encode())},
        'mismatch': {'catalog': catalog, 'catalogSha256': setup['failed']['catalog'],
            'archive': {'status': 'observed', 'value': {'bytes': len(setup['dump'].getvalue()),
                'sha256': package.digest(setup['dump'].getvalue())}}}}
    setup['init'] = identity.INIT
    setup['roles'] = io.BytesIO(b'CREATE ROLE supabase_admin;\nALTER ROLE supabase_admin WITH SUPERUSER;\n')
    assert package.publish(**setup)
    path, metadata, hashed = package.read_package()
    f2 = {'status': 'full_control_verified', 'fingerprint': metadata['failed'], 'F2EqualsF': True,
        'causalSnapshotEqualsF': True, 'catalog': catalog, 'inventory': replay.toc_inventory(toc()),
        'schemaWriterSql': {'bytes': 3, 'sha256': 'd' * 64, 'coverage': 'schema-only-not-complete-writer-proof'},
        'installedFiles': {}, 'netSourceAttributesObserved': True, 'S0': 'unavailable', 'Is': 'unavailable',
        'In': 'archive_function_equivalence_unproved', 'reason': 'session_boundary_unproved',
        'causalAttributionAccepted': False, 'recoveryAccepted': False,
        'input': {k: metadata[k] for k in replay.INPUT_KEYS}, 'sourceCommandSha256': 'c' * 64,
        'sourceInstalledFiles': {'status': 'unavailable'}}
    optional = {'status': 'full_sql_verified', 'stream': {'bytes': 3, 'sha256': 'e' * 64},
        'tool': {'version': '17.6', 'sha256': 'f' * 64}, 'initializedEqualsOriginal': True,
        'freshTarget': True, 'fingerprint': metadata['failed'], 'catalog': catalog,
        'FsqlEqualsF2': True, 'causalSnapshotEqualsF2': True,
        'recoveryAccepted': False, 'causalAttributionAccepted': False,
        'ledger': replay.sql_ledger.unavailable('headroom', 'admission')}
    return path, metadata, f2, optional, hashed, setup['failed_raw']


@pytest.mark.parametrize('ledger_fault', ['unavailable', 'error', 'cancel'])
def test_full_script_is_unfiltered_unchanged_and_uses_fresh_initialized_target(control, monkeypatch, ledger_fault):
    path, metadata, _, _, _, failed = control
    script = b'COPY fixture FROM stdin;\n-- TOC entry 99999\n\\.\n\\connect postgres\n'
    calls = []
    def command(args, deadline, **kw):
        calls.append(('command', args, deadline, kw))
        if args[-1] == replay.TOOL_COMMAND: return b'pg_restore (PostgreSQL) 17.6\n' + b'f' * 64 + b'\n'
        assert kw['archive'].read() == b'private-archive'
        assert args[-1] == 'test -p /proc/self/fd/0 && exec pg_restore --verbose --clean --if-exists --create --file=- 2>/dev/null'
        assert kw['cap'] == 128 * 1024**2
        return script
    monkeypatch.setattr(replay, 'command', command)
    monkeypatch.setattr(replay, 'cleanup_resources', lambda *a: calls.append(('cleanup', a)) or True)
    monkeypatch.setattr(replay, 'start_target', lambda *a: calls.append(('start', a)) or 'new')
    monkeypatch.setattr(replay, 'psql', lambda *a, **kw: calls.append(('psql', a, kw)))
    monkeypatch.setattr(replay, '_snapshot', lambda *a, **kw: metadata['phases']['target_initialized']['catalog'])
    monkeypatch.setattr(replay, 'failed_state', lambda *a: (metadata['failed'], metadata['phases']['mismatch']['catalog']))
    def observe(p, actual_script, toc, m, inventory, fsql, deadline, **kw):
        assert actual_script is script and fsql['FsqlEqualsF2'] is True
        assert fsql['fingerprint'] == metadata['failed']
        if ledger_fault == 'error': raise RuntimeError('synthetic-private-canary')
        if ledger_fault == 'cancel': raise KeyboardInterrupt()
        return replay.sql_ledger.unavailable('role', 'emitter')
    monkeypatch.setattr(replay.sql_ledger, 'observe', observe)
    if ledger_fault == 'cancel':
        with pytest.raises(KeyboardInterrupt):
            replay.full_sql_control(path, metadata, 'old', b'fixed roles', failed, 999)
        return
    result = replay.full_sql_control(path, metadata, 'old', b'fixed roles', failed, 999)
    assert calls[2][0] == 'cleanup' and calls[3][0] == 'start'
    assert [c[1][1] for c in calls if c[0] == 'psql'] == [b'fixed roles', b'drop database postgres with (force);', script]
    assert [c[2].get('database') for c in calls if c[0] == 'psql'] == [None, 'template1', 'template1']
    assert result['stream'] == {'bytes': len(script), 'sha256': package.digest(script)}
    assert result['fingerprint'] == metadata['failed'] and result['FsqlEqualsF2']
    assert result['recoveryAccepted'] is result['causalAttributionAccepted'] is False
    assert result['ledger']['status'] == 'unavailable'
    assert result['ledger']['reason'] == ('role' if ledger_fault == 'unavailable' else 'internal')


def test_summary_reduces_ledger_before_verified_fsql(control, monkeypatch):
    path, metadata, f2, optional, _, _ = control
    reduced = optional | {'ledger': replay.sql_ledger.unavailable('summary', 'summary')}
    size = len(package._encoded(completed(f2, reduced, reason='summary_oversized', stage='composition') | {'optionalWorkerOutcome': 'result_invalid', 'ownedCleanupComplete': False}))
    monkeypatch.setattr(replay, 'MAX_PLAINTEXT', size)
    optional['ledger'] = {'syntheticOversizedShape': 'x'*4096}
    result = replay.fit_optional(f2, optional, metadata)
    assert result['Fsql'] == reduced and result['Fsql']['status'] == 'full_sql_verified'
    assert result['fingerprint'] == f2['fingerprint']


@pytest.mark.parametrize('fault', ['tool', 'empty', 'generation_failure', 'cleanup', 'same_target', 'initialized'])
def test_full_sql_rejects_before_unproved_execution(control, monkeypatch, fault):
    path, metadata, _, _, _, failed = control
    calls = []
    def command(args, *a, **kw):
        if args[-1] == replay.TOOL_COMMAND:
            return b'invalid' if fault == 'tool' else b'pg_restore (PostgreSQL) 17.6\n' + b'f' * 64 + b'\n'
        if fault == 'generation_failure': raise package.Unavailable('command_unavailable')
        return b'' if fault == 'empty' else b'full script'
    monkeypatch.setattr(replay, 'command', command)
    monkeypatch.setattr(replay, 'cleanup_resources', lambda *a: fault != 'cleanup')
    monkeypatch.setattr(replay, 'start_target', lambda *a: calls.append('start') or ('old' if fault == 'same_target' else 'new'))
    monkeypatch.setattr(replay, 'psql', lambda *a, **kw: calls.append(a[1]))
    monkeypatch.setattr(replay, '_snapshot', lambda *a, **kw: {'unexpected': True})
    with pytest.raises(package.Unavailable): replay.full_sql_control(path, metadata, 'old', b'roles', failed, 999)
    assert b'full script' not in calls
    if fault in ('tool', 'empty', 'generation_failure', 'cleanup'): assert 'start' not in calls


@pytest.mark.parametrize('fault', ['roles', 'auth', 'companyMemberships', 'catalog', 'raw', 'causal'])
def test_every_strict_comparison_remains_required(control, monkeypatch, fault):
    import rf1086_identity_restore as identity
    _, metadata, _, _, _, failed = control
    original = identity.checked
    def fingerprint(*a, catalog_capture, **kw):
        catalog_capture.capture(b'changed' if fault == 'raw' else failed)
        return metadata['failed'] | ({fault: 'changed'} if fault not in ('raw', 'causal') else {})
    monkeypatch.setattr(identity, 'fingerprint', fingerprint)
    monkeypatch.setattr(replay, '_snapshot', lambda *a, **kw: {'changed': True})
    with pytest.raises(package.Unavailable): replay.failed_state('target', metadata, failed, time.monotonic()+5)
    assert identity.checked is original


@pytest.mark.parametrize('fault', ['deadline', 'failure', 'cancel'])
def test_saved_f2_precedes_optional_work_and_deadline_reserve(control, monkeypatch, fault):
    path, metadata, f2, _, _, failed = control
    called = []
    def optional(*args, **kwargs):
        assert replay.read_f2(path, metadata) == f2
        assert not (path / 'f2.pending').exists()
        called.append(args[-1])
        if fault == 'cancel': raise KeyboardInterrupt()
        raise package.Unavailable('command_unavailable')
    monkeypatch.setattr(replay, 'full_sql_control', optional)
    start = time.monotonic(); deadline = start + (5 if fault == 'deadline' else 416)
    if fault == 'cancel':
        with pytest.raises(KeyboardInterrupt): replay.add_full_sql(path, metadata, 'old', b'roles', failed, f2, deadline)
    else:
        result = replay.add_full_sql(path, metadata, 'old', b'roles', failed, f2, deadline)
        assert result['fingerprint'] == f2['fingerprint'] and result['Fsql']['status'] == 'unavailable'
        assert result['Fsql']['reason'] == ('insufficient_headroom' if fault == 'deadline' else 'command_unavailable')
    assert called == ([] if fault == 'deadline' else [deadline-12])


@pytest.mark.parametrize('fault', ['partial', 'fingerprint', 'catalog', 'input', 'source', 'accepted', 'extra', 'symlink'])
def test_partial_or_tampered_checkpoints_never_accept_f2(control, fault):
    path, metadata, f2, _, _, _ = control
    if fault == 'partial': package.write_private(path / 'f2.pending', package._encoded(f2))
    else:
        if fault == 'fingerprint': f2['fingerprint'] = metadata['failed'] | {'roles': 'bad'}
        elif fault == 'catalog': f2['catalog'] = {'bad': True}
        elif fault == 'input': f2['input'] = {}
        elif fault == 'source': f2['sourceCommandSha256'] = 'a' * 64
        elif fault == 'accepted': f2['recoveryAccepted'] = True
        elif fault == 'extra': f2['unexpected'] = 'bad'
        package.write_private(path / 'f2.json', package._encoded(f2))
        if fault == 'symlink':
            (path / 'f2.json').rename(path / 'f2.pending');(path / 'f2.json').symlink_to(path / 'f2.pending')
    result = replay.fallback_result(path, metadata, 'deadline')
    assert result == {'schema': 'actual-image-control-v2', 'status': 'unavailable',
                      'reason': 'worker_deadline', 'recoveryAccepted': False,
                      'S0': {'schema': 's0-checkpoint-v1', 'status': 'unavailable',
                             'reason': 'worker_deadline', 'stage': 'unobserved', 'point': None}}


@pytest.mark.parametrize('fault', ['fingerprint', 'catalog', 'version', 'hash', 'zero_bytes', 'too_large', 'accepted', 'extra'])
def test_completed_optional_success_needs_all_bindings(control, fault):
    _, metadata, _, optional, _, _ = control
    if fault == 'fingerprint': optional['fingerprint'] = {'bad': True}
    elif fault == 'catalog': optional['catalog'] = {'bad': True}
    elif fault == 'version': optional['tool']['version'] = '17.11'
    elif fault == 'hash': optional['tool']['sha256'] = 'private-canary'
    elif fault == 'zero_bytes': optional['stream']['bytes'] = 0
    elif fault == 'too_large': optional['stream']['bytes'] = replay.MAX_SQL_BYTES+1
    elif fault == 'accepted': optional['recoveryAccepted'] = True
    else: optional['extra'] = 'private-canary'
    with pytest.raises(package.Unavailable): replay.validate_fsql(optional, metadata)


def test_optional_size_fallback_reserves_consumer_fields_and_crypto_framing(control, monkeypatch, key):
    _, metadata, f2, optional, _, _ = control
    fallback = completed(f2, replay.unavailable_fsql('summary_oversized'), reason='summary_oversized', stage='composition')
    size = len(package._encoded(fallback | {'optionalWorkerOutcome': 'result_invalid', 'ownedCleanupComplete': False}))
    monkeypatch.setattr(replay, 'MAX_PLAINTEXT', size)
    result = replay.fit_optional(f2, optional, metadata)
    assert result['Fsql']['reason'] == 'summary_oversized'
    result.update(optionalWorkerOutcome='result_invalid', ownedCleanupComplete=False)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    aad = {'version': 2, **metadata['binding'], 'image': package.IMAGE, 'packageSha256': 'a'*64, 'publicKeySha256': package.digest(public)}
    line = replay.seal(result, aad, key.public_key())
    assert len(line.encode()) <= replay.MAX_ENVELOPE
    assert replay.decrypt(line, key, {k:v for k,v in aad.items() if k!='version'}) == result
    monkeypatch.setattr(replay, 'MAX_PLAINTEXT', size-1)
    with pytest.raises(package.Unavailable): replay.fit_optional(f2, optional, metadata)


def test_command_unwind_leaves_publication_reserve(control, monkeypatch):
    path, metadata, f2, _, _, failed = control
    ticks=[100.0]
    monkeypatch.setattr(replay.time,'monotonic',lambda:ticks[0])
    def late(*args, **kwargs):
        assert args[-1]==504.0
        ticks[0]=506.0  # The optional command plus its full two-second unwind.
        raise package.Unavailable('command_unavailable')
    monkeypatch.setattr(replay,'full_sql_control',late)
    result=replay.add_full_sql(path,metadata,'old',b'roles',failed,f2,516.0)
    package.write_private(path/'result.json',package._encoded(result))
    assert replay.completed_result(path,metadata)['Fsql']['reason']=='command_unavailable'
    assert 516.0-ticks[0]==10.0


WORKER = r'''
import json,os,signal,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import rf1086_actual_replay as r
path,metadata,f2,optional,mode,ack=json.loads(sys.argv[2])
path=Path(path)
r.FSQL_HEADROOM_SECONDS=0
r.FSQL_RESERVE_SECONDS=0.1
if mode=='oversized':r.MAX_PLAINTEXT=int(os.environ['TEST_FSQL_MAX'])
r.read_package=lambda:(path,metadata,'a'*64)
def stage(*args, **kwargs):
    os.write(ack,b'1');os.close(ack)
    if mode=='failed':raise SystemExit(2)
    if mode=='oversized':return optional
    if mode=='invalid':
        (path/'result.json').write_text('invalid')
        (path/'result.json').chmod(0o600)
        raise SystemExit(0)
    signal.pause()
r.full_sql_control=stage
r.replay=lambda p,m,d,**kw:r.add_full_sql(p,m,'old',b'roles',b'catalog',f2,d,**kw)
r.worker()
'''


@pytest.mark.parametrize('mode,expected', [('deadline','worker_deadline'), ('failed','worker_failed'),
    ('invalid','worker_result_invalid'), ('oversized','summary_oversized'), ('cancel',None),
    ('reap_failure',None), ('signal_failure',None), ('cancel_signal_failure',None)])
def test_real_worker_interruption_preserves_checkpoint_after_reaping(control, monkeypatch, key, tmp_path, capsys, mode, expected):
    path, metadata, f2, optional, hashed, _ = control
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    pub = tmp_path/'test.pub';pub.write_bytes(public)
    monkeypatch.setattr(replay, 'PUBLIC_KEY_PATH', pub)
    monkeypatch.setattr(replay, 'ACTIVE_SECONDS', 3)
    if mode=='oversized':
        limit=max(len(package._encoded(completed(f2, replay.unavailable_fsql(reason), reason='worker_result_invalid', stage='unobserved') | {
            'optionalWorkerOutcome':'result_invalid','ownedCleanupComplete':False})) for reason in replay.FSQL_REASONS)
        monkeypatch.setenv('TEST_FSQL_MAX',str(limit))
        monkeypatch.setattr(replay,'MAX_PLAINTEXT',limit)
    monkeypatch.setenv('TALLI_RF_REPLAY_JOB_STARTED', str(time.monotonic()))
    monkeypatch.setattr(replay, 'read_package', lambda:(path,metadata,hashed))
    original_popen = subprocess.Popen;original_read = replay.read_private;original_killpg=os.killpg
    children=[];events=[];cleanup_waits={};direct_kills=[];group_signals=[]
    cancellation=KeyboardInterrupt()
    def popen(args, **kwargs):
        rd,wr=os.pipe()
        try:
            payload=json.dumps([str(path),metadata,f2,optional,mode,wr])
            child=original_popen([sys.executable,'-c',WORKER,str(Path(replay.__file__).parent),payload],
                pass_fds=(wr,),**kwargs)
            cleanup_waits[child.pid]=child.wait
            children.append(child);os.close(wr);wr=None
            with selectors.DefaultSelector() as select:
                select.register(rd,selectors.EVENT_READ)
                assert select.select(3), 'worker never reached saved-checkpoint stage'
                assert os.read(rd,1)==b'1'
            if mode in ('cancel','reap_failure','signal_failure','cancel_signal_failure'):
                original_wait=child.wait;waits=[]
                def wait(*a,**kw):
                    waits.append(1)
                    if len(waits)==1:
                        if mode in ('cancel','cancel_signal_failure'):raise cancellation
                        raise subprocess.TimeoutExpired('owned_worker',3)
                    if len(waits)==2 and mode=='reap_failure':raise RuntimeError('reap_unproved')
                    return original_wait(*a,**kw)
                child.wait=wait
            if mode in ('signal_failure','cancel_signal_failure'):
                original_kill=child.kill
                def kill():
                    direct_kills.append(child.pid)
                    return original_kill()
                child.kill=kill
            return child
        finally:
            os.close(rd)
            if wr is not None:os.close(wr)
    def read(file, limit):
        if file.name=='f2.json':
            assert children and children[-1].poll() is not None
            events.append('read_after_reap')
        return original_read(file,limit)
    monkeypatch.setattr(replay.subprocess,'Popen',popen)
    monkeypatch.setattr(replay,'read_private',read)
    monkeypatch.setattr(replay,'cleanup_resources',lambda *a:events.append('cleanup') or True)
    if mode in ('signal_failure','cancel_signal_failure'):
        def fail_group(pid,sig):
            group_signals.append((pid,sig))
            raise PermissionError('injected_group_signal_failure')
        monkeypatch.setattr(replay.os,'killpg',fail_group)
    # consume temporarily ignores these during cleanup; restore the test process.
    handlers={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
    try:
        if mode in ('cancel','reap_failure','signal_failure','cancel_signal_failure'):
            with pytest.raises(KeyboardInterrupt if mode in ('cancel','cancel_signal_failure') else package.Unavailable) as failure:
                replay.consume()
            assert capsys.readouterr().out=='' and events==['cleanup']
            if mode in ('cancel','cancel_signal_failure'):assert failure.value is cancellation
            if mode in ('signal_failure','cancel_signal_failure'):
                assert direct_kills==[children[0].pid] and group_signals==[(children[0].pid,signal.SIGKILL)]
                assert children[0].poll() is not None
            return
        replay.consume()
        line=capsys.readouterr().out.strip()
        expected_aad={**metadata['binding'],'image':package.IMAGE,'packageSha256':hashed,'publicKeySha256':package.digest(public)}
        result=replay.decrypt(line,key,expected_aad)
        assert result['F2EqualsF'] and result['fingerprint']==f2['fingerprint']
        assert result['Fsql']==replay.unavailable_fsql(expected)
        assert result['optionalWorkerOutcome']==({'invalid':'result_invalid','oversized':'completed'}.get(mode,mode))
        assert result['ownedCleanupComplete'] and events==(['cleanup'] if mode=='oversized' else ['read_after_reap','cleanup'])
        assert all(c.poll() is not None for c in children)
    finally:
        for child in children:
            # The simulated reap failure follows a real SIGKILL. Reap that
            # child with the original method before considering another signal.
            try:cleanup_waits[child.pid](timeout=2)
            except subprocess.TimeoutExpired:
                try:original_killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                cleanup_waits[child.pid](timeout=2)
        for sig,handler in handlers.items():signal.signal(sig,handler)
