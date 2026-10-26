"""Read evidence is guarded, durable, deduplicated and never a mutation retry."""
import asyncio
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from talli_backend.modules.company_tax_filing.public import CompanyTaxError,TaxDeliveryInstanceObservation
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_journal_archive import complete_archive
from test_company_tax_delivery_submission import workflow,advancing
from test_company_tax_delivery_observation import instance_document


@pytest.fixture
def read_workflow(workflow):
    session,service,command,calls,response,clock,grant=workflow
    session.base=replace(session.base,contract_version='company-tax-source-v4',coverage=dict(session.base.coverage)|{
        'contractVersion':'company-tax-source-v4','declaredObservationExtentValid':True,'observationCodecVersion':'tax-read-evidence-v1'})
    response['instance']=b'\xef\xbb\xbf'+json.dumps(instance_document(session.draft),indent=2).encode()+b'\n'
    return workflow


def test_review_retains_nonsecret_admission_and_known_instance_reads_preserve_mutation_truth(read_workflow):
    session,service,command,calls,response,clock,grant=read_workflow
    async def exercise():
        approval=await service.approve(session,command)
        assert [row.slot for row in session.events]==['review','admission']
        assert grant.credential not in session.events[1].value.canonical_json
        assert await service.approve(session,command)==approval
        advance=advancing(command,approval)
        created=await service.advance(session,advance)
        assert created.status=='mutation_completed'
        observed=await service.reconcile(session,advance)
        assert observed.status=='mutation_completed' and observed.mutation_kind.value=='create_instance'
        value=session.events[-1].value
        assert type(value) is TaxDeliveryInstanceObservation and value.original.raw_bytes==response['instance']
        assert value.inspection.empty_data and len(session.events)==5
        clock[0]=Timestamp(clock[0].value+timedelta(seconds=1))
        repeated=await service.reconcile(session,advance)
        assert repeated==observed and len(session.events)==5
        assert await service.approve(session,command)==approval
        clock[0]=grant.expires_at
        assert (await service.advance(session,advance)).status=='mutation_completed'
        with pytest.raises(CompanyTaxError):await service.reconcile(session,advance)
    asyncio.run(exercise())
    assert [method for method,_ in calls]==['GET','GET','POST','GET','GET']


def test_unknown_create_retains_admission_but_cannot_invent_an_instance_read(read_workflow):
    session,service,command,calls,response,clock,grant=read_workflow
    async def exercise():
        approval=await service.approve(session,command);advance=advancing(command,approval)
        response['lost']=True
        result=await service.advance(session,advance)
        assert result.status=='uncertain'
        clock[0]=grant.expires_at
        assert await service.reconcile(session,advance)==result
        assert await service.advance(session,advance)==result
    asyncio.run(exercise())
    assert [method for method,_ in calls]==['GET','GET','POST']
    assert [row.slot for row in session.events]==['review','admission','intent:create_instance']


@pytest.mark.parametrize('revoked',['owner','fresh'])
def test_owner_or_mfa_change_during_read_blocks_archive_append_and_disclosure(read_workflow,revoked):
    session,service,command,calls,response,_,_=read_workflow
    async def exercise():
        approval=await service.approve(session,command);advance=advancing(command,approval)
        await service.advance(session,advance)
        response['on_instance_get']=lambda:setattr(session,revoked,False)
        with pytest.raises(CompanyTaxError):await service.reconcile(session,advance)
        assert len(session.events)==4 and session.events[-1].slot=='completion:create_instance'
        # A previously observed create result is preserved, but a new read is
        # denied before network while current owner/MFA is absent.
        before=len(calls)
        with pytest.raises(CompanyTaxError):await service.reconcile(session,advance)
        assert len(calls)==before
    asyncio.run(exercise())


