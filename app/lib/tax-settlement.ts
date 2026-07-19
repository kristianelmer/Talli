export type TaxSettlementType = "payable" | "payment" | "refund";
export type TaxSettlementDocumentStatus = "attached" | "missing_accepted_warning" | "not_required";

export type TaxSettlementInput = {
  settlementDate: string;
  amount: number;
  settlementType: TaxSettlementType;
  documentStatus: TaxSettlementDocumentStatus;
  bankTransactionId?: string | null;
  documentId?: string | null;
};

export type TaxSettlementPayload = {
  settlement_date: string;
  amount: number;
  settlement_type: TaxSettlementType;
  document_status: TaxSettlementDocumentStatus;
  bank_transaction_id: string | null;
  document_id: string | null;
};

export type AnnualTaxEstimateInput = {
  ledgerEntries: { entry_type: string; lines: unknown[] }[];
  holdingActions: { action_type: string; payload: Record<string, unknown> }[];
};

export class TaxSettlementValidationError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "TaxSettlementValidationError";
    this.code = code;
  }
}

export function estimateAnnualTax(input: AnnualTaxEstimateInput) {
  const adminCosts = input.ledgerEntries
    .filter((entry) => entry.entry_type === "admin_cost")
    .reduce<number>((sum, entry) => sum + taxableCostFromLines(entry.lines), 0);
  const fritaksmetodenAddBack = input.holdingActions
    .filter((action) => action.action_type === "dividend_received")
    .reduce<number>((sum, action) => sum + Number(action.payload.taxable_add_back ?? 0), 0);
  const taxBasis = roundMoney(adminCosts + fritaksmetodenAddBack);
  const estimatedTax = roundMoney(Math.max(0, taxBasis) * 0.22);
  return {
    adminCosts: roundMoney(adminCosts),
    fritaksmetodenAddBack: roundMoney(fritaksmetodenAddBack),
    taxBasis,
    estimatedTax,
    status: estimatedTax > 0 ? "payable" : "zero",
  };
}

export function validateTaxSettlement(input: TaxSettlementInput): TaxSettlementPayload {
  const settlementDate = input.settlementDate.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(settlementDate)) {
    throw new TaxSettlementValidationError("Oppgjørsdato må være YYYY-MM-DD.", "invalid_date");
  }
  if (!Number.isFinite(input.amount) || input.amount <= 0) {
    throw new TaxSettlementValidationError("Skattebeløp må være større enn 0.", "invalid_amount");
  }
  if (!["payable", "payment", "refund"].includes(input.settlementType)) {
    throw new TaxSettlementValidationError("Ugyldig skatteoppgjørstype.", "invalid_settlement_type");
  }
  if (!["attached", "missing_accepted_warning", "not_required"].includes(input.documentStatus)) {
    throw new TaxSettlementValidationError("Ugyldig dokumentstatus.", "invalid_document_status");
  }
  if (input.settlementType === "payable" && input.bankTransactionId) {
    throw new TaxSettlementValidationError("Betalbar skatt-estimat skal ikke knyttes direkte til bank.", "payable_bank_link_blocked");
  }
  return {
    settlement_date: settlementDate,
    amount: roundMoney(input.amount),
    settlement_type: input.settlementType,
    document_status: input.documentStatus,
    bank_transaction_id: input.bankTransactionId || null,
    document_id: input.documentId || null,
  };
}

export function taxSettlementLedgerLines(payload: TaxSettlementPayload) {
  if (payload.settlement_type === "payable") {
    return [
      { account: "8300", description: "Skattekostnad", debit: payload.amount, credit: 0 },
      { account: "2500", description: "Betalbar skatt", debit: 0, credit: payload.amount },
    ];
  }
  if (payload.settlement_type === "refund") {
    return [
      { account: "1920", description: "Skatterefusjon mottatt", debit: payload.amount, credit: 0 },
      { account: "1570", description: "Skatt til gode", debit: 0, credit: payload.amount },
    ];
  }
  return [
    { account: "2500", description: "Betalt skatt", debit: payload.amount, credit: 0 },
    { account: "1920", description: "Bank", debit: 0, credit: payload.amount },
  ];
}

export function expectedBankAmountForTaxSettlement(payload: TaxSettlementPayload) {
  if (payload.settlement_type === "payment") {
    return -payload.amount;
  }
  if (payload.settlement_type === "refund") {
    return payload.amount;
  }
  return null;
}

function taxableCostFromLines(lines: unknown[]) {
  return lines.reduce<number>((sum, line) => {
    if (!isLedgerLine(line) || line.account === "1920") {
      return sum;
    }
    return sum + Number(line.debit ?? 0) - Number(line.credit ?? 0);
  }, 0);
}

function isLedgerLine(line: unknown): line is { account: string; debit?: number; credit?: number } {
  return Boolean(line && typeof line === "object" && "account" in line);
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100;
}
