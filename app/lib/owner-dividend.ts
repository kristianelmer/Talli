export type OwnerDividendDocumentStatus = "attached" | "missing_accepted_warning" | "not_required";

export type OwnerDividendAllocation = {
  shareholderId: string;
  shareholderName: string;
  shareCount: number;
  amount: number;
};

export type OwnerDividendShareholder = {
  shareholderId: string;
  shareholderName: string;
  shareCount: number;
};

export type OwnerDividendInput = {
  decisionDate: string;
  paymentDate: string;
  totalAmount: number;
  distributableEquity: number;
  liquidityAfterPayment: number;
  documentStatus: OwnerDividendDocumentStatus;
  allocations: OwnerDividendAllocation[];
};

export type OwnerDividendActionPayload = {
  decision_date: string;
  payment_date: string;
  total_amount: number;
  distributable_equity: number;
  liquidity_after_payment: number;
  document_status: OwnerDividendDocumentStatus;
  allocations: OwnerDividendAllocation[];
};

export class OwnerDividendValidationError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "OwnerDividendValidationError";
    this.code = code;
  }
}

export function validateOwnerDividend(input: OwnerDividendInput): OwnerDividendActionPayload {
  if (!isIsoDate(input.decisionDate) || !isIsoDate(input.paymentDate)) {
    throw new OwnerDividendValidationError("Dato må være YYYY-MM-DD.", "invalid_date");
  }
  if (input.paymentDate < input.decisionDate) {
    throw new OwnerDividendValidationError(
      "Betalingsdato kan ikke være før beslutningsdato.",
      "payment_before_decision",
    );
  }
  if (!Number.isFinite(input.totalAmount) || input.totalAmount <= 0) {
    throw new OwnerDividendValidationError("Utbyttebeløp må være større enn 0.", "invalid_amount");
  }
  if (!Number.isFinite(input.distributableEquity) || input.distributableEquity < 0) {
    throw new OwnerDividendValidationError("Fri egenkapital må være et gyldig beløp.", "invalid_distributable_equity");
  }
  if (!Number.isFinite(input.liquidityAfterPayment)) {
    throw new OwnerDividendValidationError("Likviditet må være et gyldig beløp.", "invalid_liquidity");
  }
  moneyToCents(input.totalAmount);
  moneyToCents(input.distributableEquity);
  moneyToCents(input.liquidityAfterPayment);
  if (input.totalAmount > input.distributableEquity) {
    throw new OwnerDividendValidationError("Utbytte overstiger fri egenkapital.", "dividend_exceeds_distributable_equity");
  }
  if (input.liquidityAfterPayment < 0) {
    throw new OwnerDividendValidationError("Likviditet etter betaling kan ikke være negativ.", "liquidity_check_failed");
  }
  if (!["attached", "missing_accepted_warning", "not_required"].includes(input.documentStatus)) {
    throw new OwnerDividendValidationError("Ugyldig dokumentstatus.", "invalid_document_status");
  }
  if (input.allocations.length === 0) {
    throw new OwnerDividendValidationError("Minst én aksjonærallokering kreves.", "missing_allocations");
  }
  const allocations = input.allocations.map((allocation) => ({
    shareholderId: allocation.shareholderId.trim(),
    shareholderName: allocation.shareholderName.trim(),
    shareCount: allocation.shareCount,
    amount: moneyToCents(allocation.amount) / 100,
  }));
  if (
    allocations.some(
      (allocation) =>
        !allocation.shareholderId ||
        !allocation.shareholderName ||
        !Number.isFinite(allocation.amount) ||
        allocation.amount <= 0 ||
        !Number.isInteger(allocation.shareCount) ||
        allocation.shareCount <= 0,
    )
  ) {
    throw new OwnerDividendValidationError("Aksjonærallokering er ugyldig.", "invalid_allocation");
  }
  if (new Set(allocations.map((allocation) => allocation.shareholderId)).size !== allocations.length) {
    throw new OwnerDividendValidationError("Aksjonær kan ikke forekomme flere ganger.", "duplicate_shareholder");
  }
  const allocated = roundMoney(allocations.reduce((sum, allocation) => sum + allocation.amount, 0));
  if (allocated !== roundMoney(input.totalAmount)) {
    throw new OwnerDividendValidationError("Aksjonærallokeringer må summere til totalutbytte.", "allocation_mismatch");
  }
  const totalShares = allocations.reduce((sum, allocation) => sum + allocation.shareCount, 0);
  const totalCents = moneyToCents(input.totalAmount);
  if (
    allocations.some(
      (allocation) => moneyToCents(allocation.amount) * totalShares !== totalCents * allocation.shareCount,
    )
  ) {
    throw new OwnerDividendValidationError(
      "Enkelt utbytte må fordeles likt per aksje.",
      "unequal_per_share_allocation",
    );
  }
  return {
    decision_date: input.decisionDate,
    payment_date: input.paymentDate,
    total_amount: roundMoney(input.totalAmount),
    distributable_equity: roundMoney(input.distributableEquity),
    liquidity_after_payment: roundMoney(input.liquidityAfterPayment),
    document_status: input.documentStatus,
    allocations,
  };
}

export function allocateOwnerDividend(
  totalAmount: number,
  shareholders: OwnerDividendShareholder[],
): OwnerDividendAllocation[] {
  if (!Number.isFinite(totalAmount) || totalAmount <= 0) {
    throw new OwnerDividendValidationError("Utbyttebeløp må være større enn 0.", "invalid_amount");
  }
  if (
    shareholders.length === 0 ||
    shareholders.some(
      (shareholder) =>
        !shareholder.shareholderId.trim() ||
        !shareholder.shareholderName.trim() ||
        !Number.isInteger(shareholder.shareCount) ||
        shareholder.shareCount <= 0,
    )
  ) {
    throw new OwnerDividendValidationError("Aksjeeierboken er ugyldig.", "invalid_shareholder_register");
  }
  if (new Set(shareholders.map((shareholder) => shareholder.shareholderId)).size !== shareholders.length) {
    throw new OwnerDividendValidationError("Aksjeeierboken inneholder duplikater.", "duplicate_shareholder");
  }
  const totalCents = moneyToCents(totalAmount);
  const totalShares = shareholders.reduce((sum, shareholder) => sum + shareholder.shareCount, 0);
  if (totalCents % totalShares !== 0) {
    throw new OwnerDividendValidationError(
      "Totalutbyttet kan ikke fordeles likt per aksje med hele øre.",
      "indivisible_per_share_amount",
    );
  }
  const centsPerShare = totalCents / totalShares;
  return shareholders.map((shareholder) => ({
    shareholderId: shareholder.shareholderId.trim(),
    shareholderName: shareholder.shareholderName.trim(),
    shareCount: shareholder.shareCount,
    amount: (shareholder.shareCount * centsPerShare) / 100,
  }));
}

export function ownerDividendLedgerLines(payload: OwnerDividendActionPayload) {
  return [
    { account: "2050", description: "Dividend to shareholders", debit: payload.total_amount, credit: 0 },
    { account: "1920", description: "Dividend paid from bank", debit: 0, credit: payload.total_amount },
  ];
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100;
}

function moneyToCents(value: number) {
  if (!Number.isFinite(value)) {
    throw new OwnerDividendValidationError("Beløpet er ugyldig.", "invalid_amount");
  }
  const cents = Math.round(value * 100);
  if (Math.abs(value * 100 - cents) > 1e-7) {
    throw new OwnerDividendValidationError("Beløp kan ha maksimalt to desimaler.", "invalid_money_precision");
  }
  return cents;
}

function isIsoDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}
