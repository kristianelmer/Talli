"""Final owner action is distinct, durable and never retried after uncertainty."""
import asyncio
from dataclasses import replace

import pytest

from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,ConfirmTaxDeliverySubmission,AdvanceTaxDelivery,TaxMutationKind,TaxFilingSubmissionId,
)
from talli_backend.shared.kernel import IdempotencyKey
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_journal_archive import complete_archive
from test_company_tax_delivery_submission import workflow
from test_company_tax_delivery_upload_workflow import upload_workflow
from test_company_tax_delivery_validation_workflow import validation_workflow
from test_company_tax_delivery_confirmation_workflow import confirmation_workflow
from test_company_tax_delivery_owner_review import prepared

pytestmark=pytest.mark.parametrize('workflow',[80],indirect=True)


@pytest.fixture
def submission_workflow(confirmation_workflow):
    session,_,_,_,state,*_=confirmation_workflow
    session.base=replace(session.base,contract_version='company-tax-source-v8',coverage=dict(session.base.coverage)|{
        'contractVersion':'company-tax-source-v8','declaredSubmissionExtentValid':True,'submissionCodecVersion':'tax-submission-evidence-v1'})
    state.update(submissionEnabled=True,submissionPuts=0,lostSubmission=False,on_submission=lambda:None)
    return confirmation_workflow


async def reviewed(fixture):
    session,service,*_=fixture;query=await prepared(fixture);artifact=await service.owner_review(session,query)
    command=ConfirmTaxDeliverySubmission(query.company_id,query.income_year,query.actor_id,TaxFilingSubmissionId(query.filing_id),
        IdempotencyKey('final-owner-confirmation'),query.correlation_id,query.expected_approval_sha256,artifact.sha256,True,True)
    recovery=AdvanceTaxDelivery(command.company_id,command.income_year,command.actor_id,command.filing_id,
        command.command_key,command.correlation_id,command.expected_approval_sha256)
    return command,recovery,artifact


@pytest.mark.parametrize('lost',[False,True])
def test_final_owner_confirmation_sends_one_separate_put_and_known_reads_resolve_it(submission_workflow,lost):
    session,service,_,calls,state,*_=submission_workflow
    async def exercise():
        command,recovery,artifact=await reviewed(submission_workflow)
        assert state['confirmationPuts']==1 and state['submissionPuts']==0
        state['lostSubmission']=lost
        result=await service.advance_submission(session,command)
        assert result.status=='uncertain' and result.mutation_kind is TaxMutationKind.CONFIRM_SUBMISSION
        assert state['submissionPuts']==1
        request=next(event.value for event in session.events if event.slot=='intent:confirm_submission')
        assert request.submission_prerequisite.owner_confirmation.owner_review_sha256==artifact.sha256
        if not lost:assert any(event.slot=='acknowledgment:confirm_submission' for event in session.events)
        count=len(calls)
        assert await service.advance_submission(session,command)==result and len(calls)==count
        complete=await service.reconcile_submission(session,recovery)
        assert complete.status=='mutation_completed' and all(method=='GET' for method,_ in calls[count:])
        assert state['confirmationPuts']==1 and state['submissionPuts']==1
        count=len(calls);assert await service.reconcile_submission(session,recovery)==complete and len(calls)==count
        assert await service.advance_submission(session,command)==complete and len(calls)==count
    asyncio.run(exercise())


@pytest.mark.parametrize('change',['review','source','owner','mfa','contract','auditor','result','file'])
def test_current_scope_source_owner_review_and_exact_ordinary_stage_are_required_before_submission(submission_workflow,change):
    session,service,_,_,state,*_=submission_workflow
    async def exercise():
        command,_,_=await reviewed(submission_workflow)
        if change=='review':command=replace(command,expected_owner_review_sha256='d'*64)
        elif change=='source':session.source=replace(session.source,upstream_sha256=session.source.upstream_sha256|{'annual':'d'*64})
        elif change=='owner':session.owner=False
        elif change=='mfa':session.fresh=False
        elif change=='contract':session.base=replace(session.base,coverage=dict(session.base.coverage)|{'declaredSubmissionExtentValid':False})
        elif change=='auditor':state['processElement']='Task_2Revisor'
        elif change=='result':state['resultBytes']+=b'\n'
        else:state['uploaded']+=b'\n'
        with pytest.raises(CompanyTaxError):await service.advance_submission(session,command)
        assert state['submissionPuts']==0 and not any(event.slot=='intent:confirm_submission' for event in session.events)
    asyncio.run(exercise())


@pytest.mark.parametrize('stage',['intent','acknowledgment','completion'])
def test_lost_commit_acknowledgment_never_elects_another_submission_put(submission_workflow,stage):
    session,service,_,_,state,*_=submission_workflow
    async def exercise():
        command,recovery,_=await reviewed(submission_workflow)
        if stage!='completion':
            session.lose=stage+':confirm_submission'
            with pytest.raises(CompanyTaxError):await service.advance_submission(session,command)
        else:
            await service.advance_submission(session,command);session.lose='completion:confirm_submission'
            with pytest.raises(CompanyTaxError):await service.reconcile_submission(session,recovery)
        count=state['submissionPuts'];await service.advance_submission(session,command)
        assert state['submissionPuts']==count
        complete=await service.reconcile_submission(session,recovery)
        assert complete.status==('uncertain' if stage=='intent' else 'mutation_completed')
        assert state['submissionPuts']==(0 if stage=='intent' else 1)
    asyncio.run(exercise())


