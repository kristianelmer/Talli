"""Owned workspace rows retain nested data while rejecting scope and link corruption."""
import copy
from contextlib import asynccontextmanager
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from talli_backend.main import create_app
from talli_backend.application.ledger_session import LedgerAuthenticationError
from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsError, AnnualAccountsFilingRows
from talli_backend.shared.kernel import ActorId,ActorKind,CompanyId,IncomeYear,UserId

COMPANY=CompanyId('15300000-0000-4000-8000-000000000001')
ACTOR=ActorId(ActorKind.USER,UserId('15300000-0000-4000-8000-000000000010'))
PREVIEW='15300000-0000-4000-8000-000000000020'
EVIDENCE='15300000-0000-4000-8000-000000000021'


def rows():
    return dict(previews=[dict(id=PREVIEW,company_id=str(COMPANY),income_year=2025,filing='årsregnskap',issues=[{'message':'kept'}])],
        submissions=[dict(id='15300000-0000-4000-8000-000000000026',company_id=str(COMPANY),income_year=2025,filing='årsregnskap',preview_id=None,authority_test_run_id=EVIDENCE)],
        overrides=[],review_comments=[],permissions=[],
        test_evidence=[dict(id=EVIDENCE,company_id=str(COMPANY),obligation='aarsregnskap')])


def test_workspace_recursively_copies_rows():
    original=rows();result=AnnualAccountsFilingRows(COMPANY,IncomeYear(2025),**original)
    original['previews'][0]['issues'][0]['message']='changed'
    assert result.previews[0]['issues'][0]['message']=='kept'
    with pytest.raises(TypeError):result.previews[0]['issues'][0]['message']='changed'


@pytest.mark.parametrize('mutate',[
    lambda r:r['previews'][0].update(company_id='15300000-0000-4000-8000-000000000099'),
    lambda r:r['previews'][0].update(income_year=2024),
    lambda r:r['previews'][0].update(filing='skattemelding for AS'),
    lambda r:r['submissions'].append(copy.deepcopy(r['submissions'][0])),
    lambda r:r['submissions'][0].update(preview_id='15300000-0000-4000-8000-000000000099'),
    lambda r:r['test_evidence'].clear(),
    lambda r:r['test_evidence'][0].update(obligation='skattemelding'),
    lambda r:r.update(previews=None),
    lambda r:r.update(previews={}),
    lambda r:r.update(previews=''),
    lambda r:r['previews'][0].update(id='invalid'),
])
def test_workspace_rejects_scope_and_link_corruption(mutate):
    value=rows();mutate(value)
    with pytest.raises(AnnualAccountsError) as error:AnnualAccountsFilingRows(COMPANY,IncomeYear(2025),**value)
    assert error.value.code=='ANNUAL_ACCOUNTS_DEPENDENCY_UNAVAILABLE'


class Sessions:
    actor_id=ACTOR
    def __init__(self):self.queries=[];self.corrupt=False
    async def session(self, token):
        if token!='fixture':raise LedgerAuthenticationError()
        return self
    @asynccontextmanager
    async def transaction(self):yield self
    async def filing_workspace(self, query):
        self.queries.append(query)
        return AnnualAccountsFilingRows(CompanyId('15300000-0000-4000-8000-000000000099') if self.corrupt else query.company_id,
            query.income_year,previews=[],submissions=[],overrides=[],review_comments=[],permissions=[],test_evidence=[])


def test_http_workspace_binds_actor_and_rejects_wrong_result_company():
    sessions=Sessions();client=TestClient(create_app(annual_accounts_session_factory=sessions))
    url=f'/api/v1/annual-accounts/filing-workspace?companyId={COMPANY}&incomeYear=2025'
    assert client.get(url).status_code==401 and sessions.queries==[]
    headers={'Authorization':'Bearer fixture'};response=client.get(url,headers=headers)
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    assert response.json()==dict(companyId=str(COMPANY),incomeYear=2025,previews=[],submissions=[],overrides=[],reviewComments=[],permissions=[],testEvidence=[])
    assert sessions.queries[0].actor_id==ACTOR
    sessions.corrupt=True
    assert client.get(url,headers=headers).status_code==503
