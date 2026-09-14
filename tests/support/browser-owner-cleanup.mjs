import assert from "node:assert/strict";
import { fixtureTableTransaction, deleteRfFixtureCompanies } from "./rf1086-fixture-access.mjs";
import { stopOwnedProcess } from "./owned-process-lifecycle.mjs";

export async function cleanupBrowserOwnerResources(resources) {
  const errors = [];
  const attempt = async (cleanup) => {
    try {
      await cleanup();
    } catch (error) {
      errors.push(error);
    }
  };

  await attempt(() => resources.browser?.close());
  await attempt(() => stopOwnedProcess(resources.server));
  await attempt(() => stopOwnedProcess(resources.backend));
  await attempt(() => resources.cleanupBackendDatabaseRole?.());
  if (resources.storageKeys?.length > 0) {
    await attempt(async () => {
      const { error } = await resources.admin.storage
        .from("company-documents")
        .remove(resources.storageKeys);
      if (error) throw error;
    });
  }

  const companyIds = [...new Set([
    resources.companyId,
    ...(resources.companyIds ?? []),
  ].filter((companyId) => typeof companyId === "string" && companyId.length > 0))];
  for (const companyId of companyIds) {
    if (resources.databaseStarted) {
      await attempt(() =>
        deleteBrowserOwnerCompanySources(resources.database, companyId),
      );
    }
  }
  for (const companyId of companyIds) {
    await attempt(async () => {
      const { error } = await resources.admin
        .from("companies")
        .delete()
        .eq("id", companyId);
      if (error) throw error;
    });
  }
  if (resources.ownerId) {
    await attempt(async () => {
      const { error } = await resources.admin.auth.admin.deleteUser(
        resources.ownerId,
      );
      if (error) throw error;
    });
  }
  if (resources.databaseStarted) {
    await attempt(() => resources.database.end());
  }

  return errors;
}

export function cleanupFailure(primaryFailure, cleanupErrors) {
  if (cleanupErrors.length === 0 || primaryFailure) return null;
  return new AggregateError(cleanupErrors, "annual_loop_teardown_failed");
}

// This list is the retained owner/onboarding cleanup inventory. Catalog checks
// select only named capability rollout replacements and the existing optional
// investment projections; an unexpected absence of a required family fails.
const requiredCleanupRelations = Object.freeze([
  "public.company_year_acceptances",
  "public.company_year_admissions",
  "public.company_eligibility_assessments",
  "public.customer_agreement_acceptances",
  "backend_system.banking_command_receipts",
  "banking.transaction_sources",
  "banking.coverage_intervals",
  "banking.suggestion_acceptances",
  "banking.transactions",
  "banking.source_files",
  "banking.sync_attempts",
  "banking.accounts",
  "banking.connections",
  "backend_system.ledger_command_receipts",
  "ledger.opening_received_dividend_settlements",
  "ledger.opening_position_component_sources",
  "ledger.opening_position_components",
  "ledger.opening_position_rebuilds",
  "ledger.entry_corrections",
  "ledger.entry_sources",
  "ledger.entry_contexts",
  "ledger.entries",
  "investments.lifecycle_correction_sources",
  "investments.lifecycle_corrections",
  "investments.measurement_sources",
  "investments.year_end_measurements",
  "investments.received_fund_distribution_recognitions",
  "investments.received_dividend_recognitions",
  "investments.share_purchase_recognitions",
  "investments.cash_settlements",
  "investments.event_sources",
  "investments.economic_events",
  "investments.position_boundary_confirmations",
  "investments.position_classifications",
  "investments.source_fact_registry",
  "investments.company_year_policies",
  "investments.corrections",
  "investments.share_sale_allocations",
  "investments.received_fund_distributions",
  "investments.received_dividends",
  "investments.share_sales",
  "investments.share_purchases",
  "investments.acquisition_lots",
  "investments.positions",
  "backend_system.ledger_workflow_receipts",
  "public.company_deletion_reviews",
  "public.documents",
  "public.audit_events",
  "public.company_archive_export_receipts",
  "public.company_archive_export_attempts",
  "public.company_archive_source_generations",
  "public.company_memberships",
  "public.companies",
  "documents.evidence_references"
]);
const canonicalGovernanceCleanupRelations = Object.freeze(["corporate_governance.owner_dividend_payments", "corporate_governance.owner_dividend_finalizations", "corporate_governance.owner_dividend_events", "corporate_governance.owner_dividend_artifacts", "corporate_governance.owner_dividend_decisions", "corporate_governance.annual_close_finalizations", "corporate_governance.annual_close_events", "corporate_governance.annual_close_artifacts", "corporate_governance.annual_close_decisions", "corporate_governance.shareholder_loans"]);
const canonicalTaxFilingCleanupRelations = Object.freeze([
  "company_tax_filing.filing_submissions",
  "company_tax_filing.filing_review_comments",
  "company_tax_filing.filing_overrides",
  "company_tax_filing.filing_previews",
  "company_tax_filing.authority_test_runs",
  "company_tax_filing.authority_permissions",
]);
const genericFilingCleanupRelations = Object.freeze(["public.filing_submissions", "public.filing_review_comments", "public.filing_overrides", "public.filing_previews", "public.authority_test_runs", "public.authority_permissions"]);
const canonicalAccountsCleanupRelations = Object.freeze(["annual_accounts_filing.filing_submissions", "annual_accounts_filing.filing_review_comments", "annual_accounts_filing.filing_overrides", "annual_accounts_filing.filing_previews", "annual_accounts_filing.authority_test_runs", "annual_accounts_filing.authority_permissions"]);
const rolloutCleanupRelations = Object.freeze([
  ...genericFilingCleanupRelations,
  ...canonicalAccountsCleanupRelations,
  "public.bank_suggestion_acceptances",
  "public.corporate_document_events",
  "public.corporate_decision_finalizations",
  "public.corporate_document_artifacts",
  "public.corporate_document_sets",
  "public.corporate_decisions",
  "public.holding_actions",
  "public.bank_transactions",
  "company_tax_filing.settlements",
  ...canonicalTaxFilingCleanupRelations,
  ...canonicalGovernanceCleanupRelations,
  "public.investment_lot_allocations",
  "public.investment_lots",
  "public.investment_positions",
  "public.opening_balance_setups",
  "public.opening_shareholders",
  "public.production_feedback_artifacts",
  "public.production_filing_events",
  "public.production_filing_submissions",
  "public.filing_approval_snapshots",
  "shareholder_register_filing.production_feedback_artifacts",
  "shareholder_register_filing.production_filing_events",
  "shareholder_register_filing.production_filing_submissions",
  "shareholder_register_filing.filing_approval_snapshots",
  "shareholder_register_filing.filing_review_comments",
  "shareholder_register_filing.filing_overrides",
  "shareholder_register_filing.filing_submissions",
  "shareholder_register_filing.authority_test_runs",
  "shareholder_register_filing.authority_permissions",
  "shareholder_register_filing.filing_previews",
  "shareholder_register_filing.opening_shareholders",
  "shareholder_register_filing.opening_balance_setups",
  "shareholder_register_filing.migration_inventory",
  "shareholder_register_filing.migration_quarantine",
  "ledger.opening_bank_inputs",
  "authority_connections.system_user_requests",
  "public.system_user_requests",
  "billing.production_pilot_entitlements",
  "public.production_pilot_entitlements",
  "billing.billing_accounts",
  "public.billing_accounts"
]);

