import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationUrl = new URL(
  "../supabase/migrations/0003_bank_rule_suggestions.sql",
  import.meta.url,
);

test("bank suggestion approvals are immutable and posted atomically", async () => {
  const sql = await readFile(migrationUrl, "utf8");

  assert.match(sql, /create table if not exists public\.bank_suggestion_acceptances/i);
  assert.match(sql, /unique \(bank_transaction_id\)/i);
  assert.match(sql, /create or replace function public\.accept_bank_transaction_suggestion/i);
  assert.match(sql, /for update/i);
  assert.match(sql, /security definer/i);
  assert.match(sql, /set search_path = public, pg_temp/i);
  assert.match(sql, /insert into public\.ledger_entries/i);
  assert.match(sql, /update public\.bank_transactions/i);
  assert.match(sql, /insert into public\.audit_events/i);
  assert.match(
    sql,
    /revoke insert, update, delete on public\.bank_suggestion_acceptances from authenticated/i,
  );
});

test("database independently validates rule, version, direction, ambiguity, and period lock", async () => {
  const sql = await readFile(migrationUrl, "utf8");

  for (const invariant of [
    "bank_rule_version_mismatch",
    "bank_suggestion_rule_mismatch",
    "bank_suggestion_ambiguous",
    "bank_suggestion_direction_mismatch",
    "income_year_locked",
    "bank_transaction_already_reconciled",
  ]) {
    assert.match(sql, new RegExp(invariant, "i"));
  }
  assert.match(sql, /company_owner_required/i);
  assert.match(sql, /bankgebyr/i);
  assert.match(sql, /systemabonnement/i);
  assert.match(sql, /renter/i);
});
