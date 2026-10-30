import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import vm from "node:vm";
import test from "node:test";
import ts from "typescript";
import { createTalliApiClient, TalliApiError } from "@talli/talli-api-client";
import { createPreviewBackendFetch, BackendFetchError, BackendTransportError } from "../lib/protected-backend-fetch.ts";

const require = createRequire(import.meta.url);
const context = { companyId: "53454096-3fb6-45a6-a9c8-35fa83824614", incomeYear: 2025 };
function apiError(status, code) {
  return new TalliApiError(status, { type: "https://talli.no/problems/dependency", title: "Unavailable", status, detail: "Controlled failure", code });
}
const empty = { error: null, documents: [], setups: [], shareholders: [], locks: [], annualData: [], transactions: [], actions: [], corrections: [], positions: [], entries: [], readinessSnapshots: [], previews: [], submissions: [], overrides: [], comments: [], authorityPermissions: [] };
function compile(path, dependencies, globals = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, { exports, console: { error() {} }, Error, TypeError, AbortController, URLSearchParams, setTimeout, clearTimeout, ...globals, require(name) {
    if (name in dependencies) return dependencies[name];
    if (name === "react/jsx-runtime") return require(name);
    throw new Error(`Unexpected dependency: ${name}`);
  } });
  return exports;
}
function harness({ billing = async () => ({}), access = async () => ({ companies: [{ id: context.companyId, name: "Fixture", role: "owner", currentAgreementAccepted: true }], error: null }), token = "fixture-token", source = async () => empty, globals = {} } = {}) {
  let billingCalls = 0;
  const dependencies = {
    "@talli/talli-api-client": { TalliApiError },
    "../../lib/protected-backend-fetch.ts": { BackendFetchError, BackendTransportError },
    "react": { cache: fn => fn },
    "next/navigation.js": { notFound() { throw new Error("NOT_FOUND"); }, redirect(href) { throw new Error(`REDIRECT:${href}`); } },
    "./supabase/server.ts": Object.fromEntries(["listAnnualData", "listBankTransactions", "listDocumentsForCompanies", "listFilingReadinessSnapshots", "listLedgerEntries", "listOpeningSetups", "listPeriodLocks"].map(name => [name, async () => empty]).concat([["getCurrentUser", async () => ({ id: "owner" })]])),
    "./company-access-context.ts": { listCompanyAccessContexts: access },
    "./supabase/auth-session.ts": { getCurrentSessionAccessToken: async () => token },
    "../../features/investments": { effectiveInvestmentActivity: () => [], ...Object.fromEntries(["listPresentedInvestmentActivity", "listPresentedInvestmentCorrections", "listPresentedInvestmentPositions"].map(name => [name, async () => empty])) },
    "../../features/billing": { loadBillingEntitlement: async () => { billingCalls++; return billing(); } },
    "../../features/company-tax-filing": { loadTaxDeliveryWorkspace: async () => ({ rows: [] }) },
    "../../features/annual-accounts-filing": { loadAccountsDeliveryWorkspace: async () => ({ rows: [] }) },
    "./annual-delivery-summary.ts": { readAnnualDeliverySummary: async () => ({ state: "empty", count: 0, synthetic: false }) },
    "./annual-accounts-workspace-source.ts": { loadPresentedAnnualAccountsSource: source },
    "./company-tax-workspace-source.ts": { loadPresentedCompanyTaxSource: source },
    "./rf1086-workspace-source": { loadPresentedRf1086Source: source, newestFirst: x => x, composeFilingSources: (a, b) => [...a, ...b] },
    "./annual-workspace.ts": { buildAnnualWorkspaceViewModel: input => ({ context: input.context }) },
    "./annual-workspace-scope.ts": { scopeAnnualWorkspaceRecords: (_context, records) => records },
    "./deadlines.ts": { buildDeadlineDashboard: () => ({}) },
  };
  const module = compile("../app/lib/annual-workspace-server.ts", dependencies, globals);
  return { load: module.loadAnnualWorkspace, billingCalls: () => billingCalls };
}

test("the observed billing dependency 503 returns a scoped unavailable workspace instead of crashing the overview", async () => {
  const h = harness({ billing: async () => { throw apiError(503, "BILLING_DEPENDENCY_UNAVAILABLE"); } });
  const result = await h.load(context);
  assert.equal(result.status, "unavailable");
  assert.equal(result.context.companyId, context.companyId);
  assert.equal(result.context.incomeYear, 2025);
  assert.equal(result.model, undefined);
  assert.equal(h.billingCalls(), 1);
});

