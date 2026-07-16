import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

import pg from "pg";

const files = await readdir(new URL("../supabase/migrations/", import.meta.url));
const migrationName = files.find((file) => file.endsWith("_rf1086_feedback_reconciliation.sql"));
assert.ok(migrationName, "the Supabase CLI must create the RF-1086 feedback migration");
const sql = await readFile(new URL(`../supabase/migrations/${migrationName}`, import.meta.url), "utf8");
const rollback = await readFile(
  new URL("../supabase/rollback/rf1086_feedback_reconciliation.sql", import.meta.url),
  "utf8",
).catch(() => "");

function isLocalDatabase() {
  if (!process.env.DATABASE_URL) return false;
  try {
    return ["127.0.0.1", "localhost"].includes(new URL(process.env.DATABASE_URL).hostname);
  } catch {
    return false;
  }
}

test("creates private, constrained feedback metadata and durable reconciliation state", () => {
  assert.match(sql, /create table(?: if not exists)? public\.production_feedback_artifacts/iu);
  assert.match(sql, /byte_length bigint not null check \(byte_length between 1 and 10485760\)/iu);
  assert.match(sql, /sha256 text not null check \(sha256 ~ '\^\[a-f0-9\]\{64\}\$'\)/iu);
  assert.match(sql, /classification text not null check \(classification in \('accepted','rejected','action_required'\)\)/iu);
  assert.match(sql, /unique \(submission_id, sha256\)/iu);
  assert.match(sql, /unique \(document_id\)/iu);
  assert.match(sql, /alter table public\.production_feedback_artifacts enable row level security/iu);
  assert.match(sql, /add column(?: if not exists)? feedback_state text not null default 'sent'/iu);
  assert.match(sql, /sent.*processing.*accepted.*rejected.*action_required.*unknown/isu);
  assert.match(sql, /feedback_artifact_count/iu);
  assert.match(sql, /feedback_last_checked_at/iu);
  assert.match(sql, /artifact_hashes text\[\]/iu);
  assert.match(sql, /safe_error_code/iu);
  assert.match(sql, /correlation_id/iu);
});

test("uses explicit least privilege grants and owner/operator read policies", () => {
  assert.match(
    sql,
    /revoke all on table public\.production_feedback_artifacts from public, anon, authenticated, service_role/iu,
  );
  assert.match(sql, /grant select on table public\.production_feedback_artifacts to authenticated, service_role/iu);
  assert.doesNotMatch(sql, /grant (?:insert|update|delete)[^;]+production_feedback_artifacts[^;]+authenticated/iu);
  assert.match(sql, /company_memberships[\s\S]+role = 'owner'[\s\S]+accepted_at is not null/iu);
  assert.match(sql, /support_operators[\s\S]+active/iu);
  assert.match(sql, /create or replace function public\.record_production_feedback_artifact/iu);
  assert.match(sql, /grant execute on function public\.record_production_feedback_artifact[^;]+to service_role/isu);
  assert.doesNotMatch(sql, /grant execute on function public\.record_production_feedback_artifact[^;]+to authenticated/isu);
  assert.match(sql, /coalesce\(\(select auth\.jwt\(\)\) ->> 'role', ''\) <> 'service_role'/iu);
});

test("recording validates exact relationships and the deterministic private key", () => {
  assert.match(sql, /s\.id = p_submission_id[\s\S]+s\.company_id = p_company_id/iu);
  assert.match(sql, /d\.id = p_document_id[\s\S]+d\.company_id = p_company_id/iu);
  assert.match(sql, /authority-feedback\/%s\/%s\/%s/iu);
  assert.match(sql, /company-documents/iu);
  assert.match(sql, /application\/xml/iu);
  assert.match(sql, /application\/pdf/iu);
  assert.match(sql, /text\/plain/iu);
  assert.match(sql, /application\/octet-stream/iu);
  assert.match(sql, /on conflict \(submission_id, sha256\) do nothing/iu);
  assert.match(sql, /company members can read company document objects/iu);
  assert.match(sql, /authority-feedback/iu);
});

