export type ShareAcquisitionLot = {
  id: string;
  acquisitionDate: string;
  remainingShareCount: number;
  remainingCostBasis: number;
};

export type ShareLotAllocation = {
  lotId: string;
  acquisitionDate: string;
  shareCount: number;
  costBasis: number;
};

export type FifoShareSaleAllocation = {
  allocations: ShareLotAllocation[];
  updatedLots: ShareAcquisitionLot[];
  costBasisReduction: number;
  remainingShareCount: number;
  remainingCostBasis: number;
};

export class FifoLotValidationError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "FifoLotValidationError";
    this.code = code;
  }
}

export function allocateFifoShareSale(input: {
  lots: ShareAcquisitionLot[];
  saleDate: string;
  soldShareCount: number;
}): FifoShareSaleAllocation {
  assertIsoDate(input.saleDate, "invalid_sale_date");
  assertSafeWholeNumber(input.soldShareCount, "invalid_sold_share_count", false);
  if (input.lots.length === 0) {
    throw new FifoLotValidationError(
      "Aksjesalget mangler anskaffelsesposter og kan ikke FIFO-beregnes.",
      "missing_acquisition_lots",
    );
  }

  const seenIds = new Set<string>();
  const lots = input.lots
    .map((lot) => {
      const id = lot.id.trim();
      if (!id || seenIds.has(id)) {
        throw new FifoLotValidationError("Anskaffelsesposter må ha unike ID-er.", "invalid_lot_id");
      }
      seenIds.add(id);
      assertIsoDate(lot.acquisitionDate, "invalid_lot_date");
      if (lot.acquisitionDate > input.saleDate) {
        throw new FifoLotValidationError(
          "En anskaffelsespost kan ikke være datert etter salget.",
          "future_acquisition_lot",
        );
      }
      assertSafeWholeNumber(lot.remainingShareCount, "invalid_lot_share_count", true);
      const remainingCostCents = toCents(lot.remainingCostBasis, "invalid_lot_cost_basis");
      if (lot.remainingShareCount === 0 && remainingCostCents !== BigInt(0)) {
        throw new FifoLotValidationError(
          "En tom anskaffelsespost kan ikke ha gjenværende kostpris.",
          "invalid_empty_lot",
        );
      }
      return {
        id,
        acquisitionDate: lot.acquisitionDate,
        remainingShareCount: BigInt(lot.remainingShareCount),
        remainingCostCents,
      };
    })
    .sort((left, right) =>
      left.acquisitionDate === right.acquisitionDate
        ? left.id.localeCompare(right.id)
        : left.acquisitionDate.localeCompare(right.acquisitionDate),
    );

  const availableShares = lots.reduce((total, lot) => total + lot.remainingShareCount, BigInt(0));
  const soldShares = BigInt(input.soldShareCount);
  if (soldShares > availableShares) {
    throw new FifoLotValidationError(
      "Salg kan ikke overstige tilgjengelige aksjer i anskaffelsespostene.",
      "sale_exceeds_lots",
    );
  }

  let sharesToAllocate = soldShares;
  let allocatedCostCents = BigInt(0);
  const allocations: ShareLotAllocation[] = [];
  const updatedLots = lots.map((lot) => {
    if (sharesToAllocate === BigInt(0) || lot.remainingShareCount === BigInt(0)) {
      return serializeLot(lot);
    }

    const allocatedShares = sharesToAllocate < lot.remainingShareCount ? sharesToAllocate : lot.remainingShareCount;
    const allocatedLotCost =
      allocatedShares === lot.remainingShareCount
        ? lot.remainingCostCents
        : divideAndRoundHalfUp(lot.remainingCostCents * allocatedShares, lot.remainingShareCount);
    sharesToAllocate -= allocatedShares;
    allocatedCostCents += allocatedLotCost;
    allocations.push({
      lotId: lot.id,
      acquisitionDate: lot.acquisitionDate,
      shareCount: Number(allocatedShares),
      costBasis: fromCents(allocatedLotCost),
    });
    return serializeLot({
      ...lot,
      remainingShareCount: lot.remainingShareCount - allocatedShares,
      remainingCostCents: lot.remainingCostCents - allocatedLotCost,
    });
  });

  const remainingShareCount = updatedLots.reduce((total, lot) => total + lot.remainingShareCount, 0);
  const remainingCostCents = updatedLots.reduce(
    (total, lot) => total + toCents(lot.remainingCostBasis, "invalid_lot_cost_basis"),
    BigInt(0),
  );
  return {
    allocations,
    updatedLots,
    costBasisReduction: fromCents(allocatedCostCents),
    remainingShareCount,
    remainingCostBasis: fromCents(remainingCostCents),
  };
}

function assertIsoDate(value: string, code: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new FifoLotValidationError("Dato må være YYYY-MM-DD.", code);
  }
  const parsed = new Date(`${value}T00:00:00.000Z`);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new FifoLotValidationError("Dato finnes ikke i kalenderen.", code);
  }
}

function assertSafeWholeNumber(value: number, code: string, allowZero: boolean) {
  if (!Number.isSafeInteger(value) || (allowZero ? value < 0 : value <= 0)) {
    throw new FifoLotValidationError("Antall aksjer må være et gyldig heltall.", code);
  }
}

function toCents(value: number, code: string) {
  if (!Number.isFinite(value) || value < 0) {
    throw new FifoLotValidationError("Kostpris må være et gyldig positivt beløp.", code);
  }
  const cents = Math.round(value * 100);
  if (!Number.isSafeInteger(cents) || Math.abs(value - cents / 100) > 1e-9) {
    throw new FifoLotValidationError("Kostpris kan ha maksimalt to desimaler.", code);
  }
  return BigInt(cents);
}

function divideAndRoundHalfUp(numerator: bigint, denominator: bigint) {
  const quotient = numerator / denominator;
  const remainder = numerator % denominator;
  return remainder * BigInt(2) >= denominator ? quotient + BigInt(1) : quotient;
}

function fromCents(cents: bigint) {
  return Number(cents) / 100;
}

function serializeLot(lot: {
  id: string;
  acquisitionDate: string;
  remainingShareCount: bigint;
  remainingCostCents: bigint;
}): ShareAcquisitionLot {
  return {
    id: lot.id,
    acquisitionDate: lot.acquisitionDate,
    remainingShareCount: Number(lot.remainingShareCount),
    remainingCostBasis: fromCents(lot.remainingCostCents),
  };
}
