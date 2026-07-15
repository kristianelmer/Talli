import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationUrl = new URL(
  "../supabase/migrations/20260715143000_retention_safe_document_removal.sql",
  import.meta.url,
);

test("accidental document removal is owner-only, audited, and blocked for linked evidence", async () => {
  const sql = await readFile(migrationUrl, "utf8");

  assert.match(sql, /add column if not exists removed_at timestamptz/i);
  assert.match(sql, /add column if not exists removed_by uuid/i);
  assert.match(sql, /add column if not exists removal_reason text/i);
  assert.match(sql, /create or replace function public\.remove_unlinked_document\(p_document_id uuid\)/i);
  assert.match(sql, /security definer[\s\S]+set search_path = public/i);
  assert.match(sql, /m\.role = 'owner'[\s\S]+m\.accepted_at is not null/i);
  assert.match(sql, /public\.holding_actions[\s\S]+document_id = p_document_id/i);
  assert.match(sql, /public\.corporate_document_artifacts[\s\S]+document_id = p_document_id/i);
  assert.match(sql, /public\.filing_submissions[\s\S]+feedback_document_ids/i);
  assert.match(sql, /public\.ledger_entries[\s\S]+p_document_id::text/i);
  assert.match(sql, /document_removal_evidence_linked/i);
  assert.match(sql, /action[\s\S]+document_removal_requested/i);
  assert.match(sql, /status = 'removed'[\s\S]+removed_by = v_actor_id/i);
  assert.match(sql, /create policy "owners can delete removed unlinked document objects"/i);
  assert.match(sql, /storage\.objects for delete[\s\S]+d\.status = 'removed'[\s\S]+d\.removed_by = \(select auth\.uid\(\)\)/i);
  assert.match(sql, /create policy "company members can read company document objects"[\s\S]+not exists[\s\S]+d\.status = 'removed'/i);
  assert.match(sql, /revoke all on function public\.remove_unlinked_document\(uuid\) from public, anon/i);
  assert.match(sql, /grant execute on function public\.remove_unlinked_document\(uuid\) to authenticated, service_role/i);
});

test("a failed object-store removal can restore only the same recent owner request", async () => {
  const sql = await readFile(migrationUrl, "utf8");

  assert.match(sql, /create or replace function public\.restore_unlinked_document_after_storage_failure\(p_document_id uuid\)/i);
  assert.match(sql, /removed_by = v_actor_id/i);
  assert.match(sql, /removed_at >= now\(\) - interval '5 minutes'/i);
  assert.match(sql, /document_removal_storage_failed/i);
  assert.match(sql, /revoke all on function public\.restore_unlinked_document_after_storage_failure\(uuid\) from public, anon/i);
});

test("removed documents disappear from active lists and cannot receive signed download URLs", async () => {
  const [serverSource, downloadSource, pageSource] = await Promise.all([
    readFile(new URL("../app/lib/supabase/server.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/documents/[documentId]/download/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/(owner)/documents/page.tsx", import.meta.url), "utf8"),
  ]);

  assert.match(serverSource, /\.neq\("status", "removed"\)/);
  assert.match(downloadSource, /select\("company_id, storage_key, status"\)/);
  assert.match(downloadSource, /document\.status !== "attached"/);
  assert.match(pageSource, /removeUnlinkedDocument|DocumentRemovalButton/);
});
