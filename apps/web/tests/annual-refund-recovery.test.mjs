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
  } }).outputText, { exports, require: id => id in dependencies ? dependencies[id] : require(id), URLSearchParams, Error, ...globals });
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
      const next = new URL(login.searchParams.get("next"), login.origin);
      assert.equal(next.searchParams.get("companyId"), companyId);
      assert.equal(next.searchParams.get("refundPurchaseId"), purchaseId);
      assert.equal(next.searchParams.get("refundRequestId"), refundRequestId);
      assert.equal(next.searchParams.get("beforePurchaseId"), cursor);
      assert.equal(next.searchParams.get("beforeRefundRequestId"), refundCursor);
    }
  });
}
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
  assert.doesNotMatch(render(lost), /Dette refusjonsforsøket er bekreftet/);
  assert.equal((await wrapper(lost, form())).status, "confirmed");
  assert.equal(attempts, 2);
});
