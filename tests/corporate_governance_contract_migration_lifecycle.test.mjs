import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import pg from "pg";

const { Client } = pg;
const databaseUrl = process.env.DATABASE_URL;
const migrationName =
  "20260902071000_corporate_governance_shareholder_loan_contract.sql";

async function state(client) {
  const result = await client.query(String.raw`
    select
      pg_catalog.to_regprocedure(
        'backend_system.prepare_shareholder_loan_v1(jsonb,text)'
      ) is not null as predecessor_prepare,
      pg_catalog.to_regprocedure(
        'backend_system.complete_shareholder_loan_v1(jsonb,uuid,jsonb,text)'
      ) is not null as predecessor_complete,
      pg_catalog.to_regprocedure(
        'backend_system.rollback_145_prepare_shareholder_loan_v1(jsonb,text)'
      ) is not null as rollback_prepare,
      pg_catalog.to_regprocedure(
        'backend_system.rollback_145_complete_shareholder_loan_v1(jsonb,uuid,jsonb,text)'
      ) is not null as rollback_complete
  `);
  return result.rows[0];
}

test(
  "shareholder-loan contract cutover and rollback are repeatable twice",
  { skip: !databaseUrl && "DATABASE_URL is required", timeout: 120_000 },
  async () => {
    const [forward, rollback] = await Promise.all([
      readFile(
        new URL(
          `../supabase/contract-migrations/${migrationName}`,
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL(`../supabase/rollback/${migrationName}`, import.meta.url),
        "utf8",
      ),
    ]);
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      const predecessorState = {
        predecessor_prepare: true,
        predecessor_complete: true,
        rollback_prepare: false,
        rollback_complete: false,
      };
      const cutoverState = {
        predecessor_prepare: false,
        predecessor_complete: false,
        rollback_prepare: true,
        rollback_complete: true,
      };
      assert.deepEqual(await state(client), predecessorState);
      for (let rehearsal = 0; rehearsal < 2; rehearsal += 1) {
        await client.query(forward);
        assert.deepEqual(await state(client), cutoverState);
        await client.query(rollback);
        assert.deepEqual(await state(client), predecessorState);
      }
    } finally {
      await client.end();
    }
  },
);
