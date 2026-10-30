"""Additive RF source commitments; no live authority or foreign policy inference.

Foreign anchor/receipt/chain hashes are public-owner attestations. This module
checks their supplied linkage and the documented compact manifest, not whether
an owner omitted a real row or whether retained original bytes are available.
"""
from __future__ import annotations

from dataclasses import fields, replace
from datetime import datetime, timedelta
import hashlib
import json

from talli_backend.shared.kernel import ActorId, CompanyId, IncomeYear
from . import public as rf
from . import year_source as legacy


_INVALID = 'rf1086_source_v2_evidence_invalid'
_CAPITAL = frozenset({'cash_issue', 'loss_covering_reduction'})


def _require(condition: bool, code: str = _INVALID) -> None:
    legacy._require(condition, code)


def _utc(value: datetime) -> None:
    _require(type(value) is datetime and value.tzinfo is not None
             and value.utcoffset() == timedelta(0))


def _scope(company_id, income_year) -> None:
    _require(type(company_id) is CompanyId and type(income_year) is IncomeYear
             and type(income_year.value) is int and 2000 <= income_year.value <= 2100)
    legacy._uuid(company_id.value)


def _fact(value) -> None:
    _require(type(value) is rf.Rf1086YearRegisterFactV2
             and type(value.observation_id) is rf.Rf1086RegisterObservationId
             and type(value.version) is int and value.version > 0)
    legacy._uuid(value.observation_id.value)
    legacy._sha(value.fact_sha256)


def _head(value) -> None:
    _require(type(value) is rf.Rf1086YearGovernanceHeadV2
             and type(value.revision) is int and value.revision > 0)
    legacy._uuid(value.amendment_id)
    legacy._sha(value.amendment_sha256)


def _chain(value, source_id, confirmed_at) -> None:
    _require(type(value) is rf.Rf1086YearGovernanceChainV2)
    _scope(value.company_id, value.income_year)
    legacy._uuid(value.receipt_id)
    for digest in (value.original_finalization_sha256, value.original_anchor_sha256,
                   value.enumeration_sha256):
        legacy._sha(digest)
    _require(value.event_type in _CAPITAL and type(value.amendment_count) is int
             and type(value.amendments) is tuple
             and value.amendment_count == len(value.amendments))
    _utc(value.original_recorded_at)
    _utc(value.evidence_cutoff)
    _fact(value.original_register_fact)
    _fact(value.effective_register_fact)
    current = value.original_register_fact
    previous = None
    recorded_at = value.original_recorded_at
    seen_observations = {current.observation_id}
    seen_heads, seen_withdrawals = set(), set()
    _require(current.observation_id.value != source_id.value)
    for revision, link in enumerate(value.amendments, 1):
        _require(type(link) is rf.Rf1086YearGovernanceLinkV2)
        _head(link.head)
        if link.previous_head is not None:
            _head(link.previous_head)
        _fact(link.target)
        _fact(link.replacement)
        _utc(link.recorded_at)
        legacy._uuid(link.withdrawal_id)
        legacy._sha(link.withdrawal_sha256)
        _require(link.head.revision == revision and link.previous_head == previous
                 and link.target == current and link.recorded_at > recorded_at
                 and link.head.amendment_id not in seen_heads
                 and link.withdrawal_id not in seen_withdrawals
                 and link.replacement.observation_id not in seen_observations
                 and link.replacement.observation_id.value != source_id.value)
        seen_heads.add(link.head.amendment_id)
        seen_withdrawals.add(link.withdrawal_id)
        seen_observations.add(link.replacement.observation_id)
        current, previous, recorded_at = link.replacement, link.head, link.recorded_at
    if value.head is not None:
        _head(value.head)
    _require(value.head == previous and value.effective_register_fact == current
             and value.evidence_cutoff == recorded_at and recorded_at < confirmed_at)


