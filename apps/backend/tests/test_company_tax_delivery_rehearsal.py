"""Technical admission confines exact approved bytes to a finite local run."""
import asyncio
import time
import json
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from talli_backend.application.company_tax_delivery_rehearsal import TaxDeliveryRehearsalAdmission,TaxDeliveryRehearsalRuntime,loopback_tax_database_scope
from talli_backend.adapters.loopback_company_tax_delivery import LoopbackCompanyTaxDelivery
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,CompanyTaxReturnAuthorityError,TaxMutationKind,approve_tax_delivery_review,
    build_tax_delivery_mutation_request,
)
from talli_backend.shared.kernel import Timestamp,ActorId,ActorKind,UserId
from test_company_tax_delivery_approval import review_basis


def recursive_result():
    raw=b'{"id":"123456/00000000-0000-4000-8000-000000000155","nested":'+b'['*10000+b'0'+b']'*10000+b'}'
    # Keep this a parser-recursion regression, not an unrelated missing-id path.
    with pytest.raises(RecursionError):json.loads(raw)
    return raw


def admitted(review_basis,**changes):
    draft=review_basis['draft'];now=draft.current_document.response.observed_at
    grant=TaxDeliveryRehearsalAdmission(**(dict(run_id=str(uuid4()),company_id=draft.envelope.source.company_id,
        income_year=draft.envelope.source.income_year,actor_id=review_basis['approved_by'],filing_id=draft.filing_id,
        draft_sha256=draft.sha256,organization_number=draft.envelope.source.organization_number,issued_at=now,
        expires_at=Timestamp(now.value+timedelta(minutes=10)),origin='http://127.0.0.1:17829',
        credential='d'*64,database_scope_sha256=loopback_tax_database_scope('127.0.0.1',17830,'postgres','tax_runtime'),maximum_requests=5)|changes))
    clock=[now]
    runtime=TaxDeliveryRehearsalRuntime(grant,now=lambda:clock[0])
    approval=approve_tax_delivery_review(**(review_basis|{'authority_context_sha256':grant.context_sha256}))
    return grant,runtime,clock,approval,draft


@pytest.mark.parametrize('origin',['https://api.skatteetaten.no','http://localhost:12345','http://127.0.0.2:12345',
    'http://127.0.0.1:12345/','http://127.0.0.1:12345?url=remote','http://127.0.0.1:12345#fragment',
    'http://user:password@127.0.0.1:12345','http://[::1]:12345','http://127.0.0.1:443','http://127.0.0.1:65536'])
def test_trusted_composition_cannot_accidentally_admit_another_authority_or_url(review_basis,origin):
    with pytest.raises(ValueError):admitted(review_basis,origin=origin)


def test_scope_expiry_and_budget_are_independently_required(review_basis):
    grant,runtime,clock,approval,draft=admitted(review_basis,maximum_requests=1)
    assert runtime.authorize(draft,approval.approved_by)==grant.context_sha256
    assert grant.credential not in repr(grant)
    with pytest.raises(CompanyTaxError):runtime.authorize(replace(draft,filing_id=str(uuid4())),approval.approved_by)
    with pytest.raises(CompanyTaxError):runtime.authorize(draft,ActorId(ActorKind.USER,UserId(str(uuid4()))))
    with pytest.raises(CompanyTaxError):runtime.consume(organization_number='999999999',income_year=2025)
    assert runtime.requests_used==0
    clock[0]=grant.expires_at
    with pytest.raises(CompanyTaxError):runtime.authorize(draft,approval.approved_by)
    clock[0]=Timestamp(grant.issued_at.value-timedelta(seconds=1))
    with pytest.raises(CompanyTaxError):runtime.authorize(draft,approval.approved_by)
    clock[0]=grant.issued_at
    runtime.consume(organization_number=grant.organization_number,income_year=2025)
    assert runtime.requests_used==1
    with pytest.raises(CompanyTaxError):runtime.authorize(draft,approval.approved_by)


@pytest.mark.parametrize('change',['too-long','zero','bool-budget','unbounded-budget','credential','run','digest'])
def test_admission_requires_finite_typed_configuration(review_basis,change):
    now=review_basis['draft'].current_document.response.observed_at
    changes={'too-long':{'expires_at':Timestamp(now.value+timedelta(hours=2))},'zero':{'expires_at':now},
        'bool-budget':{'maximum_requests':True},'unbounded-budget':{'maximum_requests':1001},
        'credential':{'credential':'not-a-local-run-secret'},'run':{'run_id':'unknown'},'digest':{'draft_sha256':'bad'}}[change]
    with pytest.raises(ValueError):admitted(review_basis,**changes)


def test_provider_sends_only_fixed_paths_and_exact_approved_body_with_no_ambient_credentials(review_basis,monkeypatch):
    grant,runtime,_,approval,draft=admitted(review_basis)
    monkeypatch.setenv('HTTPS_PROXY','http://must-not-be-used.invalid:8080')
    monkeypatch.setenv('ALTINN_TOKEN','must-not-be-read')
    seen=[];instance='123456/00000000-0000-4000-8000-000000000155'
    async def authority(request):
        assert request.url.host=='127.0.0.1' and request.url.port==17829
        assert request.headers['x-talli-rehearsal-key']==grant.credential
        assert request.headers['x-talli-rehearsal-run']==grant.run_id
        assert 'authorization' not in request.headers
        seen.append((request.method,request.url.path,request.content))
        return httpx.Response(200,content=draft.current_document.response.raw_bytes) if request.method=='GET' else httpx.Response(201,content=('\ufeff{"id":"'+instance+'"}\n').encode())
    provider=LoopbackCompanyTaxDelivery(runtime,transport=httpx.MockTransport(authority))
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.CREATE_INSTANCE)
    async def exercise():
        original=await provider.fetch_current_document(income_year=2025,company_org_number=grant.organization_number)
        assert original.raw_bytes==draft.current_document.response.raw_bytes
        result=await provider.execute(request,approval,draft)
        assert result.response_bytes==('\ufeff{"id":"'+instance+'"}\n').encode()
        result.assert_request(request,approval)
    asyncio.run(exercise())
    assert seen==[('GET','/api/skattemelding/v2/2025/'+grant.organization_number,b''),
        ('POST','/skd/formueinntekt-skattemelding-v2/instances/',request.body_bytes)]
    assert runtime.requests_used==2


