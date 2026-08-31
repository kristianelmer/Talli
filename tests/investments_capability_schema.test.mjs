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
const saleWorkflowPath = new URL(
  "../supabase/migrations/20260831162145_investments_share_sale_workflow.sql",
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
const saleContractPath = new URL(
  "../supabase/contract-migrations/20260831170000_investments_share_sale_contract.sql",
  import.meta.url,
);
const saleRollbackPath = new URL(
  "../supabase/rollback/20260831170000_investments_share_sale_contract.sql",
  import.meta.url,
);
const dividendWorkflowPath = new URL(
  "../supabase/migrations/20260831182000_investments_received_dividend_workflow.sql",
  import.meta.url,
);
const dividendContractPath = new URL(
  "../supabase/contract-migrations/20260831190000_investments_received_dividend_contract.sql",
  import.meta.url,
);
const dividendRollbackPath = new URL(
  "../supabase/rollback/20260831190000_investments_received_dividend_contract.sql",
  import.meta.url,
);
const allocationIdentityPath = new URL(
  "../supabase/migrations/20260831180000_investments_allocation_identity.sql",
  import.meta.url,
);
const stageExitPath = new URL(
  "../supabase/contract-migrations/20260831193000_investments_stage_exit.sql",
  import.meta.url,
);
const stageExitPolicyCleanupPath = new URL(
  "../supabase/contract-migrations/20260901001500_investments_stage_exit_policy_cleanup.sql",
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

function assertBoundedBackendSystemDdlAuthority(source, phase) {
  assert.match(
    source,
    /grant (?=[^']*investments_store_owner)(?=[^']*ledger_store_owner)[^']+ to %I/iu,
    `${phase} must acquire only the owning roles`,
  );
  assert.match(
    source,
    /grant usage, create on schema backend_system to ledger_store_owner/iu,
    `${phase} must let the schema owner delegate hosted DDL authority`,
  );
  assert.match(
    source,
    /grant usage, create on schema backend_system to %I/iu,
    `${phase} must grant the hosted migrator direct schema DDL authority`,
  );
  assert.match(
    source,
    /revoke create on schema backend_system from %I/iu,
    `${phase} must revoke hosted migrator schema DDL authority`,
  );
  assert.match(
    source,
    /revoke create on schema backend_system from ledger_store_owner/iu,
    `${phase} must restore the schema owner's runtime boundary`,
  );
  assert.match(
    source,
    /revoke (?=[^']*investments_store_owner)(?=[^']*ledger_store_owner)[^']+ from %I/iu,
    `${phase} must release temporary owner-role membership`,
  );
}

test("the complete local database gate includes the investments lifecycle", () => {
  const source = readFileSync(localGatePath, "utf8");
  assert.match(source, /npm run test:investments-database-lifecycle/iu);
});

test("contract and rollback artifacts bound hosted backend-system DDL authority", () => {
  for (const [path, phase] of [
    [contractPath, "share-purchase contract"],
    [rollbackPath, "share-purchase rollback"],
    [saleContractPath, "share-sale contract"],
    [saleRollbackPath, "share-sale rollback"],
    [dividendContractPath, "received-dividend contract"],
    [dividendRollbackPath, "received-dividend rollback"],
    [stageExitPath, "investments stage exit"],
  ]) {
    assertBoundedBackendSystemDdlAuthority(artifact(path, phase), phase);
  }
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
  assert.match(
    workflow,
    /grant usage, create on schema ledger, backend_system to ledger_store_owner/iu,
  );
  assert.match(
    workflow,
    /revoke create on schema ledger, backend_system from ledger_store_owner/iu,
  );
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

test("sale workflow owns FIFO persistence behind restricted investments functions", () => {
  const source = artifact(saleWorkflowPath, "share-sale workflow");
  assert.match(
    source,
    /grant investments_store_owner, investments_executor, investments_workflow_executor, company_access_executor, ledger_store_owner to %I/iu,
  );
  assert.match(
    source,
    /revoke investments_store_owner, investments_executor, investments_workflow_executor, company_access_executor, ledger_store_owner from %I/iu,
  );
  assert.match(
    source,
    /grant usage, create on schema ledger, backend_system to ledger_store_owner/iu,
  );
  assert.match(
    source,
    /revoke create on schema ledger, backend_system from ledger_store_owner/iu,
  );
  for (const table of ["share_sales", "share_sale_allocations"]) {
    assert.match(source, new RegExp(`create table investments\\.${table}`, "iu"));
    assert.match(source, new RegExp(
      `alter table investments\\.${table} force row level security`, "iu",
    ));
  }
  for (const routine of [
    "share_sale_fingerprint_v1",
    "get_share_sale_replay_v1",
    "prepare_share_sale_v1",
    "complete_share_sale_v1",
  ]) {
    assert.match(source, new RegExp(`function investments\\.${routine}`, "iu"));
  }
  assert.match(source, /sync_legacy_share_sale_v1/iu);
  assert.match(source, /sync_legacy_share_sale_allocation_v1/iu);
  assert.match(source, /mirror_investment_sale_to_legacy_v1/iu);
  assert.match(source, /investment_sale_entry_matches_v1/iu);
  assert.match(source, /order by lot\.acquisition_date, lot\.id[\s\S]+for update/iu);
  assert.match(source, /grant execute on function[\s\S]+investments\.prepare_share_sale_v1/iu);
  assert.doesNotMatch(source, /grant[^;]+investments\.(?:share_sales|share_sale_allocations)[^;]+(?:anon|authenticated|service_role)/iu);
  assert.doesNotMatch(source, /drop function backend_system\.(?:prepare|complete)_investment_sale_fifo_v1/iu);
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

test("sale contract reconciles FIFO state before removing predecessor names", () => {
  const source = artifact(saleContractPath, "share-sale contract");
  assert.match(source, /CONTRACT RELEASE ARTIFACT:.*#142/iu);
  assert.match(source, /investments_sale_contract_position_reconciliation_failed/iu);
  assert.match(source, /investments_sale_contract_lot_reconciliation_failed/iu);
  assert.match(source, /investments_sale_contract_sale_reconciliation_failed/iu);
  assert.match(source, /investments_sale_contract_allocation_reconciliation_failed/iu);
  assert.match(source, /investments_sale_contract_ledger_binding_failed/iu);
  assert.match(source, /rename to rollback_142_prepare_investment_sale_fifo_v1/iu);
  assert.match(source, /rename to rollback_142_complete_investment_sale_fifo_v1/iu);
  assert.match(source, /drop function if exists public\.record_share_sale_fifo/iu);
  const reconcileAt = source.search(/investments_sale_contract_sale_reconciliation_failed/iu);
  const capsuleAt = source.search(/rename to rollback_142_prepare_investment_sale_fifo_v1/iu);
  assert.ok(reconcileAt >= 0 && capsuleAt > reconcileAt);
});

test("sale rollback is non-destructive and recutover-safe", () => {
  const source = artifact(saleRollbackPath, "share-sale rollback");
  assert.match(source, /BOUNDED ROLLBACK ARTIFACT:.*#142/iu);
  assert.doesNotMatch(source, /drop table|truncate/iu);
  const disableAt = source.search(
    /revoke execute on function investments\.get_share_sale_replay_v1/iu,
  );
  const restoreAt = source.search(/rename to prepare_investment_sale_fifo_v1/iu);
  assert.ok(disableAt >= 0 && restoreAt > disableAt);
  assert.match(source, /investments_sale_rollback_position_reconciliation_failed/iu);
  assert.match(source, /investments_sale_rollback_lot_reconciliation_failed/iu);
  assert.match(source, /investments_sale_rollback_sale_reconciliation_failed/iu);
  assert.match(source, /investments_sale_rollback_allocation_reconciliation_failed/iu);
  assert.doesNotMatch(source, /record_share_sale_fifo/iu);
});

test("received-dividend workflow owns policy persistence behind restricted functions", () => {
  const source = artifact(dividendWorkflowPath, "received-dividend workflow");
  assert.match(source, /create table investments\.received_dividends/iu);
  assert.match(source, /alter table investments\.received_dividends force row level security/iu);
  for (const routine of [
    "received_dividend_fingerprint_v1",
    "get_received_dividend_replay_v1",
    "prepare_received_dividend_v1",
    "complete_received_dividend_v1",
  ]) {
    assert.match(source, new RegExp(`function investments\\.${routine}`, "iu"));
  }
  assert.match(source, /sync_legacy_received_dividend_v1/iu);
  assert.match(source, /mirror_received_dividend_to_legacy_v1/iu);
  assert.match(source, /investment_dividend_entry_matches_v1/iu);
  assert.match(source, /grant execute on function[\s\S]+investments\.prepare_received_dividend_v1/iu);
  assert.doesNotMatch(source, /grant[^;]+investments\.received_dividends[^;]+(?:anon|authenticated|service_role)/iu);
  assert.doesNotMatch(source, /drop function backend_system\.(?:prepare|complete)_investment_dividend_v1/iu);
});

test("received-dividend contract reconciles before predecessor removal", () => {
  const source = artifact(dividendContractPath, "received-dividend contract");
  assert.match(source, /CONTRACT RELEASE ARTIFACT:.*#143/iu);
  assert.match(source, /investments_dividend_contract_reconciliation_failed/iu);
  assert.match(source, /investments_dividend_contract_position_binding_failed/iu);
  assert.match(source, /investments_dividend_contract_ledger_binding_failed/iu);
  assert.match(source, /rename to rollback_143_prepare_investment_dividend_v1/iu);
  assert.match(source, /rename to rollback_143_complete_investment_dividend_v1/iu);
  const reconcileAt = source.search(/investments_dividend_contract_reconciliation_failed/iu);
  const capsuleAt = source.search(/rename to rollback_143_prepare_investment_dividend_v1/iu);
  assert.ok(reconcileAt >= 0 && capsuleAt > reconcileAt);
});

test("received-dividend rollback is non-destructive and recutover-safe", () => {
  const source = artifact(dividendRollbackPath, "received-dividend rollback");
  assert.match(source, /BOUNDED ROLLBACK ARTIFACT:.*#143/iu);
  assert.doesNotMatch(source, /drop table|truncate/iu);
  const disableAt = source.search(
    /revoke execute on function investments\.get_received_dividend_replay_v1/iu,
  );
  const restoreAt = source.search(/rename to prepare_investment_dividend_v1/iu);
  assert.ok(disableAt >= 0 && restoreAt > disableAt);
  assert.match(source, /investments_dividend_rollback_reconciliation_failed/iu);
});

test("allocation identities remain stable across the overlap window", () => {
  const source = artifact(allocationIdentityPath, "allocation identity");
  assert.match(source, /alter table investments\.share_sale_allocations add column id uuid/iu);
  assert.match(source, /set id = legacy\.id/iu);
  assert.match(source, /investments_allocation_identity_reconciliation_failed/iu);
  assert.match(source, /add constraint investments_share_sale_allocations_id_key unique \(id\)/iu);
  assert.match(source, /align_legacy_share_sale_allocation_id_v1/iu);
  assert.match(source, /grant usage, create on schema backend_system to ledger_store_owner/iu);
  assert.match(source, /grant usage, create on schema backend_system to %I/iu);
  assert.match(source, /revoke create on schema backend_system from %I/iu);
  assert.match(source, /revoke create on schema backend_system from ledger_store_owner/iu);
});

test("complete stage exit reconciles before deleting every investment predecessor", () => {
  const source = artifact(stageExitPath, "complete stage exit");
  assert.match(source, /CONTRACT RELEASE ARTIFACT: complete investments stage exit, issue #143/iu);
  for (const failure of [
    "position_reconciliation_failed",
    "lot_reconciliation_failed",
    "allocation_reconciliation_failed",
    "activity_reconciliation_failed",
    "activity_count_failed",
  ]) {
    assert.match(source, new RegExp(`investments_stage_exit_${failure}`, "iu"));
  }
  const reconcileAt = source.search(/investments_stage_exit_position_reconciliation_failed/iu);
  const deleteAt = source.search(/delete from public\.holding_actions/iu);
  assert.ok(reconcileAt >= 0 && deleteAt > reconcileAt);
  for (const table of [
    "investment_lot_allocations",
    "investment_lots",
    "investment_positions",
  ]) {
    assert.match(source, new RegExp(`drop table if exists public\\.${table}`, "iu"));
  }
  assert.match(source, /drop function if exists backend_system\.rollback_141_/iu);
  assert.match(source, /drop function if exists backend_system\.rollback_142_/iu);
  assert.match(source, /drop function if exists backend_system\.rollback_143_/iu);
  assert.match(source, /drop function if exists backend_system\.sync_legacy_/iu);
  assert.match(source, /drop function if exists backend_system\.mirror_investment_/iu);
  assert.match(source, /drop function if exists backend_system\.mirror_received_dividend_/iu);
  assert.doesNotMatch(source, /drop table investments\./iu);
});

test("complete stage exit removes overlap-era and duplicate write policies", () => {
  const stageExit = artifact(stageExitPath, "complete stage exit");
  const hostedCleanup = artifact(
    stageExitPolicyCleanupPath,
    "hosted stage-exit policy cleanup",
  );
  const retiredPolicies = [
    '"investments successor mirrors actions"',
    '"investments successor appends audit"',
    "investments_positions_workflow_insert",
    "investments_positions_workflow_update",
    "investments_lots_workflow_insert",
  ];

  for (const policy of retiredPolicies) {
    const escaped = policy.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
    assert.match(stageExit, new RegExp(`drop policy if exists ${escaped}`, "iu"));
    assert.match(hostedCleanup, new RegExp(`drop policy if exists ${escaped}`, "iu"));
  }
  assert.match(hostedCleanup, /grant investments_store_owner to %I/iu);
  assert.match(hostedCleanup, /revoke investments_store_owner from %I/iu);
});

test("complete stage exit binds canonical investment writes to archive freshness", () => {
  const source = artifact(stageExitPath, "complete stage exit");
  assert.match(
    source,
    /grant investments_store_owner, ledger_store_owner, company_archive_projection_executor to %I/iu,
  );
  assert.match(
    source,
    /grant execute on function public\.company_archive_track_source_write_v1\(\) to %I/iu,
  );
  assert.match(
    source,
    /revoke execute on function public\.company_archive_track_source_write_v1\(\) from %I/iu,
  );
  assert.match(
    source,
    /revoke investments_store_owner, ledger_store_owner, company_archive_projection_executor from %I/iu,
  );
  const scopes = [
    ["positions", "company"],
    ["acquisition_lots", "company"],
    ["share_purchases", "year"],
    ["share_sales", "year"],
    ["share_sale_allocations", "company"],
    ["received_dividends", "year"],
  ];

  for (const [table, scope] of scopes) {
    assert.match(
      source,
      new RegExp(
        `before insert or update or delete on investments\\.${table} for each row\\s+execute function public\\.company_archive_track_source_write_v1\\('${scope}', 'company_id'\\)`,
        "iu",
      ),
    );
  }
});
