import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import pg from "pg";

const { Client } = pg;
const databaseUrl = process.env.DATABASE_URL;
const migrationName = "20260901233000_documents_capability.sql";

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
    const [forward, rollback] = await Promise.all([
      readFile(new URL(`../supabase/migrations/${migrationName}`, import.meta.url), "utf8"),
      readFile(new URL(`../supabase/rollback/${migrationName}`, import.meta.url), "utf8"),
    ]);
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      const initial = await state(client);
      assert.equal(initial.table_owner, "documents_store_owner");
      assert.equal(initial.capability_schema, true);

      for (let rehearsal = 0; rehearsal < 2; rehearsal += 1) {
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
      }
    } finally {
      await client.end();
    }
  },
);
