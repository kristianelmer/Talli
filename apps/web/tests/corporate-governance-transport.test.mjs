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

test("decision-facts transport sends only identity and accepts the generated response", async () => {
  const captured = [];
  const sha = "b".repeat(64);
  const client = createTalliApiClient({
    baseUrl: "https://backend.example/",
    fetch: async (url, request) => {
      captured.push({ url: String(url), request });
      return Response.json({
        company: { organizationNumber: "310279617", legalName: "Talli AS" },
        shareholders: [{ shareholderId: "owner-1", name: "Owner", shareCount: 100, order: 0 }],
        annualBasis: {
          sourceId: "33333333-3333-4333-8333-333333333333",
          incomeYear: 2024,
          latestApproved: true,
          annualDataSha256: sha,
          annualAccountsPayloadSha256: sha,
          resultAfterTaxOre: 100,
          equityOre: 200,
          availableDistributionOre: 100,
          cashOre: 300,
        },
        reviewedFacts: {
          organizationNumber: "310279617",
          legalName: "Talli AS",
          shareholders: [{ shareholderId: "owner-1", name: "Owner", shareCount: 100 }],
          totalCompanyShares: 100,
          availableDistributionOre: 100,
          annualDataSha256: sha,
          annualAccountsPayloadSha256: sha,
        },
      });
    },
  });

  const result = await client.corporateGovernanceDeriveDecisionFacts({
    companyId,
    incomeYear: 2025,
    decisionKind: "owner_dividend",
  });

  assert.equal(result.annualBasis.incomeYear, 2024);
  assert.equal(
    captured[0].url,
    `https://backend.example/api/v1/corporate-governance/decision-facts?companyId=${companyId}&incomeYear=2025&decisionKind=owner_dividend`,
  );
  assert.equal(captured[0].request.method, "GET");
});

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

test("shareholder-loan transport preserves identity and rejects malformed responses", async () => {
  const captured = [];
  const response = {
    actionId: "12121212-1212-4212-8212-121212121212",
    companyId,
    incomeYear: 2025,
    loanDate: "2025-03-01",
    amountOre: 125050,
    direction: "shareholder_to_company",
    counterpartyName: "Eier Holding AS",
    documentStatus: "attached",
    interestModelled: true,
    relatedPartySecurity: false,
    bankTransactionId: null,
    documentId: null,
    accountingEntryId: "13131313-1313-4313-8313-131313131313",
    replayed: false,
  };
  const client = createTalliApiClient({
    baseUrl: "https://backend.example/",
    fetch: async (url, request) => {
      captured.push({ url: String(url), request });
      return Response.json(response, { status: 201 });
    },
  });

  const result = await client.corporateGovernanceRecordShareholderLoan(
    {
      actionId: response.actionId,
      companyId,
      incomeYear: 2025,
      ledgerEntryId: response.accountingEntryId,
      loanDate: response.loanDate,
      amount: { amount: "1250.50", currency: "NOK" },
      direction: response.direction,
      counterpartyName: response.counterpartyName,
      documentStatus: response.documentStatus,
      interestModelled: true,
      relatedPartySecurity: false,
      bankTransactionId: null,
      documentId: null,
    },
    {
      idempotencyKey: "shareholder-loan-record-0001",
      requestId: "shareholder-loan-record-0001",
    },
  );

  assert.equal(result.actionId, response.actionId);
  assert.equal(
    captured[0].url,
    "https://backend.example/api/v1/corporate-governance/shareholder-loans",
  );
  assert.equal(
    captured[0].request.headers["Idempotency-Key"],
    "shareholder-loan-record-0001",
  );
});
