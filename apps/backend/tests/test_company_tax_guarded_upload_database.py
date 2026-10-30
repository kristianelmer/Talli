"""Actual signed MFA + owning source topology + finite HTTP guarded upload.

Synthetic local authority only; no real provider or hosted activation claim.
"""
import base64
import json
from pathlib import Path
import subprocess

import psycopg
import pytest

from test_company_tax_delivery_events_database import signed_runtime,ARCHIVE
from test_company_tax_delivery_observations_database import finite_http,start
from test_company_tax_delivery_journal import INSTANCE,DATA

pytestmark=pytest.mark.company_tax_database
UPLOAD='/api/v1/company-tax/delivery-upload-advances'
RECOVER='/api/v1/company-tax/delivery-upload-reconciliations'


def archive(client,draft,headers,version=2):
    return client.get(ARCHIVE,params={'companyId':str(draft.envelope.source.company_id),'incomeYear':2025,
        'readEvidence':True,'readEvidenceVersion':version},headers=headers)


def test_signed_owner_unknown_upload_recovers_exact_originals_without_another_post(signed_runtime):
    with finite_http(signed_runtime,upload=True) as (client,draft,state,token,aal1):
        legacy=client.get(ARCHIVE,params={'companyId':str(draft.envelope.source.company_id),'incomeYear':2025},headers={'Authorization':'Bearer '+token})
        assert legacy.status_code==200 and legacy.json()['sourceFacts']['evidence']['version'].startswith('company-tax-source-v3:')
        command,headers=start(client,draft,token)
        # Before guarded records exist, the previous reader still gets every
        # original through a fully reprojected compatible Source V4 archive.
        assert archive(client,draft,headers,1).json()['sourceFacts']['evidence']['version'].startswith('company-tax-source-v4:')
        state['lostUpload']=True
        unknown=client.post(UPLOAD,json=command,headers=headers)
        assert unknown.status_code==200 and unknown.json()['status']=='uncertain'
        assert unknown.json()['mutationKind']=='upload_envelope'
        before=len(state['calls'])
        assert client.post(UPLOAD,json=command,headers=headers).json()==unknown.json()
        assert len(state['calls'])==before
        result=client.post(RECOVER,json=command,headers=headers)
        assert result.status_code==200 and result.json()['status']=='mutation_completed'
        assert state['calls'][-2:]==[('GET','/skd/formueinntekt-skattemelding-v2/instances/'+INSTANCE),
            ('GET','/skd/formueinntekt-skattemelding-v2/instances/'+INSTANCE+'/data/'+DATA)]
        stored=archive(client,draft,headers)
        assert stored.status_code==200
        value=stored.json()
        assert value['sourceFacts']['historyCoverage']['status']=='complete'
        assert value['sourceFacts']['evidence']['version'].startswith('company-tax-source-v5:')
        completion=json.loads(value['events'][-1]['canonicalJson'])['completion']
        evidence=completion['upload_read_evidence']
        metadata=json.loads(evidence['instance_canonical_json'])['observation']
        file=json.loads(evidence['envelope_canonical_json'])['observation']
        assert base64.b64decode(file['original']['body_base64'])==state['uploaded']==draft.envelope.envelope_xml.encode()
        assert base64.b64decode(metadata['original']['body_base64'])==state['original']
        assert json.loads(base64.b64decode(metadata['original']['body_base64']).decode('utf-8-sig'))['data'][0]['fileScanResult']=='Pending'
        assert value['sourceFacts']['productionAttempts']==[]
        source=client.get('/api/v1/company-tax/source-facts',params={'companyId':str(draft.envelope.source.company_id),'incomeYear':2025},headers=headers)
        assert source.status_code==200
        checked=subprocess.run(['node','tests/support/check-tax-journal-client.mjs'],input=json.dumps({'archive':value,'source':source.json()}),
            text=True,capture_output=True,cwd=Path(__file__).resolve().parents[3],timeout=30)
        assert checked.returncode==0,checked.stdout+checked.stderr
        assert state['grant'].credential not in stored.text
        assert archive(client,draft,headers,1).status_code==503
        assert client.get(ARCHIVE,params={'companyId':str(draft.envelope.source.company_id),'incomeYear':2025},headers=headers).status_code==503
        assert archive(client,draft,headers|{'Authorization':'Bearer '+aal1}).status_code==403
        before=len(state['calls'])
        assert client.post(RECOVER,json=command,headers=headers).json()==result.json()
        assert client.post(UPLOAD,json=command,headers=headers).json()==result.json()
        assert len(state['calls'])==before
        assert sum(method=='POST' for method,_ in state['calls'])==2


