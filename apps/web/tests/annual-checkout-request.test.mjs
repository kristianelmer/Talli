import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";
import {
  parseAnnualCheckoutDraft, sameAnnualCheckoutDraft, readAnnualCheckoutDraft,
  saveAnnualCheckoutDraft, removeAnnualCheckoutDraft, annualCheckoutHistoryHref,
} from "../app/lib/annual-checkout-request.ts";

const companyId = "10000000-0000-4000-8000-000000000001";
const userId = "20000000-0000-4000-8000-000000000001";
const purchaseId = "30000000-0000-4000-8000-000000000001";
const cursor = "40000000-0000-4000-8000-000000000001";
const key = `talli:annual-checkout:${companyId}`;
function draft(overrides = {}) {
  return { version: 1, initiatingUserId: userId, idempotencyKey: randomUUID(), beforePurchaseId: cursor,
    phase: "checkout-requested", body: { companyId, incomeYear: 2026, offerVersion: "original-offer",
      termsDigest: "a".repeat(64), purchaseAccepted: true, recurringConsent: false, consentVersion: "original-consent" }, ...overrides };
}
class Storage {
  values = new Map();
  fail;
  getItem(key) { if (this.fail === "read") throw new Error("storage denied"); return this.values.get(key) ?? null; }
  setItem(key, value) { if (this.fail === "write") throw new Error("quota"); this.values.set(key, value); }
  removeItem(key) { if (this.fail === "remove") throw new Error("storage denied"); this.values.delete(key); }
}

test("restoration retains exact original body/key/year/user without network work", () => {
  const storage = new Storage(), original = draft();
  assert.equal(saveAnnualCheckoutDraft(storage, original, null), true);
  assert.deepEqual(readAnnualCheckoutDraft(storage, companyId), { kind: "retained", draft: original });
  assert.equal(saveAnnualCheckoutDraft(storage, draft(), null), false);
  assert.equal(saveAnnualCheckoutDraft(storage, { ...original, body: { ...original.body, consentVersion: "new" } }, original), false);
  assert.equal(saveAnnualCheckoutDraft(storage, { ...original, initiatingUserId: purchaseId }, original), false);
  assert.deepEqual(readAnnualCheckoutDraft(storage, companyId).draft, original);
});

test("withdrawal choice persists before recovery and cannot revert or change intent", () => {
  const storage = new Storage(), original = draft();
  saveAnnualCheckoutDraft(storage, original, null);
  const withdrawal = { ...original, phase: "withdrawal-requested" };
  assert.equal(saveAnnualCheckoutDraft(storage, withdrawal, original), true);
  assert.deepEqual(readAnnualCheckoutDraft(storage, companyId).draft, withdrawal);
  assert.equal(saveAnnualCheckoutDraft(storage, original, withdrawal), false);
  assert.equal(saveAnnualCheckoutDraft(storage, { ...withdrawal, idempotencyKey: randomUUID() }, withdrawal), false);
  assert.equal(saveAnnualCheckoutDraft(storage, withdrawal, withdrawal), true);
});

test("only a matching saved request can be removed; late A cannot erase B", () => {
  const storage = new Storage(), a = draft(), b = draft();
  saveAnnualCheckoutDraft(storage, a, null);
  storage.setItem(key, JSON.stringify(b));
  assert.equal(removeAnnualCheckoutDraft(storage, a), false);
  assert.deepEqual(readAnnualCheckoutDraft(storage, companyId).draft, b);
  assert.equal(removeAnnualCheckoutDraft(storage, b), true);
  assert.deepEqual(readAnnualCheckoutDraft(storage, companyId), { kind: "empty" });
});

for (const fail of ["read", "write", "remove"]) test(`storage ${fail} failure cannot overwrite or release retained intent`, () => {
  const storage = new Storage(), original = draft();
  saveAnnualCheckoutDraft(storage, original, null);
  storage.fail = fail;
  if (fail === "remove") assert.equal(removeAnnualCheckoutDraft(storage, original), false);
  else assert.equal(saveAnnualCheckoutDraft(storage, { ...original, phase: "withdrawal-requested" }, original), false);
  storage.fail = undefined;
  assert.deepEqual(readAnnualCheckoutDraft(storage, companyId).draft, original);
});

