import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import pg from "pg";

const { Client } = pg;
const databaseUrl = process.env.DATABASE_URL;

test(
  "#200 rollback fails closed, preserves evidence, is repeatable, and recuts over",
  {
    skip:
      !databaseUrl &&
      "DATABASE_URL is required for the Supabase lifecycle rehearsal",
    timeout: 120_000,
  },
  async () => {
    const [forward, rollback] = await Promise.all([
      readFile(
        new URL(
          "../supabase/migrations/20260830091341_case_bound_support_access.sql",
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          "../supabase/rollback/20260830091341_case_bound_support_access.sql",
          import.meta.url,
        ),
        "utf8",
      ),
    ]);
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      const before = await client.query(String.raw`
      select
        (select count(*)::int from public.support_access_grants) grants,
        (select count(*)::int from public.support_access_operation_receipts) receipts,
        (select count(*)::int from public.support_case_openings) openings
    `);

      await client.query(rollback);
      await client.query(rollback);

      const disabled = await client.query(String.raw`
      select
        pg_catalog.pg_get_functiondef(
          'public.company_access_has_open_support_case_v1(uuid,uuid,text)'::regprocedure
        ) as helper_definition,
        has_function_privilege(
          'company_access_executor',
          'public.company_access_read_support_case(uuid)',
          'EXECUTE'
        ) as executor_can_read,
        (select count(*)::int from public.support_access_grants) grants,
        (select count(*)::int from public.support_access_operation_receipts) receipts,
        (select count(*)::int from public.support_case_openings) openings
    `);
      assert.equal(disabled.rows[0].executor_can_read, false);
      assert.deepEqual(
        {
          grants: disabled.rows[0].grants,
          receipts: disabled.rows[0].receipts,
          openings: disabled.rows[0].openings,
        },
        before.rows[0],
      );
      assert.match(disabled.rows[0].helper_definition, /select false/iu);

      await client.query(forward);
      const recutover = await client.query(String.raw`
      select
        has_function_privilege(
          'company_access_executor',
          'public.company_access_read_support_case(uuid)',
          'EXECUTE'
        ) as executor_can_read,
        (select count(*)::int from public.support_access_grants) grants,
        (select count(*)::int from public.support_access_operation_receipts) receipts,
        (select count(*)::int from public.support_case_openings) openings,
        exists (
          select 1 from pg_catalog.pg_policies
          where schemaname = 'public' and tablename = 'audit_events'
            and policyname = 'support_case_read_audit_events'
        ) as support_policy_restored
    `);
      assert.deepEqual(recutover.rows[0], {
        executor_can_read: true,
        ...before.rows[0],
        support_policy_restored: true,
      });
    } finally {
      await client.end();
    }
  },
);
