"""Borrowed deadlines; transport tests use only owned loopback TCP fixtures."""
import asyncio
import ast
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import selectors
import signal
import sys
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
import rf1086_restore_control as control
import rf1086_identity_restore as identity
import rf1086_storage_restore as storage
from psycopg.conninfo import conninfo_to_dict


def budget(seconds=8):
    value = control.RecoveryBudget(time.monotonic())
    value.end = time.monotonic() + seconds
    return value


@pytest.fixture
def relays(monkeypatch):
    values = []
    original = control._InternalRelay.__init__
    def init(self, *args):
        original(self, *args)
        values.append(self)
    monkeypatch.setattr(control._InternalRelay, '__init__', init)
    return values


def relay_owner(value, endpoints):
    calls = []
    def inspect():
        calls.append(True)
        return endpoints
    return SimpleNamespace(budget=value, internal_endpoints=inspect), calls


@contextmanager
def relay_upstream():
    """One finite test peer; reads through EOF before returning reversed bytes."""
    import socket
    import threading
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(.05)
    stop = threading.Event()
    failures = []
    def serve():
        try:
            while not stop.is_set():
                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    continue
                with connection:
                    connection.settimeout(2)
                    received = bytearray()
                    while data := connection.recv(65536):
                        received.extend(data)
                    connection.sendall(received[::-1])
                return
        except BaseException as error:
            if not stop.is_set(): failures.append(error)
    thread = threading.Thread(target=serve, daemon=True, name='relay-test-peer')
    thread.start()
    try:
        yield listener.getsockname()
    finally:
        stop.set(); listener.close(); thread.join(timeout=3)
        assert not thread.is_alive() and not failures


def test_internal_relay_duplex_half_close_and_queue_bound(relays, monkeypatch):
    import socket
    maximum = [0]
    original = control._InternalRelay.refresh
    def refresh(self, sock):
        maximum[0] = max(maximum[0], *(len(s['out']) for s in self.peers.values()))
        return original(self, sock)
    monkeypatch.setattr(control._InternalRelay, 'refresh', refresh)
    with relay_upstream() as db, relay_upstream() as auth:
        value = budget(6); value.phase = 'actors'; end = value.end
        owner, inspections = relay_owner(value, (db, auth))
        with control.internal_loopback_ports(owner, budget=value) as ports:
            assert len(set(ports)) == 2
            for index, port in enumerate(ports):
                payload = bytes(range(256)) * (4096 if index == 0 else 32)
                with socket.create_connection(('127.0.0.1', port), timeout=2) as client:
                    client.sendall(payload); client.shutdown(socket.SHUT_WR)
                    received = bytearray()
                    while data := client.recv(65536): received.extend(data)
                    assert received == payload[::-1]
            assert all(s.getsockname()[0] == '127.0.0.1' for s in relays[0].listeners)
        assert len(inspections) == 2 and value.end == end and value.phase == 'actors'
        assert 0 < maximum[0] <= 65536
        assert not relays[0].thread.is_alive() and not relays[0].sockets
        assert not value.context.owner.uncertain


def test_internal_relay_partial_bind_failure_closes_only_owned_listeners(relays):
    import socket
    with socket.socket() as existing:
        existing.bind(('127.0.0.1', 0)); existing.listen(1)
        value = budget(); value.phase = 'actors'
        owner, _ = relay_owner(value, (('127.0.0.1', 1), ('127.0.0.1', 2)))
        with pytest.raises(OSError):
            with control.internal_loopback_ports(owner, (0, existing.getsockname()[1]), budget=value):
                pytest.fail('occupied port admitted')
        assert existing.fileno() >= 0
        assert not relays[0].sockets and relays[0].thread is None


@pytest.mark.parametrize('started', [False, True])
def test_internal_relay_thread_start_cancellation_is_owned_and_preserved(relays, monkeypatch, started):
    original = control._io_threading.Thread.start
    primary = KeyboardInterrupt('generated cancellation')
    def start(self):
        if started: original(self)
        raise primary
    monkeypatch.setattr(control._io_threading.Thread, 'start', start)
    value = budget(); value.phase = 'actors'
    owner, _ = relay_owner(value, (('127.0.0.1', 1), ('127.0.0.1', 2)))
    with pytest.raises(KeyboardInterrupt) as caught:
        with control.internal_loopback_ports(owner, budget=value):
            pytest.fail('cancelled start yielded')
    assert caught.value is primary
    assert not relays[0].sockets and not relays[0].thread.is_alive()


def test_internal_relay_deadline_closes_idle_connections_without_new_phase(relays):
    import socket
    value = budget(.45); value.phase = 'actors'; end = value.end
    owner, _ = relay_owner(value, (('127.0.0.1', 1), ('127.0.0.1', 2)))
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.internal_loopback_ports(owner, budget=value) as ports:
            with socket.create_connection(('127.0.0.1', ports[0]), timeout=1):
                time.sleep(1)
    assert caught.value.reason == 'deadline'
    assert value.end == end and value.phase == 'actors'
    assert not relays[0].thread.is_alive() and not relays[0].sockets


