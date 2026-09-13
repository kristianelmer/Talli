export type AnnualTaxEstimateInput = {
  ledgerEntries: { entry_type: string; lines: unknown[] }[];
  holdingActions: { action_type: string; payload: Record<string, unknown> }[];
};

export function estimateAnnualTax(input: AnnualTaxEstimateInput) {
  const adminCosts = input.ledgerEntries
    .filter((entry) => entry.entry_type === "admin_cost")
    .reduce<number>((sum, entry) => sum + taxableCostFromLines(entry.lines), 0);
  const interestIncome = ledgerAccountNetCredit(input.ledgerEntries, "8050");
  const fritaksmetodenAddBack = input.holdingActions
    .filter((action) => [
      "dividend_received",
      "fund_distribution_received",
    ].includes(action.action_type))
    .reduce<number>((sum, action) => sum + Number(action.payload.taxable_add_back ?? 0), 0);
  const taxableShareSaleGain = input.holdingActions
    .filter((action) => action.action_type === "share_sale")
    .reduce<number>(
      (sum, action) => sum + Number(action.payload.taxable_gain ?? 0),
      0,
    );
  const deductibleShareSaleLoss = input.holdingActions
    .filter((action) => action.action_type === "share_sale")
    .reduce<number>(
      (sum, action) => sum + Number(action.payload.deductible_loss ?? 0),
      0,
    );
  const taxBasis = roundMoney(
    interestIncome
      + fritaksmetodenAddBack
      + taxableShareSaleGain
      - deductibleShareSaleLoss
      - adminCosts,
  );
  const estimatedTax = roundMoney(Math.max(0, taxBasis) * 0.22);
  return {
    adminCosts: roundMoney(adminCosts),
    interestIncome: roundMoney(interestIncome),
    fritaksmetodenAddBack: roundMoney(fritaksmetodenAddBack),
    taxableShareSaleGain: roundMoney(taxableShareSaleGain),
    deductibleShareSaleLoss: roundMoney(deductibleShareSaleLoss),
    taxBasis,
    estimatedTax,
    status: estimatedTax > 0 ? "payable" : "zero",
  };
}

function taxableCostFromLines(lines: unknown[]) {
  return lines.reduce<number>((sum, line) => {
    if (!isLedgerLine(line) || line.account === "1920") {
      return sum;
    }
    return sum + Number(line.debit ?? 0) - Number(line.credit ?? 0);
  }, 0);
}

function ledgerAccountNetCredit(
  entries: AnnualTaxEstimateInput["ledgerEntries"],
  account: string,
) {
  return roundMoney(entries.flatMap((entry) => entry.lines).reduce<number>(
    (sum, line) => {
      if (!isLedgerLine(line) || line.account !== account) return sum;
      return sum + Number(line.credit ?? 0) - Number(line.debit ?? 0);
    },
    0,
  ));
}

function isLedgerLine(line: unknown): line is { account: string; debit?: number; credit?: number } {
  return Boolean(line && typeof line === "object" && "account" in line);
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100;
}
