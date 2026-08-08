import { createHash } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import type { SupabaseClient } from "@supabase/supabase-js";

type PersistenceResult = { error: unknown | null };
type LookupResult<T> = { data: T | null; error: unknown | null };

type InvitationOutboxRow = {
  id: string;
  company_id: string;
  recipient_email: string;
  template: string;
  payload: Record<string, unknown>;
  status: "queued";
  created_by: string;
};

type InvitationAuditRow = {
  id: string;
  company_id: string;
  actor_id: string;
  category: string;
  action: string;
  message: string;
};

export type InvitationSideEffectStore = {
  insertOutbox(row: InvitationOutboxRow): Promise<PersistenceResult>;
  findOutbox(id: string): Promise<LookupResult<InvitationOutboxRow>>;
  insertAudit(row: InvitationAuditRow): Promise<PersistenceResult>;
  findAudit(id: string): Promise<LookupResult<InvitationAuditRow>>;
};

type SideEffectIdentity = {
  actorId: string;
  operationId: string;
  purpose: string;
};

export type InvitationOutboxInput = SideEffectIdentity & {
  companyId: string;
  recipientEmail: string;
  template: string;
  payload: Record<string, unknown>;
};

export type InvitationAuditInput = SideEffectIdentity & {
  companyId: string;
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

export function deriveInvitationSideEffectId(input: SideEffectIdentity) {
  const framed = JSON.stringify(["talli:company-access-side-effect:v1", input.actorId, input.operationId, input.purpose]);
  return uuidFromDigest(createHash("sha256").update(framed).digest());
}

function sameOutboxRow(existing: InvitationOutboxRow, expected: InvitationOutboxRow) {
  return existing.id === expected.id
    && existing.company_id === expected.company_id
    && existing.recipient_email === expected.recipient_email
    && existing.template === expected.template
    && existing.created_by === expected.created_by
    && isDeepStrictEqual(existing.payload, expected.payload);
}

function sameAuditRow(existing: InvitationAuditRow, expected: InvitationAuditRow) {
  return existing.id === expected.id
    && existing.company_id === expected.company_id
    && existing.actor_id === expected.actor_id
    && existing.category === expected.category
    && existing.action === expected.action
    && existing.message === expected.message;
}

export async function persistInvitationOutbox(
  store: InvitationSideEffectStore,
  input: InvitationOutboxInput,
) {
  const expected: InvitationOutboxRow = {
    id: deriveInvitationSideEffectId(input),
    company_id: input.companyId,
    recipient_email: input.recipientEmail,
    template: input.template,
    payload: input.payload,
    status: "queued",
    created_by: input.actorId,
  };
  const inserted = await store.insertOutbox(expected);
  if (!inserted.error) return expected.id;

  const existing = await store.findOutbox(expected.id);
  if (existing.error || !existing.data || !sameOutboxRow(existing.data, expected)) {
    throw new Error("Could not persist invitation delivery.");
  }
  return expected.id;
}

export async function persistInvitationAudit(
  store: InvitationSideEffectStore,
  input: InvitationAuditInput,
) {
  const expected: InvitationAuditRow = {
    id: deriveInvitationSideEffectId(input),
    company_id: input.companyId,
    actor_id: input.actorId,
    category: input.category,
    action: input.action,
    message: `${input.message} Forespørsels-ID: ${input.operationId}.`,
  };
  const inserted = await store.insertAudit(expected);
  if (!inserted.error) return expected.id;

  const existing = await store.findAudit(expected.id);
  if (existing.error || !existing.data || !sameAuditRow(existing.data, expected)) {
    throw new Error("Could not persist invitation audit evidence.");
  }
  return expected.id;
}

export function createInvitationSideEffectStore(
  supabase: SupabaseClient,
): InvitationSideEffectStore {
  return {
    async insertOutbox(row) {
      const { error } = await supabase.from("notification_outbox").insert(row);
      return { error };
    },
    async findOutbox(id) {
      const { data, error } = await supabase
        .from("notification_outbox")
        .select("id, company_id, recipient_email, template, payload, status, created_by")
        .eq("id", id)
        .maybeSingle();
      return { data: data as InvitationOutboxRow | null, error };
    },
    async insertAudit(row) {
      const { error } = await supabase.from("audit_events").insert(row);
      return { error };
    },
    async findAudit(id) {
      const { data, error } = await supabase
        .from("audit_events")
        .select("id, company_id, actor_id, category, action, message")
        .eq("id", id)
        .maybeSingle();
      return { data: data as InvitationAuditRow | null, error };
    },
  };
}
