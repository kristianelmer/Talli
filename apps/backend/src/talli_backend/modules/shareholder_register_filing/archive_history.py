"""Verify retained source chains without consulting today's source or admission."""
from datetime import datetime
from hashlib import sha256
from uuid import UUID
import re

from . import public as rf


def _require(condition):
    if not condition:
        raise ValueError('RF source history is inconsistent')


def _instant(value):
    result = datetime.fromisoformat(value)
    _require(result.tzinfo is not None)
    return result


def _indexed(values, kind, identity):
    _require(type(values) is tuple and all(isinstance(value, kind) for value in values))
    result = {identity(value): value for value in values}
    _require(len(result) == len(values))
    return result


def validate(archive):
    history = archive.source_history
    if history is None:
        return
    _require(isinstance(history, rf.Rf1086ArchiveSourceHistory))
    sources = _indexed(history.year_sources, rf.Rf1086YearSourceSnapshot, lambda row: row.source_id)
    observations = _indexed(history.register_observations, rf.Rf1086RegisterObservationSnapshot, lambda row: row.observation_id.value)
    previews = _indexed(history.source_previews, rf.Rf1086ArchiveSourcePreview, lambda row: row.preview.preview_id.value)
    bridges = _indexed(history.review_bridges, rf.Rf1086ArchiveSourceReviewBridge, lambda row: row.preview_id)
    projections = {row.id: row for row in archive.previews}
    for records, snapshots, parser, digest in (
        (history.source_capture_records, {key.value: value for key, value in sources.items()},
            rf.parse_rf1086_year_source, rf.rf1086_year_source_digest),
        (history.observation_capture_records, observations,
            rf.parse_rf1086_register_observation, rf.rf1086_register_observation_request_digest),
    ):
        captures = _indexed(records, rf.Rf1086ArchiveCaptureRecord, lambda row: row.record_id)
        _require(set(captures) == set(snapshots))
        keys = set()
        for identity, capture in captures.items():
            value = snapshots[identity]
            _require(type(capture.idempotency_key) is str
                     and re.fullmatch(r'[A-Za-z0-9._:-]{16,255}', capture.idempotency_key) is not None
                     and capture.request_sha256 == digest(value.command)
                     and parser(capture.snapshot_text) == value)
            key = (value.command.actor_id, capture.idempotency_key)
            _require(key not in keys)
            keys.add(key)
    scope = (archive.company_id, archive.income_year)
    ordered = sorted(sources.values(), key=lambda row: row.version)
    previous = None
    for version, source in enumerate(ordered, 1):
        rf.assert_rf1086_year_source_integrity(source)
        _require(isinstance(source.source_id, rf.Rf1086YearSourceId)
                 and isinstance(source.confirmed_at, datetime) and source.confirmed_at.tzinfo is not None
                 and (source.company_id, source.income_year) == scope and source.version == version)
        command = source.command
        if previous is None:
            _require(command.supersedes_source_id is None and command.supersedes_source_sha256 is None
                     and command.correction_reason is None)
        else:
            _require(command.supersedes_source_id == previous.source_id
                     and command.supersedes_source_sha256 == previous.source_sha256
                     and type(command.correction_reason) is str and bool(command.correction_reason.strip())
                     and source.confirmed_at > previous.confirmed_at)
        previous = source
    head = history.year_source_head
    if previous is None:
        _require(head is None)
    else:
        _require(isinstance(head, rf.Rf1086ArchiveYearSourceHead)
                 and type(head.version) is int and (head.company_id, head.income_year) == scope
                 and (head.source_id, head.version, head.source_sha256)
                 == (previous.source_id, previous.version, previous.source_sha256))
    successors = set()
    for observation in observations.values():
        rf.assert_rf1086_register_observation_integrity(observation)
        command = observation.command
        _require((command.company_id, command.income_year) == scope)
        prior_id = command.supersedes_observation_id
        if prior_id is not None:
            prior = observations.get(prior_id.value)
            _require(prior is not None and prior_id not in successors)
            successors.add(prior_id)
            _require(command.supersedes_observation_sha256 == prior.fact_sha256
                     and observation.version == prior.version + 1
                     and (command.event_kind, command.effective_at) == (prior.command.event_kind, prior.command.effective_at)
                     and observation.confirmed_at > prior.confirmed_at)
    for source in sources.values():
        for receipt in source.governance_receipts:
            if receipt.register_observation_id is not None:
                observation = observations.get(receipt.register_observation_id)
                _require(observation is not None and observation.fact_sha256 == receipt.register_observation_sha256)
    for record in previews.values():
        preview = record.preview
        _require(isinstance(preview, rf.Rf1086SourcePreview) and preview.source_id in sources)
        source = sources[preview.source_id]
        # Decode the retained renderer output; a future renderer must not rewrite history.
        _require(rf.parse_rf1086_source_preview(record.payload_text) == preview
                 and sha256(record.payload_text.encode('utf-8')).hexdigest() == record.payload_sha256)
        _require((preview.company_id, preview.income_year) == scope
                 and (preview.source_sha256, preview.case_sha256) == (source.source_sha256, source.case_sha256)
                 and _instant(record.created_at) >= source.confirmed_at)
        UUID(record.created_by)
    for bridge in bridges.values():
        _require(bridge.preview_id in previews and bridge.preview_id in projections)
        record, projection = previews[bridge.preview_id], projections[bridge.preview_id]
        preview = record.preview
        _require((bridge.company_id, bridge.income_year, bridge.source_id, bridge.source_sha256, bridge.payload_sha256)
                 == (str(archive.company_id), int(archive.income_year), preview.source_id.value,
                     preview.source_sha256, record.payload_sha256))
        UUID(bridge.created_by)
        _require(_instant(bridge.created_at) >= _instant(record.created_at)
                 and _instant(bridge.created_at) == _instant(projection.created_at))
        xml = {'source_' + sha256(('rf1086-source-shareholder-v1:' + key).encode('utf-8')).hexdigest(): value
               for key, value in (preview.underskjema_xml or {}).items()}
        _require(projection.source == 'rf1086-full-year-v1' and projection.setup_id is None
                 and projection.status == preview.readiness_status and projection.issues == preview.readiness_issues
                 and projection.preview == preview.preview_text and projection.hovedskjema_xml == preview.hovedskjema_xml
                 and projection.underskjema_xml == xml)
    _require({row.id for row in archive.previews if row.source == 'rf1086-full-year-v1'} == set(bridges))
    for line in archive.source_approval_lineage:
        _require(sources.get(line.source.source_id) == line.source
                 and line.preview_id in previews and previews[line.preview_id].preview == line.source_preview
                 and bridges.get(line.preview_id) == line.bridge)
