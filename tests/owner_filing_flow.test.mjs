import assert from "node:assert/strict";
import test from "node:test";

import { buildOwnerFilingPresentation } from "../app/(owner)/filing/_presentation.ts";

function submission(overrides = {}) {
  return {
    id: "submission-id",
    filing: "skattemelding for AS",
    income_year: 2025,
    mode: "simulation",
    status: "receipt_stored",
    receipt_id: "simulation-receipt-id",
    receipt_metadata: null,
    submitted_payload_ref: null,
    ...overrides,
  };
}

test("pending company-tax feedback wins regardless of row order and suppresses posted success", () => {
  const simulation = submission({ id: "simulation" });
  const pending = submission({
    id: "pending",
    mode: "test_authority",
    status: "feedback_ready",
    receipt_id: "feedback-data-id",
    receipt_metadata: {
      archiveReference: "https://platform.tt02.altinn.no/storage/api/v1/instances/instance-id",
    },
  });
  const wrongYearPending = { ...pending, id: "wrong-year", income_year: 2024 };
  const wrongFilingPending = { ...pending, id: "wrong-filing", filing: "årsregnskap" };

  for (const submissions of [
    [simulation, wrongYearPending, pending],
    [wrongFilingPending, pending, simulation],
  ]) {
    const presentation = buildOwnerFilingPresentation({
      obligation: "skattemelding",
      incomeYear: 2025,
      submissions,
      posted: true,
      error: "Behold denne feilmeldingen",
    });

    assert.equal(presentation.primarySubmission?.id, "pending");
    assert.equal(presentation.pendingCompanyTaxSubmission?.id, "pending");
    assert.equal(presentation.submitted, false);
    assert.equal(presentation.showPostedSuccessBanner, false);
    assert.equal(presentation.showProductionSubmitControl, false);
    assert.equal(presentation.errorMessage, "Behold denne feilmeldingen");
    assert.deepEqual(presentation.pendingFeedback, {
      title: "TT02-tilbakemelding mottatt",
      badgeLabel: "Test – ikke produksjonsinnsending",
      body: "Myndighetsutfallet venter på klassifisering. Kvitteringen dokumenterer mottatt testtilbakemelding, ikke et endelig utfall.",
      receiptId: "feedback-data-id",
      archiveReference: "https://platform.tt02.altinn.no/storage/api/v1/instances/instance-id",
    });
  }
});

test("non-pending obligations preserve receipt aggregation when the receipt row is not first", () => {
  const preparing = submission({
    id: "rf-preparing",
    filing: "aksjonærregisteroppgaven",
    status: "submitted",
    receipt_id: null,
  });
  const receipted = submission({
    id: "rf-receipted",
    filing: "aksjonærregisteroppgaven",
    receipt_id: "sim-rf1086-receipt",
  });
  const presentation = buildOwnerFilingPresentation({
    obligation: "aksjonaerregisteroppgaven",
    incomeYear: 2025,
    submissions: [preparing, receipted],
    posted: true,
  });

  assert.equal(presentation.pendingCompanyTaxSubmission, null);
  assert.equal(presentation.pendingFeedback, null);
  assert.equal(presentation.primarySubmission?.id, "rf-receipted");
  assert.equal(presentation.submitted, true);
  assert.equal(presentation.showPostedSuccessBanner, true);
  assert.equal(presentation.showProductionSubmitControl, true);
  assert.equal(presentation.errorMessage, null);
});
