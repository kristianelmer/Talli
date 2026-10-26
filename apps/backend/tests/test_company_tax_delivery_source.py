"""Tax source composition consumes owner facts, never caller preview rows."""
import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from xml.etree import ElementTree

import pytest

from talli_backend.application.annual_data_compatibility import LegacyAnnualDataView, decode_annual_interview_history
from talli_backend.application.company_tax_delivery_source import read_company_tax_delivery_source
from talli_backend.modules.company_tax_filing.public import (
    CompanyTaxCompanyIdentity, CompanyTaxError, CompanyTaxSourceQuery, prepare_tax_delivery,
)
from talli_backend.modules.ledger.public import (
    LedgerCursor, LedgerEntryId, LedgerEntryKind, LedgerEntryPage, LedgerEntryView,
    LedgerLine, LedgerPage, LedgerSourceCapability, LedgerSourceRecordId,
)
from talli_backend.shared.kernel import CompanyId, CorrelationId, IncomeYear, Money, Timestamp

from test_investment_reporting_source import ACTOR, COMPANY, Queries, event, identity


YEAR = IncomeYear(2025)
NOW = Timestamp(datetime(2025, 4, 15, tzinfo=UTC))
QUERY = CompanyTaxSourceQuery(COMPANY, YEAR, ACTOR)


def annual(**changes):
    values = dict(source_id=identity(700), company_id=COMPANY, income_year=YEAR,
        answers={'company_tax_additional_attachments': 'none', 'shareholder_loans': False,
            'declared_owner_dividends': False, 'bought_or_sold_shares': False},
        confirmations=(), no_activity_confirmed=False, annual_full_time_equivalents=0,
        completed_at=NOW.value.isoformat(), updated_at=NOW.value.isoformat())
    values.update(changes)
    return LegacyAnnualDataView(**values)


def entry(number=1, *, year=YEAR):
    return LedgerEntryView(LedgerEntryId(identity(number+1000)), COMPANY, year,
        LedgerEntryKind.DIVIDEND_RECEIVED, LedgerSourceCapability.INVESTMENTS,
        LedgerSourceRecordId(identity(number)), NOW, 'Recognized dividend',
        (LedgerLine('1530', 'Dividend receivable', Money.nok('1000'), Money.nok('0')),
         LedgerLine('8070', 'Dividend income', Money.nok('0'), Money.nok('1000'))),
        (), None, None, ACTOR, NOW)


class Inputs:
    actor_id = ACTOR
    def __init__(self):
        self.annual = annual()
        self.entries = (entry(),)
        self.investments = Queries(lifecycle_events=(event(income_year=YEAR, created_at=NOW),))
        self.calls = []
        self.pages = None

    @property
    def delivery_investments_queries(self):
        return self.investments

    @property
    def delivery_ledger_queries(self):
        return self

    async def filing_company_identity(self, company_id, actor_id):
        self.calls.append('company')
        assert (company_id, actor_id) == (COMPANY, ACTOR)
        return CompanyTaxCompanyIdentity(COMPANY, '123456789')

    async def delivery_annual_interview(self, query):
        self.calls.append('annual')
        assert query == QUERY
        return self.annual

    async def list_entries(self, **query):
        self.calls.append(('ledger', query['cursor']))
        assert query['actor_id'] == ACTOR and query['company_ids'] == (COMPANY,)
        return self.pages(query) if self.pages else LedgerEntryPage(self.entries, LedgerPage(None, False))


def read(inputs, query=QUERY):
    return asyncio.run(read_company_tax_delivery_source(inputs, query,
        correlation_id=CorrelationId('tax-source-test')))


