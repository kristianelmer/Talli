"""RF overlap/onboarding fixture before the Tax and Accounts cutovers.

The aggregate deliberately retains their predecessor topology here. Explicitly
unavailable adapters cannot call those future contracts; the remaining real
application dependencies still determine readiness. Post-cutover journeys use
the full workspace launcher instead.
"""
from pathlib import Path
import runpy


def predecessor_application():
    from talli_backend.main import create_app
    from talli_backend.modules.company_tax_filing.public import CompanyTaxError
    from talli_backend.modules.annual_accounts_filing.public import AnnualAccountsError

    class UnavailableTaxSessions:
        async def session(self, access_token):
            raise CompanyTaxError.unavailable()

    class UnavailableAccountsSessions:
        async def session(self, access_token):
            raise AnnualAccountsError.unavailable()

    return create_app(company_tax_session_factory=UnavailableTaxSessions(),
                      annual_accounts_session_factory=UnavailableAccountsSessions())


if __name__ == '__main__':
    launcher = runpy.run_path(str(Path(__file__).with_name('start_rf1086_workspace_backend.py')))
    launcher['main'](application_factory=predecessor_application)
