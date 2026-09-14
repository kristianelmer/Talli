import assert from "node:assert/strict";
import test from "node:test";

import {
  estimateAnnualTax,
} from "./support/company_tax_public.mjs";

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

// Settlement normalization/mapping assertions moved to permanent frozen-input
// Python and authenticated HTTP tests in test_company_tax_filing*.py (#146).
