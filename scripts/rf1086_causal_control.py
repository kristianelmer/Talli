"""Bounded sequential S0/Is/In mechanics; never recovery or repair acceptance."""
import hashlib
import json
import math
import re
import secrets
import sys
import time
from types import SimpleNamespace

import rf1086_s0_control as runtime
import rf1086_s0_protocol as s0


def _protocol():
    import rf1086_causal_protocol
    return rf1086_causal_protocol


def new_context():
    context = runtime.new_context()
    context.acquired_targets = set()
    context.branches = {kind: _protocol().unavailable(kind, 'dependency', 'unobserved')
                        for kind in ('Is', 'In')}
    return context


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


class ReferenceCache:
    """Three sealed normalized snapshots, never raw observations or disk data."""
    def __init__(self):
        self._entries = {}
        self._pending = None
        self._seal = None
        self._invalid = False

    @property
    def ready(self):
        return not self._invalid and self._seal is not None

    def clear(self):
        self._entries.clear()
        self._pending = self._seal = None
        self._invalid = True

    def stage(self, index, projection, normalized):
        if (self._invalid or self._seal is not None or self._pending is not None
                or type(index) is not int or not 0 <= index < 3 or index in self._entries):
            raise runtime.ControlFailure('dependency')
        raw = _canonical(normalized)
        if len(raw) > 32768 or len(raw)+sum(v[2] for v in self._entries.values()) > 98304:
            self.clear()
            raise runtime.ControlFailure('dependency')
        # Detach once from the parser/callback. This is a JSON ownership copy,
        # not a second raw-catalog validation or normalization of hook hashes.
        owned = json.loads(raw)
        if s0.snapshot_commitment(owned) != projection['snapshot']:
            self.clear()
            raise runtime.ControlFailure('dependency')
        self._pending = (index, owned, len(raw), _canonical(projection))

    def complete(self, exchange):
        if exchange['point'][0] == 'anchor':
            if self._pending is not None:
                raise runtime.ControlFailure('dependency')
            return
        if (self._invalid or self._pending is None
                or exchange['point'] != ['cut', self._pending[0]]
                or _canonical(exchange['catalog']) != self._pending[3]):
            raise runtime.ControlFailure('dependency')
        index, owned, size, projection = self._pending
        self._entries[index] = (owned, projection, size)
        self._pending = None

    def seal(self, receipt):
        if (self._invalid or self._pending is not None or set(self._entries) != {0, 1, 2}
                or receipt.get('status') != 'matched'):
            raise runtime.ControlFailure('dependency')
        cuts = {e['point'][1]: e for e in receipt['exchanges'] if e['point'][0] == 'cut'}
        if (set(cuts) != {0, 1, 2} or any(_canonical(cuts[i]['catalog']) != self._entries[i][1]
                                        for i in range(3))):
            raise runtime.ControlFailure('dependency')
        self._seal = runtime._hash(receipt)

    def require(self, receipt):
        if not self.ready or self._seal != runtime._hash(receipt):
            raise runtime.ControlFailure('dependency')

    def reference(self, index, receipt):
        self.require(receipt)
        if type(index) is not int or index not in self._entries:
            raise runtime.ControlFailure('dependency')
        # Only the current bounded snapshot is copied for an untrusted callback;
        # the three-cache ownership graph is never handed out or copied per branch.
        return json.loads(_canonical(self._entries[index][0]))


def _finite_end(value):
    return type(value) in (int, float) and math.isfinite(value)


def _check(context, end, point=None):
    context.raise_if_fatal()
    if time.monotonic() >= end:
        raise runtime.ControlFailure('deadline', point)


