"""Immutable correction lineage from a known, terminal, receipted submission.

A receipt proves retained technical delivery, never assessment acceptance or a
legal right to amend. A correction is another complete, independently reviewed
packet. This value grants no dispatch authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
import hashlib

from talli_backend.shared.kernel import Timestamp
from .delivery import TaxMutationKind, _digest
from .delivery_original import _uuid


if TYPE_CHECKING:
    from .delivery_submission_read_evidence import TaxDeliverySubmissionReadEvidence


@dataclass(frozen=True, slots=True)
class TaxDeliveryCorrectionParent:
    filing_id: str
    draft_sha256: str
    approval_sha256: str
    submission_request_sha256: str
    submission_completion_sha256: str
    calculated_tax_sha256: str
    calculated_business_sha256: str
    terminal: TaxDeliverySubmissionReadEvidence

    def __post_init__(self):
        from .delivery_submission_read_evidence import TaxDeliverySubmissionReadEvidence
        _uuid(self.filing_id)
        for name in ('draft_sha256','approval_sha256','submission_request_sha256',
                'submission_completion_sha256','calculated_tax_sha256','calculated_business_sha256'):
            _digest(getattr(self,name))
        if type(self.terminal) is not TaxDeliverySubmissionReadEvidence:
            raise ValueError('Tax correction requires complete parent terminal originals.')
        instance=self.terminal.instance; inspection=instance.inspection
        if (instance.filing_id!=self.filing_id or instance.approval_sha256!=self.approval_sha256
                or self.terminal.feedback is None or inspection.process_task is not None
                or inspection.process_ended_at is None or inspection.archived is not True
                or inspection.archived_at is None):
            raise ValueError('Tax correction cannot replace an active or unresolved submission.')

    @property
    def canonical_value(self):
        return {name:getattr(self,name) for name in ('filing_id','draft_sha256','approval_sha256',
            'submission_request_sha256','submission_completion_sha256','calculated_tax_sha256',
            'calculated_business_sha256')}|{'terminal':self.terminal.canonical_value}

    def assert_parent(self,journal):
        approval=journal.approval
        request=next((e for e in journal.events if e.slot=='intent:confirm_submission'),None)
        completion=next((e for e in journal.events if e.slot=='completion:confirm_submission'),None)
        preparation=next((e for e in journal.events if e.slot=='intent:prepare_confirmation'),None)
        if (approval is None or request is None or completion is None or preparation is None
                or journal.draft.filing_id!=self.filing_id or journal.draft.sha256!=self.draft_sha256
                or approval.sha256!=self.approval_sha256 or request.value.sha256!=self.submission_request_sha256
                or completion.value.sha256!=self.submission_completion_sha256
                or request.value.kind is not TaxMutationKind.CONFIRM_SUBMISSION
                or self.terminal.instance.observed_at.value<completion.recorded_at.value):
            raise ValueError('Tax correction parent differs from its immutable submitted journal.')
        self.terminal.assert_request(request.value)
        self.terminal.instance.assert_approval(approval,journal.draft,self.terminal.instance.instance_id)
        self.terminal.envelope.assert_instance(approval,journal.draft,self.terminal.instance)
        _,documents=_parent_events_and_pair(journal)
        if (documents.get('skattemeldingUpersonligEtterBeregning')!=self.calculated_tax_sha256
                or documents.get('naeringsspesifikasjonEtterBeregning')!=self.calculated_business_sha256):
            raise ValueError('Tax correction does not bind the parent calculated statutory pair.')

    def assert_current(self,now: Timestamp):
        times=(self.terminal.instance.observed_at,self.terminal.feedback.observed_at,self.terminal.envelope.observed_at)
        if (type(now) is not Timestamp or any(t.value>now.value for t in times)
                or (now.value-min(t.value for t in times)).total_seconds()>30):
            raise ValueError('Tax correction terminal reads are stale or from the future.')

    def assert_child(self,draft):
        parent=self.terminal.instance; source=draft.envelope.source
        if (draft.filing_id==self.filing_id or source.company_id!=parent.company_id
                or source.income_year!=parent.income_year or source.organization_number!=parent.organization_number
                or draft.prepared_by!=parent.approved_by or draft.current_document is None
                or draft.current_document.response.observed_at.value<max(self.terminal.instance.observed_at.value,
                    self.terminal.feedback.observed_at.value,self.terminal.envelope.observed_at.value)):
            raise ValueError('Tax correction child has a different scope or predates its parent read.')


def _parent_events_and_pair(journal):
    events={event.slot:event.value for event in journal.events}
    preparation=events['intent:prepare_confirmation']
    pair={item.document_type:hashlib.sha256(item.raw_bytes).hexdigest()
        for item in preparation.confirmation_prerequisite.calculated.response.calculated_documents}
    return events,pair


def bind_tax_delivery_correction_parent(journal,terminal):
    """Bind a complete known parent and fresh terminal originals in one place."""
    try:
        events,pair=_parent_events_and_pair(journal)
        value=TaxDeliveryCorrectionParent(journal.draft.filing_id,journal.draft.sha256,journal.approval.sha256,
            events['intent:confirm_submission'].sha256,events['completion:confirm_submission'].sha256,
            pair['skattemeldingUpersonligEtterBeregning'],pair['naeringsspesifikasjonEtterBeregning'],terminal)
        value.assert_parent(journal)
        return value
    except (KeyError,AttributeError,TypeError):
        raise ValueError('Tax correction parent has no complete known submission.') from None


def decode_tax_delivery_correction_parent(value):
    from .delivery_draft import _object
    from .delivery_submission_read_evidence import _decode_submission_read_evidence
    value=_object(value,('filing_id','draft_sha256','approval_sha256','submission_request_sha256',
        'submission_completion_sha256','calculated_tax_sha256','calculated_business_sha256','terminal'))
    return TaxDeliveryCorrectionParent(**(value|{'terminal':_decode_submission_read_evidence(value['terminal'])}))


def tax_delivery_lineage(journals):
    """Validate one acyclic chain, including a prepared child reserving its tip.

    Unreviewed initial candidates remain harmless; any effect or correction
    claim participates. Every parent is checked against its complete journal.
    """
    if sum(bool(j.events) or j.draft.correction_parent is not None for j in journals)>64:
        raise ValueError('Tax correction chain exceeds its finite history bound.')
    by_id={j.draft.filing_id:j for j in journals}
    if len(by_id)!=len(journals):raise ValueError('Duplicate Tax lineage draft.')
    children={}; participating=set()
    for journal in journals:
        draft=journal.draft; link=draft.correction_parent
        if journal.events or link is not None:participating.add(draft.filing_id)
        if link is None:continue
        if link.filing_id not in by_id or link.filing_id in children:
            raise ValueError('Tax correction has a missing parent or forks an existing child.')
        link.assert_parent(by_id[link.filing_id]);link.assert_child(draft)
        children[link.filing_id]=draft.filing_id
    roots=participating-set(children.values())
    if not participating:return None
    if len(roots)!=1:raise ValueError('Tax history has unrelated delivery attempts.')
    current=next(iter(roots));seen=set()
    while current not in seen:
        seen.add(current)
        if current not in children:
            if seen!=participating:raise ValueError('Tax correction history has an unlinked cycle.')
            return current
        current=children[current]
    raise ValueError('Tax correction history is cyclic.')
