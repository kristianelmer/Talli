import {
  createTalliApiClient,
  type AcceptBankSuggestionWire,
  type AcceptedBankSuggestionWire,
  type BankStatementImportResultWire,
  type BankStatementImportWire,
  type BankSuggestionAcceptancePageWire,
  type BankTransactionPageWire,
  type BankTransactionWire,
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
    if (!result.page.hasMore) {
      if (result.page.nextCursor !== null) {
        throw new Error("Banking cursor page is inconsistent.");
      }
      return items;
    }
    const next = result.page.nextCursor;
    if (!next || seen.has(next)) {
      throw new Error("Banking cursor progression is invalid.");
    }
    seen.add(next);
    cursor = next;
  }
  throw new Error("Banking query exceeded its bounded page budget.");
}

export function importBankStatement(
  accessToken: string,
  command: BankStatementImportWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<BankStatementImportResultWire> {
  return client(accessToken).bankingImportStatement(
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export async function loadBankTransactions(
  accessToken: string,
  companyIds: readonly string[],
  requestId?: string,
): Promise<BankTransactionWire[]> {
  if (companyIds.length === 0) return [];
  const api = client(accessToken);
  return loadAllPages((cursor): Promise<BankTransactionPageWire> => (
    api.bankingListTransactions({
      companyIds,
      cursor,
      limit: PAGE_LIMIT,
      ...request(requestId),
    })
  ));
}

export function acceptBankSuggestion(
  accessToken: string,
  command: AcceptBankSuggestionWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<AcceptedBankSuggestionWire> {
  return client(accessToken).bankingAcceptSuggestion(
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export async function loadBankSuggestionAcceptances(
  accessToken: string,
  companyIds: readonly string[],
  requestId?: string,
): Promise<AcceptedBankSuggestionWire[]> {
  if (companyIds.length === 0) return [];
  const api = client(accessToken);
  return loadAllPages((cursor): Promise<BankSuggestionAcceptancePageWire> => (
    api.bankingListSuggestionAcceptances({
      companyIds,
      cursor,
      limit: PAGE_LIMIT,
      ...request(requestId),
    })
  ));
}
