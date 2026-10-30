"""Complete claimed correction history, real RF/Docs policy, explicit Auth/SQL doubles."""
import asyncio
from dataclasses import replace
from hashlib import sha256
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from talli_backend.modules.shareholder_register_filing import public as rf
from rf1086_retained_correction_fixture import correction_fixture, RetainedCorrectionHarness


def claimed_correction_fixture(status='rejected', amendments=0):
    parent_fixture=correction_fixture('source-v3','cash_issue',status,amendments,True)
    archive=parent_fixture.archive
    parent,approval,line=archive.production_submissions[-1],archive.approvals[-1],archive.source_approval_lineage[-1]
    manifest=json.loads(line.manifest_text)
    manifest['predecessor']={'submissionId':parent.id,'manifestSha256':approval.manifest_hash,
        'reason':parent_fixture.predecessor.reason}
    text=json.dumps(manifest,sort_keys=True,separators=(',', ':'),ensure_ascii=False)
    digest=sha256(text.encode()).hexdigest()
    child_approval=replace(approval,id=str(UUID(int=95101)),manifest=manifest,manifest_hash=digest)
    child_line=replace(line,approval_id=child_approval.id,manifest_text=text,manifest_sha256=digest)
    claim=replace(archive.source_submission_claims[-1],approval_id=rf.ApprovalId(child_approval.id),
        submission_id=rf.SubmissionId(str(UUID(int=95102))),manifest_sha256=digest,
        predecessor_submission_id=rf.SubmissionId(parent.id))
    child=replace(parent,id=claim.submission_id.value,approval_id=child_approval.id,
        supersedes_submission_id=parent.id,status='sending',feedback_state='sent',authority_references={},
        feedback_artifact_count=0)
    full=replace(archive,approvals=(*archive.approvals,child_approval),
        source_approval_lineage=(*archive.source_approval_lineage,child_line),
        source_submission_claims=(*archive.source_submission_claims,claim),
        production_submissions=(*archive.production_submissions,child),
        submission_head=replace(archive.submission_head,submission_id=claim.submission_id))
    return SimpleNamespace(parent_fixture=parent_fixture,archive=full,claim=claim,
        retained=rf.Rf1086RetainedSourceApproval(child_approval,text),lineage=child_line)


def project(item):
    return rf.prepare_rf1086_claimed_correction_predecessor_v3(item.archive,
        query=item.parent_fixture.query,claim=item.claim,retained=item.retained)


@pytest.mark.parametrize('status',['accepted','rejected'])
@pytest.mark.parametrize('amendments',[0,1,2])
def test_complete_current_claim_archive_projects_exact_parent_without_weakening_preclaim(status,amendments):
    item=claimed_correction_fixture(status,amendments)
    canonical=rf.serialize_rf1086_archive_v6(item.archive,query=item.parent_fixture.query)
    assert rf.parse_rf1086_retained_archive(canonical,query=item.parent_fixture.query)==item.archive
    before=item.archive
    assert project(item)==rf.prepare_rf1086_retained_correction_predecessor(item.parent_fixture.archive,
        query=item.parent_fixture.query,predecessor=item.parent_fixture.predecessor)
    with pytest.raises(rf.Rf1086ProductionError):
        rf.prepare_rf1086_retained_correction_predecessor(item.archive,query=item.parent_fixture.query,
            predecessor=item.parent_fixture.predecessor)
    assert item.archive==before


@pytest.mark.parametrize('fault',['missing-claim','duplicate-claim','missing-child','duplicate-child',
    'wrong-parent','wrong-actor','wrong-header','competing-root','competing-successor'])
