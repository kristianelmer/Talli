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
const uid = value => `10000000-0000-4000-8000-${String(value).padStart(12, "0")}`;
const identity = { initiatingUserId: uid(1), companyId: uid(2), purchaseId: uid(3), refundRequestId: uid(4), supportCaseId: uid(5) };
const cursors = { beforePurchaseId: uid(6), beforeRefundRequestId: uid(7) };
const helpers = { operatorReadRecovery, operatorRecoveryHref, operatorSupportLocation };
const plain = value => JSON.parse(JSON.stringify(value));
function compile(source, dependencies = {}, globals = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText, { exports, require: id => id in dependencies ? dependencies[id] : require(id),
    URL, URLSearchParams, FormData, Error, ...globals });
  return exports;
}
const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const actionSource = actions.slice(actions.indexOf("export async function recoverAnnualSupportRefund("), actions.indexOf("export async function recoverAnnualRefund("));
function action({ token = "verified-operator", userId = identity.initiatingUserId, userError = null,
  failure = null, status = "pending", foreign = null, refreshFailure = false } = {}) {
  const calls = [], refreshes = [], verifiedTokens = [];
  return { calls, refreshes, verifiedTokens, run: compile(actionSource, {}, {
    ...helpers,
    requiredFormUuid: (data, key) => {
      const value = data.get(key);
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value ?? "")) throw new Error("invalid");
      return value;
    },
    getCurrentSessionAccessToken: async () => token,
    createSupabaseServerClient: async () => ({ auth: { getUser: async value => {
      verifiedTokens.push(value); return { data: { user: userId ? { id: userId } : null }, error: userError };
    } } }),
    recoverAnnualSupportRefundThroughApi: async (...args) => {
      calls.push(args); if (failure) throw failure;
      return { ...identity, incomeYear: 2026, status, ...(foreign ? { [foreign]: uid(99) } : {}),
        providerAccount: "private", sourceReference: "private", refundedMinor: 149000 };
    },
    revalidatePath: path => { refreshes.push(path); if (refreshFailure) throw new Error("private refresh failure"); },
  }).recoverAnnualSupportRefund };
}
function form(changes = {}) {
  const value = new FormData();
  for (const [key, data] of Object.entries({ ...identity, ...cursors, ...changes })) if (data !== undefined) value.set(key, data);
  return value;
}
const expectedBody = { companyId: identity.companyId, purchaseId: identity.purchaseId,
  refundRequestId: identity.refundRequestId, supportCaseId: identity.supportCaseId };
function expectedDestination(href) {
  const auth = new URL(href, "https://talli.example");
  const destination = new URL(auth.searchParams.get("next") ?? href, auth.origin);
  assert.equal(destination.pathname, "/operator");
  assert.equal(auth.hash, "");
  assert.equal(destination.hash, auth.searchParams.has("next") ? "#annual-billing" : "");
  assert.deepEqual(Object.fromEntries(destination.searchParams), {
    supportCase: identity.supportCaseId, annualBefore: cursors.beforePurchaseId,
    companyId: identity.companyId, refundPurchaseId: identity.purchaseId, refundRequestId: identity.refundRequestId,
    beforeRefundRequestId: cursors.beforeRefundRequestId,
  });
  return auth;
}

