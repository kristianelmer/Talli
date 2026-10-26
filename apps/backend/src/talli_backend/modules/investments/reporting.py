"""Complete, immutable reporting reads of Investments' published facts.

The application supplies queries bound to its coherent database snapshot. This
reader neither authorizes a filing nor calculates a second set of book/tax facts.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
import re
from types import MappingProxyType

from talli_backend.shared.kernel import ActorId, CompanyId, CorrelationId, IncomeYear, Money, LocalDate

from .public import (
    AccountingEntryReference, AcquisitionLotPage, AcquisitionLotView, InvestmentActivityKind,
    InvestmentActivityPage, InvestmentActivityView, InvestmentCorrectionPage,
    InvestmentCorrectionTargetKind, InvestmentCorrectionView, InvestmentCursor,
    InvestmentLifecycleEventPage, InvestmentLifecycleEventView,
    InvestmentPositionPage, InvestmentPositionView, InvestmentsError,
    InvestmentsQueries, InvestmentYearEndMeasurementPage,
    InvestmentYearEndMeasurementView, ShareSaleAllocationPage, ShareSaleAllocationView,
)


def _primitive(value):
    if is_dataclass(value):
        return {field.name: _primitive(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError('Reporting fact keys must be text.')
        return {key: _primitive(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(child) for child in value]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError('Reporting amounts must be finite.')
        return str(value)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError('Reporting times require a timezone.')
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError('Unsupported reporting fact.')


def _json(value):
    return json.dumps(_primitive(value), sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)


def _freeze(value):
    if is_dataclass(value):
        if not value.__dataclass_params__.frozen:
            raise ValueError('Reporting value contracts must be immutable.')
        return replace(value, **{field.name: _freeze(getattr(value, field.name))
                                 for field in fields(value)})
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(child) for child in value)
    return value


@dataclass(frozen=True, slots=True)
class InvestmentReportingSnapshot:
    """All source families retained; only current economic heads enter totals.

    Positions are current source evidence, not a fabricated historical balance.
    Every measurement for the selected year is retained, without guessing which
    one a filing should use. ``source_json`` also retains predecessor/correction,
    lot, allocation, and other-year evidence for exact review invalidation.
    """
    company_id: CompanyId
    income_year: IncomeYear
    active_events: tuple[InvestmentActivityView | InvestmentLifecycleEventView, ...]
    positions: tuple[InvestmentPositionView, ...]
    year_end_measurements: tuple[InvestmentYearEndMeasurementView, ...]
    source_json: str

    def __post_init__(self):
        for name in ('active_events', 'positions', 'year_end_measurements'):
            object.__setattr__(self, name, _freeze(getattr(self, name)))

    @property
    def source_sha256(self) -> str:
        return sha256(self.source_json.encode('utf-8')).hexdigest()


async def _all_pages(queries, method, page_type, row_type, identity, *, actor_id,
                     company_id, correlation_id):
    cursor, rows, identities = None, [], set()
    # A bound is a dependency failure, never a successful truncated snapshot.
    for _ in range(10000):
        page = await getattr(queries, method)(actor_id=actor_id, company_ids=(company_id,),
            correlation_id=correlation_id, cursor=cursor, limit=100)
        if (not isinstance(page, page_type) or type(page.has_more) is not bool
                or not isinstance(page.items, tuple) or len(page.items) > 100
                or page.has_more != (page.next_cursor is not None)
                or (page.next_cursor is not None and not isinstance(page.next_cursor, InvestmentCursor))):
            raise ValueError('Incomplete reporting enumeration.')
        prior = str(cursor) if cursor is not None else ''
        for row in page.items:
            if (not isinstance(row, row_type) or row.company_id != company_id
                    or (hasattr(row, 'income_year') and not isinstance(row.income_year, IncomeYear))):
                raise ValueError('Reporting source scope mismatch.')
            key = str(getattr(row, identity))
            if key in identities or key <= prior:
                raise ValueError('Reporting source identity/cursor mismatch.')
            identities.add(key)
            rows.append(row)
            prior = key
        if page.has_more and (not page.items or str(page.next_cursor) != prior):
            raise ValueError('Reporting continuation does not match its page.')
        if not page.has_more:
            return tuple(rows)
        cursor = page.next_cursor
    raise ValueError('Reporting enumeration exceeded its bound.')


def _economic_events(activity, lifecycle):
    required_amounts = {
        InvestmentActivityKind.SHARE_PURCHASE: ('purchase_amount', 'transaction_costs', 'capitalized_cost'),
        InvestmentActivityKind.SHARE_SALE: ('book_gain_or_loss', 'tax_gain_or_loss', 'exempt_gain',
            'taxable_gain', 'non_deductible_loss', 'deductible_loss'),
        InvestmentActivityKind.DIVIDEND_RECEIVED: ('gross_amount', 'taxable_add_back'),
        InvestmentActivityKind.FUND_DISTRIBUTION_RECEIVED: ('gross_amount', 'dividend_portion',
            'interest_portion', 'taxable_add_back', 'total_taxable_income'),
    }
    for row in (*activity, *lifecycle):
        when = row.action_date if isinstance(row, InvestmentActivityView) else row.recognition_date
        posting = row.accounting_entry_id if isinstance(row, InvestmentActivityView) else row.recognition_accounting_entry_id
        if (row.activity_kind not in required_amounts or not isinstance(when, LocalDate)
                or when.value.year != int(row.income_year)
                or not isinstance(posting, AccountingEntryReference)
                or any(not isinstance(getattr(row, name), Money) for name in required_amounts[row.activity_kind])
                or type(row.calculation_id) is not str or re.fullmatch('[0-9a-f]{64}', row.calculation_id) is None
                or type(row.evidence_digest) is not str or re.fullmatch('[0-9a-f]{64}', row.evidence_digest) is None):
            raise ValueError('Economic reporting calculation/posting evidence is incomplete.')
    events = {str(row.activity_id): row for row in activity}
    for row in lifecycle:
        key = str(row.event_id)
        predecessor = events.get(key)
        if predecessor is not None:
            # Lifecycle sales publish their same recognition through both query
            # families. Admit that exact overlap only, never two amounts.
            shared = {field.name for field in fields(predecessor)} & {field.name for field in fields(row)}
            if (row.activity_kind is not InvestmentActivityKind.SHARE_SALE
                    or predecessor.action_date != row.recognition_date
                    or predecessor.accounting_entry_id != row.recognition_accounting_entry_id
                    or any(getattr(predecessor, name) != getattr(row, name) for name in shared)):
                raise ValueError('Conflicting predecessor/lifecycle reporting facts.')
        events[key] = row
    return events


def _current_heads(events, corrections):
    edges, incoming = {}, set()
    for correction in corrections:
        if correction.target_kind is not InvestmentCorrectionTargetKind.ECONOMIC_EVENT:
            continue  # Cash corrections change settlement evidence, not income.
        original, replacement = str(correction.original_record_id), str(correction.replacement_record_id)
        before, after = events.get(original), events.get(replacement)
        if (before is None or after is None or original == replacement
                or original in edges or replacement in incoming
                or before.income_year != correction.income_year
                or after.income_year != correction.income_year
                or before.activity_kind != correction.original_activity_kind
                or after.activity_kind != correction.replacement_activity_kind
                or getattr(after, 'recognition_accounting_entry_id', getattr(after, 'accounting_entry_id', None))
                    != correction.replacement_accounting_entry_id):
            raise ValueError('Incomplete or conflicting economic correction lineage.')
        edges[original] = replacement
        incoming.add(replacement)
    finished = set()
    for start in edges:
        seen, current = set(), start
        while current in edges and current not in finished:
            if current in seen:
                raise ValueError('Cyclic economic correction lineage.')
            seen.add(current)
            current = edges[current]
        finished.update(seen)
    return tuple(events[key] for key in sorted(events) if key not in edges)


def _validate_settlement_corrections(lifecycle, corrections):
    latest = {}
    for event in lifecycle:
        if event.settlement_id is not None:
            key = str(event.settlement_id)
            if key in latest:
                raise ValueError('Settlement identity belongs to more than one event.')
            latest[key] = event
    edges, incoming = {}, set()
    for correction in corrections:
        if correction.target_kind is not InvestmentCorrectionTargetKind.CASH_SETTLEMENT:
            continue
        original, replacement = str(correction.original_record_id), str(correction.replacement_record_id)
        if original == replacement or original in edges or replacement in incoming or original in latest:
            raise ValueError('Conflicting settlement correction lineage.')
        edges[original] = correction
        incoming.add(replacement)
    resolved = {}
    for start in edges:
        path, current = {}, start
        while current in edges and current not in resolved:
            if current in path:
                raise ValueError('Cyclic settlement correction lineage.')
            correction = edges[current]
            path[current] = correction
            current = str(correction.replacement_record_id)
        event = resolved.get(current, latest.get(current))
        if event is None:
            raise ValueError('Settlement correction has no current event evidence.')
        for key, correction in path.items():
            if (event.income_year != correction.income_year
                    or event.activity_kind != correction.original_activity_kind
                    or event.activity_kind != correction.replacement_activity_kind
                    or (str(correction.replacement_record_id) == str(event.settlement_id)
                        and correction.replacement_accounting_entry_id != event.settlement_accounting_entry_id)):
                raise ValueError('Settlement correction is not bound to its current event.')
            resolved[key] = event


async def read_investment_reporting_snapshot(queries: InvestmentsQueries, *, actor_id: ActorId,
        company_id: CompanyId, income_year: IncomeYear,
        correlation_id: CorrelationId) -> InvestmentReportingSnapshot:
    """Read all pages under the application's existing company/snapshot guard.

    Query authorization still runs in the owning adapter. Malformed, foreign,
    duplicated, truncated, or ambiguous evidence fails closed as unavailable.
    """
    families = (
        ('activity', InvestmentActivityPage, InvestmentActivityView, 'activity_id'),
        ('lifecycle_events', InvestmentLifecycleEventPage, InvestmentLifecycleEventView, 'event_id'),
        ('corrections', InvestmentCorrectionPage, InvestmentCorrectionView, 'correction_id'),
        ('positions', InvestmentPositionPage, InvestmentPositionView, 'position_id'),
        ('year_end_measurements', InvestmentYearEndMeasurementPage, InvestmentYearEndMeasurementView, 'measurement_id'),
        ('acquisition_lots', AcquisitionLotPage, AcquisitionLotView, 'lot_id'),
        ('share_sale_allocations', ShareSaleAllocationPage, ShareSaleAllocationView, 'allocation_id'),
    )
    try:
        source = {}
        for name, page_type, row_type, identity in families:
            source[name] = await _all_pages(queries, 'list_' + name, page_type, row_type, identity,
                actor_id=actor_id, company_id=company_id, correlation_id=correlation_id)
        events = _economic_events(source['activity'], source['lifecycle_events'])
        _validate_settlement_corrections(source['lifecycle_events'], source['corrections'])
        heads = _current_heads(events, source['corrections'])
        positions = {str(row.position_id) for row in source['positions']}
        for family in ('activity', 'lifecycle_events', 'year_end_measurements',
                       'acquisition_lots', 'share_sale_allocations'):
            if any(str(row.position_id) not in positions for row in source[family]):
                raise ValueError('Reporting position evidence is incomplete.')
        canonical = _json({'version': 'investment-reporting-v1', 'company_id': company_id,
                           'income_year': income_year, **source})
        return InvestmentReportingSnapshot(company_id, income_year,
            tuple(row for row in heads if row.income_year == income_year),
            source['positions'],
            tuple(row for row in source['year_end_measurements'] if row.income_year == income_year),
            canonical)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise InvestmentsError.unavailable() from None
