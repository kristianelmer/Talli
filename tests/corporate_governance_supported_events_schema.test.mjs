import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationName =
  "20260904220000_corporate_governance_supported_events.sql";

test("supported corporate events are immutable, tenant-scoped and atomic", async () => {
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

  assert.match(
    forward,
    /create table corporate_governance\.supported_events/iu,
  );
  assert.match(forward, /force row level security/iu);
  assert.match(forward, /supported_events_immutable/iu);
  assert.match(
    forward,
    /foreign key \(accounting_entry_id, company_id, income_year\)\s+references ledger\.entries\(id, company_id, income_year\)/iu,
  );
  assert.match(forward, /unique \(created_by, company_id, idempotency_key\)/iu);
  assert.match(forward, /corporate_governance\.assert_owner_v1/iu);
  assert.match(
    forward,
    /public\.company_archive_track_source_write_v1\('year', 'company_id'\)/iu,
  );
  assert.match(forward, /to corporate_governance_workflow_executor/iu);
  assert.doesNotMatch(
    forward,
    /grant (?:select|insert|update|delete).*authenticated/iu,
  );
  assert.match(forward, /company_archive_projection_executor to %I/iu);
  assert.match(forward, /company_archive_projection_executor from %I/iu);

  assert.match(
    rollback,
    /drop table if exists corporate_governance\.supported_events/iu,
  );
  assert.match(
    rollback,
    /drop function if exists corporate_governance\.prepare_supported_event_v1/iu,
  );
});
