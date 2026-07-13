import assert from "node:assert/strict";
import test from "node:test";

import {
  COMPANY_DOCUMENTS_BUCKET,
  MAX_DOCUMENT_UPLOAD_BYTES,
  documentStorageKey,
  validateDocumentUpload,
} from "../app/lib/documents.ts";

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

test("document upload derives canonical MIME type from file bytes", async () => {
  const pdf = new File(
    [new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x37])],
    "receipt.pdf",
    { type: "text/html" },
  );
  const png = new File(
    [new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])],
    "scan.png",
    { type: "application/octet-stream" },
  );

  assert.deepEqual(await validateDocumentUpload(pdf), {
    contentType: "application/pdf",
    fileName: "receipt.pdf",
  });
  assert.deepEqual(await validateDocumentUpload(png), {
    contentType: "image/png",
    fileName: "scan.png",
  });
});

test("document upload rejects spoofed, binary CSV, and oversized files", async () => {
  await assert.rejects(
    () => validateDocumentUpload(new File(["<script>"], "spoofed.pdf", { type: "application/pdf" })),
    /ekte PDF-, PNG-, JPEG- eller UTF-8 CSV-fil/,
  );
  await assert.rejects(
    () => validateDocumentUpload(new File([new Uint8Array([0x61, 0x00, 0x62])], "binary.csv")),
    /ekte PDF-, PNG-, JPEG- eller UTF-8 CSV-fil/,
  );
  await assert.rejects(
    () => validateDocumentUpload(new File([new Uint8Array(MAX_DOCUMENT_UPLOAD_BYTES + 1)], "large.pdf")),
    /større enn 6 MB/,
  );
});
