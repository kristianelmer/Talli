"""Synthetic authority and trusted composition, never imported by product code.

No draft/result is preseeded. A grant is issued once, only after actual SQL
preparation returns its exact SHA. All real services, RLS and JWT verification
remain in the request path. Every provider socket is confined to loopback.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime,UTC,timedelta
import base64
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from threading import Thread,RLock
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict

from talli_backend.adapters.postgres_company_tax_filing import PostgresCompanyTaxAdapter
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration
from talli_backend.adapters.company_tax_schemas import PinnedTax2025Schemas
from talli_backend.adapters.company_tax_response_schemas import PinnedTaxValidationResponseSchemas
from talli_backend.adapters.company_tax_calculated_schemas import PinnedTax2025CalculatedSchemas
from talli_backend.adapters.loopback_company_tax_delivery import LoopbackCompanyTaxDelivery
from talli_backend.adapters.loopback_company_tax_intake import LoopbackCompanyTaxIntake
from talli_backend.adapters.loopback_company_tax_parent_read import LoopbackCompanyTaxParentRead
from talli_backend.application.company_tax_delivery_preparation import CompanyTaxDeliveryPreparation
from talli_backend.application.company_tax_delivery_submission import CompanyTaxDeliverySubmission
from talli_backend.application.company_tax_delivery_rehearsal import TaxDeliveryRehearsalAdmission,TaxDeliveryRehearsalRuntime,loopback_tax_database_scope
from talli_backend.application.company_tax_intake_rehearsal import TaxCurrentIntakeRehearsalAdmission,TaxCurrentIntakeRehearsalRuntime
from talli_backend.application.company_tax_parent_read_rehearsal import TaxParentReadRehearsalAdmission,TaxParentReadRehearsalRuntime
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxError,CompanyTaxSourceQuery,TaxDeliveryValidationResultObservation,
)
from talli_backend.shared.kernel import ActorId,ActorKind,UserId,CompanyId,IncomeYear,Timestamp
from talli_backend.main import create_app
from fastapi import Header,HTTPException

_DEPTH=ContextVar('tax_browser_sql_depth',default=0)
_APP='/skd/formueinntekt-skattemelding-v2/instances/'
_CURRENT_NS='no:skatteetaten:fastsetting:formueinntekt:skattemeldingognaeringsspesifikasjon:forespoersel:response:v2'


class _Session:
    def __init__(self,actual):self.actual=actual
    @property
    def actor_id(self):return self.actual.actor_id
    @property
    def delivery_rehearsal_target(self):return self.actual.delivery_rehearsal_target
    @asynccontextmanager
    async def transaction(self,*,snapshot=False):
        async with self.actual.transaction(snapshot=snapshot) as transaction:
            token=_DEPTH.set(_DEPTH.get()+1)
            try:yield transaction
            finally:_DEPTH.reset(token)


class _Sessions:
    def __init__(self,actual):self.actual=actual
    async def session(self,token):return _Session(await self.actual.session(token))


class _NoSqlAuthority:
    def __init__(self,actual):self.actual=actual
    def available(self,*args):return self.actual.available(*args)
    def __getattr__(self,name):
        actual=getattr(self.actual,name)
        async def call(*args,**kwargs):
            assert _DEPTH.get()==0,'Authority I/O must follow SQL closure.'
            return await actual(*args,**kwargs)
        return call


class _ParentReader:
    def __init__(self,runtime):self.runtime=runtime
    def available(self,query,journal):
        reader=self.runtime.parents.get(journal.draft.filing_id)
        return reader is not None and reader.available(query,journal)
    def __getattr__(self,name):
        if name not in ('read_parent_instance','read_parent_feedback','read_parent_envelope'):raise AttributeError(name)
        async def call(query,journal,*args):
            reader=self.runtime.parents.get(journal.draft.filing_id)
            if reader is None:raise CompanyTaxError.unavailable()
            return await getattr(reader,name)(query,journal,*args)
        return call


class _Preparation:
    def __init__(self,runtime,actual):self.runtime=runtime;self.actual=actual
    def workspace_admission(self,*args):return self.actual.workspace_admission(*args)
    async def prepare(self,session,command):
        stored=await self.actual.prepare(session,command)
        self.runtime.register(stored.draft,session)
        return stored


class _Submission:
    _METHODS=frozenset(('approve','advance','reconcile','advance_upload','reconcile_upload','advance_validation','reconcile_validation',
        'advance_confirmation','reconcile_confirmation','advance_submission','reconcile_submission','reconcile_feedback','owner_review'))
    def __init__(self,runtime):self.runtime=runtime
    def workspace_admission(self,session,draft):
        service=self.runtime.services.get(draft.filing_id)
        return service is not None and service.workspace_admission(session,draft)
    def workspace_validation(self,journal):
        service=self.runtime.services.get(journal.draft.filing_id)
        return None if service is None else service.workspace_validation(journal)
    def __getattr__(self,name):
        if name not in self._METHODS:raise AttributeError(name)
        async def call(session,command):
            service=self.runtime.services.get(str(command.filing_id))
            if service is None:raise CompanyTaxError.unavailable()
            value=await getattr(service,name)(session,command)
            if name in ('reconcile_submission','reconcile_feedback'):await self.runtime.known_parent(session,command)
            return value
        return call


class _Runtime:
    def __init__(self):
        self.company=CompanyId(os.environ['TALLI_TAX_BROWSER_COMPANY_ID']);self.actor=ActorId(ActorKind.USER,UserId(os.environ['TALLI_TAX_BROWSER_OWNER_ID']))
        self.organization=os.environ['TALLI_TAX_BROWSER_ORG'];self.database=os.environ['DATABASE_URL']
        target=conninfo_to_dict(os.environ['TALLI_LEDGER_DATABASE_URL'])
        self.database_scope=loopback_tax_database_scope(target['host'],int(target['port']),target['dbname'],target['user'])
        assert self.database_scope is not None
        self.schemas=PinnedTax2025Schemas();self.responses=PinnedTaxValidationResponseSchemas();self.calculated=PinnedTax2025CalculatedSchemas()
        self.lock=RLock();self.services={};self.drafts={};self.parents={};self.grants={};self.instances={};self.calls=[];self.errors=[]
        self.current_pair=None;self.current_reference='synthetic-current-before-first-delivery'
        self.server=ThreadingHTTPServer(('127.0.0.1',0),self.handler());self.server.daemon_threads=True
        self.origin='http://127.0.0.1:'+str(self.server.server_port)
        self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        grant=self.read_scope(2);self.grants[grant.credential]=('intake',grant,None)
        intake=_NoSqlAuthority(LoopbackCompanyTaxIntake(TaxCurrentIntakeRehearsalRuntime(grant)))
        self.preparation=_Preparation(self,CompanyTaxDeliveryPreparation(None,self.schemas,intake=intake,parent_reader=_ParentReader(self)))

    def read_scope(self,maximum):
        now=Timestamp(datetime.now(UTC))
        return TaxCurrentIntakeRehearsalAdmission(str(uuid4()),self.company,IncomeYear(2025),self.actor,self.organization,now,
            Timestamp(now.value+timedelta(minutes=5)),self.origin,uuid4().hex+uuid4().hex,self.database_scope,maximum)

    def register(self,draft,session):
        assert session.actor_id==self.actor and session.delivery_rehearsal_target==self.database_scope
        assert draft.envelope.source.company_id==self.company and draft.envelope.source.organization_number==self.organization
        with self.lock:
            if draft.filing_id in self.services:
                assert self.drafts[draft.filing_id]==draft;return
            assert len(self.services)<64
            issued=Timestamp(datetime.now(UTC))
            grant=TaxDeliveryRehearsalAdmission(str(uuid4()),self.company,IncomeYear(2025),self.actor,draft.filing_id,draft.sha256,
                self.organization,issued,Timestamp(issued.value+timedelta(minutes=10)),self.origin,uuid4().hex+uuid4().hex,self.database_scope,150)
            self.grants[grant.credential]=('delivery',grant,draft.filing_id);self.drafts[draft.filing_id]=draft
            runtime=TaxDeliveryRehearsalRuntime(grant)
            self.services[draft.filing_id]=CompanyTaxDeliverySubmission(runtime,_NoSqlAuthority(LoopbackCompanyTaxDelivery(runtime)),self.schemas,
                response_schemas=self.responses,calculated_schemas=self.calculated)

    async def known_parent(self,session,command):
        query=CompanyTaxSourceQuery(self.company,IncomeYear(2025),session.actor_id)
        async with session.transaction() as guard:
            await guard.lock_delivery_draft_archive(query)
            async with session.transaction(snapshot=True) as tx:journal=await tx.delivery_journal(query,str(command.filing_id))
        events={event.slot:event.value for event in journal.events}
        if 'completion:confirm_submission' not in events:return
        with self.lock:
            if journal.draft.filing_id in self.parents:return
            scope=self.read_scope(3)
            grant=TaxParentReadRehearsalAdmission(scope,journal.draft.filing_id,journal.draft.sha256,journal.approval.sha256,
                events['completion:create_instance'].result['instanceId'])
            self.grants[scope.credential]=('parent',scope,journal.draft.filing_id)
            self.parents[journal.draft.filing_id]=_NoSqlAuthority(LoopbackCompanyTaxParentRead(TaxParentReadRehearsalRuntime(grant)))
            documents=events['intent:prepare_confirmation'].confirmation_prerequisite.calculated.response.calculated_documents
            self.current_pair={document.document_type:document.raw_bytes for document in documents}
            self.current_reference='synthetic-current-after-'+journal.draft.filing_id

    def current(self):
        pair=self.current_pair
        tax=(b'<skattemelding xmlns="urn:no:skatteetaten:fastsetting:formueinntekt:skattemelding:upersonlig:ekstern:v5">'
            b'<partsnummer>123456</partsnummer><inntektsaar>2025</inntektsaar></skattemelding>') if pair is None else pair['skattemeldingUpersonligEtterBeregning']
        business='' if pair is None else '<naeringsspesifikasjondokument><id>known-submitted-business</id><encoding>utf-8</encoding><content>'+base64.b64encode(pair['naeringsspesifikasjonEtterBeregning']).decode()+'</content></naeringsspesifikasjondokument>'
        return (f'\ufeff<skattemeldingOgNaeringsspesifikasjonforespoerselResponse xmlns="{_CURRENT_NS}"><dokumenter>'
            f'<skattemeldingdokument><id>{self.current_reference}</id><encoding>utf-8</encoding><content>{base64.b64encode(tax).decode()}</content>'
            f'<type>skattemeldingUpersonligFastsatt</type></skattemeldingdokument>{business}</dokumenter></skattemeldingOgNaeringsspesifikasjonforespoerselResponse>\n').encode()

    def committed(self,filing,kind,body):
        with psycopg.connect(self.database,autocommit=True) as db:
            row=db.execute('select canonical_json from company_tax_filing.delivery_events where company_id=%s and filing_id=%s and slot=%s',
                (str(self.company),filing,'intent:'+kind)).fetchone()
        assert row is not None,'External mutation must follow committed intent.'
        request=json.loads(row[0])['request'];assert request['kind']==kind and base64.b64decode(request['body_base64'])==body

    def handler(self):
        runtime=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def respond(self,status,raw,media='application/json'):
                self.send_response(status);self.send_header('Content-Type',media);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def dispatch(self):
                try:
                    assert self.headers.get('Authorization') is None
                    families=(('intake','X-Talli-Intake-Run','X-Talli-Intake-Key'),('parent','X-Talli-Parent-Run','X-Talli-Parent-Key'),('delivery','X-Talli-Rehearsal-Run','X-Talli-Rehearsal-Key'))
                    selected=[family for family in families if self.headers.get(family[2]) is not None];assert len(selected)==1
                    family,run,key=selected[0];entry=runtime.grants.get(self.headers[key]);assert entry is not None
                    kind,grant,filing=entry;assert kind==family and self.headers[run]==grant.run_id
                    body=self.rfile.read(int(self.headers.get('Content-Length','0')));assert len(body)<=8*1024*1024
                    with runtime.lock:
                        runtime.calls.append({'method':self.command,'path':self.path,'filingId':filing,'family':family})
                        if self.command=='GET' and self.path=='/api/skattemelding/v2/2025/'+runtime.organization:
                            assert family in ('intake','delivery');return self.respond(200,runtime.current(),'application/xml')
                        assert family in ('delivery','parent') and filing is not None
                        state=runtime.instances.get(filing)
                        if self.command=='POST' and self.path==_APP:
                            assert family=='delivery' and state is None
                            runtime.committed(filing,'create_instance',body)
                            state={'instance':'123456/'+str(uuid4()),'data':str(uuid4()),'receipt':str(uuid4()),'uploaded':None,'step':1,
                                'job':'storeDokument-'+uuid4().hex,'confirmationPuts':0,'submissionPuts':0}
                            runtime.instances[filing]=state
                            return self.respond(201,('\ufeff'+json.dumps({'id':state['instance']})+'\n').encode())
                        assert state is not None
                        if self.command=='GET':
                            if self.path==_APP+state['instance']:
                                data=[]
                                if state['uploaded'] is not None:data.append({'id':state['data'],'dataType':'skattemeldingOgNaeringsspesifikasjon',
                                    'contentType':'application/xml','size':len(state['uploaded']),'fileScanResult':'Clean'})
                                if state['step']==3:data.append({'id':state['receipt'],'dataType':'tilbakemelding','contentType':'text/xml','size':len(state['receiptBytes']),'fileScanResult':'Clean'})
                                process={'currentTask':{'altinnTaskType':'data' if state['step']==1 else 'confirmation','elementId':'Task_1' if state['step']==1 else 'Task_2','flow':state['step']}}
                                status={'isArchived':False}
                                if state['step']==3:process={'currentTask':None,'ended':state['terminalAt']};status={'isArchived':True,'archived':state['terminalAt']}
                                value={'id':state['instance'],'appId':'skd/formueinntekt-skattemelding-v2','instanceOwner':{'organisationNumber':runtime.organization},
                                    'dataValues':{'inntektsaar':2025},'process':process,'status':status,'data':data}
                                return self.respond(200,b'\xef\xbb\xbf'+json.dumps(value,indent=2).encode()+b'\n')
                            if self.path==_APP+state['instance']+'/data/'+state['data']:
                                assert state['uploaded'] is not None;return self.respond(200,state['uploaded'],'application/xml')
                            if self.path==_APP+state['instance']+'/data/'+state['receipt']:
                                assert state['step']==3;return self.respond(200,state['receiptBytes'],'text/xml')
                            assert family=='delivery' and state.get('validationStarted')
                            prefix='/api/skattemelding/v2/jobb/altinn/2025/'+runtime.organization+'/'+state['job']
                            if self.path==prefix+'/status':return self.respond(200,b'{"jobbStatus":"FERDIG","forrigeStatus":"KJOERER","sekunderSidenOpprettelse":0,"sekunderSidenEndring":0}')
                            assert self.path==prefix+'/resultat'
                            from test_company_tax_calculated_schemas import documents,result
                            blocked=os.environ.get('TALLI_TAX_BROWSER_VALIDATION_BLOCKED')=='true'
                            notes='<veiledningEtterKontroll><veiledning><veiledningstype>review</veiledningstype><hjelpetekst>Kontroller alle feltene.</hjelpetekst></veiledning></veiledningEtterKontroll>'
                            if blocked:notes+='<avvikVedValidering><avvik><avvikstype>synthetic-block</avvikstype><mottattVerdi>123</mottattVerdi><sti>test.felt</sti></avvik></avvikVedValidering>'
                            after=('<aarsakTilValidertMedFeil>Kontroller dette feltet.</aarsakTilValidertMedFeil>' if blocked else '')+'<informasjonOmUpersonligSkattesubjekt><erFritattForFormuesskatt>true</erFritattForFormuesskatt><erOmfattetAvSaerreglerForKraftforetak>false</erOmfattetAvSaerreglerForKraftforetak><erOmfattetAvPetroleumsskatteloven>false</erOmfattetAvPetroleumsskatteloven><erOmfattetAvRederiskatteordningen>false</erOmfattetAvRederiskatteordningen><erOmfattetAvFinansskattPaaLoennOgOverskudd>false</erOmfattetAvFinansskattPaaLoennOgOverskudd><harLeveringsfritak>false</harLeveringsfritak></informasjonOmUpersonligSkattesubjekt>'
                            values=documents(runtime.drafts[filing])
                            if os.environ.get('TALLI_TAX_BROWSER_PARTIAL_CALCULATED')=='true':
                                state['validationReads']=state.get('validationReads',0)+1
                                kind='skattemeldingUpersonligEtterBeregning'
                                values={kind:values[kind].replace(b'<beloepSomHeltall>0</beloepSomHeltall>',b'<beloepSomHeltall>'+str(state['validationReads']).encode()+b'</beloepSomHeltall>')}
                                notes=notes.replace('Kontroller alle feltene.','Kontroller alle feltene. Versjon '+str(state['validationReads'])+'.')
                            return self.respond(200,result(values,code='validertMedFeil' if blocked else 'validertOK',before=notes,after=after).raw_bytes,'application/xml')
                        assert family=='delivery'
                        if self.command=='POST' and self.path==_APP+state['instance']+'/data?dataType=skattemeldingOgNaeringsspesifikasjon':
                            runtime.committed(filing,'upload_envelope',body);assert state['uploaded'] is None
                            assert self.headers.get('Content-Type')=='text/xml' and self.headers.get('Content-Disposition')=='attachment; filename=skattemelding.xml'
                            assert body==runtime.drafts[filing].envelope.envelope_xml.encode();state['uploaded']=body
                            return self.respond(201,json.dumps({'id':state['data'],'fileScanResult':'Pending'}).encode())
                        if self.command=='POST':
                            assert self.path=='/api/skattemelding/v2/jobb/altinn/2025/'+runtime.organization+'/start' and state['uploaded'] is not None and not state.get('validationStarted')
                            runtime.committed(filing,'start_validation',body);state['validationStarted']=True
                            return self.respond(200,json.dumps({'jobbId':state['job'],'jobbStatus':'OPPRETTET'}).encode())
                        assert self.command=='PUT' and self.path==_APP+state['instance']+'/process/next' and body==b''
                        if state['step']==1:
                            runtime.committed(filing,'prepare_confirmation',body);state['step']=2;state['confirmationPuts']+=1
                        else:
                            assert state['step']==2
                            runtime.committed(filing,'confirm_submission',body);state['step']=3;state['submissionPuts']+=1
                            state['terminalAt']=datetime.now(UTC).isoformat();state['receiptBytes']=b'\xef\xbb\xbf <synthetic-technical-receipt/>\n\xff'
                        return self.respond(200,b'\xef\xbb\xbf {"acknowledgment":"opaque"}\n')
                except Exception as error:
                    runtime.errors.append(type(error).__name__);self.respond(500,b'{"error":"synthetic_authority_fixture_failed"}')
            do_GET=dispatch
            do_POST=dispatch
            do_PUT=dispatch
        return Handler

    def close(self):
        self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
        assert not self.thread.is_alive()


def build_application():
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'apps/backend/tests'))
    runtime=_Runtime()
    sessions=_Sessions(PostgresCompanyTaxAdapter(LedgerSupabaseConfiguration(url=os.environ['SUPABASE_URL'],anon_key=os.environ['SUPABASE_ANON_KEY'],database_url=os.environ['TALLI_LEDGER_DATABASE_URL'])))
    application=create_app(company_tax_session_factory=sessions,company_tax_delivery_preparation=runtime.preparation,company_tax_delivery_submission=_Submission(runtime))
    secret=os.environ['TALLI_TAX_BROWSER_CONTROL_KEY'];assert len(secret)==64
    @application.get('/__fixture__/tax-delivery-state')
    async def state(x_talli_fixture_key: str=Header()):
        if not hmac.compare_digest(x_talli_fixture_key,secret):raise HTTPException(404)
        with runtime.lock:
            return {'calls':list(runtime.calls),'errors':list(runtime.errors),'filings':{filing:{key:state[key] for key in ('instance','confirmationPuts','submissionPuts','step')} for filing,state in runtime.instances.items()}}
    application.router.add_event_handler('shutdown',runtime.close)
    return application
