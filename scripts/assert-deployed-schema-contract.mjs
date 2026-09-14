import { pathToFileURL } from "node:url";

export const REQUIRED_DEPLOYED_SCHEMA_PATHS = Object.freeze([
  "/bank_suggestion_acceptances",
  "/customer_agreement_acceptances",
  "/filing_approval_snapshots",
  "/production_filing_events",
  "/production_filing_submissions",
  "/rpc/append_company_agreement_acceptance",
  "/rpc/append_production_filing_event",
  "/rpc/approve_production_filing",
  "/rpc/begin_production_filing",
  "/rpc/remove_unlinked_document",
  "/rpc/restore_unlinked_document_after_storage_failure",
]);

export const FORBIDDEN_DEPLOYED_SCHEMA_PATHS = Object.freeze([
  "/production_pilot_entitlements",
  "/corporate_accounting_policies",
  "/corporate_decision_finalizations",
  "/corporate_decisions",
  "/corporate_document_artifacts",
  "/corporate_document_events",
  "/corporate_document_sets",
  "/investment_lot_allocations",
  "/investment_lots",
  "/investment_positions",
  "/rpc/attest_corporate_signed_artifact",
  "/rpc/create_corporate_document_draft",
  "/rpc/finalize_corporate_decision",
  "/rpc/import_company_tax_tt02_evidence",
  "/rpc/manage_production_pilot_entitlement",
  "/rpc/record_corporate_document_event",
  "/rpc/record_owner_dividend_payment",
  "/rpc/record_share_purchase_fifo",
  "/rpc/record_share_sale_fifo",
]);

export function missingDeployedSchemaPaths(openApi) {
  if (!openApi || typeof openApi !== "object" || !openApi.paths || typeof openApi.paths !== "object") {
    throw new Error("Expected a PostgREST OpenAPI document with a paths object.");
  }
  return REQUIRED_DEPLOYED_SCHEMA_PATHS.filter((path) => !(path in openApi.paths));
}

export function presentForbiddenDeployedSchemaPaths(openApi) {
  if (!openApi || typeof openApi !== "object" || !openApi.paths || typeof openApi.paths !== "object") {
    throw new Error("Expected a PostgREST OpenAPI document with a paths object.");
  }
  return FORBIDDEN_DEPLOYED_SCHEMA_PATHS.filter((path) => path in openApi.paths);
}

export async function inspectDeployedSchema({ supabaseUrl, serviceRoleKey, fetchImpl = fetch }) {
  if (!supabaseUrl || !serviceRoleKey) {
    throw new Error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.");
  }
  const endpoint = new URL("/rest/v1/", supabaseUrl);
  if (endpoint.protocol !== "https:" && endpoint.hostname !== "127.0.0.1" && endpoint.hostname !== "localhost") {
    throw new Error("The deployed schema contract requires HTTPS for a remote project.");
  }
  const response = await fetchImpl(endpoint, {
    headers: {
      accept: "application/openapi+json",
      apikey: serviceRoleKey,
      authorization: `Bearer ${serviceRoleKey}`,
    },
  });
  if (!response.ok) {
    throw new Error(`PostgREST schema request failed with HTTP ${response.status}.`);
  }
  const openApi = await response.json();
  return {
    endpoint: endpoint.origin,
    missing: missingDeployedSchemaPaths(openApi),
    forbidden: presentForbiddenDeployedSchemaPaths(openApi),
  };
}

async function main() {
  const result = await inspectDeployedSchema({
    supabaseUrl: process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL,
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY,
  });
  if (result.missing.length > 0 || result.forbidden.length > 0) {
    console.error(JSON.stringify({
      endpoint: result.endpoint,
      missing: result.missing,
      forbidden: result.forbidden,
    }, null, 2));
    process.exitCode = 1;
    return;
  }
  console.log(JSON.stringify({ endpoint: result.endpoint, status: "ready", paths: REQUIRED_DEPLOYED_SCHEMA_PATHS.length }, null, 2));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : "Deployed schema contract check failed.");
    process.exitCode = 1;
  });
}
