import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const expand = readFileSync(new URL(
  "../supabase/migrations/20260827100000_ledger_capability.sql",
  import.meta.url,
), "utf8");
const contract = readFileSync(new URL(
  "../supabase/contract-migrations/20260827101000_ledger_capability_contract.sql",
  import.meta.url,
), "utf8");
const rollback = readFileSync(new URL(
  "../supabase/rollback/20260827101000_ledger_capability_contract.sql",
  import.meta.url,
), "utf8");

test("ledger business data moves to its owned schema without claiming shareholder setup", () => {
  assert.match(expand, /create schema if not exists ledger/iu);
  assert.match(expand, /alter table public\.ledger_entries set schema ledger/iu);
  assert.match(expand, /alter table ledger\.ledger_entries rename to entries/iu);
  assert.match(expand, /alter table public\.period_locks set schema ledger/iu);
  assert.match(expand, /ledger\.period_locks/iu);
  assert.doesNotMatch(expand, /alter table public\.opening_balance_setups (?:set schema|enable row level security|force row level security)/iu);
  assert.doesNotMatch(expand, /grant[^;]+opening_balance_setups[^;]+ledger_executor/iu);
});

test("legacy entry kinds are explicitly and completely normalized", () => {
  const mappings = new Map([
    ["opening_balance", "OPENING_BALANCE"],
    ["admin_cost", "ADMINISTRATIVE_COST"],
    ["manual_journal", "MANUAL_JOURNAL"],
    ["bank_rule_suggestion", "BANK_RULE_SUGGESTION"],
    ["dividend_received", "DIVIDEND_RECEIVED"],
    ["dividend_to_owner_declared", "OWNER_DIVIDEND_DECLARED"],
    ["dividend_to_owner_payment", "OWNER_DIVIDEND_PAYMENT"],
    ["share_purchase", "SHARE_PURCHASE"],
    ["share_sale", "SHARE_SALE"],
    ["shareholder_loan", "SHAREHOLDER_LOAN"],
    ["tax_settlement", "TAX_SETTLEMENT"],
  ]);
  for (const [legacy, canonical] of mappings) {
    assert.match(
      expand,
      new RegExp(`when\\s+'${legacy}'\\s+then\\s+'${canonical}'`, "iu"),
      `${legacy} must map explicitly`,
    );
  }
  assert.doesNotMatch(expand, /entry_(?:type|kind)\s*=\s*pg_catalog\.upper\(entry_(?:type|kind)\)/iu);
});

test("target persistence is company-scoped, opening-unique, and admission-gated", () => {
  assert.match(expand, /unique[^;]+company_id[^;]+source_capability[^;]+source_record_id/iu);
  assert.match(expand, /unique index[^;]+company_id[^;]+income_year[^;]+where[^;]+entry_kind\s*=\s*'OPENING_BALANCE'/iu);
  assert.match(expand, /company_access_[a-z0-9_]*company_year[a-z0-9_]*v1/iu);
  assert.match(expand, /consequential_operations_allowed/iu);
  assert.match(expand, /LEDGER_COMPANY_YEAR_NOT_ADMITTED|ledger_company_year_not_admitted/iu);
});

test("technical receipts and cursor keys are immutable and non-forgeable", () => {
  assert.match(expand, /create schema if not exists backend_system/iu);
  assert.match(expand, /backend_system\.ledger_command_receipts/iu);
  assert.match(expand, /backend_system\.ledger_cursor_signing_keys/iu);
  assert.match(expand, /gen_random_bytes\(32\)/iu);
  assert.match(expand, /prevent_[a-z0-9_]*(?:receipt|technical|immutable)[a-z0-9_]*mutation/iu);
  assert.doesNotMatch(expand, /grant[^;]+update[^;]+ledger_command_receipts[^;]+ledger_executor/iu);
  assert.doesNotMatch(expand, /current_database\(\)[^;]+ledger_executor/iu);
});

test("the backend executor cannot bypass the intent facade with direct table DML", () => {
  assert.doesNotMatch(expand, /grant[^;]+(?:insert|update|delete)[^;]+ledger\.(?:entries|period_locks)[^;]+ledger_executor/iu);
  assert.doesNotMatch(expand, /policy[^;]+for insert to ledger_executor/iu);
  assert.match(expand, /grant execute on function\s+ledger\./iu);
});

test("future capability SQL is not rewritten into a generic ledger dispatcher", () => {
  assert.doesNotMatch(expand, /pg_get_functiondef/iu);
  assert.doesNotMatch(expand, /ledger_legacy_posting_bridge/iu);
  assert.doesNotMatch(expand, /ledger_post_entry\s*\(\s*p_operation/iu);
  assert.doesNotMatch(expand, /replace\([^;]+public\.ledger_entries/iu);
});

test("contract removes browser posting RPCs and rollback disables target before restoring legacy", () => {
  for (const routine of [
    "accept_bank_transaction_suggestion",
    "record_share_purchase_fifo",
    "record_share_sale_fifo",
    "finalize_corporate_decision",
    "record_owner_dividend_payment",
  ]) {
    assert.match(
      contract,
      new RegExp(`revoke\\s+execute\\s+on\\s+function\\s+public\\.${routine}`, "iu"),
      `${routine} remains browser callable`,
    );
  }
  const disableTargetAt = rollback.search(/revoke[^;]+ledger\.[a-z0-9_]+[^;]+ledger_executor/iu);
  const restoreLegacyAt = rollback.search(/set schema public|create view public\.ledger_entries/iu);
  assert.ok(disableTargetAt >= 0, "rollback must revoke the target executor");
  assert.ok(restoreLegacyAt > disableTargetAt, "rollback must disable target before restoring legacy");
});
