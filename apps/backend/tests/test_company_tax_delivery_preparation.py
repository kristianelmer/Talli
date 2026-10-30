"""Server-owned preparation: no provider I/O under SQL, exact committed replay."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import pytest

from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.application.company_tax_delivery_preparation import CompanyTaxDeliveryPreparation
from talli_backend.application.company_tax_filing_workflow import CompanyTaxApplication
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError, PrepareTaxDeliveryDraft, StoredTaxDeliveryDraft, TaxFilingSubmissionId,
)
from talli_backend.shared.kernel import CorrelationId, IdempotencyKey, ActorId, ActorKind, UserId
from test_company_tax_delivery_source import Inputs, QUERY
from test_company_tax_current_document import response, NOW


class Session(Inputs):
    def __init__(self):
        super().__init__()
        self.active=0
        self.transactions=[]
        self.current_snapshot=False
        self.on_guard=lambda:None
        self.after_snapshot=lambda:None
        self.stored=None
        self.lose_store_response=False
        self.guards=[]
        self.deny_guard=False

    async def session(self,_token):return self

    @asynccontextmanager
    async def transaction(self,*,snapshot=False):
        self.transactions.append(snapshot)
        self.active+=1
        previous=self.current_snapshot
        self.current_snapshot=snapshot
        try:yield self
        finally:
            self.active-=1
            self.current_snapshot=previous
            if snapshot:self.after_snapshot()

    async def delivery_draft_by_key(self,query,key):
        assert self.active==1 and not self.current_snapshot
        assert query==QUERY
        return self.stored

    async def lock_delivery_draft_archive(self,query):
        assert self.active==1 and not self.current_snapshot and query==QUERY
        self.guards.append(query)
        self.on_guard()
        if self.deny_guard:raise CompanyTaxError.mfa_required()

    async def store_delivery_draft(self,draft):
        assert self.active==1 and not self.current_snapshot
        self.stored=StoredTaxDeliveryDraft(draft,NOW)
        if self.lose_store_response:
            self.lose_store_response=False
            raise CompanyTaxError.unavailable()
        return self.stored


class Current:
    def __init__(self,session,validator):
        self.session=session
        self.original=response(validator,bom=True)
        self.calls=0
        self.on_read=lambda:None

    async def fetch_current_document(self,**scope):
        assert self.session.active==0,'Authority GET must follow source transaction closure.'
        assert scope=={'income_year':2025,'company_org_number':'123456789'}
        self.calls+=1
        self.on_read()
        return self.original


def setup():
    session=Session();schemas=PinnedTax2025Schemas();current=Current(session,schemas)
    preparation=CompanyTaxDeliveryPreparation(current,schemas)
    app=CompanyTaxApplication(session,lambda tx:None,preparation=preparation)
    command=PrepareTaxDeliveryDraft(QUERY.company_id,QUERY.income_year,QUERY.actor_id,
        TaxFilingSubmissionId(str(uuid4())),IdempotencyKey('prepare-from-current-command'),CorrelationId('prepare-current'))
    return session,current,app,command


def test_preparation_derives_documents_from_owner_sources_and_retains_authority_original_outside_transactions():
    session,current,app,command=setup()
    async def exercise():
        actor=await app.session('synthetic')
        stored=await actor.prepare_delivery_draft(command)
        assert stored.draft.current_document.response.raw_bytes==current.original.raw_bytes
        assert stored.draft.current_document.document_reference==stored.draft.envelope.current_document_reference
        assert stored.draft.prepared_by==command.actor_id
        assert stored.draft.filing_id==str(command.filing_id)
        return stored
    stored=asyncio.run(exercise())
    assert session.stored==stored and current.calls==1
    assert session.transactions==[False,True,False,False,True]


def test_lost_committed_response_replays_exact_original_without_refetching_or_regenerating():
    session,current,app,command=setup();session.lose_store_response=True
    async def exercise():
        actor=await app.session('synthetic')
        with pytest.raises(CompanyTaxError):await actor.prepare_delivery_draft(command)
        original=session.stored.draft.canonical_json
        current.on_read=lambda:pytest.fail('Replay must precede authority access.')
        # Later source edits cannot rewrite this command's already stored draft.
        session.annual=replace(session.annual,updated_at='2026-10-26T01:00:00+00:00')
        replay=await actor.prepare_delivery_draft(replace(command,correlation_id=CorrelationId('retry-current')))
        assert replay.draft.canonical_json==original
    asyncio.run(exercise());assert current.calls==1
    assert session.transactions==[False,True,False,False,True,False]


def test_source_change_during_current_read_conflicts_without_persisting_a_stale_new_draft():
    session,current,app,command=setup()
    current.on_read=lambda:setattr(session,'annual',replace(session.annual,updated_at='2026-10-26T01:00:00+00:00'))
    async def exercise():
        actor=await app.session('synthetic')
        with pytest.raises(CompanyTaxError) as error:await actor.prepare_delivery_draft(command)
        assert error.value.code=='COMPANY_TAX_DRAFT_CONFLICT'
    asyncio.run(exercise());assert session.stored is None and current.calls==1


def test_default_unconfigured_preparation_and_forged_actor_never_read_sources_or_authority():
    session,current,_,command=setup()
    async def exercise():
        actor=await CompanyTaxApplication(session,lambda tx:None).session('synthetic')
        with pytest.raises(CompanyTaxError) as error:await actor.prepare_delivery_draft(command)
        assert error.value.code=='COMPANY_TAX_DEPENDENCY_UNAVAILABLE'
        wrong=ActorId(ActorKind.USER,UserId(str(uuid4())))
        with pytest.raises(CompanyTaxError) as error:await actor.prepare_delivery_draft(replace(command,actor_id=wrong))
        assert error.value.code=='COMPANY_TAX_FORBIDDEN'
    asyncio.run(exercise());assert session.transactions==[] and current.calls==0


def test_replay_identity_conflict_and_cross_actor_storage_failure_do_not_read_authority():
    session,current,app,command=setup()
    async def exercise():
        actor=await app.session('synthetic');await actor.prepare_delivery_draft(command)
        with pytest.raises(CompanyTaxError) as error:
            await actor.prepare_delivery_draft(replace(command,filing_id=TaxFilingSubmissionId(str(uuid4()))))
        assert error.value.code=='COMPANY_TAX_DRAFT_CONFLICT'
        session.stored=replace(session.stored,draft=replace(session.stored.draft,
            prepared_by=ActorId(ActorKind.USER,UserId(str(uuid4())))))
        with pytest.raises(CompanyTaxError) as error:await actor.prepare_delivery_draft(command)
        assert error.value.code=='COMPANY_TAX_DEPENDENCY_UNAVAILABLE'
    asyncio.run(exercise());assert current.calls==1


def test_authority_response_for_different_requested_org_never_creates_a_draft():
    session,current,app,command=setup()
    current.original=replace(current.original,organization_number='999999999')
    async def exercise():
        with pytest.raises(CompanyTaxError):await (await app.session('synthetic')).prepare_delivery_draft(command)
    asyncio.run(exercise());assert session.stored is None


def test_current_mfa_is_required_before_authority_read_and_again_before_retaining_originals():
    for after_get in [False,True]:
        session,current,app,command=setup()
        if after_get:current.on_read=lambda:setattr(session,'deny_guard',True)
        else:session.deny_guard=True
        async def exercise():
            with pytest.raises(CompanyTaxError) as error:
                await (await app.session('synthetic')).prepare_delivery_draft(command)
            assert error.value.code=='COMPANY_TAX_MFA_REQUIRED'
        asyncio.run(exercise())
        assert current.calls==int(after_get) and session.stored is None


def test_http_preparation_uses_verified_actor_and_server_facts_and_only_returns_identifiers_and_hashes():
    from fastapi.testclient import TestClient
    from talli_backend.main import create_app
    session,current,app,command=setup()
    client=TestClient(create_app(company_tax_session_factory=session,
        company_tax_delivery_preparation=app._preparation))
    body={'companyId':str(command.company_id),'incomeYear':2025,'filingId':str(command.filing_id)}
    headers={'Authorization':'Bearer synthetic','Idempotency-Key':str(command.command_key)}
    path='/api/v1/company-tax/delivery-drafts'
    assert client.post(path,json=body,headers={'Idempotency-Key':str(command.command_key)}).status_code==401
    for extra in [{'annualData':{}},{'currentDocumentReference':'forged'},{'actorId':str(uuid4())},
                  {'taxXml':'<forged/>'},{'url':'https://example.com'}]:
        assert client.post(path,json=body|extra,headers=headers).status_code==422
    assert client.post(path,json=body|{'incomeYear':2026},headers=headers).status_code==422
    assert client.post(path,json=body|{'incomeYear':True},headers=headers).status_code==422
    assert client.post(path,json=body,headers={'Authorization':'Bearer synthetic'}).status_code==422
    assert client.post(path,json=body,headers=headers|{'Idempotency-Key':'invalid key with spaces'}).status_code==422
    assert current.calls==0 and not session.transactions
    first=client.post(path,json=body,headers=headers)
    assert first.status_code==200,first.text
    value=first.json();stored=session.stored
    assert set(value)=={'companyId','incomeYear','filingId','recordedAt','draftSha256',
                        'reviewSha256','schemaSha256','status'}
    assert value['draftSha256']==stored.draft.sha256 and value['status']=='prepared_only'
    assert value['reviewSha256']==stored.draft.envelope.review_sha256
    assert first.headers['cache-control']=='no-store'
    assert stored.draft.prepared_by==session.actor_id
    # Replay can return non-sensitive receipt metadata after MFA expires.
    session.deny_guard=True
    replay=client.post(path,json=body,headers=headers)
    assert replay.status_code==200 and replay.json()==value and current.calls==1
    conflict=client.post(path,json=body|{'filingId':str(uuid4())},headers=headers)
    assert conflict.status_code==409 and current.calls==1


def test_http_default_preparation_is_unavailable_and_stale_mfa_never_fetches_current():
    from fastapi.testclient import TestClient
    from talli_backend.main import create_app
    for configured in [False,True]:
        session,current,app,command=setup();session.deny_guard=True
        client=TestClient(create_app(company_tax_session_factory=session,
            company_tax_delivery_preparation=app._preparation if configured else None))
        result=client.post('/api/v1/company-tax/delivery-drafts',json={
            'companyId':str(command.company_id),'incomeYear':2025,'filingId':str(command.filing_id)},
            headers={'Authorization':'Bearer synthetic','Idempotency-Key':str(command.command_key)})
        assert result.status_code==(403 if configured else 503),result.text
        assert current.calls==0 and session.stored is None


@pytest.mark.parametrize('failure',['network','empty-response'])
def test_http_current_authority_failure_is_sanitized_unavailable_and_retains_nothing(failure):
    from fastapi.testclient import TestClient
    from talli_backend.main import create_app
    from talli_backend.modules.company_tax_filing.public import CompanyTaxReturnAuthorityError
    session,current,app,command=setup()
    async def unavailable(**scope):
        if failure=='network':
            raise CompanyTaxReturnAuthorityError('provider-private-detail',code='COMPANY_TAX_NETWORK_ERROR',retryable=True)
        raise ValueError('provider-private-original')
    current.fetch_current_document=unavailable
    client=TestClient(create_app(company_tax_session_factory=session,
        company_tax_delivery_preparation=app._preparation))
    result=client.post('/api/v1/company-tax/delivery-drafts',json={
        'companyId':str(command.company_id),'incomeYear':2025,'filingId':str(command.filing_id)},
        headers={'Authorization':'Bearer synthetic','Idempotency-Key':str(command.command_key)})
    assert result.status_code==503 and result.json()['code']=='COMPANY_TAX_DEPENDENCY_UNAVAILABLE'
    assert 'provider-private' not in result.text and session.stored is None


def test_expiry_during_source_enumeration_blocks_current_get():
    session,current,app,command=setup()
    session.after_snapshot=lambda:setattr(session,'deny_guard',True)
    async def exercise():
        with pytest.raises(CompanyTaxError) as error:
            await (await app.session('synthetic')).prepare_delivery_draft(command)
        assert error.value.code=='COMPANY_TAX_MFA_REQUIRED'
    asyncio.run(exercise());assert current.calls==0 and session.stored is None


def test_source_change_while_waiting_for_final_guard_cannot_persist_stale_draft():
    session,current,app,command=setup()
    def changed():
        if current.calls:
            session.annual=replace(session.annual,updated_at='2026-10-26T01:00:00+00:00')
    session.on_guard=changed
    async def exercise():
        with pytest.raises(CompanyTaxError) as error:
            await (await app.session('synthetic')).prepare_delivery_draft(command)
        assert error.value.code=='COMPANY_TAX_DRAFT_CONFLICT'
    asyncio.run(exercise());assert current.calls==1 and session.stored is None


def test_connected_loopback_fixture_preserves_preparation_admission_interface():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).resolve().parents[3]/'tests/fixtures/tax_delivery_browser_runtime.py'
    spec=importlib.util.spec_from_file_location('tax_browser_preparation_contract',path)
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    session,current,app,command=setup()
    registered=[]
    class Runtime:
        def register(self,draft,actor):registered.append((draft,actor))
    preparation=fixture._Preparation(Runtime(),app._preparation)
    assert preparation.preparation_only is False
    async def exercise():
        await preparation.authorize(session,QUERY)
        await preparation.authorize_transaction(session,session,QUERY)
        stored=await preparation.prepare(session,command)
        assert registered==[(stored.draft,session)]
    asyncio.run(exercise())
    assert current.calls==1
