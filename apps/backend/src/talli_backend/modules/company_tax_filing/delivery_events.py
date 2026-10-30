"""Retained Tax event originals and complete, scope-bound journal reconstruction."""
from __future__ import annotations

from dataclasses import dataclass,replace
import json
from enum import StrEnum

from talli_backend.shared.kernel import ActorId, ActorKind, Timestamp, UserId, CompanyId, IncomeYear
from .delivery import TaxMutationKind, TaxMutationRecord, plan_tax_mutation
from .delivery_approval import TaxDeliveryAuthorityMode, TaxDeliveryReviewApproval, decode_tax_delivery_review_approval
from .delivery_draft import TaxDeliveryDraft
from .delivery_journal import (TaxDeliveryMutationRequest, TaxDeliveryMutationCompletion,
    decode_tax_delivery_mutation_request, decode_tax_delivery_mutation_completion)
from .delivery_observation import (TaxDeliveryAdmissionEvidence, TaxDeliveryInstanceObservation,
    decode_tax_delivery_observation)
from .delivery_envelope_observation import TaxDeliveryEnvelopeObservation,decode_tax_delivery_envelope_observation
from .delivery_validation_job import TaxDeliveryValidationJobObservation,decode_tax_delivery_validation_job_observation
from .delivery_validation_result import TaxDeliveryValidationResultObservation,decode_tax_delivery_validation_result_observation
from .delivery_process_acknowledgment import TaxDeliveryProcessAcknowledgment,decode_tax_delivery_process_acknowledgment
from .delivery_feedback_observation import TaxDeliveryFeedbackObservation,decode_tax_delivery_feedback_observation

_EVIDENCE=(TaxDeliveryAdmissionEvidence,TaxDeliveryInstanceObservation,TaxDeliveryEnvelopeObservation,
    TaxDeliveryValidationJobObservation,TaxDeliveryValidationResultObservation,TaxDeliveryProcessAcknowledgment,TaxDeliveryFeedbackObservation)


def _submission_value(value):
    return (type(value) is TaxDeliveryFeedbackObservation
        or type(value) is TaxDeliveryProcessAcknowledgment and value.kind is TaxMutationKind.CONFIRM_SUBMISSION
        or type(value) is TaxDeliveryMutationRequest and value.submission_prerequisite is not None
        or type(value) is TaxDeliveryMutationCompletion and value.submission_read_evidence is not None)


def _confirmation_value(value):
    return (type(value) is TaxDeliveryProcessAcknowledgment and value.kind is TaxMutationKind.PREPARE_CONFIRMATION
        or type(value) is TaxDeliveryMutationRequest and value.confirmation_prerequisite is not None
        or type(value) is TaxDeliveryMutationCompletion and value.confirmation_read_evidence is not None)


def _guarded_upload_value(value):
    return (type(value) is TaxDeliveryEnvelopeObservation
        or type(value) is TaxDeliveryMutationRequest and value.upload_prerequisite is not None
        or type(value) is TaxDeliveryMutationCompletion and value.upload_read_evidence is not None)


def _validation_value(value):
    return (type(value) in (TaxDeliveryValidationJobObservation,TaxDeliveryValidationResultObservation)
        or type(value) is TaxDeliveryMutationRequest and value.validation_prerequisite is not None)


class TaxDeliveryEventFormat(StrEnum):
    JOURNAL='journal'
    OBSERVATION='observation'
    GUARDED_UPLOAD='guarded_upload'
    VALIDATION='validation'
    CONFIRMATION='confirmation'
    SUBMISSION='submission'


def tax_delivery_event_format(value) -> TaxDeliveryEventFormat:
    """Classify one retained format; persistence alone chooses its fixed RPC."""
    if _submission_value(value):return TaxDeliveryEventFormat.SUBMISSION
    if _confirmation_value(value):return TaxDeliveryEventFormat.CONFIRMATION
    if _validation_value(value):return TaxDeliveryEventFormat.VALIDATION
    if _guarded_upload_value(value):return TaxDeliveryEventFormat.GUARDED_UPLOAD
    if type(value) in (TaxDeliveryAdmissionEvidence,TaxDeliveryInstanceObservation):return TaxDeliveryEventFormat.OBSERVATION
    if type(value) in (TaxDeliveryReviewApproval,TaxDeliveryMutationRequest,TaxDeliveryMutationCompletion):return TaxDeliveryEventFormat.JOURNAL
    raise ValueError('Tax delivery event format is unsupported.')


