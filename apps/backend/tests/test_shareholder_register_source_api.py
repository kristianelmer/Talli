"""Authenticated source routes run the real workflow against synthetic owners."""
from contextlib import asynccontextmanager
from dataclasses import fields, is_dataclass, replace
from datetime import datetime
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
from talli_backend.shared.kernel import CompanyId
from talli_backend.modules.shareholder_register_filing.public import Rf1086YearSourceId
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
        owner=self
        class RFSession:
            def __init__(self, wrapped):self.wrapped=wrapped
            @property
            def actor_id(self):return h.actor
            def __getattr__(self,name):return getattr(self.wrapped,name)
            async def record_year_source(self,command,*,context,idempotency_key):
                owner.idempotencies.append(idempotency_key.value)
                if owner.persistence_error:raise owner.persistence_error
                return await self.wrapped.record_year_source(command,context=context,idempotency_key=idempotency_key)
            async def record_register_observation(self,command,*,context,idempotency_key):
                owner.idempotencies.append(idempotency_key.value)
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
                return CorporateReportingYearBasis(COMPANY,CorporateLifecycleSnapshot((),(),(),(),()),())
            async def list_entry_amendments(self,**kwargs):return ()
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
