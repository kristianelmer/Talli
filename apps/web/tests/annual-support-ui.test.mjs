import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { createTalliApiClient, TalliApiError } from "@talli/talli-api-client";
import { operatorReadRecovery, operatorRecoveryHref, operatorSupportLocation } from "../app/lib/operator-support.ts";

const require = createRequire(import.meta.url);
const companyId = "10000000-0000-4000-8000-000000000001";
const purchaseId = "20000000-0000-4000-8000-000000000001";
const caseId = "30000000-0000-4000-8000-000000000001";
const recorded = {
  companyId, purchaseId, incomeYear: 2026, status: "paid", acceptedAt: "2026-09-05T11:00:00Z",
  updatedAt: "2026-09-05T12:00:00Z", currency: "NOK", grossMinor: 149000, capturedMinor: 149000,
  refundedMinor: 50000, renewalCanceledAt: "2026-09-05T12:00:00Z", paidThrough: "2027-07-31",
  exportThrough: "2027-10-31", recurringConsent: true, refundCaseCount: 2, recordedRefundMinor: 149000, remainingRefundMinor: 99000,
  refundInitiateBy: "2026-09-19", refundRequestCount: 2, latestRefundRequestedAt: "2026-09-05T12:00:00Z",
  refundOperations: { created: 0, pending: 0, unknown: 1, confirmed: 1, failed: 1 }, cleanupStatus: "unknown",
};
const page = { companyId, supportCaseId: caseId, purchases: [recorded], nextPurchaseId: purchaseId };
function compile(source, dependencies = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { exports, require: id => id === "../../lib/operator-support"
    ? { operatorReadRecovery, operatorRecoveryHref, operatorSupportLocation }
    : id === "../../components/billing/AnnualSupportRefundRecoveryControl" ? { AnnualSupportRefundRecoveryControl }
    : id === "../ui" ? {
      Banner: ({ children }) => React.createElement("div", {}, children),
      Button: ({ variant, ...props }) => React.createElement("button", props),
      LinkButton: props => React.createElement("a", props),
    } : require(id),
    URLSearchParams, Intl, Date, Object, Error, ...dependencies });
  return exports;
}
const { AnnualSupportRefundRecoveryControl } = compile(readFileSync(new URL("../app/components/billing/AnnualSupportRefundRecoveryControl.tsx", import.meta.url), "utf8"));
const { AnnualBillingSupport } = compile(readFileSync(new URL("../app/(operator)/operator/annual-billing-support.tsx", import.meta.url), "utf8"));
function render(extra = {}) {
  return renderToStaticMarkup(React.createElement(AnnualBillingSupport, { page, supportCaseId: caseId, error: null, ...extra }));
}

test("support view preserves outstanding money, deadline, failed and unknown effects after a partial refund", () => {
  const html = render();
  assert.match(html, /990,00/);
  assert.match(html, /19\. september 2026/);
  assert.match(html, /1 ukjent utfall, 1 bekreftet, 1 mislyktes/);
  assert.match(html, /Stopp hos betalingsleverandør: <strong>ukjent utfall/);
  assert.match(html, /Fornyelse i Talli: stoppet/);
  assert.doesNotMatch(html, /<button|<form|Stopp fornyelse|Refunder nå/);
  assert.match(html, new RegExp(`supportCase=${caseId}&amp;annualBefore=${purchaseId}`));
});

test("support view distinguishes absent refund and stop evidence from confirmation", () => {
  const html = render({ page: { ...page, purchases: [{ ...recorded, refundCaseCount: 0, cleanupStatus: null,
    refundOperations: { created: 0, pending: 0, unknown: 0, confirmed: 0, failed: 0 } }] } });
  assert.match(html, /Ingen refusjon registrert/);
  assert.match(html, /Ingen operasjon registrert/);
  assert.doesNotMatch(html, /Ingen rett til refusjon|Ingen refusjon nødvendig|refusjon fullført/);
});

test("empty and denied support states remain distinct and errors hide previous data", () => {
  assert.match(render({ page: { ...page, purchases: [] } }), /Ingen årskjøp registrert/);
  const html = render({ error: "step-up" });
  assert.match(html, /role="alert"/);
  assert.match(html, /Bekreft MFA/);
  assert.doesNotMatch(html, /990,00|Ingen årskjøp registrert/);
  assert.equal(render({ page: null }), "");
});

