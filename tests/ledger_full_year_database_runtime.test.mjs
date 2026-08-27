import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const migrationPath = new URL(
  "../supabase/migrations/20260827101000_ledger_full_year_reconstruction.sql",
  import.meta.url,
);
const hardenedLedgerPath = new URL(
  "../supabase/migrations/20260827100000_ledger_capability.sql",
  import.meta.url,
);
const rollbackPath = new URL(
  "../supabase/rollback/20260827101000_ledger_capability_contract.sql",
  import.meta.url,
);
const additiveLedgerMigrationPaths = [
  "20260827101000_ledger_full_year_reconstruction.sql",
  "20260827102000_ledger_supported_patterns.sql",
  "20260827103000_ledger_corrections.sql",
  "20260827104000_ledger_company_year_close.sql",
  "20260827105000_ledger_received_dividend_lifecycle.sql",
  "20260827106000_ledger_bank_loan_lifecycle.sql",
  "20260827107000_ledger_cash_capital_increase_lifecycle.sql",
  "20260827108000_ledger_loss_coverage_capital_reduction_lifecycle.sql",
  "20260827109000_ledger_opening_position_rebuild.sql",
  "20260827109200_ledger_reconstruction_economic_facts.sql",
].map((name) => new URL(`../supabase/migrations/${name}`, import.meta.url));

const economicFactsPath = new URL(
  "../supabase/migrations/20260827109200_ledger_reconstruction_economic_facts.sql",
  import.meta.url,
);
const lifecyclePath = new URL("./ledger_database_runtime.test.mjs", import.meta.url);

function functionBody(source, name) {
  const match = source.match(new RegExp(
    `create\\s+or\\s+replace\\s+function\\s+ledger\\.${name}\\s*\\([\\s\\S]+?\\$function\\$\\s*;`,
    "iu",
  ));
  assert.ok(match, `missing ledger.${name}`);
  return match[0];
}

test("reconstruction evidence is immutable, tenant-scoped, and executor-only", () => {
  const source = readFileSync(migrationPath, "utf8");
  for (const table of ["reconstruction_assessments", "reconstruction_evidence"]) {
    assert.match(source, new RegExp(`alter table ledger\\.${table} force row level security`, "iu"));
    assert.match(source, new RegExp(`create trigger ${table}_immutable`, "iu"));
    assert.doesNotMatch(
      source,
      new RegExp(`grant[^;]+(?:insert|update|delete)[^;]+ledger\\.${table}[^;]+(?:authenticated|ledger_executor)`, "iu"),
    );
  }
  const record = functionBody(source, "record_reconstruction_assessment");
  assert.match(record, /company_access_is_accepted_owner_v1/iu);
  assert.match(record, /company_access_company_year_allows_consequential_v1/iu);
  assert.match(record, /ledger_idempotency_in_progress/iu);
  assert.match(record, /ledger_idempotency_key_reused/iu);
  assert.match(record, /extensions\.digest\(p_evidence::text, 'sha256'\)/iu);
  assert.match(source, /to ledger_executor/iu);
  assert.doesNotMatch(source, /to authenticated/iu);
});

