import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationUrl = new URL(
  "../supabase/migrations/0004_corporate_document_artifacts.sql",
  import.meta.url,
);

test("corporate decision schema is immutable, tenant scoped, and hash bound", async () => {
  const sql = await readFile(migrationUrl, "utf8");

  for (const table of [
    "corporate_accounting_policies",
    "corporate_decisions",
    "corporate_document_sets",
    "corporate_document_artifacts",
    "corporate_document_events",
    "corporate_decision_finalizations",
  ]) {
    assert.match(sql, new RegExp(`create table if not exists public\\.${table}`, "i"));
    assert.match(sql, new RegExp(`alter table public\\.${table} enable row level security`, "i"));
    assert.match(
      sql,
      new RegExp(`revoke insert, update, delete on public\\.${table} from authenticated`, "i"),
    );
  }

  assert.match(sql, /check \(decision_hash ~ '\^\[0-9a-f\]\{64\}\$'\)/i);
  assert.match(sql, /check \(content_sha256 ~ '\^\[0-9a-f\]\{64\}\$'\)/i);
  assert.match(sql, /unique \(company_id, income_year, id\)/i);
  assert.match(sql, /unique \(set_id, artifact_kind, variant\)/i);
  assert.match(sql, /unique \(storage_key\)/i);
  assert.match(sql, /unique \(decision_id\)/i);
  assert.match(sql, /unique \(idempotency_key\)/i);
  assert.match(sql, /foreign key \(company_id, income_year, decision_id\)/i);
  assert.match(sql, /foreign key \(company_id, income_year, set_id\)/i);
  assert.match(sql, /create or replace function public\.prevent_corporate_record_mutation/i);
  assert.match(sql, /security definer/i);
  assert.match(sql, /set search_path = public, pg_temp/i);
  assert.match(sql, /raise exception 'corporate_records_are_immutable'/i);
  assert.match(sql, /create trigger prevent_corporate_decisions_mutation/i);
  assert.match(sql, /create policy "company members can read corporate decisions"/i);
  assert.match(sql, /m\.accepted_at is not null/i);
  assert.doesNotMatch(sql, /for insert\s+to authenticated\s+with check/i);
});

test("accounting policy accounts are server-side reviewed facts", async () => {
  const sql = await readFile(migrationUrl, "utf8");

  assert.match(sql, /policy_version text primary key/i);
  assert.match(sql, /declaration_debit_account text not null check \(declaration_debit_account ~ '\^\[0-9\]\{4\}\$'\)/i);
  assert.match(sql, /dividend_payable_account text not null check \(dividend_payable_account ~ '\^\[0-9\]\{4\}\$'\)/i);
  assert.match(sql, /bank_account text not null check \(bank_account ~ '\^\[0-9\]\{4\}\$'\)/i);
  assert.match(sql, /reviewer text not null check \(btrim\(reviewer\) <> ''\)/i);
  assert.match(sql, /evidence_reference text not null check \(btrim\(evidence_reference\) <> ''\)/i);
  assert.doesNotMatch(sql, /grant select on public\.corporate_accounting_policies to authenticated/i);
});

test("database RPCs recompute canonical hashes and persisted accounting facts", async () => {
  const sql = await readFile(migrationUrl, "utf8");

  assert.match(sql, /create or replace function public\.canonical_corporate_json_text\(p_value jsonb\)/i);
  assert.match(sql, /digest\(public\.canonical_corporate_json_text\(p_canonical_input\), 'sha256'\)/i);
  assert.match(sql, /create or replace function public\.assert_corporate_decision_persisted_facts/i);
  assert.match(sql, /from public\.ledger_entries entry/i);
  assert.match(sql, /from public\.opening_shareholders shareholder/i);
  assert.match(sql, /available_distribution_ore/i);
  assert.match(sql, /revoke all on function public\.canonical_corporate_json_text\(jsonb\)\s+from public, anon, authenticated/i);
  assert.match(sql, /revoke all on function public\.assert_corporate_decision_persisted_facts[\s\S]+from public, anon, authenticated/i);
  assert.equal(
    (sql.match(/perform public\.assert_corporate_decision_persisted_facts\(/gi) ?? []).length,
    2,
  );
  assert.equal(
    (sql.match(/raise exception 'corporate_documents_income_year_locked'/gi) ?? []).length,
    3,
  );
});
