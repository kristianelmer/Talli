"""Owned PG17 plus real loopback HTTP: commit-before-send and recovery.

Annual/Ledger/Investments use the already tested source seam here. This fixture
does not substitute for full Supabase/JWT/source topology verification.
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
from talli_backend.modules.company_tax_filing.public import ApproveTaxDeliveryDraft,AdvanceTaxDelivery,CompanyTaxSourceQuery,CompanyTaxError,TaxFilingSubmissionId
from talli_backend.shared.kernel import CorrelationId,IdempotencyKey,Timestamp
from test_company_tax_delivery import ACTOR,COMPANY
from test_company_tax_delivery_draft import draft
from test_postgres_tax_source_snapshot import database
from test_postgres_tax_delivery_draft import draft_database
from test_postgres_tax_current_draft import current_database,current_draft,current_session
from test_postgres_tax_delivery_events import events_database,enable

pytestmark=pytest.mark.company_tax_database


@pytest.fixture
def delivery(events_database,current_draft,monkeypatch):
    enable(events_database)
    with psycopg.connect(**events_database,user='postgres',autocommit=True) as db:
        db.execute('truncate company_tax_filing.delivery_events,company_tax_filing.delivery_drafts')
    session=current_session(events_database)
    value=replace(current_draft,filing_id=str(uuid4()),command_key=IdempotencyKey(uuid4().hex))
    async def store():
        async with session.transaction() as tx:await tx.store_delivery_draft(value)
    asyncio.run(store())
    state={'calls':[],'accepted':0,'lost':False,'parallel':False,'barrier':threading.Barrier(2),
        'on_post':lambda:None,'errors':[],'key':uuid4().hex+uuid4().hex,'run':str(uuid4())}
    body=json.dumps({'instanceOwner':{'organisationNumber':value.envelope.source.organization_number},
        'appId':'skd/formueinntekt-skattemelding-v2','dataValues':{'inntektsaar':2025}},separators=(',',':')).encode()
    result=('\ufeff{"id":"123456/'+str(uuid4())+'"}\n').encode()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,raw):
            self.send_response(status);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def verify(self):
            assert self.headers.get('X-Talli-Rehearsal-Run')==state['run']
            assert self.headers.get('X-Talli-Rehearsal-Key')==state['key']
            if not state['parallel']:
                with psycopg.connect(**events_database,user='postgres',autocommit=True) as probe:
                    assert probe.execute("select count(*) from pg_stat_activity where usename='snapshot_runtime' and state in ('active','idle in transaction')").fetchone()==(0,)
        def do_GET(self):
            try:
                self.verify();state['calls'].append(('GET',self.path))
                assert self.path=='/api/skattemelding/v2/2025/'+value.envelope.source.organization_number
                if state['parallel']:state['barrier'].wait(timeout=5)
                self.send(200,value.current_document.response.raw_bytes)
            except Exception as error:state['errors'].append(type(error).__name__);self.send(500,b'{}')
        def do_POST(self):
            try:
                self.verify();state['calls'].append(('POST',self.path))
                assert self.path=='/skd/formueinntekt-skattemelding-v2/instances/'
                assert self.rfile.read(int(self.headers['Content-Length']))==body
                with psycopg.connect(**events_database,user='postgres',autocommit=True) as probe:
                    assert probe.execute("select count(*) from company_tax_filing.delivery_events where filing_id=%s and slot='intent:create_instance'",(value.filing_id,)).fetchone()==(1,)
                state['accepted']+=1;state['on_post']()
                if state['lost']:
                    self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
                self.send(201,result)
            except Exception as error:state['errors'].append(type(error).__name__);self.send(500,b'{}')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    now=Timestamp(datetime.now(UTC))
    grant=TaxDeliveryRehearsalAdmission(run_id=state['run'],company_id=COMPANY,income_year=value.envelope.source.income_year,
        actor_id=ACTOR,filing_id=value.filing_id,draft_sha256=value.sha256,organization_number=value.envelope.source.organization_number,
        issued_at=now,expires_at=Timestamp(now.value+timedelta(minutes=5)),origin='http://127.0.0.1:'+str(server.server_port),
        credential=state['key'],database_scope_sha256=session.delivery_rehearsal_target,maximum_requests=20)
    runtime=TaxDeliveryRehearsalRuntime(grant)
    service=CompanyTaxDeliverySubmission(runtime,LoopbackCompanyTaxDelivery(runtime),PinnedTax2025Schemas())
    async def source(*args,**kwargs):return value.envelope.source
    from talli_backend.application import company_tax_delivery_submission
    monkeypatch.setattr(company_tax_delivery_submission,'read_company_tax_delivery_source',source)
    command=ApproveTaxDeliveryDraft(COMPANY,value.envelope.source.income_year,ACTOR,TaxFilingSubmissionId(value.filing_id),
        IdempotencyKey('native-delivery-review-'+uuid4().hex),CorrelationId('native-delivery-review'),value.sha256,value.envelope.review_sha256)
    try:yield session,service,command,state,events_database,result
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        assert not thread.is_alive()
        assert not state['errors'],state['errors']


def advancing(command,approved):
    return AdvanceTaxDelivery(command.company_id,command.income_year,command.actor_id,command.filing_id,
        IdempotencyKey('native-delivery-dispatch-'+uuid4().hex),CorrelationId('native-delivery-dispatch'),approved.approval_sha256)


async def journal(session,command):
    query=CompanyTaxSourceQuery(command.company_id,command.income_year,command.actor_id)
    async with session.transaction(snapshot=True) as tx:return await tx.delivery_journal(query,str(command.filing_id))


def test_actual_http_runs_after_intent_commit_and_retains_exact_response_original(delivery):
    session,service,command,state,_,raw=delivery
    async def exercise():
        approved=await service.approve(session,command)
        result=await service.advance(session,advancing(command,approved))
        assert result.status=='mutation_completed'
        retained=await journal(session,command)
        assert retained.events[-1].value.response_bytes==raw
        assert retained.progress==result
        assert await service.advance(session,advancing(command,approved))==result
    asyncio.run(exercise());assert state['accepted']==1


def test_provider_acceptance_with_lost_response_stays_unknown_and_never_resends(delivery):
    session,service,command,state,_,_=delivery
    async def exercise():
        approved=await service.approve(session,command);state['lost']=True
        first=await service.advance(session,advancing(command,approved))
        assert first.status=='uncertain'
        assert await service.advance(session,advancing(command,approved))==first
        assert await service.reconcile(session,advancing(command,approved))==first
        assert len((await journal(session,command)).events)==2
    asyncio.run(exercise());assert state['accepted']==1


@pytest.mark.parametrize('lost',['intent:create_instance','completion:create_instance'])
def test_real_committed_journal_with_lost_acknowledgement_never_duplicates_the_effect(delivery,lost):
    inner,service,command,state,_,_=delivery
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
                        result=await actual.append_delivery_event(value)
                        affected=result.event.slot==lost
                        return result
                yield Transaction()
            if affected and self.lose:
                self.lose=False
                raise CompanyTaxError.unavailable()
    session=Session()
    async def exercise():
        approved=await service.approve(session,command)
        with pytest.raises(CompanyTaxError):await service.advance(session,advancing(command,approved))
        replay=await service.advance(session,advancing(command,approved))
        assert replay.status==('uncertain' if lost.startswith('intent') else 'mutation_completed')
    asyncio.run(exercise());assert state['accepted']==(0 if lost.startswith('intent') else 1)


def test_two_actual_readers_elect_only_one_provider_mutation(delivery):
    session,service,command,state,_,_=delivery
    async def exercise():
        approved=await service.approve(session,command);state['parallel']=True
        first,second=await asyncio.gather(service.advance(session,advancing(command,approved)),
            service.advance(session,advancing(command,approved)))
        assert 'mutation_completed' in (first.status,second.status)
        assert (await service.reconcile(session,advancing(command,approved))).status=='mutation_completed'
    asyncio.run(exercise());assert state['accepted']==1


def test_provider_result_survives_actual_owner_revocation_after_send(delivery):
    session,service,command,state,database,_=delivery
    def revoke():
        with psycopg.connect(**database,user='postgres',autocommit=True) as db:
            db.execute('delete from public.tax_draft_fixture_owner where company=%s',(str(COMPANY),))
    async def exercise():
        approved=await service.approve(session,command);state['on_post']=revoke
        try:
            result=await service.advance(session,advancing(command,approved))
            assert result.status=='mutation_completed'
        finally:
            with psycopg.connect(**database,user='postgres',autocommit=True) as db:
                db.execute('insert into public.tax_draft_fixture_owner values(%s,%s)',(str(COMPANY),str(ACTOR.subject)))
        assert (await journal(session,command)).progress==result
    asyncio.run(exercise());assert state['accepted']==1