def _manifest_digest(schema, payload):
    # Public Governance wire protocol; intentionally not its private year codec.
    return hashlib.sha256(json.dumps([schema, payload], sort_keys=True,
        separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def _projection(value, command, source_id, confirmed_at) -> None:
    _require(type(value) is rf.Rf1086YearGovernanceProjectionV2)
    _scope(value.company_id, value.income_year)
    _require(value.company_id == command.company_id and value.income_year == command.income_year
             and type(value.chains) is tuple and type(value.chain_count) is int
             and value.chain_count == len(value.chains))
    for digest in (value.original_enumeration_sha256, value.chain_enumeration_sha256,
                   value.enumeration_sha256):
        legacy._sha(digest)
    for chain in value.chains:
        _chain(chain, source_id, confirmed_at)
        _require(chain.company_id == value.company_id)
    ids = tuple(chain.receipt_id for chain in value.chains)
    _require(ids == tuple(sorted(set(ids))))
    manifest = _manifest_digest('corporate-reporting-register-evidence-v1', {
        'company_id': value.company_id.value, 'income_year': value.income_year.value,
        'chain_count': value.chain_count, 'chains': [
            {'event_id': chain.receipt_id, 'income_year': chain.income_year.value,
             'anchor_sha256': chain.original_anchor_sha256,
             'amendment_count': chain.amendment_count,
             'enumeration_sha256': chain.enumeration_sha256} for chain in value.chains]})
    combined = _manifest_digest('corporate-reporting-register-evidence-projection-v1', {
        'company_id': value.company_id.value, 'income_year': value.income_year.value,
        'original_enumeration_sha256': value.original_enumeration_sha256,
        'chain_enumeration_sha256': value.chain_enumeration_sha256})
    _require(manifest == value.chain_enumeration_sha256 and combined == value.enumeration_sha256)


def _observation(wrapper, chain, event, command, event_index, documents, confirmed_at):
    original, observation = wrapper.original, wrapper.register_observation
    _require(type(observation) is rf.Rf1086RegisterObservationSnapshot
             and original.register_observation_id == chain.original_register_fact.observation_id.value
             and original.register_observation_sha256 == chain.original_register_fact.fact_sha256
             and original.finalization_sha256 == chain.original_finalization_sha256
             and original.event_type == chain.event_type)
    effective = chain.effective_register_fact
    before, after = rf.rf1086_event_register_states(command.case, event_index)
    rf.verify_rf1086_register_observation(observation, rf.Rf1086RegisterObservationMatchQuery(
        effective.observation_id, effective.version, effective.fact_sha256,
        command.company_id, command.income_year, event.timestamp, event.type, before, after))
    # Frozen observation timestamps retain their original offset-significant bytes.
    _require(observation.confirmed_at <= chain.evidence_cutoff
             and observation.confirmed_at < confirmed_at)
    for source in observation.command.documents:
        current = documents.get(source.document_id)
        _require(current is not None and all(getattr(current, item.name) == getattr(source, item.name)
                 for item in fields(rf.Rf1086YearDocumentEvidence)),
                 'rf1086_source_register_original_changed')


def _validate(command, context, source_id, confirmed_at) -> None:
    _require(type(command) is rf.RecordRf1086YearSource
             and type(context) is rf.Rf1086VerifiedYearSourceContextV2
             and type(source_id) is rf.Rf1086YearSourceId
             and type(command.actor_id) is ActorId)
    legacy._uuid(source_id.value)
    _scope(command.company_id, command.income_year)
    _utc(confirmed_at)
    legacy._sha(context.company_identity_sha256)
    _projection(context.governance_projection, command, source_id, confirmed_at)
    _require(type(context.governance_receipts) is tuple
             and all(type(item) is rf.Rf1086YearGovernanceReceiptV2
                     and type(item.original) is rf.Rf1086YearGovernanceReceipt
                     for item in context.governance_receipts))
    # Reuse frozen business validation only. The ephemeral result is discarded;
    # it is neither serialized nor passed as an invented historical predecessor.
    legacy.prepare_rf1086_year_source(replace(command, supersedes_source_id=None,
        supersedes_source_sha256=None, correction_reason=None), context=rf.Rf1086VerifiedYearSourceContext(
            context.actor_id, context.accepted_owner, context.company_id, context.income_year,
            context.company, context.company_identity_sha256, context.documents,
            tuple(item.original for item in context.governance_receipts),
            context.complete_governance_enumeration,
            context.governance_projection.original_enumeration_sha256),
        source_id=source_id, confirmed_at=confirmed_at)
    chains = {item.receipt_id: item for item in context.governance_projection.chains
              if item.income_year == command.income_year}
    capital = {item.original.receipt_id for item in context.governance_receipts
               if item.original.event_type in _CAPITAL}
    _require(capital == chains.keys(), 'rf1086_source_unreported_governance_event')
    receipts = {item.original.receipt_id: item for item in context.governance_receipts}
    documents = {item.document_id: item for item in context.documents}
    for evidence in command.event_evidence:
        if evidence.governance_receipt_id is None:
            continue
        wrapper = receipts[evidence.governance_receipt_id]
        event = command.case.events[evidence.event_index]
        if event.type == 'dividend':
            _require(wrapper.register_observation is None
                     and wrapper.original.register_observation_id is None
                     and wrapper.original.register_observation_sha256 is None)
        else:
            _require(event.type in _CAPITAL)
            _observation(wrapper, chains[wrapper.original.receipt_id], event, command,
                         evidence.event_index, documents, confirmed_at)


def _receipts_digest(receipts):
    return legacy.rf1086_year_source_digest(tuple(sorted(receipts, key=lambda item: item.original.receipt_id)))


def _source_digest(command, source_id, version, confirmed_at, context):
    return legacy.rf1086_year_source_digest({'schema': 'rf1086-year-source-v2',
        'source_id': source_id, 'version': version, 'command': command, 'confirmed_at': confirmed_at,
        'governance_receipts': tuple(sorted(context.governance_receipts, key=lambda item: item.original.receipt_id)),
        'governance_projection': context.governance_projection,
        'company_identity_sha256': context.company_identity_sha256})


def _freshness(source_id, source_sha256, context):
    projection = context.governance_projection
    return rf.Rf1086YearSourceFreshnessV2(source_id, source_sha256, context.company_identity_sha256,
        legacy._documents_digest(context.documents), _receipts_digest(context.governance_receipts),
        projection.original_enumeration_sha256, projection.chain_enumeration_sha256, projection.enumeration_sha256)


def _correction_shape(command, source_id, version):
    _require(type(version) is int and version > 0)
    if version == 1:
        _require(command.supersedes_source_id is None and command.supersedes_source_sha256 is None
                 and command.correction_reason is None, 'rf1086_source_predecessor_required')
    else:
        _require(type(command.supersedes_source_id) is rf.Rf1086YearSourceId
                 and command.supersedes_source_id != source_id,
                 'rf1086_source_predecessor_mismatch')
        legacy._uuid(command.supersedes_source_id.value)
        legacy._sha(command.supersedes_source_sha256)
        _require(type(command.correction_reason) is str and bool(command.correction_reason.strip()),
                 'rf1086_source_correction_reason_required')


def prepare(command, *, context, source_id, confirmed_at, previous=None):
    try:
        _validate(command, context, source_id, confirmed_at)
        if previous is None:
            version = 1
        else:
            if type(previous) is rf.Rf1086YearSourceSnapshot:
                legacy.assert_rf1086_year_source_integrity(previous)
            else:
                assert_integrity(previous)
            _require(type(previous.version) is int and previous.version > 0
                     and previous.company_id == command.company_id and previous.income_year == command.income_year
                     and source_id != previous.source_id and command.supersedes_source_id == previous.source_id
                     and command.supersedes_source_sha256 == previous.source_sha256,
                     'rf1086_source_predecessor_mismatch')
            _require(confirmed_at > previous.confirmed_at, 'rf1086_source_confirmation_time_invalid')
            version = previous.version + 1
        _correction_shape(command, source_id, version)
        digest = _source_digest(command, source_id, version, confirmed_at, context)
        return rf.Rf1086YearSourceSnapshotV2(source_id, version, command.company_id, command.income_year,
            command, command.actor_id, confirmed_at,
            tuple(sorted(context.governance_receipts, key=lambda item: item.original.receipt_id)),
            context.governance_projection, digest, legacy.rf1086_year_source_digest(command.case),
            _freshness(source_id, digest, context))
    except rf.Rf1086YearSourceError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, ArithmeticError, RecursionError):
        raise rf.Rf1086YearSourceError(_INVALID) from None


def _context(snapshot):
    return rf.Rf1086VerifiedYearSourceContextV2(snapshot.command.actor_id, True,
        snapshot.company_id, snapshot.income_year, snapshot.command.case.company,
        snapshot.freshness.company_identity_sha256, snapshot.command.documents,
        snapshot.governance_receipts, True, snapshot.governance_projection)


def assert_integrity(snapshot):
    """Internal integrity, not proof of current ownership, history or head status."""
    try:
        _require(type(snapshot) is rf.Rf1086YearSourceSnapshotV2
                 and type(snapshot.freshness) is rf.Rf1086YearSourceFreshnessV2
                 and snapshot.company_id == snapshot.command.company_id
                 and snapshot.income_year == snapshot.command.income_year
                 and snapshot.confirmed_by == snapshot.command.actor_id)
        context = _context(snapshot)
        _validate(snapshot.command, context, snapshot.source_id, snapshot.confirmed_at)
        _correction_shape(snapshot.command, snapshot.source_id, snapshot.version)
        _require(snapshot.governance_receipts == tuple(sorted(snapshot.governance_receipts,
                 key=lambda item: item.original.receipt_id)))
        digest = _source_digest(snapshot.command, snapshot.source_id, snapshot.version, snapshot.confirmed_at, context)
        _require(snapshot.source_sha256 == digest and snapshot.freshness == _freshness(snapshot.source_id, digest, context)
                 and snapshot.case_sha256 == legacy.rf1086_year_source_digest(snapshot.command.case),
                 'rf1086_source_snapshot_invalid')
    except rf.Rf1086YearSourceError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, ArithmeticError, RecursionError):
        raise rf.Rf1086YearSourceError(_INVALID) from None


def assert_fresh(snapshot, *, current_source_id, current_source_sha256, context):
    assert_integrity(snapshot)
    try:
        _require(type(context) is rf.Rf1086VerifiedYearSourceContextV2)
        # A new accepted owner can check an unchanged historical source. The
        # creator's actor in its immutable command remains unchanged.
        _require(context.accepted_owner is True)
        _validate(snapshot.command, replace(context, actor_id=snapshot.command.actor_id),
                  snapshot.source_id, snapshot.confirmed_at)
        # Opaque foreign digests cannot independently authenticate the supplied
        # compact links. Compare all locally committed facts as well as labels.
        _require(context.governance_projection == snapshot.governance_projection
                 and _freshness(current_source_id, current_source_sha256, context) == snapshot.freshness,
                 'rf1086_source_changed')
    except rf.Rf1086YearSourceError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, IndexError, ArithmeticError, RecursionError):
        raise rf.Rf1086YearSourceError(_INVALID) from None


def assert_replay(snapshot, command):
    assert_integrity(snapshot)
    _require(type(command) is rf.RecordRf1086YearSource
             and legacy.rf1086_year_source_digest(snapshot.command) == legacy.rf1086_year_source_digest(command),
             'rf1086_source_idempotency_conflict')
