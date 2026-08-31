import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const expandPath = new URL(
  "../supabase/migrations/20260831124939_investments_capability.sql",
  import.meta.url,
);
const workflowPath = new URL(
  "../supabase/migrations/20260831131203_investments_share_purchase_workflow.sql",
  import.meta.url,
);
const contractPath = new URL(
  "../supabase/contract-migrations/20260831133000_investments_share_purchase_contract.sql",
  import.meta.url,
);
const rollbackPath = new URL(
  "../supabase/rollback/20260831133000_investments_share_purchase_contract.sql",
  import.meta.url,
);
const localGatePath = new URL("../scripts/test-supabase-local.sh", import.meta.url);

function artifact(path, phase) {
  assert.equal(existsSync(path), true, `missing investments ${phase} artifact`);
  const source = readFileSync(path, "utf8");
  assert.match(source, /\bbegin\s*;/iu);
  assert.match(source, /\bcommit\s*;\s*$/iu);
  return source;
}

test("the complete local database gate includes the investments lifecycle", () => {
  const source = readFileSync(localGatePath, "utf8");
  assert.match(source, /npm run test:investments-database-lifecycle/iu);
});

test("expand and workflow keep predecessor and successor stores coherent", () => {
  const expand = artifact(expandPath, "expand");
  const workflow = artifact(workflowPath, "workflow");
  assert.match(expand, /pg_advisory_xact_lock[\s\S]+investments:purchase-cutover:v1/iu);
  assert.match(workflow, /pg_advisory_xact_lock[\s\S]+investments:purchase-cutover:v1/iu);
  assert.match(workflow, /sync_legacy_investment_position_v1/iu);
  assert.match(workflow, /sync_legacy_investment_lot_v1/iu);
  assert.match(workflow, /sync_legacy_share_purchase_v1/iu);
  assert.match(workflow, /mirror_investment_purchase_to_successor_v1/iu);
  assert.doesNotMatch(workflow, /drop function backend_system\.(?:prepare|complete)_investment_purchase_fifo_v1/iu);
});

test("canonical investments tables are forced-RLS and runtime roles do not own them", () => {
  const expand = artifact(expandPath, "expand");
  const workflow = artifact(workflowPath, "workflow");
  for (const table of ["positions", "acquisition_lots"]) {
    assert.match(expand, new RegExp(
      `alter table investments\\.${table} force row level security`, "iu",
    ));
  }
  assert.match(workflow, /alter table investments\.share_purchases force row level security/iu);
  assert.match(expand, /create role investments_store_owner nologin noinherit nobypassrls/iu);
  assert.doesNotMatch(
    `${expand}\n${workflow}`,
    /grant[^;]+(?:insert|update|delete)[^;]+investments\.[a-z_]+[^;]+investments_executor/iu,
  );
  assert.match(expand, /grant investments_executor to talli_ledger_backend/iu);
  assert.match(workflow, /grant investments_workflow_executor to talli_ledger_backend/iu);
});

test("contract reconciles live state before removing predecessor production names", () => {
  const source = artifact(contractPath, "contract");
  assert.match(source, /CONTRACT RELEASE ARTIFACT:.*#141/iu);
  assert.match(source, /investments_contract_position_reconciliation_failed/iu);
  assert.match(source, /investments_contract_lot_reconciliation_failed/iu);
  assert.match(source, /investments_contract_purchase_reconciliation_failed/iu);
  assert.match(source, /investments_contract_ledger_binding_failed/iu);
  assert.match(source, /rename to rollback_141_prepare_investment_purchase_fifo_v1/iu);
  assert.match(source, /rename to rollback_141_complete_investment_purchase_fifo_v1/iu);
  assert.match(source, /drop function if exists public\.record_share_purchase_fifo/iu);
  const reconcileAt = source.search(/investments_contract_position_reconciliation_failed/iu);
  const capsuleAt = source.search(/rename to rollback_141_prepare_investment_purchase_fifo_v1/iu);
  assert.ok(reconcileAt >= 0 && capsuleAt > reconcileAt);
});

test("rollback disables successor first, preserves data, and is recutover-safe", () => {
  const source = artifact(rollbackPath, "rollback");
  assert.match(source, /BOUNDED ROLLBACK ARTIFACT:.*#141/iu);
  assert.doesNotMatch(source, /drop table|truncate/iu);
  const disableAt = source.search(
    /revoke execute on function investments\.get_share_purchase_replay_v1/iu,
  );
  const restoreAt = source.search(
    /rename to prepare_investment_purchase_fifo_v1/iu,
  );
  assert.ok(disableAt >= 0 && restoreAt > disableAt);
  assert.match(source, /investments_rollback_position_reconciliation_failed/iu);
  assert.match(source, /investments_rollback_lot_reconciliation_failed/iu);
  assert.match(source, /investments_rollback_purchase_reconciliation_failed/iu);
  assert.doesNotMatch(source, /record_share_purchase_fifo/iu);
});