for (const change of [
  { version: 2 }, { initiatingUserId: "bad" }, { idempotencyKey: "bad" }, { beforePurchaseId: "bad" },
  { phase: "paid" }, { providerUrl: "https://forged.example" }, { token: "never-store" },
]) test(`unsupported draft ${Object.keys(change)[0]} is retained without replacement`, () => {
  const storage = new Storage(), original = JSON.stringify({ ...draft(), ...change });
  storage.setItem(key, original);
  assert.equal(parseAnnualCheckoutDraft(original), null);
  assert.deepEqual(readAnnualCheckoutDraft(storage, companyId), { kind: "unavailable" });
  assert.equal(saveAnnualCheckoutDraft(storage, draft(), null), false);
  assert.equal(storage.getItem(key), original);
});

for (const change of [
  { companyId: "bad" }, { incomeYear: 2026.1 }, { incomeYear: 2101 }, { termsDigest: "no" },
  { purchaseAccepted: false }, { recurringConsent: "true" }, { offerVersion: "" }, { consentVersion: "x".repeat(101) },
  { readiness: true }, { actorId: userId },
]) test(`draft business input ${Object.keys(change)[0]} fails before use`, () => {
  const original = draft();
  assert.equal(parseAnnualCheckoutDraft(JSON.stringify({ ...original, body: { ...original.body, ...change } })), null);
});

test("history navigation selects the purchase on newest history and keeps prior cursor only as a backlink", () => {
  const url = new URL(annualCheckoutHistoryHref(companyId, purchaseId, cursor), "https://talli.example");
  assert.equal(url.searchParams.get("checkoutPurchaseId"), purchaseId);
  assert.equal(url.searchParams.get("beforePurchaseId"), null);
  assert.equal(url.searchParams.get("checkoutBeforePurchaseId"), cursor);
  assert.equal(url.hash, `#annual-purchase-${purchaseId}`);
});

const require = createRequire(import.meta.url);
const actions = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const start = actions.indexOf("async function executeAnnualCheckoutRequest(");
const end = actions.indexOf("export async function observeAnnualCheckout(", start);
assert.ok(start >= 0 && end > start, "real checkout action boundaries must exist");
function action({ token = "verified-owner", user = userId, failure, foreign, refreshFailure = false } = {}) {
  const calls = [], verifiedTokens = [], refreshes = [];
  const exports = {};
  const globals = {
    parseAnnualCheckoutDraft,
    ownerPathWithQuery: (path, values) => `${path}?${new URLSearchParams(Object.entries(values).filter(([, value]) => value !== undefined))}`,
    getCurrentSessionAccessToken: async () => token,
    createSupabaseServerClient: async () => ({ auth: { getUser: async value => {
      verifiedTokens.push(value); return { data: { user: user ? { id: user } : null }, error: null };
    } } }),
    startAnnualCheckoutThroughApi: async (...args) => {
      calls.push(["start", ...args]); if (failure) throw new Error("private failure");
      return { companyId: foreign ? purchaseId : companyId, incomeYear: 2026, purchaseId, checkoutUrl: "https://payment.example/approval" };
    },
    withdrawAnnualCheckoutRequestThroughApi: async (...args) => {
      calls.push(["withdraw", ...args]); if (failure) throw new Error("private failure");
      return { companyId: foreign ? purchaseId : companyId, incomeYear: 2026, state: "withdrawn", purchaseId: null,
        withdrawalId: purchaseId, withdrawnAt: "2026-09-06T12:00:00Z" };
    },
    annualBillingRecovery: () => failure ?? "unavailable",
    annualCheckoutNeedsWithdrawal: () => failure === "stale-terms",
    annualBillingAccessRejected: () => failure === "sign-in" || failure === "step-up",
    revalidatePath: path => { refreshes.push(path); if (refreshFailure) throw new Error("refresh failed"); },
  };
  vm.runInNewContext(ts.transpileModule(actions.slice(start, end), { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
  } }).outputText, { exports, require, URLSearchParams, Error, ...globals });
  const run = async original => {
    const form = new FormData(); form.set("draft", JSON.stringify(original));
    form.set("actorId", "forged"); form.set("paid", "true");
    return exports[original.phase === "withdrawal-requested" ? "withdrawAnnualCheckoutRequest" : "startAnnualCheckoutRequest"](
      { kind: "started", draft: original, purchaseId, checkoutUrl: "javascript:forged()" }, form);
  };
  return { calls, verifiedTokens, refreshes, run, exports };
}

