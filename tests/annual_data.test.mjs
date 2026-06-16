import assert from "node:assert/strict";
import test from "node:test";

import { annualConfirmations, buildYearEndInterviewAnswers, noActivityConfirmed } from "../app/lib/annual-data.ts";

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
