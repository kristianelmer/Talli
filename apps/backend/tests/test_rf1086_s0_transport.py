"""Real-pipe fixture policies exercise the shared controller, never S0 acceptance."""
import hashlib
import json
import os
from pathlib import Path
import select
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import rf1086_s0_control as control
from test_rf1086_s0_control import children


# os.read exact lengths deliberately avoids BufferedReader prefetch across cuts.
PEER = r'''
import hashlib,json,os,select,sys,time
role,nonce,mode,journal=sys.argv[1:5]
def write(raw):
    while raw:
        n=os.write(1,raw[:3] if raw.startswith(b'S0') else raw[:4096]); raw=raw[n:]
def line(kind,seq,payload,suffix=''):
    prefix=f'{kind}/{nonce}/{seq:02d}/'+suffix
    write(prefix.encode()+json.dumps(payload,separators=(',',':')).encode().hex().encode()+b'\n')
def exact(n,slow=False):
    out=bytearray()
    while len(out)<n:
        raw=os.read(0,min(4096,n-len(out)))
        if not raw: raise RuntimeError('unexpected EOF')
        out.extend(raw)
        if slow: time.sleep(.0005)
    return bytes(out)
if role=='writer':
    points=json.loads(sys.argv[5]); size=int(sys.argv[6]); count=0; digest=hashlib.sha256()
    for seq,(point,offset) in enumerate(points):
        raw=exact(offset-count,mode=='pressure'); digest.update(raw); count=offset
        if exact(len(f'P/{nonce}/{seq:02d}\n'))!=f'P/{nonce}/{seq:02d}\n'.encode(): raise RuntimeError('P request')
        epoch=point[1] if point[0]=='anchor' else 1
        db='template1' if epoch==0 else 'postgres'; pid=1000+epoch
        if mode=='early': write(f'S0B/{nonce}/{seq:02d}/{pid}\n'.encode())
        else: line('S0P',seq,[db,pid])
        if mode=='duplicate': line('S0P',seq,[db,pid])
        if exact(len(f'Q/{nonce}/{seq:02d}\n'))!=f'Q/{nonce}/{seq:02d}\n'.encode(): raise RuntimeError('Q request')
        write(f'S0B/{nonce}/{seq:02d}/{pid}\n'.encode())
        # The observer stays alive long enough for this independent zero-input check.
        ready=select.select([0],[],[],.04)[0]
        if ready:
            extra=os.read(0,1)
            if extra: raise RuntimeError('future original input during pause')
        with open(journal,'a') as f: f.write(f'pause:{seq}:0\n')
        if mode in ('late','eof_stall') and seq==0:
            write(b'z'*262144+b'\n')
            with open(journal,'a') as f: f.write('drained\n')
            if mode=='late': line('S0P',seq,[db,pid])
    raw=exact(size-count,mode=='pressure'); digest.update(raw)
    if os.read(0,1): raise RuntimeError('unexpected trailing input')
    with open(journal,'a') as f: f.write('original:'+str(size)+':'+digest.hexdigest()+'\n')
    if mode=='trailing': write(b'S0P/')
    if mode=='nonzero': sys.exit(2)
else:
    req=json.loads(sys.stdin.buffer.read(4096)); point,seq,pid=req['point'],req['seq'],req['pid']
    epoch=point[1] if point[0]=='anchor' else 1
    db='template1' if epoch==0 else 'postgres'
    witness=[db,'100',pid,'100',db,'epoch'+str(epoch)]
    roles=['anchor'] if point[0]=='anchor' else ['before','catalog','after']
    for part in roles:
        if part=='catalog': write(b'{"fixture":true}\n')
        else: line('S0O',seq,witness,part+'/')
    if mode=='stderr': os.write(2,b'x')
    if mode in ('late','eof_stall') and seq==0:
        os.close(1); os.close(2)
        if mode=='late': time.sleep(30)
        else:
            end=time.monotonic()+2
            while time.monotonic()<end:
                if os.path.exists(journal) and 'drained\n' in open(journal).read(): break
                time.sleep(.001)
            else: sys.exit(3)
    else: time.sleep(.08)
'''


