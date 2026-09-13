import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("../apps/web/app/lib/rf1086-workspace-source.ts", import.meta.url), "utf8");
function load(loadRf1086Workspaces) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
  } }).outputText, { exports, require: () => ({ loadRf1086Workspaces,
    rf1086ActionErrorMessage: () => "RF-1086 er midlertidig utilgjengelig.",
    ...Object.fromEntries(["Preview", "Simulation", "Override", "ReviewComment", "Permission", "TestEvidence"].map((name) => [`presentRf1086${name}`, (value) => value])),
  }) });
  return exports;
}
const plain = (value) => JSON.parse(JSON.stringify(value));
test("failed RF source preserves explicit unavailable state and never returns successful partial facts", async () => {
  const { loadPresentedRf1086Source } = load(async () => { throw new Error("private upstream failure"); });
  const value = await loadPresentedRf1086Source("token", ["company"], 2025);
  assert.deepEqual(plain(value), { error: "RF-1086 er midlertidig utilgjengelig.", previews: [], submissions: [], overrides: [], comments: [], authorityPermissions: [], authorityTestRuns: [] });
});
test("composition replaces overlap mirrors by identity and preserves sibling records and ordering", () => {
  const { composeFilingSources, newestFirst } = load();
  const sibling = { id: "tax", updated: "2026-09-10", value: "tax original" };
  const mirror = { id: "rf", updated: "2026-09-08", value: "stale mirror" };
  const canonical = { id: "rf", updated: "2026-09-11", value: "RF canonical" };
  const legacy = [sibling, mirror], owned = [canonical];
  assert.deepEqual(plain(newestFirst(composeFilingSources(legacy, owned), (row) => row.updated)), [canonical, sibling]);
  assert.deepEqual(legacy, [sibling, mirror]);
  assert.deepEqual(owned, [canonical]);
});
test("one scoped source read supplies every family without substituting a current year", async () => {
  const calls = [];
  const workspace = { previews: [{ id: "p" }], simulations: [{ id: "s" }], overrides: [{ id: "o" }],
    reviewComments: [{ id: "c" }], permissions: [{ id: "a" }], testEvidence: [{ id: "t" }] };
  const { loadPresentedRf1086Source } = load(async (...args) => { calls.push(args); return [workspace]; });
  const value = await loadPresentedRf1086Source("token", ["company"]);
  assert.deepEqual(calls, [["token", ["company"], undefined]]);
  assert.deepEqual(plain(value), { error: null, previews: workspace.previews, submissions: workspace.simulations,
    overrides: workspace.overrides, comments: workspace.reviewComments, authorityPermissions: workspace.permissions, authorityTestRuns: workspace.testEvidence });
});
