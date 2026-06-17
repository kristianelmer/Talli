import assert from "node:assert/strict";
import test from "node:test";

import {
  BillingValidationError,
  applyBillingProviderEvent,
  buildBillingAccount,
  productionBillingGate,
  simulateBillingProviderEvent,
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

test("simulated provider events persist idempotent payment and refund references", () => {
  const active = buildBillingAccount({ companyId: "company-id", pricingPlan: "founder", founderCohortNumber: 1 });
  const subscriptionEvent = simulateBillingProviderEvent({
    companyId: "company-id",
    kind: "subscription",
    amountNok: active.monthly_nok,
  });
  const subscribed = applyBillingProviderEvent(active, subscriptionEvent);

  assert.equal(subscriptionEvent.idempotencyKey, "billing-company-id-subscription");
  assert.equal(subscribed.subscription_active, true);
  assert.equal(subscribed.subscription_provider_ref, "sim_subscription_company-id");

  const filingEvent = simulateBillingProviderEvent({
    companyId: "company-id",
    kind: "filing_package",
    amountNok: active.filing_package_nok,
    incomeYear: 2025,
  });
  const paid = applyBillingProviderEvent(subscribed, filingEvent);

  assert.equal(filingEvent.idempotencyKey, "billing-company-id-filing_package-2025");
  assert.equal(paid.filing_package_paid, true);
  assert.equal(paid.filing_package_payment_ref, "sim_filing_package_company-id_2025");

  const declinedEvent = simulateBillingProviderEvent({
    companyId: "company-id",
    kind: "filing_package",
    amountNok: active.filing_package_nok,
    incomeYear: 2026,
    status: "failed",
  });
  const declined = applyBillingProviderEvent(subscribed, declinedEvent);

  assert.equal(declined.filing_package_paid, false);
  assert.equal(declined.filing_package_payment_ref, undefined);

  const refundEvent = simulateBillingProviderEvent({
    companyId: "company-id",
    kind: "refund",
    amountNok: active.filing_package_nok,
    incomeYear: 2025,
    status: "refunded",
  });
  const refunded = applyBillingProviderEvent({ ...paid, refund_eligible: true }, refundEvent);

  assert.equal(refunded.refund_completed, true);
  assert.equal(refunded.refund_eligible, false);
  assert.equal(refunded.refund_provider_ref, "sim_refund_company-id_2025");
});
