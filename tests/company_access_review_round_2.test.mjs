import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("..", import.meta.url);

async function source(path) {
  return readFile(new URL(path, root), "utf8");
}

test("authorization and hashing use versioned least-privilege helper boundaries", async () => {
  const sql = await source("supabase/migrations/20260801090000_company_access_invitations.sql");

  assert.match(sql, /function public\.company_access_is_accepted_owner_v1\(/u);
  assert.match(sql, /function public\.company_access_current_identity_v1\(\)/u);
  assert.match(sql, /company_access_current_identity_v1[\s\S]+from auth\.users/u);
  assert.match(sql, /company_access_current_identity_v1[\s\S]+security definer[\s\S]+set search_path = ''/u);
  assert.match(sql, /function public\.company_access_token_hash_v1\(/u);
  assert.match(sql, /company_access_token_hash_v1[\s\S]+security definer[\s\S]+set search_path = ''/u);
  assert.match(
    sql,
    /revoke all on function public\.company_access_current_identity_v1\(\) from public, anon, authenticated/u,
  );
  assert.match(
    sql,
    /revoke all on function public\.company_access_token_hash_v1\(text\) from public, anon, authenticated/u,
  );
  assert.match(sql, /grant execute on function public\.company_access_current_identity_v1\(\) to company_access_executor/u);
  assert.doesNotMatch(sql, /grant usage on schema extensions to company_access_executor/iu);
  assert.doesNotMatch(sql, /company_access_is_accepted_owner\(/u);
});

test("destructive contract is a later release artifact outside the automatic runner", async () => {
  const migrations = await readdir(new URL("supabase/migrations/", root));
  const contract = await source(
    "supabase/contract-migrations/20260801091000_company_access_invitations_contract.sql",
  );

  assert.equal(migrations.some((name) => name.includes("company_access_invitations_contract")), false);
  assert.match(contract, /CONTRACT RELEASE ARTIFACT/u);
  assert.match(contract, /revoke insert, update, delete on public\.company_invitations/u);
});

test("cutover removes every authenticated self-membership update surface", async () => {
  const expand = await source("supabase/migrations/20260801090000_company_access_invitations.sql");
  const contract = await source(
    "supabase/contract-migrations/20260801091000_company_access_invitations_contract.sql",
  );
  const combined = `${expand}\n${contract}`;

  assert.match(combined, /drop policy if exists "owners can update their own membership acceptance"/iu);
  assert.match(combined, /revoke update on public\.company_memberships from authenticated/iu);
});

test("command receipts are backend-system technical idempotency state", async () => {
  const catalog = JSON.parse(await source("architecture/database-catalog.json"));
  const backendSystem = JSON.parse(await source("architecture/backend-system.json"));
  const capability = JSON.parse(
    await source("apps/backend/src/talli_backend/modules/company_access/module.json"),
  );

  const receipt = catalog.tables.find(
    ({ name }) => name === "public.company_access_command_receipts",
  );
  assert.deepEqual(receipt, {
    name: "public.company_access_command_receipts",
    kind: "technical",
  });
  assert.ok(backendSystem.technicalOwnership.tables.includes(receipt.name));
  assert.ok(
    backendSystem.technicalOwnership.migrations.includes(
      "supabase/migrations/20260801090000_company_access_invitations.sql",
    ),
  );
  assert.equal(capability.owns.tables.includes(receipt.name), false);
});

test("owner receipt visibility is atomic while acceptance keeps actor replay semantics", async () => {
  const sql = await source("supabase/migrations/20260801090000_company_access_invitations.sql");
  const receiptPolicy = sql.match(
    /create policy "company access commands read receipts"[\s\S]+?;\n\n/u,
  )?.[0];

  assert.ok(receiptPolicy);
  assert.match(receiptPolicy, /command_name = 'accept_invitation'[\s\S]+actor_id = \(select auth\.uid\(\)\)/u);
  assert.match(
    receiptPolicy,
    /command_name in \('create_invitation', 'revoke_invitation', 'resend_invitation', 'administer_membership'\)/u,
  );
  assert.match(receiptPolicy, /expires_at > statement_timestamp\(\)/u);
  assert.match(receiptPolicy, /auth\.jwt\(\)[\s\S]+aal2/u);
  assert.match(receiptPolicy, /company_access_is_accepted_owner_v1\(company_id\)/u);
  assert.match(
    sql,
    /function public\.company_access_receipt_exists_v1\(\s*p_operation_id uuid,\s*p_company_id uuid,\s*p_command_name text,\s*p_request_fingerprint text\s*\)/u,
  );
  assert.match(sql, /r\.actor_id = \(select auth\.uid\(\)\)/u);
  assert.match(sql, /r\.company_id = p_company_id/u);
  assert.match(sql, /r\.command_name = p_command_name/u);
  assert.match(sql, /r\.request_fingerprint = p_request_fingerprint/u);
  assert.match(
    sql,
    /revoke all on function public\.company_access_receipt_exists_v1\(uuid, uuid, text, text\) from public, anon, authenticated/u,
  );
  assert.match(
    sql,
    /grant execute on function public\.company_access_receipt_exists_v1\(uuid, uuid, text, text\) to company_access_executor/u,
  );
  for (const command of [
    "create_invitation",
    "revoke_invitation",
    "resend_invitation",
    "administer_membership",
  ]) {
    assert.match(
      sql,
      new RegExp(
        `company_access_receipt_exists_v1\\(\\s*p_operation_id, p_company_id, '${command}', v_fingerprint\\s*\\)`,
        "u",
      ),
      command,
    );
  }
  assert.equal(
    sql.match(/where r\.actor_id = v_actor_id and r\.operation_id = p_operation_id/gu)?.length,
    7,
    "every command and side-effect receipt lookup must use the actor namespace",
  );
  assert.equal(
    sql.match(
      /pg_advisory_xact_lock\(pg_catalog\.hashtextextended\(v_actor_id::text \|\| '\|' \|\| p_operation_id::text, 160\)\)/gu,
    )?.length,
    5,
    "every command lock must use the same actor and operation namespace",
  );
});

test("evidence distinguishes forced receipt RLS from genuine non-owner RLS", async () => {
  const progress = await source(".superpowers/sdd/progress.md");
  const docs = await source("apps/backend/src/talli_backend/modules/company_access/MODULE.md");

  assert.doesNotMatch(progress, /executor[^\n]+against forced RLS/iu);
  assert.match(docs, /forced RLS applies only to the technical command-receipt table/iu);
});

test("OpenAPI validates command UUIDs and RFC3339 revisions", async () => {
  const contract = JSON.parse(await source("contracts/openapi/talli-v1.json"));
  const schemas = contract.components.schemas;

  for (const name of [
    "CreateCompanyInvitationRequest",
    "AcceptCompanyInvitationRequest",
    "CompanyInvitationCommandRequest",
    "AdministerCompanyMembershipRequest",
  ]) {
    assert.equal(schemas[name].properties.operationId.format, "uuid", name);
  }
  assert.equal(
    schemas.CompanyInvitationCommandRequest.properties.expectedUpdatedAt.format,
    "date-time",
  );
  assert.equal(schemas.CreateCompanyInvitationRequest.properties.companyId.format, "uuid");
});
