"""Final owner action, compatible archive negotiation and exact receipt originals."""
import json
import os
from pathlib import Path
import subprocess

import pytest

from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_journal_archive import complete_archive
from test_company_tax_delivery_submission import workflow
from test_company_tax_delivery_upload_workflow import upload_workflow
from test_company_tax_delivery_validation_workflow import validation_workflow
from test_company_tax_delivery_confirmation_workflow import confirmation_workflow
from test_company_tax_delivery_final_submission_workflow import submission_workflow
from test_company_tax_delivery_owner_review_api import prepared_http
from test_company_tax_delivery_submission_api import client_for

pytestmark=pytest.mark.parametrize('workflow',[80],indirect=True)
ADVANCE='/api/v1/company-tax/delivery-submission-advances'
RECONCILE='/api/v1/company-tax/delivery-submission-reconciliations'
FEEDBACK='/api/v1/company-tax/delivery-feedback-reconciliations'


def test_exact_owner_confirmation_then_read_recovery_and_later_receipt_survive_actual_sdk_and_web_readers(submission_workflow):
    client,params,headers=prepared_http(submission_workflow);state=submission_workflow[4]
    artifact=client.get('/api/v1/company-tax/delivery-owner-review',params=params,headers=headers)
    assert artifact.status_code==200
    command=params|{'ownerReviewSha256':artifact.json()['artifactSha256'],'documentsConfirmed':True,'warningsAcknowledged':True}
    pending=client.post(ADVANCE,json=command,headers=headers)
    assert pending.status_code==200 and pending.json()['status']=='uncertain' and pending.json()['mutationKind']=='confirm_submission'
    assert client.post(ADVANCE,json=command,headers=headers).json()==pending.json() and state['submissionPuts']==1
    complete=client.post(RECONCILE,json=params,headers=headers)
    assert complete.status_code==200 and complete.json()['status']=='mutation_completed'
    state.update(receiptBytes=b'\xef\xbb\xbf <receipt/>\n\xff',terminal=True)
    assert client.post(FEEDBACK,json=params,headers=headers).json()==complete.json()
    scope={key:params[key] for key in ('companyId','incomeYear')}
    archive='/api/v1/company-tax/archive-source/delivery-journal-v1'
    flags={'readEvidence':True,'readEvidenceVersion':2,'validationEvidence':True,'confirmationEvidence':True}
    assert client.get(archive,params=scope|flags,headers=headers).status_code==503
    response=client.get(archive,params=scope|flags|{'submissionEvidence':True},headers=headers)
    assert response.status_code==200
    source=client.get('/api/v1/company-tax/source-facts',params=scope,headers=headers)
    assert source.status_code==200
    value=response.json();assert value['sourceFacts']['evidence']['version'].startswith('company-tax-source-v8:')
    assert any(row['slot'].startswith('observation:feedback:') for row in value['events'])
    checked=subprocess.run([os.environ.get('TALLI_NODE_BIN','node'),'--experimental-strip-types','tests/support/check-tax-journal-client.mjs'],
        input=json.dumps({'archive':value,'source':source.json(),'testSubmissionCorruptions':True}),text=True,capture_output=True,cwd=Path(__file__).resolve().parents[3],timeout=30)
    assert checked.returncode==0,(checked.stdout+checked.stderr)[-4000:]
    assert state['confirmationPuts']==1 and state['submissionPuts']==1


@pytest.mark.parametrize('route',[ADVANCE,RECONCILE,FEEDBACK])
def test_final_submission_routes_are_default_closed(workflow,route):
    client,body,headers=client_for(workflow,enabled=False)
    command={key:body[key] for key in ('companyId','incomeYear','filingId')}|{'approvalSha256':'a'*64}
    if route==ADVANCE:command|={'ownerReviewSha256':'b'*64,'documentsConfirmed':True,'warningsAcknowledged':True}
    assert client.post(route,json=command,headers=headers).status_code==503
    assert workflow[3]==[] and workflow[0].guards==[]


@pytest.mark.parametrize('field,value',[('documentsConfirmed',False),('warningsAcknowledged',False),('documentsConfirmed',1),
    ('warningsAcknowledged','true'),('ready',True),('actorId','caller'),('instanceId','caller'),('receiptAccepted',True),('submissionPrerequisite',{})])
def test_final_owner_action_rejects_nonexplicit_choices_and_caller_proofs(workflow,field,value):
    client,body,headers=client_for(workflow)
    command={key:body[key] for key in ('companyId','incomeYear','filingId')}|{'approvalSha256':'a'*64,
        'ownerReviewSha256':'b'*64,'documentsConfirmed':True,'warningsAcknowledged':True,field:value}
    assert client.post(ADVANCE,json=command,headers=headers).status_code==422
    assert workflow[3]==[] and workflow[0].guards==[]
