from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from holding_core.annual import AnnualData, simulate_annual_accounts, simulate_tax_return


class ExpectedAnnualTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bank_balance: float | None = None
    investment_balance: float | None = None
    dividend_income: float | None = None
    admin_costs: float | None = None
    fritaksmetoden_add_back: float | None = None
    result_before_tax: float | None = None


class AnnualValidationFixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    annual_data: AnnualData
    expected_totals: ExpectedAnnualTotals = ExpectedAnnualTotals()
    unsupported_reason: str | None = None


class AnnualValidationCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_path: str
    case_id: str | None
    outcome: str
    filings: list[str]
    assumptions: list[str]
    issues: list[str]
    mismatches: list[str]
    generated_previews: int


class AnnualValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filing: str
    source: str
    authority_maps: list[str]
    limitations: list[str]
    cases: list[AnnualValidationCaseResult]


PUBLIC_DATA_LIMITATIONS = [
    "Public and synthetic data cannot prove voucher completeness.",
    "Public and synthetic data cannot prove exact bank transaction classification.",
    "Public and synthetic data cannot prove parity with Fiken or accountant-submitted payloads.",
]


def run_annual_compliance_validation(
    case_paths: list[str | Path],
    *,
    source: str = "public/synthetic",
) -> AnnualValidationReport:
    results = [_run_annual_case(Path(path)) for path in case_paths]
    return AnnualValidationReport(
        filing="årsregnskap + skattemelding for AS",
        source=source,
        authority_maps=[
            "docs/filing/annual-accounts-authority-map.md",
            "docs/filing/company-tax-return-authority-map.md",
        ],
        limitations=PUBLIC_DATA_LIMITATIONS
        + [
            "Annual accounts validation is mapped to public RR-0002 requirements, not production Altinn submission.",
            "Company tax return validation is mapped to public Skatteetaten sources, not production submission payload parity.",
        ],
        cases=results,
    )


def _run_annual_case(path: Path) -> AnnualValidationCaseResult:
    assumptions = [
        "Small Norwegian holding AS launch subset",
        "No production authority submission",
        "Authority maps define production blockers separately",
    ]
    try:
        fixture = AnnualValidationFixture.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError) as error:
        return AnnualValidationCaseResult(
            case_path=str(path),
            case_id=None,
            outcome="blocked",
            filings=[],
            assumptions=assumptions,
            issues=[f"Annual validation fixture failed: {error}"],
            mismatches=[],
            generated_previews=0,
        )

    if fixture.unsupported_reason:
        return AnnualValidationCaseResult(
            case_path=str(path),
            case_id=fixture.case_id,
            outcome="unsupported",
            filings=[],
            assumptions=assumptions,
            issues=[fixture.unsupported_reason],
            mismatches=[],
            generated_previews=0,
        )

    annual = simulate_annual_accounts(fixture.annual_data)
    tax = simulate_tax_return(fixture.annual_data)
    readiness_issues = [
        issue.message
        for simulation in (annual, tax)
        for issue in simulation.readiness.issues
    ]
    mismatches = _annual_mismatches(fixture.annual_data, fixture.expected_totals)
    if any(not simulation.readiness.is_ready for simulation in (annual, tax)):
        outcome = "blocked"
    elif mismatches:
        outcome = "mismatch"
    elif readiness_issues:
        outcome = "warning"
    else:
        outcome = "pass"
    return AnnualValidationCaseResult(
        case_path=str(path),
        case_id=fixture.case_id,
        outcome=outcome,
        filings=[annual.filing, tax.filing],
        assumptions=assumptions,
        issues=readiness_issues,
        mismatches=mismatches,
        generated_previews=len([simulation for simulation in (annual, tax) if simulation.preview]),
    )


def _annual_mismatches(data: AnnualData, expected: ExpectedAnnualTotals) -> list[str]:
    actual = {
        "bank_balance": data.bank_balance,
        "investment_balance": data.investment_balance,
        "dividend_income": data.dividend_income,
        "admin_costs": data.admin_costs,
        "fritaksmetoden_add_back": data.fritaksmetoden_add_back,
        "result_before_tax": data.result_before_tax,
    }
    mismatches = []
    for key, expected_value in expected.model_dump().items():
        if expected_value is None:
            continue
        if round(actual[key], 2) != round(expected_value, 2):
            mismatches.append(f"{key}: expected {expected_value}, got {actual[key]}")
    return mismatches
