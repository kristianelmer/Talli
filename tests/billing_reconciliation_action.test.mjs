import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import test from "node:test";

const require = createRequire(resolve("package.json"));
const ts = require("typescript");
const source = readFileSync(resolve("apps/web/app/actions.ts"), "utf8");
const start = source.indexOf("export async function reconcileRf1086ProductionAction");
const end = source.indexOf("export async function postManualJournal", start);
assert.ok(start >= 0 && end > start);
const actionCode = ts.transpileModule(source.slice(start, end).replace("export async", "async"), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
}).outputText;

for (const state of ["accepted", "processing", "unknown"]) {
  test(`RF recovery delegates stored ${state} feedback without reimposing a billing gate`, async () => {
    const submissionId = "30000000-0000-4000-8000-000000000001";
    const calls = [];
    const dependencies = {
      requiredFormUuid: (form, key) => form.get(key),
      getCurrentSessionAccessToken: async () => "local-test-session",
      reconcileRf1086ThroughApi: async (token, id) => {
        calls.push([token, id]);
        return { state, errorCode: null, requiresManualRetry: false };
      },
      buildRf1086OwnerReconciliationActionState: (value, options) => ({ state: value, ...options }),
      safeRf1086OwnerErrorCode: code => code,
      rf1086ApiErrorCode: () => "status_unavailable",
      revalidatePath: () => {},
    };
    const action = new Function(...Object.keys(dependencies), `${actionCode}\nreturn reconcileRf1086ProductionAction;`)(...Object.values(dependencies));
    const form = new FormData();
    form.set("submissionId", submissionId);
    assert.deepEqual(await action({}, form), { state, errorCode: null, requiresManualRetry: false });
    assert.deepEqual(calls, [["local-test-session", submissionId]]);
    assert.doesNotMatch(actionCode, /loadBillingEntitlement|loadBillingSnapshot|service_role|requestMaskinportenToken/);
  });
}