@dataclass(frozen=True, slots=True)
class StoredTaxDeliveryEvent:
    value: TaxDeliveryReviewApproval | TaxDeliveryMutationRequest | TaxDeliveryMutationCompletion | TaxDeliveryAdmissionEvidence | TaxDeliveryInstanceObservation | TaxDeliveryEnvelopeObservation | TaxDeliveryValidationJobObservation | TaxDeliveryValidationResultObservation | TaxDeliveryProcessAcknowledgment
    recorded_at: Timestamp
    recorded_by: ActorId

    def __post_init__(self):
        if (type(self.value) not in (TaxDeliveryReviewApproval,TaxDeliveryMutationRequest,TaxDeliveryMutationCompletion,*_EVIDENCE)
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
        if type(self.value) is TaxDeliveryAdmissionEvidence:return 'admission'
        if type(self.value) is TaxDeliveryInstanceObservation:return 'observation:instance:'+self.value.evidence_sha256
        if type(self.value) is TaxDeliveryEnvelopeObservation:return 'observation:envelope:'+self.value.evidence_sha256
        if type(self.value) is TaxDeliveryValidationJobObservation:return 'observation:validation-job:'+self.value.evidence_sha256
        if type(self.value) is TaxDeliveryValidationResultObservation:return 'observation:validation-result:'+self.value.evidence_sha256
        if type(self.value) is TaxDeliveryFeedbackObservation:return 'observation:feedback:'+self.value.evidence_sha256
        if type(self.value) is TaxDeliveryProcessAcknowledgment:return 'acknowledgment:'+self.value.kind.value
        prefix='completion' if type(self.value) is TaxDeliveryMutationCompletion else 'intent'
        return prefix+':'+self.binding.kind.value


def decode_tax_delivery_event(raw: str, expected_sha256: str, recorded_at: Timestamp, recorded_by: ActorId,
        *,guarded_upload: bool=False,validation_evidence: bool=False,confirmation_evidence: bool=False,
        submission_evidence: bool=False) -> StoredTaxDeliveryEvent:
    # Each decoder checks the exact complete envelope, canonical bytes, hash,
    # duplicate keys, field sets and its own bounded payload. This dispatch does
    # not downgrade unknown versions or infer them from optional fields.
    if (type(guarded_upload) is not bool or type(validation_evidence) is not bool or type(confirmation_evidence) is not bool
            or type(submission_evidence) is not bool or submission_evidence and not confirmation_evidence
            or confirmation_evidence and not validation_evidence or validation_evidence and not guarded_upload
            or type(raw) is not str or len(raw.encode('utf-8'))>(36*1024*1024+49152 if submission_evidence else
                24*1024*1024+32768 if guarded_upload else 12*1024*1024+16384)):
        raise ValueError('Tax event original exceeds its limit.')
    try:
        version=json.loads(raw)['version']
        if version in ('company-tax-delivery-mutation-request-v5','company-tax-delivery-mutation-completion-v4',
                'company-tax-delivery-process-acknowledgment-v2','company-tax-delivery-feedback-observation-v1') and not submission_evidence:
            raise ValueError()
        guarded_versions={'company-tax-delivery-mutation-request-v2','company-tax-delivery-mutation-completion-v2',
            'company-tax-delivery-envelope-observation-v1'}
        if version in guarded_versions and not guarded_upload:raise ValueError()
        if version in ('company-tax-delivery-mutation-request-v3','company-tax-delivery-validation-job-observation-v1',
                'company-tax-delivery-validation-result-observation-v1') and not validation_evidence:raise ValueError()
        if version in ('company-tax-delivery-mutation-request-v4','company-tax-delivery-mutation-completion-v3',
                'company-tax-delivery-process-acknowledgment-v1') and not confirmation_evidence:raise ValueError()
        decoder={
            'company-tax-delivery-review-approval-v1':decode_tax_delivery_review_approval,
            'company-tax-delivery-mutation-request-v1':decode_tax_delivery_mutation_request,
            'company-tax-delivery-mutation-completion-v1':decode_tax_delivery_mutation_completion,
            'company-tax-delivery-admission-v1':decode_tax_delivery_observation,
            'company-tax-delivery-instance-observation-v1':decode_tax_delivery_observation,
            'company-tax-delivery-mutation-request-v2':decode_tax_delivery_mutation_request,
            'company-tax-delivery-mutation-completion-v2':decode_tax_delivery_mutation_completion,
            'company-tax-delivery-envelope-observation-v1':decode_tax_delivery_envelope_observation,
            'company-tax-delivery-mutation-request-v3':decode_tax_delivery_mutation_request,
            'company-tax-delivery-validation-job-observation-v1':decode_tax_delivery_validation_job_observation,
            'company-tax-delivery-validation-result-observation-v1':decode_tax_delivery_validation_result_observation,
            'company-tax-delivery-mutation-request-v4':decode_tax_delivery_mutation_request,
            'company-tax-delivery-mutation-completion-v3':decode_tax_delivery_mutation_completion,
            'company-tax-delivery-process-acknowledgment-v1':decode_tax_delivery_process_acknowledgment,
            'company-tax-delivery-mutation-request-v5':decode_tax_delivery_mutation_request,
            'company-tax-delivery-mutation-completion-v4':decode_tax_delivery_mutation_completion,
            'company-tax-delivery-process-acknowledgment-v2':decode_tax_delivery_process_acknowledgment,
            'company-tax-delivery-feedback-observation-v1':decode_tax_delivery_feedback_observation,
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
    read_evidence: bool=False
    guarded_upload: bool=False
    validation_evidence: bool=False
    confirmation_evidence: bool=False
    submission_evidence: bool=False
    correction_evidence: bool=False

    def __post_init__(self):
        if (type(self.draft) is not TaxDeliveryDraft or type(self.read_evidence) is not bool or type(self.guarded_upload) is not bool
                or type(self.validation_evidence) is not bool or type(self.confirmation_evidence) is not bool
                or type(self.correction_evidence) is not bool or self.correction_evidence and not self.submission_evidence
                or self.draft.correction_parent is not None and not self.correction_evidence
                or type(self.submission_evidence) is not bool or self.submission_evidence and not self.confirmation_evidence
                or self.confirmation_evidence and not self.validation_evidence or self.validation_evidence and not self.guarded_upload
                or self.guarded_upload and not self.read_evidence):raise ValueError('Tax journal draft is invalid.')
        object.__setattr__(self,'events',tuple(self.events))
        if len(self.events)>2048:raise ValueError('Tax journal exceeds its evidence limit.')
        approval=None;admission=None;requests={};request_times={};completions={};completion_times={};instances={};envelopes={};jobs={};results={};last_job=None;last_result=None;slots=set();previous_time=None
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
            if _submission_value(value) and not self.submission_evidence:
                raise ValueError('Tax submission requires the positive successor contract.')
            if _confirmation_value(value) and not self.confirmation_evidence:
                raise ValueError('Tax confirmation requires the positive successor contract.')
            if _guarded_upload_value(value) and not self.guarded_upload:raise ValueError('Tax upload proof requires the successor contract.')
            if _validation_value(value) and not self.validation_evidence:
                raise ValueError('Tax validation proof requires the successor contract.')
            if type(value) in _EVIDENCE and not self.read_evidence:raise ValueError('Tax read evidence requires the successor contract.')
            if type(value) is TaxDeliveryReviewApproval:
                if self.events[0]!=event:raise ValueError('Tax review must precede effects.')
                value.assert_draft(self.draft);approval=value
            else:
                if approval is None:raise ValueError('Tax mutation has no retained approval.')
                if event.recorded_by!=approval.approved_by:raise ValueError('Tax journal recorder differs from its approval.')
                if type(value) is TaxDeliveryAdmissionEvidence:
                    value.assert_approval(approval,self.draft);admission=value
                elif type(value) is TaxDeliveryInstanceObservation:
                    created=completions.get(TaxMutationKind.CREATE_INSTANCE)
                    if admission is None or created is None:raise ValueError('Tax read has no retained admission and known instance.')
                    value.assert_approval(approval,self.draft,created.result['instanceId'])
                    instances[value.evidence_sha256]=value
                elif type(value) is TaxDeliveryEnvelopeObservation:
                    instance=instances.get(value.instance_evidence_sha256)
                    if instance is None:raise ValueError('Tax envelope has no retained metadata predecessor.')
                    value.assert_instance(approval,self.draft,instance)
                    envelopes[value.evidence_sha256]=value
                elif type(value) is TaxDeliveryValidationJobObservation:
                    request=requests.get(TaxMutationKind.START_VALIDATION);started=completions.get(TaxMutationKind.START_VALIDATION)
                    if request is None or started is None:raise ValueError('Tax status has no retained known job.')
                    value.assert_started(approval,self.draft,request,started)
                    if not completion_times[TaxMutationKind.START_VALIDATION].value<=value.observed_at.value<=event.recorded_at.value:
                        raise ValueError('Tax job read is outside its committed start/record interval.')
                    jobs[value.evidence_sha256]=value
                    last_job=value
                elif type(value) is TaxDeliveryValidationResultObservation:
                    job=jobs.get(value.job_status_evidence_sha256)
                    if job is None:raise ValueError('Tax result has no retained known-job status.')
                    value.assert_status(approval,self.draft,requests[TaxMutationKind.START_VALIDATION],completions[TaxMutationKind.START_VALIDATION],job)
                    if value.observed_at.value>event.recorded_at.value:raise ValueError('Tax result read postdates its record.')
                    results[value.evidence_sha256]=value
                    last_result=value
                elif type(value) is TaxDeliveryProcessAcknowledgment:
                    request=requests.get(value.kind)
                    if request is None:raise ValueError('Tax process acknowledgment has no committed preparation.')
                    value.assert_request(request,approval,self.draft)
                    if not request_times[request.kind].value<=value.observed_at.value<=event.recorded_at.value:
                        raise ValueError('Tax process acknowledgment predates its committed intent or postdates its record.')
                elif type(value) is TaxDeliveryFeedbackObservation:
                    instance=instances.get(value.instance_evidence_sha256)
                    if instance is None or TaxMutationKind.CONFIRM_SUBMISSION not in requests:
                        raise ValueError('Tax feedback has no retained metadata and committed submission intent.')
                    value.assert_instance(approval,self.draft,instance)
                    if not request_times[TaxMutationKind.CONFIRM_SUBMISSION].value<=instance.observed_at.value<=value.observed_at.value<=event.recorded_at.value:
                        raise ValueError('Tax feedback read is outside its committed submission/record interval.')
                elif type(value) is TaxDeliveryMutationRequest:
                    value.assert_draft(approval,self.draft)
                    kinds=list(TaxMutationKind);index=kinds.index(value.kind)
                    if index and kinds[index-1] not in completions:
                        raise ValueError('Tax journal predecessor is unknown or incomplete.')
                    if index and value.target_instance!=completions[TaxMutationKind.CREATE_INSTANCE].result['instanceId']:
                        raise ValueError('Tax journal targets a different authority instance.')
                    if value.upload_prerequisite is not None:
                        instance=instances.get(value.upload_prerequisite.instance_read.evidence_sha256)
                        if admission is None or instance is None:raise ValueError('Tax upload has no retained admission and instance proof.')
                        value.upload_prerequisite.assert_retained(approval,self.draft,instance)
                        value.upload_prerequisite.assert_current(event.recorded_at)
                    if value.validation_prerequisite is not None:
                        proof=value.validation_prerequisite
                        instance=instances.get(proof.instance_read.evidence_sha256);envelope=envelopes.get(proof.envelope_read.evidence_sha256)
                        if admission is None or instance is None or envelope is None:raise ValueError('Tax validation has no retained Clean/file originals.')
                        proof.assert_retained(approval,self.draft,instance,envelope);proof.assert_current(event.recorded_at)
                        if proof.observed_from.value<completion_times[TaxMutationKind.UPLOAD_ENVELOPE].value:
                            raise ValueError('Tax validation reads predate the retained known upload result.')
                    if value.confirmation_prerequisite is not None:
                        proof=value.confirmation_prerequisite
                        job=jobs.get(proof.job_read.evidence_sha256);result=results.get(proof.result_read.evidence_sha256)
                        instance=instances.get(proof.clean_file.instance_read.evidence_sha256)
                        envelope=envelopes.get(proof.clean_file.envelope_read.evidence_sha256)
                        if (admission is None or job is None or result is None or instance is None or envelope is None
                                or job is not last_job or result is not last_result):
                            raise ValueError('Tax confirmation has missing or superseded validation originals.')
                        proof.assert_retained(approval,self.draft,requests[TaxMutationKind.START_VALIDATION],
                            completions[TaxMutationKind.START_VALIDATION],job,result,instance,envelope)
                        proof.assert_current(event.recorded_at)
                        if proof.observed_from.value<completion_times[TaxMutationKind.START_VALIDATION].value:
                            raise ValueError('Tax confirmation reads predate the committed known validation start.')
                    if value.submission_prerequisite is not None:
                        proof=value.submission_prerequisite
                        job=jobs.get(proof.job_read.evidence_sha256);result=results.get(proof.result_read.evidence_sha256)
                        instance=instances.get(proof.instance_read.evidence_sha256);envelope=envelopes.get(proof.envelope_read.evidence_sha256)
                        if (admission is None or job is None or result is None or instance is None or envelope is None
                                or job is not last_job or result is not last_result):
                            raise ValueError('Tax submission has missing or superseded validation/file originals.')
                        proof.assert_retained(approval,self.draft,requests[TaxMutationKind.PREPARE_CONFIRMATION],
                            completions[TaxMutationKind.PREPARE_CONFIRMATION],requests[TaxMutationKind.START_VALIDATION],
                            completions[TaxMutationKind.START_VALIDATION],job,result,instance,envelope)
                        proof.assert_current(event.recorded_at)
                        if proof.observed_from.value<completion_times[TaxMutationKind.PREPARE_CONFIRMATION].value:
                            raise ValueError('Tax submission fresh reads predate its committed known preparation.')
                    requests[value.kind]=value
                    request_times[value.kind]=event.recorded_at
                else:
                    if value.intent.kind not in requests:raise ValueError('Tax result has no committed request.')
                    value.assert_request(requests[value.intent.kind],approval)
                    if (value.intent.kind is TaxMutationKind.CREATE_INSTANCE and self.draft.correction_parent is not None
                            and value.result['instanceId']==self.draft.correction_parent.terminal.instance.instance_id):
                        raise ValueError('Tax correction creation reused its parent instance.')
                    if value.upload_read_evidence is not None and value.upload_read_evidence.instance.observed_at.value<request_times[value.intent.kind].value:
                        raise ValueError('Tax upload recovery read predates its committed request.')
                    if value.confirmation_read_evidence is not None and value.confirmation_read_evidence.instance.observed_at.value<request_times[value.intent.kind].value:
                        raise ValueError('Tax confirmation recovery read predates its committed preparation.')
                    if value.submission_read_evidence is not None and value.submission_read_evidence.instance.observed_at.value<request_times[value.intent.kind].value:
                        raise ValueError('Tax submission recovery read predates its committed owner-confirmed intent.')
                    if (value.confirmation_read_evidence is not None or value.submission_read_evidence is not None) and value.observed_at.value>event.recorded_at.value:
                        raise ValueError('Tax process completion postdates its server record.')
                    completions[value.intent.kind]=value
                    completion_times[value.intent.kind]=event.recorded_at
            slots.add(event.slot)

    @property
    def approval(self):
        return self.events[0].value if self.events else None

    @property
    def progress(self) -> TaxDeliveryProgress:
        if self.approval is None:raise ValueError('Tax journal has no retained review.')
        latest=self.events[-1]
        effect=next(event for event in reversed(self.events) if type(event.value) not in _EVIDENCE)
        return TaxDeliveryProgress(self.draft.filing_id,self.draft.envelope.source.company_id,
            self.draft.envelope.source.income_year,self.approval.approval_id,self.approval.sha256,
            self.draft.sha256,self.approval.review_sha256,self.approval.authority_mode,
            'reviewed' if effect.slot=='review' else 'uncertain' if effect.slot.startswith('intent:') else 'mutation_completed',
            None if effect.slot=='review' else effect.binding.kind,latest.value.sha256,latest.recorded_at)

    def mutation_progress(self,kind: TaxMutationKind) -> TaxDeliveryProgress:
        """Replay this operation's original receipt across later-stage updates."""
        if type(kind) is not TaxMutationKind:raise ValueError('Tax mutation kind is invalid.')
        event=next((row for row in reversed(self.events) if row.slot in
            ('intent:'+kind.value,'completion:'+kind.value)),None)
        if event is None:raise ValueError('Tax mutation has no committed original.')
        return replace(self.progress,status='uncertain' if event.slot.startswith('intent:') else 'mutation_completed',
            mutation_kind=kind,latest_event_sha256=event.value.sha256,recorded_at=event.recorded_at)

    def plan(self, request: TaxDeliveryMutationRequest):
        if self.approval is None:raise ValueError('Tax journal has no review approval.')
        request.assert_draft(self.approval,self.draft)
        intent=request.intent(self.approval)
        prior=next((event.value for event in self.events if event.slot=='intent:'+request.kind.value),None)
        if prior is None:
            if (self.guarded_upload and request.kind is not TaxMutationKind.CREATE_INSTANCE
                    and request.upload_prerequisite is None and request.validation_prerequisite is None
                    and request.confirmation_prerequisite is None and request.submission_prerequisite is None):
                raise ValueError('A new later-stage Tax intent requires retained prerequisites.')
            # Validate an append in the same order persistence will retain it.
            # Historical reconstruction validates server recording time. A new
            # upload's eventual SQL record must follow its completed fresh read.
            proof=request.upload_prerequisite or request.validation_prerequisite or request.confirmation_prerequisite or request.submission_prerequisite
            recorded_at=(Timestamp(max(proof.observed_until.value,self.events[-1].recorded_at.value))
                if proof is not None else self.events[-1].recorded_at)
            TaxDeliveryJournal(self.draft,self.events+(StoredTaxDeliveryEvent(request,recorded_at,self.approval.approved_by),),
                self.read_evidence,self.guarded_upload,self.validation_evidence,self.confirmation_evidence,self.submission_evidence,self.correction_evidence)
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


@dataclass(frozen=True,slots=True)
class TaxDeliveryProgress:
    filing_id: str
    company_id: CompanyId
    income_year: IncomeYear
    approval_id: str
    approval_sha256: str
    draft_sha256: str
    review_sha256: str
    authority_mode: TaxDeliveryAuthorityMode
    status: str
    mutation_kind: TaxMutationKind | None
    latest_event_sha256: str
    recorded_at: Timestamp


def assert_tax_delivery_attempt_history(query,snapshot,filing_id: str) -> TaxDeliveryJournal:
    """Only a complete scope with no other active delivery can open a first run.

    Correction/replacement admission is added with its terminal original proofs.
    A new filing identifier cannot bypass a previously retained uncertain effect.
    """
    from .public import CompanyTaxError,project_company_tax_source
    facts=project_company_tax_source(query,snapshot)
    if snapshot.contract_version not in ('company-tax-source-v3','company-tax-source-v4','company-tax-source-v5','company-tax-source-v6','company-tax-source-v7','company-tax-source-v8','company-tax-source-v9') or facts.history_coverage.status!='complete':
        raise CompanyTaxError.unavailable()
    from .delivery_correction import tax_delivery_lineage
    journals=tuple(tax_delivery_snapshot_journal(snapshot,row.draft) for row in snapshot.delivery_drafts)
    try:frontier=tax_delivery_lineage(journals)
    except ValueError:raise CompanyTaxError.draft_conflict() from None
    if frontier is not None and frontier!=filing_id:raise CompanyTaxError.draft_conflict()
    draft=next((row.draft for row in snapshot.delivery_drafts if row.draft.filing_id==filing_id),None)
    if draft is None:raise CompanyTaxError.not_found()
    return tax_delivery_snapshot_journal(snapshot,draft)


def tax_delivery_snapshot_journal(snapshot,draft):
    versions=('company-tax-source-v3','company-tax-source-v4','company-tax-source-v5',
        'company-tax-source-v6','company-tax-source-v7','company-tax-source-v8','company-tax-source-v9')
    if snapshot.contract_version not in versions:raise ValueError('Tax journal source contract is unsupported.')
    level=versions.index(snapshot.contract_version)
    return TaxDeliveryJournal(draft,tuple(e for e in snapshot.delivery_events if e.binding.filing_id==draft.filing_id),
        *(level>=n for n in range(1,7)))
