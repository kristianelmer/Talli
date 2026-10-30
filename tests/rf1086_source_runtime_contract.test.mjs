import assert from "node:assert/strict";
import { randomBytes, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import test from "node:test";
import pg from "pg";
import { isLoopbackPostgresUrl } from "./support/supabase_fixture_safety.mjs";

const name = "20261025104137_rf1086_source_runtime_v3_contract.sql";
const contract = await readFile(new URL(`../supabase/contract-migrations/${name}`, import.meta.url), "utf8");
const rollback = await readFile(new URL(`../supabase/rollback/${name}`, import.meta.url), "utf8");
const runtime = "shareholder_register_filing_executor";
const entries = [
  "shareholder_register_filing.lock_year_source_capture_v2(uuid,integer)",
  "shareholder_register_filing.append_year_source_v2(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamp with time zone)",
  "shareholder_register_filing.read_source_approval_context_v3(uuid,uuid,text,text)",
  "shareholder_register_filing.append_source_approval_v3(uuid,uuid,text,text,text,text)",
  "shareholder_register_filing.lock_source_claim_recovery_v3(uuid,text,text)",
  "shareholder_register_filing.claim_source_submission_v3(uuid,text,uuid,text,text)",
  "shareholder_register_filing.prepare_source_operation_v3(uuid,text,text,text,uuid,uuid,text,uuid,text,text)",
  "corporate_governance.read_guarded_reporting_register_evidence_v1(uuid,integer,text)",
  "corporate_governance.prepare_rf_year_source_governance_proof_v1(uuid,integer,text,text)",
];
const retired = [
  "shareholder_register_filing.append_year_source_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamp with time zone)",
  "shareholder_register_filing.append_source_approval_v1(uuid,uuid,text,text,text,text)",
  "shareholder_register_filing.append_source_approval_v2(uuid,uuid,text,text,text,text)",
  "shareholder_register_filing.claim_source_submission_v1(uuid,text,uuid,text)",
  "shareholder_register_filing.claim_source_submission_v2(uuid,text,uuid,text,text)",
  "shareholder_register_filing.prepare_source_operation_v1(uuid,text,text,text,uuid,uuid,text,text)",
  "shareholder_register_filing.prepare_source_operation_v2(uuid,text,text,text,uuid,uuid,text,uuid,text,text)",
];
const keep = [
  "shareholder_register_filing.lock_year_source_v1(uuid,integer)",
  "shareholder_register_filing.append_source_preview_v1(uuid,uuid,integer,uuid,text,text,text,text)",
  "shareholder_register_filing.bridge_source_preview_v1(uuid,text,text)",
  "shareholder_register_filing.read_source_submission_claim_v1(uuid,text,text)",
  "shareholder_register_filing.finish_source_operation_v1(uuid,uuid,text,text,text,text)",
  "shareholder_register_filing.read_source_approval_context_v2(uuid,uuid,text,text)",
];
// Superseded fresh-review context, explicitly closed by the annual binding migration.
// It is not a retained-history reader and has no current Python caller.
const baselineClosed = ["shareholder_register_filing.read_source_approval_context_v1(uuid,uuid,text)"];
const internal = [
  "shareholder_register_filing.receive_year_source_governance_proof_v1(uuid,integer,text,jsonb,text)",
  "shareholder_register_filing.invalidate_year_source_governance_proofs_v1(uuid)",
  "shareholder_register_filing.assert_year_source_v2_internal_v1(uuid,integer,text)",
  "shareholder_register_filing.source_approval_context_internal_v3(uuid,uuid,text,text)",
  "shareholder_register_filing.assert_retained_annual_readiness_v2_shape_internal_v1(text)",
  "shareholder_register_filing.source_annual_binding_internal_v2(uuid,text)",
];

function grantedFunctions(source) {
  return [...source.matchAll(/grant execute on function\s+([\s\S]*?)\s+to shareholder_register_filing_executor\s*;/gu)]
    .flatMap((match) => match[1].match(/\b(?:shareholder_register_filing|corporate_governance)\.[a-z0-9_]+\([^)]*\)/gu) ?? []);
}

