import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const sql = readFileSync(
  new URL("../supabase/migrations/20260717110000_customer_agreement_acceptances.sql", import.meta.url),
  "utf8",
);
const rollbackSql = readFileSync(
  new URL("../supabase/rollback/customer_agreement_acceptances.sql", import.meta.url),
  "utf8",
);
const correctiveSql = readFileSync(
  new URL("../supabase/migrations/20260717113000_restrict_customer_agreement_creation.sql", import.meta.url),
  "utf8",
);

test("stores immutable company-scoped agreement evidence", () => {
  assert.match(sql, /create table public\.customer_agreement_acceptances/iu);
  assert.match(sql, /company_id[^\n]+references public\.companies\(id\) on delete restrict/iu);
  assert.match(sql, /business_terms_sha256[^\n]+\^\[a-f0-9\]\{64\}\$/iu);
  assert.match(sql, /dpa_sha256[^\n]+\^\[a-f0-9\]\{64\}\$/iu);
  assert.match(sql, /acceptance_method[^\n]+in_app_clickwrap/iu);
  assert.match(sql, /prevent_customer_agreement_acceptance_mutation/iu);
  assert.match(sql, /before update or delete/iu);
  assert.match(sql, /enable row level security/iu);
  assert.match(sql, /company members can read customer agreement acceptances/iu);
  assert.doesNotMatch(sql, /grant\s+(insert|update|delete)[^;]+customer_agreement_acceptances[^;]+authenticated/iu);
  assert.match(
    sql,
    /revoke all on table public\.customer_agreement_acceptances from public, anon, authenticated, service_role/iu,
  );
  assert.match(sql, /grant select on table public\.customer_agreement_acceptances to service_role/iu);
  assert.doesNotMatch(
    sql,
    /grant\s+(?:all(?: privileges)?|insert|update|delete|truncate)[^;]*customer_agreement_acceptances[^;]*service_role/iu,
  );
});

test("creates company, owner, acceptance, and audit evidence atomically", () => {
  const fn = sql.match(/create or replace function public\.create_company_workspace_with_acceptance[\s\S]+?\n\$\$;/iu)?.[0] ?? "";
  assert.match(
    fn,
    /create or replace function public\.create_company_workspace_with_acceptance\(\s*p_actor_id uuid,\s*p_org_number text,\s*p_name text,\s*p_entity_type text,\s*p_address text,\s*p_postal_code text,\s*p_city text,\s*p_status_text text,\s*p_source text,\s*p_business_terms_version text,\s*p_business_terms_effective_date date,\s*p_business_terms_path text,\s*p_business_terms_sha256 text,\s*p_dpa_version text,\s*p_dpa_effective_date date,\s*p_dpa_path text,\s*p_dpa_sha256 text,\s*p_authority_statement_version text,\s*p_acceptance_method text\s*\)/iu,
  );
  assert.match(fn, /security definer\s+set search_path = ''/iu);
  assert.match(fn, /auth\.role\(\) is distinct from 'service_role'/iu);
  assert.match(fn, /p_actor_id is null/iu);
  assert.match(fn, /p_entity_type is distinct from 'AS'/iu);
  assert.match(fn, /p_acceptance_method is distinct from 'in_app_clickwrap'/iu);
  assert.match(fn, /p_authority_statement_version is distinct from 'authority-v1'/iu);
  assert.match(fn, /insert into public\.companies/iu);
  assert.match(fn, /insert into public\.company_memberships/iu);
  assert.match(fn, /insert into public\.customer_agreement_acceptances/iu);
  assert.match(fn, /insert into public\.audit_events/iu);
  assert.doesNotMatch(fn, /production_pilot_entitlements/iu);
  assert.match(sql, /revoke all on function public\.create_company_workspace_with_acceptance[\s\S]+from public, anon/iu);
  assert.doesNotMatch(sql, /grant execute on function public\.create_company_workspace_with_acceptance[\s\S]+to authenticated/iu);
  assert.match(
    sql,
    /grant execute on function public\.create_company_workspace_with_acceptance\(\s*uuid, text, text, text, text, text, text, text, text, text, date, text, text, text, date, text, text, text, text\s*\)\s*to service_role/iu,
  );
});

test("migration can be replayed by the local database gate", () => {
  assert.match(sql, /create table public\.customer_agreement_acceptances[\s\S]+when duplicate_table then null/iu);
  assert.match(sql, /create index if not exists customer_agreement_acceptances_company_id_idx/iu);
  assert.match(
    sql,
    /drop trigger if exists prevent_customer_agreement_acceptance_mutation[\s\S]+create trigger prevent_customer_agreement_acceptance_mutation/iu,
  );
  assert.match(
    sql,
    /drop policy if exists "company members can read customer agreement acceptances"[\s\S]+create policy "company members can read customer agreement acceptances"/iu,
  );
});

test("rollback revokes the RPC first and tolerates an absent evidence table", () => {
  const legacySignature = "text, text, text, text, text, text, text, text, text, date, text, text, text, date, text, text, text, text";
  const serviceSignature = `uuid, ${legacySignature}`;
  const normalizedRollback = rollbackSql.replace(/\s+/gu, " ");
  for (const signature of [legacySignature, serviceSignature]) {
    const revokeRpc = normalizedRollback.indexOf(
      `revoke all on function public.create_company_workspace_with_acceptance( ${signature} )`,
    );
    const dropRpc = normalizedRollback.indexOf(
      `drop function if exists public.create_company_workspace_with_acceptance( ${signature} )`,
    );
    assert.ok(revokeRpc >= 0, `rollback must revoke ${signature}`);
    assert.ok(dropRpc > revokeRpc, `rollback must drop ${signature} after revoke`);
  }
  assert.match(rollbackSql, /if to_regclass\('public\.customer_agreement_acceptances'\) is not null then/iu);
  assert.match(rollbackSql, /drop policy if exists "company members can read customer agreement acceptances"/iu);
  assert.match(rollbackSql, /drop trigger if exists prevent_customer_agreement_acceptance_mutation/iu);
  assert.match(rollbackSql, /drop table if exists public\.customer_agreement_acceptances/iu);
});

test("corrective migration removes the legacy overload and repairs deployed constraints", () => {
  assert.match(
    correctiveSql,
    /revoke all on function public\.create_company_workspace_with_acceptance\(\s*text, text, text, text, text, text, text, text, text, date, text, text, text, date, text, text, text, text\s*\)[\s\S]+from public, anon, authenticated, service_role/iu,
  );
  assert.match(
    correctiveSql,
    /drop function public\.create_company_workspace_with_acceptance\(\s*text, text, text, text, text, text, text, text, text, date, text, text, text, date, text, text, text, text\s*\)/iu,
  );
  assert.match(correctiveSql, /drop constraint if exists customer_agreement_acceptances_company_id_fkey/iu);
  assert.match(
    correctiveSql,
    /foreign key \(company_id\) references public\.companies\(id\) on delete restrict/iu,
  );
  assert.match(
    correctiveSql,
    /grant execute on function public\.create_company_workspace_with_acceptance\(\s*uuid, text, text, text, text, text, text, text, text, text, date, text, text, text, date, text, text, text, text\s*\)\s*to service_role/iu,
  );
  assert.doesNotMatch(
    correctiveSql,
    /grant execute on function public\.create_company_workspace_with_acceptance[\s\S]+to (?:anon|authenticated)/iu,
  );
});
