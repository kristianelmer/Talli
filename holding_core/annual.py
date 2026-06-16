from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from holding_core.ledger import PostedEntry


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
        cost_accounts = {"7770", "6705", "6420", "7790", "6720", "7795"}
        return round(
            sum(line.debit for entry in self.posted_entries for line in entry.lines if line.account in cost_accounts),
            2,
        )

    @property
    def dividend_income(self) -> float:
        return self.account_credit_balance("8070")

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
        return round(self.dividend_income - self.admin_costs, 2)

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
    issues = _common_issues(data)
    if not data.interview.general_meeting_approved:
        issues.append(_error("general_meeting_not_approved", "Generalforsamling må godkjenne årsregnskapet før filing."))
    if data.bank_balance < 0:
        issues.append(_error("negative_bank_balance", "Bankbalanse kan ikke være negativ i enkel holdingselskapssimulering."))
    issues.extend(_annual_accounts_payload_issues(data))
    return _result("årsregnskap", issues)


def assess_tax_return_readiness(data: AnnualData) -> AnnualReadinessResult:
    issues = _common_issues(data)
    if data.shareholder_loan_receivable > 0:
        issues.append(_error("shareholder_loan_receivable", "Lån fra selskap til aksjonær krever regnskapsføreravklaring."))
    return _result("skattemelding for AS", issues)


def simulate_annual_accounts(data: AnnualData) -> FilingSimulation:
    readiness = assess_annual_accounts_readiness(data)
    payload = build_annual_accounts_payload(data)
    preview = "\n".join(
        [
            f"Årsregnskap {data.income_year}",
            f"Selskap: {data.company_id}",
            f"Schema: {payload.schema_type}",
            "",
            "Balanse:",
            f"- Bank: {_money(data.bank_balance)}",
            f"- Aksjeinvesteringer: {_money(data.investment_balance)}",
            f"- Aksjekapital: {_money(data.share_capital)}",
            f"- Annen egenkapital: {_money(data.retained_earnings)}",
            f"- Aksjonærlån: {_money(data.shareholder_loan_payable)}",
            "",
            "Resultat:",
            f"- Utbytte/gevinster: {_money(data.dividend_income)}",
            f"- Administrasjonskostnader: {_money(data.admin_costs)}",
            f"- Resultat før skatt: {_money(data.result_before_tax)}",
            "",
            "Noter/vedlegg:",
            f"- Årsverk: {payload.notes.annual_full_time_equivalents:g}",
            f"- Vedleggsbeslutninger: {len(payload.attachment_decisions)}",
        ]
    )
    return FilingSimulation(
        filing="årsregnskap",
        preview=preview + "\n",
        readiness=readiness,
        simulated_receipt_id=f"sim-arsregnskap-{data.company_id}-{data.income_year}" if readiness.is_ready else None,
        payload=payload.model_dump(mode="json"),
    )


def build_annual_accounts_payload(data: AnnualData) -> AnnualAccountsPayload:
    feedback_items = tuple(_annual_accounts_payload_issues(data))
    return AnnualAccountsPayload(
        schema_type="aarsregnskap-vanlig-202406",
        hovedskjema_data_format_id="1266",
        hovedskjema_data_format_version="51820",
        selskapsregnskap_data_format_id="758",
        selskapsregnskap_data_format_version="51980",
        fields=tuple(_rr0002_fields(data)),
        notes=AnnualAccountsNotePayload(
            annual_full_time_equivalents=float(data.annual_full_time_equivalents or 0),
            confirmations=tuple(data.confirmations),
        ),
        attachment_decisions=tuple(_annual_accounts_attachment_decisions(data)),
        feedback_items=feedback_items,
    )


def simulate_tax_return(data: AnnualData) -> FilingSimulation:
    readiness = assess_tax_return_readiness(data)
    estimated_tax_basis = round(data.admin_costs + data.fritaksmetoden_add_back, 2)
    estimated_tax = round(estimated_tax_basis * 0.22, 2)
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


def _annual_accounts_payload_issues(data: AnnualData) -> list[AnnualReadinessIssue]:
    issues: list[AnnualReadinessIssue] = []
    if data.annual_full_time_equivalents is None:
        issues.append(_error("annual_accounts_aarsverk_missing", "Årsverk må oppgis i årsregnskapsnoten."))
    elif data.annual_full_time_equivalents < 0:
        issues.append(_error("annual_accounts_aarsverk_negative", "Årsverk kan ikke være negativt."))
    if data.audit_required:
        issues.append(_error("annual_accounts_audit_required", "Revisjonsplikt er utenfor enkel holding-AS-løype."))
    if not data.small_enterprise:
        issues.append(_error("annual_accounts_not_small_enterprise", "Ikke-små foretak krever utvidet årsregnskapsmodell."))
    if data.annual_report_required:
        issues.append(_error("annual_accounts_annual_report_required", "Årsberetning er ikke støttet i første årsregnskapsløype."))
    if data.cash_flow_statement_required:
        issues.append(_error("annual_accounts_cash_flow_required", "Kontantstrømoppstilling er ikke støttet i første årsregnskapsløype."))
    if data.sustainability_reporting_required:
        issues.append(_error("annual_accounts_sustainability_required", "Bærekraftsrapportering er ikke støttet i første årsregnskapsløype."))
    if not data.fiscal_year_is_calendar_year:
        issues.append(_error("annual_accounts_non_calendar_year", "Avvikende regnskapsår er ikke støttet i første årsregnskapsløype."))
    if not data.prior_year_figures_confirmed:
        issues.append(_error("annual_accounts_prior_year_missing", "Fjorårstall må bekreftes før RR-0002 payload kan bygges."))
    return issues


