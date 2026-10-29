"""Owner action projection follows stored evidence; no projection grants a write."""
import asyncio
from dataclasses import replace
from hashlib import sha256

import pytest

from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxSourceQuery,TaxDeliveryAction,TaxDeliveryJournal,project_tax_delivery_workspace,CompanyTaxError,
)
from test_company_tax_delivery_final_submission_workflow import (
    submission_workflow,confirmation_workflow,validation_workflow,upload_workflow,workflow,complete_archive,review_basis,reviewed,
)

pytestmark=pytest.mark.parametrize('workflow',[80],indirect=True)


@pytest.fixture
def workspace_workflow(submission_workflow):
    session,*_=submission_workflow
    session.base=replace(session.base,contract_version='company-tax-source-v9',coverage=dict(session.base.coverage)|{
        'contractVersion':'company-tax-source-v9','declaredCorrectionExtentValid':True,'correctionCodecVersion':'tax-correction-lineage-v1'})
    return submission_workflow


def projected(fixture,*,dispatch=True,correction=False,source=None):
    session,service,*_=fixture;draft=session.draft
    query=CompanyTaxSourceQuery(draft.envelope.source.company_id,draft.envelope.source.income_year,session.actor_id)
    journal=TaxDeliveryJournal(draft,tuple(session.events),True,True,True,True,True,True)
    return project_tax_delivery_workspace(query,session.snapshot(),source or session.source,
        preparation_available=True,dispatch_admissions={draft.filing_id:dispatch},correction_admissions={draft.filing_id:correction},
        validation={draft.filing_id:service.workspace_validation(journal)})


def test_closed_workspace_keeps_prepared_fields_and_exact_originals_without_advertising_dispatch(workspace_workflow):
    value=projected(workspace_workflow,dispatch=False);row=value.rows[0]
    assert value.preparation_available and row.state=='prepared' and not row.actions
    assert row.fields and {original.purpose for original in row.originals}=={'current','draft_tax','draft_business','draft_envelope'}
    assert all(sha256(original.raw_bytes).hexdigest()==original.sha256 and original.key.endswith(original.sha256) for original in row.originals)
    assert projected(workspace_workflow).rows[0].actions==(TaxDeliveryAction.APPROVE,)


def test_owner_review_and_unknown_submission_never_offer_a_second_put(workspace_workflow):
    session,service,_,_,state,*_=workspace_workflow
    async def exercise():
        command,recovery,_=await reviewed(workspace_workflow)
        value=projected(workspace_workflow);assert not value.preparation_available
        assert value.rows[0].state=='owner_review' and value.rows[0].actions==(TaxDeliveryAction.SUBMIT,)
        state['lostSubmission']=True
        await service.advance_submission(session,command)
        row=projected(workspace_workflow).rows[0]
        assert row.state=='submission_uncertain' and row.actions==(TaxDeliveryAction.RECONCILE_SUBMISSION,)
        changed=replace(session.source,upstream_sha256=session.source.upstream_sha256|{'annual':'d'*64})
        assert projected(workspace_workflow,source=changed).rows[0].actions==(TaxDeliveryAction.RECONCILE_SUBMISSION,)
        state.update(terminal=True,receiptBytes=b'\xef\xbb\xbf <receipt/>\n\xff')
        await service.reconcile_submission(session,recovery)
        value=projected(workspace_workflow,correction=True,source=changed);row=value.rows[0]
        assert row.state=='submitted_receipted' and not row.source_current
        assert row.actions==(TaxDeliveryAction.PREPARE_CORRECTION,)
        assert next(original.raw_bytes for original in row.originals if original.purpose=='feedback')==state['receiptBytes']
        assert state['submissionPuts']==1
    asyncio.run(exercise())


def test_expired_dispatch_does_not_erase_workspace_or_originals(workspace_workflow):
    session,service,_,calls,_,clock,grant=workspace_workflow
    assert service.workspace_admission(session,session.draft)
    clock[0]=grant.expires_at
    assert not service.workspace_admission(session,session.draft)
    value=projected(workspace_workflow,dispatch=service.workspace_admission(session,session.draft))
    assert not value.rows[0].actions and value.rows[0].originals and calls==[]


