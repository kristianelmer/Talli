import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import pg from "pg";

const { Client } = pg;
const databaseUrl = process.env.DATABASE_URL;
const migrationName = "20260902110000_corporate_governance_contract.sql";

async function state(client) {
  const result = await client.query(String.raw`
    select
      pg_catalog.to_regclass('public.corporate_decisions') is not null
        as predecessor_projection,
      pg_catalog.to_regprocedure(
        'public.create_corporate_document_draft(jsonb)'
      ) is not null as predecessor_writer,
      pg_catalog.to_regclass(
        'corporate_governance.annual_close_decisions'
      ) is not null as annual_decisions,
      pg_catalog.to_regclass(
        'corporate_governance.annual_close_artifacts'
      ) is not null as annual_artifacts,
      pg_catalog.to_regclass(
        'corporate_governance.annual_close_finalizations'
      ) is not null as annual_finalizations,
      pg_catalog.to_regclass(
        'corporate_governance.owner_dividend_decisions'
      ) is not null as owner_decisions,
      pg_catalog.to_regclass(
        'corporate_governance.owner_dividend_accounting_policies'
      ) is not null as owner_policies,
      pg_catalog.to_regclass(
        'corporate_governance.owner_dividend_artifacts'
      ) is not null as owner_artifacts,
      pg_catalog.to_regclass(
        'corporate_governance.owner_dividend_finalizations'
      ) is not null as owner_finalizations,
      pg_catalog.to_regprocedure(
        'corporate_governance.read_corporate_lifecycle_v1(uuid[],uuid,text)'
      ) is not null as lifecycle_reader,
      pg_catalog.strpos(
        pg_catalog.pg_get_functiondef(
          'corporate_governance.prepare_owner_dividend_finalization_v1(jsonb,text)'::regprocedure
        ),
        'corporate_governance_rollback_write_blocked'
      ) > 0 as writers_blocked,
      pg_catalog.to_regprocedure(
        'corporate_governance.prepare_owner_dividend_finalization_contract_v1(jsonb,text)'
      ) is not null
      and pg_catalog.to_regprocedure(
        'corporate_governance.complete_owner_dividend_finalization_contract_v1(jsonb,text)'
      ) is not null
      and pg_catalog.to_regprocedure(
        'corporate_governance.prepare_owner_dividend_payment_contract_v1(jsonb,text)'
      ) is not null
      and pg_catalog.to_regprocedure(
        'corporate_governance.complete_owner_dividend_payment_contract_v1(jsonb,text)'
      ) is not null
      and pg_catalog.to_regprocedure(
        'corporate_governance.finalize_annual_close_contract_v1(jsonb,text)'
      ) is not null as writer_backups
  `);
  return result.rows[0];
}

async function evidence(client) {
  const result = await client.query(String.raw`
    select pg_catalog.jsonb_build_object(
      'ownerDecisions', (select coalesce(pg_catalog.jsonb_agg(
        pg_catalog.to_jsonb(item) order by item.id
      ), '[]'::jsonb) from corporate_governance.owner_dividend_decisions item),
      'ownerArtifacts', (select coalesce(pg_catalog.jsonb_agg(
        pg_catalog.to_jsonb(item) order by item.id
      ), '[]'::jsonb) from corporate_governance.owner_dividend_artifacts item),
      'ownerEvents', (select coalesce(pg_catalog.jsonb_agg(
        pg_catalog.to_jsonb(item) order by item.id
      ), '[]'::jsonb) from corporate_governance.owner_dividend_events item),
      'ownerFinalizations', (select coalesce(pg_catalog.jsonb_agg(
        pg_catalog.to_jsonb(item) order by item.id
      ), '[]'::jsonb) from corporate_governance.owner_dividend_finalizations item),
      'ownerPayments', (select coalesce(pg_catalog.jsonb_agg(
        pg_catalog.to_jsonb(item) order by item.id
      ), '[]'::jsonb) from corporate_governance.owner_dividend_payments item),
      'annualDecisions', (select coalesce(pg_catalog.jsonb_agg(
        pg_catalog.to_jsonb(item) order by item.id
      ), '[]'::jsonb) from corporate_governance.annual_close_decisions item),
      'annualArtifacts', (select coalesce(pg_catalog.jsonb_agg(
        pg_catalog.to_jsonb(item) order by item.id
      ), '[]'::jsonb) from corporate_governance.annual_close_artifacts item),
      'annualEvents', (select coalesce(pg_catalog.jsonb_agg(
        pg_catalog.to_jsonb(item) order by item.id
      ), '[]'::jsonb) from corporate_governance.annual_close_events item),
      'annualFinalizations', (select coalesce(pg_catalog.jsonb_agg(
        pg_catalog.to_jsonb(item) order by item.id
      ), '[]'::jsonb) from corporate_governance.annual_close_finalizations item),
      'documents', (select coalesce(pg_catalog.jsonb_agg(
        pg_catalog.to_jsonb(item) order by item.id
      ), '[]'::jsonb) from public.documents item),
      'ledgerEntries', (select coalesce(pg_catalog.jsonb_agg(
        pg_catalog.to_jsonb(item) order by item.id
      ), '[]'::jsonb) from ledger.entries item)
    ) as value
  `);
  return result.rows[0].value;
}

