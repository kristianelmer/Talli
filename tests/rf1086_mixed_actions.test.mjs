import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const parsed = ts.createSourceFile("actions.ts", source, ts.ScriptTarget.Latest, true);
function action(name, dependencies) {
  const node = parsed.statements.find((value) => ts.isFunctionDeclaration(value) && value.name.text === name);
  assert.ok(node, name);
  const code = ts.transpileModule(node.getText(parsed).replace("export async", "async"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
  }).outputText;
  return new Function(...Object.keys(dependencies), `${code}\nreturn ${name};`)(...Object.values(dependencies));
}
const redirectSignal = Symbol("redirect");
const companyId = "10000000-0000-4000-8000-000000000001";
const preview = { id: "preview", company_id: companyId, income_year: 2025, filing: "skattemelding for AS" };
function setup({ owned = false, failure = false } = {}) {
  const effects = [];
  const result = { recordId: "record", companyId, incomeYear: 2025 };
  const form = new FormData();
  for (const [key, value] of Object.entries({ previewId: "preview", commentId: "comment", companyId,
    authorityConfirmed: "on", previewConfirmed: "on", ownerConfirmed: "on", fieldTarget: "company.name",
    oldValue: "Before", newValue: "After", reason: "Documented reason", riskLevel: "warning",
    severity: "advisory", body: "Review note", obligation: owned ? "aksjonaerregisteroppgaven" : "skattemelding",
    productionEnabled: "on", environment: "test", status: "accepted", testReference: "test-ref" })) form.set(key, value);
  const command = async () => { effects.push("canonical-write"); if (failure) throw new Error("unavailable"); return result; };
  const dependencies = {
    hasSupabaseEnv: () => true,
    createSupabaseServerClient: async () => ({
      auth: { getUser: async () => ({ data: { user: { id: "owner" } } }) },
      from(table) {
        let kind = "read";
        const chain = new Proxy({}, { get(_target, method) {
          if (method === "then") return (resolve) => {
            effects.push(`${table}:${kind}`);
            resolve({ data: table === "filing_review_comments" ? { id: "comment", company_id: companyId, severity: "advisory" } : preview, error: null });
          };
          return () => { if (["insert", "upsert", "update"].includes(method)) kind = method; return chain; };
        } });
        return chain;
      },
    }),
    formString: (data, key) => data.get(key) ?? "",
    getCurrentSessionAccessToken: async () => "verified-session",
    findRf1086Preview: async () => { effects.push("canonical-lookup"); if (failure) throw new Error("unavailable"); return owned ? preview : null; },
    presentRf1086Preview: (value) => value,
    acknowledgeOwnedRf1086Comment: async () => { effects.push("canonical-acknowledge"); if (failure) throw new Error("unavailable"); return owned ? result : null; },
    recordRf1086OverrideThroughApi: command,
    addRf1086ReviewCommentThroughApi: command,
    confirmRf1086SimulationThroughApi: command,
    confirmRf1086PermissionThroughApi: command,
    recordRf1086TestEvidenceThroughApi: command,
    rf1086ActionErrorMessage: () => "Unavailable",
    requireSensitiveActionStepUp: async () => { effects.push("step-up"); },
    validateAuthorityObligation: (value) => value,
    validateFilingOverride: (value) => { effects.push("validate-override"); return value; },
    assertAdvisoryCanBeAcknowledged: () => { effects.push("validate-advisory"); },
    buildAuthorityTestRun: () => ({ test_reference: "test-ref", feedback_summary: "ok", receipt_reference: null,
      archive_reference: null, evidence_url: null, payload_hash: null }),
    revalidatePath: () => {}, returnTarget: () => "/workspace",
    redirect: () => { throw redirectSignal; },
  };
  return { effects, form, dependencies };
}

for (const name of ["addFilingOverride", "addFilingReviewComment", "acknowledgeFilingReviewComment"]) {
  test(`${name} uses canonical ownership even when a public RF mirror exists`, async () => {
    const { effects, form, dependencies } = setup({ owned: true });
    await assert.rejects(action(name, dependencies)(form), (error) => error === redirectSignal);
    assert.deepEqual(effects.filter((value) => value.includes(":")), ["audit_events:insert"]);
    assert.ok(effects.indexOf(name === "acknowledgeFilingReviewComment" ? "canonical-acknowledge" : "canonical-write") < effects.indexOf("audit_events:insert"));
  });
  test(`${name} fails closed before any legacy effect when canonical ownership is unavailable`, async () => {
    const { effects, form, dependencies } = setup({ failure: true });
    await assert.rejects(action(name, dependencies)(form), (error) => error === redirectSignal);
    assert.deepEqual(effects.filter((value) => value.includes(":")), []);
  });
}
for (const [name, expected] of [
  ["addFilingOverride", ["canonical-lookup", "filing_previews:read", "validate-override", "filing_overrides:insert", "audit_events:insert"]],
  ["addFilingReviewComment", ["canonical-lookup", "filing_previews:read", "filing_review_comments:insert", "audit_events:insert"]],
  ["acknowledgeFilingReviewComment", ["canonical-acknowledge", "filing_review_comments:read", "validate-advisory", "filing_review_comments:update", "audit_events:insert"]],
]) {
  test(`${name} preserves the sibling validator, writer and subsequent audit`, async () => {
    const { effects, form, dependencies } = setup();
    await assert.rejects(action(name, dependencies)(form), (error) => error === redirectSignal);
    assert.deepEqual(effects, expected);
  });
}
test("RF simulation delegates all five retired persistence effects before its unchanged audit", async () => {
  const { effects, form, dependencies } = setup({ owned: true });
  await assert.rejects(action("confirmSimulatedRf1086Submission", dependencies)(form), (error) => error === redirectSignal);
  assert.deepEqual(effects, ["canonical-write", "audit_events:insert"]);
});
for (const [name, table, kind] of [["confirmAuthorityPermission", "authority_permissions", "upsert"], ["recordAuthorityTestEvidence", "authority_test_runs", "insert"]]) {
  for (const owned of [true, false]) test(`${name} preserves step-up and audit for ${owned ? "RF" : "sibling"}`, async () => {
    const { effects, form, dependencies } = setup({ owned });
    await assert.rejects(action(name, dependencies)(form), (error) => error === redirectSignal);
    assert.deepEqual(effects, ["step-up", owned ? "canonical-write" : `${table}:${kind}`, "audit_events:insert"]);
  });
}
