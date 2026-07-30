import assert from "node:assert/strict";
import test from "node:test";

import { buildNoActivityRf1086Case, renderRf1086Preview } from "../apps/web/app/lib/rf1086.ts";
import {
  Rf1086ProductionAdapterDisabledError,
  assertRf1086SimulationConfirmations,
  rf1086PayloadHash,
  rf1086ReceiptMetadata,
  rf1086SubmissionFeedbackItems,
  rf1086SubmissionIdempotencyKey,
  rf1086SubmittedPayloadReference,
  rf1086SubmittedPayloadSnapshot,
  runRf1086SubmissionAdapter,
  simulateRf1086Submission,
  simulateRf1086SubmissionWithPython,
} from "../apps/web/app/lib/rf1086-submission.ts";

const company = {
  id: "company-id",
  org_number: "314259521",
  name: "Demo Holding AS",
  entity_type: "AS",
  address: "Storgata 1",
  postal_code: "0155",
  city: "OSLO",
  status_text: "aktiv",
  source: "brreg",
  created_by: "owner",
  identity_confirmed_at: "2026-01-01T00:00:00Z",
  identity_locked_at: "2026-01-01T00:00:00Z",
  created_at: "2026-01-01T00:00:00Z",
};

const setup = {
  id: "setup-id",
  company_id: "company-id",
  income_year: 2025,
  bank_balance: 30000,
  share_capital: 30000,
  share_count: 100,
  nominal_value: 300,
  locked_at: "2026-01-01T00:00:00Z",
  created_by: "owner",
};

const shareholders = [
  {
    id: "shareholder-id",
    setup_id: "setup-id",
    company_id: "company-id",
    name: "Ola Nordmann",
    shareholder_kind: "norwegian_person",
    national_id: "01017012345",
    org_number: null,
    share_count: 100,
  },
];

function readyPreview() {
  const rendered = renderRf1086Preview(buildNoActivityRf1086Case(company, setup, shareholders));
  return {
    id: "12345678-1234-1234-1234-123456789abc",
    company_id: company.id,
    setup_id: setup.id,
    income_year: setup.income_year,
    filing: rendered.filing,
    status: rendered.status,
    issues: rendered.issues,
    preview: rendered.preview,
    hovedskjema_xml: rendered.hovedskjemaXml,
    underskjema_xml: rendered.underskjemaXml,
    source: "python_rf1086_engine",
    created_at: "2026-01-01T00:00:00Z",
  };
}

test("blocks simulated submission without authority confirmation", () => {
  assert.throws(
    () => assertRf1086SimulationConfirmations({ authorityConfirmed: false, previewConfirmed: true }),
    /rett til å sende inn/,
  );
});

test("blocks simulated submission without final preview confirmation", () => {
  assert.throws(
    () => assertRf1086SimulationConfirmations({ authorityConfirmed: true, previewConfirmed: false }),
    /forhåndsvisning/,
  );
});

test("prepares deterministic simulated submission calls and receipt from persisted preview", () => {
  const first = simulateRf1086SubmissionWithPython(readyPreview(), "owner-user", {
    authorityConfirmed: true,
    previewConfirmed: true,
  });
  const retry = simulateRf1086SubmissionWithPython(readyPreview(), "owner-user", {
    authorityConfirmed: true,
    previewConfirmed: true,
  });

  assert.equal(first.status, "receipt_stored");
  assert.equal(first.receipt_id, "sim-rf1086-company-id-2025-12345678");
  assert.equal(first.calls.length, 4);
  assert.deepEqual(
    retry.calls.map((call) => call.idempotency_key),
    first.calls.map((call) => call.idempotency_key),
  );
  assert.deepEqual(retry.feedback_document_ids, ["sim-feedback-12345678"]);
});

test("simulates a persisted submission without a Python runtime", () => {
  const previous = process.env.TALLI_PYTHON_BIN;
  process.env.TALLI_PYTHON_BIN = "/definitely/missing/talli-python";
  try {
    const result = simulateRf1086Submission(readyPreview(), "owner-user", {
      authorityConfirmed: true,
      previewConfirmed: true,
    });

    assert.equal(result.status, "receipt_stored");
    assert.equal(result.receipt_id, "sim-rf1086-company-id-2025-12345678");
    assert.equal(result.calls.length, 4);
  } finally {
    if (previous === undefined) delete process.env.TALLI_PYTHON_BIN;
    else process.env.TALLI_PYTHON_BIN = previous;
  }
});

