import assert from "node:assert/strict";
import test from "node:test";

import {
  BillingValidationError,
  buildBillingAccount,
  productionBillingGate,
} from "../app/lib/billing.ts";

test("builds founder and standard billing accounts with launch prices", () => {
  const founder = buildBillingAccount({ companyId: "company-id", pricingPlan: "founder", founderCohortNumber: 100 });
  const standard = buildBillingAccount({ companyId: "company-id", pricingPlan: "standard" });

  assert.equal(founder.monthly_nok, 29);
  assert.equal(founder.filing_package_nok, 299);
  assert.equal(founder.founder_cohort_number, 100);
  assert.equal(standard.monthly_nok, 49);
  assert.equal(standard.filing_package_nok, 499);
});

test("blocks founder cohorts outside first 100 companies", () => {
  assert.throws(
    () => buildBillingAccount({ companyId: "company-id", pricingPlan: "founder", founderCohortNumber: 101 }),
    (error) => error instanceof BillingValidationError && error.code === "founder_cohort_limit",
  );
});

test("filing package charge waits for subscription and readiness", () => {
  const inactive = buildBillingAccount({ companyId: "company-id", pricingPlan: "standard" });
  const active = buildBillingAccount({ companyId: "company-id", pricingPlan: "standard", subscriptionActive: true });
  const paid = buildBillingAccount({
    companyId: "company-id",
    pricingPlan: "standard",
    subscriptionActive: true,
    filingPackagePaid: true,
  });

  assert.equal(productionBillingGate(inactive, true).status, "subscription_required");
  assert.equal(productionBillingGate(active, false).chargeAllowed, false);
  assert.equal(productionBillingGate(active, true).status, "filing_package_required");
  assert.equal(productionBillingGate(active, true).chargeAllowed, true);
  assert.equal(productionBillingGate(paid, true).allowed, true);
});

test("unsupported cases remain no-charge and supported paid failures are refund eligible", () => {
  const unsupported = buildBillingAccount({
    companyId: "company-id",
    pricingPlan: "standard",
    subscriptionActive: true,
    supportedCase: false,
    noChargeReason: "Utenfor støtte.",
  });
  const refund = buildBillingAccount({
    companyId: "company-id",
    pricingPlan: "standard",
    subscriptionActive: true,
    filingPackagePaid: true,
    refundEligible: true,
  });

  assert.equal(productionBillingGate(unsupported, true).status, "unsupported_case");
  assert.equal(productionBillingGate(unsupported, true).chargeAllowed, false);
  assert.equal(productionBillingGate(refund, true).status, "refund_eligible");
});