test("deferred contract has the exact nine callgraph grants and no broad or provider activation", () => {
  assert.deepEqual(grantedFunctions(contract), entries);
  assert.deepEqual(grantedFunctions(rollback), []);
  assert.match(rollback, /rf1086-v3-retentive-read-only-rollback-v1, NOT pre-contract ACL restoration/u);
  assert.equal(existsSync(new URL(`../supabase/migrations/${name}`, import.meta.url)), false);
  for (const source of [contract, rollback]) {
    assert.doesNotMatch(source, /grant\s+(?:all|execute)\s+on\s+all\s+functions|create\s+(?:or replace\s+)?function|alter\s+default\s+privileges/iu);
    assert.doesNotMatch(source, /grant\s+.*?\s+to\s+(?:public|anon|authenticated|service_role)\b/iu);
    assert.doesNotMatch(source, /(?:insert into|update|delete from)\s+(?:shareholder_register_filing|corporate_governance)\./iu);
    assert.match(source, /item\.prior->>'admin'[\s\S]*item\.prior->>'inherit'[\s\S]*item\.prior->>'set'/u);
  }
});

const databaseUrl = process.env.DATABASE_URL;
const local = isLoopbackPostgresUrl(databaseUrl);
if (databaseUrl && !local) throw new Error("RF runtime contract tests require the owned loopback database");
const dbTest = (title, fn) => test(title, { skip: !databaseUrl }, async () => {
  const admin = new pg.Client({ connectionString: databaseUrl });
  try {
    await admin.connect();
    await fn(admin);
  } finally {
    await admin.end();
  }
});
async function canExecute(db, role, signature) {
  return (await db.query("select has_function_privilege($1,$2,'EXECUTE') as allowed", [role, signature])).rows[0].allowed;
}
function nullCall(signature) {
  const [name, types] = signature.slice(0, -1).split("(");
  return `select ${name}(${types.split(",").map(type => `null::${type}`).join(",")})`;
}
async function withRuntime(admin, fn) {
  const role = `rf_runtime_contract_${randomUUID().replaceAll("-", "")}`;
  const password = randomBytes(32).toString("hex");
  // Only generated hex identifiers/literals; no caller SQL or credential output.
  await admin.query(`create role "${role}" login inherit nosuperuser nocreatedb nocreaterole noreplication nobypassrls password '${password}'`);
  let db;
  try {
    await admin.query(`grant shareholder_register_filing_executor to "${role}" with inherit true,set false`);
    const url = new URL(databaseUrl);
    url.username = role; url.password = password;
    db = new pg.Client({ connectionString: url.toString() });
    await db.connect();
    assert.deepEqual((await db.query("select rolsuper,rolbypassrls,rolcreaterole from pg_roles where rolname=current_user")).rows,
      [{ rolsuper: false, rolbypassrls: false, rolcreaterole: false }]);
    await fn(db);
  } finally {
    if (db) await db.end();
    await admin.query(`revoke shareholder_register_filing_executor from "${role}"`);
    await admin.query(`drop role "${role}"`);
  }
}

dbTest("activated executor has exactly the new entrypoints; retained reads and owner-only proof delegation survive", async db => {
  for (const signature of entries) {
    assert.equal(await canExecute(db, runtime, signature), true, signature);
    for (const role of ["anon", "authenticated", "service_role"]) assert.equal(await canExecute(db, role, signature), false, `${role}: ${signature}`);
    const { rows: [row] } = await db.query("select proowner::regrole::text as owner,prosecdef,proconfig from pg_proc where oid=$1::regprocedure", [signature]);
    assert.deepEqual(row, { owner: signature.startsWith("corporate_governance.") ? "corporate_governance_store_owner" : "shareholder_register_filing_store_owner",
      prosecdef: true, proconfig: ['search_path=""'] });
  }
  for (const signature of [...retired, ...internal, ...baselineClosed]) assert.equal(await canExecute(db, runtime, signature), false, signature);
  for (const signature of keep) assert.equal(await canExecute(db, runtime, signature), true, signature);
  for (const signature of internal.slice(0, 2)) assert.equal(await canExecute(db, "corporate_governance_store_owner", signature), true);
  assert.equal(await canExecute(db, "corporate_governance_workflow_executor", entries[7]), true);
  for (const table of ["year_source_versions", "source_approval_bindings", "source_submission_bindings"]) {
    assert.equal((await db.query("select has_table_privilege($1,$2,'INSERT,UPDATE,DELETE') as allowed",
      [runtime, `shareholder_register_filing.${table}`])).rows[0].allowed, false);
  }
});

