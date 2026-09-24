"""Deterministic independent register evidence; no IO or current-head authority."""
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from enum import Enum
import hashlib
import json
import re
from uuid import UUID

from .public import (
    Rf1086RegisterObservationError, Rf1086RegisterObservationSnapshot,
)


def require(condition, code):
    if not condition:
        raise Rf1086RegisterObservationError("rf1086_register_" + code)


def validate_identity(value):
    try:
        valid = str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        valid = False
    require(valid, "identity_invalid")


def sha(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None, "digest_invalid")


def canonical(value):
    if is_dataclass(value):
        return {f.name: canonical(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return canonical(value.value)
    if isinstance(value, Decimal):
        require(value.is_finite(), "amount_invalid")
        rendered = format(value, "f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (tuple, list)):
        return [canonical(item) for item in value]
    if value is None or type(value) in (str, int, bool):
        return value
    raise Rf1086RegisterObservationError("rf1086_register_value_invalid")


def digest(observation_id, version, command, confirmed_at):
    value = ["rf1086-register-observation-v1", observation_id, version, command, confirmed_at]
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode()).hexdigest()


def state(value):
    for amount in (value.share_capital, value.nominal_value):
        require(type(amount) is Decimal and amount.is_finite() and amount > 0
                and amount.as_tuple().exponent >= -6, "amount_invalid")
    require(type(value.share_count) is int and value.share_count > 0, "count_invalid")
    with localcontext() as ctx:
        ctx.prec = max(28, len(value.nominal_value.as_tuple().digits) + len(str(value.share_count)) + 2)
        require(value.share_capital == value.nominal_value * value.share_count, "capital_count_mismatch")
    require(value.share_capital >= Decimal(30000), "capital_below_supported_minimum")
    require(bool(value.holdings), "holders_missing")
    identities, holders = set(), {}
    for holding in value.holdings:
        require(isinstance(holding.shareholder_id, str) and bool(holding.shareholder_id.strip())
                and isinstance(holding.name, str) and bool(holding.name.strip()), "holder_invalid")
        width = {"norwegian_person": 11, "norwegian_company": 9}.get(holding.kind)
        require(width is not None and isinstance(holding.identifier, str)
                and re.fullmatch(r"[0-9]{" + str(width) + r"}", holding.identifier) is not None, "holder_identity_invalid")
        require(type(holding.share_count) is int and holding.share_count > 0, "holder_count_invalid")
        identity = (holding.kind, holding.identifier)
        require(holding.shareholder_id not in holders and identity not in identities, "holder_duplicate")
        holders[holding.shareholder_id] = holding
        identities.add(identity)
    require(sum(h.share_count for h in value.holdings) == value.share_count, "holder_total_mismatch")
    return replace(value, holdings=tuple(sorted(value.holdings, key=lambda h: h.shareholder_id)))


def normalized(command):
    require(type(command.complete_register_confirmed) is bool and command.complete_register_confirmed
            and type(command.registration_confirmed) is bool and command.registration_confirmed
            and command.single_share_class_confirmed is True,
            "owner_confirmation_required")
    effective = command.effective_at
    require(isinstance(effective, datetime) and effective.tzinfo is None and effective.microsecond == 0
            and effective.year == command.income_year.value, "effective_time_invalid")
    before, after = state(command.before), state(command.after)
    old = {h.shareholder_id: h for h in before.holdings}
    new = {h.shareholder_id: h for h in after.holdings}
    for identifier in old.keys() & new.keys():
        require((old[identifier].kind, old[identifier].identifier, old[identifier].name)
                == (new[identifier].kind, new[identifier].identifier, new[identifier].name), "holder_identity_changed")
    if command.event_kind == "cash_issue":
        require(after.share_count > before.share_count and after.nominal_value == before.nominal_value,
                "issue_transition_invalid")
        require(all(k in new and new[k].share_count >= h.share_count for k, h in old.items()),
                "issue_holder_transition_invalid")
    elif command.event_kind in ("cash_nominal_increase", "loss_covering_reduction"):
        require(before.share_count == after.share_count and before.holdings == after.holdings,
                "nominal_holder_transition_invalid")
        require(after.nominal_value > before.nominal_value if command.event_kind == "cash_nominal_increase"
                else after.nominal_value < before.nominal_value, "nominal_transition_invalid")
    else:
        require(False, "event_unsupported")
    documents = command.documents
    require(bool(documents), "documents_missing")
    keys = set()
    roles = set()
    versions = {}
    for doc in documents:
        validate_identity(doc.document_id)
        sha(doc.content_sha256)
        sha(doc.content_version_sha256)
        sha(doc.metadata_sha256)
        require(doc.company_id == command.company_id and doc.content_version_sha256 == doc.content_sha256
                and type(doc.byte_length) is int and doc.byte_length > 0
                and isinstance(doc.document_type, str) and bool(doc.document_type.strip())
                and doc.integrity_status in {"attached", "generated_unsigned", "signed_owner_attested", "stored"}
                and isinstance(doc.created_at, datetime) and doc.created_at.tzinfo is not None
                and doc.created_at.utcoffset() is not None, "document_binding_invalid")
        require(doc.role in ("register_before", "register_after", "registration"), "document_role_invalid")
        key = (doc.document_id, doc.role)
        require(key not in keys, "document_duplicate")
        content = (doc.content_version_sha256, doc.content_sha256, doc.byte_length, doc.document_type,
                   doc.integrity_status, doc.created_at, doc.metadata_sha256, doc.source_income_year)
        require(doc.document_id not in versions or versions[doc.document_id] == content, "document_version_conflict")
        keys.add(key)
        versions[doc.document_id] = content
        roles.add(doc.role)
    require(roles == {"register_before", "register_after", "registration"}, "document_coverage_incomplete")
    if command.supersedes_observation_id is not None:
        validate_identity(command.supersedes_observation_id.value)
        sha(command.supersedes_observation_sha256)
        require(isinstance(command.correction_reason, str) and bool(command.correction_reason.strip()), "correction_reason_required")
    else:
        require(command.supersedes_observation_sha256 is None and command.correction_reason is None,
                "correction_link_invalid")
    return replace(command, before=before, after=after,
                   documents=tuple(sorted(documents, key=lambda d: (d.document_id, d.role))))


def instant(value):
    require(isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None,
            "capture_time_invalid")
    return value.astimezone(timezone.utc)


def prepare(command, *, context, observation_id, confirmed_at, previous=None):
    command = normalized(command)
    confirmed_at = instant(confirmed_at)
    validate_identity(observation_id.value)
    require(context.accepted_owner is True and context.independent_originals_verified is True,
            "trusted_evidence_required")
    require((context.actor_id, context.company_id, context.income_year)
            == (command.actor_id, command.company_id, command.income_year), "context_binding_invalid")
    require(tuple(sorted(context.documents, key=lambda d: (d.document_id, d.role))) == command.documents,
            "verified_documents_mismatch")
    require(all(doc.created_at <= confirmed_at for doc in command.documents), "document_postdates_capture")
    # Civil event dates are checked coarsely here; no timezone is invented for them.
    require(confirmed_at.date() >= command.effective_at.date(), "capture_predates_event")
    if previous is None:
        require(command.supersedes_observation_id is None, "previous_required")
        version = 1
    else:
        assert_integrity(previous)
        require(command.supersedes_observation_id == previous.observation_id
                and command.supersedes_observation_sha256 == previous.fact_sha256
                and observation_id != previous.observation_id, "correction_link_invalid")
        require((command.company_id, command.income_year, command.event_kind, command.effective_at)
                == (previous.command.company_id, previous.command.income_year,
                    previous.command.event_kind, previous.command.effective_at), "correction_scope_invalid")
        require(confirmed_at > previous.confirmed_at, "correction_time_invalid")
        version = previous.version + 1
    return Rf1086RegisterObservationSnapshot(observation_id, version, command, confirmed_at,
        digest(observation_id, version, command, confirmed_at))


def assert_integrity(snapshot):
    validate_identity(snapshot.observation_id.value)
    require(type(snapshot.version) is int and snapshot.version > 0, "version_invalid")
    command = normalized(snapshot.command)
    require(command == snapshot.command, "noncanonical_snapshot")
    confirmed_at = instant(snapshot.confirmed_at)
    require(all(doc.created_at <= confirmed_at for doc in command.documents), "document_postdates_capture")
    require(snapshot.confirmed_at.date() >= command.effective_at.date(), "capture_predates_event")
    require((snapshot.version == 1) == (command.supersedes_observation_id is None), "version_link_invalid")
    require(command.supersedes_observation_id != snapshot.observation_id, "correction_link_invalid")
    sha(snapshot.fact_sha256)
    require(snapshot.fact_sha256 == digest(snapshot.observation_id, snapshot.version, command, confirmed_at),
            "integrity_mismatch")


def verify(snapshot, query):
    assert_integrity(snapshot)
    require((query.observation_id, query.revision, query.fact_sha256) ==
            (snapshot.observation_id, snapshot.version, snapshot.fact_sha256)
            and type(query.revision) is int, "reference_mismatch")
    command = snapshot.command
    require((query.company_id, query.income_year, query.effective_at, query.event_kind,
             state(query.before), state(query.after)) ==
            (command.company_id, command.income_year, command.effective_at, command.event_kind,
             command.before, command.after), "economic_binding_mismatch")
    return snapshot


def request_digest(command):
    payload = ["rf1086-register-observation-request-v1", normalized(command)]
    return hashlib.sha256(json.dumps(canonical(payload), sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode()).hexdigest()
