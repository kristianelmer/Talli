import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const migration = readFileSync(new URL(
  "../supabase/migrations/20260827103000_ledger_corrections.sql",
  import.meta.url,
), "utf8");
const lifecycle = readFileSync(new URL(
  "./ledger_database_runtime.test.mjs",
  import.meta.url,
), "utf8");
const rollback = readFileSync(new URL(
  "../supabase/rollback/20260827101000_ledger_capability_contract.sql",
  import.meta.url,
), "utf8");

const correctionFunction = migration.match(
  /create or replace function ledger\.correct_entry_v1\([\s\S]+?\$function\$\s*;/iu,
)?.[0];

test("correction API has the canonical immutable reversal contract", () => {
  assert.ok(correctionFunction);
  assert.match(correctionFunction, /p_original_entry_id uuid/iu);
  assert.match(correctionFunction, /returns table \([\s\S]+reversal_entry_id uuid[\s\S]+replacement_entry_id uuid[\s\S]+replayed boolean/iu);
  assert.match(correctionFunction, /'CORRECTION_REVERSAL'/u);
  assert.match(correctionFunction, /line ->> 'credit'[\s\S]+line ->> 'debit'/u);
  assert.match(correctionFunction, /ledger_entry_already_corrected/iu);
  assert.match(
    correctionFunction,
    /ledger_prior_year_correction_policy_unresolved/iu,
  );
  assert.match(correctionFunction, /operation_name = 'correct_entry'/u);
  assert.doesNotMatch(correctionFunction, /ledger\.post_entry\(/iu);
  assert.doesNotMatch(correctionFunction, /ledger_period_locked/iu);
});

test("SQL coordinates persistence but contains no replacement accounting selection", () => {
  assert.ok(correctionFunction);
  assert.doesNotMatch(correctionFunction, /'1920'|'6720'|'7795'|'8050'|'2030'/u);
  assert.doesNotMatch(correctionFunction, /category|administrative_cost_lines/iu);
  assert.match(correctionFunction, /ledger\.normalize_lines_v1\(p_replacement_lines\)/iu);
  assert.match(correctionFunction, /'DOCUMENTS'/u);
  assert.match(correctionFunction, /'BANKING'/u);
  assert.match(
    correctionFunction,
    /v_original\.entry_kind <> 'ADMINISTRATIVE_COST'/u,
  );
});

test("lineage and provenance are forced-RLS immutable evidence", () => {
  assert.match(migration, /alter table ledger\.entry_corrections force row level security/iu);
  assert.match(migration, /create trigger ledger_entry_corrections_immutable/iu);
  assert.match(migration, /original_entry_id uuid primary key/iu);
  assert.match(migration, /reversal_entry_id uuid not null unique/iu);
  assert.match(migration, /replacement_entry_id uuid not null unique/iu);
  assert.doesNotMatch(
    migration,
    /grant[^;]+(?:insert|update|delete)[^;]+ledger\.entry_corrections[^;]+ledger_executor/iu,
  );
});

test("fresh database lifecycle exercises correction and recutover", () => {
  for (const evidence of [
    "ledger.correct_entry_v1",
    "ledger_entry_already_corrected",
    "ledger_cutover_inactive",
    "entry_corrections",
  ]) {
    assert.match(lifecycle, new RegExp(evidence, "u"));
  }
  assert.match(migration, /correction-reversal:/u);
  assert.match(rollback, /tg_op = 'INSERT'[\s\S]+correction_reversal/iu);
  assert.match(lifecycle, /Forged rollback reversal/u);
});
