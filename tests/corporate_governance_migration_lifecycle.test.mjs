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
const companyIdentityMigrationName =
  "20260902095000_company_access_corporate_governance_identity.sql";
const lifecycleMigrationName =
  "20260902100000_corporate_governance_artifact_lifecycle.sql";
const hostedShapeParityMigrationName =
  "20260902105000_corporate_governance_hosted_shape_parity.sql";

async function assertGovernanceRolesCannotInheritCompanyAccessExecutor(client) {
  const result = await client.query(String.raw`
    select pg_catalog.count(*)::integer as unintended_members
    from pg_catalog.pg_auth_members membership
    join pg_catalog.pg_roles granted_role
      on granted_role.oid = membership.roleid
    join pg_catalog.pg_roles member_role
      on member_role.oid = membership.member
    where granted_role.rolname = 'company_access_executor'
      and member_role.rolname in (
        'corporate_governance_store_owner',
        'corporate_governance_workflow_executor',
        'backend_system_annual_data_reader',
        'ledger_store_owner'
      )
  `);
  assert.equal(result.rows[0].unintended_members, 0);
}

test("artifact persistence does not duplicate Python signer policy", async () => {
  const forward = await readFile(
    new URL(`../supabase/migrations/${lifecycleMigrationName}`, import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(forward, /v_required_signers|v_actual_signers/iu);
  assert.match(forward, /jsonb_typeof\(signer\).*'string'/isu);
});

test("hosted owner-dividend shape is upgraded before contract", async () => {
  const [forward, rollback] = await Promise.all([
    readFile(
      new URL(
        `../supabase/migrations/${hostedShapeParityMigrationName}`,
        import.meta.url,
      ),
      "utf8",
    ),
    readFile(
      new URL(
        `../supabase/rollback/${hostedShapeParityMigrationName}`,
        import.meta.url,
      ),
      "utf8",
    ),
  ]);

  assert.match(
    forward,
    /owner_dividend_finalizations[\s\S]+add column if not exists event_id uuid/iu,
  );
  assert.match(
    forward,
    /owner_dividend_finalizations[\s\S]+add column if not exists occurred_at timestamptz/iu,
  );
  assert.match(
    forward,
    /owner_dividend_payments[\s\S]+add column if not exists occurred_at timestamptz/iu,
  );
  assert.match(
    forward,
    /public\.corporate_document_events[\s\S]+event_kind = 'finalized'/iu,
  );
  assert.match(forward, /alter column event_id set not null/iu);
  assert.match(forward, /alter column occurred_at set not null/iu);
  assert.doesNotMatch(rollback, /drop column/iu);
});

test(
  "hosted owner-dividend predecessor shape recuts to the current canonical shape",
  { skip: !databaseUrl && "DATABASE_URL is required" },
  async () => {
    const forward = await readFile(
      new URL(
        `../supabase/migrations/${hostedShapeParityMigrationName}`,
        import.meta.url,
      ),
      "utf8",
    );
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      await client.query(String.raw`
        do $authority$ begin
          execute pg_catalog.format(
            'grant corporate_governance_store_owner to %I with set true',
            current_user
          );
        end $authority$;
        set role corporate_governance_store_owner;
        alter table corporate_governance.owner_dividend_finalizations
          drop column if exists event_id,
          drop column if exists occurred_at;
        alter table corporate_governance.owner_dividend_payments
          drop column if exists occurred_at;
        reset role;
        do $authority$ begin
          execute pg_catalog.format(
            'revoke corporate_governance_store_owner from %I', current_user
          );
        end $authority$;
      `);

      await client.query(forward);
      const result = await client.query(String.raw`
        select table_name, pg_catalog.array_agg(column_name order by column_name)
          as columns
        from information_schema.columns
        where table_schema = 'corporate_governance'
          and table_name in (
            'owner_dividend_finalizations', 'owner_dividend_payments'
          )
        group by table_name
        order by table_name
      `);
      const columnsByTable = Object.fromEntries(
        result.rows.map((row) => [row.table_name, row.columns]),
      );
      assert.ok(columnsByTable.owner_dividend_finalizations.includes("event_id"));
      assert.ok(columnsByTable.owner_dividend_finalizations.includes("occurred_at"));
      assert.ok(columnsByTable.owner_dividend_payments.includes("occurred_at"));
    } finally {
      await client.query(forward).catch(() => undefined);
      await client.end();
    }
  },
);

test("governance evidence is locked and revalidated before immutable insertion", async () => {
  const [forward, rollback, documents] = await Promise.all([
    readFile(
      new URL(`../supabase/migrations/${lifecycleMigrationName}`, import.meta.url),
      "utf8",
    ),
    readFile(
      new URL(`../supabase/rollback/${lifecycleMigrationName}`, import.meta.url),
      "utf8",
    ),
    readFile(
      new URL(
        "../supabase/migrations/20260902030000_documents_evidence_reference_registry.sql",
        import.meta.url,
      ),
      "utf8",
    ),
  ]);

  assert.match(
    documents,
    /create table documents\.evidence_references[\s\S]+function documents\.register_evidence_reference_v1[\s\S]+for update/iu,
  );
  assert.match(forward, /grant documents_store_owner to %I with set true/iu);
  assert.match(forward, /revoke documents_store_owner from %I/iu);
  assert.match(
    forward,
    /grant execute on function documents\.register_evidence_reference_v1[\s\S]+to corporate_governance_workflow_executor/iu,
  );
  assert.doesNotMatch(forward, /create or replace function documents\./iu);
  assert.match(
    forward,
    /function[\s\S]+backend_system\.register_corporate_governance_documents_v1/iu,
  );
  assert.match(
    forward,
    /function[\s\S]+backend_system\.attest_corporate_governance_signed_artifact_v1/iu,
  );
  assert.match(
    forward,
    /function[\s\S]+backend_system\.complete_corporate_governance_shareholder_loan_v1/iu,
  );
  assert.doesNotMatch(forward, /create trigger[^\n]*document_evidence/iu);
  const removal = documents.match(
    /function documents\.mark_removed_v1[\s\S]+?\$function\$;/iu,
  )?.[0];
  assert.ok(removal);
  assert.ok(removal.indexOf("for update") < removal.indexOf("has_evidence_references_v1"));
  assert.match(
    rollback,
    /drop function if exists[\s\S]+backend_system\.register_corporate_governance_documents_v1[\s\S]+delete from documents\.evidence_references/iu,
  );
  assert.doesNotMatch(rollback, /create or replace function documents\./iu);
});

test("governance decisions keep compatibility source identity without cross-capability foreign keys", async () => {
  const [ownerForward, annualForward] = await Promise.all([
    readFile(
      new URL(`../supabase/migrations/${ownerMigrationName}`, import.meta.url),
      "utf8",
    ),
    readFile(
      new URL(`../supabase/migrations/${annualMigrationName}`, import.meta.url),
      "utf8",
    ),
  ]);

  assert.doesNotMatch(ownerForward, /annual_close_source_id uuid[^,]+references public\.annual_data/iu);
  assert.doesNotMatch(annualForward, /annual_close_source_id uuid[^,]+references public\.annual_data/iu);
  assert.match(annualForward, /source_hash_uses_current_basis boolean not null default true/iu);
  assert.match(annualForward, /decision\.annual_close_source_id, decision\.source_hash, false/iu);
});

test("company access owns the governance identity query migration", async () => {
  const [companyAccessForward, governanceForward] = await Promise.all([
    readFile(
      new URL(
        `../supabase/migrations/${companyIdentityMigrationName}`,
        import.meta.url,
      ),
      "utf8",
    ),
    readFile(
      new URL(`../supabase/migrations/${lifecycleMigrationName}`, import.meta.url),
      "utf8",
    ),
  ]);

  assert.match(
    companyAccessForward,
    /create or replace function public\.company_access_read_company_identity_v1/iu,
  );
  assert.doesNotMatch(
    governanceForward,
    /create or replace function public\.company_access_read_company_identity_v1/iu,
  );
  assert.match(
    companyAccessForward,
    /revoke company_access_executor from %I/iu,
  );
});

test(
  "company identity reader serves only an accepted member through its owned contract",
  { skip: !databaseUrl && "DATABASE_URL is required" },
  async () => {
    const actorId = "95000000-0000-4000-8000-000000000147";
    const outsiderId = "95000000-0000-4000-8000-000000000148";
    const companyId = "95000000-0000-4000-8000-000000000146";
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      await client.query("begin");
      await client.query(String.raw`
        do $authority$ begin
          execute pg_catalog.format(
            'grant corporate_governance_workflow_executor to %I', current_user
          );
        end $authority$;
        insert into auth.users (id, is_sso_user, is_anonymous)
        values
          ('${actorId}', false, false),
          ('${outsiderId}', false, false)
        on conflict (id) do nothing;
        insert into public.companies (
          id, org_number, name, entity_type, created_by
        ) values (
          '${companyId}', '900000146', 'Company Identity Reader AS', 'AS',
          '${actorId}'
        ) on conflict (id) do nothing;
        insert into public.company_memberships (
          company_id, user_id, role, accepted_at
        ) values (
          '${companyId}', '${actorId}', 'owner', pg_catalog.now()
        ) on conflict (company_id, user_id) do nothing;
        select pg_catalog.set_config(
          'talli.verified_actor_id', '${actorId}', true
        );
        select pg_catalog.set_config(
          'talli.verified_actor_claims',
          '{"sub":"${actorId}","aal":"aal2"}', true
        );
        set local role corporate_governance_workflow_executor;
      `);
      const result = await client.query(String.raw`
        select public.company_access_read_company_identity_v1(
          '${companyId}'::uuid, '${actorId}'
        ) as result
      `);
      assert.deepEqual(result.rows[0].result, {
        companyId,
        organizationNumber: "900000146",
        legalName: "Company Identity Reader AS",
      });
      await assert.rejects(
        client.query(String.raw`
          select public.company_access_read_company_identity_v1(
            '${companyId}'::uuid, '${outsiderId}'
          )
        `),
        /company_access_forbidden/iu,
      );
    } finally {
      await client.query("rollback");
      await client.end();
    }
  },
);

