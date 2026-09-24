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
const RF193_ARCHIVE = "20260917114424_rf1086_production_archive_evidence.sql";
const DOCUMENTS_LEDGER_GUARD = "20260923125730_documents_ledger_evidence_guard.sql";
const RF193_YEAR_SOURCE = "20260923091509_rf1086_immutable_year_source.sql";

const RF193_OBSERVATION = "20260923102314_rf1086_register_observation_store.sql";
const RF193_SOURCE_COMPANY_GUARD = "20260924062746_rf1086_source_company_guard.sql";
const CONSEQUENTIAL_GUARDS = [
  "20260924080208_company_access_rf_admission_guard.sql",
  "20260924080249_documents_rf_consequential_company_guards.sql",
  "20260924080355_governance_ledger_company_write_guards.sql",
  "20260924083154_governance_guarded_reporting_year_read.sql",
  "20260924084752_billing_rf_full_year_pilot_profile.sql",
  "20260924085227_rf1086_source_review_bridge.sql",
  "20260924091015_rf1086_source_approval_foundation.sql",
  "20260924094631_rf1086_journal_company_guard.sql",
];
const RF193_SOURCE_PREVIEW = "20260923105912_rf1086_source_backed_preview.sql";

async function topology(database) {
  const { rows: [state] } = await database.query(`select
    to_regclass('shareholder_register_filing.migration_state') is not null as rf_owned,
    to_regclass('shareholder_register_filing.source_previews') is not null as rf_source_previews,
    to_regprocedure('shareholder_register_filing.lock_source_company_write_v1()') is not null as rf_source_company_guard,
    to_regclass('shareholder_register_filing.register_observations') is not null as rf_register_observations,
    to_regclass('shareholder_register_filing.year_source_versions') is not null as rf_year_sources,
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
      if (state.rf_register_observations) {
        const { rows: [observation] } = await database.query("select exists(select 1 from shareholder_register_filing.register_observations) as retained_observations");
        if (observation.retained_observations) throw new Error("rf1086_retained_register_observations_block_full_schema_rollback");
      }
      if (state.rf_year_sources) {
        const { rows: [source] } = await database.query("select exists(select 1 from shareholder_register_filing.year_source_versions) as retained_sources");
        if (source.retained_sources) throw new Error("rf1086_retained_year_sources_block_full_schema_rollback");
      }
      await apply([...(state.rf_source_company_guard ? [`rollback/${RF193_SOURCE_COMPANY_GUARD}`] : []), ...(state.rf_source_previews ? [`rollback/${RF193_SOURCE_PREVIEW}`] : []), ...(state.rf_register_observations ? [`rollback/${RF193_OBSERVATION}`] : []), ...(state.rf_year_sources ? [`rollback/${RF193_YEAR_SOURCE}`] : []), `rollback/${RF193_ARCHIVE}`, `rollback/${RF151}`]);
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
      `migrations/${RF151}`, `migrations/${RF151_CUTOVER}`, `migrations/${DOCUMENTS_LEDGER_GUARD}`, `migrations/${RF193_READ_RECOVERY}`, `migrations/${RF193_ARCHIVE}`, `migrations/${RF193_YEAR_SOURCE}`, `migrations/${RF193_OBSERVATION}`, `migrations/${RF193_SOURCE_PREVIEW}`, `migrations/${RF193_SOURCE_COMPANY_GUARD}`,
      ...(direction === "recutover" ? [`contract-migrations/${RF151_CONTRACT}`] : []),
      // Historical owner lifecycles can replace entire routine bodies. Reapply
      // the ordered additive guards only after every predecessor/contract body.
      ...CONSEQUENTIAL_GUARDS.map(file => `migrations/${file}`)]);
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
