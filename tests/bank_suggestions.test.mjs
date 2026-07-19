import assert from "node:assert/strict";
import test from "node:test";

import {
  BANK_RULE_VERSION,
  suggestBankTransaction,
} from "../app/lib/bank-suggestions.ts";

test("suggests the required bank fee and annual fee posting", () => {
  for (const text of ["Årsgebyr bedriftskonto", "BANKGEBYR JULI"]) {
    const suggestion = suggestBankTransaction({ text, amount: -50 });

    assert.equal(suggestion?.ruleId, "bank_fee");
    assert.equal(suggestion?.ruleVersion, BANK_RULE_VERSION);
    assert.deepEqual(suggestion?.lines, [
      { account: "7770", description: "Bankomkostninger", debit: 50, credit: 0 },
      { account: "1920", description: "Bank", debit: 0, credit: 50 },
    ]);
  }
});

test("suggests system subscription and incoming interest postings", () => {
  assert.deepEqual(suggestBankTransaction({ text: "Systemabonnement Talli", amount: -990 })?.lines, [
    { account: "6700", description: "Fremmede tjenester", debit: 990, credit: 0 },
    { account: "1920", description: "Bank", debit: 0, credit: 990 },
  ]);
  assert.deepEqual(suggestBankTransaction({ text: "Renter innskudd", amount: 125.5 })?.lines, [
    { account: "1920", description: "Bank", debit: 125.5, credit: 0 },
    { account: "8050", description: "Annen renteinntekt", debit: 0, credit: 125.5 },
  ]);
});

test("does not suggest on wrong direction, ambiguous text, or unknown transactions", () => {
  assert.equal(suggestBankTransaction({ text: "Renter lån", amount: -125 }), null);
  assert.equal(suggestBankTransaction({ text: "Bankgebyr og renter", amount: 125 }), null);
  assert.equal(suggestBankTransaction({ text: "Overføring til eier", amount: -1000 }), null);
  assert.equal(suggestBankTransaction({ text: "Restaurant", amount: 125 }), null);
});