def test_stale_or_incomplete_history_never_opens_new_owner_actions(workspace_workflow):
    session,*_=workspace_workflow
    changed=replace(session.source,upstream_sha256=session.source.upstream_sha256|{'annual':'d'*64})
    row=projected(workspace_workflow,source=changed).rows[0]
    assert not row.source_current and not row.actions
    session.base=replace(session.base,coverage=dict(session.base.coverage)|{'declaredCorrectionExtentValid':False})
    with pytest.raises(CompanyTaxError):projected(workspace_workflow)


def test_unknown_creation_reserves_frontier_without_a_second_create(workspace_workflow):
    from test_company_tax_delivery_submission import advancing
    session,service,command,_,state,*_=workspace_workflow
    async def exercise():
        approved=await service.approve(session,command)
        # Retain the committed intent while the create response is unknown.
        async def unknown(*args,**kwargs):
            from talli_backend.modules.company_tax_filing.public import CompanyTaxReturnAuthorityError
            raise CompanyTaxReturnAuthorityError('synthetic create response lost')
        service._authority.execute=unknown
        await service.advance(session,advancing(command,approved))
        value=projected(workspace_workflow)
        assert not value.preparation_available
        assert value.rows[0].state=='creation_uncertain' and not value.rows[0].actions
    asyncio.run(exercise())


def test_http_workspace_and_archive_only_downloads_recheck_access_without_authority_io(workspace_workflow,monkeypatch):
    from test_company_tax_delivery_submission_api import client_for
    from talli_backend.application import company_tax_delivery_source
    session=workspace_workflow[0]
    async def source(*args,**kwargs):return session.source
    monkeypatch.setattr(company_tax_delivery_source,'read_company_tax_delivery_source',source)
    client,body,headers=client_for(workspace_workflow)
    params={key:body[key] for key in ('companyId','incomeYear')}
    response=client.get('/api/v1/company-tax/delivery-workspace',params=params,headers=headers)
    assert response.status_code==200,response.text[:500]
    value=response.json();assert value['technicalMode']=='finite_loopback'
    assert value['rows'][0]['actions']==['approve']
    assert 'bodyBase64' not in response.text
    original=value['rows'][0]['originals'][0]
    original_params=params|{'filingId':body['filingId'],'key':original['key']}
    path='/api/v1/company-tax/delivery-original'
    first=client.get(path,params=original_params,headers=headers)
    assert first.status_code==200 and first.json()['sha256']==original['sha256']
    async def unavailable(*args,**kwargs):raise CompanyTaxError.unavailable()
    monkeypatch.setattr(company_tax_delivery_source,'read_company_tax_delivery_source',unavailable)
    assert client.get('/api/v1/company-tax/delivery-workspace',params=params,headers=headers).status_code==503
    assert client.get(path,params=original_params,headers=headers).json()==first.json()
    for owner,fresh,status in [(True,False,403),(False,True,404)]:
        session.owner=owner;session.fresh=fresh
        assert client.get(path,params=original_params,headers=headers).status_code==status
    assert client.get(path,params=original_params).status_code==401
    assert workspace_workflow[3]==[]


def test_later_known_clean_receipt_updates_workspace_without_replacing_submission_completion(workspace_workflow):
    session,service,_,calls,state,*_=workspace_workflow
    async def exercise():
        command,recovery,_=await reviewed(workspace_workflow)
        await service.advance_submission(session,command)
        await service.reconcile_submission(session,recovery)
        completed=next(event for event in session.events if event.slot=='completion:confirm_submission')
        assert projected(workspace_workflow).rows[0].state=='submitted_receipt_pending'
        state.update(receiptBytes=b'\xef\xbb\xbf <later/>\n\xff')
        await service.reconcile_feedback(session,recovery)
        assert projected(workspace_workflow).rows[0].state=='submitted_receipt_recorded'
        before=len(calls)
        await service.reconcile_feedback(session,recovery)
        assert len(calls)==before+1,'unchanged known metadata needs no duplicate receipt GET'
        state['terminal']=True
        await service.reconcile_feedback(session,recovery)
        row=projected(workspace_workflow).rows[0]
        assert row.state=='submitted_receipted' and not row.actions
        assert completed==next(event for event in session.events if event.slot=='completion:confirm_submission')
    asyncio.run(exercise())


