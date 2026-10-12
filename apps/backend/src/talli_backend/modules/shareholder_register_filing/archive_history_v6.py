"""Mixed retained source history, separate from current source admission.

The v1-v5 validator and registries remain closed. This private path binds local
captured rows; it cannot authenticate origin or certify omitted owner evidence.
Company-wide off-year Governance commitments never imply local RF row coverage.
"""
from datetime import datetime
import json

from . import public as rf
from .archive_history import (_indexed, _require, _validate_captures,
                              _validate_observations, _validate_previews)
from .readiness_shape_v2 import matches_shape
from .year_source_storage import _unique


_SOURCES = (rf.Rf1086YearSourceSnapshot, rf.Rf1086YearSourceSnapshotV2)


def _parse_source(text):
    _require(type(text) is str)
    raw = json.loads(text, object_pairs_hook=_unique)
    _require(type(raw) is dict and set(raw) == {'codec', 'snapshot'})
    if raw['codec'] == 'rf1086-year-source-v1':
        return rf.parse_rf1086_year_source(text)
    if raw['codec'] == 'rf1086-year-source-v2':
        return rf.parse_rf1086_year_source_v2(text)
    raise ValueError('RF source history is inconsistent')


def _source_text(source):
    if type(source) is rf.Rf1086YearSourceSnapshot:
        return rf.serialize_rf1086_year_source(source)
    _require(type(source) is rf.Rf1086YearSourceSnapshotV2)
    return rf.serialize_rf1086_year_source_v2(source)


def _capture_bodies(records, snapshots, parser, serializer):
    # Equal datetime instants and Decimal values need not retain the same wire
    # representation. Compare the owner's canonical bodies without requiring
    # canonical formatting of the original recovery envelope itself.
    for record in records:
        _require(serializer(parser(record.snapshot_text)) == serializer(snapshots[record.record_id]))


def _source_integrity(source):
    if type(source) is rf.Rf1086YearSourceSnapshot:
        rf.assert_rf1086_year_source_integrity(source)
    else:
        _require(type(source) is rf.Rf1086YearSourceSnapshotV2)
        rf.assert_rf1086_year_source_integrity_v2(source)


def _source_chain(archive, sources):
    scope = (archive.company_id, archive.income_year)
    previous = None
    for version, source in enumerate(sorted(sources.values(), key=lambda row: row.version), 1):
        _source_integrity(source)
        _require(type(source.source_id) is rf.Rf1086YearSourceId
                 and type(source.version) is int and source.version == version
                 and isinstance(source.confirmed_at, datetime) and source.confirmed_at.tzinfo is not None
                 and (source.company_id, source.income_year) == scope)
        command = source.command
        if previous is None:
            _require(command.supersedes_source_id is None and command.supersedes_source_sha256 is None
                     and command.correction_reason is None)
        else:
            _require(not (type(previous) is rf.Rf1086YearSourceSnapshotV2
                          and type(source) is rf.Rf1086YearSourceSnapshot)
                     and command.supersedes_source_id == previous.source_id
                     and command.supersedes_source_sha256 == previous.source_sha256
                     and type(command.correction_reason) is str and bool(command.correction_reason.strip())
                     and source.confirmed_at > previous.confirmed_at)
        previous = source
    head = archive.source_history.year_source_head
    if previous is None:
        _require(head is None)
    else:
        _require(matches_shape(head, rf.Rf1086ArchiveYearSourceHead)
                 and (head.company_id, head.income_year) == scope
                 and (head.source_id, head.version, head.source_sha256)
                 == (previous.source_id, previous.version, previous.source_sha256))


def _observation(fact, observations):
    row = observations.get(fact.observation_id.value)
    _require(row is not None and (row.observation_id, row.version, row.fact_sha256)
             == (fact.observation_id, fact.version, fact.fact_sha256))
    return row


