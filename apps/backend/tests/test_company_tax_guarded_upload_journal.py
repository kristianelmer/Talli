"""Guarded journal binds retained prerequisites and causal recovery reads."""
import base64
from dataclasses import replace
from datetime import timedelta
import json

import pytest

from talli_backend.modules.company_tax_filing.public import (
    TaxDeliveryJournal,StoredTaxDeliveryEvent,TaxDeliveryAdmissionEvidence,TaxDeliveryOriginalPurpose,TaxDeliveryReadOriginal,
    TaxMutationKind,TaxMutationDisposition,TaxDeliveryCompletionOrigin,TaxDeliveryUploadReadEvidence,
    bind_tax_delivery_upload_prerequisite,build_tax_delivery_mutation_request,complete_tax_delivery_mutation,
    reconcile_tax_delivery_upload,decode_tax_delivery_event,
)
from talli_backend.shared.kernel import Timestamp
from test_company_tax_delivery_approval import review_basis
from test_company_tax_delivery_rehearsal import admitted
from test_company_tax_delivery_observation import observation
from test_company_tax_delivery_envelope_observation import envelope_read
from test_company_tax_delivery_journal import INSTANCE


def guarded(review_basis):
    grant,_,_,approval,draft=admitted(review_basis)
    base=draft.current_document.response.observed_at.value
    at=lambda seconds:Timestamp(base+timedelta(seconds=seconds))
    admission=TaxDeliveryAdmissionEvidence(draft.filing_id,approval.company_id,approval.income_year,approval.approved_by,approval.sha256,
        TaxDeliveryReadOriginal(TaxDeliveryOriginalPurpose.ADMISSION,base64.b64encode(grant.canonical_context.encode()).decode(),'application/json',None))
    create=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.CREATE_INSTANCE)
    created=complete_tax_delivery_mutation(create,approval,draft,response_bytes=json.dumps({'id':INSTANCE}).encode(),
        observed_at=at(.2),origin=TaxDeliveryCompletionOrigin.MUTATION_RESPONSE)
    instance,_,_=observation(review_basis)
    instance=replace(instance,approval_sha256=approval.sha256,observed_at=at(1))
    events=tuple(StoredTaxDeliveryEvent(value,at(time),approval.approved_by) for value,time in
        ((approval,0),(admission,.01),(create,.02),(created,.3),(instance,1.1)))
    fresh=replace(instance,observed_at=at(2))
    proof=bind_tax_delivery_upload_prerequisite(approval,draft,retained=instance,fresh=fresh,observed_from=at(1.9),observed_until=at(2.1))
    request=build_tax_delivery_mutation_request(approval,draft,TaxMutationKind.UPLOAD_ENVELOPE,target_instance=INSTANCE,upload_prerequisite=proof)
    return TaxDeliveryJournal(draft,events,True,True),request,approval,at


def test_only_positive_successor_journal_can_plan_and_reconstruct_new_upload(review_basis):
    journal,request,approval,at=guarded(review_basis)
    assert journal.plan(request) is TaxMutationDisposition.EXECUTE
    event=decode_tax_delivery_event(request.canonical_json,request.sha256,at(2.2),approval.approved_by,guarded_upload=True)
    retained=replace(journal,events=journal.events+(event,))
    assert retained.progress.status=='uncertain' and retained.progress.mutation_kind is TaxMutationKind.UPLOAD_ENVELOPE
    assert retained.plan(request) is TaxMutationDisposition.RECONCILE
    assert retained.mutation_progress(TaxMutationKind.CREATE_INSTANCE).status=='mutation_completed'
    assert retained.mutation_progress(TaxMutationKind.UPLOAD_ENVELOPE).status=='uncertain'
    assert retained.mutation_progress(TaxMutationKind.CREATE_INSTANCE).latest_event_sha256==journal.mutation_progress(TaxMutationKind.CREATE_INSTANCE).latest_event_sha256
    with pytest.raises(ValueError):replace(retained,guarded_upload=False)


@pytest.mark.parametrize('defect',['reference','stale','missing-admission'])
def test_missing_borrowed_or_stale_prerequisite_cannot_open_upload(review_basis,defect):
    journal,request,approval,at=guarded(review_basis)
    if defect=='reference':request=replace(request,upload_prerequisite=replace(request.upload_prerequisite,
        instance_read=replace(request.upload_prerequisite.instance_read,event_sha256='a'*64)))
    event=StoredTaxDeliveryEvent(request,at(33 if defect=='stale' else 2.2),approval.approved_by)
    events=tuple(event for event in journal.events if defect!='missing-admission' or event.slot!='admission')+(event,)
    with pytest.raises(ValueError):replace(journal,events=events)


def test_fresh_legacy_later_stage_cannot_be_planned_but_historical_unknown_replays(review_basis):
    journal,_,approval,at=guarded(review_basis)
    request=build_tax_delivery_mutation_request(approval,journal.draft,TaxMutationKind.UPLOAD_ENVELOPE,target_instance=INSTANCE)
    with pytest.raises(ValueError):journal.plan(request)
    historical=replace(journal,events=journal.events+(StoredTaxDeliveryEvent(request,at(2.2),approval.approved_by),))
    assert historical.plan(request) is TaxMutationDisposition.RECONCILE


@pytest.mark.parametrize('before_intent',[False,True])
def test_upload_recovery_requires_fresh_causal_reads_and_preserves_exact_pair(review_basis,before_intent):
    journal,request,approval,at=guarded(review_basis)
    journal=replace(journal,events=journal.events+(StoredTaxDeliveryEvent(request,at(2.2),approval.approved_by),))
    envelope,instance,_,_=envelope_read(review_basis)
    instance=replace(instance,approval_sha256=approval.sha256,observed_at=at(1 if before_intent else 2.7))
    envelope=replace(envelope,approval_sha256=approval.sha256,instance_evidence_sha256=instance.evidence_sha256,
        observed_at=at(1.1 if before_intent else 2.8))
    result=reconcile_tax_delivery_upload(request,approval,journal.draft,evidence=TaxDeliveryUploadReadEvidence(instance,envelope),observed_at=at(2.9))
    event=decode_tax_delivery_event(result.canonical_json,result.sha256,at(3),approval.approved_by,guarded_upload=True)
    if before_intent:
        with pytest.raises(ValueError):replace(journal,events=journal.events+(event,))
    else:
        completed=replace(journal,events=journal.events+(event,))
        assert completed.progress.status=='mutation_completed' and completed.plan(request) is TaxMutationDisposition.REPLAY
        assert completed.events[-1].value.upload_read_evidence.envelope.original.raw_bytes==journal.draft.envelope.envelope_xml.encode()
