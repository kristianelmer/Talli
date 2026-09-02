import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationUrl = new URL(
  "../supabase/migrations/20260902022500_documents_advisor_cleanup.sql",
  import.meta.url,
);
const rollbackUrl = new URL(
  "../supabase/rollback/20260902022500_documents_advisor_cleanup.sql",
  import.meta.url,
);

test("documents cleanup removes the residual browser metadata policy", async () => {
  const sql = await readFile(migrationUrl, "utf8");
  assert.match(
    sql,
    /drop policy if exists "company members can read document metadata" on public\.documents/iu,
  );
  assert.doesNotMatch(
    sql,
    /create policy "company members can read document metadata"/iu,
  );
});

test("documents cleanup plans request-local settings once per statement", async () => {
  const sql = await readFile(migrationUrl, "utf8");
  assert.match(sql, /grant documents_store_owner to %I with set true/iu);
  assert.match(sql, /set local role documents_store_owner/iu);
  assert.match(sql, /grant documents_store_owner to %I with set false/iu);
  for (const policy of [
    "documents_store_reads_visible_documents",
    "documents_store_creates_owner_documents",
    "documents_store_updates_owner_documents",
    "documents_store_appends_document_audit",
  ]) {
    assert.match(sql, new RegExp(`create policy ${policy}`, "iu"));
  }
  assert.match(sql, /select pg_catalog\.current_setting\('talli\.verified_actor_id', true\)/iu);
  assert.match(sql, /select pg_catalog\.current_setting\('talli\.authorized_company_roles', true\)/iu);
});

test("documents advisor cleanup has an explicit predecessor rollback", async () => {
  const rollback = await readFile(rollbackUrl, "utf8");
  assert.match(rollback, /set local role documents_store_owner/iu);
  assert.match(
    rollback,
    /create policy "company members can read document metadata" on public\.documents/iu,
  );
  assert.match(rollback, /create policy documents_store_reads_visible_documents/iu);
  assert.match(rollback, /create policy documents_store_appends_document_audit/iu);
});