def test_complete_operation_parent_projection_refuses_unbound_or_competing_history(fault):
    item=claimed_correction_fixture()
    archive=item.archive;child=archive.production_submissions[-1]
    if fault=='missing-claim':archive=replace(archive,source_submission_claims=archive.source_submission_claims[:-1])
    elif fault=='duplicate-claim':archive=replace(archive,source_submission_claims=(*archive.source_submission_claims,item.claim))
    elif fault=='missing-child':archive=replace(archive,production_submissions=archive.production_submissions[:-1])
    elif fault=='duplicate-child':archive=replace(archive,production_submissions=(*archive.production_submissions,child))
    elif fault=='wrong-parent':item.claim=replace(item.claim,predecessor_submission_id=rf.SubmissionId(str(UUID(int=95103))))
    elif fault=='wrong-actor':item.claim=replace(item.claim,claimed_by=replace(item.claim.claimed_by,subject=type(item.claim.claimed_by.subject)(str(UUID(int=95104)))))
    elif fault=='wrong-header':item.retained=replace(item.retained,manifest_text=item.retained.manifest_text+' ')
    else:
        other=replace(child,id=str(UUID(int=95105)),supersedes_submission_id=None if fault=='competing-root' else child.supersedes_submission_id)
        archive=replace(archive,production_submissions=(*archive.production_submissions,other))
    item.archive=archive
    with pytest.raises(rf.Rf1086ProductionError):project(item)


def configured_correction(item):
    h=RetainedCorrectionHarness(item.parent_fixture)
    h.archive=h.locked_archive=item.archive
    sessions=h.correction._sessions
    class Sessions:
        async def session(self,token):
            delegate=await sessions.session(token)
            class Session:
                actor_id=delegate.actor_id
                async def read_source_submission_claim(self,*args):return item.claim
                async def read_source_operation_approval_v3(self,*args):return item.retained
                async def read_retained_correction_archive(self,*args):return await delegate.read_retained_correction_archive(*args)
            return Session()
    h.correction._sessions=Sessions()
    return h


@pytest.mark.parametrize('status',['accepted','rejected'])
def test_configured_service_rechecks_complete_claimed_archive_and_actual_feedback_receipts(status):
    item=claimed_correction_fixture(status);h=configured_correction(item)
    async def run():
        verified=await h.correction.prepare_claimed_operation_v3('synthetic-token',claim=item.claim,retained=item.retained)
        assert verified.snapshot.submission.id==item.parent_fixture.predecessor.submission_id.value
        assert len(verified.originals)==len(verified.snapshot.artifacts)>0
        h.held=True
        try:await h.correction.assert_claimed_operation_admitted_v3(verified,h.transaction,
            claim=item.claim,retained=item.retained)
        finally:h.held=False
        return verified
    result=asyncio.run(run())
    assert sum(name.startswith('historical_bytes:') for name in h.calls)==len(result.originals)
    assert h.calls.count('historical_original')==len(result.originals)
    assert max(index for index,name in enumerate(h.calls) if name.startswith('historical_bytes:')) < h.calls.index('retained_prior_lock')
    assert h.calls.index('retained_prior_lock') < h.calls.index('historical_original')


@pytest.mark.parametrize('fault',['selected-evidence','parent-state','original-receipt'])
def test_configured_held_service_refuses_stale_parent_selection_or_original_identity(fault):
    item=claimed_correction_fixture();h=configured_correction(item)
    async def run():
        verified=await h.correction.prepare_claimed_operation_v3('synthetic-token',claim=item.claim,retained=item.retained)
        if fault=='selected-evidence':verified=replace(verified,selected_evidence=None)
        elif fault=='original-receipt':verified=replace(verified,originals=(replace(verified.originals[0],metadata_sha256='f'*64),*verified.originals[1:]))
        else:
            rows=h.locked_archive.production_submissions
            h.locked_archive=replace(h.locked_archive,production_submissions=(replace(rows[0],updated_at='2026-10-12T00:00:00+00:00'),*rows[1:]))
        h.held=True
        try:await h.correction.assert_claimed_operation_admitted_v3(verified,h.transaction,
            claim=item.claim,retained=item.retained)
        finally:h.held=False
    with pytest.raises(rf.Rf1086ProductionError):asyncio.run(run())
