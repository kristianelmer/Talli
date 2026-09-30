"""Full-year previews bound to RF-owned evidence, with no provider operation."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
import json
import re

from . import public as rf
from .production import _sha256
from .rendering import render_rf1086_preview
from .year_source_storage import _decode, _encode, _unique

PROFILE = "rf1086-full-year-v1"


def _paid_in_amount(value) -> str:
    # Preserve the verified amount exactly; ambient Decimal rounding is irrelevant.
    whole, _, fraction = format(Decimal(str(value)), "f").partition(".")
    return whole + "." + fraction.rstrip("0").ljust(2, "0")


def prepare(command: rf.GenerateRf1086SourcePreview) -> rf.Rf1086PreparedSourcePreview:
    try:
        if not isinstance(command, rf.GenerateRf1086SourcePreview):
            raise ValueError()
        source = command.source
        rf.assert_rf1086_year_source_integrity(source)
        rendered = render_rf1086_preview(source.command.case)
        paid_in = source.command.paid_in
        # Nominal capital and tax paid-in amounts are distinct review inputs.
        text = rendered.preview + "\nSkattemessig innbetalt kapital fra bekreftet årsgrunnlag:\n" + "\n".join((
            f"- Aksjekapital 1. januar: {_paid_in_amount(paid_in.opening_capital)} kr",
            f"- Aksjekapital 31. desember: {_paid_in_amount(paid_in.closing_capital)} kr",
            f"- Overkurs 1. januar: {_paid_in_amount(paid_in.opening_premium)} kr",
            f"- Overkurs 31. desember: {_paid_in_amount(paid_in.closing_premium)} kr",
        )) + "\n"
        return rf.Rf1086PreparedSourcePreview(source, replace(rendered, preview=text))
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError):
        raise rf.Rf1086YearSourceError("rf1086_source_preview_invalid") from None


def _assert_integrity(preview: rf.Rf1086SourcePreview) -> None:
    if not isinstance(preview, rf.Rf1086SourcePreview):
        raise ValueError()
    valid_hash = lambda value: isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None
    if not (isinstance(preview.preview_id, rf.PreviewId)
            and isinstance(preview.source_id, rf.Rf1086YearSourceId)
            and isinstance(preview.company_id, rf.CompanyId)
            and isinstance(preview.income_year, rf.IncomeYear)
            and valid_hash(preview.source_sha256) and valid_hash(preview.case_sha256)
            and preview.rendering_profile == PROFILE
            and preview.readiness_status in {"ready", "blocked"}
            and all(isinstance(issue, rf.Rf1086ReadinessIssue) for issue in preview.readiness_issues)
            and isinstance(preview.preview_text, str)
            and ((preview.hovedskjema_xml is None and preview.underskjema_xml is None
                    and preview.readiness_status == "blocked")
                or (isinstance(preview.hovedskjema_xml, str)
                    and isinstance(preview.underskjema_xml, Mapping)
                    and all(isinstance(key, str) and isinstance(xml, str)
                        for key, xml in preview.underskjema_xml.items())))):
        raise ValueError()


def assert_matches(preview: rf.Rf1086SourcePreview, source: rf.Rf1086YearSourceSnapshot) -> None:
    """Check new writes against the canonical renderer, not historical reads."""
    try:
        _assert_integrity(preview)
        prepared = prepare(rf.GenerateRf1086SourcePreview(source.company_id, source.income_year, source))
        rendered = prepared.rendered
        if not (preview.source_id == source.source_id and preview.source_sha256 == source.source_sha256
                and preview.case_sha256 == source.case_sha256
                and preview.company_id == source.company_id and preview.income_year == source.income_year
                and preview.readiness_status == rendered.status
                and preview.readiness_issues == rendered.issues
                and preview.preview_text == rendered.preview
                and preview.hovedskjema_xml == rendered.hovedskjema_xml
                and preview.underskjema_xml == rendered.underskjema_xml):
            raise ValueError()
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError):
        raise rf.Rf1086YearSourceError("rf1086_source_preview_mismatch") from None


def serialize(preview: rf.Rf1086SourcePreview) -> str:
    try:
        _assert_integrity(preview)
        payload = _encode(preview)
        # Detect accidental alteration while retaining historical renderer output.
        return json.dumps({"codec": "rf1086-source-preview-v1", "preview": payload,
            "sha256": _sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False))},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError, RecursionError):
        raise rf.Rf1086YearSourceError("rf1086_source_preview_storage_invalid") from None


def parse(value: str) -> rf.Rf1086SourcePreview:
    try:
        raw = json.loads(value, object_pairs_hook=_unique)
        if (set(raw) != {"codec", "preview", "sha256"} or raw["codec"] != "rf1086-source-preview-v1"
                or raw["sha256"] != _sha256(json.dumps(raw["preview"], sort_keys=True,
                    separators=(",", ":"), ensure_ascii=False))):
            raise ValueError()
        result = _decode(raw["preview"])
        _assert_integrity(result)
        return result
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError, RecursionError):
        raise rf.Rf1086YearSourceError("rf1086_source_preview_storage_invalid") from None
