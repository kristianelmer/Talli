"""Frozen preview output through authenticated FastAPI, with strict wire validation."""
from fastapi.testclient import TestClient
import pytest

from talli_backend.main import create_app
from talli_backend.application.ledger_session import LedgerAuthenticationError
from test_company_tax_filing import CASES


class Sessions:
    async def session(self, token):
        if token != 'fixture': raise LedgerAuthenticationError()
        return self


@pytest.fixture
def client(): return TestClient(create_app(company_tax_session_factory=Sessions()))


@pytest.mark.parametrize('case',CASES,ids=lambda case:case['name'])
def test_frozen_preview_http(client,case):
    value=case['input']
    response=client.post('/api/v1/company-tax/settlement-previews',json=value,headers={'Authorization':'Bearer fixture'})
    if 'error' in case:
        assert response.status_code==422
        assert response.json()['code']==case['error']['code']
        assert response.json()['detail']==case['error']['message']
    else:
        assert response.status_code==200,response.text
        assert response.json()==case['result']


@pytest.mark.parametrize('change',[{'amount':True},{'amount':'100'},{'lines':[]},{'companyId':'forged'}])
def test_preview_rejects_coercion_and_unknown_fields(client,change):
    response=client.post('/api/v1/company-tax/settlement-previews',json={
        'settlementDate':'2026-04-15','amount':100,'settlementType':'payment','documentStatus':'attached',**change},headers={'Authorization':'Bearer fixture'})
    assert response.status_code==422 and response.json()['code']=='REQUEST_VALIDATION_FAILED'


def test_preview_requires_authentication(client):
    response=client.post('/api/v1/company-tax/settlement-previews',json={
        'settlementDate':'2026-04-15','amount':100,'settlementType':'payment','documentStatus':'attached'})
    assert response.status_code==401
