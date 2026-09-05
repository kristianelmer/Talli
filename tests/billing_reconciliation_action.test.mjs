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

for (const reason of ["expired", "suspended", "readiness_changed"]) {
  test(`pending filing feedback remains recoverable after ${reason}`, async () => {
    const companyId = "10000000-0000-4000-8000-000000000001";
    const userId = "20000000-0000-4000-8000-000000000001";
    const submissionId = "30000000-0000-4000-8000-000000000001";
    const obligation = "aksjonaerregisteroppgaven";
    const profile = "rf1086_no_activity_v1";
    const submission = { id: submissionId, approval_id: "approval", entitlement_id: "pilot", company_id: companyId,
      user_id: userId, income_year: 2025, obligation, case_profile: profile,
      environment: "production", feedback_state: "processing" };
    const rows = {
      production_filing_submissions: submission,
      filing_approval_snapshots: { ...submission, id: "approval", preview_id: "preview", invalidated_at: null },
      system_user_requests: { id: "request", company_id: companyId, initiating_owner_user_id: userId,
        obligation, external_ref: "system-user", status: "accepted", preflight_verified_at: "2026-01-01" },
      filing_previews: { company_id: companyId, income_year: 2025, hovedskjema_xml: "<form/>", underskjema_xml: {} },
    };
    const pilot = { entitlementId: "pilot", companyId, userId, incomeYear: 2025, obligation, caseProfile: profile,
      systemUserRequestId: "request", systemUserExternalReference: "system-user",
      status: reason === "suspended" ? "suspended" : "active", expiresAt: "2025-12-31" };
    let reconciliations = 0;
    let claims = 0;
    const supabase = {
      auth: { getUser: async () => ({ data: { user: { id: userId } } }) },
      from(table) {
        const query = { select: () => query, eq: () => query, single: async () => ({ data: rows[table], error: null }) };
        return query;
      },
    };
    const dependencies = {
      requiredFormUuid: (form, key) => form.get(key),
      hasSupabaseEnv: () => true,
      createSupabaseServerClient: async () => supabase,
      getCurrentSessionAccessToken: async () => "local-test-session",
      buildRf1086OwnerReconciliationActionState: (state, options = {}) => ({ state, ...options }),
      loadAcceptedMembershipCompany: async () => ({ id: companyId, role: "owner", org_number: "123456789" }),
      loadBillingSnapshot: async () => ({ pilotEntitlements: [pilot] }),
      loadBillingEntitlement: async () => ({ allowed: false, pilotEntitlementId: reason === "readiness_changed" ? "pilot" : null }),
      rf1086ProductionEnvironment: () => ({}),
      createSupabaseServiceRoleClient: () => ({ rpc: async (name) => {
        assert.ok(["claim_production_feedback_reconciliation", "release_production_feedback_reconciliation"].includes(name));
        if (name === "claim_production_feedback_reconciliation") claims += 1;
        return { error: null, data: true };
      } }),
      randomUUID: () => "lease",
      readClaimedRf1086ForsendelseId: async () => "stored-forsendelse",
      requestMaskinportenToken: async () => ({ accessToken: "local-test-token" }),
      createRf1086FeedbackJournal: () => ({}),
      createRf1086AuthorityClient: () => ({}),
      reconcileJournaledRf1086Production: async (_journal, _authority, input, options) => {
        assert.equal(input.forsendelseId, "stored-forsendelse");
        assert.equal(options.initialPoll, false);
        reconciliations += 1;
        return { state: "accepted" };
      },
      revalidatePath: () => {},
      reportRf1086ProductionFailure: (_operation, error) => { throw error; },
    };
    const action = new Function(...Object.keys(dependencies), `${actionCode}\nreturn reconcileRf1086ProductionAction;`)(...Object.values(dependencies));
    const form = new FormData();
    form.set("submissionId", submissionId);
    const result = await action({}, form);
    assert.deepEqual(result, { state: "accepted" });
    assert.equal(claims, 1);
    assert.equal(reconciliations, 1);
    dependencies.loadAcceptedMembershipCompany = async () => ({ id: companyId, role: "member" });
    const deniedAction = new Function(...Object.keys(dependencies), `${actionCode}\nreturn reconcileRf1086ProductionAction;`)(...Object.values(dependencies));
    assert.equal((await deniedAction({}, form)).errorCode, "basis_unavailable");
    assert.equal(claims, 1, "a non-owner cannot claim feedback reconciliation");
    assert.equal(reconciliations, 1);

  });
}
