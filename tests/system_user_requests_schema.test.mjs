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
  new URL("../app/lib/supabase/server.ts", import.meta.url),
  "utf8",
);

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
    const functionSql = sql.match(
      new RegExp(`create or replace function public\\.${functionName}\\([\\s\\S]+?\\n\\$\\$;`, "iu"),
    )?.[0] ?? "";
    assert.match(functionSql, /security definer/iu);
    assert.match(functionSql, /set search_path = ''/iu);
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
  const functionSql = sql.match(
    /create or replace function public\.record_system_user_authority_state\([\s\S]+?\n\$\$;/iu,
  )?.[0] ?? "";
  assert.match(functionSql, /where r\.id = p_request_id[\s\S]+for update/iu);
  assert.match(functionSql, /v_request\.company_id is distinct from p_company_id/iu);
  assert.match(functionSql, /v_request\.external_ref is distinct from p_external_ref/iu);
  assert.match(functionSql, /v_request\.altinn_request_id is not null[\s\S]+p_altinn_request_id/iu);
  assert.match(functionSql, /from public\.company_memberships[\s\S]+m\.user_id = v_request\.initiating_owner_user_id/iu);
  assert.match(functionSql, /v_request\.status = 'creating'[\s\S]+p_status in \([^)]*'new'[^)]*'accepted'/iu);
  assert.match(functionSql, /v_request\.status = 'accepted'[\s\S]+p_status in \('accepted', 'verification_failed'\)/iu);
  assert.match(functionSql, /v_request\.status = 'verification_failed'[\s\S]+p_status in \('verification_failed', 'accepted'\)/iu);
  assert.match(functionSql, /invalid_system_user_transition/iu);
  assert.match(functionSql, /p_failure_code not in \(/iu);
  assert.match(functionSql, /public\.authority_operations/iu);
  assert.match(functionSql, /requested_at =/iu);
  assert.match(functionSql, /last_status_checked_at =/iu);
  assert.match(functionSql, /accepted_at =/iu);
  assert.match(functionSql, /resolved_at =/iu);
  assert.match(functionSql, /updated_at =/iu);
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

  const beginSql = sql.match(
    /create or replace function public\.begin_production_filing\(p_approval_id uuid\)[\s\S]+?\n\$\$;/iu,
  )?.[0] ?? "";
  assert.match(beginSql, /join public\.system_user_requests r on r\.id = e\.system_user_request_id/iu);
  assert.match(beginSql, /r\.initiating_owner_user_id = v_actor_id/iu);
  assert.match(beginSql, /r\.company_id = v_approval\.company_id/iu);
  assert.match(beginSql, /r\.obligation = v_approval\.obligation/iu);
  assert.match(beginSql, /r\.status = 'accepted'/iu);
  assert.match(beginSql, /r\.preflight_verified_at is not null/iu);
  assert.match(beginSql, /r\.external_ref = e\.system_user_external_reference/iu);
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
