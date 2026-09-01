import assert from "node:assert/strict";
import test from "node:test";

import { TalliApiError } from "@talli/talli-api-client";

import {
  investmentsActionErrorMessage,
  investmentsOutcomeMayBeUnknown,
  effectiveInvestmentActivity,
  correctInvestment,
  loadInvestmentAcquisitionLots,
  loadInvestmentCorrections,
  loadInvestmentPositions,
  loadInvestmentActivity,
  loadInvestmentShareSaleAllocations,
  presentAcquisitionLots,
  presentInvestmentPositions,
  presentInvestmentActivity,
  presentInvestmentCorrections,
  presentShareSaleAllocations,
  recordInvestmentSharePurchase,
  recordInvestmentShareSale,
  recordInvestmentReceivedDividend,
  recordInvestmentReceivedFundDistribution,
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
    movements: [{ movement_type: "purchase" }],
    name: "Portfolio AS",
    orgNumber: "999888777",
    shareCount: 100,
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
    remainingShareCount: null,
    remainingTaxBasis: null,
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
    allocatedShareCount: 40,
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
    originalShareCount: 100,
    originalTaxBasis: { amount: "50000.00", currency: "NOK" },
    positionId,
    remainingCostBasis: { amount: "50000.00", currency: "NOK" },
    remainingShareCount: 100,
    remainingTaxBasis: { amount: "50000.00", currency: "NOK" },
    ...overrides,
  };
}

