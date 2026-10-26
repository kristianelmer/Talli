"""Retained Tax event originals and complete, scope-bound journal reconstruction."""
from __future__ import annotations

from dataclasses import dataclass
import json

from talli_backend.shared.kernel import ActorId, ActorKind, Timestamp, UserId
from .delivery import TaxMutationKind, TaxMutationRecord, plan_tax_mutation
from .delivery_approval import TaxDeliveryReviewApproval, decode_tax_delivery_review_approval
from .delivery_draft import TaxDeliveryDraft
from .delivery_journal import (TaxDeliveryMutationRequest, TaxDeliveryMutationCompletion,
    decode_tax_delivery_mutation_request, decode_tax_delivery_mutation_completion)


@dataclass(frozen=True, slots=True)
class StoredTaxDeliveryEvent:
    value: TaxDeliveryReviewApproval | TaxDeliveryMutationRequest | TaxDeliveryMutationCompletion
    recorded_at: Timestamp
    recorded_by: ActorId

    def __post_init__(self):
        if (type(self.value) not in (TaxDeliveryReviewApproval,TaxDeliveryMutationRequest,TaxDeliveryMutationCompletion)
                or type(self.recorded_at) is not Timestamp or type(self.recorded_by) is not ActorId
                or self.recorded_by.kind is not ActorKind.USER or type(self.recorded_by.subject) is not UserId):
            raise ValueError('Tax delivery event is invalid.')
        if type(self.value) is not TaxDeliveryMutationRequest and self.recorded_by!=self.binding.approved_by:
            raise ValueError('Tax event recorder differs from its approval.')

    @property
    def binding(self):
        return self.value.intent if type(self.value) is TaxDeliveryMutationCompletion else self.value

    @property
    def slot(self):
        if type(self.value) is TaxDeliveryReviewApproval:return 'review'
        prefix='completion' if type(self.value) is TaxDeliveryMutationCompletion else 'intent'
        return prefix+':'+self.binding.kind.value


def decode_tax_delivery_event(raw: str, expected_sha256: str, recorded_at: Timestamp, recorded_by: ActorId) -> StoredTaxDeliveryEvent:
    # Each decoder checks the exact complete envelope, canonical bytes, hash,
    # duplicate keys, field sets and its own bounded payload. This dispatch does
    # not downgrade unknown versions or infer them from optional fields.
    if type(raw) is not str or len(raw.encode('utf-8'))>12*1024*1024+16384:
        raise ValueError('Tax event original exceeds its limit.')
    try:
        version=json.loads(raw)['version']
        decoder={
            'company-tax-delivery-review-approval-v1':decode_tax_delivery_review_approval,
            'company-tax-delivery-mutation-request-v1':decode_tax_delivery_mutation_request,
            'company-tax-delivery-mutation-completion-v1':decode_tax_delivery_mutation_completion,
        }[version]
        return StoredTaxDeliveryEvent(decoder(raw,expected_sha256),recorded_at,recorded_by)
    except (KeyError,TypeError,ValueError,RecursionError,OverflowError):
        raise ValueError('Tax delivery event original is invalid.') from None


@dataclass(frozen=True, slots=True)
class TaxDeliveryJournal:
    """A positively complete retained history, never a dispatch authorization.

    Persistence enumerates all events before constructing this value. Mutation
    sequencing here enforces causal bindings only. Clean scan, validation, fresh
    owner/MFA/source and finite runtime admission remain application prerequisites.
    """
    draft: TaxDeliveryDraft
    events: tuple[StoredTaxDeliveryEvent, ...]

    def __post_init__(self):
        if type(self.draft) is not TaxDeliveryDraft:raise ValueError('Tax journal draft is invalid.')
        object.__setattr__(self,'events',tuple(self.events))
        if len(self.events)>9:raise ValueError('Tax journal has unknown event slots.')
        approval=None;requests={};completions={};slots=set();previous_time=None
        for event in self.events:
            if type(event) is not StoredTaxDeliveryEvent or event.slot in slots:
                raise ValueError('Tax journal has duplicate or invalid events.')
            if previous_time is not None and event.recorded_at.value<previous_time:
                raise ValueError('Tax journal recording order is invalid.')
            previous_time=event.recorded_at.value
            binding=event.binding
            if (binding.filing_id!=self.draft.filing_id or binding.company_id!=self.draft.envelope.source.company_id
                    or binding.income_year!=self.draft.envelope.source.income_year):
                raise ValueError('Tax journal contains foreign scope.')
            value=event.value
            if type(value) is TaxDeliveryReviewApproval:
                if self.events[0]!=event:raise ValueError('Tax review must precede effects.')
                value.assert_draft(self.draft);approval=value
            else:
                if approval is None:raise ValueError('Tax mutation has no retained approval.')
                if event.recorded_by!=approval.approved_by:raise ValueError('Tax journal recorder differs from its approval.')
                if type(value) is TaxDeliveryMutationRequest:
                    value.assert_draft(approval,self.draft)
                    kinds=list(TaxMutationKind);index=kinds.index(value.kind)
                    if index and kinds[index-1] not in completions:
                        raise ValueError('Tax journal predecessor is unknown or incomplete.')
                    if index and value.target_instance!=completions[TaxMutationKind.CREATE_INSTANCE].result['instanceId']:
                        raise ValueError('Tax journal targets a different authority instance.')
                    requests[value.kind]=value
                else:
                    if value.intent.kind not in requests:raise ValueError('Tax result has no committed request.')
                    value.assert_request(requests[value.intent.kind],approval)
                    completions[value.intent.kind]=value
            slots.add(event.slot)

    @property
    def approval(self):
        return self.events[0].value if self.events else None

    def plan(self, request: TaxDeliveryMutationRequest):
        if self.approval is None:raise ValueError('Tax journal has no review approval.')
        request.assert_draft(self.approval,self.draft)
        intent=request.intent(self.approval)
        prior=next((event.value for event in self.events if event.slot=='intent:'+request.kind.value),None)
        if prior is None:
            # Validate an append in the same order persistence will retain it.
            TaxDeliveryJournal(self.draft,self.events+(StoredTaxDeliveryEvent(request,self.events[-1].recorded_at,self.approval.approved_by),))
            return plan_tax_mutation(intent,None)
        completion=next((event.value for event in self.events if event.slot=='completion:'+request.kind.value),None)
        record=TaxMutationRecord(prior.intent(self.approval),'completed' if completion else 'uncertain',
            completion.result if completion else None)
        return plan_tax_mutation(intent,record)


@dataclass(frozen=True, slots=True)
class TaxDeliveryEventAppend:
    event: StoredTaxDeliveryEvent
    inserted: bool

    def __post_init__(self):
        if type(self.event) is not StoredTaxDeliveryEvent or type(self.inserted) is not bool:
            raise ValueError('Tax event append result is invalid.')
