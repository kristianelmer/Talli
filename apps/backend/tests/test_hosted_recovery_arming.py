"""Offline protocol risk tests: signatures, freshness, replay and durable ordering."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

import pytest
import socket
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from talli_backend.adapters import hosted_recovery_arming as core


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Protocol tests must never access the network")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


class Clock:
    def __init__(self):
        self.wall = 1793700000.0
        self.mono = 100.0

    def __call__(self):
        return self.wall

    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds


def utc(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


class Session:
    def __init__(self, mode='cleanup', persist=None, publish=None, consume=None):
        self.clock = Clock()
        self.coordinator = Ed25519PrivateKey.from_private_bytes(b'c' * 32)
        self.remote = Ed25519PrivateKey.from_private_bytes(b'r' * 32)
        self.projects = {'capacity': 'b' * 20, 'target': 'c' * 20}
        self.binding = {'version': 1, 'windowId': str(uuid4()), 'authoritySha256': 'a' * 64,
            'configSha256': 'b' * 64, 'commit': 'c' * 40, 'repository': 'owner/repo',
            'workflowPath': '.github/workflows/talli-recovery-cleanup.yml', 'runId': 10,
            'runAttempt': 1, 'jobId': 11, 'issueNumber': 192,
            'cleanupAtUtc': utc(self.clock() + 120), 'armBeforeUtc': utc(self.clock() + 10),
            'coordinatorPublicKey': core.public_key(self.coordinator), 'mode': mode}
        self.records, self.published, self.consumed = [], [], []
        self.ledger = core.RemoteLedger(self.binding, self.remote, self.projects,
            persist or self.records.append, publish or self.published.append, self.clock,
            monotonic=lambda: self.clock.mono)
        self.local = core.LocalAdmission(self.binding, core.public_key(self.remote),
            consume or (lambda intent, ack: self.consumed.append((intent, ack))), self.clock,
            monotonic=lambda: self.clock.mono)
        self.nonce = str(uuid4())

    def arm(self):
        ack = self.ledger.arm(self.nonce)
        self.local.accept_arm(ack, self.nonce, True)
        return ack

    def preflight(self):
        self.ledger.observe(self.projects['capacity'], 'ACTIVE_HEALTHY')
        self.ledger.observe(self.projects['target'], 'INACTIVE')

    def command(self, kind='heartbeat', seq=1, **payload):
        return core.sign(self.coordinator, self.binding, kind, str(uuid4()),
            {'commandSeq': seq, **payload}, self.clock())

    def pause(self):
        return self.command('intent', action='pause', role='capacity')

    def resume(self, seq=2):
        return self.command('intent', seq, action='resume', role='target')


def rejected(call, code=None):
    with pytest.raises(ValueError) as error:
        call()
    assert str(error.value).startswith('hosted_arming_')
    if code:
        assert str(error.value) == 'hosted_arming_' + code
    return error


def test_canonical_is_strict_deterministic_and_has_no_coercions():
    assert core.canonical({'z': [True, None], 'a': 'ø'}) == b'{"a":"\\u00f8","z":[true,null]}'
    for invalid in [float('nan'), float('inf'), {1: 'x'}, {True: 'x'}, (1,), b'x', object(), '\ud800']:
        rejected(lambda: core.canonical(invalid), 'invalid')
    cyclic = []
    cyclic.append(cyclic)
    rejected(lambda: core.canonical(cyclic), 'invalid')


def test_key_forms_and_invalid_keys_are_safe():
    seed = b'c' * 32
    assert core.public_key(seed) == core.public_key(seed.hex()) == core.public_key(
        Ed25519PrivateKey.from_private_bytes(seed))
    for invalid in [None, 'secret-key', 'a' * 63, b'a' * 31, 12, {}, 'A' * 64]:
        error = rejected(lambda: core.public_key(invalid), 'invalid')
        assert 'secret-key' not in str(error.value)
    s = Session()
    msg = s.command()
    for invalid in [None, 'x' * 64, '0' * 64, 'a' * 62]:
        rejected(lambda: core.verify(msg, invalid, s.binding, s.clock()))


def test_sign_and_verify_are_detached_and_bind_every_binding_field():
    s = Session()
    msg = s.command()
    verified = core.verify(msg, core.public_key(s.coordinator), s.binding, s.clock())
    assert verified == msg and verified is not msg
    verified['binding']['runId'] = 999
    for field, original in s.binding.items():
        changed = deepcopy(s.binding)
        if type(original) is int:
            changed[field] += 1
        elif field in ('cleanupAtUtc', 'armBeforeUtc'):
            changed[field] = utc(core._stamp(original) + 1)
        elif field == 'windowId':
            changed[field] = str(uuid4())
        else:
            changed[field] = original + 'x'
        rejected(lambda: core.verify(msg, core.public_key(s.coordinator), changed, s.clock()))
    assert msg['binding'] == s.binding


def test_binding_strict_fields_types_dates_mode_and_single_attempt():
    s = Session()
    invalid = [{}, {**s.binding, 'unexpected': 1}]
    for field, value in [('version', True), ('runId', True), ('jobId', 0), ('runAttempt', 2),
            ('issueNumber', -1), ('mode', []), ('mode', 'pilot'), ('windowId', '0' * 32),
            ('coordinatorPublicKey', '0' * 64), ('authoritySha256', 'G' * 64),
            ('repository', '../owner/repo'), ('workflowPath', 'other.yml'),
            ('cleanupAtUtc', '2026-11-03'), ('cleanupAtUtc', '2026-11-03T12:00:00+01:00'),
            ('armBeforeUtc', s.binding['cleanupAtUtc'])]:
        invalid.append({**s.binding, field: value})
    for binding in invalid:
        rejected(lambda: core.validate_binding(binding, s.clock()))
    assert core.validate_binding(s.binding, s.clock()) == s.binding


def test_envelope_and_nonce_malformed_objects_fail_safely():
    s = Session()
    msg = s.command()
    for bad in [None, [], {}, {**msg, 'extra': True}, {**msg, 'version': True},
            {**msg, 'kind': []}, {**msg, 'nonce': 'not UUID'},
            {**msg, 'nonce': '00000000-0000-0000-0000-000000000000'},
            {**msg, 'payload': []}, {**msg, 'issuedAtUtc': 'yesterday'},
            {**msg, 'signature': 'z' * 128}]:
        rejected(lambda: core.verify(bad, core.public_key(s.coordinator), s.binding, s.clock()))
    nested = {}
    for _ in range(1000):
        nested = {'nested': nested}
    rejected(lambda: core.sign(s.coordinator, s.binding, 'armed', str(uuid4()), nested, s.clock()))
    for nonce in [None, '', str(uuid4()).upper(), 'secret']:
        rejected(lambda: core.sign(s.coordinator, s.binding, 'heartbeat', nonce, {'commandSeq': 1}, s.clock()))


def test_signature_tampering_and_wrong_key_fail_without_leaking_values():
    s = Session()
    msg = s.command()
    for bad in [{**msg, 'nonce': str(uuid4())}, {**msg, 'issuedAtUtc': utc(s.clock() - 1)},
            {**msg, 'signature': '0' * 128},
            {**msg, 'payload': {**msg['payload'], 'commandSeq': 2}}]:
        rejected(lambda: core.verify(bad, core.public_key(s.coordinator), s.binding, s.clock()))
    rejected(lambda: core.verify(msg, core.public_key(s.remote), s.binding, s.clock()), 'signature_invalid')


def test_freshness_future_deadline_and_recovery_verification_are_separate():
    s = Session()
    msg = s.command()
    rejected(lambda: core.verify(msg, core.public_key(s.coordinator), s.binding, s.clock() - 1), 'stale')
    assert core.verify(msg, core.public_key(s.coordinator), s.binding, s.clock() + 30) == msg
    rejected(lambda: core.verify(msg, core.public_key(s.coordinator), s.binding, s.clock() + 31), 'stale')
    rejected(lambda: core.verify(msg, core.public_key(s.coordinator), s.binding, s.clock() + 120,
        max_age=200), 'expired')
    assert core.verify(msg, core.public_key(s.coordinator), s.binding, s.clock() + 120,
        max_age=200, allow_expired_cleanup=True) == msg
    rejected(lambda: core.validate_binding(s.binding, s.clock() + 120), 'expired')
    assert core.validate_binding(s.binding, s.clock() + 120, allow_expired_cleanup=True) == s.binding
    rejected(lambda: core.validate_binding({**s.binding, 'runAttempt': 2}, s.clock() + 120,
        allow_expired_cleanup=True))
    rejected(lambda: core.validate_binding(s.binding, s.clock(), allow_expired_cleanup=1))
    for bad in [-1, True, float('nan'), 'secret', 10 ** 1000]:
        rejected(lambda: core.verify(msg, core.public_key(s.coordinator), s.binding, s.clock(), max_age=bad))


def test_arm_persists_before_publishing_and_both_require_matching_nonce():
    events = []
    s = Session(persist=lambda record: events.append(('persist', deepcopy(record))),
        publish=lambda reply: events.append(('publish', deepcopy(reply))))
    ack = s.arm()
    assert [event for event, _ in events] == ['persist', 'publish']
    assert events[0][1]['lastReply'] == ack
    assert ack['payload']['state']['binding'] == s.binding
    assert ack['payload']['state']['commandSeq'] == 0
    rejected(lambda: s.local.accept_arm(ack, s.nonce, True), 'replay')
    rejected(lambda: s.ledger.arm(str(uuid4())), 'replay')
    other = core.LocalAdmission(s.binding, core.public_key(s.remote), lambda *args: None, s.clock)
    rejected(lambda: other.accept_arm(ack, str(uuid4()), True))


def test_delayed_arm_freshness_arm_before_and_job_checks():
    for delay, job in [(10, True), (31, True), (0, False), (0, 1)]:
        s = Session()
        ack = s.ledger.arm(s.nonce)
        s.clock.advance(delay)
        rejected(lambda: s.local.accept_arm(ack, s.nonce, job))
    s = Session()
    s.clock.advance(10)
    rejected(lambda: s.ledger.arm(s.nonce), 'expired')


def test_unarmed_commands_and_metadata_intents_never_admit():
    s = Session()
    rejected(lambda: s.ledger.handle(s.command()), 'not_armed')
    s = Session(mode='metadata-only')
    s.arm()
    ack = s.ledger.handle(s.command())
    assert ack['kind'] == 'heartbeat_ack'
    rejected(lambda: s.ledger.handle(s.command('intent', 2, action='pause', role='capacity')), 'mode_denied')
    assert s.ledger.accepted == [] and s.consumed == [] and s.ledger.pending == {}


def test_initial_preflight_and_stale_or_unchanged_goal_cannot_admit():
    s = Session()
    s.arm()
    rejected(lambda: s.ledger.handle(s.pause()), 'preflight')
    s.ledger.observe(s.projects['capacity'], 'INACTIVE')
    s.ledger.observe(s.projects['target'], 'INACTIVE')
    rejected(lambda: s.ledger.handle(s.pause()), 'preflight')
    s.preflight()
    s.clock.advance(31)
    rejected(lambda: s.ledger.handle(s.pause()), 'preflight')
    assert s.ledger.accepted == []


def test_pause_then_resume_only_after_pending_goal_observed_and_never_repeat():
    s = Session()
    s.arm()
    s.preflight()
    rejected(lambda: s.ledger.handle(s.resume(1)), 'order')
    pause = s.pause()
    ack = s.ledger.handle(pause)
    assert s.local.consume(pause, ack, True) == {'action': 'pause', 'project': s.projects['capacity']}
    s.ledger.observe(s.projects['capacity'], 'ACTIVE_HEALTHY')
    assert s.ledger.pending
    rejected(lambda: s.ledger.handle(s.resume()), 'pending')
    s.ledger.observe(s.projects['capacity'], 'INACTIVE')
    assert s.ledger.pending == {}
    resume = s.resume()
    ack = s.ledger.handle(resume)
    assert s.local.consume(resume, ack, True) == {'action': 'resume', 'project': s.projects['target']}
    s.ledger.observe(s.projects['target'], 'INACTIVE')
    assert s.ledger.pending
    s.ledger.observe(s.projects['target'], 'ACTIVE_HEALTHY')
    rejected(lambda: s.ledger.handle(s.command('intent', 3, action='pause', role='capacity')), 'order')
    assert len(s.ledger.accepted) == 2 and len(s.consumed) == 2


def test_exact_last_retry_is_cached_but_changed_duplicate_or_old_sequence_is_denied():
    s = Session()
    s.arm()
    command = s.command()
    ack = s.ledger.handle(command)
    count = len(s.records)
    assert s.ledger.handle(deepcopy(command)) == ack
    assert len(s.records) == count
    rejected(lambda: s.ledger.handle(s.command()), 'replay')
    changed = core.sign(s.coordinator, s.binding, 'finish', command['nonce'], {'commandSeq': 1}, s.clock())
    rejected(lambda: s.ledger.handle(changed), 'replay')
    s.ledger.handle(s.command(seq=2))
    rejected(lambda: s.ledger.handle(command), 'sequence')


def test_sequence_bounds_gaps_boolean_and_nonce_reuse():
    s = Session()
    s.arm()
    for seq in [0, -1, True, 2049, '1']:
        rejected(lambda: s.command(seq=seq))
    rejected(lambda: s.ledger.handle(s.command(seq=2)), 'sequence')
    # The whole finite sequence space is exercised through the public interface.
    for seq in range(1, 2049):
        s.ledger.handle(s.command(seq=seq))
    rejected(lambda: s.command(seq=2049))
    other = Session()
    other.arm()
    first = other.command()
    other.ledger.handle(first)
    repeated = core.sign(other.coordinator, other.binding, 'heartbeat', first['nonce'],
        {'commandSeq': 2}, other.clock())
    rejected(lambda: other.ledger.handle(repeated), 'replay')


def test_intent_allowlist_cannot_choose_arbitrary_action_role_or_project():
    s = Session()
    for payload in [{'action': 'pause', 'role': 'source'}, {'action': 'resume', 'role': 'capacity'},
            {'action': 'pause', 'role': 'target'}, {'action': 'delete', 'role': 'target'},
            {'action': 'pause', 'role': 'capacity', 'project': 'x' * 20}]:
        rejected(lambda: s.command('intent', **payload))
    rejected(lambda: core.sign(s.coordinator, s.binding, 'heartbeat', str(uuid4()),
        {'commandSeq': 1, 'requestNonce': str(uuid4())}, s.clock()))


def test_every_ack_carries_pending_and_accepted_history_and_signed_command_correlation():
    s = Session()
    s.arm()
    s.preflight()
    intent = s.pause()
    ack = s.ledger.handle(intent)
    payload = ack['payload']
    assert payload['replyTo'] == intent['nonce']
    assert payload['commandDigest'] == sha256(core.canonical(intent)).hexdigest()
    key = 'pause:' + s.projects['capacity']
    assert payload['state']['pendingMutations'][key] == {'action': 'pause',
        'project': s.projects['capacity'], 'goal': 'INACTIVE', 'atUtc': ack['issuedAtUtc'], 'acknowledged': False}
    heartbeat = s.command(seq=2)
    hb_ack = s.ledger.handle(heartbeat)
    assert hb_ack['payload']['state']['pendingMutations'] == s.ledger.pending
    assert hb_ack['payload']['state']['acceptedActions'] == s.ledger.accepted
    assert s.ledger.snapshot()['lastCommand'] == heartbeat
    assert s.ledger.snapshot()['lastReply'] == hb_ack


def test_finish_durably_closes_before_publication_and_allows_only_exact_finish_retry():
    s = Session()
    s.arm()
    finish = s.command('finish')
    ack = s.ledger.handle(finish)
    assert s.records[-1]['admissionClosed']
    assert s.published[-1]['payload']['state']['admissionClosed']
    assert s.ledger.admission_closed
    assert s.local.accept_reply(finish, ack, True)['admissionClosed']
    assert s.ledger.handle(finish) == ack
    rejected(lambda: s.ledger.handle(s.command(seq=2)), 'closed')
    rejected(lambda: s.local.accept_reply(finish, ack, True), 'closed')


def test_finish_preserves_pending_unknown_provider_outcomes():
    s = Session()
    s.arm()
    s.preflight()
    s.ledger.handle(s.pause())
    pending = s.ledger.pending
    ack = s.ledger.handle(s.command('finish', 2))
    assert ack['payload']['state']['pendingMutations'] == pending
    assert ack['payload']['state']['acceptedActions'] == s.ledger.accepted
    assert s.ledger.close()['pendingMutations'] == pending


def test_remote_persistence_failure_never_publishes_and_closes_admission():
    def broken(record):
        raise OSError('credential-or-path-must-not-leak')
    s = Session(persist=broken)
    error = rejected(lambda: s.ledger.arm(s.nonce), 'persist_failed')
    assert 'credential' not in str(error.value) and error.value.__cause__ is None
    assert s.ledger.admission_closed and s.published == []
    s = Session()
    s.arm()
    s.preflight()
    s.ledger._persist = broken
    count = len(s.published)
    rejected(lambda: s.ledger.handle(s.pause()), 'persist_failed')
    assert s.ledger.admission_closed and len(s.published) == count


def test_publication_failure_preserves_durable_pending_and_closes_admission():
    s = Session()
    s.arm()
    s.preflight()
    def broken(reply):
        raise OSError('mailbox response secret')
    s.ledger._publish = broken
    command = s.pause()
    rejected(lambda: s.ledger.handle(command), 'publish_failed')
    assert s.ledger.admission_closed and s.ledger.pending and len(s.ledger.accepted) == 1
    assert s.records[-1]['admissionClosed'] and s.records[-1]['pendingMutations']
    rejected(lambda: s.ledger.handle(command), 'closed')


def test_arm_publication_failure_and_double_callback_failure_are_fail_closed():
    def broken(*args):
        raise RuntimeError('private')
    s = Session(publish=broken)
    rejected(lambda: s.ledger.arm(s.nonce), 'publish_failed')
    assert s.ledger.admission_closed and s.records[-1]['admissionClosed']
    s = Session()
    s.arm()
    s.ledger._publish = broken
    calls = []
    def fail_second(record):
        calls.append(record)
        if len(calls) > 1:
            broken()
    s.ledger._persist = fail_second
    rejected(lambda: s.ledger.handle(s.command()))
    assert s.ledger.admission_closed
    # Durability itself can consume the arm/ack freshness budget.
    for phase, delay in [('arm', 10), ('command', 31), ('command', 120)]:
        s = Session()
        if phase == 'command':
            s.arm()
        command = s.command()
        first = True
        def slow(record):
            nonlocal first
            if first:
                first = False
                s.clock.advance(delay)
        s.ledger._persist = slow
        count = len(s.published)
        rejected(lambda: s.ledger.arm(s.nonce) if phase == 'arm' else s.ledger.handle(command))
        assert s.ledger.admission_closed and len(s.published) == count


def test_local_durable_consumption_precedes_dispatch_and_is_never_repeated():
    s = Session()
    s.arm()
    s.preflight()
    intent = s.pause()
    ack = s.ledger.handle(intent)
    assert s.consumed == []
    dispatch = s.local.consume(intent, ack, True)
    assert len(s.consumed) == 1 and dispatch['action'] == 'pause'
    rejected(lambda: s.local.consume(intent, ack, True), 'replay')
    assert len(s.consumed) == 1
    # Restart protection is the callback's durable exclusive record, not memory.
    restarted = core.LocalAdmission(s.binding, core.public_key(s.remote),
        lambda *args: (_ for _ in ()).throw(FileExistsError('consumed')), s.clock)
    restarted.accept_arm(s.records[0]['lastReply'], s.nonce, True)
    rejected(lambda: restarted.consume(intent, ack, True), 'consume_failed')


def test_local_consume_failure_or_time_spent_persisting_cannot_dispatch():
    for failure in ('io', 'deadline', 'stale'):
        s = Session()
        s.arm()
        s.preflight()
        intent = s.pause()
        ack = s.ledger.handle(intent)
        def consume(*args):
            if failure == 'io':
                raise OSError('private-path')
            s.clock.advance(120 if failure == 'deadline' else 31)
        s.local._persist = consume
        rejected(lambda: s.local.consume(intent, ack, True))
        rejected(lambda: s.local.consume(intent, ack, True), 'closed')


def test_local_job_must_be_current_for_each_command_not_just_arm():
    s = Session()
    s.arm()
    command = s.command()
    ack = s.ledger.handle(command)
    rejected(lambda: s.local.accept_reply(command, ack, False), 'closed')
    rejected(lambda: s.local.accept_reply(command, ack, True), 'closed')


def test_local_ack_requires_exact_nonce_digest_sequence_kind_key_and_binding():
    s = Session()
    s.arm()
    command = s.command()
    ack = s.ledger.handle(command)
    for field, value in [('replyTo', str(uuid4())), ('commandDigest', 'a' * 64), ('commandSeq', 2)]:
        payload = {**ack['payload'], field: value}
        wrong = core.sign(s.remote, s.binding, 'heartbeat_ack', command['nonce'], payload, s.clock())
        rejected(lambda: s.local.accept_reply(command, wrong, True))
    wrong = core.sign(s.remote, s.binding, 'finish_ack', command['nonce'], ack['payload'], s.clock())
    rejected(lambda: s.local.accept_reply(command, wrong, True))
    wrong = core.sign(s.coordinator, s.binding, 'heartbeat_ack', command['nonce'], ack['payload'], s.clock())
    rejected(lambda: s.local.accept_reply(command, wrong, True), 'signature_invalid')
    s.local.accept_reply(command, ack, True)
    rejected(lambda: s.local.accept_reply(command, ack, True), 'replay')


def test_local_cannot_use_intent_ack_as_heartbeat_or_admit_fabricated_pending_state():
    s = Session()
    s.arm()
    s.preflight()
    intent = s.pause()
    ack = s.ledger.handle(intent)
    rejected(lambda: s.local.accept_reply(intent, ack, True))
    payload = deepcopy(ack['payload'])
    payload['state']['pendingMutations'] = {}
    bad = core.sign(s.remote, s.binding, 'intent_ack', intent['nonce'], payload, s.clock())
    rejected(lambda: s.local.consume(intent, bad, True))
    assert s.consumed == []


def test_deadline_and_clock_steps_close_admission_preserving_pending():
    for change in ('deadline', 'backwards', 'forward', 'monotonic'):
        s = Session()
        s.arm()
        s.preflight()
        s.ledger.handle(s.pause())
        pending = s.ledger.pending
        command = s.command(seq=2)
        if change == 'deadline':
            s.clock.advance(120)
        elif change == 'backwards':
            s.clock.wall -= 1
        elif change == 'forward':
            s.clock.wall += 5
        else:
            s.clock.mono -= 1
        rejected(lambda: s.ledger.handle(command))
        assert s.ledger.admission_closed and s.ledger.snapshot()['pendingMutations'] == pending
        assert s.records[-1]['admissionClosed']


def test_detached_snapshots_properties_callbacks_and_inputs_cannot_mutate_state():
    s = Session()
    s.arm()
    s.preflight()
    intent = s.pause()
    ack = s.ledger.handle(intent)
    snapshot = s.ledger.snapshot()
    s.ledger.binding['cleanupAtUtc'] = utc(s.clock() + 1000)
    s.local.binding['mode'] = 'metadata-only'
    s.binding['jobId'] += 1
    assert s.ledger.binding['jobId'] != s.binding['jobId']
    assert s.local.binding['mode'] == 'cleanup'
    snapshot['pendingMutations'].clear()
    s.ledger.pending.clear()
    s.ledger.accepted.clear()
    ack['payload']['state']['pendingMutations'].clear()
    intent['payload']['action'] = 'resume'
    s.records[-1]['pendingMutations'].clear()
    assert s.ledger.pending and len(s.ledger.accepted) == 1
    assert s.ledger.snapshot()['lastCommand']['payload']['action'] == 'pause'


def test_unknown_history_state_is_never_accepted_as_admission_checkpoint():
    s = Session()
    arm = s.ledger.arm(s.nonce)
    payload = deepcopy(arm['payload'])
    payload['state']['pendingHistoryKnown'] = False
    bad = core.sign(s.remote, s.binding, 'armed', s.nonce, payload, s.clock())
    rejected(lambda: s.local.accept_arm(bad, s.nonce, True))
    assert s.local.accept_arm(arm, s.nonce, True)['commandSeq'] == 0


def test_project_mapping_and_observations_are_strict_and_never_touch_source():
    s = Session()
    for projects in [{}, {'capacity': 'b' * 20, 'target': 'b' * 20},
            {**s.projects, 'source': 'a' * 20}, {'capacity': None, 'target': 'c' * 20}]:
        rejected(lambda: core.RemoteLedger(s.binding, s.remote, projects, list.append, list.append, s.clock))
    for ref, status in [('a' * 20, 'INACTIVE'), (s.projects['target'], 'secret'), (None, []),
            (s.projects['target'], {})]:
        rejected(lambda: s.ledger.observe(ref, status))
