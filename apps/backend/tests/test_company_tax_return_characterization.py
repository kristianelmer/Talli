"""Frozen predecessor outputs, exercised through Company Tax's public contract."""
from collections.abc import Mapping
import dataclasses
import json
from pathlib import Path

import pytest

from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxEvidenceInput, project_company_tax_evidence,
    CompanyTaxEnvelopeInput, CompanyTaxReturnSource, build_company_tax_return,
    estimate_annual_tax, render_company_tax_envelope, render_company_tax_return,
)

FIXTURE = json.loads((Path(__file__).resolve().parents[3] / 'architecture/evidence/issues/152/legacy-characterization.json').read_text())


def plain(value):
    if dataclasses.is_dataclass(value):
        return {field.name: plain(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {key: plain(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [plain(child) for child in value]
    return value


def source(value):
    return CompanyTaxReturnSource(
        organization_number=value['companyOrgNumber'], income_year=value['incomeYear'],
        annual_data=value['annualData'], ledger_entries=value['ledgerEntries'],
        holding_actions=value['holdingActions'], party_number=value.get('companyPartyNumber'),
    )


@pytest.mark.parametrize('case', FIXTURE['cases'], ids=lambda case: case['id'])
def test_preserves_payload_feedback_estimate_and_exact_xml_envelope_bytes(case):
    input = source(case['input'])
    candidate = build_company_tax_return(input)
    assert plain(candidate) == case['output']['payload']['value']
    estimate = estimate_annual_tax(input)
    assert {
        'adminCosts': estimate.admin_costs, 'interestIncome': estimate.interest_income,
        'fritaksmetodenAddBack': estimate.participation_exemption_add_back,
        'taxableShareSaleGain': estimate.taxable_share_sale_gain,
        'deductibleShareSaleLoss': estimate.deductible_share_sale_loss,
        'taxBasis': estimate.tax_basis, 'estimatedTax': estimate.estimated_tax, 'status': estimate.status,
    } == case['output']['annualEstimate']['value']
    expected_xml = case['output']['xml']
    if 'error' in expected_xml:
        with pytest.raises(ValueError) as error:
            render_company_tax_return(candidate)
        assert str(error.value) == expected_xml['error']['message']
        return
    documents = render_company_tax_return(candidate)
    assert documents.tax_return_xml == expected_xml['value']['skattemeldingXml']
    assert documents.business_specification_xml == expected_xml['value']['naeringsspesifikasjonXml']
    envelope = CompanyTaxEnvelopeInput(documents, input.organization_number, input.income_year, 'Synthetic & Talli <owner>')
    assert render_company_tax_envelope(envelope) == case['output']['validationEnvelope']['value']
    assert render_company_tax_envelope(dataclasses.replace(envelope, current_document_reference='synthetic-current-&-reference')) == case['output']['submissionEnvelope']['value']


def test_caller_mutation_cannot_change_source_or_candidate_facts():
    raw = json.loads(json.dumps(FIXTURE['cases'][0]['input']))
    input = source(raw)
    expected = build_company_tax_return(input)
    raw['holdingActions'][0]['payload']['gross_amount'] = 0
    raw['ledgerEntries'].clear()
    raw['annualData']['answers']['shareholder_loans'] = True
    assert build_company_tax_return(input) == expected
    with pytest.raises(TypeError):
        input.holding_actions[0]['payload']['gross_amount'] = 0
    with pytest.raises(TypeError):
        expected.fields[0]['value'] = 'changed'


IMPORT_BOUNDARIES = json.loads((Path(__file__).resolve().parents[3] / 'architecture/evidence/issues/152/legacy-import-boundaries.json').read_text())


@pytest.mark.parametrize('case', FIXTURE['evidenceCases'] + IMPORT_BOUNDARIES['cases'], ids=lambda case: case['id'])
def test_preserves_sanitized_evidence_projection_or_exact_rejection(case):
    raw = case['input']
    input = CompanyTaxEvidenceInput(
        company_id=raw['companyId'], expected_organization_number=raw['expectedCompanyOrgNumber'],
        expected_income_year=raw['expectedIncomeYear'], evidence=raw['evidence'], recorded_by=raw['recordedBy'],
        evidence_url=raw.get('evidenceUrl'), recorded_at=raw.get('recordedAt'),
    )
    if 'error' in case['output']:
        with pytest.raises(ValueError) as error:
            project_company_tax_evidence(input)
        assert str(error.value) == case['output']['error']['message']
    else:
        projection = project_company_tax_evidence(input)
        assert {'authorityRun': plain(projection.authority_run), 'submission': plain(projection.submission)} == case['output']['value']
        with pytest.raises(TypeError):
            projection.submission['calls'][0]['status'] = 'accepted'