test("full-year migration temporarily restores hosted migration authority and re-hardens it", () => {
  const hardenedLedger = readFileSync(hardenedLedgerPath, "utf8");
  const source = readFileSync(migrationPath, "utf8");
  const rollback = readFileSync(rollbackPath, "utf8");

  assert.match(hardenedLedger, /alter schema ledger owner to ledger_store_owner/iu);
  assert.match(
    hardenedLedger,
    /revoke create on schema ledger, backend_system from ledger_store_owner/iu,
  );
  assert.match(
    hardenedLedger,
    /revoke ledger_store_owner, ledger_workflow_store_owner, company_access_executor from %I['"],\s*current_user/iu,
  );

  const transaction = source.search(/^begin\s*;/imu);
  const temporaryMembership = source.search(
    /grant ledger_store_owner to %I['"], current_user/iu,
  );
  const temporaryCreate = source.search(
    /grant create on schema ledger to %I['"], current_user/iu,
  );
  const temporaryOwnerCreate = source.search(
    /grant create on schema ledger to ledger_store_owner/iu,
  );
  const firstLedgerTable = source.search(
    /create table ledger\.reconstruction_assessments/iu,
  );
  const lastLedgerObject = source.search(
    /create trigger reconstruction_evidence_immutable/iu,
  );
  const revokeCreate = source.search(
    /revoke create on schema ledger from %I['"], current_user/iu,
  );
  const revokeOwnerCreate = source.search(
    /revoke create on schema ledger from ledger_store_owner/iu,
  );
  const revokeMembership = source.search(
    /revoke ledger_store_owner from %I['"], current_user/iu,
  );
  const commit = source.search(/commit\s*;\s*$/imu);

  for (const [label, position] of [
    ["transaction", transaction],
    ["temporary ledger owner membership", temporaryMembership],
    ["temporary ledger schema CREATE", temporaryCreate],
    ["temporary storage-owner schema CREATE", temporaryOwnerCreate],
    ["first reconstruction table", firstLedgerTable],
    ["last reconstruction object", lastLedgerObject],
    ["ledger schema CREATE revocation", revokeCreate],
    ["storage-owner schema CREATE revocation", revokeOwnerCreate],
    ["ledger owner membership revocation", revokeMembership],
    ["transaction commit", commit],
  ]) {
    assert.notEqual(position, -1, `missing ${label}`);
  }
  assert.ok(transaction < temporaryMembership);
  assert.ok(temporaryMembership < temporaryCreate);
  assert.ok(temporaryCreate < temporaryOwnerCreate);
  assert.ok(temporaryOwnerCreate < firstLedgerTable);
  assert.ok(firstLedgerTable < lastLedgerObject);
  assert.ok(lastLedgerObject < revokeCreate);
  assert.ok(revokeCreate < revokeOwnerCreate);
  assert.ok(revokeOwnerCreate < revokeMembership);
  assert.ok(revokeMembership < commit);

  for (const table of ["reconstruction_assessments", "reconstruction_evidence"]) {
    assert.match(source, new RegExp(`alter table ledger\\.${table} enable row level security`, "iu"));
    assert.match(source, new RegExp(`alter table ledger\\.${table} force row level security`, "iu"));
    assert.doesNotMatch(
      source,
      new RegExp(
        `grant[^;]*(?:insert|update|delete)[^;]*on(?: table)? ledger\\.${table}[^;]*to (?:public|anon|authenticated|service_role|ledger_executor|ledger_workflow_executor|talli_ledger_backend)`,
        "iu",
      ),
    );
  }

  assert.doesNotMatch(
    rollback,
    /drop table(?: if exists)? ledger\.(?:reconstruction_assessments|reconstruction_evidence)/iu,
    "contract rollback must preserve reconstruction evidence for recutover",
  );
});

test("every additive ledger migration bounds hosted authority to one transaction", () => {
  for (const path of additiveLedgerMigrationPaths) {
    const source = readFileSync(path, "utf8");
    const transaction = source.search(/^begin\s*;/imu);
    const membership = source.search(/grant ledger_store_owner to %I['"], current_user/iu);
    const migratorCreate = source.search(/grant create on schema ledger to %I['"], current_user/iu);
    const ownerCreate = source.search(/grant create on schema ledger to ledger_store_owner/iu);
    const revokeMigratorCreate = source.search(/revoke create on schema ledger from %I['"], current_user/iu);
    const revokeOwnerCreate = source.search(/revoke create on schema ledger from ledger_store_owner/iu);
    const revokeMembership = source.search(/revoke ledger_store_owner from %I['"], current_user/iu);
    const commit = source.search(/commit\s*;\s*$/imu);

    for (const [label, position] of [
      ["transaction", transaction],
      ["owner membership", membership],
      ["migrator CREATE", migratorCreate],
      ["owner CREATE", ownerCreate],
      ["migrator CREATE revocation", revokeMigratorCreate],
      ["owner CREATE revocation", revokeOwnerCreate],
      ["owner membership revocation", revokeMembership],
      ["commit", commit],
    ]) {
      assert.notEqual(position, -1, `${path.pathname}: missing ${label}`);
    }
    assert.ok(transaction < membership, path.pathname);
    assert.ok(membership < migratorCreate, path.pathname);
    assert.ok(migratorCreate < ownerCreate, path.pathname);
    assert.ok(ownerCreate < revokeMigratorCreate, path.pathname);
    assert.ok(revokeMigratorCreate < revokeOwnerCreate, path.pathname);
    assert.ok(revokeOwnerCreate < revokeMembership, path.pathname);
    assert.ok(revokeMembership < commit, path.pathname);
  }
});

test("database revalidates the exact source-owner evidence topology", () => {
  const source = readFileSync(migrationPath, "utf8");
  for (const pair of [
    ["PRIOR_CLOSING_OPENING", "LEDGER"],
    ["BANK_MOVEMENTS", "BANKING"],
    ["BANK_RECONCILIATION", "BANKING"],
    ["INVESTMENTS", "INVESTMENTS"],
    ["SHAREHOLDERS", "SHAREHOLDER_REGISTER_FILING"],
    ["LOANS", "BANKING"],
    ["LOANS", "CORPORATE_GOVERNANCE"],
    ["EQUITY", "CORPORATE_GOVERNANCE"],
    ["EQUITY", "SHAREHOLDER_REGISTER_FILING"],
    ["TAX_HISTORY", "COMPANY_TAX_FILING"],
    ["CURRENT_YEAR_ACTIVITY", "LEDGER"],
    ["DOCUMENTS", "DOCUMENTS"],
    ["UNSUPPORTED_ACTIVITY_CHECK", "COMPANY_ACCESS"],
  ]) {
    assert.match(source, new RegExp(`'${pair[0]}'\\s*,\\s*'${pair[1]}'`, "u"));
  }
  assert.match(source, /jsonb_array_length\(p_evidence\) <> 13/iu);
  assert.match(source, /BANK_MOVEMENTS[\s\S]+make_date\(p_income_year, 1, 1\)/iu);
  assert.match(source, /CURRENT_YEAR_ACTIVITY[\s\S]+p_as_of/iu);
  assert.match(source, /DOCUMENTS_INCOMPLETE/iu);
  assert.match(source, /UNSUPPORTED_ACTIVITY_FOUND/iu);
});

test("reconstruction readiness binds the complete canonical economic-fact set", () => {
  const source = readFileSync(economicFactsPath, "utf8");
  for (const table of [
    "reconstruction_economic_fact_sets",
    "reconstruction_economic_facts",
  ]) {
    assert.match(source, new RegExp(`alter table ledger\\.${table} force row level security`, "iu"));
    assert.match(source, new RegExp(`create trigger ${table}_immutable`, "iu"));
  }
  const record = functionBody(source, "record_reconstruction_assessment");
  assert.match(record, /p_economic_fact_entry_ids uuid\[\]/iu);
  assert.match(record, /ledger_reconstruction_economic_facts_invalid/iu);
  assert.match(record, /coalesce\(context\.event_date, entry\.posted_at::date\)[\s\S]+between[\s\S]+make_date\(p_income_year, 1, 1\)[\s\S]+p_as_of/iu);
  assert.match(record, /source\.source_role = 'PRIMARY'/iu);
  assert.match(
    record,
    /record_reconstruction_assessment_without_state_digest_v1[\s\S]+select coalesce\(pg_catalog\.array_agg\(entry\.id/iu,
  );
  assert.match(source, /coalesce\(context\.event_date, entry\.posted_at::date\)/iu);
  assert.match(source, /get_reconstruction_economic_facts_v1/iu);
  assert.match(source, /get_reconstruction_assessment_with_economic_facts_v1/iu);
  assert.match(source, /economic_facts_digest/iu);
  assert.doesNotMatch(source, /jsonb_array_length\(p_economic_fact_entry_ids\)/iu);
});

test("fresh database rehearsal executes reconstruction replay, RLS, and gap cases", () => {
  const lifecycle = readFileSync(lifecyclePath, "utf8");
  assert.match(lifecycle, /20260827101000_ledger_full_year_reconstruction\.sql/iu);
  assert.match(lifecycle, /reconstructionCall\(\{ documentsReady: false \}\)/u);
  assert.match(lifecycle, /ledger_idempotency_key_reused/iu);
  assert.match(lifecycle, /ledger\.get_reconstruction_assessment/iu);
  assert.match(lifecycle, /ledger\.reconstruction_assessments', 'insert'/iu);
});
