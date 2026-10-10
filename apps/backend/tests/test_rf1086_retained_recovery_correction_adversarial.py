"""Independent retained recovery/correction boundaries; no live authority proof."""
from dataclasses import fields, replace
from hashlib import sha256
import json
from uuid import UUID, uuid5, NAMESPACE_URL

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import ActorId, ActorKind, UserId
from test_rf1086_archive_storage_v6 import forbid_fresh, query
from test_rf1086_retained_source_dispatch import retained_submission
from test_rf1086_source_correction import predecessor_snapshot
from test_rf1086_year_source import ACTOR

DIALOG = 'abcdef01-2345-6789-abcd-ef0123456789'
TRANSMISSION = 'fedcba98-7654-3210-fedc-ba9876543210'


def uid(name):
    return str(uuid5(NAMESPACE_URL, 'independent-retained-recovery:' + name))


def confirmation(archive, reference, index=0):
    selected = archive.production_submissions[index]
    return replace(archive, production_submissions=tuple(
        replace(row, authority_references={**row.authority_references, 'confirm': reference})
        if row.id == selected.id else row for row in archive.production_submissions),
        production_events=tuple(replace(row, authority_reference=reference)
            if row.submission_id == selected.id and row.operation_name == 'confirm' else row
            for row in archive.production_events))


def terminal():
    return confirmation(retained_submission(status='accepted'),
        json.dumps({'dialogId': DIALOG, 'forsendelseId': TRANSMISSION}, indent=2))


def prior(archive, index=0):
    row = archive.production_submissions[index]
    approval = next(item for item in archive.approvals if item.id == row.approval_id)
    return rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(row.id), approval.manifest_hash,
        '  Exact correction reason  ')


def invoke(archive, endpoint, *, index=0, **changes):
    if endpoint == 'recovery':
        row = archive.production_submissions[index]
        submission = rf.Rf1086Submission(**{field.name: getattr(row, field.name)
            for field in fields(rf.Rf1086Submission)})
        args = dict(query=query(archive), submission=submission,
            dialog_id=DIALOG, forsendelse_id=TRANSMISSION)
        return rf.prepare_rf1086_retained_source_reconciliation(archive, **(args | changes))
    return rf.prepare_rf1086_retained_correction_predecessor(archive,
        **(dict(query=query(archive), predecessor=prior(archive, index)) | changes))


def legacy_terminal(status='accepted'):
    snapshot = predecessor_snapshot(status)
    return rf.Rf1086ArchiveSnapshot(snapshot.company_id, snapshot.income_year,
        previews=(snapshot.preview,), approvals=(snapshot.approval,),
        production_submissions=(snapshot.submission,), production_events=snapshot.reconciliation_events,
        feedback_artifacts=snapshot.artifacts)


def corrected(terminal_child):
    """Append a real v3 predecessor manifest and a distinct retained child journal."""
    archive = terminal()
    parent, approval, line, claim = (archive.production_submissions[0], archive.approvals[0],
        archive.source_approval_lineage[0], archive.source_submission_claims[0])
    annual = rf.parse_rf1086_annual_readiness_v2(approval.manifest['annualReadiness']['proofText'],
        line.source, line.source_preview)
    manifest = rf.build_rf1086_source_approval_manifest_v3(rf.Rf1086SourceApprovalManifestBasisV3(
        line.source, line.source_preview, annual, ACTOR, approval.entitlement_id,
        line.review_sha256, tuple(approval.manifest['review']['acknowledgedWarningCodes']), prior(archive)))
    child_approval = replace(approval, id=uid('child-approval'), manifest=manifest.manifest,
        manifest_hash=manifest.manifest_sha256)
    child = replace(parent, id=uid('child-submission'), approval_id=child_approval.id,
        supersedes_submission_id=parent.id, status='accepted' if terminal_child else 'approved',
        feedback_state='accepted' if terminal_child else 'sent',
        authority_references=parent.authority_references if terminal_child else {},
        feedback_artifact_count=parent.feedback_artifact_count if terminal_child else 0)
    child_claim = replace(claim, approval_id=rf.ApprovalId(child_approval.id),
        submission_id=rf.SubmissionId(child.id), manifest_sha256=manifest.manifest_sha256,
        predecessor_submission_id=rf.SubmissionId(parent.id))
    child_line = replace(line, approval_id=child_approval.id, manifest_sha256=manifest.manifest_sha256,
        manifest_text=rf.serialize_rf1086_source_approval_manifest_v3(manifest))
    artifacts = tuple(replace(row, id=uid('artifact:' + row.id), document_id=uid('document:' + row.document_id),
        submission_id=child.id, sha256=sha256(('child:' + row.sha256).encode()).hexdigest())
        for row in archive.feedback_artifacts) if terminal_child else ()
    events = tuple(replace(row, id=uid('event:' + row.id), submission_id=child.id,
        idempotency_key=uid('key:' + row.id) if row.idempotency_key is not None else None,
        artifact_hashes=tuple(item.sha256 for item in artifacts) if row.artifact_hashes else ())
        for row in archive.production_events) if terminal_child else ()
    return replace(archive, approvals=(*archive.approvals, child_approval),
        source_approval_lineage=(*archive.source_approval_lineage, child_line),
        source_submission_claims=(*archive.source_submission_claims, child_claim),
        production_submissions=(*archive.production_submissions, child),
        production_events=(*archive.production_events, *events),
        feedback_artifacts=(*archive.feedback_artifacts, *artifacts),
        submission_head=replace(archive.submission_head, submission_id=child_claim.submission_id))


