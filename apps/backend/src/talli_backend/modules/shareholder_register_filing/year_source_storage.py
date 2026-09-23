"""Versioned, closed RF storage codec. No executable types or binary float loss."""
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import json

from . import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId


_RECORDS = {kind.__name__: kind for kind in (
    ActorId, CompanyId, IncomeYear, UserId, rf.Rf1086YearSourceId,
    rf.Rf1086RegisterObservationId, rf.Rf1086RegisterHolding, rf.Rf1086RegisteredShareState,
    rf.Rf1086RegisterDocumentEvidence, rf.RecordRf1086RegisterObservation, rf.Rf1086RegisterObservationSnapshot,
    rf.Rf1086Company, rf.Rf1086ShareSnapshot, rf.Rf1086Shareholder,
    rf.Rf1086ShareholderSnapshot, rf.Rf1086FormationAllocation, rf.Rf1086FormationEvent,
    rf.Rf1086CashIssueEvent, rf.Rf1086NominalIncreaseAllocation, rf.Rf1086CashNominalIncreaseEvent,
    rf.Rf1086LossCoveringReductionEvent, rf.Rf1086ShareSaleEvent, rf.Rf1086DividendAllocation,
    rf.Rf1086DividendEvent, rf.Rf1086Case, rf.Rf1086PaidInSourceFacts,
    rf.Rf1086YearDocumentEvidence, rf.Rf1086YearEventEvidence, rf.Rf1086YearGovernanceReceipt,
    rf.RecordRf1086YearSource, rf.Rf1086YearSourceFreshness, rf.Rf1086YearSourceSnapshot,
)}
_ENUMS = {kind.__name__: kind for kind in (ActorKind, rf.Rf1086ShareholderKind)}


def _encode(value):
    if isinstance(value, Enum):
        return {"enum": type(value).__name__, "value": value.value}
    if value is None or type(value) in (bool, str, int):
        return value
    if isinstance(value, (Decimal, float)):
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError()
        return {"decimal": format(number, "f")}
    if isinstance(value, datetime):
        return {"datetime": value.isoformat()}
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if is_dataclass(value) and _RECORDS.get(type(value).__name__) is type(value):
        return {"record": type(value).__name__, "fields": {
            field.name: _encode(getattr(value, field.name)) for field in fields(value)}}
    raise ValueError()


def _decode(value):
    if value is None or type(value) in (bool, str, int):
        return value
    if type(value) is list:
        return tuple(_decode(item) for item in value)
    if type(value) is not dict:
        raise ValueError()
    if set(value) == {"decimal"} and type(value["decimal"]) is str:
        number = Decimal(value["decimal"])
        if not number.is_finite():
            raise ValueError()
        return number
    if set(value) == {"datetime"} and type(value["datetime"]) is str:
        return datetime.fromisoformat(value["datetime"])
    if set(value) == {"enum", "value"} and value["enum"] in _ENUMS:
        return _ENUMS[value["enum"]](value["value"])
    if set(value) == {"record", "fields"} and value["record"] in _RECORDS:
        kind = _RECORDS[value["record"]]
        if type(value["fields"]) is not dict or set(value["fields"]) != {field.name for field in fields(kind)}:
            raise ValueError()
        return kind(**{name: _decode(item) for name, item in value["fields"].items()})
    raise ValueError()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def serialize(snapshot):
    rf.assert_rf1086_year_source_integrity(snapshot)
    try:
        return json.dumps({"codec": "rf1086-year-source-v1", "snapshot": _encode(snapshot)},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise rf.Rf1086YearSourceError("rf1086_source_storage_invalid") from None


def parse(value):
    try:
        raw = json.loads(value, object_pairs_hook=_unique)
        if set(raw) != {"codec", "snapshot"} or raw["codec"] != "rf1086-year-source-v1":
            raise ValueError()
        result = _decode(raw["snapshot"])
        rf.assert_rf1086_year_source_integrity(result)
        return result
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, ArithmeticError):
        raise rf.Rf1086YearSourceError("rf1086_source_storage_invalid") from None


def serialize_observation(snapshot):
    rf.assert_rf1086_register_observation_integrity(snapshot)
    try:
        return json.dumps({"codec": "rf1086-register-observation-v1", "snapshot": _encode(snapshot)},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, AttributeError, RecursionError):
        raise rf.Rf1086RegisterObservationError("rf1086_register_storage_invalid") from None


def parse_observation(value):
    try:
        raw = json.loads(value, object_pairs_hook=_unique)
        if set(raw) != {"codec", "snapshot"} or raw["codec"] != "rf1086-register-observation-v1":
            raise ValueError()
        result = _decode(raw["snapshot"])
        rf.assert_rf1086_register_observation_integrity(result)
        return result
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, ArithmeticError):
        raise rf.Rf1086RegisterObservationError("rf1086_register_storage_invalid") from None
