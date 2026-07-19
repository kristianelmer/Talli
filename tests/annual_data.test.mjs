import assert from "node:assert/strict";
import test from "node:test";

import {
  annualConfirmations,
  buildYearEndInterviewAnswers,
  buildYearEndInterviewInitialAnswers,
  noActivityConfirmed,
} from "../app/lib/annual-data.ts";

test("builds structured year-end answers without free text", () => {
  const answers = buildYearEndInterviewAnswers({
    bank_balance_confirmed: true,
    general_meeting_approved: true,
    authority_to_submit_confirmed: true,
  });

  assert.equal(answers.bank_balance_confirmed, true);
  assert.equal(answers.received_dividends, false);
  assert.equal(noActivityConfirmed(answers), true);
  assert.deepEqual(annualConfirmations(answers), [
    "bank_balance_confirmed",
    "general_meeting_approved",
    "authority_to_submit_confirmed",
    "no_activity_confirmed",
  ]);
});

test("does not mark activity years as no-activity", () => {
  const answers = buildYearEndInterviewAnswers({
    shares_owned_at_year_end: true,
    bank_balance_confirmed: true,
    general_meeting_approved: true,
    authority_to_submit_confirmed: true,
  });

  assert.equal(noActivityConfirmed(answers), false);
  assert.deepEqual(annualConfirmations(answers), [
    "bank_balance_confirmed",
    "general_meeting_approved",
    "authority_to_submit_confirmed",
  ]);
});

test("seeds recorded activity into an unsaved year-end interview", () => {
  const answers = buildYearEndInterviewInitialAnswers(null, {
    shares_owned_at_year_end: true,
    bought_or_sold_shares: true,
    paid_costs: true,
  });

  assert.equal(answers.shares_owned_at_year_end, true);
  assert.equal(answers.bought_or_sold_shares, true);
  assert.equal(answers.paid_costs, true);
  assert.equal(noActivityConfirmed(answers), false);
});

test("recorded activity cannot be hidden by a stale saved false answer", () => {
  const answers = buildYearEndInterviewInitialAnswers(
    {
      bought_or_sold_shares: false,
      bank_balance_confirmed: true,
    },
    { bought_or_sold_shares: true },
  );

  assert.equal(answers.bought_or_sold_shares, true);
  assert.equal(answers.bank_balance_confirmed, true);
});

test("keeps user confirmations independent from registered activity", () => {
  const answers = buildYearEndInterviewInitialAnswers(
    { received_dividends: true },
    { paid_costs: true },
  );

  assert.equal(answers.received_dividends, true);
  assert.equal(answers.paid_costs, true);
  assert.equal(answers.bank_balance_confirmed, false);
  assert.equal(answers.has_unpaid_items, false);
  assert.equal(answers.general_meeting_approved, false);
  assert.equal(answers.authority_to_submit_confirmed, false);
});
