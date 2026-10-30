"""Owned Python peers exercise branch barriers; no PostgreSQL or Docker."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import rf1086_s0_control as control
from test_rf1086_s0_control import children


PEER = r'''
import hashlib,json,os,select,sys,time
role,nonce,mode,journal=sys.argv[1:5]
def write(data):
    while data:
        n=os.write(1,data[:7]); data=data[n:]
def frame(kind,seq,value,suffix=''):
    write(f'C1{kind}/{nonce}/{seq:02d}/{suffix}'.encode()+json.dumps(value,separators=(',',':')).encode().hex().encode()+b'\n')
def exact(n):
    out=bytearray()
    while len(out)<n:
        raw=os.read(0,min(4096,n-len(out)))
        if not raw: raise RuntimeError('short input')
        out.extend(raw)
    return bytes(out)
if role=='writer':
    points=json.loads(sys.argv[5]); size=int(sys.argv[6]); mutation=bytes.fromhex(sys.argv[7]); count=0; h=hashlib.sha256()
    for seq,(point,offset) in enumerate(points):
        if point[0]=='post':
            if exact(len(mutation))!=mutation: raise RuntimeError('mutation differs')
            with open(journal,'a') as f:f.write('mutation\n')
        original=exact(offset-count); h.update(original); count=offset
        if exact(len(f'P/{nonce}/{seq:02d}\n'))!=f'P/{nonce}/{seq:02d}\n'.encode():raise RuntimeError('P input')
        epoch=point[1] if point[0]=='anchor' else (1 if point[1]<2 else 2)
        pid=1000+epoch
        frame('P',seq,['template1' if epoch==0 else 'postgres',pid])
        if exact(len(f'Q/{nonce}/{seq:02d}\n'))!=f'Q/{nonce}/{seq:02d}\n'.encode():raise RuntimeError('Q input')
        write(f'C1B/{nonce}/{seq:02d}/{pid}\n'.encode())
        if select.select([0],[],[],.03)[0] and os.read(0,1):raise RuntimeError('future input during pause')
        with open(journal,'a') as f:f.write('paused:'+str(seq)+'\n')
        if mode=='late' and point[0]=='post':frame('P',seq,['postgres',pid])
        if mode=='pressure' and point[0]=='post':
            # Write enough ordinary output to require concurrent drainage while
            # the observer has EOF but remains alive waiting for this journal.
            raw=b'x'*262144+b'\n'
            while raw:
                n=os.write(1,raw[:4096]);raw=raw[n:]
            with open(journal,'a') as f:f.write('drained\n')
    h.update(exact(size-count))
    if os.read(0,1):raise RuntimeError('trailing input')
    with open(journal,'a') as f:f.write('original:'+h.hexdigest()+'\n')
else:
    req=json.loads(sys.stdin.buffer.read(4096));point,seq,pid=req['point'],req['seq'],req['pid']
    roles=['anchor'] if point[0]=='anchor' else ['before','catalog','after']
    for part in roles:
        if part=='catalog':write(json.dumps({'point':point}).encode()+b'\n')
        else:frame('O',seq,['postgres','1',pid,'1','postgres','epoch'+str(pid)],part+'/')
    if point[0]=='post' and mode=='stderr':os.write(2,b'x')
    if point[0]=='post' and mode=='nonzero':sys.exit(2)
    if mode=='pressure' and point[0]=='post':
        os.close(1);os.close(2);end=time.monotonic()+2
        while time.monotonic()<end:
            if os.path.exists(journal) and 'drained\n' in open(journal).read():break
            time.sleep(.001)
        else:sys.exit(3)
    else:time.sleep(.06)
'''


def branch_call(tmp_path, mode='normal', *, mutation_index=1, epochs=3):
    script=b'x'*700; nonce='d'*32; journal=tmp_path/'journal'; context=control.new_context()
    points=[(('anchor',0),0),(('anchor',1),100),(('cut',0),200),(('cut',1),300)]
    if epochs==3:points.append((('anchor',2),400))
    points.append((('cut',2),500))
    position=next(i for i,(p,_) in enumerate(points) if p==('cut',mutation_index))
    points.insert(position+1,(('post',mutation_index),points[position][1]))
    sql=b'BEGIN;\nSELECT 1;\nCOMMIT;\n'; confirmed=[]
    def argv(role):return [sys.executable,'-c',PEER,role,nonce,mode,str(journal)]
    def request(point,seq,pid):return argv('observer'),json.dumps(dict(point=point,seq=seq,pid=pid)).encode()
    def session(raw,**kw):return json.loads(raw)
    def witness(raw,**kw):return json.loads(raw)
    def probe(nonce,seq):return tuple(f'{p}/{nonce}/{seq:02d}\n'.encode() for p in ('P','Q'))
    def confirm(exchange):
        assert all(s.process is None or s.process.args==writer for s in context.owner.slots)
        confirmed.append(tuple(exchange['point']))
    writer=argv('writer')+[json.dumps(points),str(len(script)),sql.hex()]
    args=dict(script=script,descriptor={'cuts':[[1],[1],[2 if epochs==3 else 1]]},
        ledger={'selected':[{}, {}, {}]},context=context,nonce=nonce,writer_args=writer,
        observer_request=request,parse_session=session,parse_witness=witness,
        project=lambda raw,selected:json.loads(raw),probe=probe,points=points,
        work_end=time.monotonic()+15,reap_end=time.monotonic()+17,
        mutation_policy=control.MutationPolicy('Is' if mutation_index==1 else 'In',
            ('cut',mutation_index),sql),exchange_complete=confirm)
    return args,journal,confirmed


@pytest.mark.parametrize('epochs',[2,3])
def test_branch_mutation_is_separate_delivery_and_post_reap_precedes_suffix(tmp_path,children,epochs):
    args,journal,confirmed=branch_call(tmp_path,epochs=epochs)
    result=control.transport(**args)
    assert len(result['exchanges'])==epochs+4
    assert confirmed==[point for point,_ in args['points']]
    assert result['delivery']['original']==dict(bytes=700,sha256=hashlib.sha256(args['script']).hexdigest())
    sql=args['mutation_policy'].sql
    assert result['delivery']['mutation']==dict(bytes=len(sql),sha256=hashlib.sha256(sql).hexdigest())
    probes=b''.join(x for i in range(epochs+4) for x in args['probe'](args['nonce'],i))
    assert result['delivery']['probes']==dict(bytes=len(probes),sha256=hashlib.sha256(probes).hexdigest())
    assert journal.read_text().count('mutation\n')==1
    assert all(c.returncode==0 for c in children)
    assert all(s.process is None for s in args['context'].owner.slots)


def measured_writes(monkeypatch):
    original=os.write; totals={'original':0,'mutation':0}; mutation=[False]
    def write(fd,data):
        n=original(fd,data)
        if bytes(data[:1])==b'x':totals['original']+=n
        if bytes(data).startswith(b'BEGIN;\n'):mutation[0]=True
        if mutation[0]:
            totals['mutation']+=n
            if bytes(data[:n]).endswith(b'COMMIT;\n'):mutation[0]=False
        return n
    monkeypatch.setattr(control.os,'write',write)
    return totals


@pytest.mark.parametrize('where',['pre','post'])
def test_admission_or_post_comparison_failure_never_delivers_suffix(tmp_path,children,monkeypatch,where):
    args,journal,confirmed=branch_call(tmp_path); counts=measured_writes(monkeypatch)
    original=args['exchange_complete']; point=('cut',1) if where=='pre' else ('post',1)
    def reject(exchange):
        original(exchange)
        if tuple(exchange['point'])==point:raise control.ControlFailure('prefix_mismatch',point)
    args['exchange_complete']=reject
    with pytest.raises(control.ControlFailure) as caught:control.transport(**args)
    assert caught.value.point==point and counts['original']==300
    assert counts['mutation']==(0 if where=='pre' else len(args['mutation_policy'].sql))
    assert 'original:' not in journal.read_text()
    assert all(c.returncode is not None for c in children)
    assert all(s.process is None for s in args['context'].owner.slots)


@pytest.mark.parametrize('mode,reason',[('late','frame'),('stderr','observer'),('nonzero','observer')])
def test_post_observer_or_late_reserved_frame_failure_stops_at_mutation_cut(tmp_path,children,monkeypatch,mode,reason):
    args,journal,_=branch_call(tmp_path,mode); counts=measured_writes(monkeypatch)
    with pytest.raises(control.ControlFailure) as caught:control.transport(**args)
    assert (caught.value.reason,caught.value.point)==(reason,('post',1))
    assert counts['original']==300 and counts['mutation']==len(args['mutation_policy'].sql)
    assert all(c.returncode is not None for c in children)
    assert 'original:' not in journal.read_text()


def test_post_observer_eof_continues_draining_writer_backpressure(tmp_path,children):
    args,journal,_=branch_call(tmp_path,'pressure')
    value=control.transport(**args)
    assert 'drained\n' in journal.read_text() and value['delivery']['writer']['stdoutBytes']>262144
    assert all(c.returncode==0 for c in children)


def test_eagain_and_actual_short_mutation_writes_keep_exact_bytes(tmp_path,children,monkeypatch):
    args,journal,_=branch_call(tmp_path); original=os.write; attempts=[0]; sizes=[]
    def short_write(fd,data):
        attempts[0]+=1
        if attempts[0]%7==1:raise BlockingIOError()
        n=original(fd,data[:7]);sizes.append((len(data),n));return n
    monkeypatch.setattr(control.os,'write',short_write)
    value=control.transport(**args)
    assert any(0<n<size for size,n in sizes)
    assert value['delivery']['mutation']['sha256']==hashlib.sha256(args['mutation_policy'].sql).hexdigest()
    assert 'original:'+hashlib.sha256(args['script']).hexdigest() in journal.read_text()
    assert all(c.returncode==0 for c in children)


def test_cancel_after_partial_mutation_preserves_identity_and_reaps_writer(tmp_path,children,monkeypatch):
    args,journal,_=branch_call(tmp_path); original=os.write; primary=KeyboardInterrupt(); sent=[]
    def cancel(fd,data):
        if bytes(data).startswith(b'BEGIN;\n'):
            sent.append(original(fd,data[:7]));raise primary
        return original(fd,data)
    monkeypatch.setattr(control.os,'write',cancel)
    with pytest.raises(KeyboardInterrupt) as caught:control.transport(**args)
    assert caught.value is primary and args['context'].owner.primary is primary and sent==[7]
    assert all(c.returncode is not None for c in children)
    assert 'mutation\n' not in journal.read_text() and 'original:' not in journal.read_text()


def test_mutation_work_expires_at_two_seconds_not_remaining_writer_budget(tmp_path,children,monkeypatch):
    args,journal,_=branch_call(tmp_path); original=os.write; clock=time.monotonic; shifted=[0.0]
    monkeypatch.setattr(control.time,'monotonic',lambda:clock()+shifted[0])
    def write(fd,data):
        if bytes(data).startswith(b'BEGIN;\n'):
            n=original(fd,data[:7]);shifted[0]=2.01;return n
        return original(fd,data)
    monkeypatch.setattr(control.os,'write',write)
    with pytest.raises(control.ControlFailure) as caught:control.transport(**args)
    assert (caught.value.reason,caught.value.point)==('deadline',('cut',1))
    assert all(c.returncode is not None for c in children)
    assert 'mutation\n' not in journal.read_text() and 'original:' not in journal.read_text()


def test_cancel_at_post_observer_reaps_both_without_suffix(tmp_path,children,monkeypatch):
    args,journal,_=branch_call(tmp_path); original=args['project']; counts=measured_writes(monkeypatch)
    primary=KeyboardInterrupt()
    def project(raw,selected):
        value=original(raw,selected)
        if value['point']==['post',1]:raise primary
        return value
    args['project']=project
    with pytest.raises(KeyboardInterrupt) as caught:control.transport(**args)
    assert caught.value is primary and args['context'].owner.primary is primary
    assert counts=={'original':300,'mutation':len(args['mutation_policy'].sql)}
    assert all(c.returncode is not None for c in children)
    assert all(s.process is None for s in args['context'].owner.slots)


@pytest.mark.parametrize('bad',['kind','size','transaction','post','default'])
def test_mutation_optin_rejects_malformed_policy_before_child(tmp_path,children,bad):
    args,_,_=branch_call(tmp_path); policy=args['mutation_policy']
    if bad=='kind':args['mutation_policy']=control.MutationPolicy('unknown',policy.point,policy.sql)
    elif bad=='size':args['mutation_policy']=control.MutationPolicy('Is',policy.point,b'BEGIN;\n'+b'x'*2048+b'COMMIT;\n')
    elif bad=='transaction':args['mutation_policy']=control.MutationPolicy('Is',policy.point,b'SELECT 1;\n')
    elif bad=='default':args['mutation_policy']=None
    else:args['points']=[(p,o+1 if p[0]=='post' else o) for p,o in args['points']]
    with pytest.raises(control.ControlFailure):control.transport(**args)
    assert children==[]