def test_signed_upload_requires_current_mfa_and_rejects_caller_proof(signed_runtime):
    with finite_http(signed_runtime,upload=True) as (client,draft,state,token,aal1):
        command,headers=start(client,draft,token);before=len(state['calls'])
        assert client.post(UPLOAD,json=command,headers=headers|{'Authorization':'Bearer '+aal1}).status_code==403
        assert client.post(UPLOAD,json=command|{'uploadPrerequisite':{'empty':True}},headers=headers).status_code==422
        assert client.post(UPLOAD,json=command|{'approvalSha256':'f'*64},headers=headers).status_code==409
        assert len(state['calls'])==before
        result=client.post(UPLOAD,json=command,headers=headers)
        assert result.status_code==200 and result.json()['status']=='mutation_completed'
        assert result.json()['mutationKind']=='upload_envelope'


def test_signed_drift_is_retained_without_clearing_unknown_upload(signed_runtime):
    with finite_http(signed_runtime,upload=True) as (client,draft,state,token,_):
        command,headers=start(client,draft,token);state['lostUpload']=True
        assert client.post(UPLOAD,json=command,headers=headers).json()['status']=='uncertain'
        state['fileBytes']=b'\xef\xbb\xbf'+state['uploaded']
        result=client.post(RECOVER,json=command,headers=headers)
        assert result.status_code==200 and result.json()['status']=='uncertain'
        value=archive(client,draft,headers).json()
        assert value['events'][-1]['slot'].startswith('observation:envelope:')
        original=json.loads(value['events'][-1]['canonicalJson'])['observation']['original']
        assert base64.b64decode(original['body_base64'])==state['fileBytes']
        assert not any(event['slot']=='completion:upload_envelope' for event in value['events'])
        assert sum(method=='POST' for method,_ in state['calls'])==2


def test_signed_known_file_result_survives_revocation_during_get(signed_runtime):
    connection,_,_=signed_runtime;url,_,cid,actor,_=connection
    with psycopg.connect(url) as db:
        accepted=db.execute('select accepted_at from public.company_memberships where company_id=%s and user_id=%s',(cid,str(actor.subject))).fetchone()[0]
    def revoke():
        with psycopg.connect(url) as db:
            db.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',(cid,str(actor.subject)))
    try:
        with finite_http(signed_runtime,upload=True) as (client,draft,state,token,_):
            command,headers=start(client,draft,token);state['lostUpload']=True
            assert client.post(UPLOAD,json=command,headers=headers).json()['status']=='uncertain'
            state['onFile']=revoke
            result=client.post(RECOVER,json=command,headers=headers)
            assert result.status_code==200 and result.json()['status']=='mutation_completed'
            assert archive(client,draft,headers).status_code==404
            with psycopg.connect(url) as db:
                rows=db.execute('select slot,canonical_json from company_tax_filing.delivery_events where filing_id=%s order by sequence',(draft.filing_id,)).fetchall()
                assert rows[-1][0]=='completion:upload_envelope'
                assert json.loads(rows[-1][1])['version']=='company-tax-delivery-mutation-completion-v2'
    finally:
        with psycopg.connect(url) as db:
            db.execute('update public.company_memberships set accepted_at=%s where company_id=%s and user_id=%s',(accepted,cid,str(actor.subject)))
