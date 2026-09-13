/** #146 final local-only topology; predecessor lifecycle lanes run first. */
import { readFile } from "node:fs/promises";
import pg from "pg";
import { isLoopbackPostgresUrl } from "../tests/support/supabase_fixture_safety.mjs";

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl || !isLoopbackPostgresUrl(databaseUrl)) throw new Error("tax_rehearsal_requires_owned_loopback_database");
const direction = process.argv[2];
if (!["prepare", "contract"].includes(direction)) throw new Error("invalid_tax_rehearsal_direction");
const database = new pg.Client({ connectionString: databaseUrl });
await database.connect();
const apply = async (path) => database.query(await readFile(new URL(`../supabase/${path}`, import.meta.url), "utf8"));
const kind = async (name) => (await database.query("select relkind from pg_class where oid=to_regclass($1)", [name])).rows[0]?.relkind;
try {
  if (await kind("public.ledger_entries") || await kind("public.opening_balance_setups")) throw new Error("tax_rehearsal_requires_final_ledger_and_rf_contracts");
  if (direction === "prepare") {
    if (await kind("public.bank_transactions") === "r") await apply("contract-migrations/20260828101000_banking_capability_contract.sql");
    if (await kind("public.investment_positions")) {
      for (const name of ["20260831133000_investments_share_purchase_contract.sql", "20260831170000_investments_share_sale_contract.sql",
        "20260831190000_investments_received_dividend_contract.sql", "20260831193000_investments_stage_exit.sql",
        "20260901001500_investments_stage_exit_policy_cleanup.sql", "20260901150538_investments_lifecycle_public_cutover.sql"]) {
        await apply(`contract-migrations/${name}`);
      }
    }
    const oldGovernance = (await database.query("select to_regprocedure('backend_system.prepare_shareholder_loan_v1(jsonb,text)') is not null present")).rows[0].present;
    if (oldGovernance) {
      await apply("contract-migrations/20260902071000_corporate_governance_shareholder_loan_contract.sql");
    }
    // The full Governance rollback restores tables with blocked writers; the
    // already-retired shareholder-loan function need not reappear with them.
    if (oldGovernance || await kind("public.corporate_decisions") === "r") {
      await apply("contract-migrations/20260902110000_corporate_governance_contract.sql");
    }
    const state = (await database.query("select phase from backend_system.tax_settlement_migration_state where singleton")).rows[0]?.phase;
    if (["expanded", "rolled_back"].includes(state)) await apply("migrations/20260913171000_company_tax_settlement_expand.sql");
  } else {
    await apply("contract-migrations/20260913172000_company_tax_settlement_cutover.sql");
    await apply("contract-migrations/20260913173000_company_tax_settlement_contract.sql");
  }
  console.log(`Company Tax local topology ${direction} completed`);
} finally {
  await database.end();
}
