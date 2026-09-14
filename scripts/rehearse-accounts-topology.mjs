/** Explicit final Accounts topology for the owned local gate database. */
import { readFile } from "node:fs/promises";
import pg from "pg";
import { isLoopbackPostgresUrl } from "../tests/support/supabase_fixture_safety.mjs";

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl || !isLoopbackPostgresUrl(databaseUrl)) throw new Error("accounts_rehearsal_requires_owned_loopback_database");
if (process.argv[2] !== "activate") throw new Error("invalid_accounts_rehearsal_direction");
const database = new pg.Client({ connectionString: databaseUrl });
await database.connect();
try {
  const predecessor = await database.query("select phase from backend_system.company_tax_return_migration_state where singleton");
  if (predecessor.rows[0]?.phase !== "contracted") throw new Error("accounts_rehearsal_requires_final_tax_contract");
  const existing = await database.query("select to_regnamespace('annual_accounts_filing') is not null present");
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
} finally {
  await database.end();
}
