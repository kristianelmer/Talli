import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import test from "node:test";

const migrations = readdirSync(new URL("../supabase/migrations/", import.meta.url));
const matches = migrations.filter((file) => file.endsWith("_rf1086_system_user_requests.sql"));
assert.equal(matches.length, 1, "Expected exactly one Systembruker request migration");

const sql = readFileSync(
  new URL(`../supabase/migrations/${matches[0]}`, import.meta.url),
  "utf8",
);
const rollback = readFileSync(
  new URL("../supabase/rollback/rf1086_system_user_requests.sql", import.meta.url),
  "utf8",
);
const server = readFileSync(
  new URL("../apps/web/app/lib/supabase/server.ts", import.meta.url),
  "utf8",
);

function functionSql(name) {
  return sql.match(
    new RegExp(`create or replace function public\\.${name}\\([\\s\\S]+?\\n\\$\\$;`, "iu"),
  )?.[0] ?? "";
}

test("request persistence is owner-readable and mutation is RPC-only", () => {
  assert.match(sql, /create table (?:if not exists )?public\.system_user_requests/iu);
  assert.match(sql, /initiating_owner_user_id uuid not null/iu);
  assert.match(sql, /preflight_verified_at timestamptz/iu);
  assert.match(sql, /alter table public\.system_user_requests enable row level security/iu);
  assert.match(
    sql,
    /revoke all on (?:table )?public\.system_user_requests from public, anon, authenticated, service_role/iu,
  );
  assert.match(sql, /grant select on (?:table )?public\.system_user_requests to authenticated/iu);
  assert.doesNotMatch(
    sql,
    /grant\s+(?:insert|update|delete)[^;]*system_user_requests[^;]*authenticated/iu,
  );
  assert.match(
    sql,
    /grant execute on function public\.begin_system_user_request\(uuid, uuid, text\)\s+to authenticated/iu,
  );
});

test("RLS isolates an initiating owner and permits active operator metadata reads", () => {
  const ownerPolicy = sql.match(
    /create policy system_user_requests_owner_read[\s\S]+?\n\);/iu,
  )?.[0] ?? "";
  assert.match(ownerPolicy, /initiating_owner_user_id = \(select auth\.uid\(\)\)/iu);
  assert.match(ownerPolicy, /m\.company_id = system_user_requests\.company_id/iu);
  assert.match(ownerPolicy, /m\.user_id = \(select auth\.uid\(\)\)/iu);
  assert.match(ownerPolicy, /m\.role = 'owner'/iu);
  assert.match(ownerPolicy, /m\.accepted_at is not null/iu);

  const operatorPolicy = sql.match(
    /create policy system_user_requests_operator_read[\s\S]+?\n\);/iu,
  )?.[0] ?? "";
  assert.match(operatorPolicy, /o\.user_id = \(select auth\.uid\(\)\)/iu);
  assert.match(operatorPolicy, /o\.active/iu);
  assert.doesNotMatch(sql, /create policy[^;]+system_user_requests[^;]+for (?:insert|update|delete)/isu);
});

