import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const migrationUrl = new URL(
  "../supabase/migrations/20260716110000_authority_operations.sql",
  import.meta.url,
);
const rollbackUrl = new URL("../supabase/rollback/authority_operations.sql", import.meta.url);

test("authority operations are constrained, RLS protected, and service-written", () => {
  const sql = readFileSync(migrationUrl, "utf8");

  assert.match(sql, /create table if not exists public\.authority_operations/iu);
  assert.match(sql, /register_rf1086_system/u);
  assert.match(sql, /started.*succeeded.*failed.*conflict/su);
  assert.match(sql, /alter table public\.authority_operations enable row level security/iu);
  assert.match(
    sql,
    /revoke all on table public\.authority_operations from public, anon, authenticated/iu,
  );
  assert.match(sql, /grant select on table public\.authority_operations to authenticated/iu);
  assert.match(
    sql,
    /grant insert, update on table public\.authority_operations to service_role/iu,
  );
  assert.doesNotMatch(
    sql,
    /grant (?:insert|update)[^;]*authority_operations[^;]*authenticated/iu,
  );
  assert.match(sql, /support_operators[\s\S]*role = 'admin'[\s\S]*active/iu);
});

test("rollback revokes access before dropping the table", () => {
  const rollback = readFileSync(rollbackUrl, "utf8");
  assert.ok(
    rollback.indexOf("revoke all on table public.authority_operations") <
      rollback.indexOf("drop table if exists public.authority_operations"),
  );
});
