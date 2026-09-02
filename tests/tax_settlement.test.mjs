import assert from "node:assert/strict";
import test from "node:test";

import {
  TaxSettlementValidationError,
  estimateAnnualTax,
  expectedBankAmountForTaxSettlement,
  taxSettlementLedgerLines,
  validateTaxSettlement,
} from "../apps/web/app/lib/tax-settlement.ts";

test("estimates payable tax from interest, costs, and canonical investment tax components", () => {
  const estimate = estimateAnnualTax({
    ledgerEntries: [
      {
        entry_type: "admin_cost",
        lines: [
          { account: "7770", description: "Admin cost: Bank", debit: 50, credit: 0 },
          { account: "1920", description: "Paid from bank", debit: 0, credit: 50 },
        ],
      },
      {
        entry_type: "fund_distribution",
        lines: [
          { account: "1920", description: "Received", debit: 100, credit: 0 },
          { account: "8050", description: "Fund interest", debit: 0, credit: 100 },
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
    interestIncome: 100,
    fritaksmetodenAddBack: 30,
    taxableShareSaleGain: 0,
    deductibleShareSaleLoss: 0,
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

test("uses fund-sale taxable and deductible portions without taxing exempt portions", () => {
  const estimate = estimateAnnualTax({
    ledgerEntries: [],
    holdingActions: [{
      action_type: "share_sale",
      payload: {
        exempt_gain: 70,
        taxable_gain: 30,
        non_deductible_loss: 0,
        deductible_loss: 5,
      },
    }],
  });

  assert.equal(estimate.taxBasis, 25);
  assert.equal(estimate.estimatedTax, 5.5);
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
