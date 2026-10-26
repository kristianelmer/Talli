"""Reporting must retain complete provenance without duplicating income."""
import asyncio
from dataclasses import fields, replace
from datetime import UTC, date, datetime
import json

import pytest

from talli_backend.modules.investments import public as inv
from talli_backend.shared.kernel import (
    ActorId, ActorKind, CompanyId, CorrelationId, IncomeYear, LocalDate,
    Money, Timestamp, UserId,
)


COMPANY = CompanyId('10000000-0000-0000-0000-000000000001')
ACTOR = ActorId(ActorKind.USER, UserId('20000000-0000-0000-0000-000000000001'))
YEAR = IncomeYear(2026)
POSITION = inv.InvestmentPositionId('30000000-0000-0000-0000-000000000001')
WHEN = Timestamp(datetime(2026, 4, 15, tzinfo=UTC))


def identity(number):
    return f'40000000-0000-0000-0000-{number:012d}'


def event(number=1, *, legacy=False, **changes):
    kind = inv.InvestmentActivityView if legacy else inv.InvestmentLifecycleEventView
    values = {field.name: None for field in fields(kind)}
    values.update(company_id=COMPANY, income_year=YEAR,
        activity_kind=inv.InvestmentActivityKind.DIVIDEND_RECEIVED,
        position_id=POSITION, investment_key='example', investment_name='Example AS',
        investment_kind=inv.InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
        accounting_classification=inv.InvestmentAccountingClassification.OTHER_LONG_TERM,
        tax_treatment=inv.InvestmentTaxTreatment.EXEMPTION_METHOD,
        org_number='123456789', paying_company_name='Example AS',
        gross_amount=Money.nok('1000.00'), taxable_add_back=Money.nok('30.00'),
        lawful_dividend_confirmed=True, group_exception_claimed=False,
        group_exception_applied=False, evidence_mode=inv.InvestmentEvidenceMode.LINKED_SOURCES,
        evidence_reference='synthetic-dividend-advice', evidence_digest='a'*64,
        calculation_id='b'*64, owner_attested=False, created_by=ACTOR, created_at=WHEN)
    posting = inv.AccountingEntryReference(identity(number + 1000))
    if legacy:
        values.update(activity_id=inv.InvestmentActionId(identity(number)),
            action_date=LocalDate(date(2026, 4, 15)), accounting_entry_id=posting,
            document_status=inv.InvestmentDocumentStatus.ATTACHED)
    else:
        values.update(event_id=inv.InvestmentEconomicEventId(identity(number)),
            recognition_date=LocalDate(date(2026, 4, 15)),
            expected_settlement_amount=Money.nok('1000.00'),
            settlement_balance_kind=inv.InvestmentSettlementBalanceKind.DIVIDEND_RECEIVABLE,
            recognition_accounting_entry_id=posting, document_facts=())
    values.update(changes)
    when_name = 'action_date' if legacy else 'recognition_date'
    if 'income_year' in changes and when_name not in changes:
        values[when_name] = LocalDate(date(int(values['income_year']), 4, 15))
    return kind(**values)


def position(**changes):
    values = dict(position_id=POSITION, company_id=COMPANY, investment_key='example',
        name='Example AS', kind=inv.InvestmentKind.NORWEGIAN_PRIVATE_COMPANY,
        accounting_classification=inv.InvestmentAccountingClassification.OTHER_LONG_TERM,
        tax_treatment=inv.InvestmentTaxTreatment.EXEMPTION_METHOD, org_number='123456789',
        fund_equity_ratio_basis_points=None, fund_tax_statement_reference=None,
        share_count=inv.InvestmentUnits.of('10'), cost_basis=Money.nok('800.00'),
        tax_basis=Money.nok('700.00'), lot_history_status=inv.InvestmentLotHistoryStatus.COMPLETE,
        movement_count=1, movements=({'movement_type': 'purchase_recognition'},),
        created_by=ACTOR, created_at=WHEN, updated_at=WHEN)
    values.update(changes)
    return inv.InvestmentPositionView(**values)


def correction(original=1, replacement=2, *, number=501, **changes):
    values = dict(correction_id=inv.InvestmentCorrectionId(identity(number)), company_id=COMPANY,
        income_year=YEAR, target_kind=inv.InvestmentCorrectionTargetKind.ECONOMIC_EVENT,
        original_record_id=inv.InvestmentEconomicEventId(identity(original)),
        original_activity_kind=inv.InvestmentActivityKind.DIVIDEND_RECEIVED,
        reversal_accounting_entry_id=inv.AccountingEntryReference(identity(number+1000)),
        replacement_record_id=inv.InvestmentEconomicEventId(identity(replacement)),
        replacement_activity_kind=inv.InvestmentActivityKind.DIVIDEND_RECEIVED,
        replacement_accounting_entry_id=inv.AccountingEntryReference(identity(replacement+1000)),
        reason='Correct evidenced dividend amount', document_facts=(),
        legacy_bank_transaction_id=None, legacy_document_id=None, legacy_document_status=None,
        legacy=False, evidence_mode=inv.InvestmentEvidenceMode.LINKED_SOURCES,
        evidence_reference='synthetic-correction-document', evidence_digest='c'*64,
        owner_attested=False, created_by=ACTOR, created_at=WHEN)
    values.update(changes)
    return inv.InvestmentCorrectionView(**values)


