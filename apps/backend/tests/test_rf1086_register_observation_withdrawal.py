"""Pure public withdrawal integrity/history; no repository or admission proof."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from uuid import UUID

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId
from test_rf1086_register_observation import ACTOR, COMPANY, NOW, YEAR, basis, prepare


WITHDRAWN_AT = NOW + timedelta(seconds=2, microseconds=123456)
WITHDRAWAL_ID = rf.Rf1086RegisterObservationWithdrawalId(str(UUID(int=20)))


def command_for(observation=None, **changes):
    observation = observation or prepare()
    command = rf.WithdrawRf1086RegisterObservation(
        COMPANY, ACTOR, YEAR, observation.observation_id, observation.version,
        observation.fact_sha256, "  Feil original – behold begrunnelsen.\n",
    )
    return replace(command, **changes)


def withdrawal(observation=None, **changes):
    observation = observation or prepare()
    args = {"observation": observation, "withdrawal_id": WITHDRAWAL_ID, "withdrawn_at": WITHDRAWN_AT}
    args.update(changes)
    return rf.prepare_rf1086_register_observation_withdrawal(command_for(observation), **args)


def correction(previous, *, identity=9, confirmed_at=None):
    _, context = basis()
    command = replace(previous.command, supersedes_observation_id=previous.observation_id,
        supersedes_observation_sha256=previous.fact_sha256, correction_reason="Corrected original")
    return prepare(command, context, previous=previous,
        observation_id=rf.Rf1086RegisterObservationId(str(UUID(int=identity))),
        confirmed_at=confirmed_at or previous.confirmed_at + timedelta(seconds=1))


def lifecycle(observations, withdrawals=(), **scope):
    return rf.derive_rf1086_register_observation_lifecycle(
        company_id=scope.get("company_id", COMPANY), income_year=scope.get("income_year", YEAR),
        observations=observations, withdrawals=withdrawals,
    )


def test_exact_reason_actor_target_and_server_receipt_are_immutable():
    receipt = withdrawal()
    assert receipt.command == command_for()
    assert receipt.command.reason == "  Feil original – behold begrunnelsen.\n"
    assert receipt.withdrawn_at == WITHDRAWN_AT
    rf.assert_rf1086_register_observation_withdrawal_integrity(receipt)
    rf.assert_rf1086_register_observation_withdrawal_replay(receipt, command_for())
    for value, field in ((receipt, "withdrawn_at"), (receipt.command, "reason"), (receipt.withdrawal_id, "value")):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, None)


def test_withdrawing_actor_is_not_required_to_be_the_historical_capturing_actor():
    command = command_for(actor_id=ActorId(ActorKind.USER, UserId(str(UUID(int=99)))))
    receipt = rf.prepare_rf1086_register_observation_withdrawal(command, observation=prepare(),
        withdrawal_id=WITHDRAWAL_ID, withdrawn_at=WITHDRAWN_AT)
    assert receipt.command.actor_id != prepare().command.actor_id
    assert receipt.request_sha256 != withdrawal().request_sha256


@pytest.mark.parametrize("changes", [
    {"company_id": str(COMPANY)}, {"income_year": 2025}, {"income_year": IncomeYear(2025.0)},
    {"actor_id": "caller"}, {"actor_id": ActorId("USER", ACTOR.subject)},
    {"actor_id": ActorId(ActorKind.SYSTEM, ACTOR.subject)},
    {"actor_id": ActorId(ActorKind.SUPPORT_OPERATOR, ACTOR.subject)},
    {"actor_id": ActorId(ActorKind.USER, ACTOR.subject.value)},
    {"observation_id": str(UUID(int=3))}, {"observation_version": True},
    {"observation_version": 1.0}, {"observation_version": 0}, {"observation_version": -1},
    {"observation_fact_sha256": "A" * 64}, {"observation_fact_sha256": "a" * 63},
    {"reason": ""}, {"reason": " \t\n"}, {"reason": "x" * 1001},
    {"reason": True}, {"reason": ["editable"]}, {"reason": "bad\x00text"}, {"reason": "bad\ud800text"},
])
def test_command_rejects_loose_primitives_and_unstorable_reason(changes):
    with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError):
        command_for(**changes)


@pytest.mark.parametrize("value", [True, 1, "invalid", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",
                                   "00000000000000000000000000000020"])
def test_withdrawal_identity_requires_canonical_uuid(value):
    with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError, match="identity_invalid"):
        rf.Rf1086RegisterObservationWithdrawalId(value)


def test_reason_bound_counts_characters_preserves_unicode_and_never_trims():
    command = command_for(reason="😀" * 1000)
    receipt = rf.prepare_rf1086_register_observation_withdrawal(command, observation=prepare(),
        withdrawal_id=WITHDRAWAL_ID, withdrawn_at=WITHDRAWN_AT)
    assert rf.parse_rf1086_register_observation_withdrawal(
        rf.serialize_rf1086_register_observation_withdrawal(receipt)) == receipt
    digest = rf.rf1086_register_observation_withdrawal_request_digest
    assert digest(command_for(reason="å")) != digest(command_for(reason="a\u030a"))
    assert digest(command_for(reason="original")) != digest(command_for(reason=" original "))
    with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError):
        command_for(reason="😀" * 1001)


@pytest.mark.parametrize("changes", [
    {"company_id": CompanyId(str(UUID(int=99)))}, {"income_year": IncomeYear(2024)},
    {"observation_id": rf.Rf1086RegisterObservationId(str(UUID(int=99)))},
    {"observation_version": 2}, {"observation_fact_sha256": "0" * 64},
])
def test_target_binding_requires_exact_company_year_id_version_and_hash(changes):
    with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError, match="target_mismatch"):
        rf.prepare_rf1086_register_observation_withdrawal(command_for(**changes), observation=prepare(),
            withdrawal_id=WITHDRAWAL_ID, withdrawn_at=WITHDRAWN_AT)


def test_target_integrity_is_checked_not_only_the_callers_claimed_hash():
    target = replace(prepare(), fact_sha256="0" * 64)
    with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError, match="target_integrity_invalid"):
        withdrawal(target)


@pytest.mark.parametrize("changes", [
    {"company_id": CompanyId(str(UUID(int=99)))}, {"income_year": IncomeYear(2024)},
    {"actor_id": ActorId(ActorKind.USER, UserId(str(UUID(int=99))))},
    {"observation_id": rf.Rf1086RegisterObservationId(str(UUID(int=99)))},
    {"observation_version": 2}, {"observation_fact_sha256": "0" * 64},
    {"reason": "Feil original – behold begrunnelsen."},
])
def test_exact_replay_rejects_every_changed_request_commitment(changes):
    receipt = withdrawal()
    changed = command_for(**changes)
    assert rf.rf1086_register_observation_withdrawal_request_digest(changed) != receipt.request_sha256
    with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError, match="replay_conflict"):
        rf.assert_rf1086_register_observation_withdrawal_replay(receipt, changed)


def test_time_normalizes_offsets_to_utc_without_losing_microseconds():
    receipt = withdrawal()
    offset = WITHDRAWN_AT.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert withdrawal(withdrawn_at=offset) == receipt
    assert receipt.withdrawn_at.tzinfo is timezone.utc
    encoded = rf.serialize_rf1086_register_observation_withdrawal(receipt)
    assert '"withdrawn_at":"2025-07-01T12:00:02.123456+00:00"' in encoded
    assert withdrawal(withdrawn_at=WITHDRAWN_AT + timedelta(microseconds=1)).withdrawal_sha256 != receipt.withdrawal_sha256
    assert withdrawal(withdrawn_at=NOW).withdrawn_at == NOW


@pytest.mark.parametrize("value", [datetime(2025, 7, 1), "2025-07-01", None, NOW - timedelta(microseconds=1)])
def test_withdrawal_cannot_have_naive_or_pre_capture_time(value):
    with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError):
        withdrawal(withdrawn_at=value)


@pytest.mark.parametrize("changes", [
    {"withdrawal_id": rf.Rf1086RegisterObservationWithdrawalId(str(UUID(int=99)))},
    {"withdrawn_at": WITHDRAWN_AT + timedelta(microseconds=1)},
    {"request_sha256": "0" * 64}, {"withdrawal_sha256": "0" * 64},
    {"command": command_for(reason="Another retained reason")},
])
def test_retained_receipt_tampering_is_not_accepted(changes):
    corrupted = replace(withdrawal(), **changes)
    with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError):
        rf.serialize_rf1086_register_observation_withdrawal(corrupted)


def test_codec_is_closed_canonical_and_round_trips_original_receipt():
    receipt = withdrawal()
    encoded = rf.serialize_rf1086_register_observation_withdrawal(receipt)
    assert rf.parse_rf1086_register_observation_withdrawal(encoded) == receipt
    assert rf.serialize_rf1086_register_observation_withdrawal(
        rf.parse_rf1086_register_observation_withdrawal(encoded)) == encoded
    assert json.loads(encoded)["codec"] == "rf1086-register-observation-withdrawal-v1"


def test_v1_request_and_receipt_commitments_are_frozen():
    receipt = withdrawal()
    assert receipt.request_sha256 == "373d824dd34b26d129f8069b7eff467e34f41a509807e778319bbfcfb2609b64"
    assert receipt.withdrawal_sha256 == "5f5ea525f826f30589eca9505320d1749596ba14920b8ed96ffd34f83c237839"
    encoded = rf.serialize_rf1086_register_observation_withdrawal(receipt)
    assert sha256(encoded.encode("utf-8")).hexdigest() == "bf10599e324d6c32ea177cc213827e16f63e8ac7325eec5a10810d0b27d48d94"


@pytest.mark.parametrize("mutation", [
    "codec", "top_field", "receipt_field", "command_field", "actor_field", "missing", "loose_year",
    "loose_version", "uppercase_company", "uppercase_actor", "system_actor", "reason", "hash",
    "time_offset", "time_precision", "time_naive", "object_type",
])
def test_codec_rejects_unknown_shapes_coercion_and_altered_commitments(mutation):
    raw = json.loads(rf.serialize_rf1086_register_observation_withdrawal(withdrawal()))
    receipt, command = raw["withdrawal"], raw["withdrawal"]["command"]
    if mutation == "codec": raw["codec"] = "rf1086-archive-v4"
    if mutation == "top_field": raw["extra"] = True
    if mutation == "receipt_field": receipt["current"] = True
    if mutation == "command_field": command["accepted_owner"] = True
    if mutation == "actor_field": command["actor_id"]["verified"] = True
    if mutation == "missing": del command["reason"]
    if mutation == "loose_year": command["income_year"] = 2025.0
    if mutation == "loose_version": command["observation_version"] = True
    if mutation == "uppercase_company": command["company_id"] = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
    if mutation == "uppercase_actor": command["actor_id"]["subject"] = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
    if mutation == "system_actor": command["actor_id"]["kind"] = "SYSTEM"
    if mutation == "reason": command["reason"] = command["reason"].strip()
    if mutation == "hash": receipt["withdrawal_sha256"] = "0" * 64
    if mutation == "time_offset": receipt["withdrawn_at"] = "2025-07-01T14:00:02.123456+02:00"
    if mutation == "time_precision": receipt["withdrawn_at"] = "2025-07-01T12:00:02.1234567+00:00"
    if mutation == "time_naive": receipt["withdrawn_at"] = "2025-07-01T12:00:02.123456"
    if mutation == "object_type": raw["withdrawal"] = {"record": "os.system", "fields": receipt}
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError, match="storage_invalid"):
        rf.parse_rf1086_register_observation_withdrawal(encoded)


@pytest.mark.parametrize("mutation", ["duplicate_top", "duplicate_nested", "whitespace", "nan", "too_large", "not_text"])
def test_codec_rejects_ambiguous_or_unbounded_input(mutation):
    encoded = rf.serialize_rf1086_register_observation_withdrawal(withdrawal())
    if mutation == "duplicate_top": encoded = encoded.replace('{"codec":', '{"codec":"ignored","codec":', 1)
    if mutation == "duplicate_nested": encoded = encoded.replace('"observation_version":1', '"observation_version":2,"observation_version":1')
    if mutation == "whitespace": encoded += "\n"
    if mutation == "nan": encoded = encoded.replace('"observation_version":1', '"observation_version":NaN')
    if mutation == "too_large": encoded = " " * 16385 + encoded
    if mutation == "not_text": encoded = encoded.encode()
    with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError, match="storage_invalid") as error:
        rf.parse_rf1086_register_observation_withdrawal(encoded)
    assert str(error.value) == "rf1086_register_withdrawal_storage_invalid"


def test_withdrawn_head_preserves_every_superseded_ancestor_and_new_root_is_possible():
    first = prepare()
    second = correction(first)
    third = correction(second, identity=10)
    receipt = withdrawal(third, withdrawn_at=WITHDRAWN_AT + timedelta(seconds=1))
    independent = prepare(observation_id=rf.Rf1086RegisterObservationId(str(UUID(int=11))),
                          confirmed_at=WITHDRAWN_AT + timedelta(seconds=2))
    result = lifecycle((third, independent, first, second), (receipt,))
    assert [(row.observation.observation_id, row.status, row.superseded_by) for row in result] == [
        (first.observation_id, "superseded", second.observation_id),
        (second.observation_id, "superseded", third.observation_id),
        (third.observation_id, "withdrawn", None),
        (independent.observation_id, "active", None),
    ]
    assert result[2].withdrawal is receipt
    assert all(row.withdrawal is None for row in (result[0], result[1], result[3]))
    assert lifecycle(tuple(reversed((third, independent, first, second))), (receipt,)) == result
    rf.assert_rf1086_register_observation_withdrawal_replay(receipt, command_for(third))
    with pytest.raises(FrozenInstanceError):
        result[2].status = "active"


def test_no_history_and_several_independent_roots_are_supported_without_claiming_completeness():
    assert lifecycle(()) == ()
    other = prepare(observation_id=rf.Rf1086RegisterObservationId(str(UUID(int=9))))
    assert [row.status for row in lifecycle((prepare(), other))] == ["active", "active"]
    # A pure function cannot detect omitted rows. The repository must establish
    # complete history under a guard; this is deliberately not a live grant.
    assert lifecycle((prepare(),))[0].status == "active"


@pytest.mark.parametrize("after", [False, True])
def test_withdrawn_observation_cannot_also_be_an_ancestor_even_if_correction_precedes_withdrawal(after):
    first = prepare()
    second = correction(first, confirmed_at=NOW + timedelta(seconds=3 if after else 1))
    # Pure target preparation intentionally cannot see a successor. The full
    # supplied-history check refuses this contradiction in either ordering.
    with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError, match="withdrawn_ancestor"):
        lifecycle((first, second), (withdrawal(first),))


@pytest.mark.parametrize("mutation", ["duplicate", "orphan", "fork", "foreign_scope", "bad_hash", "wrong_parent"])
def test_lifecycle_refuses_inconsistent_observation_history(mutation):
    first, observations = prepare(), ()
    second = correction(first)
    if mutation == "duplicate": observations = (first, first)
    if mutation == "orphan": observations = (second,)
    if mutation == "fork": observations = (first, second, correction(first, identity=10))
    if mutation == "foreign_scope":
        with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError, match="scope_mismatch"):
            lifecycle((first,), company_id=CompanyId(str(UUID(int=99))))
        return
    if mutation == "bad_hash": observations = (first, replace(second, fact_sha256="0" * 64))
    if mutation == "wrong_parent":
        alternate = prepare(confirmed_at=NOW - timedelta(seconds=1))
        observations = (first, correction(alternate))
    with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError):
        lifecycle(observations)


@pytest.mark.parametrize("mutation", ["duplicate_row", "duplicate_target", "duplicate_id", "orphan", "tampered_time"])
def test_lifecycle_refuses_duplicate_or_unbound_withdrawals(mutation):
    first = prepare()
    receipt = withdrawal(first)
    observations, receipts = (first,), (receipt,)
    if mutation == "duplicate_row": receipts = (receipt, receipt)
    if mutation == "duplicate_target": receipts += (withdrawal(first, withdrawal_id=rf.Rf1086RegisterObservationWithdrawalId(str(UUID(int=21)))),)
    if mutation == "duplicate_id":
        other = prepare(observation_id=rf.Rf1086RegisterObservationId(str(UUID(int=9))))
        observations += (other,)
        receipts += (withdrawal(other),)
    if mutation == "orphan": observations = ()
    if mutation == "tampered_time": receipts = (replace(receipt, withdrawn_at=NOW - timedelta(seconds=1)),)
    with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError):
        lifecycle(observations, receipts)


def test_lifecycle_requires_explicit_immutable_collections_and_valid_scope():
    for observations, receipts in (([prepare()], ()), ((prepare(),), [withdrawal()])):
        with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError, match="history_invalid"):
            lifecycle(observations, receipts)
    with pytest.raises(rf.Rf1086RegisterObservationWithdrawalError, match="scope_invalid"):
        lifecycle((), income_year=IncomeYear(2025.0))
