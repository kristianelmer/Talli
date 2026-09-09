/** Exact #150 dependency ordering around the unchanged predecessor Billing lane. */
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import pg from "pg";
import { isLoopbackPostgresUrl } from "../tests/support/supabase_fixture_safety.mjs";

const AUTHORITY = "20260909120610_authority_connections_capability.sql";
const OPERATIONS = "20260909123709_authority_operations_capability.sql";
const RF = "20260909125113_legacy_rf1086_authority_relocation.sql";
const CONTRACT = "20260909124659_authority_connections_contract.sql";
const SIGNOFF_CONTRACT = "20260909125250_backend_system_launch_signoffs_contract.sql";

export async function rehearseAuthorityTopology({ direction, database, loadSql = (relative) => readFile(new URL(`../supabase/${relative}`, import.meta.url), "utf8") }) {
  if (!new Set(["rollback", "recutover"]).has(direction)) throw new Error("invalid_authority_rehearsal_direction");
  const state = await database.query(`select c.relkind::text kind from pg_catalog.pg_class c
    join pg_catalog.pg_namespace n on n.oid=c.relnamespace
    where n.nspname='public' and c.relname='system_user_requests'`);
  const kind = state.rows[0]?.kind ?? null;
  if (direction === "rollback" && kind !== null && kind !== "v") throw new Error("authority_overlap_topology_required");
  if (direction === "recutover" && kind !== "r") throw new Error("authority_predecessor_topology_required");
  const files = direction === "rollback"
    ? [...(kind === null ? [`rollback/${CONTRACT}`] : []), `rollback/${RF}`, `rollback/${OPERATIONS}`, `rollback/${AUTHORITY}`]
    : [`migrations/${AUTHORITY}`, `migrations/${OPERATIONS}`, `migrations/${RF}`,
      `contract-migrations/${CONTRACT}`, `contract-migrations/${SIGNOFF_CONTRACT}`];
  for (const file of files) {
    const sql = await loadSql(file);
    await database.query(sql);
  }
}

async function main() {
  const databaseUrl = process.env.DATABASE_URL;
  if (!databaseUrl || !isLoopbackPostgresUrl(databaseUrl)) throw new Error("authority_rehearsal_requires_disposable_loopback_database");
  const database = new pg.Client({ connectionString: databaseUrl });
  await database.connect();
  try {
    await rehearseAuthorityTopology({ direction: process.argv[2], database });
    console.log(`Authority predecessor topology ${process.argv[2]} completed`);
  } finally {
    await database.end();
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
}
