"""Project the correction parent of one exactly bound already-claimed V3 leaf."""
from . import public as rf
from .retained_archive_lineage import validate as validate_lineage
from .retained_source_dispatch import _inspect_approval, _validate_input
from .source_correction import _assert_predecessor, _assert_source_predecessor_impl, _require


def prepare(archive, *, query, claim, retained):
    """Complete retained correspondence only; no live permission or byte proof."""
    try:
        _require(isinstance(query, rf.Rf1086ArchiveQuery))
        _validate_input(query, archive)
        predecessor = rf.inspect_rf1086_source_operation_identity_v3(claim, retained,
            actor_id=query.actor_id)
        _require(predecessor is not None and claim.company_id == query.company_id
            and claim.income_year == query.income_year)
        _require(tuple(row for row in archive.source_submission_claims
            if row.submission_id == claim.submission_id) == (claim,))
        _require(tuple(row for row in archive.approvals
            if row.id == claim.approval_id.value) == (retained.approval,))
        _require(tuple(row.manifest_text for row in archive.source_approval_lineage
            if row.approval_id == claim.approval_id.value) == (retained.manifest_text,))
        rf.assert_rf1086_source_operation_history_v3(claim, retained,
            archive.production_submissions, actor_id=query.actor_id)
        current = rf.assess_rf1086_retained_source_dispatch(archive, query=query,
            submission_id=claim.submission_id)
        _require(current.claim == claim)
        if current.disposition == 'recovery_required':
            raise rf.Rf1086UnknownProductionOutcomeError(current.pending_operation)
        if current.disposition == 'blocked':
            raise rf.Rf1086BlockedProductionOperationError(current.pending_operation)
        _require(current.disposition in ('current_admission_required', 'retry_admission_required')
            and current.pending_operation == 'post_hovedskjema')
        submission = next(row for row in archive.production_submissions
            if row.id == predecessor.submission_id.value)
        _require(submission.user_id == str(query.actor_id.subject))
        approval = next(row for row in archive.approvals if row.id == submission.approval_id)
        preview = next(row for row in archive.previews if row.id == approval.preview_id)
        lineage = next((row for row in archive.source_approval_lineage
            if row.approval_id == approval.id), None)
        claim = next((row for row in archive.source_submission_claims
            if row.submission_id.value == submission.id), None)
        snapshot = rf.Rf1086CorrectionPredecessorSnapshot(query.company_id, query.income_year,
            submission, approval, preview,
            tuple(sorted((row for row in archive.feedback_artifacts if row.submission_id == submission.id),
                key=lambda row: (row.document_id, row.id))),
            tuple(sorted((row for row in archive.production_events if row.submission_id == submission.id
                and row.operation_name.startswith('reconciliation:') and row.operation_state == 'succeeded'),
                key=lambda row: (row.created_at, row.id))),
            source_approval_lineage=lineage, source_claim=claim)

        def validate_approval(query, approval, preview, lineage, require):
            validate_lineage(query, approval, preview, lineage, archive, require)

        def assert_source(snapshot, company_id, income_year):
            _assert_source_predecessor_impl(snapshot, company_id, income_year,
                inspect_approval=_inspect_approval, validate_approval=validate_approval)
            _require(rf.assess_rf1086_retained_source_dispatch(archive, query=query,
                submission_id=predecessor.submission_id).disposition == 'confirmed')

        _assert_predecessor(snapshot, company_id=query.company_id, income_year=query.income_year,
            predecessor=predecessor, assert_source_predecessor=assert_source)
        return snapshot
    except rf.Rf1086ProductionError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration, RecursionError,
            ArithmeticError, rf.ShareholderRegisterFilingError, rf.Rf1086YearSourceError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
