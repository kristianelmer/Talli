"""Source claims bind retained approval and recover without a second send grant."""
import asyncio
from dataclasses import replace
import hashlib
from uuid import uuid4

import pytest

from talli_backend.application.shareholder_register_source_claim import ShareholderRegisterSourceClaimWorkflow
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CorrelationId
from test_rf1086_source_approval import ApprovalHarness, ENTITLEMENT
from test_rf1086_source_correction import CorrectionHarness
from test_rf1086_year_source import COMPANY, YEAR, NOW as SOURCE_NOW


NOW = SOURCE_NOW.isoformat()


class ClaimHarness:
    def __init__(self, kind='no_activity', *, correction=False, snapshot=None):
        self.h = h = CorrectionHarness(snapshot=snapshot) if correction else ApprovalHarness(kind)
        h.approve(**({'predecessor': h.prior} if correction else {}))
        manifest = h.writes[0]
        self.approval_id = rf.ApprovalId(h.result.record_id)
        self.manifest_sha256 = manifest.manifest_sha256
        self.expected_head = h.prior.submission_id if correction else None
        self.retained = rf.Rf1086RetainedSourceApproval(rf.Rf1086ApprovalRecord(
            id=self.approval_id.value, entitlement_id=ENTITLEMENT, preview_id=h.preview.preview_id.value,
            company_id=str(COMPANY), user_id=str(h.actor.subject), income_year=int(YEAR),
            obligation='aksjonaerregisteroppgaven', case_profile='rf1086_full_year_v1',
            adapter_version='rf1086-source-production-v1',
            payload_hash=hashlib.sha256(rf.serialize_rf1086_source_preview(h.preview).encode()).hexdigest(),
            manifest_hash=manifest.manifest_sha256, manifest=manifest.manifest,
            approved_by=str(h.actor.subject), approved_at=NOW, invalidated_at=None, invalidation_reason=None),
            rf.serialize_rf1086_source_approval_manifest(manifest))
        self.locked_retained = self.retained
        self.claim = rf.Rf1086SourceSubmissionClaim(rf.SubmissionId(str(uuid4())),self.approval_id,
            COMPANY,YEAR,self.manifest_sha256,self.retained.approval.payload_hash,self.expected_head,h.actor,NOW)
        self.result = rf.Rf1086SourceSubmissionClaimResult(self.claim,True)
        self.existing = None
        self.on_read_approval = lambda: None
        h.calls.clear(); h.committed=False; h.writes.clear()
        owner=self
        base=h.approval._admission._sessions
        class Session:
            def __init__(self, delegate): self.delegate=delegate
            def __getattr__(self, name): return getattr(self.delegate,name)
            async def read_source_submission_claim(self,*args):
                assert not h.held; h.calls.append('recover'); return owner.existing
            async def read_source_claim_approval(self,*args):
                assert not h.held; h.calls.append('approval'); owner.on_read_approval(); return owner.retained
        class Sessions:
            async def session(self,token): return Session(await base.session(token))
        async def read(*args):
            assert h.held; h.calls.append('locked_approval'); return owner.locked_retained
        async def recover(*args):
            assert h.held; h.calls.append('locked_recover'); return owner.existing
        async def claim(*args):
            assert h.held and args==(owner.approval_id,owner.manifest_sha256,owner.expected_head,h.last_annual)
            h.calls.append('claim'); return owner.result
        h.transaction.read_source_claim_approval=read
        h.transaction.read_source_submission_claim=recover
        h.transaction.claim_source_submission=claim
        self.workflow=ShareholderRegisterSourceClaimWorkflow(Sessions(),h.approval._admission._documents)

    def run(self,**changes):
        args=dict(approval_id=self.approval_id,manifest_sha256=self.manifest_sha256,
            expected_head=self.expected_head,correlation_id=CorrelationId('source-claim'))
        args.update(changes)
        return asyncio.run(self.workflow.claim('token',**args))


