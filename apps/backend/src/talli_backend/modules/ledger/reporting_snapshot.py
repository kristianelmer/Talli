"""Ledger owns exhaustive reporting enumeration and immutable amendment effects."""
from decimal import Decimal

from talli_backend.shared.kernel import IncomeYear
from .public import (
    LedgerCursor,LedgerEntryPage,LedgerEntryView,LedgerEntryAmendment,LedgerEntryKind,LedgerError,LedgerReportingSnapshot,
)


def _amounts(entry):
    result={}
    for line in entry.lines:
        if line.debit.currency!=line.credit.currency:raise ValueError('Ledger line currencies differ.')
        key=(line.account,line.debit.currency)
        debit,credit=result.get(key,(Decimal(0),Decimal(0)))
        result[key]=(debit+line.debit.amount,credit+line.credit.amount)
    return result


def _amendments(entries,amendments,company_id):
    if type(amendments) is not tuple:raise ValueError('Ledger amendments were not fully enumerated.')
    indexed={row.entry_id:row for row in entries};originals=set();reversals={};edges={};replacements=set()
    for amendment in amendments:
        if (type(amendment) is not LedgerEntryAmendment or amendment.company_id!=company_id
                or type(amendment.income_year) is not IncomeYear):raise ValueError('Ledger amendment scope is invalid.')
        original=indexed.get(amendment.original_entry_id);reversal=indexed.get(amendment.reversal_entry_id)
        replacement=indexed.get(amendment.replacement_entry_id) if amendment.replacement_entry_id is not None else None
        if (original is None or reversal is None or original.entry_id in originals or reversal.entry_id in reversals
                or original.entry_id==reversal.entry_id or original.entry_kind is LedgerEntryKind.CORRECTION_REVERSAL
                or reversal.entry_kind is not LedgerEntryKind.CORRECTION_REVERSAL
                or original.income_year!=amendment.income_year or reversal.income_year!=amendment.income_year
                or amendment.replacement_entry_id is not None and (replacement is None
                    or replacement.income_year!=amendment.income_year or replacement.entry_kind is LedgerEntryKind.CORRECTION_REVERSAL
                    or replacement.entry_id in replacements
                    or replacement.entry_id in (original.entry_id,reversal.entry_id))):
            raise ValueError('Ledger amendment lineage is incomplete or ambiguous.')
        if _amounts(reversal)!={key:(credit,debit) for key,(debit,credit) in _amounts(original).items()}:
            raise ValueError('Ledger reversal does not exactly cancel its original accounts and currency.')
        originals.add(original.entry_id);reversals[reversal.entry_id]=original
        if replacement is not None:
            edges[original.entry_id]=replacement.entry_id
            replacements.add(replacement.entry_id)
    if any(row.entry_kind is LedgerEntryKind.CORRECTION_REVERSAL and row.entry_id not in reversals for row in entries):
        raise ValueError('Ledger reversal has no owning amendment.')
    # Shared tails are checked once; long valid correction chains stay linear.
    complete=set()
    for start in edges:
        current=start;path=set()
        while current in edges and current not in complete:
            if current in path:raise ValueError('Ledger correction lineage is cyclic.')
            path.add(current);current=edges[current]
        complete.update(path)
    return originals,reversals


async def read(queries,*,actor_id,company_id,income_year,correlation_id):
    try:
        if type(income_year) is not IncomeYear:raise ValueError()
        rows=[];identities=set();cursors=set();cursor=None
        for _ in range(10000):
            page=await queries.list_entries(actor_id=actor_id,company_ids=(company_id,),correlation_id=correlation_id,cursor=cursor,limit=100)
            if (type(page) is not LedgerEntryPage or type(page.items) is not tuple or len(page.items)>100
                    or type(page.page.has_more) is not bool or page.page.has_more!=(page.page.next_cursor is not None)):
                raise ValueError('Ledger reporting enumeration is incomplete.')
            for row in page.items:
                if (type(row) is not LedgerEntryView or row.company_id!=company_id or row.entry_id in identities
                        or type(row.income_year) is not IncomeYear):raise ValueError('Ledger reporting row scope or identity differs.')
                rows.append(row);identities.add(row.entry_id)
            if not page.page.has_more:break
            cursor=page.page.next_cursor
            if not page.items or type(cursor) is not LedgerCursor or str(cursor) in cursors:raise ValueError('Ledger continuation did not advance.')
            cursors.add(str(cursor))
        else:raise ValueError('Ledger reporting enumeration exceeded its bound.')
        amendments=await queries.list_entry_amendments(actor_id=actor_id,company_id=company_id,correlation_id=correlation_id)
        originals,reversals=_amendments(rows,amendments,company_id)
        effective=tuple(row for row in rows if row.income_year==income_year and row.entry_id not in originals and row.entry_id not in reversals)
        return LedgerReportingSnapshot(company_id,income_year,tuple(rows),amendments,effective,tuple(reversals.items()))
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):raise LedgerError.unavailable() from None