const server = readFileSync(new URL("../app/lib/supabase/server.ts", import.meta.url), "utf8");
const dashboardSource = server.slice(server.indexOf("export async function readOperatorSupportDashboard("));
function dashboard({ scopes = ["billing"], annualError = false, caseError = false,
  operatorError = false, token = "verified", returnedActor = "actor", userError = null, returnedCase = caseId, returnedPage = page, companies = [], targetError = null, returnedTargets = null } = {}) {
  const calls = [];
  const dependencies = {
    hasSupabaseEnv: () => true,
    createSupabaseServerClient: async () => ({ auth: { getUser: async exactToken => { assert.equal(exactToken, token); return { data: { user: returnedActor ? { id: returnedActor } : null }, error: userError }; } } }),
    backendAccessToken: async () => token,
    loadOperatorContext: async () => { if (operatorError) throw operatorError; return { active: true, role: "admin" }; },
    readOperatorSupportCase: async () => {
      if (caseError) throw caseError instanceof Error ? caseError : new Error("private case data");
      return { caseId: returnedCase, companyId, scopes, resources: { companies } };
    },
    buildOperatorSupportSummaries: (resources) => resources.companies,
    loadAnnualSupportPurchases: async (...args) => { calls.push(args); if (annualError) throw annualError instanceof Error ? annualError : new Error("private provider data"); return returnedPage; },
    loadAnnualSupportRefundRecoveryTargets: async (...args) => { calls.push(["targets", ...args]); if (targetError) throw targetError; return returnedTargets; },
    annualBillingRecovery: () => "unavailable",
    operatorReadRecovery,
  };
  return { calls, read: compile(dashboardSource, dependencies).readOperatorSupportDashboard };
}

test("billing-only support case loads annual evidence without company-profile rows and retains its cursor", async () => {
  const harness = dashboard();
  const result = await harness.read(caseId, "actor", purchaseId);
  assert.equal(result.summaries.length, 0);
  assert.equal(result.annualBilling, page);
  assert.equal(harness.calls[0][0], "verified");
  assert.deepEqual(JSON.parse(JSON.stringify(harness.calls[0][1])), { companyId, supportCaseId: caseId, beforePurchaseId: purchaseId });
});

test("profile-only or unreadable cases cannot trigger annual billing reads", async () => {
  for (const options of [{ scopes: ["profile"] }, { caseError: true }]) {
    const harness = dashboard(options);
    const result = await harness.read(caseId, "actor");
    assert.equal(harness.calls.length, 0);
    assert.equal(result.annualBilling, null);
  }
});

test("early fresh MFA rejection remains recoverable before the annual support read", async () => {
  const harness = dashboard({ caseError: new TalliApiError(403, {
    code: "FRESH_MFA_REQUIRED", title: "Fresh MFA required", status: 403,
  }) });
  const result = await harness.read(caseId, "actor", purchaseId);
  assert.equal(result.recovery, "step-up");
  assert.equal(result.summaries.length, 0);
  assert.equal(result.annualBilling, null);
  assert.equal(harness.calls.length, 0);
});

test("annual access failure remains an error even when the generic support case is readable", async () => {
  const harness = dashboard({ annualError: true });
  const result = await harness.read(caseId, "actor");
  assert.equal(result.annualBilling, null);
  assert.equal(result.annualBillingError, "unavailable");
  assert.equal(result.error, "support_case_read_failed");
  assert.equal(result.summaries.length, 0);
  assert.equal(result.recovery, "unavailable");
});

for (const [status, code, recovery] of [[401, "AUTH_REQUIRED", "sign-in"],
  [403, "FRESH_MFA_REQUIRED", "step-up"], [403, "BILLING_STEP_UP_REQUIRED", "step-up"],
  [403, "AAL2_REQUIRED", "step-up"], [403, "SUPPORT_ACCESS_DENIED", "forbidden"],
  [404, "COMPANY_ACCESS_NOT_FOUND", "unavailable"], [503, "FRESH_MFA_REQUIRED", "unavailable"]]) {
  test(`operator read ${status}/${code} retains recovery and hides all earlier case evidence`, async () => {
    const failure = new TalliApiError(status, { status, code, title: "Private details" });
    for (const options of [{ operatorError: failure }, { caseError: failure }, { annualError: failure }]) {
      const harness = dashboard({ ...options, companies: [{ id: companyId, name: "Private company" }] });
      const result = await harness.read(caseId, "actor", purchaseId);
      assert.equal(result.recovery, recovery);
      assert.equal(result.summaries.length, 0);
      assert.equal(result.annualBilling, null);
      assert.ok(result.error);
    }
    const html = render({ error: recovery === "forbidden" ? "unavailable" : recovery, beforePurchaseId: purchaseId });
    const raw = html.match(/href="([^"]+)"/)[1].replaceAll("&amp;", "&");
    const link = new URL(raw, "https://talli.example");
    const next = new URL(link.searchParams.get("next") ?? link.href, link.origin);
    assert.equal(next.pathname, "/operator");
    assert.equal(next.searchParams.get("supportCase"), caseId);
    assert.equal(next.searchParams.get("annualBefore"), purchaseId);
    assert.equal(next.hash, "#annual-billing");
    if (recovery === "sign-in") assert.equal(link.searchParams.get("reauth"), "1");
    if (recovery === "step-up") assert.equal(link.searchParams.get("fresh"), "1");
    assert.doesNotMatch(html, /990,00|Private details|Ingen årskjøp/);
  });
}

