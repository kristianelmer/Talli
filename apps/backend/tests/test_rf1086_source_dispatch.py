"""Retained full-year dispatch state cannot authorize a duplicate provider POST."""
from dataclasses import replace
from datetime import datetime, timedelta
import json
from uuid import uuid4

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_annual_approval_evidence import annual_basis, rewrite_archive
from test_rf1086_source_submission_archive import source_submission_archive, correction_archive
from test_rf1086_year_source import ACTOR


KINDS = ['no_activity', 'formation', 'dividend', 'cash_issue',
         'cash_nominal_increase', 'loss_covering_reduction', 'mixed']


def annual_submission(kind='formation', status='approved'):
    snapshot = source_submission_archive(kind, status)
    line, approval = snapshot.source_approval_lineage[0], snapshot.approvals[0]
    basis = annual_basis(basis=rf.Rf1086SourceApprovalManifestBasis(
        line.source, line.source_preview, ACTOR, approval.entitlement_id, line.review_sha256, ()))
    draft = rf.build_rf1086_source_approval_manifest(basis)
    review = json.loads(line.review_text)
    review.pop('storedReleaseReady')
    review.update(version='rf1086-source-review-v2', otherOverridesReady=True,
                  annualReadiness=dict(draft.manifest['annualReadiness']))
    review['scope']['warningCodes'] = list(basis.acknowledged_warning_codes)
    snapshot = rewrite_archive(snapshot, review, basis)
    return replace(snapshot, source_submission_claims=(replace(snapshot.source_submission_claims[0],
        manifest_sha256=snapshot.approvals[0].manifest_hash),))


def assess(snapshot, **kwargs):
    return rf.assess_rf1086_source_dispatch(snapshot, **(dict(
        query=rf.Rf1086ArchiveQuery(snapshot.company_id, snapshot.income_year, ACTOR),
        submission_id=snapshot.source_submission_claims[-1].submission_id) | kwargs))


def with_events(snapshot, events):
    refs = {event.operation_name: event.authority_reference for event in events
            if event.operation_state == 'succeeded'}
    return replace(snapshot, production_events=tuple(events), production_submissions=(replace(
        snapshot.production_submissions[0], status='sending', feedback_state='sent',
        authority_references=refs),))


def events_for(snapshot, index, states):
    """Build persisted intents/outcomes for one operation after completed predecessors."""
    complete = source_submission_archive(status='accepted')
    templates = tuple(event for event in complete.production_events
        if event.operation_name in ('post_hovedskjema', 'confirm')
        or event.operation_name.startswith('post_underskjema:'))
    rows = list(templates[:index])
    template = templates[index]
    for offset, (attempt, state, failure) in enumerate(states):
        rows.append(replace(template, id=str(uuid4()), attempt=attempt, operation_state=state,
            failure_class=failure, authority_reference=template.authority_reference if state == 'succeeded' else None,
            created_at=(datetime.fromisoformat(template.created_at) + timedelta(seconds=offset)).isoformat()))
    return with_events(snapshot, rows)


@pytest.mark.parametrize('kind', KINDS)
def test_unstarted_v2_requires_current_admission_with_exact_immutable_payload(kind):
    archive = annual_submission(kind)
    result = assess(archive)
    assert result.disposition == 'current_admission_required'
    assert result.pending_operation == 'post_hovedskjema'
    assert result.operation_id is result.idempotency_key is result.attempt is None
    assert result.claim == archive.source_submission_claims[0]
    assert result.payload.hovedskjema_xml == archive.previews[0].hovedskjema_xml
    assert result.payload.underskjema_xml == archive.previews[0].underskjema_xml
    assert result.payload.document_order == tuple(d['name'].removeprefix('underskjema_')
        for d in archive.approvals[0].manifest['documentHashes'][1:])
    with pytest.raises(TypeError): result.payload.underskjema_xml['other'] = 'changed'


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_confirmed_history_has_no_mutation_to_resume(kind, version):
    archive = annual_submission(kind, 'accepted') if version == 'v2' else source_submission_archive(kind)
    result = assess(archive)
    assert result.disposition == 'confirmed' and result.pending_operation is None


@pytest.mark.parametrize('index', [0, 1, 2])
@pytest.mark.parametrize('state,failure,disposition', [
    ('prepared', None, 'recovery_required'), ('unknown', 'unknown', 'recovery_required'),
    ('failed', 'unknown', 'recovery_required'), ('failed', 'blocked', 'blocked'),
    ('failed', 'retryable', 'retry_admission_required'),
])
def test_crash_and_failure_at_each_mutation_preserve_original_key_without_send_authority(index, state, failure, disposition):
    archive = events_for(annual_submission(), index, [(1, state, failure)])
    result = assess(archive)
    event = archive.production_events[-1]
    assert result.disposition == disposition and result.pending_operation == event.operation_name
    assert (result.operation_id, result.attempt, result.idempotency_key) == (event.id, 1, event.idempotency_key)


def test_retry_requires_committed_new_intent_and_same_stored_key():
    archive = events_for(annual_submission(), 0, [(1, 'failed', 'retryable'), (2, 'prepared', None)])
    result = assess(archive)
    assert result.disposition == 'recovery_required' and result.attempt == 2
    assert result.idempotency_key == archive.production_events[0].idempotency_key


def test_twentieth_failure_is_exhausted_without_incrementing_attempt():
    archive = events_for(annual_submission(), 0, [(attempt, 'failed', 'retryable') for attempt in range(1, 21)])
    result = assess(archive)
    assert result.disposition == 'blocked' and result.attempt == 20


