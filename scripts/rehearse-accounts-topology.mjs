/** Explicit final Accounts topology for the owned local gate database. */
import { readFile } from "node:fs/promises";
import pg from "pg";
import { isLoopbackPostgresUrl } from "../tests/support/supabase_fixture_safety.mjs";

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl || !isLoopbackPostgresUrl(databaseUrl)) throw new Error("accounts_rehearsal_requires_owned_loopback_database");
const direction=process.argv[2];
const phases={
  "delivery-expand":["contract-migrations/20261026221935_annual_accounts_delivery_store_v1.sql"],
  "journal-expand":["contract-migrations/20261026232554_annual_accounts_delivery_events_v1.sql"],
  "correction-expand":["contract-migrations/20261027004007_annual_accounts_delivery_corrections_v1.sql",
    "contract-migrations/20261027010818_corporate_accounts_owning_read_admission.sql",
    "contract-migrations/20261027011601_corporate_immutable_guarded_decision_reads_v1.sql",
    "contract-migrations/20261027012022_corporate_evidence_authoritative_income_year_v1.sql",
    "contract-migrations/20261027080000_company_access_corporate_owner_read.sql",
    "contract-migrations/20261027080100_corporate_annual_close_2025.sql",
    "contract-migrations/20261027150656_annual_accounts_company_archive_read_guard.sql"],
};
const enables={"delivery-enable":"20261026221935_annual_accounts_delivery_store_v1.sql",
  "journal-enable":"20261026232554_annual_accounts_delivery_events_v1.sql",
  "correction-enable":"20261027004007_annual_accounts_delivery_corrections_v1.sql"};
if (direction!=="activate" && !phases[direction] && !enables[direction]) throw new Error("invalid_accounts_rehearsal_direction");
const database = new pg.Client({ connectionString: databaseUrl });
await database.connect();
try {
  const predecessor = await database.query("select phase from backend_system.company_tax_return_migration_state where singleton");
  if (predecessor.rows[0]?.phase !== "contracted") throw new Error("accounts_rehearsal_requires_final_tax_contract");
  const existing = await database.query("select to_regnamespace('annual_accounts_filing') is not null present");
  if (direction!=="activate") {
    if (!existing.rows[0].present) throw new Error("accounts_rehearsal_requires_contracted_topology");
    for (const name of phases[direction] ?? []) await database.query(await readFile(new URL("../supabase/"+name,import.meta.url),"utf8"));
    if (enables[direction]) {
      const rollback=await readFile(new URL("../supabase/rollback/"+enables[direction],import.meta.url),"utf8");
      const pattern=/begin return false; end;\s*\$function\$;/gu;
      const count=[...rollback.matchAll(pattern)].length;
      if (count!==(direction==="correction-enable"?2:1)) throw new Error("accounts_rehearsal_containment_changed");
      await database.query(rollback.replace(pattern,"begin return true; end;$function$;"));
    }
    console.log("Annual Accounts owned loopback phase "+direction);
  } else {
  if (existing.rows[0].present) throw new Error("accounts_rehearsal_requires_unexpanded_topology");
  for (const name of [
    "20260914090244_annual_accounts_filing_expand.sql",
    "20260914092018_annual_accounts_filing_read_contracts.sql",
    "20260914092924_annual_accounts_filing_preparation_contracts.sql",
    "20260914093204_annual_accounts_filing_import_contract.sql",
    "20260914101625_annual_accounts_filing_dependency_contracts.sql",
    "20260914110840_annual_accounts_filing_source_contract.sql",
    "20260914101805_annual_accounts_filing_cutover.sql",
    "20260914101842_annual_accounts_filing_contract.sql",
    "20260914112549_annual_accounts_filing_backend_binding.sql",
  ]) {
    await database.query(await readFile(new URL(`../supabase/contract-migrations/${name}`, import.meta.url), "utf8"));
  }
  console.log("Annual Accounts local topology contracted");
  }
} finally {
  await database.end();
}
