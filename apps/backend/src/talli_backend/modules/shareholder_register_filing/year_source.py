"""RF-owned immutable full-year source preparation, independent of persistence.

The verified context is supplied only by the named application workflow after
reading owner public contracts. It is not part of a browser command or an HTTP
request model. Production application/persistence integration is separate work.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from enum import Enum
import hashlib
import json
import re
from uuid import UUID

from .public import (
    Rf1086Case,
    Rf1086YearSourceError,
    Rf1086YearSourceId,
    Rf1086PaidInSourceFacts,
    Rf1086YearDocumentEvidence,
    Rf1086YearEventEvidence,
    Rf1086YearGovernanceReceipt,
    Rf1086VerifiedYearSourceContext,
    RecordRf1086YearSource,
    Rf1086YearSourceFreshness,
    Rf1086YearSourceSnapshot,
)
from .readiness import assess_rf1086_readiness


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise Rf1086YearSourceError(code)


def _uuid(value: str) -> str:
    try:
        parsed = str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise Rf1086YearSourceError("rf1086_source_identity_invalid") from None
    _require(parsed == value, "rf1086_source_identity_invalid")
    return parsed


def _sha(value: str) -> str:
    _require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None,
             "rf1086_source_digest_invalid")
    return value


def _decimal(value: object) -> Decimal:
    _require(type(value) in (int, float, Decimal), "rf1086_source_amount_invalid")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise Rf1086YearSourceError("rf1086_source_amount_invalid") from None
    _require(number.is_finite() and number >= 0, "rf1086_source_amount_invalid")
    return number


def _canonical(value: object) -> str:
    """Finite decimal JSON numbers; no binary64 formatting or rounding step."""
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, (int, float, Decimal)):
        number = _decimal(value)
        if number == 0:
            return "0"
        text = format(number, "f")
        return (text.rstrip("0").rstrip(".") if "." in text else text) or "0"
    if isinstance(value, datetime):
        return _canonical(value.isoformat())
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if is_dataclass(value):
        return _canonical({field.name: getattr(value, field.name) for field in fields(value)})
    if isinstance(value, Mapping):
        _require(all(type(key) is str for key in value), "rf1086_source_structure_invalid")
        return "{" + ",".join(_canonical(key) + ":" + _canonical(value[key]) for key in sorted(value)) + "}"
    if isinstance(value, (tuple, list)):
        return "[" + ",".join(_canonical(item) for item in value) + "]"
    raise Rf1086YearSourceError("rf1086_source_structure_invalid")


def rf1086_year_source_digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


_GOVERNED = frozenset({"dividend", "cash_issue", "cash_nominal_increase", "loss_covering_reduction"})


def rf1086_governance_economic_facts(event: object) -> Mapping[str, object]:
    """Normalization for comparison with independently projected owner facts.

    Governance stores capital event dates (not invented timestamps). RF retains
    the exact civil time separately in its full event digest and source evidence.
    """
    def times_count(amount, count):
        number = _decimal(amount)
        with localcontext() as context:
            context.prec = len(number.as_tuple().digits) + len(str(count)) + 2
            return number * count

    result = {"event_type": event.type, "event_date": event.timestamp.date().isoformat()}
    if event.type == "dividend":
        result.update(amount=event.total_amount, allocations=tuple(sorted(
            ((item.shareholder_id, item.amount, item.share_count_basis) for item in event.allocations),
            key=lambda item: item[0])))
    elif event.type == "cash_issue":
        result.update(nominal_increase=times_count(event.nominal_value, event.issued_share_count),
                      share_premium=times_count(event.premium, event.issued_share_count),
                      issued_share_count=event.issued_share_count)
    elif event.type == "cash_nominal_increase":
        result.update(nominal_increase=event.capital_increase, share_premium=event.premium,
                      issued_share_count=0)
    elif event.type == "loss_covering_reduction":
        amount = _decimal(event.capital_reduction)
        nominal_reduction = _decimal(event.nominal_value_reduction)
        nominal_after = _decimal(event.nominal_value_after)
        _require(amount > 0 and nominal_reduction > 0 and nominal_after > 0,
                 "rf1086_source_reduction_basis_invalid")
        # Derive the unchanged share count exactly from the stated reduction;
        # never round a fractional quotient into an apparently valid register.
        amount_numerator, amount_denominator = amount.as_integer_ratio()
        nominal_numerator, nominal_denominator = nominal_reduction.as_integer_ratio()
        share_count, remainder = divmod(amount_numerator * nominal_denominator,
                                       amount_denominator * nominal_numerator)
        _require(share_count > 0 and remainder == 0,
                 "rf1086_source_reduction_basis_invalid")
        with localcontext() as context:
            context.prec = (max(nominal_after.adjusted(), nominal_reduction.adjusted())
                            - min(nominal_after.as_tuple().exponent, nominal_reduction.as_tuple().exponent) + 3)
            nominal_before = nominal_after + nominal_reduction
        result.update(nominal_reduction=amount,
                      old_share_capital=times_count(nominal_before, share_count),
                      new_share_capital=times_count(nominal_after, share_count))
    else:
        raise Rf1086YearSourceError("rf1086_source_governance_kind_invalid")
    return result


def _documents_digest(documents: tuple[Rf1086YearDocumentEvidence, ...]) -> str:
    return rf1086_year_source_digest(tuple(sorted(documents, key=lambda item: item.document_id)))


def _receipts_digest(receipts: tuple[Rf1086YearGovernanceReceipt, ...]) -> str:
    return rf1086_year_source_digest(tuple(sorted(receipts, key=lambda item: item.receipt_id)))


def prepare_rf1086_year_source(command: RecordRf1086YearSource, *,
        context: Rf1086VerifiedYearSourceContext, source_id: Rf1086YearSourceId,
        confirmed_at: datetime, previous: Rf1086YearSourceSnapshot | None = None) -> Rf1086YearSourceSnapshot:
    """Validate immutable source material; persistence must claim the current head.

    This function is not authorization middleware and cannot establish that the
    caller obtained context from owner contracts. The application binding owns
    that trust boundary and its database context/current-head lock.
    """
    _require(isinstance(command, RecordRf1086YearSource) and isinstance(context, Rf1086VerifiedYearSourceContext),
             "rf1086_source_contract_invalid")
    _require(isinstance(command.case, Rf1086Case) and isinstance(source_id, Rf1086YearSourceId)
             and all(isinstance(item, Rf1086YearDocumentEvidence) for item in (*command.documents, *context.documents))
             and all(isinstance(item, Rf1086YearEventEvidence) for item in command.event_evidence)
             and all(isinstance(item, Rf1086YearGovernanceReceipt) for item in context.governance_receipts),
             "rf1086_source_contract_invalid")
    _require(context.accepted_owner is True and context.actor_id == command.actor_id,
             "rf1086_source_owner_required")
    _require(command.company_id == context.company_id and command.income_year == context.income_year
             and command.case.company.income_year == command.income_year.value
             and command.case.company == context.company, "rf1086_source_company_year_mismatch")
    _require(isinstance(confirmed_at, datetime) and confirmed_at.tzinfo is not None,
             "rf1086_source_confirmation_time_invalid")
    _require(all(value is True for value in (command.identities_reviewed, command.complete_year_confirmed,
                                           command.paid_in_reviewed)), "rf1086_source_completeness_required")
    _require(type(command.no_activity_confirmed) is bool and command.no_activity_confirmed == (not command.case.events),
             "rf1086_source_no_activity_confirmation_mismatch")
    _require(isinstance(command.paid_in, Rf1086PaidInSourceFacts), "rf1086_source_paid_in_required")
    shares = command.case.share_snapshot
    _require(tuple(getattr(command.paid_in, field.name) for field in fields(command.paid_in)) == tuple(_decimal(value) for value in (
        shares.previous_paid_in_share_capital, shares.current_paid_in_share_capital,
        shares.previous_paid_in_premium, shares.current_paid_in_premium)), "rf1086_source_paid_in_mismatch")
    _require(assess_rf1086_readiness(command.case).is_ready, "rf1086_source_case_not_ready")
    # Validate every immutable holder identity as well as chronological economics.
    identities = set()
    for holder in command.case.shareholders:
        value = holder.national_id if holder.kind == "norwegian_person" else holder.org_number
        expected = 11 if holder.kind == "norwegian_person" else 9
        _require(holder.kind in {"norwegian_person", "norwegian_company"} and isinstance(holder.name, str)
                 and bool(holder.name.strip()) and isinstance(value, str)
                 and re.fullmatch(r"[0-9]{%d}" % expected, value) is not None,
                 "rf1086_source_holder_identity_invalid")
        _require((holder.kind, value) not in identities, "rf1086_source_holder_identity_duplicate")
        identities.add((holder.kind, value))
    docs = {item.document_id: item for item in command.documents}
    verified = {item.document_id: item for item in context.documents}
    _require(bool(docs) and len(docs) == len(command.documents) and len(verified) == len(context.documents)
             and docs == verified and all(item.company_id == command.company_id for item in docs.values()),
             "rf1086_source_documents_unverified")
    # Prior-year closing evidence is legitimate; source_income_year is retained,
    # not required to equal the target reporting year.
    for references in (command.opening_document_ids, command.closing_document_ids, command.paid_in_document_ids):
        _require(bool(references) and len(set(references)) == len(references)
                 and set(references) <= docs.keys(), "rf1086_source_basis_evidence_missing")
    _require(context.complete_governance_enumeration is True, "rf1086_source_governance_enumeration_incomplete")
    receipts = {item.receipt_id: item for item in context.governance_receipts}
    _require(len(receipts) == len(context.governance_receipts), "rf1086_source_governance_receipt_duplicate")
    by_event = {item.event_index: item for item in command.event_evidence}
    _require(len(by_event) == len(command.event_evidence) and set(by_event) == set(range(len(command.case.events))),
             "rf1086_source_event_evidence_incomplete")
    used_receipts = set()
    for index, event in enumerate(command.case.events):
        evidence = by_event[index]
        _require(evidence.event_sha256 == rf1086_year_source_digest(event)
                 and bool(evidence.document_ids) and len(set(evidence.document_ids)) == len(evidence.document_ids)
                 and set(evidence.document_ids) <= docs.keys(), "rf1086_source_event_evidence_mismatch")
        if event.type not in _GOVERNED:
            _require(evidence.governance_receipt_id is None, "rf1086_source_unexpected_governance_receipt")
            continue
        receipt = receipts.get(evidence.governance_receipt_id)
        _require(receipt is not None and receipt.receipt_id not in used_receipts and receipt.active is True
                 and receipt.company_id == command.company_id and receipt.income_year == command.income_year
                 and receipt.event_type == event.type
                 and receipt.economic_sha256 == rf1086_year_source_digest(rf1086_governance_economic_facts(event)),
                 "rf1086_source_governance_receipt_mismatch")
        _require(bool(receipt.signed_document_hashes) and set(receipt.signed_document_hashes)
                 <= {docs[reference].content_sha256 for reference in evidence.document_ids},
                 "rf1086_source_signed_evidence_missing")
        if event.type != "dividend":
            _require(receipt.register_observation_id is not None and receipt.register_observation_sha256 is not None
                     and receipt.register_observation_id != source_id.value,
                     "rf1086_source_circular_register_evidence")
        used_receipts.add(receipt.receipt_id)
    _require(used_receipts == receipts.keys(), "rf1086_source_unreported_governance_event")
    if previous is None:
        _require(command.supersedes_source_id is None and command.supersedes_source_sha256 is None
                 and command.correction_reason is None, "rf1086_source_predecessor_required")
        version = 1
    else:
        assert_rf1086_year_source_integrity(previous)
        _require(previous.company_id == command.company_id and previous.income_year == command.income_year
                 and source_id != previous.source_id and command.supersedes_source_id == previous.source_id
                 and command.supersedes_source_sha256 == previous.source_sha256,
                 "rf1086_source_predecessor_mismatch")
        _require(isinstance(command.correction_reason, str) and bool(command.correction_reason.strip()),
                 "rf1086_source_correction_reason_required")
        _require(confirmed_at > previous.confirmed_at, "rf1086_source_confirmation_time_invalid")
        version = previous.version + 1
    case_digest = rf1086_year_source_digest(command.case)
    source_digest = rf1086_year_source_digest({"schema": "rf1086-year-source-v1", "source_id": source_id,
        "version": version, "command": command, "confirmed_at": confirmed_at,
        "governance_receipts": tuple(sorted(context.governance_receipts, key=lambda item: item.receipt_id)),
        "company_identity_sha256": context.company_identity_sha256,
        "governance_enumeration_sha256": context.governance_enumeration_sha256})
    freshness = Rf1086YearSourceFreshness(source_id, source_digest, context.company_identity_sha256,
        _documents_digest(command.documents), _receipts_digest(context.governance_receipts), context.governance_enumeration_sha256)
    return Rf1086YearSourceSnapshot(source_id, version, command.company_id, command.income_year, command,
        command.actor_id, confirmed_at, tuple(sorted(context.governance_receipts, key=lambda item: item.receipt_id)),
        source_digest, case_digest, freshness)


def assert_rf1086_year_source_fresh(snapshot: Rf1086YearSourceSnapshot, *,
        current_source_id: Rf1086YearSourceId, current_source_sha256: str,
        context: Rf1086VerifiedYearSourceContext) -> None:
    """Called with a complete fresh owner projection, never cached browser data."""
    assert_rf1086_year_source_integrity(snapshot)
    expected = snapshot.freshness
    _require(context.accepted_owner is True and context.company_id == snapshot.company_id
             and context.income_year == snapshot.income_year and context.company == snapshot.command.case.company,
             "rf1086_source_company_year_mismatch")
    _require(context.complete_governance_enumeration is True and all(item.active is True for item in context.governance_receipts),
             "rf1086_source_governance_enumeration_incomplete")
    actual = Rf1086YearSourceFreshness(current_source_id, current_source_sha256, context.company_identity_sha256,
        _documents_digest(context.documents), _receipts_digest(context.governance_receipts), context.governance_enumeration_sha256)
    _require(actual == expected, "rf1086_source_changed")


def assert_rf1086_year_source_integrity(snapshot: Rf1086YearSourceSnapshot) -> None:
    """Reject altered persisted snapshots before using correction/freshness facts."""
    _require(isinstance(snapshot, Rf1086YearSourceSnapshot)
             and type(snapshot.version) is int and snapshot.version > 0
             and snapshot.company_id == snapshot.command.company_id
             and snapshot.income_year == snapshot.command.income_year
             and snapshot.confirmed_by == snapshot.command.actor_id,
             "rf1086_source_snapshot_invalid")
    source_digest = rf1086_year_source_digest({"schema": "rf1086-year-source-v1",
        "source_id": snapshot.source_id, "version": snapshot.version, "command": snapshot.command,
        "confirmed_at": snapshot.confirmed_at, "governance_receipts": snapshot.governance_receipts,
        "company_identity_sha256": snapshot.freshness.company_identity_sha256,
        "governance_enumeration_sha256": snapshot.freshness.governance_enumeration_sha256})
    expected = Rf1086YearSourceFreshness(snapshot.source_id, source_digest,
        snapshot.freshness.company_identity_sha256, _documents_digest(snapshot.command.documents),
        _receipts_digest(snapshot.governance_receipts), snapshot.freshness.governance_enumeration_sha256)
    _require(source_digest == snapshot.source_sha256 and expected == snapshot.freshness
             and rf1086_year_source_digest(snapshot.command.case) == snapshot.case_sha256,
             "rf1086_source_snapshot_invalid")


def assert_rf1086_year_source_replay(snapshot: Rf1086YearSourceSnapshot,
        command: RecordRf1086YearSource) -> None:
    """Persistence first finds its actor/company-scoped idempotency-key record.

    It may return the original only for the identical canonical request. This
    check does not replace the transaction lock or unique idempotency constraint.
    """
    assert_rf1086_year_source_integrity(snapshot)
    _require(rf1086_year_source_digest(snapshot.command) == rf1086_year_source_digest(command),
             "rf1086_source_idempotency_conflict")
