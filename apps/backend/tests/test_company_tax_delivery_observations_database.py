"""Signed MFA HTTP + complete owning sources + real finite loopback reads.

This is synthetic local infrastructure. It enables no hosted/live filing and
does not substitute for the remaining browser, scan, validation or receipt flow.
"""
import asyncio
from contextlib import contextmanager
from datetime import UTC,datetime,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import socket
from threading import Thread
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg.conninfo import conninfo_to_dict
import pytest

from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.adapters.company_tax_response_schemas import PinnedTaxValidationResponseSchemas
from talli_backend.adapters.loopback_company_tax_delivery import LoopbackCompanyTaxDelivery
from talli_backend.application.company_tax_delivery_rehearsal import (
    TaxDeliveryRehearsalAdmission,TaxDeliveryRehearsalRuntime,loopback_tax_database_scope,
)
from talli_backend.application.company_tax_delivery_submission import CompanyTaxDeliverySubmission
from talli_backend.main import create_app
from talli_backend.shared.kernel import Timestamp
from test_company_tax_current_preparation_database import configured
from test_company_tax_delivery_events_database import signed_runtime,ARCHIVE
from test_company_tax_delivery_journal import INSTANCE,DATA

pytestmark=pytest.mark.company_tax_database


@contextmanager
def finite_http(signed_runtime,*,upload=False,validation=False,confirmation=False,submission=False):
    confirmation=confirmation or submission
    validation=validation or confirmation
    upload=upload or validation
    connection,token,aal1=signed_runtime;url,backend,cid,actor,sessions=connection
    app,command,_,original=configured(connection);app._sessions=sessions
    async def prepare():return await (await app.session(token)).prepare_delivery_draft(command)
    draft=asyncio.run(prepare()).draft
    state={'calls':[],'grant':None,'revoke':False,'uploaded':None,'lostUpload':False,
        'fileBytes':None,'onFile':lambda:None,'errors':[],
        'scan':'Clean' if validation else 'Pending','validationPosts':0,'lostValidation':False,
        'onValidation':lambda:None,'onJob':lambda:None,'jobStatus':'FERDIG','jobId':'storeDokument-signed-http-v1',
        'validationResult':b'\xef\xbb\xbf<skattemeldingOgNaeringsspesifikasjonResponse xmlns="no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:response:v2"><veiledningEtterKontroll><veiledning><veiledningstype>guidance</veiledningstype><hjelpetekst>Kontroller bel\xc3\xb8pet</hjelpetekst></veiledning></veiledningEtterKontroll><resultatAvValidering>validertOK</resultatAvValidering></skattemeldingOgNaeringsspesifikasjonResponse>\n'}
    if confirmation:
        from test_company_tax_calculated_schemas import documents,result
        state.update(validationResult=result(documents(draft)).raw_bytes,processTask='data',processElement='Task_1',processFlow=1,
            confirmationPuts=0,lostPreparation=False,onConfirmation=lambda:None,
            processResponse=b'\xef\xbb\xbf {"currentTask":{"altinnTaskType":"confirmation"}}\n')
    if submission:state.update(submissionPuts=0,lostSubmission=False,onSubmission=lambda:None,onFeedback=lambda:None)
    user=conninfo_to_dict(backend)['user']
    class Authority(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,status,raw,media='application/json; charset=utf-8'):
            self.send_response(status);self.send_header('Content-Type',media)
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def check_request(self):
            grant=state['grant']
            assert self.headers['X-Talli-Rehearsal-Run']==grant.run_id
            assert self.headers['X-Talli-Rehearsal-Key']==grant.credential
            assert self.headers.get('Authorization') is None
            with psycopg.connect(url,autocommit=True) as db:
                assert db.execute("select count(*) from pg_stat_activity where usename=%s and state in ('active','idle in transaction')",(user,)).fetchone()==(0,)
            state['calls'].append((self.command,self.path))
        def do_GET(self):
            self.check_request()
            if self.path=='/api/skattemelding/v2/2025/'+draft.envelope.source.organization_number:
                state.get('onCurrent',lambda:None)()
                return self.respond(200,original.raw_bytes)
            if validation and self.path.endswith('/'+state['jobId']+'/status'):
                state['onJob']()
                return self.respond(200,json.dumps({'jobbStatus':state['jobStatus'],'forrigeStatus':'KJOERER',
                    'sekunderSidenOpprettelse':0,'sekunderSidenEndring':0}).encode())
            if validation and self.path.endswith('/'+state['jobId']+'/resultat'):
                return self.respond(200,state['validationResult'],'application/xml')
            if upload and self.path=='/skd/formueinntekt-skattemelding-v2/instances/'+INSTANCE+'/data/'+DATA:
                state['onFile']()
                return self.respond(200,state['uploaded'] if state['fileBytes'] is None else state['fileBytes'],'application/xml')
            if submission and state.get('receiptBytes') is not None and self.path.endswith('/data/00000000-0000-4000-8000-000000009999'):
                state['onFeedback']();return self.respond(200,state['receiptBytes'],'text/xml')
            assert self.path=='/skd/formueinntekt-skattemelding-v2/instances/'+INSTANCE
            if state['revoke']:
                with psycopg.connect(url) as db:
                    db.execute('update public.company_memberships set accepted_at=null where company_id=%s and user_id=%s',(cid,str(actor.subject)))
            value={'id':INSTANCE,'appId':'skd/formueinntekt-skattemelding-v2',
                'instanceOwner':{'organisationNumber':draft.envelope.source.organization_number},
                'dataValues':{'inntektsaar':2025},'process':{'currentTask':{'altinnTaskType':'data'}},
                'status':{'isArchived':False},'data':[]}
            if confirmation:value['process']['currentTask']|={'altinnTaskType':state['processTask'],
                'elementId':state['processElement'],'flow':state['processFlow']}
            if upload and state['uploaded'] is not None:
                raw=state['uploaded'] if state['fileBytes'] is None else state['fileBytes']
                value['data']=[{'id':DATA,'dataType':'skattemeldingOgNaeringsspesifikasjon',
                    'contentType':'application/xml','size':len(raw),'fileScanResult':state['scan']}]
            if submission and state.get('receiptBytes') is not None:value['data'].append({'id':'00000000-0000-4000-8000-000000009999',
                'dataType':'tilbakemelding','contentType':'text/xml','size':len(state['receiptBytes']),'fileScanResult':'Clean'})
            if submission and state.get('terminal'):
                terminal_at=state.setdefault('terminalAt',datetime.now(UTC).isoformat())
                value['process']['currentTask']=None;value['process']['ended']=terminal_at
                value['status']={'isArchived':True,'archived':terminal_at}
            state['original']=b'\xef\xbb\xbf'+json.dumps(value,indent=2).encode()+b'\n'
            self.respond(200,state['original'])
        def do_PUT(self):
            self.check_request();body=self.rfile.read(int(self.headers['Content-Length']))
            assert confirmation and self.path=='/skd/formueinntekt-skattemelding-v2/instances/'+INSTANCE+'/process/next'
            assert body==b'' and self.headers['Content-Type']=='application/json'
            if submission:
                with psycopg.connect(url) as db:
                    rows=db.execute("select canonical_json from company_tax_filing.delivery_events where filing_id=%s and slot='intent:confirm_submission'",(draft.filing_id,)).fetchall()
                if rows:
                    assert len(rows)==1 and json.loads(rows[0][0])['version']=='company-tax-delivery-mutation-request-v5'
                    assert state['processTask']=='confirmation' and state['processElement']=='Task_2'
                    state['submissionPuts']+=1;state.update(processTask='feedback',processElement='Task_3',processFlow=3)
                    state['onSubmission']()
                    if state['lostSubmission']:
                        self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                    return self.respond(200,state['processResponse'])
            with psycopg.connect(url) as db:
                rows=db.execute("select canonical_json from company_tax_filing.delivery_events where filing_id=%s and slot='intent:prepare_confirmation'",(draft.filing_id,)).fetchall()
                assert len(rows)==1 and json.loads(rows[0][0])['version']=='company-tax-delivery-mutation-request-v4'
            state['confirmationPuts']+=1;state.update(processTask='confirmation',processElement='Task_2',processFlow=2)
            state['onConfirmation']()
            if state['lostPreparation']:
                self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
            self.respond(200,state['processResponse'])
        def do_POST(self):
            self.check_request()
            body=self.rfile.read(int(self.headers['Content-Length']))
            with psycopg.connect(url) as db:
                rows=db.execute('select slot,canonical_json from company_tax_filing.delivery_events where filing_id=%s order by sequence',(draft.filing_id,)).fetchall()
                import base64
                if validation and self.path=='/api/skattemelding/v2/jobb/altinn/2025/'+draft.envelope.source.organization_number+'/start':
                    assert rows[-1][0]=='intent:start_validation'
                    assert json.loads(rows[-1][1])['version']=='company-tax-delivery-mutation-request-v3'
                    assert base64.b64decode(json.loads(rows[-1][1])['request']['body_base64'])==body
                    assert json.loads(body)=={'appId':'skd/formueinntekt-skattemelding-v2','instansId':INSTANCE}
                    state['validationPosts']+=1;state['onValidation']()
                    if state['lostValidation']:
                        self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                    state['startOriginal']=b'\xef\xbb\xbf \n'+json.dumps({'jobbId':state['jobId'],'jobbStatus':'OPPRETTET'}).encode()+b'\n'
                    return self.respond(200,state['startOriginal'])
                if upload and self.path=='/skd/formueinntekt-skattemelding-v2/instances/'+INSTANCE+'/data?dataType=skattemeldingOgNaeringsspesifikasjon':
                    assert rows[-1][0]=='intent:upload_envelope'
                    assert base64.b64decode(json.loads(rows[-1][1])['request']['body_base64'])==body==draft.envelope.envelope_xml.encode()
                    assert sum(row[0]=='intent:upload_envelope' for row in rows)==1
                    state['uploaded']=body
                    if state['lostUpload']:
                        self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                    return self.respond(201,json.dumps({'id':DATA,'fileScanResult':'Pending'}).encode())
                assert self.path=='/skd/formueinntekt-skattemelding-v2/instances/'
                assert [row[0] for row in rows]==['review','admission','intent:create_instance']
                assert base64.b64decode(json.loads(rows[-1][1])['request']['body_base64'])==body
            self.respond(201,('\ufeff{"id":"'+INSTANCE+'"}\n').encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Authority);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        target=conninfo_to_dict(backend)
        issued=Timestamp(datetime.now(UTC))
        grant=TaxDeliveryRehearsalAdmission(str(uuid4()),command.company_id,command.income_year,actor,draft.filing_id,
            draft.sha256,draft.envelope.source.organization_number,issued,Timestamp(issued.value+timedelta(minutes=10)),
            'http://127.0.0.1:'+str(server.server_port),uuid4().hex+uuid4().hex,
            loopback_tax_database_scope(target['host'],int(target['port']),target['dbname'],target['user']),80 if submission else 40)
        state['grant']=grant
        runtime=TaxDeliveryRehearsalRuntime(grant)
        submission_service=CompanyTaxDeliverySubmission(runtime,LoopbackCompanyTaxDelivery(runtime),PinnedTax2025Schemas(),
            response_schemas=PinnedTaxValidationResponseSchemas() if validation else None)
        if confirmation:
            from talli_backend.adapters.company_tax_calculated_schemas import PinnedTax2025CalculatedSchemas
            submission_service._calculated_schemas=PinnedTax2025CalculatedSchemas()
        client=TestClient(create_app(company_tax_session_factory=sessions,company_tax_delivery_submission=submission_service))
        yield client,draft,state,token,aal1
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5);assert not thread.is_alive()


