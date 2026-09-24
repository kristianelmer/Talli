"""Review commitment and approval append share fresh source admission."""
import asyncio
from dataclasses import replace
import hashlib
import json
from uuid import uuid4

import pytest

from talli_backend.application.shareholder_register_source_approval import ShareholderRegisterSourceApprovalWorkflow
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CorrelationId
from test_rf1086_source_admission import AdmissionHarness, COMPANY, YEAR

ENTITLEMENT=str(uuid4())


class ApprovalHarness(AdmissionHarness):
    def __init__(self,kind='no_activity'):
        super().__init__(kind)
        self.review=rf.Rf1086SourceApprovalReview(COMPANY,YEAR,self.preview.preview_id,self.source.source_id,
            self.source.source_sha256,ENTITLEMENT,'a'*64,
            tuple(sorted({i.code for i in self.preview.readiness_issues if i.level=='warning'})),(),True)
        self.writes=[];self.append_error=None;self.result=rf.Rf1086RecordedResult(str(uuid4()),COMPANY,YEAR)
        async def bridge(preview):
            assert self.held and preview==self.preview
            self.calls.append('bridge');return preview.preview_id
        async def read(preview_id,entitlement_id):
            assert self.held and preview_id==self.preview.preview_id and entitlement_id==ENTITLEMENT
            self.calls.append('review');return self.review
        async def append(preview,entitlement_id,manifest,review_sha256):
            assert self.held and 'original' in self.calls and 'governance' in self.calls
            assert preview==self.preview and entitlement_id==ENTITLEMENT and review_sha256==self.review.review_sha256
            self.calls.append('append')
            if self.append_error:raise self.append_error
            self.writes.append(manifest);return self.result
        self.transaction.bridge_source_preview=bridge
        self.transaction.read_source_approval_context=read
        self.transaction.append_source_approval=append
        self.approval=ShareholderRegisterSourceApprovalWorkflow(self.workflow._sessions,self.workflow._documents)

    def approve(self,**changes):
        args=dict(company_id=COMPANY,income_year=YEAR,preview_id=self.preview.preview_id,entitlement_id=ENTITLEMENT,
            review_sha256=self.review.review_sha256,acknowledged_warning_codes=self.review.warning_codes,
            real_filing_confirmed=True,correlation_id=CorrelationId('source-approval'))
        args.update(changes)
        return asyncio.run(self.approval.approve('token',**args))


@pytest.mark.parametrize('kind',['no_activity','formation','transfer','dividend'])
def test_supported_source_approval_binds_manifest_and_commits_inside_original_guard(kind):
    h=ApprovalHarness(kind)
    assert h.approve()==h.result and h.committed
    assert h.calls.index('original') < h.calls.index('append') < h.calls.index('release')
    assert h.calls.count('guard')==1
    manifest=h.writes[0]
    assert manifest.manifest['caseProfile']=='rf1086_full_year_v1'
    assert manifest.manifest['source']['sha256']==h.source.source_sha256
    assert manifest.manifest['review']['sha256']==h.review.review_sha256
    assert manifest.manifest['userId']==str(h.actor.subject)
    text=rf.serialize_rf1086_source_approval_manifest(manifest)
    assert hashlib.sha256(text.encode()).hexdigest()==manifest.manifest_sha256
    assert json.loads(text)['preview']['id']==h.preview.preview_id.value


def test_review_materializes_bridge_but_never_appends_an_approval():
    h=ApprovalHarness()
    review=asyncio.run(h.approval.read_review('token',company_id=COMPANY,income_year=YEAR,
        preview_id=h.preview.preview_id,entitlement_id=ENTITLEMENT,correlation_id=CorrelationId('review')))
    assert review==h.review and h.committed and not h.writes
    assert h.calls.index('bridge') < h.calls.index('review') < h.calls.index('release')


@pytest.mark.parametrize('name,value',[('entitlement_id','bad'),('review_sha256','A'*64),
    ('review_sha256',None),('real_filing_confirmed',False),('real_filing_confirmed',1),
    ('acknowledged_warning_codes',[]),('acknowledged_warning_codes',('x','x')),
    ('acknowledged_warning_codes',(' ',))])
def test_invalid_direct_command_never_reads_original_bytes_or_enters_guard(name,value):
    h=ApprovalHarness()
    with pytest.raises(rf.ShareholderRegisterFilingError):h.approve(**{name:value})
    assert not h.calls and not h.writes


@pytest.mark.parametrize('kind',['review','warning','blocked','source','original','write-race','result-scope'])
def test_changed_or_blocked_facts_never_commit_approval(kind):
    h=ApprovalHarness();changes={}
    if kind=='review':changes['review_sha256']='b'*64
    if kind=='warning':changes['acknowledged_warning_codes']=('new-warning',)
    if kind=='blocked':h.review=replace(h.review,blockers=('hard_comment',),can_approve=False)
    if kind=='source':h.on_guard=lambda:setattr(h,'current',replace(h.source,source_sha256='f'*64))
    if kind=='original':h.receipt_failure=True
    if kind=='write-race':h.append_error=rf.Rf1086ProductionError('payload_changed')
    if kind=='result-scope':h.result=replace(h.result,company_id=type(COMPANY)(str(uuid4())))
    with pytest.raises((rf.Rf1086ProductionError,rf.Rf1086YearSourceError)):h.approve(**changes)
    assert not h.committed and not h.held
    if kind!='result-scope':assert not h.writes


@pytest.mark.parametrize('field,value',[('company_id',rf.CompanyId(str(uuid4()))),
    ('source_sha256','c'*64),('entitlement_id',str(uuid4())),('review_sha256','bad'),
    ('warning_codes',('invented',)),('blockers',('x','x')),('can_approve',False)],
    ids=['company','source-hash','entitlement','review-hash','warnings','blockers','verdict'])
def test_malformed_review_projection_is_never_approval_authority(field,value):
    h=ApprovalHarness();h.review=replace(h.review,**{field:value})
    with pytest.raises(rf.Rf1086ProductionError):h.approve(review_sha256='a'*64)
    assert not h.committed and not h.writes


def test_exact_correction_identity_is_bound_but_source_correction_does_not_invent_one():
    h=ApprovalHarness();prior=rf.Rf1086SourceCorrectionPredecessor(rf.SubmissionId(str(uuid4())),'c'*64,'Reviewed replacement')
    h.approve(predecessor=prior)
    assert dict(h.writes[0].manifest['predecessor'])=={
        'submissionId':prior.submission_id.value,'manifestSha256':prior.manifest_sha256,'reason':prior.reason}
    other=ApprovalHarness();other.approve();assert other.writes[0].manifest['predecessor'] is None


def test_manifest_serialization_refuses_wrong_digest_and_version():
    h=ApprovalHarness();h.approve();manifest=h.writes[0]
    with pytest.raises(rf.Rf1086ProductionError):rf.serialize_rf1086_source_approval_manifest(replace(manifest,manifest_sha256='f'*64))
    with pytest.raises(rf.Rf1086ProductionError):rf.serialize_rf1086_source_approval_manifest(replace(manifest,manifest={**manifest.manifest,'schemaVersion':'unknown'}))
