"""Fixed test-only JSON driver for the real Company Tax public contracts.

This lets existing cross-output web fixtures exercise the owned Python policy.
It has no network, provider, persistence, dynamic module or file dispatch.
"""
from collections.abc import Mapping
import dataclasses
import json
import math
import sys

from talli_backend.modules.company_tax_filing.public import (
    AnnualTaxEstimateSource, CompanyTaxEvidenceInput, CompanyTaxReturnCandidate,
    CompanyTaxReturnSource, build_company_tax_return, estimate_annual_tax,
    project_company_tax_evidence, render_company_tax_return,
)


def plain(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if dataclasses.is_dataclass(value):
        return {field.name: plain(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def invoke(operation, value):
    if operation == 'payload':
        return build_company_tax_return(CompanyTaxReturnSource(
            organization_number=value['companyOrgNumber'], income_year=value['incomeYear'],
            annual_data=value['annualData'], ledger_entries=value['ledgerEntries'],
            holding_actions=value['holdingActions'], party_number=value.get('companyPartyNumber'),
        ))
    if operation == 'estimate':
        estimate = estimate_annual_tax(AnnualTaxEstimateSource(
            ledger_entries=value['ledgerEntries'], holding_actions=value['holdingActions']))
        return {'adminCosts': estimate.admin_costs, 'interestIncome': estimate.interest_income,
                'fritaksmetodenAddBack': estimate.participation_exemption_add_back,
                'taxableShareSaleGain': estimate.taxable_share_sale_gain,
                'deductibleShareSaleLoss': estimate.deductible_share_sale_loss,
                'taxBasis': estimate.tax_basis, 'estimatedTax': estimate.estimated_tax,
                'status': estimate.status}
    if operation == 'render':
        documents = render_company_tax_return(CompanyTaxReturnCandidate({}, {}, value, ()))
        return {'skattemeldingXml': documents.tax_return_xml,
                'naeringsspesifikasjonXml': documents.business_specification_xml}
    if operation == 'evidence':
        projected = project_company_tax_evidence(CompanyTaxEvidenceInput(
            company_id=value['companyId'], expected_organization_number=value['expectedCompanyOrgNumber'],
            expected_income_year=value['expectedIncomeYear'], evidence=value['evidence'],
            recorded_by=value['recordedBy'], recorded_at=value.get('recordedAt'),
            evidence_url=value.get('evidenceUrl'),
        ))
        return {'authorityRun': projected.authority_run, 'submission': projected.submission}
    raise ValueError('Unknown fixed Tax test operation.')


if __name__ == '__main__':
    try:
        raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('Tax fixture exceeds the test-driver input limit.')
        request = json.loads(raw)
        response = {'value': plain(invoke(request['operation'], request['input']))}
    except Exception as error:
        response = {'error': str(error)}
    print(json.dumps(response, ensure_ascii=True, allow_nan=False))
