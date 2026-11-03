"""Pure signed admission protocol; no provider, mailbox, credentials or filesystem IO.

Bindings are plain dicts. Keys accept Ed25519PrivateKey, raw 32-byte seeds or
lowercase hex. ``now`` returns Unix seconds; optional ``monotonic`` detects wall
clock steps (enabled by default with the real clock). Callers using a fake clock
can inject its monotonic clock too. Runtime must serialize access to each object.

sign() adds requestNonce to command payloads. verify() returns a detached complete
verified envelope. allow_expired_cleanup permits authentication of old recovery
metadata only; neither admission class uses it. Every acknowledgement carries a
signed state checkpoint. A mailbox tail alone is NOT a trusted full checkpoint.

Remote persistence receives snapshot(), including the last command/reply cache,
before publication. Failures close admission; callbacks must raise on failure.
observe() accepts only fresh, post-request provider GET results, never cached GETs.
Local consumption calls persist_consume_callback(intent, ack) before returning
{action, project}; this callback must durably create an exclusive consumption
record across process restarts. Only that return authorizes ONE provider dispatch.
No provider dispatch is authorized by accept_reply(). Job verification is an
external, fresh GitHub job in_progress check, not a cached run/arm check.
"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import re
import time
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


_BINDING_FIELDS = {'version', 'windowId', 'authoritySha256', 'configSha256', 'commit',
    'repository', 'workflowPath', 'runId', 'runAttempt', 'jobId', 'issueNumber',
    'cleanupAtUtc', 'armBeforeUtc', 'coordinatorPublicKey', 'mode'}
_KINDS = {'armed', 'intent', 'intent_ack', 'heartbeat', 'heartbeat_ack', 'finish', 'finish_ack'}
_COMMANDS = {'intent', 'heartbeat', 'finish'}
_STATUSES = {'ACTIVE_HEALTHY', 'INACTIVE', 'PAUSING', 'COMING_UP', 'RESTORING',
    'ACTIVE_UNHEALTHY', 'GOING_DOWN', 'INIT_FAILED', 'REMOVED', 'UNKNOWN'}
_STATE_FIELDS = {'version', 'binding', 'remotePublicKey', 'projects', 'armed', 'armNonce',
    'admissionClosed', 'closeReason', 'commandSeq', 'acceptedActions', 'pendingMutations',
    'observations', 'pendingHistoryKnown'}


def _require(ok, code='hosted_arming_invalid'):
    if not ok:
        raise ValueError(code)


def _json(value, depth=0):
    _require(depth <= 32)
    if type(value) is dict:
        _require(all(type(key) is str for key in value))
        for key in value:
            key.encode('utf-8')
        for item in value.values():
            _json(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _json(item, depth + 1)
    elif type(value) is str:
        value.encode('utf-8')
    else:
        _require(value is None or type(value) in (str, int, bool) or
            type(value) is float and math.isfinite(value))


def canonical(value) -> bytes:
    """Strict JSON bytes: sorted string keys, compact separators, no NaN."""
    try:
        _json(value)
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise ValueError('hosted_arming_invalid') from None


def _hex(value, length):
    _require(type(value) is str and re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is not None)
    return bytes.fromhex(value)


def _private(value):
    if isinstance(value, Ed25519PrivateKey):
        return value
    if type(value) is str:
        value = _hex(value, 64)
    _require(type(value) is bytes and len(value) == 32)
    return Ed25519PrivateKey.from_private_bytes(value)


def public_key(private) -> str:
    return _private(private).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def _public(value):
    raw = _hex(value, 64)
    _require(raw != bytes(32))
    return Ed25519PublicKey.from_public_bytes(raw)


def _uuid(value):
    _require(type(value) is str)
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise ValueError('hosted_arming_invalid') from None
    _require(str(parsed) == value and parsed.int != 0)


def _stamp(value):
    _require(type(value) is str and 'T' in value)
    try:
        parsed = datetime.fromisoformat(value)
        _require(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0)
        return parsed.timestamp()
    except (ValueError, OverflowError, AttributeError, OSError):
        raise ValueError('hosted_arming_invalid') from None


def _seconds(value):
    try:
        _require(type(value) in (int, float) and math.isfinite(value))
        datetime.fromtimestamp(value, timezone.utc)
    except (ValueError, OverflowError, OSError):
        raise ValueError('hosted_arming_invalid') from None
    return value


def _utc(value):
    return datetime.fromtimestamp(_seconds(value), timezone.utc).isoformat()


def _binding(binding):
    _require(type(binding) is dict and set(binding) == _BINDING_FIELDS)
    canonical(binding)
    _require(type(binding['version']) is int and binding['version'] == 1)
    _uuid(binding['windowId'])
    for field, length in [('authoritySha256', 64), ('configSha256', 64), ('commit', 40)]:
        _hex(binding[field], length)
    for field in ('runId', 'runAttempt', 'jobId', 'issueNumber'):
        _require(type(binding[field]) is int and binding[field] > 0)
    _require(binding['runAttempt'] == 1)
    _require(type(binding['repository']) is str and
        re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', binding['repository']) is not None)
    _require(binding['workflowPath'] == '.github/workflows/talli-recovery-cleanup.yml')
    _require(binding['mode'] in ('metadata-only', 'cleanup'))
    _public(binding['coordinatorPublicKey'])
    _require(_stamp(binding['armBeforeUtc']) < _stamp(binding['cleanupAtUtc']))


def validate_binding(binding, now=None, *, allow_expired_cleanup=False):
    """Validate a plain binding; expiry bypass is only for cleanup metadata."""
    _binding(binding)
    _require(type(allow_expired_cleanup) is bool)
    _require(_seconds(time.time() if now is None else now) < _stamp(binding['cleanupAtUtc']) or
        allow_expired_cleanup, 'hosted_arming_expired')
    return deepcopy(binding)


def _payload(kind, nonce, payload):
    _require(type(payload) is dict)
    canonical(payload)
    if kind in _COMMANDS:
        fields = {'commandSeq', 'requestNonce'} | ({'action', 'role'} if kind == 'intent' else set())
        _require(set(payload) == fields)
        _require(type(payload['commandSeq']) is int and 1 <= payload['commandSeq'] <= 2048)
        _require(payload['requestNonce'] == nonce)
        if kind == 'intent':
            _require((payload['action'], payload['role']) in (('pause', 'capacity'), ('resume', 'target')))


def sign(private, binding, kind, nonce, payload, now=None) -> dict:
    when = _seconds(time.time() if now is None else now)
    validate_binding(binding, when)
    _require(type(kind) is str and kind in _KINDS)
    _uuid(nonce)
    _require(type(payload) is dict)
    canonical(payload)
    payload = deepcopy(payload)
    if kind in _COMMANDS:
        payload.setdefault('requestNonce', nonce)
    _payload(kind, nonce, payload)
    message = {'version': 1, 'binding': deepcopy(binding), 'kind': kind, 'nonce': nonce,
        'issuedAtUtc': _utc(when), 'payload': payload}
    message['signature'] = _private(private).sign(canonical(message)).hex()
    return message


def verify(message, public_hex, binding, now=None, max_age=30, allow_expired_cleanup=False) -> dict:
    when = _seconds(time.time() if now is None else now)
    _binding(binding)
    _require(type(allow_expired_cleanup) is bool)
    _require(_seconds(max_age) >= 0)
    _require(type(message) is dict and set(message) ==
        {'version', 'binding', 'kind', 'nonce', 'issuedAtUtc', 'payload', 'signature'})
    _require(type(message['version']) is int and message['version'] == 1)
    _require(canonical(message['binding']) == canonical(binding))
    _require(type(message['kind']) is str and message['kind'] in _KINDS)
    _uuid(message['nonce'])
    _payload(message['kind'], message['nonce'], message['payload'])
    issued = _stamp(message['issuedAtUtc'])
    _require(0 <= when - issued <= max_age, 'hosted_arming_stale')
    _require(issued < _stamp(binding['cleanupAtUtc']))
    _require(allow_expired_cleanup or when < _stamp(binding['cleanupAtUtc']), 'hosted_arming_expired')
    unsigned = {key: value for key, value in message.items() if key != 'signature'}
    signature = _hex(message['signature'], 128)
    try:
        _public(public_hex).verify(signature, canonical(unsigned))
    except InvalidSignature:
        raise ValueError('hosted_arming_signature_invalid') from None
    return deepcopy(message)


def _projects(projects):
    _require(type(projects) is dict and set(projects) == {'capacity', 'target'})
    _require(all(type(ref) is str and re.fullmatch('[a-z0-9]{20}', ref) is not None
        for ref in projects.values()))
    _require(projects['capacity'] != projects['target'])
    return deepcopy(projects)


class _Clock:
    def __init__(self, now, monotonic):
        _require(callable(now) and (monotonic is None or callable(monotonic)))
        self.now = now
        self.monotonic = time.monotonic if monotonic is None and now is time.time else monotonic
        self.wall = _seconds(now())
        self.start = self.wall
        self.mono = None if self.monotonic is None else _seconds(self.monotonic())
        self.origin = self.mono

    def read(self):
        wall = _seconds(self.now())
        mono = None if self.monotonic is None else _seconds(self.monotonic())
        _require(wall >= self.wall and (mono is None or mono >= self.mono and
            abs((wall - self.start) - (mono - self.origin)) <= 2), 'hosted_arming_clock_invalid')
        self.wall, self.mono = wall, mono
        return wall


class RemoteLedger:
    """Single-writer admission ledger. persist(snapshot) precedes publish(envelope).

    arm/handle return the published signed reply; observe/close return snapshot.
    snapshot adds lastCommand/lastReply to the state in every signed reply. There
    is no mailbox restore constructor: incomplete reconstruction must never acquire
    pendingHistoryKnown=True merely by instantiating a new ledger.
    """
    def __init__(self, binding, private_key, projects, persist_callback, publish_callback,
            now=time.time, *, monotonic=None):
        self._clock = _Clock(now, monotonic)
        self._binding = validate_binding(binding, self._clock.wall)
        self._private = _private(private_key)
        _require(callable(persist_callback) and callable(publish_callback))
        self._persist, self._publish = persist_callback, publish_callback
        self._state = {'version': 1, 'binding': deepcopy(self._binding),
            'remotePublicKey': public_key(self._private), 'projects': _projects(projects),
            'armed': False, 'armNonce': None, 'admissionClosed': False, 'closeReason': None,
            'commandSeq': 0, 'acceptedActions': [], 'pendingMutations': {},
            'observations': {}, 'pendingHistoryKnown': True}
        self._last_command = self._last_reply = None
        self._nonces = set()

    @property
    def binding(self):
        return deepcopy(self._binding)

    @property
    def pending(self):
        return deepcopy(self._state['pendingMutations'])

    @property
    def accepted(self):
        return deepcopy(self._state['acceptedActions'])

    @property
    def admission_closed(self):
        return self.snapshot()['admissionClosed']

    def _record(self):
        return {**deepcopy(self._state), 'lastCommand': deepcopy(self._last_command),
            'lastReply': deepcopy(self._last_reply)}

    def _save(self, state, command=None, reply=None):
        record = {**deepcopy(state), 'lastCommand': deepcopy(command), 'lastReply': deepcopy(reply)}
        try:
            self._persist(record)
        except Exception:
            self._state['admissionClosed'] = True
            self._state['closeReason'] = 'persistence'
            raise ValueError('hosted_arming_persist_failed') from None
        self._state = deepcopy(state)
        self._last_command, self._last_reply = deepcopy(command), deepcopy(reply)

    def close(self, reason='closed'):
        _require(reason in ('closed', 'deadline', 'clock', 'cancelled', 'publication'))
        if not self._state['admissionClosed']:
            state = deepcopy(self._state)
            state.update(admissionClosed=True, closeReason=reason)
            self._save(state, self._last_command, self._last_reply)
        return self._record()

    def _current(self, *, allow_closed=False):
        try:
            when = self._clock.read()
        except ValueError:
            self.close('clock')
            raise ValueError('hosted_arming_clock_invalid') from None
        if when >= _stamp(self._binding['cleanupAtUtc']):
            self.close('deadline')
        _require(allow_closed or not self._state['admissionClosed'], 'hosted_arming_closed')
        return when

    def snapshot(self):
        # Recovery inspection must remain available after a failed clock or write.
        try:
            self._current(allow_closed=True)
        except ValueError:
            if not self._state['admissionClosed']:
                raise
        return self._record()

    def _emit(self, reply, *, finishing=False):
        # Persistence/publication can block: recheck time after durability too.
        when = self._current(allow_closed=finishing)
        if reply['kind'] == 'armed' and when >= _stamp(self._binding['armBeforeUtc']):
            self.close('publication')
            raise ValueError('hosted_arming_expired')
        if when - _stamp(reply['issuedAtUtc']) > 30:
            self.close('publication')
            raise ValueError('hosted_arming_stale')
        _require(when < _stamp(self._binding['cleanupAtUtc']), 'hosted_arming_expired')
        try:
            self._publish(deepcopy(reply))
        except Exception:
            self.close('publication')
            raise ValueError('hosted_arming_publish_failed') from None
        self._current(allow_closed=finishing)
        return deepcopy(reply)

    def arm(self, nonce):
        when = self._current()
        _require(when < _stamp(self._binding['armBeforeUtc']), 'hosted_arming_expired')
        _require(not self._state['armed'], 'hosted_arming_replay')
        _uuid(nonce)
        state = deepcopy(self._state)
        state.update(armed=True, armNonce=nonce)
        reply = sign(self._private, self._binding, 'armed', nonce, {'state': state}, when)
        self._save(state, reply=reply)
        return self._emit(reply)

    def observe(self, project, status):
        when = self._current(allow_closed=True)
        _require(type(project) is str and project in self._state['projects'].values())
        _require(type(status) is str and status in _STATUSES)
        state = deepcopy(self._state)
        state['observations'][project] = {'status': status, 'atUtc': _utc(when)}
        for key, pending in list(state['pendingMutations'].items()):
            if pending['project'] == project and pending['goal'] == status:
                del state['pendingMutations'][key]
        self._save(state, self._last_command, self._last_reply)
        return self._record()

    def _intent(self, state, message, when):
        _require(self._binding['mode'] == 'cleanup', 'hosted_arming_mode_denied')
        payload = message['payload']
        action, role = payload['action'], payload['role']
        _require(not state['pendingMutations'], 'hosted_arming_pending')
        prior = [(item['action'], item['role']) for item in state['acceptedActions']]
        expected = ('pause', 'capacity') if not prior else ('resume', 'target')
        _require(len(prior) < 2 and (action, role) == expected, 'hosted_arming_order')
        for checked_role, expected_status in (
                [('capacity', 'ACTIVE_HEALTHY'), ('target', 'INACTIVE')] if not prior else
                [('capacity', 'INACTIVE'), ('target', 'INACTIVE')]):
            observed = state['observations'].get(state['projects'][checked_role])
            _require(observed is not None and observed['status'] == expected_status and
                0 <= when - _stamp(observed['atUtc']) <= 30, 'hosted_arming_preflight')
        project = state['projects'][role]
        pending = {'action': action, 'project': project,
            'goal': 'INACTIVE' if action == 'pause' else 'ACTIVE_HEALTHY',
            'atUtc': _utc(when), 'acknowledged': False}
        state['pendingMutations'][action + ':' + project] = pending
        state['acceptedActions'].append({**pending, 'role': role,
            'commandSeq': payload['commandSeq'], 'nonce': message['nonce']})

    def handle(self, message):
        when = self._current(allow_closed=True)
        message = verify(message, self._binding['coordinatorPublicKey'], self._binding, when)
        _require(message['kind'] in _COMMANDS)
        seq = message['payload']['commandSeq']
        finishing_retry = self._last_command is not None and self._last_command['kind'] == 'finish'
        _require(not self._state['admissionClosed'] or finishing_retry, 'hosted_arming_closed')
        _require(self._state['armed'], 'hosted_arming_not_armed')
        if seq == self._state['commandSeq']:
            _require(self._last_command is not None and canonical(message) == canonical(self._last_command),
                'hosted_arming_replay')
            return self._emit(self._last_reply, finishing=finishing_retry)
        _require(not self._state['admissionClosed'], 'hosted_arming_closed')
        _require(seq == self._state['commandSeq'] + 1, 'hosted_arming_sequence')
        used_nonces = {item['nonce'] for item in self._state['acceptedActions']}
        used_nonces.add(self._state['armNonce'])
        # Include heartbeat/finish nonces, even when their sequences have aged out.
        _require(message['nonce'] not in self._nonces, 'hosted_arming_replay')
        _require(message['nonce'] not in used_nonces, 'hosted_arming_replay')
        state = deepcopy(self._state)
        if message['kind'] == 'intent':
            self._intent(state, message, when)
        state['commandSeq'] = seq
        if message['kind'] == 'finish':
            state.update(admissionClosed=True, closeReason='closed')
        payload = {'commandSeq': seq, 'replyTo': message['nonce'],
            'commandDigest': sha256(canonical(message)).hexdigest(), 'state': state}
        reply = sign(self._private, self._binding, message['kind'] + '_ack', message['nonce'], payload, when)
        self._save(state, message, reply)
        self._nonces.add(message['nonce'])
        return self._emit(reply, finishing=message['kind'] == 'finish')


class LocalAdmission:
    """Fresh job + exact signed ack + durable exclusive consume, before dispatch."""
    def __init__(self, binding, remote_public_key, persist_consume_callback, now=time.time,
            *, monotonic=None):
        self._clock = _Clock(now, monotonic)
        self._binding = validate_binding(binding, self._clock.wall)
        _public(remote_public_key)
        _require(callable(persist_consume_callback))
        self.remote_public_key, self._persist = remote_public_key, persist_consume_callback
        self._armed = False
        self._closed = False
        self._seq = 0
        self._nonces = set()
        self._projects = None
        self._arm_nonce = None

    @property
    def binding(self):
        return deepcopy(self._binding)

    def _current(self, job_verified):
        try:
            when = self._clock.read()
        except ValueError:
            self._closed = True
            raise ValueError('hosted_arming_clock_invalid') from None
        if when >= _stamp(self._binding['cleanupAtUtc']) or job_verified is not True:
            self._closed = True
        _require(not self._closed, 'hosted_arming_closed')
        return when

    def _state(self, reply):
        state = reply['payload'].get('state')
        _require(type(state) is dict and set(state) == _STATE_FIELDS)
        _require(type(state['version']) is int and state['version'] == 1 and
            canonical(state['binding']) == canonical(self._binding) and
            state['remotePublicKey'] == self.remote_public_key and state['armed'] is True and
            type(state['admissionClosed']) is bool and state['pendingHistoryKnown'] is True)
        _uuid(state['armNonce'])
        _require(type(state['commandSeq']) is int and 0 <= state['commandSeq'] <= 2048)
        _require(type(state['acceptedActions']) is list and type(state['pendingMutations']) is dict and
            type(state['observations']) is dict)
        projects = _projects(state['projects'])
        _require(self._projects is None or self._projects == projects)
        return state

    def accept_arm(self, message, nonce, job_verified: bool):
        when = self._current(job_verified)
        _uuid(nonce)
        _require(not self._armed, 'hosted_arming_replay')
        _require(when < _stamp(self._binding['armBeforeUtc']), 'hosted_arming_expired')
        message = verify(message, self.remote_public_key, self._binding, when)
        _require(message['kind'] == 'armed' and message['nonce'] == nonce and
            set(message['payload']) == {'state'})
        _require(_stamp(message['issuedAtUtc']) < _stamp(self._binding['armBeforeUtc']))
        state = self._state(message)
        _require(state['armNonce'] == nonce and state['commandSeq'] == 0 and
            not state['admissionClosed'] and not state['acceptedActions'] and not state['pendingMutations'])
        self._armed = True
        self._arm_nonce = nonce
        self._projects = deepcopy(state['projects'])
        self._nonces.add(nonce)
        return deepcopy(state)

    def _reply(self, command, ack, job_verified):
        when = self._current(job_verified)
        _require(self._armed, 'hosted_arming_not_armed')
        command = verify(command, self._binding['coordinatorPublicKey'], self._binding, when)
        _require(command['kind'] in _COMMANDS)
        ack = verify(ack, self.remote_public_key, self._binding, when)
        seq = command['payload']['commandSeq']
        _require(seq == self._seq + 1 and command['nonce'] not in self._nonces, 'hosted_arming_replay')
        _require(ack['kind'] == command['kind'] + '_ack' and ack['nonce'] == command['nonce'] and
            set(ack['payload']) == {'commandSeq', 'replyTo', 'commandDigest', 'state'})
        _require(type(ack['payload']['commandSeq']) is int and ack['payload']['commandSeq'] == seq and
            ack['payload']['replyTo'] == command['nonce'] and
            ack['payload']['commandDigest'] == sha256(canonical(command)).hexdigest() and
            _stamp(ack['issuedAtUtc']) >= _stamp(command['issuedAtUtc']))
        state = self._state(ack)
        _require(state['commandSeq'] == seq and state['armNonce'] == self._arm_nonce and
            state['admissionClosed'] is (command['kind'] == 'finish'))
        return command, ack, state

    def _accepted(self, command):
        self._seq = command['payload']['commandSeq']
        self._nonces.add(command['nonce'])
        if command['kind'] == 'finish':
            self._closed = True

    def accept_reply(self, command, ack, job_verified: bool):
        command, ack, state = self._reply(command, ack, job_verified)
        _require(command['kind'] in ('heartbeat', 'finish'))
        self._accepted(command)
        return deepcopy(state)

    def consume(self, intent, ack, job_verified: bool):
        intent, ack, state = self._reply(intent, ack, job_verified)
        _require(intent['kind'] == 'intent' and self._binding['mode'] == 'cleanup', 'hosted_arming_mode_denied')
        payload = intent['payload']
        project = self._projects[payload['role']]
        pending = {'action': payload['action'], 'project': project,
            'goal': 'INACTIVE' if payload['action'] == 'pause' else 'ACTIVE_HEALTHY',
            'atUtc': ack['issuedAtUtc'], 'acknowledged': False}
        accepted = {**pending, 'role': payload['role'], 'commandSeq': payload['commandSeq'],
            'nonce': intent['nonce']}
        _require(state['pendingMutations'].get(payload['action'] + ':' + project) == pending and
            state['acceptedActions'] and state['acceptedActions'][-1] == accepted)
        try:
            self._persist(deepcopy(intent), deepcopy(ack))
        except Exception:
            self._closed = True
            raise ValueError('hosted_arming_consume_failed') from None
        self._accepted(intent)
        self._current(job_verified)
        if self._clock.wall - _stamp(ack['issuedAtUtc']) > 30:
            self._closed = True
            raise ValueError('hosted_arming_stale')
        return {'action': payload['action'], 'project': project}
