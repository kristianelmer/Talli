"""Fixture-only observations after the shipped V6 stream verifier reaches EOF.

This is not a business API, admission decision or replacement archive codec.
The owner verifies all originals and the final commitment before any JSON emits.
"""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
import json
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/backend/src"))

from talli_backend.application.shareholder_register_archive import verify_retained_archive_stream
from talli_backend.modules.documents.public import DocumentsError
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId


def _camel(name):
    head, *tail = name.split("_")
    return head + "".join(word.capitalize() for word in tail)


def _observe(value):
    """Keep every record field; leave opaque mapping keys and exact decimals alone."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {key: _observe(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_observe(child) for child in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if is_dataclass(value):
        members = fields(value)
        if len(members) == 1 and members[0].name == "value":
            return _observe(value.value)
        return {_camel(field.name): _observe(getattr(value, field.name)) for field in members}
    return value


def read_history(stream, company_id, income_year):
    query = rf.Rf1086ArchiveQuery(CompanyId(company_id), IncomeYear(income_year),
        ActorId(ActorKind.SYSTEM, UserId("00000000-0000-0000-0000-000000000000")))
    archive, _, _ = verify_retained_archive_stream(stream, query=query, require_feedback_originals=True)
    # The canonical source history used by the assertions remains the owner's
    # complete, typed V6 representation, not a hand-decoded V4 approximation.
    result = {"schema": "rf1086-retained-browser-history-v1", "companyId": str(archive.company_id),
        "incomeYear": int(archive.income_year),
        "canonicalArchive": rf.serialize_rf1086_archive_v6(archive, query=query)}
    for name in ("approvals", "production_submissions", "production_events", "source_submission_claims",
                 "submission_head", "feedback_artifacts", "source_approval_lineage", "overrides"):
        result[_camel(name)] = _observe(getattr(archive, name))
    return result


def main():
    try:
        result = read_history(sys.stdin.buffer, sys.argv[1], int(sys.argv[2]))
        text = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (DocumentsError, rf.Rf1086ArchiveError, ValueError, TypeError, KeyError, IndexError):
        sys.stderr.write("Invalid retained RF browser history.\n")
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