@pytest.mark.parametrize('body',[b'{"metadata":"unavailable"}',b'{not json'])
def test_unknown_metadata_original_is_retained_without_claiming_empty_or_submitted(read_workflow,body):
    session,service,command,_,response,_,_=read_workflow
    async def exercise():
        approval=await service.approve(session,command);advance=advancing(command,approval)
        await service.advance(session,advance);response['instance']=body
        result=await service.reconcile(session,advance)
        assert result.status=='mutation_completed'
        assert not session.events[-1].value.inspection.known
        assert not session.events[-1].value.inspection.empty_data
        assert session.events[-1].value.original.raw_bytes==body
    asyncio.run(exercise())


def test_foreign_instance_read_is_not_retained_and_lost_append_ack_reuses_first_original(read_workflow):
    session,service,command,_,response,clock,_=read_workflow
    async def exercise():
        approval=await service.approve(session,command);advance=advancing(command,approval)
        created=await service.advance(session,advance)
        good=response['instance'];document=instance_document(session.draft);document['instanceOwner']['organisationNumber']='999999999'
        response['instance']=json.dumps(document).encode()
        with pytest.raises(CompanyTaxError):await service.reconcile(session,advance)
        assert len(session.events)==4
        response['instance']=good
        # The fixture loses the commit acknowledgement for the actual content
        # identity, not a guessed slot. The committed original survives.
        def lost(slot):
            if slot.startswith('observation:'):session.lose=slot
        session.on_commit=lost
        with pytest.raises(CompanyTaxError):await service.reconcile(session,advance)
        session.on_commit=lambda slot:None
        first=session.events[-1]
        clock[0]=Timestamp(clock[0].value+timedelta(seconds=1))
        result=await service.reconcile(session,advance)
        assert result==created
        assert session.events[-1]==first and len(session.events)==5
    asyncio.run(exercise())


def test_lost_admission_commit_ack_keeps_the_whole_review_and_replays_without_io(read_workflow):
    session,service,command,calls,_,_,_=read_workflow
    # Model acknowledgement loss after the two-row review transaction commits.
    def failure(slot):
        if slot=='admission':raise CompanyTaxError.unavailable()
    # A lost acknowledgement commits both originals; recovery returns only the
    # immutable review receipt and performs no repeat authority request.
    session.on_commit=failure
    async def exercise():
        with pytest.raises(CompanyTaxError):await service.approve(session,command)
        assert [row.slot for row in session.events]==['review','admission']
        session.on_commit=lambda slot:None
        assert (await service.approve(session,command)).status=='reviewed'
    asyncio.run(exercise())
    assert [method for method,_ in calls]==['GET']


def legacy_contract(session):
    proof=dict(session.base.coverage)|{'contractVersion':'company-tax-source-v3'}
    proof.pop('declaredObservationExtentValid',None);proof.pop('observationCodecVersion',None)
    session.base=replace(session.base,contract_version='company-tax-source-v3',coverage=proof)
    session.events=[event for event in session.events if event.slot!='admission']


def test_predecessor_reader_preserves_replay_but_cannot_open_new_approval_or_first_dispatch(read_workflow):
    session,service,command,calls,_,_,_=read_workflow
    async def exercise():
        # A reader-first deployment against the predecessor must not open a
        # new review that cannot retain its nonsecret admission original.
        successor=session.base
        legacy_contract(session)
        with pytest.raises(CompanyTaxError):await service.approve(session,command)
        assert not session.events and not calls
        session.base=successor
        approved=await service.approve(session,command)
        legacy_contract(session)
        before=len(calls)
        assert await service.approve(session,command)==approved
        with pytest.raises(CompanyTaxError):await service.advance(session,advancing(command,approved))
        assert len(calls)==before and len(session.events)==1
    asyncio.run(exercise())


def test_predecessor_committed_unknown_intent_replays_without_missing_admission_or_provider_io(read_workflow):
    session,service,command,calls,response,_,_=read_workflow
    async def exercise():
        approved=await service.approve(session,command);advance=advancing(command,approved)
        response['lost']=True
        result=await service.advance(session,advance)
        legacy_contract(session)
        before=len(calls)
        assert await service.approve(session,command)==approved
        assert await service.advance(session,advance)==result
        assert await service.reconcile(session,advance)==result
        assert len(calls)==before
    asyncio.run(exercise())
