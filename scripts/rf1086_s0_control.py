"""Owned, bounded S0 control. No recovery, intervention or acceptance policy."""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
import secrets
import selectors
import signal
import subprocess
import sys
import time

import rf1086_catalog_semantics as commands
from rf1086_actual_replay_package import Unavailable


def _protocol():
    import rf1086_s0_protocol
    return rf1086_s0_protocol


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=True, allow_nan=False).encode('ascii')).hexdigest()


class S0ChildUncertain(BaseException):
    """Never caught by ordinary diagnostic-error shielding."""


class ControlFailure(ValueError):
    def __init__(self, reason, point=None):
        self.reason, self.point = reason, point
        super().__init__('s0_unavailable')


class _Slot:
    def __init__(self):
        self.process = None
        self.acquiring = False
        self.waited = False


class ChildOwner:
    """Two live slots, one first fatal exception, finite secondary bookkeeping."""
    def __init__(self):
        self.slots = (_Slot(), _Slot())
        self.primary = None
        self.uncertain = False
        self.cancelled = False
        self.errors = set()
        self._depth = 0
        self._active_primary = None

    def raise_if_fatal(self):
        if self.uncertain or self.cancelled:
            if self.primary is None:
                self.primary = S0ChildUncertain('s0_child_uncertain')
            raise self.primary

    def _uncertain(self, flag, error, primary=None):
        self.uncertain = True
        self.errors.add(flag)
        if self.primary is None:
            self.primary = primary if primary is not None else self._active_primary
            if self.primary is None:
                self.primary = error

    def _cancel(self, error):
        self.cancelled = True
        if self.primary is None:
            self.primary = self._active_primary if self._active_primary is not None else error

    @contextmanager
    def deferred(self, primary=None):
        """Callable handlers only: never leave a child with blocked/ignored signals."""
        previous_primary = self._active_primary
        if primary is not None:
            self._active_primary = primary
            if not isinstance(primary, Exception):
                self._cancel(primary)
        outer = self._depth == 0
        saved = []
        caught = None

        def record(signum, frame):
            self._cancel(KeyboardInterrupt())

        self._depth += 1
        try:
            if outer:
                for number in (signal.SIGINT, signal.SIGTERM):
                    old = signal.getsignal(number)
                    saved.append((number, old))
                    signal.signal(number, record)
            yield
        except BaseException as error:
            caught = error
            if not isinstance(error, Exception):
                self._cancel(error)
            raise
        finally:
            if outer:
                for number, handler in saved:
                    try:
                        signal.signal(number, handler)
                    except BaseException as error:
                        self._uncertain('handler', error, caught or primary)
            self._depth -= 1
            self._active_primary = previous_primary
            if outer:
                self.raise_if_fatal()

    def launch(self, args, *, stdin=subprocess.PIPE):
        self.raise_if_fatal()
        slot = next((s for s in self.slots if s.process is None and not s.acquiring), None)
        if slot is None:
            raise ControlFailure('command')
        with self.deferred():
            self.raise_if_fatal()
            slot.waited = False
            slot.acquiring = True
            try:
                process = subprocess.Popen(args, stdin=stdin, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, bufsize=0, restore_signals=True, start_new_session=False)
                # No validation, pipe setup or handler restoration before registration.
                slot.process = process
                slot.acquiring = False
            except BaseException as error:
                self._uncertain('acquisition', error)
                raise
        return process

    def reaped(self, process):
        slot = next(s for s in self.slots if s.process is process)
        slot.waited = True

    def unwind(self, deadline, *, primary=None, selector=None):
        """Disarm writes; attempt all kills, waits and closes under one endpoint."""
        with self.deferred(primary):
            if selector is not None:
                try:
                    for key in list(selector.get_map().values()):
                        if key.events & selectors.EVENT_WRITE:
                            selector.unregister(key.fileobj)
                except BaseException as error:
                    self._uncertain('selector', error, primary)
            for slot in self.slots:
                if slot.process is not None and not slot.waited:
                    try:
                        slot.process.kill()
                    except ProcessLookupError:
                        pass  # A subsequent wait is still required.
                    except BaseException as error:
                        self._uncertain('kill', error, primary)
            for slot in self.slots:
                process = slot.process
                if process is None:
                    continue
                if not slot.waited:
                    try:
                        process.wait(timeout=max(0, deadline - time.monotonic()))
                        slot.waited = True
                    except BaseException as error:
                        self._uncertain('wait', error, primary)
                closed = True
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except BaseException as error:
                            closed = False
                            self._uncertain('close', error, primary)
                if slot.waited and closed:
                    slot.process = None
            if selector is not None:
                try:
                    selector.close()
                except BaseException as error:
                    self._uncertain('selector', error, primary)
        if primary is None and time.monotonic() > deadline:
            raise ControlFailure('deadline')

    def finish(self, process, deadline):
        """Close just a confirmed completed observer, leaving the writer owned."""
        slot = next(s for s in self.slots if s.process is process)
        if not slot.waited or time.monotonic() > deadline:
            raise ControlFailure('deadline')
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                if stream is not None:
                    stream.close()
            except BaseException as error:
                self._uncertain('close', error)
        self.raise_if_fatal()
        slot.process = None


