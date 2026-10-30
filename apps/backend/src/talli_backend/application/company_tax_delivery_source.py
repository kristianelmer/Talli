"""Named Tax source read: compose immutable public facts in one snapshot."""
from __future__ import annotations

from typing import Protocol

from talli_backend.application.annual_data_compatibility import LegacyAnnualDataView
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxCompanyIdentity, CompanyTaxError, CompanyTaxSourceQuery,
    TaxDeliverySource, tax_delivery_digest,
)
from talli_backend.modules.investments.public import (
    InvestmentActivityView, InvestmentLifecycleEventView, InvestmentsQueries,
    InvestmentsError, read_investment_reporting_snapshot,
)
from talli_backend.modules.ledger.public import LedgerQueries, LedgerError, LedgerEntryAmendment, LedgerEntryKind, LedgerEntryPage, LedgerEntryView, LedgerCursor
from talli_backend.shared.kernel import ActorId, CompanyId, CorrelationId, IncomeYear


class TaxDeliverySourceInputs(Protocol):
    @property
    def actor_id(self) -> ActorId: ...
    @property
    def delivery_ledger_queries(self) -> LedgerQueries: ...
    @property
    def delivery_investments_queries(self) -> InvestmentsQueries: ...
    async def filing_company_identity(self, company_id: CompanyId,
                                     actor_id: ActorId) -> CompanyTaxCompanyIdentity: ...
    async def delivery_annual_interview(self, query: CompanyTaxSourceQuery) -> LegacyAnnualDataView | None: ...


async def _ledger_entries(queries, query, correlation_id):
    rows, identities, cursors, cursor = [], set(), set(), None
    for _ in range(10000):
        page = await queries.list_entries(actor_id=query.actor_id, company_ids=(query.company_id,),
            correlation_id=correlation_id, cursor=cursor, limit=100)
        if (not isinstance(page, LedgerEntryPage) or type(page.page.has_more) is not bool
                or not isinstance(page.items, tuple) or len(page.items) > 100
                or page.page.has_more != (page.page.next_cursor is not None)):
            raise ValueError('Incomplete Tax ledger enumeration.')
        for row in page.items:
            if (not isinstance(row, LedgerEntryView) or row.company_id != query.company_id
                    or str(row.entry_id) in identities or not isinstance(row.income_year, IncomeYear)):
                raise ValueError('Tax ledger source scope/identity mismatch.')
            identities.add(str(row.entry_id))
            rows.append(row)
        if not page.page.has_more:
            return tuple(rows)
        next_cursor = page.page.next_cursor
        if not page.items or not isinstance(next_cursor, LedgerCursor) or str(next_cursor) in cursors:
            raise ValueError('Tax ledger continuation did not advance.')
        cursors.add(str(next_cursor))
        cursor = next_cursor
    raise ValueError('Tax ledger enumeration exceeded its bound.')


def _investment_action(row: InvestmentActivityView | InvestmentLifecycleEventView):
    # Investments owns the calculation/classification. This is a lossless shape
    # adapter for the characterized Tax calculator, with no new amount rules.
    amounts = ('gross_amount', 'taxable_add_back', 'book_gain_or_loss', 'tax_gain_or_loss',
        'exempt_gain', 'taxable_gain', 'non_deductible_loss', 'deductible_loss',
        'dividend_portion', 'interest_portion', 'total_taxable_income', 'proceeds',
        'net_proceeds', 'purchase_amount', 'transaction_costs', 'capitalized_cost',
        'fifo_cost_basis_reduction', 'fifo_tax_basis_reduction')
    payload = {name: format(getattr(row, name).amount, 'f') for name in amounts
               if getattr(row, name) is not None}
    payload.update(tax_treatment=row.tax_treatment.value, calculation_id=row.calculation_id,
        investment_name=row.investment_name, org_number=row.org_number,
        evidence_digest=row.evidence_digest)
    identity = row.activity_id if isinstance(row, InvestmentActivityView) else row.event_id
    return {'id': str(identity), 'company_id': str(row.company_id),
        'income_year': int(row.income_year), 'action_type': row.activity_kind.value,
        'risk_level': 'info', 'payload': payload}


