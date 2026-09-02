import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import pg from "pg";

const { Client } = pg;
const databaseUrl = process.env.DATABASE_URL;
const migrationName = "20260902090000_corporate_governance_annual_close.sql";

async function state(client) {
  const result = await client.query(String.raw`
    select
      to_regclass('corporate_governance.annual_close_decisions') is not null
        as decisions_exist,
      to_regclass('corporate_governance.annual_close_artifacts') is not null
        as artifacts_exist,
      to_regclass('corporate_governance.annual_close_events') is not null
        as events_exist,
      to_regclass('corporate_governance.annual_close_finalizations') is not null
        as finalizations_exist,
      case when to_regclass('corporate_governance.annual_close_decisions') is null
        then null else (
          select relation.relforcerowsecurity
          from pg_catalog.pg_class relation
          where relation.oid = to_regclass(
            'corporate_governance.annual_close_decisions'
          )
        ) end as decisions_force_rls,
      to_regprocedure(
        'corporate_governance.propose_annual_close_v1(jsonb,jsonb,jsonb,jsonb,text)'
      ) is not null as proposal_exists,
      to_regprocedure(
        'corporate_governance.register_annual_close_documents_v1(jsonb,text)'
      ) is not null as registration_exists,
      to_regprocedure(
        'corporate_governance.attest_annual_close_signed_artifact_v1(jsonb,text)'
      ) is not null as attestation_exists
  `);
  return result.rows[0];
}

test(
  "annual-close migration rolls back and recuts over twice without authority drift",
  { skip: !databaseUrl && "DATABASE_URL is required", timeout: 120_000 },
  async () => {
    const [forward, rollback] = await Promise.all([
      readFile(new URL(`../supabase/migrations/${migrationName}`, import.meta.url), "utf8"),
      readFile(new URL(`../supabase/rollback/${migrationName}`, import.meta.url), "utf8"),
    ]);
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      assert.deepEqual(await state(client), {
        decisions_exist: true,
        artifacts_exist: true,
        events_exist: true,
        finalizations_exist: true,
        decisions_force_rls: true,
        proposal_exists: true,
        registration_exists: true,
        attestation_exists: true,
      });
      for (let rehearsal = 0; rehearsal < 2; rehearsal += 1) {
        await client.query(rollback);
        assert.deepEqual(await state(client), {
          decisions_exist: false,
          artifacts_exist: false,
          events_exist: false,
          finalizations_exist: false,
          decisions_force_rls: null,
          proposal_exists: false,
          registration_exists: false,
          attestation_exists: false,
        });
        await client.query(forward);
        assert.deepEqual(await state(client), {
          decisions_exist: true,
          artifacts_exist: true,
          events_exist: true,
          finalizations_exist: true,
          decisions_force_rls: true,
          proposal_exists: true,
          registration_exists: true,
          attestation_exists: true,
        });
      }
    } finally {
      await client.end();
    }
  },
);
