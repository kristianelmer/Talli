import assert from "node:assert/strict";
import test from "node:test";

import { TalliApiError } from "@talli/talli-api-client";

import {
  investmentsActionErrorMessage,
  investmentsOutcomeMayBeUnknown,
  loadInvestmentAcquisitionLots,
  loadInvestmentPositions,
  loadInvestmentActivity,
  loadInvestmentShareSaleAllocations,
  presentAcquisitionLots,
  presentInvestmentPositions,
  presentInvestmentActivity,
  presentShareSaleAllocations,
  recordInvestmentSharePurchase,
  recordInvestmentShareSale,
  recordInvestmentReceivedDividend,
  summarizeReceivedDividendAnnualImpact,
} from "../features/investments/index.ts";

const companyId = "10000000-0000-0000-0000-000000000001";
const actorId = "20000000-0000-0000-0000-000000000002";
const positionId = "30000000-0000-0000-0000-000000000003";
const actionId = "40000000-0000-0000-0000-000000000004";
const lotId = "50000000-0000-0000-0000-000000000005";
const entryId = "60000000-0000-0000-0000-000000000006";
const saleActionId = "40000000-0000-0000-0000-000000000014";
const dividendActionId = "40000000-0000-0000-0000-000000000024";

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
    movements: [{ movement_type: "purchase" }],
    name: "Portfolio AS",
    orgNumber: "999888777",
    shareCount: 100,
    taxTreatment: "fritaksmetoden",
    updatedAt: "2026-08-31T10:00:01Z",
    ...overrides,
  };
}

function dividendActivity(overrides = {}) {
  return {
    accountingEntryId: entryId,
    acquisitionLotId: null,
    actionDate: "2026-08-15",
    activityKind: "dividend_received",
    bankTransactionId: null,
    companyId,
    createdAt: "2026-08-15T10:00:00Z",
    createdBy: actorId,
    declaredDate: "2026-08-01",
    documentId: null,
    documentStatus: "not_required",
    fifoCostBasisReduction: null,
    gainOrLoss: null,
    grossAmount: { amount: "125.50", currency: "NOK" },
    id: dividendActionId,
    incomeYear: 2026,
    investmentKey: "portfolio-as",
    investmentKind: "norwegian_private_company",
    investmentName: "Portfolio AS",
    orgNumber: "999888777",
    payingCompanyName: "Portfolio AS",
    positionId,
    proceeds: null,
    purchaseAmount: null,
    remainingCostBasis: null,
    remainingShareCount: null,
    shareCount: null,
    soldShareCount: null,
    taxableAddBack: { amount: "3.77", currency: "NOK" },
    taxTreatment: "fritaksmetoden",
    ...overrides,
  };
}

