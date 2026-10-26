"""Exact known-instance receipt bytes, with authority outcome unclassified.

No published final-receipt XSD/outcome contract is assumed from the distinct
validation response schema. Original bytes remain available even when opaque.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import re

from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IncomeYear,Timestamp,UserId
from .delivery import _digest,_json,tax_delivery_digest
from .delivery_draft import _canonical,_object
from .delivery_original import _instance,_uuid,_response_object
from .delivery_observation import TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose,TaxDeliveryInstanceObservation,_scope,_decode_original


@dataclass(frozen=True,slots=True)
class TaxDeliveryFeedbackObservation:
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
                or type(self.original) is not TaxDeliveryReadOriginal or self.original.purpose is not TaxDeliveryOriginalPurpose.FEEDBACK
                or type(self.observed_at) is not Timestamp):raise ValueError('Tax feedback original binding is invalid.')

    @property
    def canonical_json(self):
        return _canonical({'version':'company-tax-delivery-feedback-observation-v1','observation':_json(self)})

    @property
    def sha256(self):return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()

    @property
    def evidence_sha256(self):
        return tax_delivery_digest(['tax-feedback-read-identity-v1',self.filing_id,str(self.company_id),int(self.income_year),
            str(self.approved_by.subject),self.approval_sha256,self.organization_number,self.instance_id,
            self.data_id,self.instance_evidence_sha256,self.original.sha256])

    def assert_instance(self,approval,draft,instance):
        if type(instance) is not TaxDeliveryInstanceObservation:raise ValueError('Tax feedback has no known metadata original.')
        instance.assert_approval(approval,draft,self.instance_id)
        self.assert_metadata(instance)

    def assert_metadata(self,instance):
        if type(instance) is not TaxDeliveryInstanceObservation:raise ValueError('Tax feedback has no known metadata original.')
        element=instance.inspection.feedback
        if (not instance.inspection.known or element is None or element.data_id!=self.data_id
                or element.content_type.split(';',1)[0].strip().lower() not in ('application/xml','text/xml')
                or element.size_bytes!=len(self.original.raw_bytes)
                or self.instance_evidence_sha256!=instance.evidence_sha256
                or self.observed_at.value<instance.observed_at.value
                or any(getattr(self,name)!=getattr(instance,name) for name in
                    ('filing_id','company_id','income_year','approved_by','approval_sha256','organization_number','instance_id'))):
            raise ValueError('Tax feedback bytes differ from their exact known metadata and scope.')


def decode_tax_delivery_feedback_observation(raw,expected_sha256):
    try:
        if (type(raw) is not str or len(raw.encode('utf-8'))>12*1024*1024+16384
                or _digest(expected_sha256)!=hashlib.sha256(raw.encode('utf-8')).hexdigest()):raise ValueError()
        value=_object(_response_object(raw.encode('utf-8')),('version','observation'))
        if value['version']!='company-tax-delivery-feedback-observation-v1':raise ValueError()
        body=_object(value['observation'],('filing_id','company_id','income_year','approved_by','approval_sha256',
            'organization_number','instance_id','data_id','instance_evidence_sha256','original','observed_at'))
        company=_object(body['company_id'],('value',));year=_object(body['income_year'],('value',))
        actor=_object(body['approved_by'],('kind','subject'));subject=_object(actor['subject'],('value',))
        observed=_object(body['observed_at'],('value',))
        result=TaxDeliveryFeedbackObservation(**(body|{'company_id':CompanyId(company['value']),
            'income_year':IncomeYear(year['value']),'approved_by':ActorId(ActorKind(actor['kind']),UserId(subject['value'])),
            'original':_decode_original(body['original']),'observed_at':Timestamp(datetime.fromisoformat(observed['value']))}))
        if result.canonical_json!=raw:raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ValueError('Retained Tax feedback original is invalid or its exact bytes changed.') from None
