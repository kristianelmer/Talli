import assert from "node:assert/strict";
import test from "node:test";

import { buildNoActivityRf1086Case, renderRf1086PreviewWithPython } from "../app/lib/rf1086.ts";

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

test("builds RF-1086 no-activity case from persisted setup rows", () => {
  const filingCase = buildNoActivityRf1086Case(company, setup, shareholders);

  assert.equal(filingCase.company.org_number, "314259521");
  assert.equal(filingCase.share_snapshot.current_share_count, 100);
  assert.equal(filingCase.shareholders[0].national_id, "01017012345");
  assert.deepEqual(filingCase.events, []);
});

test("renders persisted no-activity case through Python RF-1086 engine", async () => {
  const result = await renderRf1086PreviewWithPython(buildNoActivityRf1086Case(company, setup, shareholders));

  assert.equal(result.status, "ready");
  assert.equal(result.filing, "aksjonærregisteroppgaven");
  assert.match(result.preview, /Demo Holding AS/);
  assert.match(result.hovedskjemaXml ?? "", /RF-1086/);
  assert.equal(Object.keys(result.underskjemaXml ?? {}).length, 1);
});

test("blocks persisted setup with mismatched shareholder totals through Python engine", async () => {
  const badCase = buildNoActivityRf1086Case(company, setup, [{ ...shareholders[0], share_count: 90 }]);
  const result = await renderRf1086PreviewWithPython(badCase);

  assert.equal(result.status, "blocked");
  assert.equal(result.issues[0].code, "invalid_case");
  assert.match(result.issues[0].message, /shareholder shares/);
});
