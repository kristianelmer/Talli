"""Authenticated source routes run the real workflow against synthetic owners."""
from contextlib import asynccontextmanager
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
import re
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from talli_backend.main import create_app
from talli_backend.application.shareholder_register_filing_session import ShareholderRegisterFilingAuthenticationError
from talli_backend.modules.corporate_governance.public import CorporateReportingYearBasis, CorporateLifecycleSnapshot
from talli_backend.modules.documents.public import document_metadata_sha256, DocumentId
from talli_backend.shared.kernel import CompanyId, IncomeYear
from talli_backend.modules.shareholder_register_filing.public import (
    Rf1086YearSourceId, prepare_rf1086_year_source, rf1086_year_source_digest,
)
from test_shareholder_register_source_workflow import Harness
from test_shareholder_register_capital_source_workflow import setup as capital_setup
from test_shareholder_register_source_preview_workflow import correction
from test_rf1086_year_source import ACTOR, COMPANY, YEAR, DOCUMENT, NOW

BASE='/api/v1/shareholder-register-filings'
HEADERS={'Authorization':'Bearer verified-token','X-Request-ID':'source-api-proof','Idempotency-Key':'source-api-capture-0001'}


def draft(value):
    if isinstance(value, Enum):return value.value
    if isinstance(value, (float,Decimal)):return str(value)
    if isinstance(value, datetime):return value.isoformat()
    if isinstance(value, tuple):return [draft(row) for row in value]
    if is_dataclass(value):
        if {field.name for field in fields(value)}=={'value'}:return value.value
        return {field.name:draft(getattr(value,field.name)) for field in fields(value) if field.name!='actor_id'}
    return value


class ApiHarness:
    def __init__(self, *, capital=False, kind='no_activity'):
        self.h=capital_setup() if capital else Harness(kind)
        h=self.h; self.idempotencies=[]; self.auth_failure=False; self.persistence_error=None
        self.reporting_basis=None; self.reporting_amendments=(); self.observations=None
        owner=self
        class RFSession:
            def __init__(self, wrapped):self.wrapped=wrapped
            @property
            def actor_id(self):return h.actor
            def __getattr__(self,name):return getattr(self.wrapped,name)
            async def record_year_source(self,command,*,context,idempotency_key):
                owner.idempotencies.append(idempotency_key.value)
                if owner.persistence_error:raise owner.persistence_error
                if h.current_source is not None:
                    result=prepare_rf1086_year_source(command,context=context,
                        source_id=Rf1086YearSourceId(str(uuid4())),previous=h.current_source,
                        confirmed_at=h.current_source.confirmed_at+timedelta(seconds=1))
                    h.context=context;h.saved.append(result);h.sources[result.source_id]=result;h.current_source=result
                    h.calls.append('persist');return result
                return await self.wrapped.record_year_source(command,context=context,idempotency_key=idempotency_key)
            async def list_register_observations(self,query):
                h.calls.append('list_observations')
                if owner.persistence_error:raise owner.persistence_error
                if owner.observations is not None:return owner.observations
                return tuple(row for row in h.register_saved if row.command.company_id==query.company_id
                             and row.command.income_year==query.income_year)
            async def record_register_observation(self,command,*,context,idempotency_key):
                owner.idempotencies.append(idempotency_key.value)
                if command.supersedes_observation_id is not None:
                    from talli_backend.modules.shareholder_register_filing.public import prepare_rf1086_register_observation, Rf1086RegisterObservationId
                    previous=next(row for row in h.register_saved if row.observation_id==command.supersedes_observation_id)
                    result=prepare_rf1086_register_observation(command,context=context,previous=previous,
                        observation_id=Rf1086RegisterObservationId(str(uuid4())),confirmed_at=previous.confirmed_at+timedelta(seconds=1))
                    h.register_saved.append(result);return result
                return await self.wrapped.record_register_observation(command,context=context,idempotency_key=idempotency_key)
            async def source_preview(self,preview_id):
                h.calls.append('read_preview')
                return next((row for row in h.previews if row.preview_id==preview_id),None)
        class RF:
            async def session(self,token):
                if token!='verified-token' or owner.auth_failure:raise ShareholderRegisterFilingAuthenticationError()
                return RFSession(await h.workflow._rf_sessions.session(token))
        class CompanyGateway:
            async def session_subject(self,token):
                assert token=='verified-token';return str(h.actor.subject)
            async def memberships(self,token,subject):
                h.calls.append('company_membership')
                return [{'company_id':h.company.id,'role':h.company.role,'accepted_at':NOW.isoformat()}]
            async def companies(self,token,company_ids):
                return [{**vars(h.company),'status_text':'Active','source':'test','created_by':str(ACTOR.subject),'created_at':NOW.isoformat()}]
        class GovTransaction:
            async def read_reporting_year_basis(self,company_id):
                h.calls.append('governance');assert company_id==COMPANY
                return owner.reporting_basis or CorporateReportingYearBasis(COMPANY,CorporateLifecycleSnapshot((),(),(),(),()),())
            async def list_entry_amendments(self,**kwargs):return owner.reporting_amendments
        class GovSession:
            actor_id=ACTOR
            @asynccontextmanager
            async def transaction(self):yield GovTransaction()
        class Gov:
            async def session(self,token):return GovSession()
        self.app=create_app(company_access_gateway=CompanyGateway(),documents_session_factory=h.workflow._documents,
            corporate_governance_session_factory=Gov(),shareholder_register_filing_session_factory=RF())
        self.client=TestClient(self.app)
    def capture(self,body=None,headers=None):
        return self.client.post(BASE+'/year-sources',json=body if body is not None else draft(self.h.command),headers=headers or HEADERS)
    def current_source(self,**query):
        return self.client.get(BASE+'/current-year-source',
            params={'companyId':str(COMPANY),'incomeYear':int(YEAR),**query},headers=HEADERS)
    def preview(self,source_id):
        return self.client.post(BASE+'/source-previews',json={'companyId':str(COMPANY),'incomeYear':int(YEAR),'sourceId':source_id},headers=HEADERS)
    def source_document(self,**query):
        return self.client.get(BASE+'/source-documents/'+DOCUMENT,
            params={'companyId':str(COMPANY),**query},headers=HEADERS)
    def read(self,preview_id,**query):
        return self.client.get(BASE+'/source-previews/'+preview_id,
            params={'companyId':str(COMPANY),'incomeYear':int(YEAR),**query},headers=HEADERS)


