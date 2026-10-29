"""Read-only owner workspace; available actions never replace mutation guards."""
from __future__ import annotations

import base64
from dataclasses import dataclass,field
from enum import StrEnum
import hashlib

from talli_backend.shared.kernel import CompanyId,IncomeYear,Timestamp
from .delivery import TaxMutationKind
from .delivery_events import TaxDeliveryJournal,tax_delivery_snapshot_journal
from .delivery_correction import tax_delivery_lineage
from .delivery_validation_response import TaxValidationResultCode
from .delivery_calculated_documents import TaxCalculatedDocumentsInspection
from .delivery_validation_review import TaxValidationResponseReview
from .delivery_owner_review import TaxCalculatedDocumentsReview,TaxCalculatedDocumentReview
from .delivery_observation import TaxDeliveryInstanceObservation
from .delivery_feedback_observation import TaxDeliveryFeedbackObservation


@dataclass(frozen=True,slots=True)
class TaxDeliveryWorkspaceValidation:
    response: TaxValidationResponseReview
    calculated: TaxCalculatedDocumentsReview | None
    documents: tuple[TaxCalculatedDocumentReview,...]

    def __post_init__(self):
        if (type(self.response) is not TaxValidationResponseReview or self.calculated is not None and
                (type(self.calculated) is not TaxCalculatedDocumentsReview or self.calculated.inspection.response!=self.response.inspection)):
            raise ValueError('Tax workspace validation must preserve its exact response.')
        originals={item.document_type:hashlib.sha256(item.raw_bytes).hexdigest() for item in self.response.inspection.calculated_documents}
        if (type(self.documents) is not tuple or len({item.document_type for item in self.documents})!=len(self.documents)
                or any(type(item) is not TaxCalculatedDocumentReview or originals.get(item.document_type)!=item.original_sha256 for item in self.documents)
                or self.calculated is not None and self.documents!=self.calculated.documents):
            raise ValueError('Tax displayed documents must match their exact retained response.')


class TaxDeliveryWorkspaceState(StrEnum):
    PREPARED='prepared'
    LEGACY_PREPARED='legacy_prepared'
    REVIEWED='reviewed'
    CREATION_UNCERTAIN='creation_uncertain'
    CREATED='created'
    UPLOAD_UNCERTAIN='upload_uncertain'
    UPLOADED='uploaded'
    VALIDATION_START_UNCERTAIN='validation_start_uncertain'
    VALIDATION_PENDING='validation_pending'
    VALIDATION_BLOCKED='validation_blocked'
    VALIDATED='validated'
    CONFIRMATION_UNCERTAIN='confirmation_uncertain'
    OWNER_REVIEW='owner_review'
    SUBMISSION_UNCERTAIN='submission_uncertain'
    SUBMITTED_RECEIPT_PENDING='submitted_receipt_pending'
    SUBMITTED_RECEIPT_RECORDED='submitted_receipt_recorded'
    SUBMITTED_RECEIPTED='submitted_receipted'


class TaxDeliveryAction(StrEnum):
    APPROVE='approve'
    CREATE='create'
    UPLOAD='upload'
    RECONCILE_UPLOAD='reconcile_upload'
    VALIDATE='validate'
    RECONCILE_VALIDATION='reconcile_validation'
    PREPARE_CONFIRMATION='prepare_confirmation'
    RECONCILE_CONFIRMATION='reconcile_confirmation'
    SUBMIT='submit'
    RECONCILE_SUBMISSION='reconcile_submission'
    RECONCILE_FEEDBACK='reconcile_feedback'
    PREPARE_CORRECTION='prepare_correction'


@dataclass(frozen=True,slots=True)
class TaxDeliveryWorkspaceField:
    document: str
    path: str
    value: str
    source: str


@dataclass(frozen=True,slots=True)
class TaxDeliveryWorkspaceOriginal:
    key: str
    purpose: str
    source_filing_id: str
    sha256: str
    media_type: str
    body_base64: str=field(repr=False)

    @property
    def raw_bytes(self):return base64.b64decode(self.body_base64,validate=True)


