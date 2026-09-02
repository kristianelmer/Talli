import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const migrationName = "20260902090000_corporate_governance_annual_close.sql";

test("annual-close proposals are immutable and restricted to the governance executor", async () => {
  const [forward, rollback] = await Promise.all([
    readFile(new URL(`../supabase/migrations/${migrationName}`, import.meta.url), "utf8"),
    readFile(new URL(`../supabase/rollback/${migrationName}`, import.meta.url), "utf8"),
  ]);

  assert.match(forward, /create table corporate_governance\.annual_close_decisions/iu);
  assert.match(forward, /create table corporate_governance\.annual_close_artifacts/iu);
  assert.match(forward, /create table corporate_governance\.annual_close_events/iu);
  assert.match(forward, /create table corporate_governance\.annual_close_finalizations/iu);
  assert.match(forward, /force row level security/iu);
  assert.match(forward, /annual_close_decisions_immutable/iu);
  assert.match(forward, /public\.assert_corporate_decision_persisted_facts/iu);
  assert.match(forward, /p_canonical_input -> 'dividend' is distinct from 'null'::jsonb/iu);
  assert.match(forward, /corporate_governance\.propose_annual_close_v1/iu);
  assert.match(forward, /corporate_governance\.register_annual_close_documents_v1/iu);
  assert.match(forward, /corporate_governance\.attest_annual_close_signed_artifact_v1/iu);
  assert.match(forward, /'signed_owner_attested'/iu);
  assert.match(forward, /v_decision\.generated_artifacts/iu);
  assert.doesNotMatch(forward, /v_required_signers|v_actual_signers/iu);
  assert.match(forward, /to corporate_governance_workflow_executor/iu);
  assert.doesNotMatch(forward, /grant (?:select|insert|update|delete).*authenticated/iu);

  assert.match(rollback, /drop table corporate_governance\.annual_close_decisions/iu);
  assert.match(rollback, /drop function corporate_governance\.propose_annual_close_v1/iu);
  assert.match(rollback, /drop function if exists corporate_governance\.attest_annual_close_signed_artifact_v1/iu);
});