test(
  "annual-data compatibility reader serves an accepted owner under the runtime role",
  { skip: !databaseUrl && "DATABASE_URL is required" },
  async () => {
    const actorId = "96000000-0000-4000-8000-000000000147";
    const companyId = "96000000-0000-4000-8000-000000000146";
    const annualDataId = "96000000-0000-4000-8000-000000000145";
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      await client.query("begin");
      await client.query(String.raw`
        do $authority$ begin
          execute pg_catalog.format(
            'grant corporate_governance_workflow_executor to %I', current_user
          );
        end $authority$;
        insert into auth.users (id, is_sso_user, is_anonymous)
        values ('${actorId}', false, false)
        on conflict (id) do nothing;
        insert into public.companies (
          id, org_number, name, entity_type, created_by
        ) values (
          '${companyId}', '900000147', 'Annual Source Reader AS', 'AS',
          '${actorId}'
        ) on conflict (id) do nothing;
        insert into public.company_memberships (
          company_id, user_id, role, accepted_at
        ) values (
          '${companyId}', '${actorId}', 'owner', pg_catalog.now()
        ) on conflict (company_id, user_id) do nothing;
        insert into public.annual_data (
          id, company_id, income_year, answers, confirmations,
          completed_by, updated_by
        ) values (
          '${annualDataId}', '${companyId}', 2024,
          '{"general_meeting_approved":true}'::jsonb, '[]'::jsonb,
          '${actorId}', '${actorId}'
        ) on conflict (id) do nothing;
        select pg_catalog.set_config(
          'talli.verified_actor_id', '${actorId}', true
        );
        select pg_catalog.set_config(
          'talli.verified_actor_claims',
          '{"sub":"${actorId}","aal":"aal2"}', true
        );
        set local role corporate_governance_workflow_executor;
      `);
      const result = await client.query(String.raw`
        select
          pg_catalog.jsonb_array_length(items)::int as item_count,
          items -> 0 ->> 'sourceId' as source_id
        from (
          select backend_system.list_annual_data_legacy_v1(
            '${companyId}'::uuid, 2024, '${actorId}'
          ) as items
        ) source
      `);
      assert.deepEqual(result.rows[0], {
        item_count: 1,
        source_id: annualDataId,
      });
      const authority = await client.query(String.raw`
        select
          pg_catalog.pg_get_userbyid(routine.proowner) as function_owner,
          reader.rolinherit as reader_inherits,
          reader.rolbypassrls as reader_bypasses_rls,
          pg_catalog.has_table_privilege(
            'backend_system_annual_data_reader',
            'public.annual_data', 'select'
          ) as reader_selects_annual_data,
          pg_catalog.has_table_privilege(
            'corporate_governance_workflow_executor',
            'public.annual_data', 'select'
          ) as workflow_selects_annual_data
        from pg_catalog.pg_proc routine
        join pg_catalog.pg_namespace namespace
          on namespace.oid = routine.pronamespace
        join pg_catalog.pg_roles reader
          on reader.rolname = 'backend_system_annual_data_reader'
        where namespace.nspname = 'backend_system'
          and routine.proname = 'list_annual_data_legacy_v1'
      `);
      assert.deepEqual(authority.rows[0], {
        function_owner: "backend_system_annual_data_reader",
        reader_inherits: false,
        reader_bypasses_rls: false,
        reader_selects_annual_data: true,
        workflow_selects_annual_data: false,
      });
    } finally {
      await client.query("rollback");
      await client.end();
    }
  },
);

