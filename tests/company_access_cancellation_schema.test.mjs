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
  assert.match(source, /evidence_reference text not null check \(btrim\(evidence_reference\) <> ''\)/iu);
  assert.match(source, /operation_id uuid not null unique/iu);
  assert.match(source, /cancellation_revision timestamptz not null/iu);
  assert.match(source, /alter table public\.company_deletion_reviews enable row level security/iu);
  assert.doesNotMatch(source, /grant (?:update|delete)[^;]*company_deletion_reviews/iu);
  assert.doesNotMatch(source, /create policy[^;]+company_deletion_reviews for (?:update|delete)/iu);
});

test("request derives archive and source completeness inside one atomic RPC", () => {
  const source = sql(expandPath);
  const request = functionBody(source, "company_access_request_cancellation");

  assert.match(request, /company_year_archive_exported:/iu);
  assert.match(request, /from public\.documents/iu);
  assert.match(request, /status like 'missing%'/iu);
  assert.match(request, /from public\.corporate_document_artifacts/iu);
  assert.match(request, /created_at > v_archive_exported_at/iu);
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
  assert.match(finalize, /from public\.company_deletion_reviews/iu);
  assert.match(finalize, /decision = 'approved'/iu);
  assert.match(finalize, /cancellation_revision/iu);
  assert.match(finalize, /from public\.documents/iu);
  assert.match(finalize, /from public\.corporate_document_artifacts/iu);
  assert.match(finalize, /company_year_archive_exported:/iu);
  assert.match(finalize, /update public\.companies[\s\S]+status_text = 'deleted_retention_record'/iu);
  assert.match(finalize, /update public\.company_cancellations[\s\S]+status = 'deleted'/iu);
  assert.match(finalize, /company_deletion_completed/iu);
  assert.doesNotMatch(finalize, /delete from public\./iu);
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
