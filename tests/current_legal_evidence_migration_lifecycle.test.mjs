import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import pg from "pg";

const { Client } = pg;
const databaseUrl = process.env.DATABASE_URL;
const reacceptSignature = String.raw`public.company_access_reaccept_agreement(
  uuid,uuid,uuid,text,boolean,text,date,text,text,text,date,text,text,text,text
)`;
const admitSignature = String.raw`public.company_access_admit_company_year(
  uuid,uuid,text,text,text,text,text,text,text,text,text,integer,date,
  text,text,text,text,text,text,text,text,text,text,date,text,text,text,
  date,text,text,text,date,text,text,text,text
)`;

test(
  "#196 legal evidence rollback fails closed twice, preserves evidence, and recuts over",
  {
    skip:
      !databaseUrl &&
      "DATABASE_URL is required for the legal-evidence lifecycle rehearsal",
    timeout: 120_000,
  },
  async () => {
    const [forward, rollback] = await Promise.all([
      readFile(
        new URL(
          "../supabase/migrations/20260830093000_current_legal_evidence.sql",
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          "../supabase/rollback/20260830093000_current_legal_evidence.sql",
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
          (select count(*)::int from public.customer_agreement_acceptances)
            as agreement_acceptances,
          (select count(*)::int from public.company_year_acceptances)
            as company_year_acceptances
      `);

      await client.query(rollback);
      await client.query(rollback);

      const disabled = await client.query(
        String.raw`
          select
            pg_catalog.pg_get_functiondef(
              'public.company_access_has_current_agreement_v1(uuid)'::regprocedure
            ) as helper_definition,
            has_function_privilege(
              'company_access_executor', $1, 'EXECUTE'
            ) as executor_can_reaccept,
            has_function_privilege(
              'company_access_executor', $2, 'EXECUTE'
            ) as executor_can_admit,
            (select count(*)::int from public.customer_agreement_acceptances)
              as agreement_acceptances,
            (select count(*)::int from public.company_year_acceptances)
              as company_year_acceptances
        `,
        [reacceptSignature, admitSignature],
      );
      assert.match(disabled.rows[0].helper_definition, /select false/iu);
      assert.equal(disabled.rows[0].executor_can_reaccept, false);
      assert.equal(disabled.rows[0].executor_can_admit, false);
      assert.deepEqual(
        {
          agreement_acceptances: disabled.rows[0].agreement_acceptances,
          company_year_acceptances: disabled.rows[0].company_year_acceptances,
        },
        before.rows[0],
      );

      await client.query(forward);
      const recutover = await client.query(
        String.raw`
          select
            pg_catalog.pg_get_functiondef(
              'public.company_access_has_current_agreement_v1(uuid)'::regprocedure
            ) as helper_definition,
            has_function_privilege(
              'company_access_executor', $1, 'EXECUTE'
            ) as executor_can_reaccept,
            has_function_privilege(
              'company_access_executor', $2, 'EXECUTE'
            ) as executor_can_admit,
            (select count(*)::int from public.customer_agreement_acceptances)
              as agreement_acceptances,
            (select count(*)::int from public.company_year_acceptances)
              as company_year_acceptances
        `,
        [reacceptSignature, admitSignature],
      );
      assert.match(recutover.rows[0].helper_definition, /2026-08-30/u);
      assert.match(
        recutover.rows[0].helper_definition,
        /afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04/u,
      );
      assert.equal(recutover.rows[0].executor_can_reaccept, true);
      assert.equal(recutover.rows[0].executor_can_admit, true);
      assert.deepEqual(
        {
          agreement_acceptances: recutover.rows[0].agreement_acceptances,
          company_year_acceptances: recutover.rows[0].company_year_acceptances,
        },
        before.rows[0],
      );
    } finally {
      await client.end();
    }
  },
);
