import {
  createTalliApiClient,
  TalliApiError,
  type RfCompanyTestRetentionRecordWire,
  type RfCompanyTestRetentionWire,
} from "@talli/talli-api-client";
import { backendClientOptions } from "#backend-configuration";

const pageSize = 50;
const canonicalCompany = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;

export function isCompanyTestHistoryCompany(value: string) {
  return canonicalCompany.test(value) && value !== "00000000-0000-0000-0000-000000000000";
}

export function companyTestHistoryHref(companyId: string, page = 1) {
  if (!isCompanyTestHistoryCompany(companyId) || !Number.isInteger(page) || page < 1 || page > 2000) {
    throw new TalliApiError(400, undefined);
  }
  const path = `/companies/${companyId}/rf1086-test-history`;
  return page === 1 ? path : `${path}?page=${page}`;
}

export function companyTestHistoryPageNumber(value: string | string[] | undefined) {
  if (value === undefined) return 1;
  if (typeof value !== "string" || !/^[1-9][0-9]{0,3}$/u.test(value) || Number(value) > 2000) return null;
  return Number(value);
}

export async function loadCompanyTestHistory(accessToken: string, companyId: string, requestId: string) {
  if (!isCompanyTestHistoryCompany(companyId)) throw new TalliApiError(400, undefined);
  const client = createTalliApiClient({
    ...backendClientOptions(), headers: { Authorization: `Bearer ${accessToken}` },
  });
  return client.rf1086ReadCompanyTestRetention(companyId, {
    requestId, signal: AbortSignal.timeout(30_000),
  });
}

export async function downloadCompanyTestHistory(
  accessToken: string, companyId: string, signal: AbortSignal, requestId: string,
) {
  if (!isCompanyTestHistoryCompany(companyId)) throw new TalliApiError(400, undefined);
  const client = createTalliApiClient({
    ...backendClientOptions(), headers: { Authorization: `Bearer ${accessToken}` },
  });
  return client.rf1086DownloadCompanyTestRetention(companyId, {
    requestId, signal: AbortSignal.any([signal, AbortSignal.timeout(300_000)]),
  });
}

export function companyTestHistoryPage(value: RfCompanyTestRetentionWire, page: number) {
  if (!Number.isInteger(page) || page < 1 || page > 2000) throw new TalliApiError(400, undefined);
  if (value.coverage === "unavailable") return { kind: "unavailable" as const };
  const pageCount = Math.max(1, Math.ceil(value.recordCount / pageSize));
  if (page > pageCount) return { kind: "out_of_range" as const, recordCount: value.recordCount };
  const offset = (page - 1) * pageSize;
  return {
    kind: "complete" as const, recordCount: value.recordCount,
    observedAt: value.observedAt, recordsSha256: value.recordsSha256,
    page, pageCount, firstRecord: value.recordCount === 0 ? 0 : offset + 1,
    lastRecord: Math.min(offset + pageSize, value.recordCount),
    records: value.records.slice(offset, offset + pageSize),
  };
}

export const companyTestHistoryRecordFields: ReadonlyArray<readonly [keyof RfCompanyTestRetentionRecordWire, string]> = [
  ["id", "Postens ID"], ["company_id", "Selskapets ID"], ["obligation", "Rapportering"],
  ["environment", "Miljø"], ["status", "Registrert status"], ["test_reference", "Testreferanse"],
  ["feedback_summary", "Tilbakemelding"], ["receipt_reference", "Kvitteringsreferanse"],
  ["archive_reference", "Arkivreferanse"], ["evidence_url", "Oppgitt kildeadresse"],
  ["payload_hash", "Opprinnelig hash"], ["recorded_by", "Registrert av"], ["recorded_at", "Registreringstid"],
];
