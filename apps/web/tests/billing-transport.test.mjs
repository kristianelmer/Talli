import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

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

test("current client exposes cleanup but no retired acquisition methods", async () => {
  let captured;
  const payload = { eventId: "30000000-0000-4000-8000-000000000001", companyId,
    provider: "simulation", providerReference: "sim_cancel", idempotencyKey: "cleanup-00000001",
    kind: "subscription_cancellation", status: "canceled", amountNok: 0, incomeYear: null,
    createdBy: "20000000-0000-4000-8000-000000000001", createdAt: "2026-09-05T00:00:00Z", replayed: false };
  const api = createTalliApiClient({ baseUrl: "https://backend.example/", fetch: async (url, request) => {
    captured = { url, request }; return Response.json(payload);
  }});
  for (const name of ["billingConfigureAccount", "billingActivateSubscription", "billingPurchaseFilingPackage"]) {
    assert.equal(api[name], undefined);
  }
  await api.billingCancelSubscription({ companyId }, { idempotencyKey: payload.idempotencyKey, requestId: "cleanup" });
  assert.equal(captured.url, "https://backend.example/api/v1/billing/subscriptions/cancellation");
  assert.equal(captured.request.headers["Idempotency-Key"], payload.idempotencyKey);
  assert.equal(captured.request.headers["X-Request-ID"], "cleanup");
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

test("annual billing owns current offers and workspace exposes historical cleanup", () => {
  const pages = [
    new URL("../app/(account)/billing/page.tsx", import.meta.url),
    new URL("../app/(owner)/workspace/page.tsx", import.meta.url),
  ].map((path) => readFileSync(path, "utf8"));
  assert.match(pages[0], /loadAnnualBillingSnapshot/u);
  assert.doesNotMatch(pages[0], /loadWorkspaceData|billingPricing|primaryBillingAccount/u);
  assert.doesNotMatch(pages[1], /billingPricing|saveBillingAccount|activateBillingSubscription|requestFilingPackagePayment/u);
  assert.match(pages[1], /href=\{`\/billing\?companyId=/u);
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
    "billingCancelOperationId",
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
  assert.doesNotMatch(actions, /saveBillingAccount|activateBillingSubscription|requestFilingPackagePayment/u);
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

function annualPurchase() {
  const { renewalReminderBy, priceChangeNoticeBy, ...stored } = annualOffer();
  return { ...stored, purchaseId: "20000000-0000-4000-8000-000000000002", status: "paid",
    acceptedAt: "2026-09-05T12:00:00Z", capturedAt: "2026-09-05T12:00:00Z", capturedMinor: 149000,
    refundedMinor: 50000, recurringConsent: true, renewalCanceledAt: null };
}

function ownerSnapshotLoader(fetch, name = "loadAnnualBillingSnapshot") {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL("../features/billing/transport.ts", import.meta.url), "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText, { exports, AbortSignal, require: (id) => id === "#backend-configuration"
    ? { backendBaseUrl: () => "https://backend.example" }
    : { TalliApiError, createTalliApiClient: (options) => createTalliApiClient({ ...options, fetch }) } });
  return exports[name];
}

test("web-first owner loader falls back to predecessor history without inventing refund evidence", async () => {
  const payload = { offer: annualOffer(), purchases: [annualPurchase()], nextPurchaseId: null };
  const calls = [];
  const load = ownerSnapshotLoader(async (url, request) => {
    calls.push({ url: new URL(url), request });
    return calls.length === 1 ? Response.json({ detail: "Not Found" }, { status: 404 }) : Response.json(payload);
  });
  assert.deepEqual(await load("verified-owner", { companyId, incomeYear: 2026, beforePurchaseId: payload.purchases[0].purchaseId }), payload);
  assert.deepEqual(calls.map(({ url }) => url.pathname), ["/api/v1/billing/annual/refund-snapshot", "/api/v1/billing/annual/snapshot"]);
  for (const { url, request } of calls) {
    assert.equal(url.searchParams.get("companyId"), companyId);
    assert.equal(url.searchParams.get("beforePurchaseId"), payload.purchases[0].purchaseId);
    assert.equal(request.method, "GET");
    assert.equal(request.cache, "no-store");
    assert.equal(request.headers.Authorization, "Bearer verified-owner");
    assert.equal(request.body, undefined);
  }
});

test("new owner snapshot uses one strict expanded response for money and refund evidence", async () => {
  const row = { ...annualPurchase(), recordedRefundMinor: 149000, remainingRefundMinor: 99000,
    refundInitiateBy: "2026-09-12", refundRequestCount: 2, latestRefundRequestedAt: "2026-09-05T12:00:00Z",
    refundOperations: { created: 0, pending: 0, unknown: 1, confirmed: 1, failed: 0 } };
  const payload = { offer: annualOffer(), purchases: [row], nextPurchaseId: null };
  let calls = 0;
  const load = ownerSnapshotLoader(async () => { calls++; return Response.json(payload); });
  assert.deepEqual(await load("owner", { companyId, incomeYear: 2026 }), payload);
  assert.equal(calls, 1);
  for (const altered of [{ ...row, recordedRefundMinor: "149000" }, { ...row, refundOperations: { ...row.refundOperations, unknown: "1" } }]) {
    const invalid = ownerSnapshotLoader(async () => Response.json({ ...payload, purchases: [altered] }));
    await assert.rejects(invalid("owner", { companyId, incomeYear: 2026 }), error => error instanceof TalliApiError && error.status === 502);
  }
});

test("company-wide owner history sends no income year and keeps its cursor company-scoped", async () => {
  const row = { ...annualPurchase(), incomeYear: 2025, recordedRefundMinor: 0, remainingRefundMinor: 0,
    refundInitiateBy: null, refundRequestCount: 0, latestRefundRequestedAt: null,
    refundOperations: { created: 0, pending: 0, unknown: 0, confirmed: 0, failed: 0 } };
  const payload = { companyId, purchases: [row], nextPurchaseId: row.purchaseId };
  let captured;
  const load = ownerSnapshotLoader(async (url, request) => { captured = { url: new URL(url), request }; return Response.json(payload); }, "loadAnnualPurchaseHistory");
  assert.deepEqual(await load("owner", { companyId, beforePurchaseId: row.purchaseId }), payload);
  assert.equal(captured.url.pathname, "/api/v1/billing/annual/purchases");
  assert.equal(captured.url.searchParams.get("companyId"), companyId);
  assert.equal(captured.url.searchParams.get("beforePurchaseId"), row.purchaseId);
  assert.equal(captured.url.searchParams.has("incomeYear"), false);
  assert.equal(captured.request.method, "GET");
  assert.equal(captured.request.cache, "no-store");
  assert.equal(captured.request.body, undefined);
});

test("missing history endpoint is distinct from an application cursor or authorization error", async () => {
  const absent = ownerSnapshotLoader(async () => Response.json({ detail: "Not Found" }, { status: 404 }), "loadAnnualPurchaseHistory");
  assert.equal(await absent("owner", { companyId }), null);
  for (const status of [401, 403, 404, 503]) {
    const problem = { type: "about:blank", title: "Unavailable", status, code: status === 404 ? "BILLING_NOT_FOUND" : "BILLING_UNAVAILABLE",
      detail: "Unavailable", instance: "/api/v1/billing/annual/purchases", requestId: "history-fixture" };
    const load = ownerSnapshotLoader(async () => Response.json(problem, { status, headers: { "Content-Type": "application/problem+json" } }), "loadAnnualPurchaseHistory");
    await assert.rejects(load("owner", { companyId }), error => error instanceof TalliApiError && error.status === status);
  }
});

test("offer access rejection follows backend authentication status rather than error text", async () => {
  const { annualBillingAccessRejected } = await import("../features/billing/transport.ts");
  assert.equal(annualBillingAccessRejected(new TalliApiError(401, undefined)), true);
  assert.equal(annualBillingAccessRejected(new TalliApiError(403, undefined)), true);
  assert.equal(annualBillingAccessRejected(new TalliApiError(503, undefined)), false);
  assert.equal(annualBillingAccessRejected(new Error("Forbidden")), false);
});

for (const status of [401, 403, 503]) {
  test(`owner refund read ${status} never falls back to potentially stale purchase evidence`, async () => {
    let calls = 0;
    const load = ownerSnapshotLoader(async () => { calls++; return Response.json({}, { status }); });
    await assert.rejects(load("owner", { companyId, incomeYear: 2026 }), error => error instanceof TalliApiError && error.status === status);
    assert.equal(calls, 1);
  });
}

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


test("historical cleanup remains reachable without reactivated legacy flags", () => {
  assert.match(workspace, /action=\{cancelBillingSubscription\}/u);
  assert.match(workspace, /action=\{markBillingRefundEligible\}/u);
  assert.doesNotMatch(workspace, /subscription_active \?\s*\(/u);
  assert.doesNotMatch(workspace, /filing_package_paid &&/u);
  assert.match(workspace, /Inntektsår for tidligere betaling/u);
});

test("annual checkout and observation use POST with bounded customer data and exact retry identity", async () => {
  const requests = [];
  const purchaseId = "10000000-0000-4000-8000-000000000002";
  const payload = { purchaseId, companyId, incomeYear: 2026, status: "pending", offer: annualOffer(),
    capturedMinor: 0, refundedMinor: 0, checkoutUrl: "https://checkout.example/verified-test" };
  const api = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async (url, request) => {
    requests.push({ url, request });
    return Response.json(payload);
  }});
  const offer = annualOffer();
  const body = { companyId, incomeYear: 2026, offerVersion: offer.offerVersion, termsDigest: offer.termsDigest,
    purchaseAccepted: true, recurringConsent: false, consentVersion: offer.offerVersion };
  const options = { idempotencyKey: "annual-checkout-client-00001", accessToken: "owner-fixture", requestId: "checkout-fixture" };
  assert.deepEqual(await api.billingStartAnnualCheckout(body, options), payload);
  assert.deepEqual(await api.billingStartAnnualCheckout(body, options), payload);
  assert.deepEqual(requests[1], requests[0]);
  assert.equal(requests[0].url, "https://backend.example/api/v1/billing/annual/checkouts");
  assert.equal(requests[0].request.headers["Idempotency-Key"], options.idempotencyKey);
  assert.deepEqual(JSON.parse(requests[0].request.body), body);
  assert.deepEqual(await api.billingObserveAnnualCheckout({ companyId, purchaseId }, options), payload);
  assert.equal(requests[2].url, "https://backend.example/api/v1/billing/annual/checkout-observations");
  assert.deepEqual(JSON.parse(requests[2].request.body), { companyId, purchaseId });
  for (const { request } of requests) {
    assert.equal(request.method, "POST");
    assert.equal(request.cache, "no-store");
  }
});

test("annual checkout client rejects leaked provider state and malformed purchase totals", async () => {
  const payload = { purchaseId: "10000000-0000-4000-8000-000000000002", companyId, incomeYear: 2026,
    status: "pending", offer: annualOffer(), capturedMinor: 0, refundedMinor: 0, checkoutUrl: null };
  for (const changes of [{ providerAccount: "private" }, { capturedMinor: -1 }, { refundedMinor: 0.5 }, { status: "complete" }]) {
    const api = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async () => Response.json({ ...payload, ...changes }) });
    await assert.rejects(api.billingObserveAnnualCheckout({ companyId, purchaseId: payload.purchaseId }, {}),
      (error) => error instanceof TalliApiError && error.status === 502);
  }
});

test("annual agreement cleanup sends only purchase scope and validates unresolved outcomes", async () => {
  const body = { companyId, purchaseId: "10000000-0000-4000-8000-000000000002" };
  for (const status of ["deferred", "pending", "unknown", "confirmed"]) {
    let captured;
    const payload = { ...body, status };
    const api = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async (url, request) => {
      captured = { url, request }; return Response.json(payload);
    }});
    assert.deepEqual(await api.billingCleanupAnnualAgreement(body, { requestId: "cleanup-fixture" }), payload);
    assert.equal(captured.url, "https://backend.example/api/v1/billing/annual/agreement-cleanups");
    assert.equal(captured.request.method, "POST");
    assert.equal(captured.request.cache, "no-store");
    assert.equal(captured.request.headers["X-Request-ID"], "cleanup-fixture");
    assert.deepEqual(JSON.parse(captured.request.body), body);
  }
  for (const changes of [{ status: "stopped" }, { status: null }, { providerAccount: "private" }, { receipt: "private" }]) {
    const api = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async () =>
      Response.json({ ...body, status: "confirmed", ...changes }) });
    await assert.rejects(api.billingCleanupAnnualAgreement(body), error => error instanceof TalliApiError && error.status === 502);
  }
});

test("owner status recovery observes the original checkout with strict no-store transport", async () => {
  const body = { companyId, purchaseId: "20000000-0000-4000-8000-000000000002" };
  const payload = { ...body, incomeYear: 2026, offer: annualOffer(), status: "pending",
    capturedMinor: 10000, refundedMinor: 0, checkoutUrl: null };
  let captured;
  const observe = ownerSnapshotLoader(async (url, request) => { captured = { url, request }; return Response.json(payload); }, "observeAnnualCheckout");
  assert.deepEqual(await observe("verified-owner", body), payload);
  assert.equal(captured.url, "https://backend.example/api/v1/billing/annual/checkout-observations");
  assert.equal(captured.request.method, "POST");
  assert.equal(captured.request.cache, "no-store");
  assert.equal(captured.request.headers.Authorization, "Bearer verified-owner");
  assert.equal(captured.request.headers["Idempotency-Key"], undefined);
  assert.deepEqual(JSON.parse(captured.request.body), body);
  const malformed = ownerSnapshotLoader(async () => Response.json({ ...payload, status: "confirmed" }), "observeAnnualCheckout");
  await assert.rejects(malformed("owner", body), error => error instanceof TalliApiError && error.status === 502);
});
