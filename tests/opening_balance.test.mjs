import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

const legacyPolicy = new URL("../apps/web/app/lib/opening-balance.ts", import.meta.url);
const actions = readFileSync(new URL("../apps/web/app/actions.ts", import.meta.url), "utf8");
const contract = JSON.parse(readFileSync(
  new URL("../contracts/openapi/talli-v1.json", import.meta.url),
  "utf8",
));

test("new-year start replaces the duplicate browser opening policy", () => {
  assert.equal(existsSync(legacyPolicy), false);
  const start = actions.indexOf("export async function createOpeningBalanceSetup");
  const end = actions.indexOf("export async function lockCompanyYear", start);
  const action = actions.slice(start, end);
  assert.match(action, /startNewYear\(/u);
  assert.doesNotMatch(action, /(?:1920|2000|2050)/u);
  assert.doesNotMatch(action, /\.from\("(?:opening_balance_setups|opening_shareholders|ledger_entries)"\)/u);
  assert.match(action, /persistLedgerAudit\(/u);
  assert.match(action, /\.from\("audit_events"\)/u);
});

test("public contract accepts only new-year business facts", () => {
  const operation = contract.paths["/api/v1/new-year-starts"].post;
  assert.equal(operation.operationId, "ledgerStartNewYear");
  assert.equal(contract.paths["/api/v1/ledger/opening-balances"], undefined);
  const schemaName = operation.requestBody.content["application/json"].schema.$ref
    .split("/")
    .at(-1);
  const properties = contract.components.schemas[schemaName].properties;
  const required = contract.components.schemas[schemaName].required;
  assert.ok(properties.openingMode);
  assert.ok(properties.openingBasis);
  assert.ok(properties.openingComponents);
  assert.ok(properties.shareholders);
  assert.ok(properties.bankBalance);
  assert.ok(properties.shareCapital);
  assert.ok(required.includes("bankBalance"));
  assert.ok(required.includes("shareCapital"));
  assert.ok(!required.includes("openingMode"));
  assert.ok(!required.includes("openingBasis"));
  assert.ok(!required.includes("openingComponents"));
  assert.equal(properties.lines, undefined);
});
