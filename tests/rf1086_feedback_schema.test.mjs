import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

import { createClient } from "@supabase/supabase-js";
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

function isLocalRuntime() {
  if (!isLocalDatabase()) return false;
  if (!["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"].every((key) => process.env[key])) {
    return false;
  }
  try {
    return ["127.0.0.1", "localhost"].includes(new URL(process.env.SUPABASE_URL).hostname);
  } catch {
    return false;
  }
}

function serviceClient() {
  return createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

function anonClient() {
  return createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

async function createConfirmedUser(admin, label) {
  const user = {
    email: `talli-feedback-${label}-${randomUUID()}@example.test`,
    password: `Talli-${randomUUID()}!`,
  };
  const { data, error } = await admin.auth.admin.createUser({
    ...user,
    email_confirm: true,
  });
  assert.ifError(error);
  return { ...user, id: data.user.id };
}

async function signIn(user) {
  const client = anonClient();
  const { error } = await client.auth.signInWithPassword({
    email: user.email,
    password: user.password,
  });
  assert.ifError(error);
  return client;
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
  assert.match(
    sql,
    /company members can read document metadata[\s\S]+document_type = 'authority_feedback'[\s\S]+role = 'owner'[\s\S]+accepted_at is not null[\s\S]+support_operators[\s\S]+active/iu,
  );
  assert.match(
    sql,
    /company members can read company document objects[\s\S]+authority-feedback[\s\S]+role = 'owner'[\s\S]+accepted_at is not null[\s\S]+support_operators[\s\S]+active/iu,
  );
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

test("backfills and atomically claims only an exact valid succeeded confirmation reference", () => {
  assert.match(sql, /latest_succeeded_confirm/iu);
  assert.match(sql, /operation_name = 'confirm'[\s\S]+operation_state = 'succeeded'/iu);
  assert.match(sql, /create or replace function public\.rf1086_confirmation_forsendelse_id\(p_reference text\)/iu);
  assert.match(sql, /exception when invalid_text_representation then[\s\S]+return null/iu);
  assert.match(
    sql,
    /revoke all on function public\.rf1086_confirmation_forsendelse_id\(text\)[^;]+from public, anon, authenticated, service_role/isu,
  );
  assert.match(sql, /jsonb_typeof\([^;]+?\) is distinct from 'object'/iu);
  assert.match(sql, /jsonb_object_keys/iu);
  assert.match(sql, /dialogId/iu);
  assert.match(sql, /forsendelseId/iu);
  assert.match(sql, /feedback_forsendelse_id = [^;]+forsendelse/iu);

  const claimSql = sql.match(
    /create or replace function public\.claim_production_feedback_reconciliation[\s\S]+?\n\$\$;/iu,
  )?.[0] ?? "";
  assert.match(claimSql, /from public\.production_filing_submissions[\s\S]+for update/iu);
  assert.match(claimSql, /operation_name = 'confirm'[\s\S]+operation_state = 'succeeded'/iu);
  assert.match(claimSql, /public\.rf1086_confirmation_forsendelse_id\(v_authority_reference\)/iu);
  assert.match(claimSql, /feedback_forsendelse_id[\s\S]+is distinct from[\s\S]+forsendelse/iu);
  assert.match(
    claimSql,
    /set feedback_forsendelse_id = [^,]+,[\s\S]+feedback_reconciliation_lease_id = p_lease_id/iu,
  );
  assert.match(claimSql, /feedback_state not in \('sent', 'processing', 'unknown'\)/iu);
  assert.match(claimSql, /interval '5 minutes'/iu);
});

test("rollback revokes functions first and restores only feature-owned schema and storage policy changes", () => {
  assert.ok(rollback, "rollback migration is required");
  const revokeIndex = rollback.indexOf("revoke all on function public.append_production_feedback_reconciliation");
  const tableDropIndex = rollback.indexOf("drop table if exists public.production_feedback_artifacts");
  assert.ok(revokeIndex >= 0 && tableDropIndex > revokeIndex);
  assert.match(rollback, /drop function if exists public\.record_production_feedback_artifact/iu);
  assert.match(rollback, /drop function if exists public\.claim_production_feedback_reconciliation/iu);
  assert.match(rollback, /drop function if exists public\.rf1086_confirmation_forsendelse_id/iu);
  assert.match(rollback, /drop column if exists feedback_state/iu);
  assert.match(rollback, /drop column if exists artifact_hashes/iu);
  assert.match(rollback, /company members can read company document objects/iu);
  assert.match(rollback, /company members can read document metadata/iu);
  const restoredDocumentPolicy = rollback.match(
    /create policy "company members can read document metadata"[\s\S]+?\n\);/iu,
  )?.[0] ?? "";
  assert.match(restoredDocumentPolicy, /company_memberships/iu);
  assert.doesNotMatch(restoredDocumentPolicy, /authority_feedback|role = 'owner'|support_operators/iu);
  const restoredStoragePolicy = rollback.match(
    /create policy "company members can read company document objects"[\s\S]+?\n\);/iu,
  )?.[0] ?? "";
  assert.doesNotMatch(restoredStoragePolicy, /authority-feedback|role = 'owner'|support_operators/iu);
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
          has_function_privilege('authenticated', 'public.claim_production_feedback_reconciliation(uuid,uuid)', 'execute') as authenticated_claim,
          has_function_privilege('service_role', 'public.claim_production_feedback_reconciliation(uuid,uuid)', 'execute') as service_claim,
          has_function_privilege('authenticated', 'public.append_production_feedback_reconciliation(uuid,uuid,uuid,text,text[],text,text)', 'execute') as authenticated_append,
          has_function_privilege('service_role', 'public.append_production_feedback_reconciliation(uuid,uuid,uuid,text,text[],text,text)', 'execute') as service_append,
          has_function_privilege('authenticated', 'public.rf1086_confirmation_forsendelse_id(text)', 'execute') as authenticated_parse,
          has_function_privilege('service_role', 'public.rf1086_confirmation_forsendelse_id(text)', 'execute') as service_parse
      `);
      assert.equal(functions.authenticated_record, false);
      assert.equal(functions.service_record, true);
      assert.equal(functions.authenticated_claim, false);
      assert.equal(functions.service_claim, true);
      assert.equal(functions.authenticated_append, false);
      assert.equal(functions.service_append, true);
      assert.equal(functions.authenticated_parse, false);
      assert.equal(functions.service_parse, false);

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

test(
  "local Supabase recovers confirmed submissions and limits feedback data to authorized readers",
  { skip: isLocalRuntime() ? false : "local Supabase runtime variables are required", timeout: 120_000 },
  async () => {
    const database = new pg.Client({ connectionString: process.env.DATABASE_URL });
    await database.connect();
    const admin = serviceClient();
    const users = [];
    const clients = [];
    const companyId = randomUUID();
    const previewId = randomUUID();
    const entitlementId = randomUUID();
    const approvalId = randomUUID();
    const submissionId = randomUUID();
    const feedbackDocumentId = randomUUID();
    const normalDocumentId = randomUUID();
    const dialogId = randomUUID();
    const forsendelseId = randomUUID();
    const firstLeaseId = randomUUID();
    const competingLeaseId = randomUUID();
    const persistenceFailureLeaseId = randomUUID();
    const persistenceRetryLeaseId = randomUUID();
    const feedbackHash = "a".repeat(64);
    const feedbackKey = `authority-feedback/${companyId}/${submissionId}/${feedbackHash}`;
    const normalKey = `${companyId}/2025/${normalDocumentId}/ordinary.pdf`;

    try {
      const ownerUser = await createConfirmedUser(admin, "owner");
      const reviewerUser = await createConfirmedUser(admin, "reviewer");
      const readOnlyUser = await createConfirmedUser(admin, "read-only");
      const operatorUser = await createConfirmedUser(admin, "operator");
      users.push(ownerUser, reviewerUser, readOnlyUser, operatorUser);

      const owner = await signIn(ownerUser);
      const reviewer = await signIn(reviewerUser);
      const readOnly = await signIn(readOnlyUser);
      const operator = await signIn(operatorUser);
      clients.push(owner, reviewer, readOnly, operator);

      await database.query(
        `insert into public.companies (id, org_number, name, entity_type, created_by)
         values ($1, $2, 'Feedback RLS Company', 'AS', $3)`,
        [companyId, String(100_000_000 + Math.floor(Math.random() * 899_999_999)), ownerUser.id],
      );
      await database.query(
        `insert into public.company_memberships (company_id, user_id, role, accepted_at)
         values ($1, $2, 'owner', now()), ($1, $3, 'reviewer', now()), ($1, $4, 'read_only', now())`,
        [companyId, ownerUser.id, reviewerUser.id, readOnlyUser.id],
      );
      await database.query(
        `insert into public.support_operators (user_id, role, active) values ($1, 'support', true)`,
        [operatorUser.id],
      );
      await database.query(
        `insert into public.filing_previews (
           id, company_id, income_year, filing, status, issues, preview,
           hovedskjema_xml, underskjema_xml, created_by
         ) values ($1, $2, 2025, 'RF-1086', 'ready', '[]', 'preview', '<xml/>', '{}', $3)`,
        [previewId, companyId, ownerUser.id],
      );
      await database.query(
        `insert into public.production_pilot_entitlements (
           id, company_id, user_id, income_year, obligation, case_profile, status,
           billing_exempt, system_user_external_reference, starts_at, expires_at,
           evidence_reference, approved_by
         ) values (
           $1, $2, $3, 2025, 'aksjonaerregisteroppgaven', 'rf1086_no_activity_v1', 'revoked',
           true, 'feedback-rls-test', now() - interval '2 hours', now() - interval '1 hour',
           'local feedback RLS test', $3
         )`,
        [entitlementId, companyId, ownerUser.id],
      );
      await database.query(
        `insert into public.filing_approval_snapshots (
           id, entitlement_id, preview_id, company_id, user_id, income_year,
           obligation, case_profile, adapter_version, payload_hash, manifest_hash,
           manifest, approved_by, invalidated_at, invalidation_reason
         ) values (
           $1, $2, $3, $4, $5, 2025, 'aksjonaerregisteroppgaven', 'rf1086_no_activity_v1',
           'test-v1', $6, $7, '{}', $5, now(), 'entitlement revoked'
         )`,
        [approvalId, entitlementId, previewId, companyId, ownerUser.id, "b".repeat(64), "c".repeat(64)],
      );
      await database.query(
        `insert into public.production_filing_submissions (
           id, approval_id, entitlement_id, company_id, user_id, income_year,
           obligation, case_profile, payload_hash, adapter_version, environment,
           status, submitted_by
         ) values (
           $1, $2, $3, $4, $5, 2025, 'aksjonaerregisteroppgaven', 'rf1086_no_activity_v1',
           $6, 'test-v1', 'production', 'received', $5
         )`,
        [submissionId, approvalId, entitlementId, companyId, ownerUser.id, "b".repeat(64)],
      );
      await database.query(
        `insert into public.production_filing_events (
           submission_id, operation_name, operation_state, attempt, body_hash,
           idempotency_key, authority_reference, failure_class, resulting_status
         ) values ($1, 'confirm', 'succeeded', 1, $2, $3, $4, null, 'received')`,
        [
          submissionId,
          "d".repeat(64),
          randomUUID(),
          JSON.stringify({ dialogId, forsendelseId }),
        ],
      );

      // Reapplying the additive migration simulates upgrading a pre-Task-6
      // submission whose immutable confirmation event already exists.
      await database.query(sql);
      const backfilled = await database.query(
        `select feedback_forsendelse_id
         from public.production_filing_submissions where id = $1`,
        [submissionId],
      );
      assert.equal(backfilled.rows[0].feedback_forsendelse_id, forsendelseId);

      await database.query(
        `update public.production_filing_submissions
         set feedback_forsendelse_id = null,
             feedback_reconciliation_lease_id = null,
             feedback_reconciliation_started_at = null
         where id = $1`,
        [submissionId],
      );
      const [firstClaim, competingClaim] = await Promise.all([
        admin.rpc("claim_production_feedback_reconciliation", {
          p_submission_id: submissionId,
          p_lease_id: firstLeaseId,
        }),
        admin.rpc("claim_production_feedback_reconciliation", {
          p_submission_id: submissionId,
          p_lease_id: competingLeaseId,
        }),
      ]);
      assert.ifError(firstClaim.error);
      assert.ifError(competingClaim.error);
      assert.deepEqual([firstClaim.data, competingClaim.data].sort(), [false, true]);
      const recovered = await database.query(
        `select feedback_forsendelse_id, feedback_reconciliation_lease_id
         from public.production_filing_submissions where id = $1`,
        [submissionId],
      );
      assert.equal(recovered.rows[0].feedback_forsendelse_id, forsendelseId);
      assert.ok([firstLeaseId, competingLeaseId].includes(recovered.rows[0].feedback_reconciliation_lease_id));

      const released = await admin.rpc("release_production_feedback_reconciliation", {
        p_submission_id: submissionId,
        p_lease_id: recovered.rows[0].feedback_reconciliation_lease_id,
      });
      assert.ifError(released.error);
      assert.equal(released.data, true);

      const persistenceFailureClaim = await admin.rpc("claim_production_feedback_reconciliation", {
        p_submission_id: submissionId,
        p_lease_id: persistenceFailureLeaseId,
      });
      assert.ifError(persistenceFailureClaim.error);
      assert.equal(persistenceFailureClaim.data, true);
      const persistenceFailure = await admin.rpc("append_production_feedback_reconciliation", {
        p_submission_id: submissionId,
        p_lease_id: persistenceFailureLeaseId,
        p_forsendelse_id: forsendelseId,
        p_state: "unknown",
        p_artifact_hashes: [],
        p_safe_error_code: "RF1086_FEEDBACK_ARTIFACT_PERSIST_RETRY",
        p_correlation_id: null,
      });
      assert.ifError(persistenceFailure.error);
      assert.equal(persistenceFailure.data, true);
      const persistenceFailureRelease = await admin.rpc("release_production_feedback_reconciliation", {
        p_submission_id: submissionId,
        p_lease_id: persistenceFailureLeaseId,
      });
      assert.ifError(persistenceFailureRelease.error);
      assert.equal(persistenceFailureRelease.data, true);
      const persistenceRetryClaim = await admin.rpc("claim_production_feedback_reconciliation", {
        p_submission_id: submissionId,
        p_lease_id: persistenceRetryLeaseId,
      });
      assert.ifError(persistenceRetryClaim.error);
      assert.equal(persistenceRetryClaim.data, true);
      const persistenceRetryRelease = await admin.rpc("release_production_feedback_reconciliation", {
        p_submission_id: submissionId,
        p_lease_id: persistenceRetryLeaseId,
      });
      assert.ifError(persistenceRetryRelease.error);
      assert.equal(persistenceRetryRelease.data, true);

      await database.query(
        `update public.production_filing_submissions
         set feedback_forsendelse_id = $2,
             feedback_reconciliation_lease_id = null,
             feedback_reconciliation_started_at = null
         where id = $1`,
        [submissionId, randomUUID()],
      );
      const mismatchedClaim = await admin.rpc("claim_production_feedback_reconciliation", {
        p_submission_id: submissionId,
        p_lease_id: randomUUID(),
      });
      assert.match(mismatchedClaim.error?.message ?? "", /confirmation_relationship_mismatch/iu);
      await database.query(
        `update public.production_filing_submissions
         set feedback_forsendelse_id = null,
             feedback_reconciliation_lease_id = null,
             feedback_reconciliation_started_at = null
         where id = $1`,
        [submissionId],
      );

      await database.query(
        `insert into public.production_filing_events (
           submission_id, operation_name, operation_state, attempt, body_hash,
           idempotency_key, authority_reference, failure_class, resulting_status
         ) values ($1, 'confirm', 'succeeded', 2, $2, $3, $4, null, 'received')`,
        [
          submissionId,
          "e".repeat(64),
          randomUUID(),
          JSON.stringify({ dialogId, forsendelseId: "not-a-uuid" }),
        ],
      );
      const malformedClaim = await admin.rpc("claim_production_feedback_reconciliation", {
        p_submission_id: submissionId,
        p_lease_id: randomUUID(),
      });
      assert.match(malformedClaim.error?.message ?? "", /confirmation_reference_invalid/iu);

      await database.query(
        `insert into public.production_filing_events (
           submission_id, operation_name, operation_state, attempt, body_hash,
           idempotency_key, authority_reference, failure_class, resulting_status
         ) values ($1, 'confirm', 'succeeded', 3, $2, $3, '{malformed', null, 'received')`,
        [submissionId, "f".repeat(64), randomUUID()],
      );
      const invalidJsonClaim = await admin.rpc("claim_production_feedback_reconciliation", {
        p_submission_id: submissionId,
        p_lease_id: randomUUID(),
      });
      assert.match(invalidJsonClaim.error?.message ?? "", /confirmation_reference_invalid/iu);
      const unclaimed = await database.query(
        `select feedback_forsendelse_id, feedback_reconciliation_lease_id
         from public.production_filing_submissions where id = $1`,
        [submissionId],
      );
      assert.equal(unclaimed.rows[0].feedback_forsendelse_id, null);
      assert.equal(unclaimed.rows[0].feedback_reconciliation_lease_id, null);

      await database.query(
        `insert into public.documents (
           id, company_id, income_year, document_type, name, linked_to, status,
           storage_key, created_by
         ) values
           ($1, $3, 2025, 'authority_feedback', 'authority-feedback-aaaaaaaaaaaa.xml', $4, 'attached', $5, $6),
           ($2, $3, 2025, 'annual_accounts', 'ordinary.pdf', 'annual_accounts:2025', 'attached', $7, $6)`,
        [
          feedbackDocumentId,
          normalDocumentId,
          companyId,
          `production_filing_submission:${submissionId}`,
          feedbackKey,
          ownerUser.id,
          normalKey,
        ],
      );
      await database.query(
        `insert into public.production_feedback_artifacts (
           company_id, submission_id, document_id, authority_reference,
           content_type, byte_length, sha256, classification
         ) values ($1, $2, $3, 'authority-reference', 'application/xml', 8, $4, 'accepted')`,
        [companyId, submissionId, feedbackDocumentId, feedbackHash],
      );

      const uploads = [
        await admin.storage.from("company-documents").upload(feedbackKey, "feedback", {
          contentType: "application/xml",
        }),
        await admin.storage.from("company-documents").upload(normalKey, "ordinary", {
          contentType: "application/pdf",
        }),
      ];
      for (const upload of uploads) assert.ifError(upload.error);

      for (const client of [owner, operator]) {
        const feedbackDocument = await client.from("documents").select("id").eq("id", feedbackDocumentId).maybeSingle();
        assert.ifError(feedbackDocument.error);
        assert.equal(feedbackDocument.data?.id, feedbackDocumentId);
        const artifact = await client
          .from("production_feedback_artifacts")
          .select("document_id")
          .eq("document_id", feedbackDocumentId)
          .maybeSingle();
        assert.ifError(artifact.error);
        assert.equal(artifact.data?.document_id, feedbackDocumentId);
        const download = await client.storage.from("company-documents").download(feedbackKey);
        assert.ifError(download.error);
        assert.equal(await download.data.text(), "feedback");
        const signed = await client.storage.from("company-documents").createSignedUrl(feedbackKey, 60);
        assert.ifError(signed.error);
        assert.match(signed.data.signedUrl, /\/storage\/v1\/object\/sign\/company-documents\//u);
      }

      for (const client of [reviewer, readOnly]) {
        const feedbackDocument = await client.from("documents").select("id").eq("id", feedbackDocumentId).maybeSingle();
        assert.ifError(feedbackDocument.error);
        assert.equal(feedbackDocument.data, null);
        const artifact = await client
          .from("production_feedback_artifacts")
          .select("document_id")
          .eq("document_id", feedbackDocumentId)
          .maybeSingle();
        assert.ifError(artifact.error);
        assert.equal(artifact.data, null);
        const download = await client.storage.from("company-documents").download(feedbackKey);
        assert.ok(download.error);
        const signed = await client.storage.from("company-documents").createSignedUrl(feedbackKey, 60);
        assert.ok(signed.error);

        const normalDocument = await client.from("documents").select("id").eq("id", normalDocumentId).single();
        assert.ifError(normalDocument.error);
        assert.equal(normalDocument.data.id, normalDocumentId);
        const normalDownload = await client.storage.from("company-documents").download(normalKey);
        assert.ifError(normalDownload.error);
        assert.equal(await normalDownload.data.text(), "ordinary");
      }
    } finally {
      await admin.storage.from("company-documents").remove([feedbackKey, normalKey]);
      await database.query("delete from public.production_feedback_artifacts where company_id = $1", [companyId]);
      await database.query("delete from public.production_filing_submissions where company_id = $1", [companyId]);
      await database.query("delete from public.filing_approval_snapshots where company_id = $1", [companyId]);
      await database.query("delete from public.production_pilot_entitlements where company_id = $1", [companyId]);
      await database.query("delete from public.documents where company_id = $1", [companyId]);
      await database.query("delete from public.filing_previews where company_id = $1", [companyId]);
      await database.query("delete from public.support_operators where user_id = any($1::uuid[])", [users.map((user) => user.id)]);
      await database.query("delete from public.company_memberships where company_id = $1", [companyId]);
      await database.query("delete from public.companies where id = $1", [companyId]);
      for (const client of clients) await client.auth.signOut();
      for (const user of users) await admin.auth.admin.deleteUser(user.id);
      await database.end();
    }
  },
);
