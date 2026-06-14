import assert from "node:assert/strict";
import test from "node:test";

import {
  assertBankTransactionMatchesCost,
  buildAdminCostLedgerLines,
  parseBankCsv,
} from "../app/lib/bank.ts";

test("parses bank CSV with stable duplicate hash", () => {
  const csv = "date,text,amount,balance\n2025-01-02,Opening,30000,30000\n2025-01-03,Bank fee,-50,29950\n";
  const first = parseBankCsv(csv);
  const retry = parseBankCsv(csv);

  assert.equal(first.length, 2);
  assert.equal(first[1].transactionDate, "2025-01-03");
  assert.equal(first[1].amount, -50);
  assert.equal(first[1].sourceHash, retry[1].sourceHash);
});

test("builds deterministic admin cost posting lines", () => {
  const lines = buildAdminCostLedgerLines({ category: "bank_fee", payee: "Bank", amount: 50 });

  assert.deepEqual(lines, [
    { account: "7770", description: "Admin cost: Bank", debit: 50, credit: 0 },
    { account: "1920", description: "Paid from bank", debit: 0, credit: 50 },
  ]);
});

test("requires selected bank transaction to match cost amount", () => {
  assert.doesNotThrow(() => assertBankTransactionMatchesCost(-50, 50));
  assert.throws(() => assertBankTransactionMatchesCost(-49, 50), /samme beløp/);
});
