"""Exact status originals for one already-known validation job; no lookup/reset."""
from __future__ import annotations

from dataclasses import dataclass,field
from datetime import datetime
from enum import StrEnum
import hashlib
import re

from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IncomeYear,Timestamp,UserId
from .delivery import _digest,_json,tax_delivery_digest,TaxMutationKind
from .delivery_draft import _canonical,_object
from .delivery_observation import TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose,_scope,_decode_original
from .delivery_original import _instance,_job,_response_object


class TaxValidationJobStatus(StrEnum):
    CREATED='OPPRETTET'
    NEW='NY'
    RUNNING='KJOERER'
    WAITING='VENTER'
    ABORTED='AVBRUTT'
    FAILED='FEILET'
    FINISHED='FERDIG'


@dataclass(frozen=True,slots=True)
class TaxValidationJobInspection:
    status: TaxValidationJobStatus | None
    previous_status: TaxValidationJobStatus | None
    seconds_since_creation: int | None
    seconds_since_change: int | None
    error_code: str | None=None

    @property
    def known(self):return self.error_code is None


class _ForeignJob(ValueError):pass


def _inspect(raw,job_id):
    try:
        value=_response_object(raw)
        if 'jobbId' in value:
            identity=_job(value['jobbId'])
            if identity!=job_id:raise _ForeignJob()
        status=TaxValidationJobStatus(value['jobbStatus'])
        if status is TaxValidationJobStatus.CREATED:raise ValueError()
        previous=value['forrigeStatus']
        if previous is not None:previous=TaxValidationJobStatus(previous)
        age=value['sekunderSidenOpprettelse'];changed=value['sekunderSidenEndring']
        if type(age) is not int or type(changed) is not int or not 0<=changed<=age<=2147483647:raise ValueError()
        return TaxValidationJobInspection(status,previous,age,changed)
    except _ForeignJob:
        raise ValueError('Authority returned a different Tax validation job.') from None
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        return TaxValidationJobInspection(None,None,None,None,'validation_job_response_unavailable')


@dataclass(frozen=True,slots=True)
class TaxDeliveryValidationJobObservation:
    filing_id: str
    company_id: CompanyId
    income_year: IncomeYear
    approved_by: ActorId
    approval_sha256: str
    organization_number: str
    instance_id: str
    job_id: str
    start_request_sha256: str
    original: TaxDeliveryReadOriginal
    observed_at: Timestamp
    _inspection: TaxValidationJobInspection=field(init=False,repr=False,compare=False)

    def __post_init__(self):
        _scope(self);_instance(self.instance_id);_job(self.job_id);_digest(self.start_request_sha256)
        if (type(self.organization_number) is not str or re.fullmatch('[0-9]{9}',self.organization_number) is None
                or type(self.original) is not TaxDeliveryReadOriginal or self.original.purpose is not TaxDeliveryOriginalPurpose.VALIDATION_JOB
                or type(self.observed_at) is not Timestamp):raise ValueError('Tax validation job observation is invalid.')
        object.__setattr__(self,'_inspection',_inspect(self.original.raw_bytes,self.job_id))

    @property
    def inspection(self) -> TaxValidationJobInspection:return self._inspection

    @property
    def canonical_json(self):
        value={name:getattr(self,name) for name in ('filing_id','company_id','income_year','approved_by','approval_sha256',
            'organization_number','instance_id','job_id','start_request_sha256','original','observed_at')}
        return _canonical({'version':'company-tax-delivery-validation-job-observation-v1','observation':_json(value)})

    @property
    def sha256(self):return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()

    @property
    def evidence_sha256(self):
        return tax_delivery_digest(['tax-validation-job-read-identity-v1',self.filing_id,str(self.company_id),int(self.income_year),
            str(self.approved_by.subject),self.approval_sha256,self.organization_number,self.instance_id,self.job_id,
            self.start_request_sha256,self.original.sha256])

    def assert_started(self,approval,draft,request,started) -> None:
        from .delivery_journal import TaxDeliveryMutationRequest,TaxDeliveryMutationCompletion
        if (type(request) is not TaxDeliveryMutationRequest or type(started) is not TaxDeliveryMutationCompletion
                or request.kind is not TaxMutationKind.START_VALIDATION):raise ValueError('Tax job has no known committed start.')
        request.assert_draft(approval,draft);started.assert_request(request,approval)
        if (self.filing_id!=draft.filing_id or self.company_id!=approval.company_id or self.income_year!=approval.income_year
                or self.approved_by!=approval.approved_by or self.approval_sha256!=approval.sha256
                or self.organization_number!=draft.envelope.source.organization_number
                or self.instance_id!=started.result['instanceId'] or self.job_id!=started.result['jobId']
                or self.start_request_sha256!=request.sha256 or self.observed_at.value<started.observed_at.value):
            raise ValueError('Tax job status differs from its retained start result.')


def decode_tax_delivery_validation_job_observation(raw: str,expected_sha256: str) -> TaxDeliveryValidationJobObservation:
    try:
        if (type(raw) is not str or len(raw.encode('utf-8'))>12*1024*1024+16384
                or _digest(expected_sha256)!=hashlib.sha256(raw.encode('utf-8')).hexdigest()):raise ValueError()
        value=_object(_response_object(raw.encode('utf-8')),('version','observation'))
        if value['version']!='company-tax-delivery-validation-job-observation-v1':raise ValueError()
        body=_object(value['observation'],('filing_id','company_id','income_year','approved_by','approval_sha256',
            'organization_number','instance_id','job_id','start_request_sha256','original','observed_at'))
        company=_object(body['company_id'],('value',));year=_object(body['income_year'],('value',))
        actor=_object(body['approved_by'],('kind','subject'));subject=_object(actor['subject'],('value',))
        observed=_object(body['observed_at'],('value',))
        result=TaxDeliveryValidationJobObservation(**(body|{'company_id':CompanyId(company['value']),
            'income_year':IncomeYear(year['value']),'approved_by':ActorId(ActorKind(actor['kind']),UserId(subject['value'])),
            'original':_decode_original(body['original']),'observed_at':Timestamp(datetime.fromisoformat(observed['value']))}))
        if result.canonical_json!=raw:raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ValueError('Retained Tax validation job read is invalid or its exact bytes changed.') from None
