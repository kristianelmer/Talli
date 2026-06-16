export type BillingPlan = "founder" | "standard";
export type BillingStatus =
  | "active"
  | "subscription_required"
  | "filing_package_required"
  | "ready_for_production_filing"
  | "unsupported_case"
  | "refund_eligible";

export type BillingAccount = {
  company_id: string;
  pricing_plan: BillingPlan;
  monthly_nok: number;
  filing_package_nok: number;
  founder_cohort_number: number | null;
  subscription_active: boolean;
  filing_package_paid: boolean;
  supported_case: boolean;
  refund_eligible: boolean;
  no_charge_reason: string | null;
};

export type BillingGateResult = {
  status: BillingStatus;
  allowed: boolean;
  chargeAllowed: boolean;
  message: string;
};

export class BillingValidationError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "BillingValidationError";
    this.code = code;
  }
}

export function billingPricing(plan: BillingPlan) {
  if (plan === "founder") {
    return { pricing_plan: plan, monthly_nok: 29, filing_package_nok: 299 };
  }
  return { pricing_plan: plan, monthly_nok: 49, filing_package_nok: 499 };
}

export function buildBillingAccount(input: {
  companyId: string;
  pricingPlan: BillingPlan;
  founderCohortNumber?: number | null;
  subscriptionActive?: boolean;
  filingPackagePaid?: boolean;
  supportedCase?: boolean;
  refundEligible?: boolean;
  noChargeReason?: string | null;
}): BillingAccount {
  if (!input.companyId) {
    throw new BillingValidationError("Selskap mangler.", "missing_company");
  }
  if (!["founder", "standard"].includes(input.pricingPlan)) {
    throw new BillingValidationError("Ugyldig prisplan.", "invalid_pricing_plan");
  }
  const founderCohortNumber = input.pricingPlan === "founder" ? input.founderCohortNumber : null;
  const validFounderCohort =
    typeof founderCohortNumber === "number" &&
    Number.isInteger(founderCohortNumber) &&
    founderCohortNumber >= 1 &&
    founderCohortNumber <= 100;
  if (input.pricingPlan === "founder" && !validFounderCohort) {
    throw new BillingValidationError("Founder-kull må være mellom 1 og 100.", "founder_cohort_limit");
  }
  const pricing = billingPricing(input.pricingPlan);
  return {
    company_id: input.companyId,
    ...pricing,
    founder_cohort_number: founderCohortNumber ?? null,
    subscription_active: Boolean(input.subscriptionActive),
    filing_package_paid: Boolean(input.filingPackagePaid),
    supported_case: input.supportedCase ?? true,
    refund_eligible: Boolean(input.refundEligible),
    no_charge_reason: input.noChargeReason ?? null,
  };
}

export function productionBillingGate(account: BillingAccount, filingReady: boolean): BillingGateResult {
  if (account.refund_eligible) {
    return {
      status: "refund_eligible",
      allowed: false,
      chargeAllowed: false,
      message: "Filingpakken er markert refusjonsberettiget etter støttet feil.",
    };
  }
  if (!account.supported_case) {
    return {
      status: "unsupported_case",
      allowed: false,
      chargeAllowed: false,
      message: account.no_charge_reason || "Saken er utenfor Talli-støtte. Ikke ta betalt for filingpakke.",
    };
  }
  if (!account.subscription_active) {
    return {
      status: "subscription_required",
      allowed: false,
      chargeAllowed: false,
      message: "Aktivt abonnement kreves før produksjonsfiling.",
    };
  }
  if (!filingReady) {
    return {
      status: "active",
      allowed: false,
      chargeAllowed: false,
      message: "Filing readiness må være klar før filingpakke kan betales.",
    };
  }
  if (!account.filing_package_paid) {
    return {
      status: "filing_package_required",
      allowed: false,
      chargeAllowed: true,
      message: "Filingpakke må betales før produksjonsinnsending.",
    };
  }
  return {
    status: "ready_for_production_filing",
    allowed: true,
    chargeAllowed: false,
    message: "Billing og filing readiness er klare.",
  };
}
