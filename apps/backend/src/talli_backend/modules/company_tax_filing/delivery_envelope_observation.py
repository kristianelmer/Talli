"""Exact known-instance envelope reads; scan and byte equality stay distinct.

An upload acknowledgement alone does not establish that a retained remote file
is the approved envelope or that its virus scan is clean. This value retains
the file original and binds the metadata read that supplied its exact data ID.
It authorizes no mutation and clears no uncertain journal slot by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import re

from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IncomeYear,Timestamp,UserId
from .delivery import _digest,_json,tax_delivery_digest
from .delivery_approval import TaxDeliveryReviewApproval
from .delivery_draft import TaxDeliveryDraft,_canonical,_object
from .delivery_original import _instance,_response_object,_uuid
from .delivery_observation import (
    TaxDeliveryInstanceObservation,TaxDeliveryOriginalPurpose,TaxDeliveryReadOriginal,_decode_original,_scope,
)


@dataclass(frozen=True,slots=True)
class TaxDeliveryEnvelopeObservation:
    filing_id: str
    company_id: CompanyId
    income_year: IncomeYear
    approved_by: ActorId
    approval_sha256: str
    organization_number: str
    instance_id: str
    data_id: str
    instance_evidence_sha256: str
    original: TaxDeliveryReadOriginal
    observed_at: Timestamp

    def __post_init__(self):
        _scope(self);_instance(self.instance_id);_uuid(self.data_id);_digest(self.instance_evidence_sha256)
        if (type(self.organization_number) is not str or re.fullmatch('[0-9]{9}',self.organization_number) is None
                or type(self.original) is not TaxDeliveryReadOriginal or self.original.purpose is not TaxDeliveryOriginalPurpose.ENVELOPE
                or type(self.observed_at) is not Timestamp):
            raise ValueError('Tax envelope observation is invalid.')

    @property
    def canonical_json(self) -> str:
        return _canonical({'version':'company-tax-delivery-envelope-observation-v1','observation':_json(self)})

    @property
    def sha256(self) -> str:return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()

    @property
    def evidence_sha256(self) -> str:
        return tax_delivery_digest(['tax-envelope-read-identity-v1',self.filing_id,str(self.company_id),
            int(self.income_year),str(self.approved_by.subject),self.approval_sha256,self.organization_number,
            self.instance_id,self.data_id,self.instance_evidence_sha256,self.original.sha256])

    def assert_instance(self,approval: TaxDeliveryReviewApproval,draft: TaxDeliveryDraft,
                        instance: TaxDeliveryInstanceObservation) -> None:
        if type(instance) is not TaxDeliveryInstanceObservation:raise ValueError('Tax envelope has no instance read.')
        instance.assert_approval(approval,draft,self.instance_id)
        element=instance.inspection.envelope
        if (not instance.inspection.known or element is None or element.data_id!=self.data_id
                or self.filing_id!=instance.filing_id or self.company_id!=instance.company_id
                or self.income_year!=instance.income_year or self.approved_by!=instance.approved_by
                or self.approval_sha256!=instance.approval_sha256 or self.organization_number!=instance.organization_number
                or self.instance_evidence_sha256!=instance.evidence_sha256 or self.observed_at.value<instance.observed_at.value):
            raise ValueError('Tax envelope read differs from its retained instance metadata.')

    def matches_approved_bytes(self,approval: TaxDeliveryReviewApproval,draft: TaxDeliveryDraft,
                               instance: TaxDeliveryInstanceObservation) -> bool:
        self.assert_instance(approval,draft,instance)
        element=instance.inspection.envelope
        return (element.content_type.split(';',1)[0].strip().lower() in ('application/xml','text/xml')
            and element.size_bytes==len(self.original.raw_bytes)
            and self.original.sha256==draft.envelope.envelope_sha256)

    def has_clean_approved_envelope(self,approval: TaxDeliveryReviewApproval,draft: TaxDeliveryDraft,
                                   instance: TaxDeliveryInstanceObservation) -> bool:
        return (self.matches_approved_bytes(approval,draft,instance)
            and instance.inspection.envelope.scan_result=='Clean')


def decode_tax_delivery_envelope_observation(raw: str,expected_sha256: str) -> TaxDeliveryEnvelopeObservation:
    try:
        if (type(raw) is not str or len(raw.encode('utf-8'))>12*1024*1024+16384
                or _digest(expected_sha256)!=hashlib.sha256(raw.encode('utf-8')).hexdigest()):raise ValueError()
        value=_object(_response_object(raw.encode('utf-8')),('version','observation'))
        if value['version']!='company-tax-delivery-envelope-observation-v1':raise ValueError()
        body=_object(value['observation'],('filing_id','company_id','income_year','approved_by','approval_sha256',
            'organization_number','instance_id','data_id','instance_evidence_sha256','original','observed_at'))
        company=_object(body['company_id'],('value',));year=_object(body['income_year'],('value',))
        actor=_object(body['approved_by'],('kind','subject'));subject=_object(actor['subject'],('value',))
        observed=_object(body['observed_at'],('value',))
        result=TaxDeliveryEnvelopeObservation(**(body|{'company_id':CompanyId(company['value']),
            'income_year':IncomeYear(year['value']),'approved_by':ActorId(ActorKind(actor['kind']),UserId(subject['value'])),
            'original':_decode_original(body['original']),'observed_at':Timestamp(datetime.fromisoformat(observed['value']))}))
        if result.canonical_json!=raw:raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ValueError('Retained Tax envelope read is invalid or its exact bytes changed.') from None