async function deleteBrowserOwnerCompanySources(database, companyId) {
  assert.ok(["127.0.0.1", "localhost", "::1"].includes(database.connectionParameters?.host));
  assert.match(companyId, /^[0-9a-f-]{36}$/iu);
  const present = new Set(requiredCleanupRelations);
  for (const relation of rolloutCleanupRelations) {
    const { rows: [row] } = await database.query(
      "select relkind from pg_class where oid=pg_catalog.to_regclass($1)", [relation]);
    if (row && ["r", "p"].includes(row.relkind)) present.add(relation);
    else assert.ok(!row || row.relkind === "v", "unexpected fixture relation kind");
  }
  if (genericFilingCleanupRelations.some(relation => !present.has(relation))) {
    assert.ok(genericFilingCleanupRelations.every(relation => !present.has(relation)), "partial generic filing retirement");
    assert.equal((await database.query("select phase from backend_system.annual_accounts_migration_state where singleton")).rows[0]?.phase, "contracted");
    for (const relation of canonicalAccountsCleanupRelations) assert.ok(present.has(relation), `missing Accounts fixture family ${relation}`);
  }
  if (!present.has("public.holding_actions")) {
    assert.ok(present.has("company_tax_filing.settlements"), "missing Tax fixture family");
  }
  if (!present.has("public.corporate_decisions")) {
    for (const relation of canonicalGovernanceCleanupRelations) {
      assert.ok(present.has(relation), `missing Corporate Governance fixture family ${relation}`);
    }
  } else {
    for (const relation of ["public.corporate_document_events", "public.corporate_decision_finalizations",
      "public.corporate_document_artifacts", "public.corporate_document_sets"]) {
      assert.ok(present.has(relation), `missing Corporate Governance fixture family ${relation}`);
    }
  }
  const rfSchema = present.has("shareholder_register_filing.production_filing_submissions")
    ? "shareholder_register_filing" : "public";
  for (const name of [
    "production_feedback_artifacts",
    "production_filing_events",
    "production_filing_submissions",
    "filing_approval_snapshots",
    "filing_review_comments",
    "filing_overrides",
    "filing_submissions",
    "authority_test_runs",
    "authority_permissions",
    "filing_previews",
    "opening_shareholders",
    "opening_balance_setups",
    "migration_inventory",
    "migration_quarantine"
  ]) {
    if (["migration_inventory", "migration_quarantine"].includes(name) && rfSchema === "public") continue;
    assert.ok(present.has(`${rfSchema}.${name}`), `missing RF fixture family ${name}`);
  }
  const authorityTable = present.has("authority_connections.system_user_requests")
    ? "authority_connections.system_user_requests" : "public.system_user_requests";
  assert.ok(present.has(authorityTable), "missing Authority fixture family");
  const billingSchema = present.has("billing.production_pilot_entitlements") ? "billing" : "public";
  assert.ok(present.has(`${billingSchema}.production_pilot_entitlements`));
  assert.ok(present.has(`${billingSchema}.billing_accounts`));

  await fixtureTableTransaction(database, [...present], async () => {
    const remove = async (relation) => {
      if (present.has(relation)) await database.query(`delete from ${relation} where company_id = $1`, [companyId]);
    };
    for (const relation of canonicalAccountsCleanupRelations) await remove(relation);
    for (const relation of canonicalTaxFilingCleanupRelations) await remove(relation);
    await remove("company_tax_filing.settlements");
    for (const relation of canonicalGovernanceCleanupRelations) await remove(relation);
    // Corporate finalizations/holding actions and bank links precede the Ledger
    // entries they reference. Internal FK triggers remain enabled throughout.
    for (const name of [
      "company_year_acceptances",
      "company_year_admissions",
      "company_eligibility_assessments",
      "customer_agreement_acceptances",
      "corporate_document_events",
      "corporate_decision_finalizations",
      "corporate_document_artifacts",
      "corporate_document_sets",
      "corporate_decisions",
      "investment_lot_allocations",
      "investment_lots",
      "investment_positions",
      "bank_suggestion_acceptances",
      "holding_actions",
      "bank_transactions"
    ]) await remove(`public.${name}`);
    await remove("backend_system.banking_command_receipts");
    for (const name of [
      "transaction_sources",
      "coverage_intervals",
      "suggestion_acceptances",
      "transactions",
      "source_files",
      "sync_attempts",
      "accounts",
      "connections"
    ]) await remove(`banking.${name}`);
    await remove("backend_system.ledger_command_receipts");
    for (const name of [
      "opening_received_dividend_settlements",
      "opening_position_component_sources",
      "opening_position_components",
      "opening_position_rebuilds",
      "entry_corrections",
      "entry_sources",
      "entry_contexts",
      "entries"
    ]) await remove(`ledger.${name}`);
    for (const name of [
      "lifecycle_correction_sources",
      "lifecycle_corrections",
      "measurement_sources",
      "year_end_measurements",
      "received_fund_distribution_recognitions",
      "received_dividend_recognitions",
      "share_purchase_recognitions",
      "cash_settlements",
      "event_sources",
      "economic_events",
      "position_boundary_confirmations",
      "position_classifications",
      "source_fact_registry",
      "company_year_policies",
      "corrections",
      "share_sale_allocations",
      "received_fund_distributions",
      "received_dividends",
      "share_sales",
      "share_purchases",
      "acquisition_lots",
      "positions"
    ]) await remove(`investments.${name}`);
    await remove("backend_system.ledger_workflow_receipts");

    for (const schema of ["public", "shareholder_register_filing"]) {
      if (!present.has(`${schema}.production_filing_submissions`)) continue;
      await remove(`${schema}.production_feedback_artifacts`);
      await database.query(`delete from ${schema}.production_filing_events where submission_id in (
        select id from ${schema}.production_filing_submissions where company_id = $1)`, [companyId]);
      await remove(`${schema}.production_filing_submissions`);
      await remove(`${schema}.filing_approval_snapshots`);
    }
    await remove(`${billingSchema}.production_pilot_entitlements`);
    await remove(authorityTable);
    // Frozen sibling preview/submission rows and canonical RF rows both retain
    // their original company scope; no absent facade is recreated for cleanup.
    for (const schema of ["public", "shareholder_register_filing"]) {
      for (const name of ["filing_review_comments", "filing_overrides", "filing_submissions", "authority_test_runs", "authority_permissions", "filing_previews"])
        await remove(`${schema}.${name}`);
    }
    await database.query(`delete from documents.evidence_references where document_id in (
      select id from public.documents where company_id = $1)`, [companyId]);
    await remove("public.documents");
    await remove("ledger.opening_bank_inputs");
    for (const schema of ["public", "shareholder_register_filing"]) {
      await remove(`${schema}.opening_shareholders`);
      await remove(`${schema}.opening_balance_setups`);
    }
    for (const name of ["migration_inventory", "migration_quarantine"]) await remove(`shareholder_register_filing.${name}`);
    await remove(`${billingSchema}.billing_accounts`);
    for (const name of ["company_deletion_reviews", "audit_events", "company_archive_export_receipts", "company_archive_export_attempts", "company_archive_source_generations", "company_memberships"])
      await remove(`public.${name}`);
    if (billingSchema === "billing") await deleteRfFixtureCompanies(database, [companyId]);
    else await database.query("delete from public.companies where id = $1", [companyId]);
  });
}
