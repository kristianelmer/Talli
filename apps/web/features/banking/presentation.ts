import {
  TalliApiError,
  type AcceptedBankSuggestionWire,
  type BankSuggestionKind,
  type BankSuggestionWire,
  type BankTransactionWire,
} from "@talli/talli-api-client";

export type BankingSuggestionPresentation = {
  kind: BankSuggestionKind;
  reason: string;
  ruleVersion: string;
};

export type BankTransactionPresentation = {
  id: string;
  company_id: string;
  income_year: number;
  transaction_date: string;
  text: string;
  amount: number;
  balance: number | null;
  source_hash: string;
  matched_entry_id: string | null;
  matched_action_id: string | null;
  accepted_warning: boolean;
  suggestion: BankingSuggestionPresentation | null;
  created_at: string;
};

export type BankSuggestionAcceptancePresentation = {
  id: string;
  bank_transaction_id: string;
  ledger_entry_id: string;
  rule_id: "bank_fee" | "system_subscription" | "deposit_interest";
  rule_version: string;
  reason: string;
  accepted_by: string;
  accepted_at: string;
  replayed?: boolean;
};

const RULE_IDS: Record<BankSuggestionKind, BankSuggestionAcceptancePresentation["rule_id"]> = {
  BANK_FEE: "bank_fee",
  SYSTEM_SUBSCRIPTION: "system_subscription",
  DEPOSIT_INTEREST: "deposit_interest",
};

function suggestion(value: BankSuggestionWire): BankingSuggestionPresentation {
  if (!(value.kind in RULE_IDS)) throw new Error("Banking suggestion kind is invalid.");
  return {
    kind: value.kind as BankSuggestionKind,
    reason: value.reason,
    ruleVersion: value.ruleVersion,
  };
}

function nok(value: { amount: string; currency: "NOK" }): number {
  const amount = Number(value.amount);
  if (!Number.isFinite(amount)) throw new Error("Banking amount is invalid.");
  return amount;
}

export function presentBankTransactions(
  transactions: readonly BankTransactionWire[],
): BankTransactionPresentation[] {
  return transactions.map((transaction) => ({
    id: transaction.transactionId,
    company_id: transaction.companyId,
    income_year: transaction.incomeYear,
    transaction_date: transaction.transactionDate,
    text: transaction.text,
    amount: nok(transaction.amount),
    balance: transaction.balance === null ? null : nok(transaction.balance),
    source_hash: transaction.sourceHash,
    matched_entry_id: transaction.matchedEntryId,
    matched_action_id: transaction.matchedActionReference,
    accepted_warning: transaction.warningAccepted,
    suggestion: transaction.suggestion === null ? null : suggestion(transaction.suggestion),
    created_at: transaction.createdAt,
  }));
}

export function presentBankSuggestionAcceptances(
  acceptances: readonly AcceptedBankSuggestionWire[],
): BankSuggestionAcceptancePresentation[] {
  return acceptances.map((acceptance) => {
    const presentedSuggestion = suggestion(acceptance.suggestion);
    return {
      id: acceptance.acceptanceId,
      bank_transaction_id: acceptance.bankTransactionId,
      ledger_entry_id: acceptance.accountingEntryId,
      rule_id: RULE_IDS[presentedSuggestion.kind],
      rule_version: presentedSuggestion.ruleVersion,
      reason: presentedSuggestion.reason,
      accepted_by: acceptance.acceptedBy,
      accepted_at: acceptance.acceptedAt,
      replayed: acceptance.replayed,
    };
  });
}

const BANKING_ERROR_MESSAGES: Record<string, string> = {
  AUTHENTICATION_REQUIRED: "Innlogging kreves.",
  BANKING_COMPANY_YEAR_NOT_ADMITTED: "Selskapsåret er ikke godkjent for denne handlingen.",
  BANKING_FORBIDDEN: "Du har ikke tilgang til bankdataene.",
  BANKING_IDEMPOTENCY_IN_PROGRESS: "Forespørselen behandles allerede. Prøv samme forespørsel igjen.",
  BANKING_IDEMPOTENCY_KEY_REUSED: "Forespørsels-ID-en er allerede brukt til et annet innhold.",
  BANKING_STATEMENT_FORMAT_UNSUPPORTED: "Bankfilformatet støttes ikke.",
  BANKING_STATEMENT_INVALID: "Bankfilen kunne ikke leses. Kontroller kolonnene og inntektsåret.",
  BANKING_SUGGESTION_NOT_AVAILABLE: "Forslaget er ikke lenger tilgjengelig. Last siden på nytt.",
  BANKING_SUGGESTION_STALE: "Forslaget er endret eller ikke lenger gyldig. Last siden på nytt.",
  BANKING_TRANSACTION_ALREADY_RECONCILED: "Bankbevegelsen er allerede avstemt.",
  BANKING_TRANSACTION_NOT_FOUND: "Fant ikke bankbevegelsen.",
  REQUEST_VALIDATION_FAILED: "Kontroller feltene og prøv igjen.",
};

export function bankingActionErrorMessage(error: unknown): string {
  if (error instanceof TalliApiError) {
    const code = error.problem?.code;
    return code === undefined
      ? "Banktjenesten svarte ikke som forventet. Prøv igjen."
      : BANKING_ERROR_MESSAGES[code] ?? "Bankhandlingen kunne ikke fullføres. Kontroller opplysningene.";
  }
  return "Forbindelsen til banktjenesten ble brutt. Prøv samme forespørsel igjen.";
}

export function bankingOutcomeMayBeUnknown(error: unknown): boolean {
  return !(error instanceof TalliApiError)
    || error.status >= 500
    || error.problem?.code === "BANKING_IDEMPOTENCY_IN_PROGRESS";
}