@pytest.mark.parametrize('terminal_child', [False, True])
def test_confirmed_ancestor_remains_recoverable_but_cannot_be_correction_head(terminal_child, monkeypatch):
    archive = corrected(terminal_child)
    forbid_fresh(monkeypatch)
    result = invoke(archive, 'recovery')
    assert result.hovedskjema_xml == archive.previews[0].hovedskjema_xml
    assert dict(result.underskjema_xml) == dict(archive.previews[0].underskjema_xml)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        invoke(archive, 'correction')
    if terminal_child:
        selected = invoke(archive, 'correction', index=1)
        assert selected.submission == archive.production_submissions[1]
        assert selected.approval.manifest['predecessor']['reason'] == prior(archive).reason
    else:
        with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
            invoke(archive, 'correction', index=1)


@pytest.mark.parametrize('endpoint', ['recovery', 'correction'])
@pytest.mark.parametrize('field', ['source_history', 'overrides', 'withdrawal_capture_records'])
def test_new_typed_entrypoints_require_v3_capture_sections(endpoint, field):
    archive = terminal()
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        invoke(replace(archive, **{field: None}), endpoint)


@pytest.mark.parametrize('endpoint', ['recovery', 'correction'])
@pytest.mark.parametrize('shape', ['actor-subclass', 'subject-string', 'subject-subclass', 'foreign-user'])
def test_actor_shapes_and_original_submitter_are_bound(endpoint, shape):
    archive = terminal()
    class ActorSubclass(ActorId):
        pass
    class UserSubclass(UserId):
        pass
    actors = {'actor-subclass': ActorSubclass(ActorKind.USER, ACTOR.subject),
        'subject-string': ActorId(ActorKind.USER, str(ACTOR.subject)),
        'subject-subclass': ActorId(ActorKind.USER, UserSubclass(str(ACTOR.subject))),
        'foreign-user': ActorId(ActorKind.USER, UserId(uid('other-owner')))}
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        invoke(archive, endpoint, query=replace(query(archive), actor_id=actors[shape]))


@pytest.mark.parametrize('field', ['dialog_id', 'forsendelse_id'])
@pytest.mark.parametrize('shape', ['uppercase', 'braces'])
def test_confirmation_uuid_canonicality_uses_genuinely_changed_alphabetic_values(field, shape):
    archive = terminal()
    canonical = DIALOG if field == 'dialog_id' else TRANSMISSION
    changed = canonical.upper() if shape == 'uppercase' else '{' + canonical + '}'
    assert changed != canonical and UUID(changed) == UUID(canonical)
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        invoke(archive, 'recovery', **{field: changed})


def test_pretty_confirmation_and_original_payload_are_preserved_without_fresh_builders(monkeypatch):
    archive = terminal()
    forbid_fresh(monkeypatch)
    result = invoke(archive, 'recovery')
    assert result.dialog_id == DIALOG and result.forsendelse_id == TRANSMISSION
    assert result.hovedskjema_xml == archive.previews[0].hovedskjema_xml
    assert dict(result.underskjema_xml) == dict(archive.previews[0].underskjema_xml)
    with pytest.raises(TypeError):
        result.underskjema_xml['changed'] = 'XML'


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('endpoint', ['recovery', 'correction'])
def test_legacy_unknown_coverage_uses_retained_semantics_without_rendering(version, endpoint, monkeypatch):
    from test_rf1086_source_submission_archive import source_submission_archive
    from test_rf1086_source_dispatch import annual_submission
    archive = (source_submission_archive if version == 1 else annual_submission)(status='accepted')
    archive = confirmation(archive, json.dumps({'dialogId': DIALOG, 'forsendelseId': TRANSMISSION}))
    assert archive.source_history is archive.overrides is archive.withdrawal_capture_records is None
    forbid_fresh(monkeypatch)
    result = invoke(archive, endpoint)
    if endpoint == 'correction':
        assert result.source_approval_lineage == archive.source_approval_lineage[0]
        assert result.source_claim == archive.source_submission_claims[0]
    else:
        assert result.hovedskjema_xml == archive.previews[0].hovedskjema_xml


