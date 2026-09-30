"""The archive reads one filing year plus its original company-wide evidence."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import pytest

from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086ArchiveQuery,Rf1086ArchiveSnapshot,Rf1086SimulationRecord,
    Rf1086ReviewCommentRecord,Rf1086FilingPermissionRecord,Rf1086TestEvidenceRecord,
    ShareholderRegisterFilingError,create_rf1086_preparation_service,
)
from talli_backend.shared.kernel import CompanyId,IncomeYear
from test_rf1086_preparation import ACTOR,COMPANY,YEAR,NOW,CASES,preview

QUERY=Rf1086ArchiveQuery(COMPANY,YEAR,ACTOR)
OTHER=CompanyId('10000000-0000-4000-8000-000000000009')
EVIDENCE='60000000-0000-4000-8000-000000000006'


def simulation():
    case=CASES[0];result=case['result']
    return Rf1086SimulationRecord('50000000-0000-4000-8000-000000000005',preview().id,EVIDENCE,
        str(COMPANY),2025,preview().filing,'test_authority','test_authority',case['payload_hash'],case['idempotency_key'],
        result['status'],tuple(result['calls']),result['receipt_id'],tuple(result['feedback_document_ids']),
        tuple(case['feedback_items']),case['receipt_metadata'],case['submitted_payload_ref'],case['submitted_payload'],
        result['authority_confirmed_at'],result['preview_confirmed_at'],NOW,NOW,str(ACTOR.subject))


def snapshot():
    # This company-wide comment intentionally refers to a different year's
    # preview, whose payload must never be needed to read the comment.
    comment=Rf1086ReviewCommentRecord('comment','other-year-preview',str(COMPANY),'rf1086_preview',
        'advisory','Retained company-wide note',str(ACTOR.subject),None,None,NOW)
    permission=Rf1086FilingPermissionRecord('permission',str(COMPANY),'aksjonaerregisteroppgaven',
        str(ACTOR.subject),str(ACTOR.subject),NOW,False,NOW)
    evidence=Rf1086TestEvidenceRecord(EVIDENCE,str(COMPANY),'aksjonaerregisteroppgaven','manual_evidence',
        'accepted','original-reference','original-summary',None,None,None,None,str(ACTOR.subject),NOW)
    return Rf1086ArchiveSnapshot(COMPANY,YEAR,(preview(),),(simulation(),),(comment,),(permission,),(evidence,))


class Store:
    def __init__(self,result):self.result=result;self.queries=[]
    async def archive_source(self,query):self.queries.append(query);return self.result
    async def workspace(self,query):raise AssertionError('Archive must not request all-year workspace')


def read(result):return asyncio.run(create_rf1086_preparation_service(Store(result)).archive_source(QUERY))


def test_archive_preserves_exact_selected_payload_and_company_wide_comment_without_parent_decode():
    original=snapshot();store=Store(original)
    result=asyncio.run(create_rf1086_preparation_service(store).archive_source(QUERY))
    assert result is original and store.queries==[QUERY]
    assert result.review_comments[0].preview_id not in {p.id for p in result.previews}
    assert result.simulations[0].submitted_payload==simulation().submitted_payload
    with pytest.raises(TypeError):result.simulations[0].submitted_payload['incomeYear']=2024
    assert result.production_submissions==() and result.approvals==()


@pytest.mark.parametrize('change',[{'company_id':str(COMPANY)},{'income_year':None},{'income_year':2025},{'actor_id':str(ACTOR.subject)}])
def test_archive_query_requires_explicit_typed_scope(change):
    with pytest.raises(ShareholderRegisterFilingError):replace(QUERY,**change)


@pytest.mark.parametrize('change',[{'company_id':OTHER},{'income_year':IncomeYear(2024)}])
def test_archive_snapshot_scope_must_match_verified_query(change):
    with pytest.raises(ShareholderRegisterFilingError):read(replace(snapshot(),**change))


@pytest.mark.parametrize('field',['previews','simulations','review_comments','permissions','test_evidence'])
def test_archive_rejects_cross_company_rows_before_publishing(field):
    original=snapshot();record=getattr(original,field)[0]
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,**{field:(replace(record,company_id=str(OTHER)),)}))


@pytest.mark.parametrize('field',['previews','simulations'])
def test_archive_rejects_another_year_and_another_obligation(field):
    original=snapshot();record=getattr(original,field)[0]
    for change in ({'income_year':2024},{'filing':'skattemelding'}):
        with pytest.raises(ShareholderRegisterFilingError):read(replace(original,**{field:(replace(record,**change),)}))


@pytest.mark.parametrize('field',['permissions','test_evidence'])
def test_archive_rejects_sibling_obligation_evidence(field):
    original=snapshot();record=getattr(original,field)[0]
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,**{field:(replace(record,obligation='skattemelding'),)}))


@pytest.mark.parametrize('field',['previews','simulations','review_comments','permissions','test_evidence'])
def test_archive_rejects_duplicate_source_identity(field):
    original=snapshot();record=getattr(original,field)[0]
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,**{field:(record,record)}))


def test_archive_rejects_sibling_comment_target_and_unreferenced_evidence():
    original=snapshot()
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,review_comments=(replace(original.review_comments[0],target='company_tax_preview'),)))
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,test_evidence=(*original.test_evidence,replace(original.test_evidence[0],id='not-referenced'))))
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,test_evidence=()))


def test_simulation_mode_does_not_pull_authority_evidence_and_empty_year_is_retained():
    original=snapshot();result=replace(original,simulations=(replace(simulation(),mode='simulation'),),test_evidence=())
    assert read(result) is result
    empty=Rf1086ArchiveSnapshot(COMPANY,YEAR,review_comments=original.review_comments,permissions=original.permissions)
    assert read(empty) is empty


@pytest.mark.parametrize('field',['previews','simulations','review_comments','permissions','test_evidence'])
def test_archive_rejects_untyped_rows(field):
    with pytest.raises(ShareholderRegisterFilingError):read(replace(snapshot(),**{field:({'company_id':str(COMPANY)},)}))


def production_snapshot():
    from talli_backend.modules.shareholder_register_filing.public import (
        Rf1086ApprovalRecord, Rf1086ProductionSubmissionRecord,
        Rf1086ArchiveProductionEventRecord, Rf1086ArchiveFeedbackArtifactRecord,
    )
    from talli_backend.modules.shareholder_register_filing.preparation import _production_preview
    from talli_backend.modules.shareholder_register_filing.production import rf1086_current_manifest, rf1086_current_manifest_hash, rf1086_preview_payload_hash
    original=snapshot();p=_production_preview(original.previews[0]);actor=str(ACTOR.subject)
    manifest=rf1086_current_manifest(p,actor_id=actor,organization_number='123456789')
    approval=Rf1086ApprovalRecord('approval','entitlement',p.id,str(COMPANY),actor,2025,
        'aksjonaerregisteroppgaven','rf1086_no_activity_v1','rf1086-production-v1',rf1086_preview_payload_hash(p),
        rf1086_current_manifest_hash(p,actor_id=actor,organization_number='123456789'),manifest,actor,NOW,None,None)
    submission=Rf1086ProductionSubmissionRecord('submission',approval.id,'entitlement',str(COMPANY),actor,2025,
        approval.obligation,approval.case_profile,approval.payload_hash,approval.adapter_version,'production','accepted',
        {'confirmation':'original-reference'},None,None,actor,'accepted',1,NOW,NOW,None,None,NOW,NOW)
    artifact=Rf1086ArchiveFeedbackArtifactRecord('artifact',str(COMPANY),submission.id,'document','application/xml',13,'a'*64,NOW,
        'accepted','original-provider-reference')
    event=Rf1086ArchiveProductionEventRecord('event',str(COMPANY),2025,submission.id,'reconciliation:original','succeeded',1,
        None,None,None,None,'accepted',('a'*64,),None,None,NOW)
    return replace(original,approvals=(approval,),production_submissions=(submission,),production_events=(event,),feedback_artifacts=(artifact,))


def test_production_archive_preserves_immutable_original_manifests_journal_and_document_references():
    result=production_snapshot()
    assert read(result) is result
    assert result.feedback_artifacts[0].authority_reference=='original-provider-reference'
    assert result.production_events[0].artifact_hashes==('a'*64,)
    with pytest.raises(TypeError):result.approvals[0].manifest['payloadHash']='changed'
    with pytest.raises(TypeError):result.approvals[0].manifest['documentHashes'][0]['sha256']='changed'


@pytest.mark.parametrize('field',['approvals','production_submissions','production_events','feedback_artifacts'])
def test_production_archive_rejects_cross_company_duplicate_or_untyped_rows(field):
    original=production_snapshot();row=getattr(original,field)[0]
    for rows in ((replace(row,company_id=str(OTHER)),),(row,row),({'id':row.id},)):
        with pytest.raises(ShareholderRegisterFilingError):read(replace(original,**{field:rows}))


@pytest.mark.parametrize('field,change',[
    ('approvals',{'income_year':2024}),('production_submissions',{'income_year':2024}),
    ('production_events',{'income_year':2024}),('approvals',{'preview_id':'missing'}),
    ('approvals',{'manifest_hash':'b'*64}),('approvals',{'payload_hash':'b'*64}),
    ('production_submissions',{'approval_id':'missing'}),('production_submissions',{'payload_hash':'b'*64}),
    ('production_submissions',{'feedback_artifact_count':0}),('production_submissions',{'feedback_artifact_count':True}),
    ('production_submissions',{'supersedes_submission_id':'submission'}),
    ('production_submissions',{'supersedes_submission_id':'missing'}),
    ('production_events',{'submission_id':'missing'}),('production_events',{'artifact_hashes':('b'*64,)}),
    ('feedback_artifacts',{'submission_id':'missing'}),('feedback_artifacts',{'sha256':'invalid'}),
    ('feedback_artifacts',{'classification':'action_required'}),('feedback_artifacts',{'byte_length':0}),
])
def test_production_archive_rejects_wrong_year_references_hashes_counts_and_final_evidence(field,change):
    original=production_snapshot();row=getattr(original,field)[0]
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,**{field:(replace(row,**change),)}))


def test_production_archive_rejects_missing_receipt_or_modified_manifest_and_preserves_unknown_outcome():
    original=production_snapshot()
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,feedback_artifacts=()))
    approval=original.approvals[0]
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,approvals=(replace(approval,manifest=dict(approval.manifest,payloadHash='b'*64)),)))
    unknown=replace(original.production_submissions[0],status='unknown',feedback_state='unknown',feedback_artifact_count=0)
    result=replace(original,production_submissions=(unknown,),production_events=(),feedback_artifacts=())
    assert read(result).production_submissions[0].status=='unknown'


@pytest.mark.parametrize('change',[{}, {'artifact_hashes':()}, {'resulting_status':'processing'},
    {'operation_name':'confirm'}, {'operation_state':'unknown'}])
def test_terminal_archive_requires_matching_complete_final_reconciliation_journal(change):
    original=production_snapshot()
    events=(replace(original.production_events[0],**change),) if change else ()
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,production_events=events))


def test_terminal_status_cannot_hide_in_processing_feedback_state():
    original=production_snapshot()
    with pytest.raises(ShareholderRegisterFilingError):read(replace(original,
        production_submissions=(replace(original.production_submissions[0],feedback_state='processing',feedback_artifact_count=0),),
        feedback_artifacts=(),production_events=()))
