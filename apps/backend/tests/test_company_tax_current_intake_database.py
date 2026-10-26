"""Actual signed MFA/owning source and real finite pre-draft current GET."""
import asyncio
from dataclasses import replace
from contextlib import contextmanager
from datetime import datetime,UTC,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg.conninfo import conninfo_to_dict
import pytest

from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.adapters.loopback_company_tax_intake import LoopbackCompanyTaxIntake
from talli_backend.application.company_tax_intake_rehearsal import TaxCurrentIntakeRehearsalAdmission,TaxCurrentIntakeRehearsalRuntime
from talli_backend.application.company_tax_delivery_rehearsal import loopback_tax_database_scope
from talli_backend.application.company_tax_delivery_preparation import CompanyTaxDeliveryPreparation
from talli_backend.application.company_tax_delivery_source import read_company_tax_delivery_source
from talli_backend.application.company_tax_filing_workflow import CompanyTaxApplication
from talli_backend.modules.company_tax_filing.public import CompanyTaxSourceQuery
from talli_backend.main import create_app
from talli_backend.shared.kernel import Timestamp
from test_company_tax_current_preparation_database import configured
from test_company_tax_delivery_events_database import signed_runtime
from test_company_tax_delivery_observations_database import finite_http
from test_company_tax_final_submission_database import reviewed,ADVANCE,RECONCILE,FEEDBACK
from test_company_tax_confirmation_database import checked_archive

pytestmark=pytest.mark.company_tax_database


