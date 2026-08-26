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
    // Bypass only immutable fixture guards; transaction scope restores this on
    // every commit or rollback, and regular source cleanup runs with triggers.
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
    await database.query("set local session_replication_role = origin");
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
      "ledger_entries",
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
