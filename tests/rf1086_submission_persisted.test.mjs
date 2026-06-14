import assert from "node:assert/strict";
import test from "node:test";

import { buildNoActivityRf1086Case, renderRf1086PreviewWithPython } from "../app/lib/rf1086.ts";
import {
  assertRf1086SimulationConfirmations,
  simulateRf1086SubmissionWithPython,
} from "../app/lib/rf1086-submission.ts";

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
  const rendered = renderRf1086PreviewWithPython(buildNoActivityRf1086Case(company, setup, shareholders));
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