def test_internal_relay_background_failure_cannot_mint_success(relays, monkeypatch):
    import socket
    primary = RuntimeError('generated reactor failure')
    def fail(*args): raise primary
    monkeypatch.setattr(control._InternalRelay, 'accept', fail)
    value = budget(); value.phase = 'actors'
    owner, _ = relay_owner(value, (('127.0.0.1', 1), ('127.0.0.1', 2)))
    with pytest.raises(RuntimeError) as caught:
        with control.internal_loopback_ports(owner, budget=value) as ports:
            with socket.create_connection(('127.0.0.1', ports[0]), timeout=1):
                relays[0].thread.join(timeout=1)
    assert caught.value is primary
    assert not relays[0].thread.is_alive() and not relays[0].sockets


def test_internal_relay_unexpected_failure_racing_stop_is_retained(relays, monkeypatch):
    import socket
    primary = control.RestoreUnavailable('limit')
    def fail(self, *args):
        self.stop.set()
        raise primary
    monkeypatch.setattr(control._InternalRelay, 'accept', fail)
    value = budget(); value.phase = 'actors'
    owner, _ = relay_owner(value, (('127.0.0.1', 1), ('127.0.0.1', 2)))
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.internal_loopback_ports(owner, budget=value) as ports:
            with socket.create_connection(('127.0.0.1', ports[0]), timeout=1):
                relays[0].thread.join(timeout=1)
    assert caught.value is primary and relays[0].failure is primary
    assert not relays[0].thread.is_alive() and not relays[0].sockets


def test_internal_relay_setup_expiry_closes_sockets_before_thread_exists(relays, monkeypatch):
    original = control._InternalRelay.setup
    value = budget(); value.phase = 'actors'
    owner, _ = relay_owner(value, (('127.0.0.1', 1), ('127.0.0.1', 2)))
    def setup(self, *args):
        result = original(self, *args)
        value.end = time.monotonic() - .01
        return result
    monkeypatch.setattr(control._InternalRelay, 'setup', setup)
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.internal_loopback_ports(owner, budget=value): pytest.fail('expired')
    assert caught.value.reason == 'deadline'
    assert not relays[0].sockets and relays[0].thread is None
    assert relays[0].selector.get_map() is None and value.context.owner.uncertain


@pytest.mark.parametrize('primary_failure', [False, True])
def test_internal_relay_unjoined_worker_is_sticky_and_keeps_primary(relays, monkeypatch, primary_failure):
    threads = []
    class Thread:
        ident = None
        def __init__(self, **kwargs): threads.append(self); self.joined = False
        def start(self): self.ident = 123
        def join(self, timeout): self.joined = True; assert 0 <= timeout <= 8
        def is_alive(self): return True
    monkeypatch.setattr(control._io_threading, 'Thread', Thread)
    value = budget(); value.phase = 'actors'
    owner, _ = relay_owner(value, (('127.0.0.1', 1), ('127.0.0.1', 2)))
    primary = KeyboardInterrupt('generated caller cancellation')
    error_type = KeyboardInterrupt if primary_failure else control.RestoreUnavailable
    with pytest.raises(error_type) as caught:
        with control.internal_loopback_ports(owner, budget=value):
            if primary_failure: raise primary
    if primary_failure: assert caught.value is primary
    assert threads[0].joined and value.context.owner.uncertain
    assert not relays[0].sockets and relays[0].selector.get_map() is None


def test_internal_relay_endpoint_drift_rejects_after_cleanup(relays):
    value = budget(); value.phase = 'actors'
    calls = []
    def inspect():
        calls.append(True)
        return (('127.0.0.1', len(calls)), ('127.0.0.1', 2))
    owner = SimpleNamespace(budget=value, internal_endpoints=inspect)
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.internal_loopback_ports(owner, budget=value): pass
    assert caught.value.reason == 'source_binding' and len(calls) == 2
    assert not relays[0].sockets and not relays[0].thread.is_alive()


@pytest.mark.parametrize('cap', ['pairs', 'accepts'])
def test_internal_relay_caps_include_pending_connections(relays, monkeypatch, cap):
    import socket
    limits = dict(control.CONFIG['actorTransport']); limits[cap] = 1
    monkeypatch.setitem(control.CONFIG, 'actorTransport', limits)
    with socket.socket() as upstream:
        upstream.bind(('127.0.0.1', 0)); upstream.listen(4)
        value = budget(); value.phase = 'actors'
        owner, _ = relay_owner(value, (upstream.getsockname(), upstream.getsockname()))
        with pytest.raises(control.RestoreUnavailable) as caught:
            with control.internal_loopback_ports(owner, budget=value) as ports:
                with socket.create_connection(('127.0.0.1', ports[0]), timeout=1) as first:
                    first.sendall(b'kept open')
                    with socket.create_connection(('127.0.0.1', ports[1]), timeout=1):
                        relays[0].thread.join(timeout=1)
        assert caught.value.reason == 'limit'
    assert not relays[0].sockets and not relays[0].thread.is_alive()


