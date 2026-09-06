import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { createTalliApiClient, TalliApiError } from "@talli/talli-api-client";

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
  } }).outputText, { exports, require, URLSearchParams, Intl, Date, Object, Error, ...dependencies });
  return exports;
}
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
function dashboard({ scopes = ["billing"], annualError = false, caseError = false } = {}) {
  const calls = [];
  const dependencies = {
    hasSupabaseEnv: () => true,
    createSupabaseServerClient: async () => ({}),
    backendOperatorSession: async () => ({ accessToken: "verified", operator: {} }),
    readOperatorSupportCase: async () => {
      if (caseError) throw new Error("private case data");
      return { caseId, companyId, scopes, resources: { companies: [] } };
    },
    buildOperatorSupportSummaries: (resources) => resources.companies,
    loadAnnualSupportPurchases: async (...args) => { calls.push(args); if (annualError) throw new Error("private provider data"); return page; },
    annualBillingRecovery: () => "unavailable",
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

test("annual access failure remains an error even when the generic support case is readable", async () => {
  const harness = dashboard({ annualError: true });
  const result = await harness.read(caseId, "actor");
  assert.equal(result.annualBilling, null);
  assert.equal(result.annualBillingError, "unavailable");
  assert.equal(result.error, null);
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
