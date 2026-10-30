"""Complete Ledger inputs for RF annual policy on an already guarded session."""
from dataclasses import dataclass

from talli_backend.modules.ledger.public import (
    LedgerCursor, LedgerPage, LedgerQueries, OpeningBankInput, PeriodLock, PeriodLockPage,
)
from talli_backend.modules.shareholder_register_filing import public as rf
from talli_backend.shared.kernel import CompanyId, CorrelationId, IncomeYear


@dataclass(frozen=True, slots=True)
class Rf1086AnnualLedgerInputs:
    """Original bank inputs and compatibility locks; neither proves year close."""
    company_id: CompanyId
    income_year: IncomeYear
    opening_bank_inputs: tuple[OpeningBankInput, ...]
    period_locks: tuple[PeriodLock, ...]


async def read_annual_ledger_inputs(ledger: LedgerQueries, query: rf.Rf1086SourceQuery,
                                   correlation_id: CorrelationId) -> Rf1086AnnualLedgerInputs:
    """Read every lock page before selecting the requested year.

    The caller owns the shared company guard and connection throughout. The
    existing Ledger contracts retain their authorization and history semantics.
    A missing source is represented only after successful complete enumeration.
    """
    openings = await ledger.read_opening_bank_inputs(actor_id=query.actor_id,
        company_id=query.company_id, income_year=query.income_year, correlation_id=correlation_id)
    if (type(openings) is not tuple
            or any(not isinstance(item, OpeningBankInput) or item.company_id != query.company_id
                   or item.income_year != query.income_year for item in openings)
            or len({item.snapshot_id for item in openings}) != len(openings)):
        raise rf.ShareholderRegisterFilingError.unavailable()
    cursor = None
    cursors, identities = set(), set()
    selected = []
    while True:
        page = await ledger.list_period_locks(actor_id=query.actor_id,
            company_ids=(query.company_id,), correlation_id=correlation_id, cursor=cursor, limit=100)
        if (not isinstance(page, PeriodLockPage) or type(page.items) is not tuple
                or not isinstance(page.page, LedgerPage)
                or type(page.page.has_more) is not bool
                or (page.page.next_cursor is not None and not isinstance(page.page.next_cursor, LedgerCursor))
                or page.page.has_more != (page.page.next_cursor is not None)
                or len(page.items) > 100
                or ((page.page.has_more or cursor is not None) and not page.items)):
            raise rf.ShareholderRegisterFilingError.unavailable()
        for item in page.items:
            if (not isinstance(item, PeriodLock) or item.company_id != query.company_id
                    or item.period_lock_id in identities):
                raise rf.ShareholderRegisterFilingError.unavailable()
            identities.add(item.period_lock_id)
            if item.income_year == query.income_year:
                selected.append(item)
        if not page.page.has_more:
            return Rf1086AnnualLedgerInputs(
                query.company_id, query.income_year,
                tuple(sorted(openings, key=lambda item: item.snapshot_id)),
                tuple(sorted(selected, key=lambda item: str(item.period_lock_id))))
        cursor = page.page.next_cursor
        if str(cursor) in cursors:
            raise rf.ShareholderRegisterFilingError.unavailable()
        cursors.add(str(cursor))
