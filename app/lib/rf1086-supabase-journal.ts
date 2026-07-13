import type { FilingPreviewRow } from "./supabase/server.ts";
import {
  assertRf1086AuthorityCheckpoint,
  type Rf1086AuthorityCheckpoint,
  type Rf1086AuthorityJournal,
} from "./rf1086-authority-orchestration.ts";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const MAX_CHECKPOINT_BYTES = 256 * 1024;

type SupabaseError = { code?: unknown };
type SupabaseResult = PromiseLike<{ data: unknown; error: SupabaseError | null }>;

export type Rf1086SupabaseJournalClient = {
  from(table: string): {
    select(columns: string): {
      eq(column: string, value: string): {
        maybeSingle(): SupabaseResult;
      };
    };
  };
  rpc(name: string, parameters: Record<string, unknown>): SupabaseResult;
};

export class Rf1086SupabaseJournalError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "Rf1086SupabaseJournalError";
    this.code = code;
  }
}

function journalError(code: string, message: string) {
  return new Rf1086SupabaseJournalError(code, message);
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]) {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length && actual.every((key, index) => key === wanted[index]);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function assertBoundPreview(preview: FilingPreviewRow) {
  const underskjema = preview?.underskjema_xml;
  if (
    !preview ||
    !UUID_PATTERN.test(preview.id) ||
    !UUID_PATTERN.test(preview.company_id) ||
    !Number.isInteger(preview.income_year) ||
    preview.income_year < 2000 ||
    preview.income_year > 2100 ||
    preview.filing !== "aksjonærregisteroppgaven" ||
    preview.status !== "ready" ||
    typeof preview.hovedskjema_xml !== "string" ||
    preview.hovedskjema_xml.length < 1 ||
    !underskjema ||
    typeof underskjema !== "object" ||
    Array.isArray(underskjema) ||
    Object.keys(underskjema).length < 1
  ) {
    throw journalError(
      "rf1086_supabase_journal_preview_invalid",
      "RF-1086 database journal requires a persisted UUID preview and company identity.",
    );
  }
}

function assertCheckpoint(
  value: unknown,
  preview: FilingPreviewRow,
): asserts value is Rf1086AuthorityCheckpoint {
  try {
    assertRf1086AuthorityCheckpoint(value as Rf1086AuthorityCheckpoint, preview);
    const size = Buffer.byteLength(JSON.stringify(value), "utf8");
    if (size < 1 || size > MAX_CHECKPOINT_BYTES) throw new Error("invalid");
  } catch {
    throw journalError(
      "rf1086_supabase_journal_checkpoint_invalid",
      "Stored RF-1086 authority checkpoint is invalid.",
    );
  }
}

function cloneCheckpoint(value: Rf1086AuthorityCheckpoint) {
  return structuredClone(value);
}

export function createRf1086SupabaseJournal(input: {
  preview: FilingPreviewRow;
  client: Rf1086SupabaseJournalClient;
}): Rf1086AuthorityJournal {
  assertBoundPreview(input.preview);
  if (!input.client || typeof input.client.from !== "function" || typeof input.client.rpc !== "function") {
    throw journalError(
      "rf1086_supabase_journal_client_invalid",
      "RF-1086 database journal requires a server-side Supabase client.",
    );
  }

  return {
    async load(previewId) {
      if (previewId !== input.preview.id) {
        throw journalError(
          "rf1086_supabase_journal_preview_mismatch",
          "RF-1086 database journal is bound to one preview.",
        );
      }
      let result: { data: unknown; error: SupabaseError | null };
      try {
        result = await input.client
          .from("rf1086_authority_checkpoints")
          .select("preview_id, company_id, income_year, revision, checkpoint")
          .eq("preview_id", previewId)
          .maybeSingle();
      } catch {
        throw journalError(
          "rf1086_supabase_journal_read_failed",
          "RF-1086 database journal could not be read.",
        );
      }
      if (result.error) {
        throw journalError(
          "rf1086_supabase_journal_read_failed",
          "RF-1086 database journal could not be read.",
        );
      }
      if (result.data === null) return null;
      if (
        !isRecord(result.data) ||
        !exactKeys(result.data, ["preview_id", "company_id", "income_year", "revision", "checkpoint"]) ||
        result.data.preview_id !== input.preview.id ||
        result.data.company_id !== input.preview.company_id ||
        result.data.income_year !== input.preview.income_year ||
        !Number.isSafeInteger(result.data.revision)
      ) {
        throw journalError(
          "rf1086_supabase_journal_row_invalid",
          "RF-1086 database journal returned an invalid row.",
        );
      }
      assertCheckpoint(result.data.checkpoint, input.preview);
      if (result.data.revision !== result.data.checkpoint.revision) {
        throw journalError(
          "rf1086_supabase_journal_row_invalid",
          "RF-1086 database journal returned an invalid row.",
        );
      }
      return cloneCheckpoint(result.data.checkpoint);
    },

    async save(checkpointInput, expectedRevision) {
      assertCheckpoint(checkpointInput, input.preview);
      if (
        expectedRevision !== null &&
        (!Number.isSafeInteger(expectedRevision) || expectedRevision < 1)
      ) {
        throw journalError(
          "rf1086_supabase_journal_revision_invalid",
          "RF-1086 database journal expected revision is invalid.",
        );
      }
      const nextRevision = expectedRevision === null ? 1 : expectedRevision + 1;
      if (checkpointInput.revision !== nextRevision) {
        throw journalError(
          "rf1086_supabase_journal_revision_invalid",
          "RF-1086 database journal revision must advance by one.",
        );
      }

      let result: { data: unknown; error: SupabaseError | null };
      try {
        result = await input.client.rpc("save_rf1086_authority_checkpoint", {
          p_preview_id: input.preview.id,
          p_expected_revision: expectedRevision,
          p_checkpoint: cloneCheckpoint(checkpointInput),
        });
      } catch {
        throw journalError(
          "rf1086_supabase_journal_write_failed",
          "RF-1086 database journal could not be written.",
        );
      }
      if (result.error) {
        if (result.error.code === "PT409") {
          throw journalError(
            "rf1086_supabase_journal_revision_conflict",
            "RF-1086 database journal revision conflict.",
          );
        }
        throw journalError(
          "rf1086_supabase_journal_write_failed",
          "RF-1086 database journal could not be written.",
        );
      }
      if (result.data !== checkpointInput.revision) {
        throw journalError(
          "rf1086_supabase_journal_response_invalid",
          "RF-1086 database journal returned an invalid write result.",
        );
      }
    },
  };
}
