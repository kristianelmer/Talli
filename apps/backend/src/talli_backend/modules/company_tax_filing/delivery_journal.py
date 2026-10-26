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

from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, Timestamp, UserId
from .delivery import TaxMutationIntent, TaxMutationKind, TaxMutationRecord, _digest, _json
from .delivery_approval import TaxDeliveryReviewApproval
from .delivery_draft import TaxDeliveryDraft, _canonical, _object

from .delivery_original import _bytes,_instance,_response_object,_uuid,_MAX_BODY
from .delivery_upload_prerequisite import TaxDeliveryUploadPrerequisite,_decode_upload_prerequisite
from .delivery_upload_read_evidence import TaxDeliveryUploadReadEvidence,_decode_upload_read_evidence

_APP_ID='skd/formueinntekt-skattemelding-v2'


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
    upload_prerequisite: TaxDeliveryUploadPrerequisite | None=None

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
        if self.upload_prerequisite is not None and (
                type(self.upload_prerequisite) is not TaxDeliveryUploadPrerequisite
                or self.kind is not TaxMutationKind.UPLOAD_ENVELOPE
                or self.upload_prerequisite.instance_id!=self.target_instance):
            raise ValueError('Tax upload prerequisite differs from its exact request.')

    @property
    def body_bytes(self) -> bytes:
        return _bytes(self.body_base64,allow_empty=self.kind is TaxMutationKind.PREPARE_CONFIRMATION)

    @property
    def canonical_json(self) -> str:
        value=_json(self)
        version='company-tax-delivery-mutation-request-v2'
        if self.upload_prerequisite is None:
            value.pop('upload_prerequisite');version='company-tax-delivery-mutation-request-v1'
        return _canonical({'version':version,'request':value})

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
        if self != build_tax_delivery_mutation_request(approval,draft,self.kind,target_instance=self.target_instance,
                upload_prerequisite=self.upload_prerequisite):
            raise ValueError('Tax mutation request differs from the approved original.')


def build_tax_delivery_mutation_request(approval: TaxDeliveryReviewApproval, draft: TaxDeliveryDraft,
        kind: TaxMutationKind, *, target_instance: str | None = None,
        upload_prerequisite: TaxDeliveryUploadPrerequisite | None=None) -> TaxDeliveryMutationRequest:
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
        source.organization_number,approval.sha256,kind,target_instance,base64.b64encode(body).decode('ascii'),upload_prerequisite)


class TaxDeliveryCompletionOrigin(StrEnum):
    MUTATION_RESPONSE = 'mutation_response'
    INSTANCE_READ = 'instance_read'
    ENVELOPE_READ = 'envelope_read'


@dataclass(frozen=True, slots=True)
class TaxDeliveryMutationCompletion:
    intent: TaxMutationIntent
    result: Mapping[str, object]
    response_base64: str | None
    observed_at: Timestamp
    origin: TaxDeliveryCompletionOrigin
    upload_read_evidence: TaxDeliveryUploadReadEvidence | None=None

    def __post_init__(self):
        if (type(self.intent) is not TaxMutationIntent or type(self.observed_at) is not Timestamp
                or type(self.origin) is not TaxDeliveryCompletionOrigin):
            raise ValueError('Tax completion binding is invalid.')
        record=TaxMutationRecord(self.intent,'completed',self.result)
        if self.upload_read_evidence is not None:
            proof=self.upload_read_evidence
            if (type(proof) is not TaxDeliveryUploadReadEvidence or self.intent.kind is not TaxMutationKind.UPLOAD_ENVELOPE
                    or self.origin is not TaxDeliveryCompletionOrigin.ENVELOPE_READ or self.response_base64 is not None
                    or dict(record.result)!=proof.result or self.intent.filing_id!=proof.instance.filing_id
                    or self.intent.company_id!=proof.instance.company_id or self.intent.income_year!=proof.instance.income_year
                    or self.intent.approved_by!=proof.instance.approved_by or self.intent.approval_sha256!=proof.instance.approval_sha256
                    or self.observed_at.value<proof.instance.observed_at.value or self.observed_at.value<proof.envelope.observed_at.value):
                raise ValueError('Tax upload reconciliation is not bound to its original intent and read originals.')
            object.__setattr__(self,'result',record.result)
            return
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
        if self.upload_read_evidence is not None:return self.upload_read_evidence.instance.original.raw_bytes
        return _bytes(self.response_base64)

    @property
    def canonical_json(self) -> str:
        value=_json({key:getattr(self,key) for key in ('intent','result','response_base64','observed_at','origin')})
        version='company-tax-delivery-mutation-completion-v1'
        if self.upload_read_evidence is not None:
            value.pop('response_base64');value['upload_read_evidence']=self.upload_read_evidence.canonical_value
            version='company-tax-delivery-mutation-completion-v2'
        return _canonical({'version':version,'completion':value})

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
        if self.upload_read_evidence is not None:self.upload_read_evidence.assert_request(request)


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