def _annual_accounts_attachment_decisions(data: AnnualData) -> list[AnnualAccountsAttachmentDecision]:
    decisions = [
        AnnualAccountsAttachmentDecision(
            required=data.audit_required,
            code="auditor_report",
            message="Revisjonsberetning kreves ved revisjonsplikt.",
        ),
        AnnualAccountsAttachmentDecision(
            required=data.annual_report_required,
            code="annual_report",
            message="Årsberetning kreves utenfor småforetaksløypen.",
        ),
        AnnualAccountsAttachmentDecision(
            required=data.cash_flow_statement_required,
            code="cash_flow_statement",
            message="Kontantstrømoppstilling kreves utenfor enkel småforetaksløype.",
        ),
        AnnualAccountsAttachmentDecision(
            required=data.sustainability_reporting_required,
            code="sustainability_report",
            message="Bærekraftsrapportering er utenfor launch-scope.",
        ),
    ]
    if not any(decision.required for decision in decisions):
        decisions.append(
            AnnualAccountsAttachmentDecision(
                required=False,
                code="small_holding_no_extra_attachment",
                message="Ingen ekstra vedlegg kreves for støttet små holding-AS før TT02-validering sier noe annet.",
            )
        )
    return decisions


def _rr0002_fields(data: AnnualData) -> list[Rr0002Field]:
    result_before_tax = data.result_before_tax
    annual_result = result_before_tax
    sum_financial_assets = data.investment_balance
    sum_current_assets = data.bank_balance
    sum_assets = round(sum_financial_assets + sum_current_assets, 2)
    sum_paid_in_equity = data.share_capital
    retained = round(data.retained_earnings + annual_result, 2)
    sum_equity = round(sum_paid_in_equity + retained, 2)
    short_term_debt = data.shareholder_loan_payable
    sum_debt = short_term_debt
    return [
        _field("regnskapsaar", "17102", data.income_year, "company.income_year"),
        _field("regnskapsstart", "17103", f"{data.income_year}-01-01", "calendar_year"),
        _field("regnskapsslutt", "17104", f"{data.income_year}-12-31", "calendar_year"),
        _field("aarsregnskapIkkeRevideres", "34669", "ja" if not data.audit_required else "nei", "annual_accounts.audit_required"),
        _field("valuta", "34984", "NOK", "launch_currency"),
        _field("sumDriftskostnad/aarets", "17126", data.admin_costs, "ledger.expense_accounts"),
        _field("sumFinansinntekter/aarets", "153", data.dividend_income, "ledger.8070"),
        _field("sumFinanskostnader/aarets", "17130", 0, "launch_scope"),
        _field("resultatFoerSkattekostnad/aarets", "167", result_before_tax, "derived"),
        _field("aarsresultat/aarets", "172", annual_result, "derived"),
        _field("investeringAksjerAndeler/aarets", "7100", data.investment_balance, "ledger.1800"),
        _field("sumFinansielleAnleggsmidler/aarets", "5267", sum_financial_assets, "derived"),
        _field("sumBankinnskuddKontanter/aarets", "29042", data.bank_balance, "ledger.1920"),
        _field("sumOmloepsmidler/aarets", "194", sum_current_assets, "derived"),
        _field("sumEiendeler/aarets", "219", sum_assets, "derived"),
        _field("sumInnskuttEgenkapital/aarets", "3730", sum_paid_in_equity, "ledger.2000"),
        _field("annenEgenkapital/aarets", "3274", retained, "ledger.2050_and_result"),
        _field("sumOpptjentEgenkapital/aarets", "9702", retained, "derived"),
        _field("sumEgenkapital/aarets", "250", sum_equity, "derived"),
        _field("sumKortsiktigGjeld/aarets", "85", short_term_debt, "ledger.2255"),
        _field("sumGjeld/aarets", "1119", sum_debt, "derived"),
        _field("antallAarsverk", "37467", data.annual_full_time_equivalents or 0, "annual_accounts.notes"),
    ]


def _field(tag: str, orid: str, value: str | float | int, source: str) -> Rr0002Field:
    if isinstance(value, float):
        value = round(value, 2)
    return Rr0002Field(tag=tag, orid=orid, value=value, source=source)


def _result(filing: str, issues: list[AnnualReadinessIssue]) -> AnnualReadinessResult:
    status = "blocked" if any(issue.level == "error" for issue in issues) else "ready"
    return AnnualReadinessResult(filing=filing, status=status, issues=issues)


def _error(code: str, message: str) -> AnnualReadinessIssue:
    return AnnualReadinessIssue(level="error", code=code, message=message)


def _warning(code: str, message: str) -> AnnualReadinessIssue:
    return AnnualReadinessIssue(level="warning", code=code, message=message)


def _money(value: float) -> str:
    return f"{value:.2f} kr"
