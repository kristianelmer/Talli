"""Actual signed MFA + owning sources + real finite HTTP validation originals."""
import base64
import json
from pathlib import Path
import subprocess

import psycopg
import pytest
from talli_backend.adapters.company_tax_response_schemas import PinnedTaxValidationResponseSchemas
from talli_backend.modules.company_tax_filing.public import decode_tax_delivery_validation_result_observation

from test_company_tax_delivery_events_database import signed_runtime,ARCHIVE
from test_company_tax_delivery_observations_database import finite_http,start

pytestmark=pytest.mark.company_tax_database
ADVANCE='/api/v1/company-tax/delivery-validation-advances'
RECONCILE='/api/v1/company-tax/delivery-validation-reconciliations'


def upload(client,draft,token):
    command,headers=start(client,draft,token)
    result=client.post('/api/v1/company-tax/delivery-upload-advances',json=command,headers=headers)
    assert result.status_code==200 and result.json()['status']=='mutation_completed'
    return command,headers,result.json()


def checked_archive(client,draft,headers):
    params={'companyId':str(draft.envelope.source.company_id),'incomeYear':2025}
    result=client.get(ARCHIVE,params=params|{'readEvidence':True,'readEvidenceVersion':2,'validationEvidence':True},headers=headers)
    assert result.status_code==200
    value=result.json()
    assert value['sourceFacts']['evidence']['version'].startswith('company-tax-source-v6:')
    source=client.get('/api/v1/company-tax/source-facts',params=params,headers=headers)
    assert source.status_code==200
    checked=subprocess.run(['node','tests/support/check-tax-journal-client.mjs'],input=json.dumps({'archive':value,'source':source.json()}),
        text=True,capture_output=True,cwd=Path(__file__).resolve().parents[3],timeout=30)
    assert checked.returncode==0,checked.stdout+checked.stderr
    return value


def test_signed_validation_keeps_exact_known_job_and_result_originals_through_sdk_and_web(signed_runtime):
    with finite_http(signed_runtime,validation=True) as (client,draft,state,token,_):
        command,headers,upload_receipt=upload(client,draft,token)
        params={'companyId':str(draft.envelope.source.company_id),'incomeYear':2025,'readEvidence':True,'readEvidenceVersion':2}
        assert client.get(ARCHIVE,params=params,headers=headers).json()['sourceFacts']['evidence']['version'].startswith('company-tax-source-v5:')
        result=client.post(ADVANCE,json=command,headers=headers)
        assert result.status_code==200 and result.json()['mutationKind']=='start_validation'
        assert result.json()['status']=='mutation_completed'
        before=len(state['calls'])
        assert client.post(ADVANCE,json=command,headers=headers).json()==result.json()
        assert client.post('/api/v1/company-tax/delivery-upload-advances',json=command,headers=headers).json()==upload_receipt
        assert len(state['calls'])==before
        observed=client.post(RECONCILE,json=command,headers=headers)
        assert observed.status_code==200 and observed.json()==result.json()
        assert state['calls'][-2:][0][1].endswith('/'+state['jobId']+'/status')
        assert state['calls'][-1][1].endswith('/'+state['jobId']+'/resultat')
        value=checked_archive(client,draft,headers)
        start_original=next(json.loads(row['canonicalJson'])['completion'] for row in value['events'] if row['slot']=='completion:start_validation')
        assert base64.b64decode(start_original['response_base64'])==state['startOriginal']
        original=json.loads(value['events'][-1]['canonicalJson'])['observation']['original']
        assert base64.b64decode(original['body_base64'])==state['validationResult']
        retained=decode_tax_delivery_validation_result_observation(value['events'][-1]['canonicalJson'],value['events'][-1]['eventSha256'])
        assert retained.inspect(PinnedTaxValidationResponseSchemas()).guidance_count==1
        assert value['events'][-1]['slot'].startswith('observation:validation-result:')
        assert value['sourceFacts']['productionAttempts']==[]
        assert not any(event['slot']=='intent:prepare_confirmation' for event in value['events'])
        assert state['grant'].credential not in json.dumps(value)
        assert client.get(ARCHIVE,params=params,headers=headers).status_code==503
        count=value['eventCount']
        assert client.post(RECONCILE,json=command,headers=headers).json()==result.json()
        assert checked_archive(client,draft,headers)['eventCount']==count
        assert state['validationPosts']==1 and sum(method=='POST' for method,_ in state['calls'])==3


def test_signed_unknown_start_has_no_lookup_retry_or_false_absence_in_export(signed_runtime):
    with finite_http(signed_runtime,validation=True) as (client,draft,state,token,_):
        command,headers,_=upload(client,draft,token);state['lostValidation']=True
        result=client.post(ADVANCE,json=command,headers=headers)
        assert result.status_code==200 and result.json()['status']=='uncertain'
        before=len(state['calls'])
        assert client.post(ADVANCE,json=command,headers=headers).json()==result.json()
        assert client.post(RECONCILE,json=command,headers=headers).json()==result.json()
        assert len(state['calls'])==before and state['validationPosts']==1
        value=checked_archive(client,draft,headers)
        assert value['events'][-1]['slot']=='intent:start_validation'
        assert value['journals'][0]['status']=='uncertain' and value['journals'][0]['mutationKind']=='start_validation'


def test_signed_validation_needs_actual_step_up_and_rejects_caller_job_proofs(signed_runtime):
    with finite_http(signed_runtime,validation=True) as (client,draft,state,token,aal1):
        command,headers,_=upload(client,draft,token);before=len(state['calls'])
        assert client.post(ADVANCE,json=command,headers=headers|{'Authorization':'Bearer '+aal1}).status_code==403
        for field in ('jobId','validationPrerequisite','validated','actorId','credential'):
            assert client.post(ADVANCE,json=command|{field:'caller supplied'},headers=headers).status_code==422
        assert client.post(ADVANCE,json=command|{'approvalSha256':'f'*64},headers=headers).status_code==409
        assert len(state['calls'])==before
        assert client.post(ADVANCE,json=command,headers=headers).status_code==200


@pytest.mark.parametrize('during',['start','job-read'])
def test_signed_access_change_retains_known_mutation_but_denies_new_read_originals(signed_runtime,during):
    connection,_,_=signed_runtime;url,_,cid,actor,_=connection
    with psycopg.connect(url) as db:
        accepted=db.execute('select accepted_at from public.company_memberships where company_id=%s and user_id=%s',(cid,str(actor.subject))).fetchone()[0]
    def revoke():
        with psycopg.connect(url) as db:
            db.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',(cid,str(actor.subject)))
    try:
        with finite_http(signed_runtime,validation=True) as (client,draft,state,token,_):
            command,headers,_=upload(client,draft,token)
            if during=='start':state['onValidation']=revoke
            started=client.post(ADVANCE,json=command,headers=headers)
            assert started.status_code==200 and started.json()['status']=='mutation_completed'
            if during=='job-read':state['onJob']=revoke
            before=len(state['calls'])
            assert client.post(RECONCILE,json=command,headers=headers).status_code==404
            assert len(state['calls'])==before+(1 if during=='job-read' else 0)
            with psycopg.connect(url) as db:
                slots=[row[0] for row in db.execute('select slot from company_tax_filing.delivery_events where filing_id=%s order by sequence',(draft.filing_id,)).fetchall()]
            assert slots[-1]=='completion:start_validation'
            assert not any(slot.startswith('observation:validation-') for slot in slots)
    finally:
        with psycopg.connect(url) as db:
            db.execute('update public.company_memberships set accepted_at=%s where company_id=%s and user_id=%s',(accepted,cid,str(actor.subject)))