for (const status of ["pending", "unknown", "confirmed", "failed"]) {
  test(`${status} operator action verifies the exact token and sends only original scoped IDs`, async () => {
    const harness = action({ status });
    const result = await harness.run({ kind: "observed", ...identity, status: "confirmed" }, form({
      actorId: uid(99), sourceReference: "forged", amountMinor: "149000", idempotencyKey: "new-attempt", next: "https://outside.invalid",
    }));
    assert.deepEqual(plain(result), { kind: "observed", ...identity, status });
    assert.deepEqual(harness.verifiedTokens, ["verified-operator"]);
    assert.deepEqual(plain(harness.calls), [["verified-operator", expectedBody]]);
    assert.deepEqual(harness.refreshes, ["/operator"]);
  });
}
for (const options of [{ token: null }, { userId: null }, { userError: new Error("private") }, { userId: uid(99) }]) {
  test(`missing or changed verified operator blocks dispatch ${JSON.stringify(options)}`, async () => {
    const harness = action(options);
    const result = await harness.run({ kind: "idle" }, form());
    assert.equal(result.kind, options.userId === uid(99) ? "different-user" : "recovery");
    if (result.kind === "recovery") { assert.equal(result.reason, "sign-in"); expectedDestination(result.href); }
    assert.deepEqual(harness.calls, []);
    assert.deepEqual(harness.refreshes, ["/operator"]);
    assert.deepEqual(harness.verifiedTokens, options.token === null ? [] : ["verified-operator"]);
  });
}
for (const [status, code, recovery] of [[401, "AUTHENTICATION_REQUIRED", "sign-in"],
  [403, "BILLING_STEP_UP_REQUIRED", "step-up"], [403, "BILLING_FORBIDDEN", "forbidden"],
  [404, "BILLING_NOT_FOUND", "unavailable"], [503, "BILLING_UNAVAILABLE", "unavailable"]]) {
  test(`${status}/${code} refreshes all operator evidence and keeps complete explicit return`, async () => {
    const harness = action({ failure: new TalliApiError(status, { code, status, detail: "private provider details" }) });
    const result = await harness.run({ kind: "idle" }, form());
    assert.equal(result.kind, "recovery"); assert.equal(result.reason, recovery);
    const auth = expectedDestination(result.href);
    if (recovery === "sign-in") assert.equal(auth.searchParams.get("reauth"), "1");
    if (recovery === "step-up") assert.equal(auth.searchParams.get("fresh"), "1");
    assert.deepEqual(harness.refreshes, ["/operator"]);
    assert.doesNotMatch(JSON.stringify(result), /private|refundedMinor|providerAccount/);
  });
}

test("duplicate, missing and malformed identity or cursors never dispatch", async () => {
  for (const name of Object.keys({ ...identity, ...cursors })) {
    for (const mode of ["malformed", "duplicate", ...(name in identity ? ["missing"] : [])]) {
      const data = form(mode === "missing" ? { [name]: undefined } : mode === "malformed" ? { [name]: "bad" } : {});
      if (mode === "duplicate") data.append(name, data.get(name));
      const harness = action();
      assert.equal((await harness.run({ kind: "idle" }, data)).kind, "invalid");
      assert.deepEqual(harness.calls, []); assert.deepEqual(harness.verifiedTokens, []);
    }
  }
});
test("foreign response or failed canonical refresh cannot report confirmation", async () => {
  for (const foreign of Object.keys(expectedBody)) {
    const harness = action({ foreign, status: "confirmed" });
    const result = await harness.run({ kind: "idle" }, form());
    assert.equal(result.kind, "recovery"); assert.equal(result.reason, "unavailable");
    assert.deepEqual(harness.refreshes, ["/operator"]);
  }
  const result = await action({ refreshFailure: true, status: "confirmed" }).run({ kind: "idle" }, form());
  assert.equal(result.kind, "recovery"); assert.equal(result.reason, "unavailable");
});
test("explicit repeated operator checks retain the same four IDs and no attempt key", async () => {
  const harness = action();
  const first = await harness.run({ kind: "idle" }, form());
  await harness.run(first, form());
  assert.deepEqual(harness.calls[0], harness.calls[1]);
});

