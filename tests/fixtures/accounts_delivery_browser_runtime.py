"""Opt-in real JWT/restricted SQL Accounts rehearsal, with loopback effects only."""
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC,datetime,timedelta
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from io import BytesIO
import json
import os
from threading import RLock,Thread
from uuid import uuid4

from fastapi import Header,HTTPException
import psycopg
from psycopg.conninfo import conninfo_to_dict
from reportlab.pdfgen.canvas import Canvas

from talli_backend.adapters.annual_accounts_schemas import DeferredAnnualAccountsSchemas
from talli_backend.adapters.postgres_annual_accounts import PostgresAnnualAccountsAdapter
from talli_backend.adapters.supabase_ledger import LedgerSupabaseConfiguration
from talli_backend.adapters.supabase_documents import SupabaseDocumentsAdapter
from talli_backend.adapters.supabase_corporate_governance import compose_corporate_governance_application
from talli_backend.adapters.loopback_annual_accounts_delivery import (
    LoopbackAccountsSystemPreparation,LoopbackAccountsSystemConfirmation,LoopbackAccountsPersonSigning,LoopbackAccountsKnownRead,
)
from talli_backend.application.annual_accounts_delivery_rehearsal import AccountsRehearsalPorts,loopback_accounts_database_scope
from talli_backend.application.annual_accounts_delivery_preparation import AnnualAccountsDeliveryPreparation
from talli_backend.application.annual_accounts_delivery_workflow import AnnualAccountsDeliveryWorkflow
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsAuthorityPort as Port,AnnualAccountsDeliveryStage as Stage,AnnualAccountsCorrectionReadGrant
from talli_backend.shared.kernel import ActorId,ActorKind,UserId,CompanyId,IncomeYear,Timestamp
from talli_backend.main import create_app

_DEPTH=ContextVar('accounts_browser_sql_depth',default=0)
_APP='/brg/aarsregnskap-vanlig-202406/instances/'


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


class _NoSqlPort:
    def __init__(self,actual,owner):self.actual=actual;self.runtime=actual.runtime;self.owner=owner
    async def execute(self,request,review,draft):
        assert _DEPTH.get()==0,'Accounts mutation crossed an open SQL context.'
        self.owner.assert_committed(request.binding.filing_id,request.sha256,'intent:'+request.action.value)
        return await self.actual.execute(request,review,draft)
    async def read(self,**query):
        assert _DEPTH.get()==0,'Accounts GET crossed an open SQL context.'
        grant=self.runtime.admission
        self.owner.assert_read_admission_committed(grant)
        return await self.actual.read(**query)


class _Preparation:
    def __init__(self,owner,actual):self.owner=owner;self.actual=actual
    async def prepare(self,session,command):
        stored=await self.actual.prepare(session,command)
        assert _DEPTH.get()==0
        self.owner.register(stored.draft)
        return stored


def _pdf(label):
    output=BytesIO();canvas=Canvas(output,invariant=1)
    canvas.drawString(50,780,'Synthetic Accounts rehearsal')
    canvas.drawString(50,755,label);canvas.save();return output.getvalue()


