from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PricingPlan(StrEnum):
    FOUNDER = "founder"
    STANDARD = "standard"


class BillingStatus(StrEnum):
    ACTIVE = "active"
    SUBSCRIPTION_REQUIRED = "subscription_required"
    FILING_PACKAGE_REQUIRED = "filing_package_required"
    READY_FOR_PRODUCTION_FILING = "ready_for_production_filing"
    UNSUPPORTED_CASE = "unsupported_case"
    REFUND_ELIGIBLE = "refund_eligible"


class Pricing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan: PricingPlan
    monthly_nok: int
    filing_package_nok: int


class CompanyBillingAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: str
    pricing: Pricing
    founder_cohort_number: int | None = Field(default=None, ge=1, le=100)
    subscription_active: bool = False
    filing_package_paid: bool = False
    supported_case: bool = True
    refund_eligible: bool = False


class BillingGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: BillingStatus
    allowed: bool
    charge_allowed: bool
    message: str


FOUNDER_PRICING = Pricing(plan=PricingPlan.FOUNDER, monthly_nok=29, filing_package_nok=299)
STANDARD_PRICING = Pricing(plan=PricingPlan.STANDARD, monthly_nok=49, filing_package_nok=499)


def assign_founder_pricing(company_id: str, *, cohort_number: int) -> CompanyBillingAccount:
    return CompanyBillingAccount(
        company_id=company_id,
        pricing=FOUNDER_PRICING,
        founder_cohort_number=cohort_number,
    )


def assign_standard_pricing(company_id: str) -> CompanyBillingAccount:
    return CompanyBillingAccount(company_id=company_id, pricing=STANDARD_PRICING)


def production_filing_gate(account: CompanyBillingAccount, *, filing_ready: bool) -> BillingGateResult:
    if not account.supported_case:
        return BillingGateResult(
            status=BillingStatus.UNSUPPORTED_CASE,
            allowed=False,
            charge_allowed=False,
            message="Case is outside Talli support boundary; do not charge filing package.",
        )
    if not account.subscription_active:
        return BillingGateResult(
            status=BillingStatus.SUBSCRIPTION_REQUIRED,
            allowed=False,
            charge_allowed=False,
            message="Active subscription required before production filing.",
        )
    if not filing_ready:
        return BillingGateResult(
            status=BillingStatus.ACTIVE,
            allowed=False,
            charge_allowed=False,
            message="Filing readiness gate must pass before charging filing package.",
        )
    if not account.filing_package_paid:
        return BillingGateResult(
            status=BillingStatus.FILING_PACKAGE_REQUIRED,
            allowed=False,
            charge_allowed=True,
            message="Filing package payment required before production submission starts.",
        )
    return BillingGateResult(
        status=BillingStatus.READY_FOR_PRODUCTION_FILING,
        allowed=True,
        charge_allowed=False,
        message="Billing and filing readiness gates have passed.",
    )


def mark_supported_filing_failure(account: CompanyBillingAccount) -> CompanyBillingAccount:
    return account.model_copy(update={"refund_eligible": True})
