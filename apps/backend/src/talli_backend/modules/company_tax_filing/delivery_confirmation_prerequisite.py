"""Fresh known validation and Clean/file originals before entering confirmation.

This value prepares a reviewable confirmation stage. It never records owner
confirmation or authorizes the later transition that submits the filing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from talli_backend.shared.kernel import Timestamp
from .delivery import _digest
from .delivery_draft import _object
from .delivery_original import _response_object
from .delivery_upload_prerequisite import TaxDeliveryReadReference
from .delivery_validation_prerequisite import TaxDeliveryValidationPrerequisite,_decode_validation_prerequisite
from .delivery_validation_job import TaxDeliveryValidationJobObservation,TaxValidationJobStatus
from .delivery_validation_result import TaxDeliveryValidationResultObservation
from .delivery_validation_response import TaxValidationResultCode
from .delivery_calculated_documents import TaxCalculatedDocumentsInspection,_decode_calculated_inspection

CALCULATED_SCHEMA_SHA256='c9631dcb56397a2e9632f9a8339d4060aa8f3ae6f58c7bf35b7cc19df5e77769'
RESPONSE_SCHEMA_SHA256='eaeabcebee3915f31113f026a1d7f854343670c2f45a584691213668d18a71a1'


def _reference(reference,retained,expected_type,finished):
    if (type(retained) is not expected_type or reference.event_sha256!=retained.sha256
            or reference.evidence_sha256!=retained.evidence_sha256 or retained.observed_at.value>finished.value):
        raise ValueError('Tax confirmation reference differs from its first retained original.')


def _fresh_pair(retained,fresh,expected_type):
    if (type(retained) is not expected_type or type(fresh) is not expected_type
            or retained.evidence_sha256!=fresh.evidence_sha256 or retained.original!=fresh.original):
        raise ValueError('Fresh Tax validation differs from its retained original.')
    return TaxDeliveryReadReference(retained.sha256,retained.evidence_sha256,fresh.observed_at)


def assert_process_element(instance,*,task_type,element_id):
    inspection=instance.inspection
    if (not inspection.known or inspection.process_task!=task_type or inspection.archived is not False
            or inspection.archived_at is not None or inspection.process_ended_at is not None):
        raise ValueError('Tax process task is unavailable or no longer active.')
    task=_response_object(instance.original.raw_bytes)['process']['currentTask']
    if (task.get('elementId')!=element_id or type(task.get('flow')) is not int
            or not 1<=task['flow']<=2147483647):
        raise ValueError('Tax process element is not the supported ordinary-company stage.')


def is_tax_delivery_owner_confirmation_instance(instance) -> bool:
    try:assert_process_element(instance,task_type='confirmation',element_id='Task_2')
    except (ValueError,TypeError,KeyError,AttributeError):return False
    return True


@dataclass(frozen=True,slots=True)
class TaxDeliveryConfirmationPrerequisite:
    clean_file: TaxDeliveryValidationPrerequisite
    envelope_sha256: str
    job_read: TaxDeliveryReadReference
    result_read: TaxDeliveryReadReference
    calculated: TaxCalculatedDocumentsInspection
    observed_from: Timestamp
    observed_until: Timestamp

    def __post_init__(self):
        _digest(self.envelope_sha256)
        if (type(self.clean_file) is not TaxDeliveryValidationPrerequisite
                or type(self.job_read) is not TaxDeliveryReadReference or type(self.result_read) is not TaxDeliveryReadReference
                or type(self.calculated) is not TaxCalculatedDocumentsInspection
                or self.calculated.schema_sha256!=CALCULATED_SCHEMA_SHA256
                or self.calculated.response.schema_sha256!=RESPONSE_SCHEMA_SHA256
                or self.calculated.response.result_code is not TaxValidationResultCode.VALIDATED
                or self.calculated.response.validation_deviation_count!=0 or self.calculated.response.failure_reason_count!=0
                or type(self.observed_from) is not Timestamp or type(self.observed_until) is not Timestamp
                or not 0<=(self.observed_until.value-self.observed_from.value).total_seconds()<=30
                or not self.observed_from.value<=self.job_read.observed_at.value<=self.result_read.observed_at.value
                    <=self.clean_file.observed_from.value<=self.clean_file.observed_until.value<=self.observed_until.value):
            raise ValueError('Tax confirmation requires fresh positive validation and exact Clean file originals.')

    @property
    def instance_id(self):return self.clean_file.instance_id

    def assert_current(self,now: Timestamp):
        self.clean_file.assert_current(now)
        if (type(now) is not Timestamp or now.value<self.observed_until.value
                or (now.value-self.observed_from.value).total_seconds()>30):
            raise ValueError('Tax confirmation prerequisite is stale or from the future.')

    def assert_retained(self,approval,draft,request,started,job,result,instance,envelope):
        self.clean_file.assert_retained(approval,draft,instance,envelope)
        assert_process_element(instance,task_type='data',element_id='Task_1')
        _reference(self.job_read,job,TaxDeliveryValidationJobObservation,self.observed_until)
        _reference(self.result_read,result,TaxDeliveryValidationResultObservation,self.observed_until)
        result.assert_status(approval,draft,request,started,job)
        if (request.validation_prerequisite is None or not job.inspection.known
                or job.inspection.status is not TaxValidationJobStatus.FINISHED
                or result.instance_id!=self.instance_id or result.schema_sha256!=RESPONSE_SCHEMA_SHA256):
            raise ValueError('Tax confirmation has no known finished validation of the committed envelope.')
        self.calculated.assert_original(result.original,draft)
        if self.envelope_sha256!=draft.envelope.envelope_sha256:
            raise ValueError('Tax confirmation does not bind the exact approved upload bytes.')


def bind_tax_delivery_confirmation_prerequisite(approval,draft,request,started,*,
        retained_job,retained_result,fresh_job,fresh_result,calculated,
        clean_file,retained_instance,retained_envelope,observed_from,observed_until):
    fresh_job.assert_started(approval,draft,request,started)
    fresh_result.assert_status(approval,draft,request,started,fresh_job)
    value=TaxDeliveryConfirmationPrerequisite(clean_file,draft.envelope.envelope_sha256,
        _fresh_pair(retained_job,fresh_job,TaxDeliveryValidationJobObservation),
        _fresh_pair(retained_result,fresh_result,TaxDeliveryValidationResultObservation),
        calculated,observed_from,observed_until)
    value.assert_retained(approval,draft,request,started,retained_job,retained_result,retained_instance,retained_envelope)
    value.assert_current(observed_until)
    return value


def _decode_confirmation_prerequisite(value):
    value=_object(value,('clean_file','envelope_sha256','job_read','result_read','calculated','observed_from','observed_until'))
    def reference(value):
        value=_object(value,('event_sha256','evidence_sha256','observed_at'))
        observed=_object(value['observed_at'],('value',))
        return TaxDeliveryReadReference(value['event_sha256'],value['evidence_sha256'],Timestamp(datetime.fromisoformat(observed['value'])))
    times={key:Timestamp(datetime.fromisoformat(_object(value[key],('value',))['value'])) for key in ('observed_from','observed_until')}
    return TaxDeliveryConfirmationPrerequisite(_decode_validation_prerequisite(value['clean_file']),value['envelope_sha256'],
        reference(value['job_read']),reference(value['result_read']),_decode_calculated_inspection(value['calculated']),**times)
