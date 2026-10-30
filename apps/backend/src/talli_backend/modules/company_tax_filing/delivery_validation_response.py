"""Offline inspection of exact validation-response XML, without filing authority.

The common response schema has no company, year or job identity. These facts
therefore cannot prove response scope, a clean scan, owner confirmation, Tax
submission or acceptance; a later known-job observation must bind that context.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .delivery import _digest
from .delivery_original import _bytes
from .delivery_observation import TaxDeliveryReadOriginal,TaxDeliveryOriginalPurpose


class TaxValidationResultCode(StrEnum):
    VALIDATED='validertOK'
    REJECTED='validertMedFeil'


_DOCUMENT_TYPES=frozenset({
    'skattemeldingPersonligEtterBeregning','beregnetSkattPersonlig','summertSkattegrunnlagForVisningPersonlig',
    'naeringsspesifikasjonEtterBeregning','skattemeldingUpersonligEtterBeregning','beregnetSkattUpersonlig',
    'beregnetSkattUpersonligSvalbard','summertSkattegrunnlagForVisningUpersonlig',
    'summertSkattegrunnlagForVisningUpersonligSvalbard','selskapsmeldingSdfEtterBeregning',
    'beregnetSkattPersonligSvalbard','summertSkattegrunnlagForVisningPersonligSvalbard',
    'beregnetSkattUpersonligPetroleum','summertSkattegrunnlagForVisningUpersonligPetroleum',
})


@dataclass(frozen=True,slots=True)
class TaxValidationCalculatedDocument:
    document_type: str
    body_base64: str

    def __post_init__(self):
        if type(self.document_type) is not str or self.document_type not in _DOCUMENT_TYPES:
            raise ValueError('Tax calculated document type is unknown.')
        _bytes(self.body_base64)

    @property
    def raw_bytes(self) -> bytes:return _bytes(self.body_base64)


@dataclass(frozen=True,slots=True)
class TaxValidationResponseInspection:
    schema_sha256: str
    original_sha256: str
    result_code: TaxValidationResultCode
    calculation_deviation_count: int
    validation_deviation_count: int
    guidance_count: int
    failure_reason_count: int
    calculated_documents: tuple[TaxValidationCalculatedDocument,...]

    def __post_init__(self):
        _digest(self.schema_sha256);_digest(self.original_sha256)
        if type(self.result_code) is not TaxValidationResultCode:
            raise ValueError('Tax validation result code is unknown.')
        if any(type(value) is not int or not 0<=value<=100000 for value in
            (self.calculation_deviation_count,self.validation_deviation_count,self.guidance_count,self.failure_reason_count)):
            raise ValueError('Tax response counts are invalid or exceed their bound.')
        if (type(self.calculated_documents) is not tuple or len(self.calculated_documents)>len(_DOCUMENT_TYPES)
                or any(type(value) is not TaxValidationCalculatedDocument for value in self.calculated_documents)
                or len({value.document_type for value in self.calculated_documents})!=len(self.calculated_documents)):
            raise ValueError('Tax calculated documents are missing types or ambiguous.')

    def verify_original(self,original: TaxDeliveryReadOriginal) -> None:
        if (type(original) is not TaxDeliveryReadOriginal
                or original.purpose is not TaxDeliveryOriginalPurpose.VALIDATION_RESULT
                or original.sha256!=self.original_sha256):
            raise ValueError('Tax response inspection does not bind the exact original.')
