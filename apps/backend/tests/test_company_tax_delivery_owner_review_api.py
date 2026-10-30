"""Owner review returns one complete, stable content commitment through HTTP."""
from dataclasses import replace
from hashlib import sha256
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
from test_company_tax_delivery_submission_api import client_for
from test_company_tax_calculated_schemas import documents,result


def prepared_http(fixture):
    client,body,headers=client_for(fixture)
    response=client.post('/api/v1/company-tax/delivery-reviews',json=body,headers=headers)
    assert response.status_code==200
    command={key:body[key] for key in ('companyId','incomeYear','filingId')}|{'approvalSha256':response.json()['approvalSha256']}
    for route in ('delivery-advances','delivery-upload-advances','delivery-validation-advances',
                  'delivery-confirmation-advances','delivery-confirmation-reconciliations'):
        response=client.post('/api/v1/company-tax/'+route,json=command,headers=headers)
        assert response.status_code==200
    return client,command,headers


def test_complete_owner_review_through_api_and_generated_browser_readers(confirmation_workflow):
    confirmation_workflow[4]['resultBytes']=result(documents(confirmation_workflow[0].draft),before=
        '<avvikEtterBeregning><avvik><avvikstype>changed</avvikstype><mottattVerdi>1.00</mottattVerdi>'
        '<beregnetVerdi>2.00</beregnetVerdi></avvik></avvikEtterBeregning>'
        '<veiledningEtterKontroll><veiledning><veiledningstype>review</veiledningstype>'
        '<hjelpetekst>Kontroller økt beløp &amp; behold originalen.</hjelpetekst></veiledning></veiledningEtterKontroll>').raw_bytes
    client,params,headers=prepared_http(confirmation_workflow)
    session,_,_,calls,*_=confirmation_workflow
    before=(len(calls),tuple(session.events))
    response=client.get('/api/v1/company-tax/delivery-owner-review',params=params,headers=headers)
    assert response.status_code==200,response.text[:500]
    value=response.json()
    assert value['review']['response']['inspection']['result_code']=='validertOK'
    assert value['review']['response']['guidance'][0]['message']=='Kontroller økt beløp & behold originalen.'
    assert value['review']['response']['calculation_deviations'][0]['received_value']=='1.00'
    assert len(value['review']['documents'])==4
    content={key:value[key] for key in ('version','review')}
    raw=json.dumps(content,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
    assert sha256(raw.encode()).hexdigest()==value['artifactSha256']
    assert client.get('/api/v1/company-tax/delivery-owner-review',params=params,headers=headers).json()==value
    assert (len(calls),tuple(session.events))==before
    # Exercise the actual generated SDK and feature loader with the actual DTO,
    # then consistently rehash corruptions so tests reach each semantic guard.
    node=os.environ.get('TALLI_NODE_BIN','node')
    root=Path(__file__).resolve().parents[3]
    checked=subprocess.run([node,'--experimental-strip-types','tests/support/check-tax-owner-review-client.mjs'],
        cwd=root,input=json.dumps(value),text=True,capture_output=True,check=False)
    assert checked.returncode==0,(checked.stdout+checked.stderr)[-4000:]
    assert 'Owner-review readers passed' in checked.stdout


@pytest.mark.parametrize('change',['owner','mfa','source','approval','authorization'])
def test_owner_review_http_rechecks_current_access_and_scope(confirmation_workflow,change):
    client,params,headers=prepared_http(confirmation_workflow);session=confirmation_workflow[0]
    count=len(confirmation_workflow[3]);events=tuple(session.events)
    if change=='owner':session.owner=False
    elif change=='mfa':session.fresh=False
    elif change=='source':session.source=replace(session.source,upstream_sha256=session.source.upstream_sha256|{'annual':'d'*64})
    elif change=='approval':params['approvalSha256']='d'*64
    else:headers={}
    response=client.get('/api/v1/company-tax/delivery-owner-review',params=params,headers=headers)
    assert response.status_code in (401,403,404,409,422)
    assert len(confirmation_workflow[3])==count and tuple(session.events)==events


def test_owner_review_default_composition_is_closed(workflow):
    client,body,headers=client_for(workflow,enabled=False)
    params={key:body[key] for key in ('companyId','incomeYear','filingId')}|{'approvalSha256':'a'*64}
    assert client.get('/api/v1/company-tax/delivery-owner-review',params=params,headers=headers).status_code==503
    assert workflow[0].guards==[] and workflow[3]==[]