def test_capture_preview_and_fresh_review_use_real_workflow_and_owner_values():
    api=ApiHarness();result=api.capture()
    assert result.status_code==200,result.text
    receipt=result.json();assert set(receipt)=={'sourceId','companyId','incomeYear','version','sourceSha256','caseSha256','confirmedAt'}
    assert api.h.saved[0].command.actor_id==ACTOR and api.idempotencies==[HEADERS['Idempotency-Key']]
    assert 'verify_document' in api.h.calls and 'governance' in api.h.calls
    preview=api.preview(receipt['sourceId']);assert preview.status_code==200,preview.text
    body=preview.json();assert body['sourceSha256']==receipt['sourceSha256'] and body['hovedskjemaXml']
    assert body['sourceId']==receipt['sourceId'] and body['renderingProfile']=='rf1086-full-year-v1'
    count=len(api.h.previews);api.h.calls=[]
    read=api.read(body['previewId']);assert read.status_code==200,read.text
    assert read.json()==body and len(api.h.previews)==count
    assert {'read_preview','read_source','verify_document','governance','read_current_source'}<=set(api.h.calls)
    assert 'preview_persist' not in api.h.calls
    assert all(key not in receipt for key in ('command','actorId','governanceReceipts','freshness'))


def test_register_observation_capture_binds_authenticated_actor_and_independent_original():
    api=ApiHarness(capital=True)
    response=api.client.post(BASE+'/register-observations',json=draft(api.h.register_command),headers=HEADERS)
    assert response.status_code==200,response.text
    record=api.h.register_saved[0]
    assert response.json()['observationId']==record.observation_id.value
    assert response.json()['factSha256']==record.fact_sha256
    assert record.command.actor_id==ACTOR and 'verify_document' in api.h.calls
    assert set(response.json())=={'observationId','companyId','incomeYear','version','factSha256','confirmedAt'}


@pytest.mark.parametrize('headers',[{'Idempotency-Key':'source-api-capture-0001'},
    {**HEADERS,'Authorization':'Bearer wrong-token'}])
def test_authentication_failure_never_captures(headers):
    api=ApiHarness();response=api.capture(headers=headers)
    assert response.status_code==401 and not api.h.saved


@pytest.mark.parametrize('role',['reviewer','read_only'])
def test_current_nonowner_cannot_capture_or_review(role):
    api=ApiHarness();receipt=api.capture().json();preview=api.preview(receipt['sourceId']).json()
    api.h.company.role=role
    assert api.capture().status_code==403
    assert api.read(preview['previewId']).status_code==403
    assert len(api.h.saved)==1


@pytest.mark.parametrize('field,value',[('actorId','11111111-1111-4111-8111-111111111111'),('context',{'acceptedOwner':True}),
    ('acceptedOwner',True),('governanceReceipts',[]),('freshness',{}),('confirmedAt',NOW.isoformat())])
def test_caller_cannot_supply_trusted_fields(field,value):
    api=ApiHarness();body=draft(api.h.command);body[field]=value
    response=api.capture(body)
    assert response.status_code==422 and not api.h.saved
    assert value is True or str(value) not in response.text


@pytest.mark.parametrize('value',[30000,30000.0,True,'NaN','Infinity','1e3','-1'])
def test_source_money_rejects_lossy_or_noncanonical_input(value):
    api=ApiHarness();body=draft(api.h.command)
    body['case']['share_snapshot']['previous_share_capital']=value
    response=api.capture(body)
    assert response.status_code==422 and not api.h.saved


def test_decimal_strings_are_retained_without_binary_rounding():
    api=ApiHarness();body=draft(api.h.command);amount='9007199254740993.000001'
    body['case']['share_snapshot'].update(previous_paid_in_premium=amount,current_paid_in_premium=amount)
    body['paid_in'].update(opening_premium=amount,closing_premium=amount)
    response=api.capture(body);assert response.status_code==200,response.text
    assert api.h.saved[0].command.case.share_snapshot.previous_paid_in_premium==Decimal(amount)
    assert api.h.saved[0].command.paid_in.opening_premium==Decimal(amount)


@pytest.mark.parametrize('problem',['changed_bytes','changed_metadata','invalid_bytes','unconfirmed','wrong_tenant','wrong_year'])
def test_changed_or_invalid_owner_evidence_prevents_capture(problem):
    api=ApiHarness();body=draft(api.h.command)
    if problem=='changed_bytes':api.h.record=replace(api.h.record,content_sha256='e'*64)
    if problem=='changed_metadata':api.h.record=replace(api.h.record,name='changed original')
    if problem=='invalid_bytes':api.h.document_failure=True
    if problem=='unconfirmed':api.h.company.identity_locked_at=None
    if problem=='wrong_tenant':body['company_id']=str(uuid4())
    if problem=='wrong_year':body['income_year']=2024
    response=api.capture(body)
    assert response.status_code in {403,404,409} and not api.h.saved,response.text
    assert DOCUMENT not in response.text and 'changed original' not in response.text


