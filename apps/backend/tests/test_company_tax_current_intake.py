"""Finite pre-draft current GETs use real scope, never a placeholder draft hash."""
import asyncio
import concurrent.futures
from dataclasses import replace
from datetime import timedelta
import json
from uuid import uuid4

import httpx
import pytest

from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.adapters.loopback_company_tax_intake import LoopbackCompanyTaxIntake
from talli_backend.application.company_tax_intake_rehearsal import TaxCurrentIntakeRehearsalAdmission,TaxCurrentIntakeRehearsalRuntime
from talli_backend.application.company_tax_delivery_preparation import CompanyTaxDeliveryPreparation
from talli_backend.application.company_tax_filing_workflow import CompanyTaxApplication
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,CompanyTaxReturnAuthorityError,TaxCurrentDocumentIntakeQuery,TaxCurrentDocumentResponse,
)
from talli_backend.shared.kernel import CompanyId,ActorId,ActorKind,UserId,Timestamp
from test_company_tax_delivery_preparation import setup
from test_company_tax_current_document import NOW


def configured(**changes):
    session,current,_,command=setup();session.delivery_rehearsal_target='e'*64
    grant=TaxCurrentIntakeRehearsalAdmission(**(dict(run_id=str(uuid4()),company_id=command.company_id,income_year=command.income_year,
        actor_id=command.actor_id,organization_number='123456789',issued_at=NOW,expires_at=Timestamp(NOW.value+timedelta(seconds=60)),
        origin='http://127.0.0.1:17830',credential='c'*64,database_scope_sha256=session.delivery_rehearsal_target)|changes))
    clock=[NOW];runtime=TaxCurrentIntakeRehearsalRuntime(grant,now=lambda:clock[0])
    query=TaxCurrentDocumentIntakeQuery(command.company_id,command.income_year,command.actor_id,grant.organization_number,
        session.delivery_rehearsal_target,command.correlation_id)
    return session,current,command,grant,runtime,clock,query


def test_intake_has_no_placeholder_filing_or_draft_and_never_exposes_its_secret():
    *_,grant,runtime,clock,query=configured()
    context=json.loads(grant.canonical_context)
    assert context['version']=='tax-loopback-current-intake-v1'
    assert grant.credential not in repr(grant) and grant.credential not in grant.canonical_context
    assert not any(name in context for name in ('filingId','draftSha256','ready','submitted'))
    assert not any(hasattr(grant,name) for name in ('filing_id','draft_sha256'))


@pytest.mark.parametrize('origin',['https://127.0.0.1:17830','http://localhost:17830','http://[::1]:17830',
    'http://192.168.1.2:17830','http://127.0.0.1:17830/','http://127.0.0.1:17830?target=other',
    'http://name@127.0.0.1:17830','http://127.0.0.1:08080','http://127.0.0.1:80'])
def test_intake_origin_cannot_be_hosted_redirected_or_noncanonical(origin):
    with pytest.raises(ValueError):configured(origin=origin)


@pytest.mark.parametrize('changes',[{'maximum_requests':0},{'maximum_requests':5},{'maximum_requests':True},
    {'expires_at':Timestamp(NOW.value+timedelta(seconds=301))},{'expires_at':NOW},{'credential':'caller'},
    {'database_scope_sha256':'unknown'}])
def test_intake_admission_cannot_gain_unbounded_lifetime_or_budget(changes):
    with pytest.raises(ValueError):configured(**changes)


