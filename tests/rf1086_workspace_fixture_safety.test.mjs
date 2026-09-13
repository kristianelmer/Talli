import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fixtureTableTransaction } from "./support/rf1086-fixture-access.mjs";
import { apiRequest, deniedRf } from "./support/rf1086-workspace-api.mjs";
import { TalliApiError } from "../packages/talli-api-client/src/index.ts";
import { createRfDatabaseActor } from "./support/rf1086-database-actor.mjs";

const python = process.env.TALLI_BACKEND_PYTHON_BIN || "apps/backend/.venv/bin/python";
const fixture = "tests/fixtures/start_rf1086_workspace_backend.py";
const local = {
  DATABASE_URL: "postgresql://localhost/fixture", TALLI_LEDGER_DATABASE_URL: "postgresql://localhost/fixture",
  TALLI_COMPANY_ACCESS_DATABASE_URL: "postgresql://localhost/fixture", SUPABASE_URL: "http://127.0.0.1:45001",
  TALLI_AUTHORITY_OPS_ENABLED: "false", TALLI_RF1086_PRODUCTION_ENABLED: "false",
};

for (const [name, additions, failure] of [
  ["hosted database", { DATABASE_URL: "postgresql://hosted.invalid/fixture" }, "authority_browser_fixture_requires_loopback"],
  ["hosted Supabase", { SUPABASE_URL: "https://hosted.invalid" }, "authority_browser_fixture_requires_loopback"],
  ["global RF activation", { TALLI_RF1086_PRODUCTION_ENABLED: "true" }, "workspace_fixture_provider_activation_forbidden"],
  ["global operator activation", { TALLI_AUTHORITY_OPS_ENABLED: "true" }, "workspace_fixture_provider_activation_forbidden"],
  ["ambient credential", { TALLI_PROD_MASKINPORTEN_CLIENT_ID: "synthetic-forbidden" }, "workspace_fixture_provider_credentials_forbidden"],
]) {
  test(`workspace RF backend refuses ${name} before opening a listener`, () => {
    const result = spawnSync(python, [fixture], { env: { PATH: process.env.PATH, ...local, ...additions }, encoding: "utf8", timeout: 10_000 });
    assert.notEqual(result.status, 0);
    assert.ok(result.stderr.includes(failure));
    assert.doesNotMatch(result.stdout, /TALLI_BACKEND_BOUND/u);
  });
}

test("workspace API requests use the actual current Supabase session and exact denial statuses", async () => {
  const options = await apiRequest({ auth: { getSession: async () => ({ data: { session: { access_token: "synthetic-current-owner" } }, error: null }) } }, { idempotencyKey: "original" });
  assert.deepEqual(options, { idempotencyKey: "original", headers: { Authorization: "Bearer synthetic-current-owner" } });
  await assert.rejects(apiRequest({ auth: { getSession: async () => ({ data: { session: null }, error: null }) } }));
  assert.equal(deniedRf(new TalliApiError(403)), true);
  assert.equal(deniedRf(new TalliApiError(404)), true);
  for (const status of [400, 401, 409, 422, 500, 503]) assert.equal(deniedRf(new TalliApiError(status)), false);
});

test("feedback fixture refuses hosted databases and undeclared operations before actor or SQL effects", async () => {
  const statements = [];
  const database = { query: async statement => { statements.push(statement); return { rows: [{ count: 0 }] }; } };
  await assert.rejects(createRfDatabaseActor(database, "postgresql://hosted.invalid/fixture"));
  assert.equal(statements.length, 0);
  const fixture = await createRfDatabaseActor(database, "postgresql://localhost/fixture");
  const actor = { auth: { getSession: () => { throw new Error("unexpected actor access"); } } };
  try {
    const setupCount = statements.length;
    await assert.rejects(fixture.rpc(actor, "begin_production_filing", { p_approval_id: "synthetic" }), /unapproved RF fixture SQL operation/u);
    await assert.rejects(fixture.rpc(actor, "claim_production_feedback_reconciliation", {
      p_submission_id: "synthetic", p_lease_id: "synthetic", p_actor_id: "synthetic",
    }));
    assert.equal(statements.length, setupCount);
  } finally { await fixture.close(); }
});

test("feedback fixture verifies the token owner before reading membership or connecting an actor database session", async () => {
  const database = { query: async () => ({ rows: [{ count: 0 }] }) };
  const fixture = await createRfDatabaseActor(database, "postgresql://localhost/fixture");
  const token = `synthetic.${Buffer.from(JSON.stringify({ sub: "claimed-owner" })).toString("base64url")}.synthetic`;
  let verifiedToken;
  let membershipReads = 0;
  const actor = {
    auth: {
      getSession: async () => ({ data: { session: { access_token: token } }, error: null }),
      getUser: async value => { verifiedToken = value; return { data: { user: { id: "different-verified-owner" } }, error: null }; },
    },
    from: () => { membershipReads += 1; throw new Error("unexpected membership access"); },
  };
  try {
    const result = await fixture.rpc(actor, "claim_production_feedback_reconciliation", {
      p_submission_id: "synthetic", p_lease_id: "synthetic",
    });
    assert.equal(verifiedToken, token);
    assert.equal(membershipReads, 0);
    assert.equal(result.data, null);
    assert.ok(result.error instanceof assert.AssertionError);
  } finally { await fixture.close(); }
});

