import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const migrationPath = new URL(
  "../supabase/migrations/20260827101000_ledger_full_year_reconstruction.sql",
  import.meta.url,
);
const lifecyclePath = new URL("./ledger_database_runtime.test.mjs", import.meta.url);

function functionBody(source, name) {
  const match = source.match(new RegExp(
    `create\\s+or\\s+replace\\s+function\\s+ledger\\.${name}\\s*\\([\\s\\S]+?\\$function\\$\\s*;`,
    "iu",
  ));
  assert.ok(match, `missing ledger.${name}`);
  return match[0];
}

test("reconstruction evidence is immutable, tenant-scoped, and executor-only", () => {
  const source = readFileSync(migrationPath, "utf8");
  for (const table of ["reconstruction_assessments", "reconstruction_evidence"]) {
    assert.match(source, new RegExp(`alter table ledger\\.${table} force row level security`, "iu"));
    assert.match(source, new RegExp(`create trigger ${table}_immutable`, "iu"));
    assert.doesNotMatch(
      source,
      new RegExp(`grant[^;]+(?:insert|update|delete)[^;]+ledger\\.${table}[^;]+(?:authenticated|ledger_executor)`, "iu"),
    );
  }
  const record = functionBody(source, "record_reconstruction_assessment");
  assert.match(record, /company_access_is_accepted_owner_v1/iu);
  assert.match(record, /company_access_company_year_allows_consequential_v1/iu);
  assert.match(record, /ledger_idempotency_in_progress/iu);
  assert.match(record, /ledger_idempotency_key_reused/iu);
  assert.match(record, /extensions\.digest\(p_evidence::text, 'sha256'\)/iu);
  assert.match(source, /to ledger_executor/iu);
  assert.doesNotMatch(source, /to authenticated/iu);
});

test("database revalidates the exact source-owner evidence topology", () => {
  const source = readFileSync(migrationPath, "utf8");
  for (const pair of [
    ["PRIOR_CLOSING_OPENING", "LEDGER"],
    ["BANK_MOVEMENTS", "BANKING"],
    ["BANK_RECONCILIATION", "BANKING"],
    ["INVESTMENTS", "INVESTMENTS"],
    ["SHAREHOLDERS", "SHAREHOLDER_REGISTER_FILING"],
    ["LOANS", "BANKING"],
    ["LOANS", "CORPORATE_GOVERNANCE"],
    ["EQUITY", "CORPORATE_GOVERNANCE"],
    ["EQUITY", "SHAREHOLDER_REGISTER_FILING"],
    ["TAX_HISTORY", "COMPANY_TAX_FILING"],
    ["CURRENT_YEAR_ACTIVITY", "LEDGER"],
    ["DOCUMENTS", "DOCUMENTS"],
    ["UNSUPPORTED_ACTIVITY_CHECK", "COMPANY_ACCESS"],
  ]) {
    assert.match(source, new RegExp(`'${pair[0]}'\\s*,\\s*'${pair[1]}'`, "u"));
  }
  assert.match(source, /jsonb_array_length\(p_evidence\) <> 13/iu);
  assert.match(source, /BANK_MOVEMENTS[\s\S]+make_date\(p_income_year, 1, 1\)/iu);
  assert.match(source, /CURRENT_YEAR_ACTIVITY[\s\S]+p_as_of/iu);
  assert.match(source, /DOCUMENTS_INCOMPLETE/iu);
  assert.match(source, /UNSUPPORTED_ACTIVITY_FOUND/iu);
});

test("fresh database rehearsal executes reconstruction replay, RLS, and gap cases", () => {
  const lifecycle = readFileSync(lifecyclePath, "utf8");
  assert.match(lifecycle, /20260827101000_ledger_full_year_reconstruction\.sql/iu);
  assert.match(lifecycle, /reconstructionCall\(\{ documentsReady: false \}\)/u);
  assert.match(lifecycle, /ledger_idempotency_key_reused/iu);
  assert.match(lifecycle, /ledger\.get_reconstruction_assessment/iu);
  assert.match(lifecycle, /ledger\.reconstruction_assessments', 'insert'/iu);
});
