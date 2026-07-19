import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

async function trustedBoundaryMigration() {
  const files = await readdir(new URL("../supabase/migrations/", import.meta.url));
  const matches = files.filter((file) => file.endsWith("_trusted_aal2_boundary.sql"));
  assert.equal(matches.length, 1, "Expected exactly one trusted AAL2 boundary migration");
  return readFile(new URL(`../supabase/migrations/${matches[0]}`, import.meta.url), "utf8");
}

test("legacy step-up events are inaccessible to customer Data API roles", async () => {
  const sql = await trustedBoundaryMigration();

  assert.match(sql, /revoke all(?: privileges)? on (?:table )?public\.step_up_events from anon, authenticated/i);
  assert.match(sql, /drop policy if exists "users can read their own step up events" on public\.step_up_events/i);
  assert.match(sql, /drop policy if exists "users can create their own step up events" on public\.step_up_events/i);
  assert.doesNotMatch(sql, /grant\s+(?:select|insert|update|delete)[^;]*step_up_events[^;]*authenticated/i);
});

test("corporate step-up RPC trusts signed AAL2 and timestamped AMR claims only", async () => {
  const sql = await trustedBoundaryMigration();
  const functionMatch = sql.match(
    /create or replace function public\.assert_fresh_corporate_step_up\(target_company_id uuid\)[\s\S]+?\n\$\$;/i,
  );

  assert.ok(functionMatch, "Expected the trusted corporate step-up function replacement");
  const functionSql = functionMatch[0];
  assert.match(functionSql, /v_actor_id := public\.assert_corporate_owner\(target_company_id\)/i);
  assert.match(functionSql, /auth\.uid\(\)/i);
  assert.match(functionSql, /auth\.jwt\(\)/i);
  assert.match(functionSql, /->>\s*'aal'[^;]+aal2/i);
  assert.match(functionSql, /jsonb_array_elements/i);
  assert.match(functionSql, /->>\s*'method'/i);
  assert.match(functionSql, /->>\s*'timestamp'/i);
  assert.match(functionSql, /interval '15 minutes'/i);
  assert.doesNotMatch(functionSql, /public\.step_up_events/i);
});

test("final founder confirmation is a database-enforced launch signoff key", async () => {
  const sql = await trustedBoundaryMigration();

  assert.match(sql, /drop constraint if exists launch_signoffs_key_check/i);
  assert.match(sql, /add constraint launch_signoffs_key_check[\s\S]+founder_production_go_live/i);
});