FAMILIES = {
    'activity': inv.InvestmentActivityPage,
    'lifecycle_events': inv.InvestmentLifecycleEventPage,
    'corrections': inv.InvestmentCorrectionPage,
    'positions': inv.InvestmentPositionPage,
    'year_end_measurements': inv.InvestmentYearEndMeasurementPage,
    'acquisition_lots': inv.AcquisitionLotPage,
    'share_sale_allocations': inv.ShareSaleAllocationPage,
}


class Queries:
    def __init__(self, **rows):
        self.rows = {'positions': (position(),), **rows}
        self.calls = []
        self.overrides = {}

    def __getattr__(self, method):
        family = method.removeprefix('list_')
        page_type = FAMILIES[family]

        async def read(**query):
            assert query['actor_id'] == ACTOR
            assert query['company_ids'] == (COMPANY,)
            assert query['limit'] == 100
            self.calls.append((family, query['cursor']))
            if family in self.overrides:
                return self.overrides[family](query)
            return page_type(self.rows.get(family, ()), None, False)
        return read


def read(queries, year=YEAR):
    return asyncio.run(inv.read_investment_reporting_snapshot(queries, actor_id=ACTOR,
        company_id=COMPANY, income_year=year, correlation_id=CorrelationId('reporting-test')))


def test_recognized_unsettled_dividend_is_reported_without_cash_or_second_calculation():
    source = read(Queries(lifecycle_events=(event(),)))
    assert source.active_events[0].gross_amount == Money.nok('1000')
    assert source.active_events[0].taxable_add_back == Money.nok('30')
    assert source.active_events[0].settlement_id is None
    assert source.positions[0].cost_basis != source.positions[0].tax_basis
    assert len(source.source_sha256) == 64
    assert set(json.loads(source.source_json)) == {
        'version', 'company_id', 'income_year', *FAMILIES}


def test_pagination_is_complete_and_other_year_facts_remain_in_evidence():
    queries = Queries(lifecycle_events=())
    first = event(1, income_year=IncomeYear(2025))
    last = event(2)
    def pages(query):
        if query['cursor'] is None:
            return inv.InvestmentLifecycleEventPage((first,), inv.InvestmentCursor(identity(1)), True)
        assert str(query['cursor']) == identity(1)
        return inv.InvestmentLifecycleEventPage((last,), None, False)
    queries.overrides['lifecycle_events'] = pages
    source = read(queries)
    assert source.active_events == (last,)
    assert len(json.loads(source.source_json)['lifecycle_events']) == 2
    assert [str(cursor) if cursor else None for family, cursor in queries.calls
            if family == 'lifecycle_events'] == [None, identity(1)]


def test_chained_economic_corrections_keep_only_final_head_and_all_originals():
    queries = Queries(lifecycle_events=(event(1), event(2), event(3)),
        corrections=(correction(), correction(2, 3, number=502)))
    source = read(queries)
    assert [str(row.event_id) for row in source.active_events] == [identity(3)]
    retained = json.loads(source.source_json)
    assert len(retained['lifecycle_events']) == 3
    assert len(retained['corrections']) == 2
    queries.rows['lifecycle_events'] = (event(1, gross_amount=Money.nok('999')), event(2), event(3))
    assert read(queries).source_sha256 != source.source_sha256


def test_exact_lifecycle_sale_overlap_is_counted_once():
    legacy = event(legacy=True, activity_kind=inv.InvestmentActivityKind.SHARE_SALE,
        gross_amount=None, taxable_add_back=None, paying_company_name=None,
        book_gain_or_loss=Money.nok('100'), tax_gain_or_loss=Money.nok('120'),
        exempt_gain=Money.nok('120'), taxable_gain=Money.nok('0'),
        non_deductible_loss=Money.nok('0'), deductible_loss=Money.nok('0'))
    current = event()
    # Both public projections carry the same immutable sale calculation/post.
    common = {field.name for field in fields(legacy)} & {field.name for field in fields(current)}
    current = replace(current, **{**{name: getattr(legacy, name) for name in common},
        'activity_kind': inv.InvestmentActivityKind.SHARE_SALE})
    legacy = replace(legacy, activity_kind=inv.InvestmentActivityKind.SHARE_SALE)
    assert len(read(Queries(activity=(legacy,), lifecycle_events=(current,))).active_events) == 1
    with pytest.raises(inv.InvestmentsError):
        read(Queries(activity=(legacy,), lifecycle_events=(replace(current, proceeds=Money.nok('12')),)))


