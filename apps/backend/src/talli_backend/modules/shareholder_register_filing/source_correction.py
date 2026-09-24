"""Retained correction ancestry policy; no document I/O or current-source lookup."""
import re
from uuid import UUID

from . import public as rf
from .preparation import _production_preview
from .production import rf1086_preview_payload_hash, rf1086_current_manifest_hash


def _require(condition):
    if not condition:
        raise rf.Rf1086ProductionError('basis_unavailable')


def _uuid(value):
    return type(value) is str and str(UUID(value)) == value


def _hash(value):
    return type(value) is str and re.fullmatch('[a-f0-9]{64}', value) is not None


def assert_predecessor(snapshot, *, company_id, income_year, predecessor):
    try:
        _require(isinstance(predecessor, rf.Rf1086SourceCorrectionPredecessor)
            and isinstance(predecessor.submission_id, rf.SubmissionId)
            and _uuid(predecessor.submission_id.value) and _hash(predecessor.manifest_sha256)
            and type(predecessor.reason) is str and bool(predecessor.reason.strip()))
        _require(isinstance(snapshot, rf.Rf1086CorrectionPredecessorSnapshot)
            and snapshot.company_id == company_id and snapshot.income_year == income_year)
        submission, approval, preview = snapshot.submission, snapshot.approval, snapshot.preview
        _require(isinstance(submission, rf.Rf1086ProductionSubmissionRecord)
            and isinstance(approval, rf.Rf1086ApprovalRecord) and isinstance(preview, rf.Rf1086PreviewRecord))
        _require(all(row.company_id == str(company_id) and row.income_year == int(income_year)
            for row in (submission, approval, preview)))
        _require(submission.id == predecessor.submission_id.value and submission.approval_id == approval.id
            and approval.preview_id == preview.id and approval.manifest_hash == predecessor.manifest_sha256
            and submission.status in ('accepted','rejected') and submission.feedback_state == submission.status
            and submission.environment == 'production' and submission.obligation == approval.obligation == 'aksjonaerregisteroppgaven'
            and submission.user_id == submission.submitted_by == approval.user_id == approval.approved_by
            and all(_uuid(value) for value in (submission.id, approval.id, preview.id, approval.user_id, approval.entitlement_id)))
        _require((submission.entitlement_id,submission.case_profile,submission.adapter_version,submission.payload_hash)
            == (approval.entitlement_id,approval.case_profile,approval.adapter_version,approval.payload_hash))
        # Source-backed production sends remain closed. Their ancestry requires
        # the future source submission/archive contract, not legacy hashing.
        _require(approval.case_profile == 'rf1086_no_activity_v1' and approval.adapter_version == 'rf1086-production-v1'
            and preview.source != 'rf1086-full-year-v1' and preview.status == 'ready'
            and preview.filing in ('aksjonaerregisteroppgaven','aksjonærregisteroppgaven')
            and bool(preview.hovedskjema_xml))
        production = _production_preview(preview)
        _require(approval.payload_hash == rf1086_preview_payload_hash(production)
            and approval.manifest_hash == rf1086_current_manifest_hash(production,
                actor_id=approval.user_id,organization_number=approval.manifest['organizationNumber'],approved_manifest=approval.manifest))
        artifacts = snapshot.artifacts
        _require(type(artifacts) is tuple and bool(artifacts)
            and all(isinstance(row, rf.Rf1086ArchiveFeedbackArtifactRecord) for row in artifacts)
            and type(submission.feedback_artifact_count) is int and submission.feedback_artifact_count == len(artifacts))
        for attribute in ('id','document_id','sha256'):
            _require(len({getattr(row,attribute) for row in artifacts}) == len(artifacts))
        for artifact in artifacts:
            _require(artifact.company_id == str(company_id) and artifact.submission_id == submission.id
                and _uuid(artifact.id) and _uuid(artifact.document_id) and _hash(artifact.sha256)
                and type(artifact.byte_length) is int and 0 < artifact.byte_length <= 10485760
                and artifact.classification == submission.status
                and type(artifact.content_type) is str and bool(artifact.content_type)
                and type(artifact.authority_reference) is str and 0 < len(artifact.authority_reference) <= 500)
        events = snapshot.reconciliation_events
        _require(type(events) is tuple and bool(events)
            and all(isinstance(row, rf.Rf1086ArchiveProductionEventRecord) for row in events)
            and len({row.id for row in events}) == len(events))
        for event in events:
            _require(event.company_id == str(company_id) and event.income_year == int(income_year)
                and event.submission_id == submission.id and _uuid(event.id)
                and event.operation_name.startswith('reconciliation:') and event.operation_state == 'succeeded'
                and all(_hash(value) for value in event.artifact_hashes)
                and len(set(event.artifact_hashes)) == len(event.artifact_hashes))
        hashes = {row.sha256 for row in artifacts}
        _require(any(event.resulting_status == submission.status and set(event.artifact_hashes) == hashes for event in events))
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
