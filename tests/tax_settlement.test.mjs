import assert from "node:assert/strict";
import test from "node:test";

import {
  TaxSettlementValidationError,
  estimateAnnualTax,
  expectedBankAmountForTaxSettlement,
  taxSettlementLedgerLines,
  validateTaxSettlement,
} from "../app/lib/tax-settlement.ts";

test("estimates payable tax from persisted admin costs and dividend add-back", () => {
  const estimate = estimateAnnualTax({
    ledgerEntries: [
      {
        entry_type: "admin_cost",
        lines: [
          { account: "7770", description: "Admin cost: Bank", debit: 50, credit: 0 },
          { account: "1920", description: "Paid from bank", debit: 0, credit: 50 },
        ],
      },
    ],
    holdingActions: [
      {
        action_type: "dividend_received",
        payload: { taxable_add_back: 30 },
      },
    ],
  });

  assert.deepEqual(estimate, {
    adminCosts: 50,
    fritaksmetodenAddBack: 30,
    taxBasis: 80,
    estimatedTax: 17.6,
    status: "payable",
  });
});

test("estimates zero tax when persisted annual data has no taxable basis", () => {
  const estimate = estimateAnnualTax({ ledgerEntries: [], holdingActions: [] });

  assert.equal(estimate.status, "zero");
  assert.equal(estimate.estimatedTax, 0);
});

test("builds deterministic payable, payment, and refund settlement ledger lines", () => {
  const payable = validateTaxSettlement({
    settlementDate: "2025-12-31",
    amount: 100,
    settlementType: "payable",
    documentStatus: "attached",
  });
  const payment = validateTaxSettlement({
    settlementDate: "2026-05-31",
    amount: 100,
    settlementType: "payment",
    documentStatus: "attached",
    bankTransactionId: "bank-payment",
  });
  const refund = validateTaxSettlement({
    settlementDate: "2026-10-15",
    amount: 20,
    settlementType: "refund",
    documentStatus: "attached",
    bankTransactionId: "bank-refund",
  });

  assert.deepEqual(taxSettlementLedgerLines(payable), [
    { account: "8300", description: "Skattekostnad", debit: 100, credit: 0 },
    { account: "2500", description: "Betalbar skatt", debit: 0, credit: 100 },
  ]);
  assert.deepEqual(taxSettlementLedgerLines(payment), [
    { account: "2500", description: "Betalt skatt", debit: 100, credit: 0 },
    { account: "1920", description: "Bank", debit: 0, credit: 100 },
  ]);
  assert.deepEqual(taxSettlementLedgerLines(refund), [
    { account: "1920", description: "Skatterefusjon mottatt", debit: 20, credit: 0 },
    { account: "1570", description: "Skatt til gode", debit: 0, credit: 20 },
  ]);
  assert.equal(expectedBankAmountForTaxSettlement(payment), -100);
  assert.equal(expectedBankAmountForTaxSettlement(refund), 20);
});

test("blocks payable estimate with direct bank link", () => {
  assert.throws(
    () =>
      validateTaxSettlement({
        settlementDate: "2025-12-31",
        amount: 100,
        settlementType: "payable",
        documentStatus: "attached",
        bankTransactionId: "bank-id",
      }),
    (error) => error instanceof TaxSettlementValidationError && error.code === "payable_bank_link_blocked",
  );
});