def test_internal_relay_close_fault_is_sticky_even_if_retry_closes(relays, monkeypatch):
    original = control._InternalRelay.close
    def close(self, sock):
        self.close_failed = True  # Model a reported close fault followed by closure.
        original(self, sock)
    monkeypatch.setattr(control._InternalRelay, 'close', close)
    value = budget(); value.phase = 'actors'
    owner, _ = relay_owner(value, (('127.0.0.1', 1), ('127.0.0.1', 2)))
    with pytest.raises(control.RestoreUnavailable):
        with control.internal_loopback_ports(owner, budget=value): pass
    assert value.context.owner.uncertain
    assert not relays[0].sockets and not relays[0].thread.is_alive()


def test_internal_relay_partial_socket_acquisition_preserves_cancellation(relays, monkeypatch):
    original = control._InternalRelay.track
    primary = KeyboardInterrupt('generated acquisition cancellation')
    def track(self, sock):
        result = original(self, sock)
        if len(self.sockets) == 2: raise primary
        return result
    monkeypatch.setattr(control._InternalRelay, 'track', track)
    value = budget(); value.phase = 'actors'
    owner, _ = relay_owner(value, (('127.0.0.1', 1), ('127.0.0.1', 2)))
    with pytest.raises(KeyboardInterrupt) as caught:
        with control.internal_loopback_ports(owner, budget=value): pytest.fail('cancelled')
    assert caught.value is primary
    assert not relays[0].sockets and relays[0].thread is None


def test_internal_relay_allows_bounded_health_retry_after_connection_refused(relays, monkeypatch):
    import errno
    import socket
    with socket.socket() as upstream:
        upstream.bind(('127.0.0.1', 0)); upstream.listen(1); upstream.settimeout(1)
        refusals = []
        original = socket.socket
        class RefuseOnce(original):
            def connect_ex(self, address):
                if address == upstream.getsockname() and not refusals:
                    refusals.append(True)
                    return errno.ECONNREFUSED
                return super().connect_ex(address)
        monkeypatch.setattr(socket, 'socket', RefuseOnce)
        value = budget(); value.phase = 'actors'
        owner, _ = relay_owner(value, (upstream.getsockname(), upstream.getsockname()))
        with control.internal_loopback_ports(owner, budget=value) as ports:
            # Inject only the first connect result; the retry uses real TCP bytes.
            with socket.create_connection(('127.0.0.1', ports[0]), timeout=1) as client:
                assert client.recv(1) == b''
            with socket.create_connection(('127.0.0.1', ports[0]), timeout=1) as client:
                client.sendall(b'ready')
                server, _ = upstream.accept()
                with server:
                    server.settimeout(1)
                    assert server.recv(5) == b'ready'
                    server.sendall(b'ok')
                assert client.recv(2) == b'ok'
        assert relays[0].failure is None and refusals == [True]
    assert not relays[0].sockets and not relays[0].thread.is_alive()


@pytest.mark.parametrize('stage', ['connect', 'so-error', 'recv', 'send'])
@pytest.mark.parametrize('code', ['EIO', 'EBADF', 'ECONNRESET'])
def test_internal_relay_distinguishes_expected_disconnect_from_io_failure(stage, code, monkeypatch):
    import errno
    primary = OSError(getattr(errno, code), 'generated peer fault')
    relay = control._InternalRelay((('172.28.0.2', 5432), ('172.28.0.3', 9999)), time.monotonic()+2)
    class Socket:
        def setblocking(self, value): pass
        def close(self): pass
        def connect_ex(self, address): return primary.errno
        def getsockopt(self, *args): return primary.errno
        def recv(self, size): raise primary
        def send(self, data): raise primary
        def shutdown(self, how): pass
    left, right = Socket(), Socket()
    relay.track(left); relay.track(right)
    calls = []
    def select(timeout):
        if calls:
            relay.stop.set(); return []
        calls.append(True)
        return [(SimpleNamespace(fileobj=left), selectors.EVENT_WRITE if stage=='send' else selectors.EVENT_READ)]
    relay.selector = SimpleNamespace(unregister=lambda *a:None, register=lambda *a:None, select=select)
    try:
        if stage == 'connect':
            listener = SimpleNamespace(accept=lambda:(left, ('127.0.0.1', 1)))
            # A hashable generated listener avoids any actual network operation.
            class Listener:
                def accept(self): return left, ('127.0.0.1', 1)
            listener = Listener(); relay.listeners[listener] = relay.endpoints[0]
            monkeypatch.setattr(relay, 'new_socket', lambda:right)
            action = lambda:relay.accept(listener)
        else:
            relay.peers = {
                left: {'peer':right,'out':bytearray(b'x' if stage=='send' else b''),
                       'read':True,'write':True,'connecting':stage=='so-error'},
                right: {'peer':left,'out':bytearray(),'read':True,'write':True,'connecting':False}}
            action = lambda:relay.exchange(left, selectors.EVENT_WRITE)
        if stage in ('connect', 'so-error'):
            if code == 'ECONNRESET': action()
            else:
                with pytest.raises(OSError) as caught: action()
                assert caught.value.errno == primary.errno
        else:
            relay.run()
            assert relay.failure is (None if code=='ECONNRESET' else primary)
    finally:
        relay.close_all()
    assert not relay.sockets


