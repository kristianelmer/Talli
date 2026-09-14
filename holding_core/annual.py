from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from holding_core.ledger import PostedEntry
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsOfflineSource, assess_annual_accounts_offline,
    build_annual_accounts_offline_payload, simulate_annual_accounts_offline,
)


class DocumentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    document_type: str
    name: str
    status: str
    storage_uri: str | None = None


class YearEndInterviewAnswers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shares_owned_at_year_end: bool
    bought_or_sold_shares: bool
    received_dividends: bool
    declared_owner_dividends: bool
    shareholder_loans: bool
    paid_costs: bool
    bank_balance_confirmed: bool
    has_unpaid_items: bool
    general_meeting_approved: bool
    authority_to_submit_confirmed: bool


class AnnualReadinessIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str
    code: str
    message: str


class AnnualReadinessResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filing: str
    status: str
    issues: list[AnnualReadinessIssue]

    @property
    def is_ready(self) -> bool:
        return self.status == "ready"


class AnnualData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: str
    income_year: int
    interview: YearEndInterviewAnswers
    posted_entries: tuple[PostedEntry, ...]
    documents: tuple[DocumentRecord, ...] = ()
    confirmations: tuple[str, ...] = ()
    annual_full_time_equivalents: float | None = 0
    audit_required: bool = False
    small_enterprise: bool = True
    annual_report_required: bool = False
    cash_flow_statement_required: bool = False
    sustainability_reporting_required: bool = False
    fiscal_year_is_calendar_year: bool = True
    prior_year_figures_confirmed: bool = True

    def account_balance(self, account: str) -> float:
        debit = sum(line.debit for entry in self.posted_entries for line in entry.lines if line.account == account)
        credit = sum(line.credit for entry in self.posted_entries for line in entry.lines if line.account == account)
        return round(debit - credit, 2)

    def account_credit_balance(self, account: str) -> float:
        return round(-self.account_balance(account), 2)

    @property
    def bank_balance(self) -> float:
        return self.account_balance("1920")

    @property
    def investment_balance(self) -> float:
        return self.account_balance("1800")

    @property
    def admin_costs(self) -> float:
        cost_accounts = {"7770", "6700", "6705", "6420", "7790", "6720", "7795"}
        return round(
            sum(line.debit for entry in self.posted_entries for line in entry.lines if line.account in cost_accounts),
            2,
        )

    @property
    def dividend_income(self) -> float:
        return self.account_credit_balance("8070")

    @property
    def interest_income(self) -> float:
        return self.account_credit_balance("8050")

    @property
    def financial_income(self) -> float:
        return round(self.dividend_income + self.interest_income, 2)

    @property
    def financial_costs(self) -> float:
        return round(
            sum(line.debit for entry in self.posted_entries for line in entry.lines if line.account == "8090"),
            2,
        )

    @property
    def shareholder_loan_payable(self) -> float:
        return self.account_credit_balance("2255")

    @property
    def shareholder_loan_receivable(self) -> float:
        return self.account_balance("1370")

    @property
    def share_capital(self) -> float:
        return self.account_credit_balance("2000")

    @property
    def retained_earnings(self) -> float:
        return self.account_credit_balance("2050")

    @property
    def result_before_tax(self) -> float:
        return round(self.financial_income - self.admin_costs - self.financial_costs, 2)

    @property
    def fritaksmetoden_add_back(self) -> float:
        total = 0.0
        for entry in self.posted_entries:
            marker = "taxable_add_back:"
            if marker in entry.source:
                raw = entry.source.split(marker, 1)[1].split(":", 1)[0]
                total += float(raw)
        return round(total, 2)


class FilingSimulation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filing: str
    preview: str
    readiness: AnnualReadinessResult
    simulated_receipt_id: str | None = None
    payload: dict | None = None


