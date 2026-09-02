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