@pytest.mark.parametrize('stage', ['setup', 'start-before', 'start-after'])
def test_internal_relay_live_deadline_interrupts_delayed_acquisition(relays, monkeypatch, stage):
    value = budget(.5); value.phase = 'actors'; end = value.end
    owner, _ = relay_owner(value, (('127.0.0.1', 1), ('127.0.0.1', 2)))
    if stage == 'setup':
        original = control._InternalRelay.setup
        def setup(self, *args):
            result = original(self, *args); time.sleep(1); return result
        monkeypatch.setattr(control._InternalRelay, 'setup', setup)
    else:
        original = control._io_threading.Thread.start
        def start(self):
            if stage == 'start-after': original(self)
            time.sleep(1)
            if stage == 'start-before': original(self)
        monkeypatch.setattr(control._io_threading.Thread, 'start', start)
    began = time.monotonic()
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.internal_loopback_ports(owner, budget=value): pytest.fail('delayed startup yielded')
    assert caught.value.reason == 'deadline' and time.monotonic()-began < .8
    assert value.end == end and value.phase == 'actors'
    assert not relays[0].sockets
    assert relays[0].thread is None or not relays[0].thread.is_alive()
    if stage == 'start-before':
        assert value.context.owner.uncertain and value.context.owner.primary is caught.value


@pytest.mark.parametrize('earlier', [False, True])
@pytest.mark.parametrize('close_error', [KeyboardInterrupt('generated close interrupt'),
    SystemExit(17), control.RestoreUnavailable('deadline')])
def test_internal_relay_retains_first_close_exception_and_prior_primary(relays, monkeypatch, earlier, close_error):
    import socket
    import threading
    original = socket.socket
    fired = []; lock = threading.Lock()
    class CloseFault(original):
        def close(self):
            with lock:
                first = not fired
                if first: fired.append(True)
            super().close()
            if first: raise close_error
    monkeypatch.setattr(socket, 'socket', CloseFault)
    value = budget(); value.phase = 'actors'
    owner, _ = relay_owner(value, (('127.0.0.1', 1), ('127.0.0.1', 2)))
    body_error = ValueError('generated earlier caller failure')
    expected = body_error if earlier else close_error
    with pytest.raises(type(expected)) as caught:
        with control.internal_loopback_ports(owner, budget=value):
            if earlier: raise body_error
    assert caught.value is expected and value.context.owner.primary is expected
    assert value.context.owner.uncertain and relays[0].close_error is close_error
    assert not relays[0].sockets and not relays[0].thread.is_alive()


@pytest.mark.parametrize('inspection', ['before', 'after'])
def test_internal_relay_inspection_record_waits_share_live_actor_deadline(relays, inspection):
    value = budget(.5); value.phase = 'actors'; end = value.end
    calls = []
    def inspect():
        calls.append(True)
        if len(calls) == (1 if inspection == 'before' else 2):
            time.sleep(1)  # Stand in for a blocked ownership-record fsync.
        return (('127.0.0.1', 1), ('127.0.0.1', 2))
    owner = SimpleNamespace(budget=value, internal_endpoints=inspect)
    started = time.monotonic()
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.internal_loopback_ports(owner, budget=value): pass
    assert caught.value.reason == 'deadline' and time.monotonic()-started < .8
    assert value.end == end and value.phase == 'actors'
    if inspection == 'before':
        assert len(calls) == 1 and relays == []
    else:
        assert len(calls) == 2 and not relays[0].sockets and not relays[0].thread.is_alive()


@pytest.mark.parametrize('script', ['rehearse-rf1086-owned-restore.py', 'rehearse-rf1086-company-test-retention-restore.py'])
def test_entry_clock_precedes_all_heavy_imports_and_is_reused(script):
    source = (ROOT/'scripts'/script).read_text()
    tree = ast.parse(source)
    start = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_RECOVERY_STARTED' for t in n.targets))
    heavy = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) and ('psycopg' in ast.unparse(n) or 'rf1086_' in ast.unparse(n))]
    assert heavy and all(start.lineno < n.lineno for n in heavy)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'RecoveryBudget']
    assert len(calls) == 1 and ast.unparse(calls[0].args[0]) == '_RECOVERY_STARTED'
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    assert 'budget_scope(budget)' in ast.unparse(main)


def test_scope_inherits_same_object_without_extending_or_advancing():
    value = budget(); end = value.end
    with control.budget_scope(value):
        assert control.current_budget() is value
        before = time.monotonic()
        assert control.io_timeout(maximum=50) <= end-before
        with control.budget_scope(None): assert control.current_budget() is None
        assert control.current_budget() is value
    assert control.current_budget() is None and value.end == end and value.phase == 'construction'


