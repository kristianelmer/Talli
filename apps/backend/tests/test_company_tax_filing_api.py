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


@pytest.mark.parametrize('settlement_date,code', [('2026-04-15','invalid_amount'),('invalid','invalid_date')])
def test_unparseable_browser_amount_keeps_original_domain_message_and_validation_order(client,settlement_date,code):
    response=client.post('/api/v1/company-tax/settlement-previews',json={
        'settlementDate':settlement_date,'amount':None,'settlementType':'payable','documentStatus':'attached'},headers={'Authorization':'Bearer fixture'})
    assert response.status_code==422 and response.json()['code']==code
    if code=='invalid_amount':assert response.json()['detail']=='Skattebeløp må være større enn 0.'


def test_filing_workspace_http_preserves_receipt_json_and_fails_closed():
    from contextlib import asynccontextmanager
    from talli_backend.modules.company_tax_filing.public import CompanyTaxError, CompanyTaxFilingRows
    from talli_backend.shared.kernel import ActorId, ActorKind, UserId
    from test_company_tax_workspace import COMPANY, rows

    class WorkspaceSessions(Sessions):
        actor_id = ActorId(ActorKind.USER, UserId('00000000-0000-0000-0000-000000000153'))
        error = None

        @asynccontextmanager
        async def transaction(self):
            yield self

        async def filing_workspace(self, query):
            assert query.actor_id == self.actor_id and query.company_id == COMPANY
            if self.error:
                raise self.error
            return CompanyTaxFilingRows(query.company_id, query.income_year, **rows())

    sessions = WorkspaceSessions()
    client = TestClient(create_app(company_tax_session_factory=sessions))
    path = f'/api/v1/company-tax/filing-workspace?companyId={COMPANY}&incomeYear=2025'
    response = client.get(path)
    assert response.status_code == 401
    response = client.get(path, headers={'Authorization': 'Bearer fixture'})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['companyId'] == str(COMPANY) and value['incomeYear'] == 2025
    original = rows()['submissions'][0]
    assert value['submissions'][0]['receiptMetadata'] == original['receipt_metadata']
    assert value['submissions'][0]['calls'] == original['calls']
    assert value['submissions'][0]['submittedPayloadRef'] == original['submitted_payload_ref']
    assert value['testEvidence'][0]['status'] == 'pending'
    assert response.headers['cache-control'] == 'no-store'
    for error, status in ((CompanyTaxError.not_found(), 404), (CompanyTaxError.unavailable(), 503), (CompanyTaxError.forbidden(), 403)):
        sessions.error = error
        response = client.get(path, headers={'Authorization': 'Bearer fixture'})
        assert response.status_code == status and response.json()['code'] == error.code
