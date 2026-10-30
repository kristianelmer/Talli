"""Pure retained dispatch fixtures; no persisted writer, owner or provider proof."""
from dataclasses import replace
from hashlib import sha256
import json
from uuid import UUID, uuid5, NAMESPACE_URL

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, UserId
from test_rf1086_archive_storage import query
from test_rf1086_archive_storage_v6 import approved_v6, forbid_fresh
from test_rf1086_source_dispatch import annual_submission, KINDS
from test_rf1086_source_submission_archive import source_submission_archive
from test_rf1086_year_source import ACTOR


def retained_submission(kind='cash_issue', amendments=2, status='approved', *, correction=True):
    """Build saved v3 identity with synthetic claims/journals, never a live producer."""
    archive = approved_v6(kind, amendments, correction=correction)
    template = source_submission_archive(status='accepted' if status != 'rejected' else 'rejected')
    approval = archive.approvals[0]
    claim = replace(template.source_submission_claims[0],
        approval_id=rf.ApprovalId(approval.id), manifest_sha256=approval.manifest_hash,
        payload_sha256=approval.payload_hash, claimed_at=approval.approved_at)
    submission = replace(template.production_submissions[0], approval_id=approval.id,
        entitlement_id=approval.entitlement_id, payload_hash=approval.payload_hash,
        status=status, authority_references={}, feedback_state='sent', feedback_artifact_count=0)
    events, refs = [], {}
    if status != 'approved':
        event = template.production_events[0]
        for document in approval.manifest['documentHashes']:
            name = ('post_hovedskjema' if document['name'] == 'hovedskjema' else
                    'post_underskjema:' + document['name'].removeprefix('underskjema_'))
            reference = 'retained-main' if name == 'post_hovedskjema' else 'retained-post'
            events.append(replace(event, id=str(uuid5(NAMESPACE_URL, name)), operation_name=name,
                body_hash=document['sha256'], idempotency_key=str(uuid5(NAMESPACE_URL, 'key:' + name)),
                authority_reference=reference))
            refs[name] = reference
        refs['confirm'] = json.dumps({'dialogId': str(UUID(int=700)),
            'forsendelseId': str(UUID(int=701))}, separators=(',', ':'))
        events.append(replace(event, id=str(UUID(int=702)), operation_name='confirm',
            body_hash=sha256(f'retained-main:{len(approval.manifest["documentHashes"])-1}'.encode()).hexdigest(),
            idempotency_key=str(UUID(int=703)), authority_reference=refs['confirm'], resulting_status='received'))
        events.extend(template.production_events[-1:])
        submission = replace(submission, authority_references=refs, feedback_state=status,
            feedback_artifact_count=len(template.feedback_artifacts))
    return replace(archive, production_submissions=(submission,), source_submission_claims=(claim,),
        submission_head=replace(template.submission_head, updated_at=claim.claimed_at),
        production_events=tuple(events), feedback_artifacts=template.feedback_artifacts if events else ())


def retained_value(archive):
    return rf.Rf1086RetainedSourceApproval(archive.approvals[0],
        archive.source_approval_lineage[0].manifest_text)


def inspect(value, **changes):
    args = dict(approval_id=rf.ApprovalId(value.approval.id),
        manifest_sha256=value.approval.manifest_hash, actor_id=ACTOR)
    args.update(changes)
    return rf.inspect_rf1086_retained_source_approval_v3(value, **args)


def assess(archive):
    return rf.assess_rf1086_retained_source_dispatch(archive, query=query(archive),
        submission_id=archive.source_submission_claims[0].submission_id)


def position(archive):
    return rf.inspect_rf1086_retained_source_dispatch_position(archive,
        query=query(archive), approval_id=rf.ApprovalId(archive.approvals[0].id))


def reheader(value, mutate):
    manifest = json.loads(value.manifest_text)
    mutate(manifest)
    text = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return replace(value, approval=replace(value.approval, manifest=manifest,
        manifest_hash=sha256(text.encode()).hexdigest()), manifest_text=text)


