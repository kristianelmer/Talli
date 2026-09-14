import assert from "node:assert/strict";
import test from "node:test";

import {
  FORBIDDEN_DEPLOYED_SCHEMA_PATHS,
  REQUIRED_DEPLOYED_SCHEMA_PATHS,
  missingDeployedSchemaPaths,
  presentForbiddenDeployedSchemaPaths,
} from "../scripts/assert-deployed-schema-contract.mjs";

test("deployed schema contract covers every post-baseline product capability", () => {
  assert.deepEqual(REQUIRED_DEPLOYED_SCHEMA_PATHS, [
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
  assert.deepEqual(FORBIDDEN_DEPLOYED_SCHEMA_PATHS, [
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
});

test("reports only missing OpenAPI paths in stable order", () => {
  const openApi = {
    paths: {
      "/corporate_decisions": {},
    },
  };

  assert.deepEqual(missingDeployedSchemaPaths(openApi),
    REQUIRED_DEPLOYED_SCHEMA_PATHS.filter(
      (path) => path !== "/corporate_decisions",
    ));
});

test("reports compatibility paths that survived a completed stage exit", () => {
  const openApi = {
    paths: {
      "/corporate_decisions": {},
      "/investment_lots": {},
      "/rpc/record_share_purchase_fifo": {},
    },
  };

  assert.deepEqual(presentForbiddenDeployedSchemaPaths(openApi), [
    "/corporate_decisions",
    "/investment_lots",
    "/rpc/record_share_purchase_fifo",
  ]);
});

test("fails closed when the response is not a PostgREST OpenAPI document", () => {
  assert.throws(
    () => missingDeployedSchemaPaths({ message: "unauthorized" }),
    /PostgREST OpenAPI document/u,
  );
  assert.throws(
    () => presentForbiddenDeployedSchemaPaths({ message: "unauthorized" }),
    /PostgREST OpenAPI document/u,
  );
});

test("contracted Tax schema needs no retired import RPC and rejects its restoration", () => {
  const paths = Object.fromEntries(REQUIRED_DEPLOYED_SCHEMA_PATHS.map(path => [path, {}]));
  assert.deepEqual(missingDeployedSchemaPaths({ paths }), []);
  assert.deepEqual(presentForbiddenDeployedSchemaPaths({ paths }), []);
  paths["/rpc/import_company_tax_tt02_evidence"] = {};
  assert.deepEqual(presentForbiddenDeployedSchemaPaths({ paths }), ["/rpc/import_company_tax_tt02_evidence"]);
});
