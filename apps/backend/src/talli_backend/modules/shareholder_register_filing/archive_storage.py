"""Closed, versioned archival records; parsing grants no write or filing authority."""
from hashlib import sha256
import json

from talli_backend.shared.kernel import ActorId, CompanyId, IncomeYear, UserId
from . import public as rf
from .preparation import _validate_archive_source
from .year_source_storage import _unique, _RECORDS as _SOURCE_RECORDS, _ENUMS

_CODEC = "rf1086-production-archive-v5"
_OVERRIDE_CODEC = "rf1086-production-archive-v4"
_FEEDBACK_CODEC = "rf1086-production-archive-v3"
_HISTORY_CODEC = "rf1086-production-archive-v2"
_ORIGINAL_FIELDS = frozenset({"original_id", "original_metadata_sha256", "original_source_income_year", "original_retained_at"})
_LEGACY_CODEC = "rf1086-production-archive-v1"
_MAX_BYTES = 64 * 1024 * 1024
_RECORDS = {**_SOURCE_RECORDS, **{kind.__name__: kind for kind in (
    ActorId, CompanyId, IncomeYear, UserId, rf.ApprovalId, rf.SubmissionId,
    rf.Rf1086ArchiveSnapshot, rf.Rf1086PreviewRecord, rf.Rf1086SimulationRecord,
    rf.Rf1086ReadinessIssue, rf.Rf1086OverrideRecord, rf.Rf1086ReviewCommentRecord, rf.Rf1086FilingPermissionRecord,
    rf.Rf1086TestEvidenceRecord, rf.Rf1086ApprovalRecord, rf.Rf1086ProductionSubmissionRecord,
    rf.Rf1086ArchiveProductionEventRecord, rf.Rf1086ArchiveFeedbackArtifactRecord,
    rf.Rf1086ArchiveSourceApprovalLineage, rf.Rf1086ArchiveSourceReviewBridge,
    rf.Rf1086SourceSubmissionClaim, rf.Rf1086SubmissionHead,
    rf.Rf1086ArchiveCaptureRecord, rf.Rf1086ArchiveYearSourceHead, rf.Rf1086ArchiveSourcePreview, rf.Rf1086ArchiveSourceHistory,
)}}


def _encode(value):
    from .archive_codec import encode
    return encode(value, records=_RECORDS, enums=_ENUMS)


def _decode(value, *, legacy):
    from .archive_codec import decode
    return decode(value, records=_RECORDS, enums=_ENUMS, legacy=legacy)


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
        codec = (_CODEC if snapshot.withdrawal_capture_records is not None
                 else _OVERRIDE_CODEC if snapshot.overrides is not None
                 else _FEEDBACK_CODEC if any(row.original_id is not None for row in snapshot.feedback_artifacts)
                 else _LEGACY_CODEC if snapshot.source_history is None else _HISTORY_CODEC)
        if codec in (_CODEC, _OVERRIDE_CODEC, _FEEDBACK_CODEC) and snapshot.source_history is None:
            raise ValueError()
        if codec == _CODEC and snapshot.overrides is None:
            raise ValueError()
        result = _text({"codec": codec, "snapshotText": text, "sha256": sha256(text.encode("utf-8")).hexdigest()})
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
                or envelope["codec"] not in (_CODEC, _OVERRIDE_CODEC, _FEEDBACK_CODEC, _HISTORY_CODEC, _LEGACY_CODEC) or type(envelope["snapshotText"]) is not str
                or sha256(envelope["snapshotText"].encode("utf-8")).hexdigest() != envelope["sha256"]):
            raise ValueError()
        encoded = json.loads(envelope["snapshotText"], object_pairs_hook=_unique)
        if type(encoded) is not dict or encoded.get('record') != 'Rf1086ArchiveSnapshot' or type(encoded.get('fields')) is not dict:
            raise ValueError()
        if envelope['codec'] == _LEGACY_CODEC:
            if 'source_history' in encoded['fields']:
                raise ValueError()
            encoded['fields']['source_history'] = None
        elif encoded['fields'].get('source_history') is None:
            raise ValueError()
        if envelope['codec'] in (_CODEC, _OVERRIDE_CODEC):
            if type(encoded['fields'].get('overrides')) is not list:
                raise ValueError()
        else:
            if 'overrides' in encoded['fields']:
                raise ValueError()
            encoded['fields']['overrides'] = None
        if envelope['codec'] == _CODEC:
            if type(encoded['fields'].get('withdrawal_capture_records')) is not list:
                raise ValueError()
        else:
            if 'withdrawal_capture_records' in encoded['fields']:
                raise ValueError()
            encoded['fields']['withdrawal_capture_records'] = None
        snapshot = _decode(encoded, legacy=envelope["codec"] not in (_CODEC, _OVERRIDE_CODEC, _FEEDBACK_CODEC))
        if envelope["codec"] == _FEEDBACK_CODEC and not any(row.original_id is not None for row in snapshot.feedback_artifacts):
            raise ValueError()
        return _validate(query, snapshot)
    except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError, RecursionError,
            rf.ShareholderRegisterFilingError):
        raise rf.Rf1086ArchiveError("rf1086_archive_storage_invalid") from None
