"""Fresh Clean metadata and exact approved file proof before validation start."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from talli_backend.shared.kernel import Timestamp
from .delivery_approval import TaxDeliveryReviewApproval
from .delivery_draft import TaxDeliveryDraft,_object
from .delivery_envelope_observation import TaxDeliveryEnvelopeObservation
from .delivery_observation import TaxDeliveryInstanceObservation
from .delivery_original import _instance,_uuid
from .delivery_upload_prerequisite import TaxDeliveryReadReference


@dataclass(frozen=True,slots=True)
class TaxDeliveryValidationPrerequisite:
    instance_id: str
    data_id: str
    instance_read: TaxDeliveryReadReference
    envelope_read: TaxDeliveryReadReference
    observed_from: Timestamp
    observed_until: Timestamp

    def __post_init__(self):
        _instance(self.instance_id);_uuid(self.data_id)
        if (type(self.instance_read) is not TaxDeliveryReadReference or type(self.envelope_read) is not TaxDeliveryReadReference
                or type(self.observed_from) is not Timestamp or type(self.observed_until) is not Timestamp
                or not 0<=(self.observed_until.value-self.observed_from.value).total_seconds()<=30
                or not self.observed_from.value<=self.instance_read.observed_at.value
                    <=self.envelope_read.observed_at.value<=self.observed_until.value):
            raise ValueError('Tax validation requires a bounded fresh metadata/file read pair.')

    def assert_current(self,now: Timestamp) -> None:
        if (type(now) is not Timestamp or now.value<self.observed_until.value
                or (now.value-self.observed_from.value).total_seconds()>30):
            raise ValueError('Tax validation prerequisite is stale or from the future.')

    def assert_retained(self,approval: TaxDeliveryReviewApproval,draft: TaxDeliveryDraft,
            instance: TaxDeliveryInstanceObservation,envelope: TaxDeliveryEnvelopeObservation) -> None:
        self.instance_read.assert_retained_instance(instance)
        if (type(envelope) is not TaxDeliveryEnvelopeObservation
                or self.envelope_read.event_sha256!=envelope.sha256
                or self.envelope_read.evidence_sha256!=envelope.evidence_sha256
                or instance.observed_at.value>self.observed_until.value or envelope.observed_at.value>self.observed_until.value
                or self.instance_id!=instance.instance_id or self.data_id!=envelope.data_id):
            raise ValueError('Tax validation read references differ from retained originals.')
        inspection=instance.inspection
        if (not envelope.has_clean_approved_envelope(approval,draft,instance)
                or inspection.process_task!='data' or inspection.archived is not False
                or inspection.archived_at is not None or inspection.process_ended_at is not None
                or len(inspection.data)!=1):
            raise ValueError('Tax validation requires only the reviewed Clean envelope in an active data task.')


def bind_tax_delivery_validation_prerequisite(approval: TaxDeliveryReviewApproval,draft: TaxDeliveryDraft,
        *,retained_instance: TaxDeliveryInstanceObservation,retained_envelope: TaxDeliveryEnvelopeObservation,
        fresh_instance: TaxDeliveryInstanceObservation,fresh_envelope: TaxDeliveryEnvelopeObservation,
        observed_from: Timestamp,observed_until: Timestamp) -> TaxDeliveryValidationPrerequisite:
    for retained,fresh,expected in ((retained_instance,fresh_instance,TaxDeliveryInstanceObservation),
            (retained_envelope,fresh_envelope,TaxDeliveryEnvelopeObservation)):
        if (type(retained) is not expected or type(fresh) is not expected
                or retained.evidence_sha256!=fresh.evidence_sha256 or retained.original!=fresh.original):
            raise ValueError('Fresh Tax validation read differs from its retained original.')
    if not fresh_envelope.has_clean_approved_envelope(approval,draft,fresh_instance):
        raise ValueError('Fresh Tax metadata and approved file are not Clean.')
    value=TaxDeliveryValidationPrerequisite(fresh_instance.instance_id,fresh_envelope.data_id,
        TaxDeliveryReadReference(retained_instance.sha256,retained_instance.evidence_sha256,fresh_instance.observed_at),
        TaxDeliveryReadReference(retained_envelope.sha256,retained_envelope.evidence_sha256,fresh_envelope.observed_at),
        observed_from,observed_until)
    value.assert_retained(approval,draft,retained_instance,retained_envelope)
    value.assert_current(observed_until)
    return value


def _decode_validation_prerequisite(value):
    value=_object(value,('instance_id','data_id','instance_read','envelope_read','observed_from','observed_until'))
    def reference(raw):
        raw=_object(raw,('event_sha256','evidence_sha256','observed_at'))
        observed=_object(raw['observed_at'],('value',))
        return TaxDeliveryReadReference(raw['event_sha256'],raw['evidence_sha256'],Timestamp(datetime.fromisoformat(observed['value'])))
    start=_object(value['observed_from'],('value',));end=_object(value['observed_until'],('value',))
    return TaxDeliveryValidationPrerequisite(value['instance_id'],value['data_id'],reference(value['instance_read']),
        reference(value['envelope_read']),Timestamp(datetime.fromisoformat(start['value'])),Timestamp(datetime.fromisoformat(end['value'])))