test("unavailable company verification publishes no company facts or filing status", async () => {
  const h = harness({ access: async () => ({ companies: [], error: "Company access is temporarily unavailable." }) });
  const result = await h.load(context);
  assert.equal(result.status, "unavailable");
  assert.equal(result.model, undefined);
  assert.equal(result.records, undefined);
  assert.equal(result.billingEntitlement, undefined);
  assert.equal(h.billingCalls(), 0);
});

test("missing credentials, rejected credentials, step-up and forbidden access remain distinct", async () => {
  const next = encodeURIComponent(`/companies/${context.companyId}/annual-reporting/2025`);
  await assert.rejects(harness({ token: null }).load(context), { message: `REDIRECT:/login?reauth=1&next=${next}` });
  for (const [accessResult, expected] of [
    [{ requiresSignIn: true }, `REDIRECT:/login?reauth=1&next=${next}`],
    [{ requiresAal2: true }, `REDIRECT:/mfa?fresh=1&next=${next}`],
    [{ accessDenied: true }, "NOT_FOUND"],
    [{ companies: [], error: null }, "NOT_FOUND"],
  ]) {
    const h = harness({ access: async () => ({ companies: [], error: "denied", ...accessResult }) });
    await assert.rejects(h.load(context), { message: expected });
    assert.equal(h.billingCalls(), 0);
  }
  for (const [status, code, expected] of [
    [401, "AUTHENTICATION_REQUIRED", `REDIRECT:/login?reauth=1&next=${next}`],
    [403, "BILLING_STEP_UP_REQUIRED", `REDIRECT:/mfa?fresh=1&next=${next}`],
    [403, "BILLING_FORBIDDEN", "NOT_FOUND"],
    [404, "BILLING_NOT_FOUND", "NOT_FOUND"],
  ]) {
    await assert.rejects(harness({ billing: async () => { throw apiError(status, code); } }).load(context), { message: expected });
  }
});

test("the single 12-second display deadline discards a late read and does not retry", async () => {
  let fireDeadline, deadlineMs, cleared = false, finish;
  const h = harness({ billing: () => new Promise(resolve => { finish = resolve; }), globals: {
    setTimeout(callback, ms) { fireDeadline = callback; deadlineMs = ms; return 42; },
    clearTimeout(id) { assert.equal(id, 42); cleared = true; },
  } });
  const pending = h.load(context);
  for (let i = 0; i < 10 && !finish; i++) await Promise.resolve();
  assert.equal(deadlineMs, 12_000);
  fireDeadline();
  const result = await pending;
  assert.equal(result.status, "unavailable");
  assert.equal(cleared, true);
  assert.equal(h.billingCalls(), 1);
  finish({ allowed: true });
  await Promise.resolve();
  assert.equal(result.status, "unavailable");
  assert.equal(result.billingEntitlement, undefined);
});

test("a failed required source cannot become an empty or ready workspace; healthy reload returns real facts", async () => {
  let failed = true;
  const h = harness({ source: async () => failed ? { ...empty, error: "Unavailable" } : empty });
  assert.equal((await h.load(context)).status, "unavailable");
  failed = false;
  const recovered = await h.load(context);
  assert.equal(recovered.status, "ready");
  assert.equal(recovered.model.context.companyId, context.companyId);
  assert.equal(recovered.model.context.incomeYear, 2025);
});

test("company verification that finishes after the deadline cannot start a new business-read fanout", async () => {
  let fireDeadline, finishAccess;
  const h = harness({ access: () => new Promise(resolve => { finishAccess = resolve; }), globals: {
    setTimeout(callback) { fireDeadline = callback; return 42; }, clearTimeout() {},
  } });
  const pending = h.load(context);
  for (let i = 0; i < 10 && !finishAccess; i++) await Promise.resolve();
  fireDeadline();
  assert.equal((await pending).status, "unavailable");
  finishAccess({ companies: [{ id: context.companyId, currentAgreementAccepted: true }], error: null });
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(h.billingCalls(), 0);
});

test("programming errors are not hidden as dependency failures", async () => {
  await assert.rejects(harness({ billing: async () => { throw new TypeError("incorrect property"); } }).load(context), { message: "incorrect property" });
});

