import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationUrl = new URL(
  "../supabase/migrations/20260801090000_company_access_invitations.sql",
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

  assert.match(sql, /revoke insert, update, delete on public\.company_invitations from authenticated/iu);
  assert.match(sql, /revoke insert, update, delete on public\.company_memberships from authenticated/iu);
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
