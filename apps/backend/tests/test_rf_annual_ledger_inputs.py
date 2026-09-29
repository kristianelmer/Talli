"""RF consumes complete Ledger history without changing Ledger policy."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from talli_backend.application.shareholder_register_annual_ledger import read_annual_ledger_inputs
from talli_backend.adapters.postgres_shareholder_register_filing import _SourceAdmission
from talli_backend.modules.ledger.public import LedgerCursor, LedgerPage, OpeningBankInput, PeriodLock, PeriodLockId, PeriodLockPage
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, CorrelationId, IncomeYear, Money, Timestamp
from test_postgres_rf_source_admission import rf_session
from test_rf1086_source_admission import AdmissionHarness, COMPANY, YEAR

ACTOR=rf_session().actor_id
QUERY=rf.Rf1086SourceQuery(COMPANY,YEAR,ACTOR)
CORRELATION=CorrelationId('annual-ledger-inputs')
STAMP=Timestamp(datetime(2026,1,1,tzinfo=timezone.utc))


def opening():
    return OpeningBankInput(str(uuid4()),COMPANY,YEAR,Money(Decimal('123.45')),ACTOR,STAMP)


def lock(year=YEAR):
    return PeriodLock(PeriodLockId(str(uuid4())),COMPANY,year,'Original reason',ACTOR,STAMP,False)


def page(items=(),cursor=None,more=False):
    return PeriodLockPage(tuple(items),LedgerPage(LedgerCursor(cursor) if cursor else None,more))


class Ledger:
    def __init__(self,openings=(),pages=None):
        self.openings=openings;self.pages=list(pages or [page()]);self.calls=[]
    async def read_opening_bank_inputs(self,**args):
        self.calls.append(('opening',args));return self.openings
    async def list_period_locks(self,**args):
        self.calls.append(('period',args));value=self.pages.pop(0)
        if isinstance(value,Exception):raise value
        return value


def read(ledger):return asyncio.run(read_annual_ledger_inputs(ledger,QUERY,CORRELATION))


def test_all_pages_complete_before_exact_year_selection_and_original_facts_are_retained():
    old=lock(IncomeYear(int(YEAR)-1));current=lock();new=lock(IncomeYear(int(YEAR)+1));bank=opening()
    ledger=Ledger((bank,),[page([old],'cursor-1',True),page([new,current])])
    result=read(ledger)
    assert result.opening_bank_inputs==(bank,) and result.period_locks==(current,)
    assert result.opening_bank_inputs[0].bank_balance.amount==Decimal('123.45')
    assert ledger.calls[0]==('opening',dict(actor_id=ACTOR,company_id=COMPANY,income_year=YEAR,correlation_id=CORRELATION))
    assert [args['cursor'] for name,args in ledger.calls if name=='period']==[None,LedgerCursor('cursor-1')]
    assert all(args['actor_id']==ACTOR for _,args in ledger.calls)
    assert all(args['company_ids']==(COMPANY,) and args['limit']==100 for name,args in ledger.calls if name=='period')
    with pytest.raises(AttributeError):result.period_locks=()


def test_complete_empty_year_does_not_substitute_historical_period():
    result=read(Ledger(pages=[page([lock(IncomeYear(int(YEAR)-1))])]))
    assert result.company_id==COMPANY and result.income_year==YEAR
    assert result.opening_bank_inputs==() and result.period_locks==()


def test_later_page_failure_is_not_partial_year_evidence():
    ledger=Ledger(pages=[page([lock()],'next',True),RuntimeError('unavailable')])
    with pytest.raises(RuntimeError,match='unavailable'):read(ledger)


@pytest.mark.parametrize('kind',['cycle','duplicate','foreign','empty-more','empty-last','missing-cursor','extra-cursor','invalid-more','invalid-page'])
def test_incomplete_or_inconsistent_history_fails_closed(kind):
    item=lock()
    pages={
        'cycle':[page([item],'same',True),page([lock()],'same',True)],
        'duplicate':[page([item],'next',True),page([item])],
        'foreign':[page([replace(item,company_id=CompanyId(str(uuid4())))])],
        'empty-more':[page((),'next',True)],
        'empty-last':[page([item],'next',True),page()],
        'missing-cursor':[page([item],None,True)],
        'extra-cursor':[page([item],'next',False)],
        'invalid-more':[page([item],None,0)],
        'invalid-page':[PeriodLockPage((),None)],
    }
    with pytest.raises(rf.ShareholderRegisterFilingError):read(Ledger(pages=pages[kind]))


@pytest.mark.parametrize('kind',['duplicate','foreign','year','not-tuple'])
def test_opening_identity_and_scope_are_checked(kind):
    item=opening()
    values={'duplicate':(item,item),'foreign':(replace(item,company_id=CompanyId(str(uuid4()))),),
        'year':(replace(item,income_year=IncomeYear(int(YEAR)-1)),),'not-tuple':[item]}
    with pytest.raises(rf.ShareholderRegisterFilingError):read(Ledger(values[kind]))


def test_real_ledger_adapter_uses_held_connection_and_admission_lifetime():
    store=rf_session();calls=[];identity=str(uuid4())
    class Connection:
        info=SimpleNamespace(transaction_status=TransactionStatus.INTRANS)
        async def execute(self,statement,args):
            calls.append((statement,args));return self
        async def fetchall(self):
            if 'read_opening_bank_inputs' in calls[-1][0]:
                return [dict(snapshot_id=identity,company_id=str(COMPANY),income_year=int(YEAR),
                    bank_balance_nok=Decimal('123.45'),recorded_by=str(ACTOR.subject),recorded_at=STAMP.value)]
            return [dict(items=[],has_more=False,next_cursor=None)]
    scope=_SourceAdmission(store,Connection(),rf.Rf1086SourceQuery(COMPANY,YEAR,store.actor_id),AdmissionHarness().identity)
    async def run():
        result=await scope.annual_ledger_inputs(CORRELATION)
        assert result.opening_bank_inputs[0].snapshot_id==identity
        assert result.period_locks==()
        assert len(calls)==2 and all(statement.startswith('select * from ledger.') for statement,_ in calls)
        scope.close()
        with pytest.raises(rf.ShareholderRegisterFilingError):await scope.annual_ledger_inputs(CORRELATION)
        assert len(calls)==2
    asyncio.run(run())