@contextmanager
def current_intake_http(signed_runtime):
    connection,token,aal1=signed_runtime;url,backend,cid,actor,sessions=connection
    _,command,legacy_calls,original=configured(connection)
    async def organization():
        session=await sessions.session(token)
        async with session.transaction(snapshot=True) as tx:
            source=await read_company_tax_delivery_source(tx,CompanyTaxSourceQuery(command.company_id,command.income_year,actor),
                correlation_id=command.correlation_id)
        return source.organization_number
    original=replace(original,organization_number=asyncio.run(organization()))
    target=conninfo_to_dict(backend);state={'calls':[],'grant':None,'on_read':lambda:None,'errors':[]}
    path='/api/skattemelding/v2/2025/'+original.organization_number
    class Current(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            try:
                grant=state['grant']
                assert self.path==path and self.headers.get('X-Talli-Intake-Run')==grant.run_id
                assert self.headers.get('X-Talli-Intake-Key')==grant.credential
                assert self.headers.get('Authorization') is None and self.headers.get('X-Talli-Rehearsal-Run') is None
                with psycopg.connect(url,autocommit=True) as db:
                    assert db.execute("select count(*) from pg_stat_activity where usename=%s and state in ('active','idle in transaction')",(target['user'],)).fetchone()==(0,)
                state['calls'].append((self.command,self.path));state['on_read']()
                self.send_response(200);self.send_header('Content-Type','application/xml; charset=utf-8')
                self.send_header('Content-Length',str(len(original.raw_bytes)));self.end_headers();self.wfile.write(original.raw_bytes)
            except Exception as error:
                state['errors'].append(type(error).__name__);self.send_response(500);self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',0),Current);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    client=None
    try:
        issued=Timestamp(datetime.now(UTC));clock=[issued]
        grant=TaxCurrentIntakeRehearsalAdmission(str(uuid4()),command.company_id,command.income_year,actor,original.organization_number,
            issued,Timestamp(issued.value+timedelta(minutes=5)),'http://127.0.0.1:'+str(server.server_port),uuid4().hex+uuid4().hex,
            loopback_tax_database_scope(target['host'],int(target['port']),target['dbname'],target['user']),2)
        state['grant']=grant;runtime=TaxCurrentIntakeRehearsalRuntime(grant,now=lambda:clock[0])
        preparation=CompanyTaxDeliveryPreparation(None,PinnedTax2025Schemas(),intake=LoopbackCompanyTaxIntake(runtime))
        app=CompanyTaxApplication(sessions,lambda tx:None,preparation=preparation)
        client=TestClient(create_app(company_tax_session_factory=sessions,company_tax_delivery_preparation=preparation))
        body={'companyId':str(command.company_id),'incomeYear':2025,'filingId':str(command.filing_id)}
        headers={'Authorization':'Bearer '+token,'Idempotency-Key':str(command.command_key)}
        yield client,app,command,body,headers,state,clock,original,token,aal1
        assert legacy_calls==[]
    finally:
        if client is not None:client.close()
        server.shutdown();server.server_close();thread.join(timeout=5)
        assert not thread.is_alive() and not state['errors'],state['errors']


def retained(app,command,token):
    async def read():return await (await app.session(token)).prepare_delivery_draft(command)
    return asyncio.run(read())


def test_signed_initial_intake_requires_mfa_then_replays_exact_original_after_read_admission_expires(signed_runtime):
    with current_intake_http(signed_runtime) as (client,app,command,body,headers,state,clock,original,token,aal1):
        assert client.post('/api/v1/company-tax/delivery-drafts',json=body,headers=headers|{'Authorization':'Bearer '+aal1}).status_code==403
        assert state['calls']==[]
        response=client.post('/api/v1/company-tax/delivery-drafts',json=body,headers=headers)
        assert response.status_code==200
        stored=retained(app,command,token)
        assert stored.draft.current_document.response.raw_bytes==original.raw_bytes and len(state['calls'])==1
        assert stored.draft.sha256==response.json()['draftSha256']
        clock[0]=state['grant'].expires_at
        assert client.post('/api/v1/company-tax/delivery-drafts',json=body,headers=headers).json()==response.json()
        assert retained(app,command,token)==stored and len(state['calls'])==1


@pytest.mark.parametrize('lost',[False,True])
def test_signed_actual_intake_to_submission_never_uses_a_placeholder_draft_or_mock_current_read(signed_runtime,lost):
    with current_intake_http(signed_runtime) as (client,app,command,body,headers,state,_,original,token,_):
        response=client.post('/api/v1/company-tax/delivery-drafts',json=body,headers=headers);assert response.status_code==200
        draft=retained(app,command,token).draft
        assert len(state['calls'])==1 and draft.current_document.response.raw_bytes==original.raw_bytes
        with finite_http(signed_runtime,submission=True,prepared_current=(command,draft,original)) as (delivery,draft,wire,token,_):
            advance,headers,confirm=reviewed(delivery,draft,token);wire['lostSubmission']=lost
            pending=delivery.post(ADVANCE,json=confirm,headers=headers)
            assert pending.status_code==200 and pending.json()['status']=='uncertain' and wire['submissionPuts']==1
            complete=delivery.post(RECONCILE,json=advance,headers=headers)
            assert complete.status_code==200 and complete.json()['status']=='mutation_completed'
            wire.update(terminal=True,receiptBytes=b'\xef\xbb\xbf <opaque/>\n\xff')
            assert delivery.post(FEEDBACK,json=advance,headers=headers).json()==complete.json()
            checked_archive(delivery,draft,headers,version=8)
            assert len(state['calls'])==1 and wire['confirmationPuts']==1 and wire['submissionPuts']==1


def test_signed_access_loss_during_initial_intake_retains_no_draft_or_submission_authority(signed_runtime):
    connection,_,_=signed_runtime;url,_,cid,actor,_=connection
    with current_intake_http(signed_runtime) as (client,_,command,body,headers,state,*_):
        def revoke():
            with psycopg.connect(url) as db:
                db.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',(cid,str(actor.subject)))
        state['on_read']=revoke
        assert client.post('/api/v1/company-tax/delivery-drafts',json=body,headers=headers).status_code in (403,404)
        assert len(state['calls'])==1
        with psycopg.connect(url) as db:
            assert db.execute('select count(*) from company_tax_filing.delivery_drafts where id=%s',(str(command.filing_id),)).fetchone()==(0,)
            assert db.execute('select count(*) from company_tax_filing.delivery_events where filing_id=%s',(str(command.filing_id),)).fetchone()==(0,)
