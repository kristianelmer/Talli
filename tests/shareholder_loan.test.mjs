import assert from "node:assert/strict";
import test from "node:test";

import {
  ShareholderLoanValidationError,
  shareholderLoanLedgerLines,
  validateShareholderLoan,
} from "../apps/web/app/lib/shareholder-loan.ts";

test("builds supported shareholder-to-company loan ledger lines", () => {
  const payload = validateShareholderLoan({
    loanDate: "2025-07-01",
    amount: 20000,
    direction: "shareholder_to_company",
    counterpartyName: "Ola Nordmann",
    documentStatus: "attached",
    interestModelled: true,
    relatedPartySecurity: false,
  });

  assert.deepEqual(shareholderLoanLedgerLines(payload), [
    { account: "1920", description: "Loan received from Ola Nordmann", debit: 20000, credit: 0 },
    { account: "2255", description: "Loan payable to Ola Nordmann", debit: 0, credit: 20000 },
  ]);
});

test("builds supported company-to-corporate-shareholder loan ledger lines", () => {
  const payload = validateShareholderLoan({
    loanDate: "2025-07-01",
    amount: 20000,
    direction: "company_to_corporate_shareholder",
    counterpartyName: "Owner Holding AS",
    documentStatus: "attached",
    interestModelled: true,
    relatedPartySecurity: false,
  });

  assert.deepEqual(shareholderLoanLedgerLines(payload), [
    { account: "1370", description: "Loan receivable from Owner Holding AS", debit: 20000, credit: 0 },
    { account: "1920", description: "Loan paid to Owner Holding AS", debit: 0, credit: 20000 },
  ]);
});

test("blocks company-to-personal-shareholder loans with machine-readable reason", () => {
  assert.throws(
    () =>
      validateShareholderLoan({
        loanDate: "2025-07-01",
        amount: 20000,
        direction: "company_to_personal_shareholder",
        counterpartyName: "Ola Nordmann",
        documentStatus: "attached",
        interestModelled: false,
        relatedPartySecurity: false,
      }),
    (error) => error instanceof ShareholderLoanValidationError && error.code === "personal_shareholder_loan_blocked",
  );
});