test("workspace RF assertions use canonical commands and preserve sibling tax and audit rehearsals", () => {
  const source = readFileSync("tests/supabase_workspace.test.mjs", "utf8");
  const helper = readFileSync("tests/support/rf1086-workspace-api.mjs", "utf8");
  assert.doesNotMatch(source, /(?:renderRf1086Preview|runRf1086SubmissionAdapter|rf1086PayloadHash|lib\/rf1086\.ts)/u);
  for (const operation of ["rf1086GeneratePreview", "rf1086ConfirmFilingPermission", "rf1086RecordOverride",
    "rf1086ConfirmSimulation", "rf1086AddReviewComment", "rf1086AcknowledgeReviewComment"])
    assert.ok(source.includes(`"${operation}"`), operation);
  for (const assertion of ["noMfaImportError", "company_tax_evidence_mfa_required", "authorityPermissionsAfterImport, authorityPermissionsBeforeImport",
    "launchSignoffsAfterImport, launchSignoffsBeforeImport", "companyTaxAuditAfterRetry, companyTaxAuditBeforeRetry", "archive.rf1086Submissions[0].submittedPayload.hovedskjemaXml"])
    assert.ok(source.includes(assertion), assertion);
  const seed = helper.slice(helper.indexOf("export async function seedHistoricalRfOpening"), helper.indexOf("export const RF_FIXTURE_TABLES"));
  assert.doesNotMatch(seed, /insert into [^\n]*(?:filing_preview|filing_submission|approval|feedback|company_year_admission)/u);
  assert.doesNotMatch(helper, /session_replication_role/u);
  assert.match(helper, /alter role \$\{role\} nologin password null/u);
  assert.match(source, /if \(rf\) await collectCleanupError\(\(\) => rf\.close\(\)/u);
});


test("fixture access refuses external databases and undeclared relations before SQL", async () => {
  const database = { connectionParameters: { host: "remote.invalid" }, query: () => { throw new Error("unexpected SQL"); } };
  await assert.rejects(fixtureTableTransaction(database, ["public.audit_events"], async () => {}), /loopback/u);
  database.connectionParameters.host = "127.0.0.1";
  await assert.rejects(fixtureTableTransaction(database, ["auth.users"], async () => {}), /undeclared/u);
});

for (const fails of [false, true]) test(`fixture restores exact USER trigger modes on ${fails ? "rollback" : "success"} without disabling foreign keys`, async () => {
  const original = [{ name: 'quoted"trigger', mode: "O" }, { name: "disabled", mode: "D" }, { name: "replica", mode: "R" }, { name: "always", mode: "A" }];
  let current = structuredClone(original);
  const statements = [];
  const database = { connectionParameters: { host: "127.0.0.1" }, query: async statement => {
    statements.push(statement);
    if (statement.includes("select current_user principal")) return { rows: [{ principal: "postgres", bypass: true }] };
    if (statement.includes("nspacl::text acl,has_schema_privilege")) return { rows: [{ acl: "original-schema-acl", permitted: true }] };
    if (statement.includes("nspacl::text acl")) return { rows: [{ acl: "original-schema-acl" }] };
    if (statement.includes("c.relacl::text acl")) return { rows: [{ acl: "original-table-acl", forced: true, owner: "postgres", missing: [] }] };
    if (statement.includes("select relacl::text acl")) return { rows: [{ acl: "original-table-acl", forced: true }] };
    if (statement.includes("from pg_trigger")) { assert.ok(statement.includes("not tgisinternal")); return { rows: structuredClone(current) }; }
    const alteration = /^alter table "public"\."audit_events" (enable replica|enable always|enable|disable) trigger "((?:[^"]|"")+)"$/u.exec(statement);
    if (alteration) current.find(row => row.name === alteration[2].replaceAll('""', '"')).mode = { enable: "O", disable: "D", "enable replica": "R", "enable always": "A" }[alteration[1]];
    if (statement === "rollback") current = structuredClone(original);
    return { rows: [] };
  } };
  const failure = new Error("fixture operation failed");
  const action = fixtureTableTransaction(database, ["public.audit_events"], async () => {
    assert.ok(current.every(trigger => trigger.mode === "D"));
    if (fails) throw failure;
    return "fixture-result";
  });
  if (fails) await assert.rejects(action, error => error === failure);
  else assert.equal(await action, "fixture-result");
  assert.deepEqual(current, original);
  assert.equal(statements.at(-1), fails ? "rollback" : "commit");
  assert.doesNotMatch(statements.join("\n"), /session_replication_role|disable trigger (?:all|user)|no force row level security/iu);
});
