import {
  createTalliApiClient,
  type LedgerAdministrativeCostWire,
  type LedgerCorporateDecisionFinalizationWire,
  type LedgerCompanyYearCloseAssessmentWire,
  type LedgerEntryViewWire,
  type LedgerInvestmentDividendWire,
  type LedgerInvestmentPurchaseWire,
  type LedgerInvestmentSaleWire,
  type LedgerLockPeriodWire,
  type LedgerManualJournalWire,
  type LedgerOpeningSnapshotWire,
  type LedgerOwnerDividendPaymentWire,
  type LedgerPeriodLockWire,
  type LedgerReconstructionAssessmentWire,
  type LedgerShareholderLoanWire,
  type LedgerSourceCapability,
  type LedgerTaxSettlementWire,
  type NewYearStartWire,
} from "@talli/talli-api-client";
import { backendBaseUrl } from "#backend-configuration";

const PAGE_LIMIT = 100;
const MAX_CURSOR_PAGES = 10_000;
const MAX_COMPANIES_PER_QUERY = 100;

export type LedgerEntryArchiveWire = LedgerEntryViewWire & {
  createdAt: string;
  sourceCapability: LedgerSourceCapability;
  sourceRecordId: string;
};

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

export async function loadLedgerEntriesForArchive(
  accessToken: string,
  companyIds: readonly string[],
  requestId?: string,
): Promise<LedgerEntryArchiveWire[]> {
  if (companyIds.length === 0) return [];
  const api = client(accessToken);
  const entries = await loadAllPages((cursor) => api.ledgerListEntries({
    companyIds,
    cursor,
    includeSource: true,
    limit: PAGE_LIMIT,
    ...request(requestId),
  }));
  for (const entry of entries) {
    if (
      entry.sourceCapability === undefined
      || entry.sourceCapability === null
      || typeof entry.sourceRecordId !== "string"
      || entry.sourceRecordId.length === 0
      || typeof entry.createdAt !== "string"
      || entry.createdAt.length === 0
    ) {
      throw new Error("Ledger archive facts are unavailable.");
    }
  }
  return entries as LedgerEntryArchiveWire[];
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

export function loadLedgerReconstructionAssessment(
  accessToken: string,
  companyId: string,
  incomeYear: number,
  requestId?: string,
): Promise<LedgerReconstructionAssessmentWire> {
  return client(accessToken).ledgerGetReconstructionAssessment({
    companyId,
    incomeYear,
    ...request(requestId),
  });
}

export function loadLedgerCompanyYearCloseAssessment(
  accessToken: string,
  companyId: string,
  incomeYear: number,
  requestId?: string,
): Promise<LedgerCompanyYearCloseAssessmentWire> {
  return client(accessToken).ledgerGetCompanyYearCloseAssessment({
    companyId,
    incomeYear,
    ...request(requestId),
  });
}

function companyChunks(companyIds: readonly string[]): string[][] {
  const unique = [...new Set(companyIds)];
  const chunks: string[][] = [];
  for (let start = 0; start < unique.length; start += MAX_COMPANIES_PER_QUERY) {
    chunks.push(unique.slice(start, start + MAX_COMPANIES_PER_QUERY));
  }
  return chunks;
}

function nonnegativeOre(amount: string): bigint | null {
  const match = /^(0|[1-9]\d*)(?:\.(\d{1,2}))?$/u.exec(amount);
  if (!match) return null;
  return BigInt(match[1]) * BigInt(100)
    + BigInt((match[2] ?? "").padEnd(2, "0"));
}

function openingSnapshotIsConsistent(
  snapshot: LedgerOpeningSnapshotWire,
  allowedCompanies: ReadonlySet<string>,
): boolean {
  const bank = nonnegativeOre(snapshot.bankBalance.amount);
  const capital = nonnegativeOre(snapshot.shareCapital.amount);
  const nominal = nonnegativeOre(snapshot.nominalValue.amount);
  if (
    !allowedCompanies.has(snapshot.companyId)
    || bank === null
    || capital === null
    || nominal === null
    || nominal === BigInt(0)
    || capital !== nominal * BigInt(snapshot.shareCount)
  ) return false;

  let shareholderShares = 0;
  const shareholderIds = new Set<string>();
  for (const shareholder of snapshot.shareholders) {
    const primaryIdentifierValid = shareholder.shareholderKind === "norwegian_person"
      ? /^\d{11}$/u.test(shareholder.nationalId ?? "")
      : /^\d{9}$/u.test(shareholder.orgNumber ?? "");
    if (
      shareholder.setupId !== snapshot.setupId
      || shareholder.companyId !== snapshot.companyId
      || !primaryIdentifierValid
      || shareholderIds.has(shareholder.shareholderId)
    ) return false;
    shareholderIds.add(shareholder.shareholderId);
    shareholderShares += shareholder.shareCount;
  }
  return shareholderShares === snapshot.shareCount;
}

export async function loadOpeningSnapshots(
  accessToken: string,
  companyIds: readonly string[],
  requestId?: string,
): Promise<LedgerOpeningSnapshotWire[]> {
  if (companyIds.length === 0) return [];
  const api = client(accessToken);
  const chunks = companyChunks(companyIds);
  const allowedCompanies = new Set(chunks.flat());
  const snapshots: LedgerOpeningSnapshotWire[] = [];
  for (const companyIdsChunk of chunks) {
    snapshots.push(...await loadAllPages(async (cursor) => {
      const page = await api.ledgerListOpeningSnapshots({
        companyIds: companyIdsChunk,
        cursor,
        limit: PAGE_LIMIT,
        ...request(requestId),
      });
      if (page.hasMore !== (page.nextCursor !== null)) {
        throw new Error("Opening-snapshot page is inconsistent.");
      }
      return {
        items: page.items,
        page: { hasMore: page.hasMore, nextCursor: page.nextCursor },
      };
    }));
  }

  const setupIds = new Set<string>();
  const shareholderIds = new Set<string>();
  for (const snapshot of snapshots) {
    if (
      setupIds.has(snapshot.setupId)
      || snapshot.shareholders.some((shareholder) => (
        shareholderIds.has(shareholder.shareholderId)
      ))
      || !openingSnapshotIsConsistent(snapshot, allowedCompanies)
    ) {
      throw new Error("Opening-snapshot response is inconsistent.");
    }
    setupIds.add(snapshot.setupId);
    for (const shareholder of snapshot.shareholders) {
      shareholderIds.add(shareholder.shareholderId);
    }
  }
  snapshots.sort((left, right) => (
    Date.parse(right.createdAt) - Date.parse(left.createdAt)
    || right.setupId.localeCompare(left.setupId)
  ));
  return snapshots;
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

export function postLedgerInvestmentDividend(
  accessToken: string,
  command: LedgerInvestmentDividendWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).ledgerPostInvestmentDividend(
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export function postLedgerShareholderLoan(
  accessToken: string,
  command: LedgerShareholderLoanWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).ledgerPostShareholderLoan(
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export function postLedgerTaxSettlement(
  accessToken: string,
  command: LedgerTaxSettlementWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).ledgerPostTaxSettlement(
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export function postLedgerInvestmentPurchase(
  accessToken: string,
  command: LedgerInvestmentPurchaseWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).ledgerPostInvestmentPurchase(
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export function postLedgerInvestmentSale(
  accessToken: string,
  command: LedgerInvestmentSaleWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).ledgerPostInvestmentSale(
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export function finalizeLedgerCorporateDecision(
  accessToken: string,
  command: LedgerCorporateDecisionFinalizationWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).ledgerFinalizeCorporateDecision(
    command,
    mutationRequest(idempotencyKey, requestId),
  );
}

export function postLedgerOwnerDividendPayment(
  accessToken: string,
  command: LedgerOwnerDividendPaymentWire,
  idempotencyKey: string,
  requestId?: string,
) {
  return client(accessToken).ledgerPostOwnerDividendPayment(
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
