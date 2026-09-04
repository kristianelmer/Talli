import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function text(path) {
  return readFile(new URL(path, root), "utf8");
}

async function json(path) {
  return JSON.parse(await text(path));
}

test("corporate-governance manifests declare the implemented public surface", async () => {
  const [backend, web] = await Promise.all([
    json("apps/backend/src/talli_backend/modules/corporate_governance/module.json"),
    json("apps/web/features/corporate-governance/module.json"),
  ]);

  assert.equal(
    backend.owns.migrations,
    "supabase/contract-migrations/20260902110000_corporate_governance_contract.sql",
  );
  for (const exportedType of [
    "AnnualCloseEventKind",
    "AnnualCloseLifecycle",
    "AnnualDataSourceFacts",
    "CorporateAccountMovementFacts",
    "CorporateDecisionFactSources",
    "DerivedCorporateDecisionFacts",
    "OwnerDividendEventKind",
  ]) {
    assert.ok(backend.exports.queries.includes(exportedType), exportedType);
  }
  assert.ok(
    web.apiOperations.includes("corporateGovernanceDeriveDecisionFacts"),
  );
});

test("backend workflow documentation has one canonical governance workflow", async () => {
  const documentation = await text("architecture/BACKEND-SYSTEM.md");

  assert.doesNotMatch(documentation, /The `owner-dividend-governance` workflow/iu);
  assert.match(documentation, /The `corporate-governance` workflow/iu);
});

test("lifecycle reader exposes migrated source-hash compatibility explicitly", async () => {
  const migration = await text(
    "supabase/migrations/20260902100000_corporate_governance_artifact_lifecycle.sql",
  );

  assert.equal(
    [...migration.matchAll(/'sourceHashUsesCurrentBasis'/gu)].length,
    2,
  );
});

test("local gate rehearses predecessor ledger cutover before governance retires it", async () => {
  const localGate = await text("scripts/test-supabase-local.sh");
  const ledgerAuthority = localGate.indexOf(
    "npm run test:ledger-hosted-migration-authority",
  );
  const governanceContract = localGate.indexOf(
    "npm run test:corporate-governance-database-lifecycle",
  );

  assert.notEqual(ledgerAuthority, -1);
  assert.notEqual(governanceContract, -1);
  assert.ok(ledgerAuthority < governanceContract);
});

test("complete gate uses the backend-managed Python runtime", async () => {
  const completeGate = await text("scripts/run-customer-ready-gate.mjs");

  assert.doesNotMatch(completeGate, /TALLI_PYTHON_BIN:\s*"\.venv\/bin\/python"/u);
  assert.match(
    completeGate,
    /TALLI_PYTHON_BIN:\s*"apps\/backend\/\.venv\/bin\/python"/u,
  );
});