const ui = {
  Banner: ({ children }) => React.createElement("div", {}, children),
  Button: ({ variant, ...props }) => React.createElement("button", props),
  LinkButton: () => { throw new Error("Reload requires a native document navigation"); },
};
const controlSource = readFileSync(new URL("../app/components/billing/AnnualSupportRefundRecoveryControl.tsx", import.meta.url), "utf8");
function control(recoverAction) {
  const hooks = [], cleanups = [];
  let cursor = 0, tree;
  const Control = compile(controlSource, { "../ui": ui, "../../lib/operator-support": helpers,
    react: {
      useRef: value => { const index = cursor++; return hooks[index] ??= { current: value }; },
      useState: value => { const index = cursor++; if (!(index in hooks)) hooks[index] = value;
        return [hooks[index], next => { hooks[index] = typeof next === "function" ? next(hooks[index]) : next; }]; },
      useEffect: effect => { const index = cursor++; if (!(index in hooks)) { hooks[index] = true; cleanups.push(effect()); } },
    },
  }, { FormData: class extends FormData { constructor(value) { super(); if (value) for (const [key, item] of value) this.append(key, item); } } }).AnnualSupportRefundRecoveryControl;
  function find(node, name) {
    if (node?.type === name) return node;
    const children = node?.props?.children;
    for (const child of Array.isArray(children) ? children.flat(Infinity) : [children]) {
      const result = child && find(child, name); if (result) return result;
    }
  }
  return {
    render: (changes = {}) => { cursor = 0; tree = Control({ ...identity, ...cursors, recoverAction, ...changes }); return renderToStaticMarkup(tree); },
    submit: () => find(tree, "form").props.onSubmit({ preventDefault() {}, currentTarget: form() }),
    unmount: () => cleanups.forEach(value => value?.()),
    snapshot: () => plain(hooks),
  };
}

test("actual control stays read-only on render and blocks duplicate events until same-request pending recovery settles", async () => {
  let release;
  const calls = [];
  const harness = control(async (previous, data) => { calls.push(Object.fromEntries(data)); return new Promise(resolve => { release = resolve; }); });
  const idle = harness.render();
  assert.equal(calls.length, 0); assert.match(idle, /Sjekk refusjonsstatus/);
  const pending = harness.submit();
  await harness.submit();
  assert.equal(calls.length, 1); assert.match(harness.render(), /disabled=""/);
  release({ kind: "observed", ...identity, status: "pending" }); await pending;
  assert.doesNotMatch(harness.render(), /disabled=""/);
  const again = harness.submit();
  release({ kind: "observed", ...identity, status: "pending" }); await again;
  assert.match(harness.render(), /venter fortsatt på bekreftelse/);
  assert.deepEqual(calls[0], calls[1]);
  assert.deepEqual(calls[0], { ...identity, ...cursors });
});
test("lost action response leaves original scope for explicit retry and never posts during a fresh mount", async () => {
  let calls = 0;
  const harness = control(async () => { calls++; throw new Error("lost browser response"); });
  harness.render(); await harness.submit();
  const html = harness.render();
  assert.match(html, /Vi fikk ikke bekreftet/);
  for (const [name, value] of Object.entries(identity)) assert.match(html, new RegExp(`name="${name}" value="${value}"`));
  assert.doesNotMatch(html, /lost browser response/);
  const link = html.match(/href="([^"]+)"/)[1].replaceAll("&amp;", "&");
  const destination = new URL(link, "https://talli.example");
  assert.equal(destination.searchParams.get("refundRequestId"), identity.refundRequestId);
  assert.equal(destination.hash, "");
  const remounted = control(async () => { calls++; }); remounted.render();
  assert.equal(calls, 1);
});
test("late results after unmount cannot replace a new operator's state", async () => {
  let release;
  const harness = control(async () => new Promise(resolve => { release = resolve; }));
  harness.render(); const pending = harness.submit(); harness.unmount();
  const before = harness.snapshot();
  release({ kind: "observed", ...identity, status: "confirmed" }); await pending;
  assert.deepEqual(harness.snapshot(), before.map((value, index) => index === 2 ? { current: false } : value));
});
test("feedback remains operation-scoped and mismatched identity never announces confirmation", async () => {
  for (const field of Object.keys(identity)) {
    const harness = control(async () => ({ kind: "observed", ...identity, [field]: uid(99), status: "confirmed" }));
    harness.render(); await harness.submit();
    assert.doesNotMatch(harness.render(), /Dette refusjonsforsøket er bekreftet/);
  }
  const harness = control(async () => ({ kind: "observed", ...identity, status: "confirmed" }));
  harness.render(); await harness.submit();
  assert.match(harness.render(), /Det kan fortsatt gjenstå et beløp/);
});
