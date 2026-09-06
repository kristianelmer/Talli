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
const cursor = "30000000-0000-4000-8000-000000000001";
function compile(source, dependencies = {}, globals = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { exports, require: (id) => id in dependencies ? dependencies[id] : require(id),
    URLSearchParams, Error, ...globals });
  return exports;
}
const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const actionSource = actions.slice(actions.indexOf("export async function observeAnnualCheckout("), actions.indexOf("export async function cleanupAnnualAgreement("));
function action({ token = "verified-owner", status = "pending", failure, foreign, refreshFailure = false } = {}) {
  const calls = [];
  const refreshes = [];
  const globals = {
    formString: (form, key) => form.get(key) ?? "",
    requiredFormUuid: (form, key) => {
      const value = form.get(key);
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value ?? "")) throw new Error("invalid");
      return value;
    },
    ownerPathWithQuery: (path, values) => `${path}?${new URLSearchParams(Object.entries(values).filter(([, value]) => value !== undefined))}`,
    getCurrentSessionAccessToken: async () => token,
    observeAnnualCheckoutThroughApi: async (...args) => {
      calls.push(args);
      if (failure) throw new Error("private provider detail");
      return { companyId, purchaseId, ...(foreign ? { [foreign]: cursor } : {}), status,
        capturedMinor: 10000, refundedMinor: 0, checkoutUrl: "https://provider.example/private", offer: { termsText: "Do not replace stored terms" } };
    },
    annualBillingRecovery: () => failure ?? "unavailable",
    revalidatePath: (path) => { refreshes.push(path); if (refreshFailure) throw new Error("failed refresh"); },
  };
  return { calls, refreshes, run: compile(actionSource, {}, globals).observeAnnualCheckout };
}
function form(extra = {}) {
  return Object.entries({ companyId, purchaseId, beforePurchaseId: cursor, ...extra }).reduce((data, [key, value]) => {
    if (value !== undefined) data.set(key, value); return data;
  }, new FormData());
}
for (const status of ["pending", "paid", "refunded", "failed"]) {
  test(`scoped ${status} observation refreshes canonical history and discards partial checkout details`, async () => {
    const harness = action({ status });
    const result = await harness.run({ kind: "observed", companyId, purchaseId, status: "paid" },
      form({ status: "paid", actorId: cursor, operationId: cursor, incomeYear: "2030", purchaseAccepted: "true", checkoutUrl: "https://forged.example" }));
    assert.deepEqual(JSON.parse(JSON.stringify(result)), { kind: "observed", companyId, purchaseId, status });
    assert.deepEqual(JSON.parse(JSON.stringify(harness.calls)), [["verified-owner", { companyId, purchaseId }]]);
    assert.deepEqual(harness.refreshes, ["/billing"]);
    assert.doesNotMatch(JSON.stringify(result), /capturedMinor|refundedMinor|checkoutUrl|termsText|provider.example/);
  });
}
for (const failure of ["step-up", "sign-in", "unavailable"]) {
  test(`${failure} keeps original checkout and company-wide cursor for explicit recovery`, async () => {
    const harness = action({ failure });
    const result = await harness.run({ kind: "observed", companyId, purchaseId, status: "paid" }, form());
    assert.equal(result.kind, "recovery");
    assert.equal(result.reason, failure);
    assert.equal(result.companyId, companyId);
    assert.equal(result.purchaseId, purchaseId);
    if (failure === "unavailable") assert.equal(result.href, null);
    else {
      const target = new URL(result.href, "https://talli.example");
      assert.equal(target.pathname, failure === "step-up" ? "/mfa" : "/login");
      if (failure === "step-up") assert.equal(target.searchParams.get("fresh"), "1");
      if (failure === "sign-in") assert.equal(target.searchParams.get("reauth"), "1");
      const next = new URL(target.searchParams.get("next"), target.origin);
      assert.equal(next.searchParams.get("companyId"), companyId);
      assert.equal(next.searchParams.get("checkoutPurchaseId"), purchaseId);
      assert.equal(next.searchParams.get("beforePurchaseId"), cursor);
    }
    assert.equal(harness.refreshes.length, 0);
    assert.doesNotMatch(JSON.stringify(result), /private provider detail|paid/);
  });
}
test("missing session and malformed intent cannot observe a checkout", async () => {
  const noSession = action({ token: null });
  assert.equal((await noSession.run({ kind: "idle" }, form())).reason, "sign-in");
  assert.equal(noSession.calls.length, 0);
  for (const key of ["companyId", "purchaseId", "beforePurchaseId"]) {
    const harness = action();
    assert.equal((await harness.run({ kind: "idle" }, form({ [key]: "malformed" }))).kind, "invalid");
    assert.equal(harness.calls.length, 0);
    assert.equal(harness.refreshes.length, 0);
  }
});
test("foreign company or purchase cannot refresh or confirm the requested checkout", async () => {
  for (const foreign of ["companyId", "purchaseId"]) {
    const harness = action({ foreign, status: "paid" });
    assert.equal((await harness.run({ kind: "idle" }, form())).reason, "unavailable");
    assert.equal(harness.refreshes.length, 0);
  }
});
test("repeated checks keep the same purchase and no new operation identity", async () => {
  const harness = action();
  const first = await harness.run({ kind: "idle" }, form());
  await harness.run(first, form());
  assert.deepEqual(harness.calls[0], harness.calls[1]);
  assert.equal(harness.calls[0].length, 2);
});
test("failed revalidation cannot announce a locally paid purchase", async () => {
  const result = await action({ status: "paid", refreshFailure: true }).run({ kind: "idle" }, form());
  assert.equal(result.reason, "unavailable");
  assert.doesNotMatch(JSON.stringify(result), /paid/);
});

