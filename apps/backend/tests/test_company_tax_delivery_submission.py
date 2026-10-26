"""Guarded review/intent/provider ordering and immutable recovery at the seam.

This workflow fixture models commits and claim loss; native SQL and signed-token
topology proofs separately establish real lock, role, RLS and current MFA policy.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.adapters.loopback_company_tax_delivery import LoopbackCompanyTaxDelivery
from talli_backend.application.company_tax_delivery_submission import CompanyTaxDeliverySubmission
from talli_backend.modules.company_tax_filing.public import (
    AdvanceTaxDelivery,ApproveTaxDeliveryDraft,CompanyTaxError,TaxDeliveryEventAppend,StoredTaxDeliveryEvent,
    StoredTaxDeliveryDraft,approve_tax_delivery_review,
    TaxDeliveryInstanceObservation,
    TaxDeliveryEnvelopeObservation,
)
from talli_backend.shared.kernel import CorrelationId,IdempotencyKey,Timestamp
from talli_backend.modules.company_tax_filing.public import TaxFilingSubmissionId
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_journal_archive import complete_archive
from test_company_tax_delivery_rehearsal import admitted


class Session:
    def __init__(self,snapshot,draft,actor):
        self.base=snapshot;self.draft=draft;self.actor_id=actor;self.events=[];self.active=[]
        self.source=draft.envelope.source;self.owner=self.fresh=True
        self.lose=None;self.on_commit=lambda slot:None;self.on_source=lambda:None
        self.guards=[];self.extra_drafts=[]
        self.current_time=None

    @asynccontextmanager
    async def transaction(self,*,snapshot=False):
        self.active.append(snapshot);before=list(self.events);last=None
        session=self
        class Transaction:
            async def lock_delivery_draft_archive(self,query):
                assert session.active==[False]
                session.guards.append(query)
                if not session.owner:raise CompanyTaxError.not_found()
                if not session.fresh:raise CompanyTaxError.mfa_required()
            async def journal_history_snapshot(self,query):
                assert session.active[-1] is True
                if not session.owner:raise CompanyTaxError.not_found()
                if not session.fresh:raise CompanyTaxError.mfa_required()
                return session.snapshot()
            async def append_delivery_event(self,value):
                nonlocal last
                assert session.active==[False]
                recorded=(session.current_time() if session.current_time is not None else Timestamp(session.base.as_of.value+timedelta(microseconds=len(session.events)+1)))
                event=StoredTaxDeliveryEvent(value,recorded,session.actor_id)
                if not event.slot.startswith('completion:'):
                    if not session.owner:raise CompanyTaxError.not_found()
                    if not session.fresh:raise CompanyTaxError.mfa_required()
                prior=next((row for row in session.events if row.slot==event.slot and row.binding.filing_id==event.binding.filing_id),None)
                if prior is not None:
                    if prior.value!=value and not (type(value) in (TaxDeliveryInstanceObservation,TaxDeliveryEnvelopeObservation)
                        and type(prior.value) is type(value)
                        and value.evidence_sha256==prior.value.evidence_sha256 and value.original==prior.value.original):
                        raise CompanyTaxError.draft_conflict()
                    return TaxDeliveryEventAppend(prior,False)
                session.events.append(event);last=event.slot
                return TaxDeliveryEventAppend(event,True)
        try:yield Transaction()
        except BaseException:
            self.events=before
            raise
        finally:self.active.pop()
        if last:
            self.on_commit(last)
            if self.lose is not None and self.lose in (row.slot for row in self.events[len(before):]):
                self.lose=None
                raise CompanyTaxError.unavailable()

    def snapshot(self):
        drafts=tuple(self.base.delivery_drafts)+tuple(self.extra_drafts)
        proof=dict(self.base.coverage)|{'deliveryDraftCount':len(drafts),
            'deliveryDraftDigests':{row.draft.filing_id:row.draft.sha256 for row in drafts},
            'deliveryEventCount':len(self.events),'deliveryEventDigests':{
                row.binding.filing_id+':'+row.slot:row.value.sha256 for row in self.events}}
        return replace(self.base,coverage=proof,delivery_events=tuple(self.events),delivery_drafts=drafts,
            as_of=(self.current_time() if self.current_time is not None else Timestamp(self.base.as_of.value+timedelta(microseconds=len(self.events)+2))))


@pytest.fixture
def workflow(review_basis,complete_archive,monkeypatch):
    _,base=complete_archive
    grant,runtime,clock,_,draft=admitted(review_basis,maximum_requests=20)
    base=replace(base,contract_version='company-tax-source-v4',coverage=dict(base.coverage)|{
        'contractVersion':'company-tax-source-v4','declaredObservationExtentValid':True,'observationCodecVersion':'tax-read-evidence-v1'})
    session=Session(replace(base,delivery_events=()),draft,review_basis['approved_by'])
    session.delivery_rehearsal_target=grant.database_scope_sha256
    calls=[];response={'lost':False,'on_get':lambda:None,'on_post':lambda:None,'instance':b'{"metadata":"unavailable"}'}
    async def authority(request):
        assert session.active==[],'Authority I/O must follow transaction commit.'
        calls.append((request.method,request.content))
        if request.method=='GET':
            if request.url.path.startswith('/skd/formueinntekt-skattemelding-v2/instances/') and 'instance' in response:
                response.get('on_instance_get',lambda:None)()
                return httpx.Response(200,content=response['instance'],headers={'content-type':'application/json; charset=utf-8'})
            response['on_get']()
            return httpx.Response(200,content=draft.current_document.response.raw_bytes)
        assert any(row.slot=='intent:create_instance' for row in session.events)
        response['on_post']()
        if response['lost']:raise httpx.ReadTimeout('synthetic result lost',request=request)
        return httpx.Response(201,content=response.get('body',b'\xef\xbb\xbf{"id":"123456/00000000-0000-4000-8000-000000000155"}\n'))
    provider=LoopbackCompanyTaxDelivery(runtime,transport=httpx.MockTransport(authority))
    service=CompanyTaxDeliverySubmission(runtime,provider,PinnedTax2025Schemas())
    async def source(transaction,query,*,correlation_id):
        assert session.active in ([True],[False,True])
        value=session.source;session.on_source();return value
    from talli_backend.application import company_tax_delivery_submission
    monkeypatch.setattr(company_tax_delivery_submission,'read_company_tax_delivery_source',source)
    command=ApproveTaxDeliveryDraft(draft.envelope.source.company_id,draft.envelope.source.income_year,
        session.actor_id,TaxFilingSubmissionId(draft.filing_id),IdempotencyKey('finite-review-command-v1'),
        CorrelationId('finite-review'),draft.sha256,draft.envelope.review_sha256)
    return session,service,command,calls,response,clock,grant


def advancing(command,approval):
    return AdvanceTaxDelivery(command.company_id,command.income_year,command.actor_id,command.filing_id,
        IdempotencyKey('finite-dispatch-command-v1'),CorrelationId('finite-dispatch'),approval.approval_sha256)


def test_review_and_first_mutation_preserve_exact_order_and_replay_without_authority_io(workflow):
    session,service,command,calls,_,_,_=workflow
    async def exercise():
        approved=await service.approve(session,command)
        assert approved.status=='reviewed'
        assert await service.approve(session,command)==approved
        result=await service.advance(session,advancing(command,approved))
        assert result.status=='mutation_completed'
        assert await service.advance(session,advancing(command,approved))==result
        # Approval retries keep the original immutable review receipt even after
        # a later operation has changed the current progress projection.
        assert await service.approve(session,command)==approved
        observed=await service.reconcile(session,advancing(command,approved))
        assert observed.status==result.status and observed.mutation_kind==result.mutation_kind
        assert observed.latest_event_sha256==session.events[-1].value.sha256
    asyncio.run(exercise())
    assert [method for method,_ in calls]==['GET','GET','POST','GET']
    assert [row.slot for row in session.events[:4]]==['review','admission','intent:create_instance','completion:create_instance']


def test_lost_create_response_never_reissues_even_with_changed_key_or_expired_run(workflow):
    session,service,command,calls,response,clock,grant=workflow
    async def exercise():
        approved=await service.approve(session,command);advance=advancing(command,approved)
        response['lost']=True
        result=await service.advance(session,advance)
        assert result.status=='uncertain'
        clock[0]=grant.expires_at
        assert await service.advance(session,replace(advance,command_key=IdempotencyKey('different-retry-command-v1')))==result
        assert await service.reconcile(session,advance)==result
    asyncio.run(exercise())
    assert [method for method,_ in calls]==['GET','GET','POST']
    assert len(session.events)==3


@pytest.mark.parametrize('lost',['review','intent:create_instance','completion:create_instance'])
def test_lost_commit_acknowledgement_replays_the_committed_original_without_duplicate_post(workflow,lost):
    session,service,command,calls,_,_,_=workflow
    async def exercise():
        if lost=='review':
            session.lose=lost
            with pytest.raises(CompanyTaxError):await service.approve(session,command)
            approved=await service.approve(session,command)
            assert approved.status=='reviewed'
            return
        approved=await service.approve(session,command);advance=advancing(command,approved)
        session.lose=lost
        with pytest.raises(CompanyTaxError):await service.advance(session,advance)
        replay=await service.advance(session,advance)
        assert replay.status==('uncertain' if lost.startswith('intent') else 'mutation_completed')
    asyncio.run(exercise())
    assert sum(method=='POST' for method,_ in calls)==(1 if lost.startswith('completion') else 0)
    assert len({row.slot for row in session.events})==len(session.events)


@pytest.mark.parametrize('change',['source','owner','mfa','expiry','original-command'])
def test_stale_review_or_current_access_cannot_open_approval_or_mutation(workflow,change):
    session,service,command,calls,_,clock,grant=workflow
    if change=='source':session.source=replace(session.source,upstream_sha256=dict(session.source.upstream_sha256)|{'annual':'f'*64})
    elif change=='owner':session.owner=False
    elif change=='mfa':session.fresh=False
    elif change=='expiry':clock[0]=grant.expires_at
    else:command=replace(command,expected_review_sha256='f'*64)
    with pytest.raises(CompanyTaxError):asyncio.run(service.approve(session,command))
    assert calls==[] and session.events==[]


@pytest.mark.parametrize('change',['owner','mfa','source'])
def test_change_during_authority_get_cannot_commit_review(workflow,change):
    session,service,command,calls,response,_,_=workflow
    def alter():
        if change=='owner':session.owner=False
        elif change=='mfa':session.fresh=False
        else:session.source=replace(session.source,upstream_sha256=dict(session.source.upstream_sha256)|{'annual':'f'*64})
    response['on_get']=alter
    with pytest.raises(CompanyTaxError):asyncio.run(service.approve(session,command))
    assert len(calls)==1 and session.events==[]


def test_mfa_expiry_during_source_enumeration_prevents_even_the_next_authority_get(workflow):
    session,service,command,calls,_,_,_=workflow
    session.on_source=lambda:setattr(session,'fresh',False)
    with pytest.raises(CompanyTaxError):asyncio.run(service.approve(session,command))
    assert calls==[] and session.events==[]


def test_bound_known_result_is_retained_after_revocation_and_source_change_during_post(workflow):
    session,service,command,calls,response,_,_=workflow
    async def exercise():
        approval=await service.approve(session,command)
        def change():
            session.owner=False;session.fresh=False
            session.source=replace(session.source,upstream_sha256=dict(session.source.upstream_sha256)|{'annual':'f'*64})
        response['on_post']=change
        result=await service.advance(session,advancing(command,approval))
        assert result.status=='mutation_completed'
    asyncio.run(exercise())
    assert len(session.events)==4 and calls[-1][0]=='POST'


def test_admission_expiring_after_intent_commit_leaves_uncertain_intent_without_post(workflow):
    session,service,command,calls,_,clock,grant=workflow
    async def exercise():
        approval=await service.approve(session,command)
        session.on_commit=lambda slot:clock.__setitem__(0,grant.expires_at) if slot.startswith('intent:') else None
        result=await service.advance(session,advancing(command,approval))
        assert result.status=='uncertain'
    asyncio.run(exercise())
    assert [method for method,_ in calls]==['GET','GET'] and len(session.events)==3


def test_new_filing_cannot_bypass_an_existing_retained_review_or_uncertain_effect(workflow,review_basis):
    session,service,command,calls,_,_,_=workflow
    other=replace(session.draft,filing_id=str(uuid4()),command_key=IdempotencyKey('another-tax-draft-command'))
    approval=approve_tax_delivery_review(**(review_basis|{'draft':other,'expected_draft_sha256':other.sha256}))
    session.extra_drafts=[StoredTaxDeliveryDraft(other,session.base.as_of)]
    session.events=[StoredTaxDeliveryEvent(approval,session.base.as_of,session.actor_id)]
    with pytest.raises(CompanyTaxError):asyncio.run(service.approve(session,command))
    assert calls==[] and len(session.events)==1
