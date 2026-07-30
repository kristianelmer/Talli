import assert from "node:assert/strict";
import test from "node:test";

import {
  assertOperatorSearchAllowed,
  buildOperatorSupportSummaries,
} from "../apps/web/app/lib/operator-support.ts";

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

test("operator summary keeps cross-company data separated", () => {
  const summaries = buildOperatorSupportSummaries({
    companies: [{ id: "company-a", org_number: "314259521", name: "A Holding AS" }],
    readinessSnapshots: [
      { company_id: "company-a", hard_blocks: [{ code: "missing_authority" }] },
      { company_id: "company-b", hard_blocks: [{ code: "billing_missing" }, { code: "bank_missing" }] },
    ],
    submissions: [
      { company_id: "company-a", status: "submitted" },
      { company_id: "company-b", status: "failed" },
    ],
    authorityPermissions: [{ company_id: "company-b", production_enabled: true }],
    billingAccounts: [{ company_id: "company-b", refund_eligible: true }],
    billingPaymentEvents: [],
    cancellations: [{ company_id: "company-b", evidence: { missingDocumentIds: ["leaked"] } }],
    auditEvents: [
      { company_id: "company-a", action: "visible_audit", created_at: "2026-06-17T10:00:00.000Z" },
      { company_id: "company-b", action: "hidden_audit", created_at: "2026-06-17T11:00:00.000Z" },
    ],
  });

  assert.equal(summaries.length, 1);
  assert.equal(summaries[0].filingStatus, "submitted");
  assert.equal(summaries[0].readinessBlockCount, 1);
  assert.equal(summaries[0].authorityProductionEnabled, 0);
  assert.equal(summaries[0].billingStatus, "unpaid");
  assert.equal(summaries[0].restoreStatus, "missing_evidence");
  assert.deepEqual(summaries[0].recentAuditActions, ["visible_audit"]);
});
