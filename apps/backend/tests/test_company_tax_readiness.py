"""Tax-only annual readiness matches the unchanged predecessor's exact issues."""
from dataclasses import asdict, FrozenInstanceError
import json
from pathlib import Path

import pytest

from talli_backend.modules.company_tax_filing.public import CompanyTaxReturnSource, assess_company_tax_readiness

CAPTURE = json.loads((Path(__file__).resolve().parents[3] / 'architecture/evidence/issues/152/legacy-tax-readiness.json').read_text())


def source(value):
    return CompanyTaxReturnSource(
        organization_number=value['companyOrgNumber'], income_year=value['incomeYear'],
        annual_data=value['annualData'], ledger_entries=value['ledgerEntries'], holding_actions=value['holdingActions'],
        party_number=value.get('companyPartyNumber'),
    )


@pytest.mark.parametrize('case', CAPTURE['cases'], ids=lambda case: case['id'])
def test_owned_tax_readiness_preserves_exact_codes_messages_order_and_acceptance(case):
    issues = assess_company_tax_readiness(source(case['input']), company_id=case['input']['company']['id'])
    assert [asdict(issue) for issue in issues] == case['output']


def test_tax_readiness_snapshot_is_immutable_and_does_not_mutate_source():
    value = json.loads(json.dumps(CAPTURE['cases'][0]['input']))
    snapshot = source(value)
    expected = assess_company_tax_readiness(snapshot, company_id=value['company']['id'])
    value['annualData']['no_activity_confirmed'] = True
    value['holdingActions'].clear()
    assert assess_company_tax_readiness(snapshot, company_id=value['company']['id']) == expected
    with pytest.raises(FrozenInstanceError):
        expected[0].accepted = True

from fastapi.testclient import TestClient
from talli_backend.main import create_app
from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.shared.kernel import ActorId, ActorKind, UserId

COMPANY = '00000000-0000-0000-0000-000000000152'


class PreviewSessions:
    actor_id = ActorId(ActorKind.USER, UserId('00000000-0000-0000-0000-000000000153'))

    async def session(self, token):
        if token != 'fixture':
            raise LedgerAuthenticationError()
        return self

    def transaction(self):
        raise AssertionError('A caller-supplied assessment preview must not persist or attest source history.')


@pytest.fixture(scope='module')
def preview_client():
    return TestClient(create_app(company_tax_session_factory=PreviewSessions()))


@pytest.mark.parametrize('case', CAPTURE['cases'], ids=lambda case: case['id'])
def test_generated_readiness_route_preserves_the_scoped_preview_issues(preview_client, case):
    value = json.loads(json.dumps(case['input']).replace('company-id', COMPANY))
    body = {key: value[key] for key in ('annualData', 'ledgerEntries', 'holdingActions')}
    body.update(companyId=COMPANY, incomeYear=int(value['incomeYear']))
    response = preview_client.post('/api/v1/company-tax/readiness-previews', json=body, headers={'Authorization': 'Bearer fixture'})
    assert response.status_code == 200, response.text
    assert response.json() == {'companyId': COMPANY, 'incomeYear': body['incomeYear'], 'issues': case['output']}


PURE_CASES = sum((json.loads((Path(__file__).resolve().parents[3] / f'architecture/evidence/issues/152/{name}').read_text())['cases']
                  for name in ('legacy-characterization.json', 'legacy-review-boundaries.json')), [])


@pytest.mark.parametrize('case', PURE_CASES, ids=lambda case: case['id'])
def test_generated_estimate_route_preserves_ordered_cross_company_aggregation(preview_client, case):
    body = {key: case['input'][key] for key in ('ledgerEntries', 'holdingActions')}
    expected = case['output']['annualEstimate']['value']
    response = preview_client.post('/api/v1/company-tax/annual-estimate-previews', json=body, headers={'Authorization': 'Bearer fixture'})
    if any(value is None for value in expected.values()):
        # Nonfinite legacy values cannot be displayed as monetary estimates.
        assert response.status_code == 422
        assert response.json()['code'] == 'COMPANY_TAX_INVALID_INPUT'
    else:
        assert response.status_code == 200, response.text
        assert response.json() == expected


@pytest.mark.parametrize('path,body', [
    ('readiness-previews', {'companyId': COMPANY, 'incomeYear': 2025, 'annualData': None, 'ledgerEntries': [], 'holdingActions': []}),
    ('annual-estimate-previews', {'ledgerEntries': [], 'holdingActions': []}),
])
def test_assessment_preview_requires_authentication_without_any_persistence(preview_client, path, body):
    for headers in ({}, {'Authorization': 'Bearer invalid'}):
        response = preview_client.post(f'/api/v1/company-tax/{path}', json=body, headers=headers)
        assert response.status_code == 401


@pytest.mark.parametrize('change', [
    {'ledgerEntries': {}}, {'holdingActions': 'invalid'},
    {'ledgerEntries': [{'entry_type': 'admin_cost', 'lines': None}]},
    {'holdingActions': [{'action_type': 'share_sale', 'payload': None}]},
])
def test_malformed_preview_facts_are_rejected(preview_client, change):
    response = preview_client.post('/api/v1/company-tax/annual-estimate-previews',
        json={'ledgerEntries': [], 'holdingActions': [], **change}, headers={'Authorization': 'Bearer fixture'})
    assert response.status_code == 422


