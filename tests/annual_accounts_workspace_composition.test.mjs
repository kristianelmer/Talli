import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
function module(path, dependencies = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(read(path), { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
  } }).outputText, { exports, require: () => dependencies });
  return exports;
}
const plain = value => JSON.parse(JSON.stringify(value));
const presenters = module("../apps/web/features/annual-accounts-filing/presentation.ts");
const empty = () => ({ previews: [], submissions: [], overrides: [], reviewComments: [], permissions: [], testEvidence: [] });
function load(query) {
  return module("../apps/web/app/lib/annual-accounts-workspace-source.ts", {
    ...presenters, loadAnnualAccountsFilingWorkspace: query,
  }).loadPresentedAnnualAccountsSource;
}
const unavailable = { error: "Årsregnskapsgrunnlaget kunne ikke leses. Prøv igjen.", previews: [], submissions: [], overrides: [], comments: [], authorityPermissions: [], authorityTestRuns: [] };
test("Accounts reads exactly once per company and preserves an omitted or explicit year", async () => {
  const calls = [];
  const source = load(async (...args) => { calls.push(args); return empty(); });
  assert.equal((await source("token", ["first", "second"])).error, null);
  await source("token", ["first"], 2024);
  assert.deepEqual(calls, [["token", "first", null], ["token", "second", null], ["token", "first", 2024]]);
});
test("a failed company discards partial results and an absent token never reads", async () => {
  let calls = 0;
  const source = load(async (_, company) => { calls++; if (company === "second") throw new Error("private"); return empty(); });
  assert.deepEqual(plain(await source("token", ["first", "second"])), unavailable);
  assert.equal(calls, 2);
  assert.deepEqual(plain(await source(null, ["first"])), unavailable);
  assert.equal(calls, 2);
  assert.deepEqual(plain(await source(null, [])), { ...unavailable, error: null });
});
test("Accounts presentation preserves opaque nested receipt, payload and call extensions", () => {
  const opaque = { original: { retained: [null, "ø", 42] }, legacyKey: true };
  const wire = { id: "submission", companyId: "company", incomeYear: 2025, filing: "årsregnskap",
    receiptMetadata: opaque, submittedPayloadRef: opaque, submittedPayload: opaque,
    calls: [{ endpoint: "/original", body_hash: "hash", idempotency_key: null, status: "accepted", created_at: "original-time", extension: opaque }],
    feedbackItems: [{ severity: "warning", code: "original", message: "Original", documentId: null, extension: opaque }],
  };
  const shown = presenters.presentAnnualAccountsSubmission(wire);
  assert.deepEqual(plain(shown.receipt_metadata), opaque);
  assert.deepEqual(plain(shown.submitted_payload_ref), opaque);
  assert.deepEqual(plain(shown.submitted_payload), opaque);
  assert.deepEqual(plain(shown.calls), wire.calls);
  assert.deepEqual(plain(shown.feedback_items), wire.feedbackItems);
});
const assessmentInput = { accessToken: "token", companyId: "company", incomeYear: 2025,
  annualData: { company_id: "company", original: true }, ledgerEntries: [{ company_id: "other" }, { company_id: "company", income_year: 2024 }],
  corporateEnabled: true, corporateBlockers: [{ level: "block", code: "missing", message: "Missing" }], sourceUnavailable: false };
function assessment(query) {
  return module("../apps/web/app/lib/annual-accounts-assessment-source.ts", { previewAnnualAccountsReadiness: query }).loadAnnualAccountsAssessmentSource;
}
test("Accounts assessment sends scoped original facts and preserves owned Corporate issues", async () => {
  const result = { companyId: "company", incomeYear: 2025, issues: assessmentInput.corporateBlockers };
  let calls = 0;
  const source = assessment(async (token, facts) => {
    calls++;
    assert.equal(token, "token");
    assert.deepEqual(plain(facts), { companyId: "company", incomeYear: 2025, annualData: assessmentInput.annualData,
      ledgerEntries: assessmentInput.ledgerEntries.slice(1), corporateEnabled: true, corporateBlockers: assessmentInput.corporateBlockers });
    return result;
  });
  assert.deepEqual(plain(await source(assessmentInput)), { readiness: result, error: null });
  assert.equal(calls, 1);
});
for (const change of [{ sourceUnavailable: true }, { accessToken: null }]) {
  test("unavailable readiness facts never become an empty clear assessment", async () => {
    const source = assessment(async () => { assert.fail("must not query"); });
    const value = await source({ ...assessmentInput, ...change });
    assert.equal(value.readiness, null);
    assert.ok(value.error);
  });
}
test("assessment transport failure returns explicit unavailable state", async () => {
  const value = await assessment(async () => { throw new Error("private"); })(assessmentInput);
  assert.equal(value.readiness, null);
  assert.ok(value.error);
});
