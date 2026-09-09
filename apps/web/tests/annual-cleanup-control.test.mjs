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
const actionSource = actions.slice(actions.indexOf("export async function cleanupAnnualAgreement("), actions.indexOf("export async function cancelAnnualRenewal("));
function action({ token = "verified-owner", status = "confirmed", failure, foreign = false } = {}) {
  const calls = [];
  const globals = {
    formString: (form, key) => form.get(key) ?? "",
    requiredFormUuid: (form, key) => {
      const value = form.get(key);
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value ?? "")) throw new Error("invalid");
      return value;
    },
    ownerPathWithQuery: (path, values) => `${path}?${new URLSearchParams(Object.entries(values).filter(([, value]) => value !== undefined))}`,
    getCurrentSessionAccessToken: async () => token,
    cleanupAnnualAgreementThroughApi: async (...args) => {
      calls.push(args);
      if (failure) throw new Error("private provider detail");
      return { companyId: foreign ? cursor : companyId, purchaseId, status };
    },
    annualBillingRecovery: () => failure,
  };
  return { calls, run: compile(actionSource, {}, globals).cleanupAnnualAgreement };
}
function form(extra = {}) {
  return Object.entries({ companyId, purchaseId, beforePurchaseId: cursor, ...extra }).reduce((data, [key, value]) => {
    if (value !== undefined) data.set(key, value); return data;
  }, new FormData());
}
for (const status of ["confirmed", "pending", "unknown", "deferred"]) {
  test(`owner cleanup action returns only the scoped backend ${status} result`, async () => {
    const harness = action({ status });
    const result = await harness.run({ kind: "result", value: { companyId, purchaseId, status: "confirmed" } },
      form({ status: "confirmed", actorId: cursor, operationId: cursor, provider: "forged", supportCaseId: cursor }));
    assert.deepEqual(JSON.parse(JSON.stringify(result)), { kind: "result", value: { companyId, purchaseId, status } });
    assert.deepEqual(JSON.parse(JSON.stringify(harness.calls)), [["verified-owner", { companyId, purchaseId }]]);
  });
}
for (const failure of ["step-up", "sign-in", "unavailable"]) {
  test(`owner cleanup ${failure} never trusts previous confirmation and retains retry scope`, async () => {
    const harness = action({ failure });
    const result = await harness.run({ kind: "result", value: { companyId, purchaseId, status: "confirmed" } }, form());
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
      assert.equal(next.searchParams.get("cleanupPurchaseId"), purchaseId);
      assert.equal(next.searchParams.get("beforePurchaseId"), cursor);
    }
    assert.doesNotMatch(JSON.stringify(result), /private provider detail|confirmed/);
  });
}
test("missing session and malformed scope never call the provider recovery endpoint", async () => {
  const unauthenticated = action({ token: null });
  assert.equal((await unauthenticated.run({ kind: "idle" }, form())).reason, "sign-in");
  assert.equal(unauthenticated.calls.length, 0);
  for (const key of ["companyId", "purchaseId", "beforePurchaseId"]) {
    const harness = action();
    assert.equal((await harness.run({ kind: "idle" }, form({ [key]: "malformed" }))).kind, "invalid");
    assert.equal(harness.calls.length, 0);
  }
});
test("retries use the same purchase without a browser operation key and reject mismatched response scope", async () => {
  const harness = action({ status: "unknown" });
  const first = await harness.run({ kind: "idle" }, form());
  await harness.run(first, form());
  assert.deepEqual(harness.calls[0], harness.calls[1]);
  assert.equal(harness.calls[0].length, 2);
  const foreign = await action({ foreign: true }).run({ kind: "idle" }, form());
  assert.equal(foreign.kind, "recovery");
  assert.equal(foreign.reason, "unavailable");
});

