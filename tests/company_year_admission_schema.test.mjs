import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";

const migrationPath = new URL(
  "../supabase/migrations/20260826110000_company_year_admission.sql",
  import.meta.url,
);

function sql() {
  return readFileSync(migrationPath, "utf8");
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

test("company-year admission is one atomic executor-only evidence graph", () => {
  const source = sql();
  assert.match(source, /^-- EXPAND: versioned company-year eligibility and admission\./u);
  assert.match(source, /\nbegin;\n/iu);
  assert.match(source, /\ncommit;\s*$/iu);
  for (const table of [
    "company_eligibility_assessments",
    "company_year_acceptances",
    "company_year_admissions",
  ]) {
    assert.match(source, new RegExp(`create table public\\.${table}`, "iu"));
    assert.match(source, new RegExp(`alter table public\\.${table} enable row level security`, "iu"));
    assert.match(source, new RegExp(`create trigger ${table}_immutable`, "iu"));
  }
  assert.match(source, /unique \(company_id, accounting_year\)/iu);
  assert.match(source, /foreign key \(eligibility_assessment_id, company_id, accounting_year\)[\s\S]+references public\.company_eligibility_assessments\(id, company_id, accounting_year\)/iu);
  assert.match(source, /foreign key \(company_year_admission_id, company_id, accounting_year\)[\s\S]+references public\.company_year_admissions\(id, company_id, accounting_year\)/iu);
  assert.match(source, /foreign key \(previous_assessment_id, company_id, accounting_year\)[\s\S]+references public\.company_eligibility_assessments\(id, company_id, accounting_year\)/iu);
  assert.match(source, /create or replace function public\.company_access_admit_company_year/iu);
  const rpc = source.slice(source.indexOf("create or replace function public.company_access_admit_company_year"));
  const orderedInserts = [
    "insert into public.companies",
    "insert into public.company_memberships",
    "insert into public.customer_agreement_acceptances",
    "insert into public.company_eligibility_assessments",
    "insert into public.company_year_admissions",
    "insert into public.company_year_acceptances",
    "insert into public.company_access_command_receipts",
  ];
  let prior = -1;
  for (const statement of orderedInserts) {
    const at = statement.endsWith("company_access_command_receipts")
      ? rpc.lastIndexOf(statement)
      : rpc.indexOf(statement);
    assert.ok(at > prior, `${statement} must be present in atomic order`);
    prior = at;
  }
});

test("admission validates every immutable active document and capability digest", () => {
  const source = sql();
  for (const literal of [
    "2026.1",
    "9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de",
    "2026-07-17",
    "f64a7f6a9758389fca8985a883a945d84c849f5b3316944621507db336992543",
    "083ee63c1917ef227068befd7706ba2d636c52070ed4d880a8efae720528191c",
    "2026-07-15",
    "4777d7b1bce8218219db06f40c255ca9ef6e0d5f1c84ccdc9b5616b75b9d472c",
    "authority-v1",
    "in_app_clickwrap",
    "2026-01-01",
  ]) {
    assert.match(source, new RegExp(literal, "u"));
  }
  assert.match(source, /p_public_facts_json::jsonb/iu);
  assert.match(source, /p_answers_json::jsonb/iu);
  assert.match(source, /v_public_facts := p_public_facts_json::jsonb/iu);
  assert.match(source, /v_answers := p_answers_json::jsonb/iu);
  assert.match(source, /v_capability_manifest := p_capability_manifest_json::jsonb/iu);
  assert.match(source, /v_company_year_promise := p_company_year_promise_json::jsonb/iu);
  assert.match(source, /capability_manifest jsonb not null/iu);
  assert.match(source, /company_year_promise jsonb not null/iu);
  assert.match(source, /jsonb_typeof\(v_public_facts\)[\s\S]+object/iu);
  assert.match(source, /jsonb_typeof\(v_answers\)[\s\S]+object/iu);
  assert.match(source, /request_fingerprint/iu);
  assert.match(source, /pg_advisory_xact_lock/iu);
  assert.match(source, /command_name = 'admit_company_year'/iu);
  assert.match(source, /company_access_conflict/iu);
  assert.match(source, /replayed/iu);
});

test("manifest digest, durable snapshot, and change control stay one exact boundary", () => {
  const source = sql();
  const manifest = JSON.parse(readFileSync(new URL(
    "../apps/backend/src/talli_backend/modules/company_access/capability_manifest.json",
    import.meta.url,
  ), "utf8"));
  const digest = createHash("sha256").update(canonicalJson(manifest), "utf8").digest("hex");

  assert.equal(digest, "9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de");
  assert.match(source, new RegExp(digest, "u"));
  assert.equal(manifest.changeControl.acceptedPromiseIsImmutable, true);
  assert.deepEqual(manifest.changeControl.boundaryRemovalRequires, [
    "reopened_172",
    "refreshed_practical_majority_evidence",
    "approval_180",
  ]);
  assert.equal(manifest.promise.mode, "atomic_company_year");
  assert.equal(manifest.promise.capabilities.length, 12);
  assert.equal(manifest.promise.customerClaims.length, 12);
  assert.match(
    manifest.questions.find(({ code }) => code === "has_supported_investments").prompt,
    /EØS/u,
  );
  assert.match(
    manifest.questions.find(({ code }) => code === "has_supported_loans").prompt,
    /norske motparter/u,
  );
  assert.deepEqual(manifest.questions.map(({ code }) => code), [
    "is_small_enterprise",
    "is_owner_managed",
    "conducts_regulated_finance",
    "uses_calendar_year",
    "has_auditor_or_audit_requirement",
    "requires_consolidated_accounts",
    "has_supported_share_structure",
    "has_only_norwegian_shareholders",
    "uses_only_nok_bank_and_bookkeeping",
    "has_only_holding_or_no_activity",
    "has_supported_investments",
    "investment_tax_treatment_is_clear",
    "has_no_complex_investment_activity",
    "has_supported_dividends",
    "dividend_basis_and_evidence_are_clear",
    "has_supported_capital_events",
    "has_no_complex_corporate_events",
    "has_supported_loans",
    "loan_terms_are_ordinary_and_clear",
    "has_supported_group_contributions",
    "group_contribution_facts_are_clear",
    "has_only_supported_income_and_costs",
    "prior_closing_matches_opening",
    "all_bank_movements_available",
    "bank_accounts_reconciliable",
    "material_company_facts_confirmable",
    "documents_available",
    "no_unsupported_current_year_activity",
    "requires_no_earlier_year_rebuild",
    "is_deterministic_self_service",
    "has_normal_holding_volume_character",
  ]);
  assert.deepEqual(manifest.recheckTriggers, [
    "public_fact_changed",
    "material_answer_changed",
    "manifest_changed",
    "before_payment",
    "before_filing",
  ]);
  assert.deepEqual(manifest.decisionReferences, ["#172", "#176", "#177", "#178", "#180"]);
});

test("post-admission rechecks append a current safety gate and preserve export", () => {
  const source = sql();
  assert.match(source, /create or replace function public\.company_access_recheck_company_year_eligibility/iu);
  assert.match(source, /company_eligibility_assessments_previous_same_company_year_fk/iu);
  assert.match(source, /decision text not null check \(decision in \('supported', 'clarify', 'blocked'\)\)/iu);
  assert.match(source, /p_archive_export_available is distinct from true/iu);
  assert.match(source, /p_consequential_operations_allowed is distinct from false/iu);
  assert.match(source, /STOP_EXPORT_AND_CONTACT/iu);
  assert.match(source, /PAUSE_AND_CLARIFY/iu);
  assert.match(source, /CONTINUE_COMPANY_YEAR/iu);
  assert.match(source, /command_name = 'recheck_company_year_eligibility'/iu);
  assert.match(source, /'eligibility-recheck\|' \|\| p_company_year_admission_id::text/iu);
  assert.doesNotMatch(source, /v_actor_id::text \|\| '\|eligibility-recheck\|'/iu);
  assert.match(source, /drop function if exists public\.company_access_onboard_company/iu);
});

test("admission evidence is append-only, tenant concealed, and browser inaccessible", () => {
  const source = sql();
  assert.match(source, /create or replace function public\.company_access_prevent_admission_evidence_mutation/iu);
  assert.match(source, /raise exception 'company_access_admission_evidence_is_immutable'/iu);
  assert.doesNotMatch(source, /for update\s+to company_access_executor|for delete\s+to company_access_executor/iu);
  assert.doesNotMatch(source, /grant (?:update|delete|truncate)[^;]*company_(?:eligibility_assessments|year_acceptances|year_admissions)/iu);
  assert.doesNotMatch(source, /grant [^;]*(?:company_eligibility_assessments|company_year_acceptances|company_year_admissions)[^;]*to (?:anon|authenticated|service_role)/iu);
  assert.match(source, /public\.company_access_is_accepted_member_v1\(company_id\)/iu);
  assert.match(source, /assessed_by = \(select public\.company_access_auth_uid_v1\(\)\)/iu);
  assert.match(source, /accepted_by = \(select public\.company_access_auth_uid_v1\(\)\)/iu);
  assert.match(source, /admitted_by = \(select public\.company_access_auth_uid_v1\(\)\)/iu);
  assert.match(source, /alter function public\.company_access_admit_company_year[\s\S]+owner to company_access_executor/iu);
  assert.match(source, /revoke all on function public\.company_access_admit_company_year[\s\S]+from public, anon, authenticated, service_role/iu);
  assert.match(source, /grant execute on function public\.company_access_admit_company_year[\s\S]+to company_access_executor/iu);
});

test("admission command receipts are actor-bound and permit exact replay only", () => {
  const source = sql();
  assert.match(source, /company_access_command_receipts_command_name_check[\s\S]+admit_company_year/iu);
  assert.match(source, /r\.actor_id = v_actor_id[\s\S]+r\.operation_id = p_operation_id[\s\S]+r\.command_name = 'admit_company_year'/iu);
  assert.match(source, /v_receipt\.request_fingerprint is distinct from v_fingerprint[\s\S]+company_access_conflict/iu);
  assert.match(source, /v_receipt\.result ->> 'company_year_admission_id'/iu);
  assert.match(source, /company_access_current_identity_v1\(\)/iu);
  assert.match(source, /p_verified_subject is distinct from v_current_subject/iu);
  assert.match(source, /p_verified_email/iu);
});
