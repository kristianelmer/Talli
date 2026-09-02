import assert from "node:assert/strict";
import test from "node:test";
import pg from "pg";

const { Client } = pg;
const databaseUrl = process.env.DATABASE_URL;

test(
  "governance tables and workflow routines are isolated behind the backend role",
  { skip: !databaseUrl && "DATABASE_URL is required", timeout: 60_000 },
  async () => {
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      const result = await client.query(String.raw`
        select
          (select bool_and(relation.relforcerowsecurity)
             from pg_catalog.pg_class relation
            where relation.oid = any(array[
              'corporate_governance.owner_dividend_accounting_policies'::regclass,
              'corporate_governance.owner_dividend_decisions'::regclass,
              'corporate_governance.owner_dividend_artifacts'::regclass,
              'corporate_governance.owner_dividend_events'::regclass,
              'corporate_governance.owner_dividend_finalizations'::regclass,
              'corporate_governance.owner_dividend_payments'::regclass
            ])) as every_table_forces_rls,
          (select count(distinct owner.rolname)::int
             from pg_catalog.pg_class relation
             join pg_catalog.pg_roles owner on owner.oid = relation.relowner
            where relation.oid = any(array[
              'corporate_governance.owner_dividend_accounting_policies'::regclass,
              'corporate_governance.owner_dividend_decisions'::regclass,
              'corporate_governance.owner_dividend_artifacts'::regclass,
              'corporate_governance.owner_dividend_events'::regclass,
              'corporate_governance.owner_dividend_finalizations'::regclass,
              'corporate_governance.owner_dividend_payments'::regclass
            ]) and owner.rolname = 'corporate_governance_store_owner')
            as store_owner_count,
          has_table_privilege(
            'corporate_governance_workflow_executor',
            'corporate_governance.owner_dividend_decisions', 'SELECT'
          ) as executor_reads_table,
          has_table_privilege(
            'authenticated',
            'corporate_governance.owner_dividend_decisions', 'SELECT'
          ) as browser_reads_table,
          has_function_privilege(
            'corporate_governance_workflow_executor',
            'corporate_governance.propose_owner_dividend_v1(jsonb,jsonb,jsonb,text)',
            'EXECUTE'
          ) as executor_proposes,
          has_function_privilege(
            'authenticated',
            'corporate_governance.propose_owner_dividend_v1(jsonb,jsonb,jsonb,text)',
            'EXECUTE'
          ) as browser_proposes,
          has_function_privilege(
            'corporate_governance_workflow_executor',
            'ledger.post_corporate_governance_entry_v1(text,uuid,integer,text,text,jsonb,text,text,text,text,uuid)',
            'EXECUTE'
          ) as executor_posts_typed_ledger,
          has_function_privilege(
            'corporate_governance_workflow_executor',
            'ledger.post_entry_with_id_v1(text,uuid,integer,text,text,jsonb,jsonb,boolean,text,text,text,text,uuid)',
            'EXECUTE'
          ) as executor_posts_generic_ledger,
          has_function_privilege(
            'corporate_governance_workflow_executor',
            'banking.claim_owner_dividend_transaction_v1(jsonb,uuid,text)',
            'EXECUTE'
          ) as executor_claims_typed_bank,
          has_function_privilege(
            'corporate_governance_workflow_executor',
            'banking.claim_transaction_for_external_action_v1(jsonb,uuid,text)',
            'EXECUTE'
          ) as executor_claims_generic_bank
      `);
      assert.deepEqual(result.rows[0], {
        every_table_forces_rls: true,
        store_owner_count: 1,
        executor_reads_table: false,
        browser_reads_table: false,
        executor_proposes: true,
        browser_proposes: false,
        executor_posts_typed_ledger: true,
        executor_posts_generic_ledger: false,
        executor_claims_typed_bank: true,
        executor_claims_generic_bank: false,
      });

      await client.query("begin");
      try {
        await client.query(String.raw`
          do $authority$ begin
            execute pg_catalog.format(
              'grant corporate_governance_workflow_executor to %I',
              current_user
            );
          end $authority$
        `);
        await client.query(
          "set local role corporate_governance_workflow_executor",
        );
        await assert.rejects(
          client.query(
            "select * from corporate_governance.owner_dividend_decisions",
          ),
          /permission denied/iu,
        );
      } finally {
        await client.query("rollback");
      }
    } finally {
      await client.end();
    }
  },
);