def fixture_call(tmp_path, mode='normal'):
    script=b'x'*(2*1024**2 if mode=='pressure' else 500)
    offsets=[0,len(script)//2,len(script)//2+10,len(script)-10,len(script)]
    points=[(('anchor',0),offsets[0]),(('anchor',1),offsets[1]),
            *[(('cut',i),offsets[i+2]) for i in range(3)]]
    nonce='c'*32; journal=tmp_path/'fixture-journal'; context=control.new_context()
    def argv(role): return [sys.executable,'-c',PEER,role,nonce,mode,str(journal)]
    writer=argv('writer')+[json.dumps(points),str(len(script))]
    def request(point,seq,pid):
        return argv('observer'), json.dumps({'point':point,'seq':seq,'pid':pid}).encode()
    def session(raw,*,point,descriptor,baseline=None):
        value=json.loads(raw); epoch=point[1] if point[0]=='anchor' else 1
        expected=['template1' if epoch==0 else 'postgres',1000+epoch]
        if value != expected: raise ValueError('fixture session')
        if point[0]=='cut' and baseline != expected: raise ValueError('fixture epoch')
        return value
    def witness(raw,*,nonce,sequence,session,epoch_witness=None):
        value=json.loads(raw)
        if value[2]!=session[1]: raise ValueError('fixture PID')
        if epoch_witness is not None and value!=epoch_witness: raise ValueError('fixture epoch')
        return value
    def probe(nonce,seq): return tuple(f'{p}/{nonce}/{seq:02d}\n'.encode() for p in ('P','Q'))
    args=dict(script=script,descriptor={'cuts':[[1],[1],[1]]},ledger={'selected':[{}, {}, {}]},
        context=context,nonce=nonce,writer_args=writer,observer_request=request,parse_session=session,
        parse_witness=witness,project=lambda raw,selected:json.loads(raw),probe=probe,points=points,
        work_end=time.monotonic()+15,reap_end=time.monotonic()+17)
    return args,journal


def test_real_pipes_hold_all_future_bytes_and_keep_one_writer_across_epochs(tmp_path, children):
    args,journal=fixture_call(tmp_path)
    result=control.transport(**args)
    assert 'schema' not in result and 'status' not in result  # internal mechanics only
    assert len(children)==6 and all(c.returncode==0 for c in children)
    assert result['delivery']['original']==dict(bytes=len(args['script']),sha256=hashlib.sha256(args['script']).hexdigest())
    probes=b''.join(p for i in range(5) for p in args['probe'](args['nonce'],i))
    assert result['delivery']['probes']==dict(bytes=len(probes),sha256=hashlib.sha256(probes).hexdigest())
    assert result['delivery']['frames']==[5,5]
    assert [x['input'] for x in result['exchanges']]==[[p[1]]*2 for p in args['points']]
    assert journal.read_text().count(':0\n')==5
    assert f"original:{len(args['script'])}:{hashlib.sha256(args['script']).hexdigest()}\n" in journal.read_text()
    assert all(slot.process is None for slot in args['context'].owner.slots)


def test_actual_partial_nonblocking_writes_preserve_exact_delivery(tmp_path, children, monkeypatch):
    args,journal=fixture_call(tmp_path,'pressure'); original=os.write; writes=[]
    def measured(fd,data):
        n=original(fd,data); writes.append((len(data),n)); return n
    monkeypatch.setattr(control.os,'write',measured)
    result=control.transport(**args)
    assert any(0<n<size for size,n in writes)  # actual OS return, no injected short write
    assert result['delivery']['original']['sha256']==hashlib.sha256(args['script']).hexdigest()
    assert journal.read_text().count(':0\n')==5


def test_prefilled_real_pipe_eagain_and_handshake_drain_force_short_write(children):
    owner=control.ChildOwner(); read_fd,write_fd=os.pipe(); filled=0
    try:
        os.set_blocking(write_fd,False)
        while filled<=2*1024**2:
            try: filled+=os.write(write_fd,b'x'*65536)
            except BlockingIOError: break
        else: pytest.fail('fixture did not reach bounded pipe capacity')
        assert filled>=4096
        child=owner.launch([sys.executable,'-c',
            'import os,time; b=os.read(0,4096); os.write(1,str(len(b)).encode()+b"\\n"); time.sleep(30)'],stdin=read_fd)
        assert select.select([child.stdout],[],[],1)[0]
        assert os.read(child.stdout.fileno(),32)==b'4096\n'
        written=os.write(write_fd,b'y'*65536)
        assert 0<written<65536
    finally:
        os.close(read_fd); os.close(write_fd)
        owner.unwind(time.monotonic()+2,primary=sys.exception())
    assert children[0].returncode is not None and not owner.uncertain


def test_observer_pipe_eof_does_not_block_writer_backpressure_drain(tmp_path, children):
    args,journal=fixture_call(tmp_path,'eof_stall')
    result=control.transport(**args)
    assert 'drained\n' in journal.read_text()
    assert result['delivery']['writer']['stdoutBytes']>262144
    assert all(child.returncode==0 for child in children)


@pytest.mark.parametrize(('mode','reason','point'), [('early','frame',('anchor',0)),
    ('duplicate','frame',('anchor',0)),('late','frame',('anchor',0)),
    ('stderr','observer',('anchor',0)),('trailing','frame',None),('nonzero','command',None)])
def test_rejected_frames_late_errors_and_nonzero_reap_never_return_evidence(tmp_path,children,monkeypatch,mode,reason,point):
    args,journal=fixture_call(tmp_path,mode)
    original=os.write; original_writes=[]
    def write(fd,data):
        n=original(fd,data)
        if data[0]==ord('x'): original_writes.append(n)
        return n
    monkeypatch.setattr(control.os,'write',write)
    with pytest.raises(control.ControlFailure) as caught: control.transport(**args)
    assert (caught.value.reason,caught.value.point)==(reason,point)
    assert all(c.returncode is not None for c in children)
    assert all(s.process is None for s in args['context'].owner.slots)
    if point is not None:
        assert original_writes==[]  # first anchor at byte zero: no original suffix entered pipe
        assert 'original:' not in (journal.read_text() if journal.exists() else '')
    if mode=='late': assert 'drained\n' in journal.read_text()


def test_cancel_after_observer_acquisition_reaps_both_and_preserves_identity(tmp_path,children,monkeypatch):
    args,_=fixture_call(tmp_path); original=os.read; primary=KeyboardInterrupt(); writes=[]; real_write=os.write
    def read(fd,size):
        raw=original(fd,size)
        if raw.startswith(b'S0O'): raise primary
        return raw
    monkeypatch.setattr(control.os,'read',read)
    def write(fd,data):
        n=real_write(fd,data)
        if data[0]==ord('x'): writes.append(n)
        return n
    monkeypatch.setattr(control.os,'write',write)
    with pytest.raises(KeyboardInterrupt) as caught: control.transport(**args)
    assert caught.value is primary and args['context'].owner.primary is primary
    assert len(children)==2 and all(c.returncode is not None for c in children)
    assert writes==[]


def test_expired_transport_never_acquires_child(tmp_path,children):
    args,_=fixture_call(tmp_path); args['work_end']=time.monotonic()-1
    with pytest.raises(control.ControlFailure) as caught: control.transport(**args)
    assert caught.value.reason=='deadline' and children==[]


def test_lifetime_frame_scanner_bounds_partial_lines_before_accumulation():
    accepted=[]; parser=control._Lines((b'S0P/',b'S0B/'),4096,accepted.append,ordinary=True)
    for _ in range(20): parser.feed(b'x'*65536)
    assert len(parser.pending)==0
    parser.feed(b'\nS0'); parser.feed(b'P/'+b'x'*4092)
    assert len(parser.pending)==4096
    with pytest.raises(control.ControlFailure): parser.feed(b'\n')
    assert len(parser.pending)==4096 and accepted==[]


def test_split_reserved_frames_and_observer_role_specific_buffer_limits():
    output=[]; cap=[4]; parser=control._Lines((),lambda:cap[0],lambda raw:output.append(raw))
    parser.feed(b'ab'); parser.feed(b'c\n')
    assert output==[b'abc\n']
    parser.feed(b'abcd')
    with pytest.raises(control.ControlFailure): parser.feed(b'x')
    assert len(parser.pending)==4
    partial=control._Lines((b'S0P/',b'S0B/'),4096,output.append,ordinary=True)
    partial.feed(b'S0')
    with pytest.raises(control.ControlFailure): partial.eof()
