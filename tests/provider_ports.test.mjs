import assert from "node:assert/strict";
import test from "node:test";

import {
  BankProviderDisabledError,
  bankWebhookReceiptKey,
  createDisabledBankProvider,
  redactBankProviderDiagnostic,
} from "../app/lib/bank-provider.ts";
import {
  DocumentExtractionDisabledError,
  createDisabledDocumentExtractionAdapter,
  normalizeDocumentExtractionResult,
  validateDocumentExtractionInput,
} from "../app/lib/document-extraction.ts";

test("bank provider port fails closed until a provider is approved", async () => {
  const adapter = createDisabledBankProvider();

  assert.equal(adapter.mode, "disabled");
  await assert.rejects(
    adapter.beginConsent({
      companyId: "company-1",
      returnUrl: "https://talli.example/bank/callback",
    }),
    (error) => error instanceof BankProviderDisabledError,
  );
  await assert.rejects(
    adapter.syncTransactions({
      companyId: "company-1",
      connectionId: "connection-1",
      cursor: null,
    }),
    (error) => error instanceof BankProviderDisabledError,
  );
});

test("bank webhook receipts are replay-safe without persisting raw provider identifiers", () => {
  const first = bankWebhookReceiptKey("provider-a", "event-123");
  const repeated = bankWebhookReceiptKey("provider-a", "event-123");
  const otherCompanyEvent = bankWebhookReceiptKey("provider-a", "event-124");

  assert.equal(first, repeated);
  assert.notEqual(first, otherCompanyEvent);
  assert.match(first, /^[a-f0-9]{64}$/);
  assert.doesNotMatch(first, /event-123/);
  assert.throws(() => bankWebhookReceiptKey("provider-a", ""), /event-ID/);
});

test("bank diagnostics redact bearer and credential material", () => {
  const diagnostic = redactBankProviderDiagnostic(
    "Authorization: Bearer abc.def.ghi access_token=secret refresh_token=also-secret",
  );

  assert.doesNotMatch(diagnostic, /abc\.def\.ghi|secret|also-secret/);
  assert.match(diagnostic, /Bearer \[REDACTED\]/);
});

test("document extraction port validates tenant scope and remains disabled", async () => {
  const input = validateDocumentExtractionInput({
    companyId: "company-1",
    documentId: "document-1",
    storageKey: "company-1/2026/document-1/invoice.pdf",
    contentType: "application/pdf",
    sha256: "a".repeat(64),
  });
  const adapter = createDisabledDocumentExtractionAdapter();

  assert.equal(input.status, "quarantined");
  assert.equal(adapter.mode, "disabled");
  await assert.rejects(adapter.extract(input), (error) => error instanceof DocumentExtractionDisabledError);
  assert.throws(
    () =>
      validateDocumentExtractionInput({
        ...input,
        storageKey: "company-2/2026/document-1/invoice.pdf",
      }),
    /selskapets lagringsområde/,
  );
});

test("extraction output is always review-required and restricted to supported fields", () => {
  const result = normalizeDocumentExtractionResult({
    providerRequestId: "request-1",
    suggestions: [
      { field: "amount", value: 990, confidence: 0.98, evidence: "Total 990,00" },
      { field: "date", value: "2026-07-13", confidence: 0.95, evidence: "13.07.2026" },
      { field: "counter_account", value: "6700", confidence: 0.8, evidence: "System service" },
    ],
  });

  assert.equal(result.status, "review_required");
  assert.equal(result.ownerConfirmationRequired, true);
  assert.throws(
    () =>
      normalizeDocumentExtractionResult({
        providerRequestId: "request-2",
        suggestions: [
          { field: "counter_account", value: "9999", confidence: 0.9, evidence: "Guess" },
        ],
      }),
    /motkonto/,
  );
});
