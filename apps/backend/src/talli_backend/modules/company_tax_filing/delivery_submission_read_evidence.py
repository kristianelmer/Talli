"""Known ordinary feedback stage or terminal instance plus exact receipt bytes."""
from __future__ import annotations

from dataclasses import dataclass

from .delivery import TaxMutationKind
from .delivery_draft import _object
from .delivery_upload_read_evidence import _assert_file_read_pair
from .delivery_confirmation_prerequisite import assert_process_element
from .delivery_observation import TaxDeliveryInstanceObservation,decode_tax_delivery_observation
from .delivery_envelope_observation import TaxDeliveryEnvelopeObservation,decode_tax_delivery_envelope_observation
from .delivery_feedback_observation import TaxDeliveryFeedbackObservation,decode_tax_delivery_feedback_observation


def is_tax_delivery_submitted_instance(instance):
    try:assert_process_element(instance,task_type='feedback',element_id='Task_3')
    except (ValueError,TypeError,KeyError,AttributeError):return False
    return True


@dataclass(frozen=True,slots=True)
class TaxDeliverySubmissionReadEvidence:
    instance: TaxDeliveryInstanceObservation
    envelope: TaxDeliveryEnvelopeObservation
    feedback: TaxDeliveryFeedbackObservation | None=None

    def __post_init__(self):
        _assert_file_read_pair(self.instance,self.envelope)
        inspection=self.instance.inspection
        if (inspection.envelope.scan_result!='Clean'
                or any(row.data_type not in ('skattemeldingOgNaeringsspesifikasjon','tilbakemelding') for row in inspection.data)):
            raise ValueError('Tax submission metadata has unknown data or its approved file is not Clean.')
        if self.feedback is not None:
            if type(self.feedback) is not TaxDeliveryFeedbackObservation:raise ValueError('Tax receipt is not a complete known original.')
            # Bind all complete originals without needing an unrelated draft read.
            self.feedback.assert_metadata(self.instance)
            if inspection.feedback.scan_result!='Clean':raise ValueError('Tax submission receipt scanning is not Clean.')
        if is_tax_delivery_submitted_instance(self.instance):return
        if (self.feedback is None or inspection.process_task is not None or inspection.process_ended_at is None
                or inspection.archived is not True or inspection.archived_at is None
                or inspection.archived_at.value<inspection.process_ended_at.value
                or inspection.archived_at.value>self.instance.observed_at.value):
            raise ValueError('Tax submission needs ordinary feedback or terminal archived scope with an exact known receipt.')

    @property
    def canonical_value(self):
        return {'instance_canonical_json':self.instance.canonical_json,'instance_sha256':self.instance.sha256,
            'envelope_canonical_json':self.envelope.canonical_json,'envelope_sha256':self.envelope.sha256,
            'feedback_canonical_json':None if self.feedback is None else self.feedback.canonical_json,
            'feedback_sha256':None if self.feedback is None else self.feedback.sha256}

    @property
    def result(self):return {'instanceId':self.instance.instance_id,'processTask':'feedback'}

    def assert_request(self,request):
        proof=request.submission_prerequisite;instance=self.instance
        if (request.kind is not TaxMutationKind.CONFIRM_SUBMISSION or proof is None
                or request.target_instance!=instance.instance_id or request.filing_id!=instance.filing_id
                or request.company_id!=instance.company_id or request.income_year!=instance.income_year
                or request.approval_sha256!=instance.approval_sha256 or request.organization_number!=instance.organization_number
                or proof.data_id!=self.envelope.data_id or proof.envelope_sha256!=self.envelope.original.sha256):
            raise ValueError('Tax submission read differs from its exact owner-confirmed committed intent.')


def _decode_submission_read_evidence(value):
    value=_object(value,('instance_canonical_json','instance_sha256','envelope_canonical_json','envelope_sha256',
        'feedback_canonical_json','feedback_sha256'))
    if (value['feedback_canonical_json'] is None)!=(value['feedback_sha256'] is None):raise ValueError('Tax receipt original is incomplete.')
    feedback=None if value['feedback_canonical_json'] is None else decode_tax_delivery_feedback_observation(
        value['feedback_canonical_json'],value['feedback_sha256'])
    return TaxDeliverySubmissionReadEvidence(decode_tax_delivery_observation(value['instance_canonical_json'],value['instance_sha256']),
        decode_tax_delivery_envelope_observation(value['envelope_canonical_json'],value['envelope_sha256']),feedback)
