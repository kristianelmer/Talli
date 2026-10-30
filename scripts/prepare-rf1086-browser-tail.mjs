/** Fixed topology bootstrap for a fresh owned local browser diagnostic only. */
import { readFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import pg from "pg";
import { isLoopbackPostgresUrl } from "../tests/support/supabase_fixture_safety.mjs";

const writers = [
  "corporate_governance.prepare_owner_dividend_finalization_v1(jsonb,text)",
  "corporate_governance.complete_owner_dividend_finalization_v1(jsonb,text)",
  "corporate_governance.prepare_owner_dividend_payment_v1(jsonb,text)",
  "corporate_governance.complete_owner_dividend_payment_v1(jsonb,text)",
  "corporate_governance.finalize_annual_close_v1(jsonb,text)",
];
async function guardedWriters(database) {
  const { rows } = await database.query(`select p.oid::text as oid,
    p.proowner::regrole::text as owner,pg_catalog.md5(p.prosrc) as body_hash,
    p.prosecdef,p.proconfig,
    pg_catalog.left(p.prosrc,pg_catalog.length(E'BEGIN\n  -- rf193-company-write-guard-v1\n'))
      =E'BEGIN\n  -- rf193-company-write-guard-v1\n' as guarded
    from pg_catalog.pg_proc p where p.oid=any($1::regprocedure[]) order by p.oid`, [writers]);
  if (rows.length !== writers.length || rows.some(row => !row.guarded || !row.prosecdef)) {
    throw new Error("browser_bootstrap_rf_writer_guard_missing");
  }
  return rows;
}

// Explicit subprocess/SQL ports make ordering/failure tests resource-free.
export async function prepareRf1086BrowserTail({ database, run }) {
  run(["node", "scripts/rehearse-authority-topology.mjs", "rollback"]);
  run(["npm", "run", "test:ledger-hosted-migration-authority"], { TALLI_LEDGER_HOSTED_AUTHORITY_REHEARSAL: "1" });
  run(["npm", "run", "test:corporate-governance-database-lifecycle"]);
  await database.query(await readFile(new URL("../supabase/contract-migrations/20260905013000_billing_contract.sql", import.meta.url), "utf8"));
  run(["node", "scripts/rehearse-governance-contract.mjs"]);
  run(["node", "scripts/rehearse-authority-topology.mjs", "recutover"]);
  const before = await guardedWriters(database);
  for (const phase of ["prepare", "contract", "filing-expand", "filing-contract"]) {
    run(["node", "scripts/rehearse-tax-topology.mjs", phase]);
  }
  run(["node", "scripts/rehearse-accounts-topology.mjs", "activate"]);
  const after = await guardedWriters(database);
  if (JSON.stringify(after) !== JSON.stringify(before)) {
    throw new Error("browser_bootstrap_rf_writer_guard_changed");
  }
  run(["node", "scripts/activate-rf-source-runtime.mjs"]);
}

async function main() {
  if (process.argv.length !== 2 || !isLoopbackPostgresUrl(process.env.DATABASE_URL)
      || !process.env.TALLI_SUPABASE_WORKDIR) {
    throw new Error("browser_bootstrap_requires_owned_loopback_workdir");
  }
  const database = new pg.Client({ connectionString: process.env.DATABASE_URL,
    connectionTimeoutMillis: 10000, query_timeout: 125000 });
  let failure;
  try {
    await database.connect();
    await prepareRf1086BrowserTail({ database, run(args, extra = {}) {
      const command = args[0] === "node" ? process.execPath : args[0];
      console.log(`RF10_BOOTSTRAP:${args.join(" ")}`);
      const result = spawnSync(command, args.slice(1), { stdio: "inherit", env: { ...process.env, ...extra } });
      if (result.error || result.status !== 0) {
        throw Object.assign(new Error("browser_bootstrap_child_failed"),
          { exitStatus: Number.isInteger(result.status) && result.status > 0 ? result.status : 1 });
      }
    } });
  } catch (error) { failure = error; }
  try { await database.end(); } catch (error) { failure ??= error; }
  if (failure) throw failure;
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch(error => {
    const labels = new Set(["browser_bootstrap_requires_owned_loopback_workdir", "browser_bootstrap_child_failed",
      "browser_bootstrap_rf_writer_guard_missing", "browser_bootstrap_rf_writer_guard_changed"]);
    console.error(labels.has(error.message) ? error.message : "browser_bootstrap_failed");
    process.exitCode = error.exitStatus ?? 1;
  });
}