def _v2_references(source, observations, withdrawals):
    # Source integrity has already verified the full company-wide projection,
    # its scope/digests and target-year receipt bijection. Only that year's RF
    # rows are enumerated by this archive; all off-year chains remain untouched.
    for chain in source.governance_projection.chains:
        if chain.income_year != source.income_year:
            continue
        original = _observation(chain.original_register_fact, observations)
        _require(original.command.event_kind == chain.event_type
                 and original.confirmed_at <= chain.original_recorded_at)
        for link in chain.amendments:
            target = _observation(link.target, observations)
            replacement = _observation(link.replacement, observations)
            withdrawal = None if withdrawals is None else withdrawals.get(link.withdrawal_id)
            _require(withdrawal is not None
                     and withdrawal.withdrawal_sha256 == link.withdrawal_sha256
                     and (withdrawal.command.observation_id, withdrawal.command.observation_version,
                          withdrawal.command.observation_fact_sha256)
                     == (target.observation_id, target.version, target.fact_sha256)
                     and withdrawal.withdrawn_at <= link.recorded_at
                     and replacement.confirmed_at <= link.recorded_at
                     and replacement.command.event_kind == chain.event_type)
        effective = _observation(chain.effective_register_fact, observations)
        receipt = next(row for row in source.governance_receipts
                       if row.original.receipt_id == chain.receipt_id)
        _require(receipt.register_observation == effective
                 and rf.serialize_rf1086_register_observation(receipt.register_observation)
                 == rf.serialize_rf1086_register_observation(effective))


def validate(archive):
    """Validate mixed captured history; do not assert a past reference is active now."""
    try:
        _require(type(archive) is rf.Rf1086ArchiveSnapshot)
        history = archive.source_history
        if archive.withdrawal_capture_records is not None:
            _require(history is not None and archive.overrides is not None)
        if history is None:
            return  # Unknown remains unknown; lineage validation is a separate layer.
        _require(type(history) is rf.Rf1086ArchiveSourceHistory
                 and type(history.year_sources) is tuple
                 and all(type(row) in _SOURCES for row in history.year_sources))
        sources = _indexed(history.year_sources, _SOURCES, lambda row: row.source_id)
        observations = _indexed(history.register_observations, rf.Rf1086RegisterObservationSnapshot,
                                lambda row: row.observation_id.value)
        _require(all(type(row) is rf.Rf1086RegisterObservationSnapshot for row in observations.values()))
        previews = _indexed(history.source_previews, rf.Rf1086ArchiveSourcePreview,
                            lambda row: row.preview.preview_id.value)
        bridges = _indexed(history.review_bridges, rf.Rf1086ArchiveSourceReviewBridge, lambda row: row.preview_id)
        projections = {row.id: row for row in archive.previews}
        for captures in (history.source_capture_records, history.observation_capture_records,
                         () if archive.withdrawal_capture_records is None else archive.withdrawal_capture_records):
            _require(type(captures) is tuple and all(matches_shape(row, rf.Rf1086ArchiveCaptureRecord)
                                                   for row in captures))
        _validate_captures(history.source_capture_records,
            {key.value: row for key, row in sources.items()}, _parse_source, rf.rf1086_year_source_digest)
        _validate_captures(history.observation_capture_records, observations,
            rf.parse_rf1086_register_observation, rf.rf1086_register_observation_request_digest)
        _capture_bodies(history.source_capture_records, {key.value: row for key, row in sources.items()},
                        _parse_source, _source_text)
        _capture_bodies(history.observation_capture_records, observations,
                        rf.parse_rf1086_register_observation, rf.serialize_rf1086_register_observation)
        _source_chain(archive, sources)
        withdrawals = _validate_observations(archive, observations)
        for source in sources.values():
            if type(source) is rf.Rf1086YearSourceSnapshotV2:
                _v2_references(source, observations, withdrawals)
            else:
                for receipt in source.governance_receipts:
                    if receipt.register_observation_id is not None:
                        observation = observations.get(receipt.register_observation_id)
                        _require(observation is not None
                                 and observation.fact_sha256 == receipt.register_observation_sha256)
        for record in previews.values():
            _require(matches_shape(record, rf.Rf1086ArchiveSourcePreview)
                     and record.preview.source_id in sources)
        _require(all(matches_shape(row, rf.Rf1086ArchiveSourceReviewBridge) for row in bridges.values()))
        _validate_previews(archive, sources, previews, bridges, projections)
        for line in archive.source_approval_lineage:
            _require(_source_text(line.source) == _source_text(sources[line.source.source_id]))
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RecursionError,
            StopIteration, rf.Rf1086ProductionError, rf.ShareholderRegisterFilingError):
        raise ValueError('RF source history is inconsistent') from None
