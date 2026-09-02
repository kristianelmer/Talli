import assert from "node:assert/strict";
import test from "node:test";

import { TalliApiError } from "@talli/talli-api-client";

import {
  acceptBankSourceFile,
  bankingActionErrorMessage,
  bankingOutcomeMayBeUnknown,
  loadBankTransactions,
  previewBankSourceFile,
  presentBankSuggestionAcceptances,
  presentBankTransactions,
} from "../features/banking/index.ts";

const companyId = "10000000-0000-0000-0000-000000000001";

function transaction(overrides = {}) {
  return {
    amount: { amount: "-125.50", currency: "NOK" },
    balance: { amount: "1000.25", currency: "NOK" },
    companyId,
    createdAt: "2026-08-28T10:00:00Z",
    incomeYear: 2026,
    matchedActionReference: null,
    matchedEntryId: null,
    sourceHash: "a".repeat(64),
    suggestion: {
      kind: "BANK_FEE",
      reason: "Teksten beskriver et bankgebyr og beløpet er en utbetaling.",
      ruleVersion: "2026-07-13.1",
    },
    text: "Bankgebyr",
    transactionDate: "2026-08-01",
    transactionId: "30000000-0000-0000-0000-000000000003",
    warningAccepted: false,
    ...overrides,
  };
}

test("banking transport follows opaque pages through the generated client", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  const calls = [];
  globalThis.fetch = async (url, request) => {
    calls.push({ url: String(url), request });
    const next = String(url).includes("cursor=opaque-next") ? null : "opaque-next";
    return Response.json({
      items: next ? [transaction()] : [],
      page: { hasMore: next !== null, nextCursor: next },
    });
  };
  process.env.TALLI_BACKEND_URL = "https://backend.example";

  try {
    const result = await loadBankTransactions("session-token", [companyId], "bank-list-test");
    assert.equal(result.length, 1);
    assert.equal(calls.length, 2);
    assert.match(calls[1].url, /cursor=opaque-next/u);
    const headers = new Headers(calls[0].request.headers);
    assert.equal(headers.get("Authorization"), "Bearer session-token");
    assert.equal(headers.get("X-Request-ID"), "bank-list-test");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("bank file transport persists a backend preview before explicit acceptance", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  const calls = [];
  globalThis.fetch = async (url, request) => {
    calls.push({ url: String(url), request });
    if (String(url).endsWith("/previews")) {
      return Response.json({
        sourceFileId: "60000000-0000-0000-0000-000000000006",
        documentSha256: "a".repeat(64),
        accountMask: null,
        intervalStart: "2026-01-02",
        intervalEnd: "2026-01-02",
        currency: "NOK",
        openingBalance: null,
        closingBalance: null,
        transactionCount: 1,
        duplicateCount: 0,
        correctionCount: 0,
        ignoredCount: 0,
        replayed: false,
      });
    }
    return Response.json({ importedCount: 1, duplicateCount: 0, replayed: false });
  };
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  try {
    const preview = await previewBankSourceFile("session-token", {
      companyId,
      incomeYear: 2026,
      sourceFileId: "60000000-0000-0000-0000-000000000006",
      accountId: "70000000-0000-0000-0000-000000000007",
      dataFormat: "CSV",
      filename: "statement.csv",
      content: "date,text,amount\n2026-01-02,Annual fee,-89\n",
      columnMapping: {
        bookingDate: "date",
        text: "text",
        amount: "amount",
      },
    }, "banking-preview-route-0001");
    const accepted = await acceptBankSourceFile(
      "session-token",
      preview.sourceFileId,
      { companyId, incomeYear: 2026, documentSha256: preview.documentSha256 },
      "banking-accept-route-0001",
    );
    assert.equal(accepted.importedCount, 1);
    assert.equal(calls.length, 2);
    assert.match(calls[0].url, /source-files\/previews$/u);
    assert.match(calls[1].url, /source-files\/60000000-0000-0000-0000-000000000006\/acceptance$/u);
    assert.equal(JSON.parse(calls[1].request.body).documentSha256, "a".repeat(64));
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("banking presentation preserves the frozen consumer shape without recreating policy", () => {
  assert.deepEqual(presentBankTransactions([transaction()]), [{
    accepted_warning: false,
    amount: -125.5,
    balance: 1000.25,
    company_id: companyId,
    created_at: "2026-08-28T10:00:00Z",
    id: "30000000-0000-0000-0000-000000000003",
    income_year: 2026,
    matched_action_id: null,
    matched_entry_id: null,
    source_hash: "a".repeat(64),
    suggestion: {
      kind: "BANK_FEE",
      reason: "Teksten beskriver et bankgebyr og beløpet er en utbetaling.",
      ruleVersion: "2026-07-13.1",
    },
    text: "Bankgebyr",
    transaction_date: "2026-08-01",
  }]);

  assert.deepEqual(presentBankSuggestionAcceptances([{
    acceptanceId: "40000000-0000-0000-0000-000000000004",
    acceptedAt: "2026-08-28T10:01:00Z",
    acceptedBy: "20000000-0000-0000-0000-000000000002",
    accountingEntryId: "50000000-0000-0000-0000-000000000005",
    bankTransactionId: "30000000-0000-0000-0000-000000000003",
    replayed: false,
    suggestion: transaction().suggestion,
  }]), [{
    accepted_at: "2026-08-28T10:01:00Z",
    accepted_by: "20000000-0000-0000-0000-000000000002",
    bank_transaction_id: "30000000-0000-0000-0000-000000000003",
    id: "40000000-0000-0000-0000-000000000004",
    ledger_entry_id: "50000000-0000-0000-0000-000000000005",
    reason: "Teksten beskriver et bankgebyr og beløpet er en utbetaling.",
    replayed: false,
    rule_id: "bank_fee",
    rule_version: "2026-07-13.1",
  }]);
});

test("banking error presentation preserves retry identity only for unknown outcomes", () => {
  const problem = (code, status = 422) => new TalliApiError(status, {
    code,
    detail: "Banking request failed.",
    instance: "/api/v1/banking/statement-imports",
    requestId: "bank-error-test",
    status,
    title: "Banking request failed",
    type: "https://talli.no/problems/banking",
  });
  assert.equal(bankingOutcomeMayBeUnknown(problem("BANKING_IDEMPOTENCY_IN_PROGRESS", 409)), true);
  assert.equal(bankingOutcomeMayBeUnknown(problem("BANKING_STATEMENT_INVALID")), false);
  assert.equal(
    bankingActionErrorMessage(problem("BANKING_STATEMENT_INVALID")),
    "Bankfilen kunne ikke leses. Kontroller kolonnene og inntektsåret.",
  );
  assert.equal(
    bankingActionErrorMessage(problem("BANKING_SUGGESTION_STALE", 412)),
    "Forslaget er endret eller ikke lenger gyldig. Last siden på nytt.",
  );
});
