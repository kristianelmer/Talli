"""Pure withdrawal identity and retained lineage; no IO or live authority."""

from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from uuid import UUID

from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId

from . import public as rf


_CODEC = "rf1086-register-observation-withdrawal-v1"
_REQUEST = "rf1086-register-observation-withdrawal-request-v1"
_COMMAND_FIELDS = {"company_id", "actor_id", "income_year", "observation_id",
                   "observation_version", "observation_fact_sha256", "reason"}
_RECEIPT_FIELDS = {"withdrawal_id", "command", "withdrawn_at", "request_sha256", "withdrawal_sha256"}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise rf.Rf1086RegisterObservationWithdrawalError("rf1086_register_withdrawal_" + code)


def validate_identity(value: str) -> None:
    try:
        valid = type(value) is str and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        valid = False
    _require(valid, "identity_invalid")


def _sha(value: str) -> None:
    _require(type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None, "digest_invalid")


def _scope(company_id: CompanyId, income_year: IncomeYear) -> None:
    _require(type(company_id) is CompanyId, "scope_invalid")
    validate_identity(company_id.value)
    _require(type(income_year) is IncomeYear and type(income_year.value) is int
             and 2000 <= income_year.value <= 2100, "scope_invalid")


def validate_command(command: rf.WithdrawRf1086RegisterObservation) -> None:
    _require(type(command) is rf.WithdrawRf1086RegisterObservation, "command_invalid")
    _scope(command.company_id, command.income_year)
    actor = command.actor_id
    _require(type(actor) is ActorId and type(actor.kind) is ActorKind
             and actor.kind is ActorKind.USER and type(actor.subject) is UserId, "actor_invalid")
    validate_identity(actor.subject.value)
    _require(type(command.observation_id) is rf.Rf1086RegisterObservationId, "target_invalid")
    validate_identity(command.observation_id.value)
    _require(type(command.observation_version) is int and command.observation_version > 0, "version_invalid")
    _sha(command.observation_fact_sha256)
    reason = command.reason
    _require(type(reason) is str and bool(reason.strip()) and len(reason) <= 1000
             and "\x00" not in reason, "reason_invalid")
    try:
        reason.encode("utf-8", errors="strict")
    except UnicodeError:
        _require(False, "reason_invalid")


def _instant(value: datetime) -> datetime:
    _require(type(value) is datetime, "time_invalid")
    try:
        _require(value.tzinfo is not None and value.utcoffset() is not None, "time_invalid")
        return value.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        raise rf.Rf1086RegisterObservationWithdrawalError("rf1086_register_withdrawal_time_invalid") from None


def _command_payload(command: rf.WithdrawRf1086RegisterObservation) -> dict:
    validate_command(command)
    return {
        "company_id": command.company_id.value,
        "actor_id": {"kind": command.actor_id.kind.value, "subject": command.actor_id.subject.value},
        "income_year": command.income_year.value,
        "observation_id": command.observation_id.value,
        "observation_version": command.observation_version,
        "observation_fact_sha256": command.observation_fact_sha256,
        "reason": command.reason,
    }


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: object) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def request_digest(command: rf.WithdrawRf1086RegisterObservation) -> str:
    return _digest([_REQUEST, _command_payload(command)])


def _receipt_digest(withdrawal_id, command, withdrawn_at, request_sha256):
    return _digest([_CODEC, withdrawal_id.value, _command_payload(command),
                    _instant(withdrawn_at).isoformat(timespec="microseconds"), request_sha256])


def _observation(observation: rf.Rf1086RegisterObservationSnapshot) -> None:
    _require(type(observation) is rf.Rf1086RegisterObservationSnapshot
             and type(observation.observation_id) is rf.Rf1086RegisterObservationId
             and type(observation.command) is rf.RecordRf1086RegisterObservation, "target_invalid")
    _scope(observation.command.company_id, observation.command.income_year)
    try:
        rf.assert_rf1086_register_observation_integrity(observation)
    except (ValueError, TypeError, AttributeError, ArithmeticError):
        raise rf.Rf1086RegisterObservationWithdrawalError("rf1086_register_withdrawal_target_integrity_invalid") from None


def _target(command, observation) -> None:
    validate_command(command)
    _observation(observation)
    _require((command.company_id, command.income_year, command.observation_id,
              command.observation_version, command.observation_fact_sha256)
             == (observation.command.company_id, observation.command.income_year,
                 observation.observation_id, observation.version, observation.fact_sha256), "target_mismatch")
    # The withdrawing owner may differ from the historical capturing actor.


def prepare(command, *, observation, withdrawal_id, withdrawn_at):
    _target(command, observation)
    _require(type(withdrawal_id) is rf.Rf1086RegisterObservationWithdrawalId, "identity_invalid")
    validate_identity(withdrawal_id.value)
    withdrawn_at = _instant(withdrawn_at)
    _require(withdrawn_at >= _instant(observation.confirmed_at), "predates_capture")
    request_sha256 = request_digest(command)
    return rf.Rf1086RegisterObservationWithdrawal(withdrawal_id, command, withdrawn_at, request_sha256,
        _receipt_digest(withdrawal_id, command, withdrawn_at, request_sha256))