@pytest.mark.parametrize('problem',['source_superseded','bytes_drift','metadata_drift','invalid_bytes'])
def test_preview_creation_and_review_reject_stale_sources_and_originals(problem):
    api=ApiHarness();receipt=api.capture().json();body=api.preview(receipt['sourceId']).json()
    if problem=='source_superseded':api.h.current_source=correction(api.h)
    if problem=='bytes_drift':api.h.record=replace(api.h.record,content_sha256='e'*64)
    if problem=='metadata_drift':api.h.record=replace(api.h.record,name='changed original')
    if problem=='invalid_bytes':api.h.document_failure=True
    assert api.preview(receipt['sourceId']).status_code==409
    assert api.read(body['previewId']).status_code==409
    assert len(api.h.previews)==1


def test_review_conceals_other_scope_and_missing_record_without_original_io():
    api=ApiHarness();receipt=api.capture().json();preview=api.preview(receipt['sourceId']).json();api.h.calls=[]
    for query in ({'companyId':str(uuid4())},{'incomeYear':2024}):
        assert api.read(preview['previewId'],**query).status_code==404
    assert api.read(str(uuid4())).status_code==404
    assert 'verify_document' not in api.h.calls


def test_source_transport_openapi_has_exact_inputs_and_no_internal_context():
    schema=ApiHarness().app.openapi();models=schema['components']['schemas']
    assert models['RfSourceSharesWire']['properties']['previousShareCapital']['type']=='string'
    assert models['RfYearSourceCaptureWire']['additionalProperties'] is False
    assert {'context','actorId','freshness','governanceReceipts'}.isdisjoint(models['RfYearSourceCaptureWire']['properties'])
    assert models['RfSourceCaseWire']['properties']['events']['items']['discriminator']['propertyName']=='type'
    assert 'metadataSha256' not in models['DocumentWire']['properties']
    assert models['RfSourceDocumentWire']['additionalProperties'] is False
    operation=schema['paths'][BASE+'/source-documents/{documentId}']['get']
    assert operation['operationId']=='rf1086ReadSourceDocument'


def test_existing_document_projection_retains_predecessor_response_shape():
    from talli_backend.main import _document_wire
    api=ApiHarness();wire=_document_wire(api.h.record).model_dump(mode='json',by_alias=True)
    assert set(wire)=={'id','companyId','incomeYear','documentType','name','linkedTo','status',
        'retentionYears','storageKey','contentType','byteLength','contentSha256','createdBy',
        'createdAt','removedAt','removalReason'}
    assert wire['contentSha256']==api.h.record.content_sha256
    models=api.app.openapi()['components']['schemas']
    assert 'metadataSha256' not in models['DocumentWire']['properties']
    for model in ('RfSourceDocumentWire','RfRegisterDocumentWire'):
        assert 'metadataSha256' in models[model]['required']
        assert models[model]['properties']['metadataSha256']['type']=='string'


def test_verified_source_document_round_trips_into_capture_preserving_prior_year():
    api=ApiHarness();response=api.source_document()
    assert response.status_code==200,response.text
    source=response.json()
    assert set(source)=={'documentId','companyId','contentVersionSha256','contentSha256',
        'documentType','integrityStatus','byteLength','createdAt','metadataSha256','sourceIncomeYear'}
    assert source['metadataSha256']==document_metadata_sha256(api.h.record)
    assert source['sourceIncomeYear']==2024 and int(YEAR)==2025
    assert api.h.calls==['rf_auth','company_membership','verify_document']
    assert not api.h.saved
    body=draft(api.h.command);body['documents']=[source]
    response=api.capture(body)
    assert response.status_code==200,response.text
    assert api.h.saved[0].command.documents==api.h.command.documents
    assert api.h.calls.count('verify_document')==2


@pytest.mark.parametrize('headers',[{}, {'Authorization':'Bearer wrong-token'}])
def test_source_document_requires_authenticated_actor(headers):
    api=ApiHarness()
    response=api.client.get(BASE+'/source-documents/'+DOCUMENT,
        params={'companyId':str(COMPANY)},headers=headers)
    assert response.status_code==401 and 'verify_document' not in api.h.calls


@pytest.mark.parametrize('problem',['reviewer','read_only','unconfirmed','unlocked','not_as','wrong_tenant','actor_mismatch'])
def test_source_document_checks_current_owner_before_reading_original(problem):
    api=ApiHarness();query={}
    assert api.source_document().status_code==200
    api.h.calls=[]
    if problem in {'reviewer','read_only'}:api.h.company.role=problem
    if problem=='unconfirmed':api.h.company.identity_confirmed_at=None
    if problem=='unlocked':api.h.company.identity_locked_at=None
    if problem=='not_as':api.h.company.entity_type='ENK'
    if problem=='wrong_tenant':query['companyId']=str(uuid4())
    if problem=='actor_mismatch':api.h.document_actor=replace(ACTOR,subject=str(uuid4()))
    response=api.source_document(**query)
    assert response.status_code in {403,404},response.text
    assert 'verify_document' not in api.h.calls
    assert api.h.record.name not in response.text and 'metadataSha256' not in response.text


@pytest.mark.parametrize('problem',['wrong_document_tenant','wrong_document_id','invalid_bytes'])
def test_source_document_never_returns_unverified_or_out_of_scope_metadata(problem):
    api=ApiHarness()
    if problem=='wrong_document_tenant':api.h.record=replace(api.h.record,company_id=CompanyId(str(uuid4())))
    if problem=='wrong_document_id':api.h.record=replace(api.h.record,document_id=DocumentId(str(uuid4())))
    if problem=='invalid_bytes':api.h.document_failure=True
    response=api.source_document()
    assert response.status_code in {404,409},response.text
    assert 'metadataSha256' not in response.text and api.h.record.name not in response.text


