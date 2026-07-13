import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationPath = "supabase/migrations/20260713121355_secure_step_up_attestation.sql";
const identityMigrationPath = "supabase/migrations/20260713122759_lock_membership_and_company_identity.sql";
const cancellationMigrationPath = "supabase/migrations/20260713122955_secure_cancellation_transitions.sql";
const documentMigrationPath = "supabase/migrations/20260713124354_restrict_company_document_uploads.sql";
const grantImmutabilityMigrationPath =
  "supabase/migrations/20260713125515_make_production_security_grants_append_only.sql";
const orphanCleanupMigrationPath = "supabase/migrations/20260713130403_allow_orphan_document_cleanup.sql";
const launchHistoryMigrationPath = "supabase/migrations/20260713130731_preserve_launch_signoff_history.sql";
const ownerDividendMigrationPath = "supabase/migrations/20260713133300_record_owner_dividend_atomically.sql";

test("step-up migration derives freshness from signed Supabase MFA claims", async () => {
  const sql = await readFile(migrationPath, "utf8");

  assert.match(sql, /auth\.jwt\(\) ->> 'aal'\) = 'aal2'/u);
  assert.match(sql, /entry ->> 'method' = 'totp'/u);
  assert.match(sql, /entry ->> 'timestamp'/u);
  assert.match(sql, /not security_review_approved/u);
  assert.match(sql, /not production_credentials_enabled/u);
  assert.match(sql, /drop policy if exists "users can create their own step up events"/u);
});

test("final deletion requires an independent admin and immutable cancellation identity", async () => {
  const sql = await readFile(cancellationMigrationPath, "utf8");

  assert.match(sql, /requested_by <> \(select auth\.uid\(\)\)/u);
  assert.match(sql, /operator\.role = 'admin'/u);
  assert.match(sql, /old\.evidence ->> 'archiveExportedAt'/u);
  assert.match(sql, /new\.company_id is distinct from old\.company_id/u);
  assert.match(sql, /support operators can create audit events for themselves/u);
});

test("private document bucket enforces the bounded upload allowlist", async () => {
  const sql = await readFile(documentMigrationPath, "utf8");

  assert.match(sql, /file_size_limit = 6291456/u);
  assert.match(sql, /allowed_mime_types = array\['application\/pdf', 'image\/png', 'image\/jpeg', 'text\/csv'\]/u);
  assert.match(sql, /set public = false/u);
});

test("owners can clean up only uncommitted document objects", async () => {
  const sql = await readFile(orphanCleanupMigrationPath, "utf8");

  assert.match(sql, /on storage\.objects for delete/u);
  assert.match(sql, /membership\.role = 'owner'/u);
  assert.match(sql, /membership\.accepted_at is not null/u);
  assert.match(sql, /not exists \([\s\S]*document\.storage_key = storage\.objects\.name/u);
});

test("membership roles and confirmed company identity are not client-updatable", async () => {
  const sql = await readFile(identityMigrationPath, "utf8");

  assert.match(sql, /revoke update on public\.companies from authenticated/u);
  assert.match(sql, /revoke update on public\.company_memberships from authenticated/u);
  assert.match(sql, /drop policy if exists "owners can update their own membership acceptance"/u);
  assert.match(sql, /drop policy if exists "owners can invite company members"/u);
});

test("production privileges require a separate expiring admin grant", async () => {
  const sql = await readFile(migrationPath, "utf8");

  assert.match(sql, /create table if not exists public\.production_security_grants/u);
  assert.match(sql, /expires_at timestamptz not null/u);
  assert.match(sql, /operator\.role = 'admin'/u);
  assert.match(sql, /actor_id <> \(select auth\.uid\(\)\)/u);
  assert.match(sql, /alter table public\.production_security_grants enable row level security/u);
});

test("production security approvals are append-only and revocations identify the operator", async () => {
  const sql = await readFile(grantImmutabilityMigrationPath, "utf8");

  assert.match(sql, /add column if not exists revoked_by uuid/u);
  assert.match(sql, /production security approval metadata is immutable/u);
  assert.match(sql, /production security grants support one-way revocation only/u);
  assert.match(sql, /revoke update on public\.production_security_grants from authenticated/u);
  assert.match(sql, /grant update \(revoked_at\)/u);
  assert.match(sql, /new\.revoked_by := auth\.uid\(\)/u);
  assert.match(sql, /create policy "admins can revoke production security grants"/u);
  assert.match(sql, /revoked_by = \(select auth\.uid\(\)\)/u);
});

test("launch signoff transitions are preserved in append-only history", async () => {
  const sql = await readFile(launchHistoryMigrationPath, "utf8");

  assert.match(sql, /create table if not exists public\.launch_signoff_events/u);
  assert.match(sql, /revoke insert, update, delete on public\.launch_signoff_events/u);
  assert.match(sql, /active operators can read launch signoff history/u);
  assert.match(sql, /security definer/u);
  assert.match(sql, /after insert or update on public\.launch_signoffs/u);
  assert.match(sql, /lower\(tg_op\)/u);
});

test("owner dividend ledger, action, and generated PDF metadata persist atomically", async () => {
  const sql = await readFile(ownerDividendMigrationPath, "utf8");

  assert.match(sql, /create or replace function public\.record_owner_dividend_action/u);
  assert.match(sql, /security invoker/u);
  assert.match(sql, /p_payload ->> 'document_status' <> 'attached'/u);
  assert.match(sql, /owner dividend requires two valid PDF records/u);
  assert.match(sql, /owner dividend must include the complete register at an equal amount per share/u);
  assert.match(sql, /from storage\.objects object/u);
  assert.match(sql, /'generated_unsigned'/u);
  assert.match(sql, /insert into public\.ledger_entries[\s\S]*insert into public\.holding_actions[\s\S]*insert into public\.documents/u);
  assert.match(sql, /revoke all on function public\.record_owner_dividend_action/u);
  assert.match(sql, /grant execute on function public\.record_owner_dividend_action[\s\S]*to authenticated/u);
});

test("security-definer RLS helpers are moved out of the exposed schema", async () => {
  const sql = await readFile(migrationPath, "utf8");

  assert.match(sql, /create schema if not exists private/u);
  assert.match(sql, /function private\.is_company_creator/u);
  assert.match(sql, /function private\.can_accept_company_invitation/u);
  assert.match(sql, /drop function if exists public\.is_company_creator/u);
  assert.match(sql, /drop function if exists public\.can_accept_company_invitation/u);
});