test("the actual recovery view offers scoped full reload/readback links and no filing commands or status claims", () => {
  const React = require("react"), { renderToStaticMarkup } = require("react-dom/server");
  const { AnnualWorkspaceRecovery } = compile("../app/components/annual-workspace/AnnualWorkspaceRecovery.tsx", {
    "./annual-workspace.module.css": { default: {} },
  });
  const html = renderToStaticMarkup(React.createElement(AnnualWorkspaceRecovery, { context }));
  assert.match(html, /Leveringsstatus og innsendingsklarhet er ukjent/u);
  assert.match(html, new RegExp(`href="/companies/${context.companyId}/annual-reporting/2025"`, "u"));
  for (const obligation of ["aksjonaerregisteroppgaven", "skattemelding", "aarsregnskap"]) {
    assert.ok(html.includes(`href="/filing/${obligation}?companyId=${context.companyId}&amp;incomeYear=2025"`));
  }
  assert.doesNotMatch(html, /<form|<button|Klar til innsending|Ingen åpne punkter/u);
});

test("recovery has one main landmark both standalone and inside a retained annual layout", async () => {
  const React = require("react"), { renderToStaticMarkup } = require("react-dom/server");
  const { AnnualWorkspaceRecovery } = compile("../app/components/annual-workspace/AnnualWorkspaceRecovery.tsx", {
    "./annual-workspace.module.css": { default: {} },
  });
  const { AnnualWorkspaceShell } = compile("../app/components/annual-workspace/AnnualWorkspaceShell.tsx", {
    "next/link": props => React.createElement("a", props, props.children), "./annual-workspace.module.css": { default: {} },
  });
  const model = { context, company: { name: "Fixture" }, role: "owner", obligations: [{ href: `/companies/${context.companyId}/annual-reporting/2025/aarsregnskap` }] };
  for (const status of ["ready", "unavailable"]) {
    const layout = compile("../app/companies/[companyId]/annual-reporting/[incomeYear]/layout.tsx", {
      "../../../../components/annual-workspace/AnnualWorkspaceRecovery": { AnnualWorkspaceRecovery },
      "../../../../components/annual-workspace/AnnualWorkspaceShell": { AnnualWorkspaceShell },
      "../../../../lib/annual-workspace-server": { loadAnnualWorkspace: async () => ({ status, context, model }) },
    }).default;
    const html = renderToStaticMarkup(await layout({ params: Promise.resolve({ companyId: context.companyId, incomeYear: "2025" }), children: React.createElement(AnnualWorkspaceRecovery, { context }) }));
    assert.equal([...html.matchAll(/<main\b/gu)].length, 1, status);
  }
});

test("actual billing transport and generated client preserve timeout, 503, 401 and 403 distinctions without retries", async () => {
  for (const failure of ["timeout", 503, 401, 403]) {
    let calls = 0;
    const transport = compile("../features/billing/transport.ts", {
      "@talli/talli-api-client": { createTalliApiClient, TalliApiError },
      "#backend-configuration": { backendClientOptions: () => ({ baseUrl: "https://backend.example", fetch: createPreviewBackendFetch({ backendOrigin: "https://backend.example", tokenProvider: async () => "a.b.c", fetchImplementation: async (url, options) => {
        calls++;
        assert.equal(options.method, "GET");
        assert.ok(String(url).startsWith("https://backend.example/api/v1/billing/entitlement?"));
        assert.equal(new Headers(options.headers).get("Authorization"), "Bearer fixture-token");
        if (failure === "timeout") throw Object.assign(new Error("Controlled Auth read timeout"), { name: "TimeoutError" });
        return Response.json(apiError(failure, failure === 503 ? "BILLING_DEPENDENCY_UNAVAILABLE" : "BILLING_ACCESS_REJECTED").problem, { status: failure });
      } }) }) },
    }, { AbortSignal });
    const h = harness({ billing: () => transport.loadBillingEntitlement("fixture-token", { ...context, obligation: "aksjonaerregisteroppgaven", caseProfile: "rf1086_no_activity_v1" }) });
    if (failure === "timeout" || failure === 503) assert.equal((await h.load(context)).status, "unavailable");
    else await assert.rejects(h.load(context), failure === 401 ? /REDIRECT:\/login/u : /NOT_FOUND/u);
    assert.equal(calls, 1);
  }
});
