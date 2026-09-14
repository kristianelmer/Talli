"""Fixed CLI mapping to the Accounts-owned calculation and XML contracts."""
from talli_backend.modules.annual_accounts_filing.public import (
    AnnualAccountsSource, AnnualAccountsRenderInput, build_annual_accounts, render_annual_accounts,
)


def generate(value):
    candidate = build_annual_accounts(AnnualAccountsSource(
        income_year=value['incomeYear'], annual_data=value.get('annualData'),
        ledger_entries=() if value.get('ledgerEntries') is None else value['ledgerEntries'],
    ))
    documents = render_annual_accounts(AnnualAccountsRenderInput(
        candidate=candidate, organization_number=value['companyOrgNumber'],
        company_name=value['companyName'], contact_email=value['contactEmail'],
        approval_date=value['approvalDate'], confirming_representative=value['confirmingRepresentative'],
    ))
    return {'mainFormXml': documents.main_form_xml, 'companyAccountsXml': documents.company_accounts_xml,
            'feedback': [dict(item) for item in candidate.feedback]}