def test_snapshot_does_not_retain_nested_caller_mutability():
    movements = [{'movement_type': 'purchase_recognition', 'details': ['original']}]
    queries = Queries(positions=(position(movements=movements),), lifecycle_events=(event(),))
    source = read(queries)
    digest = source.source_sha256
    movements[0]['details'].append('changed')
    assert source.positions[0].movements[0]['details'] == ('original',)
    assert source.source_sha256 == digest
    with pytest.raises(TypeError):
        source.positions[0].movements[0]['movement_type'] = 'changed'


@pytest.mark.parametrize('bad', [
    lambda q: inv.InvestmentLifecycleEventPage((), inv.InvestmentCursor(identity(1)), True),
    lambda q: inv.InvestmentLifecycleEventPage((event(),), None, True),
    lambda q: inv.InvestmentLifecycleEventPage((event(),), inv.InvestmentCursor(identity(2)), True),
    lambda q: inv.InvestmentLifecycleEventPage((event(), event()), None, False),
    lambda q: inv.InvestmentLifecycleEventPage((event(2), event(1)), None, False),
    lambda q: inv.InvestmentLifecycleEventPage((event(),), None, 0),
    lambda q: inv.InvestmentLifecycleEventPage((event(company_id=CompanyId(identity(99))),), None, False),
    lambda q: inv.InvestmentLifecycleEventPage((event(),)*101, None, False),
    lambda q: inv.InvestmentLifecycleEventPage((object(),), None, False),
])
def test_incomplete_foreign_or_invalid_enumeration_fails_closed(bad):
    queries = Queries()
    queries.overrides['lifecycle_events'] = bad
    with pytest.raises(inv.InvestmentsError) as error:
        read(queries)
    assert error.value.code == inv.InvestmentsErrorCode.DEPENDENCY_UNAVAILABLE


@pytest.mark.parametrize('rows', [
    (correction(replacement=9),),
    (correction(), correction(2, 1, number=502)),
    (correction(), correction(1, 3, number=502)),
    (correction(1, 3), correction(2, 3, number=502)),
    (correction(income_year=IncomeYear(2025)),),
    (correction(replacement_activity_kind=inv.InvestmentActivityKind.SHARE_SALE),),
    (correction(replacement_accounting_entry_id=inv.AccountingEntryReference(identity(99))),),
])
def test_incomplete_cyclic_forked_or_unbound_correction_lineage_fails_closed(rows):
    with pytest.raises(inv.InvestmentsError):
        read(Queries(lifecycle_events=(event(1), event(2), event(3)), corrections=rows))


def test_missing_position_or_nonfinite_retained_fact_fails_closed():
    with pytest.raises(inv.InvestmentsError):
        read(Queries(positions=(), lifecycle_events=(event(),)))
    with pytest.raises(inv.InvestmentsError):
        read(Queries(positions=(position(movements=({'invalid': float('nan')},)),)))


@pytest.mark.parametrize('changes', [
    {'gross_amount': None}, {'taxable_add_back': None},
    {'recognition_accounting_entry_id': None}, {'calculation_id': 'unproved'},
    {'evidence_digest': 'unproved'}, {'recognition_date': LocalDate(date(2025, 4, 15))},
])
def test_missing_economic_amounts_or_posting_evidence_never_become_zero_income(changes):
    with pytest.raises(inv.InvestmentsError):
        read(Queries(lifecycle_events=(event(**changes),)))


def test_cash_settlement_correction_never_removes_the_economic_income():
    cash = correction(target_kind=inv.InvestmentCorrectionTargetKind.CASH_SETTLEMENT,
        original_record_id=inv.InvestmentSettlementId(identity(50)),
        replacement_record_id=inv.InvestmentSettlementId(identity(51)),
        replacement_accounting_entry_id=inv.AccountingEntryReference(identity(1051)))
    settled = event(settlement_id=inv.InvestmentSettlementId(identity(51)),
        settlement_accounting_entry_id=inv.AccountingEntryReference(identity(1051)),
        settlement_date=LocalDate(date(2026, 5, 1)), settlement_amount=Money.nok('1000'))
    assert len(read(Queries(lifecycle_events=(settled,), corrections=(cash,))).active_events) == 1
    with pytest.raises(inv.InvestmentsError):
        read(Queries(lifecycle_events=(event(),), corrections=(cash,)))
