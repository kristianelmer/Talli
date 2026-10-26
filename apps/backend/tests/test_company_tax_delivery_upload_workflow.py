"""Explicit upload routes elect one committed effect and recover only by reads.

The unit commit fixture is complemented by native SQL and full signed topology;
it is not evidence of real provider dispatch or commercial/live authority.
"""
import asyncio
from dataclasses import replace
from datetime import timedelta
import json

import httpx
import pytest

from talli_backend.adapters.loopback_company_tax_delivery import LoopbackCompanyTaxDelivery
from talli_backend.modules.company_tax_filing.public import CompanyTaxError,TaxMutationKind
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_journal_archive import complete_archive
from test_company_tax_delivery_submission import workflow,advancing
from test_company_tax_delivery_journal import INSTANCE,DATA
from test_company_tax_delivery_observation import instance_document
from test_company_tax_validation_response_schemas import xml


@pytest.fixture
def upload_workflow(workflow):
    session,service,command,calls,response,clock,grant=workflow
    session.base=replace(session.base,contract_version='company-tax-source-v5',coverage=dict(session.base.coverage)|{
        'contractVersion':'company-tax-source-v5','declaredGuardedUploadExtentValid':True,'guardedUploadCodecVersion':'tax-guarded-upload-v1'})
    clock[0]=Timestamp(session.base.as_of.value+timedelta(seconds=1))
    def tick():
        clock[0]=Timestamp(clock[0].value+timedelta(milliseconds=1));return clock[0]
    session.current_time=tick
    state={'uploaded':None,'uploadPosts':0,'lost':False,'metadata':None,'on_metadata':lambda:None,
        'on_file':lambda:None,'on_upload':lambda:None,'on_current':lambda:None,
        'scan':'Pending','validationPosts':0,'lostValidation':False,'startStatus':'OPPRETTET','jobStatus':'FERDIG',
        'jobBody':None,'resultBytes':xml(),'on_validation':lambda:None,'on_job':lambda:None,'on_result':lambda:None}
    async def authority(request):
        assert session.active==[],'Every provider operation follows closed SQL contexts.'
        tick();calls.append((request.method,request.url.path))
        if request.method=='GET' and request.url.path.endswith('/storeDokument-workflow-v1/status'):
            state['on_job']()
            return httpx.Response(200,content=state['jobBody'],headers={'content-type':'application/json'}) if state['jobBody'] is not None else httpx.Response(200,json={
                'jobbStatus':state['jobStatus'],'forrigeStatus':'KJOERER','sekunderSidenOpprettelse':10,'sekunderSidenEndring':1})
        if request.method=='GET' and request.url.path.endswith('/storeDokument-workflow-v1/resultat'):
            state['on_result']();return httpx.Response(200,content=state['resultBytes'],headers={'content-type':'application/xml'})
        if request.method=='GET' and request.url.path=='/api/skattemelding/v2/2025/'+session.draft.envelope.source.organization_number:
            state['on_current']();return httpx.Response(200,content=session.draft.current_document.response.raw_bytes)
        if request.method=='POST' and request.url.path.endswith('/instances/'):
            assert any(event.slot=='intent:create_instance' for event in session.events)
            return httpx.Response(201,json={'id':INSTANCE})
        if request.method=='POST' and request.url.path.endswith('/start'):
            assert any(event.slot=='intent:start_validation' for event in session.events)
            assert json.loads(request.content)=={'appId':'skd/formueinntekt-skattemelding-v2','instansId':INSTANCE}
            state['validationPosts']+=1;state['on_validation']()
            if state['lostValidation']:raise httpx.ReadTimeout('synthetic validation start acknowledgement lost',request=request)
            return httpx.Response(200,json={'jobbId':'storeDokument-workflow-v1','jobbStatus':state['startStatus']})
        if request.method=='POST':
            assert request.url.path=='/skd/formueinntekt-skattemelding-v2/instances/'+INSTANCE+'/data'
            assert request.url.params['dataType']=='skattemeldingOgNaeringsspesifikasjon'
            assert request.content==session.draft.envelope.envelope_xml.encode()
            assert any(event.slot=='intent:upload_envelope' for event in session.events)
            state['uploadPosts']+=1;state['uploaded']=request.content;state['on_upload']()
            if state['lost']:raise httpx.ReadTimeout('synthetic upload acknowledgement lost',request=request)
            return httpx.Response(201,json={'id':DATA,'fileScanResult':'Pending'})
        if request.url.path.endswith('/data/'+DATA):
            state['on_file']();return httpx.Response(200,content=state['uploaded'],headers={'content-type':'application/xml'})
        assert request.method=='GET' and request.url.path.endswith('/instances/'+INSTANCE)
        state['on_metadata']()
        if state['metadata'] is not None:return httpx.Response(200,content=state['metadata'],headers={'content-type':'application/json'})
        value=instance_document(session.draft)
        if state['uploaded'] is not None:value['data']=[{'id':DATA,'dataType':'skattemeldingOgNaeringsspesifikasjon',
            'contentType':'application/xml','size':len(state['uploaded']),'fileScanResult':state['scan']}]
        return httpx.Response(200,json=value)
    service._authority=LoopbackCompanyTaxDelivery(service._runtime,transport=httpx.MockTransport(authority))
    return session,service,command,calls,state,clock,grant