@pytest.mark.parametrize('problem',['bytes','metadata'])
def test_source_capture_rechecks_observation_after_source_document_read(problem):
    api=ApiHarness();source=api.source_document().json()
    if problem=='bytes':api.h.record=replace(api.h.record,content_sha256='e'*64)
    else:api.h.record=replace(api.h.record,name='Changed after read.pdf')
    body=draft(api.h.command);body['documents']=[source]
    response=api.capture(body)
    assert response.status_code==409 and not api.h.saved
    assert api.h.calls.count('verify_document')==2


@pytest.mark.parametrize('timestamp', ['2025-06-01T12:00:00Z', '2025-06-01T12:00:00+02:00', '2025-06-01T12:00:00.123456'])
def test_register_effective_time_rejects_timezone_and_fractional_seconds(timestamp):
    api=ApiHarness(capital=True);body=draft(api.h.register_command)
    body['effective_at']=timestamp
    response=api.client.post(BASE+'/register-observations',json=body,headers=HEADERS)
    assert response.status_code==422 and not api.h.register_saved


@pytest.mark.parametrize('kind', ['formation', 'transfer'])
def test_complete_event_case_captures_and_previews_civil_timestamps(kind):
    api=ApiHarness(kind=kind);body=draft(api.h.command)
    body['case']['share_snapshot'].update(previous_paid_in_premium='0',current_paid_in_premium='0')
    response=api.capture(body);assert response.status_code==200,response.text
    preview=api.preview(response.json()['sourceId'])
    assert preview.status_code==200,preview.text
    assert preview.json()['readinessStatus']=='ready'
    assert all(event.timestamp.tzinfo is None for event in api.h.saved[0].command.case.events)


@pytest.mark.parametrize('key', [None, 'short', 'bad key with spaces'])
def test_capture_requires_valid_idempotency_key(key):
    api=ApiHarness();headers=dict(HEADERS)
    if key is None:headers.pop('Idempotency-Key')
    else:headers['Idempotency-Key']=key
    response=api.capture(headers=headers)
    assert response.status_code==422 and not api.h.saved


def test_unsupported_decimal_precision_fails_domain_validation_without_capture():
    api=ApiHarness();body=draft(api.h.command);amount='2000.0000001'
    body['case']['share_snapshot'].update(previous_paid_in_premium=amount,current_paid_in_premium=amount)
    body['paid_in'].update(opening_premium=amount,closing_premium=amount)
    response=api.capture(body)
    assert response.status_code==409 and response.json()['code']=='rf1086_source_case_not_ready'
    assert not api.h.saved


@pytest.mark.parametrize('model,field', [
    ('RfSourceFormationWire','timestamp'),('RfSourceCashIssueWire','timestamp'),
    ('RfSourceNominalIncreaseWire','timestamp'),('RfSourceLossReductionWire','timestamp'),
    ('RfSourceShareSaleWire','timestamp'),('RfSourceDividendWire','timestamp'),
    ('RfRegisterObservationCaptureWire','effectiveAt'),
])
def test_civil_timestamp_schema_matches_local_whole_second_contract(model,field):
    models=ApiHarness().app.openapi()['components']['schemas']
    schema=models[model]['properties'][field]
    assert schema['type']=='string' and 'format' not in schema
    assert re.fullmatch(schema['pattern'],'2025-06-01T12:00:00')
    for invalid in ('2025-06-01T12:00:00Z','2025-06-01T12:00:00+02:00',
                    '2025-06-01T12:00:00.123456','2025-06-01 12:00:00'):
        assert re.fullmatch(schema['pattern'],invalid) is None
    assert models['RfSourceDocumentWire']['properties']['createdAt']['format']=='date-time'


@pytest.mark.parametrize('kind',['formation','transfer'])
@pytest.mark.parametrize('digest_input',['omitted','null','explicit'])
def test_customer_event_evidence_uses_server_owned_canonical_hash(kind,digest_input):
    api=ApiHarness(kind=kind);body=draft(api.h.command)
    body['case']['share_snapshot'].update(previous_paid_in_premium='0',current_paid_in_premium='0')
    expected=[row.event_sha256 for row in api.h.command.event_evidence]
    for item in body['event_evidence']:
        if digest_input=='omitted':item.pop('event_sha256')
        elif digest_input=='null':item['event_sha256']=None
    response=api.capture(body)
    assert response.status_code==200,response.text
    assert [row.event_sha256 for row in api.h.saved[0].command.event_evidence]==expected
    preview=api.preview(response.json()['sourceId'])
    assert preview.status_code==200 and preview.json()['readinessStatus']=='ready',preview.text


def test_explicit_event_hash_mismatch_remains_a_domain_conflict():
    api=ApiHarness(kind='transfer');body=draft(api.h.command)
    body['case']['share_snapshot'].update(previous_paid_in_premium='0',current_paid_in_premium='0')
    body['event_evidence'][0]['event_sha256']='f'*64
    response=api.capture(body)
    assert response.status_code==409 and response.json()['code']=='rf1086_source_event_evidence_mismatch'
    assert not api.h.saved


