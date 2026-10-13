"""Synthetic S0 lifecycle and real owned-child failures; no database or Docker."""
from copy import deepcopy
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import rf1086_s0_control as control
import rf1086_s0_protocol as protocol
import rf1086_catalog_causal_capture as capture
from rf1086_actual_replay_package import Unavailable
from test_rf1086_s0_protocol import valid_receipt_context, synthetic_inventory
from test_rf1086_sql_ledger import source_rows, script_fixture


@pytest.fixture
def children(monkeypatch):
    """Harness cleanup never calls a test-injected kill/wait implementation."""
    original, kill, wait = subprocess.Popen, subprocess.Popen.kill, subprocess.Popen.wait
    tracked = []
    def start(*a, **kw):
        child = original(*a, **kw); tracked.append(child); return child
    monkeypatch.setattr(subprocess, 'Popen', start)
    yield tracked
    for child in tracked:
        try:
            wait(child, timeout=0)
        except subprocess.TimeoutExpired:
            kill(child); wait(child, timeout=2)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None: stream.close()
    assert all(child.returncode is not None for child in tracked)


def sleeping(owner):
    return owner.launch([sys.executable, '-c', 'import time; time.sleep(30)'])


def test_reused_slot_second_child_failure_is_killed_and_reaped(children):
    context = control.new_context()
    run = control.S0Runner(context, time.monotonic()+4)
    assert run([sys.executable, '-c', 'print("first")'], run.work_end) == b'first\n'
    assert all(slot.process is None for slot in context.owner.slots)
    # The first launch finished normally and left its slot's waited flag true.
    run.end = time.monotonic()+2.05
    with pytest.raises(Unavailable):
        run([sys.executable, '-c', 'import time; time.sleep(30)'], run.work_end)
    assert len(children) == 2 and children[1].returncode is not None
    assert not context.owner.uncertain and all(s.process is None for s in context.owner.slots)


def test_cancel_at_acquisition_registers_then_reaps_child(children, monkeypatch):
    context = control.new_context(); underlying = subprocess.Popen
    old = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}
    def acquire(*a, **kw):
        child = underlying(*a, **kw)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return child
    monkeypatch.setattr(subprocess, 'Popen', acquire)
    run = control.S0Runner(context, time.monotonic()+3)
    with pytest.raises(KeyboardInterrupt) as caught:
        run([sys.executable, '-c', 'import time; time.sleep(30)'], run.work_end)
    assert caught.value is context.owner.primary and context.owner.cancelled
    assert len(children) == 1 and children[0].returncode is not None
    assert all(signal.getsignal(s) is h for s, h in old.items())


@pytest.mark.parametrize('where', ['pipe_setup','handler_restore'])
def test_registered_child_is_reaped_if_setup_or_handler_restoration_fails(children,monkeypatch,where):
    context=control.new_context(); run=control.S0Runner(context,time.monotonic()+3)
    primary=KeyboardInterrupt() if where=='pipe_setup' else OSError('restore fault')
    if where=='pipe_setup':
        def fail(*a,**kw): raise primary
        monkeypatch.setattr(control.os,'set_blocking',fail)
    else:
        original=signal.signal; once=[False]; handler=signal.getsignal(signal.SIGTERM)
        def replace(number,value):
            result=original(number,value)
            if number==signal.SIGTERM and value is handler and children and not once[0]:
                once[0]=True; raise primary
            return result
        monkeypatch.setattr(signal,'signal',replace)
    with pytest.raises(type(primary)) as caught:
        run([sys.executable,'-c','import time; time.sleep(30)'],run.work_end)
    assert caught.value is primary and context.owner.primary is primary
    assert len(children)==1 and children[0].returncode is not None


def test_unknown_constructor_child_is_never_claimed_reaped(children,monkeypatch):
    context=control.new_context(); original=subprocess.Popen; primary=OSError('constructor outcome unknown')
    def fail(*a,**kw):
        original(*a,**kw)
        raise primary
    monkeypatch.setattr(subprocess,'Popen',fail)
    run=control.S0Runner(context,time.monotonic()+3)
    with pytest.raises(OSError) as caught:
        run([sys.executable,'-c','import time; time.sleep(30)'],run.work_end)
    assert caught.value is primary and context.owner.uncertain
    assert any(slot.acquiring for slot in context.owner.slots)
    assert len(children)==1  # independent fixture teardown, not a driver reap claim


def test_queued_cancel_before_constructor_launches_nothing(children, monkeypatch):
    owner = control.ChildOwner(); install = signal.signal
    def set_handler(number, handler):
        previous = install(number, handler)
        if number == signal.SIGTERM and callable(handler) and handler.__name__ == 'record':
            handler(number, None)
        return previous
    monkeypatch.setattr(signal, 'signal', set_handler)
    with pytest.raises(KeyboardInterrupt): sleeping(owner)
    assert children == [] and not owner.uncertain


