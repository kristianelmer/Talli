"""Actual signed MFA/full owning source + finite HTTP submission and receipts."""
import base64
import json
from pathlib import Path
import subprocess

import psycopg
import pytest

from test_company_tax_delivery_events_database import signed_runtime
from test_company_tax_delivery_observations_database import finite_http
from test_company_tax_confirmation_database import validated,checked_archive

pytestmark=pytest.mark.company_tax_database
ADVANCE='/api/v1/company-tax/delivery-submission-advances'
RECONCILE='/api/v1/company-tax/delivery-submission-reconciliations'
FEEDBACK='/api/v1/company-tax/delivery-feedback-reconciliations'


def reviewed(client,draft,token):
    command,headers=validated(client,draft,token)
    for route in ('delivery-confirmation-advances','delivery-confirmation-reconciliations'):
        assert client.post('/api/v1/company-tax/'+route,json=command,headers=headers).status_code==200
    response=client.get('/api/v1/company-tax/delivery-owner-review',params=command,headers=headers)
    assert response.status_code==200
    checked=subprocess.run(['node','--experimental-strip-types','tests/support/check-tax-owner-review-client.mjs'],
        input=response.text,text=True,capture_output=True,cwd=Path(__file__).resolve().parents[3],timeout=30)
    assert checked.returncode==0,checked.stdout+checked.stderr
    return command,headers,command|{'ownerReviewSha256':response.json()['artifactSha256'],'documentsConfirmed':True,'warningsAcknowledged':True}


@pytest.mark.parametrize('lost',[False,True])
def test_signed_owner_confirms_once_and_exact_later_receipt_reaches_actual_sdk_and_web(signed_runtime,lost):
    with finite_http(signed_runtime,submission=True) as (client,draft,state,token,aal1):
        command,headers,confirm=reviewed(client,draft,token);before=len(state['calls'])
        assert client.post(ADVANCE,json=confirm,headers=headers|{'Authorization':'Bearer '+aal1}).status_code==403
        assert client.post(ADVANCE,json=confirm|{'warningsAcknowledged':False},headers=headers).status_code==422
        assert len(state['calls'])==before
        state['lostSubmission']=lost
        pending=client.post(ADVANCE,json=confirm,headers=headers)
        assert pending.status_code==200 and pending.json()['status']=='uncertain' and state['submissionPuts']==1
        assert client.post(ADVANCE,json=confirm,headers=headers).json()==pending.json() and state['submissionPuts']==1
        complete=client.post(RECONCILE,json=command,headers=headers)
        assert complete.status_code==200 and complete.json()['status']=='mutation_completed'
        before=len(state['calls'])
        assert client.post(RECONCILE,json=command,headers=headers).json()==complete.json() and len(state['calls'])==before
        state.update(terminal=True,receiptBytes=b'\xef\xbb\xbf <receipt outcome="unclassified"/>\n\xff')
        assert client.post(FEEDBACK,json=command,headers=headers).json()==complete.json()
        value=checked_archive(client,draft,headers,version=8)
        original=next(json.loads(row['canonicalJson'])['observation'] for row in value['events'] if row['slot'].startswith('observation:feedback:'))
        assert base64.b64decode(original['original']['body_base64'])==state['receiptBytes']
        assert state['confirmationPuts']==1 and state['submissionPuts']==1


def test_signed_owner_revocation_during_receipt_download_keeps_original_but_blocks_further_reads(signed_runtime):
    connection,_,_=signed_runtime;url,_,cid,actor,_=connection
    with finite_http(signed_runtime,submission=True) as (client,draft,state,token,_):
        command,headers,confirm=reviewed(client,draft,token)
        assert client.post(ADVANCE,json=confirm,headers=headers).status_code==200
        complete=client.post(RECONCILE,json=command,headers=headers)
        assert complete.status_code==200 and complete.json()['status']=='mutation_completed'
        def revoke():
            with psycopg.connect(url) as db:
                db.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',(cid,str(actor.subject)))
        state.update(terminal=True,receiptBytes=b'\xef\xbb\xbf <receipt/>\n\xff',onFeedback=revoke)
        response=client.post(FEEDBACK,json=command,headers=headers)
        assert response.status_code==200 and response.json()==complete.json()
        with psycopg.connect(url) as db:
            assert db.execute("select count(*) from company_tax_filing.delivery_events where filing_id=%s and slot like 'observation:feedback:%%'",(draft.filing_id,)).fetchone()==(1,)
        before=len(state['calls'])
        assert client.post(FEEDBACK,json=command,headers=headers).status_code in (403,404)
        assert len(state['calls'])==before and state['submissionPuts']==1


def test_signed_revocation_during_current_document_read_blocks_the_next_validation_read(signed_runtime):
    connection,_,_=signed_runtime;url,_,cid,actor,_=connection
    with finite_http(signed_runtime,submission=True) as (client,draft,state,token,_):
        _,headers,confirm=reviewed(client,draft,token)
        def revoke():
            with psycopg.connect(url) as db:
                db.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',(cid,str(actor.subject)))
        state['onCurrent']=revoke;before=len(state['calls'])
        assert client.post(ADVANCE,json=confirm,headers=headers).status_code in (403,404)
        assert len(state['calls'])==before+1 and state['submissionPuts']==0


def test_signed_terminal_receipt_is_retained_then_revocation_blocks_envelope_download(signed_runtime):
    connection,_,_=signed_runtime;url,_,cid,actor,_=connection
    with finite_http(signed_runtime,submission=True) as (client,draft,state,token,_):
        command,headers,confirm=reviewed(client,draft,token)
        assert client.post(ADVANCE,json=confirm,headers=headers).status_code==200
        def revoke():
            with psycopg.connect(url) as db:
                db.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',(cid,str(actor.subject)))
        state.update(terminal=True,receiptBytes=b'\xef\xbb\xbf <opaque/>\n\xff',onFeedback=revoke);before=len(state['calls'])
        assert client.post(RECONCILE,json=command,headers=headers).status_code in (403,404)
        assert len(state['calls'])==before+2 and state['submissionPuts']==1
        with psycopg.connect(url) as db:
            assert db.execute("select count(*) from company_tax_filing.delivery_events where filing_id=%s and slot like 'observation:feedback:%%'",(draft.filing_id,)).fetchone()==(1,)
            assert db.execute("select count(*) from company_tax_filing.delivery_events where filing_id=%s and slot='completion:confirm_submission'",(draft.filing_id,)).fetchone()==(0,)