test(
  "lifecycle reader preserves evidence event identity and distinct timestamps",
  { skip: !databaseUrl && "DATABASE_URL is required" },
  async () => {
    const client = new Client({ connectionString: databaseUrl });
    await client.connect();
    try {
      await client.query("begin");
      await client.query(String.raw`
        insert into auth.users (id, is_sso_user, is_anonymous)
        values ('98000000-0000-4000-8000-000000000141', false, false);
        insert into public.companies (
          id, org_number, name, entity_type, created_by
        ) values (
          '98000000-0000-4000-8000-000000000140', '900000149',
          'Lifecycle Timestamp AS', 'AS',
          '98000000-0000-4000-8000-000000000141'
        );
        insert into public.company_memberships (
          company_id, user_id, role, accepted_at
        ) values (
          '98000000-0000-4000-8000-000000000140',
          '98000000-0000-4000-8000-000000000141', 'owner',
          pg_catalog.now()
        );
        insert into public.annual_data (
          id, company_id, income_year, answers, confirmations,
          completed_by, updated_by
        ) values (
          '98000000-0000-4000-8000-000000000142',
          '98000000-0000-4000-8000-000000000140', 2024,
          '{}'::jsonb, '[]'::jsonb,
          '98000000-0000-4000-8000-000000000141',
          '98000000-0000-4000-8000-000000000141'
        );
        do $authority$ begin
          execute pg_catalog.format(
            'grant corporate_governance_store_owner, ledger_store_owner, '
              || 'banking_store_owner to %I', current_user
          );
        end $authority$;
        select pg_catalog.set_config(
          'talli.verified_actor_id',
          '98000000-0000-4000-8000-000000000141', true
        );
        set local role corporate_governance_store_owner;
        alter table corporate_governance.owner_dividend_accounting_policies
          no force row level security;
        alter table corporate_governance.owner_dividend_decisions
          no force row level security;
        alter table corporate_governance.owner_dividend_finalizations
          no force row level security;
        alter table corporate_governance.owner_dividend_payments
          no force row level security;
        alter table corporate_governance.annual_close_decisions
          no force row level security;
        alter table corporate_governance.annual_close_finalizations
          no force row level security;
        insert into corporate_governance.owner_dividend_accounting_policies (
          policy_version, declaration_debit_account,
          dividend_payable_account, bank_account, reviewer, reviewed_at,
          evidence_reference, enabled, recorded_by, created_at
        ) values (
          'timestamp-evidence-v1', '2050', '2920', '1920', 'test',
          '2025-01-01 00:00:00+00', 'test-evidence', true,
          '98000000-0000-4000-8000-000000000141',
          '2025-01-01 00:00:00+00'
        );
        insert into corporate_governance.owner_dividend_decisions (
          id, document_set_id, company_id, income_year,
          annual_close_source_id, source_hash, canonical_input,
          decision_hash, declared_amount_ore, idempotency_key,
          correlation_id, request_fingerprint, created_by, created_at
        ) values (
          '98000000-0000-4000-8000-000000000143',
          '98000000-0000-4000-8000-000000000144',
          '98000000-0000-4000-8000-000000000140', 2025,
          '98000000-0000-4000-8000-000000000142', repeat('a', 64),
          pg_catalog.jsonb_build_object(
            'decisionId', '98000000-0000-4000-8000-000000000143',
            'documentSetId', '98000000-0000-4000-8000-000000000144',
            'companyId', '98000000-0000-4000-8000-000000000140',
            'incomeYear', 2025, 'sourceHash', repeat('a', 64),
            'decisionHash', repeat('b', 64),
            'dividend', pg_catalog.jsonb_build_object('amountOre', 10000)
          ), repeat('b', 64), 10000, 'timestamp-owner-decision',
          'timestamp-owner-decision', repeat('c', 64),
          '98000000-0000-4000-8000-000000000141',
          '2025-01-01 00:00:00+00'
        );
        insert into corporate_governance.annual_close_decisions (
          id, document_set_id, company_id, income_year,
          annual_close_source_id, source_hash, canonical_input,
          persisted_facts, generated_artifacts, decision_hash,
          annual_result_allocation_ore, idempotency_key, correlation_id,
          request_fingerprint, created_by, created_at
        ) values (
          '98000000-0000-4000-8000-000000000153',
          '98000000-0000-4000-8000-000000000154',
          '98000000-0000-4000-8000-000000000140', 2025,
          '98000000-0000-4000-8000-000000000142', repeat('d', 64),
          pg_catalog.jsonb_build_object(
            'decisionId', '98000000-0000-4000-8000-000000000153',
            'documentSetId', '98000000-0000-4000-8000-000000000154',
            'companyId', '98000000-0000-4000-8000-000000000140',
            'incomeYear', 2025, 'sourceHash', repeat('d', 64),
            'decisionHash', repeat('e', 64), 'decisionKind', 'annual_close',
            'dividend', null, 'annualResultAllocationOre', 0
          ), '{}'::jsonb, '[{},{}]'::jsonb, repeat('e', 64), 0,
          'timestamp-annual-decision', 'timestamp-annual-decision',
          repeat('f', 64), '98000000-0000-4000-8000-000000000141',
          '2025-01-01 00:00:00+00'
        );
        reset role;
        set local role ledger_store_owner;
        alter table ledger.entries no force row level security;
        alter table ledger.entries disable trigger user;
        insert into ledger.entries (
          id, company_id, income_year, entry_kind, memo, lines,
          created_by, source_capability, source_record_id,
          correlation_id, posted_at, created_at
        ) values
          (
            '98000000-0000-4000-8000-000000000148',
            '98000000-0000-4000-8000-000000000140', 2025,
            'OWNER_DIVIDEND_DECLARED', 'declaration',
            '[{"account":"2050","debit":100,"credit":0,"currency":"NOK"},{"account":"2920","debit":0,"credit":100,"currency":"NOK"}]',
            '98000000-0000-4000-8000-000000000141',
            'CORPORATE_GOVERNANCE', 'timestamp-declaration',
            'timestamp-declaration', '2025-05-01 10:00:00+00',
            '2025-05-01 11:00:00+00'
          ),
          (
            '98000000-0000-4000-8000-000000000149',
            '98000000-0000-4000-8000-000000000140', 2025,
            'OWNER_DIVIDEND_PAYMENT', 'payment',
            '[{"account":"2920","debit":40,"credit":0,"currency":"NOK"},{"account":"1920","debit":0,"credit":40,"currency":"NOK"}]',
            '98000000-0000-4000-8000-000000000141',
            'CORPORATE_GOVERNANCE', 'timestamp-payment',
            'timestamp-payment', '2025-05-02 10:00:00+00',
            '2025-05-02 11:00:00+00'
          );
        alter table ledger.entries force row level security;
        reset role;
        set local role banking_store_owner;
        alter table banking.transactions no force row level security;
        alter table banking.transactions disable trigger user;
        insert into banking.transactions (
          id, company_id, income_year, transaction_date, text, amount,
          source_hash, created_by, created_at
        ) values (
          '98000000-0000-4000-8000-000000000150',
          '98000000-0000-4000-8000-000000000140', 2025,
          '2025-05-02', 'payment', -40.00, repeat('1', 64),
          '98000000-0000-4000-8000-000000000141',
          '2025-05-02 11:00:00+00'
        );
        alter table banking.transactions force row level security;
        reset role;
        set local role corporate_governance_store_owner;
        insert into corporate_governance.owner_dividend_finalizations (
          id, event_id, decision_id, document_set_id, company_id,
          income_year, decision_hash, holding_action_id,
          accounting_entry_id, declared_amount_ore,
          signed_artifact_hashes, accounting_policy_version,
          idempotency_key, correlation_id, request_fingerprint,
          created_by, occurred_at, created_at
        ) values (
          '98000000-0000-4000-8000-000000000145',
          '98000000-0000-4000-8000-000000000146',
          '98000000-0000-4000-8000-000000000143',
          '98000000-0000-4000-8000-000000000144',
          '98000000-0000-4000-8000-000000000140', 2025,
          repeat('b', 64), '98000000-0000-4000-8000-000000000151',
          '98000000-0000-4000-8000-000000000148', 10000,
          '{}'::jsonb, 'timestamp-evidence-v1',
          'timestamp-owner-finalization', 'timestamp-owner-finalization',
          repeat('2', 64), '98000000-0000-4000-8000-000000000141',
          '2025-05-01 10:00:00+00', '2025-05-01 11:00:00+00'
        );
        insert into corporate_governance.owner_dividend_payments (
          id, decision_id, document_set_id, company_id, income_year,
          decision_hash, holding_action_id, accounting_entry_id,
          bank_transaction_id, payment_amount_ore, bank_transaction_date,
          bank_signed_amount, bank_source_sha256,
          accounting_policy_version, idempotency_key, correlation_id,
          request_fingerprint, created_by, occurred_at, created_at
        ) values (
          '98000000-0000-4000-8000-000000000147',
          '98000000-0000-4000-8000-000000000143',
          '98000000-0000-4000-8000-000000000144',
          '98000000-0000-4000-8000-000000000140', 2025,
          repeat('b', 64), '98000000-0000-4000-8000-000000000152',
          '98000000-0000-4000-8000-000000000149',
          '98000000-0000-4000-8000-000000000150', 4000, '2025-05-02',
          -40.00, repeat('1', 64), 'timestamp-evidence-v1',
          'timestamp-owner-payment', 'timestamp-owner-payment',
          repeat('3', 64), '98000000-0000-4000-8000-000000000141',
          '2025-05-02 10:00:00+00', '2025-05-02 11:00:00+00'
        );
        insert into corporate_governance.annual_close_finalizations (
          id, event_id, decision_id, document_set_id, company_id,
          income_year, annual_close_source_id, decision_hash,
          signed_artifact_hashes, idempotency_key, correlation_id,
          request_fingerprint, created_by, occurred_at, created_at
        ) values (
          '98000000-0000-4000-8000-000000000155',
          '98000000-0000-4000-8000-000000000156',
          '98000000-0000-4000-8000-000000000153',
          '98000000-0000-4000-8000-000000000154',
          '98000000-0000-4000-8000-000000000140', 2025,
          '98000000-0000-4000-8000-000000000142', repeat('e', 64),
          '{}'::jsonb, 'timestamp-annual-finalization',
          'timestamp-annual-finalization', repeat('4', 64),
          '98000000-0000-4000-8000-000000000141',
          '2025-05-03 10:00:00+00', '2025-05-03 11:00:00+00'
        );
        alter table corporate_governance.owner_dividend_accounting_policies
          force row level security;
        alter table corporate_governance.owner_dividend_decisions
          force row level security;
        alter table corporate_governance.owner_dividend_finalizations
          force row level security;
        alter table corporate_governance.owner_dividend_payments
          force row level security;
        alter table corporate_governance.annual_close_decisions
          force row level security;
        alter table corporate_governance.annual_close_finalizations
          force row level security;
        reset role;
      `);
      const result = await client.query(String.raw`
        with lifecycle as (
          select corporate_governance.read_corporate_lifecycle_v1(
            array['98000000-0000-4000-8000-000000000140'::uuid],
            null, '98000000-0000-4000-8000-000000000141'
          ) as value
        )
        select
          event ->> 'eventId' as event_id,
          event ->> 'occurredAt' as occurred_at,
          event ->> 'createdAt' as created_at
        from lifecycle,
          lateral pg_catalog.jsonb_array_elements(value -> 'events') event
        where event ->> 'eventId' in (
          '98000000-0000-4000-8000-000000000146',
          '98000000-0000-4000-8000-000000000147',
          '98000000-0000-4000-8000-000000000156'
        )
        order by event_id
      `);
      assert.deepEqual(result.rows, [
        {
          event_id: "98000000-0000-4000-8000-000000000146",
          occurred_at: "2025-05-01T10:00:00+00:00",
          created_at: "2025-05-01T11:00:00+00:00",
        },
        {
          event_id: "98000000-0000-4000-8000-000000000147",
          occurred_at: "2025-05-02T10:00:00+00:00",
          created_at: "2025-05-02T11:00:00+00:00",
        },
        {
          event_id: "98000000-0000-4000-8000-000000000156",
          occurred_at: "2025-05-03T10:00:00+00:00",
          created_at: "2025-05-03T11:00:00+00:00",
        },
      ]);
    } finally {
      await client.query("rollback");
      await client.end();
    }
  },
);

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

