import assert from "node:assert/strict";
import test from "node:test";

import { createTalliApiClient, TalliApiError } from "@talli/talli-api-client";

const companyId = "10000000-0000-0000-0000-000000000001";
const operationId = "70000000-0000-4000-8000-000000000070";

function postedEntry(overrides = {}) {
  return {
    companyId,
    entryId: "40000000-0000-0000-0000-000000000004",
    entryKind: "DIVIDEND_RECEIVED",
    incomeYear: 2026,
    postedAt: "2026-08-27T10:00:00Z",
    replayed: false,
    ...overrides,
  };
}

function dividendCommand() {
  return {
    actionId: operationId,
    bankTransactionId: null,
    companyId,
    declaredDate: "2026-04-01",
    documentId: null,
    documentStatus: "not_required",
    grossAmount: { amount: "125.50", currency: "NOK" },
    incomeYear: 2026,
    linkedInvestmentId: null,
    paidDate: "2026-04-15",
    payingCompanyName: "Example AS",
    taxTreatment: "fritaksmetoden",
  };
}

function clientReturning(payload, capture = {}) {
  return createTalliApiClient({
    baseUrl: "https://backend.example",
    fetch: async (url, request) => {
      capture.url = String(url);
      capture.request = request;
      return Response.json(payload, { status: 201 });
    },
  });
}

test("generated ledger writer binds the response to command purpose and replay state", async () => {
  const command = dividendCommand();
  const capture = {};
  const api = clientReturning(
    { postedEntry: postedEntry(), replayed: false },
    capture,
  );

  const result = await api.ledgerPostInvestmentDividend(command, {
    idempotencyKey: operationId,
    requestId: operationId,
  });

  assert.equal(
    capture.url,
    "https://backend.example/api/v1/ledger/investment-dividends",
  );
  assert.equal(new Headers(capture.request.headers).get("Idempotency-Key"), operationId);
  assert.deepEqual(JSON.parse(capture.request.body), command);
  assert.equal(result.postedEntry.entryKind, "DIVIDEND_RECEIVED");

  for (const payload of [
    { postedEntry: null, replayed: false },
    { postedEntry: postedEntry({ companyId: crypto.randomUUID() }), replayed: false },
    { postedEntry: postedEntry({ incomeYear: 2025 }), replayed: false },
    { postedEntry: postedEntry({ entryKind: "SHARE_PURCHASE" }), replayed: false },
    { postedEntry: postedEntry({ replayed: true }), replayed: false },
    { postedEntry: postedEntry(), replayed: false, rawResult: {} },
  ]) {
    await assert.rejects(
      clientReturning(payload).ledgerPostInvestmentDividend(command, {
        idempotencyKey: operationId,
      }),
      (error) => error instanceof TalliApiError && error.status === 502,
    );
  }
});

test("annual-close finalization accepts only an intentionally empty ledger result", async () => {
  const command = {
    companyId,
    decisionHash: "a".repeat(64),
    decisionId: "70000000-0000-4000-8000-000000000074",
    finalizationId: operationId,
    incomeYear: 2026,
    setId: "70000000-0000-4000-8000-000000000075",
  };

  const result = await clientReturning({ postedEntry: null, replayed: false })
    .ledgerFinalizeCorporateDecision(command, { idempotencyKey: operationId });
  assert.deepEqual(result, { postedEntry: null, replayed: false });

  await assert.rejects(
    clientReturning({ postedEntry: postedEntry(), replayed: false })
      .ledgerFinalizeCorporateDecision(command, { idempotencyKey: operationId }),
    (error) => error instanceof TalliApiError && error.status === 502,
  );
});
