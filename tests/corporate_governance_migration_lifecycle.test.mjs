import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import pg from "pg";

const { Client } = pg;
const databaseUrl = process.env.DATABASE_URL;
const migrationName = "20260902040000_corporate_governance_owner_dividend.sql";

async function state(client) {
  const result = await client.query(String.raw`
    select
      pg_catalog.to_regnamespace('corporate_governance') is not null
        as capability_schema,
      pg_catalog.to_regclass(
        'corporate_governance.owner_dividend_decisions'
      ) is not null as decision_table,
      pg_catalog.to_regprocedure(
        'ledger.post_corporate_governance_entry_v1(text,uuid,integer,text,text,jsonb,text,text,text,text,uuid)'
      ) is not null as ledger_bridge,
      pg_catalog.to_regprocedure(
        'banking.claim_owner_dividend_transaction_v1(jsonb,uuid,text)'
      ) is not null as banking_bridge
  `);
  return result.rows[0];
}

test(
  "governance rollback and recutover are lossless and repeatable twice",
  { skip: !databaseUrl && "DATABASE_URL is required", timeout: 120_000 },
  async () => {
    const [forward, rollback] = await Promise.all([
      readFile(
        new URL(`../supabase/migrations/${migrationName}`, import.meta.url),
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
      assert.deepEqual(await state(client), {
        capability_schema: true,
        decision_table: true,
        ledger_bridge: true,
        banking_bridge: true,
      });
      for (let rehearsal = 0; rehearsal < 2; rehearsal += 1) {
        await client.query(rollback);
        assert.deepEqual(await state(client), {
          capability_schema: false,
          decision_table: false,
          ledger_bridge: false,
          banking_bridge: false,
        });
        await client.query(forward);
        assert.deepEqual(await state(client), {
          capability_schema: true,
          decision_table: true,
          ledger_bridge: true,
          banking_bridge: true,
        });
      }
    } finally {
      await client.end();
    }
  },
);