const ui = {
  Banner: ({ children }) => React.createElement("div", {}, children),
  Button: ({ children, variant: _variant, ...props }) => React.createElement("button", props, children),
  LinkButton: ({ children, ...props }) => React.createElement("a", props, children),
};
const controlSource = readFileSync(new URL("../app/components/billing/AnnualCheckoutObservationControl.tsx", import.meta.url), "utf8");
function render(state = { kind: "idle" }, pending = false, suppliedAction, captureAction = () => {}) {
  let effects = 0;
  const observeAction = suppliedAction ?? (async () => { effects++; return { kind: "idle" }; });
  const { AnnualCheckoutObservationControl } = compile(controlSource, {
    "../ui": ui,
    react: { useActionState: (bound, initial) => { captureAction(bound); assert.equal(initial.kind, "idle"); return [state, () => {}, pending]; } },
  });
  const html = renderToStaticMarkup(React.createElement(AnnualCheckoutObservationControl, { companyId, purchaseId, beforePurchaseId: cursor, observeAction }));
  assert.equal(effects, 0, "Rendering must never observe a checkout");
  return html;
}
test("status check starts idle and contains only original-intent and navigation fields", () => {
  const html = render();
  assert.match(html, /Sjekk betalingsstatus/);
  assert.match(html, new RegExp(`name="purchaseId" value="${purchaseId}"`));
  assert.match(html, new RegExp(`name="beforePurchaseId" value="${cursor}"`));
  assert.doesNotMatch(html, /name="(?:operationId|status|actorId|provider|incomeYear|purchaseAccepted)"/);
  assert.doesNotMatch(controlSource, /useEffect|useOptimistic|setInterval|router\.refresh/);
});
for (const status of ["pending", "paid", "refunded", "failed"]) {
  test(`${status} result leaves canonical history in charge of payment status and money`, () => {
    const html = render({ kind: "observed", companyId, purchaseId, status });
    assert.match(html, status === "pending" ? /fortsatt ikke bekreftet/ : /Vis oppdatert kjøpshistorikk/);
    assert.match(html, /Sjekk betalingsstatus/);
    assert.doesNotMatch(html, /Betalt tilgang|Betalingen er bekreftet|Refundert|Betalingen ble ikke fullført|https:\/\/provider/);
  });
}
test("in-flight request disables duplicate clicks and hides older messages", () => {
  const html = render({ kind: "observed", companyId, purchaseId, status: "pending" }, true);
  assert.match(html, /disabled=""/);
  assert.match(html, /Sjekker betalingsstatus/);
  assert.doesNotMatch(html, /fortsatt ikke bekreftet/);
});
test("foreign result and recovery state stay hidden on the current purchase", () => {
  assert.doesNotMatch(render({ kind: "observed", companyId, purchaseId: cursor, status: "paid" }), /Statusen er kontrollert/);
  assert.doesNotMatch(render({ kind: "recovery", companyId: cursor, purchaseId, reason: "step-up", href: "/mfa" }), /Bekreft identiteten din/);
});
test("lost browser response retains retry and read-only history refresh without inventing payment", async () => {
  let wrapper;
  let attempts = 0;
  const effect = async (_previous, submitted) => {
    attempts++;
    assert.equal(submitted.get("companyId"), companyId);
    assert.equal(submitted.get("purchaseId"), purchaseId);
    if (attempts === 1) throw new Error("response lost after recorded observation");
    return { kind: "observed", companyId, purchaseId, status: "paid" };
  };
  render({ kind: "idle" }, false, effect, (value) => { wrapper = value; });
  const unknown = await wrapper({ kind: "observed", companyId, purchaseId, status: "paid" }, form());
  assert.equal(unknown.reason, "unavailable");
  const html = render(unknown);
  assert.match(html, /Vi fikk ikke bekreftet betalingsstatusen/);
  assert.match(html, /Last inn kjøpshistorikken/);
  assert.match(html, new RegExp(`beforePurchaseId=${cursor}#annual-purchase-${purchaseId}`));
  assert.doesNotMatch(html, /Betalt|Statusen er kontrollert/);
  const result = await wrapper(unknown, form());
  assert.equal(result.status, "paid");
  assert.equal(attempts, 2);
});
