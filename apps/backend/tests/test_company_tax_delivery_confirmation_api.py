"""Explicit confirmation preparation routes and compatible archive negotiation."""
import pytest
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_journal_archive import complete_archive
from test_company_tax_delivery_submission import workflow
from test_company_tax_delivery_upload_workflow import upload_workflow
from test_company_tax_delivery_validation_workflow import validation_workflow
from test_company_tax_delivery_confirmation_workflow import confirmation_workflow
from test_company_tax_delivery_submission_api import client_for


def test_confirmation_api_requires_reads_to_prove_stage_and_explicit_archive_capability(confirmation_workflow):
    client,body,headers=client_for(confirmation_workflow)
    review=client.post('/api/v1/company-tax/delivery-reviews',json=body,headers=headers);assert review.status_code==200
    command={key:body[key] for key in ('companyId','incomeYear','filingId')}|{'approvalSha256':review.json()['approvalSha256']}
    for route in ('delivery-advances','delivery-upload-advances','delivery-validation-advances'):
        response=client.post('/api/v1/company-tax/'+route,json=command,headers=headers);assert response.status_code==200
    archive='/api/v1/company-tax/archive-source/delivery-journal-v1'
    params={key:body[key] for key in ('companyId','incomeYear')}|{'readEvidence':True,'readEvidenceVersion':2,'validationEvidence':True}
    before=client.get(archive,params=params,headers=headers)
    assert before.status_code==200 and before.json()['sourceFacts']['evidence']['version'].startswith('company-tax-source-v6:')
    pending=client.post('/api/v1/company-tax/delivery-confirmation-advances',json=command,headers=headers)
    assert pending.status_code==200 and pending.json()['status']=='uncertain' and pending.json()['mutationKind']=='prepare_confirmation'
    assert client.post('/api/v1/company-tax/delivery-confirmation-advances',json=command,headers=headers).json()==pending.json()
    completed=client.post('/api/v1/company-tax/delivery-confirmation-reconciliations',json=command,headers=headers)
    assert completed.status_code==200 and completed.json()['status']=='mutation_completed'
    assert client.get(archive,params=params,headers=headers).status_code==503
    original=client.get(archive,params=params|{'confirmationEvidence':True},headers=headers)
    assert original.status_code==200 and original.json()['sourceFacts']['evidence']['version'].startswith('company-tax-source-v7:')
    assert any(row['slot']=='acknowledgment:prepare_confirmation' for row in original.json()['events'])
    assert all(key not in completed.text for key in ('body_base64','credential','canonicalJson','envelope_xml'))


@pytest.mark.parametrize('route',['delivery-confirmation-advances','delivery-confirmation-reconciliations'])
def test_default_composition_keeps_both_confirmation_routes_closed(workflow,route):
    client,body,headers=client_for(workflow,enabled=False)
    command={key:body[key] for key in ('companyId','incomeYear','filingId')}|{'approvalSha256':'a'*64}
    assert client.post('/api/v1/company-tax/'+route,json=command,headers=headers).status_code==503
    assert workflow[0].guards==[] and workflow[3]==[]


@pytest.mark.parametrize('field',['ready','calculated','confirmationPrerequisite','jobId','instanceId','actorId','credential'])
def test_confirmation_api_never_accepts_caller_readiness_proofs_or_targets(workflow,field):
    client,body,headers=client_for(workflow)
    command={key:body[key] for key in ('companyId','incomeYear','filingId')}|{'approvalSha256':'a'*64,field:True}
    assert client.post('/api/v1/company-tax/delivery-confirmation-advances',json=command,headers=headers).status_code==422
    assert workflow[3]==[]
