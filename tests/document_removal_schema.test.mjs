import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationUrl = new URL(
  "../supabase/migrations/20260901233000_documents_capability.sql",
  import.meta.url,
);

test("document metadata is forced-RLS capability state behind restricted functions", async () => {
  const sql = await readFile(migrationUrl, "utf8");
  assert.match(sql, /create role documents_store_owner nologin noinherit nobypassrls/iu);
  assert.match(sql, /create role documents_executor nologin noinherit nobypassrls/iu);
  assert.match(sql, /alter table public\.documents owner to documents_store_owner/iu);
  assert.match(sql, /alter table public\.documents force row level security/iu);
  assert.match(sql, /revoke all on public\.documents from public, anon, authenticated, service_role, documents_executor/iu);
  assert.match(sql, /talli\.authorized_company_roles/iu);
  assert.doesNotMatch(sql, /grant select on public\.company_memberships to documents_store_owner/iu);
  assert.match(sql, /create or replace function documents\.stage_upload_v1/iu);
  assert.match(sql, /create or replace function documents\.finalize_upload_v1/iu);
  assert.match(sql, /create or replace function documents\.list_documents_v1/iu);
});

test("safe removal is reference-aware, audited, and metadata-restoring", async () => {
  const sql = await readFile(migrationUrl, "utf8");
  assert.match(sql, /create or replace function documents\.has_evidence_references_v1/iu);
  for (const relation of [
    "holding_actions", "corporate_document_artifacts", "filing_submissions",
    "production_feedback_artifacts", "ledger_entries",
  ]) assert.match(sql, new RegExp(`public\\.${relation}`, "iu"));
  assert.match(sql, /grant execute on function documents\.has_evidence_references_v1\(uuid\) to documents_store_owner/iu);
  assert.match(sql, /status='removed'.*removed_at=pg_catalog\.now\(\)/isu);
  assert.match(sql, /document_removal_requested/iu);
  assert.match(sql, /removed_at >= pg_catalog\.now\(\)-interval '5 minutes'/iu);
  assert.match(sql, /document_removal_storage_failed/iu);
});

test("all broad browser bucket policies and legacy removal execution are revoked", async () => {
  const sql = await readFile(migrationUrl, "utf8");
  assert.match(sql, /drop policy if exists "company members can read company document objects" on storage\.objects/iu);
  assert.match(sql, /drop policy if exists "owners can upload company document objects" on storage\.objects/iu);
  assert.match(sql, /drop policy if exists "owners can delete removed unlinked document objects" on storage\.objects/iu);
  assert.match(sql, /revoke all on function public\.remove_unlinked_document\(uuid\).*from public, anon, authenticated, service_role/isu);
  assert.doesNotMatch(sql, /create policy .*storage\.objects/iu);
});
