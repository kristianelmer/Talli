"""Immutable request and response originals for the Tax submit-once journal."""
from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import re
from uuid import UUID

from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, Timestamp, UserId
from .delivery import TaxMutationIntent, TaxMutationKind, TaxMutationRecord, _digest, _json
from .delivery_approval import TaxDeliveryReviewApproval
from .delivery_draft import TaxDeliveryDraft, _canonical, _object

_APP_ID='skd/formueinntekt-skattemelding-v2'
_MAX_BODY=8*1024*1024


def _uuid(value):
    if type(value) is not str or str(UUID(value))!=value:
        raise ValueError('Tax journal identifier is invalid.')
    return value


def _instance(value):
    if type(value) is not str or re.fullmatch(r'[0-9]{1,19}/[0-9a-f-]{36}',value) is None:
        raise ValueError('Tax journal instance is invalid.')
    _uuid(value.split('/',1)[1])
    return value


def _bytes(encoded, *, allow_empty=False):
    if type(encoded) is not str or len(encoded)>12*1024*1024:
        raise ValueError('Tax journal original exceeds its limit.')
    raw=base64.b64decode(encoded,validate=True)
    if ((not raw and not allow_empty) or len(raw)>_MAX_BODY
            or base64.b64encode(raw).decode('ascii')!=encoded):
        raise ValueError('Tax journal original encoding is invalid.')
    raw.decode('utf-8',errors='strict')
    return raw


@dataclass(frozen=True, slots=True)
class TaxDeliveryMutationRequest:
    filing_id: str
    company_id: CompanyId
    income_year: IncomeYear
    organization_number: str
    approval_sha256: str
    kind: TaxMutationKind
    target_instance: str | None
    body_base64: str

    def __post_init__(self):
        _uuid(self.filing_id);_digest(self.approval_sha256)
        if (type(self.company_id) is not CompanyId or type(self.income_year) is not IncomeYear
                or type(self.income_year.value) is not int or int(self.income_year)!=2025
                or type(self.organization_number) is not str
                or re.fullmatch('[0-9]{9}',self.organization_number) is None
                or type(self.kind) is not TaxMutationKind):
            raise ValueError('Tax journal request scope is invalid.')
        if self.kind is TaxMutationKind.CREATE_INSTANCE:
            if self.target_instance is not None:raise ValueError('New Tax instance cannot have a prior target.')
        else:_instance(self.target_instance)
        _bytes(self.body_base64,allow_empty=self.kind is TaxMutationKind.PREPARE_CONFIRMATION)

    @property
    def body_bytes(self) -> bytes:
        return _bytes(self.body_base64,allow_empty=self.kind is TaxMutationKind.PREPARE_CONFIRMATION)

    @property
    def canonical_json(self) -> str:
        return _canonical({'version':'company-tax-delivery-mutation-request-v1','request':_json(self)})

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()

    def intent(self, approval: TaxDeliveryReviewApproval) -> TaxMutationIntent:
        if (type(approval) is not TaxDeliveryReviewApproval or self.approval_sha256!=approval.sha256
                or self.filing_id!=approval.filing_id or self.company_id!=approval.company_id
                or self.income_year!=approval.income_year):
            raise ValueError('Tax journal request does not bind its approval.')
        return TaxMutationIntent(self.filing_id,self.company_id,self.income_year,approval.approved_by,
            approval.sha256,self.kind,self.sha256)

    def assert_draft(self, approval: TaxDeliveryReviewApproval, draft: TaxDeliveryDraft) -> None:
        if self != build_tax_delivery_mutation_request(approval,draft,self.kind,target_instance=self.target_instance):
            raise ValueError('Tax mutation request differs from the approved original.')


