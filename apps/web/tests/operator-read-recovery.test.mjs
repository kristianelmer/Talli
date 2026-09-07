import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { TalliApiError } from "@talli/talli-api-client";
import { operatorReadRecovery, operatorRecoveryHref, operatorSupportLocation } from "../app/lib/operator-support.ts";

const require = createRequire(import.meta.url);
const source = path => readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");
const caseId = "10000000-0000-4000-8000-000000000009";
const cursor = "10000000-0000-4000-8000-000000000003";
const support = { operatorReadRecovery, operatorRecoveryHref, operatorSupportLocation };
const redirect = href => { throw new Error(`redirect:${href}`); };
function compile(text, dependencies = {}, globals = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(text, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { exports, require: name => name in dependencies ? dependencies[name] : require(name),
    URLSearchParams, Error, process: { env: {} }, ...globals });
  return exports;
}
const views = compile(source("(operator)/operator/annual-billing-support.tsx"), {
  "../../lib/operator-support": support,
  "../../components/billing/AnnualSupportRefundRecoveryControl": { AnnualSupportRefundRecoveryControl: () => null },
});
const ready = { recovery: null, user: { id: "operator", email: "synthetic@example.invalid" }, operator: { active: true, role: "support" } };
function entry(route, { access = ready, dashboardRecovery = null } = {}) {
  const calls = [];
  const server = {
    getOperatorPageAccess: async () => { calls.push("access"); return access; },
    readOperatorSupportDashboard: async (...args) => { calls.push(["case", ...args]); return {
      summaries: [], isOperator: true, error: dashboardRecovery ? "support_case_read_failed" : null,
      annualBilling: null, annualBillingError: null, recovery: dashboardRecovery,
    }; },
    listLaunchSignoffs: async () => { calls.push("launch"); return { launchSignoffs: [], isOperator: false, isAdminOperator: false, error: null }; },
    listAuthorityOperations: async () => { calls.push("authority"); return { operations: [], isAdminOperator: false, error: null }; },
    createSupabaseServerClient: async () => { calls.push("report-session"); return { auth: { getSession: async () => ({ data: { session: { access_token: "verified" } } }) } }; },
  };
  const dependencies = {
    "next/navigation": { redirect },
    "./annual-billing-support": views, "../annual-billing-support": views,
    "../../lib/operator-support": support, "../../../lib/operator-support": support,
    "../../lib/supabase/server": server, "../../../lib/supabase/server": server,
    "../../actions": {}, "../../lib/copy": { operatorAuthorityCopy: {} },
    "./operator-mfa": { OperatorMfa: () => null },
    "../../lib/launch-signoff": { buildLaunchSignoffGate: () => ({ blockers: [] }), launchSignoffKeys: [], launchSignoffLabel: () => "" },
    "../../lib/cancellation-operation-state": { loadPendingCancellationOperation: async () => { calls.push("pending"); return null; } },
    "../../../../features/public-acquisition/server.ts": { marketingMeasurementTransportFromEnvironment: () => ({ report: async () => {
      calls.push("report"); return { counts: {}, rates: {}, repeatedSignals: [] };
    } }) },
  };
  const Page = compile(source(`(operator)/operator/${route === "marketing" ? "marketing/" : ""}page.tsx`), dependencies).default;
  return { calls, run: async (params = { supportCase: caseId, annualBefore: cursor }) => renderToStaticMarkup(await Page({ searchParams: Promise.resolve(params) })) };
}

for (const route of ["support", "marketing"]) {
  test(`${route} entry authorizes before protected reads and preserves its recovery destination`, async () => {
    for (const recovery of ["sign-in", "step-up", "forbidden", "unavailable"]) {
      const harness = entry(route, { access: { recovery } });
      if (recovery === "unavailable") {
        assert.match(await harness.run(), /Operatørvisningen kan ikke leses/);
      } else {
        await assert.rejects(harness.run(), error => {
          const url = new URL(error.message.slice(9), "https://talli.example");
          assert.equal(url.pathname, recovery === "forbidden" ? "/dashboard" : recovery === "sign-in" ? "/login" : "/mfa");
          if (recovery !== "forbidden") {
            const next = new URL(url.searchParams.get("next"), url.origin);
            assert.equal(next.pathname, route === "marketing" ? "/operator/marketing" : "/operator");
            if (route === "support") {
              assert.equal(next.searchParams.get("supportCase"), caseId);
              assert.equal(next.searchParams.get("annualBefore"), cursor);
              assert.equal(next.hash, "#annual-billing");
            }
            assert.equal(url.searchParams.get(recovery === "sign-in" ? "reauth" : "fresh"), "1");
          }
          return true;
        });
      }
      assert.deepEqual(harness.calls, ["access"]);
    }
  });
}

test("failed case or annual read suppresses ancillary reads, mutation controls and protected evidence", async () => {
  for (const recovery of ["sign-in", "step-up", "forbidden", "unavailable"]) {
    const harness = entry("support", { dashboardRecovery: recovery });
    const html = await harness.run();
    assert.deepEqual(JSON.parse(JSON.stringify(harness.calls)), ["access", ["case", caseId, "operator", cursor, JSON.parse(JSON.stringify(operatorSupportLocation({ supportCase: caseId, annualBefore: cursor })))]]);
    assert.match(html, /Til saksvalg/);
    assert.doesNotMatch(html, /<form|Åpne sak|Launch signoff|support_case_read_failed/);
  }
});

