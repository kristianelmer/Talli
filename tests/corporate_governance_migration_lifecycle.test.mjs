import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import pg from "pg";

const { Client } = pg;
const databaseUrl = process.env.DATABASE_URL;
const ownerMigrationName =
  "20260902040000_corporate_governance_owner_dividend.sql";
const loanMigrationName =
  "20260902070000_corporate_governance_shareholder_loan.sql";
const loanInitPlanMigrationName =
  "20260902084230_corporate_governance_shareholder_loan_rls_initplan_cleanup.sql";
const annualMigrationName =
  "20260902090000_corporate_governance_annual_close.sql";
const lifecycleMigrationName =
  "20260902100000_corporate_governance_artifact_lifecycle.sql";

test("artifact persistence does not duplicate Python signer policy", async () => {
  const forward = await readFile(
    new URL(`../supabase/migrations/${lifecycleMigrationName}`, import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(forward, /v_required_signers|v_actual_signers/iu);
  assert.match(forward, /jsonb_typeof\(signer\).*'string'/isu);
});

async function state(client) {
  const result = await client.query(String.raw`
    select
      pg_catalog.to_regnamespace('corporate_governance') is not null
        as capability_schema,
      pg_catalog.to_regclass(
        'corporate_governance.owner_dividend_decisions'
      ) is not null as decision_table,
      pg_catalog.to_regclass(
        'corporate_governance.shareholder_loans'
      ) is not null as shareholder_loan_table,
      pg_catalog.to_regprocedure(
        'ledger.post_corporate_governance_entry_v1(text,uuid,integer,text,text,jsonb,text,text,text,text,uuid)'
      ) is not null as ledger_bridge,
      pg_catalog.to_regprocedure(
        'banking.claim_owner_dividend_transaction_v1(jsonb,uuid,text)'
      ) is not null as owner_banking_bridge,
      pg_catalog.to_regprocedure(
        'banking.claim_corporate_governance_transaction_v1(jsonb,uuid,text)'
      ) is not null as shareholder_loan_banking_bridge
  `);
  return result.rows[0];
}

async function assertSupersededEvidence(client, canonical) {
  const result = canonical
    ? await client.query(String.raw`
        select
          (corporate_governance.owner_dividend_lifecycle_v1(
            '97000000-0000-4000-8000-000000000148'::uuid, false
          ) ->> 'state') as state,
          pg_catalog.count(*)::int as event_count,
          (select decision.supersedes_decision_id::text
             from corporate_governance.owner_dividend_decisions decision
            where decision.id =
              '97000000-0000-4000-8000-000000000148'::uuid)
            as supersedes_decision_id,
          (select decision.supersedes_document_set_id::text
             from corporate_governance.owner_dividend_decisions decision
            where decision.id =
              '97000000-0000-4000-8000-000000000148'::uuid)
            as supersedes_set_id,
          (select pg_catalog.to_char(
                    evidence.occurred_at at time zone 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS"Z"'
                  )
             from corporate_governance.owner_dividend_events evidence
            where evidence.id =
              '97000000-0000-4000-8000-000000000152'::uuid)
            as occurred_at,
          (select pg_catalog.to_char(
                    evidence.created_at at time zone 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS"Z"'
                  )
             from corporate_governance.owner_dividend_events evidence
            where evidence.id =
              '97000000-0000-4000-8000-000000000152'::uuid)
            as created_at
        from corporate_governance.owner_dividend_events event
        where event.decision_id =
          '97000000-0000-4000-8000-000000000148'::uuid
          and event.id in (
            '97000000-0000-4000-8000-000000000150'::uuid,
            '97000000-0000-4000-8000-000000000151'::uuid,
            '97000000-0000-4000-8000-000000000152'::uuid
          )
      `)
    : await client.query(String.raw`
        select
          'superseded'::text as state,
          pg_catalog.count(*)::int as event_count,
          (select decision.supersedes_decision_id::text
             from public.corporate_decisions decision
            where decision.id =
              '97000000-0000-4000-8000-000000000148'::uuid)
            as supersedes_decision_id,
          (select document_set.supersedes_set_id::text
             from public.corporate_document_sets document_set
            where document_set.id =
              '97000000-0000-4000-8000-000000000149'::uuid)
            as supersedes_set_id,
          (select pg_catalog.to_char(
                    evidence.occurred_at at time zone 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS"Z"'
                  )
             from public.corporate_document_events evidence
            where evidence.id =
              '97000000-0000-4000-8000-000000000152'::uuid)
            as occurred_at,
          (select pg_catalog.to_char(
                    evidence.created_at at time zone 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS"Z"'
                  )
             from public.corporate_document_events evidence
            where evidence.id =
              '97000000-0000-4000-8000-000000000152'::uuid)
            as created_at
        from public.corporate_document_events event
        where event.decision_id =
          '97000000-0000-4000-8000-000000000148'::uuid
          and event.id in (
            '97000000-0000-4000-8000-000000000150'::uuid,
            '97000000-0000-4000-8000-000000000151'::uuid,
            '97000000-0000-4000-8000-000000000152'::uuid
          )
      `);
  assert.deepEqual(result.rows[0], {
    state: "superseded",
    event_count: 3,
    supersedes_decision_id: "97000000-0000-4000-8000-000000000143",
    supersedes_set_id: "97000000-0000-4000-8000-000000000144",
    occurred_at: "2025-01-02T03:04:08Z",
    created_at: "2025-01-02T04:04:08Z",
  });
}

test(
  "governance rollback and recutover are lossless and repeatable twice",
  { skip: !databaseUrl && "DATABASE_URL is required", timeout: 120_000 },
  async () => {
    const [
      ownerForward,
      ownerRollback,
      loanForward,
      loanRollback,
      annualForward,
      annualRollback,
      lifecycleForward,
      lifecycleRollback,
    ] =
      await Promise.all([
      readFile(
        new URL(
          `../supabase/migrations/${ownerMigrationName}`,
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          `../supabase/rollback/${ownerMigrationName}`,
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          `../supabase/migrations/${loanMigrationName}`,
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          `../supabase/rollback/${loanMigrationName}`,
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL(`../supabase/migrations/${annualMigrationName}`, import.meta.url),
        "utf8",
      ),
      readFile(
        new URL(`../supabase/rollback/${annualMigrationName}`, import.meta.url),
        "utf8",
      ),
      readFile(
        new URL(`../supabase/migrations/${lifecycleMigrationName}`, import.meta.url),
        "utf8",
      ),
      readFile(
        new URL(`../supabase/rollback/${lifecycleMigrationName}`, import.meta.url),
        "utf8",
      ),
    ]);
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      await client.query(String.raw`
        insert into auth.users (id, is_sso_user, is_anonymous)
        values ('97000000-0000-4000-8000-000000000147', false, false)
        on conflict (id) do nothing;
        insert into public.companies (
          id, org_number, name, entity_type, created_by
        ) values (
          '97000000-0000-4000-8000-000000000146', '900000148',
          'Superseded Evidence AS', 'AS',
          '97000000-0000-4000-8000-000000000147'
        ) on conflict (id) do nothing;
        insert into public.company_memberships (
          company_id, user_id, role, accepted_at
        ) values (
          '97000000-0000-4000-8000-000000000146',
          '97000000-0000-4000-8000-000000000147', 'owner',
          pg_catalog.now()
        ) on conflict (company_id, user_id) do nothing;
        select pg_catalog.set_config(
          'request.jwt.claim.sub',
          '97000000-0000-4000-8000-000000000147', false
        );
        select pg_catalog.set_config(
          'request.jwt.claims',
          '{"sub":"97000000-0000-4000-8000-000000000147","aal":"aal2"}',
          false
        );
        insert into public.annual_data (
          id, company_id, income_year, answers, completed_by, updated_by
        ) values (
          '97000000-0000-4000-8000-000000000145',
          '97000000-0000-4000-8000-000000000146', 2024, '{}'::jsonb,
          '97000000-0000-4000-8000-000000000147',
          '97000000-0000-4000-8000-000000000147'
        ) on conflict (id) do nothing;
        insert into public.corporate_decisions (
          id, company_id, income_year, decision_kind,
          annual_close_source_id, source_hash, canonical_input,
          decision_hash, created_by, created_at
        ) values (
          '97000000-0000-4000-8000-000000000143',
          '97000000-0000-4000-8000-000000000146', 2025,
          'owner_dividend', '97000000-0000-4000-8000-000000000145',
          repeat('8', 64),
          pg_catalog.jsonb_build_object(
            'template_family', 'norwegian_simple_as',
            'template_version', 'superseded-evidence-v0',
            'dividend', pg_catalog.jsonb_build_object('amount_ore', 9000)
          ), repeat('9', 64),
          '97000000-0000-4000-8000-000000000147',
          '2025-01-01 03:04:05+00'::timestamptz
        ) on conflict (id) do nothing;
        insert into public.corporate_document_sets (
          id, company_id, income_year, decision_id, template_family,
          template_version, decision_hash, created_by, created_at
        ) values (
          '97000000-0000-4000-8000-000000000144',
          '97000000-0000-4000-8000-000000000146', 2025,
          '97000000-0000-4000-8000-000000000143', 'norwegian_simple_as',
          'superseded-evidence-v0', repeat('9', 64),
          '97000000-0000-4000-8000-000000000147',
          '2025-01-01 03:04:05+00'::timestamptz
        ) on conflict (id) do nothing;
        insert into public.corporate_decisions (
          id, company_id, income_year, decision_kind,
          annual_close_source_id, source_hash, canonical_input,
          decision_hash, supersedes_decision_id, created_by, created_at
        ) values (
          '97000000-0000-4000-8000-000000000148',
          '97000000-0000-4000-8000-000000000146', 2025,
          'owner_dividend', '97000000-0000-4000-8000-000000000145',
          repeat('a', 64),
          pg_catalog.jsonb_build_object(
            'template_family', 'norwegian_simple_as',
            'template_version', 'superseded-evidence-v1',
            'dividend', pg_catalog.jsonb_build_object('amount_ore', 10000)
          ), repeat('b', 64),
          '97000000-0000-4000-8000-000000000143',
          '97000000-0000-4000-8000-000000000147',
          '2025-01-02 03:04:05+00'::timestamptz
        ) on conflict (id) do nothing;
        insert into public.corporate_document_sets (
          id, company_id, income_year, decision_id, template_family,
          template_version, decision_hash, supersedes_set_id,
          created_by, created_at
        ) values (
          '97000000-0000-4000-8000-000000000149',
          '97000000-0000-4000-8000-000000000146', 2025,
          '97000000-0000-4000-8000-000000000148', 'norwegian_simple_as',
          'superseded-evidence-v1', repeat('b', 64),
          '97000000-0000-4000-8000-000000000144',
          '97000000-0000-4000-8000-000000000147',
          '2025-01-02 03:04:05+00'::timestamptz
        ) on conflict (id) do nothing;
        do $authority$ begin
          execute pg_catalog.format(
            'grant corporate_governance_store_owner to %I', current_user
          );
        end $authority$;
        set role corporate_governance_store_owner;
        select pg_catalog.set_config(
          'talli.verified_actor_id',
          '97000000-0000-4000-8000-000000000147', false
        );
        insert into corporate_governance.owner_dividend_decisions (
          id, document_set_id, company_id, income_year,
          annual_close_source_id, source_hash, canonical_input,
          decision_hash, declared_amount_ore, idempotency_key,
          correlation_id, request_fingerprint, supersedes_decision_id,
          supersedes_document_set_id, created_by, created_at
        ) values (
          '97000000-0000-4000-8000-000000000148',
          '97000000-0000-4000-8000-000000000149',
          '97000000-0000-4000-8000-000000000146', 2025,
          '97000000-0000-4000-8000-000000000145', repeat('a', 64),
          pg_catalog.jsonb_build_object(
            'decisionId', '97000000-0000-4000-8000-000000000148',
            'documentSetId', '97000000-0000-4000-8000-000000000149',
            'companyId', '97000000-0000-4000-8000-000000000146',
            'incomeYear', 2025, 'sourceHash', repeat('a', 64),
            'decisionHash', repeat('b', 64),
            'dividend', pg_catalog.jsonb_build_object('amountOre', 10000)
          ), repeat('b', 64), 10000, 'superseded-decision-148',
          'superseded-decision-148', repeat('c', 64),
          '97000000-0000-4000-8000-000000000143',
          '97000000-0000-4000-8000-000000000144',
          '97000000-0000-4000-8000-000000000147',
          '2025-01-02 03:04:05+00'::timestamptz
        ) on conflict (id) do nothing;
        reset role;
        alter table corporate_governance.owner_dividend_decisions
          disable trigger owner_dividend_decisions_immutable;
        update corporate_governance.owner_dividend_decisions
        set supersedes_decision_id =
              '97000000-0000-4000-8000-000000000143',
            supersedes_document_set_id =
              '97000000-0000-4000-8000-000000000144'
        where id = '97000000-0000-4000-8000-000000000148';
        alter table corporate_governance.owner_dividend_decisions
          enable trigger owner_dividend_decisions_immutable;
        insert into public.corporate_document_events (
          id, company_id, income_year, decision_id, set_id, event_kind,
          actor_id, occurred_at, decision_hash, metadata,
          idempotency_key, created_at
        ) values
          (
            '97000000-0000-4000-8000-000000000150',
            '97000000-0000-4000-8000-000000000146', 2025,
            '97000000-0000-4000-8000-000000000148',
            '97000000-0000-4000-8000-000000000149', 'generated',
            '97000000-0000-4000-8000-000000000147',
            '2025-01-02 03:04:06+00', repeat('b', 64),
            '{"artifact":"board"}'::jsonb, 'legacy-generated-board-148',
            '2025-01-02 04:04:06+00'
          ),
          (
            '97000000-0000-4000-8000-000000000151',
            '97000000-0000-4000-8000-000000000146', 2025,
            '97000000-0000-4000-8000-000000000148',
            '97000000-0000-4000-8000-000000000149', 'generated',
            '97000000-0000-4000-8000-000000000147',
            '2025-01-02 03:04:07+00', repeat('b', 64),
            '{"artifact":"minutes"}'::jsonb, 'legacy-generated-minutes-148',
            '2025-01-02 04:04:07+00'
          ),
          (
            '97000000-0000-4000-8000-000000000152',
            '97000000-0000-4000-8000-000000000146', 2025,
            '97000000-0000-4000-8000-000000000148',
            '97000000-0000-4000-8000-000000000149', 'superseded',
            '97000000-0000-4000-8000-000000000147',
            '2025-01-02 03:04:08+00', repeat('b', 64), '{}'::jsonb,
            'legacy-superseded-148', '2025-01-02 04:04:08+00'
          )
        on conflict (id) do nothing;
        set role corporate_governance_store_owner;
        insert into corporate_governance.owner_dividend_events (
          id, decision_id, document_set_id, company_id, income_year,
          event_kind, decision_hash, metadata, idempotency_key,
          correlation_id, request_fingerprint, created_by,
          occurred_at, created_at
        ) values
          (
            '97000000-0000-4000-8000-000000000150',
            '97000000-0000-4000-8000-000000000148',
            '97000000-0000-4000-8000-000000000149',
            '97000000-0000-4000-8000-000000000146', 2025,
            'documents_registered', repeat('b', 64),
            '{"artifact":"board"}'::jsonb, 'canonical-generated-board-148',
            'canonical-generated-board-148', repeat('d', 64),
            '97000000-0000-4000-8000-000000000147',
            '2025-01-02 03:04:06+00', '2025-01-02 04:04:06+00'
          ),
          (
            '97000000-0000-4000-8000-000000000151',
            '97000000-0000-4000-8000-000000000148',
            '97000000-0000-4000-8000-000000000149',
            '97000000-0000-4000-8000-000000000146', 2025,
            'documents_registered', repeat('b', 64),
            '{"artifact":"minutes"}'::jsonb,
            'canonical-generated-minutes-148',
            'canonical-generated-minutes-148', repeat('e', 64),
            '97000000-0000-4000-8000-000000000147',
            '2025-01-02 03:04:07+00', '2025-01-02 04:04:07+00'
          ),
          (
            '97000000-0000-4000-8000-000000000152',
            '97000000-0000-4000-8000-000000000148',
            '97000000-0000-4000-8000-000000000149',
            '97000000-0000-4000-8000-000000000146', 2025,
            'superseded', repeat('b', 64), '{}'::jsonb,
            'canonical-superseded-148', 'canonical-superseded-148',
            repeat('f', 64), '97000000-0000-4000-8000-000000000147',
            '2025-01-02 03:04:08+00', '2025-01-02 04:04:08+00'
        )
        on conflict (id) do nothing;
        reset role;
        alter table corporate_governance.owner_dividend_events
          disable trigger owner_dividend_events_immutable;
        update corporate_governance.owner_dividend_events
        set occurred_at = case id
              when '97000000-0000-4000-8000-000000000150'::uuid
                then '2025-01-02 03:04:06+00'::timestamptz
              when '97000000-0000-4000-8000-000000000151'::uuid
                then '2025-01-02 03:04:07+00'::timestamptz
              else '2025-01-02 03:04:08+00'::timestamptz
            end,
            created_at = case id
              when '97000000-0000-4000-8000-000000000150'::uuid
                then '2025-01-02 04:04:06+00'::timestamptz
              when '97000000-0000-4000-8000-000000000151'::uuid
                then '2025-01-02 04:04:07+00'::timestamptz
              else '2025-01-02 04:04:08+00'::timestamptz
            end
        where id in (
          '97000000-0000-4000-8000-000000000150'::uuid,
          '97000000-0000-4000-8000-000000000151'::uuid,
          '97000000-0000-4000-8000-000000000152'::uuid
        );
        alter table corporate_governance.owner_dividend_events
          enable trigger owner_dividend_events_immutable;
      `);
      assert.deepEqual(await state(client), {
        capability_schema: true,
        decision_table: true,
        shareholder_loan_table: true,
        ledger_bridge: true,
        owner_banking_bridge: true,
        shareholder_loan_banking_bridge: true,
      });
      await assertSupersededEvidence(client, true);
      for (let rehearsal = 0; rehearsal < 2; rehearsal += 1) {
        await client.query(lifecycleRollback);
        await client.query(annualRollback);
        await client.query(loanRollback);
        await client.query(ownerRollback);
        assert.deepEqual(await state(client), {
          capability_schema: false,
          decision_table: false,
          shareholder_loan_table: false,
          ledger_bridge: false,
          owner_banking_bridge: false,
          shareholder_loan_banking_bridge: false,
        });
        await assertSupersededEvidence(client, false);
        await client.query(ownerForward);
        await client.query(loanForward);
        await client.query(annualForward);
        await client.query(lifecycleForward);
        assert.deepEqual(await state(client), {
          capability_schema: true,
          decision_table: true,
          shareholder_loan_table: true,
          ledger_bridge: true,
          owner_banking_bridge: true,
          shareholder_loan_banking_bridge: true,
        });
        await assertSupersededEvidence(client, true);
      }
    } finally {
      await client.end();
    }
  },
);

test(
  "shareholder-loan RLS cleanup rollback and recutover are repeatable twice",
  { skip: !databaseUrl && "DATABASE_URL is required", timeout: 120_000 },
  async () => {
    const [forward, rollback] = await Promise.all([
      readFile(
        new URL(
          `../supabase/migrations/${loanInitPlanMigrationName}`,
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          `../supabase/rollback/${loanInitPlanMigrationName}`,
          import.meta.url,
        ),
        "utf8",
      ),
    ]);
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      for (let rehearsal = 0; rehearsal < 2; rehearsal += 1) {
        await client.query(rollback);
        const restored = await client.query(String.raw`
          select pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid)
            as expression
          from pg_catalog.pg_policy policy
          where policy.polrelid =
            'corporate_governance.shareholder_loans'::regclass
            and policy.polname = 'governance_owner_creates_shareholder_loans'
        `);
        assert.doesNotMatch(
          restored.rows[0].expression,
          /SELECT company_access_is_accepted_owner_v1/iu,
        );
        await client.query(forward);
        const optimized = await client.query(String.raw`
          select pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid)
            as expression
          from pg_catalog.pg_policy policy
          where policy.polrelid =
            'corporate_governance.shareholder_loans'::regclass
            and policy.polname = 'governance_owner_creates_shareholder_loans'
        `);
        assert.match(
          optimized.rows[0].expression,
          /SELECT company_access_is_accepted_owner_v1/iu,
        );
      }
    } finally {
      await client.end();
    }
  },
);
