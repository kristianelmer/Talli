import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const actionsSource = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const workspaceSource = readFileSync(new URL("../apps/web/app/(owner)/workspace/page.tsx", import.meta.url), "utf8");
const readinessTransportSource = readFileSync(
  new URL("../apps/web/features/corporate-governance/transport.ts", import.meta.url),
  "utf8",
);
const migrationSource = readFileSync(
  new URL("../supabase/migrations/0004_corporate_document_artifacts.sql", import.meta.url),
  "utf8",
);

test("server delegates policy-bound accounting atomically to governance", () => {
  const start = actionsSource.indexOf("export async function recordOwnerDividendPayment");
  assert.notEqual(start, -1);
  const end = actionsSource.indexOf("\nexport async function ", start + 1);
  const action = actionsSource.slice(start, end < 0 ? undefined : end);
  assert.match(action, /recordOwnerDividendPaymentThroughApi/);
  assert.match(action, /requiredFormUuid\(formData, "operationId"\)/);
  assert.doesNotMatch(action, /\.rpc\("record_owner_dividend_payment"/);
  assert.doesNotMatch(action, /validateOwnerDividendPaymentInput/);
  assert.doesNotMatch(action, /postLedgerOwnerDividendPayment/);
  assert.match(action, /verifyCurrentAnnualSource:\s*false/);
  assert.match(
    actionsSource,
    /input\.verifyCurrentAnnualSource !== false\s*&&\s*readiness\.currentSourceMatches === false/,
  );
  assert.doesNotMatch(action, /dividend_payable_account|bank_account|account:\s*["'](?:1920|2920)["']/);
  assert.match(action, /corporateGovernanceOutcomeMayBeUnknown\(error\)/);
  assert.match(action, /corporateGovernanceActionErrorMessage\(error\)/);

  assert.match(migrationSource, /dividend_payable_account[\s\S]*debit[\s\S]*bank_account[\s\S]*credit/);
  assert.match(migrationSource, /corporate_documents_payment_exceeds_payable/);
  assert.match(migrationSource, /corporate_documents_idempotency_conflict/);
});

test("workspace presents only eligible transactions for each finalized open payable", () => {
  assert.match(readinessTransportSource, /corporateGovernanceReadDecisionReadiness/);
  assert.match(workspaceSource, /corporateDecisionReadiness/);
  assert.doesNotMatch(workspaceSource, /deriveOpenDividendPayable|validateOwnerDividendPaymentInput/);
  assert.match(workspaceSource, /recordOwnerDividendPayment/);
  assert.match(workspaceSource, /remainingAmountOre/);
  assert.match(workspaceSource, /matched_entry_id/);
  assert.match(workspaceSource, /matched_action_id/);
  assert.match(workspaceSource, /bankTransactionId/);
  assert.match(workspaceSource, /decisionHash/);
});