@pytest.mark.parametrize('problem',['duplicate','out_of_range','missing','negative','fractional','boolean'])
@pytest.mark.parametrize('omit_hash',[True,False])
def test_customer_event_evidence_does_not_bypass_index_or_coverage_checks(problem,omit_hash):
    api=ApiHarness(kind='transfer');body=draft(api.h.command)
    body['case']['share_snapshot'].update(previous_paid_in_premium='0',current_paid_in_premium='0')
    if omit_hash:
        for item in body['event_evidence']:item.pop('event_sha256')
    if problem=='duplicate':body['event_evidence'].append(dict(body['event_evidence'][0]))
    elif problem=='missing':body['event_evidence']=[]
    else:
        body['event_evidence'][0]['event_index']={
            'out_of_range':len(body['case']['events']),'negative':-1,'fractional':0.5,'boolean':True}[problem]
    response=api.capture(body)
    assert response.status_code==(422 if problem in {'negative','fractional','boolean'} else 409),response.text
    if response.status_code==409:
        assert response.json()['code']=='rf1086_source_event_evidence_incomplete'
    assert not api.h.saved


def test_event_digest_is_optional_only_at_customer_input_boundary():
    from talli_backend.modules.shareholder_register_filing.public import Rf1086YearEventEvidence, Rf1086YearSourceError
    schema=ApiHarness().app.openapi()['components']['schemas']['RfSourceEventEvidenceWire']
    assert 'eventSha256' not in schema['required']
    assert {'eventIndex','documentIds'}<=set(schema['required'])
    assert schema['additionalProperties'] is False
    with pytest.raises(Rf1086YearSourceError):
        Rf1086YearEventEvidence(0,None,(DOCUMENT,))


def test_current_source_absence_is_explicit_and_read_creates_nothing():
    api=ApiHarness();response=api.current_source()
    assert response.status_code==200,response.text
    assert response.json()=={'currentSource':None}
    assert not api.h.saved and not api.h.previews and not api.idempotencies
    assert 'read_current_source' in api.h.calls
    assert {'verify_document','governance','persist','preview_persist'}.isdisjoint(api.h.calls)


def test_current_source_read_edit_capture_preserves_predecessor_and_resets_review():
    api=ApiHarness();amount='9007199254740993.000001';body=draft(api.h.command)
    body['case']['share_snapshot'].update(previous_paid_in_premium=amount,current_paid_in_premium=amount)
    body['paid_in'].update(opening_premium=amount,closing_premium=amount)
    first=api.capture(body);assert first.status_code==200,first.text
    original=api.h.saved[0];original_hash=rf1086_year_source_digest(original);api.h.calls=[]
    response=api.current_source();assert response.status_code==200,response.text
    current=response.json()['currentSource'];assert current['receipt']==first.json()
    editable=current['draft']
    assert editable['paidIn']['openingPremium']==amount
    assert editable['case']['shareSnapshot']['previousPaidInPremium']==amount
    assert editable['documents'][0]['sourceIncomeYear']==2024
    assert editable['supersedesSourceId']==first.json()['sourceId']
    assert editable['supersedesSourceSha256']==first.json()['sourceSha256']
    assert editable['correctionReason'] is None
    flags=('identitiesReviewed','completeYearConfirmed','paidInReviewed','noActivityConfirmed')
    assert all(editable[field] is False for field in flags)
    assert {'verify_document','governance','persist','preview_persist'}.isdisjoint(api.h.calls)
    assert api.capture(editable).status_code==409
    editable.update({field:True for field in flags});editable['correctionReason']='Reviewed corrected holder name'
    editable['case']['shareholders'][0]['name']='Corrected owner name'
    second=api.capture(editable,headers={**HEADERS,'Idempotency-Key':'source-api-correction-0002'})
    assert second.status_code==200,second.text
    assert second.json()['version']==2 and second.json()['sourceId']!=first.json()['sourceId']
    assert len(api.h.saved)==2 and rf1086_year_source_digest(api.h.saved[0])==original_hash
    assert api.h.saved[1].command.supersedes_source_id==original.source_id
    again=api.current_source().json()['currentSource']
    assert again['receipt']==second.json() and again['draft']['correctionReason'] is None
    assert again['draft']['supersedesSourceId']==second.json()['sourceId']
    assert all(again['draft'][field] is False for field in flags)
    assert all(key not in current for key in ('freshness','actorId','governanceReceipts','context'))


@pytest.mark.parametrize('change',['bytes','metadata','unavailable'])
def test_stale_original_is_readable_for_correction_but_capture_reverifies(change):
    api=ApiHarness();assert api.capture().status_code==200
    if change=='bytes':api.h.record=replace(api.h.record,content_sha256='f'*64)
    if change=='metadata':api.h.record=replace(api.h.record,name='Changed original')
    if change=='unavailable':api.h.document_failure=True
    api.h.calls=[];response=api.current_source()
    assert response.status_code==200,response.text
    assert 'verify_document' not in api.h.calls
    editable=response.json()['currentSource']['draft']
    editable.update(identitiesReviewed=True,completeYearConfirmed=True,paidInReviewed=True,
        noActivityConfirmed=True,correctionReason='Re-reviewed evidence')
    assert api.capture(editable).status_code==409 and len(api.h.saved)==1
    assert 'verify_document' in api.h.calls


@pytest.mark.parametrize('change',['reviewer','read_only','revoked','unconfirmed','unlocked','entity','tenant'])
def test_current_source_denies_invalid_current_owner_before_retained_read(change):
    api=ApiHarness();assert api.capture().status_code==200;api.h.calls=[]
    if change in {'reviewer','read_only'}:api.h.company.role=change
    if change=='revoked':api.auth_failure=True
    if change=='unconfirmed':api.h.company.identity_confirmed_at=None
    if change=='unlocked':api.h.company.identity_locked_at=None
    if change=='entity':api.h.company.entity_type='ENK'
    query={'companyId':str(uuid4())} if change=='tenant' else {}
    response=api.current_source(**query)
    assert response.status_code in {401,403,404},response.text
    assert {'read_current_source','verify_document','governance','persist'}.isdisjoint(api.h.calls)
    assert DOCUMENT not in response.text and len(api.h.saved)==1


