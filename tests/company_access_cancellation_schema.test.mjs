import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const expandPath = new URL(
  "../supabase/migrations/20260808120000_company_access_cancellation_lifecycle.sql",
  import.meta.url,
);
const contractPath = new URL(
  "../supabase/contract-migrations/20260808121000_company_access_cancellation_contract.sql",
  import.meta.url,
);

function sql(path) {
  return readFileSync(path, "utf8");
}

function functionBody(source, name) {
  const match = source.match(
    new RegExp(`create or replace function public\\.${name}\\([\\s\\S]+?\\$function\\$;`, "iu"),
  );
  assert.ok(match, `missing ${name}`);
  return match[0];
}

test("expand migration adds append-only revision-bound deletion reviews", () => {
  const source = sql(expandPath);

  assert.match(source, /create table if not exists public\.company_deletion_reviews/iu);
  assert.match(source, /decision text not null check \(decision in \('approved', 'rejected'\)\)/iu);
  assert.match(source, /evidence_reference text not null check \([\s\S]+btrim\(evidence_reference\) <> ''[\s\S]+char_length\(btrim\(evidence_reference\)\) <= 500/iu);
  assert.match(source, /requester_id uuid not null/iu);
  assert.match(source, /check \(reviewed_by <> requester_id\)/iu);
  assert.match(source, /operation_id uuid not null unique/iu);
  assert.match(source, /cancellation_revision timestamptz not null/iu);
  assert.match(source, /alter table public\.company_deletion_reviews enable row level security/iu);
  assert.doesNotMatch(source, /grant (?:update|delete)[^;]*company_deletion_reviews/iu);
  assert.doesNotMatch(source, /create policy[^;]+company_deletion_reviews for (?:update|delete)/iu);
});

test("request derives archive and source completeness inside one atomic RPC", () => {
  const source = sql(expandPath);
  const request = functionBody(source, "company_access_request_cancellation");

  assert.match(source, /create table if not exists public\.company_archive_source_generations/iu);
  assert.match(source, /create table if not exists public\.company_archive_export_attempts/iu);
  assert.match(source, /create table if not exists public\.company_archive_export_receipts/iu);
  assert.match(source, /create trigger company_archive_track_documents/iu);
  assert.match(source, /create trigger company_archive_track_corporate_artifacts/iu);
  assert.match(source, /create or replace function public\.company_archive_begin_export/iu);
  assert.match(source, /create or replace function public\.company_archive_complete_export/iu);
  assert.match(request, /from public\.company_archive_export_receipts/iu);
  assert.match(request, /source_generation = v_source_generation/iu);
  assert.doesNotMatch(request, /company_year_archive_exported:/iu);
  assert.match(request, /from public\.documents/iu);
  assert.match(request, /status like 'missing%'/iu);
  assert.match(request, /raise exception 'cancellation_prerequisite_failed'/iu);
  assert.match(request, /pg_advisory_xact_lock/iu);
  assert.match(request, /status <> 'deleted'/iu);
  assert.match(request, /insert into public\.audit_events/iu);
  assert.match(request, /company_cancellation_requested/iu);
});

test("review is admin+AAL2 only, append-only, and cannot be self-approved by an owner", () => {
  const source = sql(expandPath);
  const review = functionBody(source, "company_access_review_deletion");
  const admin = functionBody(source, "company_access_is_active_admin_v1");

  assert.match(review, /company_access_is_active_admin_v1\(\)/iu);
  assert.match(admin, /from public\.support_operators/iu);
  assert.match(admin, /role = 'admin'/iu);
  assert.match(admin, /active/iu);
  assert.match(review, /company_access_has_fresh_mfa_v1\(\)/iu);
  assert.match(review, /v_cancellation\.requested_by = v_actor_id/iu);
  assert.match(review, /p_expected_updated_at is null/iu);
  assert.match(review, /char_length\([^)]*btrim\(p_evidence_reference\)\) > 500/iu);
  assert.match(review, /insert into public\.company_deletion_reviews/iu);
  assert.match(review, /cancellation_revision/iu);
  assert.match(review, /p_expected_updated_at/iu);
  assert.match(review, /case when p_decision = 'approved' then 'deletion_approved' else 'retention_hold' end/iu);
  assert.match(review, /insert into public\.audit_events/iu);
});

test("finalize re-derives prerequisites and requires exact approved review", () => {
  const source = sql(expandPath);
  const finalize = functionBody(source, "company_access_finalize_deletion");

  assert.match(finalize, /company_access_is_accepted_owner_v1/iu);
  assert.match(finalize, /company_access_has_fresh_mfa_v1\(\)/iu);
  assert.match(finalize, /p_expected_updated_at is null/iu);
  assert.match(finalize, /from public\.company_deletion_reviews/iu);
  assert.match(finalize, /decision = 'approved'/iu);
  assert.match(finalize, /cancellation_revision/iu);
  assert.match(finalize, /from public\.documents/iu);
  assert.match(finalize, /from public\.company_archive_export_receipts/iu);
  assert.match(finalize, /source_generation = v_source_generation/iu);
  assert.doesNotMatch(finalize, /company_year_archive_exported:/iu);
  assert.match(finalize, /update public\.companies[\s\S]+status_text = 'deleted_retention_record'/iu);
  assert.match(finalize, /update public\.company_cancellations[\s\S]+status = 'deleted'/iu);
  assert.match(finalize, /company_deletion_completed/iu);
  assert.doesNotMatch(finalize, /delete from public\./iu);
});

