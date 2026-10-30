"""Derived calculated-document inspection; never a submission permission.

The raw response remains the evidence. This projection binds the two statutory
documents and any supported display documents to one retained draft. A tax
calculation has no intrinsic party/year fields; its context comes from the
known-job response and the scope-bearing statutory pair, not an invented field.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib

from talli_backend.shared.kernel import CompanyId,IncomeYear
from .delivery import _digest,_json
from .delivery_draft import TaxDeliveryDraft,_canonical
from .delivery_observation import TaxDeliveryReadOriginal
from .delivery_validation_response import TaxValidationResponseInspection
from .delivery_validation_response import TaxValidationCalculatedDocument,TaxValidationResultCode
from .delivery_draft import _object


CALCULATED_STATUTORY_TYPES=frozenset({'skattemeldingUpersonligEtterBeregning','naeringsspesifikasjonEtterBeregning'})
CALCULATED_SUPPORTED_TYPES=CALCULATED_STATUTORY_TYPES|frozenset({
    'beregnetSkattUpersonlig','summertSkattegrunnlagForVisningUpersonlig'})


@dataclass(frozen=True,slots=True)
class TaxCalculatedDocumentsInspection:
    schema_sha256: str
    draft_sha256: str
    company_id: CompanyId
    income_year: IncomeYear
    party_number: str
    response: TaxValidationResponseInspection

    def __post_init__(self):
        _digest(self.schema_sha256);_digest(self.draft_sha256)
        if (type(self.company_id) is not CompanyId or type(self.income_year) is not IncomeYear
                or type(self.income_year.value) is not int or int(self.income_year)!=2025
                or type(self.party_number) is not str or not self.party_number
                or type(self.response) is not TaxValidationResponseInspection):
            raise ValueError('Tax calculated-document inspection scope is invalid.')
        kinds={item.document_type for item in self.response.calculated_documents}
        if not CALCULATED_STATUTORY_TYPES<=kinds<=CALCULATED_SUPPORTED_TYPES:
            raise ValueError('Tax calculated documents are incomplete or unsupported.')

    @property
    def canonical_json(self) -> str:
        return _canonical({'version':'company-tax-calculated-documents-inspection-v1','inspection':_json(self)})

    @property
    def sha256(self) -> str:return hashlib.sha256(self.canonical_json.encode('utf-8')).hexdigest()

    def assert_original(self,original: TaxDeliveryReadOriginal,draft: TaxDeliveryDraft) -> None:
        self.response.verify_original(original)
        if (type(draft) is not TaxDeliveryDraft or draft.current_document is None
                or self.draft_sha256!=draft.sha256 or self.company_id!=draft.envelope.source.company_id
                or self.income_year!=draft.envelope.source.income_year
                or self.party_number!=draft.current_document.party_number):
            raise ValueError('Tax calculated documents differ from the retained draft scope.')


def _decode_calculated_inspection(value):
    body=_object(value,('schema_sha256','draft_sha256','company_id','income_year','party_number','response'))
    company=_object(body['company_id'],('value',));year=_object(body['income_year'],('value',))
    response=_object(body['response'],('schema_sha256','original_sha256','result_code','calculation_deviation_count',
        'validation_deviation_count','guidance_count','failure_reason_count','calculated_documents'))
    if type(response['calculated_documents']) is not list:raise ValueError('Tax calculated documents shape is invalid.')
    documents=tuple(TaxValidationCalculatedDocument(**_object(item,('document_type','body_base64')))
        for item in response['calculated_documents'])
    return TaxCalculatedDocumentsInspection(**(body|{'company_id':CompanyId(company['value']),
        'income_year':IncomeYear(year['value']),'response':TaxValidationResponseInspection(**(response|{
            'result_code':TaxValidationResultCode(response['result_code']),'calculated_documents':documents}))}))
