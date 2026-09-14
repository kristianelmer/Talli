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
