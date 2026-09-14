"""Fixed CLI mapping to the Accounts-owned calculation and XML contracts."""
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsSource, AnnualAccountsRenderInput, build_annual_accounts, render_annual_accounts,
)


def generate(value):
    annual = value.get('annualData')
    # The released JS profile treats only falsey scalars as absent. Empty JSON
    # arrays/objects remain present and retain their original shape failures.
    if annual is False or type(annual) in (int, float) and annual == 0 or annual == '':
        annual = None
    entries = value.get('ledgerEntries')
    if entries is not None and not isinstance(entries, list):
        raise ValueError('Ledger entries must be an array.')
    candidate = build_annual_accounts(AnnualAccountsSource(
        income_year=value['incomeYear'], annual_data=annual,
        ledger_entries=() if entries is None else entries,
    ))
    documents = render_annual_accounts(AnnualAccountsRenderInput(
        candidate=candidate, organization_number=value['companyOrgNumber'],
        company_name=value['companyName'], contact_email=value['contactEmail'],
        approval_date=value['approvalDate'], confirming_representative=value['confirmingRepresentative'],
    ))
    return {'mainFormXml': documents.main_form_xml, 'companyAccountsXml': documents.company_accounts_xml,
            'feedback': [dict(item) for item in candidate.feedback]}
