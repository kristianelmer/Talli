export type OwnerDividendDocumentStatus = "attached" | "missing_accepted_warning" | "not_required";

export type OwnerDividendAllocation = {
  shareholderId: string;
  shareholderName: string;
  shareCount: number;
  amount: number;
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
  if (!/^\d{4}-\d{2}-\d{2}$/.test(input.decisionDate) || !/^\d{4}-\d{2}-\d{2}$/.test(input.paymentDate)) {
    throw new OwnerDividendValidationError("Dato må være YYYY-MM-DD.", "invalid_date");
  }
  if (!Number.isFinite(input.totalAmount) || input.totalAmount <= 0) {
    throw new OwnerDividendValidationError("Utbyttebeløp må være større enn 0.", "invalid_amount");
  }
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
    shareCount: roundMoney(allocation.shareCount),
    amount: roundMoney(allocation.amount),
  }));
  if (allocations.some((allocation) => !allocation.shareholderId || !allocation.shareholderName || allocation.amount <= 0)) {
    throw new OwnerDividendValidationError("Aksjonærallokering er ugyldig.", "invalid_allocation");
  }
  const allocated = roundMoney(allocations.reduce((sum, allocation) => sum + allocation.amount, 0));
  if (allocated !== roundMoney(input.totalAmount)) {
    throw new OwnerDividendValidationError("Aksjonærallokeringer må summere til totalutbytte.", "allocation_mismatch");
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

export function ownerDividendLedgerLines(payload: OwnerDividendActionPayload) {
  return [
    { account: "2050", description: "Dividend to shareholders", debit: payload.total_amount, credit: 0 },
    { account: "1920", description: "Dividend paid from bank", debit: 0, credit: payload.total_amount },
  ];
}

export function ownerDividendCorporateDocumentRecords(companyId: string, incomeYear: number, actionId: string, createdBy: string) {
  return [
    {
      company_id: companyId,
      income_year: incomeYear,
      document_type: "corporate_document",
      name: "Styreforslag utbytte.txt",
      linked_to: actionId,
      status: "missing_placeholder",
      storage_key: `generated/${companyId}/${incomeYear}/${actionId}/styreforslag-utbytte.txt`,
      created_by: createdBy,
    },
    {
      company_id: companyId,
      income_year: incomeYear,
      document_type: "corporate_document",
      name: "Generalforsamlingsprotokoll utbytte.txt",
      linked_to: actionId,
      status: "missing_placeholder",
      storage_key: `generated/${companyId}/${incomeYear}/${actionId}/generalforsamlingsprotokoll-utbytte.txt`,
      created_by: createdBy,
    },
  ];
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100;
}
