import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import {
  Rf1086SupabaseJournalError,
  createRf1086SupabaseJournal,
} from "../app/lib/rf1086-supabase-journal.ts";

const preview = {
  id: "12345678-1234-4234-9234-123456789abc",
  company_id: "22345678-1234-4234-9234-123456789abc",
  setup_id: "32345678-1234-4234-9234-123456789abc",
  income_year: 2025,
  filing: "aksjonærregisteroppgaven",
  status: "ready",
  issues: [],
  preview: "RF-1086 preview",
  hovedskjema_xml: "<Hovedskjema />",
  underskjema_xml: { shareholder: "<Underskjema />" },
  source: "python_rf1086_engine",
  created_at: "2026-01-01T00:00:00Z",
};

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function payloadHash() {
  return sha256(JSON.stringify({
    filing: preview.filing,
    companyId: preview.company_id,
    incomeYear: preview.income_year,
    hovedskjemaXml: preview.hovedskjema_xml,
    underskjemaXml: preview.underskjema_xml,
  }));
}

function checkpoint(overrides = {}) {
  return {
    schemaVersion: 1,
    revision: 1,
    previewId: preview.id,
    companyId: preview.company_id,
    incomeYear: 2025,
    environment: "production",
    payloadHash: payloadHash(),
    status: "submitting",
    hovedskjemaId: null,
    confirmation: null,
    calls: [
      {
        operation: "hovedskjema",
        method: "POST",
        url: "https://api.skatteetaten.no/api/aksjonaerregister/v1/2025/1086H",
        bodyHash: sha256(preview.hovedskjema_xml),
        idempotencyKey: "42345678-1234-4234-9234-123456789abc",
        documentKey: null,
        status: "prepared",
        preparedAt: "2026-07-13T18:00:00Z",
        acceptedAt: null,
        failureCode: null,
        failureMessage: null,
      },
    ],
    failureCode: null,
    failureMessage: null,
    ...overrides,
  };
}

function memoryClient(options = {}) {
  let row = options.row ?? null;
  let writes = 0;
  return {
    from(table) {
      assert.equal(table, "rf1086_authority_checkpoints");
      return {
        select() {
          return {
            eq(column, value) {
              assert.equal(column, "preview_id");
              assert.equal(value, preview.id);
              return {
                async maybeSingle() {
                  if (options.readError) return { data: null, error: options.readError };
                  return { data: structuredClone(row), error: null };
                },
              };
            },
          };
        },
      };
    },
    async rpc(name, parameters) {
      assert.equal(name, "save_rf1086_authority_checkpoint");
      if (options.writeError) return { data: null, error: options.writeError };
      const actualRevision = row?.revision ?? null;
      if (actualRevision !== parameters.p_expected_revision) {
        return { data: null, error: { code: "PT409", message: "database detail must stay private" } };
      }
      row = {
        preview_id: parameters.p_preview_id,
        company_id: parameters.p_checkpoint.companyId,
        income_year: parameters.p_checkpoint.incomeYear,
        revision: parameters.p_checkpoint.revision,
        checkpoint: structuredClone(parameters.p_checkpoint),
      };
      writes += 1;
      return { data: parameters.p_checkpoint.revision, error: null };
    },
    current() {
      return structuredClone(row);
    },
    writes() {
      return writes;
    },
  };
}

test("persists and reloads exact RF-1086 checkpoints with optimistic revisions", async () => {
  const client = memoryClient();
  const journal = createRf1086SupabaseJournal({ preview, client });
  const first = checkpoint();

  await journal.save(first, null);
  assert.deepEqual(await journal.load(preview.id), first);

  const sent = {
    ...first,
    revision: 2,
    calls: [{ ...first.calls[0], status: "sent" }],
  };
  await journal.save(sent, 1);
  assert.deepEqual(await journal.load(preview.id), sent);
  assert.equal(client.writes(), 2);
});

test("fails closed on revision conflicts and non-monotonic writes", async () => {
  const client = memoryClient();
  const journal = createRf1086SupabaseJournal({ preview, client });
  await journal.save(checkpoint(), null);

  await assert.rejects(
    journal.save(checkpoint(), null),
    (error) =>
      error instanceof Rf1086SupabaseJournalError &&
      error.code === "rf1086_supabase_journal_revision_conflict",
  );
  await assert.rejects(
    journal.save(checkpoint({ revision: 3 }), 1),
    (error) =>
      error instanceof Rf1086SupabaseJournalError &&
      error.code === "rf1086_supabase_journal_revision_invalid",
  );
});

test("rejects over-specified writes and tampered database rows", async () => {
  const client = memoryClient();
  const journal = createRf1086SupabaseJournal({ preview, client });
  await assert.rejects(
    journal.save(checkpoint({ accessToken: "must-not-be-accepted" }), null),
    /checkpoint is invalid/iu,
  );
  assert.equal(client.writes(), 0);

  const tampered = checkpoint();
  tampered.calls[0].providerBody = "must-not-be-accepted";
  const tamperedClient = memoryClient({
    row: {
      preview_id: preview.id,
      company_id: preview.company_id,
      income_year: preview.income_year,
      revision: 1,
      checkpoint: tampered,
    },
  });
  await assert.rejects(
    createRf1086SupabaseJournal({ preview, client: tamperedClient }).load(preview.id),
    /checkpoint is invalid/iu,
  );

  await assert.rejects(
    journal.save(checkpoint({ payloadHash: "0".repeat(64) }), null),
    /checkpoint is invalid/iu,
  );
  assert.throws(
    () => createRf1086SupabaseJournal({ preview: { ...preview, status: "warning" }, client }),
    /requires a persisted UUID preview/iu,
  );
});

test("maps database failures without reflecting database diagnostics", async () => {
  const readJournal = createRf1086SupabaseJournal({
    preview,
    client: memoryClient({ readError: { code: "XX000", message: "Bearer database-secret" } }),
  });
  await assert.rejects(
    readJournal.load(preview.id),
    (error) =>
      error instanceof Rf1086SupabaseJournalError &&
      error.code === "rf1086_supabase_journal_read_failed" &&
      !error.message.includes("database-secret"),
  );

  const writeJournal = createRf1086SupabaseJournal({
    preview,
    client: memoryClient({ writeError: { code: "XX000", message: "Bearer database-secret" } }),
  });
  await assert.rejects(
    writeJournal.save(checkpoint(), null),
    (error) =>
      error instanceof Rf1086SupabaseJournalError &&
      error.code === "rf1086_supabase_journal_write_failed" &&
      !error.message.includes("database-secret"),
  );
});
