/** Finish reporting-store prerequisites before RF installs writer guards. */
import { readFile } from "node:fs/promises";
import pg from "pg";
import { isLoopbackPostgresUrl } from "../tests/support/supabase_fixture_safety.mjs";

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl || !isLoopbackPostgresUrl(databaseUrl)) {
  throw new Error("governance_rehearsal_requires_owned_loopback_database");
}
const database = new pg.Client({ connectionString: databaseUrl });
await database.connect();
const apply = async (name) => database.query(await readFile(
  new URL(`../supabase/contract-migrations/${name}`, import.meta.url), "utf8",
));
try {
  const kind = async (name) => (await database.query(
    "select relkind::text from pg_class where oid=to_regclass($1)", [name],
  )).rows[0]?.relkind;
  // Investments retirement still inspects the Governance predecessor tables.
  // Close these earlier stores first, in the same order as Tax preparation.
  if (await kind("public.bank_transactions") === "r") {
    await apply("20260828101000_banking_capability_contract.sql");
  }
  if (await kind("public.investment_positions")) {
    for (const name of [
      "20260831133000_investments_share_purchase_contract.sql",
      "20260831170000_investments_share_sale_contract.sql",
      "20260831190000_investments_received_dividend_contract.sql",
      "20260831193000_investments_stage_exit.sql",
      "20260901001500_investments_stage_exit_policy_cleanup.sql",
      "20260901150538_investments_lifecycle_public_cutover.sql",
    ]) await apply(name);
  }
  const state = (await database.query(`select
    to_regprocedure('backend_system.prepare_shareholder_loan_v1(jsonb,text)') is not null as loan,
    (select relkind::text from pg_class where oid=to_regclass('public.corporate_decisions')) as decisions
  `)).rows[0];
  if (state.loan) {
    await apply("20260902071000_corporate_governance_shareholder_loan_contract.sql");
  }
  if (state.loan || state.decisions === "r") {
    await apply("20260902110000_corporate_governance_contract.sql");
  }
  const final = (await database.query(`select
    to_regprocedure('backend_system.prepare_shareholder_loan_v1(jsonb,text)') is null
      and to_regclass('public.corporate_decisions') is null as contracted
  `)).rows[0];
  if (!final.contracted) throw new Error("governance_rehearsal_contract_not_reached");
  console.log("Governance contracts completed before RF writer guards");
} finally {
  await database.end();
}
