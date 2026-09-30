"""Source submission archives require complete claims, managed ancestry and journal bytes."""
from dataclasses import replace
from hashlib import sha256
import json
from uuid import UUID,uuid5,NAMESPACE_URL

import pytest

from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_full_year_correction import full_year_predecessor
from test_rf1086_source_approval_archive import read


def source_submission_archive(kind='formation',status='accepted'):
    parent=full_year_predecessor(kind,'rejected' if status=='rejected' else 'accepted')
    approval=parent.approval;submission=parent.submission;events=[];refs={}
    if status!='approved':
        for document in approval.manifest['documentHashes']:
            name='post_hovedskjema' if document['name']=='hovedskjema' else 'post_underskjema:'+document['name'].removeprefix('underskjema_')
            reference='main-reference' if name=='post_hovedskjema' else 'posted'
            events.append(replace(parent.reconciliation_events[0],id=str(uuid5(NAMESPACE_URL,name)),
                operation_name=name,body_hash=document['sha256'],idempotency_key=str(uuid5(NAMESPACE_URL,'key:'+name)),
                authority_reference=reference,resulting_status='sending',artifact_hashes=()))
            refs[name]=reference
        confirmation=json.dumps({'dialogId':'dialog-reference','forsendelseId':'filing-reference'},separators=(',',':'))
        events.append(replace(parent.reconciliation_events[0],id=str(UUID(int=980)),operation_name='confirm',
            body_hash=sha256(f'main-reference:{len(approval.manifest["documentHashes"])-1}'.encode()).hexdigest(),
            idempotency_key=str(UUID(int=981)),authority_reference=confirmation,resulting_status='received',artifact_hashes=()))
        refs['confirm']=confirmation
        events.extend(parent.reconciliation_events)
    submission=replace(submission,status=status,authority_references=refs,
        feedback_state='sent' if status=='approved' else parent.submission.feedback_state,
        feedback_artifact_count=0 if status=='approved' else parent.submission.feedback_artifact_count)
    head=rf.Rf1086SubmissionHead(parent.company_id,parent.income_year,'aksjonaerregisteroppgaven','production',
        parent.source_claim.submission_id,parent.source_claim.claimed_at)
    return rf.Rf1086ArchiveSnapshot(parent.company_id,parent.income_year,previews=(parent.preview,),
        approvals=(approval,),production_submissions=(submission,),production_events=tuple(events),
        feedback_artifacts=() if status=='approved' else parent.artifacts,
        source_approval_lineage=(parent.source_approval_lineage,),source_submission_claims=(parent.source_claim,),submission_head=head)


@pytest.mark.parametrize('kind',['no_activity','formation','dividend','cash_issue','loss_covering_reduction'])
@pytest.mark.parametrize('status',['approved','accepted','rejected'])
def test_archive_retains_original_source_claim_and_complete_submission_journal(kind,status):
    snapshot=source_submission_archive(kind,status)
    assert read(snapshot) is snapshot
    assert snapshot.submission_head.submission_id==snapshot.source_submission_claims[0].submission_id


@pytest.mark.parametrize('change',['missing-claim','extra-claim','duplicate-claim','claim-manifest','claim-payload',
    'claim-actor','claim-parent','missing-head','head-company','head-year','head-environment','head-obligation',
    'head-submission','head-time','head-fractional-year','missing-lineage','terminal-without-posts','wrong-body','wrong-operation',
    'wrong-confirmation-body','missing-key','key-reused','projection-reference','missing-confirmation',
    'unproven-reference','missing-feedback','missing-reconciliation'])
def test_incomplete_or_changed_source_submission_evidence_is_not_published(change):
    s=source_submission_archive();claim=s.source_submission_claims[0];head=s.submission_head;events=list(s.production_events)
    if change=='missing-claim':s=replace(s,source_submission_claims=())
    if change=='extra-claim':s=replace(s,source_submission_claims=(replace(claim,submission_id=rf.SubmissionId(str(UUID(int=999)))),))
    if change=='duplicate-claim':s=replace(s,source_submission_claims=(claim,claim))
    if change=='claim-manifest':s=replace(s,source_submission_claims=(replace(claim,manifest_sha256='f'*64),))
    if change=='claim-payload':s=replace(s,source_submission_claims=(replace(claim,payload_sha256='f'*64),))
    if change=='claim-actor':s=replace(s,source_submission_claims=(replace(claim,claimed_by=replace(claim.claimed_by,subject=type(claim.claimed_by.subject)(str(UUID(int=999))))),))
    if change=='claim-parent':s=replace(s,source_submission_claims=(replace(claim,predecessor_submission_id=rf.SubmissionId(str(UUID(int=999)))),))
    if change=='missing-head':s=replace(s,submission_head=None)
    if change=='head-company':s=replace(s,submission_head=replace(head,company_id=rf.CompanyId(str(UUID(int=999)))))
    if change=='head-year':s=replace(s,submission_head=replace(head,income_year=rf.IncomeYear(2024)))
    if change=='head-fractional-year':s=replace(s,submission_head=replace(head,income_year=rf.IncomeYear(float(head.income_year.value))))
    if change=='head-environment':s=replace(s,submission_head=replace(head,environment='test'))
    if change=='head-obligation':s=replace(s,submission_head=replace(head,obligation='company_tax'))
    if change=='head-submission':s=replace(s,submission_head=replace(head,submission_id=rf.SubmissionId(str(UUID(int=999)))))
    if change=='head-time':s=replace(s,submission_head=replace(head,updated_at='2026-01-01T00:00:00'))
    if change=='missing-lineage':s=replace(s,source_approval_lineage=())
    if change=='terminal-without-posts':s=replace(s,production_events=tuple(e for e in events if e.operation_name.startswith('reconciliation:')))
    if change=='wrong-body':events[0]=replace(events[0],body_hash='f'*64);s=replace(s,production_events=tuple(events))
    if change=='wrong-operation':events[0]=replace(events[0],operation_name='post_underskjema:other');s=replace(s,production_events=tuple(events))
    if change=='wrong-confirmation-body':s=replace(s,production_events=tuple(replace(e,body_hash='f'*64) if e.operation_name=='confirm' else e for e in events))
    if change=='missing-key':events[0]=replace(events[0],idempotency_key=None);s=replace(s,production_events=tuple(events))
    if change=='key-reused':events[1]=replace(events[1],idempotency_key=events[0].idempotency_key);s=replace(s,production_events=tuple(events))
    if change=='projection-reference':s=replace(s,production_submissions=(replace(s.production_submissions[0],authority_references={}),))
    if change=='missing-confirmation':s=replace(s,production_events=tuple(e for e in events if e.operation_name!='confirm'))
    if change=='unproven-reference':s=replace(s,production_submissions=(replace(s.production_submissions[0],authority_references={**s.production_submissions[0].authority_references,'unproven':'ref'}),))
    if change=='missing-feedback':s=replace(s,feedback_artifacts=())
    if change=='missing-reconciliation':s=replace(s,production_events=tuple(e for e in events if not e.operation_name.startswith('reconciliation:')))
    with pytest.raises(rf.ShareholderRegisterFilingError):read(s)