class S0Context:
    def __init__(self):
        self.owner = ChildOwner()
        self.result = _protocol().unavailable('dependency', 'admission')

    def raise_if_fatal(self):
        self.owner.raise_if_fatal()


def new_context():
    return S0Context()


class S0Runner:
    def __init__(self, context, end):
        self.context, self.end = context, end

    @property
    def work_end(self):
        return self.end - 2

    def __call__(self, args, deadline, *, data=None, archive=None, cap=8 * 1024**2):
        self.context.raise_if_fatal()
        work = min(deadline, self.work_end, time.monotonic() + 43)
        try:
            return commands._command(args, work, data=data, archive=archive,
                stdout_cap=cap, reap_deadline=self.end, child_owner=self.context.owner)
        except Exception:
            self.context.raise_if_fatal()
            raise Unavailable('command_unavailable') from None

    def pause(self, seconds, deadline):
        self.context.raise_if_fatal()
        remaining = min(deadline, self.work_end) - time.monotonic()
        if remaining <= 0:
            raise Unavailable('command_unavailable')
        time.sleep(min(seconds, remaining))
        self.context.raise_if_fatal()
        if time.monotonic() >= min(deadline, self.work_end):
            raise Unavailable('command_unavailable')


class _Lines:
    """Keep only possible reserved frames; discard arbitrarily split ordinary lines."""
    def __init__(self, prefixes, cap, accept, *, ordinary=False, check=lambda: None):
        self.prefixes, self.cap, self.accept, self.ordinary = prefixes, cap, accept, ordinary
        self.check = check
        self.pending = bytearray()
        self.discarding = False

    def feed(self, data):
        # Bounded chunk input; at most a bounded frame is accumulated.
        for index, byte in enumerate(data):
            if index % 4096 == 0:
                self.check()
            if self.discarding:
                if byte == 10:
                    self.discarding = False
                continue
            cap = self.cap() if callable(self.cap) else self.cap
            if len(self.pending) >= cap:
                raise ControlFailure('frame')
            self.pending.append(byte)
            if self.ordinary and not any(p.startswith(self.pending) or self.pending.startswith(p)
                                         for p in self.prefixes):
                self.pending.clear()
                self.discarding = byte != 10
                continue
            if byte == 10:
                value = bytes(self.pending)
                self.pending.clear()
                self.accept(value)

    def eof(self):
        if self.pending:
            raise ControlFailure('frame')


def _payload(line, prefix, cap):
    if not line.startswith(prefix) or not line.endswith(b'\n'):
        raise ControlFailure('frame')
    value = line[len(prefix):-1]
    if len(value) > cap * 2 or len(value) % 2 or re.fullmatch(rb'[0-9a-f]+', value) is None:
        raise ControlFailure('frame')
    return bytes.fromhex(value.decode('ascii'))


@dataclass(frozen=True, repr=False)
class MutationPolicy:
    """One already-admitted transaction; no arbitrary scheduling or retries."""
    kind: str
    point: tuple
    sql: bytes


def transport(script, descriptor, ledger, *, context, nonce, writer_args, observer_request,
              parse_session, parse_witness, project, probe, points, work_end, reap_end,
              mutation_policy=None, exchange_complete=None):
    return _transport(script, descriptor, ledger, context=context, nonce=nonce,
        writer_args=writer_args, observer_request=observer_request, parse_session=parse_session,
        parse_witness=parse_witness, project=project, probe=probe, points=points,
        work_end=work_end, reap_end=reap_end, mutation_policy=mutation_policy,
        exchange_complete=exchange_complete)


