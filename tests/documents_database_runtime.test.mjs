import assert from "node:assert/strict";
import { randomInt, randomUUID } from "node:crypto";
import test from "node:test";
import pg from "pg";

const { Client } = pg;
const databaseUrl = process.env.DATABASE_URL;

async function expectDatabaseError(client, query, pattern) {
  await client.query("savepoint expected_error");
  try {
    await assert.rejects(client.query(query), pattern);
  } finally {
    await client.query("rollback to savepoint expected_error");
  }
}

test(
  "documents metadata and evidence access are restricted to narrow backend capabilities",
  { skip: !databaseUrl && "DATABASE_URL is required", timeout: 60_000 },
  async () => {
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      const result = await client.query(String.raw`
        select
          (select relforcerowsecurity from pg_catalog.pg_class
            where oid='public.documents'::regclass) as force_rls,
          (select owner.rolname from pg_catalog.pg_class relation
            join pg_catalog.pg_roles owner on owner.oid=relation.relowner
            where relation.oid='public.documents'::regclass) as table_owner,
          has_table_privilege('documents_executor','public.documents','SELECT') as executor_reads_table,
          has_table_privilege('authenticated','public.documents','SELECT') as browser_reads_table,
          has_table_privilege('documents_store_owner','public.company_memberships','SELECT') as store_reads_memberships,
          has_table_privilege('documents_store_owner','public.holding_actions','SELECT') as store_reads_evidence,
          has_function_privilege('documents_executor','documents.stage_upload_v1(jsonb,text)','EXECUTE') as executor_stages,
          has_function_privilege('authenticated','documents.stage_upload_v1(jsonb,text)','EXECUTE') as browser_stages,
          has_function_privilege('authenticated','public.remove_unlinked_document(uuid)','EXECUTE') as browser_legacy_removal,
          (select owner.rolname from pg_catalog.pg_proc procedure
            join pg_catalog.pg_roles owner on owner.oid=procedure.proowner
            where procedure.oid='documents.has_evidence_references_v1(uuid)'::regprocedure) as evidence_owner,
          (select count(*)::int from pg_catalog.pg_policies
            where schemaname='storage' and tablename='objects'
              and policyname in (
                'company members can read company document objects',
                'owners can upload company document objects',
                'owners can delete removed unlinked document objects'
              )) as legacy_storage_policies
      `);
      assert.deepEqual(result.rows[0], {
        force_rls: true,
        table_owner: "documents_store_owner",
        executor_reads_table: false,
        browser_reads_table: false,
        store_reads_memberships: false,
        store_reads_evidence: false,
        executor_stages: true,
        browser_stages: false,
        browser_legacy_removal: false,
        evidence_owner: "postgres",
        legacy_storage_policies: 0,
      });

      const producerDefinitions = await client.query(String.raw`
        select pg_catalog.pg_get_functiondef(
          'public.create_corporate_document_draft(jsonb)'::regprocedure
        ) || pg_catalog.pg_get_functiondef(
          'public.attest_corporate_signed_artifact(jsonb)'::regprocedure
        ) as definitions
      `);
      assert.match(producerDefinitions.rows[0].definitions, /documents\.assert_registered_artifact_v1/iu);
      assert.doesNotMatch(producerDefinitions.rows[0].definitions, /insert into public\.documents/iu);
    } finally {
      await client.end();
    }
  },
);