def _script_nonce(context, script, stream, end, used):
    if type(script) is not bytes or not 0 < len(script) <= 134217728:
        raise runtime.ControlFailure('binding')
    nonce = secrets.token_hex(16)
    if nonce in used:
        raise runtime.ControlFailure('nonce_collision')
    hashed = hashlib.sha256()
    needle = nonce.encode('ascii')
    for offset in range(0, len(script), 65536):
        _check(context, end)
        hashed.update(memoryview(script)[offset:offset+65536])
        if script.find(needle, max(0, offset-31), offset+65536) != -1:
            raise runtime.ControlFailure('nonce_collision')
    if stream != {'bytes': len(script), 'sha256': hashed.hexdigest()}:
        raise runtime.ControlFailure('binding')
    return nonce


def _failure(protocol, kind, stage, error, context, work_end):
    context.raise_if_fatal()
    reason = getattr(error, 'reason', 'control_unavailable')
    point = getattr(error, 'point', None) if stage == 'transport' else None
    if time.monotonic() >= work_end and reason in ('command_unavailable', 'control_unavailable'):
        reason = 'deadline'
    if reason == 'command_unavailable':
        reason = 'command'
    if stage == 'admission' and reason == 'deadline':
        reason = 'headroom'
    if reason not in protocol.CONFIG['reasonStages'][stage]:
        reason = 'control_unavailable'
    return protocol.unavailable(kind, reason, stage, point)


def _compact_exchange(exchange, control_exchange):
    if (exchange['session'][:1]+exchange['session'][2:]
            != control_exchange['session'][:1]+control_exchange['session'][2:]):
        raise runtime.ControlFailure('session', tuple(exchange['point']))
    return {'point': exchange['point'], 'input': exchange['input'],
            'pid': exchange['session'][1],
            'witnesses': [[w[1], w[5], w[13]] for w in exchange['witnesses']],
            'observer': exchange['observer'], 'catalog': exchange['catalog']}