def test_auditor_transition_stays_uncertain_and_terminal_recovery_needs_exact_receipt(submission_workflow):
    session,service,_,calls,state,*_=submission_workflow
    async def exercise():
        command,recovery,_=await reviewed(submission_workflow)
        state.update(afterSubmissionTask='confirmation',afterSubmissionElement='Task_2Revisor')
        await service.advance_submission(session,command);before=len(calls)
        pending=await service.reconcile_submission(session,recovery)
        assert pending.status=='uncertain' and len(calls)==before+1 and state['submissionPuts']==1
        state['terminal']=True
        assert (await service.reconcile_submission(session,recovery)).status=='uncertain'
        state['receiptBytes']=b'\xef\xbb\xbf <receipt outcome="unclassified"/>\n'
        complete=await service.reconcile_submission(session,recovery)
        assert complete.status=='mutation_completed' and state['submissionPuts']==1
        proof=next(event.value for event in session.events if event.slot=='completion:confirm_submission').submission_read_evidence
        assert proof.feedback.original.raw_bytes==state['receiptBytes']
    asyncio.run(exercise())


@pytest.mark.parametrize('change',['owner','mfa'])
def test_known_submission_ack_and_complete_read_survive_access_change_during_provider_io(submission_workflow,change):
    session,service,_,_,state,*_=submission_workflow
    def revoke():setattr(session,'owner' if change=='owner' else 'fresh',False)
    async def exercise():
        command,recovery,_=await reviewed(submission_workflow);state['on_submission']=revoke
        result=await service.advance_submission(session,command)
        assert result.status=='uncertain' and any(event.slot=='acknowledgment:confirm_submission' for event in session.events)
        with pytest.raises(CompanyTaxError):await service.reconcile_submission(session,recovery)
        session.owner=session.fresh=True;state['on_submission']=lambda:None
        state['on_file']=revoke
        complete=await service.reconcile_submission(session,recovery)
        assert complete.status=='mutation_completed' and state['submissionPuts']==1
    asyncio.run(exercise())


def test_later_receipt_is_retained_exactly_without_rewriting_submission_or_resending(submission_workflow):
    session,service,_,calls,state,*_=submission_workflow
    async def exercise():
        command,recovery,_=await reviewed(submission_workflow);await service.advance_submission(session,command)
        complete=await service.reconcile_submission(session,recovery)
        assert await service.reconcile_feedback(session,recovery)==complete
        state['receiptBytes']=b'\xef\xbb\xbf <receipt/>\n\xff';state['terminal']=True
        before=len(calls)
        assert await service.reconcile_feedback(session,recovery)==complete
        original=next(event.value for event in session.events if event.slot.startswith('observation:feedback:'))
        assert original.original.raw_bytes==state['receiptBytes']
        assert all(method=='GET' for method,_ in calls[before:]) and state['submissionPuts']==1
        assert await service.reconcile_feedback(session,recovery)==complete
        assert sum(event.slot.startswith('observation:feedback:') for event in session.events)==1
    asyncio.run(exercise())


def test_receipt_original_survives_owner_revocation_during_its_known_file_read(submission_workflow):
    session,service,_,_,state,*_=submission_workflow
    async def exercise():
        command,recovery,_=await reviewed(submission_workflow);await service.advance_submission(session,command)
        complete=await service.reconcile_submission(session,recovery)
        state['receiptBytes']=b'\xef\xbb\xbf <unclassified/>\n';state['terminal']=True
        state['on_feedback']=lambda:setattr(session,'owner',False)
        assert await service.reconcile_feedback(session,recovery)==complete
        assert any(event.slot.startswith('observation:feedback:') for event in session.events)
        with pytest.raises(CompanyTaxError):await service.reconcile_feedback(session,recovery)
        assert state['submissionPuts']==1
    asyncio.run(exercise())


@pytest.mark.parametrize('change',['owner','mfa'])
def test_current_document_read_access_loss_stops_before_the_next_validation_read(submission_workflow,change):
    session,service,_,calls,state,*_=submission_workflow
    async def exercise():
        command,_,_=await reviewed(submission_workflow)
        state['on_current']=lambda:setattr(session,'owner' if change=='owner' else 'fresh',False)
        before=len(calls)
        with pytest.raises(CompanyTaxError):await service.advance_submission(session,command)
        assert len(calls)==before+1 and calls[-1][1].startswith('/api/skattemelding/v2/2025/')
        assert state['submissionPuts']==0
    asyncio.run(exercise())


@pytest.mark.parametrize('change',['owner','mfa'])
def test_terminal_receipt_is_retained_before_access_loss_blocks_the_next_envelope_read(submission_workflow,change):
    session,service,_,calls,state,*_=submission_workflow
    async def exercise():
        command,recovery,_=await reviewed(submission_workflow);await service.advance_submission(session,command)
        state.update(terminal=True,receiptBytes=b'\xef\xbb\xbf <opaque/>\n\xff')
        state['on_feedback']=lambda:setattr(session,'owner' if change=='owner' else 'fresh',False)
        before=len(calls)
        with pytest.raises(CompanyTaxError):await service.reconcile_submission(session,recovery)
        assert len(calls)==before+2 and calls[-1][1].endswith('/data/00000000-0000-4000-8000-000000009999')
        original=next(event.value for event in session.events if event.slot.startswith('observation:feedback:'))
        assert original.original.raw_bytes==state['receiptBytes'] and not any(event.slot=='completion:confirm_submission' for event in session.events)
        assert state['submissionPuts']==1
    asyncio.run(exercise())