def restore_transport(script, descriptor, selections, *, context, nonce, writer_args,
                      observer_request, parse_session, parse_witness, project, probe,
                      points, work_end, reap_end, exchange_complete):
    """Closed construction profile: three pre/post hooks, at most three epochs.

    The callback runs only after a successful, reaped observer. At each cut it
    selects bytes from the source-compiled plan; it must validate each post
    observation before the next original byte is released. This entry returns
    transport evidence only, never legacy S0/C1 or recovery acceptance.
    """
    positions = tuple(points)
    cuts = [p[1] for p, _ in positions if p[0] == 'cut']
    anchors = [p[1] for p, _ in positions if p[0] == 'anchor']
    if (len(positions) not in (8, 9) or sorted(cuts) != [0, 1, 2]
            or anchors not in ([0, 1], [0, 1, 2])
            or [s.get('kind') for s in selections] != ['Is', 'In', 'acl']
            or any(type(offset) is not int or not 0 <= offset <= len(script)
                   for _, offset in positions)
            or any(a[1] > b[1] for a, b in zip(positions, positions[1:]))):
        raise ControlFailure('input')
    for i, (point, offset) in enumerate(positions):
        if point[0] == 'cut':
            if i+1 == len(positions) or positions[i+1] != (('post', point[1]), offset):
                raise ControlFailure('input')
        elif point[0] == 'post':
            if i == 0 or positions[i-1] != (('cut', point[1]), offset):
                raise ControlFailure('input')
        elif point[0] != 'anchor':
            raise ControlFailure('input')
    if (not callable(exchange_complete) or reap_end-work_end > 2
            or reap_end < work_end or work_end-time.monotonic() > 43):
        raise ControlFailure('input')
    return _transport(script, descriptor, {'selected': selections}, context=context, nonce=nonce,
        writer_args=writer_args, observer_request=observer_request, parse_session=parse_session,
        parse_witness=parse_witness, project=project, probe=probe, points=positions,
        work_end=work_end, reap_end=reap_end, exchange_complete=exchange_complete,
        construction=True)


