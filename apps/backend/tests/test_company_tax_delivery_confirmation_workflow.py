"""Confirmation PUT is submit-once; recovery never invokes process/next."""
import asyncio
from dataclasses import replace

import pytest

from talli_backend.adapters.company_tax_calculated_schemas import PinnedTax2025CalculatedSchemas
from talli_backend.modules.company_tax_filing.public import CompanyTaxError,TaxMutationKind
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_journal_archive import complete_archive
from test_company_tax_delivery_submission import workflow
from test_company_tax_delivery_upload_workflow import upload_workflow
from test_company_tax_delivery_validation_workflow import validation_workflow,uploaded
from test_company_tax_calculated_schemas import documents,result


@pytest.fixture
def confirmation_workflow(validation_workflow):
    session,service,_,_,state,*_=validation_workflow
    session.base=replace(session.base,contract_version='company-tax-source-v7',coverage=dict(session.base.coverage)|{
        'contractVersion':'company-tax-source-v7','declaredConfirmationExtentValid':True,'confirmationCodecVersion':'tax-confirmation-evidence-v1'})
    service._calculated_schemas=PinnedTax2025CalculatedSchemas()
    state|={'resultBytes':result(documents(session.draft)).raw_bytes,'processTask':'data','processElement':'Task_1','processFlow':1,
        'confirmationPuts':0,'lostPreparation':False,'on_confirmation':lambda:None,
        'processResponse':b'\xef\xbb\xbf {"currentTask":{"altinnTaskType":"confirmation"}}\n'}
    return validation_workflow


async def validated(fixture):
    session,service,*_=fixture
    command,creation,upload=await uploaded(fixture)
    validation=await service.advance_validation(session,command)
    assert validation.status=='mutation_completed'
    return command,creation,upload,validation


@pytest.mark.parametrize('lost',[False,True])
def test_successful_or_lost_put_ack_never_proves_preparation_and_recovery_uses_only_gets(confirmation_workflow,lost):
    session,service,_,calls,state,*_=confirmation_workflow
    async def exercise():
        command,creation,upload,validation=await validated(confirmation_workflow);state['lostPreparation']=lost
        prepared=await service.advance_confirmation(session,command)
        assert prepared.status=='uncertain' and prepared.mutation_kind is TaxMutationKind.PREPARE_CONFIRMATION
        assert state['confirmationPuts']==1
        if not lost:
            ack=next(event.value for event in session.events if event.slot=='acknowledgment:prepare_confirmation')
            assert ack.original.raw_bytes==state['processResponse']
        count=len(calls);assert await service.advance_confirmation(session,command)==prepared and len(calls)==count
        complete=await service.reconcile_confirmation(session,command)
        assert complete.status=='mutation_completed' and all(method=='GET' for method,_ in calls[count:])
        assert await service.reconcile_confirmation(session,command)==complete
        assert await service.advance_validation(session,command)==validation
        assert await service.advance_upload(session,command)==upload
        assert await service.advance(session,command)==creation
        assert state['confirmationPuts']==1
        evidence=next(event.value for event in session.events if event.slot=='completion:prepare_confirmation').confirmation_read_evidence
        assert evidence.instance.inspection.process_task=='confirmation' and evidence.envelope.original.sha256==session.draft.envelope.envelope_sha256
    asyncio.run(exercise())


@pytest.mark.parametrize('stage',['intent','acknowledgment','completion'])
def test_commit_acknowledgment_loss_does_not_elect_another_put(confirmation_workflow,stage):
    session,service,_,calls,state,*_=confirmation_workflow
    async def exercise():
        command,*_=await validated(confirmation_workflow)
        if stage!='completion':session.lose=stage+':prepare_confirmation'
        if stage in ('intent','acknowledgment'):
            with pytest.raises(CompanyTaxError):await service.advance_confirmation(session,command)
        else:
            await service.advance_confirmation(session,command);session.lose='completion:prepare_confirmation'
            with pytest.raises(CompanyTaxError):await service.reconcile_confirmation(session,command)
        before=state['confirmationPuts'];await service.advance_confirmation(session,command)
        assert state['confirmationPuts']==before
        result=await service.reconcile_confirmation(session,command)
        assert result.status==('uncertain' if stage=='intent' else 'mutation_completed')
        assert state['confirmationPuts']==(0 if stage=='intent' else 1)
    asyncio.run(exercise())


@pytest.mark.parametrize('task,element',[('data','Task_1'),('confirmation','Task_2Revisor'),('feedback','Task_3')])
def test_reconciliation_retains_other_known_stages_without_treating_them_as_owner_confirmation(confirmation_workflow,task,element):
    session,service,_,calls,state,*_=confirmation_workflow
    async def exercise():
        command,*_=await validated(confirmation_workflow);await service.advance_confirmation(session,command)
        state.update(processTask=task,processElement=element)
        before=len(calls);result=await service.reconcile_confirmation(session,command)
        assert result.status=='uncertain' and state['confirmationPuts']==1
        assert len(calls)==before+1 and calls[-1][0]=='GET'
        assert not any(event.slot=='completion:prepare_confirmation' for event in session.events)
    asyncio.run(exercise())


@pytest.mark.parametrize('stage',['job','result','metadata','file','put'])
def test_current_owner_changes_stop_new_work_but_keep_a_known_put_acknowledgment(confirmation_workflow,stage):
    session,service,_,calls,state,*_=confirmation_workflow
    async def exercise():
        command,*_=await validated(confirmation_workflow)
        state[{'job':'on_job','result':'on_result','metadata':'on_metadata','file':'on_file','put':'on_confirmation'}[stage]]=lambda:setattr(session,'owner',False)
        if stage=='put':
            receipt=await service.advance_confirmation(session,command)
            assert receipt.status=='uncertain' and any(event.slot=='acknowledgment:prepare_confirmation' for event in session.events)
        else:
            with pytest.raises(CompanyTaxError):await service.advance_confirmation(session,command)
            assert not any(event.slot=='intent:prepare_confirmation' for event in session.events)
        before=len(calls)
        with pytest.raises(CompanyTaxError):await service.reconcile_confirmation(session,command)
        assert len(calls)==before
    asyncio.run(exercise())


@pytest.mark.parametrize('defect',['rejected','malformed','foreign-party','no-documents','pending','source','current'])
def test_changed_validation_scope_scan_or_current_inputs_never_commit_a_confirmation_put(confirmation_workflow,defect):
    session,service,_,calls,state,*_=confirmation_workflow
    async def exercise():
        command,*_=await validated(confirmation_workflow)
        if defect=='rejected':state['resultBytes']=result(documents(session.draft),code='validertMedFeil').raw_bytes
        elif defect=='malformed':state['resultBytes']=b'<unknown/>'
        elif defect=='foreign-party':
            values=documents(session.draft);key='skattemeldingUpersonligEtterBeregning'
            values[key]=values[key].replace(session.draft.current_document.party_number.encode(),b'999999')
            state['resultBytes']=result(values).raw_bytes
        elif defect=='no-documents':
            from test_company_tax_validation_response_schemas import xml
            state['resultBytes']=xml()
        elif defect=='pending':state['scan']='Pending'
        elif defect=='source':session.source=replace(session.source,upstream_sha256=session.source.upstream_sha256|{'annual':'d'*64})
        else:state['on_current']=lambda:setattr(session,'owner',False)
        with pytest.raises(CompanyTaxError):await service.advance_confirmation(session,command)
        assert state['confirmationPuts']==0 and not any(event.slot=='intent:prepare_confirmation' for event in session.events)
    asyncio.run(exercise())
