import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationPath = "supabase/migrations/20260713121355_secure_step_up_attestation.sql";
const identityMigrationPath = "supabase/migrations/20260713122759_lock_membership_and_company_identity.sql";
const cancellationMigrationPath = "supabase/migrations/20260713122955_secure_cancellation_transitions.sql";

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

test("security-definer RLS helpers are moved out of the exposed schema", async () => {
  const sql = await readFile(migrationPath, "utf8");

  assert.match(sql, /create schema if not exists private/u);
  assert.match(sql, /function private\.is_company_creator/u);
  assert.match(sql, /function private\.can_accept_company_invitation/u);
  assert.match(sql, /drop function if exists public\.is_company_creator/u);
  assert.match(sql, /drop function if exists public\.can_accept_company_invitation/u);
});
