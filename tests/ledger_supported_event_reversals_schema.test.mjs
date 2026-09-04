import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationName = "20260904223000_ledger_supported_event_reversals.sql";

test("supported event reversals preserve immutable balanced lineage", async () => {
  const [forward, rollback] = await Promise.all([
    readFile(
      new URL(`../supabase/migrations/${migrationName}`, import.meta.url),
      "utf8",
    ),
    readFile(
      new URL(`../supabase/rollback/${migrationName}`, import.meta.url),
      "utf8",
    ),
  ]);

  assert.match(forward, /create table ledger\.entry_reversals/iu);
  assert.match(forward, /ledger_entry_reversals_immutable/iu);
  assert.match(forward, /'debit', pg_catalog\.round\(\(line ->> 'credit'\)/iu);
  assert.match(forward, /'credit', pg_catalog\.round\(\(line ->> 'debit'\)/iu);
  assert.match(
    forward,
    /v_original\.entry_kind not in[\s\S]+CAPITAL_INCREASE[\s\S]+GROUP_CONTRIBUTION/iu,
  );
  assert.match(
    forward,
    /p_correction_source ->> 'capability' <> 'DOCUMENTS'/iu,
  );
  assert.match(
    forward,
    /ledger\.entry_sources[\s\S]+CORROBORATING[\s\S]+DOCUMENTS/iu,
  );
  assert.match(forward, /reverse_supported_entry/iu);
  assert.doesNotMatch(
    forward,
    /grant (?:select|insert|update|delete).*authenticated/iu,
  );
  assert.match(rollback, /drop table if exists ledger\.entry_reversals/iu);
  assert.match(
    rollback,
    /drop function if exists ledger\.reverse_supported_entry_v1/iu,
  );
});
