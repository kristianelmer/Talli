import { createHash } from "node:crypto";

type PersistenceResult = { error: unknown | null };
type LookupResult<T> = { data: T | null; error: unknown | null };

type LedgerAuditRow = {
  id: string;
  company_id: string;
  actor_id: string;
  category: string;
  action: string;
  message: string;
};

export type LedgerAuditStore = {
  insertAudit(row: LedgerAuditRow): Promise<PersistenceResult>;
  findAudit(id: string): Promise<LookupResult<LedgerAuditRow>>;
};

export type LedgerAuditInput = {
  operationId: string;
  companyId: string;
  actorId: string;
  category: string;
  action: string;
  message: string;
};

function uuidFromDigest(digest: Buffer) {
  const bytes = Buffer.from(digest.subarray(0, 16));
  bytes[6] = (bytes[6] & 0x0f) | 0x80;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function deriveLedgerAuditId(input: LedgerAuditInput) {
  const framed = JSON.stringify([
    "talli:ledger-audit-side-effect:v1",
    input.actorId,
    input.companyId,
    input.operationId,
    input.category,
    input.action,
  ]);
  return uuidFromDigest(createHash("sha256").update(framed).digest());
}

function sameAuditRow(existing: LedgerAuditRow, expected: LedgerAuditRow) {
  return existing.id === expected.id
    && existing.company_id === expected.company_id
    && existing.actor_id === expected.actor_id
    && existing.category === expected.category
    && existing.action === expected.action
    && existing.message === expected.message;
}

export async function persistLedgerAudit(
  store: LedgerAuditStore,
  input: LedgerAuditInput,
) {
  const expected: LedgerAuditRow = {
    id: deriveLedgerAuditId(input),
    company_id: input.companyId,
    actor_id: input.actorId,
    category: input.category,
    action: input.action,
    message: input.message,
  };
  const inserted = await store.insertAudit(expected);
  if (!inserted.error) return expected.id;

  const existing = await store.findAudit(expected.id);
  if (existing.error || !existing.data || !sameAuditRow(existing.data, expected)) {
    throw new Error("Could not persist ledger audit evidence.");
  }
  return expected.id;
}
