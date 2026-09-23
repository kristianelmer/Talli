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

test("governance review regressions run in the complete acceptance boundary", async () => {
  const packageJson = await json("package.json");

  assert.match(
    packageJson.scripts["test:boundary-contract"],
    /tests\/corporate_governance_review_fixes\.test\.mjs/u,
  );
});

test("document evidence ownership is acyclic and declared", async () => {
  const [governance, documents, registry, lifecycle, adapter, contract] = await Promise.all([
    json("apps/backend/src/talli_backend/modules/corporate_governance/module.json"),
    json("apps/backend/src/talli_backend/modules/documents/module.json"),
    text("supabase/migrations/20260902030000_documents_evidence_reference_registry.sql"),
    text("supabase/migrations/20260902100000_corporate_governance_artifact_lifecycle.sql"),
    text("apps/backend/src/talli_backend/adapters/supabase_corporate_governance.py"),
    text("supabase/contract-migrations/20260902110000_corporate_governance_contract.sql"),
  ]);

  assert.deepEqual(governance.dependencies, []);
  assert.deepEqual(documents.dependencies, []);
  assert.ok(documents.owns.tables.includes("documents.evidence_references"));
  assert.equal(
    documents.owns.migrations,
    "supabase/migrations/20260902030000_documents_evidence_reference_registry.sql; supabase/migrations/20260923102419_documents_verified_rf_evidence_retention.sql; supabase/migrations/20260923125730_documents_ledger_evidence_guard.sql",
  );
  assert.match(registry, /documents\.register_evidence_reference_v1/iu);
  assert.match(lifecycle, /backend_system\.register_corporate_governance_documents_v1/iu);
  assert.match(adapter, /backend_system\.register_corporate_governance_documents_v1/iu);
  assert.match(adapter, /backend_system\.attest_corporate_governance_signed_artifact_v1/iu);
  assert.match(adapter, /backend_system\.complete_corporate_governance_shareholder_loan_v1/iu);
  assert.doesNotMatch(lifecycle, /create trigger[^\n]*document_evidence/iu);
  assert.doesNotMatch(lifecycle, /create or replace function documents\./iu);
  assert.doesNotMatch(contract, /create or replace function documents\./iu);
  assert.doesNotMatch(contract, /documents\.has_evidence_references_v1/iu);
});

test("document evidence registration cannot forge trusted actor or owner context", async () => {
  const registry = await text(
    "supabase/migrations/20260902030000_documents_evidence_reference_registry.sql",
  );
  const registration = registry.match(
    /function documents\.register_evidence_reference_v1[\s\S]+?\$function\$;/iu,
  )?.[0];

  assert.ok(registration);
  assert.match(registration, /current_setting\('talli\.verified_actor_id', true\)/iu);
  assert.match(registration, /v_actor_id is null[\s\S]+v_actor_id <> p_actor_id/iu);
  assert.match(registration, /company_access_is_accepted_owner_v1\(p_company_id\)/iu);
  assert.doesNotMatch(
    registration,
    /set_config\(\s*'talli\.verified_actor_id'\s*,\s*p_actor_id/iu,
  );
  assert.match(
    registry,
    /grant execute on function public\.company_access_is_accepted_owner_v1\(uuid\)[\s\S]+to documents_store_owner/iu,
  );
});

test("historical document evidence uses a migration-only backfill contract", async () => {
  const [registry, lifecycle] = await Promise.all([
    text("supabase/migrations/20260902030000_documents_evidence_reference_registry.sql"),
    text("supabase/migrations/20260902100000_corporate_governance_artifact_lifecycle.sql"),
  ]);
  const backfill = lifecycle.match(
    /do \$backfill_document_evidence\$[\s\S]+?\$backfill_document_evidence\$;/iu,
  )?.[0];

  assert.ok(backfill);
  assert.match(registry, /function documents\.backfill_evidence_reference_v1/iu);
  assert.match(
    registry,
    /revoke all on function documents\.backfill_evidence_reference_v1[\s\S]+from public, anon, authenticated, service_role, documents_executor/iu,
  );
  assert.match(backfill, /documents\.backfill_evidence_reference_v1/iu);
  assert.doesNotMatch(backfill, /register_corporate_governance_evidence_v1/iu);
});

test("future annual-data compatibility scopes remain frozen without a checker bypass", async () => {
  const [registry, checker, actions] = await Promise.all([
    json("architecture/compatibility.json"),
    text("scripts/check-architecture.mjs"),
    text("apps/web/app/actions.ts"),
  ]);
  const annualCompliance = registry.records.find(
    (record) => record.id === "compat-annual-compliance-persistence",
  );
  assert.ok(annualCompliance);
  for (const operation of [
    "createAnnualCorporateDecisionDraft",
    "createOwnerDividendDecisionDraft",
  ]) {
    assert.ok(annualCompliance.scopes.some(
      (scope) => scope.resource === "table:annual_data"
        && scope.operation === operation,
    ));
  }
  assert.doesNotMatch(checker, /CORPORATE_DECISION_FACT_CUTOVER/u);
  assert.match(actions, /createOwnerDividendDecisionDraft[\s\S]+from\("annual_data"\)/u);
  assert.match(actions, /createAnnualCorporateDecisionDraft[\s\S]+from\("annual_data"\)/u);
});

test("canonical decision payloads share one serializer", async () => {
  const service = await text(
    "apps/backend/src/talli_backend/modules/corporate_governance/service.py",
  );

  assert.equal(
    [...service.matchAll(/def _canonical_decision_payload\(/gu)].length,
    1,
  );
  assert.equal(
    [...service.matchAll(/["']financial_totals["']:/gu)].length,
    1,
  );
});
