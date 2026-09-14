"""Predecessor case decoding through the real public rehearsal and durable intent."""
import asyncio
import copy
import json
from pathlib import Path

import pytest

from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxRehearsalConfiguration, rehearse_company_tax_return,
)

ROOT = Path(__file__).resolve().parents[3]
CAPTURE = json.loads((ROOT / 'architecture/evidence/issues/152/authority-workflow-ownership/legacy-case-years.json').read_text())
CONFIGURATION = CompanyTaxRehearsalConfiguration(
    approved_test_write='true', authority_environment='test', mode='prepare',
    scope='skatteetaten:formueinntekt/skattemelding altinn:instances.read altinn:instances.write',
    system_user_org='310279617',
)


class StopBeforeAuthority(Exception):
    pass


class MemoryRehearsal:
    def __init__(self, year):
        self.case = json.loads((ROOT / 'tests/fixtures/authority/company-tax-no-activity-2025.json').read_text())
        self.case['company']['incomeYear'] = copy.deepcopy(year)
        self.checkpoints = []
        self.credentials_prepared = False

    def select_evidence(self):
        pass

    def load_evidence(self):
        return None

    def load_case(self):
        return self.case

    def save_evidence(self, evidence):
        self.checkpoints.append(copy.deepcopy(evidence))

    def evidence_filename(self):
        return 'synthetic-evidence.json'

    def case_filename(self):
        return 'synthetic-case.json'

    def revision(self):
        return CAPTURE['baselineRevision']

    def timestamp(self):
        return '2026-09-14T00:00:00.000Z'

    def prepare_credentials(self):
        assert self.checkpoints[-1]['status'] == 'prepared'
        assert self.checkpoints[-1]['error'] is None
        self.credentials_prepared = True

    async def connect(self, evidence):
        assert self.credentials_prepared
        assert self.checkpoints[-1] == evidence
        raise StopBeforeAuthority()


async def no_sleep(_):
    pytest.fail('A case-input check attempted authority polling')


@pytest.mark.parametrize('case', CAPTURE['cases'], ids=lambda case: case['id'])
def test_predecessor_year_decoding_before_authority_through_public_workflow(case):
    io = MemoryRehearsal(case['input'])
    expected = case['expected']
    if 'year' in expected:
        with pytest.raises(StopBeforeAuthority):
            asyncio.run(rehearse_company_tax_return(CONFIGURATION, io, sleep=no_sleep))
        assert [v['status'] for v in io.checkpoints] == ['prepared', 'failed_blocked']
        assert all(v['incomeYear'] == expected['year'] for v in io.checkpoints)
    else:
        assert expected['errorType'] == 'ValueError'
        with pytest.raises(ValueError) as caught:
            asyncio.run(rehearse_company_tax_return(CONFIGURATION, io, sleep=no_sleep))
        assert str(caught.value) == expected['message']
        assert io.checkpoints == []
        assert io.credentials_prepared is False


def completed_evidence():
    return {'status': 'submitted_and_receipted', 'environment': 'test', 'productionEnabled': False,
            'companyOrgNumber': '310279617', 'incomeYear': 2025, 'instance': {'id': 'synthetic-instance'},
            'authorityValidation': {'result': {'value': ['legacy-structured-metadata']}},
            'receipt': {'reference': {'legacy': ['receipt']}},
            'submission': {'archiveReference': 'archive'}}


def test_completed_replay_public_summary_is_recursively_detached_and_immutable():
    class CompletedReplay(MemoryRehearsal):
        def __init__(self):
            super().__init__(2025)
            self.prior = completed_evidence()

        def load_evidence(self):
            return self.prior

        def prepare_credentials(self):
            pytest.fail('Completed replay read credentials')

    io = CompletedReplay()
    result = asyncio.run(rehearse_company_tax_return(CONFIGURATION, io, sleep=no_sleep))
    assert result['validationResult']['value'] == ('legacy-structured-metadata',)
    with pytest.raises(TypeError):
        result['validationResult']['value'] = ('changed',)
    with pytest.raises(AttributeError):
        result['receiptReference']['legacy'].append('changed')
    io.prior['authorityValidation']['result']['value'].append('source-change')
    assert result['validationResult']['value'] == ('legacy-structured-metadata',)


def test_completed_replay_cli_preserves_structured_json_summary(tmp_path):
    from talli_backend.authority_tools import company_tax_test
    from talli_backend.authority_tools._filing import write_evidence
    prior = completed_evidence()
    evidence = tmp_path / 'evidence.json'
    write_evidence(evidence, prior)
    environment = {
        'TALLI_COMPANY_TAX_APPROVED_TEST_WRITE': 'true',
        'TALLI_MASKINPORTEN_ENVIRONMENT': 'test',
        'TALLI_COMPANY_TAX_REHEARSAL_MODE': 'resume',
        'TALLI_MASKINPORTEN_SCOPE': CONFIGURATION.scope,
        'TALLI_MASKINPORTEN_SYSTEM_USER_ORG': CONFIGURATION.system_user_org,
        'TALLI_COMPANY_TAX_EVIDENCE_PATH': str(evidence),
    }
    async def forbidden_provider(*_):
        pytest.fail('Completed replay called a provider')
    result = asyncio.run(company_tax_test.run(environment, client_factory=forbidden_provider))
    assert json.loads(json.dumps(result)) == result
    assert result['validationResult'] == prior['authorityValidation']['result']
    assert result['receiptReference'] == prior['receipt']['reference']