@pytest.mark.parametrize('kind',['no_activity','formation','transfer','dividend'])
def test_claim_rebuilds_approved_source_under_one_guard(kind):
    c=ClaimHarness(kind); h=c.h
    assert c.run()==c.result and h.committed
    assert h.calls.index('bytes') < h.calls.index('guard') < h.calls.index('original')
    assert h.calls.index('locked_approval') < h.calls.index('review') < h.calls.index('claim') < h.calls.index('release')
    assert h.calls.count('guard')==1


def test_exact_historical_retry_skips_source_bytes_and_new_claim():
    c=ClaimHarness(); c.existing=c.claim
    c.retained=None; c.h.receipt_failure=True
    result=c.run()
    assert result.claim==c.claim and result.newly_claimed is False
    assert c.h.calls==['recover']


@pytest.mark.parametrize('mutation',['approval','source','review','blocked','original','payload'])
def test_changed_current_evidence_rolls_back_without_claim(mutation):
    c=ClaimHarness(); h=c.h
    if mutation=='approval': c.locked_retained=replace(c.retained,approval=replace(c.retained.approval,invalidated_at=NOW))
    if mutation=='source': h.on_guard=lambda:setattr(h,'current',replace(h.source,source_sha256='f'*64))
    if mutation=='review': h.review=replace(h.review,review_sha256='b'*64)
    if mutation=='blocked': h.review=replace(h.review,can_approve=False,blockers=('blocked',))
    if mutation=='original': h.receipt_failure=True
    if mutation=='payload':
        c.retained=replace(c.retained,approval=replace(c.retained.approval,payload_hash='c'*64))
        c.locked_retained=c.retained
    with pytest.raises((rf.Rf1086ProductionError,rf.Rf1086YearSourceError)):c.run()
    assert not h.committed and not h.held and 'claim' not in h.calls


@pytest.mark.parametrize('mutation',['invalidated','hash','predecessor','actor','text'])
def test_invalid_retained_approval_never_opens_admission(mutation):
    c=ClaimHarness(); changes={}
    if mutation=='invalidated':c.retained=replace(c.retained,approval=replace(c.retained.approval,invalidated_at=NOW))
    if mutation=='hash':changes['manifest_sha256']='b'*64
    if mutation=='predecessor':changes['expected_head']=rf.SubmissionId(str(uuid4()))
    if mutation=='actor':c.retained=replace(c.retained,approval=replace(c.retained.approval,approved_by=str(uuid4())))
    if mutation=='text':c.retained=replace(c.retained,manifest_text=c.retained.manifest_text+' ')
    with pytest.raises(rf.Rf1086ProductionError):c.run(**changes)
    assert 'bytes' not in c.h.calls and 'guard' not in c.h.calls


@pytest.mark.parametrize('field,value',[('approval_id','not-typed'),('manifest_sha256','A'*64),('expected_head','bad')])
def test_invalid_command_performs_no_io(field,value):
    c=ClaimHarness()
    with pytest.raises(rf.ShareholderRegisterFilingError):c.run(**{field:value})
    assert not c.h.calls


@pytest.mark.parametrize('phase',['locked','stale-source'])
def test_concurrent_commit_recovers_same_claim_without_granting_new_dispatch(phase):
    c=ClaimHarness(); h=c.h
    def change():
        c.existing=c.claim
        if phase=='stale-source':h.current=replace(h.source,source_sha256='f'*64)
    h.on_guard=change
    result=c.run()
    assert result==rf.Rf1086SourceSubmissionClaimResult(c.claim,False)
    assert 'claim' not in h.calls and not h.held
    if phase=='stale-source':assert h.calls[-2:]==['release','recover'] and not h.committed


@pytest.mark.parametrize('field,value',[('payload_sha256','f'*64),('company_id',rf.CompanyId(str(uuid4()))),
    ('approval_id',rf.ApprovalId(str(uuid4()))),('claimed_at','2026-01-01T00:00:00'),
    ('manifest_sha256','b'*64),('income_year',rf.IncomeYear(2023))])
def test_malformed_claim_result_aborts_transaction(field,value):
    c=ClaimHarness();c.result=replace(c.result,claim=replace(c.claim,**{field:value}))
    with pytest.raises(rf.Rf1086ProductionError):c.run()
    assert not c.h.committed and not c.h.held


