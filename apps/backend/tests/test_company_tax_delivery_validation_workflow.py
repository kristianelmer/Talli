"""Finite validation starts once; lost job IDs have no invented recovery."""
import asyncio
from dataclasses import replace

import pytest

from talli_backend.adapters.company_tax_response_schemas import PinnedTaxValidationResponseSchemas
from talli_backend.modules.company_tax_filing.public import CompanyTaxError,TaxMutationKind
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_journal_archive import complete_archive
from test_company_tax_delivery_submission import workflow
from test_company_tax_delivery_upload_workflow import upload_workflow,created
from test_company_tax_validation_response_schemas import xml


@pytest.fixture
def validation_workflow(upload_workflow):
    session,service,_,_,state,*_=upload_workflow
    session.base=replace(session.base,contract_version='company-tax-source-v6',coverage=dict(session.base.coverage)|{
        'contractVersion':'company-tax-source-v6','declaredValidationExtentValid':True,'validationCodecVersion':'tax-validation-evidence-v1'})
    service._response_schemas=PinnedTaxValidationResponseSchemas();state['scan']='Clean'
    return upload_workflow


async def uploaded(fixture):
    session,service,*_=fixture
    command,creation=await created(fixture)
    upload=await service.advance_upload(session,command)
    assert upload.status=='mutation_completed'
    return command,creation,upload


def test_explicit_validation_starts_once_and_keeps_prior_operation_receipts(validation_workflow):
    session,service,_,calls,state,*_=validation_workflow
    async def exercise():
        command,creation,upload=await uploaded(validation_workflow)
        result=await service.advance_validation(session,command)
        assert result.status=='mutation_completed' and result.mutation_kind is TaxMutationKind.START_VALIDATION
        before=len(calls)
        assert await service.advance_validation(session,command)==result
        assert await service.advance_upload(session,command)==upload
        assert await service.advance(session,command)==creation
        assert await service.reconcile(session,command)==creation and len(calls)==before
        assert await service.reconcile_validation(session,command)==result
        assert session.events[-1].slot.startswith('observation:validation-result:')
        assert session.events[-1].value.inspect(service._response_schemas).result_code.value=='validertOK'
        count=len(session.events)
        assert await service.reconcile_validation(session,command)==result
        assert len(session.events)==count
    asyncio.run(exercise());assert state['validationPosts']==1 and sum(method=='POST' for method,_ in calls)==3


@pytest.mark.parametrize('failure',['lost','wrong-status'])
def test_unknown_start_cannot_lookup_a_job_or_repeat_start(validation_workflow,failure):
    session,service,_,calls,state,*_=validation_workflow
    async def exercise():
        command,*_=await uploaded(validation_workflow)
        if failure=='lost':state['lostValidation']=True
        else:state['startStatus']='FERDIG'
        unknown=await service.advance_validation(session,command)
        assert unknown.status=='uncertain'
        before=len(calls)
        assert await service.advance_validation(session,command)==unknown
        assert await service.reconcile_validation(session,command)==unknown and len(calls)==before
        assert session.events[-1].slot=='intent:start_validation'
    asyncio.run(exercise());assert state['validationPosts']==1


@pytest.mark.parametrize('scan',['Pending','Infected','Unknown'])
def test_nonclean_scan_retains_metadata_but_never_reads_file_or_starts(validation_workflow,scan):
    session,service,_,calls,state,*_=validation_workflow
    async def exercise():
        command,*_=await uploaded(validation_workflow);state['scan']=scan
        before=len(calls)
        with pytest.raises(CompanyTaxError):await service.advance_validation(session,command)
        assert all(not path.endswith('/data/') and '/data/' not in path for _,path in calls[before:])
        assert not any(event.slot=='intent:start_validation' for event in session.events)
    asyncio.run(exercise());assert state['validationPosts']==0


def test_owner_revoked_during_start_still_retains_exact_known_job_result(validation_workflow):
    session,service,_,_,state,*_=validation_workflow
    async def exercise():
        command,*_=await uploaded(validation_workflow)
        state['on_validation']=lambda:setattr(session,'owner',False)
        result=await service.advance_validation(session,command)
        assert result.status=='mutation_completed' and session.events[-1].slot=='completion:start_validation'
        with pytest.raises(CompanyTaxError):await service.reconcile_validation(session,command)
    asyncio.run(exercise());assert state['validationPosts']==1


@pytest.mark.parametrize('status',['NY','KJOERER','VENTER','AVBRUTT','FEILET','unrecognized'])
def test_nonfinished_status_retains_original_without_requesting_xml(validation_workflow,status):
    session,service,_,calls,state,*_=validation_workflow
    async def exercise():
        command,*_=await uploaded(validation_workflow);receipt=await service.advance_validation(session,command)
        state['jobStatus']=status;before=len(calls)
        assert await service.reconcile_validation(session,command)==receipt
        assert len(calls)==before+1 and calls[-1][1].endswith('/status')
        assert session.events[-1].slot.startswith('observation:validation-job:')
        assert not any(event.slot.startswith('observation:validation-result:') for event in session.events)
    asyncio.run(exercise())


@pytest.mark.parametrize('body',[xml(result='validertMedFeil'),b'<invalid/>'])
def test_rejected_or_unsupported_result_is_retained_without_claiming_tax_success(validation_workflow,body):
    session,service,_,_,state,*_=validation_workflow
    async def exercise():
        command,*_=await uploaded(validation_workflow);receipt=await service.advance_validation(session,command)
        state['resultBytes']=body
        if body==b'<invalid/>':
            with pytest.raises(CompanyTaxError):await service.reconcile_validation(session,command)
        else:assert await service.reconcile_validation(session,command)==receipt
        assert session.events[-1].value.original.raw_bytes==body
        assert not any(event.slot=='intent:prepare_confirmation' for event in session.events)
    asyncio.run(exercise())


@pytest.mark.parametrize('slot',['intent:start_validation','completion:start_validation'])
def test_validation_commit_ack_loss_never_elects_another_start(validation_workflow,slot):
    session,service,_,calls,state,*_=validation_workflow
    async def exercise():
        command,*_=await uploaded(validation_workflow);session.lose=slot
        with pytest.raises(CompanyTaxError):await service.advance_validation(session,command)
        before=len(calls);receipt=await service.advance_validation(session,command)
        assert receipt.status==('uncertain' if slot.startswith('intent:') else 'mutation_completed')
        assert len(calls)==before
    asyncio.run(exercise());assert state['validationPosts']==(0 if slot.startswith('intent:') else 1)
