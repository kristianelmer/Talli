import assert from "node:assert/strict";
import test from "node:test";

import {
  documentsActionErrorMessage,
  presentDocument,
} from "../features/documents/presentation.ts";
import { uploadDocumentObject } from "../features/documents/signed-upload.ts";

const companyId = "10000000-0000-4000-8000-000000000001";
const documentId = "20000000-0000-4000-8000-000000000001";
const actorId = "30000000-0000-4000-8000-000000000001";
const document = {
  id: documentId,
  companyId,
  incomeYear: 2026,
  documentType: "accounting_document",
  name: "Bilag.pdf",
  linkedTo: "workspace",
  status: "attached",
  retentionYears: 5,
  storageKey: `${companyId}/2026/${documentId}/Bilag.pdf`,
  contentType: "application/pdf",
  byteLength: 10,
  contentSha256: "a".repeat(64),
  createdBy: actorId,
  createdAt: "2026-09-01T12:00:00Z",
  removedAt: null,
  removalReason: null,
};

test("document presentation is a transport-only shape conversion", () => {
  assert.deepEqual(presentDocument(document), {
    id: documentId,
    company_id: companyId,
    income_year: 2026,
    document_type: "accounting_document",
    name: "Bilag.pdf",
    linked_to: "workspace",
    status: "attached",
    retention_years: 5,
    storage_key: document.storageKey,
    created_by: actorId,
    created_at: "2026-09-01T12:00:00Z",
    removed_at: null,
    removed_by: null,
    removal_reason: null,
  });
  assert.equal(documentsActionErrorMessage(new Error("secret")), "Dokumenttjenesten svarte ikke. Prøv igjen senere.");
});

function restoreEnvironment(t) {
  const originalFetch = globalThis.fetch;
  const originalUrl = process.env.TALLI_BACKEND_URL;
  t.after(() => {
    globalThis.fetch = originalFetch;
    if (originalUrl === undefined) delete process.env.TALLI_BACKEND_URL;
    else process.env.TALLI_BACKEND_URL = originalUrl;
  });
  process.env.TALLI_BACKEND_URL = "http://localhost:8000";
}

const command = {
  companyId,
  incomeYear: 2026,
  documentId,
  documentType: "accounting_document",
  linkedTo: "workspace",
  fileName: "Bilag.pdf",
  contentType: "application/pdf",
  byteLength: 10,
  headerBase64: "JVBERi0=",
  finalStatus: "attached",
};

test("signed upload uses exactly the backend-issued object and finalizes once", async (t) => {
  restoreEnvironment(t);
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url: String(url), init });
    const body = String(url).endsWith("/uploads")
      ? {
          document: { ...document, status: "staged", byteLength: null, contentSha256: null },
          bucket: "company-documents",
          storageKey: document.storageKey,
          token: "exact-token",
          signedUrl: "https://storage.invalid/exact",
        }
      : document;
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  };
  const uploaded = [];
  const result = await uploadDocumentObject({
    accessToken: "access-token",
    command,
    body: new Uint8Array([1, 2, 3]),
    port: { async upload(input) { uploaded.push(input); return { error: null }; } },
    beginIdempotencyKey: "begin-key",
    finalizeIdempotencyKey: "finalize-key",
  });
  assert.equal(result.id, documentId);
  assert.equal(requests.length, 2);
  assert.deepEqual(requests.map((request) => request.init.headers["Idempotency-Key"]), ["begin-key", "finalize-key"]);
  assert.equal(uploaded.length, 1);
  assert.equal(uploaded[0].bucket, "company-documents");
  assert.equal(uploaded[0].storageKey, document.storageKey);
  assert.equal(uploaded[0].token, "exact-token");
});

test("an ambiguous signed-transfer error is not blindly finalized", async (t) => {
  restoreEnvironment(t);
  let fetches = 0;
  globalThis.fetch = async () => {
    fetches += 1;
    return new Response(JSON.stringify({
      document: { ...document, status: "staged", byteLength: null, contentSha256: null },
      bucket: "company-documents",
      storageKey: document.storageKey,
      token: "exact-token",
      signedUrl: "https://storage.invalid/exact",
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  await assert.rejects(uploadDocumentObject({
    accessToken: "access-token",
    command,
    body: new Uint8Array([1, 2, 3]),
    port: { async upload() { return { error: { message: "ambiguous" } }; } },
    beginIdempotencyKey: "begin-key",
    finalizeIdempotencyKey: "finalize-key",
  }), /Signed document upload failed/u);
  assert.equal(fetches, 1);
});