@pytest.mark.parametrize('failure',['redirect','timeout','large','bad-result','deep-result'])
def test_uncertain_provider_response_is_never_followed_or_retried(review_basis,failure):
    _,runtime,_,approval,draft=admitted(review_basis);calls=[]
    async def authority(request):
        calls.append(request)
        if failure=='timeout':raise httpx.ReadTimeout('synthetic response lost',request=request)
        if failure=='redirect':return httpx.Response(307,headers={'location':'https://outside.invalid/forbidden'})
        if failure=='large':return httpx.Response(201,content=b' '*((8*1024*1024)+1))
        if failure=='deep-result':return httpx.Response(201,content=recursive_result())
        return httpx.Response(201,content=b'{}')
    provider=LoopbackCompanyTaxDelivery(runtime,transport=httpx.MockTransport(authority))
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.CREATE_INSTANCE)
    with pytest.raises(CompanyTaxReturnAuthorityError):asyncio.run(provider.execute(request,approval,draft))
    assert len(calls)==1 and runtime.requests_used==1


def test_other_mutations_expired_admission_and_changed_context_never_reach_http(review_basis):
    grant,runtime,clock,approval,draft=admitted(review_basis);calls=[]
    async def authority(request):calls.append(request);return httpx.Response(500)
    provider=LoopbackCompanyTaxDelivery(runtime,transport=httpx.MockTransport(authority))
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.CREATE_INSTANCE)
    changed=replace(approval,authority_context_sha256='a'*64)
    changed_request=build_tax_delivery_mutation_request(changed,draft,TaxMutationKind.CREATE_INSTANCE)
    with pytest.raises(CompanyTaxError):asyncio.run(provider.execute(changed_request,changed,draft))
    upload=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.UPLOAD_ENVELOPE,
        target_instance='123456/00000000-0000-4000-8000-000000000155')
    with pytest.raises(CompanyTaxError):asyncio.run(provider.execute(upload,approval,draft))
    clock[0]=grant.expires_at
    with pytest.raises(CompanyTaxError):asyncio.run(provider.execute(request,approval,draft))
    assert calls==[] and runtime.requests_used==0


@pytest.mark.parametrize('target',[
    'invalid-connection-info',
    'host=db.example.invalid port=5432 dbname=postgres user=tax_runtime',
    'host=localhost port=17830 dbname=postgres user=tax_runtime',
    'host=127.0.0.1 hostaddr=192.0.2.1 port=17830 dbname=postgres user=tax_runtime',
    'host=127.0.0.1 port=17830 dbname=postgres user=postgres',
    "host=127.0.0.1 port=17830 dbname='host=other' user=tax_runtime",
])
def test_actual_connector_never_advertises_a_hosted_ambiguous_or_admin_target(review_basis,target):
    from talli_backend.adapters.postgres_company_tax_filing import PostgresCompanyTaxSession
    from talli_backend.adapters.supabase_ledger import _VerifiedActor
    session=PostgresCompanyTaxSession(target,_VerifiedActor(review_basis['approved_by'],'{}'))
    assert session.delivery_rehearsal_target is None


@pytest.mark.parametrize('override',['PGHOSTADDR','PGSERVICE'])
def test_ambient_connection_overrides_cannot_spoof_a_loopback_target(review_basis,monkeypatch,override):
    from talli_backend.adapters.postgres_company_tax_filing import PostgresCompanyTaxSession
    from talli_backend.adapters.supabase_ledger import _VerifiedActor
    _,runtime,_,_,_=admitted(review_basis)
    session=PostgresCompanyTaxSession('host=127.0.0.1 port=17830 dbname=postgres user=tax_runtime',
        _VerifiedActor(review_basis['approved_by'],'{}'))
    assert session.delivery_rehearsal_target==runtime.admission.database_scope_sha256
    monkeypatch.setenv(override,'external-override')
    with pytest.raises(CompanyTaxError):runtime.assert_session(session)


@pytest.mark.parametrize('method',['GET','POST'])
def test_total_deadline_bounds_a_trickling_response_without_retry(review_basis,monkeypatch,method):
    _,runtime,_,approval,draft=admitted(review_basis);calls=[]
    from talli_backend.adapters import loopback_company_tax_delivery as transport
    monkeypatch.setattr(transport,'_AUTHORITY_DEADLINE_SECONDS',.06)
    class Trickle(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(.02)
                yield b' '
    async def authority(request):calls.append(request);return httpx.Response(200,stream=Trickle())
    provider=LoopbackCompanyTaxDelivery(runtime,transport=httpx.MockTransport(authority))
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.CREATE_INSTANCE)
    async def invoke():
        if method=='GET':return await provider.fetch_current_document(income_year=2025,company_org_number=runtime.admission.organization_number)
        return await provider.execute(request,approval,draft)
    started=time.monotonic()
    with pytest.raises(CompanyTaxReturnAuthorityError):asyncio.run(invoke())
    assert time.monotonic()-started<1 and len(calls)==1 and runtime.requests_used==1