function allocation(overrides = {}) {
  return {
    acquisitionDate: "2026-05-01",
    allocatedCostBasis: { amount: "20000.00", currency: "NOK" },
    allocatedShareCount: 40,
    allocationOrder: 1,
    companyId,
    createdAt: "2026-08-01T10:00:00Z",
    createdBy: actorId,
    id: "70000000-0000-0000-0000-000000000007",
    lotId,
    positionId,
    saleActionId,
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
    if (path.endsWith("/share-sales")) {
      return Response.json({
        accountingEntryId: entryId,
        actionId: saleActionId,
        positionId,
        replayed: false,
      });
    }
    if (path.endsWith("/received-dividends")) {
      return Response.json({
        accountingEntryId: entryId,
        actionId: dividendActionId,
        positionId,
        replayed: false,
        taxableAddBack: { amount: "3.77", currency: "NOK" },
      });
    }
    if (path.includes("/positions")) {
      const next = path.includes("cursor=opaque-next") ? null : "opaque-next";
      return Response.json({
        items: next ? [position()] : [],
        page: { hasMore: next !== null, nextCursor: next },
      });
    }
    if (path.includes("/activity")) {
      return Response.json({
        items: [dividendActivity()],
        page: { hasMore: false, nextCursor: null },
      });
    }
    if (path.includes("/share-sale-allocations")) {
      return Response.json({
        items: [allocation()],
        page: { hasMore: false, nextCursor: null },
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
    const recordedSale = await recordInvestmentShareSale("session-token", {
      actionId: saleActionId,
      companyId,
      documentStatus: "not_required",
      incomeYear: 2026,
      positionId,
      proceeds: { amount: "30000.00", currency: "NOK" },
      saleDate: "2026-08-01",
      soldShareCount: 40,
    }, "sale-idempotency", "sale-request");
    const recordedDividend = await recordInvestmentReceivedDividend("session-token", {
      actionId: dividendActionId,
      companyId,
      declaredDate: "2026-08-01",
      documentStatus: "not_required",
      grossAmount: { amount: "125.50", currency: "NOK" },
      incomeYear: 2026,
      paidDate: "2026-08-15",
      payingCompanyName: "Portfolio AS",
      positionId,
      taxTreatment: "fritaksmetoden",
    }, "dividend-idempotency", "dividend-request");
    const positions = await loadInvestmentPositions("session-token", [companyId], "position-request");
    const activity = await loadInvestmentActivity("session-token", [companyId], "activity-request");
    const lots = await loadInvestmentAcquisitionLots("session-token", [companyId], "lot-request");
    const allocations = await loadInvestmentShareSaleAllocations(
      "session-token", [companyId], "allocation-request",
    );

    assert.equal(recorded.accountingEntryId, entryId);
    assert.equal(recordedSale.actionId, saleActionId);
    assert.equal(recordedDividend.taxableAddBack.amount, "3.77");
    assert.deepEqual(positions, [position()]);
    assert.equal(activity[0].id, dividendActionId);
    assert.deepEqual(lots, [lot()]);
    assert.deepEqual(allocations, [allocation()]);
    assert.equal(calls.length, 8);
    assert.match(calls[0].url, /\/api\/v1\/investments\/share-purchases$/u);
    assert.match(calls[1].url, /\/api\/v1\/investments\/share-sales$/u);
    assert.match(calls[2].url, /\/api\/v1\/investments\/received-dividends$/u);
    assert.match(calls[4].url, /cursor=opaque-next/u);
    assert.match(calls[5].url, /\/api\/v1\/investments\/activity/u);
    assert.match(calls[7].url, /\/api\/v1\/investments\/share-sale-allocations/u);
    const mutationHeaders = new Headers(calls[0].request.headers);
    assert.equal(mutationHeaders.get("Authorization"), "Bearer session-token");
    assert.equal(mutationHeaders.get("Idempotency-Key"), "purchase-idempotency");
    assert.equal(mutationHeaders.get("X-Request-ID"), "purchase-request");
    const saleHeaders = new Headers(calls[1].request.headers);
    assert.equal(saleHeaders.get("Authorization"), "Bearer session-token");
    assert.equal(saleHeaders.get("Idempotency-Key"), "sale-idempotency");
    assert.equal(saleHeaders.get("X-Request-ID"), "sale-request");
    const dividendHeaders = new Headers(calls[2].request.headers);
    assert.equal(dividendHeaders.get("Authorization"), "Bearer session-token");
    assert.equal(dividendHeaders.get("Idempotency-Key"), "dividend-idempotency");
    assert.equal(dividendHeaders.get("X-Request-ID"), "dividend-request");
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
    movements: [{ movement_type: "purchase" }],
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
  const presentedDividendActivity = presentInvestmentActivity([dividendActivity()]);
  assert.deepEqual(presentedDividendActivity, [{
    action_date: "2026-08-15",
    action_type: "dividend_received",
    bank_transaction_id: null,
    blocker_code: null,
    company_id: companyId,
    created_at: "2026-08-15T10:00:00Z",
    created_by: actorId,
    document_id: null,
    id: dividendActionId,
    income_year: 2026,
    ledger_entry_id: entryId,
    payload: {
      bank_transaction_id: null,
      declared_date: "2026-08-01",
      document_id: null,
      document_status: "not_required",
      gross_amount: 125.5,
      investment_key: "portfolio-as",
      investment_kind: "norwegian_private_company",
      investment_name: "Portfolio AS",
      linked_investment_id: positionId,
      org_number: "999888777",
      paid_date: "2026-08-15",
      paying_company_name: "Portfolio AS",
      position_id: positionId,
      tax_treatment: "fritaksmetoden",
      taxable_add_back: 3.77,
    },
    risk_level: "ready",
  }]);
  assert.deepEqual(summarizeReceivedDividendAnnualImpact(presentedDividendActivity), {
    dividendIncome: 125.5,
    fritaksmetodenAddBack: 3.77,
  });
  assert.deepEqual(presentShareSaleAllocations([allocation()])[0], {
    allocated_cost_basis: 20000,
    allocated_share_count: 40,
    company_id: companyId,
    created_at: "2026-08-01T10:00:00Z",
    created_by: actorId,
    id: "70000000-0000-0000-0000-000000000007",
    lot_id: lotId,
    position_id: positionId,
    sale_action_id: saleActionId,
  });
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