def assert_integrity(withdrawal: rf.Rf1086RegisterObservationWithdrawal) -> None:
    _require(type(withdrawal) is rf.Rf1086RegisterObservationWithdrawal
             and type(withdrawal.withdrawal_id) is rf.Rf1086RegisterObservationWithdrawalId, "receipt_invalid")
    validate_identity(withdrawal.withdrawal_id.value)
    _sha(withdrawal.request_sha256)
    _sha(withdrawal.withdrawal_sha256)
    _require(withdrawal.request_sha256 == request_digest(withdrawal.command)
             and withdrawal.withdrawal_sha256 == _receipt_digest(withdrawal.withdrawal_id,
                 withdrawal.command, withdrawal.withdrawn_at, withdrawal.request_sha256), "integrity_mismatch")


def assert_replay(withdrawal, command) -> None:
    assert_integrity(withdrawal)
    _require(request_digest(command) == withdrawal.request_sha256
             and command == withdrawal.command, "replay_conflict")


def derive_lifecycle(*, company_id, income_year, observations, withdrawals):
    _scope(company_id, income_year)
    _require(type(observations) is tuple and type(withdrawals) is tuple, "history_invalid")
    indexed = {}
    for observation in observations:
        _observation(observation)
        _require((observation.command.company_id, observation.command.income_year)
                 == (company_id, income_year), "scope_mismatch")
        _require(observation.observation_id not in indexed, "observation_duplicate")
        indexed[observation.observation_id] = observation

    # Build immutable supersession first. Filtering withdrawals before this step
    # would incorrectly make an ancestor of a withdrawn head active again.
    successors = {}
    for observation in observations:
        command = observation.command
        predecessor = command.supersedes_observation_id
        if predecessor is None:
            continue
        _require(predecessor in indexed, "predecessor_missing")
        _require(predecessor not in successors, "successor_duplicate")
        previous = indexed[predecessor]
        _require(command.supersedes_observation_sha256 == previous.fact_sha256
                 and observation.version == previous.version + 1
                 and (command.event_kind, command.effective_at)
                 == (previous.command.event_kind, previous.command.effective_at), "lineage_mismatch")
        _require(_instant(observation.confirmed_at) > _instant(previous.confirmed_at), "lineage_time_invalid")
        successors[predecessor] = observation.observation_id

    withdrawn = {}
    withdrawal_ids = set()
    for withdrawal in withdrawals:
        assert_integrity(withdrawal)
        identifier = withdrawal.command.observation_id
        _require(identifier in indexed, "target_missing")
        _target(withdrawal.command, indexed[identifier])
        _require(withdrawal.withdrawn_at >= _instant(indexed[identifier].confirmed_at), "predates_capture")
        _require(withdrawal.withdrawal_id not in withdrawal_ids and identifier not in withdrawn,
                 "withdrawal_duplicate")
        _require(identifier not in successors, "withdrawn_ancestor")
        withdrawn[identifier] = withdrawal
        withdrawal_ids.add(withdrawal.withdrawal_id)

    return tuple(rf.Rf1086RegisterObservationLifecycle(
        observation=observation,
        status="superseded" if identifier in successors else "withdrawn" if identifier in withdrawn else "active",
        superseded_by=successors.get(identifier), withdrawal=withdrawn.get(identifier),
    ) for identifier, observation in sorted(indexed.items(), key=lambda item: item[0].value))


def serialize(withdrawal: rf.Rf1086RegisterObservationWithdrawal) -> str:
    assert_integrity(withdrawal)
    return _json({"codec": _CODEC, "withdrawal": {
        "withdrawal_id": withdrawal.withdrawal_id.value,
        "command": _command_payload(withdrawal.command),
        "withdrawn_at": _instant(withdrawal.withdrawn_at).isoformat(timespec="microseconds"),
        "request_sha256": withdrawal.request_sha256,
        "withdrawal_sha256": withdrawal.withdrawal_sha256,
    }})


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _keys(value, expected):
    if type(value) is not dict or set(value) != expected:
        raise ValueError()


def _invalid_constant(value):
    raise ValueError()


def parse(value: str) -> rf.Rf1086RegisterObservationWithdrawal:
    try:
        if type(value) is not str or len(value.encode("utf-8")) > 16384:
            raise ValueError()
        raw = json.loads(value, object_pairs_hook=_unique, parse_constant=_invalid_constant)
        _keys(raw, {"codec", "withdrawal"})
        if raw["codec"] != _CODEC:
            raise ValueError()
        receipt = raw["withdrawal"]
        _keys(receipt, _RECEIPT_FIELDS)
        command = receipt["command"]
        _keys(command, _COMMAND_FIELDS)
        _keys(command["actor_id"], {"kind", "subject"})
        if command["actor_id"]["kind"] != "USER" or type(command["income_year"]) is not int:
            raise ValueError()
        result = rf.Rf1086RegisterObservationWithdrawal(
            rf.Rf1086RegisterObservationWithdrawalId(receipt["withdrawal_id"]),
            rf.WithdrawRf1086RegisterObservation(
                CompanyId(command["company_id"]),
                ActorId(ActorKind.USER, UserId(command["actor_id"]["subject"])),
                IncomeYear(command["income_year"]),
                rf.Rf1086RegisterObservationId(command["observation_id"]),
                command["observation_version"], command["observation_fact_sha256"], command["reason"],
            ), datetime.fromisoformat(receipt["withdrawn_at"]),
            receipt["request_sha256"], receipt["withdrawal_sha256"],
        )
        if serialize(result) != value:
            raise ValueError()
        return result
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
        raise rf.Rf1086RegisterObservationWithdrawalError("rf1086_register_withdrawal_storage_invalid") from None
