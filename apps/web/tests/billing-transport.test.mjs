import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createTalliApiClient, TalliApiError } from "@talli/talli-api-client";

const companyId = "10000000-0000-4000-8000-000000000001";

function account() {
  return {
    companyId,
    pricingPlan: "standard",
    monthlyNok: 49,
    filingPackageNok: 499,
    founderCohortNumber: null,
    subscriptionActive: true,
    filingPackagePaid: false,
    supportedCase: true,
    refundEligible: false,
    refundCompleted: false,
    noChargeReason: null,
    providerCustomerReference: "sim_customer",
    subscriptionProviderReference: "sim_subscription",
    filingPackagePaymentReference: null,
    refundProviderReference: null,
    updatedBy: "20000000-0000-4000-8000-000000000001",
    createdAt: "2026-09-05T00:00:00Z",
    updatedAt: "2026-09-05T00:00:00Z",
  };
}

test("billing mutation uses generated path and durable operation key", async () => {
  const captured = {};
  const api = createTalliApiClient({
    baseUrl: "https://backend.example/",
    fetch: async (url, request) => {
      captured.url = String(url);
      captured.request = request;
      return Response.json(account());
    },
  });
  const result = await api.billingConfigureAccount(
    { companyId, pricingPlan: "standard", founderCohortNumber: null },
    { idempotencyKey: "70000000-0000-4000-8000-000000000070", requestId: "billing-configure" },
  );
  assert.equal(result.monthlyNok, 49);
  assert.equal(captured.url, "https://backend.example/api/v1/billing/accounts/configuration");
  assert.equal(captured.request.headers["Idempotency-Key"], "70000000-0000-4000-8000-000000000070");
  assert.equal(captured.request.headers["X-Request-ID"], "billing-configure");
});

test("billing entitlement is read from the backend and malformed policy is rejected", async () => {
  const captured = {};
  const api = createTalliApiClient({
    baseUrl: "https://backend.example",
    fetch: async (url) => {
      captured.url = String(url);
      return Response.json({
        companyId,
        incomeYear: 2025,
        obligation: "aksjonaerregisteroppgaven",
        status: "filing_package_required",
        allowed: false,
        chargeAllowed: true,
        readinessAllowed: true,
        billingExempt: false,
        message: "Payment required.",
        pilotEntitlementId: null,
      });
    },
  });
  const result = await api.billingReadEntitlement({
    companyId,
    incomeYear: 2025,
    obligation: "aksjonaerregisteroppgaven",
  });
  assert.equal(result.chargeAllowed, true);
  assert.match(captured.url, /\/api\/v1\/billing\/entitlement\?/u);

  const malformed = createTalliApiClient({
    baseUrl: "https://backend.example",
    fetch: async () => Response.json({ ...result, readinessAllowed: "yes" }),
  });
  await assert.rejects(
    malformed.billingReadEntitlement({
      companyId,
      incomeYear: 2025,
      obligation: "aksjonaerregisteroppgaven",
    }),
    (error) => error instanceof TalliApiError && error.status === 502,
  );
});

test("billing page renders every backend-owned price without TypeScript policy", () => {
  const pages = [
    new URL("../app/(owner)/billing/page.tsx", import.meta.url),
    new URL("../app/(owner)/workspace/page.tsx", import.meta.url),
  ].map((path) => readFileSync(path, "utf8"));
  assert.ok(pages.every((page) => /data\.billingPricing/u.test(page)));
  assert.match(pages[0], /pricing\.map\(\(item\)/u);
  assert.match(pages[1], /billingPricing\.map\(\(pricing\)/u);
  for (const page of pages) {
    assert.doesNotMatch(page, /billingPricing\(/u);
    assert.doesNotMatch(page, /monthly_nok:\s*(?:29|49)/u);
    assert.doesNotMatch(page, /filing_package_nok:\s*(?:299|499)/u);
    assert.doesNotMatch(page, /(?:Founder|Standard)\s+(?:29|49)\s+kr/u);
  }
});

test("filing page consumes the backend billing decision without rebuilding pilot policy", () => {
  const page = readFileSync(
    new URL("../app/(owner)/filing/[obligation]/page.tsx", import.meta.url),
    "utf8",
  );
  assert.match(page, /data\.primaryBillingEntitlements\[obligation\]/u);
  assert.doesNotMatch(page, /data\.productionPilotEntitlements/u);
});
