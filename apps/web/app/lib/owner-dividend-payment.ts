const SHA256_PATTERN = /^[0-9a-f]{64}$/;

export class OwnerDividendPaymentError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.name = "OwnerDividendPaymentError";
    this.code = code;
  }
}

type OwnerDividendDecision = {
  id: string;
  company_id: string;
  income_year: number;
  decision_kind: string;
  decision_hash: string;
  canonical_input: { dividend?: { amount_ore?: unknown } | null };
};

type OwnerDividendDocumentSet = {
  id: string;
  decision_id: string;
  decision_hash: string;
};

type OwnerDividendFinalization = {
  id: string;
  decision_id: string;
  finalization_kind: string;
  decision_hash: string;
  accounting_policy_version: string | null;
} | null;

type CorporatePaymentEvent = {
  decision_id: string;
  event_kind: string;
  metadata: Record<string, unknown>;
};

export type OpenOwnerDividendPayable = {
  decisionId: string;
  documentSetId: string;
  finalizationId: string;
  companyId: string;
  incomeYear: number;
  decisionHash: string;
  accountingPolicyVersion: string;
  declaredAmountOre: number;
  paidAmountOre: number;
  remainingAmountOre: number;
  settled: boolean;
};

function paymentError(message: string, code: string): never {
  throw new OwnerDividendPaymentError(message, code);
}

function positiveSafeOre(value: unknown, message: string) {
  if (!Number.isSafeInteger(value) || Number(value) <= 0) {
    paymentError(message, "corporate_documents_invalid_payment_payload");
  }
  return Number(value);
}

export function deriveOpenDividendPayable(input: {
  decision: OwnerDividendDecision;
  documentSet: OwnerDividendDocumentSet;
  finalization: OwnerDividendFinalization;
  events: CorporatePaymentEvent[];
}): OpenOwnerDividendPayable {
  const { decision, documentSet, finalization } = input;
  if (!finalization
    || finalization.finalization_kind !== "owner_dividend_declared"
    || finalization.decision_id !== decision.id
    || finalization.decision_hash !== decision.decision_hash
    || !finalization.accounting_policy_version) {
    paymentError(
      "En sluttført utbyttedeklarasjon med regnskapspolicy kreves før betaling.",
      "corporate_documents_finalized_declaration_required",
    );
  }
  if (decision.decision_kind !== "owner_dividend"
    || !SHA256_PATTERN.test(decision.decision_hash)
    || documentSet.decision_id !== decision.id
    || documentSet.decision_hash !== decision.decision_hash) {
    paymentError("Utbyttebeslutningen eller dokumentsettet er ugyldig.", "corporate_documents_source_hash_mismatch");
  }
  const declaredAmountOre = positiveSafeOre(
    decision.canonical_input.dividend?.amount_ore,
    "Det deklarerte utbyttebeløpet er ugyldig.",
  );
  let paidAmountOre = 0;
  for (const event of input.events) {
    if (event.decision_id !== decision.id || event.event_kind !== "payment_recorded") continue;
    const amountOre = positiveSafeOre(event.metadata.amount_ore, "En tidligere utbyttebetaling er ugyldig.");
    paidAmountOre += amountOre;
    if (!Number.isSafeInteger(paidAmountOre) || paidAmountOre > declaredAmountOre) {
      paymentError(
        "Registrerte utbyttebetalinger overstiger deklarert utbytte.",
        "corporate_documents_payment_exceeds_payable",
      );
    }
  }
  const remainingAmountOre = declaredAmountOre - paidAmountOre;
  return {
    decisionId: decision.id,
    documentSetId: documentSet.id,
    finalizationId: finalization.id,
    companyId: decision.company_id,
    incomeYear: decision.income_year,
    decisionHash: decision.decision_hash,
    accountingPolicyVersion: finalization.accounting_policy_version,
    declaredAmountOre,
    paidAmountOre,
    remainingAmountOre,
    settled: remainingAmountOre === 0,
  };
}

type PaymentBankTransaction = {
  id: string;
  company_id: string;
  income_year: number;
  amount: number;
  currency?: string | null;
  matched_entry_id: string | null;
  matched_action_id: string | null;
};

export function validateOwnerDividendPaymentInput(input: {
  payable: OpenOwnerDividendPayable;
  transaction: PaymentBankTransaction;
}) {
  const { payable, transaction } = input;
  if (transaction.company_id !== payable.companyId || transaction.income_year !== payable.incomeYear) {
    paymentError(
      "Banktransaksjonen tilhører ikke samme selskap og år som utbyttet.",
      "corporate_documents_cross_company_bank_transaction",
    );
  }
  if (transaction.matched_entry_id || transaction.matched_action_id) {
    paymentError(
      "Banktransaksjonen er allerede avstemt.",
      "corporate_documents_bank_transaction_already_matched",
    );
  }
  const rawOre = Math.abs(transaction.amount) * 100;
  const paymentAmountOre = Math.round(rawOre);
  if (!Number.isFinite(transaction.amount)
    || transaction.amount >= 0
    || (transaction.currency !== undefined && transaction.currency !== null && transaction.currency !== "NOK")
    || Math.abs(rawOre - paymentAmountOre) > 1e-7
    || !Number.isSafeInteger(paymentAmountOre)
    || paymentAmountOre <= 0) {
    paymentError(
      "Utbyttebetaling må være en utgående NOK-transaksjon med to desimaler.",
      "corporate_documents_invalid_payment_transaction",
    );
  }
  if (paymentAmountOre > payable.remainingAmountOre) {
    paymentError(
      "Betalingen overstiger gjenstående utbyttegjeld.",
      "corporate_documents_payment_exceeds_payable",
    );
  }
  return {
    bankTransactionId: transaction.id,
    paymentAmountOre,
    remainingAfterPaymentOre: payable.remainingAmountOre - paymentAmountOre,
  };
}
