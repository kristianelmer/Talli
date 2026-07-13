import assert from "node:assert/strict";
import test from "node:test";

import { FifoLotValidationError, allocateFifoShareSale } from "../app/lib/share-lots.ts";

const lots = [
  {
    id: "lot-b",
    acquisitionDate: "2025-02-01",
    remainingShareCount: 100,
    remainingCostBasis: 30000,
  },
  {
    id: "lot-a",
    acquisitionDate: "2025-01-01",
    remainingShareCount: 100,
    remainingCostBasis: 10000,
  },
];

test("allocates oldest acquisition lots first regardless of input order", () => {
  const result = allocateFifoShareSale({ lots, saleDate: "2025-03-01", soldShareCount: 150 });

  assert.equal(result.costBasisReduction, 25000);
  assert.equal(result.remainingShareCount, 50);
  assert.equal(result.remainingCostBasis, 15000);
  assert.deepEqual(result.allocations, [
    { lotId: "lot-a", acquisitionDate: "2025-01-01", shareCount: 100, costBasis: 10000 },
    { lotId: "lot-b", acquisitionDate: "2025-02-01", shareCount: 50, costBasis: 15000 },
  ]);
  assert.deepEqual(result.updatedLots, [
    {
      id: "lot-a",
      acquisitionDate: "2025-01-01",
      remainingShareCount: 0,
      remainingCostBasis: 0,
    },
    {
      id: "lot-b",
      acquisitionDate: "2025-02-01",
      remainingShareCount: 50,
      remainingCostBasis: 15000,
    },
  ]);
});

test("uses stable lot id order and preserves cent-exact residual cost", () => {
  const result = allocateFifoShareSale({
    saleDate: "2025-02-01",
    soldShareCount: 2,
    lots: [
      {
        id: "lot-z",
        acquisitionDate: "2025-01-01",
        remainingShareCount: 3,
        remainingCostBasis: 100,
      },
      {
        id: "lot-a",
        acquisitionDate: "2025-01-01",
        remainingShareCount: 1,
        remainingCostBasis: 999,
      },
    ],
  });

  assert.deepEqual(result.allocations, [
    { lotId: "lot-a", acquisitionDate: "2025-01-01", shareCount: 1, costBasis: 999 },
    { lotId: "lot-z", acquisitionDate: "2025-01-01", shareCount: 1, costBasis: 33.33 },
  ]);
  assert.equal(result.costBasisReduction, 1032.33);
  assert.equal(result.remainingCostBasis, 66.67);
});

test("rejects missing history, oversales, invalid lots, and future acquisitions", () => {
  assert.throws(
    () => allocateFifoShareSale({ lots: [], saleDate: "2025-03-01", soldShareCount: 1 }),
    (error) => error instanceof FifoLotValidationError && error.code === "missing_acquisition_lots",
  );
  assert.throws(
    () => allocateFifoShareSale({ lots, saleDate: "2025-03-01", soldShareCount: 201 }),
    (error) => error instanceof FifoLotValidationError && error.code === "sale_exceeds_lots",
  );
  assert.throws(
    () =>
      allocateFifoShareSale({
        lots: [{ ...lots[0], remainingShareCount: 1.5 }],
        saleDate: "2025-03-01",
        soldShareCount: 1,
      }),
    (error) => error instanceof FifoLotValidationError && error.code === "invalid_lot_share_count",
  );
  assert.throws(
    () => allocateFifoShareSale({ lots, saleDate: "2025-01-15", soldShareCount: 1 }),
    (error) => error instanceof FifoLotValidationError && error.code === "future_acquisition_lot",
  );
});
