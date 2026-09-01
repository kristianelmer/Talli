import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { TalliApiError } from "@talli/talli-api-client";

import {
  investmentsActionErrorMessage,
  investmentsOutcomeMayBeUnknown,
  effectiveInvestmentActivity,
  formatInvestmentUnits,
  hasPositiveInvestmentUnits,
  investmentUnitFact,
  correctInvestment,
  loadInvestmentAcquisitionLots,
  loadInvestmentCorrections,
  loadInvestmentPositions,
  loadInvestmentActivity,
  loadInvestmentEconomicEvents,
  loadInvestmentShareSaleAllocations,
  presentAcquisitionLots,
  presentInvestmentPositions,
  presentInvestmentActivity,
  presentInvestmentLifecycleEvents,
  presentInvestmentCorrections,
  presentShareSaleAllocations,
  recognizeInvestmentSharePurchase,
  recognizeInvestmentShareSale,
  recognizeInvestmentReceivedDividend,
  recognizeInvestmentReceivedFundDistribution,
  settleInvestmentCash,
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
const fundDistributionActionId = "40000000-0000-0000-0000-000000000034";
const correctionId = "40000000-0000-0000-0000-000000000044";
const replacementActionId = "40000000-0000-0000-0000-000000000054";
const reversalEntryId = "60000000-0000-0000-0000-000000000016";
const replacementEntryId = "60000000-0000-0000-0000-000000000026";
const documentId = "80000000-0000-0000-0000-000000000008";

function position(overrides = {}) {
  return {
    companyId,
    accountingClassification: "other_long_term",
    costBasis: { amount: "50000.00", currency: "NOK" },
    createdAt: "2026-08-31T10:00:00Z",
    createdBy: actorId,
    fundEquityRatioBasisPoints: null,
    fundTaxStatementReference: null,
    id: positionId,
    investmentKey: "portfolio-as",
    kind: "norwegian_private_company",
    lotHistoryStatus: "complete",
    movementCount: 1,
    movements: [{
      movement_date: "2026-05-01",
      movement_type: "purchase_recognition",
      share_delta: "100.125000000000",
    }],
    name: "Portfolio AS",
    orgNumber: "999888777",
    shareCount: "100.125000000000",
    taxBasis: { amount: "50000.00", currency: "NOK" },
    taxTreatment: "fritaksmetoden",
    updatedAt: "2026-08-31T10:00:01Z",
    ...overrides,
  };
}

function dividendActivity(overrides = {}) {
  return {
    accountingClassification: "other_long_term",
    accountingEntryId: entryId,
    acquisitionLotId: null,
    actionDate: "2026-08-15",
    activityKind: "dividend_received",
    bankTransactionId: null,
    bookGainOrLoss: null,
    calculationId: "c".repeat(64),
    capitalizedCost: null,
    companyId,
    createdAt: "2026-08-15T10:00:00Z",
    createdBy: actorId,
    declaredDate: "2026-08-01",
    deductibleLoss: null,
    dividendPortion: null,
    documentId: null,
    documentStatus: "not_required",
    entitlementDate: null,
    evidenceDigest: "e".repeat(64),
    evidenceMode: "manual_fallback",
    evidenceReference: "dividend-advice-example",
    exemptGain: null,
    fifoCostBasisReduction: null,
    fifoTaxBasisReduction: null,
    fundEquityRatioBasisPoints: null,
    fundName: null,
    fundTaxStatementReference: null,
    gainOrLoss: null,
    grossAmount: { amount: "125.50", currency: "NOK" },
    groupEvidenceReference: null,
    groupExceptionApplied: false,
    groupExceptionClaimed: false,
    id: dividendActionId,
    incomeYear: 2026,
    interestPortion: null,
    investmentKey: "portfolio-as",
    investmentKind: "norwegian_private_company",
    investmentName: "Portfolio AS",
    lawfulDividendConfirmed: true,
    netProceeds: null,
    nonDeductibleLoss: null,
    openingFundEquityRatioBasisPoints: null,
    orgNumber: "999888777",
    ownerAttested: true,
    payingCompanyName: "Portfolio AS",
    positionId,
    proceeds: null,
    purchaseAmount: null,
    remainingCostBasis: null,
    remainingShareCount: "6.062500000000",
    remainingTaxBasis: null,
    shareCount: "10.125000000000",
    soldShareCount: "4.062500000000",
    taxGainOrLoss: null,
    taxableAddBack: { amount: "3.77", currency: "NOK" },
    taxableGain: null,
    taxTreatment: "fritaksmetoden",
    totalTaxableIncome: null,
    transactionCosts: null,
    yearEndOwnershipBasisPoints: null,
    yearEndVotingBasisPoints: null,
    ...overrides,
  };
}

function lifecycleEvent(overrides = {}) {
  return {
    accountingClassification: "other_long_term",
    acquisitionLotId: null,
    activityKind: "dividend_received",
    bankFact: null,
    bookGainOrLoss: null,
    calculationId: "c".repeat(64),
    capitalizedCost: null,
    companyId,
    createdAt: "2026-08-15T10:00:00Z",
    createdBy: actorId,
    deductibleLoss: null,
    dividendPortion: null,
    documentFacts: [{
      capability: "DOCUMENTS",
      recordId: documentId,
      revision: 1,
      factSha256: "d".repeat(64),
    }],
    entitlementDate: null,
    evidenceDigest: "e".repeat(64),
    evidenceMode: "manual_fallback",
    evidenceReference: "dividend-advice-example",
    exemptGain: null,
    expectedSettlementAmount: { amount: "125.50", currency: "NOK" },
    fifoCostBasisReduction: null,
    fifoTaxBasisReduction: null,
    fundEquityRatioBasisPoints: null,
    fundName: null,
    fundTaxStatementReference: null,
    grossAmount: { amount: "125.50", currency: "NOK" },
    groupEvidenceReference: null,
    groupExceptionApplied: false,
    groupExceptionClaimed: false,
    id: dividendActionId,
    incomeYear: 2026,
    interestPortion: null,
    investmentKey: "portfolio-as",
    investmentKind: "norwegian_private_company",
    investmentName: "Portfolio AS",
    lawfulDividendConfirmed: true,
    netProceeds: null,
    nonDeductibleLoss: null,
    openingFundEquityRatioBasisPoints: null,
    orgNumber: "999888777",
    ownerAttested: true,
    payingCompanyName: "Portfolio AS",
    positionId,
    positionCreated: null,
    proceeds: null,
    purchaseAmount: null,
    recognitionAccountingEntryId: entryId,
    recognitionDate: "2026-08-01",
    remainingCostBasis: null,
    remainingShareCount: null,
    remainingTaxBasis: null,
    settlementAccountingEntryId: null,
    settlementAmount: null,
    settlementBalanceKind: "dividend_receivable",
    settlementDate: null,
    settlementId: null,
    shareCount: null,
    soldShareCount: null,
    taxGainOrLoss: null,
    taxableAddBack: { amount: "3.77", currency: "NOK" },
    taxableGain: null,
    taxTreatment: "fritaksmetoden",
    totalTaxableIncome: null,
    transactionCosts: null,
    yearEndOwnershipBasisPoints: null,
    yearEndVotingBasisPoints: null,
    ...overrides,
  };
}

function allocation(overrides = {}) {
  return {
    acquisitionDate: "2026-05-01",
    allocatedBookCostBasis: { amount: "20000.00", currency: "NOK" },
    allocatedCostBasis: { amount: "20000.00", currency: "NOK" },
    allocatedNetProceeds: { amount: "25000.00", currency: "NOK" },
    allocatedShareCount: "40.062500000000",
    allocatedTaxBasis: { amount: "20000.00", currency: "NOK" },
    allocationOrder: 1,
    averageFundEquityRatioBasisPoints: null,
    companyId,
    createdAt: "2026-08-01T10:00:00Z",
    createdBy: actorId,
    deductibleLoss: { amount: "0.00", currency: "NOK" },
    exemptGain: { amount: "5000.00", currency: "NOK" },
    id: "70000000-0000-0000-0000-000000000007",
    lotId,
    nonDeductibleLoss: { amount: "0.00", currency: "NOK" },
    positionId,
    saleActionId,
    taxGainOrLoss: { amount: "5000.00", currency: "NOK" },
    taxableGain: { amount: "0.00", currency: "NOK" },
    ...overrides,
  };
}

function lot(overrides = {}) {
  return {
    acquisitionActionId: actionId,
    acquisitionDate: "2026-05-01",
    acquisitionYearFundEquityRatioBasisPoints: null,
    companyId,
    createdAt: "2026-08-31T10:00:00Z",
    createdBy: actorId,
    fundTaxStatementReference: null,
    id: lotId,
    originalCostBasis: { amount: "50000.00", currency: "NOK" },
    originalShareCount: "100.125000000000",
    originalTaxBasis: { amount: "50000.00", currency: "NOK" },
    positionId,
    remainingCostBasis: { amount: "50000.00", currency: "NOK" },
    remainingShareCount: "60.062500000000",
    remainingTaxBasis: { amount: "50000.00", currency: "NOK" },
    ...overrides,
  };
}

function correction(overrides = {}) {
  return {
    companyId,
    createdAt: "2026-08-31T12:00:00Z",
    createdBy: actorId,
    documentFacts: [],
    evidenceDigest: "f".repeat(64),
    evidenceMode: "manual_fallback",
    evidenceReference: "correction-review",
    id: correctionId,
    incomeYear: 2026,
    legacy: false,
    legacyBankTransactionId: null,
    legacyDocumentId: null,
    legacyDocumentStatus: null,
    originalRecordId: dividendActionId,
    originalActivityKind: "dividend_received",
    ownerAttested: true,
    reason: "Rettet beløp mot utbytteoppgaven.",
    replacementAccountingEntryId: replacementEntryId,
    replacementRecordId: replacementActionId,
    replacementActivityKind: "dividend_received",
    reversalAccountingEntryId: reversalEntryId,
    targetKind: "economic_event",
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
    if (path.endsWith("/share-purchase-recognitions")) {
      return Response.json({
        eventId: actionId,
        expectedSettlementAmount: { amount: "50000.00", currency: "NOK" },
        positionId,
        recognitionAccountingEntryId: entryId,
        replayed: false,
        settlementBalanceKind: "purchase_payable",
      });
    }
    if (path.endsWith("/share-sale-recognitions")) {
      return Response.json({
        eventId: saleActionId,
        expectedSettlementAmount: { amount: "30000.00", currency: "NOK" },
        positionId,
        recognitionAccountingEntryId: entryId,
        replayed: false,
        settlementBalanceKind: "sale_receivable",
      });
    }
    if (path.endsWith("/received-dividend-recognitions")) {
      return Response.json({
        eventId: dividendActionId,
        expectedSettlementAmount: { amount: "125.50", currency: "NOK" },
        positionId,
        recognitionAccountingEntryId: entryId,
        replayed: false,
        settlementBalanceKind: "dividend_receivable",
      });
    }
    if (path.endsWith("/received-fund-distribution-recognitions")) {
      return Response.json({
        eventId: fundDistributionActionId,
        expectedSettlementAmount: { amount: "100.00", currency: "NOK" },
        positionId,
        recognitionAccountingEntryId: entryId,
        replayed: false,
        settlementBalanceKind: "fund_distribution_receivable",
      });
    }
    if (path.endsWith("/cash-settlements")) {
      return Response.json({
        eventId: fundDistributionActionId,
        replayed: false,
        settlementAccountingEntryId: entryId,
        settlementId: replacementActionId,
      });
    }
    if (path.endsWith("/corrections") && request.method === "POST") {
      return Response.json({
        correctionId,
        originalRecordId: dividendActionId,
        replacementAccountingEntryId: replacementEntryId,
        replacementRecordId: replacementActionId,
        replayed: false,
        reversalAccountingEntryId: reversalEntryId,
        targetKind: "economic_event",
      });
    }
    if (path.includes("/corrections")) {
      return Response.json({
        items: [correction()],
        page: { hasMore: false, nextCursor: null },
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
    if (path.includes("/economic-events")) {
      return Response.json({
        items: [lifecycleEvent()],
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
    const documentFacts = [{
      capability: "DOCUMENTS",
      recordId: documentId,
      revision: 1,
      factSha256: "c".repeat(64),
    }];
    const recorded = await recognizeInvestmentSharePurchase("session-token", {
      acquisitionDate: "2026-05-01",
      accountingClassification: "other_long_term",
      eventId: actionId,
      companyId,
      documentFacts,
      bankFact: null,
      evidenceMode: "manual_fallback",
      evidenceReference: "broker-note-purchase",
      incomeYear: 2026,
      investmentKey: "portfolio-as",
      investmentKind: "norwegian_private_company",
      investmentName: "Portfolio AS",
      ownerAttested: true,
      orgNumber: "999888777",
      purchaseAmount: { amount: "50000.00", currency: "NOK" },
      shareCount: "100.125000000000",
      transactionCosts: { amount: "0.00", currency: "NOK" },
    }, "purchase-idempotency", "purchase-request");
    const recordedSale = await recognizeInvestmentShareSale("session-token", {
      eventId: saleActionId,
      companyId,
      documentFacts,
      bankFact: null,
      evidenceMode: "manual_fallback",
      evidenceReference: "broker-note-sale",
      incomeYear: 2026,
      ownerAttested: true,
      positionId,
      proceeds: { amount: "30000.00", currency: "NOK" },
      saleDate: "2026-08-01",
      soldShareCount: "40.062500000000",
      transactionCosts: { amount: "0.00", currency: "NOK" },
    }, "sale-idempotency", "sale-request");
    const recordedDividend = await recognizeInvestmentReceivedDividend("session-token", {
      eventId: dividendActionId,
      companyId,
      declaredDate: "2026-08-01",
      documentFacts,
      bankFact: null,
      evidenceMode: "manual_fallback",
      evidenceReference: "dividend-advice",
      grossAmount: { amount: "125.50", currency: "NOK" },
      incomeYear: 2026,
      groupExceptionClaimed: false,
      lawfulDividendConfirmed: true,
      ownerAttested: true,
      payingCompanyName: "Portfolio AS",
      positionId,
    }, "dividend-idempotency", "dividend-request");
    const recordedFundDistribution = await recognizeInvestmentReceivedFundDistribution("session-token", {
      eventId: fundDistributionActionId,
      companyId,
      documentFacts,
      bankFact: null,
      entitlementDate: "2026-08-01",
      evidenceMode: "manual_fallback",
      evidenceReference: "fund-tax-statement",
      fundName: "Norsk Indeksfond",
      fundTaxStatementReference: "tax-statement-2026",
      grossAmount: { amount: "100.00", currency: "NOK" },
      incomeYear: 2026,
      openingFundEquityRatioBasisPoints: 8000,
      ownerAttested: true,
      positionId,
    }, "fund-idempotency", "fund-request");
    const settled = await settleInvestmentCash("session-token", {
      amount: { amount: "100.00", currency: "NOK" },
      bankFact: {
        capability: "BANKING",
        recordId: "70000000-0000-0000-0000-000000000007",
        revision: 1,
        factSha256: "b".repeat(64),
      },
      companyId,
      documentFacts: [],
      eventId: fundDistributionActionId,
      evidenceMode: "linked_sources",
      evidenceReference: "bank-payment",
      incomeYear: 2026,
      ownerAttested: false,
      settlementDate: "2026-08-15",
      settlementId: replacementActionId,
    }, "settlement-idempotency", "settlement-request");
    const corrected = await correctInvestment("session-token", {
      companyId,
      correctionDate: "2026-08-31",
      correctionId,
      documentFacts: [{
        capability: "DOCUMENTS",
        recordId: documentId,
        revision: 1,
        factSha256: "c".repeat(64),
      }],
      bankFact: null,
      evidenceMode: "manual_fallback",
      evidenceReference: "correction-review",
      incomeYear: 2026,
      originalRecordId: dividendActionId,
      originalActivityKind: "dividend_received",
      ownerAttested: true,
      reason: "Rettet beløp mot utbytteoppgaven.",
      replacement: {
        replacementKind: "dividend_received",
        companyId,
        declaredDate: "2026-08-01",
        documentFacts: [{
          capability: "DOCUMENTS",
          recordId: documentId,
          revision: 2,
          factSha256: "d".repeat(64),
        }],
        bankFact: null,
        evidenceMode: "linked_sources",
        evidenceReference: "replacement-dividend-advice",
        grossAmount: { amount: "130.00", currency: "NOK" },
        groupExceptionClaimed: false,
        incomeYear: 2026,
        lawfulDividendConfirmed: true,
        ownerAttested: false,
        payingCompanyName: "Portfolio AS",
        positionId,
        eventId: replacementActionId,
      },
      targetKind: "economic_event",
    }, "correction-idempotency", "correction-request");
    const positions = await loadInvestmentPositions("session-token", [companyId], "position-request");
    const activity = await loadInvestmentActivity("session-token", [companyId], "activity-request");
    const economicEvents = await loadInvestmentEconomicEvents(
      "session-token", [companyId], "event-request",
    );
    const lots = await loadInvestmentAcquisitionLots("session-token", [companyId], "lot-request");
    const allocations = await loadInvestmentShareSaleAllocations(
      "session-token", [companyId], "allocation-request",
    );
    const corrections = await loadInvestmentCorrections(
      "session-token", [companyId], "corrections-request",
    );

    assert.equal(recorded.recognitionAccountingEntryId, entryId);
    assert.equal(recordedSale.eventId, saleActionId);
    assert.equal(recordedDividend.expectedSettlementAmount.amount, "125.50");
    assert.equal(recordedFundDistribution.expectedSettlementAmount.amount, "100.00");
    assert.equal(settled.settlementId, replacementActionId);
    assert.equal(corrected.reversalAccountingEntryId, reversalEntryId);
    assert.deepEqual(positions, [position()]);
    assert.equal(activity[0].id, dividendActionId);
    assert.equal(economicEvents[0].settlementId, null);
    assert.deepEqual(lots, [lot()]);
    assert.deepEqual(allocations, [allocation()]);
    assert.deepEqual(corrections, [correction()]);
    assert.equal(calls.length, 13);
    assert.match(calls[0].url, /\/api\/v1\/investments\/share-purchase-recognitions$/u);
    assert.match(calls[1].url, /\/api\/v1\/investments\/share-sale-recognitions$/u);
    assert.match(calls[2].url, /\/api\/v1\/investments\/received-dividend-recognitions$/u);
    assert.match(calls[3].url, /\/api\/v1\/investments\/received-fund-distribution-recognitions$/u);
    assert.match(calls[4].url, /\/api\/v1\/investments\/cash-settlements$/u);
    assert.match(calls[5].url, /\/api\/v1\/investments\/corrections$/u);
    assert.match(calls[7].url, /cursor=opaque-next/u);
    assert.match(calls[8].url, /\/api\/v1\/investments\/activity/u);
    assert.match(calls[9].url, /\/api\/v1\/investments\/economic-events/u);
    assert.match(calls[11].url, /\/api\/v1\/investments\/share-sale-allocations/u);
    assert.match(calls[12].url, /\/api\/v1\/investments\/corrections/u);
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
    const correctionHeaders = new Headers(calls[5].request.headers);
    assert.equal(correctionHeaders.get("Idempotency-Key"), "correction-idempotency");
    assert.equal(correctionHeaders.get("X-Request-ID"), "correction-request");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("investment unit reads reject lossy wire values", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  try {
    for (const invalid of [
      100.125,
      "1e3",
      "0.0000000000001",
      "100000000000000000000000000.0",
    ]) {
      globalThis.fetch = async () => Response.json({
        items: [position({ shareCount: invalid })],
        page: { hasMore: false, nextCursor: null },
      });
      await assert.rejects(
        loadInvestmentPositions("session-token", [companyId], "invalid-units"),
        (error) => error instanceof TalliApiError && error.status === 502,
      );
    }
    globalThis.fetch = async () => Response.json({
      items: [position({ movements: [{
        movement_date: "2026-05-01",
        movement_type: "purchase_recognition",
        share_delta: 100.125,
      }] })],
      page: { hasMore: false, nextCursor: null },
    });
    await assert.rejects(
      loadInvestmentPositions("session-token", [companyId], "invalid-movement-units"),
      (error) => error instanceof TalliApiError && error.status === 502,
    );
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("investment position reads preserve contract-declared lifecycle movement facts", async () => {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  process.env.TALLI_BACKEND_URL = "https://backend.example";
  const movement = {
    movement_date: "2026-05-01",
    movement_type: "purchase_recognition",
    share_delta: "100.125000000000",
    event_id: actionId,
    calculation_id: "c".repeat(64),
    evidence_digest: "e".repeat(64),
    book_cost_basis_delta: 50000,
    tax_basis_delta: 50000,
  };
  try {
    globalThis.fetch = async () => Response.json({
      items: [position({ movements: [movement] })],
      page: { hasMore: false, nextCursor: null },
    });

    const [loaded] = await loadInvestmentPositions(
      "session-token",
      [companyId],
      "lifecycle-movement-facts",
    );

    assert.deepEqual(loaded.movements, [movement]);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
});

test("investment unit presentation stays decimal-string exact", () => {
  assert.equal(hasPositiveInvestmentUnits("0"), false);
  assert.equal(hasPositiveInvestmentUnits("0.000000000000"), false);
  assert.equal(hasPositiveInvestmentUnits("0.000000000001"), true);
  assert.equal(hasPositiveInvestmentUnits("100.125000000000"), true);
  assert.equal(
    formatInvestmentUnits("99999999999999999999999999.123456789012"),
    "99999999999999999999999999.123456789012",
  );
  assert.equal(formatInvestmentUnits("100.125000000000"), "100.125");
  assert.equal(formatInvestmentUnits("100.000000000000"), "100");
  assert.equal(
    investmentUnitFact({ share_count: "100.125000000000" }, "share_count"),
    "100.125000000000",
  );
  assert.equal(investmentUnitFact({ share_count: 100.125 }, "share_count"), null);
});

test("investments presentation maps canonical wire facts without owning policy", () => {
  assert.deepEqual(presentInvestmentPositions([position()]), [{
    accounting_classification: "other_long_term",
    company_id: companyId,
    cost_basis: 50000,
    created_at: "2026-08-31T10:00:00Z",
    created_by: actorId,
    fund_equity_ratio_basis_points: null,
    fund_tax_statement_reference: null,
    id: positionId,
    investment_key: "portfolio-as",
    kind: "norwegian_private_company",
    lot_history_status: "complete",
    movements: [{
      movement_date: "2026-05-01",
      movement_type: "purchase_recognition",
      share_delta: "100.125000000000",
    }],
    name: "Portfolio AS",
    org_number: "999888777",
    share_count: "100.125000000000",
    tax_basis: 50000,
    tax_treatment: "fritaksmetoden",
    updated_at: "2026-08-31T10:00:01Z",
  }]);
  assert.deepEqual(presentAcquisitionLots([lot()]), [{
    acquisition_action_id: actionId,
    acquisition_date: "2026-05-01",
    acquisition_year_fund_equity_ratio_basis_points: null,
    company_id: companyId,
    created_at: "2026-08-31T10:00:00Z",
    created_by: actorId,
    fund_tax_statement_reference: null,
    id: lotId,
    original_cost_basis: 50000,
    original_share_count: "100.125000000000",
    original_tax_basis: 50000,
    position_id: positionId,
    remaining_cost_basis: 50000,
    remaining_share_count: "60.062500000000",
    remaining_tax_basis: 50000,
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
      accounting_classification: "other_long_term",
      bank_transaction_id: null,
      calculation_id: "c".repeat(64),
      declared_date: "2026-08-01",
      document_id: null,
      document_status: "not_required",
      evidence_digest: "e".repeat(64),
      evidence_mode: "manual_fallback",
      evidence_reference: "dividend-advice-example",
      fund_equity_ratio_basis_points: null,
      fund_tax_statement_reference: null,
      gross_amount: 125.5,
      group_evidence_reference: null,
      group_exception_applied: false,
      group_exception_claimed: false,
      investment_key: "portfolio-as",
      investment_kind: "norwegian_private_company",
      investment_name: "Portfolio AS",
      lawful_dividend_confirmed: true,
      linked_investment_id: positionId,
      org_number: "999888777",
      owner_attested: true,
      paid_date: "2026-08-15",
      paying_company_name: "Portfolio AS",
      position_id: positionId,
      tax_treatment: "fritaksmetoden",
      taxable_add_back: 3.77,
      year_end_ownership_basis_points: null,
      year_end_voting_basis_points: null,
    },
    risk_level: "ready",
  }]);
  assert.deepEqual(summarizeReceivedDividendAnnualImpact(presentedDividendActivity), {
    dividendIncome: 125.5,
    fritaksmetodenAddBack: 3.77,
  });
  const [presentedLifecycleEvent] = presentInvestmentLifecycleEvents([
    lifecycleEvent(),
  ]);
  assert.equal(presentedLifecycleEvent.action_date, "2026-08-01");
  assert.equal(presentedLifecycleEvent.document_id, documentId);
  assert.equal(presentedLifecycleEvent.bank_transaction_id, null);
  assert.equal(presentedLifecycleEvent.payload.settlement_status, "pending");
  assert.equal(presentedLifecycleEvent.payload.expected_settlement_amount, 125.5);
  assert.equal(presentedLifecycleEvent.payload.taxable_add_back, 3.77);
  const [purchaseActivity] = presentInvestmentActivity([dividendActivity({
    activityKind: "share_purchase",
    shareCount: "10.125000000000",
    purchaseAmount: { amount: "125.50", currency: "NOK" },
    transactionCosts: { amount: "2.50", currency: "NOK" },
    capitalizedCost: { amount: "128.00", currency: "NOK" },
  })]);
  assert.equal(purchaseActivity.payload.share_count, "10.125000000000");
  const [saleActivity] = presentInvestmentActivity([dividendActivity({
    activityKind: "share_sale",
    soldShareCount: "4.062500000000",
    remainingShareCount: "6.062500000000",
    proceeds: { amount: "60.00", currency: "NOK" },
    transactionCosts: { amount: "1.00", currency: "NOK" },
  })]);
  assert.equal(saleActivity.payload.sold_share_count, "4.062500000000");
  assert.equal(saleActivity.payload.remaining_share_count, "6.062500000000");
  assert.deepEqual(presentShareSaleAllocations([allocation()])[0], {
    allocated_book_cost_basis: 20000,
    allocated_cost_basis: 20000,
    allocated_net_proceeds: 25000,
    allocated_share_count: "40.062500000000",
    allocated_tax_basis: 20000,
    average_fund_equity_ratio_basis_points: null,
    company_id: companyId,
    created_at: "2026-08-01T10:00:00Z",
    created_by: actorId,
    deductible_loss: 0,
    exempt_gain: 5000,
    id: "70000000-0000-0000-0000-000000000007",
    lot_id: lotId,
    non_deductible_loss: 0,
    position_id: positionId,
    sale_action_id: saleActionId,
    tax_gain_or_loss: 5000,
    taxable_gain: 0,
  });
  assert.deepEqual(presentInvestmentCorrections([correction()]), [{
    company_id: companyId,
    created_at: "2026-08-31T12:00:00Z",
    created_by: actorId,
    document_facts: [],
    evidence_digest: "f".repeat(64),
    evidence_mode: "manual_fallback",
    evidence_reference: "correction-review",
    id: correctionId,
    income_year: 2026,
    legacy: false,
    legacy_bank_transaction_id: null,
    legacy_document_id: null,
    legacy_document_status: null,
    original_record_id: dividendActionId,
    original_activity_kind: "dividend_received",
    owner_attested: true,
    reason: "Rettet beløp mot utbytteoppgaven.",
    replacement_accounting_entry_id: replacementEntryId,
    replacement_record_id: replacementActionId,
    replacement_activity_kind: "dividend_received",
    reversal_accounting_entry_id: reversalEntryId,
    target_kind: "economic_event",
  }]);
  assert.deepEqual(
    effectiveInvestmentActivity(
      presentInvestmentActivity([
        dividendActivity(),
        dividendActivity({ id: replacementActionId }),
      ]),
      presentInvestmentCorrections([correction()]),
    ).map((item) => item.id),
    [replacementActionId],
  );
});

test("investments errors preserve retry identity only for unknown outcomes", () => {
  const problem = (code, status = 422) => new TalliApiError(status, {
    code,
    detail: "Investments request failed.",
    instance: "/api/v1/investments/share-purchase-recognitions",
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

test("investment actions require explicit owner and dividend attestations", () => {
  const actionsSource = readFileSync(
    new URL("../app/actions.ts", import.meta.url),
    "utf8",
  );
  const wizardSources = [
    "SharePurchaseWizard.tsx",
    "ShareSaleWizard.tsx",
    "DividendReceivedWizard.tsx",
    "FundDistributionWizard.tsx",
    "InvestmentCorrectionWizard.tsx",
    "InvestmentSettlementCorrectionWizard.tsx",
    "InvestmentMeasurementWizard.tsx",
  ].map((fileName) => readFileSync(
    new URL(`../app/(owner)/actions/_components/${fileName}`, import.meta.url),
    "utf8",
  ));
  const evidenceFieldsSource = readFileSync(
    new URL(
      "../app/(owner)/actions/_components/InvestmentEvidenceFields.tsx",
      import.meta.url,
    ),
    "utf8",
  );

  assert.doesNotMatch(actionsSource, /lawfulDividendConfirmed:\s*true/u);
  assert.doesNotMatch(actionsSource, /ownerAttested:\s*(?:true|![A-Za-z])/u);
  assert.doesNotMatch(actionsSource, /owner-(?:entry|correction)/u);
  assert.match(
    actionsSource,
    /lawfulDividendConfirmed:\s*formString\(formData, "lawfulDividendConfirmed"\) === "true"/u,
  );
  assert.match(
    actionsSource,
    /const ownerAttested = formString\(formData, field\("ownerAttested"\)\) === "true"/u,
  );
  assert.ok(wizardSources.every((source) => source.includes("InvestmentEvidenceFields")));
  assert.match(evidenceFieldsSource, /fieldName\(fieldPrefix, "ownerAttested"\)/u);
  assert.match(wizardSources[2], /name="lawfulDividendConfirmed"/u);
  assert.match(wizardSources[4], /name="lawfulDividendConfirmed"/u);
  assert.doesNotMatch(wizardSources[4], /label="Utbetalingsdato"/u);
  assert.match(actionsSource, /targetKind: "cash_settlement"/u);
  assert.match(actionsSource, /replacementKind: "cash_settlement"/u);
  assert.match(wizardSources[4], /name="replacementSettlementAmount"/u);
  assert.match(
    actionsSource,
    /amount:\s*formString\(formData, "replacementSettlementAmount"\)/u,
  );
  assert.doesNotMatch(actionsSource, /const replacementAmount\s*=/u);
});
