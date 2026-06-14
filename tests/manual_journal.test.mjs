import assert from "node:assert/strict";
import test from "node:test";

import { manualJournalRiskFlags, validateManualJournal } from "../app/lib/manual-journal.ts";

const balancedLines = [
  { account: "7795", description: "Manual cost", debit: 100, credit: 0 },
  { account: "1920", description: "Bank", debit: 0, credit: 100 },
];

test("accepts balanced manual journal", () => {
  const result = validateManualJournal({ lines: balancedLines, warningAccepted: false });

  assert.equal(result.lines.length, 2);
  assert.deepEqual(result.riskFlags, []);
});

test("blocks unbalanced manual journal", () => {
  assert.throws(
    () =>
      validateManualJournal({
        lines: [
          { account: "7795", description: "Manual cost", debit: 100, credit: 0 },
          { account: "1920", description: "Bank", debit: 0, credit: 99 },
        ],
        warningAccepted: false,
      }),
    /balansere/,
  );
});

test("requires warning acceptance for filing-sensitive accounts", () => {
  const sensitiveLines = [
    { account: "1800", description: "Investment", debit: 100, credit: 0 },
    { account: "1920", description: "Bank", debit: 0, credit: 100 },
  ];

  assert.deepEqual(manualJournalRiskFlags(sensitiveLines).map((flag) => flag.account), ["1800"]);
  assert.throws(() => validateManualJournal({ lines: sensitiveLines, warningAccepted: false }), /warning-aksept/);
  assert.equal(validateManualJournal({ lines: sensitiveLines, warningAccepted: true }).riskFlags[0].account, "1800");
});
