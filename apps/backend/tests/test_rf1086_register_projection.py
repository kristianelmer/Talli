"""Event-time register evidence uses the complete canonical filing replay."""
from dataclasses import replace
from decimal import Decimal
import json

import pytest

from talli_backend.modules.shareholder_register_filing.public import (
    parse_rf1086_case, rf1086_event_register_states, Rf1086RegisterObservationError,
)
from test_rf1086_capital_events import capital_case, ROOT


@pytest.mark.parametrize('kind,before,after', [
    ('cash_issue', (30000,100,300), (45000,150,300)),
    ('cash_nominal_increase', (30000,100,300), (40000,100,400)),
    ('loss_covering_reduction', (40000,100,400), (30000,100,300)),
])
def test_each_registered_variant_projects_exact_states(kind,before,after):
    states=rf1086_event_register_states(parse_rf1086_case(capital_case(kind)),0)
    for observed,expected in zip(states,(before,after)):
        assert (observed.share_capital,observed.share_count,observed.nominal_value)==expected
        assert type(observed.share_capital) is Decimal and type(observed.nominal_value) is Decimal
        assert sum(h.share_count for h in observed.holdings)==observed.share_count
        assert observed.holdings[0].identifier and observed.holdings[0].name


def formation_transfer_issue_case():
    raw=json.loads((ROOT/'tests/fixtures/rf1086/stiftelse.json').read_text())
    raw['shareholders'].append({'id':'buyer','kind':'norwegian_company','name':'Synthetic Buyer AS','org_number':'123456789'})
    raw['shareholder_snapshots'][0]['current_share_count']=60
    raw['shareholder_snapshots'].append({'shareholder_id':'buyer','previous_share_count':0,'current_share_count':90})
    raw['events'].append({'type':'share_sale','timestamp':'2025-02-01T12:00:00','seller_shareholder_id':'founder',
        'buyer_shareholder_id':'buyer','share_count':40,'consideration':12000})
    issue=capital_case('cash_issue')['events'][0]
    issue['allocations'][0]['shareholder_id']='buyer'
    raw['events'].append(issue)
    raw['share_snapshot'].update(current_share_capital=45000,current_share_count=150,
        current_paid_in_share_capital=45000,current_paid_in_premium=1000)
    return parse_rf1086_case(raw)


def test_prior_formation_and_transfer_determine_event_time_holdings():
    before,after=rf1086_event_register_states(formation_transfer_issue_case(),2)
    assert [(h.shareholder_id,h.share_count) for h in before.holdings]==[('buyer',40),('founder',60)]
    assert [(h.shareholder_id,h.share_count) for h in after.holdings]==[('buyer',90),('founder',60)]
    assert before.share_count==100 and after.share_count==150


@pytest.mark.parametrize('index',[-1,0,1,3,True,'2',None])
def test_projection_requires_existing_capital_index(index):
    with pytest.raises(Rf1086RegisterObservationError):
        rf1086_event_register_states(formation_transfer_issue_case(),index)


@pytest.mark.parametrize('change',['closing','future','identity','share_class','holdings'])
def test_cannot_project_apparently_valid_transition_from_invalid_full_case(change):
    case=formation_transfer_issue_case()
    if change=='closing':case=replace(case,share_snapshot=replace(case.share_snapshot,current_paid_in_premium=999))
    if change=='future':case=replace(case,events=case.events+(replace(case.events[-1],timestamp=case.events[-1].timestamp.replace(month=4)),))
    if change=='identity':case=replace(case,shareholders=(replace(case.shareholders[0],national_id=None),case.shareholders[1]))
    if change=='share_class':case=replace(case,company=replace(case.company,share_type='02'))
    if change=='holdings':case=replace(case,shareholder_snapshots=(replace(case.shareholder_snapshots[0],current_share_count=59),case.shareholder_snapshots[1]))
    with pytest.raises(Rf1086RegisterObservationError):rf1086_event_register_states(case,2)


def test_successive_nominal_and_loss_events_use_preceding_capital_state():
    raw=capital_case('cash_issue')
    nominal=capital_case('cash_nominal_increase')['events'][0]
    nominal.update(timestamp='2025-04-01T12:00:00',capital_increase=15000)
    nominal['allocations'][0].update(share_count_basis=150,capital_increase=15000)
    loss=capital_case('loss_covering_reduction')['events'][0]
    loss.update(timestamp='2025-05-01T12:00:00',capital_reduction=15000)
    raw['events'] += [nominal,loss]
    raw['share_snapshot'].update(current_paid_in_share_capital=60000,current_paid_in_premium=1500)
    case=parse_rf1086_case(raw)
    before,after=rf1086_event_register_states(case,2)
    assert (before.share_capital,after.share_capital)==(60000,45000)
    assert (before.nominal_value,after.nominal_value)==(400,300)
    assert before.holdings==after.holdings and before.share_count==150


@pytest.mark.parametrize('invalid_kind',[False,True])
def test_later_holder_identity_is_validated_before_projecting_earlier_event(invalid_kind):
    case=formation_transfer_issue_case()
    new_holder=replace(case.shareholders[1],id='later',name='Later buyer',org_number='234567890')
    later_sale=replace(case.events[1],timestamp=case.events[1].timestamp.replace(month=4),
        seller_shareholder_id='buyer',buyer_shareholder_id='later',share_count=10,consideration=3000)
    snapshots=(case.shareholder_snapshots[0],replace(case.shareholder_snapshots[1],current_share_count=80),
        replace(case.shareholder_snapshots[1],shareholder_id='later',current_share_count=10))
    extended=replace(case,shareholders=case.shareholders+(new_holder,),shareholder_snapshots=snapshots,
        events=case.events+(later_sale,))
    assert len(rf1086_event_register_states(extended,2))==2
    invalid=replace(new_holder,kind='foreign_company') if invalid_kind else replace(new_holder,org_number=None)
    with pytest.raises(Rf1086RegisterObservationError):
        rf1086_event_register_states(replace(extended,shareholders=case.shareholders+(invalid,)),2)


def test_replay_is_independent_of_ambient_decimal_precision_and_traps():
    from decimal import localcontext, Inexact, Rounded, ROUND_DOWN
    case=parse_rf1086_case(capital_case('cash_issue'))
    expected=rf1086_event_register_states(case,0)
    with localcontext() as context:
        context.prec=6
        context.rounding=ROUND_DOWN
        context.traps[Inexact]=True
        context.traps[Rounded]=True
        assert rf1086_event_register_states(case,0)==expected
        assert context.prec==6 and context.traps[Rounded] is True
