import assert from "node:assert/strict";
import test from "node:test";

import { TalliApiError } from "@talli/talli-api-client";

import {
  investmentsActionErrorMessage,
  investmentsOutcomeMayBeUnknown,
  loadInvestmentAcquisitionLots,
  loadInvestmentPositions,
  presentAcquisitionLots,
  presentInvestmentPositions,
  recordInvestmentSharePurchase,
} from "../features/investments/index.ts";

const companyId = "10000000-0000-0000-0000-000000000001";
const actorId = "20000000-0000-0000-0000-000000000002";
const positionId = "30000000-0000-0000-0000-000000000003";
const actionId = "40000000-0000-0000-0000-000000000004";
const lotId = "50000000-0000-0000-0000-000000000005";
const entryId = "60000000-0000-0000-0000-000000000006";

function position(overrides = {}) {
  return {
    companyId,
    costBasis: { amount: "50000.00", currency: "NOK" },
    createdAt: "2026-08-31T10:00:00Z",
    createdBy: actorId,
    id: positionId,
    investmentKey: "portfolio-as",
    kind: "norwegian_private_company",
    lotHistoryStatus: "complete",
    movementCount: 1,
    name: "Portfolio AS",
    orgNumber: "999888777",
    shareCount: 100,
    taxTreatment: "fritaksmetoden",
    updatedAt: "2026-08-31T10:00:01Z",
    ...overrides,
  };
}

function lot(overrides = {}) {
  return {
    acquisitionActionId: actionId,
    acquisitionDate: "2026-05-01",
    companyId,
    createdAt: "2026-08-31T10:00:00Z",
    createdBy: actorId,
    id: lotId,
    originalCostBasis: { amount: "50000.00", currency: "NOK" },
    originalShareCount: 100,
    positionId,
    remainingCostBasis: { amount: "50000.00", currency: "NOK" },
    remainingShareCount: 100,
    ...overrides,
  };
}

test("investments transport uses generated routes, auth, idempotency, and opaque paging", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  const calls = [];
  globalThis.fetch = async (url, request) => {
    calls.push({ url: String(url), request });
    const path = String(url);
    if (path.endsWith("/share-purchases")) {
      return Response.json({
        accountingEntryId: entryId,
        acquisitionLotId: lotId,
        actionId,
        positionCreated: true,
        positionId,
        replayed: false,
      });
    }
    if (path.includes("/positions")) {
      const next = path.includes("cursor=opaque-next") ? null : "opaque-next";
      return Response.json({
        items: next ? [position()] : [],
        page: { hasMore: next !== null, nextCursor: next },
      });
    }
    return Response.json({ items: [lot()], page: { hasMore: false, nextCursor: null } });
  };
  process.env.TALLI_BACKEND_URL = "https://backend.example";

  try {
    const recorded = await recordInvestmentSharePurchase("session-token", {
      acquisitionDate: "2026-05-01",
      actionId,
      companyId,
      documentStatus: "not_required",
      incomeYear: 2026,
      investmentKey: "portfolio-as",
      investmentKind: "norwegian_private_company",
      investmentName: "Portfolio AS",
      orgNumber: "999888777",
      purchaseAmount: { amount: "50000.00", currency: "NOK" },
      shareCount: 100,
      taxTreatment: "fritaksmetoden",
    }, "purchase-idempotency", "purchase-request");
    const positions = await loadInvestmentPositions("session-token", [companyId], "position-request");
    const lots = await loadInvestmentAcquisitionLots("session-token", [companyId], "lot-request");

    assert.equal(recorded.accountingEntryId, entryId);
    assert.deepEqual(positions, [position()]);
    assert.deepEqual(lots, [lot()]);
    assert.equal(calls.length, 4);
    assert.match(calls[0].url, /\/api\/v1\/investments\/share-purchases$/u);
    assert.match(calls[2].url, /cursor=opaque-next/u);
    const mutationHeaders = new Headers(calls[0].request.headers);
    assert.equal(mutationHeaders.get("Authorization"), "Bearer session-token");
    assert.equal(mutationHeaders.get("Idempotency-Key"), "purchase-idempotency");
    assert.equal(mutationHeaders.get("X-Request-ID"), "purchase-request");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("investments presentation maps canonical wire facts without owning policy", () => {
  assert.deepEqual(presentInvestmentPositions([position()]), [{
    company_id: companyId,
    cost_basis: 50000,
    created_at: "2026-08-31T10:00:00Z",
    created_by: actorId,
    id: positionId,
    investment_key: "portfolio-as",
    kind: "norwegian_private_company",
    lot_history_status: "complete",
    movements: [null],
    name: "Portfolio AS",
    org_number: "999888777",
    share_count: 100,
    tax_treatment: "fritaksmetoden",
    updated_at: "2026-08-31T10:00:01Z",
  }]);
  assert.deepEqual(presentAcquisitionLots([lot()]), [{
    acquisition_action_id: actionId,
    acquisition_date: "2026-05-01",
    company_id: companyId,
    created_at: "2026-08-31T10:00:00Z",
    created_by: actorId,
    id: lotId,
    original_cost_basis: 50000,
    original_share_count: 100,
    position_id: positionId,
    remaining_cost_basis: 50000,
    remaining_share_count: 100,
  }]);
});

test("investments errors preserve retry identity only for unknown outcomes", () => {
  const problem = (code, status = 422) => new TalliApiError(status, {
    code,
    detail: "Investments request failed.",
    instance: "/api/v1/investments/share-purchases",
    requestId: "investment-error-test",
    status,
    title: "Investments request failed",
    type: "https://talli.no/problems/investments",
  });
  assert.equal(investmentsOutcomeMayBeUnknown(problem("INVESTMENTS_IDEMPOTENCY_IN_PROGRESS", 409)), true);
  assert.equal(investmentsOutcomeMayBeUnknown(problem("INVESTMENTS_INVALID_INPUT")), false);
  assert.equal(
    investmentsActionErrorMessage(problem("INVESTMENTS_INVALID_INPUT")),
    "Kontroller opplysningene for aksjekjøpet.",
  );
});