def build_tax_delivery_mutation_request(approval: TaxDeliveryReviewApproval, draft: TaxDeliveryDraft,
        kind: TaxMutationKind, *, target_instance: str | None = None) -> TaxDeliveryMutationRequest:
    """Create exact nonsecret wire bodies; an operation never accepts a URL.

    These bodies preserve the fixed Tax application contract. The eventual
    transport independently checks the rebuilt request before sending it.
    Journal sequencing and current runtime admission are separate decisions.
    """
    approval.assert_draft(draft)
    if type(kind) is not TaxMutationKind:raise ValueError('Tax mutation kind is invalid.')
    source=draft.envelope.source
    if kind is TaxMutationKind.CREATE_INSTANCE:
        body=json.dumps({'instanceOwner':{'organisationNumber':source.organization_number},
            'appId':_APP_ID,'dataValues':{'inntektsaar':int(source.income_year)}},separators=(',',':')).encode()
    elif kind is TaxMutationKind.UPLOAD_ENVELOPE:
        body=draft.envelope.envelope_xml.encode('utf-8')
    elif kind is TaxMutationKind.START_VALIDATION:
        body=json.dumps({'appId':_APP_ID,'instansId':_instance(target_instance)},separators=(',',':')).encode()
    else:body=b''
    return TaxDeliveryMutationRequest(draft.filing_id,source.company_id,source.income_year,
        source.organization_number,approval.sha256,kind,target_instance,base64.b64encode(body).decode('ascii'))


class TaxDeliveryCompletionOrigin(StrEnum):
    MUTATION_RESPONSE = 'mutation_response'
    INSTANCE_READ = 'instance_read'


def _response_object(raw: bytes):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate Tax response key.')
            result[key]=value
        return result
    def constant(_value):raise ValueError('Nonfinite Tax response value.')
    result=json.loads(raw.decode('utf-8-sig',errors='strict'),object_pairs_hook=pairs,parse_constant=constant)
    if type(result) is not dict:raise ValueError('Tax response must be an object.')
    return result


@dataclass(frozen=True, slots=True)
class TaxDeliveryMutationCompletion:
    intent: TaxMutationIntent
    result: Mapping[str, object]
    response_base64: str
    observed_at: Timestamp
    origin: TaxDeliveryCompletionOrigin

    def __post_init__(self):
        if (type(self.intent) is not TaxMutationIntent or type(self.observed_at) is not Timestamp
                or type(self.origin) is not TaxDeliveryCompletionOrigin):
            raise ValueError('Tax completion binding is invalid.')
        record=TaxMutationRecord(self.intent,'completed',self.result)
        value=_response_object(_bytes(self.response_base64))
        # Bind the normalized result to its original. A PUT acknowledgment does
        # not prove confirmation: that requires a separate instance read.
        if self.intent.kind is TaxMutationKind.PREPARE_CONFIRMATION:
            process=value.get('process')
            task=process.get('currentTask') if type(process) is dict else None
            if (self.origin is not TaxDeliveryCompletionOrigin.INSTANCE_READ
                    or value.get('id')!=record.result['instanceId']
                    or type(task) is not dict or task.get('altinnTaskType')!='confirmation'):
                raise ValueError('Tax confirmation requires the exact confirming instance read.')
        else:
            if self.origin is not TaxDeliveryCompletionOrigin.MUTATION_RESPONSE:
                raise ValueError('Tax mutation result has no supported read reconciliation proof.')
            field='jobbId' if self.intent.kind is TaxMutationKind.START_VALIDATION else 'id'
            key={TaxMutationKind.CREATE_INSTANCE:'instanceId',TaxMutationKind.UPLOAD_ENVELOPE:'dataId',
                TaxMutationKind.START_VALIDATION:'jobId'}[self.intent.kind]
            if value.get(field)!=record.result[key]:raise ValueError('Tax result differs from its original.')
        object.__setattr__(self,'result',record.result)

    @property
    def response_bytes(self) -> bytes:
        return _bytes(self.response_base64)

    @property
    def canonical_json(self) -> str:
        return _canonical({'version':'company-tax-delivery-mutation-completion-v1','completion':_json(self)})

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()

    def assert_request(self, request: TaxDeliveryMutationRequest, approval: TaxDeliveryReviewApproval) -> None:
        if self.intent!=request.intent(approval):
            raise ValueError('Tax completion belongs to a different request.')
        if request.target_instance is not None and self.result['instanceId']!=request.target_instance:
            raise ValueError('Tax completion belongs to a different instance.')
        if request.kind is TaxMutationKind.UPLOAD_ENVELOPE and (
                self.result['envelopeSha256']!=hashlib.sha256(request.body_bytes).hexdigest()):
            raise ValueError('Tax completion refers to different envelope bytes.')