test("returned case/company bindings and missing session fail before protected evidence is presented", async () => {
  for (const options of [{ returnedCase: purchaseId }, { returnedPage: { ...page, companyId: purchaseId } },
    { returnedPage: { ...page, supportCaseId: purchaseId } }, { token: null }]) {
    const harness = dashboard(options);
    const result = await harness.read(caseId, "actor", purchaseId);
    assert.equal(result.recovery, options.token === null ? "sign-in" : "unavailable");
    assert.equal(result.summaries.length, 0);
    assert.equal(result.annualBilling, null);
  }
});

test("generated annual support transport carries company/case/cursor without caching or mutation", async () => {
  let captured;
  const api = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async (url, request) => {
    captured = { url, request }; return Response.json(page);
  }});
  assert.deepEqual(await api.billingReadAnnualSupportPurchases({ companyId, supportCaseId: caseId, beforePurchaseId: purchaseId }), page);
  assert.match(captured.url, new RegExp(`companyId=${companyId}&supportCaseId=${caseId}&beforePurchaseId=${purchaseId}`));
  assert.equal(captured.request.method, "GET");
  assert.equal(captured.request.cache, "no-store");
  assert.equal(captured.request.body, undefined);
  const broken = createTalliApiClient({ baseUrl: "https://backend.example", fetch: async () => Response.json({
    ...page, purchases: [{ ...recorded, cleanupStatus: "safe_to_stop" }],
  }) });
  await assert.rejects(broken.billingReadAnnualSupportPurchases({ companyId, supportCaseId: caseId }),
    (error) => error instanceof TalliApiError && error.status === 502);
});

const requestId = "40000000-0000-4000-8000-000000000001";
const refundCursor = "50000000-0000-4000-8000-000000000001";
const operatorId = "60000000-0000-4000-8000-000000000001";
const targets = { companyId, supportCaseId: caseId, purchaseId, incomeYear: 2026,
  targets: [{ refundRequestId: requestId, requestedAt: "2026-09-05T12:00:00Z", status: "unknown" }], nextRefundRequestId: requestId };
const selection = { companyId, purchaseId, refundRequestId: requestId, beforeRefundRequestId: refundCursor };

