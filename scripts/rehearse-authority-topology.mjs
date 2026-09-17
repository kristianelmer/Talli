/** Exact disposable #150/#151 test phases; each SQL file owns its transaction. */
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import pg from "pg";
import { isLoopbackPostgresUrl } from "../tests/support/supabase_fixture_safety.mjs";

const AUTHORITY = "20260909120610_authority_connections_capability.sql";
const OPERATIONS = "20260909123709_authority_operations_capability.sql";
const RF = "20260909125113_legacy_rf1086_authority_relocation.sql";
const CONTRACT = "20260909124659_authority_connections_contract.sql";
const SIGNOFF_CONTRACT = "20260909125250_backend_system_launch_signoffs_contract.sql";
const RF151 = "20260909190548_shareholder_register_filing_capability.sql";
const RF151_CUTOVER = "20260909190905_shareholder_register_filing_cutover.sql";
const RF151_CONTRACT = "20260909190955_shareholder_register_filing_contract.sql";
const RF193_READ_RECOVERY = "20260917110951_rf1086_action_required_read_recovery.sql";

async function topology(database) {
  const { rows: [state] } = await database.query(`select
    to_regclass('shareholder_register_filing.migration_state') is not null as rf_owned,
    (select c.relkind::text from pg_class c join pg_namespace n on n.oid=c.relnamespace
      where n.nspname='public' and c.relname='system_user_requests') as authority_kind,
    (select c.relkind::text from pg_class c join pg_namespace n on n.oid=c.relnamespace
      where n.nspname='public' and c.relname='ledger_entries') as ledger_kind,
    (select c.relkind::text from pg_class c join pg_namespace n on n.oid=c.relnamespace
      where n.nspname='public' and c.relname='opening_balance_setups') as opening_kind,
    exists(select 1 from pg_attribute where attrelid=to_regclass('ledger.entries')
      and attname='setup_id' and not attisdropped) as ledger_setup`);
  return state;
}

export async function rehearseAuthorityTopology({ direction, database, loadSql = (relative) => readFile(new URL(`../supabase/${relative}`, import.meta.url), "utf8") }) {
  if (!new Set(["rollback", "workspace", "recutover"]).has(direction)) throw new Error("invalid_authority_rehearsal_direction");
  let state = await topology(database);
  const apply = async (files) => { for (const file of files) await database.query(await loadSql(file)); };
  if (direction === "rollback") {
    // The exact RF full rollback restores #150 routines and original openings.
    // Never run the frozen #150 rollback against a later owner's physical tables.
    if (state.rf_owned) {
      await apply([`rollback/${RF151}`]);
      state = await topology(database);
    }
    if (state.rf_owned || ![null, "v"].includes(state.authority_kind)) throw new Error("authority_overlap_topology_required");
    await apply([`rollback/${SIGNOFF_CONTRACT}`,
      ...(state.authority_kind === null ? [`rollback/${CONTRACT}`] : []),
      `rollback/${RF}`, `rollback/${OPERATIONS}`, `rollback/${AUTHORITY}`]);
  } else {
    if (state.rf_owned || state.authority_kind !== "r") throw new Error("authority_predecessor_topology_required");
    if (direction === "workspace" && (state.ledger_kind !== "v" || !state.ledger_setup || state.opening_kind !== "r")) {
      throw new Error("workspace_requires_ledger_ordinary_overlap");
    }
    if (direction === "recutover" && (state.ledger_kind !== null || state.ledger_setup || state.opening_kind !== "r")) {
      throw new Error("final_rf_requires_ledger_contract");
    }
    // Billing's ordinary pilot coordinator still reads the AU overlap view.
    // Its lifecycle retires that dependency before the final recutover phase.
    await apply([`migrations/${AUTHORITY}`, `migrations/${OPERATIONS}`, `migrations/${RF}`,
      ...(direction === "recutover" ? [`contract-migrations/${CONTRACT}`] : []),
      `contract-migrations/${SIGNOFF_CONTRACT}`,
      `migrations/${RF151}`, `migrations/${RF151_CUTOVER}`, `migrations/${RF193_READ_RECOVERY}`,
      ...(direction === "recutover" ? [`contract-migrations/${RF151_CONTRACT}`] : [])]);
  }
  const result = await topology(database);
  const valid = direction === "rollback"
    ? !result.rf_owned && result.authority_kind === "r"
    : result.rf_owned
      && (direction === "workspace"
        ? result.authority_kind === "v" && result.ledger_kind === "v" && result.ledger_setup && result.opening_kind === "r"
        : result.authority_kind === null && result.ledger_kind === null && !result.ledger_setup && result.opening_kind === null);
  if (!valid) throw new Error("authority_rehearsal_target_not_reached");
}

async function main() {
  const databaseUrl = process.env.DATABASE_URL;
  if (!databaseUrl || !isLoopbackPostgresUrl(databaseUrl)) throw new Error("authority_rehearsal_requires_disposable_loopback_database");
  const database = new pg.Client({ connectionString: databaseUrl });
  await database.connect();
  try {
    await rehearseAuthorityTopology({ direction: process.argv[2], database });
    console.log(`Authority and RF test topology ${process.argv[2]} completed`);
  } finally { await database.end(); }
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch((error) => { console.error(error.message); process.exitCode = 1; });
}