test("malformed or duplicate case/cursor selection never triggers protected page loaders", async () => {
  for (const params of [{ supportCase: "invalid" }, { supportCase: [caseId, caseId] },
    { supportCase: caseId, annualBefore: "invalid" }, { supportCase: caseId, annualBefore: [cursor, cursor] },
    { annualBefore: cursor }]) {
    const harness = entry("support");
    assert.match(await harness.run(params), /Operatørvisningen kan ikke leses/);
    assert.deepEqual(harness.calls, ["access"]);
  }
});

test("authorized support-role entry retains ordinary support and marketing behavior", async () => {
  for (const route of ["support", "marketing"]) {
    const harness = entry(route);
    const html = await harness.run();
    assert.equal(harness.calls[0], "access");
    assert.match(html, route === "support" ? /Åpne sak/ : /Anonym traktmåling/);
    assert.ok(harness.calls.includes(route === "support" ? "launch" : "report"));
  }
});

test("presentation shell leaves scoped auth recovery to each page without mutating the session", async () => {
  const Layout = compile(source("(operator)/layout.tsx"), {
    "next/link": ({ children }) => children, "../actions": {},
    "../lib/supabase/server": { getCurrentUser: async () => null },
    "next/navigation": { redirect },
  }).default;
  const html = renderToStaticMarkup(await Layout({ children: React.createElement("p", {}, "Scoped recovery") }));
  assert.match(html, /Scoped recovery/);
});

test("page access preserves missing/rejected sessions, provider errors and both authorized operator roles", async () => {
  const serverSource = source("lib/supabase/server.ts");
  const code = serverSource.slice(serverSource.indexOf("export async function getOperatorPageAccess("), serverSource.indexOf("export async function listDocumentsForCompanies("));
  for (const options of [{ user: null }, { token: null }, { role: "support" }, { role: "admin" },
    { error: new TalliApiError(401) }, { error: new TalliApiError(403, { code: "FRESH_MFA_REQUIRED" }) },
    { error: new TalliApiError(403, { code: "OPERATOR_ACCESS_REQUIRED" }) }, { error: new Error("Private failure") }]) {
    const calls = [];
    const user = options.user === null ? null : ready.user;
    const token = options.token === null ? null : "verified";
    const read = compile(code, {}, {
      hasSupabaseEnv: () => true, getCurrentUser: async () => user,
      createSupabaseServerClient: async () => ({ auth: { getUser: async exactToken => { assert.equal(exactToken, token); return { data: { user }, error: null }; } } }), backendAccessToken: async () => token,
      loadOperatorContext: async value => { calls.push(value); if (options.error) throw options.error; return { active: true, role: options.role }; },
      operatorReadRecovery,
    }).getOperatorPageAccess;
    const result = await read();
    assert.equal(result.recovery, !user || !token ? "sign-in" : options.error ? operatorReadRecovery(options.error) : null);
    if (!user || !token) assert.deepEqual(calls, []);
    else if (!options.error) assert.equal(result.operator.role, options.role);
  }
});

const fullSelection = { supportCase: caseId, annualBefore: cursor,
  companyId: "10000000-0000-4000-8000-000000000002", refundPurchaseId: "10000000-0000-4000-8000-000000000004",
  refundRequestId: "10000000-0000-4000-8000-000000000203", beforeRefundRequestId: "10000000-0000-4000-8000-000000000202" };

test("complete operator selection survives login and MFA without losing either cursor", async () => {
  const location = operatorSupportLocation(fullSelection);
  assert.equal(location.invalid, false);
  for (const recovery of ["sign-in", "step-up"]) {
    const harness = entry("support", { access: { recovery } });
    await assert.rejects(harness.run(fullSelection), error => {
      const url = new URL(error.message.slice(9), "https://talli.example");
      const next = new URL(url.searchParams.get("next"), url.origin);
      assert.deepEqual(Object.fromEntries(next.searchParams), fullSelection);
      assert.equal(url.hash, "");
      assert.equal(next.hash, "#annual-billing");
      return true;
    });
    assert.deepEqual(harness.calls, ["access"]);
  }
});
test("malformed, duplicate and orphan operator selection cannot invoke protected loaders", async () => {
  const invalid = Object.keys(fullSelection).flatMap(key => [{ ...fullSelection, [key]: [fullSelection[key], fullSelection[key]] },
    { ...fullSelection, [key]: "malformed" }]);
  invalid.push({ ...fullSelection, supportCase: undefined }, { ...fullSelection, companyId: undefined },
    { ...fullSelection, refundPurchaseId: undefined });
  for (const params of invalid) {
    const harness = entry("support");
    assert.equal(operatorSupportLocation(params).invalid, true);
    assert.match(await harness.run(params), /Operatørvisningen kan ikke leses/);
    assert.deepEqual(harness.calls, ["access"]);
  }
});
test("late selected-target failure keeps full recovery destination and suppresses ancillary controls", async () => {
  for (const recovery of ["sign-in", "step-up", "forbidden", "unavailable"]) {
    const harness = entry("support", { dashboardRecovery: recovery });
    const html = await harness.run(fullSelection);
    assert.equal(harness.calls.length, 2);
    assert.deepEqual(JSON.parse(JSON.stringify(harness.calls[1][4])), JSON.parse(JSON.stringify(operatorSupportLocation(fullSelection))));
    assert.doesNotMatch(html, /<form|Launch signoff|Åpne sak|name="refundRequestId"/);
    const href = html.match(/href="([^"]+)"/)[1].replaceAll("&amp;", "&");
    const link = new URL(href, "https://talli.example");
    const next = new URL(link.searchParams.get("next") ?? href, link.origin);
    assert.deepEqual(Object.fromEntries(next.searchParams), fullSelection);
    assert.equal(link.hash, "");
    assert.equal(next.hash, recovery === "sign-in" || recovery === "step-up" ? "#annual-billing" : "");
  }
});
