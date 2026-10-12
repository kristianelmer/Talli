"""Inspect retained v1/v2/v3 dispatch evidence without live send authority."""
from talli_backend.shared.kernel import ActorId, ActorKind, UserId

from . import public as rf
from .preparation import _validate_retained_archive_source
from .source_dispatch import _assess_validated, _position_validated, _require


_ANNUAL_VERSIONS = ('production-source-approval-v2', 'production-source-approval-v3')


def _validate_input(query, archive):
    _require(type(query.actor_id) is ActorId and query.actor_id.kind is ActorKind.USER
        and type(query.actor_id.subject) is UserId)
    _require(isinstance(archive, rf.Rf1086ArchiveSnapshot))
    history = archive.source_history
    # These APIs accept typed snapshots directly, so the v6 envelope's capture
    # requirements must also hold here. Legacy-only unknown coverage survives.
    requires_captures = (
        any(row.manifest.get('schemaVersion') == 'production-source-approval-v3'
            for row in archive.approvals)
        or any(isinstance(row.source, rf.Rf1086YearSourceSnapshotV2)
               for row in archive.source_approval_lineage)
        or (history is not None and any(isinstance(row, rf.Rf1086YearSourceSnapshotV2)
                                       for row in history.year_sources)))
    if requires_captures:
        _require(type(history) is rf.Rf1086ArchiveSourceHistory
            and type(archive.overrides) is tuple
            and type(archive.withdrawal_capture_records) is tuple)
    _validate_retained_archive_source(query, archive)


def _inspect_approval(value, *, approval_id, manifest_sha256, actor_id):
    inspect = (rf.inspect_rf1086_retained_source_approval_v3
        if value.approval.manifest.get('schemaVersion') == 'production-source-approval-v3'
        else rf.inspect_rf1086_retained_source_approval)
    return inspect(value, approval_id=approval_id,
        manifest_sha256=manifest_sha256, actor_id=actor_id)


def assess(archive, *, query, submission_id):
    """Required next admission/recovery from saved evidence, never a new intent."""
    try:
        _require(isinstance(query, rf.Rf1086ArchiveQuery)
            and query.actor_id.kind is ActorKind.USER
            and isinstance(submission_id, rf.SubmissionId))
        _validate_input(query, archive)
        return _assess_validated(archive, query=query, submission_id=submission_id,
            annual_versions=_ANNUAL_VERSIONS)
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration, RecursionError,
            rf.ShareholderRegisterFilingError, rf.Rf1086YearSourceError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None


def position(archive, *, query, approval_id):
    """Describe retained identity and state; no owner, MFA or provider query."""
    try:
        _require(isinstance(query, rf.Rf1086ArchiveQuery)
            and query.actor_id.kind is ActorKind.USER
            and isinstance(approval_id, rf.ApprovalId))
        _validate_input(query, archive)
        return _position_validated(archive, query=query, approval_id=approval_id,
            inspect_approval=_inspect_approval, assess_dispatch=assess,
            annual_versions=_ANNUAL_VERSIONS)
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration, RecursionError,
            rf.ShareholderRegisterFilingError, rf.Rf1086YearSourceError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
