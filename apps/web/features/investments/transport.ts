import {
  createTalliApiClient,
  type AcquisitionLotWire,
  type InvestmentsSharePurchaseResultWire,
  type InvestmentsSharePurchaseWire,
  type InvestmentPositionWire,
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

export function recordInvestmentSharePurchase(
  accessToken: string,
  command: InvestmentsSharePurchaseWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<InvestmentsSharePurchaseResultWire> {
  return client(accessToken).investmentsRecordSharePurchase(command, {
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
