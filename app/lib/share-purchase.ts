export type SharePurchaseInvestmentKind = "norwegian_private_company" | "simple_listed_security";
export type SharePurchaseTaxTreatment = "fritaksmetoden" | "outside_fritaksmetoden" | "needs_accountant";
export type SharePurchaseDocumentStatus = "attached" | "missing_accepted_warning" | "not_required";

export type SharePurchaseInput = {
  investmentKey: string;
  investmentName: string;
  investmentKind: SharePurchaseInvestmentKind;
  taxTreatment: SharePurchaseTaxTreatment;
  acquisitionDate: string;
  shareCount: number;
  purchaseAmount: number;
  orgNumber?: string | null;
  bankTransactionId?: string | null;
  documentId?: string | null;
  documentStatus: SharePurchaseDocumentStatus;
};

export type SharePurchaseActionPayload = {
  investment_key: string;
  investment_name: string;
  investment_kind: "norwegian_private_company";
  tax_treatment: "fritaksmetoden";
  acquisition_date: string;
  share_count: number;
  purchase_amount: number;
  org_number: string | null;
  bank_transaction_id: string | null;
  document_id: string | null;
  document_status: SharePurchaseDocumentStatus;
};

export class SharePurchaseValidationError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "SharePurchaseValidationError";
    this.code = code;
  }
}

export function validateSharePurchase(input: SharePurchaseInput): SharePurchaseActionPayload {
  const investmentKey = input.investmentKey.trim();
  const investmentName = input.investmentName.trim();
  const acquisitionDate = input.acquisitionDate.trim();
  const orgNumber = input.orgNumber?.trim() || null;
  if (!investmentKey) {
    throw new SharePurchaseValidationError("Investering-ID mangler.", "missing_investment");
  }
  if (!investmentName) {
    throw new SharePurchaseValidationError("Investeringsselskap mangler.", "missing_investment_name");
  }
  if (input.investmentKind !== "norwegian_private_company") {
    throw new SharePurchaseValidationError("Kun norske private aksjeselskap støttes for første kjøpsflyt.", "unsupported_investment_kind");
  }
  if (input.taxTreatment !== "fritaksmetoden") {
    throw new SharePurchaseValidationError("Aksjekjøpets skattebehandling støttes ikke for eierstyrt filing.", "unsupported_tax_treatment");
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(acquisitionDate)) {
    throw new SharePurchaseValidationError("Kjøpsdato må være YYYY-MM-DD.", "invalid_date");
  }
  if (!Number.isFinite(input.shareCount) || input.shareCount <= 0) {
    throw new SharePurchaseValidationError("Antall aksjer må være større enn 0.", "invalid_share_count");
  }
  if (!Number.isFinite(input.purchaseAmount) || input.purchaseAmount <= 0) {
    throw new SharePurchaseValidationError("Kjøpsbeløp må være større enn 0.", "invalid_purchase_amount");
  }
  if (orgNumber && !/^\d{9}$/.test(orgNumber)) {
    throw new SharePurchaseValidationError("Organisasjonsnummer må ha 9 sifre.", "invalid_org_number");
  }
  if (!["attached", "missing_accepted_warning", "not_required"].includes(input.documentStatus)) {
    throw new SharePurchaseValidationError("Ugyldig dokumentstatus.", "invalid_document_status");
  }
  return {
    investment_key: investmentKey,
    investment_name: investmentName,
    investment_kind: "norwegian_private_company",
    tax_treatment: "fritaksmetoden",
    acquisition_date: acquisitionDate,
    share_count: roundMoney(input.shareCount),
    purchase_amount: roundMoney(input.purchaseAmount),
    org_number: orgNumber,
    bank_transaction_id: input.bankTransactionId || null,
    document_id: input.documentId || null,
    document_status: input.documentStatus,
  };
}

export function sharePurchaseLedgerLines(payload: SharePurchaseActionPayload) {
  return [
    {
      account: "1800",
      description: `Investment in ${payload.investment_name}`,
      debit: payload.purchase_amount,
      credit: 0,
    },
    {
      account: "1920",
      description: "Paid from bank",
      debit: 0,
      credit: payload.purchase_amount,
    },
  ];
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100;
}