def _transport(script, descriptor, ledger, *, context, nonce, writer_args, observer_request,
               parse_session, parse_witness, project, probe, points, work_end, reap_end,
               mutation_policy=None, exchange_complete=None, construction=False):
    """Shared mechanics only; injected fixture policies cannot mint an S0 receipt.

    observer_request(point, sequence, pid) -> (argv, exact input bytes).
    project(raw_json_line, selected_record) -> validated projection.
    Other callbacks have the production protocol signatures.
    """
    owner = context.owner
    selector = None
    writer = observer = None
    positions = tuple(points)
    marker = b'R1' if construction else b'S0'
    if mutation_policy is not None:
        if (type(mutation_policy) is not MutationPolicy or mutation_policy.kind not in ('Is', 'In')
                or type(mutation_policy.point) is not tuple or len(mutation_policy.point) != 2
                or mutation_policy.point[0] != 'cut' or type(mutation_policy.point[1]) is not int
                or not 0 <= mutation_policy.point[1] <= 2
                or type(mutation_policy.sql) is not bytes or not 0 < len(mutation_policy.sql) <= 2048
                or not mutation_policy.sql.startswith(b'BEGIN;\n')
                or not mutation_policy.sql.endswith(b'COMMIT;\n')
                or exchange_complete is None):
            raise ControlFailure('input')
        pre = [i for i, (p, _) in enumerate(positions) if p == mutation_policy.point]
        post = [i for i, (p, _) in enumerate(positions) if p[0] == 'post']
        if (len(pre) != 1 or post != [pre[0]+1] or len(positions) not in (6, 7)
                or positions[post[0]] != (('post', mutation_policy.point[1]), positions[pre[0]][1])):
            raise ControlFailure('input')
        marker = b'C1'
    elif not construction and any(p[0] == 'post' for p, _ in positions):
        raise ControlFailure('input')
    baseline = {}
    exchanges = []
    original_hash, probe_hash, mutation_hash = (hashlib.sha256() for _ in range(3))
    original_count = probe_count = 0
    mutation_count = 0
    expected_mutation_count = 0
    mutation_exchanges = []
    sequence = 0
    state = 'original'
    pending = memoryview(b'')
    pending_kind = None
    point = None
    session = barrier_pid = None
    witnesses, catalog = [], None
    exchange_end = None
    observer_part = 0
    counters = {'writer': [0, 0], 'observer': [0, 0]}
    ends = {'writer': [False, False], 'observer': [False, False]}
    cleanup_end = reap_end

    def check():
        context.raise_if_fatal()
        end = min(work_end, exchange_end - 2) if exchange_end is not None else work_end
        if time.monotonic() >= end:
            raise ControlFailure('deadline', point)
        return end

    def register_reads(process, name):
        for i, stream in enumerate((process.stdout, process.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, (name, i))
        os.set_blocking(process.stdin.fileno(), False)

    def schedule(data, kind):
        nonlocal pending, pending_kind
        check()
        pending, pending_kind = memoryview(data), kind
        selector.register(writer.stdin, selectors.EVENT_WRITE, ('writer_input', 0))

    def frame(line):
        nonlocal state, session, barrier_pid
        prefix = ('/' + nonce + '/' + f'{sequence:02d}' + '/').encode('ascii')
        try:
            if state == 'expect_p':
                epoch = point[1] if point[0] == 'anchor' else descriptor['cuts'][point[1]][0]
                previous = None if point[0] == 'anchor' else baseline[epoch]['session']
                session = parse_session(_payload(line, marker + b'P' + prefix, 2000),
                    point=point, descriptor=descriptor, baseline=previous)
                state = 'send_q'
            elif state == 'expect_b':
                if not line.startswith(marker + b'B' + prefix):
                    raise ControlFailure('frame')
                pid = line[len(marker + b'B' + prefix):-1]
                if re.fullmatch(rb'[1-9][0-9]{0,9}', pid) is None or int(pid) != session[1]:
                    raise ControlFailure('frame')
                barrier_pid, state = int(pid), 'start_observer'
            else:
                raise ControlFailure('frame')
        except ControlFailure:
            raise
        except Exception:
            raise ControlFailure('session', point) from None

    def observer_line(line):
        nonlocal observer_part, catalog
        roles = ('anchor',) if point[0] == 'anchor' else ('before', 'catalog', 'after')
        if observer_part >= len(roles):
            raise ControlFailure('observer', point)
        role = roles[observer_part]
        try:
            if role == 'catalog':
                if len(line) > (8 * 1024**2 if construction else 32768):
                    raise ControlFailure('partial_catalog', point)
                catalog = project(line, ledger['selected'][point[1]])
            else:
                if len(line) > 4096:
                    raise ControlFailure('frame', point)
                prefix = marker + f'O/{nonce}/{sequence:02d}/{role}/'.encode('ascii')
                epoch = point[1] if point[0] == 'anchor' else descriptor['cuts'][point[1]][0]
                previous = None if point[0] == 'anchor' else baseline[epoch]['witness']
                witness = parse_witness(_payload(line, prefix, 2000), nonce=nonce,
                    sequence=sequence, session=session, epoch_witness=previous)
                if point[0] == 'anchor' and epoch:
                    old = baseline[epoch-1]['witness']
                    if (witness[2], witness[5]) == (old[2], old[5]):
                        raise ControlFailure('observer', point)
                witnesses.append(witness)
        except ControlFailure:
            raise
        except Exception:
            raise ControlFailure('partial_catalog' if role == 'catalog' else 'observer', point) from None
        observer_part += 1

    writer_lines = _Lines((marker+b'P/', marker+b'B/'), 4096, frame, ordinary=True, check=check)
    observer_lines = None
    try:
        check()
        selector = selectors.DefaultSelector()
        check()
        writer = owner.launch(writer_args)
        check()
        register_reads(writer, 'writer')
        while True:
            check()
            if state == 'original' and not pending:
                limit = positions[sequence][1] if sequence < len(positions) else len(script)
                if original_count < limit:
                    schedule(memoryview(script)[original_count:min(limit, original_count+65536)], 'original')
                elif sequence < len(positions):
                    point = positions[sequence][0]
                    allowance = 4 if point[0] == 'anchor' else 6
                    if work_end - time.monotonic() < allowance:
                        raise ControlFailure('deadline', point)
                    exchange_end = time.monotonic() + allowance
                    cleanup_end = exchange_end
                    state = 'send_p'
                else:
                    writer.stdin.close()
                    state = 'drain'
            if state in ('send_p', 'send_q'):
                p, q = probe(nonce, sequence)
                chosen = p if state == 'send_p' else q
                next_state = 'expect_p' if state == 'send_p' else 'expect_b'
                schedule(chosen, next_state)
                state = 'writing_probe'
            if state == 'start_observer':
                check()
                args, data = observer_request(point, sequence, barrier_pid)
                observer = owner.launch(args)
                check()
                register_reads(observer, 'observer')
                observer_pending = memoryview(data)
                selector.register(observer.stdin, selectors.EVENT_WRITE, ('observer_input', 0))
                observer_lines = _Lines((),
                    lambda: (8 * 1024**2 if construction else 32768)
                            if point[0] != 'anchor' and observer_part == 1 else 4096,
                    observer_line, check=check)
                counters['observer'], ends['observer'] = [0, 0], [False, False]
                observer_part, witnesses, catalog = 0, [], None
                state = 'observing'
            # EOF is not termination. Keep draining the writer while an observer
            # that closed its pipes still runs; no blocking wait in this state.
            if (state == 'observing' and all(ends['observer']) and observer.stdin.closed
                    and observer.poll() is not None):
                exit_code = observer.wait(timeout=0)
                owner.reaped(observer)
                check()
                if exit_code or observer_part != (1 if point[0] == 'anchor' else 3):
                    raise ControlFailure('observer', point)
                owner.finish(observer, exchange_end)
                exchange = {'point': list(point), 'input': [original_count, original_count],
                    'session': session, 'barrierPid': barrier_pid, 'witnesses': witnesses,
                    'observer': _io(counters['observer']), 'catalog': catalog}
                selected_mutation = None
                if exchange_complete is not None:
                    selected_mutation = exchange_complete(exchange)
                    check()
                if construction:
                    if point[0] == 'cut':
                        cap = 1024**2 if point[1] == 2 else 2048
                        if (type(selected_mutation) is not bytes or len(selected_mutation) > cap
                                or selected_mutation and (not selected_mutation.startswith(b'BEGIN;\n')
                                    or not selected_mutation.endswith(b'COMMIT;\n'))):
                            raise ControlFailure('input', point)
                        expected_mutation_count += len(selected_mutation)
                        if expected_mutation_count > 1024**2:
                            raise ControlFailure('input', point)
                        mutation_exchanges.append({'point': list(point),
                            'bytes': len(selected_mutation),
                            'sha256': hashlib.sha256(selected_mutation).hexdigest()})
                    elif selected_mutation is not None:
                        raise ControlFailure('input', point)
                exchanges.append(exchange)
                if point[0] == 'anchor':
                    baseline[point[1]] = {'session': session, 'witness': witnesses[0]}
                observer = None
                sequence += 1
                if construction and selected_mutation:
                    if work_end-time.monotonic() < 4:
                        raise ControlFailure('deadline', point)
                    exchange_end = min(time.monotonic()+4, work_end)
                    cleanup_end = exchange_end
                    schedule(selected_mutation, 'mutation')
                    state = 'writing_mutation'
                elif mutation_policy is not None and point == mutation_policy.point:
                    if mutation_count or work_end-time.monotonic() < 4:
                        raise ControlFailure('deadline', point)
                    exchange_end = min(time.monotonic()+4, work_end)
                    cleanup_end = exchange_end
                    schedule(mutation_policy.sql, 'mutation')
                    state = 'writing_mutation'
                else:
                    point, exchange_end = None, None
                    cleanup_end, state = reap_end, 'original'
            if state == 'drain' and all(ends['writer']):
                exit_code = writer.wait(timeout=max(0, check()-time.monotonic()))
                owner.reaped(writer)
                check()
                if exit_code:
                    raise ControlFailure('command')
                owner.finish(writer, reap_end)
                result = {'exchanges': exchanges, 'delivery': {
                    'original': {'bytes': original_count, 'sha256': original_hash.hexdigest()},
                    'probes': {'bytes': probe_count, 'sha256': probe_hash.hexdigest()},
                    'frames': [sequence, sequence], 'writer': _io(counters['writer'])}}
                if mutation_policy is not None:
                    if mutation_count != len(mutation_policy.sql):
                        raise ControlFailure('input')
                    result['delivery']['mutation'] = {'bytes': mutation_count, 'sha256': mutation_hash.hexdigest()}
                if construction:
                    if mutation_count != expected_mutation_count or len(mutation_exchanges) != 3:
                        raise ControlFailure('input')
                    result['delivery']['mutation'] = {'bytes': mutation_count,
                        'sha256': mutation_hash.hexdigest(), 'exchanges': mutation_exchanges}
                return result
            for key, _ in selector.select(min(0.05, max(0, check()-time.monotonic()))):
                check()
                name, index = key.data
                if name.endswith('_input'):
                    data = pending if name == 'writer_input' else observer_pending
                    try:
                        n = os.write(key.fd, data[:65536])
                    except BlockingIOError:
                        continue
                    check()
                    if n <= 0:
                        raise ControlFailure('input', point)
                    if name == 'writer_input':
                        if pending_kind == 'original':
                            original_hash.update(data[:n]); original_count += n
                        elif pending_kind == 'mutation':
                            mutation_hash.update(data[:n]); mutation_count += n
                            if mutation_count > (1024**2 if construction else 2048): raise ControlFailure('input', point)
                        else:
                            probe_hash.update(data[:n]); probe_count += n
                            if probe_count > 16384: raise ControlFailure('input', point)
                        if probe_count+mutation_count > (1024**2+16384 if construction else 16384): raise ControlFailure('input', point)
                        pending = pending[n:]
                        if not pending:
                            selector.unregister(key.fileobj)
                            if pending_kind == 'mutation':
                                point, exchange_end = None, None
                                cleanup_end, state = reap_end, 'original'
                            elif pending_kind != 'original': state = pending_kind
                    else:
                        observer_pending = observer_pending[n:]
                        if not observer_pending:
                            selector.unregister(key.fileobj); key.fileobj.close()
                    continue
                cap = (1048576 if name == 'writer' else (8*1024**2 if construction else 49152)) if index == 0 else (65536 if name == 'writer' else 0)
                try:
                    data = os.read(key.fd, min(65536, cap-counters[name][index]+1))
                except BlockingIOError:
                    continue
                check()
                if not data:
                    selector.unregister(key.fileobj); key.fileobj.close()
                    ends[name][index] = True
                    if index == 0:
                        (writer_lines if name == 'writer' else observer_lines).eof()
                    continue
                counters[name][index] += len(data)
                if counters[name][index] > cap:
                    raise ControlFailure('observer' if name == 'observer' else 'frame', point)
                if index == 0:
                    (writer_lines if name == 'writer' else observer_lines).feed(data)
    except ControlFailure as error:
        if error.point is None:
            error.point = point
        raise
    finally:
        owner.unwind(cleanup_end, primary=sys.exception(), selector=selector)


def _io(counts):
    return {'stdoutBytes': counts[0], 'stderrBytes': counts[1], 'stdoutEnd': 'eof',
            'stderrEnd': 'eof', 'exitCode': 0, 'reap': 'waited'}


def observe_s0(*, context, script, descriptor, f2, fsql, metadata, previous_target,
               optional_deadline, resources, reference_sink=None, control_started=None):
    """Default S0 is unchanged; an optional cache is subordinate to its proof."""
    sealed = False
    try:
        result = _observe_s0(context=context, script=script, descriptor=descriptor,
            f2=f2, fsql=fsql, metadata=metadata, previous_target=previous_target,
            optional_deadline=optional_deadline, resources=resources,
            reference_sink=reference_sink, control_started=control_started)
        if reference_sink is not None:
            sealed = result.get('status') == 'matched' and reference_sink.ready
        return result
    finally:
        if reference_sink is not None and not sealed:
            reference_sink.clear()


def _observe_s0(*, context, script, descriptor, f2, fsql, metadata, previous_target,
                optional_deadline, resources, reference_sink=None, control_started=None):
    protocol = _protocol()
    context.raise_if_fatal()
    stage, point = 'admission', None
    now = time.monotonic()
    started = now if control_started is None else control_started
    if type(started) not in (int, float) or not math.isfinite(started) or started > now:
        context.result = protocol.unavailable('headroom', stage)
        return context.result
    hard_end = started + 120
    if (type(optional_deadline) not in (int, float)
            or not math.isfinite(optional_deadline) or hard_end > optional_deadline):
        context.result = protocol.unavailable('headroom', stage)
        return context.result
    result = None
    runner = S0Runner(context, min(started+5, hard_end))
    target = None

    def phase(name, allocation, cumulative):
        nonlocal stage, point
        stage, point = name, None
        runner.end = min(time.monotonic()+allocation, started+cumulative, hard_end)
        if time.monotonic() >= runner.end:
            raise ControlFailure('deadline')

    def alive():
        context.raise_if_fatal()
        if time.monotonic() >= runner.end:
            raise ControlFailure('deadline', point)

    def failed(error):
        context.raise_if_fatal()
        at = None
        if isinstance(error, ControlFailure):
            reason, at = error.reason, error.point
        elif isinstance(error, Unavailable):
            specific = {'full_control_mismatch': 'fingerprint_mismatch',
                        'full_causal_control_mismatch': 'enriched_mismatch'}
            reason = (specific[error.reason] if stage == 'final' and error.reason in specific
                      else 'deadline' if time.monotonic() >= runner.work_end else 'command')
        else:
            reason = 'control_unavailable'
        if stage == 'admission' and reason in ('deadline', 'control_unavailable'):
            reason = 'headroom' if reason == 'deadline' else 'descriptor_invalid'
        if reason not in protocol.CONFIG['reasonStages'][stage]:
            reason = 'descriptor_invalid' if stage == 'admission' else 'control_unavailable'
        return protocol.unavailable(reason, stage, at if stage == 'transport' else None)

    try:
        if (fsql.get('status') != 'full_sql_verified'
                or fsql.get('ledger', {}).get('status') != 'verified_conditional'):
            raise ControlFailure('dependency')
        if descriptor is None:
            raise ControlFailure('descriptor_invalid')
        try:
            protocol.validate_descriptor(descriptor, fsql['ledger'], fsql['stream'])
        except Exception:
            raise ControlFailure('descriptor_invalid') from None
        nonce = secrets.token_hex(16)
        hashed = hashlib.sha256()
        needle = nonce.encode('ascii')
        if type(script) is not bytes or not 0 < len(script) <= 134217728:
            raise ControlFailure('descriptor_invalid')
        for offset in range(0, len(script), 65536):
            alive()
            hashed.update(memoryview(script)[offset:offset+65536])
            if script.find(needle, max(0, offset-31), offset+65536) != -1:
                raise ControlFailure('nonce_collision')
        if fsql['stream'] != {'bytes': len(script), 'sha256': hashed.hexdigest()}:
            raise ControlFailure('descriptor_invalid')
        maximum = protocol.maximum_receipt(fsql=fsql, f2_input=f2['input'], metadata=metadata,
            descriptor=descriptor, inventory=f2['inventory'])
        if not resources.summary_fits(maximum):
            raise ControlFailure('summary_oversized')
        from rf1086_catalog_causal_capture import _snapshot_statement
        catalog_sql = _snapshot_statement()
        expected = protocol.CONFIG['queries']['catalog']
        if (type(catalog_sql) is not bytes or len(catalog_sql) != expected['bytes']
                or hashlib.sha256(catalog_sql).hexdigest() != expected['sha256']):
            raise ControlFailure('descriptor_invalid')
        alive()
        phase('setup', 40, 45)
        if not resources.cleanup(runner.work_end, run=runner):
            context.raise_if_fatal()
            raise ControlFailure('ownership')
        target = resources.start(runner.work_end, run=runner, pause=runner.pause)
        context.raise_if_fatal()
        if (type(target) is not str or re.fullmatch('[a-f0-9]{64}', target) is None
                or target in (previous_target, metadata['source'], metadata['sourceAuth'])):
            raise ControlFailure('ownership')
        tool_raw = runner(protocol.tool_argv(target), runner.work_end, cap=4096)
        tool = re.fullmatch(rb'psql \(PostgreSQL\) 17\.6\n([a-f0-9]{64})\n', tool_raw)
        if tool is None: raise ControlFailure('tool')
        resources.apply_roles(target, runner.work_end, run=runner)
        initialized = resources.initialized(target, runner.work_end, run=runner)
        initialized_hash = protocol.snapshot_commitment(initialized)
        if initialized_hash != protocol.snapshot_commitment(metadata['phases']['target_initialized']['catalog']):
            raise ControlFailure('initialized_mismatch')
        resources.drop_default(target, runner.work_end, run=runner)
        alive()
        phase('transport', 45, 90)

        def observer_request(at, sequence, pid):
            database = 'template1' if at == ('anchor', 0) else 'postgres'
            w = lambda role: protocol.witness_request(nonce, sequence, role, pid)
            data = w('anchor') if at[0] == 'anchor' else w('before') + catalog_sql + w('after')
            return protocol.observer_argv(target, database), data

        def projection(raw, selected):
            if reference_sink is None:
                return protocol.project(raw, selected=selected,
                    reference_catalog=metadata['phases']['mismatch']['catalog'])
            projected, normalized = protocol.project_with_reference(raw, selected=selected,
                reference_catalog=metadata['phases']['mismatch']['catalog'])
            try:
                reference_sink.stage(fsql['ledger']['selected'].index(selected), projected, normalized)
            except Exception:
                context.raise_if_fatal()
                reference_sink.clear()
            return projected

        def confirmed(exchange):
            try:
                reference_sink.complete(exchange)
            except Exception:
                context.raise_if_fatal()
                reference_sink.clear()

        options = {} if reference_sink is None else {'exchange_complete': confirmed}
        evidence = transport(script, descriptor, fsql['ledger'], context=context, nonce=nonce,
            writer_args=protocol.writer_argv(target), observer_request=observer_request,
            parse_session=protocol.parse_session, parse_witness=protocol.parse_witness,
            project=projection,
            probe=protocol.probe, points=protocol.ordered_points(descriptor, fsql['ledger']),
            work_end=min(time.monotonic()+43, runner.end-2), reap_end=runner.end, **options)
        if evidence['delivery']['original'] != fsql['stream']:
            raise ControlFailure('input')
        phase('final', 15, 105)
        fingerprint, final_catalog = resources.final_state(target, runner.work_end, run=runner)
        if fingerprint != metadata['failed']:
            raise ControlFailure('fingerprint_mismatch')
        final_hash = protocol.snapshot_commitment(final_catalog)
        if final_hash != protocol.snapshot_commitment(metadata['phases']['mismatch']['catalog']):
            raise ControlFailure('enriched_mismatch')
        result = {'schema': protocol.CONFIG['receipt'], 'status': 'matched',
            'bindings': {'input': _hash(f2['input']), 'configuration': _hash(protocol.CONFIG),
                'ledger': _hash(fsql['ledger']), 'descriptor': _hash(descriptor)},
            'target': {'id': target, 'previous': previous_target, 'initialized': initialized_hash},
            'tool': {'version': '17.6', 'sha256': tool[1].decode('ascii')}, 'nonce': nonce,
            'references': {'epochs': descriptor['epochs'], 'cuts': descriptor['cuts']},
            **evidence, 'final': {'fingerprint': fingerprint, 'enriched': final_hash}}
        alive()
    except Exception as error:
        result = failed(error)
    finally:
        primary = sys.exception()
        try:
            context.owner.unwind(runner.end, primary=primary)
        except Exception as error:
            result = failed(error)
        context.raise_if_fatal()
        # Even a failed setup can have created remote resources; the parent also
        # retains its authoritative cleanup. Never erase its F2 package here.
        if stage != 'admission':
            try:
                phase('cleanup', 13, 118)
                complete = resources.cleanup(runner.work_end, run=runner)
                context.raise_if_fatal()
                alive()
                if not complete:
                    result = protocol.unavailable('cleanup_unproved', 'cleanup')
            except Exception:
                context.raise_if_fatal()
                result = protocol.unavailable('cleanup_unproved', 'cleanup')
    try:
        phase('composition', 2, 120)
        protocol.validate_receipt(result, fsql=fsql,
            f2_input=f2.get('input') if type(f2) is dict else None, metadata=metadata,
            inventory=f2.get('inventory') if type(f2) is dict else None)
        alive()
        if not resources.summary_fits(result):
            result = protocol.unavailable('summary_oversized', 'composition')
        if reference_sink is not None and result.get('status') == 'matched':
            try:
                reference_sink.seal(result)
            except Exception:
                context.raise_if_fatal()
                reference_sink.clear()
        alive()
    except Exception:
        context.raise_if_fatal()
        result = protocol.unavailable('control_unavailable', 'composition')
    context.result = result
    return result
