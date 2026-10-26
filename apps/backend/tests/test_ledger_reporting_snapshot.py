"""Reporting uses complete owning history, including immutable correction chains."""
import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from talli_backend.modules.ledger.public import (
    LedgerCursor, LedgerEntryAmendment, LedgerEntryId, LedgerEntryKind,
    LedgerEntryPage, LedgerEntryView, LedgerError, LedgerLine, LedgerPage,
    read_ledger_reporting_snapshot,
)
from talli_backend.shared.kernel import ActorId, ActorKind, CompanyId, CorrelationId, IncomeYear, Money, Timestamp, UserId

ACTOR=ActorId(ActorKind.USER,UserId('20000000-0000-4000-8000-000000000002'))
COMPANY=CompanyId('10000000-0000-4000-8000-000000000001')
YEAR=IncomeYear(2025)
NOW=Timestamp(datetime(2026,10,26,tzinfo=UTC))


def entry(amount='100',*,reverse=False,year=YEAR):
    lines=(LedgerLine('6700','Synthetic expense',Money.nok(amount),Money.nok('0')),
           LedgerLine('1920','Synthetic bank',Money.nok('0'),Money.nok(amount)))
    if reverse:lines=tuple(replace(line,debit=line.credit,credit=line.debit) for line in lines)
    return LedgerEntryView(LedgerEntryId(str(uuid4())),COMPANY,year,
        LedgerEntryKind.CORRECTION_REVERSAL if reverse else LedgerEntryKind.ADMINISTRATIVE_COST,
        None,None,None,'Synthetic reporting entry',lines,(),None,None,ACTOR,NOW)


def amendment(original,reversal,replacement=None):
    return LedgerEntryAmendment(original.entry_id,reversal.entry_id,
        replacement.entry_id if replacement else None,COMPANY,YEAR,'Synthetic correction',ACTOR,NOW)


class Queries:
    def __init__(self,entries,amendments=()):self.entries=entries;self.amendments=amendments;self.calls=[]
    async def list_entries(self,**query):
        self.calls.append(query);offset=int(str(query['cursor'])) if query['cursor'] else 0
        items=self.entries[offset:offset+100];more=offset+100<len(self.entries)
        return LedgerEntryPage(tuple(items),LedgerPage(LedgerCursor(str(offset+100)) if more else None,more))
    async def list_entry_amendments(self,**query):
        assert query['company_id']==COMPANY and query['actor_id']==ACTOR
        return self.amendments


def read(queries):return asyncio.run(read_ledger_reporting_snapshot(queries,actor_id=ACTOR,company_id=COMPANY,
    income_year=YEAR,correlation_id=CorrelationId('reporting-snapshot-test')))


def test_all_pages_and_years_are_retained_but_only_effective_current_year_entries_report():
    original,reversal,replacement=entry(),entry(reverse=True),entry('50')
    reversal2,replacement2=entry('50',reverse=True),entry('25')
    history=(original,reversal,replacement,reversal2,replacement2,*[entry(year=IncomeYear(2024)) for _ in range(101)])
    amendments=(amendment(original,reversal,replacement),amendment(replacement,reversal2,replacement2))
    queries=Queries(history,amendments);snapshot=read(queries)
    assert snapshot.retained_entries==history and snapshot.amendments==amendments
    assert snapshot.effective_entries==(replacement2,)
    assert dict(snapshot.reversal_sources)=={reversal.entry_id:original,reversal2.entry_id:replacement}
    assert len(queries.calls)==2 and all(q['company_ids']==(COMPANY,) and q['limit']==100 for q in queries.calls)


def test_pure_reversal_has_no_effective_original_or_reversal():
    original,reversal=entry(),entry(reverse=True)
    assert read(Queries((original,reversal),(amendment(original,reversal),))).effective_entries==()


@pytest.mark.parametrize('defect',['missing-original','missing-reversal','missing-replacement','duplicate-original',
    'duplicate-reversal','orphan-reversal','foreign-entry','foreign-amendment','year','wrong-kind',
    'amount','account','duplicate-id','amendments-list','replacement-reused','cycle'])
def test_incomplete_or_ambiguous_lineage_never_silently_omits_an_entry(defect):
    original,reversal,replacement=entry(),entry(reverse=True),entry('50')
    rows=(original,reversal,replacement);changes=(amendment(original,reversal,replacement),)
    if defect=='missing-original':rows=rows[1:]
    elif defect=='missing-reversal':rows=(original,replacement)
    elif defect=='missing-replacement':rows=rows[:2]
    elif defect=='duplicate-original':changes=changes*2
    elif defect=='duplicate-reversal':changes=(*changes,amendment(replacement,reversal))
    elif defect=='orphan-reversal':changes=()
    elif defect=='foreign-entry':rows=(replace(original,company_id=CompanyId(str(uuid4()))),*rows[1:])
    elif defect=='foreign-amendment':changes=(replace(changes[0],company_id=CompanyId(str(uuid4()))),)
    elif defect=='year':changes=(replace(changes[0],income_year=IncomeYear(2024)),)
    elif defect=='wrong-kind':rows=(original,replace(reversal,entry_kind=LedgerEntryKind.ADMINISTRATIVE_COST),replacement)
    elif defect=='amount':rows=(original,replace(reversal,lines=entry('99',reverse=True).lines),replacement)
    elif defect=='account':rows=(original,replace(reversal,lines=(replace(reversal.lines[0],account='6705'),reversal.lines[1])),replacement)
    elif defect=='duplicate-id':rows=(*rows,original)
    elif defect=='amendments-list':changes=list(changes)
    elif defect=='replacement-reused':
        other,other_reversal=entry(),entry(reverse=True);rows=(*rows,other,other_reversal)
        changes=(*changes,amendment(other,other_reversal,replacement))
    else:
        other_reversal=entry('50',reverse=True);rows=(*rows,other_reversal)
        changes=(*changes,amendment(replacement,other_reversal,original))
    with pytest.raises(LedgerError):read(Queries(rows,changes))


@pytest.mark.parametrize('defect',['empty-more','repeated-cursor','oversized-page','list-items','has-more-type','cursor-mismatch'])
def test_incomplete_pagination_is_unavailable(defect):
    class Broken(Queries):
        async def list_entries(self,**query):
            if defect=='empty-more':return LedgerEntryPage((),LedgerPage(LedgerCursor('same'),True))
            if defect=='repeated-cursor':return LedgerEntryPage((entry(),),LedgerPage(LedgerCursor('same'),True))
            if defect=='oversized-page':return LedgerEntryPage(tuple(entry() for _ in range(101)),LedgerPage(None,False))
            if defect=='list-items':return LedgerEntryPage([entry()],LedgerPage(None,False))
            if defect=='has-more-type':return LedgerEntryPage((entry(),),LedgerPage(None,0))
            return LedgerEntryPage((entry(),),LedgerPage(LedgerCursor('next'),False))
    with pytest.raises(LedgerError):read(Broken(()))
