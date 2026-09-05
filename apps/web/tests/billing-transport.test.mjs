import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { createTalliApiClient, TalliApiError } from "@talli/talli-api-client";

const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const workspace = readFileSync(
  new URL("../app/(owner)/workspace/page.tsx", import.meta.url),
  "utf8",
);

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
  assert.match(pages[0], /loadAnnualBillingSnapshot/u);
  assert.doesNotMatch(pages[0], /loadWorkspaceData|billingPricing|primaryBillingAccount/u);
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

test("ambiguous billing outcomes retain the exact operation key for replay", () => {
  assert.match(actions, /billingOutcomeMayBeUnknown/);
  for (const retryKey of [
    "billingConfigureOperationId",
    "billingActivateOperationId",
    "billingCancelOperationId",
    "billingFilingPackageOperationId",
    "billingUnsupportedOperationId",
    "billingRefundOperationId",
  ]) {
    assert.match(actions, new RegExp(`billingRetryRedirect\\(error, operationId, "${retryKey}"\\)`));
    assert.match(workspace, new RegExp(`params\\?\\.${retryKey} \\?\\? randomUUID\\(\\)`));
  }
});

test("billing retry redirects and Norwegian plan labels have one shared policy", () => {
  assert.match(actions, /function billingRetryRedirect\(/u);
  assert.equal((actions.match(/billingOutcomeMayBeUnknown\(/gu) ?? []).length, 1);
  assert.match(actions, /account\.pricingPlan === "founder" \? "grunnleggerplan" : "standardplan"/u);
  assert.doesNotMatch(actions, /\$\{account\.pricingPlan\}-prising/u);
});

function annualOffer() {
  return { companyId, incomeYear: 2026, offerVersion: "annual-fixture", termsDigest: "a".repeat(64),
    termsText: "Stored fixture terms", currency: "NOK", grossMinor: 149000, netMinor: 119200,
    vatMinor: 29800, vatBasisPoints: 2500, paidThrough: "2027-07-31", exportThrough: "2027-10-31",
    renewalDate: "2027-01-01", renewalReminderBy: "2026-12-01", priceChangeNoticeBy: "2026-11-01" };
}

test("annual snapshot uses a scoped cursor and rejects malformed stored facts", async () => {
  let captured;
  const payload = { offer: annualOffer(), purchases: [], nextPurchaseId: null };
  const api = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async (url, request) => {
    captured = {url: new URL(url), request};
    return Response.json(payload);
  }});
  const request = { companyId, incomeYear: 2026, beforePurchaseId: "10000000-0000-4000-8000-000000000002" };
  assert.deepEqual(await api.billingReadAnnualSnapshot(request), payload);
  assert.equal(captured.url.pathname, "/api/v1/billing/annual/snapshot");
  assert.equal(captured.url.searchParams.get("beforePurchaseId"), request.beforePurchaseId);
  assert.equal(captured.request.cache, "no-store");
  const malformed = createTalliApiClient({baseUrl: "https://backend.example", fetch: async () =>
    Response.json({...payload,offer:{...payload.offer,grossMinor:"149000"}})});
  await assert.rejects(malformed.billingReadAnnualSnapshot(request), error => error instanceof TalliApiError && error.status===502);
});

test("annual cancellation sends only company/purchase intent and preserves its durable key", async () => {
  let captured;
  const body = { companyId, purchaseId: "10000000-0000-4000-8000-000000000002" };
  const receipt = { ...body, cancellationId: "10000000-0000-4000-8000-000000000003", incomeYear: 2026,
    requestedAt: "2026-09-05T12:00:00Z", effectiveAt: "2026-09-05T12:00:00Z",
    paidThrough: "2027-07-31", exportThrough: "2027-10-31" };
  const api = createTalliApiClient({baseUrl: "https://backend.example", fetch: async (url,request) => {
    captured = {url,request}; return Response.json(receipt);
  }});
  const result = await api.billingCancelAnnualRenewal(body,{idempotencyKey:"annual-cancellation-00001",requestId:"annual-cancel"});
  assert.deepEqual(result,receipt);
  assert.equal(captured.url,"https://backend.example/api/v1/billing/annual/renewal-cancellations");
  assert.deepEqual(JSON.parse(captured.request.body),body);
  assert.equal(captured.request.headers["Idempotency-Key"],"annual-cancellation-00001");
  assert.equal(captured.request.headers["X-Request-ID"],"annual-cancel");
});

test("annual client rejects private provider fields and invalid money in responses", async () => {
  for (const offer of [{...annualOffer(),providerAccount:"private"},{...annualOffer(),grossMinor:-1},{...annualOffer(),grossMinor:149000.5}]) {
    const api = createTalliApiClient({baseUrl:"https://backend.example",fetch:async()=>Response.json({offer,purchases:[],nextPurchaseId:null})});
    await assert.rejects(api.billingReadAnnualSnapshot({companyId,incomeYear:2026}),error=>error instanceof TalliApiError && error.status===502);
  }
});

test("annual recovery trusts a valid step-up problem and treats malformed failures as unavailable", async () => {
  const { annualBillingRecovery } = await import("../features/billing/transport.ts");
  const problem = { type: "about:blank", title: "Forbidden", status: 403, code: "BILLING_STEP_UP_REQUIRED",
    detail: "Fresh MFA required", instance: "/api/v1/billing/annual/snapshot", requestId: "recovery-fixture" };
  for (const [payload, expected] of [[problem, "step-up"], [{ ...problem, privateField: true }, "unavailable"]]) {
    const api = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async () =>
      Response.json(payload, { status: 403, headers: { "Content-Type": "application/problem+json" } }) });
    await assert.rejects(api.billingReadAnnualSnapshot({ companyId, incomeYear: 2026 }),
      (error) => annualBillingRecovery(error) === expected);
  }
  assert.equal(annualBillingRecovery(new TalliApiError(401, undefined)), "sign-in");
  assert.equal(annualBillingRecovery(new Error("timeout")), "unavailable");
});
