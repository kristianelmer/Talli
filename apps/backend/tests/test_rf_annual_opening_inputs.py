"""Exact locked opening evidence stays independent of no-activity rendering."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from talli_backend.application.shareholder_register_annual_opening import annual_opening_inputs
from talli_backend.modules.shareholder_register_filing import public as rf
from test_rf1086_source_admission import AdmissionHarness, COMPANY, YEAR

QUERY = rf.Rf1086SourceQuery(COMPANY, YEAR, AdmissionHarness().actor)


def rows():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    opening = dict(id=uuid4(), company_id=str(COMPANY), income_year=int(YEAR),
                   share_capital=Decimal('30000.03'), share_count=3, nominal_value=Decimal('10000.01'),
                   locked_at=now, created_by=uuid4(), created_at=now)
    holders = [dict(id=uuid4(), setup_id=opening['id'], company_id=str(COMPANY), name='Synthetic Holding AS',
                    shareholder_kind='norwegian_company', national_id=None, org_number='930835978',
                    share_count=count, created_by=opening['created_by'], created_at=now) for count in (1, 2)]
    return [opening], holders


def test_exact_source_extent_is_immutable_order_independent_and_complete():
    opening, holders = rows()
    result = annual_opening_inputs(opening, holders, QUERY)
    assert result.company_id == COMPANY and result.income_year == YEAR
    assert result == annual_opening_inputs(opening, list(reversed(holders)), QUERY)
    source, = result.opening_sources
    assert source.opening_snapshot_id == rf.OpeningSnapshotId(str(opening[0]['id'])) and source.shareholder_count == 2
    with pytest.raises(AttributeError): result.opening_sources = ()
    for target, field, value in [('opening', 'locked_at', opening[0]['locked_at'] + timedelta(microseconds=1)),
                                  ('opening', 'created_by', uuid4()), ('holder', 'name', 'Renamed AS'),
                                  ('holder', 'org_number', '998877665')]:
        other_opening, other_holders = deepcopy((opening, holders))
        (other_opening[0] if target == 'opening' else other_holders[0])[field] = value
        assert annual_opening_inputs(other_opening, other_holders, QUERY) != result


def test_complete_empty_is_scope_bound():
    result = annual_opening_inputs([], [], QUERY)
    assert result.company_id == COMPANY and result.income_year == YEAR and result.opening_sources == ()


@pytest.mark.parametrize('corruption', ['multiple', 'orphan', 'wrong-company', 'wrong-year', 'bool-year',
    'unlocked', 'naive-time', 'invalid-actor', 'float-capital', 'nonfinite', 'capital-total',
    'empty-holders', 'duplicate', 'foreign-holder', 'wrong-parent', 'bad-kind', 'bad-identity',
    'bool-shares', 'holder-total', 'unavailable'])
def test_inconsistent_opening_or_incomplete_holder_extent_is_unavailable(corruption):
    opening, holders = rows()
    if corruption == 'multiple': opening.append(dict(opening[0]))
    elif corruption == 'orphan': opening.clear()
    elif corruption == 'wrong-company': opening[0]['company_id'] = uuid4()
    elif corruption == 'wrong-year': opening[0]['income_year'] -= 1
    elif corruption == 'bool-year': opening[0]['income_year'] = True
    elif corruption == 'unlocked': opening[0]['locked_at'] = None
    elif corruption == 'naive-time': opening[0]['created_at'] = datetime(2026, 1, 1)
    elif corruption == 'invalid-actor': opening[0]['created_by'] = 'bad'
    elif corruption == 'float-capital': opening[0]['share_capital'] = 30000.03
    elif corruption == 'nonfinite': opening[0]['share_capital'] = Decimal('NaN')
    elif corruption == 'capital-total': opening[0]['share_capital'] += Decimal('.01')
    elif corruption == 'empty-holders': holders.clear()
    elif corruption == 'duplicate': holders.append(dict(holders[0]))
    elif corruption == 'foreign-holder': holders[0]['company_id'] = uuid4()
    elif corruption == 'wrong-parent': holders[0]['setup_id'] = uuid4()
    elif corruption == 'bad-kind': holders[0]['shareholder_kind'] = 'unsupported'
    elif corruption == 'bad-identity': holders[0]['org_number'] = 'bad'
    elif corruption == 'bool-shares': holders[0]['share_count'] = True
    elif corruption == 'holder-total': holders[0]['share_count'] += 1
    elif corruption == 'unavailable': opening = None
    with pytest.raises(rf.ShareholderRegisterFilingError):
        annual_opening_inputs(opening, holders, QUERY)