const ui = {
  Banner: ({ children }) => React.createElement("div", {}, children),
  Button: ({ children, variant: _variant, ...props }) => React.createElement("button", props, children),
  LinkButton: ({ children, ...props }) => React.createElement("a", props, children),
};
const controlSource = readFileSync(new URL("../app/components/billing/AnnualAgreementCleanupControl.tsx", import.meta.url), "utf8");
function render(state = { kind: "idle" }, pending = false, suppliedAction, captureAction = () => {}) {
  let effects = 0;
  const cleanupAction = suppliedAction ?? (async () => { effects++; return { kind: "idle" }; });
  const { AnnualAgreementCleanupControl } = compile(controlSource, {
    "../ui": ui,
    react: { useActionState: (action, initial) => {
      assert.equal(typeof action, "function");
      captureAction(action);
      assert.equal(initial.kind, "idle");
      return [state, () => {}, pending];
    } },
  });
  const html = renderToStaticMarkup(React.createElement(AnnualAgreementCleanupControl, { companyId, purchaseId, beforePurchaseId: cursor, cleanupAction }));
  assert.equal(effects, 0, "Rendering must never perform cleanup");
  return html;
}
test("owner cleanup starts idle and only an explicit form can run recovery", () => {
  const html = render();
  assert.match(html, /Fullfør avslutning/);
  assert.match(html, new RegExp(`name="purchaseId" value="${purchaseId}"`));
  assert.match(html, new RegExp(`name="beforePurchaseId" value="${cursor}"`));
  assert.doesNotMatch(html, /name="(?:operationId|status|actorId|provider)"|har bekreftet/);
  assert.doesNotMatch(controlSource, /useEffect|useOptimistic|setInterval/);
});
for (const status of ["confirmed", "pending", "unknown", "deferred"]) {
  test(`owner cleanup renders ${status} without claiming another outcome`, () => {
    const html = render({ kind: "result", value: { companyId, purchaseId, status } });
    if (status === "confirmed") {
      assert.match(html, /har bekreftet at betalingsavtalen er avsluttet/);
      assert.doesNotMatch(html, /<button/);
    } else {
      assert.doesNotMatch(html, /har bekreftet at betalingsavtalen er avsluttet/);
      assert.match(html, /<button/);
    }
  });
}
test("pending submission disables repeated clicks and hides stale success", () => {
  const html = render({ kind: "result", value: { companyId, purchaseId, status: "unknown" } }, true);
  assert.match(html, /disabled=""/);
  assert.match(html, /Kontrollerer betalingsavtalen/);
  assert.doesNotMatch(html, /Vi fikk ikke bekreftet utfallet/);
});
test("foreign purchase state cannot appear on the current control", () => {
  const html = render({ kind: "result", value: { companyId, purchaseId: cursor, status: "confirmed" } });
  assert.doesNotMatch(html, /har bekreftet/);
  assert.match(html, /<button/);
  const recovery = render({ kind: "recovery", companyId: cursor, purchaseId, reason: "step-up", href: "/mfa" });
  assert.doesNotMatch(recovery, /Bekreft identiteten din/);
});


test("lost browser action response stays unconfirmed and the same purchase can retry", async () => {
  let wrapper;
  let attempts = 0;
  const effect = async (_previous, submitted) => {
    attempts++;
    assert.equal(submitted.get("companyId"), companyId);
    assert.equal(submitted.get("purchaseId"), purchaseId);
    if (attempts === 1) throw new Error("response lost after committed cleanup");
    return { kind: "result", value: { companyId, purchaseId, status: "confirmed" } };
  };
  render({ kind: "idle" }, false, effect, (value) => { wrapper = value; });
  const unknown = await wrapper({ kind: "result", value: { companyId, purchaseId, status: "confirmed" } }, form());
  assert.equal(unknown.kind, "recovery");
  assert.equal(unknown.reason, "unavailable");
  assert.equal(unknown.companyId, companyId);
  assert.equal(unknown.purchaseId, purchaseId);
  const html = render(unknown);
  assert.match(html, /Vi fikk ikke bekreftet at betalingsavtalen er avsluttet/);
  assert.match(html, /Fullfør avslutning av betalingsavtalen/);
  assert.doesNotMatch(html, /har bekreftet at betalingsavtalen er avsluttet/);
  const result = await wrapper(unknown, form());
  assert.equal(result.value.status, "confirmed");
  assert.equal(attempts, 2);
});
