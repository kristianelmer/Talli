"""Complete read originals resolving only a known-instance upload outcome.

The original actor can retain an already observed, exact upload result without
discarding it if access changes during the read. Both metadata and file bytes
travel with the completion, so no unrelated historical original is fetched or
disclosed by a late-result writer. Clean scanning is a later prerequisite.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import TYPE_CHECKING

from .delivery import TaxMutationKind
from .delivery_draft import _object
from .delivery_envelope_observation import TaxDeliveryEnvelopeObservation,decode_tax_delivery_envelope_observation
from .delivery_observation import TaxDeliveryInstanceObservation,decode_tax_delivery_observation

if TYPE_CHECKING:
    from .delivery_journal import TaxDeliveryMutationRequest


def _assert_file_read_pair(instance,envelope):
    if type(instance) is not TaxDeliveryInstanceObservation or type(envelope) is not TaxDeliveryEnvelopeObservation:
        raise ValueError('Tax upload reconciliation requires complete read originals.')
    element=instance.inspection.envelope
    if (not instance.inspection.known or element is None or element.data_id!=envelope.data_id
            or element.content_type.split(';',1)[0].strip().lower() not in ('application/xml','text/xml')
            or element.size_bytes!=len(envelope.original.raw_bytes)
            or envelope.observed_at.value<instance.observed_at.value
            or envelope.instance_evidence_sha256!=instance.evidence_sha256
            or any(getattr(instance,name)!=getattr(envelope,name) for name in
                ('filing_id','company_id','income_year','approved_by','approval_sha256','organization_number','instance_id'))):
        raise ValueError('Tax upload reconciliation originals differ in scope or file identity.')


@dataclass(frozen=True,slots=True)
class TaxDeliveryUploadReadEvidence:
    instance: TaxDeliveryInstanceObservation
    envelope: TaxDeliveryEnvelopeObservation

    def __post_init__(self):
        _assert_file_read_pair(self.instance,self.envelope)

    @property
    def canonical_value(self):
        # Retain each independently versioned original once. Never serialize
        # cached inspection fields or rewrite the first canonical original.
        return {'instance_canonical_json':self.instance.canonical_json,'instance_sha256':self.instance.sha256,
            'envelope_canonical_json':self.envelope.canonical_json,'envelope_sha256':self.envelope.sha256}

    @property
    def result(self):
        return {'instanceId':self.instance.instance_id,'dataId':self.envelope.data_id,'envelopeSha256':self.envelope.original.sha256}

    def assert_request(self,request: TaxDeliveryMutationRequest) -> None:
        value=self.instance
        if (request.kind is not TaxMutationKind.UPLOAD_ENVELOPE or request.target_instance!=value.instance_id
                or request.filing_id!=value.filing_id or request.company_id!=value.company_id or request.income_year!=value.income_year
                or request.organization_number!=value.organization_number or request.approval_sha256!=value.approval_sha256
                or hashlib.sha256(request.body_bytes).hexdigest()!=self.envelope.original.sha256):
            raise ValueError('Tax upload read originals do not prove the exact committed upload request.')


def _decode_upload_read_evidence(value):
    value=_object(value,('instance_canonical_json','instance_sha256','envelope_canonical_json','envelope_sha256'))
    return TaxDeliveryUploadReadEvidence(decode_tax_delivery_observation(value['instance_canonical_json'],value['instance_sha256']),
        decode_tax_delivery_envelope_observation(value['envelope_canonical_json'],value['envelope_sha256']))
