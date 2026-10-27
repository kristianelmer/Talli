"""Finite HTTP effects follow committed intents, with no SQL across requests."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC,datetime,timedelta
import json
from uuid import uuid4

import httpx
import pytest

from talli_backend.adapters.annual_accounts_schemas import PinnedAnnualAccountsSchemas
from talli_backend.adapters.loopback_annual_accounts_delivery import (
    LoopbackAccountsSystemPreparation,LoopbackAccountsSystemConfirmation,LoopbackAccountsPersonSigning,LoopbackAccountsKnownRead,
)
from talli_backend.application.annual_accounts_delivery_rehearsal import AccountsRehearsalPorts,loopback_accounts_database_scope
from talli_backend.application.annual_accounts_delivery_workflow import AnnualAccountsDeliveryWorkflow
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsError,AnnualAccountsDeliveryStage as Stage,AnnualAccountsAuthorityPort as Port,
    AnnualAccountsDeliveryAction as Action,AnnualAccountsFrameKind as Kind,StoredAnnualAccountsDeliveryEvent as Event,
    AnnualAccountsDeliveryIntent as Intent,
)
from talli_backend.shared.kernel import Timestamp,IdempotencyKey,CorrelationId
from test_annual_accounts_delivery_source import ACTOR,COMPANY,YEAR,QUERY,source_inputs,prepare,read
from test_annual_accounts_delivery_draft import delivery_snapshot
from test_annual_accounts_delivery_records import binding
from test_annual_accounts_delivery_originals import INSTANCE,MAIN,ACCOUNTS,metadata

CORRELATION=CorrelationId('accounts-operation-workflow-test')


class Harness:
    actor_id=ACTOR
    delivery_rehearsal_target=loopback_accounts_database_scope('127.0.0.1',54322,'postgres','fixture_runtime')

    def __init__(self,*,lost_uploads=False,unknown_creation=False,blocked=False):
        self.inputs,self.corporate,_=source_inputs();self.draft=prepare(read(self.inputs,self.corporate))
        _,self.snapshot=delivery_snapshot(self.draft);self.stored=self.snapshot.delivery_drafts[0]
        self.events=[];self.depth=0;self.guard=False;self.lock=asyncio.Lock();self.owner=True;self.mfa=True
        self.metadata=metadata();self.metadata['instanceOwner']['organisationNumber']=self.draft.source.organization_number
        self.files={MAIN:b'',ACCOUNTS:b''};self.requests=[];self.lost_uploads=lost_uploads;self.unknown_creation=unknown_creation;self.blocked=blocked
        self.validation_issues=None
        self.schemas=PinnedAnnualAccountsSchemas()
        self.credentials={(Port.SYSTEM_USER,Stage.PREPARE):'1'*64,(Port.SYSTEM_USER,Stage.CONFIRM):'2'*64,
            (Port.PERSON,Stage.SIGN):'3'*64,(Port.KNOWN_READ,None):'4'*64}
        transport=httpx.MockTransport(self.handle)
        self.ports=AccountsRehearsalPorts(company_id=COMPANY,income_year=YEAR,actor_id=ACTOR,
            organization_number=self.draft.source.organization_number,origin='http://127.0.0.1:23456',
            database_scope_sha256=self.delivery_rehearsal_target,credentials=self.credentials,
            builders={key:(lambda runtime,cls=cls:cls(runtime,transport=transport)) for key,cls in (
                ((Port.SYSTEM_USER,Stage.PREPARE),LoopbackAccountsSystemPreparation),
                ((Port.SYSTEM_USER,Stage.CONFIRM),LoopbackAccountsSystemConfirmation),
                ((Port.PERSON,Stage.SIGN),LoopbackAccountsPersonSigning),((Port.KNOWN_READ,None),LoopbackAccountsKnownRead))},
            expires_at=Timestamp(datetime.now(UTC)+timedelta(seconds=1800)))
        self.workflow=AnnualAccountsDeliveryWorkflow(corporate=self.corporate,schemas=self.schemas,ports=self.ports)

    @asynccontextmanager
    async def transaction(self,*,snapshot=False):
        session=self;pending=[];self.depth+=1
        class Transaction:
            actor_id=ACTOR
            delivery_corporate_queries=session.inputs.delivery_corporate_queries
            delivery_ledger_queries=session.inputs.delivery_ledger_queries
            async def delivery_annual_interview_history(self,query):
                assert snapshot
                return session.inputs.history
            async def lock_delivery_archive(self,query):
                assert not snapshot
                if not session.owner:raise AnnualAccountsError.forbidden()
                if not session.mfa:raise AnnualAccountsError.mfa_required()
                session.guard=True
            async def filing_source_snapshot(self,query):
                assert snapshot
                if not session.owner:raise AnnualAccountsError.forbidden()
                if not session.mfa:raise AnnualAccountsError.mfa_required()
                proof=dict(session.snapshot.coverage)|{'contractVersion':'annual-accounts-source-v3',
                    'deliveryEventCodecVersion':'annual-accounts-delivery-events-v1','deliveryEventContractValid':True,
                    'deliveryOperationsEnabled':True,'deliveryDraftWritesEnabled':True,
                    'deliveryEventCount':len(session.events),'deliveryEventDigests':{str(row.sequence):row.record.sha256 for row in session.events}}
                return replace(session.snapshot,contract_version='annual-accounts-source-v3',coverage=proof,
                    as_of=Timestamp(datetime.now(UTC)),delivery_events=tuple(session.events))
            async def append_delivery_event(self,record):
                assert not snapshot
                previous=next((row for row in (*session.events,*pending) if row.record.slot==record.slot),None)
                if previous is not None:
                    if previous.record!=record:raise AnnualAccountsError.draft_conflict()
                    return previous,False
                event=Event(3*(len(session.events)+len(pending)+1),record,Timestamp(datetime.now(UTC)))
                pending.append(event);return event,True
        try:
            yield Transaction()
            self.events.extend(pending)
        finally:
            self.depth-=1
            if not snapshot:self.guard=False

    def handle(self,request):
        assert self.depth==0 and not self.guard,'HTTP escaped while a SQL context remained open'
        assert request.url.host=='127.0.0.1' and request.url.port==23456
        key=request.headers['X-Talli-Rehearsal-Key']
        retained=[port.runtime.admission for port in self.ports._ports.values() if port.runtime._credential.credential==key]
        assert len(retained)==1;actual_grant=retained[0]
        self.requests.append((request.method,request.url.path,key))
        def response(raw,status=200,media='application/json'):
            return httpx.Response(status,headers={} if media is None else {'Content-Type':media},stream=httpx.ByteStream(raw))
        def value(body,status=200):return response(json.dumps(body,ensure_ascii=False).encode(),status)
        if request.method!='GET':
            action=(Action.CREATE_INSTANCE if request.method=='POST' else Action.UPLOAD_MAIN_FORM if request.url.path.endswith('/data/'+MAIN)
                else Action.UPLOAD_COMPANY_ACCOUNTS if request.url.path.endswith('/data/'+ACCOUNTS) else
                Action.CONFIRM if json.loads(request.content)['action']=='confirm' else Action.SIGN)
            committed=next((row.record for row in self.events if row.record.slot=='intent:'+action.value),None)
            assert type(committed) is Intent and committed.request_body_base64
            assert committed.request_path==request.url.path
            expected=(Port.PERSON,Stage.SIGN) if action is Action.SIGN else (Port.SYSTEM_USER,Stage.CONFIRM) if action is Action.CONFIRM else (Port.SYSTEM_USER,Stage.PREPARE)
            assert (actual_grant.port,actual_grant.stage)==expected,'A different actor port performed this mutation'
            if action is Action.CREATE_INSTANCE:
                return value({'opaque':'missing known identity'},201) if self.unknown_creation else value(self.metadata,201)
            if action in (Action.UPLOAD_MAIN_FORM,Action.UPLOAD_COMPANY_ACCOUNTS):
                data=MAIN if action is Action.UPLOAD_MAIN_FORM else ACCOUNTS;self.files[data]=request.content
                next(item for item in self.metadata['data'] if item['id']==data)['size']=len(request.content)
                if self.lost_uploads:raise httpx.ReadError('Synthetic response lost after effect',request=request)
            elif action is Action.CONFIRM:
                self.metadata['process']={'currentTask':{'elementId':'Signering','altinnTaskType':'signing'}}
                for index in range(4):
                    identity=str(uuid4());raw=b'%PDF-synthetic\x00\xff'+bytes([index]);self.files[identity]=raw
                    self.metadata['data'].append({'id':identity,'dataType':'ref-data-as-pdf','contentType':'application/pdf','size':len(raw)})
            else:
                identity=str(uuid4());raw=b'\xffopaque signature\x00';self.files[identity]=raw
                self.metadata['data'].append({'id':identity,'dataType':'signature','contentType':'application/json','size':len(raw)})
                self.metadata['process']={'currentTask':None,'ended':datetime.now(UTC).isoformat()}
                self.metadata['status']={'isArchived':True,'archived':datetime.now(UTC).isoformat()}
            return response(b'',204,None)
        if request.url.path.endswith('/validate'):
            return value(self.validation_issues if self.validation_issues is not None else [{'severity':1,'code':'BLOCK','description':'All issues must be reviewed.'}] if self.blocked else [])
        if '/data/' in request.url.path:
            identity=request.url.path.rsplit('/',1)[1];item=next(row for row in self.metadata['data'] if row['id']==identity)
            return response(self.files[identity],media=item['contentType'])
        return value(self.metadata)

    async def review(self,stage):
        state=await self.workflow.read(self,QUERY,self.draft.filing_id)
        evidence=self.draft.sha256
        if stage is not Stage.PREPARE:
            _,frame=self.workflow._frame(state,Kind.UPLOAD_REVIEW if stage is Stage.CONFIRM else Kind.SIGN_REVIEW)
            evidence=frame.review_sha256
        return await self.workflow.review(self,binding(self.draft),stage=stage,reviewed_evidence_sha256=evidence,
            documents_checked=True,action_confirmed=True,command_key=IdempotencyKey(uuid4().hex),correlation_id=CORRELATION)

    async def advance(self,action):return await self.workflow.advance(self,binding(self.draft),action=action,correlation_id=CORRELATION)
    async def reconcile(self):return await self.workflow.reconcile(self,binding(self.draft))


def test_full_distinct_actor_flow_preserves_lost_uploads_and_all_exact_archive_originals():
    harness=Harness(lost_uploads=True)
    async def exercise():
        await harness.review(Stage.PREPARE)
        for action in (Action.CREATE_INSTANCE,Action.UPLOAD_MAIN_FORM,Action.UPLOAD_COMPANY_ACCOUNTS):
            before=len(harness.requests);await harness.advance(action);after=len(harness.requests)
            await harness.advance(action);assert len(harness.requests)==after==before+1
            state=await harness.reconcile()
        assert state.inspection.state=='confirmation_review'
        await harness.review(Stage.CONFIRM);await harness.advance(Action.CONFIRM)
        state=await harness.reconcile();assert state.inspection.state=='person_review'
        await harness.review(Stage.SIGN);await harness.advance(Action.SIGN)
        state=await harness.reconcile();assert state.inspection.state=='technical_archive'
        assert len([row for row in harness.requests if row[0]!='GET'])==5
        originals=[row.record.original for row in state.events if hasattr(row.record,'original')]
        assert any(row.raw_bytes==b'\xffopaque signature\x00' for row in originals)
        assert len({row.data_id for row in originals if row.purpose.value=='pdf'})==4
    asyncio.run(exercise())


def test_unknown_creation_never_invents_a_lookup_or_second_post():
    harness=Harness(unknown_creation=True)
    async def exercise():
        await harness.review(Stage.PREPARE);state=await harness.advance(Action.CREATE_INSTANCE)
        assert state.inspection.state=='creation_unknown'
        await harness.advance(Action.CREATE_INSTANCE);await harness.reconcile()
        assert len(harness.requests)==1
    asyncio.run(exercise())


def test_changed_source_blocks_new_mutation_but_known_upload_recovery_remains_available():
    harness=Harness(lost_uploads=True)
    async def exercise():
        await harness.review(Stage.PREPARE);await harness.advance(Action.CREATE_INSTANCE);await harness.reconcile()
        await harness.advance(Action.UPLOAD_MAIN_FORM);harness.inputs.history[0]['annualFullTimeEquivalents']=None
        state=await harness.reconcile();assert state.inspection.state=='main_uploaded'
        before=len(harness.requests)
        with pytest.raises(AnnualAccountsError):await harness.advance(Action.UPLOAD_COMPANY_ACCOUNTS)
        assert len(harness.requests)==before
    asyncio.run(exercise())


def test_validation_error_remains_retained_and_cannot_be_confirmed():
    harness=Harness(blocked=True)
    async def exercise():
        await harness.review(Stage.PREPARE)
        for action in (Action.CREATE_INSTANCE,Action.UPLOAD_MAIN_FORM,Action.UPLOAD_COMPANY_ACCOUNTS):
            await harness.advance(action);state=await harness.reconcile()
        assert state.inspection.state=='validation_blocked'
        before=len(harness.requests)
        with pytest.raises(AnnualAccountsError):await harness.review(Stage.CONFIRM)
        with pytest.raises(AnnualAccountsError):await harness.advance(Action.CONFIRM)
        assert len(harness.requests)==before
        _,frame=harness.workflow._frame(state,Kind.UPLOAD_REVIEW)
        assert frame.validation_issues[0]['description']=='All issues must be reviewed.'
    asyncio.run(exercise())


@pytest.mark.parametrize('defect',['missing-review','one-choice','owner','mfa','default-runtime'])
def test_no_unreviewed_or_unauthorized_dispatch(defect):
    harness=Harness()
    async def exercise():
        if defect!='missing-review':await harness.review(Stage.PREPARE)
        if defect=='owner':harness.owner=False
        elif defect=='mfa':harness.mfa=False
        elif defect=='default-runtime':harness.workflow._ports=None
        if defect=='one-choice':
            # A different filing must not inherit the previous owner's choice.
            harness.events=[]
            with pytest.raises(AnnualAccountsError):
                await harness.workflow.review(harness,binding(harness.draft),stage=Stage.PREPARE,
                    reviewed_evidence_sha256=harness.draft.sha256,documents_checked=True,action_confirmed=False,
                    command_key=IdempotencyKey(uuid4().hex),correlation_id=CORRELATION)
        with pytest.raises(AnnualAccountsError):await harness.advance(Action.CREATE_INSTANCE)
        assert harness.requests==[]
    asyncio.run(exercise())


def test_workspace_is_non_consuming_and_archive_survives_source_and_runtime_loss():
    import base64
    import hashlib
    from talli_backend.application.annual_accounts_delivery_workspace import AnnualAccountsDeliveryWorkspace
    harness=Harness();workspace=AnnualAccountsDeliveryWorkspace(harness.workflow)
    async def exercise():
        first=await workspace.read(harness,QUERY,correlation_id=CORRELATION)
        assert first['rows'][0]['actions']==['review_prepare']
        assert first['rows'][0]['fields'] and len(harness.ports._ports)==0 and harness.requests==[]
        await harness.review(Stage.PREPARE)
        second=await workspace.read(harness,QUERY,correlation_id=CORRELATION)
        assert second['rows'][0]['actions']==['create_instance'] and len(harness.ports._ports)==0
        harness.inputs.history[0]['annualFullTimeEquivalents']=None;harness.workflow._ports=None
        archived=await workspace.original(harness,QUERY,harness.draft.filing_id,'source:'+harness.draft.source.sha256)
        raw=base64.b64decode(archived.body_base64,validate=True)
        assert hashlib.sha256(raw).hexdigest()==harness.draft.source.sha256==archived.sha256
        view=await workspace.read(harness,QUERY,correlation_id=CORRELATION)
        assert view['rows'][0]['actions']==[] and view['rows'][0]['source_current'] is False
        harness.owner=False
        with pytest.raises(AnnualAccountsError):await workspace.original(harness,QUERY,harness.draft.filing_id,archived.key)
    asyncio.run(exercise())


def test_backend_transport_binds_review_scope_and_rejects_caller_authority_fields():
    from talli_backend.main import create_app
    harness=Harness()
    class Sessions:
        async def session(self,token):
            assert token=='component-fixture-session'
            return harness
    app=create_app(annual_accounts_session_factory=Sessions(),annual_accounts_delivery_workflow=harness.workflow)
    scope={'companyId':str(COMPANY),'incomeYear':2025,'filingId':harness.draft.filing_id,'draftSha256':harness.draft.sha256}
    headers={'Authorization':'Bearer component-fixture-session','Idempotency-Key':uuid4().hex}
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            path='/api/v1/annual-accounts/delivery-reviews'
            body=scope|{'stage':'prepare','reviewedEvidenceSha256':harness.draft.sha256,'documentsChecked':True,'actionConfirmed':True}
            for changed in ({'actorId':str(ACTOR.subject)},{'incomeYear':True},{'documentsChecked':'true'},{'origin':'https://example.test'}):
                response=await client.post(path,json=body|changed,headers=headers)
                assert response.status_code==422,response.text
            response=await client.post(path,json=body|{'actionConfirmed':False},headers=headers)
            assert response.status_code==422,response.text
            response=await client.post(path,json=body,headers=headers)
            assert response.status_code==200,response.text
            assert response.json()['state']=='reviewed'
            response=await client.post('/api/v1/annual-accounts/delivery-advances',json=scope|{'action':'create_instance'},headers=headers)
            assert response.status_code==200,response.text
            assert len(harness.requests)==1
            for _ in range(2):
                response=await client.get('/api/v1/annual-accounts/delivery-workspace',params={'companyId':str(COMPANY),'incomeYear':2025},headers=headers)
                assert response.status_code==200,response.text
                wire=response.json();assert wire['rows'][0]['state']=='created' and wire['rows'][0]['originals']
                assert 'bodyBase64' not in response.text
            assert len(harness.requests)==1
            response=await client.get('/api/v1/annual-accounts/delivery-original',params={'companyId':str(COMPANY),'incomeYear':2025,
                'filingId':harness.draft.filing_id,'key':'prepared_main:'+harness.draft.inspection.main_form_sha256},headers=headers)
            assert response.status_code==200,response.text
            assert response.json()['sha256']==harness.draft.inspection.main_form_sha256
            for route,extra in [('reviews',{'stage':'prepare','reviewedEvidenceSha256':harness.draft.sha256,'documentsChecked':True,'actionConfirmed':True}),
                    ('advances',{'action':'create_instance'}),('reconciliations',{})]:
                response=await client.post('/api/v1/annual-accounts/delivery-'+route,json=scope|{'draftSha256':'f'*64}|extra,headers=headers)
                assert response.status_code==409,response.text
            await harness.reconcile();await harness.advance(Action.UPLOAD_MAIN_FORM);await harness.reconcile()
            harness.validation_issues=[{'severity':'Warning','code':'SOFT','additional':{'nested':['detail']}}]
            await harness.advance(Action.UPLOAD_COMPANY_ACCOUNTS);await harness.reconcile()
            response=await client.get('/api/v1/annual-accounts/delivery-workspace',params={'companyId':str(COMPANY),'incomeYear':2025},headers=headers)
            assert response.status_code==200,response.text
            assert response.json()['rows'][0]['validationIssues'][0]['additional']=={'nested':['detail']}
    asyncio.run(exercise())


@pytest.mark.parametrize('override',['hostaddr','service','options','ambient-hostaddr','ambient-service'])
def test_libpq_overrides_never_receive_loopback_scope(monkeypatch,override):
    from types import SimpleNamespace
    from talli_backend.adapters.postgres_annual_accounts import PostgresAnnualAccountsSession
    for key in ('PGHOSTADDR','PGSERVICE','PGSERVICEFILE','PGOPTIONS','PGLOADBALANCEHOSTS','PGTARGETSESSIONATTRS'):monkeypatch.delenv(key,raising=False)
    base='host=127.0.0.1 port=54322 dbname=postgres user=fixture_runtime'
    verified=SimpleNamespace(actor_id=ACTOR)
    expected=PostgresAnnualAccountsSession(base,verified).delivery_rehearsal_target
    assert expected==Harness.delivery_rehearsal_target
    if override=='hostaddr':changed=base+' hostaddr=203.0.113.8'
    elif override=='service':changed=base+' service=remote_fixture'
    elif override=='options':changed=base+" options='-c role=postgres'"
    else:
        changed=base;monkeypatch.setenv('PGHOSTADDR' if override=='ambient-hostaddr' else 'PGSERVICE','203.0.113.8' if override=='ambient-hostaddr' else 'remote_fixture')
    assert PostgresAnnualAccountsSession(changed,verified).delivery_rehearsal_target is None


def test_schema_failure_preserves_archive_listing_and_default_app_download(monkeypatch,tmp_path):
    from talli_backend.application.annual_accounts_delivery_workspace import AnnualAccountsDeliveryWorkspace
    from talli_backend.adapters import annual_accounts_schemas
    from talli_backend.main import create_app
    harness=Harness();workspace=AnnualAccountsDeliveryWorkspace(harness.workflow)
    class MissingSchemas:
        def validate_pair(self,*args,**kwargs):raise AnnualAccountsError.unavailable()
    class Sessions:
        async def session(self,token):return harness
    async def exercise():
        await harness.review(Stage.PREPARE)
        for action in (Action.CREATE_INSTANCE,Action.UPLOAD_MAIN_FORM,Action.UPLOAD_COMPANY_ACCOUNTS):
            await harness.advance(action);await harness.reconcile()
        harness.workflow._schemas=MissingSchemas()
        value=await workspace.read(harness,QUERY,correlation_id=CORRELATION)
        assert value['rows'][0]['state']=='inspection_unavailable' and value['rows'][0]['actions']==[]
        assert value['rows'][0]['originals']
        # Default composition must construct and serve archive reads even when
        # the local pinned resources are missing/corrupt. No injected validator.
        monkeypatch.setattr(annual_accounts_schemas,'_BUNDLE',tmp_path/'missing')
        app=create_app(annual_accounts_session_factory=Sessions())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            response=await client.get('/api/v1/annual-accounts/delivery-original',headers={'Authorization':'Bearer fixture'},
                params={'companyId':str(COMPANY),'incomeYear':2025,'filingId':harness.draft.filing_id,'key':'draft:'+harness.draft.sha256})
            assert response.status_code==200,response.text
            assert response.json()['sha256']==harness.draft.sha256
    asyncio.run(exercise())


@pytest.mark.parametrize('reviewed',[False,True])
def test_schema_loss_blocks_early_review_and_creation_without_issuing_a_grant(reviewed):
    from talli_backend.application.annual_accounts_delivery_workspace import AnnualAccountsDeliveryWorkspace
    harness=Harness()
    class MissingSchemas:
        def validate_pair(self,*args,**kwargs):raise AnnualAccountsError.unavailable()
    async def exercise():
        if reviewed:await harness.review(Stage.PREPARE)
        harness.workflow._schemas=MissingSchemas()
        value=await AnnualAccountsDeliveryWorkspace(harness.workflow).read(harness,QUERY,correlation_id=CORRELATION)
        assert value['rows'][0]['state']=='inspection_unavailable' and value['rows'][0]['actions']==[]
        assert value['preparation_available'] is False and value['rows'][0]['originals']
        if not reviewed:
            with pytest.raises(AnnualAccountsError):await harness.review(Stage.PREPARE)
        with pytest.raises(AnnualAccountsError):await harness.advance(Action.CREATE_INSTANCE)
        assert harness.requests==[] and harness.ports._ports=={}
    asyncio.run(exercise())


def test_stale_frame_offers_known_reconciliation_instead_of_a_stale_mutation():
    from talli_backend.application.annual_accounts_delivery_workspace import AnnualAccountsDeliveryWorkspace
    harness=Harness()
    async def exercise():
        await harness.review(Stage.PREPARE);await harness.advance(Action.CREATE_INSTANCE);await harness.reconcile()
        harness.workflow._now=lambda:Timestamp(datetime.now(UTC)+timedelta(seconds=61))
        value=await AnnualAccountsDeliveryWorkspace(harness.workflow).read(harness,QUERY,correlation_id=CORRELATION)
        assert value['rows'][0]['actions']==['reconcile']
        before=len(harness.requests)
        with pytest.raises(AnnualAccountsError):await harness.advance(Action.UPLOAD_MAIN_FORM)
        assert len(harness.requests)==before
    asyncio.run(exercise())
