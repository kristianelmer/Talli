"""Exact document-review approval bound to independently refreshed Tax inputs.

The first delivery lane is a finite loopback rehearsal. This value records the
review commitment; runtime admission, current owner/MFA and persistence remain
separate requirements. It grants no paid entitlement or live filing authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from uuid import UUID

from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, IncomeYear, UserId
from .current_document import TaxCurrentDocument
from .delivery import TaxDeliverySource, _digest, _json, verify_tax_review
from .delivery_draft import TaxDeliveryDraft, _canonical, _object


class TaxDeliveryAuthorityMode(StrEnum):
    FINITE_LOOPBACK = 'finite_loopback_rehearsal'


@dataclass(frozen=True, slots=True)
class TaxDeliveryReviewApproval:
    approval_id: str
    filing_id: str
    company_id: CompanyId
    income_year: IncomeYear
    approved_by: ActorId
    draft_sha256: str
    review_sha256: str
    source_sha256: str
    schema_sha256: str
    current_original_sha256: str
    authority_mode: TaxDeliveryAuthorityMode
    authority_context_sha256: str

    def __post_init__(self):
        if (type(self.approval_id) is not str or str(UUID(self.approval_id)) != self.approval_id
                or type(self.filing_id) is not str or str(UUID(self.filing_id)) != self.filing_id
                or type(self.company_id) is not CompanyId or type(self.income_year) is not IncomeYear
                or type(self.income_year.value) is not int or int(self.income_year) != 2025
                or type(self.approved_by) is not ActorId or self.approved_by.kind is not ActorKind.USER
                or type(self.approved_by.subject) is not UserId
                or type(self.authority_mode) is not TaxDeliveryAuthorityMode):
            raise ValueError('Tax review approval identity is invalid.')
        for value in (self.draft_sha256,self.review_sha256,self.source_sha256,self.schema_sha256,
                      self.current_original_sha256,self.authority_context_sha256):
            _digest(value)

    @property
    def canonical_json(self) -> str:
        return _canonical({'version':'company-tax-delivery-review-approval-v1','approval':_json(self)})

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()

    def assert_draft(self, draft: TaxDeliveryDraft) -> None:
        if (type(draft) is not TaxDeliveryDraft or draft.current_document is None
                or self.filing_id != draft.filing_id or self.company_id != draft.envelope.source.company_id
                or self.income_year != draft.envelope.source.income_year or self.draft_sha256 != draft.sha256
                or self.review_sha256 != draft.envelope.review_sha256
                or self.source_sha256 != draft.envelope.source.source_sha256
                or self.schema_sha256 != draft.envelope.schema_sha256
                or self.current_original_sha256 != draft.current_document.response.sha256):
            raise ValueError('Tax review approval does not bind the retained draft.')


def approve_tax_delivery_review(*, approval_id: str, draft: TaxDeliveryDraft, approved_by: ActorId,
        expected_draft_sha256: str, expected_review_sha256: str, current_source: TaxDeliverySource,
        current_document: TaxCurrentDocument, current_schema_sha256: str,
        authority_mode: TaxDeliveryAuthorityMode, authority_context_sha256: str) -> TaxDeliveryReviewApproval:
    """Bind the reviewed artifact only after independently current inputs match.

    The application supplies a freshly inspected authority response and a source
    snapshot protected through persistence. A new observation timestamp is fine;
    changed original bytes or interpreted identity are not silently approved.
    """
    if (type(draft) is not TaxDeliveryDraft or draft.current_document is None
            or type(current_document) is not TaxCurrentDocument
            or _digest(expected_draft_sha256) != draft.sha256):
        raise ValueError('Tax reviewed draft is missing or changed.')
    verify_tax_review(draft.envelope,expected_review_sha256=expected_review_sha256,
        current_source=current_source,current_schema_sha256=current_schema_sha256,
        current_document_reference=current_document.document_reference)
    prior=draft.current_document
    if (current_document.response.sha256 != prior.response.sha256
            or current_document.response.organization_number != prior.response.organization_number
            or current_document.response.income_year != prior.response.income_year
            or current_document.document_reference != prior.document_reference
            or current_document.document_kind != prior.document_kind
            or current_document.party_number != prior.party_number
            or current_document.tax_xml_sha256 != prior.tax_xml_sha256
            or current_document.schema_sha256 != prior.schema_sha256):
        raise ValueError('Tax authority original changed after review.')
    result=TaxDeliveryReviewApproval(approval_id,draft.filing_id,draft.envelope.source.company_id,
        draft.envelope.source.income_year,approved_by,draft.sha256,draft.envelope.review_sha256,
        current_source.source_sha256,current_schema_sha256,current_document.response.sha256,
        authority_mode,authority_context_sha256)
    result.assert_draft(draft)
    return result


def decode_tax_delivery_review_approval(raw: str, expected_sha256: str) -> TaxDeliveryReviewApproval:
    def pairs(items):
        value={}
        for key,child in items:
            if key in value:raise ValueError('Duplicate Tax approval key.')
            value[key]=child
        return value

    def constant(_value):
        raise ValueError('Nonfinite Tax approval value.')

    try:
        if (type(raw) is not str or len(raw.encode('utf-8')) > 16384
                or _digest(expected_sha256) != hashlib.sha256(raw.encode('utf-8')).hexdigest()):
            raise ValueError()
        value=_object(json.loads(raw,object_pairs_hook=pairs,parse_constant=constant),('version','approval'))
        if value['version']!='company-tax-delivery-review-approval-v1':raise ValueError()
        body=_object(value['approval'],('approval_id','filing_id','company_id','income_year','approved_by',
            'draft_sha256','review_sha256','source_sha256','schema_sha256','current_original_sha256',
            'authority_mode','authority_context_sha256'))
        company=_object(body['company_id'],('value',))
        year=_object(body['income_year'],('value',))
        actor=_object(body['approved_by'],('kind','subject'))
        subject=_object(actor['subject'],('value',))
        result=TaxDeliveryReviewApproval(**(body|{'company_id':CompanyId(company['value']),
            'income_year':IncomeYear(year['value']),
            'approved_by':ActorId(ActorKind(actor['kind']),UserId(subject['value'])),
            'authority_mode':TaxDeliveryAuthorityMode(body['authority_mode'])}))
        if result.canonical_json != raw:raise ValueError()
        return result
    except (ValueError,TypeError,KeyError,AttributeError,RecursionError,OverflowError):
        raise ValueError('Retained Tax review approval is invalid or its exact bytes changed.') from None