def test_non_boolean_newly_claimed_is_not_dispatch_authority():
    c=ClaimHarness();c.result=replace(c.result,newly_claimed=1)
    with pytest.raises(rf.Rf1086ProductionError):c.run()
    assert not c.h.committed


def test_correction_verifies_originals_before_guard_and_compares_locked_snapshot():
    c=ClaimHarness(correction=True);h=c.h
    assert c.run()==c.result and h.committed
    assert next(i for i,call in enumerate(h.calls) if call.startswith('prior_bytes:')) < h.calls.index('guard')
    assert h.calls.index('prior_lock') < h.calls.index('claim')
    assert h.calls.count('prior_original')==2


def test_changed_correction_snapshot_prevents_claim():
    c=ClaimHarness(correction=True);h=c.h
    h.locked_snapshot=replace(h.locked_snapshot,submission=replace(h.locked_snapshot.submission,feedback_state='unknown'))
    with pytest.raises(rf.Rf1086ProductionError):c.run()
    assert not h.committed and 'claim' not in h.calls


def test_commit_between_historical_lookup_and_approval_read_is_recovered():
    c=ClaimHarness()
    def committed():
        c.existing=c.claim
        c.retained=replace(c.retained,approval=replace(c.retained.approval,invalidated_at=NOW))
    c.on_read_approval=committed
    assert c.run()==rf.Rf1086SourceSubmissionClaimResult(c.claim,False)
    assert c.h.calls==['recover','approval','recover']


@pytest.mark.parametrize('field,value',[
    ('manifest_hash','x'*64),('approved_at','bad'),('approved_at','2026-01-01T00:00:00'),
    ('income_year',True),('preview_id','bad'),('adapter_version','legacy'),
    ('case_profile','rf1086_no_activity_v1'),('manifest',{}),('invalidated_at','bad')])
def test_retained_approval_decoder_rejects_malformed_authority(field,value):
    c=ClaimHarness()
    c.retained=replace(c.retained,approval=replace(c.retained.approval,**{field:value}))
    with pytest.raises(rf.Rf1086ProductionError):c.run()
    assert 'bytes' not in c.h.calls and 'claim' not in c.h.calls


def test_full_year_predecessor_is_verified_before_claiming_its_correction():
    from test_rf1086_full_year_correction import full_year_predecessor
    c=ClaimHarness(correction=True,snapshot=full_year_predecessor('formation'))
    assert c.run()==c.result and c.h.committed
    assert c.result.claim.predecessor_submission_id==c.expected_head
    assert c.h.calls.index('prior_lock') < c.h.calls.index('claim')
    assert c.h.calls.count('prior_original')==2


@pytest.mark.parametrize('family', ['opening', 'ledger', 'banking', 'interview', 'documents'])
def test_changed_annual_owner_evidence_never_first_claims_old_approval(family):
    c = ClaimHarness(); h = c.h
    if family == 'opening':
        value = h.annual['annual_opening_inputs']
        h.annual['annual_opening_inputs'] = replace(value,
            opening_sources=(replace(value.opening_sources[0], source_digest='f'*64),))
    if family == 'ledger':
        value = h.annual['annual_ledger_inputs']
        h.annual['annual_ledger_inputs'] = replace(value,
            period_locks=(replace(value.period_locks[0], reason='Changed review'),))
    if family == 'banking':
        h.annual['bank_year_evidence'] = replace(h.annual['bank_year_evidence'], source_sha256='f'*64)
    if family == 'interview':
        h.annual['annual_interview'] = replace(h.annual['annual_interview'], updated_at='2026-09-29T12:00:00+00:00')
    if family == 'documents':
        value = h.annual['annual_document_inputs']
        h.annual['annual_document_inputs'] = replace(value,
            documents=(replace(value.documents[0], name='Updated annual reference.pdf'),))
    with pytest.raises(rf.Rf1086ProductionError, match='payload_changed'): c.run()
    assert 'claim' not in h.calls and not h.committed
