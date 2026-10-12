"""Pure retained recovery/ancestry; fixtures establish no writer or external authority."""
from dataclasses import fields, replace
from hashlib import sha256
import json
from uuid import UUID, uuid5, NAMESPACE_URL

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_archive_storage import query
from test_rf1086_archive_storage_v6 import forbid_fresh
from test_rf1086_retained_source_dispatch import retained_submission
from test_rf1086_source_correction import predecessor_snapshot
from test_rf1086_source_recovery import recovery_archive, prepare as old_recovery
from test_rf1086_source_submission_archive import source_submission_archive
from test_rf1086_year_source import ACTOR


KINDS = ('no_activity', 'formation', 'dividend', 'cash_issue', 'loss_covering_reduction', 'mixed')


def terminal_archive(kind='cash_issue', amendments=2, status='accepted'):
    return retained_submission(kind, amendments, status)


def predecessor(archive):
    row = archive.production_submissions[-1]
    approval = next(a for a in archive.approvals if a.id == row.approval_id)
    return rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(row.id),
        approval.manifest_hash, 'Original retained parent')


def recovery(archive, **changes):
    row = archive.production_submissions[0]
    confirmation = json.loads(row.authority_references['confirm'])
    args = dict(query=query(archive),
        submission=rf.Rf1086Submission(**{f.name: getattr(row, f.name) for f in fields(rf.Rf1086Submission)}),
        forsendelse_id=confirmation['forsendelseId'], dialog_id=confirmation['dialogId'])
    args.update(changes)
    return rf.prepare_rf1086_retained_source_reconciliation(archive, **args)


def correction(archive, **changes):
    args = dict(query=query(archive), predecessor=predecessor(archive))
    args.update(changes)
    return rf.prepare_rf1086_retained_correction_predecessor(archive, **args)


def legacy_terminal_archive(status='accepted'):
    snapshot = predecessor_snapshot(status)
    return rf.Rf1086ArchiveSnapshot(snapshot.company_id, snapshot.income_year,
        previews=(snapshot.preview,), approvals=(snapshot.approval,),
        production_submissions=(snapshot.submission,), production_events=snapshot.reconciliation_events,
        feedback_artifacts=snapshot.artifacts)