def test_constructor_uncertainty_is_sticky_and_original_exception_survives(monkeypatch):
    context = control.new_context(); original = OSError('synthetic acquisition')
    def fail(*a, **kw): raise original
    monkeypatch.setattr(subprocess, 'Popen', fail)
    run = control.S0Runner(context, time.monotonic()+3)
    with pytest.raises(OSError) as caught: run(['synthetic'], run.work_end)
    assert caught.value is original and context.owner.uncertain
    with pytest.raises(OSError) as repeated: context.raise_if_fatal()
    assert repeated.value is original and context.owner.errors == {'acquisition'}


def test_unwind_attempts_both_children_after_kill_error_repeat_cancel(children, monkeypatch):
    owner = control.ChildOwner(); first, second = sleeping(owner), sleeping(owner)
    primary = KeyboardInterrupt(); original_kill = type(first).kill
    def kill(child):
        original_kill(child)
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        if child is first: raise PermissionError('synthetic after known kill')
    monkeypatch.setattr(type(first), 'kill', kill)
    with pytest.raises(KeyboardInterrupt) as caught:
        owner.unwind(time.monotonic()+2, primary=primary)
    assert caught.value is primary and owner.errors == {'kill'} and owner.uncertain
    assert first.returncode is not None and second.returncode is not None
    assert all(s.process is None for s in owner.slots)


def test_unwind_wait_error_does_not_skip_other_child_or_replace_primary(children, monkeypatch):
    owner = control.ChildOwner(); first, second = sleeping(owner), sleeping(owner)
    primary = ValueError('initiating'); original_wait = type(first).wait
    def wait(child, *a, **kw):
        result = original_wait(child, *a, **kw)
        if child is first: raise OSError('synthetic after actual reap')
        return result
    monkeypatch.setattr(type(first), 'wait', wait)
    with pytest.raises(ValueError) as caught: owner.unwind(time.monotonic()+2, primary=primary)
    assert caught.value is primary and owner.uncertain and owner.errors == {'wait'}
    assert all(c.returncode is not None for c in children)


def test_all_waits_share_one_absolute_end_no_fresh_one_second_wait(monkeypatch):
    owner = control.ChildOwner(); remaining = []
    clock = [10.0]
    monkeypatch.setattr(control.time, 'monotonic', lambda: clock[0])
    class Child:
        stdin = stdout = stderr = None
        def kill(self): pass
        def wait(self, *, timeout):
            remaining.append(timeout); clock[0] += min(.75,timeout)
    for slot in owner.slots: slot.process = Child()
    owner.unwind(11.0)
    assert remaining == [1.0, .25]


