"""Reconstruct a full-year dispatch position without granting provider authority."""
from datetime import datetime

from talli_backend.shared.kernel import ActorKind
from . import public as rf
from .preparation import _validate_archive_source


def _require(condition):
    if not condition:
        raise ValueError('RF source journal is inconsistent')


def _time(value):
    _require(type(value) is str)
    value = datetime.fromisoformat(value)
    _require(value.tzinfo is not None)
    return value


def _operation(events):
    """Collapse committed attempts; an abandoned intent is always uncertain.

    Historical imports may contain the outcome without a prepared event. They
    must still prove one unambiguous outcome and a contiguous retry history.
    Neither event order nor UUID ordering can choose between conflicting facts.
    """
    if not events:
        return None
    attempts = sorted({event.attempt for event in events})
    _require(attempts == list(range(1, attempts[-1] + 1)))
    previous = None
    previous_time = None
    for attempt in attempts:
        rows = tuple(event for event in events if event.attempt == attempt)
        prepared = tuple(event for event in rows if event.operation_state == 'prepared')
        outcomes = tuple(event for event in rows if event.operation_state != 'prepared')
        _require(len(prepared) <= 1 and len(outcomes) <= 1)
        _require(previous is None or (previous.operation_state == 'failed'
            and previous.failure_class == 'retryable'))
        for event in rows:
            timestamp = _time(event.created_at)
            _require(previous_time is None or timestamp >= previous_time)
            if event.operation_state in ('prepared', 'succeeded'):
                _require(event.failure_class is None)
            elif event.operation_state == 'unknown':
                _require(event.failure_class == 'unknown')
            else:
                _require(event.failure_class in ('retryable', 'blocked', 'unknown'))
            if event.operation_state != 'succeeded':
                _require(event.authority_reference is None)
        if prepared and outcomes:
            _require(_time(prepared[0].created_at) <= _time(outcomes[0].created_at))
        previous = outcomes[0] if outcomes else prepared[0]
        previous_time = max(_time(event.created_at) for event in rows)
    return previous


def assess(archive, *, query, submission_id):
    """Return retained bytes and required next admission/recovery, never a send grant."""
    try:
        _require(isinstance(query, rf.Rf1086ArchiveQuery)
            and query.actor_id.kind is ActorKind.USER
            and isinstance(submission_id, rf.SubmissionId))
        _validate_archive_source(query, archive)
        submission = next(row for row in archive.production_submissions if row.id == submission_id.value)
        _require(submission.case_profile == 'rf1086_full_year_v1'
            and submission.user_id == str(query.actor_id.subject))
        approval = next(row for row in archive.approvals if row.id == submission.approval_id)
        claim = next(row for row in archive.source_submission_claims if row.submission_id == submission_id)
        preview = next(row for row in archive.previews if row.id == approval.preview_id)
        documents = approval.manifest['documentHashes']
        order = tuple(document['name'].removeprefix('underskjema_') for document in documents[1:])
        payload = rf.JournaledRf1086ProductionInput(submission.id, submission.income_year,
            preview.hovedskjema_xml, preview.underskjema_xml, order)
        names = ('post_hovedskjema', *(f'post_underskjema:{key}' for key in order), 'confirm')
        events = tuple(event for event in archive.production_events if event.submission_id == submission.id)
        operations = {name: _operation(tuple(event for event in events if event.operation_name == name))
            for name in names}
        pending = None
        completed_at = None
        for name in names:
            operation = operations[name]
            if operation is not None and completed_at is not None:
                _require(all(_time(event.created_at) >= completed_at
                    for event in events if event.operation_name == name))
            if pending is not None:
                # A later mutation cannot establish success or even an intent
                # while its predecessor has no committed success.
                _require(operation is None)
            elif operation is None or operation.operation_state != 'succeeded':
                pending = name
            else:
                completed_at = _time(operation.created_at)
        operation = None if pending is None else operations[pending]
        if pending is None:
            disposition = 'confirmed'
        elif operation is not None and (operation.operation_state in ('prepared', 'unknown')
                or operation.failure_class == 'unknown'):
            disposition = 'recovery_required'
        elif operation is not None and (operation.failure_class == 'blocked' or operation.attempt >= 20):
            disposition = 'blocked'
        elif submission.status == 'unknown':
            # An unexplained unknown projection is not evidence of an unsent request.
            disposition = 'recovery_required'
        elif (approval.manifest['schemaVersion'] != 'production-source-approval-v2'
                or approval.invalidated_at is not None):
            disposition = 'current_approval_required'
        elif operation is None:
            disposition = 'current_admission_required'
        else:
            disposition = 'retry_admission_required'
        # List/read and reconciliation activity belongs to a confirmed filing.
        _require(pending is None or not any(event.operation_name == 'list_documents'
            or event.operation_name.startswith('reconciliation:') for event in events))
        return rf.Rf1086SourceDispatchAssessment(claim, payload,
            approval.manifest['organizationNumber'], disposition, pending,
            None if operation is None else operation.id,
            None if operation is None else operation.attempt,
            None if operation is None else operation.idempotency_key)
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration,
            rf.ShareholderRegisterFilingError, rf.Rf1086YearSourceError):
        raise rf.Rf1086ProductionError('basis_unavailable') from None
