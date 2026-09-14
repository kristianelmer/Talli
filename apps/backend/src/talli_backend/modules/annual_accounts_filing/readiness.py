"""Accounts-specific readiness, preserving Corporate and Annual fact boundaries."""
from __future__ import annotations

from .calculation import feedback
from .numbers import truthy
from .public import AnnualAccountsReadinessIssue


def assess(source, company_id, corporate):
    issues = []

    def add(level, code, message, owner, accepted=False):
        issues.append(AnnualAccountsReadinessIssue(level, code, message, owner, accepted))

    if corporate is not None and truthy(corporate.enabled):
        for item in corporate.blockers:
            add('block', item.code, item.message, 'corporate_documents')
    selected = [entry for entry in source.ledger_entries if entry['company_id'] == company_id and entry['income_year'] == source.income_year]
    if not selected:
        add('block', 'ledger_missing', 'Årsregnskap krever postert åpningsbalanse eller holdinghandlinger.', 'ledger')
    if source.annual_data is not None and not truthy(source.annual_data['answers'].get('general_meeting_approved')):
        add('block', 'general_meeting_not_approved', 'Generalforsamling må godkjenne årsregnskapet.', 'annual_data')
    for item in feedback(source.annual_data):
        add(item['level'], item['code'], item['message'], item['source'])
    if any(entry['risk_flags'] and not truthy(entry.get('warning_accepted_at')) for entry in selected):
        add('warning', 'manual_journal_warning_unaccepted', 'Manuelle posteringer med filingadvarsel må aksepteres.', 'ledger')
    if any(entry['risk_flags'] and truthy(entry.get('warning_accepted_at')) for entry in selected):
        add('warning', 'manual_journal_warning_accepted', 'Manuell postering er akseptert som advarsel.', 'ledger', True)
    return tuple(issues)