def test_sync_deadline_interrupts_wait_and_restores_alarm():
    value = budget(.03)
    original = signal.getsignal(signal.SIGALRM)
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.io_deadline(value): time.sleep(.3)
    assert caught.value.reason == 'deadline'
    assert signal.getsignal(signal.SIGALRM) is original
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_nested_earlier_alarm_not_reset_and_primary_cancellation_preserved():
    value = budget(.5); original = KeyboardInterrupt('synthetic')
    with pytest.raises(KeyboardInterrupt) as caught:
        with control.io_deadline(value):
            before = signal.getitimer(signal.ITIMER_REAL)[0]
            with control.io_deadline(value):
                assert signal.getitimer(signal.ITIMER_REAL)[0] <= before
                raise original
    assert caught.value is original and signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_explicit_io_end_checked_after_yield_without_resetting_parent(monkeypatch):
    value=budget(8);parent_end=value.end;now=time.monotonic();clock=[now]
    monkeypatch.setattr(control.time,'monotonic',lambda:clock[0])
    previous=signal.getsignal(signal.SIGALRM)
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.io_deadline(value,end=now+1):
            clock[0]=now+1.1
    assert caught.value.reason=='deadline' and value.end==parent_end
    assert value.phase=='construction' and signal.getsignal(signal.SIGALRM) is previous
    assert signal.getitimer(signal.ITIMER_REAL)[0]==0


def test_explicit_io_end_preserves_earlier_alarm_and_handler():
    value=budget(.5);primary=KeyboardInterrupt('earlier alarm')
    previous=signal.getsignal(signal.SIGALRM);prior=signal.getitimer(signal.ITIMER_REAL)
    delivered=[]
    def earlier(*args):
        delivered.append(True)
        # The existing restoration policy re-arms an elapsed external alarm;
        # record that delivery without injecting a second cancellation token.
        if len(delivered)==1:raise primary
    try:
        signal.signal(signal.SIGALRM,earlier)
        signal.setitimer(signal.ITIMER_REAL,.025)
        with pytest.raises(KeyboardInterrupt) as caught:
            with control.io_deadline(value,end=time.monotonic()+1):time.sleep(.2)
        assert delivered and caught.value is primary and signal.getsignal(signal.SIGALRM) is earlier
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,previous)
        signal.setitimer(signal.ITIMER_REAL,*prior)


def test_explicit_io_end_cannot_extend_parent_and_expired_entry_does_not_yield():
    value=budget(.5);upper=value.remaining()
    with control.io_deadline(value,end=time.monotonic()+10):
        assert 0<signal.getitimer(signal.ITIMER_REAL)[0]<=upper
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.io_deadline(value,end=time.monotonic()-1):raise AssertionError('expired entry yielded')
    assert caught.value.reason=='deadline' and signal.getitimer(signal.ITIMER_REAL)[0]==0


@pytest.mark.parametrize('delayed_selector', [False, True])
def test_async_whole_call_deadline_and_external_cancellation_identity(monkeypatch, delayed_selector):
    previous = signal.getsignal(signal.SIGALRM)
    original_select = selectors.DefaultSelector.select
    def delayed_select(selector, timeout=None):
        if timeout is not None and timeout > 0:
            # Model scheduler lateness without extending the real deadline.
            time.sleep(timeout + .005)
            return original_select(selector, 0)
        return original_select(selector, timeout)
    async def expires():
        async with control.async_scope(budget(.02)): await asyncio.sleep(.2)
    with monkeypatch.context() as local:
        if delayed_selector:
            local.setattr(selectors.DefaultSelector, 'select', delayed_select)
        # SIGALRM can interrupt the loop's wait outside the coroutine itself.
        with pytest.raises(control.RestoreUnavailable) as caught:
            asyncio.run(expires())
    assert caught.value.reason == 'deadline'
    assert signal.getsignal(signal.SIGALRM) is previous
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
    original = asyncio.CancelledError('synthetic')
    async def cancelled():
        with pytest.raises(asyncio.CancelledError) as caught:
            async with control.async_scope(budget()): raise original
        assert caught.value is original
    asyncio.run(cancelled())
    assert signal.getsignal(signal.SIGALRM) is previous
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_command_owner_never_receives_adapter_alarm_and_error_identity_survives():
    value = budget(.5); original = KeyboardInterrupt('synthetic')
    def command(*_args, **_kwargs):
        assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
        raise original
    value.command = command
    with pytest.raises(KeyboardInterrupt) as caught:
        with control.io_deadline(value): control.io_command(value, ['synthetic'])
    assert caught.value is original and signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_real_owned_pipe_timeout_uses_command_reap_and_not_outer_alarm():
    value = budget(2.08)
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.io_deadline(value):
            control.io_command(value, [sys.executable, '-B', '-c', 'import time; time.sleep(10)'], cap=64)
    assert caught.value.reason == 'deadline'
    assert not value.context.owner.uncertain
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


class Connection:
    def __init__(self, values=None): self.calls = []; self.values = values or [3]; self.closed = False
    def __enter__(self): return self
    def __exit__(self, *_): self.closed = True
    def close(self): self.closed = True
    def execute(self, *args, **kwargs): self.calls.append((args, kwargs)); return self
    def fetchone(self): return self.values


