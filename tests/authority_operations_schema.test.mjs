import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import test from "node:test";

const migrationUrl = new URL(
  "../supabase/migrations/20260716110000_authority_operations.sql",
  import.meta.url,
);
const rollbackUrl = new URL("../supabase/rollback/authority_operations.sql", import.meta.url);
const callbackMigrationNames = readdirSync(
  new URL("../supabase/migrations/", import.meta.url),
).filter((file) => file.endsWith("_rf1086_systemregister_callback_operation.sql"));
const callbackRollbackUrl = new URL(
  "../supabase/rollback/rf1086_systemregister_callback_operation.sql",
  import.meta.url,
);

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

test("callback operation migration expands only the constrained safe audit contract", () => {
  assert.equal(callbackMigrationNames.length, 1);
  const sql = readFileSync(
    new URL(`../supabase/migrations/${callbackMigrationNames[0]}`, import.meta.url),
    "utf8",
  );

  assert.match(sql, /set_rf1086_systembruker_callback/u);
  assert.match(sql, /callback_already_verified/u);
  assert.match(sql, /callback_updated_and_verified/u);
  const registrationResultCodes = sql.slice(
    sql.indexOf("operation = 'register_rf1086_system'"),
    sql.indexOf("or (", sql.indexOf("operation = 'register_rf1086_system'")),
  );
  const callbackResultCodes = sql.slice(
    sql.indexOf("operation = 'set_rf1086_systembruker_callback'"),
    sql.indexOf("add constraint authority_operations_metadata_check"),
  );
  assert.doesNotMatch(registrationResultCodes, /authority_verification_error/u);
  assert.match(callbackResultCodes, /authority_verification_error/u);
  assert.match(sql, /drop constraint if exists authority_operations_operation_check/iu);
  assert.match(sql, /add constraint authority_operations_operation_check/iu);
  assert.match(sql, /callbackPath/u);
  assert.match(sql, /\/auth\/systembruker\/confirm/u);
  assert.match(sql, /metadata - array\['systemId', 'callbackPath'\]/u);
  assert.doesNotMatch(sql, /grant\s+(?:insert|update|delete|all)/iu);
  assert.doesNotMatch(sql, /anon|authenticated/iu);
});

test("callback rollback removes callback rows before restoring the original constraints", () => {
  const rollback = readFileSync(callbackRollbackUrl, "utf8");
  const deleteIndex = rollback.indexOf(
    "delete from public.authority_operations\nwhere operation = 'set_rf1086_systembruker_callback'",
  );
  const restoreIndex = rollback.indexOf(
    "add constraint authority_operations_operation_check",
  );

  assert.ok(deleteIndex >= 0);
  assert.ok(restoreIndex > deleteIndex);
  assert.match(rollback, /operation in \('register_rf1086_system'\)/u);
  assert.doesNotMatch(rollback, /grant\s+(?:insert|update|delete|all)/iu);
});
