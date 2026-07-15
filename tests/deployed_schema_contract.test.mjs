import assert from "node:assert/strict";
import test from "node:test";

import {
  REQUIRED_DEPLOYED_SCHEMA_PATHS,
  missingDeployedSchemaPaths,
} from "../scripts/assert-deployed-schema-contract.mjs";

test("deployed schema contract covers every post-baseline product capability", () => {
  assert.deepEqual(REQUIRED_DEPLOYED_SCHEMA_PATHS, [
    "/bank_suggestion_acceptances",
    "/corporate_accounting_policies",
    "/corporate_decision_finalizations",
    "/corporate_decisions",
    "/corporate_document_artifacts",
    "/corporate_document_events",
    "/corporate_document_sets",
    "/investment_lot_allocations",
    "/investment_lots",
    "/rpc/accept_bank_transaction_suggestion",
    "/rpc/attest_corporate_signed_artifact",
    "/rpc/create_corporate_document_draft",
    "/rpc/finalize_corporate_decision",
    "/rpc/import_company_tax_tt02_evidence",
    "/rpc/record_corporate_document_event",
    "/rpc/record_owner_dividend_payment",
    "/rpc/remove_unlinked_document",
    "/rpc/restore_unlinked_document_after_storage_failure",
    "/rpc/record_share_purchase_fifo",
    "/rpc/record_share_sale_fifo",
  ]);
});

test("reports only missing OpenAPI paths in stable order", () => {
  const openApi = {
    paths: {
      "/investment_lots": {},
      "/rpc/record_share_purchase_fifo": {},
    },
  };

  assert.deepEqual(missingDeployedSchemaPaths(openApi),
    REQUIRED_DEPLOYED_SCHEMA_PATHS.filter(
      (path) => path !== "/investment_lots" && path !== "/rpc/record_share_purchase_fifo",
    ));
});

test("fails closed when the response is not a PostgREST OpenAPI document", () => {
  assert.throws(
    () => missingDeployedSchemaPaths({ message: "unauthorized" }),
    /PostgREST OpenAPI document/u,
  );
});