class Rr0002Field(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag: str
    orid: str
    value: str | float | int
    source: str


class AnnualAccountsNotePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    annual_full_time_equivalents: float
    confirmations: tuple[str, ...]


class AnnualAccountsAttachmentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool
    code: str
    message: str


class AnnualAccountsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_type: str
    hovedskjema_data_format_id: str
    hovedskjema_data_format_version: str
    selskapsregnskap_data_format_id: str
    selskapsregnskap_data_format_version: str
    fields: tuple[Rr0002Field, ...]
    notes: AnnualAccountsNotePayload
    attachment_decisions: tuple[AnnualAccountsAttachmentDecision, ...]
    feedback_items: tuple[AnnualReadinessIssue, ...]


class CompanyArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: str
    income_year: int
    exported_at: datetime
    ledger_entries: tuple[PostedEntry, ...]
    documents: tuple[DocumentRecord, ...]
    filing_previews: tuple[str, ...]
    readiness_reports: tuple[AnnualReadinessResult, ...]
    receipts: tuple[str, ...]
    missing_document_ids: tuple[str, ...]


def build_annual_data(
    *,
    company_id: str,
    income_year: int,
    interview: YearEndInterviewAnswers,
    posted_entries: tuple[PostedEntry, ...],
    documents: tuple[DocumentRecord, ...] = (),
    confirmations: tuple[str, ...] = (),
    annual_full_time_equivalents: float | None = 0,
    audit_required: bool = False,
    small_enterprise: bool = True,
    annual_report_required: bool = False,
    cash_flow_statement_required: bool = False,
    sustainability_reporting_required: bool = False,
    fiscal_year_is_calendar_year: bool = True,
    prior_year_figures_confirmed: bool = True,
) -> AnnualData:
    return AnnualData(
        company_id=company_id,
        income_year=income_year,
        interview=interview,
        posted_entries=posted_entries,
        documents=documents,
        confirmations=confirmations,
        annual_full_time_equivalents=annual_full_time_equivalents,
        audit_required=audit_required,
        small_enterprise=small_enterprise,
        annual_report_required=annual_report_required,
        cash_flow_statement_required=cash_flow_statement_required,
        sustainability_reporting_required=sustainability_reporting_required,
        fiscal_year_is_calendar_year=fiscal_year_is_calendar_year,
        prior_year_figures_confirmed=prior_year_figures_confirmed,
    )


def assess_annual_accounts_readiness(data: AnnualData) -> AnnualReadinessResult:
    return AnnualReadinessResult.model_validate(_offline_json(assess_annual_accounts_offline(_accounts_offline_source(data, include_common=True))))


def assess_tax_return_readiness(data: AnnualData) -> AnnualReadinessResult:
    issues = _common_issues(data)
    if data.shareholder_loan_receivable > 0:
        issues.append(_error("shareholder_loan_receivable", "Lån fra selskap til aksjonær krever regnskapsføreravklaring."))
    return _result("skattemelding for AS", issues)


def simulate_annual_accounts(data: AnnualData) -> FilingSimulation:
    result = simulate_annual_accounts_offline(_accounts_offline_source(data, include_common=True))
    return FilingSimulation(filing=result.filing, preview=result.preview,
        readiness=AnnualReadinessResult.model_validate(_offline_json(result.readiness)),
        simulated_receipt_id=result.simulated_receipt_id, payload=_offline_json(result.payload))


def build_annual_accounts_payload(data: AnnualData) -> AnnualAccountsPayload:
    return AnnualAccountsPayload.model_validate(_offline_json(build_annual_accounts_offline_payload(_accounts_offline_source(data))))


def simulate_tax_return(data: AnnualData) -> FilingSimulation:
    readiness = assess_tax_return_readiness(data)
    estimated_tax_basis = round(data.interest_income - data.admin_costs + data.fritaksmetoden_add_back, 2)
    estimated_tax = round(max(0, estimated_tax_basis) * 0.22, 2)
    preview = "\n".join(
        [
            f"Skattemelding for AS {data.income_year}",
            f"Selskap: {data.company_id}",
            "",
            "Skattegrunnlag:",
            f"- Regnskapsmessig resultat før skatt: {_money(data.result_before_tax)}",
            f"- 3 prosent inntektsføring etter fritaksmetoden: {_money(data.fritaksmetoden_add_back)}",
            f"- Forenklet skattegrunnlag i simulering: {_money(estimated_tax_basis)}",
            f"- Estimert skatt 22 prosent: {_money(estimated_tax)}",
        ]
    )
    return FilingSimulation(
        filing="skattemelding for AS",
        preview=preview + "\n",
        readiness=readiness,
        simulated_receipt_id=f"sim-skattemelding-{data.company_id}-{data.income_year}" if readiness.is_ready else None,
    )


def build_company_archive(
    data: AnnualData,
    *,
    filing_simulations: tuple[FilingSimulation, ...],
    receipts: tuple[str, ...] = (),
) -> CompanyArchive:
    missing = tuple(document.id for document in data.documents if document.status.startswith("missing"))
    return CompanyArchive(
        company_id=data.company_id,
        income_year=data.income_year,
        exported_at=datetime.now(UTC),
        ledger_entries=data.posted_entries,
        documents=data.documents,
        filing_previews=tuple(simulation.preview for simulation in filing_simulations),
        readiness_reports=tuple(simulation.readiness for simulation in filing_simulations),
        receipts=receipts + tuple(
            simulation.simulated_receipt_id for simulation in filing_simulations if simulation.simulated_receipt_id
        ),
        missing_document_ids=missing,
    )


def write_company_archive(archive: CompanyArchive, out_path: str | Path) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(archive.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _common_issues(data: AnnualData) -> list[AnnualReadinessIssue]:
    issues: list[AnnualReadinessIssue] = []
    if not data.interview.bank_balance_confirmed:
        issues.append(_warning("bank_not_confirmed", "Bankbalanse er ikke bekreftet."))
    if data.interview.has_unpaid_items:
        issues.append(_error("unpaid_items_not_supported", "Ubetalte poster er ikke støttet i enkel holdingselskapssimulering."))
    if not data.interview.authority_to_submit_confirmed:
        issues.append(_error("authority_not_confirmed", "Innsendingsrett må bekreftes før filing."))
    if any(document.status.startswith("missing") for document in data.documents):
        issues.append(_warning("missing_documents", "Ett eller flere dokumenter mangler eller er akseptert med advarsel."))
    return issues


def _result(filing: str, issues: list[AnnualReadinessIssue]) -> AnnualReadinessResult:
    status = "blocked" if any(issue.level == "error" for issue in issues) else "ready"
    return AnnualReadinessResult(filing=filing, status=status, issues=issues)


def _error(code: str, message: str) -> AnnualReadinessIssue:
    return AnnualReadinessIssue(level="error", code=code, message=message)


def _warning(code: str, message: str) -> AnnualReadinessIssue:
    return AnnualReadinessIssue(level="warning", code=code, message=message)


def _money(value: float) -> str:
    return f"{value:.2f} kr"


def _accounts_offline_source(data: AnnualData, *, include_common: bool = False) -> AnnualAccountsOfflineSource:
    """Adapt the existing common Annual model to the owned offline Accounts profile."""
    return AnnualAccountsOfflineSource(
        company_id=data.company_id, income_year=data.income_year,
        bank_balance=data.bank_balance, investment_balance=data.investment_balance,
        admin_costs=data.admin_costs, financial_income=data.financial_income,
        financial_costs=data.financial_costs, shareholder_loan_payable=data.shareholder_loan_payable,
        share_capital=data.share_capital, retained_earnings=data.retained_earnings,
        result_before_tax=data.result_before_tax,
        general_meeting_approved=data.interview.general_meeting_approved,
        common_issues=tuple(issue.model_dump() for issue in _common_issues(data)) if include_common else (),
        confirmations=data.confirmations, annual_full_time_equivalents=data.annual_full_time_equivalents,
        audit_required=data.audit_required, small_enterprise=data.small_enterprise,
        annual_report_required=data.annual_report_required,
        cash_flow_statement_required=data.cash_flow_statement_required,
        sustainability_reporting_required=data.sustainability_reporting_required,
        fiscal_year_is_calendar_year=data.fiscal_year_is_calendar_year,
        prior_year_figures_confirmed=data.prior_year_figures_confirmed,
    )


def _offline_json(value):
    """Convert immutable public values to the retained root Pydantic wire shape."""
    if isinstance(value, Mapping):
        return {key: _offline_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_offline_json(item) for item in value]
    return value
