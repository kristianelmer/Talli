import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const forward = await readFile(
  new URL(
    "../supabase/migrations/20260830093000_current_legal_evidence.sql",
    import.meta.url,
  ),
  "utf8",
);
const rollback = await readFile(
  new URL(
    "../supabase/rollback/20260830093000_current_legal_evidence.sql",
    import.meta.url,
  ),
  "utf8",
);

test("current legal evidence is reconciled without rewriting history", () => {
  for (const value of [
    "2026-08-30",
    "afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04",
    "1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a",
    "041a65be9f020c037bd65b7097e04afdbeb2c944ef45d7bef3dd380e92f907de",
  ]) {
    assert.match(forward, new RegExp(value, "u"));
  }
  assert.match(forward, /not valid/iu);
  assert.match(forward, /drop constraint if exists[\s\S]+add constraint/iu);
  assert.match(forward, /grant company_access_executor[\s\S]+set role company_access_executor[\s\S]+reset role[\s\S]+revoke company_access_executor/iu);
  assert.match(forward, /append_company_agreement_acceptance[\s\S]+revoke all on function/iu);
  assert.match(forward, /create_company_workspace_with_acceptance[\s\S]+revoke all on function/iu);
});

test("rollback preserves evidence and fails closed", () => {
  assert.doesNotMatch(rollback, /delete\s+from|drop\s+table/iu);
  assert.match(rollback, /select false/iu);
  assert.match(rollback, /with check \(false\)/iu);
  assert.match(rollback, /company access appends current agreement evidence/iu);
  assert.match(rollback, /company_access_reaccept_agreement[\s\S]+owner to current_user/iu);
  assert.match(rollback, /company_access_admit_company_year[\s\S]+owner to current_user/iu);
  assert.match(rollback, /append_company_agreement_acceptance[\s\S]+revoke all on function/iu);
  assert.match(rollback, /create_company_workspace_with_acceptance[\s\S]+revoke all on function/iu);
  assert.match(rollback, /ledger_store_owner, ledger_workflow_store_owner/iu);
  assert.doesNotMatch(rollback, /2026-07-17|2026-07-15/iu);
});