def tax_delivery_workspace_originals(journal: TaxDeliveryJournal):
    """Complete exact retained originals, including inline recovery evidence."""
    originals={}
    def retain(purpose,raw,media,filing):
        digest=hashlib.sha256(raw).hexdigest();key=purpose+':'+digest
        value=TaxDeliveryWorkspaceOriginal(key,purpose,filing,digest,media,base64.b64encode(raw).decode('ascii'))
        if key in originals:
            if originals[key].source_filing_id!=filing or originals[key].raw_bytes!=raw:raise ValueError('Tax original key has conflicting scope.')
            return
        originals[key]=value
    def read(value,*,parent=False):
        if value is None:return
        original=value.original
        retain(('parent_' if parent else '')+original.purpose.value,original.raw_bytes,original.content_type,value.filing_id)
    def proof(value,*,parent=False):
        if value is not None:
            for name in ('instance','envelope','feedback'):read(getattr(value,name,None),parent=parent)
    draft=journal.draft
    for name in ('tax','business','envelope'):
        retain('draft_'+name,getattr(draft.envelope,name+'_xml').encode('utf-8'),'application/xml',draft.filing_id)
    if draft.current_document is not None:retain('current',draft.current_document.response.raw_bytes,'application/xml',draft.filing_id)
    if draft.correction_parent is not None:proof(draft.correction_parent.terminal,parent=True)
    for event in journal.events:
        value=event.value
        if hasattr(value,'original'):read(value)
        if getattr(value,'response_base64',None) is not None:
            retain('mutation_response',value.response_bytes,'application/json',draft.filing_id)
        for name in ('upload_read_evidence','confirmation_read_evidence','submission_read_evidence'):proof(getattr(value,name,None))
        preparation=getattr(value,'confirmation_prerequisite',None)
        if preparation is not None:
            purposes={'skattemeldingUpersonligEtterBeregning':'calculated_tax','naeringsspesifikasjonEtterBeregning':'calculated_business',
                'beregnetSkattUpersonlig':'calculated_tax_computation','summertSkattegrunnlagForVisningUpersonlig':'calculated_summary'}
            for document in preparation.calculated.response.calculated_documents:
                retain(purposes[document.document_type],document.raw_bytes,'application/xml',draft.filing_id)
    return tuple(originals.values())


@dataclass(frozen=True,slots=True)
class TaxDeliveryWorkspaceRow:
    filing_id: str
    parent_filing_id: str | None
    recorded_at: Timestamp
    draft_sha256: str
    review_sha256: str
    approval_sha256: str | None
    state: TaxDeliveryWorkspaceState
    source_current: bool
    actions: tuple[TaxDeliveryAction,...]
    fields: tuple[TaxDeliveryWorkspaceField,...]
    originals: tuple[TaxDeliveryWorkspaceOriginal,...]
    validation: TaxDeliveryWorkspaceValidation | None


@dataclass(frozen=True,slots=True)
class TaxDeliveryWorkspace:
    company_id: CompanyId
    income_year: IncomeYear
    source_sha256: str
    observed_at: Timestamp
    preparation_available: bool
    rows: tuple[TaxDeliveryWorkspaceRow,...]
    preparation_only: bool = False


def _retained_receipt(journal):
    recorded=False
    instances={event.value.evidence_sha256:event.value for event in journal.events if type(event.value) is TaxDeliveryInstanceObservation}
    for event in journal.events:
        if type(event.value) is not TaxDeliveryFeedbackObservation:continue
        feedback=event.value;instance=instances.get(feedback.instance_evidence_sha256)
        if instance is None:continue
        feedback.assert_metadata(instance)
        inspection=instance.inspection
        if inspection.feedback.scan_result!='Clean':continue
        recorded=True
        if (inspection.feedback.scan_result=='Clean' and inspection.archived is True and inspection.process_task is None
                and inspection.process_ended_at is not None and inspection.archived_at is not None
                and inspection.process_ended_at.value<=inspection.archived_at.value<=instance.observed_at.value):return 'archived'
    return 'recorded' if recorded else None


def _stage(journal,calculated,receipted):
    slots={event.slot:event.value for event in journal.events}
    if journal.approval is None:return 'prepared',TaxDeliveryAction.APPROVE
    for kind,missing,pending,action,recovery in (
            ('create_instance','reviewed','creation_uncertain',TaxDeliveryAction.CREATE,None),
            ('upload_envelope','created','upload_uncertain',TaxDeliveryAction.UPLOAD,TaxDeliveryAction.RECONCILE_UPLOAD),
            ('start_validation','uploaded','validation_start_uncertain',TaxDeliveryAction.VALIDATE,None)):
        if 'intent:'+kind not in slots:return missing,action
        if 'completion:'+kind not in slots:return pending,recovery
    if 'intent:prepare_confirmation' not in slots:
        if calculated is None:
            state='validation_blocked' if any(slot.startswith('observation:validation-result:') for slot in slots) else 'validation_pending'
            return state,TaxDeliveryAction.RECONCILE_VALIDATION
        result=calculated.response
        if (result.result_code is not TaxValidationResultCode.VALIDATED or result.validation_deviation_count
                or result.failure_reason_count):return 'validation_blocked',TaxDeliveryAction.RECONCILE_VALIDATION
        return 'validated',TaxDeliveryAction.PREPARE_CONFIRMATION
    if 'completion:prepare_confirmation' not in slots:return 'confirmation_uncertain',TaxDeliveryAction.RECONCILE_CONFIRMATION
    if 'intent:confirm_submission' not in slots:return 'owner_review',TaxDeliveryAction.SUBMIT
    if 'completion:confirm_submission' not in slots:return 'submission_uncertain',TaxDeliveryAction.RECONCILE_SUBMISSION
    if receipted=='archived':return 'submitted_receipted',None
    if receipted=='recorded':return 'submitted_receipt_recorded',TaxDeliveryAction.RECONCILE_FEEDBACK
    return 'submitted_receipt_pending',TaxDeliveryAction.RECONCILE_FEEDBACK


