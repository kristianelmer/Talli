export type ShareholderLoanDirection =
  | "shareholder_to_company"
  | "company_to_corporate_shareholder"
  | "company_to_personal_shareholder";
export type ShareholderLoanDocumentStatus = "attached" | "missing_accepted_warning" | "not_required";

export type ShareholderLoanInput = {
  loanDate: string;
  amount: number;
  direction: ShareholderLoanDirection;
  counterpartyName: string;
  documentStatus: ShareholderLoanDocumentStatus;
  interestModelled: boolean;
  relatedPartySecurity: boolean;
  bankTransactionId?: string | null;
  documentId?: string | null;
};

export type ShareholderLoanActionPayload = {
  loan_date: string;
  amount: number;
  direction: Exclude<ShareholderLoanDirection, "company_to_personal_shareholder">;
  counterparty_name: string;
  document_status: ShareholderLoanDocumentStatus;
  interest_modelled: boolean;
  related_party_security: false;
  bank_transaction_id: string | null;
  document_id: string | null;
};

export class ShareholderLoanValidationError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "ShareholderLoanValidationError";
    this.code = code;
  }
}

export function validateShareholderLoan(input: ShareholderLoanInput): ShareholderLoanActionPayload {
  const loanDate = input.loanDate.trim();
  const counterpartyName = input.counterpartyName.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(loanDate)) {
    throw new ShareholderLoanValidationError("Lånedato må være YYYY-MM-DD.", "invalid_date");
  }
  if (!Number.isFinite(input.amount) || input.amount <= 0) {
    throw new ShareholderLoanValidationError("Lånebeløp må være større enn 0.", "invalid_amount");
  }
  if (!counterpartyName) {
    throw new ShareholderLoanValidationError("Motpart mangler.", "missing_counterparty");
  }
  if (input.direction === "company_to_personal_shareholder") {
    throw new ShareholderLoanValidationError(
      "Lån fra selskap til personlig aksjonær må håndteres av regnskapsfører.",
      "personal_shareholder_loan_blocked",
    );
  }
  if (!["shareholder_to_company", "company_to_corporate_shareholder"].includes(input.direction)) {
    throw new ShareholderLoanValidationError("Ugyldig låneretning.", "invalid_direction");
  }
  if (input.relatedPartySecurity) {
    throw new ShareholderLoanValidationError(
      "Sikkerhet eller garanti mellom nærstående må vurderes av regnskapsfører.",
      "related_party_security_blocked",
    );
  }
  if (!["attached", "missing_accepted_warning", "not_required"].includes(input.documentStatus)) {
    throw new ShareholderLoanValidationError("Ugyldig dokumentstatus.", "invalid_document_status");
  }
  return {
    loan_date: loanDate,
    amount: roundMoney(input.amount),
    direction: input.direction,
    counterparty_name: counterpartyName,
    document_status: input.documentStatus,
    interest_modelled: input.interestModelled,
    related_party_security: false,
    bank_transaction_id: input.bankTransactionId || null,
    document_id: input.documentId || null,
  };
}

export function shareholderLoanLedgerLines(payload: ShareholderLoanActionPayload) {
  if (payload.direction === "shareholder_to_company") {
    return [
      { account: "1920", description: `Loan received from ${payload.counterparty_name}`, debit: payload.amount, credit: 0 },
      { account: "2255", description: `Loan payable to ${payload.counterparty_name}`, debit: 0, credit: payload.amount },
    ];
  }
  return [
    { account: "1370", description: `Loan receivable from ${payload.counterparty_name}`, debit: payload.amount, credit: 0 },
    { account: "1920", description: `Loan paid to ${payload.counterparty_name}`, debit: 0, credit: payload.amount },
  ];
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100;
}