function correction(overrides = {}) {
  return {
    bankTransactionId: null,
    companyId,
    createdAt: "2026-08-31T12:00:00Z",
    createdBy: actorId,
    documentId: null,
    documentStatus: "not_required",
    evidenceDigest: "f".repeat(64),
    evidenceMode: "manual_fallback",
    evidenceReference: "correction-review",
    id: correctionId,
    incomeYear: 2026,
    originalActionId: dividendActionId,
    originalActivityKind: "dividend_received",
    ownerAttested: true,
    reason: "Rettet beløp mot utbytteoppgaven.",
    replacementAccountingEntryId: replacementEntryId,
    replacementActionId,
    replacementActivityKind: "dividend_received",
    reversalAccountingEntryId: reversalEntryId,
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
    if (path.endsWith("/received-fund-distributions")) {
      return Response.json({
        accountingEntryId: entryId,
        actionId: fundDistributionActionId,
        dividendPortion: { amount: "80.00", currency: "NOK" },
        interestPortion: { amount: "20.00", currency: "NOK" },
        positionId,
        replayed: false,
        taxableAddBack: { amount: "2.40", currency: "NOK" },
        totalTaxableIncome: { amount: "22.40", currency: "NOK" },
      });
    }
    if (path.endsWith("/corrections") && request.method === "POST") {
      return Response.json({
        correctionId,
        originalActionId: dividendActionId,
        replacementAccountingEntryId: replacementEntryId,
        replacementActionId,
        replayed: false,
        reversalAccountingEntryId: reversalEntryId,
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
      accountingClassification: "other_long_term",
      actionId,
      companyId,
      documentStatus: "not_required",
      evidenceMode: "manual_fallback",
      evidenceReference: "broker-note-purchase",
      incomeYear: 2026,
      investmentKey: "portfolio-as",
      investmentKind: "norwegian_private_company",
      investmentName: "Portfolio AS",
      ownerAttested: true,
      orgNumber: "999888777",
      purchaseAmount: { amount: "50000.00", currency: "NOK" },
      shareCount: 100,
      taxTreatment: "fritaksmetoden",
      transactionCosts: { amount: "0.00", currency: "NOK" },
    }, "purchase-idempotency", "purchase-request");
    const recordedSale = await recordInvestmentShareSale("session-token", {
      actionId: saleActionId,
      companyId,
      documentStatus: "not_required",
      evidenceMode: "manual_fallback",
      evidenceReference: "broker-note-sale",
      incomeYear: 2026,
      ownerAttested: true,
      positionId,
      proceeds: { amount: "30000.00", currency: "NOK" },
      saleDate: "2026-08-01",
      soldShareCount: 40,
      transactionCosts: { amount: "0.00", currency: "NOK" },
    }, "sale-idempotency", "sale-request");
    const recordedDividend = await recordInvestmentReceivedDividend("session-token", {
      actionId: dividendActionId,
      companyId,
      declaredDate: "2026-08-01",
      documentStatus: "not_required",
      evidenceMode: "manual_fallback",
      evidenceReference: "dividend-advice",
      grossAmount: { amount: "125.50", currency: "NOK" },
      incomeYear: 2026,
      groupExceptionClaimed: false,
      lawfulDividendConfirmed: true,
      ownerAttested: true,
      paidDate: "2026-08-15",
      payingCompanyName: "Portfolio AS",
      positionId,
      taxTreatment: "fritaksmetoden",
    }, "dividend-idempotency", "dividend-request");
    const recordedFundDistribution = await recordInvestmentReceivedFundDistribution("session-token", {
      actionId: fundDistributionActionId,
      companyId,
      documentStatus: "not_required",
      entitlementDate: "2026-08-01",
      evidenceMode: "manual_fallback",
      evidenceReference: "fund-tax-statement",
      fundName: "Norsk Indeksfond",
      fundTaxStatementReference: "tax-statement-2026",
      grossAmount: { amount: "100.00", currency: "NOK" },
      incomeYear: 2026,
      openingFundEquityRatioBasisPoints: 8000,
      ownerAttested: true,
      paidDate: "2026-08-15",
      positionId,
    }, "fund-idempotency", "fund-request");
    const corrected = await correctInvestment("session-token", {
      companyId,
      correctionDate: "2026-08-31",
      correctionId,
      documentStatus: "not_required",
      evidenceMode: "manual_fallback",
      evidenceReference: "correction-review",
      incomeYear: 2026,
      originalActionId: dividendActionId,
      originalActivityKind: "dividend_received",
      ownerAttested: true,
      reason: "Rettet beløp mot utbytteoppgaven.",
      replacement: {
        actionId: replacementActionId,
        companyId,
        declaredDate: "2026-08-01",
        documentStatus: "not_required",
        evidenceMode: "manual_fallback",
        evidenceReference: "replacement-dividend-advice",
        grossAmount: { amount: "130.00", currency: "NOK" },
        groupExceptionClaimed: false,
        incomeYear: 2026,
        lawfulDividendConfirmed: true,
        ownerAttested: true,
        paidDate: "2026-08-15",
        payingCompanyName: "Portfolio AS",
        positionId,
        taxTreatment: "fritaksmetoden",
      },
    }, "correction-idempotency", "correction-request");
    const positions = await loadInvestmentPositions("session-token", [companyId], "position-request");
    const activity = await loadInvestmentActivity("session-token", [companyId], "activity-request");
    const lots = await loadInvestmentAcquisitionLots("session-token", [companyId], "lot-request");
    const allocations = await loadInvestmentShareSaleAllocations(
      "session-token", [companyId], "allocation-request",
    );
    const corrections = await loadInvestmentCorrections(
      "session-token", [companyId], "corrections-request",
    );

    assert.equal(recorded.accountingEntryId, entryId);
    assert.equal(recordedSale.actionId, saleActionId);
    assert.equal(recordedDividend.taxableAddBack.amount, "3.77");
    assert.equal(recordedFundDistribution.totalTaxableIncome.amount, "22.40");
    assert.equal(corrected.reversalAccountingEntryId, reversalEntryId);
    assert.deepEqual(positions, [position()]);
    assert.equal(activity[0].id, dividendActionId);
    assert.deepEqual(lots, [lot()]);
    assert.deepEqual(allocations, [allocation()]);
    assert.deepEqual(corrections, [correction()]);
    assert.equal(calls.length, 11);
    assert.match(calls[0].url, /\/api\/v1\/investments\/share-purchases$/u);
    assert.match(calls[1].url, /\/api\/v1\/investments\/share-sales$/u);
    assert.match(calls[2].url, /\/api\/v1\/investments\/received-dividends$/u);
    assert.match(calls[3].url, /\/api\/v1\/investments\/received-fund-distributions$/u);
    assert.match(calls[4].url, /\/api\/v1\/investments\/corrections$/u);
    assert.match(calls[6].url, /cursor=opaque-next/u);
    assert.match(calls[7].url, /\/api\/v1\/investments\/activity/u);
    assert.match(calls[9].url, /\/api\/v1\/investments\/share-sale-allocations/u);
    assert.match(calls[10].url, /\/api\/v1\/investments\/corrections/u);
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
    const correctionHeaders = new Headers(calls[4].request.headers);
    assert.equal(correctionHeaders.get("Idempotency-Key"), "correction-idempotency");
    assert.equal(correctionHeaders.get("X-Request-ID"), "correction-request");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  }
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
    movements: [{ movement_type: "purchase" }],
    name: "Portfolio AS",
    org_number: "999888777",
    share_count: 100,
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
    original_share_count: 100,
    original_tax_basis: 50000,
    position_id: positionId,
    remaining_cost_basis: 50000,
    remaining_share_count: 100,
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
  assert.deepEqual(presentShareSaleAllocations([allocation()])[0], {
    allocated_book_cost_basis: 20000,
    allocated_cost_basis: 20000,
    allocated_net_proceeds: 25000,
    allocated_share_count: 40,
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
    bank_transaction_id: null,
    company_id: companyId,
    created_at: "2026-08-31T12:00:00Z",
    created_by: actorId,
    document_id: null,
    document_status: "not_required",
    evidence_digest: "f".repeat(64),
    evidence_mode: "manual_fallback",
    evidence_reference: "correction-review",
    id: correctionId,
    income_year: 2026,
    original_action_id: dividendActionId,
    original_activity_kind: "dividend_received",
    owner_attested: true,
    reason: "Rettet beløp mot utbytteoppgaven.",
    replacement_accounting_entry_id: replacementEntryId,
    replacement_action_id: replacementActionId,
    replacement_activity_kind: "dividend_received",
    reversal_accounting_entry_id: reversalEntryId,
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
