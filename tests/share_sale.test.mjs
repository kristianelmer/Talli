import assert from "node:assert/strict";
import test from "node:test";

import { ShareSaleValidationError, shareSaleLedgerLines, validateShareSale } from "../apps/web/app/lib/share-sale.ts";

test("builds partial share sale payload and gain ledger lines", () => {
  const payload = validateShareSale({
    positionId: "position-1",
    investmentKey: "portfolio-as",
    investmentName: "Portfolio AS",
    currentShareCount: 100,
    currentCostBasis: 50000,
    acquisitionLots: [
      {
        id: "lot-1",
        acquisitionDate: "2025-05-01",
        remainingShareCount: 100,
        remainingCostBasis: 50000,
      },
    ],
    saleDate: "2025-08-01",
    soldShareCount: 40,
    proceeds: 30000,
    documentStatus: "attached",
  });

  assert.equal(payload.cost_basis_reduction, 20000);
  assert.equal(payload.gain_or_loss, 10000);
  assert.equal(payload.tax_treatment, "fritaksmetoden");
  assert.equal(payload.remaining_share_count, 60);
  assert.equal(payload.remaining_cost_basis, 30000);
  assert.deepEqual(payload.lot_allocations, [
    { lot_id: "lot-1", acquisition_date: "2025-05-01", share_count: 40, cost_basis: 20000 },
  ]);
  assert.deepEqual(shareSaleLedgerLines(payload), [
    { account: "1920", description: "Sale proceeds received in bank", debit: 30000, credit: 0 },
    { account: "1800", description: "Cost basis reduction: Portfolio AS", debit: 0, credit: 20000 },
    { account: "8070", description: "Share sale gain: Portfolio AS", debit: 0, credit: 10000 },
  ]);
});

test("supports full sale and blocks oversale", () => {
  const fullSale = validateShareSale({
    positionId: "position-1",
    investmentKey: "portfolio-as",
    investmentName: "Portfolio AS",
    currentShareCount: 100,
    currentCostBasis: 50000,
    acquisitionLots: [
      {
        id: "lot-1",
        acquisitionDate: "2025-05-01",
        remainingShareCount: 100,
        remainingCostBasis: 50000,
      },
    ],
    saleDate: "2025-08-01",
    soldShareCount: 100,
    proceeds: 50000,
    documentStatus: "attached",
  });
  assert.equal(fullSale.remaining_share_count, 0);
  assert.equal(fullSale.remaining_cost_basis, 0);

  assert.throws(
    () =>
      validateShareSale({
        positionId: "position-1",
        investmentKey: "portfolio-as",
        investmentName: "Portfolio AS",
        currentShareCount: 100,
        currentCostBasis: 50000,
        acquisitionLots: [
          {
            id: "lot-1",
            acquisitionDate: "2025-05-01",
            remainingShareCount: 100,
            remainingCostBasis: 50000,
          },
        ],
        saleDate: "2025-08-01",
        soldShareCount: 101,
        proceeds: 50000,
        documentStatus: "attached",
      }),
    (error) => error instanceof ShareSaleValidationError && error.code === "sale_exceeds_position",
  );
});

test("uses FIFO lots rather than proportional position cost", () => {
  const payload = validateShareSale({
    positionId: "position-1",
    investmentKey: "portfolio-as",
    investmentName: "Portfolio AS",
    currentShareCount: 200,
    currentCostBasis: 40000,
    acquisitionLots: [
      {
        id: "lot-new",
        acquisitionDate: "2025-02-01",
        remainingShareCount: 100,
        remainingCostBasis: 30000,
      },
      {
        id: "lot-old",
        acquisitionDate: "2025-01-01",
        remainingShareCount: 100,
        remainingCostBasis: 10000,
      },
    ],
    saleDate: "2025-03-01",
    soldShareCount: 150,
    proceeds: 30000,
    documentStatus: "attached",
  });

  assert.equal(payload.cost_basis_reduction, 25000);
  assert.equal(payload.gain_or_loss, 5000);
  assert.equal(payload.remaining_share_count, 50);
  assert.equal(payload.remaining_cost_basis, 15000);
  assert.deepEqual(payload.lot_allocations, [
    { lot_id: "lot-old", acquisition_date: "2025-01-01", share_count: 100, cost_basis: 10000 },
    { lot_id: "lot-new", acquisition_date: "2025-02-01", share_count: 50, cost_basis: 15000 },
  ]);
});

test("blocks a legacy position that has no reconstructable lots", () => {
  assert.throws(
    () =>
      validateShareSale({
        positionId: "position-1",
        investmentKey: "portfolio-as",
        investmentName: "Portfolio AS",
        currentShareCount: 100,
        currentCostBasis: 50000,
        acquisitionLots: [],
        saleDate: "2025-08-01",
        soldShareCount: 40,
        proceeds: 30000,
        documentStatus: "attached",
      }),
    (error) => error instanceof ShareSaleValidationError && error.code === "missing_acquisition_lots",
  );
});
