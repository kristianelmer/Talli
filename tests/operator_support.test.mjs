import assert from "node:assert/strict";
import test from "node:test";

import {
  assertOperatorSearchAllowed,
  buildOperatorSupportSummaries,
} from "../app/lib/operator-support.ts";

test("operator search denies non-operators and too-short queries", () => {
  assert.throws(() => assertOperatorSearchAllowed({ isOperator: false, query: "314" }), /operator_access_required/);
  assert.throws(() => assertOperatorSearchAllowed({ isOperator: true, query: "31" }), /operator_search_query_too_short/);
  assert.doesNotThrow(() => assertOperatorSearchAllowed({ isOperator: true, query: "314" }));
});

test("operator summary highlights filing, billing, refund, restore, and audit state", () => {
  const summaries = buildOperatorSupportSummaries({
    companies: [{ id: "company-id", org_number: "314259521", name: "Talli Holding AS" }],
    readinessSnapshots: [
      {
        company_id: "company-id",
        hard_blocks: [{ code: "missing_authority" }, { code: "billing_missing" }],
      },
    ],
    submissions: [{ company_id: "company-id", status: "failed" }],
    authorityPermissions: [{ company_id: "company-id", production_enabled: true }],
    billingAccounts: [
      {
        company_id: "company-id",
        subscription_active: true,
        filing_package_paid: true,
        refund_eligible: false,
        refund_completed: true,
        refund_provider_ref: "sim_refund_company-id_2025",
      },
    ],
    billingPaymentEvents: [{ company_id: "company-id", provider_reference: "sim_refund_company-id_2025" }],
    cancellations: [{ company_id: "company-id", evidence: { missingDocumentIds: ["document-id"] } }],
    auditEvents: [
      { company_id: "company-id", action: "billing_refund_completed", created_at: "2026-06-17T10:00:00.000Z" },
      { company_id: "company-id", action: "filing_failed", created_at: "2026-06-17T09:00:00.000Z" },
    ],
  });

  assert.equal(summaries[0].filingStatus, "failed");
  assert.equal(summaries[0].readinessBlockCount, 2);
  assert.equal(summaries[0].authorityProductionEnabled, 1);
  assert.equal(summaries[0].billingStatus, "refund_completed");
  assert.equal(summaries[0].refundStatus, "sim_refund_company-id_2025");
  assert.equal(summaries[0].restoreStatus, "missing_evidence");
  assert.deepEqual(summaries[0].recentAuditActions, ["billing_refund_completed", "filing_failed"]);
});
