/** Deferred local RF runtime cutover; fixed artifact, owned loopback database only. */
import { readFile } from "node:fs/promises";
import pg from "pg";
import { isLoopbackPostgresUrl } from "../tests/support/supabase_fixture_safety.mjs";

const databaseUrl = process.env.DATABASE_URL;
if (!isLoopbackPostgresUrl(databaseUrl)) {
  throw new Error("rf_source_runtime_requires_owned_loopback_database");
}
const contract = new URL(
  "../supabase/contract-migrations/20261025104137_rf1086_source_runtime_v3_contract.sql",
  import.meta.url,
);
const database = new pg.Client({ connectionString: databaseUrl });
try {
  await database.connect();
  await database.query(await readFile(contract, "utf8"));
  console.log("RF source V2/V3 runtime contract applied; provider flags unchanged.");
} finally {
  await database.end();
}
