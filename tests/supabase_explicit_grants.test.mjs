import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

const migrationUrl = new URL(
  "../supabase/migrations/20260714081443_explicit_data_api_grants.sql",
  import.meta.url,
);
const anonymousRpcMigrationUrl = new URL(
  "../supabase/migrations/20260715120700_revoke_anonymous_mutation_rpcs.sql",
  import.meta.url,
);

test("Supabase Data API grants fail closed for anon and explicitly enable service_role", async () => {
  const sql = await readFile(migrationUrl, "utf8");

  assert.match(sql, /revoke all privileges on all tables in schema public from anon/i);
  assert.match(sql, /revoke all privileges on all sequences in schema public from anon/i);
  assert.match(sql, /grant usage on schema public to service_role/i);
  assert.match(sql, /grant all privileges on all tables in schema public to service_role/i);
  assert.match(sql, /grant all privileges on all sequences in schema public to service_role/i);
  assert.match(sql, /grant all privileges on all functions in schema public to service_role/i);
  assert.match(
    sql,
    /alter default privileges for role postgres in schema public[\s\S]+grant all privileges on tables to service_role/i,
  );
  assert.match(
    sql,
    /revoke all on function public\.can_accept_company_invitation\(uuid, text\)[\s\S]+from public, anon/i,
  );
  assert.match(
    sql,
    /revoke all on function public\.is_company_creator\(uuid\)[\s\S]+from public, anon/i,
  );
  assert.match(
    sql,
    /revoke all on function public\.prevent_corporate_record_mutation\(\)[\s\S]+from public, anon, authenticated/i,
  );
  assert.equal((sql.match(/\(select auth\.jwt\(\)\)/gi) ?? []).length, 3);
  assert.doesNotMatch(sql, /grant\s+[^;]+\s+to\s+anon/i);
});

test("anonymous sessions cannot invoke authenticated mutation RPCs", async () => {
  const sql = await readFile(anonymousRpcMigrationUrl, "utf8");

  assert.match(
    sql,
    /revoke all on function public\.record_share_purchase_fifo\([\s\S]+?\) from public, anon;/i,
  );
  assert.match(
    sql,
    /revoke all on function public\.record_share_sale_fifo\([\s\S]+?\) from public, anon;/i,
  );
  assert.match(
    sql,
    /revoke all on function public\.accept_bank_transaction_suggestion\(uuid, text, text\)\s+from public, anon;/i,
  );
  assert.equal((sql.match(/to authenticated, service_role;/gi) ?? []).length, 3);
});

test("Systembruker request objects have explicit least-privilege grants", async () => {
  const files = await readdir(new URL("../supabase/migrations/", import.meta.url));
  const migration = files.find((file) => file.endsWith("_rf1086_system_user_requests.sql"));
  assert.ok(migration);
  const sql = await readFile(new URL(`../supabase/migrations/${migration}`, import.meta.url), "utf8");

  assert.match(
    sql,
    /revoke all on (?:table )?public\.system_user_requests from public, anon, authenticated, service_role/iu,
  );
  assert.match(sql, /grant select on (?:table )?public\.system_user_requests to authenticated/iu);
  assert.doesNotMatch(sql, /grant\s+[^;]+system_user_requests[^;]+to anon/iu);
  assert.match(
    sql,
    /revoke all on function public\.begin_system_user_request\(uuid, uuid, text\)\s+from public, anon, authenticated, service_role/iu,
  );
  assert.match(
    sql,
    /grant execute on function public\.begin_system_user_request\(uuid, uuid, text\)\s+to authenticated/iu,
  );
  assert.match(
    sql,
    /grant execute on function public\.record_system_user_authority_state\(uuid, uuid, uuid, text, text, text, text, uuid\)\s+to service_role/iu,
  );
  assert.match(
    sql,
    /grant execute on function public\.verify_system_user_preflight\(uuid, text\)\s+to service_role/iu,
  );
});