def test_db_connect_timeout_and_each_statement_reclip_remaining(monkeypatch):
    value = budget(); conn = Connection(); seen = []
    def connect(dsn, **kw): seen.append((conninfo_to_dict(dsn), kw)); return conn
    with control.bounded_connection(connect, 'dbname=postgres user=postgres options=-csearch_path=public', budget=value) as db:
        db.execute('select 1')
        first = int(conn.calls[0][0][1][0])
        value.end -= 1
        db.execute('select 2')
        second = int(conn.calls[2][0][1][0])
        assert second < first
    assert conn.closed and 2 <= int(seen[0][0]['connect_timeout']) <= 8
    assert '-csearch_path=public' in seen[0][0]['options']
    assert 'statement_timeout=' in seen[0][0]['options']


def test_no_connection_if_libpq_minimum_timeout_cannot_fit():
    with pytest.raises(control.RestoreUnavailable):
        with control.bounded_connection(lambda *_: pytest.fail('connect'), 'dbname=postgres', budget=budget(1.9)): pass


def test_connection_close_error_cannot_replace_primary():
    primary = KeyboardInterrupt('synthetic'); value = budget()
    class Broken(Connection):
        def close(self): raise OSError('synthetic close')
    with pytest.raises(KeyboardInterrupt) as caught:
        with control.bounded_connection(lambda *_, **__: Broken(), 'dbname=postgres', budget=value): raise primary
    assert caught.value is primary and value.context.owner.uncertain


def test_expired_database_alarm_closes_without_transactional_exit():
    value = budget(); events = []; primary = None
    class BlockedRollback(Connection):
        def __exit__(self, *_):
            events.append('transactional_exit')
            raise AssertionError('rollback must never be entered after failure')
        def close(self):
            assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
            events.append('close'); super().close()
    conn = BlockedRollback()
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.bounded_connection(lambda *_, **__: conn, 'dbname=postgres', budget=value):
            # Acquisition has headroom; a real one-shot alarm then expires
            # while the connection is owned, as a blocked driver wait would.
            value.end = time.monotonic() + .02
            signal.setitimer(signal.ITIMER_REAL, .02)
            try: time.sleep(.2)
            except BaseException as error:
                primary = error
                raise
    assert caught.value is primary and caught.value.reason == 'deadline'
    assert events == ['close'] and conn.closed
    assert not value.context.owner.uncertain
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_positive_database_exit_remains_guarded_and_closes_on_expiry():
    value = budget(); events = []; primary = None
    class BlockedCommit(Connection):
        def __exit__(self, *args):
            nonlocal primary
            assert args == (None, None, None)
            assert signal.getitimer(signal.ITIMER_REAL)[0] > 0
            events.append('positive_exit')
            signal.setitimer(signal.ITIMER_REAL, .02)
            try: time.sleep(.2)
            except BaseException as error:
                primary = error
                raise
        def close(self): events.append('close'); super().close()
    conn = BlockedCommit()
    with pytest.raises(control.RestoreUnavailable) as caught:
        with control.bounded_connection(lambda *_, **__: conn, 'dbname=postgres', budget=value): pass
    assert caught.value is primary and caught.value.reason == 'deadline'
    assert events == ['positive_exit', 'close'] and conn.closed


def test_boundary_adapter_is_idempotent_and_passes_budget_only_to_owned_seams():
    value = budget(); calls = []
    original = SimpleNamespace(owned_source=lambda *a: a,
        inspect_container=lambda *a, **k: calls.append(('inspect', a, k)),
        verify_source_session=lambda *a, **k: calls.append(('session', a, k)),
        role_memberships=lambda *a, **k: calls.append(('roles', a, k)))
    bound = control.bounded_boundary(original, value)
    assert control.bounded_boundary(bound, value) is bound
    bound.inspect_container('owned'); bound.verify_source_session('source', 'owned'); bound.role_memberships('source')
    assert all(k == {'budget': value} for _, _, k in calls)
    assert original.owned_source is bound.owned_source


def test_target_session_uses_one_budget_for_db_and_exact_container_query(monkeypatch):
    value = budget(); conn = Connection([73]); calls = []
    monkeypatch.setattr(identity.psycopg, 'connect', lambda *a, **k: conn)
    value.checked = lambda *a, **k: calls.append((a, k, signal.getitimer(signal.ITIMER_REAL)[0])) or SimpleNamespace(stdout=b'1\n')
    identity.verify_target_session('dbname=postgres', 'a'*64, 'operator', budget=value)
    assert len(calls) == 1 and calls[0][2] == 0
    assert conn.closed and any('pg_backend_pid' in a[0] for a, _ in conn.calls)


def test_gateway_delegation_preserves_body_bounds_and_budget(monkeypatch):
    value = budget(); seen = []
    @contextmanager
    def bridge(port, **kwargs): seen.append((port, kwargs)); yield 'synthetic'
    monkeypatch.setattr(control, 'bounded_gateway', bridge)
    monkeypatch.setattr(storage, 'bounded_gateway', bridge)
    with identity.auth_gateway(5000, budget=value) as url: assert url == 'synthetic'
    with storage.storage_gateway(5001, budget=value) as url: assert url == 'synthetic'
    assert [k['body_cap'] for _, k in seen] == [65536, 10*1024**2]
    assert all(k['budget'] is value for _, k in seen)


