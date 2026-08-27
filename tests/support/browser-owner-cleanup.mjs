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

async function deleteBrowserOwnerCompanySources(database, companyId) {
  let transactionStarted = false;
  let operationError;
  let rollbackError;
  try {
    await database.query("begin");
    transactionStarted = true;
    // The disposable local fixture's migration principal borrows the private
    // owners below so forced-RLS rows and immutable/archive triggers can be
    // removed in one FK-safe unit. Transaction scope restores every change.
    await database.query("set local session_replication_role = replica");
    await database.query(
      "delete from public.company_year_acceptances where company_id = $1",
      [companyId],
    );
    await database.query(
      "delete from public.company_year_admissions where company_id = $1",
      [companyId],
    );
    await database.query(
      "delete from public.company_eligibility_assessments where company_id = $1",
      [companyId],
    );
    await database.query(
      "delete from public.customer_agreement_acceptances where company_id = $1",
      [companyId],
    );
    await database.query(`do $browser_owner_cleanup_authority$
      begin
        execute pg_catalog.format(
          'grant ledger_store_owner to %I', current_user
        );
        execute pg_catalog.format(
          'grant ledger_workflow_store_owner to %I', current_user
        );
      end
      $browser_owner_cleanup_authority$`);
    const ledgerTables = [
      "opening_received_dividend_settlements",
      "opening_position_component_sources",
      "opening_position_components",
      "opening_position_rebuilds",
      "entry_sources",
      "entry_contexts",
      "entries",
    ];
    await database.query("set local role ledger_store_owner");
    await database.query(
      "alter table backend_system.ledger_command_receipts no force row level security",
    );
    for (const table of ledgerTables) {
      await database.query(
        `alter table ledger.${table} no force row level security`,
      );
    }
    await database.query(
      "delete from backend_system.ledger_command_receipts where company_id = $1",
      [companyId],
    );
    for (const table of ledgerTables) {
      await database.query(`delete from ledger.${table} where company_id = $1`, [
        companyId,
      ]);
    }
    await database.query(
      "alter table backend_system.ledger_command_receipts force row level security",
    );
    for (const table of ledgerTables) {
      await database.query(
        `alter table ledger.${table} force row level security`,
      );
    }
    await database.query("reset role");
    await database.query("set local role ledger_workflow_store_owner");
    await database.query(
      "alter table backend_system.ledger_workflow_receipts no force row level security",
    );
    await database.query(
      "delete from backend_system.ledger_workflow_receipts where company_id = $1",
      [companyId],
    );
    await database.query(
      "alter table backend_system.ledger_workflow_receipts force row level security",
    );
    await database.query("reset role");
    await database.query(`do $browser_owner_cleanup_authority$
      begin
        execute pg_catalog.format(
          'revoke ledger_store_owner from %I', current_user
        );
        execute pg_catalog.format(
          'revoke ledger_workflow_store_owner from %I', current_user
        );
      end
      $browser_owner_cleanup_authority$`);
    for (const table of [
      "corporate_document_events",
      "corporate_decision_finalizations",
      "corporate_document_artifacts",
      "corporate_document_sets",
      "corporate_decisions",
    ]) {
      await database.query(`delete from public.${table} where company_id = $1`, [
        companyId,
      ]);
    }
    await database.query(
      `delete from public.production_filing_events
       where submission_id in (
         select id from public.production_filing_submissions
         where company_id = $1
       )`,
      [companyId],
    );
    for (const table of [
      "production_feedback_artifacts",
      "production_filing_submissions",
      "filing_approval_snapshots",
      "production_pilot_entitlements",
      "company_deletion_reviews",
      "bank_suggestion_acceptances",
      "investment_lot_allocations",
      "investment_lots",
      "investment_positions",
      "filing_review_comments",
      "filing_submissions",
      "holding_actions",
      "documents",
      "authority_test_runs",
      "authority_permissions",
      "filing_previews",
      "opening_shareholders",
      "opening_balance_setups",
      "billing_accounts",
      "audit_events",
      "company_archive_export_receipts",
      "company_archive_export_attempts",
      "company_archive_source_generations",
    ]) {
      await database.query(`delete from public.${table} where company_id = $1`, [
        companyId,
      ]);
    }
    await database.query("set local session_replication_role = origin");
    await database.query("alter table public.companies disable trigger user");
    await database.query("delete from public.companies where id = $1", [
      companyId,
    ]);
    await database.query("alter table public.companies enable trigger user");
    await database.query("commit");
  } catch (error) {
    operationError = error;
    if (transactionStarted) {
      try {
        await database.query("rollback");
      } catch (error) {
        rollbackError = error;
      }
    }
  }
  if (operationError && rollbackError) {
    throw new AggregateError(
      [operationError, rollbackError],
      "browser_owner_source_cleanup_and_rollback_failed",
    );
  }
  if (operationError) throw operationError;
}
