"""Derive an exact correction parent from supplied complete retained evidence."""
from . import public as rf
from .retained_archive_lineage import validate as validate_lineage
from .retained_source_dispatch import _inspect_approval, _validate_input
from .source_correction import _assert_predecessor, _assert_source_predecessor_impl, _require


def prepare(archive, *, query, predecessor):
    """Return a compact projection, never a completeness or authorization token.

    A future writer must re-enumerate and validate the full archive on its held
    connection. Documents separately proves feedback bytes; query actor identity
    does not establish current accepted-owner access.
    """
    try:
        _require(isinstance(query, rf.Rf1086ArchiveQuery))
        _validate_input(query, archive)
        rf.assert_rf1086_submission_predecessor(archive.production_submissions,
            company_id=query.company_id, income_year=query.income_year, predecessor=predecessor)
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
