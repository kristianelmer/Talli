"""Authenticated import preserves frozen TT02 outcomes and one-row transaction order."""
from contextlib import asynccontextmanager
from dataclasses import asdict
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from talli_backend.main import create_app
from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsCompanyIdentity, AnnualAccountsError, AnnualAccountsRecordId,
)
from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,UserId

CASES=json.loads((Path(__file__).resolve().parents[3]/'architecture/evidence/issues/153/characterization/legacy-pure-characterization.json').read_text())['evidenceCases']
COMPANY=CompanyId(CASES[0]['input']['companyId'])
ACTOR=ActorId(ActorKind.USER,UserId(CASES[0]['input']['recordedBy']))
RECORD=AnnualAccountsRecordId('00000000-0000-4000-8000-000000000153')


class Sessions:
    actor_id=ACTOR
    def __init__(self, organization):self.organization=organization;self.events=[];self.projection=None;self.fail=None
    async def session(self, token):
        if token!='fixture':raise LedgerAuthenticationError()
        return self
    @asynccontextmanager
    async def transaction(self):
        self.events.append('begin')
        try:yield self
        except Exception:self.events.append('rollback');raise
        else:self.events.append('commit')
    async def filing_company_identity(self, company_id, actor_id):
        assert actor_id==ACTOR and company_id==COMPANY
        self.events.append('company-identity')
        return AnnualAccountsCompanyIdentity(COMPANY,self.organization)
    async def import_tt02_evidence(self, projection, actor_id):
        assert actor_id==ACTOR and projection.recorded_by==str(ACTOR.subject)
        self.events.append('evidence-insert')
        if self.fail:raise self.fail
        self.projection=projection
        return RECORD


@pytest.mark.parametrize('case',[c for c in CASES if c['id'] not in ('blank-company','blank-actor')],ids=lambda c:c['id'])
def test_http_import_matches_released_projection_or_error(case):
    value=case['input'];sessions=Sessions(value['expectedCompanyOrgNumber'])
    client=TestClient(create_app(annual_accounts_session_factory=sessions))
    body={'companyId':str(COMPANY),'evidenceJson':json.dumps(value['evidence']), 'evidenceUrl':value.get('evidenceUrl')}
    response=client.post('/api/v1/annual-accounts/tt02-evidence-imports',json=body,headers={'Authorization':'Bearer fixture'})
    assert response.headers['cache-control']=='no-store'
    if 'error' in case['output']:
        assert response.status_code==422 and response.json()['detail']==case['output']['error']['message']
        assert sessions.events==['begin','company-identity','rollback']
    else:
        assert response.status_code==200,response.text
        assert response.json()=={'recordId':str(RECORD),'testReference':case['output']['value']['test_reference']}
        actual=asdict(sessions.projection);expected=dict(case['output']['value']);actual.pop('recorded_at');expected.pop('recorded_at')
        assert actual==expected
        assert sessions.events==['begin','company-identity','evidence-insert','commit']


def test_import_rejects_unauthenticated_and_rolls_back_persistence_failure():
    value=CASES[0]['input'];sessions=Sessions(value['expectedCompanyOrgNumber'])
    client=TestClient(create_app(annual_accounts_session_factory=sessions));url='/api/v1/annual-accounts/tt02-evidence-imports'
    body={'companyId':str(COMPANY),'evidenceJson':json.dumps(value['evidence'])}
    assert client.post(url,json=body).status_code==401 and sessions.events==[]
    sessions.fail=AnnualAccountsError.unavailable()
    assert client.post(url,json=body,headers={'Authorization':'Bearer fixture'}).status_code==503
    assert sessions.events==['begin','company-identity','evidence-insert','rollback']
