export const BANK_RULE_VERSION = "2026-07-13.1";

export type BankSuggestionLine = {
  account: string;
  description: string;
  debit: number;
  credit: number;
};

export type BankTransactionSuggestion = {
  ruleId: "bank_fee" | "system_subscription" | "deposit_interest";
  ruleVersion: typeof BANK_RULE_VERSION;
  reason: string;
  lines: BankSuggestionLine[];
};

type BankRule = {
  id: BankTransactionSuggestion["ruleId"];
  direction: "incoming" | "outgoing";
  pattern: RegExp;
  reason: string;
  debitAccount: string;
  debitDescription: string;
  creditAccount: string;
  creditDescription: string;
};

const RULES: readonly BankRule[] = [
  {
    id: "bank_fee",
    direction: "outgoing",
    pattern: /\b(?:arsgebyr|bankgebyr|bank fee|annual fee)\b/u,
    reason: "Teksten beskriver et bankgebyr og beløpet er en utbetaling.",
    debitAccount: "7770",
    debitDescription: "Bankomkostninger",
    creditAccount: "1920",
    creditDescription: "Bank",
  },
  {
    id: "system_subscription",
    direction: "outgoing",
    pattern: /\b(?:systemabonnement|system subscription)\b/u,
    reason: "Teksten beskriver et systemabonnement og beløpet er en utbetaling.",
    debitAccount: "6700",
    debitDescription: "Fremmede tjenester",
    creditAccount: "1920",
    creditDescription: "Bank",
  },
  {
    id: "deposit_interest",
    direction: "incoming",
    pattern: /\b(?:renter|rente|interest)\b/u,
    reason: "Teksten beskriver renteinntekt og beløpet er en innbetaling.",
    debitAccount: "1920",
    debitDescription: "Bank",
    creditAccount: "8050",
    creditDescription: "Annen renteinntekt",
  },
] as const;

export function suggestBankTransaction(input: {
  text: string;
  amount: number;
}): BankTransactionSuggestion | null {
  if (!Number.isFinite(input.amount) || input.amount === 0) {
    return null;
  }

  const text = normalizeRuleText(input.text);
  if (!text) {
    return null;
  }

  // If the transaction names more than one known category, owner judgement is
  // required even when only one category happens to match the amount direction.
  const matchingRules = RULES.filter((rule) => rule.pattern.test(text));
  if (matchingRules.length !== 1) {
    return null;
  }

  const rule = matchingRules[0];
  const direction = input.amount > 0 ? "incoming" : "outgoing";
  if (rule.direction !== direction) {
    return null;
  }

  const amount = roundMoney(Math.abs(input.amount));
  if (amount <= 0) {
    return null;
  }

  return {
    ruleId: rule.id,
    ruleVersion: BANK_RULE_VERSION,
    reason: rule.reason,
    lines: [
      {
        account: rule.debitAccount,
        description: rule.debitDescription,
        debit: amount,
        credit: 0,
      },
      {
        account: rule.creditAccount,
        description: rule.creditDescription,
        debit: 0,
        credit: amount,
      },
    ],
  };
}

function normalizeRuleText(value: string) {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("nb-NO")
    .replace(/\s+/g, " ")
    .trim();
}

function roundMoney(value: number) {
  return Math.round(value * 100) / 100;
}