async function assertRollbackBlocksWriters(client) {
  for (const routine of [
    "prepare_owner_dividend_finalization_v1",
    "complete_owner_dividend_finalization_v1",
    "prepare_owner_dividend_payment_v1",
    "complete_owner_dividend_payment_v1",
    "finalize_annual_close_v1",
  ]) {
    await assert.rejects(
      client.query(
        `select corporate_governance.${routine}('{}'::jsonb, '')`,
      ),
      /corporate_governance_rollback_write_blocked/u,
    );
  }
}

test(
  "corporate-governance contract rollback and cutover are repeatable twice",
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
      const cutoverState = {
        predecessor_projection: false,
        predecessor_writer: false,
        annual_decisions: true,
        annual_artifacts: true,
        annual_finalizations: true,
        owner_decisions: true,
        owner_policies: true,
        owner_artifacts: true,
        owner_finalizations: true,
        lifecycle_reader: true,
        writers_blocked: false,
        writer_backups: false,
      };
      const rollbackState = {
        ...cutoverState,
        predecessor_projection: true,
        writers_blocked: true,
        writer_backups: true,
      };

      const initialState = await state(client);
      if (initialState.predecessor_projection || initialState.predecessor_writer) {
        await client.query(forward);
      }
      const canonicalEvidence = await evidence(client);
      await client.query(rollback);
      assert.deepEqual(await state(client), rollbackState);
      assert.deepEqual(await evidence(client), canonicalEvidence);
      await assertRollbackBlocksWriters(client);
      for (let rehearsal = 0; rehearsal < 2; rehearsal += 1) {
        await client.query(forward);
        assert.deepEqual(await state(client), cutoverState);
        assert.deepEqual(await evidence(client), canonicalEvidence);
        await client.query(rollback);
        assert.deepEqual(await state(client), rollbackState);
        assert.deepEqual(await evidence(client), canonicalEvidence);
        await assertRollbackBlocksWriters(client);
      }
    } finally {
      await client.end();
    }
  },
);

test("corporate-governance contract retires every predecessor surface", async () => {
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

  for (const table of [
    "corporate_decisions",
    "corporate_accounting_policies",
    "corporate_document_events",
    "corporate_document_sets",
    "corporate_document_artifacts",
    "corporate_decision_finalizations",
  ]) {
    assert.match(forward, new RegExp(`drop table if exists public\\.${table}`));
    assert.match(rollback, new RegExp(`create table if not exists public\\.${table}`));
  }

  assert.match(forward, /corporate_governance_\w+_reconciliation_failed/i);
  assert.match(forward, /corporate_governance_event_reconciliation_failed/i);
  assert.match(
    forward,
    /delete from public\.holding_actions[\s\S]*shareholder_loan[\s\S]*dividend_to_owner/i,
  );
  assert.match(forward, /drop function if exists public\.create_corporate_document_draft/i);
  assert.match(
    forward,
    /drop function if exists\s+backend_system\.project_owner_dividend_finalization_v1/i,
  );
  assert.doesNotMatch(
    rollback,
    /create\s+(?:or\s+replace\s+)?function\s+public\.create_corporate_document_draft/i,
  );
  assert.match(
    rollback,
    /corporate_governance_rollback_write_blocked/i,
  );
  assert.match(
    rollback,
    /prepare_owner_dividend_finalization_contract_v1/i,
  );
  assert.match(forward, /restore_contract_writers/i);
});