test(
  "documents functions enforce scoped roles, lifecycle integrity, listing, removal, and restore",
  { skip: !databaseUrl && "DATABASE_URL is required", timeout: 60_000 },
  async () => {
    const client = new Client({ connectionString: databaseUrl });
    const actorId = randomUUID();
    const companyId = randomUUID();
    const documentId = randomUUID();
    const orgNumber = String(randomInt(100_000_000, 1_000_000_000));
    const storageKey = `${companyId}/2026/${documentId}/bilag.pdf`;
    const request = {
      documentId,
      companyId,
      incomeYear: 2026,
      documentType: "accounting_document",
      linkedTo: "workspace",
      name: "bilag.pdf",
      storageKey,
      contentType: "application/pdf",
      declaredByteLength: 9,
      finalStatus: "attached",
    };

    await client.connect();
    await client.query("begin");
    try {
      await client.query(
        "insert into auth.users(id,email) values ($1,$2)",
        [actorId, `${actorId}@documents.test`],
      );
      await client.query(String.raw`
        insert into public.companies(
          id,org_number,name,entity_type,address,postal_code,city,status_text,source,created_by
        ) values ($1,$2,'Documents AS','AS','Testveien 1','0150','Oslo','Active','test',$3)
      `, [companyId, orgNumber, actorId]);

      await client.query(String.raw`
        do $authority$ begin
          execute pg_catalog.format('grant documents_executor to %I', current_user);
        end $authority$
      `);
      await client.query("set local role documents_executor");
      await client.query(
        "select pg_catalog.set_config('talli.verified_actor_id',$1,true)",
        [actorId],
      );
      await client.query(
        "select pg_catalog.set_config('talli.authorized_company_roles',$1,true)",
        [JSON.stringify({ [companyId]: "owner" })],
      );

      const staged = await client.query(
        "select id,status,retention_years from documents.stage_upload_v1($1::jsonb,$2)",
        [request, actorId],
      );
      assert.deepEqual(staged.rows[0], {
        id: documentId,
        status: "staged",
        retention_years: 5,
      });

      const finalized = await client.query(
        "select status,byte_length,content_sha256 from documents.finalize_upload_v1($1,$2,$3,$4)",
        [documentId, 9, "a".repeat(64), actorId],
      );
      assert.deepEqual(finalized.rows[0], {
        status: "attached",
        byte_length: "9",
        content_sha256: "a".repeat(64),
      });
      const finalizedReplay = await client.query(
        "select status,byte_length,content_sha256 from documents.finalize_upload_v1($1,$2,$3,$4)",
        [documentId, 9, "a".repeat(64), actorId],
      );
      assert.deepEqual(finalizedReplay.rows, finalized.rows);

      const listed = await client.query(
        "select id from documents.list_documents_v1($1::uuid[],$2)",
        [[companyId], actorId],
      );
      assert.deepEqual(listed.rows, [{ id: documentId }]);

      await client.query(
        "select pg_catalog.set_config('talli.authorized_company_roles',$1,true)",
        [JSON.stringify({ [companyId]: "reviewer" })],
      );
      await expectDatabaseError(
        client,
        {
          text: "select * from documents.stage_upload_v1($1::jsonb,$2)",
          values: [{ ...request, documentId: randomUUID() }, actorId],
        },
        /documents_invalid_input/iu,
      );
      const reviewerList = await client.query(
        "select id from documents.list_documents_v1($1::uuid[],$2)",
        [[companyId], actorId],
      );
      assert.deepEqual(reviewerList.rows, [{ id: documentId }]);

      await client.query(
        "select pg_catalog.set_config('talli.authorized_company_roles','{}',true)",
      );
      const concealed = await client.query(
        "select id from documents.list_documents_v1($1::uuid[],$2)",
        [[companyId], actorId],
      );
      assert.deepEqual(concealed.rows, []);

      await client.query(
        "select pg_catalog.set_config('talli.authorized_company_roles',$1,true)",
        [JSON.stringify({ [companyId]: "owner" })],
      );
      const evidence = await client.query(
        "select documents.has_evidence_references_v1($1) as linked",
        [documentId],
      );
      assert.equal(evidence.rows[0].linked, false);

      const removed = await client.query(
        "select status,removed_from_status from documents.mark_removed_v1($1,$2,$3)",
        [documentId, "duplicate", actorId],
      );
      assert.deepEqual(removed.rows[0], {
        status: "removed",
        removed_from_status: "attached",
      });
      await client.query(
        "select documents.restore_after_storage_failure_v1($1,$2)",
        [documentId, actorId],
      );
      const restored = await client.query(
        "select status,removed_at,removal_reason from documents.get_document_v1($1,$2)",
        [documentId, actorId],
      );
      assert.deepEqual(restored.rows[0], {
        status: "attached",
        removed_at: null,
        removal_reason: null,
      });

      await client.query("reset role");
      await client.query(
        `insert into investments.source_fact_registry(
           company_id,source_capability,source_record_id,source_revision,fact_sha256
         ) values ($1,'DOCUMENTS',$2,1,$3)`,
        [companyId, documentId, "b".repeat(64)],
      );
      await client.query("set local role documents_executor");
      const investmentEvidence = await client.query(
        "select documents.has_evidence_references_v1($1) as linked",
        [documentId],
      );
      assert.equal(investmentEvidence.rows[0].linked, true);
      await expectDatabaseError(
        client,
        {
          text: "select * from documents.mark_removed_v1($1,$2,$3)",
          values: [documentId, "duplicate", actorId],
        },
        /documents_evidence_linked/iu,
      );
    } finally {
      await client.query("rollback");
      await client.end();
    }
  },
);
