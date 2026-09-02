"""Frozen read models for the future annual-compliance compatibility store.

Corporate governance consumes these source facts without importing future
annual-accounts filing policy or treating the legacy table as its own store.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

from talli_backend.modules.corporate_governance.public import (
    AnnualDataSourceFacts,
    ApprovedAnnualBasis,
    CorporateAccountMovementFacts,
    CorporateGovernanceError,
    CorporateGovernanceErrorCode,
)
from talli_backend.shared.kernel import CompanyId, IncomeYear


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class LegacyAnnualDataView:
    source_id: str
    company_id: CompanyId
    income_year: IncomeYear
    answers: Mapping[str, object]
    confirmations: tuple[str, ...]
    no_activity_confirmed: bool
    annual_full_time_equivalents: int | float
    completed_at: str
    updated_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "answers", _freeze(self.answers))


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "value") and value.__class__.__module__.startswith("talli_backend"):
        inner = value.value
        if hasattr(inner, "isoformat"):
            return inner.isoformat()
        return inner
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _ore_number(value: int) -> int | float:
    return value // 100 if value % 100 == 0 else value / 100


def _ledger_account_balance_ore(
    lines: tuple[CorporateAccountMovementFacts, ...],
    account: str,
    income_year: IncomeYear,
) -> int:
    return sum(
        line.debit_ore - line.credit_ore
        for line in lines
        if line.income_year == income_year and line.account == account
    )


def _legacy_annual_accounts_payload(
    source: AnnualDataSourceFacts,
    lines: tuple[CorporateAccountMovementFacts, ...],
) -> dict[str, Any]:
    """Reproduce the frozen pre-#153 annual-accounts projection exactly."""

    account_balance = lambda account: _ledger_account_balance_ore(
        lines, account, source.income_year
    )
    account_credit = lambda account: -account_balance(account)
    debit_total = lambda accounts: sum(
        line.debit_ore
        for line in lines
        if line.income_year == source.income_year and line.account in accounts
    )
    tax_payable = account_credit("2500")
    investment_balance = sum(
        account_balance(account)
        for account in ("1300", "1310", "1350", "1800", "1810", "1815")
    )
    bank_balance = account_balance("1920")
    admin_costs = debit_total(
        {"7770", "6700", "6705", "6420", "7790", "6720", "7795"}
    )
    financial_income = sum(
        account_credit(account) for account in ("8070", "8071", "8074", "8050")
    )
    financial_costs = debit_total({"8090", "8171", "8174"})
    tax_expense = account_balance("8300")
    share_capital = account_credit("2000")
    retained_earnings = account_credit("2050")
    short_term_debt = account_credit("2255") + tax_payable
    result_before_tax = financial_income - admin_costs - financial_costs
    annual_result = result_before_tax - tax_expense
    retained = retained_earnings + annual_result
    sum_equity = share_capital + retained
    sum_assets = investment_balance + bank_balance
    fte = source.annual_full_time_equivalents

    feedback: list[dict[str, str]] = []
    if fte < 0:
        feedback.append(
            {
                "level": "block",
                "code": "annual_accounts_aarsverk_negative",
                "message": "Årsverk kan ikke være negativt.",
                "source": "annual_accounts_payload",
            }
        )
    feedback_rules = (
        (
            "annual_accounts_audit_required",
            "Revisjonsplikt er utenfor enkel holding-AS-løype.",
        ),
        (
            "annual_accounts_not_small_enterprise",
            "Ikke-små foretak krever utvidet årsregnskapsmodell.",
        ),
        (
            "annual_accounts_annual_report_required",
            "Årsberetning er ikke støttet i første årsregnskapsløype.",
        ),
    )
    for code, message in feedback_rules:
        if code in source.confirmations:
            feedback.append(
                {
                    "level": "block",
                    "code": code,
                    "message": message,
                    "source": "annual_accounts_payload",
                }
            )

    def field(
        tag: str,
        orid: str,
        value: str | int | float,
        fact_source: str,
    ) -> dict[str, str | int | float]:
        return {"tag": tag, "orid": orid, "value": value, "source": fact_source}

    year = int(source.income_year)
    return {
        "schemaType": "aarsregnskap-vanlig-202406",
        "hovedskjemaDataFormatId": "1266",
        "hovedskjemaDataFormatVersion": "51820",
        "selskapsregnskapDataFormatId": "758",
        "selskapsregnskapDataFormatVersion": "51980",
        "notes": {"annualFullTimeEquivalents": fte},
        "fields": [
            field("regnskapsaar", "17102", year, "company.income_year"),
            field("regnskapsstart", "17103", f"{year}-01-01", "calendar_year"),
            field("regnskapsslutt", "17104", f"{year}-12-31", "calendar_year"),
            field("valuta", "34984", "NOK", "launch_currency"),
            field("sumDriftskostnad/aarets", "17126", _ore_number(admin_costs), "ledger.expense_accounts"),
            field("sumFinansinntekter/aarets", "153", _ore_number(financial_income), "ledger.8070_8050"),
            field("sumFinanskostnader/aarets", "17130", _ore_number(financial_costs), "ledger.8090"),
            field("resultatFoerSkattekostnad/aarets", "167", _ore_number(result_before_tax), "derived"),
            field("skattekostnad/aarets", "11835", _ore_number(tax_expense), "ledger.8300"),
            field("aarsresultat/aarets", "172", _ore_number(annual_result), "derived"),
            field(
                "investeringAksjerAndeler/aarets",
                "7100",
                _ore_number(investment_balance),
                "ledger.1300_1310_1350_1800_1810_1815",
            ),
            field("sumFinansielleAnleggsmidler/aarets", "5267", _ore_number(investment_balance), "derived"),
            field("sumBankinnskuddKontanter/aarets", "29042", _ore_number(bank_balance), "ledger.1920"),
            field("sumEiendeler/aarets", "219", _ore_number(sum_assets), "derived"),
            field("sumInnskuttEgenkapital/aarets", "3730", _ore_number(share_capital), "ledger.2000"),
            field("annenEgenkapital/aarets", "3274", _ore_number(retained), "ledger.2050_and_result"),
            field("sumEgenkapital/aarets", "250", _ore_number(sum_equity), "derived"),
            field("betalbarSkatt/aarets", "2483", _ore_number(tax_payable), "ledger.2500"),
            field("sumKortsiktigGjeld/aarets", "85", _ore_number(short_term_debt), "ledger.2255_2500"),
            field("sumGjeld/aarets", "1119", _ore_number(short_term_debt), "derived"),
            field("antallAarsverk", "37467", fte, "annual_accounts.notes"),
        ],
        "feedback": feedback,
    }


