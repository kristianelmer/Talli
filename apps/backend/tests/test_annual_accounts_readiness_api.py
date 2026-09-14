"""Accounts readiness HTTP previews preserve the frozen ordered source issues."""
import json
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from talli_backend.main import create_app
from talli_backend.application.ledger_session import LedgerAuthenticationError

CASES=json.loads((Path(__file__).resolve().parents[3]/'architecture/evidence/issues/153/characterization/legacy-pure-characterization.json').read_text())['readinessCases']
COMPANY='15300000-0000-4000-8000-000000000001'


class Sessions:
    async def session(self, token):
        if token!='fixture':raise LedgerAuthenticationError()
        return self


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_readiness_http_keeps_accounts_and_corporate_issue_order(case):
    value=json.loads(json.dumps(case['input']).replace('company-id',COMPANY))
    corporate=value.get('corporateDocuments')
    body=dict(companyId=value['company']['id'],incomeYear=value['incomeYear'],annualData=value.get('annualData'),ledgerEntries=value['ledgerEntries'],
        corporateEnabled=corporate['enabled'] if corporate else False,
        corporateBlockers=corporate['readiness']['blockers'] if corporate else [])
    client=TestClient(create_app(annual_accounts_session_factory=Sessions()))
    response=client.post('/api/v1/annual-accounts/readiness-previews',json=body,headers={'Authorization':'Bearer fixture'})
    assert response.status_code==200,response.text
    assert response.json()=={'companyId':COMPANY,'incomeYear':body['incomeYear'],'issues':case['output']['value']}
    assert response.headers['cache-control']=='no-store'


@pytest.mark.parametrize('mutate',[
    lambda b:b['annualData']['answers'].update(general_meeting_approved='false'),
    lambda b:b['annualData']['answers'].update(general_meeting_approved=1),
    lambda b:b['annualData'].update(annual_full_time_equivalents={}),
    lambda b:b['annualData'].update(annual_full_time_equivalents=True),
    lambda b:b['annualData'].update(confirmations={}),
    lambda b:b['annualData'].update(confirmations=[False]),
    lambda b:b['annualData'].update(company_id='15300000-0000-4000-8000-000000000099'),
    lambda b:b['annualData'].update(income_year=2024),
    lambda b:b['ledgerEntries'][0].update(risk_flags=[{}]),
    lambda b:b['ledgerEntries'][0].update(warning_accepted_at={}),
])
def test_readiness_http_rejects_malformed_consumed_facts(mutate):
    value=json.loads(json.dumps(CASES[0]['input']).replace('company-id',COMPANY))
    body=dict(companyId=COMPANY,incomeYear=2025,annualData=value['annualData'],ledgerEntries=value['ledgerEntries'],corporateEnabled=False,corporateBlockers=[])
    mutate(body)
    client=TestClient(create_app(annual_accounts_session_factory=Sessions()))
    response=client.post('/api/v1/annual-accounts/readiness-previews',json=body,headers={'Authorization':'Bearer fixture'})
    assert response.status_code==422
