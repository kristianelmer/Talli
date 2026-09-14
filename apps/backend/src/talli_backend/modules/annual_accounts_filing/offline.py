"""Accounts-specific offline public-data projection; no live RR0002 substitution.

Common Annual totals and common readiness issues are supplied as immutable facts.
The original 22 fields, Python rounding and attachment rules remain distinct.
"""
from __future__ import annotations

from .public import AnnualAccountsOfflineSimulation


def _error(code, message):
    return {'level': 'error', 'code': code, 'message': message}


def assess(data):
    issues = [dict(item) for item in data.common_issues]
    if not data.general_meeting_approved:
        issues.append(_error('general_meeting_not_approved', 'Generalforsamling må godkjenne årsregnskapet før filing.'))
    if data.bank_balance < 0:
        issues.append(_error('negative_bank_balance', 'Bankbalanse kan ikke være negativ i enkel holdingselskapssimulering.'))
    issues.extend(_annual_accounts_payload_issues(data))
    return {'filing': 'årsregnskap', 'status': 'blocked' if any(issue['level'] == 'error' for issue in issues) else 'ready', 'issues': issues}


def build_payload(data):
    return {
        'schema_type': 'aarsregnskap-vanlig-202406',
        'hovedskjema_data_format_id': '1266', 'hovedskjema_data_format_version': '51820',
        'selskapsregnskap_data_format_id': '758', 'selskapsregnskap_data_format_version': '51980',
        'fields': _rr0002_fields(data),
        'notes': {'annual_full_time_equivalents': float(data.annual_full_time_equivalents or 0), 'confirmations': data.confirmations},
        'attachment_decisions': _annual_accounts_attachment_decisions(data),
        'feedback_items': _annual_accounts_payload_issues(data),
    }


def _money(value):
    return f'{value:.2f} kr'


def simulate(data):
    readiness = assess(data)
    payload = build_payload(data)
    preview = "\n".join(
        [
            f"Årsregnskap {data.income_year}",
            f"Selskap: {data.company_id}",
            f"Schema: {payload['schema_type']}",
            "",
            "Balanse:",
            f"- Bank: {_money(data.bank_balance)}",
            f"- Aksjeinvesteringer: {_money(data.investment_balance)}",
            f"- Aksjekapital: {_money(data.share_capital)}",
            f"- Annen egenkapital: {_money(data.retained_earnings)}",
            f"- Aksjonærlån: {_money(data.shareholder_loan_payable)}",
            "",
            "Resultat:",
            f"- Finansinntekter: {_money(data.financial_income)}",
            f"- Administrasjonskostnader: {_money(data.admin_costs)}",
            f"- Finanskostnader: {_money(data.financial_costs)}",
            f"- Resultat før skatt: {_money(data.result_before_tax)}",
            "",
            "Noter/vedlegg:",
            f"- Årsverk: {payload['notes']['annual_full_time_equivalents']:g}",
            f"- Vedleggsbeslutninger: {len(payload['attachment_decisions'])}",
        ]
    )
    return AnnualAccountsOfflineSimulation(
        filing="årsregnskap",
        preview=preview + "\n",
        readiness=readiness,
        simulated_receipt_id=f"sim-arsregnskap-{data.company_id}-{data.income_year}" if readiness['status'] == 'ready' else None,
        payload=payload,
    )


def _annual_accounts_payload_issues(data):
    issues = []
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


def _annual_accounts_attachment_decisions(data):
    decisions = [
        dict(
            required=data.audit_required,
            code="auditor_report",
            message="Revisjonsberetning kreves ved revisjonsplikt.",
        ),
        dict(
            required=data.annual_report_required,
            code="annual_report",
            message="Årsberetning kreves utenfor småforetaksløypen.",
        ),
        dict(
            required=data.cash_flow_statement_required,
            code="cash_flow_statement",
            message="Kontantstrømoppstilling kreves utenfor enkel småforetaksløype.",
        ),
        dict(
            required=data.sustainability_reporting_required,
            code="sustainability_report",
            message="Bærekraftsrapportering er utenfor launch-scope.",
        ),
    ]
    if not any(decision['required'] for decision in decisions):
        decisions.append(
            dict(
                required=False,
                code="small_holding_no_extra_attachment",
                message="Ingen ekstra vedlegg kreves for støttet små holding-AS før TT02-validering sier noe annet.",
            )
        )
    return decisions


def _rr0002_fields(data):
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
        _field("sumFinansinntekter/aarets", "153", data.financial_income, "ledger.8070_8050"),
        _field("sumFinanskostnader/aarets", "17130", data.financial_costs, "ledger.8090"),
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


def _field(tag: str, orid: str, value: str | float | int, source: str):
    if isinstance(value, float):
        value = round(value, 2)
    return dict(tag=tag, orid=orid, value=value, source=source)
