"""Exact-year selection cannot turn stale or malformed interviews into readiness."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from talli_backend.adapters.postgres_rf_annual_interview import annual_interview_for_year
from talli_backend.adapters.postgres_shareholder_register_filing import _SourceAdmission
from talli_backend.modules.shareholder_register_filing import public as rf
from test_consequential_adapter_guards import rf_session
from test_rf1086_source_admission import AdmissionHarness, COMPANY, YEAR


def query():
    return rf.Rf1086SourceQuery(COMPANY,YEAR,rf_session().actor_id)


def row(year=None):
    return {'sourceId':str(uuid4()),'companyId':str(COMPANY),'incomeYear':int(YEAR) if year is None else year,
            'answers':{'bank_balance_confirmed':True,'has_unpaid_items':False,'authority_to_submit_confirmed':True,
                       'other':{'evidence':['preserve']}},'confirmations':['reviewed'],
            'noActivityConfirmed':False,'annualFullTimeEquivalents':None,
            'completedAt':'2026-01-01T01:00:00.123+01:00','updatedAt':'2026-01-02T00:00:00Z'}


def test_exact_year_is_selected_without_reusing_old_answers_and_is_deeply_immutable():
    current=row();history=[current,row(int(YEAR)-1)]
    view=annual_interview_for_year(history,query())
    assert view.source_id==current['sourceId'] and view.income_year==YEAR
    assert view.completed_at=='2026-01-01T00:00:00.123000+00:00'
    assert view.answers['has_unpaid_items'] is False
    assert view.annual_full_time_equivalents==0
    current['answers']['other']['evidence'].append('mutated')
    assert view.answers['other']['evidence']==('preserve',)
    with pytest.raises(TypeError):view.answers['has_unpaid_items']=True
    assert annual_interview_for_year([row(int(YEAR)-1)],query()) is None
    assert annual_interview_for_year([],query()) is None


@pytest.mark.parametrize('field,value',[
    pytest.param('companyId',str(uuid4()),id='company-scope'),('sourceId','bad'),('incomeYear',True),('incomeYear',str(int(YEAR))),
    ('incomeYear',int(YEAR)+1),('incomeYear',1999),('answers',[]),('answers',{'has_unpaid_items':'false'}),
    ('answers',{'authority_to_submit_confirmed':1}),('answers',{'bank_balance_confirmed':None}),
    ('answers',{'value':float('nan')}),('answers',{1:True}),('confirmations','reviewed'),('confirmations',[1]),
    ('noActivityConfirmed','false'),('annualFullTimeEquivalents',True),('annualFullTimeEquivalents',-1),
    ('annualFullTimeEquivalents',float('inf')),('completedAt',None),('completedAt','2026-01-01T00:00:00'),
    ('updatedAt','invalid'),('extra',True),
])
def test_invalid_selected_evidence_fails_closed(field,value):
    item=row();item[field]=value
    with pytest.raises(rf.ShareholderRegisterFilingError) as caught:
        annual_interview_for_year([item],query())
    assert caught.value.code=='SHAREHOLDER_REGISTER_FILING_DEPENDENCY_UNAVAILABLE'


@pytest.mark.parametrize('history',[None,{},[None]])
def test_unavailable_history_is_not_a_missing_interview(history):
    with pytest.raises(rf.ShareholderRegisterFilingError):annual_interview_for_year(history,query())


@pytest.mark.parametrize('duplicate',['year','id'])
def test_duplicate_identity_or_year_rejects_enumeration(duplicate):
    first=row();second=row()
    if duplicate=='id':second.update(sourceId=first['sourceId'],incomeYear=int(YEAR)-1)
    with pytest.raises(rf.ShareholderRegisterFilingError):annual_interview_for_year([first,second],query())


def test_prior_year_payload_is_not_interpreted_as_current_prerequisites():
    prior=row(int(YEAR)-1);prior['answers']={'has_unpaid_items':'historical-format'}
    assert annual_interview_for_year([prior],query()) is None


@pytest.mark.parametrize('missing',['answers','completedAt','noActivityConfirmed'])
def test_missing_current_evidence_is_unavailable(missing):
    item=row();del item[missing]
    with pytest.raises(rf.ShareholderRegisterFilingError):annual_interview_for_year([item],query())


def test_read_uses_existing_connection_and_verified_scope_then_expires():
    store=rf_session();q=query();calls=[];item=row()
    class Connection:
        info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        async def execute(self,sql,args):calls.append((sql,args));return self
        async def fetchall(self):return [{'items':[item]}]
    scope=_SourceAdmission(store,Connection(),q,AdmissionHarness().identity)
    async def run():
        assert (await scope.annual_interview()).source_id==item['sourceId']
        assert calls==[('select backend_system.list_annual_data_legacy_v1(%s::uuid,%s::integer,%s::text) as items',
                       (str(COMPANY),int(YEAR),str(store.actor_id.subject)))]
        scope.close()
        with pytest.raises(rf.ShareholderRegisterFilingError):await scope.annual_interview()
        assert len(calls)==1
    asyncio.run(run())