def test_archive_preserves_unknown_outcome_without_claiming_success_or_repeating_operation():
    s=source_submission_archive(status='approved');approval=s.approvals[0];submission=s.production_submissions[0]
    template=full_year_predecessor().reconciliation_events[0]
    event=replace(template,operation_name='post_hovedskjema',operation_state='unknown',resulting_status='unknown',
        body_hash=approval.manifest['documentHashes'][0]['sha256'],idempotency_key=str(UUID(int=990)),
        authority_reference=None,artifact_hashes=(),failure_class='unknown')
    s=replace(s,production_events=(event,),production_submissions=(replace(submission,status='unknown',failure_class='unknown'),))
    assert read(s) is s


def correction_archive():
    from test_rf1086_year_source import ACTOR
    parent=source_submission_archive();approval=parent.approvals[0];line=parent.source_approval_lineage[0]
    prior=rf.Rf1086SourceCorrectionPredecessor(parent.source_submission_claims[0].submission_id,approval.manifest_hash,'Corrected filing')
    manifest=rf.build_rf1086_source_approval_manifest(rf.Rf1086SourceApprovalManifestBasis(
        line.source,line.source_preview,ACTOR,approval.entitlement_id,line.review_sha256,
        tuple(approval.manifest['review']['acknowledgedWarningCodes']),prior))
    approval_id=str(UUID(int=804));submission_id=str(UUID(int=903))
    child_approval=replace(approval,id=approval_id,manifest=manifest.manifest,manifest_hash=manifest.manifest_sha256)
    child_line=replace(line,approval_id=approval_id,manifest_sha256=manifest.manifest_sha256,
        manifest_text=rf.serialize_rf1086_source_approval_manifest(manifest))
    child=replace(parent.production_submissions[0],id=submission_id,approval_id=approval_id,
        supersedes_submission_id=prior.submission_id.value,status='approved',feedback_state='sent',
        feedback_artifact_count=0,authority_references={})
    claim=replace(parent.source_submission_claims[0],submission_id=rf.SubmissionId(submission_id),
        approval_id=rf.ApprovalId(approval_id),manifest_sha256=manifest.manifest_sha256,predecessor_submission_id=prior.submission_id)
    return replace(parent,approvals=(*parent.approvals,child_approval),
        production_submissions=(*parent.production_submissions,child),source_approval_lineage=(*parent.source_approval_lineage,child_line),
        source_submission_claims=(*parent.source_submission_claims,claim),submission_head=replace(parent.submission_head,submission_id=claim.submission_id))


def test_archive_preserves_terminal_parent_and_new_claim_as_one_complete_history():
    s=correction_archive()
    assert read(s) is s
    assert len(s.source_submission_claims)==2
    with pytest.raises(rf.ShareholderRegisterFilingError):
        read(replace(s,submission_head=replace(s.submission_head,submission_id=s.source_submission_claims[0].submission_id)))
    with pytest.raises(rf.ShareholderRegisterFilingError):
        read(replace(s,production_submissions=(s.production_submissions[-1],)))


def test_managed_archive_rejects_fork_even_when_each_claim_matches_its_own_approval():
    s=correction_archive();approval=s.approvals[-1];line=s.source_approval_lineage[-1];child=s.production_submissions[-1];claim=s.source_submission_claims[-1]
    new_approval=str(UUID(int=805));new_submission=str(UUID(int=904))
    s=replace(s,approvals=(*s.approvals,replace(approval,id=new_approval)),
        source_approval_lineage=(*s.source_approval_lineage,replace(line,approval_id=new_approval)),
        production_submissions=(*s.production_submissions,replace(child,id=new_submission,approval_id=new_approval)),
        source_submission_claims=(*s.source_submission_claims,replace(claim,submission_id=rf.SubmissionId(new_submission),approval_id=rf.ApprovalId(new_approval))))
    with pytest.raises(rf.ShareholderRegisterFilingError):read(s)
