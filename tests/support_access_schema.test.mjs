import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const migration = readFileSync(
  new URL(
    "../supabase/migrations/20260830091341_case_bound_support_access.sql",
    import.meta.url,
  ),
  "utf8",
);
const rollback = readFileSync(
  new URL(
    "../supabase/rollback/20260830091341_case_bound_support_access.sql",
    import.meta.url,
  ),
  "utf8",
);
const adapter = readFileSync(
  new URL(
    "../apps/backend/src/talli_backend/adapters/supabase_company_access.py",
    import.meta.url,
  ),
  "utf8",
);
const webServer = readFileSync(
  new URL("../apps/web/app/lib/supabase/server.ts", import.meta.url),
  "utf8",
);
const openApi = JSON.parse(
  readFileSync(
    new URL("../contracts/openapi/talli-v1.json", import.meta.url),
    "utf8",
  ),
);
const generatedClient = readFileSync(
  new URL(
    "../packages/talli-api-client/src/generated/client.ts",
    import.meta.url,
  ),
  "utf8",
);

const supportResourceKeys = [
  "companies",
  "auditEvents",
  "companyCancellations",
  "filingSubmissions",
  "filingReadinessSnapshots",
  "billingAccounts",
  "billingPaymentEvents",
  "authorityPermissions",
  "authorityTestRuns",
  "systemUserRequests",
  "productionPilotEntitlements",
  "filingApprovalSnapshots",
  "productionFilingSubmissions",
  "productionFilingEvents",
  "productionFeedbackArtifacts",
  "documents",
  "storageObjects",
  "companyDeletionReviews",
];

const supportFunctions = [
  "company_access_grant_support_access",
  "company_access_revoke_support_access",
  "company_access_open_support_case",
  "company_access_read_support_case",
];

test("support grants use generated case IDs, enums, exact scopes, and bounded windows", () => {
  assert.match(
    migration,
    /case_id uuid primary key default gen_random_uuid\(\)/iu,
  );
  assert.doesNotMatch(migration, /case_reference/iu);
  for (const reason of [
    "customer_request",
    "security_incident",
    "service_recovery",
    "legal_obligation",
  ]) {
    assert.match(migration, new RegExp(`'${reason}'`, "u"));
  }
  for (const scope of [
    "profile",
    "filing",
    "billing",
    "audit",
    "cancellation",
    "authority",
    "documents",
    "production",
  ]) {
    assert.match(migration, new RegExp(`'${scope}'`, "u"));
  }
  assert.match(migration, /expires_at <= starts_at \+ interval '8 hours'/iu);
  assert.match(
    migration,
    /statement_timestamp\(\) >= g\.starts_at[\s\S]+statement_timestamp\(\) < g\.expires_at/iu,
  );
});

test("command receipts bind canonical SHA-256 fingerprints and reject operation reuse", () => {
  assert.match(migration, /request_fingerprint text not null/iu);
  assert.match(migration, /extensions\.digest\(v_request::text, 'sha256'\)/iu);
  assert.match(migration, /request_fingerprint ~ '\^\[0-9a-f\]\{64\}\$'/iu);
  for (const command of [
    "grant_support_access",
    "revoke_support_access",
    "open_support_case",
  ]) {
    assert.match(
      migration,
      new RegExp(
        `command_name <> '${command}'[\\s\\S]+request_fingerprint <> v_fingerprint`,
        "iu",
      ),
    );
  }
  assert.match(migration, /primary key \(actor_id, operation_id\)/iu);
  assert.match(
    migration,
    /company_access_lock_operation_v1\(v_actor_id, p_operation_id\)/iu,
  );
});

