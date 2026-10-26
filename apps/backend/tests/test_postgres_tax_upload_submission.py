"""Restricted PG17 + real finite HTTP upload and read-only recovery.

Owning Annual/Ledger/Investments are a controlled source seam here; signed full
Company Access/source topology remains a separate mandatory verification.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC,datetime,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import socket
import threading
from uuid import uuid4

import psycopg
import pytest

from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.adapters.loopback_company_tax_delivery import LoopbackCompanyTaxDelivery
from talli_backend.application.company_tax_delivery_rehearsal import TaxDeliveryRehearsalAdmission,TaxDeliveryRehearsalRuntime
from talli_backend.application.company_tax_delivery_submission import CompanyTaxDeliverySubmission
from talli_backend.modules.company_tax_filing.public import ApproveTaxDeliveryDraft,AdvanceTaxDelivery,CompanyTaxError,TaxFilingSubmissionId
from talli_backend.shared.kernel import CorrelationId,IdempotencyKey,Timestamp
from test_company_tax_delivery import ACTOR,COMPANY
from test_company_tax_delivery_draft import draft
from test_postgres_tax_source_snapshot import database
from test_postgres_tax_delivery_draft import draft_database
from test_postgres_tax_current_draft import current_database,current_draft,current_session
from test_postgres_tax_delivery_events import events_database,enable
from test_postgres_tax_delivery_observations import observation_database,enable_observations
from test_postgres_tax_guarded_upload import upload_database,enable_upload
from test_postgres_tax_delivery_submission import journal
from test_company_tax_delivery_observation import instance_document
from test_company_tax_delivery_journal import INSTANCE,DATA

pytestmark=pytest.mark.company_tax_database


@pytest.fixture
def upload_http(upload_database,current_draft,monkeypatch):
    enable(upload_database);enable_observations(upload_database);enable_upload(upload_database)
    with psycopg.connect(**upload_database,user='postgres',autocommit=True) as db:
        db.execute('truncate company_tax_filing.delivery_events,company_tax_filing.delivery_drafts')
    session=current_session(upload_database)
    value=replace(current_draft,filing_id=str(uuid4()),command_key=IdempotencyKey(uuid4().hex))
    async def store():
        async with session.transaction() as tx:await tx.store_delivery_draft(value)
    asyncio.run(store())
    state={'calls':[],'uploadPosts':0,'uploaded':None,'lost':False,'parallel':False,'barrier':threading.Barrier(2),
        'on_upload':lambda:None,'on_file':lambda:None,'errors':[],'key':uuid4().hex+uuid4().hex,'run':str(uuid4())}
    class Authority(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,status,raw,media='application/json'):
            self.send_response(status);self.send_header('Content-Type',media);self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw)
        def check(self):
            assert self.headers.get('X-Talli-Rehearsal-Run')==state['run'] and self.headers.get('X-Talli-Rehearsal-Key')==state['key']
            assert self.headers.get('Authorization') is None
            if not state['parallel']:
                with psycopg.connect(**upload_database,user='postgres',autocommit=True) as db:
                    assert db.execute("select count(*) from pg_stat_activity where usename='snapshot_runtime' and state in ('active','idle in transaction')").fetchone()==(0,)
            state['calls'].append((self.command,self.path))
        def do_GET(self):
            try:
                self.check()
                if self.path=='/api/skattemelding/v2/2025/'+value.envelope.source.organization_number:
                    return self.respond(200,value.current_document.response.raw_bytes)
                if self.path.endswith('/data/'+DATA):
                    state['on_file']();return self.respond(200,state['uploaded'],'application/xml')
                assert self.path=='/skd/formueinntekt-skattemelding-v2/instances/'+INSTANCE
                if state['parallel'] and state['uploaded'] is None:state['barrier'].wait(timeout=5)
                body=instance_document(value)
                if state['uploaded'] is not None:body['data']=[{'id':DATA,'dataType':'skattemeldingOgNaeringsspesifikasjon',
                    'contentType':'application/xml','size':len(state['uploaded']),'fileScanResult':'Pending'}]
                self.respond(200,b'\xef\xbb\xbf'+json.dumps(body).encode()+b'\n')
            except Exception as error:state['errors'].append(type(error).__name__);self.respond(500,b'{}')
        def do_POST(self):
            try:
                self.check();raw=self.rfile.read(int(self.headers['Content-Length']))
                if self.path=='/skd/formueinntekt-skattemelding-v2/instances/':return self.respond(201,json.dumps({'id':INSTANCE}).encode())
                assert self.path=='/skd/formueinntekt-skattemelding-v2/instances/'+INSTANCE+'/data?dataType=skattemeldingOgNaeringsspesifikasjon'
                assert raw==value.envelope.envelope_xml.encode()
                with psycopg.connect(**upload_database,user='postgres',autocommit=True) as db:
                    assert db.execute("select count(*) from company_tax_filing.delivery_events where filing_id=%s and slot='intent:upload_envelope' and canonical_json::jsonb->>'version'='company-tax-delivery-mutation-request-v2'",(value.filing_id,)).fetchone()==(1,)
                state['uploadPosts']+=1;state['uploaded']=raw;state['on_upload']()
                if state['lost']:
                    self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                self.respond(201,json.dumps({'id':DATA,'fileScanResult':'Pending'}).encode())
            except Exception as error:state['errors'].append(type(error).__name__);self.respond(500,b'{}')
    server=ThreadingHTTPServer(('127.0.0.1',0),Authority);server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    issued=Timestamp(datetime.now(UTC))
    grant=TaxDeliveryRehearsalAdmission(state['run'],COMPANY,value.envelope.source.income_year,ACTOR,value.filing_id,value.sha256,
        value.envelope.source.organization_number,issued,Timestamp(issued.value+timedelta(minutes=10)),
        'http://127.0.0.1:'+str(server.server_port),state['key'],session.delivery_rehearsal_target,50)
    runtime=TaxDeliveryRehearsalRuntime(grant)
    service=CompanyTaxDeliverySubmission(runtime,LoopbackCompanyTaxDelivery(runtime),PinnedTax2025Schemas())
    async def source(*args,**kwargs):return value.envelope.source
    from talli_backend.application import company_tax_delivery_submission
    monkeypatch.setattr(company_tax_delivery_submission,'read_company_tax_delivery_source',source)
    review=ApproveTaxDeliveryDraft(COMPANY,value.envelope.source.income_year,ACTOR,TaxFilingSubmissionId(value.filing_id),
        IdempotencyKey('native-upload-review-'+uuid4().hex),CorrelationId('native-upload-review'),value.sha256,value.envelope.review_sha256)
    try:yield session,service,review,state,upload_database
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        assert not thread.is_alive() and not state['errors'],state['errors']


async def create(fixture,*,session=None):
    inner,service,review,*_=fixture;session=session or inner
    approved=await service.approve(session,review)
    command=AdvanceTaxDelivery(review.company_id,review.income_year,review.actor_id,review.filing_id,
        IdempotencyKey('native-upload-operation-'+uuid4().hex),CorrelationId('native-upload-operation'),approved.approval_sha256)
    result=await service.advance(session,command)
    assert result.status=='mutation_completed'
    return command,result


def test_actual_upload_follows_commit_and_lost_response_recovers_only_by_exact_gets(upload_http):
    session,service,_,state,_=upload_http
    async def exercise():
        command,creation=await create(upload_http);state['lost']=True
        unknown=await service.advance_upload(session,command)
        assert unknown.status=='uncertain'
        before=len(state['calls'])
        assert await service.advance_upload(session,command)==unknown
        assert await service.advance(session,command)==creation
        assert len(state['calls'])==before
        recovered=await service.reconcile_upload(session,command)
        assert recovered.status=='mutation_completed'
        assert state['calls'][-2:]==[('GET','/skd/formueinntekt-skattemelding-v2/instances/'+INSTANCE),
            ('GET','/skd/formueinntekt-skattemelding-v2/instances/'+INSTANCE+'/data/'+DATA)]
        evidence=(await journal(session,command)).events[-1].value.upload_read_evidence
        assert evidence.envelope.original.raw_bytes==state['uploaded']
        before=len(state['calls'])
        assert await service.reconcile_upload(session,command)==recovered and len(state['calls'])==before
    asyncio.run(exercise());assert state['uploadPosts']==1


@pytest.mark.parametrize('lost',['intent:upload_envelope','completion:upload_envelope'])
def test_actual_upload_commit_ack_loss_does_not_repeat_the_effect(upload_http,lost):
    inner,service,_,state,_=upload_http
    class Session:
        actor_id=inner.actor_id
        delivery_rehearsal_target=inner.delivery_rehearsal_target
        lose=True
        @asynccontextmanager
        async def transaction(self,*,snapshot=False):
            affected=False
            async with inner.transaction(snapshot=snapshot) as actual:
                class Transaction:
                    def __getattr__(self,name):return getattr(actual,name)
                    async def append_delivery_event(self,value):
                        nonlocal affected
                        result=await actual.append_delivery_event(value);affected=result.event.slot==lost;return result
                yield Transaction()
            if affected and self.lose:self.lose=False;raise CompanyTaxError.unavailable()
    session=Session()
    async def exercise():
        command,_=await create(upload_http,session=session)
        with pytest.raises(CompanyTaxError):await service.advance_upload(session,command)
        before=len(state['calls']);result=await service.advance_upload(session,command)
        assert result.status==('uncertain' if lost.startswith('intent:') else 'mutation_completed') and len(state['calls'])==before
    asyncio.run(exercise());assert state['uploadPosts']==(0 if lost.startswith('intent:') else 1)


def test_two_real_fresh_metadata_readers_elect_one_upload(upload_http,monkeypatch):
    session,service,_,state,_=upload_http
    async def exercise():
        command,_=await create(upload_http);state['parallel']=True
        # The earlier HTTP read reaches storage second. Neither reader may
        # rewrite the first original or reject an otherwise fresh exact read.
        retain=service._retain_read;second_stored=asyncio.Event();first_stored=asyncio.Event();arrivals=0
        async def reverse_storage(*args):
            nonlocal arrivals
            arrivals+=1;position=arrivals
            if position==1:
                await second_stored.wait()
                try:return await retain(*args)
                finally:first_stored.set()
            result=await retain(*args);second_stored.set();await first_stored.wait();return result
        monkeypatch.setattr(service,'_retain_read',reverse_storage)
        results=await asyncio.wait_for(asyncio.gather(service.advance_upload(session,command),service.advance_upload(session,command)),timeout=15)
        assert any(result.status=='mutation_completed' for result in results)
        assert (await service.reconcile_upload(session,command)).status=='mutation_completed'
    asyncio.run(exercise());assert state['uploadPosts']==1


def test_known_file_result_is_recorded_after_actual_revocation_during_file_get(upload_http):
    session,service,_,state,database=upload_http
    def revoke():
        with psycopg.connect(**database,user='postgres',autocommit=True) as db:
            db.execute('delete from public.tax_draft_fixture_owner where company=%s',(str(COMPANY),))
    async def exercise():
        command,_=await create(upload_http);state['lost']=True
        await service.advance_upload(session,command);state['on_file']=revoke
        try:result=await service.reconcile_upload(session,command);assert result.status=='mutation_completed'
        finally:
            with psycopg.connect(**database,user='postgres',autocommit=True) as db:
                db.execute('insert into public.tax_draft_fixture_owner values(%s,%s)',(str(COMPANY),str(ACTOR.subject)))
        assert (await journal(session,command)).events[-1].value.upload_read_evidence is not None
    asyncio.run(exercise());assert state['uploadPosts']==1


@pytest.mark.parametrize('revoked',[False,True])
def test_concurrent_known_file_reconcilers_replay_only_under_current_access(upload_http,revoked):
    session,service,_,state,database=upload_http
    async def exercise():
        command,_=await create(upload_http);state['lost']=True
        assert (await service.advance_upload(session,command)).status=='uncertain'
        state['parallel']=True;both_files=threading.Barrier(2)
        def file_read():
            both_files.wait(timeout=5)
            if revoked:
                with psycopg.connect(**database,user='postgres',autocommit=True) as db:
                    db.execute('delete from public.tax_draft_fixture_owner where company=%s',(str(COMPANY),))
        state['on_file']=file_read
        try:
            results=await asyncio.wait_for(asyncio.gather(service.reconcile_upload(session,command),
                service.reconcile_upload(session,command),return_exceptions=True),timeout=15)
            if revoked:
                errors=[result for result in results if isinstance(result,CompanyTaxError)]
                completed=[result for result in results if not isinstance(result,BaseException)]
                assert len(errors)==1 and errors[0].code=='COMPANY_TAX_NOT_FOUND'
                assert len(completed)==1 and completed[0].status=='mutation_completed'
            else:assert results[0]==results[1] and results[0].status=='mutation_completed'
        finally:
            if revoked:
                with psycopg.connect(**database,user='postgres',autocommit=True) as db:
                    db.execute('insert into public.tax_draft_fixture_owner values(%s,%s)',(str(COMPANY),str(ACTOR.subject)))
        retained=await journal(session,command)
        assert sum(event.slot=='completion:upload_envelope' for event in retained.events)==1
        assert state['uploadPosts']==1
    asyncio.run(exercise())