@pytest.mark.parametrize('kind', ['cash_issue', 'loss_covering_reduction'])
@pytest.mark.parametrize('amendments', [0, 1, 2])
@pytest.mark.parametrize('correction', [False, True])
@pytest.mark.parametrize('status', ['approved', 'accepted', 'rejected'])
def test_v3_saved_payload_and_position_are_available_without_fresh_builders(
        kind, amendments, correction, status, monkeypatch):
    archive = retained_submission(kind, amendments, status, correction=correction)
    forbid_fresh(monkeypatch)
    result = assess(archive)
    expected = 'current_admission_required' if status == 'approved' else 'confirmed'
    assert result.disposition == position(archive).disposition == expected
    assert result.claim == archive.source_submission_claims[0]
    assert result.payload.hovedskjema_xml == archive.previews[0].hovedskjema_xml
    assert result.payload.underskjema_xml == archive.previews[0].underskjema_xml
    assert result.payload.document_order == tuple(d['name'].removeprefix('underskjema_')
        for d in archive.approvals[0].manifest['documentHashes'][1:])
    assert inspect(retained_value(archive)) is None


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('status', ['approved', 'accepted'])
def test_explicit_retained_path_preserves_legacy_results(kind, version, status, monkeypatch):
    archive = (source_submission_archive if version == 1 else annual_submission)(kind, status)
    old_assessment = rf.assess_rf1086_source_dispatch(archive, query=query(archive),
        submission_id=archive.source_submission_claims[0].submission_id)
    old_position = rf.inspect_rf1086_source_dispatch_position(archive, query=query(archive),
        approval_id=rf.ApprovalId(archive.approvals[0].id))
    forbid_fresh(monkeypatch)
    assert assess(archive) == old_assessment
    assert position(archive) == old_position


@pytest.mark.parametrize('change', ['version', 'source-codec', 'source-type', 'annual-version',
    'annual-extra', 'annual-hash', 'annual-proof-hash', 'annual-text', 'actor', 'approval',
    'manifest-hash', 'record-actor', 'preview', 'scope', 'income-bool', 'review',
    'predecessor-shape', 'predecessor-id', 'predecessor-sha', 'predecessor-reason',
    'noncanonical', 'duplicate-key', 'wrong-record', 'wrong-actor-kind'])
def test_v3_header_rejects_malformed_identity_and_binding(change):
    value = retained_value(approved_v6())
    changes = {}
    if change in ('version', 'source-codec', 'source-type', 'annual-version', 'annual-extra',
                  'annual-hash', 'annual-proof-hash', 'annual-text', 'preview', 'scope',
                  'income-bool', 'review', 'predecessor-shape', 'predecessor-id',
                  'predecessor-sha', 'predecessor-reason'):
        def mutate(m):
            if change == 'version': m['schemaVersion'] = 'production-source-approval-v2'
            elif change == 'source-codec': m['source']['codec'] = 'rf1086-year-source-v1'
            elif change == 'source-type': m['source'] = []
            elif change == 'annual-version': m['annualReadiness']['schemaVersion'] = 'rf1086-annual-readiness-binding-v1'
            elif change == 'annual-extra': m['annualReadiness']['extra'] = None
            elif change == 'annual-hash': m['annualReadiness']['proofTextSha256'] = 'f' * 64
            elif change == 'annual-proof-hash': m['annualReadiness']['proofSha256'] = 'not-a-sha'
            elif change == 'annual-text': m['annualReadiness']['proofText'] = False
            elif change == 'preview': m['preview']['id'] = str(UUID(int=999))
            elif change == 'scope': m['companyId'] = str(UUID(int=999))
            elif change == 'income-bool': m['incomeYear'] = True
            elif change == 'review': m['review']['sha256'] = 'not-a-sha'
            else:
                prior = dict(submissionId=str(UUID(int=999)), manifestSha256='f' * 64, reason='Correction')
                if change == 'predecessor-shape': prior['extra'] = None
                if change == 'predecessor-id': prior['submissionId'] = False
                if change == 'predecessor-sha': prior['manifestSha256'] = 'invalid'
                if change == 'predecessor-reason': prior['reason'] = ' '
                m['predecessor'] = prior
        value = reheader(value, mutate)
    elif change == 'actor': changes['actor_id'] = ActorId(ActorKind.USER, UserId(str(UUID(int=999))))
    elif change == 'approval': changes['approval_id'] = rf.ApprovalId(str(UUID(int=999)))
    elif change == 'manifest-hash': changes['manifest_sha256'] = 'f' * 64
    elif change == 'record-actor': value = replace(value, approval=replace(value.approval, approved_by=str(UUID(int=999))))
    elif change == 'noncanonical': value = replace(value, manifest_text=value.manifest_text + ' ')
    elif change == 'duplicate-key': value = replace(value, manifest_text=value.manifest_text[:-1] + ',"incomeYear":2025}')
    elif change == 'wrong-record': value = value.approval
    elif change == 'wrong-actor-kind': changes['actor_id'] = ActorId(ActorKind.SYSTEM, ACTOR.subject)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        if change == 'wrong-record':
            rf.inspect_rf1086_retained_source_approval_v3(value, approval_id=rf.ApprovalId(value.id),
                manifest_sha256=value.manifest_hash, actor_id=ACTOR)
        else:
            inspect(value, **changes)


