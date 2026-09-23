"""Documents-owned hashing of complete verified metadata; no storage IO."""
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json

from .public import DocumentRecord, DocumentsError


def metadata_sha256(document: DocumentRecord) -> str:
    def value(item):
        if is_dataclass(item):
            return {field.name: value(getattr(item, field.name)) for field in fields(item)}
        if isinstance(item, datetime):
            if item.tzinfo is None or item.utcoffset() is None:
                raise DocumentsError.invalid_input()
            return item.astimezone(timezone.utc).isoformat()
        if isinstance(item, Enum):
            return item.value
        if item is None or type(item) in (str, int):
            return item
        raise DocumentsError.invalid_input()
    if not isinstance(document, DocumentRecord):
        raise DocumentsError.invalid_input()
    return hashlib.sha256(json.dumps(value(document), sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()