def start(client,draft,token):
    headers={'Authorization':'Bearer '+token,'Idempotency-Key':'signed-finite-tax-review-v1'}
    body={'companyId':str(draft.envelope.source.company_id),'incomeYear':2025,'filingId':draft.filing_id,
        'draftSha256':draft.sha256,'reviewSha256':draft.envelope.review_sha256}
    approved=client.post('/api/v1/company-tax/delivery-reviews',json=body,headers=headers)
    assert approved.status_code==200
    advance={key:body[key] for key in ('companyId','incomeYear','filingId')}|{'approvalSha256':approved.json()['approvalSha256']}
    response=client.post('/api/v1/company-tax/delivery-advances',json=advance,headers=headers)
    assert response.status_code==200 and response.json()['status']=='mutation_completed'
    return advance,headers


def test_signed_owner_reads_archive_exact_originals_without_poll_generation_churn(signed_runtime):
    connection,_,_=signed_runtime;url,_,cid,_,_=connection
    with finite_http(signed_runtime) as (client,draft,state,token,aal1):
        advance,headers=start(client,draft,token)
        response=client.post('/api/v1/company-tax/delivery-reconciliations',json=advance,headers=headers)
        assert response.status_code==200 and response.json()['status']=='mutation_completed'
        assert response.json()['mutationKind']=='create_instance'
        params={'companyId':str(cid),'incomeYear':2025,'readEvidence':True}
        assert client.get(ARCHIVE,params={key:value for key,value in params.items() if key!='readEvidence'},headers=headers).status_code==503
        archive=client.get(ARCHIVE,params=params,headers=headers)
        assert archive.status_code==200
        value=archive.json()
        assert value['sourceFacts']['evidence']['version']=='company-tax-source-v4:'+value['sourceSha256']
        assert value['sourceFacts']['historyCoverage']['status']=='complete' and value['eventCount']==5
        assert value['events'][1]['slot']=='admission'
        original=json.loads(value['events'][-1]['canonicalJson'])['observation']['original']
        import base64
        assert base64.b64decode(original['body_base64'])==state['original']
        assert state['grant'].credential not in archive.text
        with psycopg.connect(url) as db:
            before=db.execute('select generation from public.company_archive_source_generations where company_id=%s and income_year=2025',(cid,)).fetchone()
        assert client.post('/api/v1/company-tax/delivery-reconciliations',json=advance,headers=headers).json()==response.json()
        with psycopg.connect(url) as db:
            assert db.execute('select generation from public.company_archive_source_generations where company_id=%s and income_year=2025',(cid,)).fetchone()==before
        assert client.get(ARCHIVE,params=params,headers={'Authorization':'Bearer '+aal1}).status_code==403
        assert client.post('/api/v1/company-tax/delivery-reconciliations',json=advance,headers=headers|{'Authorization':'Bearer '+aal1}).status_code==403
        assert len([method for method,_ in state['calls'] if method=='POST'])==1


