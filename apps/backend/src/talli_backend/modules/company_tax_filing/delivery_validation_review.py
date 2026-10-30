"""Complete owner-review text derived from one exact validation response.

Kept separate from the frozen count-only inspection and V4 request bytes. XML
normalizes character data; exact encoded response/document originals remain the
evidence. This projection grants no readiness, confirmation or filing authority.
"""
from __future__ import annotations

from dataclasses import dataclass,fields
import hashlib

from .delivery import _json
from .delivery_draft import _canonical
from .delivery_observation import TaxDeliveryReadOriginal
from .delivery_validation_response import TaxValidationResponseInspection


def _text(value,*,optional=True):
    if value is None and optional:return
    if type(value) is not str or len(value.encode('utf-8'))>8*1024*1024:
        raise ValueError('Tax review text is invalid or exceeds the original-byte bound.')


@dataclass(frozen=True,slots=True)
class TaxValidationDeviation:
    type_code: str
    occurrence_id: str | None=None
    received_value: str | None=None
    calculated_value: str | None=None
    difference_value: str | None=None
    received_text: str | None=None
    calculated_text: str | None=None
    path: str | None=None
    additional_info: str | None=None

    def __post_init__(self):
        for item in fields(self):_text(getattr(self,item.name),optional=item.name!='type_code')


@dataclass(frozen=True,slots=True)
class TaxValidationGuidance:
    type_code: str
    occurrence_id: str | None=None
    message: str | None=None
    servicing_strategy: str | None=None
    path: str | None=None

    def __post_init__(self):
        for item in fields(self):_text(getattr(self,item.name),optional=item.name!='type_code')


TAX_COMPANY_SUBJECT_FLAGS=frozenset({'erFritattForFormuesskatt','erOmfattetAvSaerreglerForKraftforetak',
    'erOmfattetAvPetroleumsskatteloven','erOmfattetAvRederiskatteordningen',
    'erOmfattetAvFinansskattPaaLoennOgOverskudd','harLeveringsfritak'})


@dataclass(frozen=True,slots=True)
class TaxValidationSubjectFlag:
    name: str
    value: bool

    def __post_init__(self):
        if type(self.name) is not str or self.name not in TAX_COMPANY_SUBJECT_FLAGS or type(self.value) is not bool:
            raise ValueError('Tax company subject flag is unsupported.')


@dataclass(frozen=True,slots=True)
class TaxValidationResponseReview:
    inspection: TaxValidationResponseInspection
    calculation_deviations: tuple[TaxValidationDeviation,...]
    validation_deviations: tuple[TaxValidationDeviation,...]
    guidance: tuple[TaxValidationGuidance,...]
    failure_reasons: tuple[str,...]
    subject_flags: tuple[TaxValidationSubjectFlag,...]

    def __post_init__(self):
        if type(self.inspection) is not TaxValidationResponseInspection:raise ValueError('Tax review has no response inspection.')
        for values,expected,count in (
            (self.calculation_deviations,TaxValidationDeviation,self.inspection.calculation_deviation_count),
            (self.validation_deviations,TaxValidationDeviation,self.inspection.validation_deviation_count),
            (self.guidance,TaxValidationGuidance,self.inspection.guidance_count),
            (self.failure_reasons,str,self.inspection.failure_reason_count)):
            if type(values) is not tuple or len(values)!=count or any(type(value) is not expected for value in values):
                raise ValueError('Tax review must preserve every counted deviation, guidance and failure.')
        for reason in self.failure_reasons:_text(reason,optional=False)
        if (type(self.subject_flags) is not tuple or len(self.subject_flags)>len(TAX_COMPANY_SUBJECT_FLAGS)
                or any(type(value) is not TaxValidationSubjectFlag for value in self.subject_flags)
                or len({value.name for value in self.subject_flags})!=len(self.subject_flags)):
            raise ValueError('Tax review company subject flags are incomplete or ambiguous.')

    @property
    def canonical_json(self):
        return _canonical({'version':'company-tax-validation-response-review-v1','review':_json(self)})

    @property
    def sha256(self):return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()

    def verify_original(self,original: TaxDeliveryReadOriginal):self.inspection.verify_original(original)
