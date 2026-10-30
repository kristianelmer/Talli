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
    LedgerCursor, LedgerEntryAmendment, LedgerEntryId, LedgerEntryKind, LedgerEntryPage, LedgerEntryView,
    LedgerLine, LedgerPage, LedgerSourceCapability, LedgerSourceRecordId,
)
from talli_backend.shared.kernel import CompanyId, CorrelationId, IncomeYear, Money, Timestamp

from test_investment_reporting_source import ACTOR, COMPANY, Queries, correction, event, identity
from talli_backend.modules.investments import public as inv


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
        self.amendments = ()

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

    async def list_entry_amendments(self, **query):
        assert query['actor_id'] == ACTOR and query['company_id'] == COMPANY
        return self.amendments


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
    business = ElementTree.fromstring(prepared.business_xml)
    balances = {row.find('./{*}type/{*}resultatOgBalanseregnskapstype').text:
        row.find('./{*}beloep/{*}beloep/{*}beloep').text
        for row in business.findall('.//{*}balanseverdiForOmloepsmiddel/{*}balanseverdi')}
    assert balances['1570'] == '1000'
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


def test_corrected_administrative_cost_nets_reversal_in_return_and_estimate():
    from talli_backend.modules.company_tax_filing.public import CompanyTaxReturnSource, estimate_annual_tax
    def cost(number, amount, kind=LedgerEntryKind.ADMINISTRATIVE_COST):
        debit, credit = ('0', amount) if kind is LedgerEntryKind.CORRECTION_REVERSAL else (amount, '0')
        return replace(entry(number), entry_kind=kind,
            lines=(LedgerLine('7770', 'Administrative cost', Money.nok(debit), Money.nok(credit)),
                   LedgerLine('1920', 'Cost payment', Money.nok(credit), Money.nok(debit))))
    inputs = Inputs()
    original, reversal, replacement = cost(2, '100'), cost(3, '100', LedgerEntryKind.CORRECTION_REVERSAL), cost(4, '60')
    inputs.entries += (original, reversal, replacement)
    inputs.amendments = (LedgerEntryAmendment(original.entry_id, reversal.entry_id,
        replacement.entry_id, COMPANY, YEAR, 'Correct cost', ACTOR, NOW),)
    source = read(inputs)
    prepared = prepare_tax_delivery(source, party_number='123456',
        current_document_reference='synthetic-current-2025', schema_sha256='a'*64)
    assert ElementTree.fromstring(prepared.tax_xml).find('.//{*}underskudd/{*}beloepSomHeltall').text == '30'
    annual_estimate = estimate_annual_tax(CompanyTaxReturnSource(source.organization_number, int(YEAR),
        source.annual_data, source.ledger_entries, source.holding_actions))
    assert annual_estimate.admin_costs == 60
    assert annual_estimate.tax_basis == -30
    costs = ElementTree.fromstring(prepared.business_xml).findall('.//{*}annenDriftskostnad/{*}kostnad')
    assert len(costs) == 1 and costs[0].find('./{*}beloep/{*}beloep/{*}beloep').text == '60'


def test_corrected_share_loss_nets_reversal_against_current_investment_head():
    def sale(number, loss):
        return event(number, income_year=YEAR, activity_kind=inv.InvestmentActivityKind.SHARE_SALE,
            gross_amount=None, taxable_add_back=None, paying_company_name=None,
            book_gain_or_loss=Money.nok('-'+loss), tax_gain_or_loss=Money.nok('-'+loss),
            exempt_gain=Money.nok('0'), taxable_gain=Money.nok('0'),
            non_deductible_loss=Money.nok(loss), deductible_loss=Money.nok('0'))
    def loss_entry(number, amount, reverse=False):
        debit, credit = ('0',amount) if reverse else (amount,'0')
        return replace(entry(number), entry_kind=LedgerEntryKind.CORRECTION_REVERSAL if reverse else LedgerEntryKind.SHARE_SALE,
            lines=(LedgerLine('8090','Share loss',Money.nok(debit),Money.nok(credit)),
                   LedgerLine('1300','Share book value',Money.nok(credit),Money.nok(debit))))
    inputs = Inputs()
    inputs.entries = (loss_entry(2,'100'), loss_entry(3,'100',True), loss_entry(4,'60'))
    inputs.investments = Queries(lifecycle_events=(sale(2,'100'),sale(4,'60')),
        corrections=(correction(2,4,income_year=YEAR,
            original_activity_kind=inv.InvestmentActivityKind.SHARE_SALE,
            replacement_activity_kind=inv.InvestmentActivityKind.SHARE_SALE,
            reversal_accounting_entry_id=inv.AccountingEntryReference(identity(1003))),))
    source = read(inputs)
    prepared = prepare_tax_delivery(source, party_number='123456',
        current_document_reference='synthetic-current-2025', schema_sha256='a'*64)
    costs = ElementTree.fromstring(prepared.business_xml).findall('.//{*}finanskostnad/{*}kostnad')
    assert len(costs)==1 and costs[0].find('./{*}beloep/{*}beloep/{*}beloep').text == '60'
    assert len(source.holding_actions) == 1


def test_bank_receivable_and_current_security_balances_have_distinct_xml_occurrences():
    inputs = Inputs()
    opening = replace(entry(2), entry_kind=LedgerEntryKind.OPENING_BALANCE,
        lines=tuple(LedgerLine(account, 'Opening balance', Money.nok(amount), Money.nok('0'))
            for account,amount in [('1810','800'),('1815','200'),('1920','300')]) +
            (LedgerLine('2000','Share capital',Money.nok('0'),Money.nok('1300')),))
    inputs.entries += (opening,)
    source = read(inputs)
    prepared = prepare_tax_delivery(source, party_number='123456',
        current_document_reference='synthetic-current-2025', schema_sha256='a'*64)
    rows = ElementTree.fromstring(prepared.business_xml).findall('.//{*}balanseverdiForOmloepsmiddel/{*}balanseverdi')
    codes = [row.find('./{*}type/{*}resultatOgBalanseregnskapstype').text for row in rows]
    values = [row.find('./{*}beloep/{*}beloep/{*}beloep').text for row in rows]
    assert len(codes)==len(set(codes))==4
    assert dict(zip(codes,values)) == {'1810':'800','1815':'200','1920':'300','1570':'1000'}


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