test("operator target read uses exact page actor and selected authorized purchase before publishing evidence", async () => {
  const harness = dashboard({ returnedTargets: targets, companies: [{ id: companyId, name: "Private company" }] });
  const result = await harness.read(caseId, "actor", purchaseId, selection);
  assert.equal(result.recovery, null); assert.equal(result.annualBilling, page);
  assert.equal(result.summaries.length, 1);
  assert.equal(result.annualRefundTargets.page, targets);
  assert.equal(result.annualRefundTargets.selectedRefundRequestId, requestId);
  assert.deepEqual(JSON.parse(JSON.stringify(harness.calls[1])), ["targets", "verified", {
    companyId, supportCaseId: caseId, purchaseId, beforeRefundRequestId: refundCursor,
  }]);
});
test("changed or unverifiable operator clears evidence before protected data reads", async () => {
  for (const options of [{ returnedActor: "other" }, { returnedActor: null }, { userError: new Error("private") }]) {
    const harness = dashboard(options);
    const result = await harness.read(caseId, "actor", purchaseId, selection);
    assert.equal(result.recovery, options.returnedActor === "other" ? "forbidden" : "sign-in");
    assert.equal(result.annualBilling, null); assert.equal(result.annualRefundTargets, null);
    assert.equal(result.summaries.length, 0); assert.deepEqual(harness.calls, []);
  }
});
test("selected company is an assertion against the opened case and never a replacement company", async () => {
  const harness = dashboard();
  const result = await harness.read(caseId, "actor", purchaseId, { ...selection, companyId: operatorId });
  assert.equal(result.recovery, "unavailable"); assert.equal(result.annualBilling, null);
  assert.equal(result.annualRefundTargets, null); assert.equal(harness.calls.length, 0);
});
test("a missing selected purchase stays explicit and cannot load a substitute target", async () => {
  const harness = dashboard();
  const result = await harness.read(caseId, "actor", purchaseId, { ...selection, purchaseId: operatorId });
  assert.equal(result.recovery, null); assert.equal(result.annualRefundTargets.purchaseId, operatorId);
  assert.equal(result.annualRefundTargets.page, null); assert.equal(harness.calls.length, 1);
  const html = render({ refundTargets: result.annualRefundTargets });
  assert.match(html, /Det valgte kjøpet vises ikke/); assert.doesNotMatch(html, /name="refundRequestId"/);
});
test("selected refund destination under a nonbilling case is a denial, not empty success", async () => {
  const harness = dashboard({ scopes: ["profile"], companies: [{ name: "Private company" }] });
  const result = await harness.read(caseId, "actor", purchaseId, selection);
  assert.equal(result.recovery, "forbidden"); assert.equal(result.annualBilling, null);
  assert.equal(result.annualRefundTargets, null); assert.equal(result.summaries.length, 0); assert.equal(harness.calls.length, 0);
});
for (const [status, code, recovery] of [[401, "AUTHENTICATION_REQUIRED", "sign-in"],
  [403, "BILLING_STEP_UP_REQUIRED", "step-up"], [403, "BILLING_FORBIDDEN", "forbidden"],
  [404, undefined, "unavailable"], [404, "BILLING_NOT_FOUND", "unavailable"], [503, "BILLING_UNAVAILABLE", "unavailable"]]) {
  test(`late targets ${status}/${code} remove earlier summaries, purchase money and controls`, async () => {
    const harness = dashboard({ companies: [{ name: "Private company" }],
      targetError: new TalliApiError(status, code ? { status, code } : undefined) });
    const result = await harness.read(caseId, "actor", purchaseId, selection);
    assert.equal(harness.calls.length, 2); assert.equal(result.recovery, recovery);
    assert.equal(result.annualBilling, null); assert.equal(result.annualRefundTargets, null);
    assert.equal(result.summaries.length, 0);
  });
}
for (const field of ["companyId", "supportCaseId", "purchaseId", "incomeYear"]) {
  test(`foreign target ${field} cannot publish earlier case evidence`, async () => {
    const harness = dashboard({ companies: [{ name: "Private company" }],
      returnedTargets: { ...targets, [field]: field === "incomeYear" ? 2025 : operatorId } });
    const result = await harness.read(caseId, "actor", purchaseId, selection);
    assert.equal(result.recovery, "unavailable"); assert.equal(result.annualBilling, null);
    assert.equal(result.annualRefundTargets, null); assert.equal(result.summaries.length, 0);
  });
}
test("target view retains all request bindings, both cursors and canonical outstanding balance", () => {
  const html = render({ initiatingUserId: operatorId, recoverAction: async () => { throw new Error("render must not post"); },
    beforePurchaseId: purchaseId, refundTargets: { purchaseId, selectedRefundRequestId: requestId, beforeRefundRequestId: refundCursor, page: targets } });
  assert.match(html, /990,00/); assert.match(html, /Oppretter ingen ny refusjon/);
  for (const [name, value] of Object.entries({ initiatingUserId: operatorId, supportCaseId: caseId, companyId, purchaseId,
    refundRequestId: requestId, beforePurchaseId: purchaseId, beforeRefundRequestId: refundCursor })) {
    assert.match(html, new RegExp(`name="${name}" value="${value}"`));
  }
  const newest = [...html.matchAll(/href="([^"]+)"[^>]*>Nyeste forespørsler/g)][0][1].replaceAll("&amp;", "&");
  const next = new URL(newest, "https://talli.example");
  assert.equal(next.searchParams.get("annualBefore"), purchaseId);
  assert.equal(next.searchParams.get("refundPurchaseId"), purchaseId);
  assert.equal(next.searchParams.get("beforeRefundRequestId"), null);
  assert.equal(next.searchParams.get("refundRequestId"), null);
});
test("missing selected receipt is announced without silently using a replacement receipt", () => {
  const html = render({ initiatingUserId: operatorId, recoverAction: async () => { throw new Error("render must not post"); },
    refundTargets: { purchaseId, selectedRefundRequestId: refundCursor, page: targets } });
  assert.match(html, /Den valgte forespørselen vises ikke/);
  assert.doesNotMatch(html, new RegExp(`name="refundRequestId" value="${refundCursor}"`));
  assert.match(html, new RegExp(`name="refundRequestId" value="${requestId}"`));
});