for (const phase of ["checkout-requested", "withdrawal-requested"]) {
  test(`${phase} verifies exact token subject and forwards only original body/key`, async () => {
    const original = draft({ phase }), harness = action();
    const result = await harness.run(original);
    assert.equal(result.kind, phase === "checkout-requested" ? "started" : "resolved");
    assert.deepEqual(harness.verifiedTokens, ["verified-owner"]);
    assert.deepEqual(harness.calls, [[phase === "checkout-requested" ? "start" : "withdraw", "verified-owner", original.body, original.idempotencyKey]]);
    assert.equal(sameAnnualCheckoutDraft(result.draft, original), true);
    assert.deepEqual(harness.refreshes, ["/billing"]);
  });
  for (const config of [{ token: null }, { user: null }, { user: purchaseId }]) test(`${phase} blocks missing or changed initiating user ${JSON.stringify(config)}`, async () => {
    const harness = action(config), original = draft({ phase });
    const result = await harness.run(original);
    assert.equal(result.kind, config.user === purchaseId ? "different-user" : "recovery");
    if (result.kind === "recovery") assert.equal(result.reason, "sign-in");
    assert.equal(harness.calls.length, 0);
    assert.equal(sameAnnualCheckoutDraft(result.draft, original), true);
  });
  for (const failure of ["sign-in", "step-up", "unavailable"]) test(`${phase} ${failure} preserves request and explicit recovery return`, async () => {
    const harness = action({ failure }), original = draft({ phase });
    const result = await harness.run(original);
    assert.equal(result.kind, "recovery");
    assert.equal(sameAnnualCheckoutDraft(result.draft, original), true);
    assert.equal(result.reason, failure);
    if (result.href) {
      const recovery = new URL(result.href, "https://talli.example");
      const next = new URL(recovery.searchParams.get("next"), recovery.origin);
      assert.equal(next.searchParams.get("companyId"), companyId);
      assert.equal(next.searchParams.get("beforePurchaseId"), cursor);
    }
    assert.doesNotMatch(JSON.stringify(result), /private failure|forged/);
  });
  for (const config of [{ foreign: true }, { refreshFailure: true }]) test(`${phase} cannot resolve a foreign response or failed canonical refresh`, async () => {
    const original = draft({ phase }), result = await action(config).run(original);
    assert.equal(result.kind, "recovery");
    assert.equal(sameAnnualCheckoutDraft(result.draft, original), true);
  });
}

test("wrong phase, malformed or duplicate draft cannot reach a checkout command", async () => {
  const harness = action(), original = draft({ phase: "withdrawal-requested" });
  const form = new FormData(); form.set("draft", JSON.stringify(original));
  assert.equal((await harness.exports.startAnnualCheckoutRequest({ kind: "idle" }, form)).kind, "invalid");
  form.append("draft", JSON.stringify(original));
  assert.equal((await harness.exports.withdrawAnnualCheckoutRequest({ kind: "idle" }, form)).kind, "invalid");
  form.set("draft", "bad-json");
  assert.equal((await harness.exports.withdrawAnnualCheckoutRequest({ kind: "idle" }, form)).kind, "invalid");
  assert.equal(harness.calls.length, 0);
});
