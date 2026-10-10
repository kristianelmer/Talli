"""Private archive primitives shared by fixed, separately versioned allowlists.

Historical JSON floats, Decimal scales, datetime offsets and omitted unknown
coverage retain their original representation. This codec confers no authority.
"""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from datetime import datetime
from decimal import Decimal
import math

from . import public as rf

_ORIGINAL_FIELDS = frozenset({"original_id", "original_metadata_sha256", "original_source_income_year", "original_retained_at"})


def encode(value, *, records, enums):
    if isinstance(value, Enum):
        if enums.get(type(value).__name__) is not type(value):
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
        return {"mapping": {key: encode(child, records=records, enums=enums) for key, child in value.items()}}
    if type(value) is tuple:
        return [encode(child, records=records, enums=enums) for child in value]
    if is_dataclass(value) and records.get(type(value).__name__) is type(value):
        return {"record": type(value).__name__, "fields": {
            field.name: encode(getattr(value, field.name), records=records, enums=enums) for field in fields(value)
            if not (type(value) is rf.Rf1086ArchiveSnapshot and field.name == 'source_history'
                    and value.source_history is None)
            and not (type(value) is rf.Rf1086ArchiveSnapshot and field.name == 'overrides'
                     and value.overrides is None)
            and not (type(value) is rf.Rf1086ArchiveSnapshot and field.name == 'withdrawal_capture_records'
                     and value.withdrawal_capture_records is None)
            and not (type(value) is rf.Rf1086ArchiveFeedbackArtifactRecord and field.name in _ORIGINAL_FIELDS
                     and value.original_id is None)}}
    raise ValueError()


def decode(value, *, records, enums, legacy):
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is list:
        return tuple(decode(child, records=records, enums=enums, legacy=legacy) for child in value)
    if type(value) is not dict:
        raise ValueError()
    if set(value) == {"enum", "value"} and type(value["enum"]) is str and value["enum"] in enums:
        return enums[value["enum"]](value["value"])
    if set(value) == {"decimal"} and type(value["decimal"]) is str:
        number = Decimal(value["decimal"])
        if not number.is_finite():
            raise ValueError()
        return number
    if set(value) == {"datetime"} and type(value["datetime"]) is str:
        return datetime.fromisoformat(value["datetime"])
    if set(value) == {"mapping"} and type(value["mapping"]) is dict:
        return {key: decode(child, records=records, enums=enums, legacy=legacy) for key, child in value["mapping"].items()}
    if set(value) == {"record", "fields"} and type(value["record"]) is str and value["record"] in records:
        kind = records[value["record"]]
        if type(value["fields"]) is not dict:
            raise ValueError()
        if kind is rf.Rf1086ArchiveFeedbackArtifactRecord:
            present = _ORIGINAL_FIELDS.intersection(value["fields"])
            if legacy and present:
                raise ValueError()
            if not present:
                value["fields"].update({name: None for name in _ORIGINAL_FIELDS})
        if set(value["fields"]) != {field.name for field in fields(kind)}:
            raise ValueError()
        return kind(**{name: decode(child, records=records, enums=enums, legacy=legacy) for name, child in value["fields"].items()})
    raise ValueError()