@pytest.mark.parametrize('change',['org_number','source_hash','case_hash','company','year'])
def test_current_source_denies_changed_identity_or_corrupt_or_wrong_scope_storage(change):
    api=ApiHarness();assert api.capture().status_code==200
    if change=='org_number':api.h.company.org_number='123456789'
    if change=='source_hash':api.h.current_source=replace(api.h.current_source,source_sha256='f'*64)
    if change=='case_hash':api.h.current_source=replace(api.h.current_source,case_sha256='f'*64)
    if change=='company':api.h.current_source=replace(api.h.current_source,company_id=CompanyId(str(uuid4())))
    query={'incomeYear':2024} if change=='year' else {}
    api.h.calls=[];response=api.current_source(**query)
    assert response.status_code==409,response.text
    assert {'verify_document','governance','persist'}.isdisjoint(api.h.calls)
    assert DOCUMENT not in response.text and len(api.h.saved)==1


@pytest.mark.parametrize('query',[{'incomeYear':1999},{'incomeYear':2101},{'incomeYear':'bad'},{'companyId':'bad'}])
def test_current_source_rejects_invalid_scope_parameters(query):
    api=ApiHarness();response=api.current_source(**query)
    assert response.status_code==422 and not api.h.calls


@pytest.mark.parametrize('kind',['formation','transfer'])
def test_current_source_preserves_civil_event_times_and_evidence_for_editing(kind):
    api=ApiHarness(kind=kind);body=draft(api.h.command)
    body['case']['share_snapshot'].update(previous_paid_in_premium='0',current_paid_in_premium='0')
    # A date near daylight-saving transition must never be converted through UTC.
    body['case']['events'][0]['timestamp']='2025-03-30T02:30:00'
    body['event_evidence'][0]['event_sha256']=None
    response=api.capture(body);assert response.status_code==200,response.text
    current=api.current_source();assert current.status_code==200,current.text
    editable=current.json()['currentSource']['draft']
    assert editable['case']['events'][0]['timestamp']=='2025-03-30T02:30:00'
    assert editable['eventEvidence'][0]['documentIds']==[DOCUMENT]
    assert editable['eventEvidence'][0]['eventSha256']==api.h.saved[0].command.event_evidence[0].event_sha256
    assert editable['case']['events'][0]['type']==api.h.saved[0].command.case.events[0].type


def test_current_source_api_is_additive_without_input_schema_splitting():
    schema=ApiHarness().app.openapi();models=schema['components']['schemas']
    assert 'RfYearSourceCaptureWire' in models and 'RfSourceCaseWire' in models
    assert not any(key.startswith(('RfSource','RfYearSource')) and key.endswith(('-Input','-Output')) for key in models)
    route=schema['paths'][BASE+'/current-year-source']['get']
    assert route['operationId']=='rf1086ReadCurrentYearSource'
    assert {item['name'] for item in route['parameters']}=={'companyId','incomeYear','X-Request-ID'}
    assert models['RfCurrentYearSourceWire']['required']==['currentSource']


@pytest.mark.parametrize('event',[
    {'type':'formation','timestamp':'2025-03-30T02:30:00','issued_share_count':100,'share_count_after':100,
     'nominal_value':'300.00','premium':'0.125',
     'allocations':[{'shareholder_id':'owner','share_count':100,'acquisition_value':'30012.500'}]},
    {'type':'cash_issue','timestamp':'2025-03-30T02:30:00','issued_share_count':100,'share_count_after':200,
     'nominal_value':'300.00','premium':'0.125','registration_confirmed':True,
     'allocations':[{'shareholder_id':'owner','share_count':100,'acquisition_value':'30012.500'}]},
    {'type':'cash_nominal_increase','timestamp':'2025-03-30T02:30:00','capital_increase':'125.00',
     'nominal_value_increase':'1.25','nominal_value_after':'301.25','registration_confirmed':True,'premium':'0.125',
     'allocations':[{'shareholder_id':'owner','share_count_basis':100,'capital_increase':'125.00','premium':'0.125'}]},
    {'type':'loss_covering_reduction','timestamp':'2025-03-30T02:30:00','capital_reduction':'125.00',
     'nominal_value_reduction':'1.25','nominal_value_after':'298.75','registration_confirmed':True,'fund_issued_capital_before':0},
    {'type':'share_sale','timestamp':'2025-03-30T02:30:00','seller_shareholder_id':'owner',
     'buyer_shareholder_id':'new-owner','share_count':1,'consideration':'9007199254740993.000001'},
    {'type':'dividend','timestamp':'2025-03-30T02:30:00','total_amount':'1000.125','per_share_amount':'10.00125',
     'allocations':[{'shareholder_id':'owner','amount':'1000.125','share_count_basis':100}]},
])
def test_every_public_event_projects_to_the_editable_wire_without_number_or_timezone_loss(event):
    from pydantic import TypeAdapter
    from talli_backend.main import RfSourceEventWire, _rf_source_value, _rf_source_public_json
    adapter=TypeAdapter(RfSourceEventWire)
    original=adapter.validate_python(event)
    domain=_rf_source_value(original)
    projected=_rf_source_public_json(domain)
    assert projected==event
    assert _rf_source_value(adapter.validate_python(projected))==domain


