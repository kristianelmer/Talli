import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { buildOperatorSupportSummaries } from "../apps/web/app/lib/operator-support.ts";

function resources(overrides) {
  return {
    companies: [],
    auditEvents: [],
    companyCancellations: [],
    filingSubmissions: [],
    filingReadinessSnapshots: [],
    billingAccounts: [],
    billingPaymentEvents: [],
    authorityPermissions: [],
    authorityTestRuns: [],
    systemUserRequests: [],
    productionPilotEntitlements: [],
    filingApprovalSnapshots: [],
    productionFilingSubmissions: [],
    productionFilingEvents: [],
    productionFeedbackArtifacts: [],
    documents: [],
    storageObjects: [],
    companyDeletionReviews: [],
    ...overrides,
  };
}

test("operator support exposes no legacy company-search seam", async () => {
  const [support, server, page] = await Promise.all([
    readFile(new URL("../apps/web/app/lib/operator-support.ts", import.meta.url), "utf8"),
    readFile(new URL("../apps/web/app/lib/supabase/server.ts", import.meta.url), "utf8"),
    readFile(new URL("../apps/web/app/(operator)/operator/page.tsx", import.meta.url), "utf8"),
  ]);
  assert.doesNotMatch(`${support}\n${server}\n${page}`, /assertOperatorSearchAllowed|searchOperatorCompanyRecords/u);
  assert.match(server, /readOperatorSupportCase/u);
  assert.match(page, /supportCaseId/u);
});

test("operator summary highlights filing, billing, refund, restore, and audit state", () => {
  const summaries = buildOperatorSupportSummaries(resources({
    companies: [{ id: "company-id", orgNumber: "314259521", name: "Talli Holding AS" }],
    filingReadinessSnapshots: [
      {
        companyId: "company-id",
        hardBlocks: [{ code: "missing_authority" }, { code: "billing_missing" }],
      },
    ],
    filingSubmissions: [{ companyId: "company-id", status: "failed" }],
    authorityPermissions: [{ companyId: "company-id", productionEnabled: true }],
    billingAccounts: [
      {
        companyId: "company-id",
        subscriptionActive: true,
        filingPackagePaid: true,
        refundEligible: false,
        refundCompleted: true,
        refundProviderRef: "sim_refund_company-id_2025",
      },
    ],
    companyCancellations: [{ companyId: "company-id", evidence: { missingDocumentIds: ["document-id"] } }],
    auditEvents: [
      { companyId: "company-id", action: "billing_refund_completed", createdAt: "2026-06-17T10:00:00.000Z" },
      { companyId: "company-id", action: "filing_failed", createdAt: "2026-06-17T09:00:00.000Z" },
    ],
  }));

  assert.equal(summaries[0].filingStatus, "failed");
  assert.equal(summaries[0].readinessBlockCount, 2);
  assert.equal(summaries[0].authorityProductionEnabled, 1);
  assert.equal(summaries[0].billingStatus, "refund_completed");
  assert.equal(summaries[0].refundStatus, "sim_refund_company-id_2025");
  assert.equal(summaries[0].restoreStatus, "missing_evidence");
  assert.deepEqual(summaries[0].recentAuditActions, ["billing_refund_completed", "filing_failed"]);
});

test("operator summary keeps cross-company data separated", () => {
  const summaries = buildOperatorSupportSummaries(resources({
    companies: [{ id: "company-a", orgNumber: "314259521", name: "A Holding AS" }],
    filingReadinessSnapshots: [
      { companyId: "company-a", hardBlocks: [{ code: "missing_authority" }] },
      { companyId: "company-b", hardBlocks: [{ code: "billing_missing" }, { code: "bank_missing" }] },
    ],
    filingSubmissions: [
      { companyId: "company-a", status: "submitted" },
      { companyId: "company-b", status: "failed" },
    ],
    authorityPermissions: [{ companyId: "company-b", productionEnabled: true }],
    billingAccounts: [{ companyId: "company-b", refundEligible: true }],
    companyCancellations: [{ companyId: "company-b", evidence: { missingDocumentIds: ["leaked"] } }],
    auditEvents: [
      { companyId: "company-a", action: "visible_audit", createdAt: "2026-06-17T10:00:00.000Z" },
      { companyId: "company-b", action: "hidden_audit", createdAt: "2026-06-17T11:00:00.000Z" },
    ],
  }));

  assert.equal(summaries.length, 1);
  assert.equal(summaries[0].filingStatus, "submitted");
  assert.equal(summaries[0].readinessBlockCount, 1);
  assert.equal(summaries[0].authorityProductionEnabled, 0);
  assert.equal(summaries[0].billingStatus, "unpaid");
  assert.equal(summaries[0].restoreStatus, "missing_evidence");
  assert.deepEqual(summaries[0].recentAuditActions, ["visible_audit"]);
});
