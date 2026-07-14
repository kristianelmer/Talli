import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const actions = await readFile(new URL("../app/actions.ts", import.meta.url), "utf8");
const workspace = await readFile(
  new URL("../app/(owner)/workspace/page.tsx", import.meta.url),
  "utf8",
);
const migration = await readFile(
  new URL("../supabase/migrations/0005_company_tax_feedback_persistence.sql", import.meta.url),
  "utf8",
).catch(() => "");

test("migration links test-authority submissions without opening the direct-write policy", () => {
  assert.match(migration, /add column if not exists authority_test_run_id uuid/u);
  assert.match(
    migration,
    /foreign key \(authority_test_run_id\)[\s\S]*references public\.authority_test_runs\(id\)/u,
  );
  assert.match(
    migration,
    /create unique index if not exists filing_submissions_authority_test_run_id_key[\s\S]*\(authority_test_run_id\)/u,
  );
  assert.match(
    migration,
    /create unique index if not exists filing_submissions_test_authority_idempotency_key[\s\S]*\(idempotency_key\)[\s\S]*where idempotency_key is not null[\s\S]*mode = 'test_authority'/u,
  );
  assert.match(migration, /mode in \('simulation', 'test_authority'\)/u);
  assert.match(
    migration,
    /adapter_mode in \('simulation', 'test_authority', 'production'\)/u,
  );
  assert.match(
    migration,
    /mode = 'simulation'[\s\S]*preview_id is not null[\s\S]*mode = 'test_authority'[\s\S]*preview_id is null/u,
  );
  assert.match(
    migration,
    /create policy "owners can create filing submissions"[\s\S]*mode = 'simulation'/u,
  );
  const updatePolicyUsing = migration.match(
    /create policy "owners can update filing submissions"[\s\S]*?\nwith check \(/u,
  )?.[0] ?? "";
  assert.match(updatePolicyUsing, /and mode = 'simulation'/u);
});

test("migration exposes one authenticated owner-AAL2-protected atomic import RPC", () => {
  assert.match(
    migration,
    /create or replace function public\.import_company_tax_tt02_evidence\(p_payload jsonb\)/u,
  );
  assert.match(migration, /security definer\s+set search_path = public, pg_temp/u);
  assert.match(migration, /auth\.uid\(\)/u);
  assert.match(migration, /auth\.jwt\(\)\s*->>\s*'aal'/u);
  assert.match(migration, /is distinct from 'aal2'/u);
  assert.match(migration, /company_tax_evidence_mfa_required/u);
  assert.match(migration, /m\.role = 'owner'/u);
  assert.match(migration, /m\.accepted_at is not null/u);
  assert.doesNotMatch(migration, /from public\.step_up_events/u);
  assert.match(migration, /obligation is distinct from 'skattemelding'/u);
  assert.match(migration, /environment is distinct from 'test'/u);
  assert.match(migration, /status is distinct from 'pending'/u);
  assert.match(migration, /mode is distinct from 'test_authority'/u);
  assert.match(migration, /adapter_mode is distinct from 'test_authority'/u);
  assert.match(migration, /status is distinct from 'feedback_ready'/u);
  assert.match(migration, /submitted_payload is not null/u);
  assert.match(migration, /feedback_items -> 0 ->> 'severity' is distinct from 'warning'/u);
  assert.match(migration, /feedback_items -> 0 ->> 'message' is distinct from/u);
  assert.match(migration, /calls -> 0 ->> 'status' is distinct from 'validertOK'/u);
  assert.match(migration, /calls -> 1 ->> 'status' is distinct from 'confirmation_prepared'/u);
  assert.match(migration, /calls -> 2 ->> 'status' is distinct from 'received'/u);
  assert.match(migration, /receipt_metadata - array\[/u);
  assert.match(migration, /submitted_payload_ref - array\[/u);
  assert.match(migration, /\?& array\[/u);
  assert.match(migration, /companyOrgNumber/u);
  assert.match(migration, /incomeYear/u);
  assert.match(migration, /from public\.companies/u);
  assert.match(migration, /encode\(digest\(/u);
  assert.match(migration, /skattemelding:/u);
  assert.match(migration, /naeringsspesifikasjon:/u);
  assert.match(migration, /validationEnvelope:/u);
  assert.match(migration, /submissionEnvelope:/u);
  assert.match(migration, /receipt_id !~/u);
  assert.match(migration, /octet_length/u);
  assert.match(migration, /company_tax_evidence_forbidden_content/u);
  assert.match(migration, /current_document_reference_sentinel/u);
  assert.match(migration, /income_year is distinct from 2025/u);
  assert.match(migration, /v_reference_income_year is distinct from 2025/u);
  assert.match(migration, /test_reference !~ '\^tt02:\[0-9\]\+\/\[0-9a-f\]/u);
  assert.match(migration, /receipt_id !~ '\^\[0-9a-f\]/u);
  assert.match(migration, /v_rfc3339_instant_pattern constant text/u);
  const rfc3339PatternSource = migration.match(
    /v_rfc3339_instant_pattern constant text :=\s*'([^']+)'/u,
  )?.[1] ?? "";
  const rfc3339Pattern = new RegExp(rfc3339PatternSource, "u");
  assert.equal(rfc3339Pattern.test("2026-07-14T23:59:59.123Z"), true);
  assert.equal(rfc3339Pattern.test("2026-07-14T23:59:59+23:59"), true);
  for (const invalidTimestamp of [
    "2026-13-14T23:59:59Z",
    "2026-07-14T24:00:00Z",
    "2026-07-14T23:60:00Z",
    "2026-07-14T23:59:60Z",
    "2026-07-14T23:59:59+24:00",
    "2026-07-14T23:59:59+23:60",
  ]) {
    assert.equal(
      rfc3339Pattern.test(invalidTimestamp),
      false,
      `${invalidTimestamp} must fail the SQL RFC3339 grammar`,
    );
  }
  for (const timestampField of [
    "recorded_at",
    "updated_at",
    "created_at",
    "receivedAt",
    "processEndedAt",
    "archivedAt",
    "storedAt",
  ]) {
    assert.match(
      migration,
      new RegExp(`${timestampField}'[^\\n]*!~ v_rfc3339_instant_pattern`, "u"),
    );
  }
  assert.match(
    migration,
    /calls -> 1 ->> 'created_at'\)::timestamptz >[\s\S]*receipt_metadata ->> 'processEndedAt'/u,
  );
  assert.match(migration, /company_tax_evidence_conflict/u);
  assert.match(migration, /insert into public\.audit_events/u);
  assert.match(
    migration,
    /create unique index if not exists authority_test_runs_evidence_identity_key[\s\S]*\(company_id, obligation, environment, test_reference\)/u,
  );
  assert.match(
    migration,
    /revoke all on function public\.import_company_tax_tt02_evidence\(jsonb\) from public, anon/u,
  );
  assert.match(
    migration,
    /grant execute on function public\.import_company_tax_tt02_evidence\(jsonb\) to authenticated/u,
  );
  assert.doesNotMatch(
    migration,
    /(?:insert into|update|delete from) public\.(?:authority_permissions|launch_signoffs)/u,
  );
});

test("runtime imports completed company-tax TT02 evidence through exactly one atomic RPC", () => {
  assert.match(actions, /buildCompanyTaxReturnEvidencePersistence/u);
  assert.match(actions, /export async function recordCompanyTaxReturnTt02Evidence/u);
  assert.match(actions, /formData\.get\("evidenceFile"\)/u);
  assert.match(actions, /expectedIncomeYear: Number\(formString\(formData, "incomeYear"\)\)/u);
  assert.match(actions, /\.select\("id, org_number"\)/u);
  assert.match(actions, /expectedCompanyOrgNumber: company\.org_number/u);

  const actionBody = actions.match(
    /export async function recordCompanyTaxReturnTt02Evidence[\s\S]*?\n\}\n/u,
  )?.[0] ?? "";
  assert.match(
    actionBody,
    /persistence = buildCompanyTaxReturnEvidencePersistence\(/u,
  );
  assert.match(
    actionBody,
    /supabase\.rpc\("import_company_tax_tt02_evidence", \{\s*p_payload: persistence,\s*\}\)/u,
  );
  assert.equal(actionBody.match(/supabase\.rpc\(/gu)?.length, 1);
  assert.doesNotMatch(actionBody, /requireSensitiveActionStepUp/u);
  assert.doesNotMatch(actionBody, /\.from\("authority_test_runs"\)\.insert/u);
  assert.doesNotMatch(actionBody, /\.from\("audit_events"\)\.insert/u);
  assert.match(actionBody, /try \{[\s\S]*buildCompanyTaxReturnEvidencePersistence/u);
  assert.match(actionBody, /Ugyldig TT02-evidens/u);
  assert.match(actionBody, /company_tax_evidence_mfa_required/u);
  assert.doesNotMatch(actionBody, /encodeURIComponent\(error\.message\)/u);
  assert.doesNotMatch(
    actionBody,
    /production_enabled|authority_permissions|launch_signoffs/u,
  );
});

test("workspace offers a company-tax JSON evidence import bound to the active year", () => {
  assert.match(workspace, /recordCompanyTaxReturnTt02Evidence/u);
  assert.match(workspace, /action=\{recordCompanyTaxReturnTt02Evidence\}/u);
  assert.match(workspace, /name="incomeYear" type="hidden" value=\{primaryIncomeYear\}/u);
  assert.match(workspace, /Verifisert skattemelding-evidens fra TT02/u);
  assert.match(workspace, /name="evidenceFile"[^>]*type="file"/u);
  assert.match(workspace, /status pending/u);
});