dbTest("actual restricted login reaches each new guard but cannot admit missing tenant/input facts", async admin => {
  await withRuntime(admin, async db => {
    for (const signature of entries) {
      await assert.rejects(db.query(nullCall(signature)), error => error.code === "P0001"
        && /^(?:rf1086_|corporate_governance_|company_access_)/u.test(error.message));
    }
  });
});

dbTest("actual restricted login cannot invoke old writers or internal proof issuers", async admin => {
  await withRuntime(admin, async db => {
    for (const signature of [...retired, ...internal, ...baselineClosed]) await assert.rejects(db.query(nullCall(signature)), error => error.code === "42501");
  });
});

async function catalogue(db) {
  const schemas = ["shareholder_register_filing", "corporate_governance"];
  return {
    routines: (await db.query("select oid,proowner,prosrc,prosecdef,proconfig,provolatile,proparallel from pg_proc where pronamespace=any($1::regnamespace[]) order by oid", [schemas])).rows,
    memberships: (await db.query("select roleid,member,grantor,admin_option,inherit_option,set_option from pg_auth_members order by 1,2,3")).rows,
    tables: (await db.query("select oid,relowner,relacl::text,relrowsecurity,relforcerowsecurity from pg_class where relnamespace=any($1::regnamespace[]) order by oid", [schemas])).rows,
    triggers: (await db.query("select t.oid,t.tgrelid,t.tgenabled,t.tgfoid from pg_trigger t join pg_class c on c.oid=t.tgrelid where c.relnamespace=any($1::regnamespace[]) order by t.oid", [schemas])).rows,
  };
}
dbTest("idempotent activation and retentive closure preserve bodies, owners, RLS and exact role memberships", async db => {
  const before = await catalogue(db);
  const keepAcl = async () => (await db.query("select oid,proacl::text from pg_proc where oid=any($1::regprocedure[]) order by oid", [[...keep, ...internal, ...baselineClosed]])).rows;
  const acl = await keepAcl();
  // This is the ACTIVATED profile's ACL, not the earlier owner-only staging ACL.
  const activatedAcl = (await db.query("select oid,proacl::text from pg_proc where oid=any($1::regprocedure[]) order by oid", [entries])).rows;
  await db.query(contract); await db.query(contract);
  assert.deepEqual(await catalogue(db), before);
  try {
    await db.query(rollback); await db.query(rollback);
    assert.deepEqual(await catalogue(db), before);
    for (const signature of [...entries.filter(entry => entry !== entries[4]), ...retired, ...baselineClosed]) assert.equal(await canExecute(db, runtime, signature), false);
    assert.equal(await canExecute(db, runtime, entries[4]), true); // newly enabled at activation; intentionally retained for historical recovery
    for (const signature of keep) assert.equal(await canExecute(db, runtime, signature), true);
    await withRuntime(db, async restricted => {
      await assert.rejects(restricted.query(nullCall(entries[0])), error => error.code === "42501");
      await assert.rejects(restricted.query(nullCall(entries[4])), error => error.code === "P0001");
    });
  } finally {
    await db.query(contract);
  }
  assert.deepEqual(await catalogue(db), before);
  assert.deepEqual(await keepAcl(), acl);
  for (const signature of entries) assert.equal(await canExecute(db, runtime, signature), true);
  for (const signature of retired) assert.equal(await canExecute(db, runtime, signature), false);
  assert.deepEqual((await db.query("select oid,proacl::text from pg_proc where oid=any($1::regprocedure[]) order by oid", [entries])).rows, activatedAcl);
});
