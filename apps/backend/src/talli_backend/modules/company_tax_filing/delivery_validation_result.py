"""Exact result XML linked to a finished, already-known validation job read."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import re

from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IncomeYear,Timestamp,UserId
from .delivery import _digest,_json,tax_delivery_digest
from .delivery_draft import _canonical,_object
from .delivery_observation import TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose,_scope,_decode_original
from .delivery_original import _instance,_job,_response_object
from .delivery_validation_job import TaxDeliveryValidationJobObservation,TaxValidationJobStatus
from .delivery_validation_response import TaxValidationResponseInspection


@dataclass(frozen=True,slots=True)
class TaxDeliveryValidationResultObservation:
    filing_id: str
    company_id: CompanyId
    income_year: IncomeYear
    approved_by: ActorId
    approval_sha256: str
    organization_number: str
    instance_id: str
    job_id: str
    start_request_sha256: str
    job_status_evidence_sha256: str
    schema_sha256: str
    original: TaxDeliveryReadOriginal
    observed_at: Timestamp

    def __post_init__(self):
        _scope(self);_instance(self.instance_id);_job(self.job_id);_digest(self.start_request_sha256)
        _digest(self.job_status_evidence_sha256);_digest(self.schema_sha256)
        if (type(self.organization_number) is not str or re.fullmatch('[0-9]{9}',self.organization_number) is None
                or type(self.original) is not TaxDeliveryReadOriginal or self.original.purpose is not TaxDeliveryOriginalPurpose.VALIDATION_RESULT
                or type(self.observed_at) is not Timestamp):raise ValueError('Tax validation result observation is invalid.')

    @property
    def canonical_json(self):
        return _canonical({'version':'company-tax-delivery-validation-result-observation-v1','observation':_json(self)})

    @property
    def sha256(self):return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()

    @property
    def evidence_sha256(self):
        return tax_delivery_digest(['tax-validation-result-read-identity-v1',self.filing_id,str(self.company_id),int(self.income_year),
            str(self.approved_by.subject),self.approval_sha256,self.organization_number,self.instance_id,self.job_id,
            self.start_request_sha256,self.job_status_evidence_sha256,self.schema_sha256,self.original.sha256])

    def assert_status(self,approval,draft,request,started,status: TaxDeliveryValidationJobObservation) -> None:
        if type(status) is not TaxDeliveryValidationJobObservation:raise ValueError('Tax validation result has no job status original.')
        status.assert_started(approval,draft,request,started)
        if (not status.inspection.known or status.inspection.status is not TaxValidationJobStatus.FINISHED
                or self.job_status_evidence_sha256!=status.evidence_sha256
                or self.observed_at.value<status.observed_at.value
                or any(getattr(self,name)!=getattr(status,name) for name in ('filing_id','company_id','income_year','approved_by',
                    'approval_sha256','organization_number','instance_id','job_id','start_request_sha256'))):
            raise ValueError('Tax validation result differs from its finished known-job read.')

    def inspect(self,validator) -> TaxValidationResponseInspection:
        if validator.schema_sha256!=self.schema_sha256:raise ValueError('Tax validation response schema pin differs.')
        result=validator.inspect(self.original)
        if type(result) is not TaxValidationResponseInspection or result.schema_sha256!=self.schema_sha256:
            raise ValueError('Tax response inspector returned an unsupported proof.')
        result.verify_original(self.original)
        return result


def decode_tax_delivery_validation_result_observation(raw: str,expected_sha256: str) -> TaxDeliveryValidationResultObservation:
    try:
        if (type(raw) is not str or len(raw.encode('utf-8'))>12*1024*1024+16384
                or _digest(expected_sha256)!=hashlib.sha256(raw.encode('utf-8')).hexdigest()):raise ValueError()
        value=_object(_response_object(raw.encode('utf-8')),('version','observation'))
        if value['version']!='company-tax-delivery-validation-result-observation-v1':raise ValueError()
        body=_object(value['observation'],('filing_id','company_id','income_year','approved_by','approval_sha256',
            'organization_number','instance_id','job_id','start_request_sha256','job_status_evidence_sha256',
            'schema_sha256','original','observed_at'))
        company=_object(body['company_id'],('value',));year=_object(body['income_year'],('value',))
        actor=_object(body['approved_by'],('kind','subject'));subject=_object(actor['subject'],('value',))
        observed=_object(body['observed_at'],('value',))
        result=TaxDeliveryValidationResultObservation(**(body|{'company_id':CompanyId(company['value']),
            'income_year':IncomeYear(year['value']),'approved_by':ActorId(ActorKind(actor['kind']),UserId(subject['value'])),
            'original':_decode_original(body['original']),'observed_at':Timestamp(datetime.fromisoformat(observed['value']))}))
        if result.canonical_json!=raw:raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ValueError('Retained Tax validation result read is invalid or its exact bytes changed.') from None
