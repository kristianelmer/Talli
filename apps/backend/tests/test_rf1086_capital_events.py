"""Public-source-backed cash capital and no-payout loss cover semantics."""
from dataclasses import replace
from pathlib import Path
import json
import subprocess
from xml.etree import ElementTree as ET

import pytest

from talli_backend.modules.shareholder_register_filing.public import (
    parse_rf1086_case, generate_rf1086_documents, assess_rf1086_readiness,
)

ROOT = Path(__file__).resolve().parents[3]


def capital_case(kind):
    raw = json.loads((ROOT / "tests/fixtures/rf1086/no_activity.json").read_text())
    # Existing synthetic fixture identifiers are used only in local tests.
    event = {"type": kind, "timestamp": "2025-03-01T12:00:00", "registration_confirmed": True}
    shares = raw["share_snapshot"]
    if kind == "cash_issue":
        event.update(issued_share_count=50, share_count_after=150, nominal_value=300, premium=20,
                     allocations=[{"shareholder_id": "owner", "share_count": 50, "acquisition_value": 16000}])
        shares.update(current_share_count=150, current_share_capital=45000, current_paid_in_share_capital=45000, current_paid_in_premium=1000)
        raw["shareholder_snapshots"][0]["current_share_count"] = 150
    elif kind == "cash_nominal_increase":
        event.update(capital_increase=10000, nominal_value_increase=100, nominal_value_after=400, premium=500,
                     allocations=[{"shareholder_id": "owner", "share_count_basis": 100, "capital_increase": 10000, "premium": 500}])
        shares.update(current_share_capital=40000, current_nominal_value=400, current_paid_in_share_capital=40000, current_paid_in_premium=500)
    else:
        event.update(capital_reduction=10000, nominal_value_reduction=100, nominal_value_after=200, fund_issued_capital_before=0)
        shares.update(current_share_capital=20000, current_nominal_value=200)
    raw["events"] = [event]
    return raw


def fields(xml):
    return {element.get("orid"): element.text for element in ET.fromstring(xml).iter() if element.get("orid")}


@pytest.mark.parametrize("kind", ["cash_issue", "cash_nominal_increase", "loss_covering_reduction"])
def test_capital_documents_pass_current_official_xsd(kind, tmp_path):
    case = parse_rf1086_case(capital_case(kind))
    assert assess_rf1086_readiness(case).is_ready
    result = generate_rf1086_documents(case)
    for name, xml, schema in [
        ("main", result.hovedskjema_xml, "Hovedskjema"),
        ("owner", result.underskjema_xml["owner"], "Underskjema"),
    ]:
        path = tmp_path / f"{name}.xml"
        path.write_text(xml)
        checked = subprocess.run(["xmllint", "--noout", "--schema", str(ROOT / f"docs/filing/aksjonaerregisteroppgave{schema}.xsd"), str(path)], capture_output=True, text=True)
        assert checked.returncode == 0, checked.stderr


def test_cash_issue_uses_n_and_per_share_premium_with_total_acquisition_value():
    result = generate_rf1086_documents(parse_rf1086_case(capital_case("cash_issue")))
    main, owner = fields(result.hovedskjema_xml), fields(result.underskjema_xml["owner"])
    assert (main["17670"], owner["17745"]) == ("N", "N")
    assert (main["23948"], main["17661"], owner["17636"]) == ("20", "1000", "16000")
    assert main["17671"] == owner["17746"]


def test_nominal_cash_increase_uses_posts_15_and_29():
    result = generate_rf1086_documents(parse_rf1086_case(capital_case("cash_nominal_increase")))
    main, owner = fields(result.hovedskjema_xml), fields(result.underskjema_xml["owner"])
    assert (main["28268"], owner["28267"]) == ("6", "6")
    assert main["17713"] == owner["22073"] == "10000"
    assert main["22071"] == owner["22076"] == "500"
    assert main["23958"] == owner["23971"] == "100"
    assert main["17716"] == owner["22075"]
    assert "17670" not in main and "17745" not in owner


def test_loss_cover_preserves_tax_paid_in_capital_without_shareholder_payout():
    result = generate_rf1086_documents(parse_rf1086_case(capital_case("loss_covering_reduction")))
    main, owner = fields(result.hovedskjema_xml), fields(result.underskjema_xml["owner"])
    assert main["17717"] == "10000" and main["23961"] == "200"
    assert main["87"] == "20000" and main["5867"] == "30000"
    assert "17722" not in main and "17761" not in owner and "22073" not in owner
    assert owner["17741"] == owner["29168"] == "100"