@pytest.mark.parametrize('kind',['dividend','cash_issue','loss_covering_reduction'])
def test_current_source_projects_governed_events_and_receipt_references(kind):
    from test_shareholder_register_capital_source_workflow import prepare_capital
    api=ApiHarness(kind='dividend' if kind=='dividend' else 'no_activity')
    if kind!='dividend':
        # Use the same public workflow with independently backed register evidence.
        # The API wrapper closes over h, so configure its retained source from a
        # separate fully prepared owner composition.
        h=capital_setup(kind);prepare_capital(h);source=h.capture()
        api.h.company=h.company;api.h.current_source=source
    else:
        source=api.h.capture()
    response=api.current_source();assert response.status_code==200,response.text
    record=response.json()['currentSource'];event=record['draft']['case']['events'][0]
    assert event['type']==kind
    evidence=record['draft']['eventEvidence'][0]
    assert evidence['governanceReceiptId']==source.command.event_evidence[0].governance_receipt_id
    assert evidence['documentIds']==list(source.command.event_evidence[0].document_ids)
    assert record['receipt']['sourceSha256']==source.source_sha256


def test_current_source_requires_authentication_and_is_not_cacheable():
    api=ApiHarness()
    response=api.client.get(BASE+'/current-year-source',params={'companyId':str(COMPANY),'incomeYear':int(YEAR)})
    assert response.status_code==401 and 'read_current_source' not in api.h.calls
    assert 'no-store' in api.current_source().headers['cache-control']


@pytest.mark.parametrize('field,new_value',[
    ('name','Renamed holding AS'),('address','New address 42'),('postal_code','0456'),('city','BERGEN'),
])
def test_current_source_remains_readable_after_company_details_change_for_correction(field,new_value):
    api=ApiHarness();assert api.capture().status_code==200
    original=api.h.saved[0];before=rf1086_year_source_digest(original)
    setattr(api.h.company,field,new_value)
    api.h.company.identity_confirmed_at=(NOW+timedelta(days=1)).isoformat()
    api.h.company.identity_locked_at=(NOW+timedelta(days=1)).isoformat()
    api.h.calls=[];response=api.current_source()
    assert response.status_code==200,response.text
    editable=response.json()['currentSource']['draft']
    wire_field={'postal_code':'postalCode'}.get(field,field)
    assert editable['case']['company'][wire_field]==getattr(original.command.case.company,field)
    assert {'verify_document','governance','persist'}.isdisjoint(api.h.calls)
    assert all(editable[key] is False for key in (
        'identitiesReviewed','completeYearConfirmed','paidInReviewed','noActivityConfirmed'))
    editable.update(identitiesReviewed=True,completeYearConfirmed=True,paidInReviewed=True,
        noActivityConfirmed=True,correctionReason='Reviewed updated company details')
    denied=api.capture(editable)
    assert denied.status_code==409 and denied.json()['code']=='rf1086_source_company_year_mismatch'
    assert len(api.h.saved)==1 and rf1086_year_source_digest(api.h.saved[0])==before
    editable['case']['company'][wire_field]=new_value
    corrected=api.capture(editable,headers={**HEADERS,'Idempotency-Key':'updated-company-correction-0002'})
    assert corrected.status_code==200,corrected.text
    assert corrected.json()['version']==2
    assert api.h.saved[1].command.supersedes_source_id==original.source_id
    assert getattr(api.h.saved[1].command.case.company,field)==new_value
    assert rf1086_year_source_digest(api.h.saved[0])==before


def test_renewed_company_identity_confirmation_does_not_hide_retained_source():
    api=ApiHarness();assert api.capture().status_code==200
    original=api.h.saved[0]
    api.h.company.identity_confirmed_at=(NOW+timedelta(days=1)).isoformat()
    api.h.company.identity_locked_at=(NOW+timedelta(days=1)).isoformat()
    response=api.current_source();assert response.status_code==200,response.text
    assert response.json()['currentSource']['receipt']['sourceSha256']==original.source_sha256
    assert len(api.h.saved)==1



def intake_basis(api, **query):
    return api.client.get(BASE+'/source-intake-basis',
        params={'companyId':str(COMPANY),'incomeYear':int(YEAR),**query},headers=HEADERS)


def populate_intake_governance(api, h):
    from talli_backend.modules.corporate_governance.public import CorporateDocumentSetRecord
    view=h.view
    sets=tuple(CorporateDocumentSetRecord(item.decision.document_set_id,COMPANY,item.decision.income_year,
        item.decision.decision_id,'dividend','1',item.decision.decision_hash,None,str(ACTOR.subject),NOW)
        for item in view.dividends)
    api.reporting_basis=CorporateReportingYearBasis(COMPANY,CorporateLifecycleSnapshot(
        tuple(item.decision for item in view.dividends),sets,
        tuple(row for item in view.dividends for row in item.artifacts),
        tuple(row for item in view.dividends for row in item.events),
        tuple(row for item in view.dividends for row in item.finalizations)),
        tuple(row for item in view.supported_events for row in (item.lifecycle_events or (item.recorded,))))
    api.reporting_amendments=view.ledger_amendments


def test_intake_basis_authentication_scope_and_no_store():
    api=ApiHarness()
    response=api.client.get(BASE+'/source-intake-basis',params={'companyId':str(COMPANY),'incomeYear':2025})
    assert response.status_code==401 and 'governance' not in api.h.calls
    api.auth_failure=True;assert intake_basis(api).status_code==401
    api.auth_failure=False
    for query in ({'companyId':str(uuid4())},{'incomeYear':1999},{'incomeYear':2101},{'companyId':'invalid'}):
        api.h.calls=[];response=intake_basis(api,**query)
        assert response.status_code in {404,422} and 'governance' not in api.h.calls
    response=intake_basis(api);assert response.status_code==200,response.text
    body=response.json();assert body['enumerationComplete'] is True
    assert body['dividends']==[] and body['capitalEvents']==[] and body['ledgerAmendments']==[]
    assert body['company']['orgNumber']==api.h.company.org_number
    assert set(body['company'])=={'orgNumber','name','address','postalCode','city','identityConfirmedAt','identityLockedAt'}
    assert 'no-store' in response.headers['cache-control']
    assert 'verify_document' not in api.h.calls and not api.h.saved