def project_legacy_annual_basis(
    source: AnnualDataSourceFacts,
    ledger_lines: tuple[CorporateAccountMovementFacts, ...],
) -> ApprovedAnnualBasis:
    """Return the immutable basis used until annual-accounts ownership moves in #153."""

    payload = _legacy_annual_accounts_payload(source, ledger_lines)
    hard_block = next(
        (
            item
            for item in payload["feedback"]
            if isinstance(item, Mapping) and item.get("level") == "block"
        ),
        None,
    )
    if isinstance(hard_block, Mapping):
        raise CorporateGovernanceError.invalid(
            CorporateGovernanceErrorCode.INVALID_INPUT,
            str(hard_block.get("message") or "Annual accounts are blocked."),
        )

    def field_ore(tag: str) -> int:
        fields = payload["fields"]
        item = next(
            (
                value
                for value in fields
                if isinstance(value, Mapping) and value.get("tag") == tag
            ),
            None,
        )
        if not isinstance(item, Mapping):
            raise CorporateGovernanceError.invalid(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                f"Annual accounts are missing {tag}.",
            )
        value = item.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CorporateGovernanceError.invalid(
                CorporateGovernanceErrorCode.INVALID_INPUT,
                f"Annual accounts are missing {tag}.",
            )
        return round(value * 100)

    equity_ore = field_ore("sumEgenkapital/aarets")
    cash_ore = field_ore("sumBankinnskuddKontanter/aarets")
    if equity_ore < 0 or cash_ore < 0:
        raise CorporateGovernanceError.invalid(
            CorporateGovernanceErrorCode.UNSUPPORTED_DIVIDEND_BASIS,
            "Negative equity or liquidity is outside the supported path.",
        )
    annual_snapshot = {
        "id": str(source.source_id),
        "company_id": str(source.company_id),
        "income_year": int(source.income_year),
        "answers": source.answers,
        "confirmations": list(source.confirmations),
        "no_activity_confirmed": source.no_activity_confirmed,
        "annual_full_time_equivalents": source.annual_full_time_equivalents,
        "completed_at": source.completed_at,
        "updated_at": source.updated_at,
    }
    return ApprovedAnnualBasis(
        source_id=source.source_id,
        income_year=source.income_year,
        latest_approved=True,
        annual_data_sha256=_sha256(annual_snapshot),
        annual_accounts_payload_sha256=_sha256(payload),
        result_after_tax_ore=field_ore("aarsresultat/aarets"),
        equity_ore=equity_ore,
        available_distribution_ore=max(0, field_ore("annenEgenkapital/aarets")),
        cash_ore=cash_ore,
    )


__all__ = ["LegacyAnnualDataView", "project_legacy_annual_basis"]