def _observe_branch(kind, *, context, script, descriptor, f2, fsql, metadata,
                    previous_target, started, hard_end, resources, references,
                    seen_targets, nonces):
    protocol = _protocol()
    stage, target, policy, prediction = 'admission', None, None, None
    runner = runtime.S0Runner(context, min(started+5, hard_end))
    cleaned = True
    acquisition_unknown = False
    result = protocol.unavailable(kind, 'dependency', 'unobserved')

    def phase(name, allocation, cumulative):
        nonlocal stage
        stage = name
        runner.end = min(time.monotonic()+allocation, started+cumulative, hard_end)
        _check(context, runner.end)

    try:
        _check(context, runner.end)
        references.cache.require(references.s0)
        prediction = resources.raw_prediction(kind, runner.end)
        policy = protocol.prepare_policy(kind,
            source_catalog=metadata['phases']['source_pre_dump']['catalog'],
            failed_catalog=metadata['phases']['mismatch']['catalog'],
            ledger=fsql['ledger'], raw_binding=prediction.binding, deadline=runner.end)
        nonce = _script_nonce(context, script, fsql['stream'], runner.end, nonces)
        if nonce.encode('ascii') in policy.sql:
            raise runtime.ControlFailure('nonce_collision')
        nonces.add(nonce)
        points = protocol.ordered_points(policy, descriptor, fsql['ledger'])
        from rf1086_catalog_causal_capture import _snapshot_statement
        catalog_sql = _snapshot_statement()
        if (len(catalog_sql) != protocol.CONFIG['catalogQuery']['bytes']
                or hashlib.sha256(catalog_sql).hexdigest() != protocol.CONFIG['catalogQuery']['sha256']):
            raise runtime.ControlFailure('binding')
        _check(context, runner.end)
        phase('setup', 40, 45)
        cleaned = False
        if not resources.cleanup(runner.work_end, run=runner):
            context.raise_if_fatal()
            raise runtime.ControlFailure('ownership')
        # The adapter can create resources and then fail readiness before it
        # returns an ID. Cleanup alone cannot recover that ID for a later
        # branch's predecessor/all-acquired identity claim.
        acquisition_unknown = True
        target = resources.start(runner.work_end, run=runner, pause=runner.pause)
        context.raise_if_fatal()
        if (type(target) is not str or re.fullmatch('[a-f0-9]{64}', target) is None
                or target in seen_targets):
            raise runtime.ControlFailure('ownership')
        seen_targets.add(target)
        acquisition_unknown = False
        tool_raw = runner(s0.tool_argv(target), runner.work_end, cap=4096)
        tool = re.fullmatch(rb'psql \(PostgreSQL\) 17\.6\n([a-f0-9]{64})\n', tool_raw)
        if tool is None:
            raise runtime.ControlFailure('tool')
        resources.apply_roles(target, runner.work_end, run=runner)
        initialized = resources.initialized(target, runner.work_end, run=runner)
        initialized_hash = s0.snapshot_commitment(initialized)
        if initialized_hash != s0.snapshot_commitment(metadata['phases']['target_initialized']['catalog']):
            raise runtime.ControlFailure('initialized_mismatch')
        resources.drop_default(target, runner.work_end, run=runner)
        _check(context, runner.end)
        phase('transport', 45, 90)
        active = [None]
        actual = [None]
        admission = [None]
        after_mutation = [False]
        control_points = {tuple(e['point']): e for e in references.s0['exchanges']}

        def mapped(point):
            return ('cut', point[1]) if point[0] == 'post' else tuple(point)

        def session(raw, *, point, descriptor, baseline=None):
            value = protocol.parse_session(raw, point=point, descriptor=descriptor, baseline=baseline)
            expected = control_points[mapped(point)]['session']
            if value[:1]+value[2:] != expected[:1]+expected[2:]:
                raise runtime.ControlFailure('session', point)
            return value

        def request(point, sequence, pid):
            active[0] = point
            database = 'template1' if point == ('anchor', 0) else 'postgres'
            w = lambda role: protocol.witness_request(nonce, sequence, role, pid)
            data = w('anchor') if point[0] == 'anchor' else w('before')+catalog_sql+w('after')
            return s0.observer_argv(target, database), data

        def project(raw, selected):
            projected, normalized = s0.project_with_reference(raw, selected=selected,
                reference_catalog=metadata['phases']['mismatch']['catalog'])
            point = active[0]
            reference = references.cache.reference(point[1], references.s0)
            after = point[0] == 'post' or after_mutation[0]
            try:
                factored = protocol.factor_catalog(policy, normalized, reference, after=after, selected=selected)
            except protocol.Unavailable as error:
                raise runtime.ControlFailure(error.reason, point) from None
            actual[0] = normalized
            return factored

        def complete(exchange):
            point = tuple(exchange['point'])
            _compact_exchange(exchange, control_points[mapped(point)])
            if point == policy.point:
                try:
                    admission[0] = protocol.admit_mutation(policy, actual[0],
                        references.cache.reference(point[1], references.s0))
                except protocol.Unavailable as error:
                    raise runtime.ControlFailure(error.reason, point) from None
            if point[0] == 'post':
                after_mutation[0] = True
            actual[0] = None

        evidence = runtime.transport(script, descriptor, fsql['ledger'], context=context,
            nonce=nonce, writer_args=s0.writer_argv(target), observer_request=request,
            parse_session=session, parse_witness=protocol.parse_witness, project=project,
            probe=protocol.probe, points=points, work_end=min(time.monotonic()+43, runner.end-2),
            reap_end=runner.end, mutation_policy=runtime.MutationPolicy(kind, policy.point, policy.sql),
            exchange_complete=complete)
        if admission[0] is None or evidence['delivery']['original'] != fsql['stream']:
            raise runtime.ControlFailure('input')
        phase('final', 15, 105)
        final = resources.branch_final_state(target, runner.work_end, run=runner,
            branch_policy=policy, references=SimpleNamespace(prediction=prediction, s0=references.s0))
        if (type(final) is not dict or set(final) != {'fingerprint', 'enriched', 'raw'}
                or final['raw'] != {**prediction.binding, 'actual': prediction.binding['expected']}):
            raise runtime.ControlFailure('raw_prediction_mismatch')
        expected_fingerprint = metadata['failed'] | {'catalog': prediction.binding['expected']['sha256']}
        if final['fingerprint'] != expected_fingerprint:
            raise runtime.ControlFailure('fingerprint_mismatch')
        if final['enriched'] != s0.snapshot_commitment(policy.expected_final):
            raise runtime.ControlFailure('enriched_prediction_mismatch')
        result = {'schema': protocol.SCHEMA, 'kind': kind, 'status': 'prediction_matched',
            'bindings': {'s0': protocol.commitment(references.s0),
                'configuration': protocol.commitment(protocol.CONFIG),
                'expectation': protocol.commitment(protocol.expectation(policy,
                    s0_receipt=references.s0, f2_input=f2['input']))},
            'target': {'id': target, 'previous': previous_target, 'initialized': initialized_hash},
            'tool': {'version': '17.6', 'sha256': tool[1].decode('ascii')}, 'nonce': nonce,
            'mutation': {'point': list(policy.point), 'sql': evidence['delivery']['mutation']},
            'admission': admission[0], 'exchanges': [_compact_exchange(e, control_points[mapped(e['point'])])
                                                    for e in evidence['exchanges']],
            'delivery': evidence['delivery'], 'final': final,
            'cleanup': {'children': 'reaped', 'resources': 'removed'}}
        _check(context, runner.end)
    except Exception as error:
        result = _failure(protocol, kind, stage, error, context, runner.work_end)
    finally:
        primary = sys.exception()
        try:
            context.owner.unwind(runner.end, primary=primary)
        except Exception as error:
            result = _failure(protocol, kind, stage, error, context, runner.work_end)
        context.raise_if_fatal()
        if stage != 'admission':
            try:
                phase('cleanup', 13, 118)
                cleaned = resources.cleanup(runner.work_end, run=runner) is True
                _check(context, runner.end)
                if not cleaned:
                    result = protocol.unavailable(kind, 'cleanup_unproved', 'cleanup')
            except Exception:
                context.raise_if_fatal()
                cleaned = False
                result = protocol.unavailable(kind, 'cleanup_unproved', 'cleanup')
    try:
        phase('composition', 2, 120)
        protocol.validate_receipt(result, s0_receipt=references.s0, fsql=fsql,
            f2_input=f2['input'], metadata=metadata, inventory=f2['inventory'],
            other=context.branches['In' if kind == 'Is' else 'Is'])
        branches = context.branches | {kind: result}
        if not resources.summary_fits_sequence(references.s0, branches):
            result = protocol.unavailable(kind, 'summary_oversized', 'composition')
        _check(context, runner.end)
    except Exception:
        context.raise_if_fatal()
        result = protocol.unavailable(kind, 'control_unavailable', 'composition')
    previous = target if not acquisition_unknown and target is not None else previous_target
    return result, previous, cleaned and not acquisition_unknown


