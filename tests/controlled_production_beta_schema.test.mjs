import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import test from "node:test";

const sql = readFileSync(new URL("../supabase/migrations/20260715180000_controlled_production_beta.sql", import.meta.url), "utf8");
const bindingSql = readFileSync(
  new URL(
    `../supabase/migrations/${readdirSync(new URL("../supabase/migrations/", import.meta.url)).find((file) => file.endsWith("_rf1086_system_user_requests.sql"))}`,
    import.meta.url,
  ),
  "utf8",
);
const rollback = readFileSync(new URL("../supabase/rollback/controlled_production_beta.sql", import.meta.url), "utf8");

test("all migrations use portable JSONB object checks", () => {
  for (const migration of readdirSync(new URL("../supabase/migrations/", import.meta.url))) {
    if (!migration.endsWith(".sql")) continue;
    const migrationSql = readFileSync(new URL(`../supabase/migrations/${migration}`, import.meta.url), "utf8");
    assert.doesNotMatch(migrationSql, /jsonb_object_length/iu, migration);
  }
});

test("creates a separate production-only aggregate with constrained states", () => {
  for (const table of [
    "production_pilot_entitlements",
    "filing_approval_snapshots",
    "production_filing_submissions",
    "production_filing_events",
  ]) {
    assert.match(sql, new RegExp(`create table (?:if not exists )?public\\.${table}`, "i"));
    assert.match(sql, new RegExp(`alter table public\\.${table} enable row level security`, "i"));
  }
  assert.match(sql, /rf1086_no_activity_v1/u);
  assert.match(sql, /pending.*active.*suspended.*completed.*revoked/su);
  assert.match(sql, /approved.*sending.*received.*processing.*accepted.*rejected.*action_required.*unknown/su);
});

test("denies direct customer mutation and keeps authority events service-only", () => {
  for (const table of [
    "production_pilot_entitlements",
    "filing_approval_snapshots",
    "production_filing_submissions",
    "production_filing_events",
  ]) {
    assert.match(sql, new RegExp(`revoke all on table public\\.${table} from public, anon, authenticated`, "i"));
  }
  assert.match(sql, /grant select on table public\.production_pilot_entitlements to authenticated/i);
  assert.doesNotMatch(sql, /grant\s+(?:insert|update|delete)[^;]*production_pilot_entitlements[^;]*authenticated/iu);
  assert.match(sql, /grant execute on function public\.append_production_filing_event[^;]+to service_role/is);
  assert.doesNotMatch(sql, /grant execute on function public\.append_production_filing_event[^;]+to authenticated/is);
});

