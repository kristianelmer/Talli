"""The production readiness handoff stays closed until its source owner exists.

Company Access owns definitive eligibility. Annual Compliance (#149, after
#193/#153) owns trustworthy aggregate company-year readiness. The legacy owner-
writable readiness snapshot cannot supply this authority. Operational production
clearance remains separately owned by #179/#198. This binding fabricates none of
those facts and is not an assertion that #192's end-to-end exit is complete.
"""

from talli_backend.modules.billing.public import (
    AnnualCheckoutPrerequisites, BillingError, BillingErrorCode,
)


async def unavailable_annual_checkout_prerequisites() -> AnnualCheckoutPrerequisites:
    raise BillingError.precondition(BillingErrorCode.FILING_NOT_READY)
