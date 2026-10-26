"""Explicit owner decision about one complete calculated review.

This value belongs inside the separately committed submission intent. It is not
an approval inferred from preparation, a read, or a successful process response.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .delivery import _digest
from .delivery_draft import _object

if TYPE_CHECKING:
    from .delivery_owner_review import TaxDeliveryOwnerReview


@dataclass(frozen=True,slots=True)
class TaxDeliveryOwnerConfirmation:
    owner_review_sha256: str
    preparation_request_sha256: str
    preparation_result_sha256: str
    response_original_sha256: str
    documents_confirmed: bool
    warnings_acknowledged: bool

    def __post_init__(self):
        for value in (self.owner_review_sha256,self.preparation_request_sha256,
                self.preparation_result_sha256,self.response_original_sha256):_digest(value)
        if (type(self.documents_confirmed) is not bool or self.documents_confirmed is not True
                or type(self.warnings_acknowledged) is not bool or self.warnings_acknowledged is not True):
            raise ValueError('Tax submission needs explicit document confirmation and warning acknowledgment.')

    def assert_preparation(self,approval,draft,request,prepared):
        from .delivery_journal import TaxDeliveryMutationRequest,TaxDeliveryMutationCompletion
        if (type(request) is not TaxDeliveryMutationRequest or request.confirmation_prerequisite is None
                or type(prepared) is not TaxDeliveryMutationCompletion or prepared.confirmation_read_evidence is None
                or request.sha256!=self.preparation_request_sha256 or prepared.sha256!=self.preparation_result_sha256
                or request.confirmation_prerequisite.calculated.response.original_sha256!=self.response_original_sha256):
            raise ValueError('Tax owner confirmation differs from its known preparation and calculated response.')
        request.assert_draft(approval,draft);prepared.assert_request(request,approval)


def confirm_tax_delivery_owner_review(review: TaxDeliveryOwnerReview,*,expected_owner_review_sha256: str,
        documents_confirmed: bool,warnings_acknowledged: bool) -> TaxDeliveryOwnerConfirmation:
    from .delivery_owner_review import TaxDeliveryOwnerReview
    if type(review) is not TaxDeliveryOwnerReview or _digest(expected_owner_review_sha256)!=review.sha256:
        raise ValueError('Tax owner confirmation refers to a missing or changed complete review.')
    return TaxDeliveryOwnerConfirmation(review.sha256,review.preparation_request_sha256,
        review.preparation_result_sha256,review.response_original.sha256,documents_confirmed,warnings_acknowledged)


def _decode_owner_confirmation(value):
    value=_object(value,('owner_review_sha256','preparation_request_sha256','preparation_result_sha256',
        'response_original_sha256','documents_confirmed','warnings_acknowledged'))
    return TaxDeliveryOwnerConfirmation(**value)
