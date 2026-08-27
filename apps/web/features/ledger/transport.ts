import {
  createTalliApiClient,
  type LedgerAdministrativeCostWire,
  type LedgerEntryViewWire,
  type LedgerLockPeriodWire,
  type LedgerManualJournalWire,
  type LedgerPeriodLockWire,
  type NewYearStartWire,
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

function mutationRequest(idempotencyKey: string, requestId?: string) {
  return { ...request(requestId), idempotencyKey };
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
    if (!next || seen.has(next)) {
      throw new Error("Ledger cursor progression is invalid.");
    }
    seen.add(next);
    cursor = next;
  }
  throw new Error("Ledger query exceeded its bounded page budget.");
}

export async function loadLedgerEntries(
  accessToken: string,
  companyIds: readonly string[],
  requestId?: string,
): Promise<LedgerEntryViewWire[]> {
  if (companyIds.length === 0) return [];
  const api = client(accessToken);
  return loadAllPages((cursor) => api.ledgerListEntries({
    companyIds,
    cursor,
    limit: PAGE_LIMIT,
    ...request(requestId),
  }));
}

export async function loadLedgerPeriodLocks(
  accessToken: string,
  companyIds: readonly string[],
  requestId?: string,
): Promise<LedgerPeriodLockWire[]> {
  if (companyIds.length === 0) return [];
  const api = client(accessToken);
  return loadAllPages((cursor) => api.ledgerListPeriodLocks({
    companyIds,
    cursor,
    limit: PAGE_LIMIT,
    ...request(requestId),
  }));
}

export function startNewYear(
  accessToken: string,
  command: NewYearStartWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).ledgerStartNewYear(
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export function postLedgerAdministrativeCost(
  accessToken: string,
  command: LedgerAdministrativeCostWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).ledgerPostAdministrativeCost(
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export function postLedgerManualJournal(
  accessToken: string,
  command: LedgerManualJournalWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).ledgerPostManualJournal(
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export function lockLedgerPeriod(
  accessToken: string,
  command: LedgerLockPeriodWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).ledgerLockPeriod(
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}