def corrected_archive():
    archive = terminal_archive()
    parent, approval, line = archive.production_submissions[0], archive.approvals[0], archive.source_approval_lineage[0]
    prior = predecessor(archive)
    proof = rf.parse_rf1086_annual_readiness_v2(approval.manifest['annualReadiness']['proofText'],
        line.source, line.source_preview)
    manifest = rf.build_rf1086_source_approval_manifest_v3(rf.Rf1086SourceApprovalManifestBasisV3(
        line.source, line.source_preview, proof, ACTOR, approval.entitlement_id,
        line.review_sha256, tuple(approval.manifest['review']['acknowledgedWarningCodes']), prior))
    child_id, approval_id = str(UUID(int=50002)), str(UUID(int=50003))
    child_approval = replace(approval, id=approval_id, manifest=manifest.manifest, manifest_hash=manifest.manifest_sha256)
    child_line = replace(line, approval_id=approval_id, manifest_sha256=manifest.manifest_sha256,
        manifest_text=rf.serialize_rf1086_source_approval_manifest_v3(manifest))
    child_claim = replace(archive.source_submission_claims[0], submission_id=rf.SubmissionId(child_id),
        approval_id=rf.ApprovalId(approval_id), manifest_sha256=manifest.manifest_sha256,
        predecessor_submission_id=rf.SubmissionId(parent.id))
    child = replace(parent, id=child_id, approval_id=approval_id, supersedes_submission_id=parent.id)
    artifacts = tuple(replace(row, id=str(UUID(int=50100+i)), document_id=str(UUID(int=50200+i)),
        submission_id=child_id, sha256=sha256(f'child-receipt-{i}'.encode()).hexdigest())
        for i, row in enumerate(archive.feedback_artifacts))
    events = tuple(replace(row, id=str(uuid5(NAMESPACE_URL, 'child:'+row.id)), submission_id=child_id,
        artifact_hashes=tuple(a.sha256 for a in artifacts) if row.operation_name.startswith('reconciliation:')
        else row.artifact_hashes) for row in archive.production_events)
    return replace(archive, approvals=(*archive.approvals, child_approval),
        source_approval_lineage=(*archive.source_approval_lineage, child_line),
        production_submissions=(parent, child), source_submission_claims=(*archive.source_submission_claims, child_claim),
        submission_head=replace(archive.submission_head, submission_id=child_claim.submission_id),
        feedback_artifacts=(*archive.feedback_artifacts, *artifacts), production_events=(*archive.production_events, *events))


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('amendments', [0, 1, 2])
@pytest.mark.parametrize('status', ['accepted', 'rejected'])
def test_v3_original_identity_and_terminal_projection_without_renderer(kind, amendments, status, monkeypatch):
    archive = terminal_archive(kind, amendments, status)
    forbid_fresh(monkeypatch)
    result = recovery(archive)
    selected = correction(archive)
    assert result.submission_id == selected.submission.id
    assert result.hovedskjema_xml == selected.preview.hovedskjema_xml
    assert result.underskjema_xml == selected.preview.underskjema_xml
    assert selected.source_approval_lineage is archive.source_approval_lineage[0]
    assert selected.source_claim is archive.source_submission_claims[0]
    assert selected.artifacts == tuple(sorted(archive.feedback_artifacts, key=lambda a: (a.document_id, a.id)))
    assert selected.submission.status == selected.submission.feedback_state == status


@pytest.mark.parametrize('status', ['accepted', 'rejected'])
def test_genuine_no_activity_parent_preserves_legacy_unknown_source_coverage(status, monkeypatch):
    archive = legacy_terminal_archive(status)
    forbid_fresh(monkeypatch)
    result = correction(archive)
    assert result == predecessor_snapshot(status)
    assert result.source_approval_lineage is result.source_claim is None
    assert archive.source_history is archive.overrides is archive.withdrawal_capture_records is None


@pytest.mark.parametrize('kind', KINDS[:-1])
def test_old_full_year_recovery_and_correction_results_stay_exact(kind, monkeypatch):
    archive = recovery_archive(kind)
    expected = old_recovery(archive)
    terminal = source_submission_archive(kind)
    forbid_fresh(monkeypatch)
    assert recovery(archive) == expected
    actual = correction(terminal)
    assert actual.submission == terminal.production_submissions[0]
    assert actual.source_approval_lineage == terminal.source_approval_lineage[0]


def test_confirmed_ancestor_recovers_while_only_terminal_leaf_can_be_correction_parent(monkeypatch):
    archive = corrected_archive()
    parent = archive.production_submissions[0]
    prior = rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(parent.id), archive.approvals[0].manifest_hash, 'Old parent')
    forbid_fresh(monkeypatch)
    assert recovery(archive).submission_id == parent.id
    assert correction(archive).submission.id == archive.production_submissions[-1].id
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        correction(archive, predecessor=prior)


@pytest.mark.parametrize('encoding', ['pretty', 'reordered'])
def test_original_confirmation_json_layout_is_not_recanonicalized(encoding):
    archive = terminal_archive()
    row = archive.production_submissions[0]
    refs = json.loads(row.authority_references['confirm'])
    text = json.dumps(refs, indent=2) if encoding == 'pretty' else json.dumps(dict(reversed(tuple(refs.items()))))
    archive = replace(archive, production_submissions=(replace(row,
        authority_references={**row.authority_references, 'confirm': text}),),
        production_events=tuple(replace(e, authority_reference=text) if e.operation_name == 'confirm' else e
            for e in archive.production_events))
    result = recovery(archive)
    assert (result.forsendelse_id, result.dialog_id) == (refs['forsendelseId'], refs['dialogId'])


