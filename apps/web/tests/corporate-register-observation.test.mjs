import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";
import { corporateRegisterFact, corporateRegisterObservations, needsCorporateRegisterObservation } from "../app/lib/corporate-register-observation.ts";

const companyId = "10000000-0000-4000-8000-000000000001";
const otherCompany = "10000000-0000-4000-8000-000000000002";
const id = n => `20000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const day = "2025-10-26";
const observation = (n = 1) => ({
  receipt: { observationId: id(n), companyId, incomeYear: 2025, version: 7, factSha256: "a".repeat(64), confirmedAt: "2025-10-27T10:00:00Z" },
  draft: { companyId, incomeYear: 2025, eventKind: "cash_issue", effectiveAt: `${day}T00:30:00`,
    before: { shareCount: 100 }, after: { shareCount: 110 }, documents: [{ documentId: id(90), role: "register_before" }] },
  isCurrent: true,
});
const source = (observations = [observation()]) => ({ companyId, incomeYear: 2025, observations });
const select = data => corporateRegisterObservations(data, companyId, 2025, "cash_capital_increase", day);
const resolve = (data = source(), selectedId = id(1)) => corporateRegisterFact(data, companyId, 2025, "cash_capital_increase", day, selectedId);

test("registered capital phases require explicit independent register evidence", () => {
  for (const [kind, phase, expected] of [
    ["cash_capital_increase", "registered", true], ["cash_capital_increase", "binding_subscription", false],
    ["cash_capital_increase", "restricted_payment", false], ["loss_coverage_capital_reduction", "registered", true],
    ["loss_coverage_capital_reduction", "first_recognized_after_registration", true],
    ["loss_coverage_capital_reduction", "decided_not_registered", false], ["owner_loan", "funding", false],
    ["group_contribution", "decision", false],
  ]) assert.equal(needsCorporateRegisterObservation(kind, phase), expected);
});

test("multiple independent current observations remain explicit choices and preserve original references", () => {
  const data = source([observation(), observation(2)]);
  assert.deepEqual(select(data), data.observations);
  assert.strictEqual(select(data)[0].draft.documents, data.observations[0].draft.documents);
  assert.throws(() => resolve(data, ""));
  assert.deepEqual(resolve(data, id(2)), { recordId: id(2), revision: 7, factSha256: "a".repeat(64) });
});

test("civil effective date matches without timezone conversion", () => {
  assert.equal(select(source()).length, 1);
  assert.equal(corporateRegisterObservations(source(), companyId, 2025, "cash_capital_increase", "2025-10-25").length, 0);
  assert.equal(corporateRegisterObservations(source(), companyId, 2025, "cash_capital_increase", "").length, 0);
});

for (const [label, change] of [
  ["historical observation", row => { row.isCurrent = false; }],
  ["different event kind", row => { row.draft.eventKind = "loss_covering_reduction"; }],
  ["unsupported nominal-only increase", row => { row.draft.eventKind = "cash_nominal_increase"; }],
  ["different effective date", row => { row.draft.effectiveAt = "2025-10-27T00:30:00"; }],
  ["foreign receipt company", row => { row.receipt.companyId = otherCompany; }],
  ["foreign draft company", row => { row.draft.companyId = otherCompany; }],
  ["foreign receipt year", row => { row.receipt.incomeYear = 2024; }],
  ["foreign draft year", row => { row.draft.incomeYear = 2024; }],
]) test(`rejects ${label}`, () => {
  const row = observation(); change(row);
  assert.deepEqual(select(source([row])), []);
  assert.throws(() => resolve(source([row])));
});

test("wrong envelope scope, invented IDs and ambiguous duplicate receipts are rejected", () => {
  assert.throws(() => resolve({ ...source(), companyId: otherCompany }));
  assert.throws(() => resolve({ ...source(), incomeYear: 2024 }));
  assert.throws(() => resolve(source(), id(99)));
  assert.throws(() => resolve(source([observation(), observation()])));
});

test("loss-covering reduction matches its own current observation", () => {
  const row = observation(); row.draft.eventKind = "loss_covering_reduction";
  assert.equal(corporateRegisterObservations(source([row]), companyId, 2025, "loss_coverage_capital_reduction", day).length, 1);
  assert.deepEqual(select(source([row])), []);
});

// Execute the real server action with its imports supplied at the application boundary.
const actionsText = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const parsed = ts.createSourceFile("actions.ts", actionsText, ts.ScriptTarget.Latest, true);
const actionNames = new Set(["supportedDocumentFact", "checked", "recordSupportedCorporateEventAction"]);
const extracted = parsed.statements.filter(node => ts.isFunctionDeclaration(node) && actionNames.has(node.name?.text))
  .map(node => node.getText(parsed)).join("\n");
assert.equal(parsed.statements.filter(node => ts.isFunctionDeclaration(node) && actionNames.has(node.name?.text)).length, 3);
const compiled = ts.transpileModule(extracted, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
function actionHarness({ data = source(), readError = false } = {}) {
  const calls = [], writes = [];
  const context = {
    exports: {}, corporateRegisterFact, needsCorporateRegisterObservation,
    returnTarget: () => "/actions", hasSupabaseEnv: () => true,
    createSupabaseServerClient: async () => ({ auth: { getUser: async () => ({ data: { user: { id: id(8) } } }) } }),
    failTo: (_path, message) => { throw new Error(message); },
    formString: (form, name) => String(form.get(name) ?? ""),
    requiredFormUuid: (form, name) => { const value = form.get(name); if (!value) throw new Error(`missing ${name}`); return value; },
    requireSensitiveActionStepUp: async () => { calls.push("step-up"); },
    getCurrentSessionAccessToken: async () => "verified-owner",
    loadRf1086RegisterObservations: async (...args) => { calls.push(args); if (readError) throw new Error("unavailable"); return data; },
    rf1086RegisterErrorMessage: () => "Register read unavailable",
    recordSupportedCorporateEventThroughApi: async (...args) => { writes.push(JSON.parse(JSON.stringify(args))); },
    revalidatePath: () => {}, succeedTo: () => "done",
  };
  vm.runInNewContext(compiled, context);
  return { run: context.exports.recordSupportedCorporateEventAction, calls, writes };
}
function form(kind = "cash_capital_increase", phase = "registered") {
  const result = new FormData();
  for (const [key, value] of Object.entries({ companyId, incomeYear: "2025", operationId: id(3), eventReference: id(4),
    eventKind: kind, phase, eventDate: day, registerObservationId: id(1),
    sourceKind: "shareholder_register", sourceDocumentId: id(90), sourceDocumentHash: "f".repeat(64),
    registerObservationRevision: "999", registerObservationHash: "b".repeat(64),
  })) result.set(key, value);
  return result;
}

test("server action rereads scoped current observation and ignores all client revision/hash/document claims", async () => {
  const h = actionHarness(); await h.run(form());
  assert.deepEqual(h.calls, ["step-up", ["verified-owner", companyId, 2025]]);
  assert.equal(h.writes.length, 1);
  const [token, body, key, correlation] = h.writes[0];
  assert.equal(token, "verified-owner"); assert.equal(key, id(3)); assert.equal(correlation, id(3));
  assert.deepEqual(body.shareholderRegisterFact, { recordId: id(1), revision: 7, factSha256: "a".repeat(64) });
  assert.equal(body.taxCalculationFact, null);
});

for (const [label, options] of [
  ["source read unavailable", { readError: true }],
  ["selected observation superseded after render", { data: source([{ ...observation(), isCurrent: false }]) }],
  ["selected observation absent", { data: source([]) }],
]) test(`server action fails before Governance write when ${label}`, async () => {
  const h = actionHarness(options); await assert.rejects(h.run(form())); assert.equal(h.writes.length, 0);
});

test("capital registration cannot fall back to generic document when explicit observation is missing", async () => {
  const h = actionHarness(); const submitted = form(); submitted.delete("registerObservationId");
  await assert.rejects(h.run(submitted), /registerObservationId/);
  assert.equal(h.writes.length, 0);
});

test("tax calculation behavior and noncapital phases remain unchanged without RF reads", async () => {
  const h = actionHarness({ readError: true }); const submitted = form("group_contribution", "decision");
  submitted.set("sourceKind", "tax_calculation");
  await h.run(submitted);
  assert.deepEqual(h.calls, ["step-up"]);
  assert.equal(h.writes[0][1].shareholderRegisterFact, null);
  assert.deepEqual(h.writes[0][1].taxCalculationFact, { recordId: id(90), revision: 1, factSha256: "f".repeat(64) });
  const pre = actionHarness({ readError: true }); await pre.run(form("cash_capital_increase", "binding_subscription"));
  assert.deepEqual(pre.calls, ["step-up"]); assert.equal(pre.writes[0][1].shareholderRegisterFact, null);
});