@pytest.mark.parametrize('first', [('prepared', None), ('unknown', 'unknown'), ('failed', 'blocked'), ('succeeded', None)])
def test_unresolved_or_final_attempt_cannot_be_followed_by_a_retry(first):
    archive = events_for(annual_submission(), 0, [(1, *first), (2, 'prepared', None)])
    with pytest.raises(rf.Rf1086ProductionError): assess(archive)


@pytest.mark.parametrize('change', ['gap', 'duplicate-outcome', 'duplicate-intent', 'success-and-unknown',
    'late-intent', 'early-retry', 'naive-time', 'unknown-success', 'unproven-reference', 'different-key'])
def test_ambiguous_or_tampered_attempt_history_fails_closed(change):
    archive = events_for(annual_submission(), 0, [(1, 'prepared', None), (1, 'failed', 'retryable')])
    rows = list(archive.production_events)
    if change == 'gap': rows.append(replace(rows[0], id=str(uuid4()), attempt=3))
    if change == 'duplicate-outcome': rows.append(replace(rows[1], id=str(uuid4())))
    if change == 'duplicate-intent': rows.append(replace(rows[0], id=str(uuid4())))
    if change == 'success-and-unknown':
        rows = [replace(rows[0], operation_state='succeeded', authority_reference='main-reference'),
                replace(rows[1], operation_state='unknown', failure_class='unknown')]
    if change == 'late-intent': rows[0] = replace(rows[0], created_at=(
        datetime.fromisoformat(rows[1].created_at) + timedelta(seconds=1)).isoformat())
    if change == 'early-retry': rows.append(replace(rows[0], id=str(uuid4()), attempt=2))
    if change == 'naive-time': rows[0] = replace(rows[0], created_at='2026-01-01T00:00:00')
    if change == 'unknown-success': rows[1] = replace(rows[1], operation_state='succeeded', authority_reference='main-reference', failure_class='unknown')
    if change == 'unproven-reference': rows[0] = replace(rows[0], authority_reference='unproven')
    if change == 'different-key': rows[1] = replace(rows[1], idempotency_key=str(uuid4()))
    with pytest.raises(rf.Rf1086ProductionError): assess(with_events(archive, rows))


def test_later_operation_cannot_be_prepared_before_predecessor_succeeds():
    archive = events_for(annual_submission(), 1, [(1, 'prepared', None)])
    rows = (replace(archive.production_events[0], operation_state='unknown', failure_class='unknown',
                    authority_reference=None), archive.production_events[1])
    with pytest.raises(rf.Rf1086ProductionError): assess(with_events(archive, rows))


def test_successful_main_resumes_next_document_without_reposting_main():
    archive = events_for(annual_submission(), 0, [(1, 'prepared', None), (1, 'succeeded', None)])
    result = assess(archive)
    assert result.disposition == 'current_admission_required'
    assert result.pending_operation == 'post_underskjema:' + result.payload.document_order[0]


def test_existing_v1_claim_does_not_make_unstarted_submission_sendable():
    assert assess(source_submission_archive(status='approved')).disposition == 'current_approval_required'


def test_invalidated_v2_approval_does_not_make_unstarted_submission_sendable():
    archive = annual_submission()
    archive = replace(archive, approvals=(replace(archive.approvals[0],
        invalidated_at=archive.approvals[0].approved_at, invalidation_reason='Source changed'),))
    assert assess(archive).disposition == 'current_approval_required'


def test_downstream_intent_cannot_predate_predecessor_success():
    archive = events_for(annual_submission(), 1, [(1, 'prepared', None)])
    rows = list(archive.production_events)
    rows[0] = replace(rows[0], created_at=(datetime.fromisoformat(rows[1].created_at)
        + timedelta(seconds=1)).isoformat())
    with pytest.raises(rf.Rf1086ProductionError): assess(with_events(archive, rows))


def test_correction_assessment_selects_claimed_child_and_retains_parent_history():
    archive = correction_archive()
    result = assess(archive)
    assert result.claim == archive.source_submission_claims[-1]
    assert result.claim.predecessor_submission_id == archive.source_submission_claims[0].submission_id
    assert result.disposition == 'current_approval_required'


@pytest.mark.parametrize('change', ['actor', 'missing-claim', 'manifest', 'original-xml', 'scope', 'submission'])
def test_dispatch_assessment_requires_complete_exact_owned_evidence(change):
    archive = annual_submission(); args = {}
    if change == 'actor': args['query'] = rf.Rf1086ArchiveQuery(archive.company_id, archive.income_year,
        replace(ACTOR, subject=type(ACTOR.subject)(str(uuid4()))))
    if change == 'missing-claim':
        args['submission_id'] = archive.source_submission_claims[0].submission_id
        archive = replace(archive, source_submission_claims=())
    if change == 'manifest': archive = replace(archive, approvals=(replace(archive.approvals[0], manifest_hash='b'*64),))
    if change == 'original-xml': archive = replace(archive, previews=(replace(archive.previews[0], hovedskjema_xml='<changed/>'),))
    if change == 'scope': args['query'] = rf.Rf1086ArchiveQuery(archive.company_id, rf.IncomeYear(2020), ACTOR)
    if change == 'submission': args['submission_id'] = rf.SubmissionId(str(uuid4()))
    query = rf.Rf1086ArchiveQuery(archive.company_id, archive.income_year, ACTOR)
    with pytest.raises(rf.Rf1086ProductionError):
        rf.assess_rf1086_source_dispatch(archive, **(dict(query=query,
            submission_id=rf.SubmissionId(archive.production_submissions[0].id)) | args))