@pytest.mark.parametrize('state', ['processing', 'action_required', 'unknown'])
def test_recovery_preserves_original_immutable_identity_subset(state):
    archive = terminal_archive()
    row = archive.production_submissions[0]
    supplied = rf.Rf1086Submission(**{f.name: getattr(row, f.name) for f in fields(rf.Rf1086Submission)})
    assert recovery(archive, submission=replace(supplied, feedback_state=state)) == recovery(archive)


@pytest.mark.parametrize('field', ['id', 'approval_id', 'entitlement_id', 'company_id', 'user_id', 'income_year',
    'obligation', 'case_profile', 'environment'])
def test_recovery_rejects_changed_original_identity(field):
    archive = terminal_archive()
    row = archive.production_submissions[0]
    supplied = rf.Rf1086Submission(**{f.name: getattr(row, f.name) for f in fields(rf.Rf1086Submission)})
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        recovery(archive, submission=replace(supplied, **{field: 2024 if field == 'income_year' else 'changed'}))


@pytest.mark.parametrize('field,value', [('manifest_sha256', 'f'*64), ('reason', ' '),
    ('submission_id', rf.SubmissionId(str(UUID(int=55555))))])
def test_correction_binds_requested_parent_hash_id_and_reason(field, value):
    archive = terminal_archive()
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        correction(archive, predecessor=replace(predecessor(archive), **{field: value}))


@pytest.mark.parametrize('change', ['missing-artifact', 'count', 'classification', 'duplicate-id', 'duplicate-document',
    'duplicate-hash', 'original-partial', 'original-year', 'reconciliation-set', 'reconciliation-status'])
def test_terminal_feedback_and_original_commitments_remain_strict(change):
    archive = terminal_archive()
    artifacts, events = list(archive.feedback_artifacts), list(archive.production_events)
    if change == 'missing-artifact': artifacts.pop()
    if change == 'count': archive = replace(archive, production_submissions=(replace(archive.production_submissions[0], feedback_artifact_count=True),))
    if change == 'classification': artifacts[0] = replace(artifacts[0], classification='rejected')
    if change == 'duplicate-id': artifacts[1] = replace(artifacts[1], id=artifacts[0].id)
    if change == 'duplicate-document': artifacts[1] = replace(artifacts[1], document_id=artifacts[0].document_id)
    if change == 'duplicate-hash': artifacts[1] = replace(artifacts[1], sha256=artifacts[0].sha256)
    if change == 'original-partial': artifacts[0] = replace(artifacts[0], original_id=str(UUID(int=55555)))
    if change == 'original-year': artifacts[0] = replace(artifacts[0], original_id=str(UUID(int=55555)),
        original_metadata_sha256='f'*64, original_source_income_year=2024, original_retained_at='2026-01-01T00:00:00+00:00')
    if change == 'reconciliation-set': events[-1] = replace(events[-1], artifact_hashes=())
    if change == 'reconciliation-status': events[-1] = replace(events[-1], resulting_status='rejected')
    with pytest.raises(rf.Rf1086ProductionError, match='basis_unavailable'):
        correction(replace(archive, feedback_artifacts=tuple(artifacts), production_events=tuple(events)))


def test_input_is_not_mutated_and_old_entrypoints_remain_v3_closed():
    archive = terminal_archive()
    before = rf.serialize_rf1086_archive_v6(archive, query=query(archive))
    selected = correction(archive)
    recovery(archive)
    assert rf.serialize_rf1086_archive_v6(archive, query=query(archive)) == before
    with pytest.raises(rf.Rf1086ProductionError):
        rf.assert_rf1086_correction_predecessor(selected, company_id=archive.company_id,
            income_year=archive.income_year, predecessor=predecessor(archive))
    with pytest.raises(rf.Rf1086ProductionError):
        old_recovery(archive)