@pytest.mark.parametrize('lines', [{}, '', None, [None], [42]])
def test_nonarray_or_nonobject_ledger_lines_cannot_become_a_zero_estimate(preview_client, lines):
    response = preview_client.post('/api/v1/company-tax/annual-estimate-previews',
        json={'ledgerEntries': [{'entry_type': 'admin_cost', 'lines': lines}], 'holdingActions': []},
        headers={'Authorization': 'Bearer fixture'})
    assert response.status_code == 422
    assert response.json()['code'] == 'REQUEST_VALIDATION_FAILED'


@pytest.mark.parametrize('bad_value', [[], {}, '', 0, 1, None])
def test_nonboolean_annual_answers_cannot_become_clear_readiness(preview_client, bad_value):
    body = {'companyId': COMPANY, 'incomeYear': 2025, 'ledgerEntries': [], 'holdingActions': [],
            'annualData': {'answers': {'shareholder_loans': bad_value}, 'no_activity_confirmed': True}}
    response = preview_client.post('/api/v1/company-tax/readiness-previews', json=body, headers={'Authorization': 'Bearer fixture'})
    assert response.status_code == 422
    body['annualData'] = {'answers': {}, 'no_activity_confirmed': bad_value}
    response = preview_client.post('/api/v1/company-tax/readiness-previews', json=body, headers={'Authorization': 'Bearer fixture'})
    assert response.status_code == 422


@pytest.mark.parametrize('flags', [None, {}, '', False])
def test_nonarray_risk_flags_cannot_become_clear_readiness(preview_client, flags):
    response = preview_client.post('/api/v1/company-tax/readiness-previews',
        json={'companyId': COMPANY, 'incomeYear': 2025, 'annualData': None, 'holdingActions': [],
              'ledgerEntries': [{'entry_type': 'opening_balance', 'lines': [], 'risk_flags': flags}]},
        headers={'Authorization': 'Bearer fixture'})
    assert response.status_code == 422


BOOLEAN_PAYLOADS = json.loads((Path(__file__).resolve().parents[3] / 'architecture/evidence/issues/152/legacy-tax-boolean-payloads.json').read_text())


def plain(value):
    from collections.abc import Mapping
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [plain(item) for item in value]
    return value


BOOLEAN_BOUNDARIES = json.loads((Path(__file__).resolve().parents[3] / 'architecture/evidence/issues/152/legacy-tax-boolean-boundaries.json').read_text())


@pytest.mark.parametrize('case', BOOLEAN_BOUNDARIES['cases'], ids=lambda case: case['id'])
def test_pure_and_cli_feedback_keeps_predecessor_boolean_semantics(case):
    from talli_backend.modules.company_tax_filing.public import build_company_tax_return
    value = source(case['input'])
    assert [asdict(issue) for issue in assess_company_tax_readiness(value, company_id=case['input']['company']['id'])] == case['output']['readiness']
    assert [dict(item) for item in build_company_tax_return(value).feedback] == case['output']['feedback']
    candidate = build_company_tax_return(value)
    assert {name: plain(getattr(candidate, name)) for name in ('schema', 'derived', 'fields', 'feedback')} == next(
        item['candidate'] for item in BOOLEAN_PAYLOADS['cases'] if item['id'] == case['id'])


@pytest.mark.parametrize('line', [{'debit': 100, 'credit': 0}, {'account': None, 'debit': 100, 'credit': 0}])
def test_missing_account_discriminator_cannot_hide_a_cost(preview_client, line):
    body = {'ledgerEntries': [{'entry_type': 'admin_cost', 'lines': [line]}], 'holdingActions': []}
    response = preview_client.post('/api/v1/company-tax/annual-estimate-previews', json=body, headers={'Authorization': 'Bearer fixture'})
    assert response.status_code == 422
    line['account'] = '7770'
    response = preview_client.post('/api/v1/company-tax/annual-estimate-previews', json=body, headers={'Authorization': 'Bearer fixture'})
    assert response.status_code == 200
    assert response.json()['adminCosts'] == 100


def test_malformed_truthy_loan_answer_still_blocks_the_pure_cli_preparation_gate():
    from talli_backend.modules.company_tax_filing.public import CompanyTaxError, prepare_company_tax_return
    for answer in ([], {}):
        raw = json.loads(json.dumps(CAPTURE['cases'][0]['input']))
        raw['annualData']['answers']['shareholder_loans'] = answer
        with pytest.raises(CompanyTaxError) as error:
            prepare_company_tax_return(source(raw))
        assert error.value.code == 'COMPANY_TAX_PAYLOAD_BLOCKED'


def test_extended_boolean_payload_capture_is_bound_to_the_unchanged_input_fixture():
    from hashlib import sha256
    path = Path(__file__).resolve().parents[3] / BOOLEAN_PAYLOADS['inputFixture']
    assert sha256(path.read_bytes()).hexdigest() == BOOLEAN_PAYLOADS['inputFixtureSha256']
    assert [case['id'] for case in BOOLEAN_PAYLOADS['cases']] == [case['id'] for case in BOOLEAN_BOUNDARIES['cases']]
