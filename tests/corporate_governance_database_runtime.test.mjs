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
              'corporate_governance.owner_dividend_payments'::regclass,
              'corporate_governance.shareholder_loans'::regclass
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
              'corporate_governance.owner_dividend_payments'::regclass,
              'corporate_governance.shareholder_loans'::regclass
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
            'corporate_governance.prepare_shareholder_loan_v1(jsonb,text)',
            'EXECUTE'
          ) as executor_prepares_shareholder_loan,
          has_function_privilege(
            'authenticated',
            'corporate_governance.prepare_shareholder_loan_v1(jsonb,text)',
            'EXECUTE'
          ) as browser_prepares_shareholder_loan,
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
            'banking.claim_corporate_governance_transaction_v1(jsonb,uuid,text)',
            'EXECUTE'
          ) as executor_claims_governance_bank,
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
        executor_prepares_shareholder_loan: true,
        browser_prepares_shareholder_loan: false,
        executor_posts_typed_ledger: true,
        executor_posts_generic_ledger: false,
        executor_claims_typed_bank: true,
        executor_claims_governance_bank: true,
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

test(
  "legacy shareholder-loan replay requires every canonical fact to match",
  { skip: !databaseUrl && "DATABASE_URL is required", timeout: 60_000 },
  async () => {
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    const actorId = "91000000-0000-4000-8000-000000000145";
    const companyId = "92000000-0000-4000-8000-000000000145";
    const actionId = "93000000-0000-4000-8000-000000000145";
    const entryId = "94000000-0000-4000-8000-000000000145";
    const exactRequest = {
      actionId,
      companyId,
      incomeYear: 2025,
      ledgerEntryId: entryId,
      loanDate: "2025-03-01",
      amountOre: 125050,
      direction: "shareholder_to_company",
      counterpartyName: "Eier Holding AS",
      documentStatus: "not_required",
      interestModelled: false,
      relatedPartySecurity: false,
      bankTransactionId: null,
      documentId: null,
      idempotencyKey: "runtime-replay-legacy-145",
      correlationId: "runtime-replay-legacy-145",
    };
    try {
      await client.query("begin");
      await client.query(
        "insert into auth.users (id, is_sso_user, is_anonymous) values ($1::uuid, false, false)",
        [actorId],
      );
      await client.query(
        "insert into public.companies (id, org_number, name, entity_type, created_by) values ($1::uuid, '900000145', 'Replay AS', 'AS', $2::uuid)",
        [companyId, actorId],
      );
      await client.query(
        String.raw`
          insert into ledger.entries (
            id, company_id, income_year, entry_kind, memo, lines, risk_flags,
            posted_at, created_by, created_at, source_capability,
            source_record_id, correlation_id
          ) values (
            $1::uuid, $2::uuid, 2025, 'SHAREHOLDER_LOAN', 'Legacy replay',
            '[{"account":"1920","description":"Bank","debit":"1250.50","credit":"0"},{"account":"2255","description":"Loan","debit":"0","credit":"1250.50"}]'::jsonb,
            '[]'::jsonb, pg_catalog.now(), $3::uuid,
            pg_catalog.now(), 'CORPORATE_GOVERNANCE', $4, 'legacy-replay-145'
          )
        `,
        [entryId, companyId, actorId, actionId],
      );
      await client.query(String.raw`
        do $authority$ begin
          execute pg_catalog.format(
            'grant corporate_governance_store_owner, corporate_governance_workflow_executor to %I',
            current_user
          );
        end $authority$;
        set local role corporate_governance_store_owner;
        alter table corporate_governance.shareholder_loans no force row level security;
      `);
      await client.query(
        String.raw`
          insert into corporate_governance.shareholder_loans (
            action_id, company_id, income_year, loan_date, amount_ore,
            direction, counterparty_name, document_status,
            interest_modelled, related_party_security, accounting_entry_id,
            idempotency_key, correlation_id, request_fingerprint,
            legacy_imported, created_by
          ) values (
            $1::uuid, $2::uuid, 2025, date '2025-03-01', 125050,
            'shareholder_to_company', 'Eier Holding AS', 'not_required',
            false, false, $3::uuid, 'legacy-import-runtime-145',
            'legacy-import-runtime-145', repeat('a', 64), true, $4::uuid
          )
        `,
        [actionId, companyId, entryId, actorId],
      );
      await client.query(String.raw`
        create or replace function corporate_governance.assert_owner_v1(
          p_company_id uuid,
          p_income_year integer,
          p_verified_subject text,
          p_consequential boolean
        ) returns uuid language sql volatile security definer set search_path = ''
        as $function$ select p_verified_subject::uuid $function$;
        reset role;
        set local role corporate_governance_workflow_executor;
      `);

      const exact = await client.query(
        "select corporate_governance.prepare_shareholder_loan_v1($1::jsonb, $2)",
        [JSON.stringify(exactRequest), actorId],
      );
      assert.equal(exact.rows[0].prepare_shareholder_loan_v1.replay.replayed, true);

      const variants = [
        { amountOre: 125051 },
        { loanDate: "2025-03-02" },
        { direction: "company_to_corporate_shareholder" },
        { counterpartyName: "Et annet AS" },
        { documentStatus: "attached" },
        { interestModelled: true },
        { relatedPartySecurity: true },
        { bankTransactionId: "95000000-0000-4000-8000-000000000145" },
        { documentId: "96000000-0000-4000-8000-000000000145" },
      ];
      for (const [index, changed] of variants.entries()) {
        await client.query(`savepoint changed_${index}`);
        await assert.rejects(
          client.query(
            "select corporate_governance.prepare_shareholder_loan_v1($1::jsonb, $2)",
            [JSON.stringify({ ...exactRequest, ...changed }), actorId],
          ),
          /corporate_governance_idempotency_conflict/iu,
        );
        await client.query(`rollback to savepoint changed_${index}`);
      }
    } finally {
      await client.query("rollback").catch(() => undefined);
      await client.end();
    }
  },
);
