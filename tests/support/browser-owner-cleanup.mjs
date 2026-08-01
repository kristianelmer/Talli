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

  if (resources.companyId && resources.databaseStarted) {
    await attempt(() =>
      deleteImmutableAgreement(resources.database, resources.companyId),
    );
  }
  if (resources.companyId) {
    await attempt(async () => {
      const { error } = await resources.admin
        .from("companies")
        .delete()
        .eq("id", resources.companyId);
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

async function deleteImmutableAgreement(database, companyId) {
  let transactionStarted = false;
  try {
    await database.query("begin");
    transactionStarted = true;
    await database.query("set local session_replication_role = replica");
    await database.query(
      "delete from public.customer_agreement_acceptances where company_id = $1",
      [companyId],
    );
    await database.query("commit");
  } catch (error) {
    if (transactionStarted) await database.query("rollback");
    throw error;
  }
}
