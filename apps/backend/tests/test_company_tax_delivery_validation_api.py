"""Strict explicit validation routes and additive archive capability opt-in."""
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_journal_archive import complete_archive
from test_company_tax_delivery_submission import workflow
from test_company_tax_delivery_upload_workflow import upload_workflow
from test_company_tax_delivery_validation_workflow import validation_workflow
from test_company_tax_delivery_submission_api import client_for


def test_explicit_validation_api_and_complete_new_archive_require_capability(validation_workflow):
    client,body,headers=client_for(validation_workflow)
    review=client.post('/api/v1/company-tax/delivery-reviews',json=body,headers=headers)
    assert review.status_code==200
    command={name:body[name] for name in ('companyId','incomeYear','filingId')}|{'approvalSha256':review.json()['approvalSha256']}
    creation=client.post('/api/v1/company-tax/delivery-advances',json=command,headers=headers)
    assert creation.status_code==200
    upload=client.post('/api/v1/company-tax/delivery-upload-advances',json=command,headers=headers)
    assert upload.status_code==200
    params={name:body[name] for name in ('companyId','incomeYear')}|{'readEvidence':True,'readEvidenceVersion':2}
    # V6 backend first: the prior reader still gets a complete compatible V5.
    archive='/api/v1/company-tax/archive-source/delivery-journal-v1'
    before=client.get(archive,params=params,headers=headers)
    assert before.status_code==200 and before.json()['sourceFacts']['evidence']['version'].startswith('company-tax-source-v5:')
    started=client.post('/api/v1/company-tax/delivery-validation-advances',json=command,headers=headers)
    assert started.status_code==200 and started.json()['mutationKind']=='start_validation'
    result=client.post('/api/v1/company-tax/delivery-validation-reconciliations',json=command,headers=headers)
    assert result.status_code==200 and result.json()==started.json()
    assert client.post('/api/v1/company-tax/delivery-advances',json=command,headers=headers).json()==creation.json()
    assert client.post('/api/v1/company-tax/delivery-upload-advances',json=command,headers=headers).json()==upload.json()
    assert client.get(archive,params=params,headers=headers).status_code==503
    compatible=client.get(archive,params=params|{'validationEvidence':True},headers=headers)
    assert compatible.status_code==200
    assert compatible.json()['sourceFacts']['evidence']['version'].startswith('company-tax-source-v6:')
    assert compatible.json()['events'][-1]['slot'].startswith('observation:validation-result:')
    assert all(name not in result.text for name in ('body_base64','credential','envelope_xml','canonicalJson'))
