"""Complete known-instance read originals proving only entry to confirmation."""
from __future__ import annotations

from dataclasses import dataclass

from .delivery import TaxMutationKind
from .delivery_draft import _object
from .delivery_observation import TaxDeliveryInstanceObservation,decode_tax_delivery_observation
from .delivery_envelope_observation import TaxDeliveryEnvelopeObservation,decode_tax_delivery_envelope_observation
from .delivery_confirmation_prerequisite import assert_process_element
from .delivery_upload_read_evidence import _assert_file_read_pair


@dataclass(frozen=True,slots=True)
class TaxDeliveryConfirmationReadEvidence:
    instance: TaxDeliveryInstanceObservation
    envelope: TaxDeliveryEnvelopeObservation

    def __post_init__(self):
        _assert_file_read_pair(self.instance,self.envelope)
        assert_process_element(self.instance,task_type='confirmation',element_id='Task_2')
        if len(self.instance.inspection.data)!=1 or self.instance.inspection.envelope.scan_result!='Clean':
            raise ValueError('Tax confirmation read has unreviewed data or scanning is not Clean.')

    @property
    def canonical_value(self):
        return {'instance_canonical_json':self.instance.canonical_json,'instance_sha256':self.instance.sha256,
            'envelope_canonical_json':self.envelope.canonical_json,'envelope_sha256':self.envelope.sha256}

    @property
    def result(self):return {'instanceId':self.instance.instance_id,'processTask':'confirmation'}

    def assert_request(self,request):
        proof=request.confirmation_prerequisite;instance=self.instance
        if (request.kind is not TaxMutationKind.PREPARE_CONFIRMATION or proof is None
                or request.target_instance!=instance.instance_id or request.filing_id!=instance.filing_id
                or request.company_id!=instance.company_id or request.income_year!=instance.income_year
                or request.approval_sha256!=instance.approval_sha256 or request.organization_number!=instance.organization_number
                or proof.clean_file.data_id!=self.envelope.data_id or proof.envelope_sha256!=self.envelope.original.sha256):
            raise ValueError('Tax confirmation read does not prove the exact committed preparation.')


def _decode_confirmation_read_evidence(value):
    value=_object(value,('instance_canonical_json','instance_sha256','envelope_canonical_json','envelope_sha256'))
    return TaxDeliveryConfirmationReadEvidence(decode_tax_delivery_observation(value['instance_canonical_json'],value['instance_sha256']),
        decode_tax_delivery_envelope_observation(value['envelope_canonical_json'],value['envelope_sha256']))