def _entry_type(row):
    return 'admin_cost' if row.entry_kind is LedgerEntryKind.ADMINISTRATIVE_COST else row.entry_kind.value.lower()


def _ledger_reversals(entries, amendments, company_id):
    indexed = {row.entry_id: row for row in entries}
    originals, reversals = set(), {}
    if not isinstance(amendments, tuple):
        raise ValueError('Ledger amendment enumeration is incomplete.')
    for amendment in amendments:
        if not isinstance(amendment, LedgerEntryAmendment) or amendment.company_id != company_id:
            raise ValueError('Ledger amendment scope is invalid.')
        original, reversal = indexed.get(amendment.original_entry_id), indexed.get(amendment.reversal_entry_id)
        replacement = indexed.get(amendment.replacement_entry_id) if amendment.replacement_entry_id else None
        if (original is None or reversal is None or original.entry_id in originals
                or reversal.entry_id in reversals or original.entry_id == reversal.entry_id
                or reversal.entry_kind is not LedgerEntryKind.CORRECTION_REVERSAL
                or original.income_year != amendment.income_year or reversal.income_year != amendment.income_year
                or (amendment.replacement_entry_id is not None and
                    (replacement is None or replacement.income_year != amendment.income_year
                     or replacement.entry_id in (original.entry_id, reversal.entry_id)))):
            raise ValueError('Ledger correction lineage is incomplete or ambiguous.')
        originals.add(original.entry_id)
        reversals[reversal.entry_id] = original
    return reversals


async def read_company_tax_delivery_source(inputs: TaxDeliverySourceInputs,
        query: CompanyTaxSourceQuery, *, correlation_id: CorrelationId) -> TaxDeliverySource:
    if inputs.actor_id != query.actor_id:
        raise CompanyTaxError.forbidden()
    try:
        company = await inputs.filing_company_identity(query.company_id, query.actor_id)
        annual = await inputs.delivery_annual_interview(query)
        if (company.company_id != query.company_id or annual is None
                or annual.company_id != query.company_id or annual.income_year != query.income_year):
            raise ValueError('Tax annual source is missing or outside its scope.')
        entries = await _ledger_entries(inputs.delivery_ledger_queries, query, correlation_id)
        amendments = await inputs.delivery_ledger_queries.list_entry_amendments(actor_id=query.actor_id,
            company_id=query.company_id, correlation_id=correlation_id)
        reversals = _ledger_reversals(entries, amendments, query.company_id)
        investments = await read_investment_reporting_snapshot(inputs.delivery_investments_queries,
            actor_id=query.actor_id, company_id=query.company_id, income_year=query.income_year,
            correlation_id=correlation_id)
        annual_data = {'id': annual.source_id, 'company_id': str(annual.company_id),
            'income_year': int(annual.income_year), 'answers': annual.answers,
            'confirmations': annual.confirmations, 'no_activity_confirmed': annual.no_activity_confirmed,
            'annual_full_time_equivalents': annual.annual_full_time_equivalents,
            'completed_at': annual.completed_at, 'updated_at': annual.updated_at}
        ledger = tuple({'id': str(row.entry_id), 'company_id': str(row.company_id),
            'income_year': int(row.income_year),
            'entry_type': _entry_type(row),
            **({'reversal_of': str(reversals[row.entry_id].entry_id),
                'reversed_entry_type': _entry_type(reversals[row.entry_id])} if row.entry_id in reversals else {}),
            'memo': row.memo, 'lines': tuple({'account': line.account, 'description': line.description,
                'debit': format(line.debit.amount, 'f'), 'credit': format(line.credit.amount, 'f')}
                for line in row.lines), 'risk_flags': tuple(flag.code.value for flag in row.risk_flags),
            'warning_accepted_at': row.warning_accepted_at.value.isoformat() if row.warning_accepted_at else None}
            for row in entries if row.income_year == query.income_year)
        return TaxDeliverySource(query.company_id, query.income_year, company.organization_number,
            annual_data, ledger, tuple(_investment_action(row) for row in investments.active_events),
            {'annual': tax_delivery_digest(annual), 'ledger': tax_delivery_digest({'entries': entries, 'amendments': amendments}),
             'investments': investments.source_sha256})
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, InvestmentsError, LedgerError):
        raise CompanyTaxError.unavailable() from None