def test_signed_owner_revoked_during_instance_get_keeps_create_but_discloses_no_new_read(signed_runtime):
    connection,_,_=signed_runtime;url,_,cid,actor,_=connection
    with psycopg.connect(url) as db:
        accepted=db.execute('select accepted_at from public.company_memberships where company_id=%s and user_id=%s',(cid,str(actor.subject))).fetchone()[0]
    try:
        with finite_http(signed_runtime) as (client,draft,state,token,_):
            advance,headers=start(client,draft,token);state['revoke']=True
            response=client.post('/api/v1/company-tax/delivery-reconciliations',json=advance,headers=headers)
            assert response.status_code==404
            with psycopg.connect(url) as db:
                slots=[row[0] for row in db.execute('select slot from company_tax_filing.delivery_events where filing_id=%s order by sequence',(draft.filing_id,)).fetchall()]
            assert slots==['review','admission','intent:create_instance','completion:create_instance']
            before=len(state['calls'])
            assert client.post('/api/v1/company-tax/delivery-reconciliations',json=advance,headers=headers).status_code==404
            assert len(state['calls'])==before
    finally:
        with psycopg.connect(url) as db:
            db.execute('update public.company_memberships set accepted_at=%s where company_id=%s and user_id=%s',(accepted,cid,str(actor.subject)))