class _Runtime:
    def __init__(self):
        self.company=CompanyId(os.environ['TALLI_ACCOUNTS_BROWSER_COMPANY_ID'])
        self.actor=ActorId(ActorKind.USER,UserId(os.environ['TALLI_ACCOUNTS_BROWSER_OWNER_ID']))
        self.organization=os.environ['TALLI_ACCOUNTS_BROWSER_ORG'];self.database=os.environ['DATABASE_URL']
        target=conninfo_to_dict(os.environ['TALLI_LEDGER_DATABASE_URL'])
        self.scope=loopback_accounts_database_scope(target['host'],int(target['port']),target['dbname'],target['user'])
        assert self.scope is not None
        self.lock=RLock();self.drafts={};self.instances={};self.grants={};self.calls=[];self.errors=[]
        self.fail_next_parent_metadata=False;self.parent_read_failures=0
        self.server=ThreadingHTTPServer(('127.0.0.1',0),self.handler());self.server.daemon_threads=True
        self.origin='http://127.0.0.1:'+str(self.server.server_port)
        self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        credentials={key:uuid4().hex+uuid4().hex for key in ((Port.SYSTEM_USER,Stage.PREPARE),(Port.SYSTEM_USER,Stage.CONFIRM),(Port.PERSON,Stage.SIGN),(Port.KNOWN_READ,None))}
        def builder(cls):
            def create(runtime):
                with self.lock:self.grants[runtime._credential.credential]=runtime.admission
                return _NoSqlPort(cls(runtime),self)
            return create
        self.ports=AccountsRehearsalPorts(company_id=self.company,income_year=IncomeYear(2025),actor_id=self.actor,
            organization_number=self.organization,origin=self.origin,database_scope_sha256=self.scope,credentials=credentials,
            builders={key:builder(cls) for key,cls in (
                ((Port.SYSTEM_USER,Stage.PREPARE),LoopbackAccountsSystemPreparation),((Port.SYSTEM_USER,Stage.CONFIRM),LoopbackAccountsSystemConfirmation),
                ((Port.PERSON,Stage.SIGN),LoopbackAccountsPersonSigning),((Port.KNOWN_READ,None),LoopbackAccountsKnownRead))},
            expires_at=Timestamp(datetime.now(UTC)+timedelta(seconds=3500)),
            parent_read_credential=uuid4().hex+uuid4().hex,parent_read_builder=builder(LoopbackAccountsKnownRead))

    def assert_read_admission_committed(self,grant):
        with psycopg.connect(self.database) as db:
            rows=db.execute('select slot,canonical_json from annual_accounts_filing.delivery_events where filing_id=%s and (event_sha256=%s or slot=%s)',
                (grant.binding.filing_id,grant.sha256,'correction:admission')).fetchall()
            expected=json.loads(grant.canonical_json)['record']
            matches=[(slot,raw) for slot,raw in rows if (json.loads(raw)['record'].get('grant') if slot=='correction:admission'
                else json.loads(raw)['record'] if slot==grant.slot else None)==expected]
            assert len(matches)==1
            if matches[0][0]=='correction:admission':
                attempt=db.execute("select canonical_json from annual_accounts_filing.delivery_events where filing_id=%s and slot like 'correction:attempt:%%' order by sequence desc limit 1",(grant.binding.filing_id,)).fetchone()
                assert attempt is not None
                assert json.loads(attempt[0])['record']['admission_sha256']==hashlib.sha256(matches[0][1].encode()).hexdigest()

    def assert_committed(self,filing,digest,slot):
        # Inspection only. The business adapter always uses its restricted
        # verified-session DSN; this independent reader proves commit ordering.
        with psycopg.connect(self.database) as db:
            assert db.execute('select count(*) from annual_accounts_filing.delivery_events where filing_id=%s and event_sha256=%s and slot=%s',
                (filing,digest,slot)).fetchone()==(1,)

    def register(self,draft):
        with psycopg.connect(self.database) as db:
            assert db.execute('select draft_sha256 from annual_accounts_filing.delivery_drafts where id=%s',(draft.filing_id,)).fetchone()==(draft.sha256,)
        with self.lock:
            prior=self.drafts.get(draft.filing_id)
            assert prior is None or prior==draft
            self.drafts[draft.filing_id]=draft

    def handler(self):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):self.process()
            def do_POST(self):self.process()
            def do_PUT(self):self.process()
            def process(self):
                try:
                    with owner.lock:
                        credential=self.headers.get('X-Talli-Rehearsal-Key','');grant=owner.grants.get(credential)
                        assert grant is not None and hmac.compare_digest(self.headers.get('X-Talli-Rehearsal-Run',''),grant.run_id)
                        assert grant.binding.company_id==owner.company and grant.binding.actor_id==owner.actor
                        grant.assert_current(Timestamp(datetime.now(UTC)))
                        draft=owner.drafts[grant.binding.filing_id]
                        assert grant.binding.draft_sha256==draft.sha256
                        raw=self.rfile.read(int(self.headers.get('Content-Length','0')))
                        owner.calls.append({'method':self.command,'path':self.path,'filingId':draft.filing_id,'port':grant.port.value,
                            'stage':grant.stage.value if grant.stage else None,'bodySha256':hashlib.sha256(raw).hexdigest()})
                        def send(body,status=200,media='application/json'):
                            self.send_response(status)
                            if media is not None:self.send_header('Content-Type',media)
                            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
                        def value(body,status=200):send(json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode(),status)
                        if self.command=='POST':
                            assert self.path==_APP+'create' and grant.port is Port.SYSTEM_USER and grant.stage is Stage.PREPARE
                            assert json.loads(raw)=={'instanceOwner':{'organisationNumber':owner.organization}}
                            assert draft.filing_id not in owner.instances
                            instance='12345678/'+str(uuid4());main,accounts=str(uuid4()),str(uuid4())
                            metadata={'id':instance,'appId':'brg/aarsregnskap-vanlig-202406',
                                'instanceOwner':{'organisationNumber':owner.organization,'partyId':12345678},
                                'process':{'currentTask':{'elementId':'Utfylling','altinnTaskType':'data'}},'status':{'isArchived':False},
                                'data':[{'id':main,'dataType':'Hovedskjema','contentType':'application/xml','size':0},
                                    {'id':accounts,'dataType':'Underskjema','contentType':'application/xml','size':0}]}
                            owner.instances[draft.filing_id]={'metadata':metadata,'files':{main:b'',accounts:b''},'mutations':1}
                            value(metadata,201);return
                        if self.command=='GET' and grant.known_instance is not None:
                            matching=[value for value in owner.instances.values() if value['metadata']['id']==grant.known_instance]
                            assert len(matching)==1;state=matching[0]
                        else:state=owner.instances[draft.filing_id]
                        metadata=state['metadata'];prefix=_APP+metadata['id']
                        assert self.path==prefix or self.path.startswith(prefix+'/')
                        if grant.known_instance is not None:assert grant.known_instance==metadata['id']
                        if (self.command=='GET' and self.path==prefix and type(grant) is AnnualAccountsCorrectionReadGrant
                                and owner.fail_next_parent_metadata):
                            owner.fail_next_parent_metadata=False;owner.parent_read_failures+=1
                            send(b'Synthetic parent metadata response unavailable',503,'text/plain');return
                        if self.command=='PUT':
                            if '/data/' in self.path:
                                assert grant.port is Port.SYSTEM_USER and grant.stage is Stage.PREPARE
                                identity=self.path.rsplit('/',1)[1];item=next(row for row in metadata['data'] if row['id']==identity)
                                expected=draft.main_form_xml if item['dataType']=='Hovedskjema' else draft.company_accounts_xml
                                assert raw==expected.encode() and self.headers.get('Content-Type')=='application/xml'
                                state['files'][identity]=raw;item['size']=len(raw);state['mutations']+=1
                                # Effect committed at the mock, exact response lost.
                                self.connection.shutdown(2);self.connection.close();return
                            assert self.path==prefix+'/process/next'
                            action=json.loads(raw)['action']
                            if action=='confirm':
                                assert grant.port is Port.SYSTEM_USER and grant.stage is Stage.CONFIRM
                                metadata['process']={'currentTask':{'elementId':'Signering','altinnTaskType':'signing'}}
                                for index in range(4):
                                    identity=str(uuid4());body=_pdf('Document '+str(index+1)+' '+draft.sha256[:16]);state['files'][identity]=body
                                    metadata['data'].append({'id':identity,'dataType':'ref-data-as-pdf','contentType':'application/pdf','size':len(body)})
                            else:
                                assert action=='sign' and grant.port is Port.PERSON and grant.stage is Stage.SIGN
                                identity=str(uuid4());body=b'\xef\xbb\xbfopaque synthetic signature\x00\xff';state['files'][identity]=body
                                metadata['data'].append({'id':identity,'dataType':'signature','contentType':'application/json','size':len(body)})
                                metadata['process']={'currentTask':None,'ended':datetime.now(UTC).isoformat()}
                                metadata['status']={'isArchived':True,'archived':datetime.now(UTC).isoformat()}
                            state['mutations']+=1;send(b'',204,None);return
                        if self.path==prefix:value(metadata)
                        elif self.path==prefix+'/validate':value([])
                        else:
                            identity=self.path.rsplit('/',1)[1];item=next(row for row in metadata['data'] if row['id']==identity)
                            send(state['files'][identity],media=item['contentType'])
                except Exception as error:
                    with owner.lock:owner.errors.append(type(error).__name__)
                    try:self.send_error(500)
                    except OSError:pass
        return Handler

    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)