def test_wrapper_executor_bounds_existing_to_thread_callback_without_orphan():
    import threading
    called = []
    def original():
        called.append(threading.current_thread())
        time.sleep(3)
    async def work():
        await asyncio.to_thread(original)
    with pytest.raises(control.RestoreUnavailable) as caught:
        control.run_async(work(), budget=budget(2.025))
    assert caught.value.reason == 'deadline'
    assert called == [threading.main_thread()]
    assert not any(t.name.startswith('ThreadPoolExecutor') for t in threading.enumerate())


def test_wrapper_executor_preserves_context_and_primary_exception():
    original = KeyboardInterrupt('original callback')
    value = budget()
    async def work():
        def callback():
            assert control.current_budget() is value
            raise original
        return await asyncio.to_thread(callback)
    with pytest.raises(KeyboardInterrupt) as caught:
        control.run_async(work(), budget=value)
    assert caught.value is original


@pytest.mark.parametrize('primary_failure,expired', [(False,False),(True,False),(True,True)])
def test_gateway_mock_lifecycle_reaps_all_threads_and_preserves_primary(monkeypatch, primary_failure, expired):
    import http.server
    value = budget(); threads = []; servers = []
    class Thread:
        def __init__(self, target=None, daemon=False):
            self.target = target; self.ident = None; self.alive = False; self.joined = False
            threads.append(self)
        def start(self): self.ident = len(threads); self.alive = True
        def is_alive(self): return self.alive
        def join(self, timeout):
            assert 0 <= timeout <= max(0, value.end-time.monotonic()+.001)
            self.joined = True
    class Timer(Thread):
        def __init__(self, seconds, callback):
            super().__init__(target=callback); assert 0 < seconds < 8
        def cancel(self): self.alive = False
    class Server:
        def __init__(self, address, handler):
            self.server_address = ('127.0.0.1', 34567); self.closed = False; servers.append(self)
        def serve_forever(self, **kwargs): pass
        def shutdown(self):
            assert not expired
            threads[0].alive = False
        def server_close(self):
            self.closed = True
            if primary_failure: raise OSError('synthetic close')
    # No socket, thread or server is actually created.
    monkeypatch.setattr(http.server, 'ThreadingHTTPServer', Server)
    monkeypatch.setattr(control._io_threading, 'Thread', Thread)
    monkeypatch.setattr(control._io_threading, 'Timer', Timer)
    original = KeyboardInterrupt('primary')
    source_cleanup = []
    try:
        try:
            with control.bounded_gateway(5000, prefix='/auth/v1', body_cap=65536, budget=value, unavailable='fixed') as url:
                assert url == 'http://127.0.0.1:34567'
                if primary_failure:
                    if expired: value.end = time.monotonic()-1
                    value.context.owner._cancel(original)
                    raise original
        finally:
            # Model the outer owner's independent source-post finally: sticky
            # gateway uncertainty must not skip that block or replace primary.
            with control.unwind_scope(value):
                value.enter('source_post')
                source_cleanup.append(value.remaining())
    except KeyboardInterrupt as caught:
        assert primary_failure and caught is original
    assert servers[0].closed and all(t.joined for t in threads)
    assert threads[0].alive is expired and not threads[1].alive
    assert len(source_cleanup) == 1 and 0 < source_cleanup[0] <= 13
    assert bool(value.context.owner.uncertain) == primary_failure


def test_optional_legacy_forwarding_cannot_escape_repair_deadline(monkeypatch):
    monkeypatch.setenv('TALLI_RF_RESTORE_SSH_CONFIG', 'synthetic-unused')
    control.require_direct_loopback(None)
    with pytest.raises(control.RestoreUnavailable) as caught: control.require_direct_loopback(budget())
    assert caught.value.reason == 'source_binding'