@pytest.mark.parametrize('change',['reviewer','unconfirmed','unlocked','not_as'])
def test_intake_basis_requires_current_confirmed_as_owner(change):
    api=ApiHarness()
    if change=='reviewer':api.h.company.role='reviewer'
    if change=='unconfirmed':api.h.company.identity_confirmed_at=None
    if change=='unlocked':api.h.company.identity_locked_at=None
    if change=='not_as':api.h.company.entity_type='ENK'
    response=intake_basis(api)
    assert response.status_code in {403,404,409},response.text
    assert 'governance' not in api.h.calls and not api.h.saved


@pytest.mark.parametrize('kind',['dividend','cash_issue','loss_covering_reduction'])
def test_intake_basis_projects_real_governance_enumeration_to_typed_economics_and_original_refs(kind):
    from test_shareholder_register_capital_source_workflow import setup, prepare_capital
    h=Harness('dividend') if kind=='dividend' else setup(kind)
    if kind!='dividend':prepare_capital(h)
    api=ApiHarness();populate_intake_governance(api,h)
    response=intake_basis(api);assert response.status_code==200,response.text
    body=response.json()
    if kind=='dividend':
        row=body['dividends'][0]
        assert row['sourceIncomeYear']==2024 and row['reportingYear']==2025
        assert row['economics']['amount']=='1000.00'
        assert row['finalizations'][0]['originalDocumentIds']==[DOCUMENT]
        assert all(doc['sourceIncomeYear']==2024 for doc in row['documents'])
    else:
        row=body['capitalEvents'][0]['events'][0]
        assert row['registerObservation']['observationId']==h.observation.observation_id.value
        assert row['registerObservation']['factSha256']==h.observation.fact_sha256
        assert len(row['documents'])==3 and row['documents'][0]['revision']==3
        assert row['economics']['nominalIncrease' if kind=='cash_issue' else 'nominalReduction']=='30000'
    assert 'canonical' not in response.text and 'actorId' not in response.text
    assert 'verify_document' not in api.h.calls and not api.h.saved


def test_intake_basis_preserves_pending_governance_as_explicit_blocker():
    h=Harness('dividend');h.view=replace(h.view,dividends=(replace(h.view.dividends[0],status='pending',finalizations=()),))
    api=ApiHarness();populate_intake_governance(api,h)
    response=intake_basis(api);assert response.status_code==200,response.text
    body=response.json()
    assert body['dividends'][0]['status']=='pending' and body['dividends'][0]['finalizations']==[]
    assert 'rf1086_source_governance_unresolved' in body['blockers']
    assert body['enumerationComplete'] is True


def test_actual_intake_responses_roundtrip_through_generated_client_and_reject_altered_economics():
    import json
    from pathlib import Path
    import subprocess
    from test_shareholder_register_capital_source_workflow import setup, prepare_capital
    responses=[]
    for kind in ('empty','dividend','pending','cash_issue','loss_covering_reduction'):
        api=ApiHarness()
        if kind in {'dividend','pending'}:
            h=Harness('dividend')
            if kind=='pending':h.view=replace(h.view,dividends=(replace(h.view.dividends[0],finalizations=()),))
            populate_intake_governance(api,h)
        elif kind!='empty':
            h=setup(kind);prepare_capital(h);populate_intake_governance(api,h)
        response=intake_basis(api);assert response.status_code==200,response.text
        responses.append(response.json())
    client=(Path(__file__).resolve().parents[3]/'packages/talli-api-client/src/generated/client.ts').as_uri()
    script='''
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const { createTalliApiClient } = await import(process.argv[1]);
const responses = JSON.parse(readFileSync(0, 'utf8'));
for (const body of responses) {
  const calls = [];
  const client = createTalliApiClient({ baseUrl: 'https://backend.invalid', fetch: async (url, init) => {
    calls.push([url, init]); return new Response(JSON.stringify(body), { status: 200 });
  }});
  const result = await client.rf1086ReadSourceIntakeBasis({ companyId: body.companyId, incomeYear: body.incomeYear,
    headers: { Authorization: 'Bearer synthetic-owner-token' }, requestId: 'intake-client-proof' });
  assert.deepEqual(result, body);
  assert.equal(new URL(calls[0][0]).searchParams.get('companyId'), body.companyId);
  assert.equal(new URL(calls[0][0]).searchParams.get('incomeYear'), String(body.incomeYear));
  assert.equal(calls[0][1].method, 'GET');
  assert.equal(calls[0][1].cache, 'no-store');
  assert.equal(new Headers(calls[0][1].headers).get('Authorization'), 'Bearer synthetic-owner-token');
}
const altered = structuredClone(responses[1]);
altered.dividends[0].economics.amount = 1000;
const client = createTalliApiClient({ baseUrl: 'https://backend.invalid', fetch: async () => new Response(JSON.stringify(altered), {status:200}) });
await assert.rejects(() => client.rf1086ReadSourceIntakeBasis({ companyId: altered.companyId, incomeYear: altered.incomeYear }));
console.log('5 real intake API responses accepted; altered decimal-string response rejected');
'''
    result=subprocess.run(['node','--experimental-strip-types','--input-type=module','-e',script,client],
        input=json.dumps(responses),capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
