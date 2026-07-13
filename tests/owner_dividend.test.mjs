import assert from "node:assert/strict";
import test from "node:test";

import {
  allocateOwnerDividend,
  OwnerDividendValidationError,
  ownerDividendLedgerLines,
  validateOwnerDividend,
} from "../app/lib/owner-dividend.ts";
import {
  generateOwnerDividendCorporateDocuments,
  prepareOwnerDividendCorporateDocuments,
} from "../app/lib/owner-dividend-documents.ts";

test("builds deterministic owner dividend payload, ledger lines, and real PDF drafts", async () => {
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
  const generated = await generateOwnerDividendCorporateDocuments({
    companyName: "LOGISK ØDE TIGER AS",
    orgNumber: "310279617",
    incomeYear: 2025,
    payload,
  });
  assert.equal(generated.length, 2);
  assert.ok(generated.every((document) => document.content.subarray(0, 5).toString() === "%PDF-"));
  const documents = prepareOwnerDividendCorporateDocuments({
    companyId: "company-1",
    incomeYear: 2025,
    actionId: "action-1",
    createdBy: "owner-1",
    documents: generated,
  });
  assert.equal(documents.length, 2);
  assert.equal(documents[0].metadata.document_type, "corporate_document");
  assert.equal(documents[0].metadata.linked_to, "action-1");
  assert.equal(documents[0].metadata.status, "generated_unsigned");
  assert.match(documents[0].storageKey, /^company-1\/2025\/[0-9a-f-]+\/styreforslag-og-protokoll-utbytte\.pdf$/u);
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
  assert.throws(
    () =>
      validateOwnerDividend({
        decisionDate: "2025-06-15",
        paymentDate: "2025-06-01",
        totalAmount: 1000,
        distributableEquity: 5000,
        liquidityAfterPayment: 1000,
        documentStatus: "attached",
        allocations: [{ shareholderId: "owner", shareholderName: "Ola Nordmann", shareCount: 100, amount: 1000 }],
      }),
    (error) => error instanceof OwnerDividendValidationError && error.code === "payment_before_decision",
  );
  assert.throws(
    () =>
      validateOwnerDividend({
        decisionDate: "2025-02-31",
        paymentDate: "2025-06-01",
        totalAmount: 1000,
        distributableEquity: 5000,
        liquidityAfterPayment: 1000,
        documentStatus: "attached",
        allocations: [{ shareholderId: "owner", shareholderName: "Ola Nordmann", shareCount: 100, amount: 1000 }],
      }),
    (error) => error instanceof OwnerDividendValidationError && error.code === "invalid_date",
  );
  assert.throws(
    () =>
      validateOwnerDividend({
        decisionDate: "2025-06-01",
        paymentDate: "2025-06-15",
        totalAmount: 1000,
        distributableEquity: Number.NaN,
        liquidityAfterPayment: 1000,
        documentStatus: "attached",
        allocations: [{ shareholderId: "owner", shareholderName: "Ola Nordmann", shareCount: 100, amount: 1000 }],
      }),
    (error) => error instanceof OwnerDividendValidationError && error.code === "invalid_distributable_equity",
  );
});

test("allocates simple dividends equally per share across the complete register", () => {
  const allocations = allocateOwnerDividend(1200, [
    { shareholderId: "owner-1", shareholderName: "Ola Nordmann", shareCount: 75 },
    { shareholderId: "owner-2", shareholderName: "Kari Nordmann", shareCount: 25 },
  ]);
  assert.deepEqual(allocations, [
    { shareholderId: "owner-1", shareholderName: "Ola Nordmann", shareCount: 75, amount: 900 },
    { shareholderId: "owner-2", shareholderName: "Kari Nordmann", shareCount: 25, amount: 300 },
  ]);
  assert.doesNotThrow(() =>
    validateOwnerDividend({
      decisionDate: "2025-06-01",
      paymentDate: "2025-06-15",
      totalAmount: 1200,
      distributableEquity: 5000,
      liquidityAfterPayment: 1000,
      documentStatus: "attached",
      allocations,
    }),
  );
  assert.throws(
    () =>
      allocateOwnerDividend(10, [
        { shareholderId: "owner-1", shareholderName: "Ola Nordmann", shareCount: 2 },
        { shareholderId: "owner-2", shareholderName: "Kari Nordmann", shareCount: 1 },
      ]),
    (error) => error instanceof OwnerDividendValidationError && error.code === "indivisible_per_share_amount",
  );
  assert.throws(
    () =>
      validateOwnerDividend({
        decisionDate: "2025-06-01",
        paymentDate: "2025-06-15",
        totalAmount: 1200,
        distributableEquity: 5000,
        liquidityAfterPayment: 1000,
        documentStatus: "attached",
        allocations: [
          { shareholderId: "owner-1", shareholderName: "Ola Nordmann", shareCount: 75, amount: 800 },
          { shareholderId: "owner-2", shareholderName: "Kari Nordmann", shareCount: 25, amount: 400 },
        ],
      }),
    (error) => error instanceof OwnerDividendValidationError && error.code === "unequal_per_share_allocation",
  );
});
