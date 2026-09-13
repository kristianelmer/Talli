"""Fixed CLI transport mapping to Company Tax's owned pure contracts."""
from __future__ import annotations

from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxEnvelopeInput, CompanyTaxReturnDocuments, CompanyTaxReturnSource,
    prepare_company_tax_return, render_company_tax_envelope, summarize_company_tax_validation,
)


def generate(operation, value):
    if operation == 'company_tax':
        prepared = prepare_company_tax_return(CompanyTaxReturnSource(
            organization_number=value['companyOrgNumber'], income_year=value['incomeYear'],
            annual_data=value['annualData'], ledger_entries=value['ledgerEntries'],
            holding_actions=value['holdingActions'], party_number=value.get('companyPartyNumber'),
        ))
        return {'skattemeldingXml': prepared.documents.tax_return_xml,
                'naeringsspesifikasjonXml': prepared.documents.business_specification_xml,
                'feedback': [dict(item) for item in prepared.feedback]}
    if operation in ('company_tax_envelope', 'company_tax_validation_envelope'):
        envelope = CompanyTaxEnvelopeInput(
            documents=CompanyTaxReturnDocuments(value['skattemeldingXml'], value['naeringsspesifikasjonXml']),
            organization_number=value['companyOrgNumber'], income_year=value['incomeYear'],
            created_by=value['createdBy'],
            # JSON null is present-but-empty; None in the public contract means
            # omitted. Preserve presence so Tax's required-reference check runs.
            current_document_reference=('' if 'currentDocumentReference' in value
                                        and value['currentDocumentReference'] is None
                                        else value.get('currentDocumentReference')),
        )
        return {'envelopeXml': render_company_tax_envelope(envelope)}
    if operation == 'company_tax_validation_summary':
        summary = summarize_company_tax_validation(value['resultXml'])
        return {'result': summary.result, 'deviationCodes': list(summary.deviation_codes),
                'guidanceCodes': list(summary.guidance_codes), 'failureReasons': list(summary.failure_reasons)}
    raise ValueError('Unknown fixed payload operation.')
