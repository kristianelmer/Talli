"""Fresh known validation and exact ordinary confirmation-stage file proof."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from talli_backend.shared.kernel import Timestamp
from .delivery import _digest
from .delivery_draft import _object
from .delivery_owner_confirmation import TaxDeliveryOwnerConfirmation,_decode_owner_confirmation
from .delivery_upload_prerequisite import TaxDeliveryReadReference
from .delivery_confirmation_prerequisite import _reference,_fresh_pair,RESPONSE_SCHEMA_SHA256
from .delivery_confirmation_read_evidence import TaxDeliveryConfirmationReadEvidence
from .delivery_observation import TaxDeliveryInstanceObservation
from .delivery_envelope_observation import TaxDeliveryEnvelopeObservation
from .delivery_validation_job import TaxDeliveryValidationJobObservation,TaxValidationJobStatus
from .delivery_validation_result import TaxDeliveryValidationResultObservation


@dataclass(frozen=True,slots=True)
class TaxDeliverySubmissionPrerequisite:
    owner_confirmation: TaxDeliveryOwnerConfirmation
    instance_id: str
    data_id: str
    envelope_sha256: str
    job_read: TaxDeliveryReadReference
    result_read: TaxDeliveryReadReference
    instance_read: TaxDeliveryReadReference
    envelope_read: TaxDeliveryReadReference
    observed_from: Timestamp
    observed_until: Timestamp

    def __post_init__(self):
        from .delivery_original import _instance,_uuid
        _instance(self.instance_id);_uuid(self.data_id);_digest(self.envelope_sha256)
        references=(self.job_read,self.result_read,self.instance_read,self.envelope_read)
        if (type(self.owner_confirmation) is not TaxDeliveryOwnerConfirmation
                or any(type(value) is not TaxDeliveryReadReference for value in references)
                or type(self.observed_from) is not Timestamp or type(self.observed_until) is not Timestamp
                or not 0<=(self.observed_until.value-self.observed_from.value).total_seconds()<=30):
            raise ValueError('Tax submission requires explicit owner confirmation and bounded fresh reads.')
        times=[self.observed_from.value,*[value.observed_at.value for value in references],self.observed_until.value]
        if times!=sorted(times):raise ValueError('Tax submission reads are out of order.')

    def assert_current(self,now: Timestamp):
        if (type(now) is not Timestamp or now.value<self.observed_until.value
                or (now.value-self.observed_from.value).total_seconds()>30):
            raise ValueError('Tax submission prerequisite is stale or from the future.')

    def assert_retained(self,approval,draft,preparation,prepared,start,started,job,result,instance,envelope):
        self.owner_confirmation.assert_preparation(approval,draft,preparation,prepared)
        for ref,retained,expected in ((self.job_read,job,TaxDeliveryValidationJobObservation),
                (self.result_read,result,TaxDeliveryValidationResultObservation),
                (self.instance_read,instance,TaxDeliveryInstanceObservation),
                (self.envelope_read,envelope,TaxDeliveryEnvelopeObservation)):
            _reference(ref,retained,expected,self.observed_until)
            if retained.observed_at.value>ref.observed_at.value:
                raise ValueError('Tax submission fresh reference predates its first retained original.')
        job.assert_started(approval,draft,start,started);result.assert_status(approval,draft,start,started,job)
        instance.assert_approval(approval,draft,self.instance_id)
        envelope.assert_instance(approval,draft,instance)
        TaxDeliveryConfirmationReadEvidence(instance,envelope)
        if (not job.inspection.known or job.inspection.status is not TaxValidationJobStatus.FINISHED
                or result.schema_sha256!=RESPONSE_SCHEMA_SHA256
                or result.original.sha256!=self.owner_confirmation.response_original_sha256
                or result.instance_id!=self.instance_id or envelope.data_id!=self.data_id
                or not envelope.has_clean_approved_envelope(approval,draft,instance)
                or self.envelope_sha256!=draft.envelope.envelope_sha256
                or self.observed_from.value<prepared.observed_at.value):
            raise ValueError('Tax submission differs from the owner-reviewed validation or exact prepared Clean file.')


def bind_tax_delivery_submission_prerequisite(approval,draft,preparation,prepared,start,started,*,owner_confirmation,
        retained_job,retained_result,retained_instance,retained_envelope,
        fresh_job,fresh_result,fresh_instance,fresh_envelope,observed_from,observed_until):
    values=[_fresh_pair(retained,fresh,expected) for retained,fresh,expected in (
        (retained_job,fresh_job,TaxDeliveryValidationJobObservation),
        (retained_result,fresh_result,TaxDeliveryValidationResultObservation),
        (retained_instance,fresh_instance,TaxDeliveryInstanceObservation),
        (retained_envelope,fresh_envelope,TaxDeliveryEnvelopeObservation))]
    value=TaxDeliverySubmissionPrerequisite(owner_confirmation,fresh_instance.instance_id,fresh_envelope.data_id,
        draft.envelope.envelope_sha256,*values,observed_from,observed_until)
    value.assert_retained(approval,draft,preparation,prepared,start,started,retained_job,retained_result,retained_instance,retained_envelope)
    value.assert_current(observed_until)
    return value


def _decode_submission_prerequisite(value):
    value=_object(value,('owner_confirmation','instance_id','data_id','envelope_sha256','job_read','result_read',
        'instance_read','envelope_read','observed_from','observed_until'))
    def reference(value):
        value=_object(value,('event_sha256','evidence_sha256','observed_at'))
        observed=_object(value['observed_at'],('value',))
        return TaxDeliveryReadReference(value['event_sha256'],value['evidence_sha256'],Timestamp(datetime.fromisoformat(observed['value'])))
    values={key:reference(value[key]) for key in ('job_read','result_read','instance_read','envelope_read')}
    times={key:Timestamp(datetime.fromisoformat(_object(value[key],('value',))['value'])) for key in ('observed_from','observed_until')}
    return TaxDeliverySubmissionPrerequisite(_decode_owner_confirmation(value['owner_confirmation']),value['instance_id'],
        value['data_id'],value['envelope_sha256'],**values,**times)
