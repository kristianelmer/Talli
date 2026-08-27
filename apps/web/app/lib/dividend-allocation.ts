export type DividendAllocationInput = {
  shareholderId: string;
  shareCount: number;
  order: number;
};

export class CorporateDecisionFactsError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "CorporateDecisionFactsError";
    this.code = code;
  }
}

function normalizedText(value: string) {
  return value.normalize("NFC").trim().replace(/\s+/g, " ");
}

function assertSafeInteger(value: number, field: string, minimum = 0) {
  if (!Number.isSafeInteger(value) || value < minimum) {
    throw new CorporateDecisionFactsError(
      `${field} må være et gyldig heltall i øre eller antall.`,
      "corporate_documents_invalid_persisted_facts",
    );
  }
}

export function allocateDividendOreProportionally(
  amountOre: number,
  shareholders: DividendAllocationInput[],
): Array<{ shareholderId: string; amountOre: number }> {
  assertSafeInteger(amountOre, "Utbyttebeløp", 1);
  const sorted = shareholders.map((shareholder) => ({
    ...shareholder,
    shareholderId: normalizedText(shareholder.shareholderId),
  })).sort((left, right) => left.order - right.order
    || left.shareholderId.localeCompare(right.shareholderId, "en"));
  if (sorted.length === 0
    || new Set(sorted.map(({ shareholderId }) => shareholderId)).size !== sorted.length) {
    throw new CorporateDecisionFactsError(
      "Utbyttefordelingen krever unike aksjonærer.",
      "corporate_documents_invalid_persisted_facts",
    );
  }
  for (const shareholder of sorted) {
    assertSafeInteger(shareholder.shareCount, "Aksjeantall", 1);
    assertSafeInteger(shareholder.order, "Aksjonærrekkefølge", 0);
  }
  const totalShares = sorted.reduce((sum, shareholder) => sum + shareholder.shareCount, 0);
  assertSafeInteger(totalShares, "Totalt aksjeantall", 1);
  const totalSharesBigInt = BigInt(totalShares);
  const allocations = sorted.map((shareholder, index) => {
    const numerator = BigInt(amountOre) * BigInt(shareholder.shareCount);
    return {
      shareholderId: shareholder.shareholderId,
      amountOre: Number(numerator / totalSharesBigInt),
      remainder: numerator % totalSharesBigInt,
      index,
    };
  });
  const allocated = allocations.reduce((sum, allocation) => sum + allocation.amountOre, 0);
  const remainderOre = amountOre - allocated;
  const remainderOrder = [...allocations].sort((left, right) => {
    if (left.remainder !== right.remainder) return left.remainder > right.remainder ? -1 : 1;
    return left.index - right.index;
  });
  for (let index = 0; index < remainderOre; index += 1) {
    remainderOrder[index].amountOre += 1;
  }
  return allocations.map(({ shareholderId, amountOre: allocatedOre }) => ({
    shareholderId,
    amountOre: allocatedOre,
  }));
}
