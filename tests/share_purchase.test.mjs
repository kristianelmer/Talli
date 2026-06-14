import assert from "node:assert/strict";
import test from "node:test";

import {
  SharePurchaseValidationError,
  sharePurchaseLedgerLines,
  validateSharePurchase,
} from "../app/lib/share-purchase.ts";

test("builds deterministic share purchase payload and ledger lines", () => {
  const payload = validateSharePurchase({
    investmentKey: "portfolio-as",
    investmentName: "Portfolio AS",
    investmentKind: "norwegian_private_company",
    taxTreatment: "fritaksmetoden",
    acquisitionDate: "2025-05-01",
    shareCount: 100,
    purchaseAmount: 50000,
    orgNumber: "999888777",
    bankTransactionId: "bank-1",
    documentId: "doc-1",
    documentStatus: "attached",
  });

  assert.equal(payload.purchase_amount, 50000);
  assert.deepEqual(sharePurchaseLedgerLines(payload), [
    { account: "1800", description: "Investment in Portfolio AS", debit: 50000, credit: 0 },
    { account: "1920", description: "Paid from bank", debit: 0, credit: 50000 },
  ]);
});

test("blocks unsupported share purchase treatment with machine-readable reasons", () => {
  assert.throws(
    () =>
      validateSharePurchase({
        investmentKey: "listed",
        investmentName: "Listed ASA",
        investmentKind: "simple_listed_security",
        taxTreatment: "fritaksmetoden",
        acquisitionDate: "2025-05-01",
        shareCount: 100,
        purchaseAmount: 50000,
        documentStatus: "attached",
      }),
    (error) => error instanceof SharePurchaseValidationError && error.code === "unsupported_investment_kind",
  );
  assert.throws(
    () =>
      validateSharePurchase({
        investmentKey: "unclear",
        investmentName: "Unclear AS",
        investmentKind: "norwegian_private_company",
        taxTreatment: "needs_accountant",
        acquisitionDate: "2025-05-01",
        shareCount: 100,
        purchaseAmount: 50000,
        documentStatus: "attached",
      }),
    (error) => error instanceof SharePurchaseValidationError && error.code === "unsupported_tax_treatment",
  );
});