test("change-only reconciliation events are serialized and expose safe diagnostics only", () => {
  const appendSql = sql.match(
    /create or replace function public\.append_production_feedback_reconciliation[\s\S]+?\n\$\$;/iu,
  )?.[0] ?? "";
  assert.match(sql, /create or replace function public\.claim_production_feedback_reconciliation/iu);
  assert.match(sql, /feedback_reconciliation_lease_id/iu);
  assert.match(sql, /interval '5 minutes'/iu);
  assert.match(sql, /create or replace function public\.append_production_feedback_reconciliation/iu);
  assert.match(sql, /p_lease_id is null/iu);
  assert.match(sql, /v_previous\.resulting_status =/iu);
  assert.match(sql, /v_previous\.artifact_hashes = v_hashes/iu);
  assert.match(sql, /operation_name[\s\S]+reconciliation:/iu);
  assert.match(sql, /p_safe_error_code !~ '\^\[A-Z0-9_\]/iu);
  assert.match(sql, /p_correlation_id !~ '\^\[A-Za-z0-9/iu);
  assert.doesNotMatch(appendSql, /xml|payload|organization_number|org_number|external_ref/iu);
});

test("rollback revokes functions first and restores only feature-owned schema and storage policy changes", () => {
  assert.ok(rollback, "rollback migration is required");
  const revokeIndex = rollback.indexOf("revoke all on function public.append_production_feedback_reconciliation");
  const tableDropIndex = rollback.indexOf("drop table if exists public.production_feedback_artifacts");
  assert.ok(revokeIndex >= 0 && tableDropIndex > revokeIndex);
  assert.match(rollback, /drop function if exists public\.record_production_feedback_artifact/iu);
  assert.match(rollback, /drop function if exists public\.claim_production_feedback_reconciliation/iu);
  assert.match(rollback, /drop column if exists feedback_state/iu);
  assert.match(rollback, /drop column if exists artifact_hashes/iu);
  assert.match(rollback, /company members can read company document objects/iu);
});

test(
  "local Supabase exposes read-only RLS metadata and service-only mutation RPCs",
  { skip: isLocalDatabase() ? false : "local Supabase DATABASE_URL is required", timeout: 30_000 },
  async () => {
    const database = new pg.Client({ connectionString: process.env.DATABASE_URL });
    await database.connect();
    try {
      const { rows: [table] } = await database.query(`
        select relrowsecurity,
          has_table_privilege('authenticated', 'public.production_feedback_artifacts', 'select') as authenticated_select,
          has_table_privilege('authenticated', 'public.production_feedback_artifacts', 'insert') as authenticated_insert,
          has_table_privilege('service_role', 'public.production_feedback_artifacts', 'insert') as service_insert
        from pg_class
        where oid = 'public.production_feedback_artifacts'::regclass
      `);
      assert.equal(table.relrowsecurity, true);
      assert.equal(table.authenticated_select, true);
      assert.equal(table.authenticated_insert, false);
      assert.equal(table.service_insert, false);

      const { rows: [functions] } = await database.query(`
        select
          has_function_privilege('authenticated', 'public.record_production_feedback_artifact(uuid,uuid,uuid,text,text,bigint,text,text)', 'execute') as authenticated_record,
          has_function_privilege('service_role', 'public.record_production_feedback_artifact(uuid,uuid,uuid,text,text,bigint,text,text)', 'execute') as service_record,
          has_function_privilege('authenticated', 'public.append_production_feedback_reconciliation(uuid,uuid,uuid,text,text[],text,text)', 'execute') as authenticated_append,
          has_function_privilege('service_role', 'public.append_production_feedback_reconciliation(uuid,uuid,uuid,text,text[],text,text)', 'execute') as service_append
      `);
      assert.equal(functions.authenticated_record, false);
      assert.equal(functions.service_record, true);
      assert.equal(functions.authenticated_append, false);
      assert.equal(functions.service_append, true);

      for (const role of ["authenticated", "service_role"]) {
        await database.query("begin");
        try {
          await database.query(`set local role ${role}`);
          await assert.rejects(
            database.query("insert into public.production_feedback_artifacts default values"),
            (error) => error?.code === "42501",
          );
        } finally {
          await database.query("rollback");
        }
      }
      await database.query("begin");
      try {
        await database.query("set local role authenticated");
        await assert.rejects(
          database.query("select public.claim_production_feedback_reconciliation(gen_random_uuid(), gen_random_uuid())"),
          (error) => error?.code === "42501",
        );
      } finally {
        await database.query("rollback");
      }

      const { rows: [bucket] } = await database.query(`
        select public, allowed_mime_types
        from storage.buckets
        where id = 'company-documents'
      `);
      assert.equal(bucket.public, false);
      for (const contentType of ["application/xml", "text/xml", "application/pdf", "text/plain", "application/octet-stream"]) {
        assert.ok(bucket.allowed_mime_types.includes(contentType));
      }
    } finally {
      await database.end();
    }
  },
);