test("authorization requires exact opened case, company, scope, operator, time, revocation, and fresh MFA", () => {
  const helper =
    migration.match(
      /create or replace function public\.company_access_has_open_support_case_v1\([\s\S]+?\$function\$\s*;/iu,
    )?.[0] ?? "";
  assert.match(
    helper,
    /p_case_id = public\.company_access_current_support_case_id_v1\(\)/iu,
  );
  assert.match(
    helper,
    /g\.operator_user_id = public\.company_access_auth_uid_v1\(\)/iu,
  );
  assert.match(helper, /g\.company_id = p_company_id/iu);
  assert.match(helper, /p_scope = any \(g\.scopes\)/iu);
  assert.match(helper, /g\.revoked_at is null/iu);
  assert.match(helper, /company_access_is_active_operator_v1\(\)/iu);
  assert.match(helper, /company_access_has_fresh_mfa_v1\(\)/iu);
  assert.match(helper, /from public\.support_case_openings o/iu);
});

test("the exact support resource surface is policy-bound and malformed storage paths fail closed", () => {
  const policyTargets = [
    "companies",
    "audit_events",
    "filing_submissions",
    "filing_readiness_snapshots",
    "billing_accounts",
    "billing_payment_events",
    "authority_permissions",
    "authority_test_runs",
    "system_user_requests",
    "production_pilot_entitlements",
    "filing_approval_snapshots",
    "production_filing_submissions",
    "production_filing_events",
    "production_feedback_artifacts",
    "documents",
    "storage.objects",
    "company_cancellations",
    "company_deletion_reviews",
  ];
  for (const target of policyTargets) {
    const qualifiedTarget = target.includes(".") ? target : `public.${target}`;
    assert.match(
      migration,
      new RegExp(`on ${qualifiedTarget.replace(".", "\\.")}`, "iu"),
    );
  }
  assert.match(
    migration,
    /company_access_support_storage_company_id_v1\(name\)/iu,
  );
  assert.match(
    migration,
    /v_candidate !~\*[\s\S]+return null[\s\S]+exception when others then[\s\S]+return null/iu,
  );
});

test("support tables and RPCs are backend-executor only", () => {
  assert.match(
    migration,
    /revoke all on table public\.support_access_grants,[\s\S]+from public, anon, authenticated, service_role/iu,
  );
  const aclBlock =
    migration.match(
      /revoke all on function public\.company_access_current_support_case_id_v1\(\)[\s\S]+?to company_access_executor;/iu,
    )?.[0] ?? "";
  for (const functionName of supportFunctions) {
    assert.match(aclBlock, new RegExp(`public\\.${functionName}`, "u"));
  }
  assert.match(aclBlock, /from public, anon, authenticated, service_role/iu);
  assert.match(aclBlock, /to company_access_executor/iu);
  assert.match(
    migration,
    /revoke all on function public\.company_access_bind_deletion_review_case_v1\(\),[\s\S]+public\.company_access_copy_review_case_v1\(\),[\s\S]+company_access_support_review_operation_available_v1\(uuid, uuid\)[\s\S]+from public, anon, authenticated, service_role/iu,
  );
});

test("grant and revoke are admin plus fresh-MFA commands while open/read are operator plus fresh-MFA", () => {
  for (const name of ["grant", "revoke"]) {
    const body =
      migration.match(
        new RegExp(
          `create or replace function public\\.company_access_${name}_support_access[\\s\\S]+?\\$function\\$\\s*;`,
          "iu",
        ),
      )?.[0] ?? "";
    assert.match(body, /company_access_is_active_admin_v1\(\)/iu);
    assert.match(body, /company_access_has_fresh_mfa_v1\(\)/iu);
  }
  for (const name of ["open", "read"]) {
    const body =
      migration.match(
        new RegExp(
          `create or replace function public\\.company_access_${name}_support_case[\\s\\S]+?\\$function\\$\\s*;`,
          "iu",
        ),
      )?.[0] ?? "";
    assert.match(body, /company_access_is_active_operator_v1\(\)/iu);
    assert.match(body, /company_access_has_fresh_mfa_v1\(\)/iu);
  }
});

test("GET is a bounded read projection and only POST open creates opening/audit/receipt evidence", () => {
  const read =
    migration.match(
      /create or replace function public\.company_access_read_support_case\([\s\S]+?\$function\$\s*;/iu,
    )?.[0] ?? "";
  assert.match(read, /jsonb_build_object/iu);
  for (const resource of [
    "companies",
    "audit_events",
    "company_cancellations",
    "filing_submissions",
    "filing_readiness_snapshots",
    "billing_accounts",
    "billing_payment_events",
    "authority_permissions",
    "authority_test_runs",
    "system_user_requests",
    "production_pilot_entitlements",
    "filing_approval_snapshots",
    "production_filing_submissions",
    "production_filing_events",
    "production_feedback_artifacts",
    "documents",
    "storage_objects",
    "company_deletion_reviews",
  ]) {
    assert.match(read, new RegExp(`'${resource}'`, "u"));
  }
  assert.doesNotMatch(read, /insert into|update public|delete from/iu);
  const open =
    migration.match(
      /create or replace function public\.company_access_open_support_case\([\s\S]+?\$function\$\s*;/iu,
    )?.[0] ?? "";
  assert.match(open, /insert into public\.support_case_openings/iu);
  assert.match(open, /'support_case_opened'/iu);
  assert.match(open, /insert into public\.support_access_operation_receipts/iu);
});

test("the generated support contract requires the exact typed 18-resource projection", () => {
  const schema = openApi.components.schemas.SupportCaseResources;
  const sortedResourceKeys = supportResourceKeys.toSorted();
  assert.deepEqual(schema.required.toSorted(), sortedResourceKeys);
  assert.deepEqual(Object.keys(schema.properties).toSorted(), sortedResourceKeys);
  for (const resource of supportResourceKeys) {
    assert.equal(schema.properties[resource].type, "array");
    assert.ok(schema.properties[resource].items.$ref);
  }
  const generatedResources =
    generatedClient.match(
      /export interface SupportCaseResources \{[\s\S]+?\n\}/u,
    )?.[0] ?? "";
  for (const resource of supportResourceKeys) {
    assert.match(generatedResources, new RegExp(`\\b${resource}:`, "u"));
  }
  assert.doesNotMatch(generatedResources, /Record<string/u);
});

test("deletion review and reconciliation require the exact support case", () => {
  assert.match(
    migration,
    /company_access_review_deletion\(\s*p_operation_id uuid,\s*p_support_case_id uuid/iu,
  );
  assert.match(
    migration,
    /company_access_reconcile_cancellation_operation\(\s*p_operation_id uuid,[\s\S]+p_support_case_id uuid/iu,
  );
  assert.match(
    migration,
    /support_case_id = public\.company_access_current_support_case_id_v1\(\)/iu,
  );
  assert.match(
    migration,
    /company_access_support_review_operation_available_v1\([\s\S]+support_access_operation_conflict/iu,
  );
});

test("active web and backend adapters have no customer-directory support search or direct business reads", () => {
  assert.match(adapter, /"company_access_open_support_case"/u);
  assert.match(adapter, /"company_access_read_support_case"/u);
  assert.doesNotMatch(adapter, /org_number ilike|name ilike/iu);
  assert.doesNotMatch(webServer, /searchOperatorSupportDashboard/u);
  const supportRead =
    webServer.match(
      /export async function readOperatorSupportDashboard[\s\S]+?\n\}/u,
    )?.[0] ?? "";
  assert.match(supportRead, /readOperatorSupportCase/u);
  for (const table of [
    "billing_accounts",
    "billing_payment_events",
    "filing_readiness_snapshots",
    "authority_permissions",
    "filing_submissions",
    "audit_events",
  ]) {
    assert.doesNotMatch(
      supportRead,
      new RegExp(`\\.from\\(\\s*["']${table}["']`, "u"),
    );
  }
});

test("rollback disables support without restoring standing operator access or deleting evidence", () => {
  assert.match(rollback, /select false/iu);
  assert.match(
    rollback,
    /revoke all on function public\.company_access_grant_support_access/iu,
  );
  assert.doesNotMatch(
    rollback,
    /drop table|truncate|delete from public\.support_/iu,
  );
  assert.doesNotMatch(
    rollback,
    /operator_support_(read|select)|search_operator/iu,
  );
});
