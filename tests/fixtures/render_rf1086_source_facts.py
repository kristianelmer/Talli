"""Local cross-output test adapter; no network, persistence or legacy engine."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import json
import sys

from talli_backend.modules.shareholder_register_filing.public import (
    OpeningSnapshotId,
    Rf1086CompanyFacts,
    Rf1086OpeningFacts,
    Rf1086OpeningShareholderFact,
    Rf1086ShareholderKind,
    build_no_activity_rf1086_case,
    render_no_activity_rf1086_preview,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear


def wire(value):
    if is_dataclass(value):
        return {field.name: wire(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: wire(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [wire(item) for item in value]
    return value


def main():
    data = json.load(sys.stdin)
    company = data["company"]
    opening = data["opening"]
    case = build_no_activity_rf1086_case(
        company=Rf1086CompanyFacts(
            CompanyId(company["id"]), company["org_number"], company["name"],
            company["address"], company["postal_code"], company["city"],
        ),
        opening=Rf1086OpeningFacts(
            CompanyId(opening["company_id"]), OpeningSnapshotId(opening["id"]),
            IncomeYear(opening["income_year"]), opening["share_capital"],
            opening["share_count"], opening["nominal_value"],
            tuple(Rf1086OpeningShareholderFact(
                item["id"], Rf1086ShareholderKind(item["shareholder_kind"]),
                item["name"], item["national_id"], item["org_number"], item["share_count"],
            ) for item in data["shareholders"]),
        ),
    )
    print(json.dumps(wire(render_no_activity_rf1086_preview(case)), ensure_ascii=False))


if __name__ == "__main__":
    main()