test("archive receipt completion is server-only, one-time, expiring, and generation-bound", () => {
  const source = sql(expandPath);
  const begin = functionBody(source, "company_archive_begin_export");
  const complete = functionBody(source, "company_archive_complete_export");
  const tracker = functionBody(source, "company_archive_track_source_write_v1");
  const lock = functionBody(source, "company_archive_lock_scope_v1");

  assert.match(begin, /company_access_is_accepted_owner_v1\(p_company_id\)/iu);
  assert.match(begin, /company_access_has_fresh_mfa_v1\(\)/iu);
  assert.match(begin, /interval '10 minutes'/iu);
  assert.match(complete, /for update/iu);
  assert.match(complete, /completed_at is not null/iu);
  assert.match(complete, /expires_at <=/iu);
  assert.match(complete, /source_generation <>/iu);
  assert.match(complete, /insert into public\.company_archive_export_receipts/iu);
  assert.match(tracker, /company_archive_lock_scope_v1/iu);
  assert.match(lock, /pg_advisory_xact_lock/iu);
  assert.match(tracker, /insert into public\.company_archive_source_generations[\s\S]+on conflict[\s\S]+generation =/iu);
  assert.match(source, /revoke all on function public\.company_archive_complete_export\(uuid, text\) from public, anon, authenticated/iu);
  assert.match(source, /grant execute on function public\.company_archive_complete_export\(uuid, text\) to service_role/iu);
  assert.doesNotMatch(source, /grant (?:select|insert|update|delete)[^;]*company_archive_export_(?:attempts|receipts)[^;]*authenticated/iu);
});

test("direct lifecycle RPCs mirror strict request validation before receipts", () => {
  const source = sql(expandPath);
  const request = functionBody(source, "company_access_request_cancellation");
  const review = functionBody(source, "company_access_review_deletion");
  const finalize = functionBody(source, "company_access_finalize_deletion");

  assert.match(request, /p_operation_id is null[\s\S]+p_company_id is null[\s\S]+p_income_year not between 2000 and 2100/iu);
  assert.match(request, /p_reason is null[\s\S]+btrim\(p_reason\) = ''[\s\S]+char_length\([^)]*btrim\(p_reason\)\) > 1000/iu);
  assert.match(review, /p_operation_id is null[\s\S]+p_cancellation_id is null[\s\S]+p_company_id is null/iu);
  assert.match(review, /p_decision not in \('approved', 'rejected'\)/iu);
  assert.match(review, /p_evidence_reference is null[\s\S]+btrim\(p_evidence_reference\) = ''/iu);
  assert.match(finalize, /p_operation_id is null[\s\S]+p_cancellation_id is null[\s\S]+p_company_id is null/iu);
  for (const body of [request, review, finalize]) {
    assert.ok(body.indexOf("company_access_invalid_request") < body.indexOf("select r.* into v_receipt"));
  }
});

test("lifecycle commands use durable receipts and least-privilege RLS", () => {
  const source = sql(expandPath);

  for (const command of ["request_cancellation", "review_deletion", "finalize_deletion"]) {
    assert.match(source, new RegExp(`command_name = '${command}'|command_name,.*'${command}'`, "isu"));
  }
  assert.match(source, /create policy "company access commands read cancellations"/iu);
  assert.match(source, /create or replace function public\.company_access_list_cancellations/iu);
  assert.match(source, /create policy "company access commands create cancellations"/iu);
  assert.match(source, /create policy "company access commands update cancellations"/iu);
  assert.match(source, /create policy "company access commands append deletion reviews"/iu);
  assert.match(source, /alter function public\.company_access_request_cancellation[\s\S]+owner to company_access_executor/iu);
  assert.match(source, /alter function public\.company_access_review_deletion[\s\S]+owner to company_access_executor/iu);
  assert.match(source, /alter function public\.company_access_finalize_deletion[\s\S]+owner to company_access_executor/iu);
  assert.match(source, /alter function public\.company_access_list_cancellations[\s\S]+owner to company_access_executor/iu);
  assert.doesNotMatch(source, /alter role company_access_executor[\s\S]+bypassrls/iu);
});

test("unknown command outcomes reconcile behind the exact operation lock", () => {
  const source = sql(expandPath);
  const reconcile = functionBody(source, "company_access_reconcile_cancellation_operation");
  for (const name of [
    "company_access_request_cancellation",
    "company_access_review_deletion",
    "company_access_finalize_deletion",
  ]) {
    assert.match(functionBody(source, name), /company_access_lock_operation_v1\(v_actor_id, p_operation_id\)/iu);
  }
  assert.match(reconcile, /company_access_lock_operation_v1\(v_actor_id, p_operation_id\)/iu);
  assert.match(reconcile, /request_fingerprint <> v_fingerprint/iu);
  assert.match(reconcile, /return query select false, null::jsonb/iu);
  assert.match(source, /grant execute on function public\.company_access_reconcile_cancellation_operation/iu);
});

test("contract migration removes direct cancellation access only after generated-client cutover", () => {
  const source = sql(contractPath);

  assert.match(source, /revoke select, insert, update on public\.company_cancellations from authenticated/iu);
  assert.match(source, /drop policy if exists "company members can read cancellation state"/iu);
  assert.match(source, /drop policy if exists "support operators can read cancellation state"/iu);
  assert.match(source, /drop policy if exists "owners can request cancellation"/iu);
  assert.match(source, /drop policy if exists "owners can update cancellation request"/iu);
  assert.match(source, /grant execute on function public\.company_access_request_cancellation/iu);
  assert.match(source, /grant execute on function public\.company_access_review_deletion/iu);
  assert.match(source, /grant execute on function public\.company_access_finalize_deletion/iu);
  assert.match(source, /grant execute on function public\.company_access_list_cancellations/iu);
});

test("the release Supabase suite includes cancellation schema coverage", () => {
  const packageJson = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.match(packageJson.scripts["test:supabase"], /tests\/company_access_cancellation_schema\.test\.mjs/u);
});
