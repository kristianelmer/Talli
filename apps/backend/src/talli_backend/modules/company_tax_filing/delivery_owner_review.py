"""Exact owner-review artifact for a known prepared confirmation stage.

The artifact has no observation timestamp in its content identity. Refreshing an
unchanged review therefore keeps the same commitment. Current source/access and
the later explicit owner action remain separate application requirements.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IncomeYear,CorrelationId,UserId
from .delivery import _digest,_json
from .delivery_draft import TaxDeliveryDraft,_canonical
from .delivery_approval import TaxDeliveryReviewApproval
from .delivery_original import _uuid
from .delivery_calculated_documents import TaxCalculatedDocumentsInspection,CALCULATED_SUPPORTED_TYPES
from .delivery_journal import TaxDeliveryMutationRequest,TaxDeliveryMutationCompletion
from .delivery_validation_result import TaxDeliveryValidationResultObservation
from .delivery_validation_review import TaxValidationResponseReview,_text
from .delivery_observation import TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose


@dataclass(frozen=True,slots=True)
class TaxCalculatedReviewField:
    path: str
    value: str

    def __post_init__(self):
        if type(self.path) is not str or not self.path.startswith('/') or len(self.path.encode('utf-8'))>16384:
            raise ValueError('Tax calculated review field path is invalid.')
        _text(self.value,optional=False)


@dataclass(frozen=True,slots=True)
class TaxCalculatedDocumentReview:
    document_type: str
    original_sha256: str
    fields: tuple[TaxCalculatedReviewField,...]

    def __post_init__(self):
        _digest(self.original_sha256)
        if (type(self.document_type) is not str or self.document_type not in CALCULATED_SUPPORTED_TYPES
                or type(self.fields) is not tuple or not 1<=len(self.fields)<=100000
                or any(type(value) is not TaxCalculatedReviewField for value in self.fields)
                or len({value.path for value in self.fields})!=len(self.fields)):
            raise ValueError('Tax calculated document review is incomplete or ambiguous.')


@dataclass(frozen=True,slots=True)
class TaxCalculatedDocumentsReview:
    inspection: TaxCalculatedDocumentsInspection
    documents: tuple[TaxCalculatedDocumentReview,...]

    def __post_init__(self):
        if (type(self.inspection) is not TaxCalculatedDocumentsInspection or type(self.documents) is not tuple
                or len(self.documents)!=len(self.inspection.response.calculated_documents)
                or any(type(value) is not TaxCalculatedDocumentReview for value in self.documents)):
            raise ValueError('Tax review cannot omit or replace a calculated document.')
        for review,original in zip(self.documents,self.inspection.response.calculated_documents):
            if review.document_type!=original.document_type or review.original_sha256!=hashlib.sha256(original.raw_bytes).hexdigest():
                raise ValueError('Tax review differs from its exact calculated document original.')


@dataclass(frozen=True,slots=True)
class TaxDeliveryOwnerReviewQuery:
    company_id: CompanyId
    income_year: IncomeYear
    actor_id: ActorId
    filing_id: str
    expected_approval_sha256: str
    correlation_id: CorrelationId

    def __post_init__(self):
        _uuid(self.filing_id);_digest(self.expected_approval_sha256)
        if (type(self.company_id) is not CompanyId or type(self.income_year) is not IncomeYear
                or type(self.income_year.value) is not int or int(self.income_year)!=2025
                or type(self.actor_id) is not ActorId or self.actor_id.kind is not ActorKind.USER
                or type(self.actor_id.subject) is not UserId or type(self.correlation_id) is not CorrelationId):
            raise ValueError('Tax owner review query scope is invalid.')


@dataclass(frozen=True,slots=True)
class TaxDeliveryOwnerReview:
    approval: TaxDeliveryReviewApproval
    preparation_request_sha256: str
    preparation_result_sha256: str
    source_sha256: str
    calculated: TaxCalculatedDocumentsReview
    response: TaxValidationResponseReview
    response_original: TaxDeliveryReadOriginal

    def __post_init__(self):
        _digest(self.preparation_request_sha256);_digest(self.preparation_result_sha256);_digest(self.source_sha256)
        if (type(self.approval) is not TaxDeliveryReviewApproval or type(self.calculated) is not TaxCalculatedDocumentsReview
                or type(self.response) is not TaxValidationResponseReview
                or type(self.response_original) is not TaxDeliveryReadOriginal
                or self.response_original.purpose is not TaxDeliveryOriginalPurpose.VALIDATION_RESULT
                or self.calculated.inspection.response!=self.response.inspection
                or self.calculated.inspection.draft_sha256!=self.approval.draft_sha256
                or self.calculated.inspection.company_id!=self.approval.company_id
                or self.calculated.inspection.income_year!=self.approval.income_year
                or self.source_sha256!=self.approval.source_sha256):
            raise ValueError('Tax owner review is not bound to the retained approval and exact response.')
        self.response.verify_original(self.response_original)

    @property
    def canonical_value(self):
        # Retain the complete response and its decoded calculated originals.
        # Projection fields never substitute for original XML bytes.
        inspection=self.calculated.inspection
        return {'approval':_json(self.approval),'preparation_request_sha256':self.preparation_request_sha256,
            'preparation_result_sha256':self.preparation_result_sha256,'source_sha256':self.source_sha256,
            'calculated_context':{name:_json(getattr(inspection,name)) for name in
                ('schema_sha256','draft_sha256','company_id','income_year','party_number')},
            'documents':_json(self.calculated.documents),'response':_json(self.response),
            'response_original':_json(self.response_original)}

    @property
    def canonical_json(self):
        raw=_canonical({'version':'company-tax-delivery-owner-review-v1','review':self.canonical_value})
        if len(raw.encode('utf-8'))>24*1024*1024:raise ValueError('Tax owner review exceeds its complete-artifact bound.')
        return raw

    @property
    def sha256(self):return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()


def build_tax_delivery_owner_review(approval: TaxDeliveryReviewApproval,draft: TaxDeliveryDraft,
        request: TaxDeliveryMutationRequest,prepared: TaxDeliveryMutationCompletion,result: TaxDeliveryValidationResultObservation,
        *,calculated: TaxCalculatedDocumentsReview,response: TaxValidationResponseReview) -> TaxDeliveryOwnerReview:
    if (type(request) is not TaxDeliveryMutationRequest or request.confirmation_prerequisite is None
            or type(prepared) is not TaxDeliveryMutationCompletion or prepared.confirmation_read_evidence is None
            or type(result) is not TaxDeliveryValidationResultObservation
            or type(calculated) is not TaxCalculatedDocumentsReview or type(response) is not TaxValidationResponseReview):
        raise ValueError('Tax owner review needs complete known preparation and response originals.')
    request.assert_draft(approval,draft);prepared.assert_request(request,approval)
    proof=request.confirmation_prerequisite
    if (result.sha256!=proof.result_read.event_sha256 or result.evidence_sha256!=proof.result_read.evidence_sha256
            or calculated.inspection!=proof.calculated or calculated.inspection.response!=response.inspection):
        raise ValueError('Tax owner review differs from the exact prepared calculation response.')
    calculated.inspection.assert_original(result.original,draft);response.verify_original(result.original)
    return TaxDeliveryOwnerReview(approval,request.sha256,prepared.sha256,draft.envelope.source.source_sha256,calculated,response,result.original)