test("request RPCs use fixed signatures, safe search paths, and least privilege", () => {
  assert.match(
    sql,
    /create or replace function public\.record_system_user_authority_state\(\s*p_request_id uuid,\s*p_company_id uuid,\s*p_altinn_request_id uuid,\s*p_external_ref text,\s*p_status text,\s*p_confirm_url text,\s*p_failure_code text,\s*p_operator_evidence_id uuid\s*\)/iu,
  );
  assert.match(
    sql,
    /create or replace function public\.verify_system_user_preflight\(\s*p_request_id uuid,\s*p_expected_external_ref text\s*\)/iu,
  );
  for (const functionName of [
    "begin_system_user_request",
    "record_system_user_authority_state",
    "verify_system_user_preflight",
  ]) {
    const source = functionSql(functionName);
    assert.match(source, /security definer/iu);
    assert.match(source, /set search_path = ''/iu);
  }
  assert.match(
    sql,
    /revoke all on function public\.record_system_user_authority_state\(uuid, uuid, uuid, text, text, text, text, uuid\)\s+from public, anon, authenticated, service_role/iu,
  );
  assert.match(
    sql,
    /grant execute on function public\.record_system_user_authority_state\(uuid, uuid, uuid, text, text, text, text, uuid\)\s+to service_role/iu,
  );
  assert.match(
    sql,
    /grant execute on function public\.verify_system_user_preflight\(uuid, text\)\s+to service_role/iu,
  );
  assert.doesNotMatch(
    sql,
    /grant execute on function public\.(?:record_system_user_authority_state|verify_system_user_preflight)[^;]+to authenticated/isu,
  );
  assert.match(
    sql,
    /begin_system_user_request\([\s\S]+?auth\.jwt\(\)[\s\S]+?'authenticated'[\s\S]+?public\.assert_fresh_production_owner/iu,
  );
  assert.match(
    sql,
    /record_system_user_authority_state\([\s\S]+?auth\.jwt\(\)[\s\S]+?'service_role'/iu,
  );
  assert.match(
    sql,
    /verify_system_user_preflight\([\s\S]+?auth\.jwt\(\)[\s\S]+?'service_role'/iu,
  );
});

test("state reconciliation locks one request and enforces exact relationships and transitions", () => {
  const source = functionSql("record_system_user_authority_state");
  assert.match(source, /where r\.id = p_request_id[\s\S]+for update/iu);
  assert.match(source, /v_request\.company_id is distinct from p_company_id/iu);
  assert.match(source, /v_request\.external_ref is distinct from p_external_ref/iu);
  assert.match(source, /v_request\.altinn_request_id is not null[\s\S]+p_altinn_request_id/iu);
  assert.match(source, /from public\.company_memberships[\s\S]+m\.user_id = v_request\.initiating_owner_user_id/iu);
  assert.match(source, /v_request\.status = 'creating'[\s\S]+p_status in \([^)]*'new'[^)]*'accepted'/iu);
  assert.match(source, /v_request\.status = 'accepted'[\s\S]+p_status in \('accepted', 'verification_failed'\)/iu);
  assert.match(source, /v_request\.status = 'verification_failed'[\s\S]+p_status in \('verification_failed', 'accepted'\)/iu);
  assert.match(source, /invalid_system_user_transition/iu);
  assert.match(source, /p_failure_code not in \(/iu);
  assert.match(source, /public\.authority_operations/iu);
  assert.match(source, /requested_at =/iu);
  assert.match(source, /last_status_checked_at =/iu);
  assert.match(source, /accepted_at =/iu);
  assert.match(source, /resolved_at =/iu);
  assert.match(source, /updated_at =/iu);
});

test("confirmation URLs are reconstructed as one exact production URL", () => {
  const source = functionSql("record_system_user_authority_state");
  assert.match(
    sql,
    /add constraint system_user_requests_confirm_url_canonical[\s\S]+confirm_url = \(\s*'https:\/\/am\.ui\.altinn\.no\/accessmanagement\/ui\/systemuser\/request\?id='\s*\|\| altinn_request_id::text/iu,
  );
  assert.match(
    source,
    /v_canonical_confirm_url :=\s*'https:\/\/am\.ui\.altinn\.no\/accessmanagement\/ui\/systemuser\/request\?id='\s*\|\| v_effective_altinn_request_id::text/iu,
  );
  assert.match(source, /p_confirm_url is distinct from v_canonical_confirm_url/iu);
  assert.match(source, /confirm_url = case[\s\S]+v_canonical_confirm_url/iu);
  assert.doesNotMatch(source, /at22|tt02|regexp_count/iu);
});

test("terminal self-reconciliation only refreshes safe timestamps", () => {
  const source = functionSql("record_system_user_authority_state");
  const terminalGuard = source.indexOf("v_request.status in ('rejected', 'denied', 'timedout')");
  const generalUpdate = source.indexOf("set altinn_request_id = v_effective_altinn_request_id");
  assert.ok(terminalGuard >= 0, "terminal self-transition guard is present");
  assert.ok(generalUpdate > terminalGuard, "terminal guard runs before the general evidence update");
  assert.match(source.slice(terminalGuard, generalUpdate), /p_altinn_request_id is distinct from v_request\.altinn_request_id/iu);
  assert.match(source.slice(terminalGuard, generalUpdate), /p_confirm_url is distinct from v_request\.confirm_url/iu);
  assert.match(source.slice(terminalGuard, generalUpdate), /p_failure_code is distinct from v_request\.failure_code/iu);
  assert.match(source.slice(terminalGuard, generalUpdate), /p_operator_evidence_id is distinct from v_request\.operator_evidence_id/iu);
  assert.match(source.slice(terminalGuard, generalUpdate), /system_user_request_terminal_evidence_immutable/iu);
  assert.match(
    source.slice(terminalGuard, generalUpdate),
    /set last_status_checked_at = v_now,\s*updated_at = v_now/iu,
  );
});

test("foreign keys and RLS join predicates have supporting indexes", () => {
  for (const index of [
    "system_user_requests_one_live_company_obligation",
    "system_user_requests_company_idx",
    "system_user_requests_owner_idx",
    "system_user_requests_operator_evidence_idx",
    "production_pilot_entitlements_system_user_request_idx",
  ]) {
    assert.match(sql, new RegExp(`create (?:unique )?index if not exists ${index}`, "iu"));
  }
});

test("active entitlements bind to the exact accepted preflight-verified request", () => {
  assert.match(
    sql,
    /add column if not exists system_user_request_id uuid\s+references public\.system_user_requests\(id\) on delete restrict/iu,
  );
  assert.match(
    sql,
    /production_pilot_entitlements_verified_request_required[\s\S]+status <> 'active'[\s\S]+system_user_request_id is not null/iu,
  );
  assert.match(
    sql,
    /create or replace function public\.manage_production_pilot_entitlement\(\s*p_id uuid,\s*p_company_id uuid,\s*p_user_id uuid,\s*p_income_year integer,\s*p_status text,\s*p_billing_exempt boolean,\s*p_system_user_request_id uuid,/iu,
  );
  assert.match(sql, /v_request\.company_id <> p_company_id/iu);
  assert.match(sql, /v_request\.initiating_owner_user_id <> p_user_id/iu);
  assert.match(sql, /v_request\.status <> 'accepted'/iu);
  assert.match(sql, /v_request\.preflight_verified_at is null/iu);
  assert.match(sql, /system_user_external_reference[\s\S]+v_request\.external_ref/iu);

  const beginSql = functionSql("begin_production_filing");
  assert.match(beginSql, /v_request\.initiating_owner_user_id <> v_actor_id/iu);
  assert.match(beginSql, /v_request\.company_id <> v_approval\.company_id/iu);
  assert.match(beginSql, /v_request\.obligation <> v_approval\.obligation/iu);
  assert.match(beginSql, /v_request\.status <> 'accepted'/iu);
  assert.match(beginSql, /v_request\.preflight_verified_at is null/iu);
  assert.match(beginSql, /v_request\.external_ref <> v_entitlement\.system_user_external_reference/iu);
});

test("authorization RPCs serialize request invalidation, entitlement changes, and begin", () => {
  const recordSql = functionSql("record_system_user_authority_state");
  const manageSql = functionSql("manage_production_pilot_entitlement");
  const beginSql = functionSql("begin_production_filing");

  const recordRequestLock = recordSql.indexOf("where r.id = p_request_id");
  const recordSuspend = recordSql.indexOf("update public.production_pilot_entitlements");
  assert.ok(recordRequestLock >= 0 && recordSuspend > recordRequestLock);
  assert.match(recordSql.slice(recordRequestLock, recordSuspend), /for update/iu);
  assert.match(recordSql.slice(recordSuspend), /where system_user_request_id = v_request\.id\s+and status = 'active'/iu);

  const manageRequestLock = manageSql.indexOf("where r.id = p_system_user_request_id");
  const manageEntitlementLock = manageSql.indexOf("from public.production_pilot_entitlements e");
  assert.ok(manageRequestLock >= 0 && manageEntitlementLock > manageRequestLock);
  assert.match(manageSql.slice(manageRequestLock, manageEntitlementLock), /for update/iu);
  assert.match(manageSql.slice(manageEntitlementLock), /for update/iu);
  assert.doesNotMatch(manageSql, /for key share/iu);

  const beginRequestLockSql = beginSql.match(
    /select r\.\*\s+into v_request\s+from public\.system_user_requests r[\s\S]+?for update;/iu,
  )?.[0] ?? "";
  const beginEntitlementLockSql = beginSql.match(
    /select e\.\*\s+into v_entitlement\s+from public\.production_pilot_entitlements e[\s\S]+?for update;/iu,
  )?.[0] ?? "";
  const beginRequestLock = beginSql.indexOf(beginRequestLockSql);
  const beginEntitlementLock = beginSql.indexOf(beginEntitlementLockSql);
  const beginInsert = beginSql.indexOf("insert into public.production_filing_submissions");
  assert.ok(beginRequestLockSql && beginEntitlementLockSql);
  assert.ok(beginRequestLock >= 0 && beginEntitlementLock > beginRequestLock);
  assert.ok(beginInsert > beginEntitlementLock);
  assert.match(beginRequestLockSql, /for update;/iu);
  assert.match(beginEntitlementLockSql, /for update;/iu);
});

test("rollback revokes first, restores old controlled-beta functions, then drops dependencies", () => {
  const revokeIndex = rollback.indexOf(
    "revoke all on function public.record_system_user_authority_state",
  );
  const restoreIndex = rollback.indexOf(
    "create or replace function public.manage_production_pilot_entitlement",
  );
  const dropColumnIndex = rollback.indexOf("drop column if exists system_user_request_id");
  const dropTableIndex = rollback.indexOf("drop table if exists public.system_user_requests");
  assert.ok(revokeIndex >= 0);
  assert.ok(restoreIndex > revokeIndex);
  assert.ok(dropColumnIndex > restoreIndex);
  assert.ok(dropTableIndex > dropColumnIndex);
  assert.match(
    rollback,
    /p_system_user_external_reference text/iu,
  );
  assert.match(
    rollback,
    /grant execute on function public\.manage_production_pilot_entitlement\(uuid, uuid, uuid, integer, text, boolean, text, timestamptz, timestamptz, text\)\s+to authenticated/iu,
  );
});

test("server data layer exposes the durable request row and an explicit ordered read helper", () => {
  assert.match(server, /export type SystemUserRequestRow = \{/u);
  assert.match(server, /status: SystemUserRequestStatus/u);
  assert.match(
    server,
    /export async function listSystemUserRequests\(\s*supabase: SupabaseClient,\s*companyIds: string\[\],\s*\): Promise<SystemUserRequestRow\[\]>/u,
  );
  assert.match(server, /from\("system_user_requests"\)/u);
  assert.match(server, /\.in\("company_id", companyIds\)/u);
  assert.match(server, /\.order\("created_at", \{ ascending: false \}\)/u);
});