def build_application():
    runtime=_Runtime();documents=SupabaseDocumentsAdapter.from_environment()
    corporate=compose_corporate_governance_application(None,documents)
    schemas=DeferredAnnualAccountsSchemas()
    sessions=_Sessions(PostgresAnnualAccountsAdapter(LedgerSupabaseConfiguration(url=os.environ['SUPABASE_URL'],
        anon_key=os.environ['SUPABASE_ANON_KEY'],database_url=os.environ['TALLI_LEDGER_DATABASE_URL'])))
    application=create_app(annual_accounts_session_factory=sessions,
        annual_accounts_delivery_preparation=_Preparation(runtime,AnnualAccountsDeliveryPreparation(corporate,schemas)),
        annual_accounts_delivery_workflow=AnnualAccountsDeliveryWorkflow(corporate=corporate,schemas=schemas,ports=runtime.ports))
    secret=os.environ['TALLI_ACCOUNTS_BROWSER_CONTROL_KEY'];assert len(secret)==64
    @application.get('/__fixture__/accounts-delivery-state')
    async def state(x_talli_fixture_key: str=Header()):
        if not hmac.compare_digest(x_talli_fixture_key,secret):raise HTTPException(404)
        with runtime.lock:return {'calls':list(runtime.calls),'errors':list(runtime.errors),
            'parentReadFailures':runtime.parent_read_failures,
            'filings':{key:{'instance':value['metadata']['id'],'mutations':value['mutations'],'archived':value['metadata']['status']['isArchived']}
                for key,value in runtime.instances.items()}}
    @application.post('/__fixture__/accounts-delivery-control')
    async def fail_parent(x_talli_fixture_key: str=Header()):
        if not hmac.compare_digest(x_talli_fixture_key,secret):raise HTTPException(404)
        with runtime.lock:runtime.fail_next_parent_metadata=True
        return {'configured':True}
    application.router.add_event_handler('shutdown',runtime.close)
    return application