async function assertFinalizationEvidence(client, canonical) {
  const result = canonical
    ? await client.query(String.raw`
        select
          finalization.id::text as finalization_id,
          finalization.event_id::text as event_id,
          pg_catalog.to_char(
            finalization.occurred_at at time zone 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS"Z"'
          ) as occurred_at,
          pg_catalog.to_char(
            finalization.created_at at time zone 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS"Z"'
          ) as created_at
        from corporate_governance.owner_dividend_finalizations finalization
        where finalization.id =
          '97000000-0000-4000-8000-000000000162'::uuid
      `)
    : await client.query(String.raw`
        select
          finalization.id::text as finalization_id,
          evidence.id::text as event_id,
          pg_catalog.to_char(
            evidence.occurred_at at time zone 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS"Z"'
          ) as occurred_at,
          pg_catalog.to_char(
            evidence.created_at at time zone 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS"Z"'
          ) as created_at
        from public.corporate_decision_finalizations finalization
        join public.corporate_document_events evidence
          on evidence.id = '97000000-0000-4000-8000-000000000163'::uuid
          and evidence.metadata ->> 'finalization_id' = finalization.id::text
        where finalization.id =
          '97000000-0000-4000-8000-000000000162'::uuid
      `);
  assert.deepEqual(result.rows[0], {
    finalization_id: "97000000-0000-4000-8000-000000000162",
    event_id: "97000000-0000-4000-8000-000000000163",
    occurred_at: "2025-01-02T03:05:00Z",
    created_at: "2025-01-02T04:05:00Z",
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
      companyIdentityForward,
      companyIdentityRollback,
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
        new URL(
          `../supabase/migrations/${companyIdentityMigrationName}`,
          import.meta.url,
        ),
        "utf8",
      ),
      readFile(
        new URL(
          `../supabase/rollback/${companyIdentityMigrationName}`,
          import.meta.url,
        ),
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
        insert into public.corporate_accounting_policies (
          policy_version, declaration_debit_account,
          dividend_payable_account, bank_account, reviewer, reviewed_at,
          evidence_reference, enabled, recorded_by, created_at
        ) values (
          'lossless-finalization-v1', '2050', '2920', '1920', 'test',
          '2025-01-01 00:00:00+00', 'migration-rehearsal', true,
          '97000000-0000-4000-8000-000000000147',
          '2025-01-01 00:00:00+00'
        ) on conflict (policy_version) do nothing;
        do $authority$ begin
          execute pg_catalog.format(
            'grant corporate_governance_store_owner, ledger_store_owner '
              || 'to %I', current_user
          );
        end $authority$;
        set role ledger_store_owner;
        alter table ledger.entries no force row level security;
        alter table ledger.entries disable trigger user;
        insert into ledger.entries (
          id, company_id, income_year, entry_kind, memo, lines,
          created_by, source_capability, source_record_id,
          correlation_id, posted_at, created_at
        ) values (
          '97000000-0000-4000-8000-000000000160',
          '97000000-0000-4000-8000-000000000146', 2025,
          'OWNER_DIVIDEND_DECLARED', 'lossless finalization',
          '[{"account":"2050","debit":100,"credit":0,"currency":"NOK"},{"account":"2920","debit":0,"credit":100,"currency":"NOK"}]',
          '97000000-0000-4000-8000-000000000147',
          'CORPORATE_GOVERNANCE', 'lossless-finalization',
          'lossless-finalization', '2025-01-02 03:05:00+00',
          '2025-01-02 04:05:00+00'
        ) on conflict (id) do nothing;
        alter table ledger.entries enable trigger user;
        alter table ledger.entries force row level security;
        reset role;
        insert into public.holding_actions (
          id, company_id, income_year, action_type, action_date,
          payload, ledger_entry_id, risk_level, created_by, created_at
        ) values (
          '97000000-0000-4000-8000-000000000161',
          '97000000-0000-4000-8000-000000000146', 2025,
          'dividend_to_owner', '2025-01-02', '{}'::jsonb,
          '97000000-0000-4000-8000-000000000160', 'ready',
          '97000000-0000-4000-8000-000000000147',
          '2025-01-02 04:05:00+00'
        ) on conflict (id) do nothing;
        insert into public.corporate_decision_finalizations (
          id, company_id, income_year, decision_id, finalization_kind,
          holding_action_id, ledger_entry_id, annual_close_source_id,
          decision_hash, signed_artifact_hashes,
          accounting_policy_version, created_by, created_at
        ) values (
          '97000000-0000-4000-8000-000000000162',
          '97000000-0000-4000-8000-000000000146', 2025,
          '97000000-0000-4000-8000-000000000148',
          'owner_dividend_declared',
          '97000000-0000-4000-8000-000000000161',
          '97000000-0000-4000-8000-000000000160', null,
          repeat('b', 64), '{}'::jsonb, 'lossless-finalization-v1',
          '97000000-0000-4000-8000-000000000147',
          '2025-01-02 04:05:00+00'
        ) on conflict (id) do nothing;
        insert into public.corporate_document_events (
          id, company_id, income_year, decision_id, set_id, event_kind,
          actor_id, occurred_at, decision_hash, metadata,
          idempotency_key, created_at
        ) values (
          '97000000-0000-4000-8000-000000000163',
          '97000000-0000-4000-8000-000000000146', 2025,
          '97000000-0000-4000-8000-000000000148',
          '97000000-0000-4000-8000-000000000149', 'finalized',
          '97000000-0000-4000-8000-000000000147',
          '2025-01-02 03:05:00+00', repeat('b', 64),
          pg_catalog.jsonb_build_object(
            'finalization_id',
            '97000000-0000-4000-8000-000000000162',
            'finalization_kind', 'owner_dividend_declared',
            'signed_artifact_hashes', '{}'::jsonb,
            'accounting_policy_version', 'lossless-finalization-v1'
          ), 'lossless-finalization-event',
          '2025-01-02 04:05:00+00'
        ) on conflict (id) do nothing;
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
        alter table corporate_governance.owner_dividend_accounting_policies
          no force row level security;
        insert into corporate_governance.owner_dividend_accounting_policies (
          policy_version, declaration_debit_account,
          dividend_payable_account, bank_account, reviewer, reviewed_at,
          evidence_reference, enabled, recorded_by, created_at
        ) values (
          'lossless-finalization-v1', '2050', '2920', '1920', 'test',
          '2025-01-01 00:00:00+00', 'migration-rehearsal', true,
          '97000000-0000-4000-8000-000000000147',
          '2025-01-01 00:00:00+00'
        ) on conflict (policy_version) do nothing;
        alter table corporate_governance.owner_dividend_accounting_policies
          force row level security;
        alter table corporate_governance.owner_dividend_finalizations
          no force row level security;
        insert into corporate_governance.owner_dividend_finalizations (
          id, event_id, decision_id, document_set_id, company_id,
          income_year, decision_hash, holding_action_id,
          accounting_entry_id, declared_amount_ore,
          signed_artifact_hashes, accounting_policy_version,
          idempotency_key, correlation_id, request_fingerprint,
          created_by, occurred_at, created_at
        ) values (
          '97000000-0000-4000-8000-000000000162',
          '97000000-0000-4000-8000-000000000163',
          '97000000-0000-4000-8000-000000000148',
          '97000000-0000-4000-8000-000000000149',
          '97000000-0000-4000-8000-000000000146', 2025,
          repeat('b', 64), '97000000-0000-4000-8000-000000000161',
          '97000000-0000-4000-8000-000000000160', 10000,
          '{}'::jsonb, 'lossless-finalization-v1',
          'lossless-finalization', 'lossless-finalization',
          repeat('7', 64), '97000000-0000-4000-8000-000000000147',
          '2025-01-02 03:05:00+00', '2025-01-02 04:05:00+00'
        ) on conflict (id) do nothing;
        alter table corporate_governance.owner_dividend_finalizations
          force row level security;
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
      await assertFinalizationEvidence(client, true);
      for (let rehearsal = 0; rehearsal < 2; rehearsal += 1) {
        await client.query(lifecycleRollback);
        await client.query(annualRollback);
        await client.query(loanRollback);
        await client.query(companyIdentityRollback);
        await assertGovernanceRolesCannotInheritCompanyAccessExecutor(client);
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
        await assertFinalizationEvidence(client, false);
        await client.query(ownerForward);
        await client.query(loanForward);
        await client.query(annualForward);
        await client.query(companyIdentityForward);
        await assertGovernanceRolesCannotInheritCompanyAccessExecutor(client);
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
        await assertFinalizationEvidence(client, true);
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