def project_tax_delivery_workspace(query,snapshot,source,*,preparation_available=False,dispatch_admissions=None,
        correction_admissions=None,validation=None,preparation_only=False):
    from .public import CompanyTaxError,project_company_tax_source,CompanyTaxReturnSource,_calculation_source
    from .calculation import build
    if type(preparation_available) is not bool or type(preparation_only) is not bool:raise CompanyTaxError.unavailable()
    facts=project_company_tax_source(query,snapshot)
    if snapshot.contract_version!='company-tax-source-v9' or facts.history_coverage.status!='complete':raise CompanyTaxError.unavailable()
    journals=tuple(tax_delivery_snapshot_journal(snapshot,row.draft) for row in snapshot.delivery_drafts)
    # Reserved synthetic reference namespace is persisted in the exact draft.
    # Provenance therefore survives expiry or removal of runtime composition.
    preparation_only = preparation_only or any(journal.draft.current_document is not None and
        journal.draft.current_document.document_reference.startswith('synthetic-private-preview-') for journal in journals)
    tip=tax_delivery_lineage(journals);dispatch_admissions=dispatch_admissions or {};correction_admissions=correction_admissions or {};validation=validation or {}
    terminals={j.draft.correction_parent.filing_id:j.draft.correction_parent.terminal for j in journals if j.draft.correction_parent is not None}
    rows=[];field_bytes=0;field_count=0
    read_actions={TaxDeliveryAction.RECONCILE_UPLOAD,TaxDeliveryAction.RECONCILE_VALIDATION,
        TaxDeliveryAction.RECONCILE_CONFIRMATION,TaxDeliveryAction.RECONCILE_SUBMISSION,TaxDeliveryAction.RECONCILE_FEEDBACK}
    for stored,journal in zip(snapshot.delivery_drafts,journals):
        draft=journal.draft;originals=tax_delivery_workspace_originals(journal)
        completed=next((e.value for e in journal.events if e.slot=='completion:confirm_submission'),None)
        terminal=terminals.get(draft.filing_id)
        if terminal is None and completed is not None:
            proof=completed.submission_read_evidence
            if proof is not None and proof.feedback is not None and proof.instance.inspection.archived is True:terminal=proof
        review=validation.get(draft.filing_id)
        if review is not None:
            if type(review) is not TaxDeliveryWorkspaceValidation:raise CompanyTaxError.unavailable()
            result=next((e.value for e in reversed(journal.events) if e.slot.startswith('observation:validation-result:')),None)
            if result is None:raise CompanyTaxError.unavailable()
            review.response.verify_original(result.original)
        inspection=None if review is None or review.calculated is None else review.calculated.inspection
        if inspection is not None:
            if type(inspection) is not TaxCalculatedDocumentsInspection:raise CompanyTaxError.unavailable()
            result=next((e.value for e in reversed(journal.events) if e.slot.startswith('observation:validation-result:')),None)
            if result is None:raise CompanyTaxError.unavailable()
            inspection.assert_original(result.original,draft)
        state,action=_stage(journal,inspection,'archived' if terminal is not None else _retained_receipt(journal))
        current=draft.envelope.source==source;actions=[]
        active=tip is None or tip==draft.filing_id
        if (active and dispatch_admissions.get(draft.filing_id) is True and action is not None
                and (current or action in read_actions)):actions.append(action)
        if active and completed is not None and correction_admissions.get(draft.filing_id) is True:actions.append(TaxDeliveryAction.PREPARE_CORRECTION)
        frozen=draft.envelope.source
        if draft.current_document is None:
            state='legacy_prepared';actions=[];fields=()
        else:
            candidate=build(_calculation_source(CompanyTaxReturnSource(frozen.organization_number,int(frozen.income_year),frozen.annual_data,
                frozen.ledger_entries,frozen.holding_actions,draft.current_document.party_number)),projection_version='company-tax-delivery-2025-v1')
            fields=tuple(TaxDeliveryWorkspaceField(str(item['authorityDocument']),str(item['path']),str(item['value']),str(item['source'])) for item in candidate['fields'])
        field_count+=len(fields);field_bytes+=sum(len((row.path+row.value+row.source+row.document).encode('utf-8')) for row in fields)
        if field_count>100000 or field_bytes>24*1024*1024:raise CompanyTaxError.unavailable()
        rows.append(TaxDeliveryWorkspaceRow(draft.filing_id,None if draft.correction_parent is None else draft.correction_parent.filing_id,
            stored.recorded_at,draft.sha256,draft.envelope.review_sha256,None if journal.approval is None else journal.approval.sha256,
            TaxDeliveryWorkspaceState(state),current,tuple(actions),fields,originals,review))
    return TaxDeliveryWorkspace(query.company_id,query.income_year,facts.evidence.digest,snapshot.as_of,
        preparation_available and tip is None,tuple(rows),preparation_only)
