import {
  createTalliApiClient,
  type AcquisitionLotWire,
  type InvestmentsEconomicEventResultWire,
  type InvestmentsCashSettlementResultWire,
  type InvestmentsRecognizeSharePurchaseWire,
  type InvestmentsRecognizeShareSaleWire,
  type InvestmentsRecognizeReceivedDividendWire,
  type InvestmentsRecognizeReceivedFundDistributionWire,
  type InvestmentsSettleCashWire,
  type InvestmentsYearEndMeasurementResultWire,
  type InvestmentsYearEndMeasurementWire,
  type InvestmentPositionWire,
  type InvestmentActivityWire,
  type InvestmentLifecycleEventWire,
  type ShareSaleAllocationWire,
  type InvestmentCorrectionWire,
  type InvestmentYearEndMeasurementViewWire,
  type InvestmentsCorrectionWire,
  type InvestmentsCorrectionResultWire,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

const PAGE_LIMIT = 100;
const MAX_CURSOR_PAGES = 10_000;

function client(accessToken: string) {
  return createTalliApiClient({
    baseUrl: backendBaseUrl(),
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

function request(requestId?: string) {
  return { requestId, signal: AbortSignal.timeout(10_000) };
}

async function loadAllPages<T>(
  load: (cursor: string | undefined) => Promise<{
    items: T[];
    page: { hasMore: boolean; nextCursor: string | null };
  }>,
): Promise<T[]> {
  const items: T[] = [];
  const seen = new Set<string>();
  let cursor: string | undefined;
  for (let pageNumber = 0; pageNumber < MAX_CURSOR_PAGES; pageNumber += 1) {
    const result = await load(cursor);
    items.push(...result.items);
    if (!result.page.hasMore) return items;
    const next = result.page.nextCursor;
    if (!next || seen.has(next)) throw new Error("Investments cursor progression is invalid.");
    seen.add(next);
    cursor = next;
  }
  throw new Error("Investments query exceeded its bounded page budget.");
}

export function recognizeInvestmentSharePurchase(
  accessToken: string,
  command: InvestmentsRecognizeSharePurchaseWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<InvestmentsEconomicEventResultWire> {
  return client(accessToken).investmentsRecognizeSharePurchase(command, {
    ...request(requestId),
    idempotencyKey,
  });
}

export function recognizeInvestmentShareSale(
  accessToken: string,
  command: InvestmentsRecognizeShareSaleWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<InvestmentsEconomicEventResultWire> {
  return client(accessToken).investmentsRecognizeShareSale(command, {
    ...request(requestId),
    idempotencyKey,
  });
}

export function recognizeInvestmentReceivedDividend(
  accessToken: string,
  command: InvestmentsRecognizeReceivedDividendWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<InvestmentsEconomicEventResultWire> {
  return client(accessToken).investmentsRecognizeReceivedDividend(command, {
    ...request(requestId),
    idempotencyKey,
  });
}

export function recognizeInvestmentReceivedFundDistribution(
  accessToken: string,
  command: InvestmentsRecognizeReceivedFundDistributionWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<InvestmentsEconomicEventResultWire> {
  return client(accessToken).investmentsRecognizeReceivedFundDistribution(command, {
    ...request(requestId),
    idempotencyKey,
  });
}

export function settleInvestmentCash(
  accessToken: string,
  command: InvestmentsSettleCashWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<InvestmentsCashSettlementResultWire> {
  return client(accessToken).investmentsSettleCash(command, {
    ...request(requestId),
    idempotencyKey,
  });
}

export function recordInvestmentYearEndMeasurement(
  accessToken: string,
  command: InvestmentsYearEndMeasurementWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<InvestmentsYearEndMeasurementResultWire> {
  return client(accessToken).investmentsRecordYearEndMeasurement(command, {
    ...request(requestId),
    idempotencyKey,
  });
}

export function correctInvestment(
  accessToken: string,
  command: InvestmentsCorrectionWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<InvestmentsCorrectionResultWire> {
  return client(accessToken).investmentsCorrectInvestment(command, {
    ...request(requestId),
    idempotencyKey,
  });
}

export function loadInvestmentPositions(
  accessToken: string,
  companyIds: readonly string[],
  requestId?: string,
): Promise<InvestmentPositionWire[]> {
  if (companyIds.length === 0) return Promise.resolve([]);
  const api = client(accessToken);
  return loadAllPages((cursor) => api.investmentsListPositions({
    companyIds,
    cursor,
    limit: PAGE_LIMIT,
    ...request(requestId),
  }));
}

export function loadInvestmentActivity(
  accessToken: string,
  companyIds: readonly string[],
  requestId?: string,
): Promise<InvestmentActivityWire[]> {
  if (companyIds.length === 0) return Promise.resolve([]);
  const api = client(accessToken);
  return loadAllPages((cursor) => api.investmentsListActivity({
    companyIds,
    cursor,
    limit: PAGE_LIMIT,
    ...request(requestId),
  }));
}

export function loadInvestmentEconomicEvents(
  accessToken: string,
  companyIds: readonly string[],
  requestId?: string,
): Promise<InvestmentLifecycleEventWire[]> {
  if (companyIds.length === 0) return Promise.resolve([]);
  const api = client(accessToken);
  return loadAllPages((cursor) => api.investmentsListEconomicEvents({
    companyIds,
    cursor,
    limit: PAGE_LIMIT,
    ...request(requestId),
  }));
}

export function loadInvestmentAcquisitionLots(
  accessToken: string,
  companyIds: readonly string[],
  requestId?: string,
): Promise<AcquisitionLotWire[]> {
  if (companyIds.length === 0) return Promise.resolve([]);
  const api = client(accessToken);
  return loadAllPages((cursor) => api.investmentsListAcquisitionLots({
    companyIds,
    cursor,
    limit: PAGE_LIMIT,
    ...request(requestId),
  }));
}

export function loadInvestmentShareSaleAllocations(
  accessToken: string,
  companyIds: readonly string[],
  requestId?: string,
): Promise<ShareSaleAllocationWire[]> {
  if (companyIds.length === 0) return Promise.resolve([]);
  const api = client(accessToken);
  return loadAllPages((cursor) => api.investmentsListShareSaleAllocations({
    companyIds,
    cursor,
    limit: PAGE_LIMIT,
    ...request(requestId),
  }));
}

export function loadInvestmentCorrections(
  accessToken: string,
  companyIds: readonly string[],
  requestId?: string,
): Promise<InvestmentCorrectionWire[]> {
  if (companyIds.length === 0) return Promise.resolve([]);
  const api = client(accessToken);
  return loadAllPages((cursor) => api.investmentsListCorrections({
    companyIds,
    cursor,
    limit: PAGE_LIMIT,
    ...request(requestId),
  }));
}

export function loadInvestmentYearEndMeasurements(
  accessToken: string,
  companyIds: readonly string[],
  requestId?: string,
): Promise<InvestmentYearEndMeasurementViewWire[]> {
  if (companyIds.length === 0) return Promise.resolve([]);
  const api = client(accessToken);
  return loadAllPages((cursor) => api.investmentsListYearEndMeasurements({
    companyIds,
    cursor,
    limit: PAGE_LIMIT,
    ...request(requestId),
  }));
}
