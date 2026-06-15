import assert from "node:assert/strict";
import test from "node:test";

import {
  OwnerDividendValidationError,
  ownerDividendCorporateDocumentRecords,
  ownerDividendLedgerLines,
  validateOwnerDividend,
} from "../app/lib/owner-dividend.ts";

test("builds deterministic owner dividend payload, ledger lines, and documents", () => {
  const payload = validateOwnerDividend({
    decisionDate: "2025-06-01",
    paymentDate: "2025-06-15",
    totalAmount: 1000,
    distributableEquity: 5000,
    liquidityAfterPayment: 1000,
    documentStatus: "attached",
    allocations: [{ shareholderId: "owner", shareholderName: "Ola Nordmann", shareCount: 100, amount: 1000 }],
  });

  assert.deepEqual(ownerDividendLedgerLines(payload), [
    { account: "2050", description: "Dividend to shareholders", debit: 1000, credit: 0 },
    { account: "1920", description: "Dividend paid from bank", debit: 0, credit: 1000 },
  ]);
  const documents = ownerDividendCorporateDocumentRecords("company-1", 2025, "action-1", "owner-1");
  assert.equal(documents.length, 2);
  assert.equal(documents[0].document_type, "corporate_document");
  assert.equal(documents[0].linked_to, "action-1");
});

test("blocks invalid owner dividend allocations and solvency checks", () => {
  assert.throws(
    () =>
      validateOwnerDividend({
        decisionDate: "2025-06-01",
        paymentDate: "2025-06-15",
        totalAmount: 1000,
        distributableEquity: 5000,
        liquidityAfterPayment: 1000,
        documentStatus: "attached",
        allocations: [{ shareholderId: "owner", shareholderName: "Ola Nordmann", shareCount: 100, amount: 900 }],
      }),
    (error) => error instanceof OwnerDividendValidationError && error.code === "allocation_mismatch",
  );
  assert.throws(
    () =>
      validateOwnerDividend({
        decisionDate: "2025-06-01",
        paymentDate: "2025-06-15",
        totalAmount: 1000,
        distributableEquity: 500,
        liquidityAfterPayment: 1000,
        documentStatus: "attached",
        allocations: [{ shareholderId: "owner", shareholderName: "Ola Nordmann", shareCount: 100, amount: 1000 }],
      }),
    (error) => error instanceof OwnerDividendValidationError && error.code === "dividend_exceeds_distributable_equity",
  );
});
