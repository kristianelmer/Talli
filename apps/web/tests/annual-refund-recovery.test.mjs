import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";

const require = createRequire(import.meta.url);
const companyId = "10000000-0000-4000-8000-000000000001";
const purchaseId = "20000000-0000-4000-8000-000000000001";
const refundRequestId = "30000000-0000-4000-8000-000000000001";
const cursor = "40000000-0000-4000-8000-000000000001";
const refundCursor = "50000000-0000-4000-8000-000000000001";
function compile(source, dependencies = {}, globals = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { exports, require: id => id in dependencies ? dependencies[id] : require(id), URL, URLSearchParams, Error, ...globals });
  return exports;
}
const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const actionSource = actions.slice(actions.indexOf("export async function recoverAnnualRefund("), actions.indexOf("export async function observeAnnualCheckout("));
function action({ token = "owner", status = "pending", failure, foreign, refreshFailure = false } = {}) {
  const calls = [], refreshes = [];
  return { calls, refreshes, run: compile(actionSource, {}, {
    formString: (data, key) => data.get(key) ?? "",
    requiredFormUuid: (data, key) => {
      const value = data.get(key);
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value ?? "")) throw new Error("invalid");
      return value;
    },
    ownerPathWithQuery: (path, values) => `${path}?${new URLSearchParams(Object.entries(values).filter(([, value]) => value !== undefined))}`,
    getCurrentSessionAccessToken: async () => token,
    recoverAnnualRefundThroughApi: async (...args) => {
      calls.push(args);
      if (failure) throw new Error("private provider detail");
      return { companyId, purchaseId, refundRequestId, status, ...(foreign ? { [foreign]: cursor } : {}),
        refundedMinor: 999, providerAccount: "private" };
    },
    annualBillingRecovery: () => failure ?? "unavailable",
    annualBillingAccessRejected: () => ["step-up", "sign-in", "forbidden"].includes(failure),
    revalidatePath: path => { refreshes.push(path); if (refreshFailure) throw new Error("failed refresh"); },
  }).recoverAnnualRefund };
}
function form(changes = {}) {
  const data = new FormData();
  for (const [key, value] of Object.entries({ companyId, purchaseId, refundRequestId,
    beforePurchaseId: cursor, beforeRefundRequestId: refundCursor, ...changes })) if (value !== undefined) data.set(key, value);
  return data;
}

for (const status of ["pending", "unknown", "confirmed", "failed"]) {
  test(`${status} recovery refreshes canonical money while returning only exact-operation feedback`, async () => {
    const harness = action({ status });
    const result = await harness.run({ kind: "observed", companyId: cursor, status: "confirmed" },
      form({ actorId: cursor, operationId: cursor, sourceReference: "forged", amountMinor: "149000", status: "confirmed" }));
    assert.deepEqual(JSON.parse(JSON.stringify(result)), { kind: "observed", companyId, purchaseId, refundRequestId, status });
    assert.deepEqual(JSON.parse(JSON.stringify(harness.calls)), [["owner", { companyId, purchaseId, refundRequestId }]]);
    assert.deepEqual(harness.refreshes, ["/billing"]);
  });
}
for (const failure of ["step-up", "sign-in", "unavailable"]) {
  test(`${failure} retains original receipt and both cursors for explicit retry`, async () => {
    const harness = action({ failure });
    const result = await harness.run({ kind: "idle" }, form());
    assert.equal(result.kind, "recovery");
    assert.equal(result.refundRequestId, refundRequestId);
    assert.doesNotMatch(JSON.stringify(result), /private provider detail|refundedMinor/);
    assert.deepEqual(harness.refreshes, failure === "unavailable" ? [] : ["/billing"]);
    if (failure === "unavailable") assert.equal(result.href, null);
    else {
      const login = new URL(result.href, "https://talli.example");
      if (failure === "step-up") assert.equal(login.searchParams.get("fresh"), "1");
      const next = new URL(login.searchParams.get("next"), login.origin);
      assert.equal(next.searchParams.get("companyId"), companyId);
      assert.equal(next.searchParams.get("refundPurchaseId"), purchaseId);
      assert.equal(next.searchParams.get("refundRequestId"), refundRequestId);
      assert.equal(next.searchParams.get("beforePurchaseId"), cursor);
      assert.equal(next.searchParams.get("beforeRefundRequestId"), refundCursor);
    }
  });
}