def test_header_preserves_predecessor_without_claiming_ancestry_or_current_eligibility():
    value = retained_value(approved_v6())
    prior = dict(submissionId=str(UUID(int=999)), manifestSha256='e' * 64, reason='Correction')
    value = reheader(value, lambda m: m.update(predecessor=prior))
    value = replace(value, approval=replace(value.approval,
        invalidated_at=value.approval.approved_at, invalidation_reason='Later source'))
    assert inspect(value) == rf.Rf1086SourceCorrectionPredecessor(
        rf.SubmissionId(prior['submissionId']), prior['manifestSha256'], prior['reason'])


def test_v3_header_is_not_a_source_or_annual_policy_validator():
    value = retained_value(approved_v6())
    def mutate(m):
        m['annualReadiness']['proofText'] = 'retained opaque proof bytes'
        m['annualReadiness']['proofTextSha256'] = sha256(m['annualReadiness']['proofText'].encode()).hexdigest()
        m['source']['sha256'] = 'b' * 64
        m['documentHashes'][0]['sha256'] = 'c' * 64
    assert inspect(reheader(value, mutate)) is None


def test_old_live_inspector_and_dispatch_still_reject_v3():
    archive = retained_submission()
    value = retained_value(archive)
    with pytest.raises(rf.Rf1086ProductionError):
        rf.inspect_rf1086_retained_source_approval(value, approval_id=rf.ApprovalId(value.approval.id),
            manifest_sha256=value.approval.manifest_hash, actor_id=ACTOR)
    with pytest.raises(rf.Rf1086ProductionError):
        rf.assess_rf1086_source_dispatch(archive, query=query(archive),
            submission_id=archive.source_submission_claims[0].submission_id)
    with pytest.raises(rf.Rf1086ProductionError):
        rf.inspect_rf1086_source_dispatch_position(archive, query=query(archive),
            approval_id=rf.ApprovalId(value.approval.id))


def pending_v3(index, *, failure='retryable', attempts=1):
    archive = retained_submission(status='accepted')
    mutations = tuple(e for e in archive.production_events
        if not e.operation_name.startswith('reconciliation:'))
    event = mutations[index]
    rows = (*mutations[:index], *(replace(event, id=str(UUID(int=8100 + n)),
        operation_state='failed', attempt=n, failure_class=failure,
        authority_reference=None, resulting_status='sending') for n in range(1, attempts + 1)))
    refs = {e.operation_name: e.authority_reference for e in rows if e.operation_state == 'succeeded'}
    return replace(archive, production_events=rows, feedback_artifacts=(),
        production_submissions=(replace(archive.production_submissions[0], status='sending',
            feedback_state='sent', feedback_artifact_count=0, authority_references=refs),))


@pytest.mark.parametrize('index', [0, 1, 2])
@pytest.mark.parametrize('failure,attempts,expected', [
    ('retryable', 1, 'retry_admission_required'), ('blocked', 1, 'blocked'),
    ('retryable', 20, 'blocked')])
def test_v3_retry_and_exhaustion_keep_original_key_without_creating_intent(index, failure, attempts, expected):
    archive = pending_v3(index, failure=failure, attempts=attempts)
    result = assess(archive)
    assert result.disposition == position(archive).disposition == expected
    event = archive.production_events[-1]
    assert (result.operation_id, result.attempt, result.idempotency_key) == (event.id, attempts, event.idempotency_key)
    assert result.pending_operation == event.operation_name


@pytest.mark.parametrize('state', ['unclaimed', 'first', 'started', 'confirmed'])
def test_v3_invalidation_changes_only_unstarted_approval_requirement(state):
    archive = (approved_v6() if state == 'unclaimed' else pending_v3(1) if state == 'started'
               else retained_submission(status='accepted' if state == 'confirmed' else 'approved'))
    approval = archive.approvals[0]
    assert position(archive).disposition == {
        'unclaimed': 'unclaimed', 'first': 'current_admission_required',
        'started': 'retry_admission_required', 'confirmed': 'confirmed'}[state]
    archive = replace(archive, approvals=(replace(approval, invalidated_at=approval.approved_at,
        invalidation_reason='Later source changed'),))
    expected = {'unclaimed': 'current_approval_required', 'first': 'current_approval_required',
                'started': 'retry_admission_required', 'confirmed': 'confirmed'}[state]
    assert position(archive).disposition == expected
    if state != 'unclaimed': assert assess(archive).disposition == expected