test("serverless simulation matches the verified Python request plan", () => {
  const preview = readyPreview();
  const confirmations = { authorityConfirmed: true, previewConfirmed: true };
  const serverless = simulateRf1086Submission(preview, "owner-user", confirmations);
  const verified = simulateRf1086SubmissionWithPython(preview, "owner-user", confirmations);

  assert.deepEqual(
    serverless.calls.map(({ endpoint, body_hash, idempotency_key, status }) => ({ endpoint, body_hash, idempotency_key, status })),
    verified.calls.map(({ endpoint, body_hash, idempotency_key, status }) => ({ endpoint, body_hash, idempotency_key, status })),
  );
  assert.equal(serverless.receipt_id, verified.receipt_id);
  assert.deepEqual(serverless.feedback_document_ids, verified.feedback_document_ids);
});

test("blocks production adapter even if the legacy environment flag is set", () => {
  const previous = process.env.TALLI_ENABLE_RF1086_PRODUCTION_ADAPTER;
  process.env.TALLI_ENABLE_RF1086_PRODUCTION_ADAPTER = "true";
  try {
    assert.throws(
      () =>
        runRf1086SubmissionAdapter({
          mode: "production",
          preview: readyPreview(),
          userId: "owner-user",
          confirmations: { authorityConfirmed: true, previewConfirmed: true },
        }),
      (error) => error instanceof Rf1086ProductionAdapterDisabledError && error.code === "rf1086_production_adapter_disabled",
    );
  } finally {
    if (previous === undefined) {
      delete process.env.TALLI_ENABLE_RF1086_PRODUCTION_ADAPTER;
    } else {
      process.env.TALLI_ENABLE_RF1086_PRODUCTION_ADAPTER = previous;
    }
  }
});

test("builds stable request payload hash and idempotency key", () => {
  const preview = readyPreview();

  assert.equal(rf1086PayloadHash(preview), rf1086PayloadHash(readyPreview()));
  assert.equal(rf1086SubmissionIdempotencyKey(preview), rf1086SubmissionIdempotencyKey(readyPreview()));
  assert.match(rf1086SubmissionIdempotencyKey(preview), /^rf1086:company-id:2025:/);
});

test("builds accepted receipt metadata and immutable submitted payload references", () => {
  const preview = readyPreview();
  const result = simulateRf1086SubmissionWithPython(preview, "owner-user", {
    authorityConfirmed: true,
    previewConfirmed: true,
  });

  assert.equal(rf1086SubmissionFeedbackItems(result)[0].severity, "accepted");
  assert.equal(rf1086ReceiptMetadata(result).receiptId, result.receipt_id);
  assert.equal(rf1086SubmittedPayloadReference(preview, result).payloadHash, rf1086PayloadHash(preview));
  assert.equal(rf1086SubmittedPayloadReference(preview, result).callCount, 4);
  assert.equal(rf1086SubmittedPayloadSnapshot(preview).hovedskjemaXml, preview.hovedskjema_xml);
});

test("builds rejected feedback as structured error state", () => {
  const feedback = rf1086SubmissionFeedbackItems({
    filing: "aksjonærregisteroppgaven",
    company_id: company.id,
    income_year: setup.income_year,
    status: "failed_blocked",
    authority_confirmed_by: "owner-user",
    authority_confirmed_at: "2026-01-01T00:00:00Z",
    preview_confirmed_by: "owner-user",
    preview_confirmed_at: "2026-01-01T00:00:00Z",
    calls: [],
    receipt_id: null,
    feedback_document_ids: [],
    failure_code: "RF1086_VALIDATION_BLOCKED",
    failure_message: "Mangler aksjonær.",
  });

  assert.deepEqual(feedback, [
    {
      severity: "error",
      code: "RF1086_VALIDATION_BLOCKED",
      message: "Mangler aksjonær.",
      documentId: null,
    },
  ]);
});
