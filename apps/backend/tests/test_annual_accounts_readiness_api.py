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
