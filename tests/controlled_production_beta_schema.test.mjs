import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const sql = readFileSync(new URL("../supabase/migrations/20260715180000_controlled_production_beta.sql", import.meta.url), "utf8");
const rollback = readFileSync(new URL("../supabase/rollback/controlled_production_beta.sql", import.meta.url), "utf8");

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