@pytest.mark.parametrize('change',['company','actor','organization','database','expired'])
def test_wrong_or_expired_intake_scope_makes_no_http_request(change):
    _,_,_,grant,runtime,clock,query=configured();calls=[]
    if change=='company':query=replace(query,company_id=CompanyId('10000000-0000-4000-8000-000000000099'))
    elif change=='actor':query=replace(query,actor_id=ActorId(ActorKind.USER,UserId('10000000-0000-4000-8000-000000000099')))
    elif change=='organization':query=replace(query,organization_number='999999999')
    elif change=='database':query=replace(query,database_scope_sha256='d'*64)
    else:clock[0]=grant.expires_at
    async def handler(request):calls.append(request);return httpx.Response(200,content=b'<unexpected/>',headers={'content-type':'text/xml'})
    with pytest.raises(CompanyTaxError):asyncio.run(LoopbackCompanyTaxIntake(runtime,transport=httpx.MockTransport(handler)).read_current_document(query))
    assert calls==[]


def test_concurrent_readers_cannot_exceed_the_exact_intake_budget():
    *_,runtime,clock,query=configured(maximum_requests=1)
    def consume(_):
        try:runtime.consume(query);return True
        except CompanyTaxError:return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(consume,range(12)))
    assert sum(results)==1


def test_actual_scoped_intake_adapter_preserves_original_and_committed_replay_after_expiry():
    session,current,command,grant,runtime,clock,_=configured();calls=[]
    async def handler(request):
        assert session.active==0
        assert request.method=='GET' and str(request.url)=='http://127.0.0.1:17830/api/skattemelding/v2/2025/123456789'
        assert request.headers['X-Talli-Intake-Run']==grant.run_id and request.headers['X-Talli-Intake-Key']==grant.credential
        assert not any(name in request.headers for name in ('Authorization','X-Talli-Rehearsal-Run','X-Talli-Rehearsal-Key'))
        calls.append(request);return httpx.Response(200,content=current.original.raw_bytes,headers={'content-type':'application/xml; charset=utf-8'})
    intake=LoopbackCompanyTaxIntake(runtime,transport=httpx.MockTransport(handler))
    preparation=CompanyTaxDeliveryPreparation(None,PinnedTax2025Schemas(),intake=intake)
    app=CompanyTaxApplication(session,lambda tx:None,preparation=preparation)
    async def exercise():
        actor=await app.session('synthetic');session.lose_store_response=True
        with pytest.raises(CompanyTaxError):await actor.prepare_delivery_draft(command)
        stored=session.stored;clock[0]=grant.expires_at
        replay=await actor.prepare_delivery_draft(command)
        assert replay==stored and replay.draft.current_document.response.raw_bytes==current.original.raw_bytes
        assert current.calls==0 and len(calls)==1
    asyncio.run(exercise())


@pytest.mark.parametrize('failure',['redirect','status','media','lost','empty','oversized'])
def test_invalid_or_lost_intake_response_does_not_retry_or_invent_a_current_document(failure):
    _,current,_,_,runtime,_,query=configured();calls=[]
    async def handler(request):
        calls.append(request)
        if failure=='lost':raise httpx.ReadTimeout('synthetic loss',request=request)
        if failure=='redirect':return httpx.Response(302,headers={'location':'https://other.example/current'})
        return httpx.Response(503 if failure=='status' else 200,
            content=b'' if failure=='empty' else b'x'*(8*1024*1024+1) if failure=='oversized' else current.original.raw_bytes,
            headers={'content-type':'text/plain' if failure=='media' else 'application/xml'})
    with pytest.raises(CompanyTaxReturnAuthorityError):asyncio.run(LoopbackCompanyTaxIntake(runtime,transport=httpx.MockTransport(handler)).read_current_document(query))
    assert len(calls)==1


def test_post_intake_access_loss_blocks_draft_storage():
    session,current,command,_,runtime,_,_=configured()
    async def handler(request):
        session.deny_guard=True;return httpx.Response(200,content=current.original.raw_bytes,headers={'content-type':'application/xml'})
    preparation=CompanyTaxDeliveryPreparation(None,PinnedTax2025Schemas(),intake=LoopbackCompanyTaxIntake(runtime,transport=httpx.MockTransport(handler)))
    with pytest.raises(CompanyTaxError):asyncio.run(preparation.prepare(session,command))
    assert session.stored is None
