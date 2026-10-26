"""Exact acknowledgment of a committed process PUT, without a stage verdict."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import re

from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IncomeYear,Timestamp,UserId
from .delivery import TaxMutationKind,_digest,_json
from .delivery_draft import _canonical,_object
from .delivery_original import _instance,_response_object
from .delivery_observation import TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose,_scope,_decode_original


@dataclass(frozen=True,slots=True)
class TaxDeliveryProcessAcknowledgment:
    filing_id: str
    company_id: CompanyId
    income_year: IncomeYear
    approved_by: ActorId
    approval_sha256: str
    organization_number: str
    instance_id: str
    request_sha256: str
    original: TaxDeliveryReadOriginal
    observed_at: Timestamp
    kind: TaxMutationKind=TaxMutationKind.PREPARE_CONFIRMATION

    def __post_init__(self):
        _scope(self);_instance(self.instance_id);_digest(self.request_sha256)
        if (type(self.organization_number) is not str or re.fullmatch('[0-9]{9}',self.organization_number) is None
                or type(self.original) is not TaxDeliveryReadOriginal or self.original.purpose is not TaxDeliveryOriginalPurpose.PROCESS_RESPONSE
                or type(self.observed_at) is not Timestamp or type(self.kind) is not TaxMutationKind
                or self.kind not in (TaxMutationKind.PREPARE_CONFIRMATION,TaxMutationKind.CONFIRM_SUBMISSION)):
            raise ValueError('Tax process acknowledgment is invalid.')

    @property
    def canonical_json(self):
        value=_json(self);version='company-tax-delivery-process-acknowledgment-v2'
        if self.kind is TaxMutationKind.PREPARE_CONFIRMATION:
            value.pop('kind');version='company-tax-delivery-process-acknowledgment-v1'
        return _canonical({'version':version,'acknowledgment':value})

    @property
    def sha256(self):return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()

    def assert_request(self,request,approval,draft):
        request.assert_draft(approval,draft)
        proof=request.confirmation_prerequisite if self.kind is TaxMutationKind.PREPARE_CONFIRMATION else request.submission_prerequisite
        if (request.kind is not self.kind or proof is None
                or self.request_sha256!=request.sha256 or self.instance_id!=request.target_instance
                or self.filing_id!=request.filing_id or self.company_id!=request.company_id or self.income_year!=request.income_year
                or self.approved_by!=approval.approved_by or self.approval_sha256!=approval.sha256
                or self.organization_number!=request.organization_number):
            raise ValueError('Tax process acknowledgment differs from the committed request.')


def decode_tax_delivery_process_acknowledgment(raw,expected_sha256):
    try:
        if (type(raw) is not str or len(raw.encode('utf-8'))>12*1024*1024+16384
                or _digest(expected_sha256)!=hashlib.sha256(raw.encode('utf-8')).hexdigest()):raise ValueError()
        value=_object(_response_object(raw.encode('utf-8')),('version','acknowledgment'))
        if value['version'] not in ('company-tax-delivery-process-acknowledgment-v1','company-tax-delivery-process-acknowledgment-v2'):raise ValueError()
        submission=value['version']=='company-tax-delivery-process-acknowledgment-v2'
        body=_object(value['acknowledgment'],('filing_id','company_id','income_year','approved_by','approval_sha256',
            'organization_number','instance_id','request_sha256','original','observed_at',*(('kind',) if submission else ())))
        if submission:
            if body['kind']!='confirm_submission':raise ValueError()
            body=body|{'kind':TaxMutationKind.CONFIRM_SUBMISSION}
        company=_object(body['company_id'],('value',));year=_object(body['income_year'],('value',))
        actor=_object(body['approved_by'],('kind','subject'));subject=_object(actor['subject'],('value',))
        observed=_object(body['observed_at'],('value',))
        result=TaxDeliveryProcessAcknowledgment(**(body|{'company_id':CompanyId(company['value']),
            'income_year':IncomeYear(year['value']),'approved_by':ActorId(ActorKind(actor['kind']),UserId(subject['value'])),
            'original':_decode_original(body['original']),'observed_at':Timestamp(datetime.fromisoformat(observed['value']))}))
        if result.canonical_json!=raw:raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ValueError('Retained Tax process acknowledgment is invalid or its exact bytes changed.') from None
