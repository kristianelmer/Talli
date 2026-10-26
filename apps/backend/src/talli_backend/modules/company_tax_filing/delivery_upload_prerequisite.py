"""A fresh backend-observed empty instance prerequisite for one upload intent.

The first retained original remains immutable across identical polls. Its local
read time is therefore separate from the fresh read attested by a new intent.
No client may supply this value, and it does not elect an upload without the
application's current source/access guards and committed submit-once journal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from talli_backend.shared.kernel import Timestamp
from .delivery import _digest
from .delivery_approval import TaxDeliveryReviewApproval
from .delivery_draft import TaxDeliveryDraft,_object
from .delivery_original import _instance
from .delivery_observation import TaxDeliveryInstanceObservation


@dataclass(frozen=True,slots=True)
class TaxDeliveryReadReference:
    event_sha256: str
    evidence_sha256: str
    observed_at: Timestamp

    def __post_init__(self):
        _digest(self.event_sha256);_digest(self.evidence_sha256)
        if type(self.observed_at) is not Timestamp:raise ValueError('Tax read reference time is invalid.')

    def assert_retained_instance(self,instance: TaxDeliveryInstanceObservation) -> None:
        if (type(instance) is not TaxDeliveryInstanceObservation or self.event_sha256!=instance.sha256
                or self.evidence_sha256!=instance.evidence_sha256):
            raise ValueError('Tax read reference differs from its first retained original.')


@dataclass(frozen=True,slots=True)
class TaxDeliveryUploadPrerequisite:
    instance_id: str
    instance_read: TaxDeliveryReadReference
    observed_from: Timestamp
    observed_until: Timestamp

    def __post_init__(self):
        _instance(self.instance_id)
        if (type(self.instance_read) is not TaxDeliveryReadReference
                or type(self.observed_from) is not Timestamp or type(self.observed_until) is not Timestamp
                or not 0<=(self.observed_until.value-self.observed_from.value).total_seconds()<=30
                or not self.observed_from.value<=self.instance_read.observed_at.value<=self.observed_until.value):
            raise ValueError('Tax upload prerequisite is not a bounded fresh read.')

    def assert_retained(self,approval: TaxDeliveryReviewApproval,draft: TaxDeliveryDraft,
                        instance: TaxDeliveryInstanceObservation) -> None:
        self.instance_read.assert_retained_instance(instance)
        # Concurrent identical reads can reach storage in the opposite order.
        # The stored original must already exist when this proof finishes; its
        # read timestamp need not precede this caller's own fresh read.
        if instance.observed_at.value>self.observed_until.value:
            raise ValueError('Tax retained original postdates the finished proof.')
        instance.assert_approval(approval,draft,self.instance_id)
        inspection=instance.inspection
        if (not inspection.empty_data or inspection.process_task!='data' or inspection.archived is not False
                or inspection.archived_at is not None or inspection.process_ended_at is not None):
            raise ValueError('Tax upload requires a positively empty active data task.')

    def assert_current(self,now: Timestamp) -> None:
        if (type(now) is not Timestamp or not self.observed_until.value<=now.value
                or (now.value-self.observed_from.value).total_seconds()>30):
            raise ValueError('Tax upload prerequisite is stale or from the future.')


def bind_tax_delivery_upload_prerequisite(approval: TaxDeliveryReviewApproval,draft: TaxDeliveryDraft,
        *,retained: TaxDeliveryInstanceObservation,fresh: TaxDeliveryInstanceObservation,
        observed_from: Timestamp,observed_until: Timestamp) -> TaxDeliveryUploadPrerequisite:
    """Trusted application binds a just-read body to its first stored original."""
    if (type(retained) is not TaxDeliveryInstanceObservation or type(fresh) is not TaxDeliveryInstanceObservation
            or retained.evidence_sha256!=fresh.evidence_sha256 or retained.original!=fresh.original):
        raise ValueError('Fresh Tax instance read differs from its retained content.')
    fresh.assert_approval(approval,draft,retained.instance_id)
    value=TaxDeliveryUploadPrerequisite(retained.instance_id,
        TaxDeliveryReadReference(retained.sha256,retained.evidence_sha256,fresh.observed_at),observed_from,observed_until)
    value.assert_retained(approval,draft,retained)
    value.assert_current(observed_until)
    return value


def _decode_upload_prerequisite(value):
    value=_object(value,('instance_id','instance_read','observed_from','observed_until'))
    read=_object(value['instance_read'],('event_sha256','evidence_sha256','observed_at'))
    observed=_object(read['observed_at'],('value',))
    start=_object(value['observed_from'],('value',));end=_object(value['observed_until'],('value',))
    return TaxDeliveryUploadPrerequisite(value['instance_id'],TaxDeliveryReadReference(read['event_sha256'],read['evidence_sha256'],
        Timestamp(datetime.fromisoformat(observed['value']))),Timestamp(datetime.fromisoformat(start['value'])),Timestamp(datetime.fromisoformat(end['value'])))
