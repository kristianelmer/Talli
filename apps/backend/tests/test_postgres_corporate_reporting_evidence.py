"""Same-connection reader behavior with real projection codecs/domain assembly."""
import asyncio
from dataclasses import fields, is_dataclass, replace
from datetime import date, datetime
from enum import Enum
from types import SimpleNamespace
from uuid import uuid4

import psycopg
from psycopg.pq import TransactionStatus
import pytest

from talli_backend.adapters.postgres_corporate_reporting_evidence import PostgresCorporateReportingEvidence
from talli_backend.modules.corporate_governance.public import (
    AccountingEntryReference, CorporateGovernanceError,
)
from talli_backend.shared.kernel import CompanyId, CorrelationId, IncomeYear
from test_corporate_governance_reporting_year import (
    ACTOR, COMPANY, amendment, build, capital, decision, lifecycle, ref,
)


def wire(value):
    if isinstance(value, Enum): return value.value
    if isinstance(value, (date, datetime)): return value.isoformat()
    if is_dataclass(value):
        names = [f.name for f in fields(value)]
        if names == ['value']: return wire(value.value)
        return {name.split('_')[0] + ''.join(p.title() for p in name.split('_')[1:]): wire(getattr(value,name)) for name in names}
    if isinstance(value, (tuple,list)): return [wire(v) for v in value]
    if isinstance(value, dict): return {k:wire(v) for k,v in value.items()}
    return value


def payload(life=None, events=(), amendments=()):
    rows=[]
    for row in events:
        value=wire(row.event)
        value.update({k:v for k,v in wire(row).items() if k!='event'})
        rows.append(value)
    return {'companyId':str(COMPANY),'incomeYear':2026,'lifecycle':wire(life or lifecycle()),
            'supportedEvents':rows,'amendments':[
                {f.name: (str(row.amended_by.subject) if f.name=='amended_by' else wire(getattr(row,f.name))) for f in fields(row)}
                for row in amendments]}


class Connection:
    def __init__(self, value, *, status=TransactionStatus.INTRANS, error=None):
        self.info=SimpleNamespace(transaction_status=status)
        self.value,self.error,self.calls=value,error,[]
    async def execute(self, query, parameters):
        self.calls.append((query,parameters))
        if self.error: raise self.error
        return self
    async def fetchone(self): return {'result':self.value}


def read(connection):
    return asyncio.run(PostgresCorporateReportingEvidence(connection,ACTOR).read_reporting_year_evidence(
        company_id=COMPANY,income_year=IncomeYear(2026),correlation_id=CorrelationId('guarded-read')))


def test_exact_company_year_actor_binding_on_one_existing_connection():
    conn=Connection(payload())
    assert read(conn)==build()
    assert len(conn.calls)==1
    assert conn.calls[0][0].startswith('select corporate_governance.read_guarded_reporting_year_inputs_v1(')
    assert conn.calls[0][1]==(str(COMPANY),2026,str(ACTOR.subject))


def test_complete_cross_year_corrections_and_ledger_amendments_match_public_builder():
    original=decision(); later=replace(decision('2027-01-01'),supersedes_decision_id=original.decision_id)
    cap=capital(); replacement=ref(AccountingEntryReference)
    first=amendment(cap.accounting_entry_id,replacement)
    second=replace(amendment(replacement),income_year=IncomeYear(2027))
    life=lifecycle((later,original)); events=(cap,capital(2025)); amendments=(second,first)
    actual=read(Connection(payload(life,events,amendments)))
    assert actual==build(life,events,amendments)
    assert len(actual.dividends)==2 and len(actual.ledger_amendments)==2
    assert actual.supported_events[0].status=='corrected'


@pytest.mark.parametrize('status',[TransactionStatus.IDLE,TransactionStatus.INERROR,TransactionStatus.UNKNOWN])
def test_no_transaction_fails_before_query(status):
    conn=Connection(payload(),status=status)
    with pytest.raises(CorporateGovernanceError):read(conn)
    assert not conn.calls


@pytest.mark.parametrize('problem',['missing','wrong_company','wrong_year','boolean_year','missing_lifecycle_array',
    'bad_event','bad_amendment','cross_company_event','duplicate_event','cross_company_amendment'])
def test_corrupt_or_unscoped_projection_fails_closed(problem):
    cap=capital(); p=payload(events=(cap,))
    if problem=='missing':p=None
    elif problem=='wrong_company':p['companyId']=str(uuid4())
    elif problem=='wrong_year':p['incomeYear']=2027
    elif problem=='boolean_year':p['incomeYear']=True
    elif problem=='missing_lifecycle_array':del p['lifecycle']['finalizations']
    elif problem=='bad_event':p['supportedEvents']=[None]
    elif problem=='bad_amendment':p['amendments']=[{}]
    elif problem=='cross_company_event':p['supportedEvents'][0]['companyId']=str(uuid4())
    elif problem=='duplicate_event':p['supportedEvents']*=2
    elif problem=='cross_company_amendment':p=payload(events=(cap,),amendments=(replace(amendment(cap.accounting_entry_id),company_id=CompanyId(str(uuid4()))),))
    with pytest.raises(CorporateGovernanceError):read(Connection(p))


@pytest.mark.parametrize('message,expected',[('corporate_governance_forbidden','corporate_governance_forbidden'),
    ('corporate_governance_reporting_guard_required','corporate_governance_dependency_unavailable'),('database secret detail','corporate_governance_dependency_unavailable')])
def test_sql_errors_fail_closed_without_exposing_database_detail(message,expected):
    conn=Connection(payload(),error=psycopg.errors.RaiseException(message))
    with pytest.raises(CorporateGovernanceError) as caught:read(conn)
    assert caught.value.code.value==expected
    assert "database secret detail" not in str(caught.value)
