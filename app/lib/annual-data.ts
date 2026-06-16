export type YearEndInterviewAnswers = {
  shares_owned_at_year_end: boolean;
  bought_or_sold_shares: boolean;
  received_dividends: boolean;
  declared_owner_dividends: boolean;
  shareholder_loans: boolean;
  paid_costs: boolean;
  bank_balance_confirmed: boolean;
  has_unpaid_items: boolean;
  general_meeting_approved: boolean;
  authority_to_submit_confirmed: boolean;
};

export const yearEndAnswerKeys: (keyof YearEndInterviewAnswers)[] = [
  "shares_owned_at_year_end",
  "bought_or_sold_shares",
  "received_dividends",
  "declared_owner_dividends",
  "shareholder_loans",
  "paid_costs",
  "bank_balance_confirmed",
  "has_unpaid_items",
  "general_meeting_approved",
  "authority_to_submit_confirmed",
];

export function buildYearEndInterviewAnswers(input: Partial<Record<keyof YearEndInterviewAnswers, boolean>>) {
  return Object.fromEntries(yearEndAnswerKeys.map((key) => [key, Boolean(input[key])])) as YearEndInterviewAnswers;
}

export function noActivityConfirmed(answers: YearEndInterviewAnswers) {
  return (
    !answers.shares_owned_at_year_end &&
    !answers.bought_or_sold_shares &&
    !answers.received_dividends &&
    !answers.declared_owner_dividends &&
    !answers.shareholder_loans &&
    !answers.paid_costs &&
    !answers.has_unpaid_items &&
    answers.bank_balance_confirmed &&
    answers.general_meeting_approved &&
    answers.authority_to_submit_confirmed
  );
}

export function annualConfirmations(answers: YearEndInterviewAnswers) {
  const confirmations = [];
  if (answers.bank_balance_confirmed) confirmations.push("bank_balance_confirmed");
  if (answers.general_meeting_approved) confirmations.push("general_meeting_approved");
  if (answers.authority_to_submit_confirmed) confirmations.push("authority_to_submit_confirmed");
  if (noActivityConfirmed(answers)) confirmations.push("no_activity_confirmed");
  return confirmations;
}