def complete_tax_delivery_mutation(request: TaxDeliveryMutationRequest, approval: TaxDeliveryReviewApproval,
        draft: TaxDeliveryDraft, *, response_bytes: bytes, observed_at: Timestamp,
        origin: TaxDeliveryCompletionOrigin) -> TaxDeliveryMutationCompletion:
    """Retain one successful response or confirmation read without reserializing it.

    The trusted adapter supplies the successful response from this exact request.
    This value does not turn a missing response into a retry or prove clean file
    scanning, successful validation, owner confirmation or final receipt.
    """
    request.assert_draft(approval,draft)
    if type(response_bytes) is not bytes or not 0<len(response_bytes)<=_MAX_BODY:
        raise ValueError('Tax response original exceeds its limit.')
    value=_response_object(response_bytes)
    kind=request.kind
    if kind is TaxMutationKind.CREATE_INSTANCE:result={'instanceId':value.get('id')}
    elif kind is TaxMutationKind.UPLOAD_ENVELOPE:
        result={'instanceId':request.target_instance,'dataId':value.get('id'),
            'envelopeSha256':hashlib.sha256(request.body_bytes).hexdigest()}
    elif kind is TaxMutationKind.START_VALIDATION:
        result={'instanceId':request.target_instance,'jobId':value.get('jobbId')}
    else:result={'instanceId':request.target_instance,'processTask':'confirmation'}
    completion=TaxDeliveryMutationCompletion(request.intent(approval),result,
        base64.b64encode(response_bytes).decode('ascii'),observed_at,origin)
    completion.assert_request(request,approval)
    return completion


def _decode(raw, expected_sha256, version, field):
    def pairs(items):
        value={}
        for key,child in items:
            if key in value:raise ValueError('Duplicate Tax journal key.')
            value[key]=child
        return value
    def constant(_value):raise ValueError('Nonfinite Tax journal value.')
    if (type(raw) is not str or len(raw.encode('utf-8'))>12*1024*1024+16384
            or _digest(expected_sha256)!=hashlib.sha256(raw.encode('utf-8')).hexdigest()):
        raise ValueError('Tax journal bytes changed.')
    value=_object(json.loads(raw,object_pairs_hook=pairs,parse_constant=constant),('version',field))
    if value['version']!=version:raise ValueError('Tax journal codec is unknown.')
    return value[field]


def decode_tax_delivery_mutation_request(raw: str, expected_sha256: str) -> TaxDeliveryMutationRequest:
    try:
        value=_object(_decode(raw,expected_sha256,'company-tax-delivery-mutation-request-v1','request'),
            ('filing_id','company_id','income_year','organization_number','approval_sha256','kind','target_instance','body_base64'))
        company=_object(value['company_id'],('value',));year=_object(value['income_year'],('value',))
        result=TaxDeliveryMutationRequest(**(value|{'company_id':CompanyId(company['value']),
            'income_year':IncomeYear(year['value']),'kind':TaxMutationKind(value['kind'])}))
        if result.canonical_json!=raw:raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ValueError('Retained Tax mutation request is invalid or its exact bytes changed.') from None


def decode_tax_delivery_mutation_completion(raw: str, expected_sha256: str) -> TaxDeliveryMutationCompletion:
    try:
        value=_object(_decode(raw,expected_sha256,'company-tax-delivery-mutation-completion-v1','completion'),
            ('intent','result','response_base64','observed_at','origin'))
        intent=_object(value['intent'],('filing_id','company_id','income_year','approved_by','approval_sha256','kind','request_sha256'))
        company=_object(intent['company_id'],('value',));year=_object(intent['income_year'],('value',))
        actor=_object(intent['approved_by'],('kind','subject'));subject=_object(actor['subject'],('value',))
        observed=_object(value['observed_at'],('value',))
        intent=TaxMutationIntent(**(intent|{'company_id':CompanyId(company['value']),
            'income_year':IncomeYear(year['value']),'kind':TaxMutationKind(intent['kind']),
            'approved_by':ActorId(ActorKind(actor['kind']),UserId(subject['value']))}))
        result=TaxDeliveryMutationCompletion(intent,value['result'],value['response_base64'],
            Timestamp(datetime.fromisoformat(observed['value'])),TaxDeliveryCompletionOrigin(value['origin']))
        if result.canonical_json!=raw:raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ValueError('Retained Tax mutation completion is invalid or its exact bytes changed.') from None
