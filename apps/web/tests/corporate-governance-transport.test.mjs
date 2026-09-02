import assert from "node:assert/strict";
import test from "node:test";

import { createTalliApiClient, TalliApiError } from "@talli/talli-api-client";

const companyId = "10000000-0000-0000-0000-000000000001";
const decisionId = "11111111-1111-4111-8111-111111111111";
const documentSetId = "22222222-2222-4222-8222-222222222222";
const decisionHash = "a".repeat(64);

function lifecycle(state = "finalized") {
  return {
    accountingEntryId: "99999999-9999-4999-8999-999999999999",
    companyId,
    decisionHash,
    decisionId,
    declaredAmountOre: 10_000_001,
    documentSetId,
    finalizationId: "55555555-5555-4555-8555-555555555555",
    incomeYear: 2025,
    paidAmountOre: 0,
    remainingAmountOre: 10_000_001,
    replayed: false,
    state,
  };
}

test("owner-dividend lifecycle transport preserves path and idempotency evidence", async () => {
  const captured = [];
  const client = createTalliApiClient({
    baseUrl: "https://backend.example/",
    fetch: async (url, request) => {
      captured.push({ url: String(url), request });
      return Response.json(lifecycle(), { status: 201 });
    },
  });
  const request = {
    idempotencyKey: "owner-dividend-finalization-0001",
    requestId: "owner-dividend-finalization-request",
  };

  const result = await client.corporateGovernanceFinalizeOwnerDividend(
    decisionId,
    {
      companyId,
      decisionHash,
      documentSetId,
      finalizationId: "55555555-5555-4555-8555-555555555555",
      holdingActionId: "aaaaaaaa-1111-4111-8111-111111111111",
      incomeYear: 2025,
      ledgerEntryId: "99999999-9999-4999-8999-999999999999",
    },
    request,
  );

  assert.equal(result.state, "finalized");
  assert.equal(
    captured[0].url,
    `https://backend.example/api/v1/corporate-governance/owner-dividends/${decisionId}/finalizations`,
  );
  assert.equal(captured[0].request.headers["Idempotency-Key"], request.idempotencyKey);
  assert.equal(captured[0].request.headers["X-Request-ID"], request.requestId);
});

test("owner-dividend transport rejects malformed lifecycle responses", async () => {
  const client = createTalliApiClient({
    baseUrl: "https://backend.example",
    fetch: async () => Response.json({ ...lifecycle(), paidAmountOre: "0" }, { status: 201 }),
  });

  await assert.rejects(
    client.corporateGovernanceApproveOwnerDividend(
      decisionId,
      {
        approvalEventId: "eeeeeeee-1111-4111-8111-111111111111",
        companyId,
        decisionHash,
        documentSetId,
      },
      { idempotencyKey: "owner-dividend-approval-0001" },
    ),
    (error) => error instanceof TalliApiError && error.status === 502,
  );
});
