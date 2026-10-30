"""Owned real pipes verify the construction hooks without a database or Docker."""
import hashlib
import json
import os
import sys
import time

import pytest

from test_rf1086_s0_control import children
from test_rf1086_causal_transport import PEER as SINGLE_PEER, measured_writes
import rf1086_s0_control as control


# Reuse the independently asserting peer's exact-read/barrier protocol. Its
# mutation input is now selected by hook, and its public wire tag is distinct.
PEER = SINGLE_PEER.replace('C1', 'R1').replace(
    'mutation=bytes.fromhex(sys.argv[7]);', 'mutations=json.loads(sys.argv[7]);').replace(
    "if point[0]=='post':\n            if exact", "if point[0]=='post':\n            mutation=bytes.fromhex(mutations[point[1]])\n            if exact").replace(
    "write(json.dumps({'point':point}).encode()+b'\\n')",
    "write(json.dumps({'point':point,'padding':'z'*60000 if point[1]==2 else ''}).encode()+b'\\n')").replace(
    'n=os.write(1,data[:7]);', 'n=os.write(1,data[:4096]);')


def construction_call(tmp_path, mode='normal', *, reordered=False, no_op=False):
    script=b'x'*700; nonce='e'*32; journal=tmp_path/'journal'; context=control.new_context()
    order=(1,0) if reordered else (0,1)
    points=[(('anchor',0),0),(('anchor',1),100)]
    for i, offset in zip(order,(200,300)):
        points.extend(((('cut',i),offset),(('post',i),offset)))
    points.extend(((('anchor',2),400),(('cut',2),500),(('post',2),500)))
    mutations=[b'BEGIN;\nSELECT 1;\nCOMMIT;\n', b'BEGIN;\nSELECT 2;\nCOMMIT;\n',
               b'BEGIN;\n'+b'SELECT 3;\n'*600+b'COMMIT;\n']
    if no_op: mutations=[b'',b'',b'']
    confirmed=[]
    def argv(role): return [sys.executable,'-c',PEER,role,nonce,mode,str(journal)]
    writer=argv('writer')+[json.dumps(points),str(len(script)),json.dumps([s.hex() for s in mutations])]
    def request(point,seq,pid):
        return argv('observer'),json.dumps(dict(point=point,seq=seq,pid=pid)).encode()
    def confirm(exchange):
        assert all(s.process is None or s.process.args==writer for s in context.owner.slots)
        point=tuple(exchange['point']); confirmed.append(point)
        return mutations[point[1]] if point[0]=='cut' else None
    now=time.monotonic()
    args=dict(script=script,descriptor={'cuts':[[1],[1],[2]]},
        selections=[{'kind':k} for k in ('Is','In','acl')],context=context,nonce=nonce,
        writer_args=writer,observer_request=request,parse_session=lambda raw,**kw:json.loads(raw),
        parse_witness=lambda raw,**kw:json.loads(raw),project=lambda raw,selected:json.loads(raw),
        probe=lambda nonce,seq:tuple(f'{p}/{nonce}/{seq:02d}\n'.encode() for p in ('P','Q')),
        points=points,work_end=now+15,reap_end=now+17,exchange_complete=confirm)
    return args,journal,confirmed,mutations


@pytest.mark.parametrize('reordered',[False,True])
def test_three_mutations_follow_observed_offsets_and_full_original_survives(tmp_path,children,reordered):
    args,journal,confirmed,mutations=construction_call(tmp_path,reordered=reordered)
    result=control.restore_transport(**args)
    assert confirmed==[point for point,_ in args['points']]
    assert result['delivery']['original']==dict(bytes=700,sha256=hashlib.sha256(args['script']).hexdigest())
    ordered=b''.join(mutations[p[1]] for p,_ in args['points'] if p[0]=='cut')
    assert result['delivery']['mutation']['sha256']==hashlib.sha256(ordered).hexdigest()
    assert result['delivery']['mutation']['bytes']==len(ordered)
    assert journal.read_text().count('mutation\n')==3
    assert all(c.returncode==0 for c in children) and len(children)==10
    assert all(s.process is None for s in args['context'].owner.slots)


def test_noop_still_observes_all_postconditions_and_eof(tmp_path,children):
    args,journal,confirmed,_=construction_call(tmp_path,no_op=True)
    result=control.restore_transport(**args)
    assert result['delivery']['mutation']['bytes']==0
    assert len(confirmed)==9 and 'original:' in journal.read_text()
    assert all(c.returncode==0 for c in children)


@pytest.mark.parametrize('point',[('cut',0),('post',0),('cut',1),('post',1),('cut',2),('post',2)])
def test_any_rejected_observation_withholds_every_future_original_byte(tmp_path,children,monkeypatch,point):
    args,journal,_,_=construction_call(tmp_path); counts=measured_writes(monkeypatch)
    original=args['exchange_complete']
    def reject(exchange):
        value=original(exchange)
        if tuple(exchange['point'])==point: raise control.ControlFailure('postcondition',point)
        return value
    args['exchange_complete']=reject
    with pytest.raises(control.ControlFailure):control.restore_transport(**args)
    assert counts['original']==dict(args['points'])[point]
    assert 'original:' not in journal.read_text()
    assert all(c.returncode is not None for c in children)
    assert all(s.process is None for s in args['context'].owner.slots)


@pytest.mark.parametrize('mode',['stderr','nonzero','late'])
def test_failed_or_unexpected_post_frame_never_releases_original_suffix(tmp_path,children,monkeypatch,mode):
    args,journal,_,_=construction_call(tmp_path,mode); counts=measured_writes(monkeypatch)
    with pytest.raises(control.ControlFailure):control.restore_transport(**args)
    assert counts['original']==200
    assert 'original:' not in journal.read_text()
    assert all(c.returncode is not None for c in children)


def test_cancel_during_second_mutation_preserves_exception_and_reaps(tmp_path,children,monkeypatch):
    args,journal,_,_=construction_call(tmp_path); original=os.write; primary=KeyboardInterrupt()
    def write(fd,data):
        if bytes(data).startswith(b'BEGIN;\nSELECT 2;'):
            original(fd,data[:7]);raise primary
        return original(fd,data)
    monkeypatch.setattr(control.os,'write',write)
    with pytest.raises(KeyboardInterrupt) as caught:control.restore_transport(**args)
    assert caught.value is primary and args['context'].owner.primary is primary
    assert all(c.returncode is not None for c in children)
    assert 'original:' not in journal.read_text()


def test_incomplete_post_schedule_refuses_without_launch(tmp_path,children):
    args,_,_,_=construction_call(tmp_path);args['points'].pop()
    with pytest.raises(control.ControlFailure):control.restore_transport(**args)
    assert not children


def test_short_writes_and_backpressure_preserve_all_three_mutation_bytes(tmp_path,children,monkeypatch):
    args,journal,_,mutations=construction_call(tmp_path,'pressure');original=os.write;calls=[0]
    def write(fd,data):
        calls[0]+=1
        if calls[0]%11==0:raise BlockingIOError()
        return original(fd,data[:17])
    monkeypatch.setattr(control.os,'write',write)
    result=control.restore_transport(**args)
    assert result['delivery']['mutation']['sha256']==hashlib.sha256(b''.join(mutations)).hexdigest()
    assert result['delivery']['writer']['stdoutBytes']>3*262144
    assert 'original:' in journal.read_text() and all(c.returncode==0 for c in children)