def observe_causal_sequence(*, context, script, descriptor, f2, fsql, metadata,
                            previous_target, optional_deadline, resources):
    """One declared sequence; ordinary branch failure never replaces matched S0."""
    protocol = _protocol()
    context.raise_if_fatal()
    context.result = s0.unavailable('dependency', 'admission')
    context.branches = {kind: protocol.unavailable(kind, 'dependency', 'unobserved')
                        for kind in ('Is', 'In')}
    started = time.monotonic()
    cache = ReferenceCache()
    def result():
        return {'S0': context.result, **context.branches}
    if not _finite_end(optional_deadline) or optional_deadline-started < 360:
        context.result = s0.unavailable('headroom', 'admission')
        context.branches = {kind: protocol.unavailable(kind, 'headroom', 'admission') for kind in ('Is', 'In')}
        return result()
    try:
        if fsql.get('status') != 'full_sql_verified' or fsql.get('ledger', {}).get('status') != 'verified_conditional':
            return result()
        common_end = min(started+5, optional_deadline)
        maximum_s0 = s0.maximum_receipt(fsql=fsql, f2_input=f2['input'], metadata=metadata,
            inventory=f2['inventory'], descriptor=descriptor)
        maximum_branches = {kind: protocol.maximum_receipt(kind, fsql=fsql, f2_input=f2['input'],
            metadata=metadata, inventory=f2['inventory'], descriptor=descriptor) for kind in ('Is', 'In')}
        _check(context, common_end)
        if not resources.summary_fits_sequence(maximum_s0, maximum_branches):
            context.result = s0.unavailable('summary_oversized', 'admission')
            context.branches = {kind: protocol.unavailable(kind, 'summary_oversized', 'admission') for kind in ('Is', 'In')}
            return result()
        _check(context, common_end)
        acquired = getattr(context, 'acquired_targets', set())
        if (type(acquired) is not set or any(type(t) is not str or re.fullmatch('[a-f0-9]{64}', t) is None
                                            for t in acquired)):
            raise runtime.ControlFailure('binding')
        seen = acquired | {previous_target, metadata['source'], metadata['sourceAuth']}
        # Keep the mutable ownership history on the same worker context. Source
        # IDs are exclusion sentinels, not a claim that this worker acquired them.
        context.acquired_targets = acquired
        acquired.add(previous_target)
        last_target = [previous_target]
        local_cleanup = [True]
        def start(deadline, **kwargs):
            local_cleanup[0] = False
            target = resources.start(deadline, **kwargs)
            if type(target) is not str or re.fullmatch('[a-f0-9]{64}', target) is None or target in seen:
                raise runtime.ControlFailure('ownership')
            seen.add(target); acquired.add(target); last_target[0] = target
            return target
        def cleanup(deadline, **kwargs):
            local_cleanup[0] = resources.cleanup(deadline, **kwargs) is True
            return local_cleanup[0]
        s0_resources = SimpleNamespace(start=start, cleanup=cleanup,
            apply_roles=resources.apply_roles, initialized=resources.initialized,
            drop_default=resources.drop_default, final_state=resources.final_state,
            summary_fits=lambda value: resources.summary_fits_sequence(value, maximum_branches))
        runtime.observe_s0(context=context, script=script, descriptor=descriptor, f2=f2,
            fsql=fsql, metadata=metadata, previous_target=previous_target,
            optional_deadline=min(started+120, optional_deadline), resources=s0_resources,
            reference_sink=cache, control_started=started)
        context.raise_if_fatal()
        if context.result.get('status') != 'matched' or not local_cleanup[0] or not cache.ready:
            return result()
        nonces = {context.result['nonce']}
        references = SimpleNamespace(s0=context.result, cache=cache)
        for number, kind in enumerate(('Is', 'In'), 2):
            now = time.monotonic()
            end = min(now+120, started+number*120, optional_deadline)
            if end-now < 120:
                context.branches[kind] = protocol.unavailable(kind, 'headroom', 'admission')
                continue
            value, previous, continue_safe = _observe_branch(kind, context=context, script=script,
                descriptor=descriptor, f2=f2, fsql=fsql, metadata=metadata,
                previous_target=last_target[0], started=now, hard_end=end, resources=resources,
                references=references, seen_targets=seen, nonces=nonces)
            context.branches[kind] = value
            last_target[0] = previous
            if previous not in (metadata['source'], metadata['sourceAuth']):
                acquired.add(previous)
            context.raise_if_fatal()
            if not continue_safe:
                break
        return result()
    except Exception:
        context.raise_if_fatal()
        # Only finite unavailable shapes escape an ordinary preparation failure;
        # do not erase already completed independent results.
        for kind in ('Is', 'In'):
            if context.branches[kind].get('status') != 'prediction_matched':
                context.branches[kind] = protocol.unavailable(kind, 'control_unavailable', 'unobserved')
        return result()
    except BaseException as error:
        # Pure admission/composition can be interrupted with no child active.
        # The nested lifecycle already unwinds any acquired children; do not
        # invent a second teardown allowance here, but keep cancellation sticky.
        context.owner._cancel(error)
        context.raise_if_fatal()
        raise
    finally:
        cache.clear()
