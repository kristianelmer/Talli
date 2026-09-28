"""Closed, versioned archival records; parsing grants no write or filing authority."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
import math

from talli_backend.shared.kernel import ActorId, CompanyId, IncomeYear, UserId
from . import public as rf
from .preparation import _validate_archive_source
from .year_source_storage import _unique, _RECORDS as _SOURCE_RECORDS, _ENUMS

_CODEC = "rf1086-production-archive-v1"
_MAX_BYTES = 64 * 1024 * 1024
_RECORDS = {**_SOURCE_RECORDS, **{kind.__name__: kind for kind in (
    ActorId, CompanyId, IncomeYear, UserId, rf.ApprovalId, rf.SubmissionId,
    rf.Rf1086ArchiveSnapshot, rf.Rf1086PreviewRecord, rf.Rf1086SimulationRecord,
    rf.Rf1086ReadinessIssue, rf.Rf1086ReviewCommentRecord, rf.Rf1086FilingPermissionRecord,
    rf.Rf1086TestEvidenceRecord, rf.Rf1086ApprovalRecord, rf.Rf1086ProductionSubmissionRecord,
    rf.Rf1086ArchiveProductionEventRecord, rf.Rf1086ArchiveFeedbackArtifactRecord,
    rf.Rf1086ArchiveSourceApprovalLineage, rf.Rf1086ArchiveSourceReviewBridge,
    rf.Rf1086SourceSubmissionClaim, rf.Rf1086SubmissionHead,
)}}


def _encode(value):
    if isinstance(value, Enum):
        if _ENUMS.get(type(value).__name__) is not type(value):
            raise ValueError()
        return {"enum": type(value).__name__, "value": value.value}
    if value is None or type(value) in (str, int, bool):
        return value
    # Preserve historical JSON numbers without using them for source arithmetic.
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is Decimal and value.is_finite():
        return {"decimal": format(value, "f")}
    if type(value) is datetime:
        return {"datetime": value.isoformat()}
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError()
        return {"mapping": {key: _encode(child) for key, child in value.items()}}
    if type(value) is tuple:
        return [_encode(child) for child in value]
    if is_dataclass(value) and _RECORDS.get(type(value).__name__) is type(value):
        return {"record": type(value).__name__, "fields": {
            field.name: _encode(getattr(value, field.name)) for field in fields(value)}}
    raise ValueError()


def _decode(value):
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is list:
        return tuple(_decode(child) for child in value)
    if type(value) is not dict:
        raise ValueError()
    if set(value) == {"enum", "value"} and type(value["enum"]) is str and value["enum"] in _ENUMS:
        return _ENUMS[value["enum"]](value["value"])
    if set(value) == {"decimal"} and type(value["decimal"]) is str:
        number = Decimal(value["decimal"])
        if not number.is_finite():
            raise ValueError()
        return number
    if set(value) == {"datetime"} and type(value["datetime"]) is str:
        return datetime.fromisoformat(value["datetime"])
    if set(value) == {"mapping"} and type(value["mapping"]) is dict:
        return {key: _decode(child) for key, child in value["mapping"].items()}
    if set(value) == {"record", "fields"} and type(value["record"]) is str and value["record"] in _RECORDS:
        kind = _RECORDS[value["record"]]
        if type(value["fields"]) is not dict or set(value["fields"]) != {field.name for field in fields(kind)}:
            raise ValueError()
        return kind(**{name: _decode(child) for name, child in value["fields"].items()})
    raise ValueError()


def _text(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _validate(query, snapshot):
    if not isinstance(query, rf.Rf1086ArchiveQuery) or not isinstance(snapshot, rf.Rf1086ArchiveSnapshot):
        raise ValueError()
    if not isinstance(snapshot.income_year, IncomeYear) or type(snapshot.income_year.value) is not int:
        raise ValueError()
    return _validate_archive_source(query, snapshot)


def serialize(snapshot, *, query):
    try:
        _validate(query, snapshot)
        text = _text(_encode(snapshot))
        result = _text({"codec": _CODEC, "snapshotText": text, "sha256": sha256(text.encode("utf-8")).hexdigest()})
        if len(result.encode("utf-8")) > _MAX_BYTES:
            raise ValueError()
        return result
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RecursionError,
            rf.ShareholderRegisterFilingError):
        raise rf.Rf1086ArchiveError("rf1086_archive_storage_invalid") from None


def parse(value, *, query):
    try:
        if type(value) is not str or len(value.encode("utf-8")) > _MAX_BYTES:
            raise ValueError()
        envelope = json.loads(value, object_pairs_hook=_unique)
        if (type(envelope) is not dict or set(envelope) != {"codec", "snapshotText", "sha256"}
                or envelope["codec"] != _CODEC or type(envelope["snapshotText"]) is not str
                or sha256(envelope["snapshotText"].encode("utf-8")).hexdigest() != envelope["sha256"]):
            raise ValueError()
        snapshot = _decode(json.loads(envelope["snapshotText"], object_pairs_hook=_unique))
        return _validate(query, snapshot)
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RecursionError,
            rf.ShareholderRegisterFilingError):
        raise rf.Rf1086ArchiveError("rf1086_archive_storage_invalid") from None
