"""Known-job GETs use fixed paths; missing IDs/status never elect a lookup."""
import asyncio
from datetime import timedelta
import json

import httpx
import pytest

from talli_backend.adapters.loopback_company_tax_delivery import LoopbackCompanyTaxDelivery
from talli_backend.adapters.company_tax_response_schemas import PinnedTaxValidationResponseSchemas
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,CompanyTaxReturnAuthorityError,TaxMutationKind,TaxDeliveryCompletionOrigin,
    build_tax_delivery_mutation_request,complete_tax_delivery_mutation,
)
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_rehearsal import admitted
from test_company_tax_delivery_journal import INSTANCE
from test_company_tax_validation_response_schemas import xml


def setup(review_basis,handler):
    grant,runtime,clock,approval,draft=admitted(review_basis)
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.START_VALIDATION,target_instance=INSTANCE)
    started=complete_tax_delivery_mutation(request,approval,draft,response_bytes=b'{"jobbId":"storeDokument-known-v1","jobbStatus":"OPPRETTET"}',
        observed_at=clock[0],origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
    clock[0]=Timestamp(clock[0].value+timedelta(seconds=1))
    return LoopbackCompanyTaxDelivery(runtime,transport=httpx.MockTransport(handler)),grant,clock,approval,draft,request,started


def test_fixed_known_job_paths_retain_exact_status_and_xml_bytes(review_basis):
    calls=[];status_raw=b'\xef\xbb\xbf'+json.dumps({'jobbStatus':'FERDIG','forrigeStatus':'KJOERER',
        'sekunderSidenOpprettelse':10,'sekunderSidenEndring':1}).encode()+b'\n'
    result_raw=b'\xef\xbb\xbf'+xml()+b'\n'
    async def handler(request):
        assert request.method=='GET' and request.headers.get('authorization') is None
        calls.append(request)
        if request.url.path.endswith('/status'):return httpx.Response(200,content=status_raw,headers={'Content-Type':'application/json; charset=utf-8'})
        return httpx.Response(200,content=result_raw,headers={'Content-Type':'application/xml; charset=utf-8'})
    adapter,grant,clock,approval,draft,request,started=setup(review_basis,handler)
    async def exercise():
        status=await adapter.observe_validation_job(approval,draft,request,started)
        assert status.original.raw_bytes==status_raw
        clock[0]=Timestamp(clock[0].value+timedelta(seconds=1))
        validator=PinnedTaxValidationResponseSchemas()
        result=await adapter.observe_validation_result(approval,draft,request,started,status,schema_sha256=validator.schema_sha256)
        assert result.original.raw_bytes==result_raw and result.inspect(validator).result_code.value=='validertOK'
        expected='/api/skattemelding/v2/jobb/altinn/2025/'+draft.envelope.source.organization_number+'/storeDokument-known-v1/'
        assert [call.url.path for call in calls]==[expected+'status',expected+'resultat']
        assert all(call.headers['X-Talli-Rehearsal-Run']==grant.run_id and call.headers['X-Talli-Rehearsal-Key']==grant.credential for call in calls)
    asyncio.run(exercise())


@pytest.mark.parametrize('status',['NY','KJOERER','VENTER','AVBRUTT','FEILET','UNRECOGNIZED'])
def test_nonfinished_or_unknown_job_never_requests_a_result(review_basis,status):
    calls=[]
    async def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200,json={'jobbStatus':status,'forrigeStatus':None,'sekunderSidenOpprettelse':1,'sekunderSidenEndring':1})
    adapter,_,_,approval,draft,request,started=setup(review_basis,handler)
    async def exercise():
        observed=await adapter.observe_validation_job(approval,draft,request,started)
        with pytest.raises(CompanyTaxError):await adapter.observe_validation_result(approval,draft,request,started,observed,schema_sha256='a'*64)
    asyncio.run(exercise());assert len(calls)==1 and calls[0].endswith('/status')


@pytest.mark.parametrize('failure',['redirect','wrong-media','no-result'])
def test_result_requires_exact_successful_xml_response_without_retry(review_basis,failure):
    calls=[]
    async def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith('/status'):return httpx.Response(200,json={'jobbStatus':'FERDIG','forrigeStatus':'KJOERER','sekunderSidenOpprettelse':1,'sekunderSidenEndring':1})
        if failure=='redirect':return httpx.Response(302,headers={'Location':'https://foreign.example/private'})
        if failure=='wrong-media':return httpx.Response(200,json={'validertOK':True})
        return httpx.Response(204)
    adapter,_,_,approval,draft,request,started=setup(review_basis,handler)
    async def exercise():
        observed=await adapter.observe_validation_job(approval,draft,request,started)
        with pytest.raises(CompanyTaxReturnAuthorityError):await adapter.observe_validation_result(approval,draft,request,started,observed,schema_sha256='a'*64)
    asyncio.run(exercise());assert len(calls)==2


def test_unknown_start_has_no_generic_status_lookup(review_basis):
    calls=[]
    async def handler(request):calls.append(request);return httpx.Response(500)
    adapter,_,_,approval,draft,request,_=setup(review_basis,handler)
    with pytest.raises(CompanyTaxError):asyncio.run(adapter.observe_validation_job(approval,draft,request,None))
    assert calls==[]
