import assert from "node:assert/strict";
import test from "node:test";

import {
  DividendReceivedValidationError,
  dividendReceivedLedgerLines,
  summarizeDividendReceivedAnnualImpact,
  validateDividendReceived,
} from "../app/lib/dividend-received.ts";

test("builds deterministic dividend received payload and ledger lines", () => {
  const payload = validateDividendReceived({
    payingCompanyName: "Portfolio AS",
    declaredDate: "2025-04-01",
    paidDate: "2025-04-15",
    grossAmount: 100000,
    linkedInvestmentId: "portfolio-as",
    taxTreatment: "fritaksmetoden",
    threePercentTreatment: "applies",
    bankTransactionId: "bank-1",
    documentId: "doc-1",
    documentStatus: "attached",
  });

  assert.equal(payload.taxable_add_back, 3000);
  assert.equal(payload.three_percent_treatment, "applies");
  assert.deepEqual(dividendReceivedLedgerLines(payload), [
    { account: "1920", description: "Dividend received in bank", debit: 100000, credit: 0 },
    { account: "8070", description: "Dividend from Portfolio AS", debit: 0, credit: 100000 },
  ]);
});

test("does not apply the three-percent add-back when the group exemption is confirmed", () => {
  const payload = validateDividendReceived({
    payingCompanyName: "Subsidiary AS",
    declaredDate: "2025-04-01",
    paidDate: "2025-04-15",
    grossAmount: 100000,
    linkedInvestmentId: "subsidiary-as",
    taxTreatment: "fritaksmetoden",
    threePercentTreatment: "group_exemption",
    documentStatus: "attached",
  });

  assert.equal(payload.taxable_add_back, 0);
  assert.equal(payload.three_percent_treatment, "group_exemption");
});

test("blocks dividend filing when the three-percent treatment needs accountant review", () => {
  assert.throws(
    () =>
      validateDividendReceived({
        payingCompanyName: "Unclear Group Company AS",
        declaredDate: "2025-04-01",
        paidDate: "2025-04-15",
        grossAmount: 100000,
        linkedInvestmentId: "unclear-group-company",
        taxTreatment: "fritaksmetoden",
        threePercentTreatment: "needs_accountant",
        documentStatus: "attached",
      }),
    (error) =>
      error instanceof DividendReceivedValidationError && error.code === "unsupported_three_percent_treatment",
  );
});

test("blocks unsupported dividend tax treatment with machine-readable reason", () => {
  assert.throws(
    () =>
      validateDividendReceived({
        payingCompanyName: "Unclear Fund",
        declaredDate: "2025-04-01",
        paidDate: "2025-04-15",
        grossAmount: 100000,
        linkedInvestmentId: "unclear-fund",
        taxTreatment: "needs_accountant",
        threePercentTreatment: "needs_accountant",
        documentStatus: "attached",
      }),
    (error) =>
      error instanceof DividendReceivedValidationError && error.code === "unsupported_tax_treatment",
  );
});

test("summarizes annual dividend income and fritaksmetoden add-back", () => {
  const summary = summarizeDividendReceivedAnnualImpact([
    {
      action_type: "dividend_received",
      payload: { gross_amount: 100000, taxable_add_back: 3000 },
    },
    {
      action_type: "dividend_received",
      payload: { gross_amount: 2000, taxable_add_back: 60 },
    },
    {
      action_type: "manual_journal",
      payload: { gross_amount: 999999, taxable_add_back: 999999 },
    },
  ]);

  assert.deepEqual(summary, { dividendIncome: 102000, fritaksmetodenAddBack: 3060 });
});