@pytest.mark.parametrize("kind,path,value", [
    ("cash_issue", ("events", 0, "premium"), 19),
    ("cash_issue", ("events", 0, "share_count_after"), 151),
    ("cash_issue", ("events", 0, "registration_confirmed"), False),
    ("cash_issue", ("events", 0, "timestamp"), "2024-03-01T12:00:00"),
    ("cash_issue", ("shareholder_snapshots", 0, "current_share_count"), 149),
    ("cash_nominal_increase", ("events", 0, "allocations", 0, "share_count_basis"), 99),
    ("cash_nominal_increase", ("events", 0, "allocations", 0, "premium"), 400),
    ("cash_nominal_increase", ("events", 0, "nominal_value_after"), 401),
    ("loss_covering_reduction", ("share_snapshot", "current_paid_in_share_capital"), 20000),
    ("loss_covering_reduction", ("events", 0, "fund_issued_capital_before"), 1000),
    ("loss_covering_reduction", ("events", 0, "capital_reduction"), 9999),
])
def test_inconsistent_capital_case_is_rejected(kind, path, value):
    raw = capital_case(kind)
    node = raw
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(ValueError):
        parse_rf1086_case(raw)


def test_direct_public_value_cannot_bypass_capital_reconciliation():
    case = parse_rf1086_case(capital_case("loss_covering_reduction"))
    invalid = replace(case, share_snapshot=replace(case.share_snapshot, current_paid_in_share_capital=20000))
    assert not assess_rf1086_readiness(invalid).is_ready
    with pytest.raises(ValueError, match="tax paid-in"):
        generate_rf1086_documents(invalid)


def test_multiple_registered_capital_changes_reconcile_in_event_time():
    raw = capital_case("cash_issue")
    nominal = capital_case("cash_nominal_increase")["events"][0]
    nominal.update(timestamp="2025-04-01T12:00:00", capital_increase=15000)
    nominal["allocations"][0].update(share_count_basis=150, capital_increase=15000)
    reduction = capital_case("loss_covering_reduction")["events"][0]
    reduction.update(timestamp="2025-05-01T12:00:00", capital_reduction=15000, nominal_value_after=300)
    raw["events"] += [nominal, reduction]
    raw["share_snapshot"].update(current_share_capital=45000, current_nominal_value=300, current_paid_in_share_capital=60000, current_paid_in_premium=1500)
    case = parse_rf1086_case(raw)
    assert assess_rf1086_readiness(case).is_ready
    assert fields(generate_rf1086_documents(case).hovedskjema_xml)["5867"] == "60000"
    raw["events"].reverse()
    with pytest.raises(ValueError):
        parse_rf1086_case(raw)


@pytest.mark.parametrize("fixture,mutate", [
    ("no_activity", lambda raw: raw["share_snapshot"].update(current_share_capital=40000)),
    ("no_activity", lambda raw: (raw["share_snapshot"].update(current_share_count=101), raw["shareholder_snapshots"][0].update(current_share_count=101))),
    ("share_sale", lambda raw: raw["events"][0].update(share_count=101)),
    ("dividend", lambda raw: raw["events"][0]["allocations"][0].update(share_count_basis=69)),
    ("stiftelse", lambda raw: raw["events"][0]["allocations"][0].update(acquisition_value=1)),
])
def test_existing_event_variants_require_complete_reconciliation(fixture, mutate):
    raw = json.loads((ROOT / f"tests/fixtures/rf1086/{fixture}.json").read_text())
    mutate(raw)
    with pytest.raises(ValueError):
        parse_rf1086_case(raw)


def test_no_activity_does_not_emit_xml_for_unexplained_capital_change():
    from talli_backend.modules.shareholder_register_filing.public import render_no_activity_rf1086_preview
    raw = json.loads((ROOT / "tests/fixtures/rf1086/no_activity.json").read_text())
    case = parse_rf1086_case(raw)
    invalid = replace(case, share_snapshot=replace(case.share_snapshot, current_share_capital=40000))
    result = render_no_activity_rf1086_preview(invalid)
    assert result.status == "blocked" and result.hovedskjema_xml is None


def test_malformed_public_values_are_blocked_without_rendering():
    from talli_backend.modules.shareholder_register_filing.public import render_rf1086_preview
    case = parse_rf1086_case(capital_case("cash_issue"))
    invalid = replace(case, events=(replace(case.events[0], timestamp=None),))
    result = render_rf1086_preview(invalid)
    assert result.status == "blocked" and result.hovedskjema_xml is None
