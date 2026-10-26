"""Actual signed MFA + full owning sources + real HTTP owner-stage evidence."""
import json
from pathlib import Path
import subprocess

import psycopg
import pytest

from test_company_tax_delivery_events_database import signed_runtime,ARCHIVE
from test_company_tax_delivery_observations_database import finite_http,start

pytestmark=pytest.mark.company_tax_database
ADVANCE='/api/v1/company-tax/delivery-confirmation-advances'
RECONCILE='/api/v1/company-tax/delivery-confirmation-reconciliations'


def validated(client,draft,token):
    command,headers=start(client,draft,token)
    for route in ('delivery-upload-advances','delivery-validation-advances'):
        response=client.post('/api/v1/company-tax/'+route,json=command,headers=headers)
        assert response.status_code==200 and response.json()['status']=='mutation_completed'
    return command,headers


def checked_archive(client,draft,headers):
    params={'companyId':str(draft.envelope.source.company_id),'incomeYear':2025}
    response=client.get(ARCHIVE,params=params|{'readEvidence':True,'readEvidenceVersion':2,'validationEvidence':True,
        'confirmationEvidence':True},headers=headers)
    assert response.status_code==200
    value=response.json();assert value['sourceFacts']['evidence']['version'].startswith('company-tax-source-v7:')
    source=client.get('/api/v1/company-tax/source-facts',params=params,headers=headers);assert source.status_code==200
    checked=subprocess.run(['node','tests/support/check-tax-journal-client.mjs'],input=json.dumps({'archive':value,'source':source.json()}),
        text=True,capture_output=True,cwd=Path(__file__).resolve().parents[3],timeout=30)
    assert checked.returncode==0,checked.stdout+checked.stderr
    return value


@pytest.mark.parametrize('lost',[False,True])
def test_signed_owner_enters_confirmation_once_and_both_archive_readers_keep_exact_originals(signed_runtime,lost):
    with finite_http(signed_runtime,confirmation=True) as (client,draft,state,token,aal1):
        command,headers=validated(client,draft,token);state['lostPreparation']=lost
        count=len(state['calls'])
        assert client.post(ADVANCE,json=command,headers=headers|{'Authorization':'Bearer '+aal1}).status_code==403
        assert len(state['calls'])==count
        pending=client.post(ADVANCE,json=command,headers=headers)
        assert pending.status_code==200 and pending.json()['status']=='uncertain' and state['confirmationPuts']==1
        assert client.post(ADVANCE,json=command,headers=headers).json()==pending.json()
        completed=client.post(RECONCILE,json=command,headers=headers)
        assert completed.status_code==200 and completed.json()['status']=='mutation_completed'
        before=len(state['calls']);assert client.post(RECONCILE,json=command,headers=headers).json()==completed.json()
        assert len(state['calls'])==before and state['confirmationPuts']==1
        response=client.get('/api/v1/company-tax/delivery-owner-review',params=command,headers=headers)
        assert response.status_code==200
        assert client.get('/api/v1/company-tax/delivery-owner-review',params=command,
            headers=headers|{'Authorization':'Bearer '+aal1}).status_code==403
        assert len(state['calls'])==before
        checked=subprocess.run(['node','--experimental-strip-types','tests/support/check-tax-owner-review-client.mjs'],
            input=response.text,text=True,capture_output=True,cwd=Path(__file__).resolve().parents[3],timeout=30)
        assert checked.returncode==0,checked.stdout+checked.stderr
        value=checked_archive(client,draft,headers)
        result=next(json.loads(row['canonicalJson'])['completion'] for row in value['events'] if row['slot']=='completion:prepare_confirmation')
        metadata=json.loads(result['confirmation_read_evidence']['instance_canonical_json'])['observation']
        assert metadata['original']['body_base64']
        if not lost:
            ack=next(json.loads(row['canonicalJson'])['acknowledgment'] for row in value['events'] if row['slot']=='acknowledgment:prepare_confirmation')
            import base64
            assert base64.b64decode(ack['original']['body_base64'])==state['processResponse']
        params={'companyId':str(draft.envelope.source.company_id),'incomeYear':2025,'readEvidence':True,'readEvidenceVersion':2,'validationEvidence':True}
        assert client.get(ARCHIVE,params=params,headers=headers).status_code==503


def test_signed_owner_change_during_put_keeps_ack_but_stops_new_reconciliation_reads(signed_runtime):
    connection,_,_=signed_runtime;url,_,cid,actor,_=connection
    with finite_http(signed_runtime,confirmation=True) as (client,draft,state,token,_):
        command,headers=validated(client,draft,token)
        def revoke():
            with psycopg.connect(url) as db:
                db.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',(cid,str(actor.subject)))
        state['onConfirmation']=revoke
        response=client.post(ADVANCE,json=command,headers=headers)
        assert response.status_code==200 and response.json()['status']=='uncertain'
        with psycopg.connect(url) as db:
            assert db.execute("select count(*) from company_tax_filing.delivery_events where filing_id=%s and slot='acknowledgment:prepare_confirmation'",(draft.filing_id,)).fetchone()==(1,)
        before=len(state['calls'])
        assert client.post(RECONCILE,json=command,headers=headers).status_code in (403,404)
        assert len(state['calls'])==before and state['confirmationPuts']==1