const mfaPageSource = readFileSync(new URL("../app/mfa/page.tsx", import.meta.url), "utf8");
function mfaPage({ user = { email_confirmed_at: "2026-09-06" }, configured = true } = {}) {
  return compile(mfaPageSource, {
    "next/navigation": { redirect: href => { throw new Error(`redirect:${href}`); } },
    "../lib/internal-redirect": compile(readFileSync(new URL("../app/lib/internal-redirect.ts", import.meta.url), "utf8")),
    "../lib/supabase/server": { getCurrentUser: async () => user,
      hasSupabaseEnv: () => configured, needsEmailVerification: () => false },
    "./OwnerMfa": { OwnerMfa: () => null },
  }, { process: { env: { SUPABASE_URL: "http://127.0.0.1:1", SUPABASE_ANON_KEY: "synthetic" } } }).default;
}
test("billing rejection reaches the real MFA inspection through its page and client with exact receipt context", async () => {
  const rejected = action({ failure: "step-up" });
  const result = await rejected.run({ kind: "idle" }, form());
  const location = new URL(result.href, "https://talli.example");
  const page = await mfaPage()({ searchParams: Promise.resolve(Object.fromEntries(location.searchParams)) });
  const props = page.props.children.props;
  assert.equal(props.requireFreshChallenge, true);
  assert.equal(props.returnTo, location.searchParams.get("next"));
  let inspection;
  const navigations = [];
  const mfa = {
    getAuthenticatorAssuranceLevel: async () => ({ data: { currentLevel: "aal2", nextLevel: "aal2",
      currentAuthenticationMethods: [{ method: "totp", timestamp: 1 }] }, error: null }),
    listFactors: async () => ({ data: { totp: [{ id: "existing-factor" }] }, error: null }),
  };
  const ownerMfa = compile(readFileSync(new URL("../app/lib/owner-mfa.ts", import.meta.url), "utf8"));
  const client = compile(readFileSync(new URL("../app/mfa/OwnerMfa.tsx", import.meta.url), "utf8"), {
    react: { ...React, useMemo: fn => fn(), useState: initial => [initial, () => {}],
      useRef: () => ({ current: null }), useEffect: effect => { effect(); } },
    "@supabase/ssr": { createBrowserClient: () => ({ auth: { mfa } }) },
    "../lib/owner-mfa": { ...ownerMfa, inspectOwnerMfa: (...args) => {
      inspection = ownerMfa.inspectOwnerMfa(...args); return inspection;
    } },
  }, { window: { location: { assign: href => navigations.push(href) } } }).OwnerMfa;
  client(props);
  assert.deepEqual(JSON.parse(JSON.stringify(await inspection)), { kind: "challenge", factorId: "existing-factor" });
  assert.deepEqual(navigations, []);
  assert.equal(rejected.calls.length, 1);
});

test("missing MFA session preserves fresh intent and the entire nested billing return through login", async () => {
  const result = await action({ failure: "step-up" }).run({ kind: "idle" }, form());
  const original = new URL(result.href, "https://talli.example");
  for (const options of [{ user: null }, { configured: false }]) {
    await assert.rejects(mfaPage(options)({ searchParams: Promise.resolve(Object.fromEntries(original.searchParams)) }), error => {
      assert.match(error.message, /^redirect:/);
      const login = new URL(error.message.slice("redirect:".length), original.origin);
      assert.equal(login.pathname, "/login");
      const resume = new URL(login.searchParams.get("next"), original.origin);
      assert.equal(resume.searchParams.get("fresh"), "1");
      assert.equal(resume.searchParams.get("next"), original.searchParams.get("next"));
      return true;
    });
  }
  for (const fresh of [undefined, "0", "true", ["1", "1"]]) {
    const page = await mfaPage()({ searchParams: Promise.resolve({ fresh, next: "https://outside.example" }) });
    assert.equal(page.props.children.props.requireFreshChallenge, false);
    assert.equal(page.props.children.props.returnTo, "/onboarding");
  }
});
test("malformed scope cannot call backend and missing session refreshes protected history", async () => {
  for (const key of ["companyId", "purchaseId", "refundRequestId", "beforePurchaseId", "beforeRefundRequestId"]) {
    const harness = action();
    assert.equal((await harness.run({ kind: "idle" }, form({ [key]: "invalid" }))).kind, "invalid");
    assert.deepEqual(harness.calls, []);
  }
  const harness = action({ token: null });
  assert.equal((await harness.run({ kind: "idle" }, form())).reason, "sign-in");
  assert.deepEqual(harness.calls, []);
  assert.deepEqual(harness.refreshes, ["/billing"]);
});
test("foreign response and failed history refresh never announce confirmation", async () => {
  for (const foreign of ["companyId", "purchaseId", "refundRequestId"]) {
    const harness = action({ foreign, status: "confirmed" });
    assert.equal((await harness.run({ kind: "idle" }, form())).reason, "unavailable");
    assert.deepEqual(harness.refreshes, []);
  }
  assert.equal((await action({ refreshFailure: true, status: "confirmed" }).run({ kind: "idle" }, form())).reason, "unavailable");
});
test("repeated explicit checks send the same receipt without a new operation key", async () => {
  const harness = action();
  await harness.run(await harness.run({ kind: "idle" }, form()), form());
  assert.deepEqual(harness.calls[0], harness.calls[1]);
});