def test_borrowed_clone_cleanup_does_not_enter_later_phase(monkeypatch):
    spec = importlib.util.spec_from_file_location('deadline_owned_clone', ROOT/'scripts/rehearse-rf1086-owned-restore.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    value = budget(); end = value.end; calls = []
    monkeypatch.setattr(module.boundary, 'owned_source', lambda *a: ('a'*64, 'postgres'))
    monkeypatch.setattr(module.boundary, 'verify_source_session', lambda *a, **k: None)
    monkeypatch.setattr(module.boundary, 'role_memberships', lambda *a, **k: [])
    def checked(args, **kwargs):
        calls.append((args, value.phase, value.end))
        assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
        return SimpleNamespace(stdout=b'')
    value.checked = checked
    import rf1086_database_clone_owner
    class CloneOwner:
        def __init__(self, container, source, clone, budget):
            assert budget is value
            self.container, self.clone = container, clone
        def create(self):
            control.io_checked(value, ['docker', 'exec', '-i', self.container, 'createdb', self.clone])
        def cleanup(self):
            control.io_checked(value, ['docker', 'exec', '-i', self.container, 'dropdb', self.clone])
    monkeypatch.setattr(rf1086_database_clone_owner, 'DatabaseCloneOwner', CloneOwner)
    primary = KeyboardInterrupt('business')
    with pytest.raises(KeyboardInterrupt) as caught:
        with module.restored_database('dbname=postgres', 'synthetic', budget=value): raise primary
    assert caught.value is primary
    assert calls[-1][0][4] == 'dropdb'
    assert all(phase == 'construction' and until == end for _, phase, until in calls)


def test_wrapper_company_uses_same_budget_at_repair_and_source_post(monkeypatch, tmp_path):
    import test_rf1086_company_test_retention_restore_runner as fixture
    args, events, _, _, _ = fixture._configure_owned_runner_double(monkeypatch, tmp_path, None)
    value = budget(); observed = []
    original_restore = fixture.runner.restored_identity
    @contextmanager
    def restore(*args, budget):
        assert budget is value
        observed.append(budget)
        with original_restore(*args, budget=budget) as recovery: yield recovery
        budget.enter('cleanup'); budget.enter('source_post')
        observed.append(budget.end)
    monkeypatch.setattr(fixture.runner, 'restored_identity', restore)
    result = fixture.runner.rehearse(args, budget=value)
    assert result['sourceInventoryUnchanged']
    assert observed[0] is value and observed[1] == value.end and value.phase == 'source_post'


def test_company_failure_output_expiry_preserves_first_failure(monkeypatch):
    import test_rf1086_company_test_retention_restore_runner as fixture
    value = budget(); primary = ValueError('private synthetic primary'); calls = []
    def blocked_print(*args, **kwargs):
        calls.append((args, kwargs))
        assert value.phase == 'output' and signal.getitimer(signal.ITIMER_REAL)[0] > 0
        signal.setitimer(signal.ITIMER_REAL, .02)
        time.sleep(.2)
    monkeypatch.setattr(fixture.runner, 'print', blocked_print, raising=False)
    try: raise primary
    except ValueError as original:
        fixture.runner._failure_output(original, ('finite_label',), value)
    assert len(calls) == 1 and value.context.owner.primary is primary
    assert value.context.owner.uncertain and signal.getitimer(signal.ITIMER_REAL)[0] == 0


@pytest.mark.parametrize('release_mode', ['caller_exit', 'while_open'])
def test_internal_relay_finishes_registration_before_owned_close(relays, monkeypatch, release_mode):
    import socket
    import threading
    value = budget(); value.phase = 'actors'; end = value.end
    ready = threading.Event(); release = threading.Event(); done = threading.Event()
    observed = {}
    original_setup = control._InternalRelay.setup
    def left():
        return max(0, end - .25 - time.monotonic())
    def setup(self, ports):
        bound = original_setup(self, ports)
        real_register = self.selector.register
        def register(item, events, data=None):
            if (threading.current_thread() is self.thread
                    and item not in self.listeners and not observed):
                observed['socket'] = item
                observed['initial_fd'] = item.fileno()
                observed['initial_stop'] = self.stop.is_set()
                observed['tracked'] = item in self.sockets and item in self.peers
                ready.set()
                assert release.wait(left()), 'register barrier expired'
                observed['register_fd'] = item.fileno()
                observed['register_stop'] = self.stop.is_set()
                try:
                    result = real_register(item, events, data)
                    observed['registered'] = True
                    return result
                finally:
                    # Control stops only after real registration, avoiding a
                    # second, uninstrumented caller-close race at teardown.
                    if release_mode == 'while_open':
                        self.stop.set()
                    done.set()
            return real_register(item, events, data)
        monkeypatch.setattr(self.selector, 'register', register)
        return bound
    monkeypatch.setattr(control._InternalRelay, 'setup', setup)
    client = None
    primary = None
    try:
        with socket.socket() as upstream:
            upstream.bind(('127.0.0.1', 0)); upstream.listen(1); upstream.settimeout(1)
            owner, inspections = relay_owner(value, (upstream.getsockname(), upstream.getsockname()))
            with control.internal_loopback_ports(owner, budget=value) as ports:
                relay = relays[0]
                real_join = relay.thread.join
                def join(timeout=None):
                    # Release at the actual owned join, after the caller has
                    # requested stop. The real selector decides whether fd is valid.
                    release.set()
                    return real_join(timeout)
                monkeypatch.setattr(relay.thread, 'join', join)
                client = socket.create_connection(('127.0.0.1', ports[0]), timeout=1)
                assert ready.wait(left()), 'register was not reached'
                assert observed['initial_fd'] >= 0 and observed['tracked']
                assert observed['initial_stop'] is False
                if release_mode == 'while_open':
                    release.set()
                    assert done.wait(left()), 'open registration did not finish'
                    real_join(left())
                    assert not relay.thread.is_alive()
            assert len(inspections) == 2
    except BaseException as error:
        primary = error
        raise
    finally:
        release.set()
        if client is not None:
            try:
                client.close()
            except BaseException:
                if primary is None:
                    raise
    assert observed['registered'] and observed['register_fd'] >= 0
    assert observed['register_stop'] is (release_mode == 'caller_exit')
    assert relays[0].failure is None and not relays[0].close_failed
    assert not relays[0].thread.is_alive() and not relays[0].sockets
    assert value.end == end and value.phase == 'actors'
