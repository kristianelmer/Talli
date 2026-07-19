import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  OwnerDividendPaymentError,
  deriveOpenDividendPayable,
  validateOwnerDividendPaymentInput,
} from "../app/lib/owner-dividend-payment.ts";

const actionsSource = readFileSync(new URL("../app/actions.ts", import.meta.url), "utf8");
const workspaceSource = readFileSync(new URL("../app/(owner)/workspace/page.tsx", import.meta.url), "utf8");
const migrationSource = readFileSync(
  new URL("../supabase/migrations/0004_corporate_document_artifacts.sql", import.meta.url),
  "utf8",
);

const payableInput = {
  decision: {
    id: "11111111-1111-4111-8111-111111111111",
    company_id: "22222222-2222-4222-8222-222222222222",
    income_year: 2025,
    decision_kind: "owner_dividend",
    decision_hash: "a".repeat(64),
    canonical_input: { dividend: { amount_ore: 100_000 } },
  },
  documentSet: {
    id: "33333333-3333-4333-8333-333333333333",
    decision_id: "11111111-1111-4111-8111-111111111111",
    decision_hash: "a".repeat(64),
  },
  finalization: {
    id: "44444444-4444-4444-8444-444444444444",
    decision_id: "11111111-1111-4111-8111-111111111111",
    finalization_kind: "owner_dividend_declared",
    decision_hash: "a".repeat(64),
    accounting_policy_version: "no-holding-v1",
  },
  events: [
    { decision_id: "11111111-1111-4111-8111-111111111111", event_kind: "payment_recorded", metadata: { amount_ore: 25_000 } },
    { decision_id: "11111111-1111-4111-8111-111111111111", event_kind: "facts_approved", metadata: {} },
  ],
};

test("open payable is derived only from a finalized declaration and immutable payment events", () => {
  const payable = deriveOpenDividendPayable(payableInput);
  assert.equal(payable.declaredAmountOre, 100_000);
  assert.equal(payable.paidAmountOre, 25_000);
  assert.equal(payable.remainingAmountOre, 75_000);
  assert.equal(payable.settled, false);
  assert.equal(payable.accountingPolicyVersion, "no-holding-v1");

  assert.throws(
    () => deriveOpenDividendPayable({ ...payableInput, finalization: null }),
    (error) => error instanceof OwnerDividendPaymentError
      && error.code === "corporate_documents_finalized_declaration_required",
  );
  assert.throws(
    () => deriveOpenDividendPayable({
      ...payableInput,
      events: [{
        decision_id: payableInput.decision.id,
        event_kind: "payment_recorded",
        metadata: { amount_ore: 100_001 },
      }],
    }),
    /overstiger/i,
  );
});

test("payment validation accepts one eligible outgoing NOK transaction within the open payable", () => {
  const payable = deriveOpenDividendPayable(payableInput);
  const transaction = {
    id: "55555555-5555-4555-8555-555555555555",
    company_id: payable.companyId,
    income_year: payable.incomeYear,
    amount: -750,
    currency: "NOK",
    matched_entry_id: null,
    matched_action_id: null,
  };
  assert.deepEqual(validateOwnerDividendPaymentInput({ payable, transaction }), {
    bankTransactionId: transaction.id,
    paymentAmountOre: 75_000,
    remainingAfterPaymentOre: 0,
  });

  for (const [patch, code] of [
    [{ company_id: "99999999-9999-4999-8999-999999999999" }, "corporate_documents_cross_company_bank_transaction"],
    [{ income_year: 2024 }, "corporate_documents_cross_company_bank_transaction"],
    [{ currency: "EUR" }, "corporate_documents_invalid_payment_transaction"],
    [{ amount: 1 }, "corporate_documents_invalid_payment_transaction"],
    [{ matched_entry_id: "already" }, "corporate_documents_bank_transaction_already_matched"],
    [{ amount: -750.01 }, "corporate_documents_payment_exceeds_payable"],
  ]) {
    assert.throws(
      () => validateOwnerDividendPaymentInput({ payable, transaction: { ...transaction, ...patch } }),
      (error) => error instanceof OwnerDividendPaymentError && error.code === code,
    );
  }
});

test("server delegates policy-bound accounting atomically to the payment RPC", () => {
  const start = actionsSource.indexOf("export async function recordOwnerDividendPayment");
  assert.notEqual(start, -1);
  const end = actionsSource.indexOf("\nexport async function ", start + 1);
  const action = actionsSource.slice(start, end < 0 ? undefined : end);
  assert.match(action, /record_owner_dividend_payment/);
  assert.match(action, /record_owner_dividend_payment|finalize_corporate_decision/);
  assert.match(action, /validateOwnerDividendPaymentInput/);
  assert.match(action, /verifyCurrentAnnualSource:\s*false/);
  assert.match(actionsSource, /if \(input\.verifyCurrentAnnualSource !== false\)/);
  assert.doesNotMatch(action, /dividend_payable_account|bank_account|account:\s*["'](?:1920|2920)["']/);

  assert.match(migrationSource, /dividend_payable_account[\s\S]*debit[\s\S]*bank_account[\s\S]*credit/);
  assert.match(migrationSource, /corporate_documents_payment_exceeds_payable/);
  assert.match(migrationSource, /corporate_documents_idempotency_conflict/);
});

test("workspace presents only eligible transactions for each finalized open payable", () => {
  assert.match(workspaceSource, /deriveOpenDividendPayable/);
  assert.match(workspaceSource, /validateOwnerDividendPaymentInput/);
  assert.match(workspaceSource, /recordOwnerDividendPayment/);
  assert.match(workspaceSource, /remainingAmountOre/);
  assert.match(workspaceSource, /matched_entry_id/);
  assert.match(workspaceSource, /matched_action_id/);
  assert.match(workspaceSource, /bankTransactionId/);
  assert.match(workspaceSource, /decisionHash/);
});
