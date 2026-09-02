import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import pg from "pg";

const { Client } = pg;
const databaseUrl = process.env.DATABASE_URL;
const ownerMigrationName =
  "20260902040000_corporate_governance_owner_dividend.sql";
const loanMigrationName =
  "20260902070000_corporate_governance_shareholder_loan.sql";
const loanInitPlanMigrationName =
  "20260902084230_corporate_governance_shareholder_loan_rls_initplan_cleanup.sql";
const annualMigrationName =
  "20260902090000_corporate_governance_annual_close.sql";
const lifecycleMigrationName =
  "20260902100000_corporate_governance_artifact_lifecycle.sql";

test("artifact persistence does not duplicate Python signer policy", async () => {
  const forward = await readFile(
    new URL(`../supabase/migrations/${lifecycleMigrationName}`, import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(forward, /v_required_signers|v_actual_signers/iu);
  assert.match(forward, /jsonb_typeof\(signer\).*'string'/isu);
});

async function state(client) {
  const result = await client.query(String.raw`
    select
      pg_catalog.to_regnamespace('corporate_governance') is not null
        as capability_schema,
      pg_catalog.to_regclass(
        'corporate_governance.owner_dividend_decisions'
      ) is not null as decision_table,
      pg_catalog.to_regclass(
        'corporate_governance.shareholder_loans'
      ) is not null as shareholder_loan_table,
      pg_catalog.to_regprocedure(
        'ledger.post_corporate_governance_entry_v1(text,uuid,integer,text,text,jsonb,text,text,text,text,uuid)'
      ) is not null as ledger_bridge,
      pg_catalog.to_regprocedure(
        'banking.claim_owner_dividend_transaction_v1(jsonb,uuid,text)'
      ) is not null as owner_banking_bridge,
      pg_catalog.to_regprocedure(
        'banking.claim_corporate_governance_transaction_v1(jsonb,uuid,text)'
      ) is not null as shareholder_loan_banking_bridge
  `);
  return result.rows[0];
}

test(
  "governance rollback and recutover are lossless and repeatable twice",
  { skip: !databaseUrl && "DATABASE_URL is required", timeout: 120_000 },
  async () => {
    const [
      ownerForward,
      ownerRollback,
      loanForward,
      loanRollback,
      annualForward,
      annualRollback,
      lifecycleForward,
      lifecycleRollback,
    ] =
      await Promise.all([
      readFile(
        new URL(
          `../supabase/migrations/${ownerMigrationName}`,
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          `../supabase/rollback/${ownerMigrationName}`,
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          `../supabase/migrations/${loanMigrationName}`,
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          `../supabase/rollback/${loanMigrationName}`,
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL(`../supabase/migrations/${annualMigrationName}`, import.meta.url),
        "utf8",
      ),
      readFile(
        new URL(`../supabase/rollback/${annualMigrationName}`, import.meta.url),
        "utf8",
      ),
      readFile(
        new URL(`../supabase/migrations/${lifecycleMigrationName}`, import.meta.url),
        "utf8",
      ),
      readFile(
        new URL(`../supabase/rollback/${lifecycleMigrationName}`, import.meta.url),
        "utf8",
      ),
    ]);
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      assert.deepEqual(await state(client), {
        capability_schema: true,
        decision_table: true,
        shareholder_loan_table: true,
        ledger_bridge: true,
        owner_banking_bridge: true,
        shareholder_loan_banking_bridge: true,
      });
      for (let rehearsal = 0; rehearsal < 2; rehearsal += 1) {
        await client.query(lifecycleRollback);
        await client.query(annualRollback);
        await client.query(loanRollback);
        await client.query(ownerRollback);
        assert.deepEqual(await state(client), {
          capability_schema: false,
          decision_table: false,
          shareholder_loan_table: false,
          ledger_bridge: false,
          owner_banking_bridge: false,
          shareholder_loan_banking_bridge: false,
        });
        await client.query(ownerForward);
        await client.query(loanForward);
        await client.query(annualForward);
        await client.query(lifecycleForward);
        assert.deepEqual(await state(client), {
          capability_schema: true,
          decision_table: true,
          shareholder_loan_table: true,
          ledger_bridge: true,
          owner_banking_bridge: true,
          shareholder_loan_banking_bridge: true,
        });
      }
    } finally {
      await client.end();
    }
  },
);

test(
  "shareholder-loan RLS cleanup rollback and recutover are repeatable twice",
  { skip: !databaseUrl && "DATABASE_URL is required", timeout: 120_000 },
  async () => {
    const [forward, rollback] = await Promise.all([
      readFile(
        new URL(
          `../supabase/migrations/${loanInitPlanMigrationName}`,
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          `../supabase/rollback/${loanInitPlanMigrationName}`,
          import.meta.url,
        ),
        "utf8",
      ),
    ]);
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      for (let rehearsal = 0; rehearsal < 2; rehearsal += 1) {
        await client.query(rollback);
        const restored = await client.query(String.raw`
          select pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid)
            as expression
          from pg_catalog.pg_policy policy
          where policy.polrelid =
            'corporate_governance.shareholder_loans'::regclass
            and policy.polname = 'governance_owner_creates_shareholder_loans'
        `);
        assert.doesNotMatch(
          restored.rows[0].expression,
          /SELECT company_access_is_accepted_owner_v1/iu,
        );
        await client.query(forward);
        const optimized = await client.query(String.raw`
          select pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid)
            as expression
          from pg_catalog.pg_policy policy
          where policy.polrelid =
            'corporate_governance.shareholder_loans'::regclass
            and policy.polname = 'governance_owner_creates_shareholder_loans'
        `);
        assert.match(
          optimized.rows[0].expression,
          /SELECT company_access_is_accepted_owner_v1/iu,
        );
      }
    } finally {
      await client.end();
    }
  },
);