def reconcile_tax_delivery_upload(request: TaxDeliveryMutationRequest,approval: TaxDeliveryReviewApproval,
        draft: TaxDeliveryDraft,*,evidence: TaxDeliveryUploadReadEvidence,observed_at: Timestamp) -> TaxDeliveryMutationCompletion:
    """Resolve a prior upload using exact originals, without sending another POST.

    Persistence must independently bind this result to the committed request.
    Pending scanning may still prove the upload exists; it cannot start validation.
    """
    request.assert_draft(approval,draft)
    if type(evidence) is not TaxDeliveryUploadReadEvidence:raise ValueError('Tax upload read evidence is required.')
    evidence.envelope.assert_instance(approval,draft,evidence.instance)
    evidence.assert_request(request)
    result=TaxDeliveryMutationCompletion(request.intent(approval),evidence.result,None,observed_at,
        TaxDeliveryCompletionOrigin.ENVELOPE_READ,evidence)
    result.assert_request(request,approval)
    return result


def _decode(raw, expected_sha256, version, field, *, maximum=12*1024*1024+16384):
    def pairs(items):
        value={}
        for key,child in items:
            if key in value:raise ValueError('Duplicate Tax journal key.')
            value[key]=child
        return value
    def constant(_value):raise ValueError('Nonfinite Tax journal value.')
    if (type(raw) is not str or len(raw.encode('utf-8'))>maximum
            or _digest(expected_sha256)!=hashlib.sha256(raw.encode('utf-8')).hexdigest()):
        raise ValueError('Tax journal bytes changed.')
    value=_object(json.loads(raw,object_pairs_hook=pairs,parse_constant=constant),('version',field))
    if value['version']!=version:raise ValueError('Tax journal codec is unknown.')
    return value[field]


def decode_tax_delivery_mutation_request(raw: str, expected_sha256: str) -> TaxDeliveryMutationRequest:
    try:
        if type(raw) is not str or len(raw.encode('utf-8'))>12*1024*1024+16384:raise ValueError()
        version=_response_object(raw.encode('utf-8')).get('version')
        if version not in ('company-tax-delivery-mutation-request-v1','company-tax-delivery-mutation-request-v2'):raise ValueError()
        successor=version=='company-tax-delivery-mutation-request-v2'
        value=_object(_decode(raw,expected_sha256,version,'request'),
            ('filing_id','company_id','income_year','organization_number','approval_sha256','kind','target_instance','body_base64',
                *(('upload_prerequisite',) if successor else ())))
        if successor:value=value|{'upload_prerequisite':_decode_upload_prerequisite(value['upload_prerequisite'])}
        company=_object(value['company_id'],('value',));year=_object(value['income_year'],('value',))
        result=TaxDeliveryMutationRequest(**(value|{'company_id':CompanyId(company['value']),
            'income_year':IncomeYear(year['value']),'kind':TaxMutationKind(value['kind'])}))
        if result.canonical_json!=raw:raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ValueError('Retained Tax mutation request is invalid or its exact bytes changed.') from None


def decode_tax_delivery_mutation_completion(raw: str, expected_sha256: str) -> TaxDeliveryMutationCompletion:
    try:
        if type(raw) is not str or len(raw.encode('utf-8'))>24*1024*1024+32768:raise ValueError()
        version=_response_object(raw.encode('utf-8')).get('version')
        if version not in ('company-tax-delivery-mutation-completion-v1','company-tax-delivery-mutation-completion-v2'):raise ValueError()
        successor=version=='company-tax-delivery-mutation-completion-v2'
        value=_object(_decode(raw,expected_sha256,version,'completion',maximum=(24*1024*1024+32768 if successor else 12*1024*1024+16384)),
            ('intent','result','observed_at','origin','upload_read_evidence' if successor else 'response_base64'))
        if successor:value=value|{'upload_read_evidence':_decode_upload_read_evidence(value['upload_read_evidence']),'response_base64':None}
        intent=_object(value['intent'],('filing_id','company_id','income_year','approved_by','approval_sha256','kind','request_sha256'))
        company=_object(intent['company_id'],('value',));year=_object(intent['income_year'],('value',))
        actor=_object(intent['approved_by'],('kind','subject'));subject=_object(actor['subject'],('value',))
        observed=_object(value['observed_at'],('value',))
        intent=TaxMutationIntent(**(intent|{'company_id':CompanyId(company['value']),
            'income_year':IncomeYear(year['value']),'kind':TaxMutationKind(intent['kind']),
            'approved_by':ActorId(ActorKind(actor['kind']),UserId(subject['value']))}))
        result=TaxDeliveryMutationCompletion(intent,value['result'],value['response_base64'],
            Timestamp(datetime.fromisoformat(observed['value'])),TaxDeliveryCompletionOrigin(value['origin']),value.get('upload_read_evidence'))
        if result.canonical_json!=raw:raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ValueError('Retained Tax mutation completion is invalid or its exact bytes changed.') from None
