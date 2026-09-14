"""Tax-specific annual readiness, preserving the predecessor issue ordering."""
from __future__ import annotations

from .calculation import feedback
from .numbers import truthy
from .public import CompanyTaxReadinessIssue, CompanyTaxReturnSource


def assess(source: CompanyTaxReturnSource, company_id: str) -> tuple[CompanyTaxReadinessIssue, ...]:
    issues = []
    scoped_actions = tuple(action for action in source.holding_actions
                           if action.get('company_id') == company_id
                           and action.get('income_year') == source.income_year)
    if any(action.get('risk_level') == 'block' for action in scoped_actions):
        issues.append(CompanyTaxReadinessIssue(
            'block', 'blocking_holding_action',
            'Støttet holdinghandling må ryddes før skattemelding.', 'holding_actions'))
    if (not any(action.get('action_type') == 'tax_settlement' for action in scoped_actions)
            and not truthy((source.annual_data or {}).get('no_activity_confirmed'))):
        issues.append(CompanyTaxReadinessIssue(
            'warning', 'tax_settlement_missing',
            'Skatteoppgjør er ikke registrert for året.', 'tax_settlement'))
    # The predecessor scopes only the two checks above. Payload feedback consumes
    # the supplied immutable snapshot as a whole; its source workflow owns scope.
    for item in feedback({'annualData': source.annual_data, 'ledgerEntries': source.ledger_entries,
                          'holdingActions': source.holding_actions}):
        if item['level'] in ('block', 'warning'):
            issues.append(CompanyTaxReadinessIssue(item['level'], item['code'], item['message'], item['source']))
    return tuple(issues)