def test_private_preparation_opt_in_preserves_old_wire_and_expired_original_reads(workspace_workflow,monkeypatch):
    from fastapi.testclient import TestClient
    from talli_backend.main import create_app
    from talli_backend.application import company_tax_delivery_source
    session=workspace_workflow[0]
    admitted=[True]
    class Preparation:
        preparation_only=True
        async def authorize(self,*_):
            if not admitted[0]:raise CompanyTaxError.forbidden()
        def workspace_admission(self,*_,**__):return admitted[0]
    async def source(*args,**kwargs):return session.source
    monkeypatch.setattr(company_tax_delivery_source,'read_company_tax_delivery_source',source)
    class Factory:
        async def session(self,token):return session
    client=TestClient(create_app(company_tax_session_factory=Factory(),company_tax_delivery_preparation=Preparation()))
    params={'companyId':str(session.source.company_id),'incomeYear':2025}
    headers={'Authorization':'Bearer synthetic-unit-bearer'}
    path='/api/v1/company-tax/delivery-workspace'
    old=client.get(path,params=params,headers=headers)
    assert old.status_code==200,old.text
    assert old.json()['technicalMode']=='unavailable' and not old.json()['preparationAvailable']
    new=client.get(path,params=params|{'includePreparationContext':'true'},headers=headers).json()
    assert new['technicalMode']=='private_preview_preparation' and new['preparationAvailable']
    assert all(not row['actions'] for row in new['rows'])
    admitted[0]=False
    expired=client.get(path,params=params|{'includePreparationContext':'true'},headers=headers).json()
    assert not expired['preparationAvailable'] and expired['rows']==new['rows']
    row=expired['rows'][0];original=row['originals'][0]
    result=client.get('/api/v1/company-tax/delivery-original',params=params|{
        'filingId':row['filingId'],'key':original['key']},headers=headers)
    assert result.status_code==200 and result.json()['sha256']==original['sha256']


@pytest.mark.parametrize('with_documents',[False,True,'partial'])
def test_blocked_validation_preserves_all_review_findings_without_opening_confirmation(workspace_workflow,with_documents):
    from test_company_tax_delivery_validation_workflow import uploaded
    from test_company_tax_calculated_schemas import result,documents
    session,service,_,_,state,*_=workspace_workflow
    supplied=documents(session.draft) if with_documents else {}
    if with_documents=='partial':supplied={'skattemeldingUpersonligEtterBeregning':supplied['skattemeldingUpersonligEtterBeregning']}
    state['resultBytes']=result(supplied,code='validertMedFeil',
        before='<avvikVedValidering><avvik><avvikstype>synthetic-block</avvikstype><mottattVerdi>123</mottattVerdi></avvik></avvikVedValidering>',
        after='<aarsakTilValidertMedFeil>Kontroller dette feltet.</aarsakTilValidertMedFeil>').raw_bytes
    if not with_documents:
        from test_company_tax_validation_response_schemas import xml
        state['resultBytes']=xml(result='validertMedFeil',before='<avvikVedValidering><avvik><avvikstype>synthetic-block</avvikstype><mottattVerdi>123</mottattVerdi></avvik></avvikVedValidering>',after='<aarsakTilValidertMedFeil>Kontroller dette feltet.</aarsakTilValidertMedFeil>')
    async def exercise():
        command,*_=await uploaded(workspace_workflow)
        await service.advance_validation(session,command)
        await service.reconcile_validation(session,command)
        row=projected(workspace_workflow).rows[0]
        assert row.state=='validation_blocked' and row.actions==(TaxDeliveryAction.RECONCILE_VALIDATION,)
        assert row.validation.response.failure_reasons==('Kontroller dette feltet.',)
        assert row.validation.response.validation_deviations[0].received_value=='123'
        assert (row.validation.calculated is not None)==(with_documents is True)
        assert len(row.validation.documents)==(4 if with_documents is True else 1 if with_documents=='partial' else 0)
        assert not any(event.slot=='intent:prepare_confirmation' for event in session.events)
    asyncio.run(exercise())