test("approval and begin RPCs enforce owner AAL2 and an exact active entitlement", () => {
  assert.match(sql, /create or replace function public\.assert_fresh_production_owner/u);
  assert.match(sql, /auth\.jwt\(\)[\s\S]*'aal'[\s\S]*'aal2'/u);
  assert.match(sql, /jsonb_array_elements\(v_claims -> 'amr'\)/u);
  assert.match(sql, /interval '15 minutes'/u);
  assert.match(sql, /production_pilot_entitlements[\s\S]*status = 'active'[\s\S]*user_id = v_actor_id/u);
  assert.match(sql, /create or replace function public\.approve_production_filing/u);
  assert.match(sql, /create or replace function public\.begin_production_filing/u);
  assert.match(sql, /jsonb_array_length\(r\.hard_blocks\) = 0[\s\S]*filing_readiness_snapshots/u);
  assert.match(sql, /filing_overrides[\s\S]*risk_level = 'block'/u);
  assert.doesNotMatch(sql, /o\.filing = v_approval\.obligation/u);
  assert.match(sql, /filing_review_comments[\s\S]*severity = 'hard_block'/u);
  assert.match(sql, /security_restore'[\s\S]*interval '30 days'/u);
  assert.doesNotMatch(sql, /authority_test_runs t[\s\S]*t\.company_id = v_approval\.company_id/u);
});

test("acceptance requires explicit final authority evidence and events are append-only", () => {
  assert.match(sql, /p_status = 'accepted'[\s\S]*p_final_authority_decision is not true/u);
  assert.match(sql, /raise exception 'production_final_authority_decision_required'/u);
  assert.doesNotMatch(sql, /create policy[^;]+production_filing_events[^;]+for (?:update|delete)/isu);
});

test("rollback revokes RPC access before dropping additive objects", () => {
  const revokeIndex = rollback.indexOf("revoke all on function public.append_production_filing_event");
  const dropIndex = rollback.indexOf("drop table if exists public.production_filing_events");
  assert.ok(revokeIndex >= 0 && dropIndex > revokeIndex);
  assert.match(rollback, /drop function if exists public\.assert_fresh_production_owner/u);
});

test("Systembruker binding preserves every existing production filing gate", () => {
  assert.match(
    bindingSql,
    /drop function if exists public\.manage_production_pilot_entitlement\(uuid, uuid, uuid, integer, text, boolean, text, timestamptz, timestamptz, text\)/iu,
  );
  assert.match(
    bindingSql,
    /p_system_user_request_id uuid[\s\S]+v_request\.preflight_verified_at is null/iu,
  );
  assert.doesNotMatch(
    bindingSql,
    /p_system_user_external_reference text/iu,
  );

  const beginSql = bindingSql.match(
    /create or replace function public\.begin_production_filing\(p_approval_id uuid\)[\s\S]+?\n\$\$;/iu,
  )?.[0] ?? "";
  for (const gate of [
    "public.assert_fresh_production_owner",
    "public.authority_permissions",
    "public.filing_readiness_snapshots",
    "public.filing_overrides",
    "public.filing_review_comments",
    "public.launch_signoffs",
    "founder_production_go_live",
    "rf1086_authority",
    "security_restore",
    "interval '30 days'",
  ]) {
    assert.match(beginSql, new RegExp(gate.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&"), "u"));
  }
  assert.match(beginSql, /from public\.system_user_requests r[\s\S]+for update/iu);
  assert.match(beginSql, /from public\.production_pilot_entitlements e[\s\S]+for update/iu);
  assert.match(beginSql, /v_entitlement\.system_user_request_id is distinct from v_request\.id/iu);
  assert.match(beginSql, /v_request\.status <> 'accepted'/iu);
  assert.match(beginSql, /v_request\.preflight_verified_at is null/iu);
});

const canonicalSql = readFileSync(new URL("../supabase/migrations/20260909190548_shareholder_register_filing_capability.sql", import.meta.url), "utf8");

test("canonical RF relocation preserves physical production aggregates and uses dedicated authority", () => {
  for (const table of ["filing_approval_snapshots", "production_filing_submissions", "production_filing_events"]) {
    assert.match(canonicalSql, new RegExp(`alter table public\\.${table} set schema shareholder_register_filing`, "iu"));
    assert.match(canonicalSql, new RegExp(`alter table shareholder_register_filing\\.${table} force row level security`, "iu"));
  }
  assert.match(canonicalSql, /shareholder_register_filing_executor nologin noinherit nobypassrls/iu);
  for (const name of ["approve_production_filing", "begin_production_filing", "append_production_filing_event"]) {
    assert.match(canonicalSql, new RegExp(`revoke all on function shareholder_register_filing\\.${name}[^;]+from public,anon,authenticated,service_role`, "isu"));
    assert.match(canonicalSql, new RegExp(`grant execute on function shareholder_register_filing\\.${name}[^;]+to shareholder_register_filing_executor`, "isu"));
  }
});

test("canonical begin retains owner MFA, exact System User and Billing bindings, and every original release gate", () => {
  function functionBody(name) {
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
    const body = canonicalSql.match(new RegExp(`create(?: or replace)? function ${escaped}\\([^]*?\\$function\\$([^]*?)\\$function\\$`, "iu"))?.[1];
    assert.ok(body, name);
    return body;
  }
  const body = functionBody("shareholder_register_filing.begin_production_filing");
  for (const gate of ["assert_fresh_owner_v1", "authority_permissions", "filing_review_comments",
    "backend_system.rf1086_stored_release_inputs_v1", "backend_system.rf1086_technical_release_ready_v1"])
    assert.ok(body.includes(gate), gate);
  assert.match(functionBody("shareholder_register_filing.assert_fresh_owner_v1"), /assert_fresh_production_owner_v1/iu);
  const storedReleaseInputs = functionBody("backend_system.rf1086_stored_release_inputs_v1");
  assert.match(storedReleaseInputs, /r\.ready and pg_catalog\.jsonb_array_length\(r\.hard_blocks\)=0/iu);
  assert.match(storedReleaseInputs, /public\.filing_readiness_snapshots/iu);
  assert.match(storedReleaseInputs, /not shareholder_register_filing\.has_blocking_override_v1/iu);
  assert.match(storedReleaseInputs, /public\.filing_overrides[\s\S]+risk_level='block'/iu);
  const technicalRelease = functionBody("backend_system.rf1086_technical_release_ready_v1");
  for (const gate of ["public.launch_signoffs", "launch_legal_name_public_copy", "legal_policy_pack", "security_restore",
    "support_rollback", "founder_production_go_live", "rf1086_authority", "interval '30 days'"])
    assert.ok(technicalRelease.includes(gate), gate);
  assert.match(technicalRelease, /s\.status='approved'/iu);
  assert.match(technicalRelease, /s\.reviewed_at<=pg_catalog\.now\(\)/iu);
  assert.match(body, /v_entitlement\.system_user_request_id is distinct from v_request\.id/iu);
  assert.match(body, /v_request\.status <> 'accepted'/iu);
  assert.match(body, /v_request\.preflight_verified_at is null/iu);
  assert.match(body, /lock_rf_request_v1/iu);
  assert.match(body, /lock_rf_pilot_v1/iu);
});