def test_owner_source_prepares_characterized_dividend_return_without_cash_settlement():
    source = read(Inputs())
    action = source.holding_actions[0]
    assert action['payload']['gross_amount'] == '1000.00'
    assert action['payload']['taxable_add_back'] == '30.00'
    assert source.ledger_entries[0]['lines'][0]['account'] == '1530'
    prepared = prepare_tax_delivery(source, party_number='123456',
        current_document_reference='synthetic-current-2025', schema_sha256='a'*64)
    assert ElementTree.fromstring(prepared.tax_xml).find('.//{*}naeringsinntekt/{*}beloepSomHeltall').text == '30'
    assert '<dokumentidentifikator>synthetic-current-2025</dokumentidentifikator>' in prepared.envelope_xml


def test_ledger_reads_all_pages_before_selecting_year_and_binds_other_year_drift():
    inputs = Inputs()
    other = entry(2, year=IncomeYear(2024))
    def pages(query):
        return (LedgerEntryPage((other,), LedgerPage(LedgerCursor('page-two'), True))
            if query['cursor'] is None else LedgerEntryPage((entry(),), LedgerPage(None, False)))
    inputs.pages = pages
    source = read(inputs)
    assert len(source.ledger_entries) == 1
    original = source.upstream_sha256['ledger']
    other = replace(other, memo='Changed retained history')
    assert read(inputs).upstream_sha256['ledger'] != original


@pytest.mark.parametrize('bad', [
    lambda q: LedgerEntryPage((), LedgerPage(LedgerCursor('same'), True)),
    lambda q: LedgerEntryPage((entry(),), LedgerPage(None, True)),
    lambda q: LedgerEntryPage((entry(), entry()), LedgerPage(None, False)),
    lambda q: LedgerEntryPage((replace(entry(), company_id=CompanyId(identity(99))),), LedgerPage(None, False)),
    lambda q: LedgerEntryPage((object(),), LedgerPage(None, False)),
])
def test_incomplete_or_foreign_ledger_is_unavailable(bad):
    inputs = Inputs()
    inputs.pages = bad
    with pytest.raises(CompanyTaxError):
        read(inputs)


def test_missing_annual_foreign_annual_or_wrong_actor_cannot_publish_source():
    inputs = Inputs()
    inputs.annual = None
    with pytest.raises(CompanyTaxError): read(inputs)
    inputs.annual = annual(company_id=CompanyId(identity(99)))
    with pytest.raises(CompanyTaxError): read(inputs)
    inputs.calls.clear()
    with pytest.raises(CompanyTaxError):
        read(inputs, replace(QUERY, actor_id=replace(ACTOR, subject=type(ACTOR.subject)(identity(99)))))
    assert inputs.calls == []


def history():
    return [{'sourceId': identity(700), 'companyId': str(COMPANY), 'incomeYear': 2025,
        'answers': {'has_unpaid_items': True}, 'confirmations': [],
        'noActivityConfirmed': False, 'annualFullTimeEquivalents': None,
        'completedAt': NOW.value.isoformat(), 'updatedAt': NOW.value.isoformat()}]


def test_annual_history_decoder_keeps_common_readiness_facts_without_deciding_them():
    rows = history()
    decoded = decode_annual_interview_history(rows, COMPANY, YEAR)
    assert decoded.answers['has_unpaid_items'] is True
    assert decode_annual_interview_history([], COMPANY, YEAR) is None
    rows[0]['answers']['has_unpaid_items'] = False
    assert decoded.answers['has_unpaid_items'] is True


@pytest.mark.parametrize('change', [
    lambda rows: rows.append(dict(rows[0])),
    lambda rows: rows[0].update(companyId=identity(99)),
    lambda rows: rows[0].update(incomeYear=2026),
    lambda rows: rows[0].update(completedAt='2025-04-15T00:00:00'),
    lambda rows: rows[0].update(noActivityConfirmed='false'),
    lambda rows: rows[0].update(annualFullTimeEquivalents=float('nan')),
    lambda rows: rows[0].update(extra=True),
])
def test_annual_history_decoder_rejects_ambiguity_and_malformed_scope(change):
    rows = history(); change(rows)
    with pytest.raises(ValueError): decode_annual_interview_history(rows, COMPANY, YEAR)
