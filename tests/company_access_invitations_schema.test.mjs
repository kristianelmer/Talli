import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationUrl = new URL(
  "../supabase/migrations/20260801090000_company_access_invitations.sql",
  import.meta.url,
);
const contractMigrationUrl = new URL(
  "../supabase/migrations/20260801091000_company_access_invitations_contract.sql",
  import.meta.url,
);

test("invitation acceptance and membership administration use atomic bearer-scoped RPCs", async () => {
  const sql = await readFile(migrationUrl, "utf8");

  for (const functionName of [
    "company_access_accept_invitation",
    "company_access_administer_membership",
  ]) {
    assert.match(sql, new RegExp(`create or replace function public\\.${functionName}`, "iu"));
    assert.match(sql, new RegExp(`grant execute on function public\\.${functionName}`, "iu"));
  }
  assert.match(sql, /insert into public\.company_memberships[\s\S]+update public\.company_invitations/iu);
  assert.match(sql, /delete from public\.company_memberships|update public\.company_memberships/iu);
  assert.match(sql, /auth\.uid\(\)/iu);
  assert.match(sql, /auth\.jwt\(\)[\s\S]+email/iu);
  assert.doesNotMatch(sql, /service_role/iu);
});

test("invitation and membership mutations are not directly granted to authenticated web callers", async () => {
  const sql = await readFile(migrationUrl, "utf8");
  const contractSql = await readFile(contractMigrationUrl, "utf8");

  assert.match(contractSql, /revoke insert, update, delete on public\.company_invitations from authenticated/iu);
  assert.match(contractSql, /drop policy if exists "invited users can accept company memberships"/iu);
  assert.match(contractSql, /revoke select on public\.company_invitations from authenticated/iu);
  assert.match(contractSql, /grant select \([\s\S]+\) on public\.company_invitations to authenticated/iu);
  const invitationSelectGrant = contractSql.match(
    /grant select \(([\s\S]+?)\) on public\.company_invitations to authenticated/iu,
  )?.[1] ?? "";
  assert.doesNotMatch(invitationSelectGrant, /token_hash/iu);
  assert.match(sql, /accepted_at is not null/iu);
  assert.match(sql, /role = 'owner'/iu);
  assert.match(sql, /role in \('reviewer', 'read_only'\)/iu);
});

test("invitation lookup is recipient-bound, expiry-aware, and never returns token hashes", async () => {
  const sql = await readFile(migrationUrl, "utf8");
  const lookup = sql.match(
    /create or replace function public\.company_access_lookup_invitation[\s\S]+?\$function\$;/iu,
  )?.[0] ?? "";

  assert.match(lookup, /i\.token_hash = p_token_hash/iu);
  assert.match(lookup, /invited_email[\s\S]+lower/iu);
  assert.match(lookup, /status = 'pending'/iu);
  assert.match(lookup, /expires_at > statement_timestamp\(\)/iu);
  const returnedColumns = lookup.match(/returns table \(([\s\S]+?)\)\s*language/iu)?.[1] ?? "";
  assert.doesNotMatch(returnedColumns, /token_hash/iu);
});

test("command functions execute through a restricted RLS role instead of the migration owner", async () => {
  const sql = await readFile(migrationUrl, "utf8");

  assert.match(sql, /create role company_access_executor[\s\S]+nobypassrls/iu);
  assert.match(sql, /alter function public\.company_access_create_invitation[\s\S]+owner to company_access_executor/iu);
  assert.match(sql, /alter function public\.company_access_accept_invitation[\s\S]+owner to company_access_executor/iu);
  assert.match(sql, /create policy "company access commands create invitations"[\s\S]+to company_access_executor/iu);
  assert.match(sql, /create policy "company access commands accept memberships"[\s\S]+to company_access_executor/iu);
  assert.doesNotMatch(sql, /alter role company_access_executor[\s\S]+bypassrls/iu);
});

test("recipient table enumeration is removed and lookup requires the presented token", async () => {
  const contractSql = await readFile(contractMigrationUrl, "utf8");
  const lookupSql = await readFile(migrationUrl, "utf8");

  assert.match(contractSql, /create policy "accepted owners can read company invitations"/iu);
  const ownerPolicy = contractSql.match(
    /create policy "accepted owners can read company invitations"[\s\S]+?\);/iu,
  )?.[0] ?? "";
  assert.doesNotMatch(ownerPolicy, /invited_email|email/iu);
  assert.match(contractSql, /revoke select on public\.company_invitations from authenticated/iu);
  assert.match(lookupSql, /i\.token_hash = p_token_hash/iu);
});

test("acceptance binds the verified Auth identity and rejects stale JWT claims atomically", async () => {
  const sql = await readFile(migrationUrl, "utf8");
  const accept = sql.match(
    /create or replace function public\.company_access_accept_invitation[\s\S]+?\$function\$;/iu,
  )?.[0] ?? "";

  assert.match(accept, /p_verified_subject uuid/iu);
  assert.match(accept, /p_verified_email text/iu);
  assert.match(accept, /p_verified_subject[^;]+auth\.uid\(\)/iu);
  assert.match(accept, /v_email <> lower\(coalesce\(auth\.jwt\(\) ->> 'email', ''\)\)/iu);
  assert.match(accept, /for update/iu);
  assert.match(accept, /insert into public\.company_memberships[\s\S]+update public\.company_invitations/iu);
});

test("consequential commands have durable replay receipts and concurrency preconditions", async () => {
  const sql = await readFile(migrationUrl, "utf8");

  assert.match(sql, /create table if not exists public\.company_access_command_receipts/iu);
  assert.match(sql, /operation_id uuid primary key/iu);
  assert.match(sql, /request_fingerprint text not null/iu);
  assert.match(sql, /delivery_token text/iu);
  assert.match(sql, /p_operation_id uuid/iu);
  assert.match(sql, /p_expected_updated_at timestamptz/iu);
  assert.match(sql, /p_expected_role text/iu);
  assert.match(sql, /for update/iu);
});

test("pgcrypto hashing resolves the extension schema under an empty search path", async () => {
  const sql = await readFile(migrationUrl, "utf8");

  assert.match(sql, /from pg_catalog\.pg_extension[\s\S]+pg_catalog\.pg_namespace/iu);
  assert.match(sql, /format\([\s\S]+%I\.digest/iu);
  assert.doesNotMatch(sql, /(?<!\.)\bdigest\s*\(/iu);
});

test("expand and contract migrations preserve an explicit mixed-revision overlap", async () => {
  const expandSql = await readFile(migrationUrl, "utf8");
  const contractSql = await readFile(contractMigrationUrl, "utf8");

  assert.doesNotMatch(expandSql, /revoke insert, update, delete on public\.company_invitations from authenticated/iu);
  assert.match(contractSql, /revoke insert, update, delete on public\.company_invitations from authenticated/iu);
  assert.match(contractSql, /drop policy if exists "owners can create company invitations"/iu);
  assert.match(contractSql, /drop policy if exists "invited users can accept company memberships"/iu);
  assert.doesNotMatch(contractSql, /revoke insert, update on public\.company_memberships from authenticated/iu);
});