const ui = {
  Banner: ({ children }) => React.createElement("div", {}, children),
  Button: ({ children, variant: _, ...props }) => React.createElement("button", props, children),
  LinkButton: ({ children, ...props }) => React.createElement("a", props, children),
};
const source = readFileSync(new URL("../app/components/billing/AnnualRefundRecoveryControl.tsx", import.meta.url), "utf8");
function render(state = { kind: "idle" }, pending = false, capture = () => {}, effect = async () => { throw new Error("unexpected action"); }) {
  const { AnnualRefundRecoveryControl } = compile(source, { "../ui": ui,
    react: { useActionState: (fn, initial) => { capture(fn); assert.equal(initial.kind, "idle"); return [state, () => {}, pending]; } } });
  return renderToStaticMarkup(React.createElement(AnnualRefundRecoveryControl, {
    companyId, purchaseId, refundRequestId, beforePurchaseId: cursor, beforeRefundRequestId: refundCursor, recoverAction: effect,
  }));
}
test("render is idle, keeps exact receipt fields and disables duplicate pending submission", () => {
  const html = render();
  assert.match(html, /Sjekk refusjonsstatus/);
  assert.match(html, new RegExp(`name="refundRequestId" value="${refundRequestId}"`));
  assert.doesNotMatch(source, /useEffect|useOptimistic|setInterval|router\.refresh/);
  assert.match(render({ kind: "observed", companyId, purchaseId, refundRequestId, status: "confirmed" }, true), /disabled=""/);
});
test("confirmation remains operation-scoped and foreign or stale request states stay hidden", () => {
  assert.match(render({ kind: "observed", companyId, purchaseId, refundRequestId, status: "confirmed" }), /kan fortsatt gjenstå et beløp/);
  for (const field of ["companyId", "purchaseId", "refundRequestId"]) {
    assert.doesNotMatch(render({ kind: "observed", companyId, purchaseId, refundRequestId, status: "confirmed", [field]: cursor }), /Dette refusjonsforsøket er bekreftet/);
    assert.doesNotMatch(render({ kind: "recovery", companyId, purchaseId, refundRequestId, reason: "step-up", href: "/mfa", [field]: cursor }), /Bekreft identiteten din/);
  }
});
test("lost browser response preserves the same receipt and only explicit retry calls again", async () => {
  let wrapper, attempts = 0;
  render(undefined, false, fn => { wrapper = fn; }, async (_previous, data) => {
    assert.equal(data.get("refundRequestId"), refundRequestId);
    if (++attempts === 1) throw new Error("lost saved result");
    return { kind: "observed", companyId, purchaseId, refundRequestId, status: "confirmed" };
  });
  assert.equal(attempts, 0);
  const lost = await wrapper({ kind: "idle" }, form());
  assert.equal(lost.reason, "unavailable");
  assert.match(render(lost), /Last inn refusjonsoversikten/);
  const reload = [...render(lost).matchAll(/href="([^"]+)"/g)].map(match => new URL(match[1].replaceAll('&amp;', '&'), 'https://talli.example'))
    .find(url => url.pathname === '/billing');
  assert.equal(reload.searchParams.get('refundRequestId'), refundRequestId);
  assert.equal(reload.searchParams.get('beforePurchaseId'), cursor);
  assert.equal(reload.searchParams.get('beforeRefundRequestId'), refundCursor);
  assert.doesNotMatch(render(lost), /Dette refusjonsforsøket er bekreftet/);
  assert.equal((await wrapper(lost, form())).status, "confirmed");
  assert.equal(attempts, 2);
});
