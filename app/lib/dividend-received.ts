export type DividendReceivedTaxTreatment = "fritaksmetoden" | "outside_fritaksmetoden" | "needs_accountant";
export type DividendReceivedDocumentStatus = "attached" | "missing_accepted_warning" | "not_required";

export type DividendReceivedInput = {
  payingCompanyName: string;
  declaredDate: string;
  paidDate: string;
  grossAmount: number;
  linkedInvestmentId: string;
  taxTreatment: DividendReceivedTaxTreatment;
  bankTransactionId?: string | null;
  documentId?: string | null;
  documentStatus: DividendReceivedDocumentStatus;
};

export type DividendReceivedActionPayload = {
  paying_company_name: string;
  declared_date: string;
  paid_date: string;
  gross_amount: number;
  linked_investment_id: string;
  tax_treatment: "fritaksmetoden";
  taxable_add_back: number;
  bank_transaction_id: string | null;
  document_id: string | null;
  document_status: DividendReceivedDocumentStatus;
};

export class DividendReceivedValidationError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "DividendReceivedValidationError";
    this.code = code;
  }
}

export function validateDividendReceived(input: DividendReceivedInput): DividendReceivedActionPayload {
  const payingCompanyName = input.payingCompanyName.trim();
  const declaredDate = input.declaredDate.trim();
  const paidDate = input.paidDate.trim();
  const linkedInvestmentId = input.linkedInvestmentId.trim();
  if (!payingCompanyName) {
    throw new DividendReceivedValidationError("Utbetalende selskap mangler.", "missing_payer");
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(declaredDate) || !/^\d{4}-\d{2}-\d{2}$/.test(paidDate)) {
    throw new DividendReceivedValidationError("Dato må være YYYY-MM-DD.", "invalid_date");
  }
  if (!Number.isFinite(input.grossAmount) || input.grossAmount <= 0) {
    throw new DividendReceivedValidationError("Brutto utbytte må være større enn 0.", "invalid_amount");
  }
  if (!linkedInvestmentId) {
    throw new DividendReceivedValidationError("Investeringstilknytning mangler.", "missing_investment");
  }
  if (input.taxTreatment !== "fritaksmetoden") {
    throw new DividendReceivedValidationError(
      "Utbyttets skattebehandling støttes ikke for eierstyrt filing.",
      "unsupported_tax_treatment",
    );
  }
  if (!["attached", "missing_accepted_warning", "not_required"].includes(input.documentStatus)) {
    throw new DividendReceivedValidationError("Ugyldig dokumentstatus.", "invalid_document_status");
  }
  return {
    paying_company_name: payingCompanyName,
    declared_date: declaredDate,
    paid_date: paidDate,
    gross_amount: roundMoney(input.grossAmount),
    linked_investment_id: linkedInvestmentId,
    tax_treatment: "fritaksmetoden",
    taxable_add_back: roundMoney(input.grossAmount * 0.03),
    bank_transaction_id: input.bankTransactionId || null,
    document_id: input.documentId || null,
    document_status: input.documentStatus,
  };
}

export function dividendReceivedLedgerLines(payload: DividendReceivedActionPayload) {
  return [
    {
      account: "1920",
      description: "Dividend received in bank",
      debit: payload.gross_amount,
      credit: 0,
    },
    {
      account: "8070",
      description: `Dividend from ${payload.paying_company_name}`,
      debit: 0,
      credit: payload.gross_amount,
    },
  ];
}

export function summarizeDividendReceivedAnnualImpact(
  actions: { action_type: string; payload: { gross_amount?: number; taxable_add_back?: number } }[],
) {
  return actions
    .filter((action) => action.action_type === "dividend_received")
    .reduce(
      (summary, action) => ({
        dividendIncome: roundMoney(summary.dividendIncome + Number(action.payload.gross_amount ?? 0)),
        fritaksmetodenAddBack: roundMoney(summary.fritaksmetodenAddBack + Number(action.payload.taxable_add_back ?? 0)),
      }),
      { dividendIncome: 0, fritaksmetodenAddBack: 0 },
    );
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100;
}
