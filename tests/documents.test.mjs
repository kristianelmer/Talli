import assert from "node:assert/strict";
import test from "node:test";

import {
  COMPANY_DOCUMENTS_BUCKET,
  documentStorageKey,
  validateDocumentUpload,
} from "../apps/web/app/lib/documents.ts";

test("document storage key scopes object by company, year, and document id", () => {
  assert.equal(COMPANY_DOCUMENTS_BUCKET, "company-documents");
  assert.equal(
    documentStorageKey("company-123", 2025, "doc-456", "Bank utskrift desember.pdf"),
    "company-123/2025/doc-456/Bank-utskrift-desember.pdf",
  );
});

test("document storage key strips unsafe filename characters", () => {
  assert.equal(
    documentStorageKey("company-123", 2025, "doc-456", "../../../secret file?.pdf"),
    "company-123/2025/doc-456/secret-file-.pdf",
  );
});

test("document upload accepts a bounded PDF based on signature, not only browser MIME", () => {
  assert.deepEqual(
    validateDocumentUpload({
      name: "bilag.pdf",
      contentType: "application/octet-stream",
      size: 1024,
      header: new TextEncoder().encode("%PDF-"),
    }),
    { name: "bilag.pdf", contentType: "application/pdf", size: 1024 },
  );
});

test("document upload rejects non-PDF content and oversized files", () => {
  assert.throws(
    () =>
      validateDocumentUpload({
        name: "bilag.pdf",
        contentType: "application/pdf",
        size: 1024,
        header: new TextEncoder().encode("<html"),
      }),
    /gyldig PDF/,
  );
  assert.throws(
    () =>
      validateDocumentUpload({
        name: "bilag.pdf",
        contentType: "application/pdf",
        size: 10 * 1024 * 1024 + 1,
        header: new TextEncoder().encode("%PDF-"),
      }),
    /10 MB/,
  );
});
