import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import pg from "pg";
import { emptyDocumentsRetentionTeardown } from "./support/documents_retention_rehearsal.mjs";

const { Client } = pg;
const databaseUrl = process.env.DATABASE_URL;
const migrationName = "20260901233000_documents_capability.sql";
const registryMigrationName =
  "20260902030000_documents_evidence_reference_registry.sql";
const retentionMigrationName = "20260923102419_documents_verified_rf_evidence_retention.sql";
const governanceLifecycleMigrationName =
  "20260902100000_corporate_governance_artifact_lifecycle.sql";

async function state(client) {
  const result = await client.query(String.raw`
    select
      (select count(*)::int from public.documents) as document_count,
      (select owner.rolname from pg_catalog.pg_class relation
        join pg_catalog.pg_roles owner on owner.oid=relation.relowner
        where relation.oid='public.documents'::regclass) as table_owner,
      to_regnamespace('documents') is not null as capability_schema,
      has_table_privilege('authenticated','public.documents','SELECT') as browser_reads,
      has_function_privilege('authenticated','public.remove_unlinked_document(uuid)','EXECUTE') as browser_removes,
      pg_catalog.pg_get_functiondef(
        'public.create_corporate_document_draft(jsonb)'::regprocedure
      ) || pg_catalog.pg_get_functiondef(
        'public.attest_corporate_signed_artifact(jsonb)'::regprocedure
      ) as producer_definitions
  `);
  return result.rows[0];
}

test(
  "documents rollback preserves predecessor state and recutover is repeatable twice",
  { skip: !databaseUrl && "DATABASE_URL is required", timeout: 120_000 },
  async () => {
    const [
      forward,
      rollback,
      registryForward,
      registryRollback,
      governanceForward,
      governanceRollback,
      retentionForward,
      ledgerGuardForward,
    ] = await Promise.all([
      readFile(new URL(`../supabase/migrations/${migrationName}`, import.meta.url), "utf8"),
      readFile(new URL(`../supabase/rollback/${migrationName}`, import.meta.url), "utf8"),
      readFile(new URL(`../supabase/migrations/${registryMigrationName}`, import.meta.url), "utf8"),
      readFile(new URL(`../supabase/rollback/${registryMigrationName}`, import.meta.url), "utf8"),
      readFile(new URL(`../supabase/migrations/${governanceLifecycleMigrationName}`, import.meta.url), "utf8"),
      readFile(new URL(`../supabase/rollback/${governanceLifecycleMigrationName}`, import.meta.url), "utf8"),
      readFile(new URL(`../supabase/migrations/${retentionMigrationName}`, import.meta.url), "utf8"),
      readFile(new URL("../supabase/migrations/20260923125730_documents_ledger_evidence_guard.sql", import.meta.url), "utf8"),
    ]);
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      const initial = await state(client);
      assert.equal(initial.table_owner, "documents_store_owner");
      assert.equal(initial.capability_schema, true);

      for (let rehearsal = 0; rehearsal < 2; rehearsal += 1) {
        await client.query(governanceRollback);
        await client.query("begin");
        try {
          await client.query(emptyDocumentsRetentionTeardown);
          await client.query("commit");
        } catch (error) {
          await client.query("rollback");
          throw error;
        }
        await client.query(registryRollback);
        await client.query(rollback);
        const predecessor = await state(client);
        assert.deepEqual(
          {
            document_count: predecessor.document_count,
            table_owner: predecessor.table_owner,
            capability_schema: predecessor.capability_schema,
            browser_reads: predecessor.browser_reads,
            browser_removes: predecessor.browser_removes,
          },
          {
            document_count: initial.document_count,
            table_owner: "postgres",
            capability_schema: false,
            browser_reads: true,
            browser_removes: true,
          },
        );
        assert.match(predecessor.producer_definitions, /insert into public\.documents/iu);

        await client.query(forward);
        await client.query(registryForward);
        await client.query(governanceForward);
        await client.query(retentionForward);
        await client.query(ledgerGuardForward);
        const successor = await state(client);
        assert.deepEqual(
          {
            document_count: successor.document_count,
            table_owner: successor.table_owner,
            capability_schema: successor.capability_schema,
            browser_reads: successor.browser_reads,
            browser_removes: successor.browser_removes,
          },
          {
            document_count: initial.document_count,
            table_owner: "documents_store_owner",
            capability_schema: true,
            browser_reads: false,
            browser_removes: false,
          },
        );
        assert.match(successor.producer_definitions, /documents\.assert_registered_artifact_v1/iu);
        assert.doesNotMatch(successor.producer_definitions, /insert into public\.documents/iu);
        const workflowGrant = await client.query(String.raw`
          select has_function_privilege(
            'corporate_governance_workflow_executor',
            'documents.register_evidence_reference_v1(text,text,uuid,uuid,uuid,integer,text,text,text,bigint,uuid)',
            'EXECUTE'
          ) as allowed
        `);
        assert.equal(workflowGrant.rows[0].allowed, true);
        const retentionGrant = await client.query(`select
          has_function_privilege('shareholder_register_filing_executor',
            'documents.retain_verified_rf_evidence_v1(text,uuid,uuid,uuid,integer,text,text,bigint,text,uuid)',
            'EXECUTE') as capture,
          has_function_privilege('shareholder_register_filing_executor',
            'documents.assert_retained_metadata_v1(text,text)', 'EXECUTE') as metadata`);
        assert.deepEqual(retentionGrant.rows[0], { capture: true, metadata: true });
      }
    } finally {
      await client.end();
    }
  },
);
