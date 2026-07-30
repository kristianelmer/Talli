import assert from "node:assert/strict";
import test from "node:test";

import { openingBalanceLedgerLines, validateOpeningBalanceInput } from "../apps/web/app/lib/opening-balance.ts";

const validInput = {
  bankBalance: 30000,
  shareCapital: 30000,
  shareCount: 100,
  nominalValue: 300,
  shareholders: [
    {
      name: "Ola Nordmann",
      shareholderKind: "norwegian_person",
      nationalId: "01017012345",
      shareCount: 100,
    },
  ],
};

test("validates opening balance and emits deterministic ledger lines", () => {
  assert.doesNotThrow(() => validateOpeningBalanceInput(validInput));
  assert.deepEqual(openingBalanceLedgerLines(validInput), [
    { account: "1920", description: "Bankinnskudd", debit: 30000, credit: 0 },
    { account: "2000", description: "Aksjekapital", debit: 0, credit: 30000 },
    { account: "2050", description: "Annen egenkapital", debit: 0, credit: 0 },
  ]);
});

test("blocks unreconciled shareholder share totals", () => {
  assert.throws(
    () =>
      validateOpeningBalanceInput({
        ...validInput,
        shareholders: [{ ...validInput.shareholders[0], shareCount: 90 }],
      }),
    /Sum aksjer/,
  );
});

test("blocks share capital mismatch against nominal value", () => {
  assert.throws(() => validateOpeningBalanceInput({ ...validInput, shareCapital: 29999 }), /Aksjekapital/);
});

test("blocks missing Norwegian shareholder identifiers", () => {
  assert.throws(
    () =>
      validateOpeningBalanceInput({
        ...validInput,
        shareholders: [{ name: "Demo AS", shareholderKind: "norwegian_company", shareCount: 100 }],
      }),
    /organisasjonsnummer/,
  );
});
