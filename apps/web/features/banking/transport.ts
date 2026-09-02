import {
  createTalliApiClient,
  type AcceptBankSuggestionWire,
  type AcceptBankFileWire,
  type AcceptedBankSuggestionWire,
  type BankStatementImportResultWire,
  type BankStatementImportWire,
  type BankFilePreviewResultWire,
  type BankFilePreviewWire,
  type BankConnectionActionWire,
  type BankConnectionListWire,
  type BankConnectionWire,
  type BankConsentRedirectWire,
  type BankingConnectionCallbackRequest,
  type BankSyncResultWire,
  type BankSyncWire,
  type StartBankConnectionWire,
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

export function previewBankSourceFile(
  accessToken: string,
  command: BankFilePreviewWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<BankFilePreviewResultWire> {
  return client(accessToken).bankingPreviewSourceFile(
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export function loadBankConnections(
  accessToken: string,
  companyId: string,
  requestId?: string,
): Promise<BankConnectionListWire> {
  return client(accessToken).bankingListConnections({
    companyId,
    ...request(requestId),
  });
}

export function startBankConnection(
  accessToken: string,
  command: StartBankConnectionWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<BankConsentRedirectWire> {
  return client(accessToken).bankingStartConnection(
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export function completeBankConnection(
  accessToken: string,
  connectionId: string,
  callback: BankingConnectionCallbackRequest,
): Promise<BankConnectionWire> {
  return client(accessToken).bankingCompleteConnection(connectionId, callback);
}

export function syncBankAccount(
  accessToken: string,
  connectionId: string,
  accountId: string,
  command: BankSyncWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<BankSyncResultWire> {
  return client(accessToken).bankingSyncAccount(
    connectionId,
    accountId,
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export function revokeBankConnection(
  accessToken: string,
  connectionId: string,
  command: BankConnectionActionWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<void> {
  return client(accessToken).bankingRevokeConnection(
    connectionId,
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export function acceptBankSourceFile(
  accessToken: string,
  sourceFileId: string,
  command: AcceptBankFileWire,
  idempotencyKey: string,
  requestId?: string,
): Promise<BankStatementImportResultWire> {
  return client(accessToken).bankingAcceptSourceFile(
    sourceFileId,
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