@pytest.mark.parametrize('status', ['accepted', 'rejected'])
def test_genuine_no_activity_parent_keeps_original_snapshot_without_source_claim(status, monkeypatch):
    archive = legacy_terminal(status)
    forbid_fresh(monkeypatch)
    result = invoke(archive, 'correction')
    assert result.submission.status == status
    assert result.source_approval_lineage is result.source_claim is None
    assert result.artifacts == archive.feedback_artifacts


def append_legacy(archive, *, other_owner=False, child=False):
    from talli_backend.modules.shareholder_register_filing.preparation import _production_preview
    from talli_backend.modules.shareholder_register_filing.production import rf1086_current_manifest, rf1086_current_manifest_hash
    approval, submission = archive.approvals[0], archive.production_submissions[0]
    actor = uid('other-owner') if other_owner else approval.user_id
    preview = _production_preview(archive.previews[0])
    manifest = rf1086_current_manifest(preview, actor_id=actor, organization_number='123456789')
    extra_approval = replace(approval, id=uid('extra-approval'), user_id=actor, approved_by=actor,
        manifest=manifest, manifest_hash=rf1086_current_manifest_hash(preview,
            actor_id=actor, organization_number='123456789'))
    extra = replace(submission, id=uid('extra-submission'), approval_id=extra_approval.id,
        user_id=actor, submitted_by=actor, created_at='2099-01-01T00:00:00Z',
        supersedes_submission_id=submission.id if child else None)
    artifacts = tuple(replace(row, id=uid('extra-artifact:' + row.id),
        document_id=uid('extra-document:' + row.id), submission_id=extra.id)
        for row in archive.feedback_artifacts)
    events = tuple(replace(row, id=uid('extra-event:' + row.id), submission_id=extra.id)
        for row in archive.production_events)
    return replace(archive, approvals=(*archive.approvals, extra_approval),
        production_submissions=(*archive.production_submissions, extra),
        feedback_artifacts=(*archive.feedback_artifacts, *artifacts),
        production_events=(*archive.production_events, *events))


@pytest.mark.parametrize('change', ['other-owner-root', 'future-root', 'new-child', 'missing-parent', 'uncertain-head'])
def test_legacy_correction_enumerates_all_history_without_actor_time_or_profile_filter(change):
    from talli_backend.modules.shareholder_register_filing.preparation import _validate_retained_archive_source
    archive = legacy_terminal()
    selected = archive.production_submissions[0]
    if change in ('other-owner-root', 'future-root', 'new-child'):
        archive = append_legacy(archive, other_owner=change == 'other-owner-root', child=change == 'new-child')
    elif change == 'missing-parent':
        archive = replace(archive, production_submissions=(replace(selected,
            supersedes_submission_id=uid('missing-parent')),))
    else:
        archive = replace(archive, production_submissions=(replace(selected,
            status='unknown', feedback_state='unknown'),))
    if change != 'missing-parent':
        # Full archive consistency alone does not select the requested terminal leaf.
        assert _validate_retained_archive_source(query(archive), archive) is archive
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        invoke(archive, 'correction', predecessor=prior(legacy_terminal()))


def original_bound(archive):
    return replace(archive, feedback_artifacts=tuple(replace(row,
        original_id=uid('original:' + row.id), original_metadata_sha256='a' * 64,
        original_source_income_year=int(archive.income_year),
        original_retained_at='2026-01-03T02:00:00+02:00') for row in archive.feedback_artifacts))


def test_original_binding_is_preserved_as_exact_retained_metadata(monkeypatch):
    archive = original_bound(terminal())
    forbid_fresh(monkeypatch)
    selected = invoke(archive, 'correction')
    assert selected.artifacts == archive.feedback_artifacts
    assert all(row.original_retained_at == '2026-01-03T02:00:00+02:00' for row in selected.artifacts)


@pytest.mark.parametrize('change', ['partial-original', 'bool-year', 'naive-time', 'wrong-classification', 'wrong-reconciliation'])
def test_original_and_terminal_receipt_correspondence_cannot_be_filled_in(change):
    archive = original_bound(terminal())
    first, *rest = archive.feedback_artifacts
    if change == 'partial-original':first = replace(first, original_metadata_sha256=None)
    if change == 'bool-year':first = replace(first, original_source_income_year=True)
    if change == 'naive-time':first = replace(first, original_retained_at='2026-01-03T00:00:00')
    if change == 'wrong-classification':first = replace(first, classification='rejected')
    if change == 'wrong-reconciliation':
        archive = replace(archive, production_events=tuple(replace(row, artifact_hashes=(first.sha256,))
            if row.operation_name.startswith('reconciliation:') else row for row in archive.production_events))
    archive = replace(archive, feedback_artifacts=(first, *rest))
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        invoke(archive, 'correction')