async def created(fixture):
    session,service,command,*_=fixture
    approved=await service.approve(session,command);advance=advancing(command,approved)
    result=await service.advance(session,advance)
    assert result.status=='mutation_completed' and result.mutation_kind is TaxMutationKind.CREATE_INSTANCE
    return advance,result


def test_explicit_upload_posts_once_and_create_retries_keep_their_original_receipt(upload_workflow):
    session,service,_,calls,state,_,_=upload_workflow
    async def exercise():
        command,creation=await created(upload_workflow)
        result=await service.advance_upload(session,command)
        assert result.status=='mutation_completed' and result.mutation_kind is TaxMutationKind.UPLOAD_ENVELOPE
        before=len(calls)
        assert await service.advance_upload(session,command)==result
        assert await service.reconcile_upload(session,command)==result
        assert await service.advance(session,command)==creation
        assert await service.reconcile(session,command)==creation
        assert len(calls)==before
    asyncio.run(exercise());assert state['uploadPosts']==1


def test_lost_upload_response_reconciles_exact_metadata_and_file_without_another_post(upload_workflow):
    session,service,_,calls,state,_,_=upload_workflow
    async def exercise():
        command,creation=await created(upload_workflow);state['lost']=True
        unknown=await service.advance_upload(session,command)
        assert unknown.status=='uncertain'
        before=len(calls)
        assert await service.advance_upload(session,command)==unknown and len(calls)==before
        assert await service.reconcile(session,command)==creation and len(calls)==before
        result=await service.reconcile_upload(session,command)
        assert result.status=='mutation_completed' and result.mutation_kind is TaxMutationKind.UPLOAD_ENVELOPE
        evidence=session.events[-1].value.upload_read_evidence
        assert evidence.envelope.original.raw_bytes==session.draft.envelope.envelope_xml.encode()
        assert evidence.instance.inspection.envelope.scan_result=='Pending'
        assert calls[-2:]==[('GET','/skd/formueinntekt-skattemelding-v2/instances/'+INSTANCE),
            ('GET','/skd/formueinntekt-skattemelding-v2/instances/'+INSTANCE+'/data/'+DATA)]
        before=len(calls)
        assert await service.reconcile_upload(session,command)==result and len(calls)==before
    asyncio.run(exercise());assert state['uploadPosts']==1


@pytest.mark.parametrize('stage',['metadata','file','upload'])
def test_owner_change_stops_new_reads_but_preserves_already_known_upload_result(upload_workflow,stage):
    session,service,_,calls,state,_,_=upload_workflow
    async def exercise():
        command,_=await created(upload_workflow);state['lost']=stage!='upload'
        if stage=='upload':state['on_upload']=lambda:setattr(session,'owner',False)
        first=await service.advance_upload(session,command)
        if stage=='upload':
            assert first.status=='mutation_completed';return
        state['on_'+stage]=lambda:setattr(session,'owner',False)
        if stage=='metadata':
            before=len(calls)
            with pytest.raises(CompanyTaxError):await service.reconcile_upload(session,command)
            assert len(calls)==before+1 and session.events[-1].slot=='intent:upload_envelope'
        else:
            result=await service.reconcile_upload(session,command)
            assert result.status=='mutation_completed'
            assert session.events[-1].value.upload_read_evidence is not None
    asyncio.run(exercise());assert state['uploadPosts']==1


def test_different_file_bytes_are_retained_as_drift_without_resolving_or_resending(upload_workflow):
    session,service,_,_,state,_,_=upload_workflow
    async def exercise():
        command,_=await created(upload_workflow);state['lost']=True
        unknown=await service.advance_upload(session,command)
        state['uploaded']=b'<different/>'
        result=await service.reconcile_upload(session,command)
        assert result.status=='uncertain' and result.latest_event_sha256==unknown.latest_event_sha256
        assert session.events[-1].slot.startswith('observation:envelope:')
        assert session.events[-1].value.original.raw_bytes==b'<different/>'
        before=len(session.events)
        assert await service.reconcile_upload(session,command)==result and len(session.events)==before
    asyncio.run(exercise());assert state['uploadPosts']==1


@pytest.mark.parametrize('defect',['unknown-metadata','nonempty','source-drift','expiry'])
def test_no_upload_intent_or_post_when_prerequisites_change_before_commit(upload_workflow,defect):
    session,service,_,_,state,clock,grant=upload_workflow
    async def exercise():
        command,_=await created(upload_workflow)
        if defect=='unknown-metadata':state['metadata']=b'{}'
        elif defect=='nonempty':state['uploaded']=b'<external/>'
        elif defect=='source-drift':state['on_metadata']=lambda:setattr(session,'source',replace(session.source,
            upstream_sha256=dict(session.source.upstream_sha256)|{'annual':'f'*64}))
        else:state['on_metadata']=lambda:clock.__setitem__(0,grant.expires_at)
        with pytest.raises(CompanyTaxError):await service.advance_upload(session,command)
        assert not any(event.slot=='intent:upload_envelope' for event in session.events)
    asyncio.run(exercise());assert state['uploadPosts']==0
