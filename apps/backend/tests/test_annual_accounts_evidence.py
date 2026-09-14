"""Immutable evidence import compared with the pinned released implementation."""
from dataclasses import asdict, FrozenInstanceError
import json
from pathlib import Path

import pytest
import icu

from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsEvidenceInput, import_annual_accounts_evidence,
)

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / 'architecture/evidence/issues/153'
CASES = json.loads((EVIDENCE / 'characterization/legacy-pure-characterization.json').read_text())['evidenceCases']
DATE_CAPTURE = json.loads((EVIDENCE / 'evidence-import/legacy-import-dates.json').read_text())
DATES = DATE_CAPTURE['cases']


def request(value):
    return AnnualAccountsEvidenceInput(value['companyId'], value['expectedCompanyOrgNumber'],
        value['evidence'], value['recordedBy'], value['recordedAt'], value.get('evidenceUrl'))


def capture(value):
    try:
        return {'value': asdict(import_annual_accounts_evidence(request(value)))}
    except ValueError as error:
        return {'error': {'name': 'Error', 'message': str(error)}}


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_evidence_projection_matches_released_output_and_first_rejection(case):
    assert capture(case['input']) == case['output']


@pytest.mark.parametrize('case', DATES, ids=lambda case: repr(case['input']))
def test_evidence_date_acceptance_matches_pinned_node(case):
    value = json.loads(json.dumps(CASES[0]['input']))
    value['evidence']['submission']['processEndedAt'] = case['input']
    result = capture(value)
    assert ('value' in result) == case['valid']
    if not case['valid']:
        assert result['error']['message'] == case['error']


@pytest.mark.parametrize('group', DATE_CAPTURE['boundaries'], ids=lambda group: group['zone'])
def test_local_and_explicit_zone_dates_at_timeclip_endpoints(group):
    original = icu.TimeZone.createDefault()
    try:
        icu.TimeZone.setDefault(icu.TimeZone.createTimeZone(group['zone']))
        for case in group['cases']:
            value = json.loads(json.dumps(CASES[0]['input']))
            value['evidence']['submission']['processEndedAt'] = case['input']
            result = capture(value)
            assert ('value' in result) == case['valid'], case['input']
    finally:
        icu.TimeZone.setDefault(original)


def test_evidence_contract_copies_input_and_never_implies_acceptance():
    value = json.loads(json.dumps(CASES[0]['input']))
    frozen = request(value)
    value['evidence']['productionEnabled'] = True
    result = import_annual_accounts_evidence(frozen)
    assert result.status == 'pending'
    assert result.environment == 'test'
    with pytest.raises(TypeError):
        frozen.evidence['submission']['archived'] = False
    with pytest.raises(FrozenInstanceError):
        result.status = 'accepted'
