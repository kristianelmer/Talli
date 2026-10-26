"""HTTP commands carry only scope/review identity; finite admission is server-owned."""
import pytest
from fastapi.testclient import TestClient

from talli_backend.main import create_app
from test_company_tax_delivery_submission import workflow
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_journal_archive import complete_archive
from test_company_tax_delivery_rehearsal import recursive_result


def client_for(workflow,*,enabled=True):
    session,service,command,*_=workflow
    class Factory:
        async def session(self,token):
            assert token=='synthetic-unit-bearer'
            return session
    client=TestClient(create_app(company_tax_session_factory=Factory(),
        company_tax_delivery_submission=service if enabled else None))
    body={'companyId':str(command.company_id),'incomeYear':2025,'filingId':str(command.filing_id),
        'draftSha256':command.expected_draft_sha256,'reviewSha256':command.expected_review_sha256}
    headers={'Authorization':'Bearer synthetic-unit-bearer','Idempotency-Key':str(command.command_key)}
    return client,body,headers


def test_http_review_create_and_reconcile_expose_only_bound_progress(workflow):
    client,body,headers=client_for(workflow)
    approved=client.post('/api/v1/company-tax/delivery-reviews',json=body,headers=headers)
    assert approved.status_code==200
    first=approved.json();assert first['status']=='reviewed'
    assert first['authorityMode']=='finite_loopback_rehearsal' and first['mutationKind'] is None
    assert client.post('/api/v1/company-tax/delivery-reviews',json=body,headers=headers).json()==first
    advance={name:body[name] for name in ('companyId','incomeYear','filingId')}|{'approvalSha256':first['approvalSha256']}
    result=client.post('/api/v1/company-tax/delivery-advances',json=advance,headers=headers)
    assert result.status_code==200 and result.json()['status']=='mutation_completed'
    assert result.json()['mutationKind']=='create_instance'
    observed=client.post('/api/v1/company-tax/delivery-reconciliations',json=advance,headers=headers)
    assert observed.status_code==200 and observed.json()['status']=='mutation_completed'
    assert observed.json()['mutationKind']=='create_instance'
    assert client.post('/api/v1/company-tax/delivery-reviews',json=body,headers=headers).json()==first
    assert all(key not in result.text for key in ('canonicalJson','body_base64','response_base64','credential','origin','envelope_xml'))
    assert [method for method,_ in workflow[3]]==['GET','GET','POST','GET']


@pytest.mark.parametrize('path',['delivery-reviews','delivery-advances','delivery-reconciliations','delivery-upload-advances','delivery-upload-reconciliations','delivery-validation-advances','delivery-validation-reconciliations'])
def test_default_composition_has_no_submission_authority(workflow,path):
    client,body,headers=client_for(workflow,enabled=False)
    if path!='delivery-reviews':body={name:body[name] for name in ('companyId','incomeYear','filingId')}|{'approvalSha256':'a'*64}
    response=client.post('/api/v1/company-tax/'+path,json=body,headers=headers)
    assert response.status_code==503 and workflow[0].guards==[] and workflow[3]==[]


@pytest.mark.parametrize('field',['origin','credential','authorityContextSha256','actorId','paid','annualReady','envelopeXml'])
def test_http_cannot_supply_runtime_credentials_readiness_or_documents(workflow,field):
    client,body,headers=client_for(workflow)
    response=client.post('/api/v1/company-tax/delivery-reviews',json=body|{field:'caller supplied'},headers=headers)
    assert response.status_code==422 and workflow[3]==[] and workflow[0].events==[]


@pytest.mark.parametrize('change',['year','year-type','digest','missing-key','unsafe-key','hosted-target','expired'])
def test_invalid_scope_or_inactive_technical_admission_cannot_reach_authority(workflow,change):
    client,body,headers=client_for(workflow)
    expected=422
    if change=='year':body['incomeYear']=2026
    elif change=='year-type':body['incomeYear']='2025'
    elif change=='digest':body['reviewSha256']='bad'
    elif change=='missing-key':headers.pop('Idempotency-Key')
    elif change=='unsafe-key':headers['Idempotency-Key']='https://caller.example/activate'
    elif change=='hosted-target':workflow[0].delivery_rehearsal_target=None;expected=503
    else:workflow[5][0]=workflow[6].expires_at;expected=503
    response=client.post('/api/v1/company-tax/delivery-reviews',json=body,headers=headers)
    assert response.status_code==expected
    assert workflow[3]==[] and workflow[0].events==[]


def test_unknown_http_result_replays_as_unknown_without_resending(workflow):
    client,body,headers=client_for(workflow)
    approved=client.post('/api/v1/company-tax/delivery-reviews',json=body,headers=headers).json()
    advance={name:body[name] for name in ('companyId','incomeYear','filingId')}|{'approvalSha256':approved['approvalSha256']}
    workflow[4]['lost']=True
    first=client.post('/api/v1/company-tax/delivery-advances',json=advance,headers=headers)
    assert first.status_code==200 and first.json()['status']=='uncertain'
    replay=client.post('/api/v1/company-tax/delivery-advances',json=advance,headers=headers|{'Idempotency-Key':'different-http-retry-key'})
    assert replay.json()==first.json()
    assert client.post('/api/v1/company-tax/delivery-reconciliations',json=advance,headers=headers).json()==first.json()
    assert sum(method=='POST' for method,_ in workflow[3])==1


def test_deeply_nested_authority_json_is_returned_as_unknown_on_the_first_response(workflow):
    client,body,headers=client_for(workflow)
    approved=client.post('/api/v1/company-tax/delivery-reviews',json=body,headers=headers).json()
    advance={name:body[name] for name in ('companyId','incomeYear','filingId')}|{'approvalSha256':approved['approvalSha256']}
    workflow[4]['body']=recursive_result()
    first=client.post('/api/v1/company-tax/delivery-advances',json=advance,headers=headers)
    assert first.status_code==200 and first.json()['status']=='uncertain'
    assert client.post('/api/v1/company-tax/delivery-advances',json=advance,headers=headers).json()==first.json()
    assert sum(method=='POST' for method,_ in workflow[3])==1


@pytest.mark.parametrize('path',['delivery-upload-advances','delivery-upload-reconciliations'])
@pytest.mark.parametrize('field',['origin','credential','actorId','annualReady','envelopeXml','uploadPrerequisite'])
def test_upload_http_cannot_supply_runtime_or_read_proof(workflow,path,field):
    client,body,headers=client_for(workflow)
    body={name:body[name] for name in ('companyId','incomeYear','filingId')}|{'approvalSha256':'a'*64,field:'caller supplied'}
    assert client.post('/api/v1/company-tax/'+path,json=body,headers=headers).status_code==422
    assert workflow[3]==[] and workflow[0].events==[]


@pytest.mark.parametrize('path',['delivery-validation-advances','delivery-validation-reconciliations'])
@pytest.mark.parametrize('field',['origin','credential','actorId','annualReady','envelopeXml','validationPrerequisite','jobId','validated'])
def test_validation_http_cannot_supply_credentials_job_identity_or_readiness(workflow,path,field):
    client,body,headers=client_for(workflow)
    body={name:body[name] for name in ('companyId','incomeYear','filingId')}|{'approvalSha256':'a'*64,field:'caller supplied'}
    assert client.post('/api/v1/company-tax/'+path,json=body,headers=headers).status_code==422
    assert workflow[3]==[] and workflow[0].events==[]