@pytest.mark.parametrize('error', [ValueError('finite'), control.commands.CommandFailure('deadline',0,0,1)])
def test_runner_translates_ordinary_errors_only_after_fatal_guard(monkeypatch, error):
    context = control.new_context(); run = control.S0Runner(context, time.monotonic()+5)
    def fail(*a, **kw): raise error
    monkeypatch.setattr(control.commands, '_command', fail)
    with pytest.raises(Unavailable) as caught: run([], run.work_end)
    assert caught.value.reason == 'command_unavailable' and not context.owner.uncertain
    context.owner._uncertain('wait', error)
    with pytest.raises(type(error)) as fatal: run([], run.work_end)
    assert fatal.value is error


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    receipt, fsql, f2_input, metadata = valid_receipt_context(tmp_path)
    descriptor = {'schema': 's0-session-descriptor-v1', 'ledgerSha256': control._hash(fsql['ledger']),
                  'database': 'postgres', **deepcopy(receipt['references'])}
    clock = [1000.0]; events = []
    monkeypatch.setattr(control.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(control.secrets, 'token_hex', lambda n: receipt['nonce'])
    def tool(self, args, deadline, **kwargs):
        events.append('tool'); return b'psql (PostgreSQL) 17.6\n'+b'7'*64+b'\n'
    monkeypatch.setattr(control.S0Runner, '__call__', tool)
    def transported(*a, **kw):
        events.append('transport')
        assert kw['work_end'] <= kw['reap_end']-2
        return deepcopy({k:receipt[k] for k in ('exchanges','delivery')})
    monkeypatch.setattr(control, 'transport', transported)
    def cleanup(*a, **kw): events.append('cleanup'); return True
    def start(*a, **kw): events.append('start'); return receipt['target']['id']
    def roles(*a, **kw): events.append('roles')
    def initialized(*a, **kw): events.append('initialized'); return metadata['phases']['target_initialized']['catalog']
    def drop(*a, **kw): events.append('drop')
    def final(*a, **kw): events.append('final'); return metadata['failed'], metadata['phases']['mismatch']['catalog']
    resources = SimpleNamespace(cleanup=cleanup, start=start, apply_roles=roles,
        initialized=initialized, drop_default=drop, final_state=final, summary_fits=lambda value:True)
    context = control.new_context()
    args = dict(context=context, script=script_fixture(source_rows()), descriptor=descriptor,
        f2={'input':f2_input, 'inventory':synthetic_inventory()}, fsql=fsql, metadata=metadata,
        previous_target=receipt['target']['previous'], optional_deadline=2000.0, resources=resources)
    return args, clock, events, receipt


def test_control_composes_verified_receipt_after_local_cleanup(lifecycle):
    args, _, events, expected = lifecycle
    original = deepcopy(args['fsql'])
    result = control.observe_s0(**args)
    assert result == expected and args['context'].result is result
    assert args['fsql'] == original
    assert events == ['cleanup','start','tool','roles','initialized','drop','transport','final','cleanup']


@pytest.mark.parametrize('kind', ['phase_cleanup', 'phase_composition', 'validate', 'sizing_raise', 'sizing_false'])
def test_late_ordinary_errors_preserve_complete_fsql_and_become_unavailable(lifecycle, monkeypatch, kind):
    args, clock, events, _ = lifecycle; resources = args['resources']; original = deepcopy(args['fsql'])
    if kind == 'phase_cleanup':
        def final(*a, **kw):
            clock[0] = 1118.0
            return args['metadata']['failed'], args['metadata']['phases']['mismatch']['catalog']
        resources.final_state = final
    elif kind == 'phase_composition':
        def cleanup(*a, **kw):
            events.append('cleanup')
            if len(events)>1: clock[0] = 1120.0
            return True
        resources.cleanup = cleanup
    elif kind == 'validate':
        def fail(*a, **kw): raise ValueError('synthetic validation')
        monkeypatch.setattr(protocol, 'validate_receipt', fail)
    else:
        count = [0]
        def fits(value):
            count[0]+=1
            if count[0] == 1: return True
            if kind == 'sizing_raise': raise ValueError('synthetic sizing')
            return False
        resources.summary_fits = fits
    result = control.observe_s0(**args)
    assert result['status'] == 'unavailable' and args['fsql'] == original
    assert result['reason'] == ('cleanup_unproved' if kind == 'phase_cleanup' else
                               'summary_oversized' if kind == 'sizing_false' else 'control_unavailable')
    assert all(s.process is None for s in args['context'].owner.slots)


@pytest.mark.parametrize(('source','reason'), [('full_control_mismatch','fingerprint_mismatch'),
                                              ('full_causal_control_mismatch','enriched_mismatch'),
                                              ('unknown_private_flag','command')])
def test_final_package_failure_maps_only_closed_reasons(lifecycle, source, reason):
    args, _, _, _ = lifecycle
    def fail(*a, **kw): raise Unavailable(source)
    args['resources'].final_state = fail
    result = control.observe_s0(**args)
    assert result == protocol.unavailable(reason, 'final')


def test_catalog_must_match_exact_frozen_bytes_before_any_target_change(lifecycle, monkeypatch):
    args, _, events, _ = lifecycle
    monkeypatch.setattr(capture, '_snapshot_statement', lambda:b'changed catalog\n')
    assert control.observe_s0(**args) == protocol.unavailable('descriptor_invalid','admission')
    assert events == []


def test_unknown_admission_callback_error_is_closed_before_any_target_change(lifecycle):
    args,_,events,_=lifecycle
    calls=[0]
    def fail(value):
        calls[0]+=1
        if calls[0]==1: raise Unavailable('private unknown cause')
        return True
    args['resources'].summary_fits=fail
    assert control.observe_s0(**args)==protocol.unavailable('descriptor_invalid','admission')
    assert events==[]


@pytest.mark.parametrize('where', ['setup', 'cleanup', 'composition'])
def test_fatal_identity_escapes_all_ordinary_shields(lifecycle, where):
    args, _, events, _ = lifecycle; context=args['context']; primary=RuntimeError('synthetic uncertainty')
    def fatal(*a, **kw):
        context.owner._uncertain('wait', primary)
        raise primary
    if where == 'setup': args['resources'].start = fatal
    elif where == 'cleanup':
        def cleanup(*a, **kw):
            events.append('cleanup')
            if len(events)>1: fatal()
            return True
        args['resources'].cleanup = cleanup
    else:
        calls=[0]
        def fits(value):
            calls[0]+=1
            if calls[0]>1: fatal()
            return True
        args['resources'].summary_fits = fits
    with pytest.raises(RuntimeError) as caught: control.observe_s0(**args)
    assert caught.value is primary and context.result['status'] == 'unavailable'


def test_known_local_cleanup_failure_cannot_be_upgraded_by_later_success(lifecycle):
    args, _, events, _ = lifecycle
    def cleanup(*a, **kw):
        events.append('cleanup'); return len(events) == 1
    args['resources'].cleanup = cleanup
    assert control.observe_s0(**args) == protocol.unavailable('cleanup_unproved','cleanup')


@pytest.mark.parametrize('deadline', [float('inf'), float('nan'), True, None, 1119.9])
def test_admission_refuses_invalid_or_insufficient_budget_before_resources(lifecycle, deadline):
    args, _, events, _ = lifecycle; args['optional_deadline']=deadline
    assert control.observe_s0(**args) == protocol.unavailable('headroom','admission')
    assert events == []
