import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const sql = readFileSync(
  new URL("../supabase/migrations/20260717110000_customer_agreement_acceptances.sql", import.meta.url),
  "utf8",
);

test("stores immutable company-scoped agreement evidence", () => {
  assert.match(sql, /create table public\.customer_agreement_acceptances/iu);
  assert.match(sql, /business_terms_sha256[^\n]+\^\[a-f0-9\]\{64\}\$/iu);
  assert.match(sql, /dpa_sha256[^\n]+\^\[a-f0-9\]\{64\}\$/iu);
  assert.match(sql, /acceptance_method[^\n]+in_app_clickwrap/iu);
  assert.match(sql, /prevent_customer_agreement_acceptance_mutation/iu);
  assert.match(sql, /before update or delete/iu);
  assert.match(sql, /enable row level security/iu);
  assert.match(sql, /company members can read customer agreement acceptances/iu);
  assert.doesNotMatch(sql, /grant\s+(insert|update|delete)[^;]+customer_agreement_acceptances[^;]+authenticated/iu);
});

test("creates company, owner, acceptance, and audit evidence atomically", () => {
  const fn = sql.match(/create or replace function public\.create_company_workspace_with_acceptance[\s\S]+?\n\$\$;/iu)?.[0] ?? "";
  assert.match(fn, /auth\.uid\(\)/iu);
  assert.match(fn, /p_entity_type <> 'AS'/iu);
  assert.match(fn, /insert into public\.companies/iu);
  assert.match(fn, /insert into public\.company_memberships/iu);
  assert.match(fn, /insert into public\.customer_agreement_acceptances/iu);
  assert.match(fn, /insert into public\.audit_events/iu);
  assert.doesNotMatch(fn, /production_pilot_entitlements/iu);
  assert.match(sql, /revoke all on function public\.create_company_workspace_with_acceptance[\s\S]+from public, anon/iu);
  assert.match(sql, /grant execute on function public\.create_company_workspace_with_acceptance[\s\S]+to authenticated/iu);
});
