import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import test from "node:test";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const dockerHost = process.env.TALLI_DOCKER_HOST;
const investmentsMigration = "20260831124939_investments_capability.sql";
const investmentsWorkflowMigration = "20260831131203_investments_share_purchase_workflow.sql";
const investmentsSaleWorkflowMigration = "20260831162145_investments_share_sale_workflow.sql";
const investmentsAllocationIdentityMigration = "20260831180000_investments_allocation_identity.sql";
const investmentsDividendWorkflowMigration = "20260831182000_investments_received_dividend_workflow.sql";
const investmentsContractMigration = "20260831133000_investments_share_purchase_contract.sql";
const investmentsRollbackMigration = "20260831133000_investments_share_purchase_contract.sql";
const investmentsSaleContractMigration = "20260831170000_investments_share_sale_contract.sql";
const investmentsSaleRollbackMigration = "20260831170000_investments_share_sale_contract.sql";
const investmentsDividendContractMigration = "20260831190000_investments_received_dividend_contract.sql";
const investmentsDividendRollbackMigration = "20260831190000_investments_received_dividend_contract.sql";
const investmentsStageExitMigration = "20260831193000_investments_stage_exit.sql";
const investmentsSupportedPatternsMigration = "20260901100000_investments_supported_patterns.sql";
const investmentsSupportedPatternsAuthorityCleanupMigration = "20260901103000_investments_supported_patterns_authority_cleanup.sql";
const investmentsCompleteManualEvidenceMigration = "20260901110000_investments_complete_manual_evidence.sql";
const investmentsLifecycleMeasurementMigration = "20260901112000_investments_lifecycle_measurement_expand.sql";
const investmentsLifecycleWorkflowMigration = "20260901113000_investments_lifecycle_workflow.sql";
const investmentsShareSaleLifecycleMigration = "20260901114000_investments_share_sale_lifecycle.sql";
const investmentsIncomeLifecycleMigration = "20260901115000_investments_income_lifecycle.sql";
const investmentsLifecycleCorrectionsMigration = "20260901116000_investments_lifecycle_corrections.sql";
const investmentsBankFactClaimMigration = "20260901117000_investments_bank_fact_claim.sql";
const investmentsYearEndMeasurementWorkflowMigration = "20260901118000_investments_year_end_measurement_workflow.sql";
const investmentsLifecyclePublicCutoverMigration = "20260901150538_investments_lifecycle_public_cutover.sql";
const ownerId = "00000000-0000-0000-0000-000000000011";
const outsiderId = "00000000-0000-0000-0000-000000000022";
const companyId = "10000000-0000-0000-0000-000000000001";
const secondCompanyId = "10000000-0000-0000-0000-000000000002";
const actionId = "20000000-0000-0000-0000-000000000002";
const positionId = "30000000-0000-0000-0000-000000000003";
const lotId = "40000000-0000-0000-0000-000000000004";
const overlapActionId = "20000000-0000-0000-0000-000000000011";
const newActionId = "20000000-0000-0000-0000-000000000012";
const rollbackActionId = "20000000-0000-0000-0000-000000000013";
const successorSaleActionId = "20000000-0000-0000-0000-000000000014";
const recutoverActionId = "20000000-0000-0000-0000-000000000015";
const oversaleActionId = "20000000-0000-0000-0000-000000000016";
const failedSaleActionId = "20000000-0000-0000-0000-000000000017";
const rollbackSaleActionId = "20000000-0000-0000-0000-000000000018";
const legacyDividendActionId = "20000000-0000-0000-0000-000000000019";
const successorDividendActionId = "20000000-0000-0000-0000-000000000020";
const failedDividendActionId = "20000000-0000-0000-0000-000000000021";
const rollbackDividendActionId = "20000000-0000-0000-0000-000000000022";
const stageExitActionId = "20000000-0000-0000-0000-000000000023";
const manualEvidenceBankId = "70000000-0000-0000-0000-000000000007";
const manualEvidenceDocumentId = "80000000-0000-0000-0000-000000000008";

const bootstrapSql = String.raw`
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
create schema extensions;
create extension pgcrypto with schema extensions;
grant usage on schema extensions to public;
create schema auth;
create table auth.users (id uuid primary key, email text);
create or replace function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$;
create or replace function auth.role() returns text language sql stable as $$
  select nullif(current_setting('request.jwt.claim.role', true), '');
$$;
create or replace function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb, '{}'::jsonb);
$$;
grant usage on schema auth to authenticated, anon, service_role;
revoke all on function auth.uid(), auth.role(), auth.jwt() from public;
grant execute on function auth.uid(), auth.role(), auth.jwt() to authenticated, anon, service_role;
create schema storage;
create table storage.buckets (
  id text primary key, name text not null, public boolean not null default false,
  file_size_limit bigint, allowed_mime_types text[]
);
create table storage.objects (
  id uuid primary key default gen_random_uuid(),
  bucket_id text not null references storage.buckets(id),
  name text not null, owner uuid, created_at timestamptz not null default now(),
  unique (bucket_id, name)
);
alter table storage.objects enable row level security;
create or replace function storage.foldername(name text) returns text[] language sql immutable as $$
  select string_to_array(name, '/');
$$;
grant usage on schema storage to authenticated, anon, service_role;
grant select, insert on storage.objects to authenticated;
`;

function docker(args, options = {}) {
  const host = dockerHost ? ["--host", dockerHost] : [];
  return spawnSync("docker", [...host, ...args], {
    encoding: "utf8",
    maxBuffer: 30 * 1024 * 1024,
    ...options,
  });
}

function psql(containerName, args = [], input) {
  const result = docker([
    "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
    "-U", "postgres", "-d", "talli_test", ...args,
  ], { input });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  return result.stdout;
}

function scalar(containerName, sql) {
  return psql(containerName, ["-Atq"], sql).trim().split("\n").at(-1);
}

test("investments schema is private, forced-RLS, and restricted-role owned", { timeout: 240_000 }, () => {
  assert.equal(docker(["info", "--format", "{{.ServerVersion}}"]).status, 0,
    "Docker is required for the mandatory investments PostgreSQL rehearsal");
  const containerName = `talli-investments-${process.pid}-${randomUUID().slice(0, 8)}`;

  try {
    const started = docker([
      "run", "--rm", "--detach", "--name", containerName,
      "--env", "POSTGRES_PASSWORD=postgres", "--env", "POSTGRES_DB=talli_test",
      "--volume", `${repositoryRoot}:/repo:ro`, "postgres:17",
    ]);
    assert.equal(started.status, 0, started.stderr);
    let readyChecks = 0;
    for (let attempt = 0; attempt < 80; attempt += 1) {
      if (docker([
        "exec", containerName, "psql", "-U", "postgres", "-d", "talli_test",
        "-Atq", "-c", "select 1",
      ]).status === 0) {
        readyChecks += 1;
        if (readyChecks === 2) break;
      } else {
        readyChecks = 0;
      }
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 250);
    }
    assert.equal(readyChecks, 2, "PostgreSQL container did not become ready");

    psql(containerName, [], bootstrapSql);
    const migrations = readdirSync(new URL("../supabase/migrations", import.meta.url))
      .filter((name) => name.endsWith(".sql"))
      .sort();
    for (const migration of migrations.filter((name) =>
      ![
        investmentsMigration,
        investmentsWorkflowMigration,
        investmentsSaleWorkflowMigration,
        investmentsAllocationIdentityMigration,
        investmentsDividendWorkflowMigration,
        investmentsSupportedPatternsMigration,
        investmentsSupportedPatternsAuthorityCleanupMigration,
        investmentsCompleteManualEvidenceMigration,
        investmentsLifecycleMeasurementMigration,
        investmentsLifecycleWorkflowMigration,
        investmentsShareSaleLifecycleMigration,
        investmentsIncomeLifecycleMigration,
        investmentsLifecycleCorrectionsMigration,
        investmentsBankFactClaimMigration,
        investmentsYearEndMeasurementWorkflowMigration,
        investmentsLifecyclePublicCutoverMigration,
      ].includes(name))) {
      psql(containerName, ["--file", `/repo/supabase/migrations/${migration}`]);
    }
    psql(containerName, [], String.raw`
      insert into auth.users (id, email) values
        ('${ownerId}', 'owner@example.test'),
        ('${outsiderId}', 'outsider@example.test');
      insert into public.companies (
        id, org_number, name, entity_type, address, postal_code, city,
        status_text, source, created_by, identity_confirmed_at, identity_locked_at
      ) values (
        '${companyId}', '314159265', 'Investments AS', 'AS', 'One', '0150',
        'Oslo', 'Active', 'test', '${ownerId}', pg_catalog.now(), pg_catalog.now()
      );
      insert into public.company_memberships (company_id, user_id, role, accepted_at)
      values ('${companyId}', '${ownerId}', 'owner', pg_catalog.now());
      insert into public.customer_agreement_acceptances (
        id, company_id, accepted_by, customer_legal_name, customer_org_number,
        business_terms_version, business_terms_effective_date,
        business_terms_path, business_terms_sha256,
        dpa_version, dpa_effective_date, dpa_path, dpa_sha256,
        authority_statement_version, acceptance_method, accepted_at
      ) values (
        '73000000-0000-0000-0000-000000000001', '${companyId}', '${ownerId}',
        'Investments AS', '314159265', '2026-08-30', date '2026-08-30',
        '/vilkar', 'afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04',
        '2026-08-30', date '2026-08-30', '/databehandleravtale',
        '1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a',
        'authority-v1', 'in_app_clickwrap', pg_catalog.now()
      );
      insert into public.company_eligibility_assessments (
        id, company_id, accounting_year, operation_id, trigger, decision,
        capability_manifest, capability_manifest_version,
        capability_manifest_sha256, public_facts, public_facts_sha256,
        answers, answers_sha256, reason_codes, reason_explanations,
        next_step_code, next_step, consequential_operations_allowed,
        archive_export_available, evaluator_version, assessed_by, assessed_at
      ) values (
        '70000000-0000-0000-0000-000000000001', '${companyId}', 2026,
        '70000000-0000-0000-0000-000000000002', 'initial_admission',
        'supported', '{}'::jsonb, '2026.1',
        '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de',
        '{}'::jsonb, repeat('a', 64), '{"supported":true}'::jsonb,
        repeat('b', 64), '{}'::text[], '{}'::text[], 'CREATE_ACCOUNT_AND_ACCEPT',
        'Test admission.', true, true, '2026.1', '${ownerId}', pg_catalog.now()
      );
      insert into public.company_year_admissions (
        id, company_id, accounting_year, eligibility_assessment_id,
        capability_manifest, capability_manifest_version,
        capability_manifest_sha256, company_year_promise,
        company_year_promise_sha256, reconstruct_from, admitted_by, admitted_at
      ) values (
        '71000000-0000-0000-0000-000000000001', '${companyId}', 2026,
        '70000000-0000-0000-0000-000000000001', '{}'::jsonb, '2026.1',
        '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de',
        '{}'::jsonb, repeat('c', 64), date '2026-01-01', '${ownerId}', pg_catalog.now()
      );
      insert into public.company_year_acceptances (
        id, company_year_admission_id, company_id, accounting_year, accepted_by,
        customer_legal_name, customer_org_number,
        business_terms_version, business_terms_effective_date,
        business_terms_path, business_terms_sha256,
        dpa_version, dpa_effective_date, dpa_path, dpa_sha256,
        privacy_notice_version, privacy_notice_effective_date,
        privacy_notice_path, privacy_notice_sha256,
        capability_manifest_version, capability_manifest_sha256,
        authority_statement_version, acceptance_method, accepted_at
      ) values (
        '72000000-0000-0000-0000-000000000001',
        '71000000-0000-0000-0000-000000000001', '${companyId}', 2026,
        '${ownerId}', 'Investments AS', '314159265',
        '2026-08-30', date '2026-08-30', '/vilkar',
        'afc6fc3610f05056f3de8cc849a33accbf3bdff7d469aef8be57c5ccbe074c04',
        '2026-08-30', date '2026-08-30', '/databehandleravtale',
        '1f5c45a882db79fb248bdff92bd1a245e97b9a7a2f174b943b761f67bda4b94a',
        '2026-08-30', date '2026-08-30', '/personvern',
        '041a65be9f020c037bd65b7097e04afdbeb2c944ef45d7bef3dd380e92f907de',
        '2026.1',
        '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de',
        'authority-v1', 'in_app_clickwrap', pg_catalog.now()
      );
      insert into public.investment_positions (
        id, company_id, investment_key, name, kind, tax_treatment, org_number,
        share_count, cost_basis, movements, lot_history_status, created_by
      ) values (
        '${positionId}', '${companyId}', 'example-as', 'Example AS',
        'norwegian_private_company', 'fritaksmetoden', '123456789',
        10, 125.50,
        '[{"action_id":"${actionId}","movement_type":"purchase","movement_date":"2026-04-15","share_delta":10,"cost_basis_delta":125.50,"amount":125.50,"lot_id":"${lotId}"}]'::jsonb,
        'complete', '${ownerId}'
      );
      select pg_catalog.set_config('talli.investment_action_write', 'on', false);
      insert into public.holding_actions (
        id, company_id, income_year, action_type, action_date, payload,
        risk_level, created_by
      ) values (
        '${actionId}', '${companyId}', 2026, 'share_purchase', '2026-04-15',
        '{"investment_key":"example-as","investment_name":"Example AS","share_count":10,"purchase_amount":125.50,"acquisition_lot_id":"${lotId}"}'::jsonb,
        'ready', '${ownerId}'
      );
      insert into public.investment_lots (
        id, company_id, position_id, acquisition_action_id, acquisition_date,
        original_share_count, remaining_share_count, original_cost_basis,
        remaining_cost_basis, created_by
      ) values (
        '${lotId}', '${companyId}', '${positionId}', '${actionId}', '2026-04-15',
        10, 10, 125.50, 125.50, '${ownerId}'
      );
    `);
    psql(containerName, ["--file", `/repo/supabase/migrations/${investmentsMigration}`]);
    psql(containerName, ["--file", `/repo/supabase/migrations/${investmentsWorkflowMigration}`]);
    psql(containerName, ["--file", `/repo/supabase/migrations/${investmentsSaleWorkflowMigration}`]);
    psql(containerName, ["--file", `/repo/supabase/migrations/${investmentsAllocationIdentityMigration}`]);

    const predecessorDividendRequest = JSON.stringify({
      companyId, incomeYear: 2026, actionId: legacyDividendActionId,
      idempotencyKey: "dividend-predecessor-0001", correlationId: "dividend-predecessor",
      payingCompanyName: "Example AS", declaredDate: "2026-05-01",
      paidDate: "2026-05-15", grossAmount: "100.00",
      linkedInvestmentId: positionId, taxTreatment: "fritaksmetoden",
      bankTransactionId: null, documentId: null, documentStatus: "not_required",
    });
    JSON.parse(scalar(containerName, String.raw`
      set role ledger_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      with prepared as materialized (
        select backend_system.prepare_investment_dividend_v1(
          '${predecessorDividendRequest}'::jsonb, '${ownerId}'
        ) as value
      ), posted as materialized (
        select * from ledger.post_entry(
          'dividend-predecessor-0001', '${companyId}', 2026,
          'DIVIDEND_RECEIVED', 'Dividend received from Example AS',
          '[{"account":"1920","description":"Dividend received in bank","debit":"100.00","credit":"0.00","currency":"NOK"},{"account":"8070","description":"Dividend from Example AS","debit":"0.00","credit":"100.00","currency":"NOK"}]'::jsonb,
          '[]'::jsonb, false, 'INVESTMENTS', '${legacyDividendActionId}',
          'dividend-predecessor', '${ownerId}'
        )
      )
      select backend_system.complete_investment_dividend_v1(
        '${predecessorDividendRequest}'::jsonb, posted.ledger_entry_id,
        prepared.value, '${ownerId}'
      )::text from prepared cross join posted;
    `));

    psql(containerName, ["--file", `/repo/supabase/migrations/${investmentsDividendWorkflowMigration}`]);

    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regclass('investments.positions') is not null)::text || ':' ||
        (pg_catalog.to_regclass('investments.acquisition_lots') is not null)::text || ':' ||
        (pg_catalog.to_regclass('investments.share_purchases') is not null)::text || ':' ||
        (pg_catalog.to_regclass('investments.received_dividends') is not null)::text || ':' ||
        (pg_catalog.to_regprocedure('investments.prepare_share_purchase_v1(jsonb,text)') is not null)::text || ':' ||
        (select rolbypassrls::text from pg_catalog.pg_roles where rolname = 'investments_executor') || ':' ||
        (select relrowsecurity::text || ':' || relforcerowsecurity::text
         from pg_catalog.pg_class where oid = 'investments.positions'::regclass) || ':' ||
        pg_catalog.has_schema_privilege('authenticated', 'investments', 'usage')::text || ':' ||
        pg_catalog.has_table_privilege('service_role', 'investments.positions', 'select')::text;
    `), "true:true:true:true:true:false:true:true:false:false");
    assert.equal(scalar(containerName, String.raw`
      select legacy_imported::text || ':' || gross_amount::text || ':' ||
        taxable_add_back::text || ':' || position_id::text
      from investments.received_dividends
      where action_id = '${legacyDividendActionId}';
    `), `true:100.00:3.00:${positionId}`);
    assert.equal(scalar(containerName, String.raw`
      set session authorization talli_ledger_backend;
      set role investments_workflow_executor;
      select current_user || ':' || session_user;
    `), "investments_workflow_executor:talli_ledger_backend");
    assert.equal(scalar(containerName, String.raw`
      select position.id::text || ':' || position.investment_key || ':' ||
        position.share_count::text || ':' || position.cost_basis::text || ':' ||
        lot.id::text || ':' || lot.acquisition_action_id::text || ':' ||
        lot.remaining_share_count::text || ':' || lot.remaining_cost_basis::text
      from investments.positions position
      join investments.acquisition_lots lot on lot.position_id = position.id;
    `), `${positionId}:example-as:10:125.50:${lotId}:${actionId}:10:125.50`);
    assert.equal(scalar(containerName, String.raw`
      set role investments_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      select count(*) from investments.positions;
    `), "1");
    assert.equal(scalar(containerName, String.raw`
      set role investments_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${outsiderId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${outsiderId}"}', false);
      select count(*) from investments.positions;
    `), "0");

    const overlapRequest = JSON.stringify({
      companyId, incomeYear: 2026, actionId: overlapActionId,
      idempotencyKey: "purchase-overlap-0001", correlationId: "overlap-request",
      investmentKey: "overlap-as", investmentName: "Overlap AS",
      investmentKind: "norwegian_private_company", taxTreatment: "fritaksmetoden",
      acquisitionDate: "2026-05-10", shareCount: 3, purchaseAmount: "300.00",
      orgNumber: null, bankTransactionId: null, documentId: null,
      documentStatus: "not_required",
    });
    JSON.parse(scalar(containerName, String.raw`
      set role ledger_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      with prepared as materialized (
        select backend_system.prepare_investment_purchase_fifo_v1(
          '${overlapRequest}'::jsonb, '${ownerId}'
        ) as value
      ), posted as materialized (
        select * from ledger.post_entry(
          'purchase-overlap-0001', '${companyId}', 2026, 'SHARE_PURCHASE',
          'Share purchase: Overlap AS',
          '[{"account":"1800","description":"Investment in Overlap AS","debit":"300.00","credit":"0.00","currency":"NOK"},{"account":"1920","description":"Paid from bank","debit":"0.00","credit":"300.00","currency":"NOK"}]'::jsonb,
          '[]'::jsonb, false, 'INVESTMENTS', '${overlapActionId}',
          'overlap-request', '${ownerId}'
        )
      )
      select backend_system.complete_investment_purchase_fifo_v1(
        '${overlapRequest}'::jsonb, posted.ledger_entry_id,
        prepared.value, '${ownerId}'
      )::text from prepared cross join posted;
    `));
    assert.equal(scalar(containerName, String.raw`
      select purchase.legacy_imported::text || ':' ||
        position.share_count::text || ':' || position.cost_basis::text || ':' ||
        lot.remaining_share_count::text || ':' || lot.remaining_cost_basis::text
      from investments.share_purchases purchase
      join investments.positions position on position.id = purchase.position_id
      join investments.acquisition_lots lot on lot.id = purchase.acquisition_lot_id
      where purchase.action_id = '${overlapActionId}';
    `), "true:3:300.00:3:300.00");
    const overlapReplay = JSON.parse(scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      select investments.get_share_purchase_replay_v1(
        '${overlapRequest}'::jsonb, '${ownerId}'
      )::text;
    `));
    assert.equal(overlapReplay.replayed, true);

    const purchaseRequest = JSON.stringify({
      companyId, incomeYear: 2026, actionId: newActionId,
      idempotencyKey: "purchase-command-0001", correlationId: "request-0001",
      investmentKey: "second-as", investmentName: "Second AS",
      investmentKind: "norwegian_private_company", taxTreatment: "fritaksmetoden",
      acquisitionDate: "2026-05-20", shareCount: 25, purchaseAmount: "500.00",
      orgNumber: "987654321", bankTransactionId: null, documentId: null,
      documentStatus: "not_required",
    });
    const completed = scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      with prepared as materialized (
        select investments.prepare_share_purchase_v1(
          '${purchaseRequest}'::jsonb, '${ownerId}'
        ) as value
      ), posted as materialized (
        select * from ledger.post_entry(
          'purchase-command-0001', '${companyId}', 2026, 'SHARE_PURCHASE',
          'Share purchase: Second AS',
          '[{"account":"1800","description":"Investment in Second AS","debit":"500.00","credit":"0.00","currency":"NOK"},{"account":"1920","description":"Paid from bank","debit":"0.00","credit":"500.00","currency":"NOK"}]'::jsonb,
          '[]'::jsonb, false, 'INVESTMENTS', '${newActionId}',
          'request-0001', '${ownerId}'
        )
      )
      select investments.complete_share_purchase_v1(
        '${purchaseRequest}'::jsonb, posted.ledger_entry_id,
        prepared.value, '${ownerId}'
      )::text from prepared cross join posted;
    `);
    const completedResult = JSON.parse(completed);
    assert.match(completedResult.accountingEntryId, /^[0-9a-f-]{36}$/u);
    const replayed = JSON.parse(scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      select investments.get_share_purchase_replay_v1(
        '${purchaseRequest}'::jsonb, '${ownerId}'
      )::text;
    `));
    assert.equal(replayed.replayed, true);
    assert.equal(replayed.positionCreated, completedResult.positionCreated);
    assert.equal(scalar(containerName, String.raw`
      set role investments_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      select purchase.share_count::text || ':' || purchase.purchase_amount::text || ':' ||
        position.share_count::text || ':' || position.cost_basis::text || ':' ||
        lot.original_share_count::text || ':' || lot.original_cost_basis::text
      from investments.share_purchases purchase
      join investments.positions position on position.id = purchase.position_id
      join investments.acquisition_lots lot on lot.id = purchase.acquisition_lot_id
      where purchase.action_id = '${newActionId}';
    `), "25:500.00:25:500.00:25:500.00");
    assert.equal(scalar(containerName, String.raw`
      select entry.entry_kind || ':' || entry.source_capability || ':' ||
        entry.source_record_id || ':' ||
        (entry.lines -> 0 ->> 'account') || ':' ||
        (entry.lines -> 1 ->> 'account') || ':' ||
        (entry.lines -> 0 ->> 'debit') || ':' ||
        (entry.lines -> 1 ->> 'credit')
      from ledger.entries entry
      join investments.share_purchases purchase
        on purchase.accounting_entry_id = entry.id
      where purchase.action_id = '${newActionId}';
    `), `SHARE_PURCHASE:INVESTMENTS:${newActionId}:1800:1920:500.00:500.00`);
    assert.equal(scalar(containerName, String.raw`
      select
        (select count(*) from public.holding_actions
          where id = '${newActionId}' and action_type = 'share_purchase')::text || ':' ||
        (select count(*) from public.investment_lots lot
          join investments.share_purchases purchase
            on purchase.acquisition_lot_id = lot.id
          where purchase.action_id = '${newActionId}')::text || ':' ||
        (select count(*) from public.investment_positions position
          join investments.share_purchases purchase
            on purchase.position_id = position.id
          where purchase.action_id = '${newActionId}'
            and position.share_count = 25 and position.cost_basis = 500.00)::text || ':' ||
        (select count(*) from public.audit_events
          where company_id = '${companyId}'
            and action = 'share_purchase_recorded'
            and message like '%Second AS%')::text;
    `), "1:1:1:1");

    const saleRequest = JSON.stringify({
      companyId, incomeYear: 2026, actionId: successorSaleActionId,
      idempotencyKey: "sale-command-0001", correlationId: "sale-request-0001",
      positionId: completedResult.positionId, saleDate: "2026-06-01",
      soldShareCount: 5, proceeds: "120.00", bankTransactionId: null,
      documentId: null, documentStatus: "not_required",
    });
    const completedSale = JSON.parse(scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      with prepared as materialized (
        select investments.prepare_share_sale_v1(
          '${saleRequest}'::jsonb, '${ownerId}'
        ) as value
      ), posted as materialized (
        select * from ledger.post_entry(
          'sale-command-0001', '${companyId}', 2026, 'SHARE_SALE',
          'Share sale: Second AS',
          '[{"account":"1920","description":"Sale proceeds received in bank","debit":"120.00","credit":"0.00","currency":"NOK"},{"account":"1800","description":"Cost basis reduction: Second AS","debit":"0.00","credit":"100.00","currency":"NOK"},{"account":"8070","description":"Share sale gain: Second AS","debit":"0.00","credit":"20.00","currency":"NOK"}]'::jsonb,
          '[]'::jsonb, false, 'INVESTMENTS', '${successorSaleActionId}',
          'sale-request-0001', '${ownerId}'
        )
      )
      select investments.complete_share_sale_v1(
        '${saleRequest}'::jsonb, posted.ledger_entry_id, '${ownerId}'
      )::text from prepared cross join posted;
    `));
    assert.equal(completedSale.actionId, successorSaleActionId);
    assert.equal(completedSale.positionId, completedResult.positionId);
    const replayedSale = JSON.parse(scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      select investments.get_share_sale_replay_v1(
        '${saleRequest}'::jsonb, '${ownerId}'
      )::text;
    `));
    assert.equal(replayedSale.replayed, true);
    assert.equal(replayedSale.accountingEntryId, completedSale.accountingEntryId);
    assert.equal(scalar(containerName, String.raw`
      select sale.sold_share_count::text || ':' ||
        sale.fifo_cost_basis_reduction::text || ':' || sale.gain_or_loss::text || ':' ||
        sale.remaining_share_count::text || ':' || sale.remaining_cost_basis::text || ':' ||
        allocation.allocated_share_count::text || ':' ||
        allocation.allocated_cost_basis::text || ':' ||
        position.share_count::text || ':' || position.cost_basis::text || ':' ||
        lot.remaining_share_count::text || ':' || lot.remaining_cost_basis::text
      from investments.share_sales sale
      join investments.share_sale_allocations allocation
        on allocation.sale_action_id = sale.action_id
      join investments.positions position on position.id = sale.position_id
      join investments.acquisition_lots lot
        on lot.id = allocation.acquisition_lot_id
      where sale.action_id = '${successorSaleActionId}';
    `), "5:100.00:20.00:20:400.00:5:100.00:20:400.00:20:400.00");
    assert.equal(scalar(containerName, String.raw`
      select
        (select count(*) from public.holding_actions
          where id = '${successorSaleActionId}' and action_type = 'share_sale')::text || ':' ||
        (select count(*) from public.investment_lot_allocations
          where sale_action_id = '${successorSaleActionId}')::text || ':' ||
        (select count(*) from ledger.entries
          where id = '${completedSale.accountingEntryId}'
            and entry_kind = 'SHARE_SALE'
            and source_capability = 'INVESTMENTS')::text;
    `), "1:1:1");
    assert.equal(scalar(containerName, String.raw`
      select position.share_count::text || ':' || position.cost_basis::text || ':' ||
        lot.remaining_share_count::text || ':' || lot.remaining_cost_basis::text
      from investments.positions position
      join investments.acquisition_lots lot on lot.position_id = position.id
      where position.id = '${completedResult.positionId}';
    `), "20:400.00:20:400.00");

    const oversaleRequest = JSON.stringify({
      ...JSON.parse(saleRequest), actionId: oversaleActionId,
      idempotencyKey: "sale-oversell-0001", correlationId: "sale-oversell",
      soldShareCount: 21,
    });
    const oversale = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test", "-Atq",
    ], { input: String.raw`
      begin;
      set local role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', true);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', true);
      select investments.prepare_share_sale_v1(
        '${oversaleRequest}'::jsonb, '${ownerId}'
      );
      commit;
    ` });
    assert.notEqual(oversale.status, 0);
    assert.match(oversale.stderr, /investments_invalid_input/u);
    assert.equal(scalar(containerName, String.raw`
      select
        (select count(*) from investments.share_sales
          where action_id = '${oversaleActionId}')::text || ':' ||
        (select count(*) from ledger.entries
          where source_record_id = '${oversaleActionId}')::text || ':' ||
        (select share_count::text || ':' || cost_basis::text
          from investments.positions where id = '${completedResult.positionId}');
    `), "0:0:20:400.00");

    const failedSaleRequest = JSON.stringify({
      ...JSON.parse(saleRequest), actionId: failedSaleActionId,
      idempotencyKey: "sale-failed-completion-0001",
      correlationId: "sale-failed-completion", soldShareCount: 1,
      proceeds: "25.00",
    });
    const failedSale = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test", "-Atq",
    ], { input: String.raw`
      begin;
      set local role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', true);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', true);
      with prepared as materialized (
        select investments.prepare_share_sale_v1(
          '${failedSaleRequest}'::jsonb, '${ownerId}'
        ) as value
      ), posted as materialized (
        select * from ledger.post_entry(
          'sale-failed-completion-0001', '${companyId}', 2026, 'SHARE_SALE',
          'Share sale: Second AS',
          '[{"account":"1920","description":"Sale proceeds received in bank","debit":"25.00","credit":"0.00","currency":"NOK"},{"account":"1800","description":"Cost basis reduction: Second AS","debit":"0.00","credit":"20.00","currency":"NOK"},{"account":"8070","description":"Share sale gain: Second AS","debit":"0.00","credit":"5.00","currency":"NOK"}]'::jsonb,
          '[]'::jsonb, false, 'INVESTMENTS', '${failedSaleActionId}',
          'sale-failed-completion', '${ownerId}'
        )
      )
      select investments.complete_share_sale_v1(
        '${failedSaleRequest}'::jsonb,
        '90000000-0000-0000-0000-000000000009', '${ownerId}'
      ) from prepared cross join posted;
      commit;
    ` });
    assert.notEqual(failedSale.status, 0);
    assert.match(failedSale.stderr, /investments_dependency_unavailable/u);
    assert.equal(scalar(containerName, String.raw`
      select
        (select count(*) from investments.share_sales
          where action_id = '${failedSaleActionId}')::text || ':' ||
        (select count(*) from ledger.entries
          where source_record_id = '${failedSaleActionId}')::text || ':' ||
        (select count(*) from backend_system.ledger_command_receipts
          where idempotency_key = 'sale-failed-completion-0001')::text || ':' ||
        (select count(*) from public.holding_actions
          where id = '${failedSaleActionId}')::text || ':' ||
        (select share_count::text || ':' || cost_basis::text
          from investments.positions where id = '${completedResult.positionId}');
    `), "0:0:0:0:20:400.00");

    const dividendRequest = JSON.stringify({
      companyId, incomeYear: 2026, actionId: successorDividendActionId,
      idempotencyKey: "dividend-command-0001", correlationId: "dividend-command",
      positionId: completedResult.positionId, payingCompanyName: "Second AS",
      declaredDate: "2026-06-10", paidDate: "2026-06-20",
      grossAmount: "125.50", taxTreatment: "fritaksmetoden",
      bankTransactionId: null, documentId: null, documentStatus: "not_required",
      taxableAddBack: "3.77",
    });
    const completedDividend = JSON.parse(scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      with prepared as materialized (
        select investments.prepare_received_dividend_v1(
          '${dividendRequest}'::jsonb, '${ownerId}'
        ) as value
      ), posted as materialized (
        select * from ledger.post_entry(
          'dividend-command-0001', '${companyId}', 2026,
          'DIVIDEND_RECEIVED', 'Dividend received from Second AS',
          '[{"account":"1920","description":"Dividend received in bank","debit":"125.50","credit":"0.00","currency":"NOK"},{"account":"8070","description":"Dividend from Second AS","debit":"0.00","credit":"125.50","currency":"NOK"}]'::jsonb,
          '[]'::jsonb, false, 'INVESTMENTS', '${successorDividendActionId}',
          'dividend-command', '${ownerId}'
        )
      )
      select investments.complete_received_dividend_v1(
        '${dividendRequest}'::jsonb, posted.ledger_entry_id, '${ownerId}'
      )::text from prepared cross join posted;
    `));
    assert.equal(completedDividend.taxableAddBack, 3.77);
    const replayedDividend = JSON.parse(scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      select investments.get_received_dividend_replay_v1(
        '${dividendRequest}'::jsonb, '${ownerId}'
      )::text;
    `));
    assert.equal(replayedDividend.replayed, true);
    assert.equal(scalar(containerName, String.raw`
      select dividend.gross_amount::text || ':' || dividend.taxable_add_back::text || ':' ||
        entry.entry_kind || ':' || entry.source_capability || ':' ||
        (select count(*) from public.holding_actions action
          where action.id = dividend.action_id
            and (action.payload ->> 'taxable_add_back')::numeric = 3.77)::text
      from investments.received_dividends dividend
      join ledger.entries entry on entry.id = dividend.accounting_entry_id
      where dividend.action_id = '${successorDividendActionId}';
    `), "125.50:3.77:DIVIDEND_RECEIVED:INVESTMENTS:1");

    const failedDividendRequest = JSON.stringify({
      ...JSON.parse(dividendRequest), actionId: failedDividendActionId,
      idempotencyKey: "dividend-failed-0001", correlationId: "dividend-failed",
      grossAmount: "50.00", taxableAddBack: "1.50",
    });
    const failedDividend = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test", "-Atq",
    ], { input: String.raw`
      begin;
      set local role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', true);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', true);
      with prepared as materialized (
        select investments.prepare_received_dividend_v1(
          '${failedDividendRequest}'::jsonb, '${ownerId}'
        ) as value
      ), posted as materialized (
        select * from ledger.post_entry(
          'dividend-failed-0001', '${companyId}', 2026,
          'DIVIDEND_RECEIVED', 'Dividend received from Second AS',
          '[{"account":"1920","description":"Dividend received in bank","debit":"50.00","credit":"0.00","currency":"NOK"},{"account":"8070","description":"Dividend from Second AS","debit":"0.00","credit":"50.00","currency":"NOK"}]'::jsonb,
          '[]'::jsonb, false, 'INVESTMENTS', '${failedDividendActionId}',
          'dividend-failed', '${ownerId}'
        )
      )
      select investments.complete_received_dividend_v1(
        '${failedDividendRequest}'::jsonb,
        '90000000-0000-0000-0000-000000000009', '${ownerId}'
      ) from prepared cross join posted;
      commit;
    ` });
    assert.notEqual(failedDividend.status, 0);
    assert.match(failedDividend.stderr, /investments_dependency_unavailable/u);
    assert.equal(scalar(containerName, String.raw`
      select
        (select count(*) from investments.received_dividends
          where action_id = '${failedDividendActionId}')::text || ':' ||
        (select count(*) from ledger.entries
          where source_record_id = '${failedDividendActionId}')::text || ':' ||
        (select count(*) from public.holding_actions
          where id = '${failedDividendActionId}')::text;
    `), "0:0:0");

    const rollbackRequest = JSON.stringify({
      ...JSON.parse(purchaseRequest), actionId: rollbackActionId,
      idempotencyKey: "purchase-command-0002", investmentKey: "rollback-as",
      investmentName: "Rollback AS", orgNumber: null,
    });
    const failedAfterLedger = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test", "-Atq",
    ], { input: String.raw`
      begin;
      set local role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', true);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', true);
      with prepared as materialized (
        select investments.prepare_share_purchase_v1(
          '${rollbackRequest}'::jsonb, '${ownerId}'
        ) as value
      ), posted as materialized (
        select * from ledger.post_entry(
          'purchase-command-0002', '${companyId}', 2026, 'SHARE_PURCHASE',
          'Share purchase: Rollback AS',
          '[{"account":"1800","description":"Investment in Rollback AS","debit":"500.00","credit":"0.00","currency":"NOK"},{"account":"1920","description":"Paid from bank","debit":"0.00","credit":"500.00","currency":"NOK"}]'::jsonb,
          '[]'::jsonb, false, 'INVESTMENTS', '${rollbackActionId}',
          'request-rollback', '${ownerId}'
        )
      )
      select investments.complete_share_purchase_v1(
        '${rollbackRequest}'::jsonb, posted.ledger_entry_id,
        prepared.value || '{"lotId":"90000000-0000-0000-0000-000000000009"}'::jsonb,
        '${ownerId}'
      ) from prepared cross join posted;
      commit;
    ` });
    assert.notEqual(failedAfterLedger.status, 0);
    assert.match(failedAfterLedger.stderr, /investments_dependency_unavailable/u);
    assert.equal(scalar(containerName, String.raw`
      select count(*) from investments.share_purchases
      where action_id = '${rollbackActionId}';
    `), "0");
    assert.equal(scalar(containerName, String.raw`
      select count(*) from investments.positions
      where company_id = '${companyId}' and investment_key = 'rollback-as';
    `), "0");
    assert.equal(scalar(containerName, String.raw`
      select
        (select count(*) from ledger.entries
          where source_capability = 'INVESTMENTS'
            and source_record_id = '${rollbackActionId}')::text || ':' ||
        (select count(*) from backend_system.ledger_command_receipts
          where idempotency_key = 'purchase-command-0002')::text || ':' ||
        (select count(*) from public.holding_actions
          where id = '${rollbackActionId}')::text || ':' ||
        (select count(*) from public.audit_events
          where message like '%Rollback AS%')::text;
    `), "0:0:0:0");

    const forbidden = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test", "-Atq",
    ], { input: String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${outsiderId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${outsiderId}"}', false);
      select investments.prepare_share_purchase_v1(
        '${rollbackRequest}'::jsonb, '${outsiderId}'
      );
    ` });
    assert.notEqual(forbidden.status, 0);
    assert.match(forbidden.stderr, /investments_forbidden/u);
    assert.equal(scalar(containerName, String.raw`
      select count(*) from investments.share_purchases
      where action_id = '${rollbackActionId}';
    `), "0");

    psql(containerName, [
      "--file", `/repo/supabase/contract-migrations/${investmentsContractMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regprocedure(
          'backend_system.prepare_investment_purchase_fifo_v1(jsonb,text)'
        ) is null)::text || ':' ||
        (pg_catalog.to_regprocedure(
          'backend_system.complete_investment_purchase_fifo_v1(jsonb,uuid,jsonb,text)'
        ) is null)::text || ':' ||
        (pg_catalog.to_regprocedure(
          'public.record_share_purchase_fifo(uuid,uuid,integer,text,text,text,text,date,bigint,numeric,text,uuid,uuid,text)'
        ) is null)::text;
    `), "true:true:true");
    assert.equal(scalar(containerName, String.raw`
      select pg_catalog.has_function_privilege(
        'investments_workflow_executor',
        'investments.prepare_share_purchase_v1(jsonb,text)', 'EXECUTE'
      )::text || ':' || pg_catalog.has_function_privilege(
        'ledger_workflow_executor',
        'investments.prepare_share_purchase_v1(jsonb,text)', 'EXECUTE'
      )::text;
    `), "true:false");

    psql(containerName, [
      "--file", `/repo/supabase/contract-migrations/${investmentsSaleContractMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regprocedure(
          'backend_system.prepare_investment_sale_fifo_v1(jsonb,text)'
        ) is null)::text || ':' ||
        (pg_catalog.to_regprocedure(
          'backend_system.complete_investment_sale_fifo_v1(jsonb,uuid,jsonb,text)'
        ) is null)::text || ':' ||
        (pg_catalog.to_regprocedure(
          'public.record_share_sale_fifo(uuid,uuid,integer,uuid,date,bigint,numeric,uuid,uuid,text)'
        ) is null)::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_share_sale_v1(jsonb,text)', 'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'ledger_workflow_executor',
          'investments.prepare_share_sale_v1(jsonb,text)', 'EXECUTE'
        )::text;
    `), "true:true:true:true:false");

    psql(containerName, [
      "--file", `/repo/supabase/contract-migrations/${investmentsDividendContractMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regprocedure(
          'backend_system.prepare_investment_dividend_v1(jsonb,text)'
        ) is null)::text || ':' ||
        (pg_catalog.to_regprocedure(
          'backend_system.complete_investment_dividend_v1(jsonb,uuid,jsonb,text)'
        ) is null)::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_received_dividend_v1(jsonb,text)', 'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'ledger_workflow_executor',
          'investments.prepare_received_dividend_v1(jsonb,text)', 'EXECUTE'
        )::text;
    `), "true:true:true:false");

    for (let application = 0; application < 2; application += 1) {
      psql(containerName, [
        "--file", `/repo/supabase/rollback/${investmentsDividendRollbackMigration}`,
      ]);
    }
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regprocedure(
          'backend_system.prepare_investment_dividend_v1(jsonb,text)'
        ) is not null)::text || ':' ||
        pg_catalog.has_function_privilege(
          'ledger_workflow_executor',
          'backend_system.prepare_investment_dividend_v1(jsonb,text)', 'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_received_dividend_v1(jsonb,text)', 'EXECUTE'
        )::text || ':' ||
        (select count(*) from pg_catalog.pg_trigger
          where tgrelid = 'public.holding_actions'::regclass
            and tgname = 'received_dividends_sync_to_investments'
            and not tgisinternal)::text;
    `), "true:true:false:1");

    const rollbackDividendRequest = JSON.stringify({
      ...JSON.parse(predecessorDividendRequest), actionId: rollbackDividendActionId,
      idempotencyKey: "dividend-rollback-0001", correlationId: "dividend-rollback",
      linkedInvestmentId: completedResult.positionId, payingCompanyName: "Second AS",
      grossAmount: "40.00",
    });
    JSON.parse(scalar(containerName, String.raw`
      set role ledger_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      with prepared as materialized (
        select backend_system.prepare_investment_dividend_v1(
          '${rollbackDividendRequest}'::jsonb, '${ownerId}'
        ) as value
      ), posted as materialized (
        select * from ledger.post_entry(
          'dividend-rollback-0001', '${companyId}', 2026,
          'DIVIDEND_RECEIVED', 'Dividend received from Second AS',
          '[{"account":"1920","description":"Dividend received in bank","debit":"40.00","credit":"0.00","currency":"NOK"},{"account":"8070","description":"Dividend from Second AS","debit":"0.00","credit":"40.00","currency":"NOK"}]'::jsonb,
          '[]'::jsonb, false, 'INVESTMENTS', '${rollbackDividendActionId}',
          'dividend-rollback', '${ownerId}'
        )
      )
      select backend_system.complete_investment_dividend_v1(
        '${rollbackDividendRequest}'::jsonb, posted.ledger_entry_id,
        prepared.value, '${ownerId}'
      )::text from prepared cross join posted;
    `));
    assert.equal(scalar(containerName, String.raw`
      select legacy_imported::text || ':' || gross_amount::text || ':' ||
        taxable_add_back::text || ':' || (completed_at is not null)::text
      from investments.received_dividends
      where action_id = '${rollbackDividendActionId}';
    `), "true:40.00:1.20:true");

    psql(containerName, [
      "--file", `/repo/supabase/contract-migrations/${investmentsDividendContractMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regprocedure(
          'backend_system.prepare_investment_dividend_v1(jsonb,text)'
        ) is null)::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_received_dividend_v1(jsonb,text)', 'EXECUTE'
        )::text;
    `), "true:true");

    for (let application = 0; application < 2; application += 1) {
      psql(containerName, [
        "--file", `/repo/supabase/rollback/${investmentsSaleRollbackMigration}`,
      ]);
    }
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regprocedure(
          'backend_system.prepare_investment_sale_fifo_v1(jsonb,text)'
        ) is not null)::text || ':' ||
        pg_catalog.has_function_privilege(
          'ledger_workflow_executor',
          'backend_system.prepare_investment_sale_fifo_v1(jsonb,text)',
          'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_share_sale_v1(jsonb,text)', 'EXECUTE'
        )::text || ':' ||
        (select count(*) from pg_catalog.pg_trigger
          where tgrelid = 'public.holding_actions'::regclass
            and tgname = 'share_sales_sync_to_investments'
            and not tgisinternal)::text;
    `), "true:true:false:1");

    const rollbackSaleRequest = JSON.stringify({
      ...JSON.parse(saleRequest), actionId: rollbackSaleActionId,
      idempotencyKey: "sale-rollback-restored-0001",
      correlationId: "sale-rollback-restored", soldShareCount: 1,
      proceeds: "25.00",
    });
    JSON.parse(scalar(containerName, String.raw`
      set role ledger_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      with prepared as materialized (
        select backend_system.prepare_investment_sale_fifo_v1(
          '${rollbackSaleRequest}'::jsonb, '${ownerId}'
        ) as value
      ), posted as materialized (
        select * from ledger.post_entry(
          'sale-rollback-restored-0001', '${companyId}', 2026, 'SHARE_SALE',
          'Share sale: Second AS',
          '[{"account":"1920","description":"Sale proceeds received in bank","debit":"25.00","credit":"0.00","currency":"NOK"},{"account":"1800","description":"Cost basis reduction: Second AS","debit":"0.00","credit":"20.00","currency":"NOK"},{"account":"8070","description":"Share sale gain: Second AS","debit":"0.00","credit":"5.00","currency":"NOK"}]'::jsonb,
          '[]'::jsonb, false, 'INVESTMENTS', '${rollbackSaleActionId}',
          'sale-rollback-restored', '${ownerId}'
        )
      )
      select backend_system.complete_investment_sale_fifo_v1(
        '${rollbackSaleRequest}'::jsonb, posted.ledger_entry_id,
        prepared.value, '${ownerId}'
      )::text from prepared cross join posted;
    `));
    assert.equal(scalar(containerName, String.raw`
      select sale.legacy_imported::text || ':' ||
        (sale.completed_at is not null)::text || ':' ||
        position.share_count::text || ':' || position.cost_basis::text
      from investments.share_sales sale
      join investments.positions position on position.id = sale.position_id
      where sale.action_id = '${rollbackSaleActionId}';
    `), "true:true:19:380.00");

    psql(containerName, [
      "--file", `/repo/supabase/contract-migrations/${investmentsSaleContractMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regprocedure(
          'backend_system.prepare_investment_sale_fifo_v1(jsonb,text)'
        ) is null)::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_share_sale_v1(jsonb,text)', 'EXECUTE'
        )::text;
    `), "true:true");

    for (let application = 0; application < 2; application += 1) {
      psql(containerName, [
        "--file", `/repo/supabase/rollback/${investmentsRollbackMigration}`,
      ]);
    }
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regprocedure(
          'backend_system.prepare_investment_purchase_fifo_v1(jsonb,text)'
        ) is not null)::text || ':' ||
        pg_catalog.has_function_privilege(
          'ledger_workflow_executor',
          'backend_system.prepare_investment_purchase_fifo_v1(jsonb,text)',
          'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_share_purchase_v1(jsonb,text)', 'EXECUTE'
        )::text;
    `), "true:true:false");

    const rollbackRestoredRequest = JSON.stringify({
      ...JSON.parse(purchaseRequest), actionId: recutoverActionId,
      idempotencyKey: "purchase-rollback-restored-0001",
      correlationId: "request-rollback-restored",
      investmentKey: "rollback-restored-as",
      investmentName: "Rollback Restored AS", orgNumber: null,
    });
    JSON.parse(scalar(containerName, String.raw`
      set role ledger_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      with prepared as materialized (
        select backend_system.prepare_investment_purchase_fifo_v1(
          '${rollbackRestoredRequest}'::jsonb, '${ownerId}'
        ) as value
      ), posted as materialized (
        select * from ledger.post_entry(
          'purchase-rollback-restored-0001', '${companyId}', 2026,
          'SHARE_PURCHASE', 'Share purchase: Rollback Restored AS',
          '[{"account":"1800","description":"Investment in Rollback Restored AS","debit":"500.00","credit":"0.00","currency":"NOK"},{"account":"1920","description":"Paid from bank","debit":"0.00","credit":"500.00","currency":"NOK"}]'::jsonb,
          '[]'::jsonb, false, 'INVESTMENTS', '${recutoverActionId}',
          'request-rollback-restored', '${ownerId}'
        )
      )
      select backend_system.complete_investment_purchase_fifo_v1(
        '${rollbackRestoredRequest}'::jsonb, posted.ledger_entry_id,
        prepared.value, '${ownerId}'
      )::text from prepared cross join posted;
    `));
    assert.equal(scalar(containerName, String.raw`
      select legacy_imported::text || ':' || (completed_at is not null)::text
      from investments.share_purchases
      where action_id = '${recutoverActionId}';
    `), "true:true");

    psql(containerName, [
      "--file", `/repo/supabase/contract-migrations/${investmentsContractMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regprocedure(
          'backend_system.prepare_investment_purchase_fifo_v1(jsonb,text)'
        ) is null)::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_share_purchase_v1(jsonb,text)', 'EXECUTE'
        )::text;
    `), "true:true");

    psql(containerName, [
      "--file", `/repo/supabase/contract-migrations/${investmentsStageExitMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regclass('public.investment_positions') is null)::text || ':' ||
        (pg_catalog.to_regclass('public.investment_lots') is null)::text || ':' ||
        (pg_catalog.to_regclass('public.investment_lot_allocations') is null)::text || ':' ||
        (select count(*) from public.holding_actions
          where action_type in ('share_purchase', 'share_sale', 'dividend_received'))::text || ':' ||
        (select count(*) from pg_catalog.pg_proc procedure
          join pg_catalog.pg_namespace namespace on namespace.oid = procedure.pronamespace
          where namespace.nspname = 'backend_system'
            and procedure.proname ~ '(investment_(purchase|sale|dividend)|legacy_(investment|share_sale|received_dividend)|rollback_14)')::text || ':' ||
        (select count(*) from pg_catalog.pg_policies
          where policyname in (
            'investments successor mirrors actions',
            'investments successor appends audit',
            'investments_positions_workflow_insert',
            'investments_positions_workflow_update',
            'investments_lots_workflow_insert'
          ))::text;
    `), "true:true:true:0:0:0");

    const archiveGenerationBeforeStageExitWrite = Number(scalar(
      containerName,
      String.raw`
        insert into public.company_archive_source_generations(company_id, income_year)
        values ('${companyId}', 2026)
        on conflict (company_id, income_year) do nothing;
        select generation from public.company_archive_source_generations
        where company_id = '${companyId}' and income_year = 2026;
      `,
    ));

    const stageExitRequest = JSON.stringify({
      ...JSON.parse(purchaseRequest), actionId: stageExitActionId,
      idempotencyKey: "purchase-stage-exit-0001",
      correlationId: "purchase-stage-exit",
      shareCount: 2, purchaseAmount: "40.00",
    });
    const stageExitResult = JSON.parse(scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      with prepared as materialized (
        select investments.prepare_share_purchase_v1(
          '${stageExitRequest}'::jsonb, '${ownerId}'
        ) as value
      ), posted as materialized (
        select * from ledger.post_entry(
          'purchase-stage-exit-0001', '${companyId}', 2026,
          'SHARE_PURCHASE', 'Share purchase: Second AS',
          '[{"account":"1800","description":"Investment in Second AS","debit":"40.00","credit":"0.00","currency":"NOK"},{"account":"1920","description":"Paid from bank","debit":"0.00","credit":"40.00","currency":"NOK"}]'::jsonb,
          '[]'::jsonb, false, 'INVESTMENTS', '${stageExitActionId}',
          'purchase-stage-exit', '${ownerId}'
        )
      )
      select investments.complete_share_purchase_v1(
        '${stageExitRequest}'::jsonb, posted.ledger_entry_id,
        prepared.value, '${ownerId}'
      )::text from prepared cross join posted;
    `));
    assert.equal(stageExitResult.actionId, stageExitActionId);
    const archiveGenerationAfterStageExitWrite = Number(scalar(
      containerName,
      String.raw`
        select generation from public.company_archive_source_generations
        where company_id = '${companyId}' and income_year = 2026;
      `,
    ));
    assert.ok(
      archiveGenerationAfterStageExitWrite > archiveGenerationBeforeStageExitWrite,
      "canonical investment writes must invalidate an earlier archive generation",
    );
    assert.equal(scalar(containerName, String.raw`
      select
        (select count(*) from investments.share_purchases
          where action_id = '${stageExitActionId}'
            and accounting_entry_id is not null)::text || ':' ||
        (select count(*) from public.holding_actions
          where id = '${stageExitActionId}')::text || ':' ||
        (select count(*) from public.audit_events
          where company_id = '${companyId}'
            and action = 'share_purchase_recorded'
            and message like '%Second AS%')::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_share_purchase_v1(jsonb,text)', 'EXECUTE'
        )::text;
    `), "1:0:2:true");

    psql(containerName, [
      "--file", `/repo/supabase/rollback/${investmentsStageExitMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regclass('public.investment_positions') is not null)::text || ':' ||
        (select count(*) from public.investment_positions)::text || ':' ||
        (select count(*) from public.investment_lots)::text || ':' ||
        (select count(*) from public.investment_lot_allocations)::text || ':' ||
        (select count(*) from public.holding_actions
          where id = '${stageExitActionId}' and action_type = 'share_purchase')::text;
    `), "true:4:5:2:1");

    psql(containerName, [
      "--file", `/repo/supabase/contract-migrations/${investmentsStageExitMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regclass('public.investment_positions') is null)::text || ':' ||
        (pg_catalog.to_regclass('public.investment_lots') is null)::text || ':' ||
        (pg_catalog.to_regclass('public.investment_lot_allocations') is null)::text || ':' ||
        (select count(*) from public.holding_actions
          where action_type in ('share_purchase', 'share_sale', 'dividend_received'))::text || ':' ||
        (select count(*) from pg_catalog.pg_policies
          where policyname in (
            'investments successor mirrors actions',
            'investments successor appends audit',
            'investments_positions_workflow_insert',
            'investments_positions_workflow_update',
            'investments_lots_workflow_insert'
          ))::text;
    `), "true:true:true:0:0");

    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsSupportedPatternsMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsSupportedPatternsAuthorityCleanupMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsCompleteManualEvidenceMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsLifecycleMeasurementMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsLifecycleWorkflowMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsShareSaleLifecycleMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsIncomeLifecycleMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsLifecycleCorrectionsMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsBankFactClaimMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsYearEndMeasurementWorkflowMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/rollback/${investmentsYearEndMeasurementWorkflowMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsYearEndMeasurementWorkflowMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regclass('investments.economic_events') is not null)::text || ':' ||
        (pg_catalog.to_regclass('investments.event_sources') is not null)::text || ':' ||
        (pg_catalog.to_regclass('investments.cash_settlements') is not null)::text || ':' ||
        (pg_catalog.to_regclass('investments.year_end_measurements') is not null)::text || ':' ||
        (select count(*) from pg_catalog.pg_class relation
          join pg_catalog.pg_namespace namespace on namespace.oid = relation.relnamespace
          where namespace.nspname = 'investments'
            and relation.relname in (
              'company_year_policies', 'economic_events', 'event_sources',
              'cash_settlements', 'position_classifications',
              'year_end_measurements', 'measurement_sources'
            )
            and relation.relrowsecurity and relation.relforcerowsecurity)::text || ':' ||
        pg_catalog.has_table_privilege(
          'authenticated', 'investments.cash_settlements', 'INSERT'
        )::text || ':' ||
        (select numeric_scale from information_schema.columns
          where table_schema = 'investments' and table_name = 'positions'
            and column_name = 'share_count')::text;
    `), "true:true:true:true:7:false:12");

    const expectLifecycleForeignKeyFailure = (sql, label) => {
      const result = docker([
        "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
        "-U", "postgres", "-d", "talli_test",
      ], { input: sql });
      assert.notEqual(result.status, 0, `${label} must fail closed`);
      assert.match(
        `${result.stdout}\n${result.stderr}`,
        /foreign key constraint/iu,
        label,
      );
    };

    const lifecycleEventId = "91000000-0000-0000-0000-000000000001";
    const lifecycleSettlementId = "91000000-0000-0000-0000-000000000002";
    const lifecycleDocumentOne = "91000000-0000-0000-0000-000000000003";
    const lifecycleDocumentTwo = "91000000-0000-0000-0000-000000000004";
    const lifecycleBankFact = "91000000-0000-0000-0000-000000000005";
    const lifecycleRollbackBankFact = "91000000-0000-0000-0000-000000000006";
    const lifecycleCalculationId = "e".repeat(64);
    const lifecycleEvidenceDigest = "d".repeat(64);
    const lifecycleSettlementEvidenceDigest = "f".repeat(64);
    const lifecycleDocumentFacts = [
      {
        capability: "DOCUMENTS", recordId: lifecycleDocumentOne,
        revision: 1, factSha256: "a".repeat(64),
      },
      {
        capability: "DOCUMENTS", recordId: lifecycleDocumentTwo,
        revision: 2, factSha256: "b".repeat(64),
      },
    ];
    const lifecyclePurchaseRequest = JSON.stringify({
      companyId, incomeYear: 2026, eventId: lifecycleEventId,
      idempotencyKey: "lifecycle-purchase-0001",
      correlationId: "lifecycle-purchase",
      investmentKey: "lifecycle-private-as",
      investmentName: "Lifecycle Private AS",
      investmentKind: "norwegian_private_company",
      accountingClassification: "other_long_term",
      acquisitionDate: "2026-12-29", shareCount: "10.125000000000",
      purchaseAmount: "120.00", transactionCosts: "5.50",
      orgNumber: "123456789", fundEquityRatioBasisPoints: null,
      fundTaxStatementReference: null, evidenceMode: "linked_sources",
      evidenceReference: "signed purchase agreement and approval",
      ownerAttested: false, documentFacts: lifecycleDocumentFacts,
      bankFact: null, acquisitionCost: "125.50",
      evidenceDigest: lifecycleEvidenceDigest,
      calculationId: lifecycleCalculationId,
    });
    const lifecycleRecognitionSources = JSON.stringify([
      {
        role: "PRIMARY", capability: "INVESTMENTS",
        recordId: lifecycleEventId, revision: 1,
        factSha256: lifecycleCalculationId,
      },
      ...lifecycleDocumentFacts.map((fact) => ({
        role: "CORROBORATING", ...fact,
      })),
    ]);
    const lifecycleSettlementRequest = JSON.stringify({
      companyId, incomeYear: 2026, settlementId: lifecycleSettlementId,
      eventId: lifecycleEventId, idempotencyKey: "lifecycle-settlement-0001",
      correlationId: "lifecycle-settlement", settlementDate: "2026-12-31",
      amount: "125.50", evidenceMode: "linked_sources",
      evidenceReference: "bank transaction revision 1", ownerAttested: false,
      documentFacts: [], bankFact: {
        capability: "BANKING", recordId: lifecycleBankFact,
        revision: 1, factSha256: "c".repeat(64),
      }, evidenceDigest: lifecycleSettlementEvidenceDigest,
    });

    psql(containerName, [], String.raw`
      begin;
      set local role banking_store_owner;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', true);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', true
      );
      insert into banking.transactions (
        id, company_id, income_year, transaction_date, text, amount,
        source_hash, created_by
      ) values (
        '${lifecycleBankFact}', '${companyId}', 2026, date '2026-12-31',
        'Lifecycle investment purchase', -125.50, repeat('c', 64), '${ownerId}'
      ), (
        '${lifecycleRollbackBankFact}', '${companyId}', 2026,
        date '2026-12-31', 'Lifecycle rollback purchase', -125.50,
        repeat('9', 64), '${ownerId}'
      );
      commit;
    `);

    assert.equal(scalar(containerName, String.raw`
      begin;
      set local role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', true);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', true
      );
      create temporary table lifecycle_purchase_prepared as
      select investments.prepare_share_purchase_recognition_v2(
        '${lifecyclePurchaseRequest}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_recognition_entry as
      select * from ledger.post_investment_lifecycle_entry_v2(
        'lifecycle-purchase-0001', '${companyId}', 2026,
        'SHARE_PURCHASE', 'Investment recognized: Lifecycle Private AS',
        '[{"account":"1350","description":"Investment in Lifecycle Private AS","debit":"125.50","credit":"0.00","currency":"NOK"},{"account":"2990","description":"Investment settlement payable","debit":"0.00","credit":"125.50","currency":"NOK"}]'::jsonb,
        'INVESTMENTS', '${lifecycleEventId}', 'lifecycle-purchase',
        '${ownerId}', date '2026-12-29',
        'ledger-supported-patterns-2026.1', '${lifecycleRecognitionSources}'::jsonb
      );
      create temporary table lifecycle_recognized as
      select investments.complete_share_purchase_recognition_v2(
        '${lifecyclePurchaseRequest}'::jsonb,
        (select ledger_entry_id from lifecycle_recognition_entry),
        (select value from lifecycle_purchase_prepared), '${ownerId}'
      ) as value;
      create temporary table lifecycle_settlement_prepared as
      select investments.prepare_cash_settlement_v2(
        '${lifecycleSettlementRequest}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_settlement_entry as
      select * from ledger.post_investment_lifecycle_entry_v2(
        'lifecycle-settlement-0001', '${companyId}', 2026,
        'SHARE_PURCHASE', 'Investment purchase payable settled',
        '[{"account":"2990","description":"Investment settlement payable cleared","debit":"125.50","credit":"0.00","currency":"NOK"},{"account":"1920","description":"Investment paid from bank","debit":"0.00","credit":"125.50","currency":"NOK"}]'::jsonb,
        'INVESTMENTS', '${lifecycleSettlementId}', 'lifecycle-settlement',
        '${ownerId}', date '2026-12-31',
        'ledger-supported-patterns-2026.1',
        pg_catalog.jsonb_build_array(
          pg_catalog.jsonb_build_object(
            'role', 'PRIMARY', 'capability', 'INVESTMENTS',
            'recordId', '${lifecycleSettlementId}', 'revision', 1,
            'factSha256',
              (select value ->> 'eventFactSha256'
               from lifecycle_settlement_prepared)
          ),
          pg_catalog.jsonb_build_object(
            'role', 'CORROBORATING', 'capability', 'BANKING',
            'recordId', '${lifecycleBankFact}', 'revision', 1,
            'factSha256', repeat('c', 64)
          )
        )
      );
      select banking.claim_transaction_for_external_action_v1(
        pg_catalog.jsonb_build_object(
          'companyId', '${companyId}',
          'incomeYear', 2026,
          'transactionId', '${lifecycleBankFact}',
          'transactionDate', '2026-12-31',
          'signedAmount', '-125.50',
          'sourceHash', repeat('c', 64),
          'actionReference', 'investment-settlement:${lifecycleSettlementId}'
        ),
        (select ledger_entry_id from lifecycle_settlement_entry),
        '${ownerId}'
      );
      create temporary table lifecycle_settled as
      select investments.complete_cash_settlement_v2(
        '${lifecycleSettlementRequest}'::jsonb,
        (select ledger_entry_id from lifecycle_settlement_entry),
        (select value from lifecycle_settlement_prepared), '${ownerId}'
      ) as value;
      commit;
      select
        (select value ->> 'settlementBalanceKind'
          from lifecycle_recognized) || ':' ||
        (select value ->> 'replayed' from lifecycle_recognized) || ':' ||
        (select value ->> 'replayed' from lifecycle_settled) || ':' ||
        (select share_count::text from investments.positions
          where investment_key = 'lifecycle-private-as') || ':' ||
        (select count(*)::text from investments.event_sources
          where event_id = '${lifecycleEventId}') || ':' ||
        (select income_year::text from investments.cash_settlements
          where settlement_id = '${lifecycleSettlementId}') || ':' ||
        (select matched_action_reference from banking.transactions
          where id = '${lifecycleBankFact}');
    `), `purchase_payable:false:false:10.125000000000:2:2026:investment-settlement:${lifecycleSettlementId}`);

    const reusedLifecycleBankFact = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test",
    ], { input: String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', false
      );
      select banking.claim_transaction_for_external_action_v1(
        pg_catalog.jsonb_build_object(
          'companyId', '${companyId}', 'incomeYear', 2026,
          'transactionId', '${lifecycleBankFact}',
          'transactionDate', '2026-12-31', 'signedAmount', '-125.50',
          'sourceHash', repeat('c', 64),
          'actionReference', 'investment-settlement:${lifecycleSettlementId}'
        ),
        '${actionId}',
        '${ownerId}'
      );
    ` });
    assert.notEqual(reusedLifecycleBankFact.status, 0);
    assert.match(
      `${reusedLifecycleBankFact.stdout}\n${reusedLifecycleBankFact.stderr}`,
      /banking_transaction_already_reconciled/u,
    );

    const lifecycleSettlementEntryId = scalar(containerName, String.raw`
      select matched_accounting_entry_id::text
      from banking.transactions
      where id = '${lifecycleBankFact}';
    `);
    const failedAfterLifecycleBankClaim = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test",
    ], { input: String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', false
      );
      begin;
      select banking.claim_transaction_for_external_action_v1(
        pg_catalog.jsonb_build_object(
          'companyId', '${companyId}', 'incomeYear', 2026,
          'transactionId', '${lifecycleRollbackBankFact}',
          'transactionDate', '2026-12-31', 'signedAmount', '-125.50',
          'sourceHash', repeat('9', 64),
          'actionReference',
            'investment-settlement:91000000-0000-0000-0000-000000000099'
        ),
        '${lifecycleSettlementEntryId}', '${ownerId}'
      );
      select investments.complete_cash_settlement_v2(
        '${lifecycleSettlementRequest}'::jsonb,
        '${lifecycleSettlementEntryId}', '{}'::jsonb, '${ownerId}'
      );
      commit;
    ` });
    assert.notEqual(failedAfterLifecycleBankClaim.status, 0);
    assert.equal(scalar(containerName, String.raw`
      select (
        matched_accounting_entry_id is null
        and matched_action_reference is null
      )::text
      from banking.transactions
      where id = '${lifecycleRollbackBankFact}';
    `), "true");

    assert.equal(scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', false
      );
      select
        (investments.get_share_purchase_recognition_replay_v2(
          pg_catalog.jsonb_set(
            '${lifecyclePurchaseRequest}'::jsonb,
            '{correlationId}', '"lifecycle-purchase-retry"'
          ), '${ownerId}'
        ) ->> 'replayed') || ':' ||
        (investments.get_cash_settlement_replay_v2(
          pg_catalog.jsonb_set(
            '${lifecycleSettlementRequest}'::jsonb,
            '{correlationId}', '"lifecycle-settlement-retry"'
          ), '${ownerId}'
        ) ->> 'replayed');
    `), "true:true");

    assert.equal(scalar(containerName, String.raw`
      with lifecycle_entries as (
        select entry.id from ledger.entries entry
        where entry.source_capability = 'INVESTMENTS'
          and entry.source_record_id in (
            '${lifecycleEventId}', '${lifecycleSettlementId}'
          )
      ), totals as (
        select line ->> 'account' as account,
          pg_catalog.sum(
            (line ->> 'debit')::numeric - (line ->> 'credit')::numeric
          ) as net
        from ledger.entries entry
        join lifecycle_entries selected on selected.id = entry.id
        cross join lateral pg_catalog.jsonb_array_elements(entry.lines) line
        group by line ->> 'account'
      )
      select pg_catalog.string_agg(
        account || ':' || net::text, ',' order by account
      ) from totals;
    `), "1350:125.50,1920:-125.50,2990:0.00");

    const lifecycleSettlementCorrectionId =
      "92500000-0000-0000-0000-000000000001";
    const lifecycleReplacementSettlementId =
      "92500000-0000-0000-0000-000000000002";
    const lifecycleCorrectionDocumentId =
      "92500000-0000-0000-0000-000000000003";
    const lifecycleReplacementBankFact =
      "92500000-0000-0000-0000-000000000004";
    const lifecycleReplacementSettlementRequest = {
      companyId, incomeYear: 2026,
      settlementId: lifecycleReplacementSettlementId,
      eventId: lifecycleEventId,
      idempotencyKey: "lifecycle-replacement-settlement-0001",
      correlationId: "lifecycle-replacement-settlement",
      settlementDate: "2026-12-30", amount: "125.50",
      evidenceMode: "linked_sources",
      evidenceReference: "corrected immutable bank transaction",
      ownerAttested: false, documentFacts: [], bankFact: {
        capability: "BANKING", recordId: lifecycleReplacementBankFact,
        revision: 1, factSha256: "1".repeat(64),
      }, evidenceDigest: "2".repeat(64),
    };
    const lifecycleSettlementCorrectionRequest = JSON.stringify({
      companyId, incomeYear: 2026,
      correctionId: lifecycleSettlementCorrectionId,
      idempotencyKey: "lifecycle-settlement-correction-0001",
      correlationId: "lifecycle-settlement-correction",
      targetKind: "cash_settlement", originalRecordId: lifecycleSettlementId,
      replacementRecordId: lifecycleReplacementSettlementId,
      originalActivityKind: "share_purchase",
      replacementActivityKind: "share_purchase",
      correctionDate: "2026-12-31", reason: "Correct bank settlement date",
      evidenceMode: "linked_sources",
      evidenceReference: "signed settlement correction",
      ownerAttested: false, documentFacts: [{
        capability: "DOCUMENTS", recordId: lifecycleCorrectionDocumentId,
        revision: 1, factSha256: "0".repeat(64),
      }], bankFact: null, evidenceDigest: "3".repeat(64),
      replacement: lifecycleReplacementSettlementRequest,
    });

    assert.equal(scalar(containerName, String.raw`
      set role investments_store_owner;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', false
      );
      select (company_id = '${companyId}')::text || ':' ||
        (income_year = 2026)::text || ':' ||
        ((request.value ->> 'eventId') = event_id::text)::text || ':' ||
        ((request.value ->> 'amount')::numeric = amount)::text || ':' ||
        exists (
          select 1 from investments.cash_settlements newer
          where newer.supersedes_settlement_id = original.settlement_id
        )::text
      from investments.cash_settlements original
      cross join lateral (
        select '${lifecycleSettlementCorrectionRequest}'::jsonb -> 'replacement'
      ) request(value)
      where settlement_id = '${lifecycleSettlementId}';
    `), "true:true:true:true:false");

    assert.equal(scalar(containerName, String.raw`
      begin;
      set local role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', true);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', true
      );
      create temporary table lifecycle_settlement_correction_prepared as
      select investments.prepare_cash_settlement_correction_v2(
        '${lifecycleSettlementCorrectionRequest}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_replacement_settlement_entry as
      select * from ledger.post_investment_lifecycle_entry_v2(
        'lifecycle-replacement-settlement-0001', '${companyId}', 2026,
        'SHARE_PURCHASE', 'Investment purchase payable settled',
        '[{"account":"2990","description":"Investment settlement payable cleared","debit":"125.50","credit":"0.00","currency":"NOK"},{"account":"1920","description":"Investment paid from bank","debit":"0.00","credit":"125.50","currency":"NOK"}]'::jsonb,
        'INVESTMENTS', '${lifecycleReplacementSettlementId}',
        'lifecycle-replacement-settlement', '${ownerId}', date '2026-12-30',
        'ledger-supported-patterns-2026.1',
        pg_catalog.jsonb_build_array(
          pg_catalog.jsonb_build_object(
            'role', 'PRIMARY', 'capability', 'INVESTMENTS',
            'recordId', '${lifecycleReplacementSettlementId}', 'revision', 1,
            'factSha256', (select value ->> 'eventFactSha256'
              from lifecycle_settlement_correction_prepared)
          ),
          pg_catalog.jsonb_build_object(
            'role', 'CORROBORATING', 'capability', 'BANKING',
            'recordId', '${lifecycleReplacementBankFact}', 'revision', 1,
            'factSha256', repeat('1', 64)
          )
        )
      );
      create temporary table lifecycle_settlement_reversal as
      select ledger.link_investment_correction_v1(
        '${companyId}', 2026,
        (select (value ->> 'originalAccountingEntryId')::uuid
          from lifecycle_settlement_correction_prepared),
        (select ledger_entry_id from lifecycle_replacement_settlement_entry),
        '${lifecycleSettlementId}', '${lifecycleReplacementSettlementId}',
        'Correct bank settlement date', 'lifecycle-settlement-correction',
        date '2026-12-31', '${ownerId}'
      ) as reversal_entry_id;
      create temporary table lifecycle_settlement_corrected as
      select investments.complete_lifecycle_correction_v2(
        '${lifecycleSettlementCorrectionRequest}'::jsonb,
        (select (value ->> 'originalAccountingEntryId')::uuid
          from lifecycle_settlement_correction_prepared),
        (select ledger_entry_id from lifecycle_replacement_settlement_entry),
        (select reversal_entry_id from lifecycle_settlement_reversal),
        '${ownerId}'
      ) as value;
      commit;
      select
        (select value ->> 'targetKind' from lifecycle_settlement_corrected) || ':' ||
        (select supersedes_settlement_id::text
          from investments.cash_settlements
          where settlement_id = '${lifecycleReplacementSettlementId}') || ':' ||
        (select count(*)::text from investments.cash_settlements
          where event_id = '${lifecycleEventId}') || ':' ||
        (select count(*)::text from investments.lifecycle_correction_sources
          where correction_id = '${lifecycleSettlementCorrectionId}');
    `), `cash_settlement:${lifecycleSettlementId}:2:1`);

    assert.equal(scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', false
      );
      select investments.get_lifecycle_correction_replay_v2(
        pg_catalog.jsonb_set(
          '${lifecycleSettlementCorrectionRequest}'::jsonb,
          '{correlationId}', '"lifecycle-settlement-correction-retry"'
        ), '${ownerId}'
      ) ->> 'replayed';
    `), "true");

    const changedSettlementCorrection = JSON.stringify({
      ...JSON.parse(lifecycleSettlementCorrectionRequest),
      correctionId: "92500000-0000-0000-0000-000000000005",
      idempotencyKey: "lifecycle-settlement-correction-0002",
      originalRecordId: lifecycleReplacementSettlementId,
      replacementRecordId: "92500000-0000-0000-0000-000000000006",
      replacement: {
        ...lifecycleReplacementSettlementRequest,
        settlementId: "92500000-0000-0000-0000-000000000006",
        idempotencyKey: "lifecycle-replacement-settlement-0002",
        amount: "124.50",
      },
    });
    const refusedChangedSettlement = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test",
    ], { input: String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', false
      );
      select investments.prepare_cash_settlement_correction_v2(
        '${changedSettlementCorrection}'::jsonb, '${ownerId}'
      );
    ` });
    assert.notEqual(refusedChangedSettlement.status, 0);
    assert.match(
      `${refusedChangedSettlement.stdout}\n${refusedChangedSettlement.stderr}`,
      /investments_dependency_unavailable/u,
    );

    const settledEventCorrection = JSON.stringify({
      companyId, incomeYear: 2026,
      correctionId: "92500000-0000-0000-0000-000000000007",
      idempotencyKey: "lifecycle-event-correction-0001",
      correlationId: "lifecycle-event-correction",
      targetKind: "economic_event", originalRecordId: lifecycleEventId,
      replacementRecordId: "92500000-0000-0000-0000-000000000008",
      originalActivityKind: "share_purchase",
      replacementActivityKind: "share_purchase",
      correctionDate: "2026-12-31", reason: "Change settled acquisition amount",
      evidenceMode: "linked_sources", evidenceReference: "signed correction",
      ownerAttested: false, documentFacts: [{
        capability: "DOCUMENTS", recordId: lifecycleCorrectionDocumentId,
        revision: 2, factSha256: "4".repeat(64),
      }], bankFact: null, evidenceDigest: "5".repeat(64),
    });
    const refusedSettledEvent = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test",
    ], { input: String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', false
      );
      select investments.prepare_economic_event_correction_v2(
        '${settledEventCorrection}'::jsonb, '${ownerId}'
      );
    ` });
    assert.notEqual(refusedSettledEvent.status, 0);
    assert.match(
      `${refusedSettledEvent.stdout}\n${refusedSettledEvent.stderr}`,
      /investments_dependency_unavailable/u,
    );

    const refusedLifecycleCorrectionsRollback = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test", "--file",
      `/repo/supabase/rollback/${investmentsLifecycleCorrectionsMigration}`,
    ]);
    assert.notEqual(refusedLifecycleCorrectionsRollback.status, 0);
    assert.match(
      `${refusedLifecycleCorrectionsRollback.stdout}\n${refusedLifecycleCorrectionsRollback.stderr}`,
      /investments_lifecycle_corrections_rollback_unsafe/u,
    );

    const lifecyclePositionId = scalar(containerName, String.raw`
      select position_id from investments.economic_events
      where event_id = '${lifecycleEventId}';
    `);
    const lifecycleLotId = scalar(containerName, String.raw`
      select id from investments.acquisition_lots
      where acquisition_action_id = '${lifecycleEventId}';
    `);
    const lifecycleSaleEventId = "92000000-0000-0000-0000-000000000001";
    const lifecycleSaleSettlementId = "92000000-0000-0000-0000-000000000002";
    const lifecycleSaleDocumentId = "92000000-0000-0000-0000-000000000003";
    const lifecycleSaleBankFact = "92000000-0000-0000-0000-000000000004";
    const lifecycleSaleCalculationId = "3".repeat(64);
    const lifecycleSaleEvidenceDigest = "4".repeat(64);
    const lifecycleSaleSettlementEvidenceDigest = "5".repeat(64);
    const lifecycleSaleDocumentFacts = [{
      capability: "DOCUMENTS", recordId: lifecycleSaleDocumentId,
      revision: 3, factSha256: "1".repeat(64),
    }];
    const lifecycleSaleRequest = JSON.stringify({
      companyId, incomeYear: 2026, eventId: lifecycleSaleEventId,
      positionId: lifecyclePositionId,
      idempotencyKey: "lifecycle-sale-recognition-0001",
      correlationId: "lifecycle-sale-recognition",
      saleDate: "2026-12-30", soldShareCount: "4.125000000000",
      proceeds: "80.00", transactionCosts: "5.00", netProceeds: "75.00",
      saleYearFundEquityRatioBasisPoints: null,
      fundTaxStatementReference: null, evidenceMode: "linked_sources",
      evidenceReference: "signed sale agreement", ownerAttested: false,
      documentFacts: lifecycleSaleDocumentFacts, bankFact: null,
      evidenceDigest: lifecycleSaleEvidenceDigest,
    });
    const lifecycleSalePrepared = JSON.stringify({
      positionId: lifecyclePositionId, netProceeds: "75.00",
      fifoBookCostBasisReduction: "51.13",
      fifoTaxBasisReduction: "51.13", bookGainOrLoss: "23.87",
      taxGainOrLoss: "23.87", exemptGain: "23.87", taxableGain: "0.00",
      nonDeductibleLoss: "0.00", deductibleLoss: "0.00",
      evidenceDigest: lifecycleSaleEvidenceDigest,
      calculationId: lifecycleSaleCalculationId,
      lotCalculations: [{
        lotId: lifecycleLotId, allocationOrder: 1,
        allocatedShareCount: "4.125000000000",
        allocatedNetProceeds: "75.00", allocatedBookCostBasis: "51.13",
        allocatedTaxBasis: "51.13", taxGainOrLoss: "23.87",
        averageFundEquityRatioBasisPoints: null, exemptGain: "23.87",
        taxableGain: "0.00", nonDeductibleLoss: "0.00",
        deductibleLoss: "0.00",
      }],
    });
    const lifecycleSaleSources = JSON.stringify([
      {
        role: "PRIMARY", capability: "INVESTMENTS",
        recordId: lifecycleSaleEventId, revision: 1,
        factSha256: lifecycleSaleCalculationId,
      },
      ...lifecycleSaleDocumentFacts.map((fact) => ({
        role: "CORROBORATING", ...fact,
      })),
    ]);
    const lifecycleSaleSettlementRequest = JSON.stringify({
      companyId, incomeYear: 2026, settlementId: lifecycleSaleSettlementId,
      eventId: lifecycleSaleEventId,
      idempotencyKey: "lifecycle-sale-settlement-0001",
      correlationId: "lifecycle-sale-settlement", settlementDate: "2026-12-31",
      amount: "75.00", evidenceMode: "linked_sources",
      evidenceReference: "sale proceeds bank transaction revision 1",
      ownerAttested: false, documentFacts: [], bankFact: {
        capability: "BANKING", recordId: lifecycleSaleBankFact,
        revision: 1, factSha256: "2".repeat(64),
      }, evidenceDigest: lifecycleSaleSettlementEvidenceDigest,
    });

    assert.equal(scalar(containerName, String.raw`
      begin;
      set local role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', true);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', true
      );
      create temporary table lifecycle_sale_prepared as
      select investments.prepare_share_sale_recognition_v2(
        '${lifecycleSaleRequest}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_sale_entry as
      select * from ledger.post_investment_lifecycle_entry_v2(
        'lifecycle-sale-recognition-0001', '${companyId}', 2026,
        'SHARE_SALE', 'Investment sale recognized: Lifecycle Private AS',
        '[{"account":"1570","description":"Investment settlement receivable","debit":"75.00","credit":"0.00","currency":"NOK"},{"account":"1350","description":"Cost basis reduction: Lifecycle Private AS","debit":"0.00","credit":"51.13","currency":"NOK"},{"account":"8071","description":"Share sale gain: Lifecycle Private AS","debit":"0.00","credit":"23.87","currency":"NOK"}]'::jsonb,
        'INVESTMENTS', '${lifecycleSaleEventId}', 'lifecycle-sale-recognition',
        '${ownerId}', date '2026-12-30',
        'ledger-supported-patterns-2026.1', '${lifecycleSaleSources}'::jsonb
      );
      create temporary table lifecycle_sale_recognized as
      select investments.complete_share_sale_recognition_v2(
        '${lifecycleSaleRequest}'::jsonb,
        (select ledger_entry_id from lifecycle_sale_entry),
        '${lifecycleSalePrepared}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_sale_settlement_prepared as
      select investments.prepare_cash_settlement_v2(
        '${lifecycleSaleSettlementRequest}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_sale_settlement_entry as
      select * from ledger.post_investment_lifecycle_entry_v2(
        'lifecycle-sale-settlement-0001', '${companyId}', 2026,
        'SHARE_SALE', 'Investment sale receivable settled',
        '[{"account":"1920","description":"Investment proceeds received","debit":"75.00","credit":"0.00","currency":"NOK"},{"account":"1570","description":"Investment settlement receivable cleared","debit":"0.00","credit":"75.00","currency":"NOK"}]'::jsonb,
        'INVESTMENTS', '${lifecycleSaleSettlementId}',
        'lifecycle-sale-settlement', '${ownerId}', date '2026-12-31',
        'ledger-supported-patterns-2026.1',
        pg_catalog.jsonb_build_array(
          pg_catalog.jsonb_build_object(
            'role', 'PRIMARY', 'capability', 'INVESTMENTS',
            'recordId', '${lifecycleSaleSettlementId}', 'revision', 1,
            'factSha256',
              (select value ->> 'eventFactSha256'
               from lifecycle_sale_settlement_prepared)
          ),
          pg_catalog.jsonb_build_object(
            'role', 'CORROBORATING', 'capability', 'BANKING',
            'recordId', '${lifecycleSaleBankFact}', 'revision', 1,
            'factSha256', repeat('2', 64)
          )
        )
      );
      create temporary table lifecycle_sale_settled as
      select investments.complete_cash_settlement_v2(
        '${lifecycleSaleSettlementRequest}'::jsonb,
        (select ledger_entry_id from lifecycle_sale_settlement_entry),
        (select value from lifecycle_sale_settlement_prepared), '${ownerId}'
      ) as value;
      commit;
      select
        (select value ->> 'fifoBookCostBasisReduction'
          from lifecycle_sale_prepared) || ':' ||
        (select value ->> 'settlementBalanceKind'
          from lifecycle_sale_recognized) || ':' ||
        (select value ->> 'replayed' from lifecycle_sale_settled) || ':' ||
        (select share_count::text from investments.positions
          where id = '${lifecyclePositionId}') || ':' ||
        (select remaining_share_count::text from investments.acquisition_lots
          where id = '${lifecycleLotId}') || ':' ||
        (select count(*)::text from investments.share_sale_allocations
          where sale_action_id = '${lifecycleSaleEventId}');
    `), "51.13:sale_receivable:false:6.000000000000:6.000000000000:1");

    assert.equal(scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', false
      );
      select
        (investments.get_share_sale_recognition_replay_v2(
          pg_catalog.jsonb_set(
            '${lifecycleSaleRequest}'::jsonb,
            '{correlationId}', '"lifecycle-sale-recognition-retry"'
          ), '${ownerId}'
        ) ->> 'replayed') || ':' ||
        (investments.get_cash_settlement_replay_v2(
          pg_catalog.jsonb_set(
            '${lifecycleSaleSettlementRequest}'::jsonb,
            '{correlationId}', '"lifecycle-sale-settlement-retry"'
          ), '${ownerId}'
        ) ->> 'replayed');
    `), "true:true");

    expectLifecycleForeignKeyFailure(String.raw`
      insert into investments.cash_settlements (
        settlement_id, event_id, company_id, income_year, settlement_date,
        amount, source_capability, source_record_id, source_revision,
        fact_sha256, idempotency_key, request_fingerprint, evidence_mode,
        evidence_reference, owner_attested, evidence_digest,
        settlement_accounting_entry_id, created_by, supersedes_settlement_id
      ) values (
        '92000000-0000-0000-0000-000000000005',
        '${lifecycleEventId}', '${companyId}', 2026, date '2026-12-31',
        125.50, 'BANKING', '${lifecycleBankFact}', 1, repeat('c', 64),
        'cross-event-supersession-0001', repeat('6', 64), 'linked_sources',
        'cross-event supersession must fail', false, repeat('7', 64),
        '92000000-0000-0000-0000-000000000006', '${ownerId}',
        '${lifecycleSaleSettlementId}'
      );
    `, "cash settlement cross-event supersession");

    const reusedLifecycleSale = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test",
    ], { input: String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', false
      );
      select investments.get_share_sale_recognition_replay_v2(
        pg_catalog.jsonb_set(
          '${lifecycleSaleRequest}'::jsonb, '{soldShareCount}', '"4.126"'
        ), '${ownerId}'
      );
    ` });
    assert.notEqual(reusedLifecycleSale.status, 0);
    assert.match(
      `${reusedLifecycleSale.stdout}\n${reusedLifecycleSale.stderr}`,
      /investments_idempotency_key_reused/u,
    );

    const refusedShareSaleLifecycleRollback = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test", "--file",
      `/repo/supabase/rollback/${investmentsShareSaleLifecycleMigration}`,
    ]);
    assert.notEqual(refusedShareSaleLifecycleRollback.status, 0);
    assert.match(
      `${refusedShareSaleLifecycleRollback.stdout}\n${refusedShareSaleLifecycleRollback.stderr}`,
      /investments_share_sale_lifecycle_rollback_unsafe/u,
    );

    const lifecycleDividendEventId = "93000000-0000-0000-0000-000000000001";
    const lifecycleDividendSettlementId = "93000000-0000-0000-0000-000000000002";
    const lifecycleDividendDocumentId = "93000000-0000-0000-0000-000000000003";
    const lifecycleDividendBankFact = "93000000-0000-0000-0000-000000000004";
    const lifecycleFundPositionId = "94000000-0000-0000-0000-000000000001";
    const lifecycleFundEventId = "94000000-0000-0000-0000-000000000002";
    const lifecycleFundSettlementId = "94000000-0000-0000-0000-000000000003";
    const lifecycleFundDocumentId = "94000000-0000-0000-0000-000000000004";
    const lifecycleFundBankFact = "94000000-0000-0000-0000-000000000005";
    const lifecycleFundReplacementEventId =
      "94000000-0000-0000-0000-000000000006";
    const lifecycleFundCorrectionId =
      "94000000-0000-0000-0000-000000000007";
    const lifecycleFundCorrectionDocumentId =
      "94000000-0000-0000-0000-000000000008";
    const lifecycleFundReplacementDocumentId =
      "94000000-0000-0000-0000-000000000009";
    const lifecycleDividendCalculationId = "6".repeat(64);
    const lifecycleFundCalculationId = "7".repeat(64);
    const lifecycleDividendRequest = JSON.stringify({
      companyId, incomeYear: 2026, eventId: lifecycleDividendEventId,
      positionId: lifecyclePositionId,
      idempotencyKey: "lifecycle-dividend-recognition-0001",
      correlationId: "lifecycle-dividend-recognition",
      payingCompanyName: "Lifecycle Private AS", declaredDate: "2026-12-30",
      grossAmount: "100.00", lawfulDividendConfirmed: true,
      groupExceptionClaimed: false, yearEndOwnershipBasisPoints: null,
      yearEndVotingBasisPoints: null, groupEvidenceReference: null,
      evidenceMode: "linked_sources", evidenceReference: "dividend decision",
      ownerAttested: false, documentFacts: [{
        capability: "DOCUMENTS", recordId: lifecycleDividendDocumentId,
        revision: 1, factSha256: "8".repeat(64),
      }], bankFact: null, evidenceDigest: "9".repeat(64),
    });
    const lifecycleDividendPrepared = JSON.stringify({
      positionId: lifecyclePositionId, taxableAddBack: "3.00",
      groupExceptionApplied: false, evidenceDigest: "9".repeat(64),
      calculationId: lifecycleDividendCalculationId,
    });
    const lifecycleDividendSources = JSON.stringify([
      {
        role: "PRIMARY", capability: "INVESTMENTS",
        recordId: lifecycleDividendEventId, revision: 1,
        factSha256: lifecycleDividendCalculationId,
      },
      {
        role: "CORROBORATING", capability: "DOCUMENTS",
        recordId: lifecycleDividendDocumentId, revision: 1,
        factSha256: "8".repeat(64),
      },
    ]);
    const lifecycleDividendSettlementRequest = JSON.stringify({
      companyId, incomeYear: 2026, settlementId: lifecycleDividendSettlementId,
      eventId: lifecycleDividendEventId,
      idempotencyKey: "lifecycle-dividend-settlement-0001",
      correlationId: "lifecycle-dividend-settlement",
      settlementDate: "2026-12-31", amount: "100.00",
      evidenceMode: "linked_sources", evidenceReference: "dividend bank receipt",
      ownerAttested: false, documentFacts: [], bankFact: {
        capability: "BANKING", recordId: lifecycleDividendBankFact,
        revision: 1, factSha256: "a".repeat(64),
      }, evidenceDigest: "b".repeat(64),
    });
    const lifecycleFundRequest = JSON.stringify({
      companyId, incomeYear: 2026, eventId: lifecycleFundEventId,
      positionId: lifecycleFundPositionId,
      idempotencyKey: "lifecycle-fund-recognition-0001",
      correlationId: "lifecycle-fund-recognition",
      fundName: "Lifecycle Mixed Fund", entitlementDate: "2026-12-30",
      grossAmount: "100.00", openingFundEquityRatioBasisPoints: 5000,
      fundTaxStatementReference: "fund-tax-statement-2026",
      evidenceMode: "linked_sources", evidenceReference: "fund distribution notice",
      ownerAttested: false, documentFacts: [{
        capability: "DOCUMENTS", recordId: lifecycleFundDocumentId,
        revision: 2, factSha256: "c".repeat(64),
      }], bankFact: null, evidenceDigest: "d".repeat(64),
    });
    const lifecycleFundPrepared = JSON.stringify({
      positionId: lifecycleFundPositionId, dividendPortion: "50.00",
      interestPortion: "50.00", taxableAddBack: "1.50",
      totalTaxableIncome: "51.50", evidenceDigest: "d".repeat(64),
      calculationId: lifecycleFundCalculationId,
    });
    const lifecycleFundSources = JSON.stringify([
      {
        role: "PRIMARY", capability: "INVESTMENTS",
        recordId: lifecycleFundEventId, revision: 1,
        factSha256: lifecycleFundCalculationId,
      },
      {
        role: "CORROBORATING", capability: "DOCUMENTS",
        recordId: lifecycleFundDocumentId, revision: 2,
        factSha256: "c".repeat(64),
      },
    ]);
    const lifecycleFundSettlementRequest = JSON.stringify({
      companyId, incomeYear: 2026, settlementId: lifecycleFundSettlementId,
      eventId: lifecycleFundReplacementEventId,
      idempotencyKey: "lifecycle-fund-settlement-0001",
      correlationId: "lifecycle-fund-settlement",
      settlementDate: "2026-12-31", amount: "110.00",
      evidenceMode: "linked_sources", evidenceReference: "fund bank receipt",
      ownerAttested: false, documentFacts: [], bankFact: {
        capability: "BANKING", recordId: lifecycleFundBankFact,
        revision: 1, factSha256: "e".repeat(64),
      }, evidenceDigest: "f".repeat(64),
    });
    const lifecycleFundReplacementRequest = JSON.stringify({
      companyId, incomeYear: 2026, eventId: lifecycleFundReplacementEventId,
      positionId: lifecycleFundPositionId,
      idempotencyKey: "lifecycle-fund-replacement-0001",
      correlationId: "lifecycle-fund-replacement",
      fundName: "Lifecycle Mixed Fund", entitlementDate: "2026-12-31",
      grossAmount: "110.00", openingFundEquityRatioBasisPoints: 5000,
      fundTaxStatementReference: "fund-tax-statement-2026-corrected",
      evidenceMode: "linked_sources",
      evidenceReference: "corrected fund distribution notice",
      ownerAttested: false, documentFacts: [{
        capability: "DOCUMENTS", recordId: lifecycleFundReplacementDocumentId,
        revision: 1, factSha256: "1".repeat(64),
      }], bankFact: null, evidenceDigest: "2".repeat(64),
    });
    const lifecycleFundReplacementPrepared = JSON.stringify({
      positionId: lifecycleFundPositionId, dividendPortion: "55.00",
      interestPortion: "55.00", taxableAddBack: "1.65",
      totalTaxableIncome: "56.65", evidenceDigest: "2".repeat(64),
      calculationId: "3".repeat(64),
    });
    const lifecycleFundReplacementSources = JSON.stringify([
      {
        role: "PRIMARY", capability: "INVESTMENTS",
        recordId: lifecycleFundReplacementEventId, revision: 1,
        factSha256: "3".repeat(64),
      },
      {
        role: "CORROBORATING", capability: "DOCUMENTS",
        recordId: lifecycleFundReplacementDocumentId, revision: 1,
        factSha256: "1".repeat(64),
      },
    ]);
    const lifecycleFundCorrectionRequest = JSON.stringify({
      companyId, incomeYear: 2026, correctionId: lifecycleFundCorrectionId,
      idempotencyKey: "lifecycle-fund-event-correction-0001",
      correlationId: "lifecycle-fund-event-correction",
      targetKind: "economic_event", originalRecordId: lifecycleFundEventId,
      replacementRecordId: lifecycleFundReplacementEventId,
      originalActivityKind: "fund_distribution_received",
      replacementActivityKind: "fund_distribution_received",
      correctionDate: "2026-12-31",
      reason: "Correct fund entitlement amount",
      evidenceMode: "linked_sources",
      evidenceReference: "signed fund entitlement correction",
      ownerAttested: false, documentFacts: [{
        capability: "DOCUMENTS", recordId: lifecycleFundCorrectionDocumentId,
        revision: 1, factSha256: "4".repeat(64),
      }], bankFact: null, evidenceDigest: "5".repeat(64),
      replacement: JSON.parse(lifecycleFundReplacementRequest),
    });

    psql(containerName, [], String.raw`
      insert into investments.positions (
        id, company_id, investment_key, name, kind, tax_treatment,
        share_count, cost_basis, tax_basis, movements, lot_history_status,
        accounting_classification, fund_equity_ratio_basis_points,
        fund_tax_statement_reference, created_by
      ) values (
        '${lifecycleFundPositionId}', '${companyId}', 'lifecycle-mixed-fund',
        'Lifecycle Mixed Fund', 'norwegian_equity_fund', 'fritaksmetoden',
        100, 1000, 1000, '[]'::jsonb, 'complete', 'current_fund', 5000,
        'fund-tax-statement-2026', '${ownerId}'
      );
    `);

    assert.equal(scalar(containerName, String.raw`
      begin;
      set local role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', true);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', true
      );
      create temporary table lifecycle_dividend_prepared as
      select investments.prepare_received_dividend_recognition_v2(
        '${lifecycleDividendRequest}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_dividend_entry as
      select * from ledger.post_investment_lifecycle_entry_v2(
        'lifecycle-dividend-recognition-0001', '${companyId}', 2026,
        'DIVIDEND_RECEIVED', 'Final investment-dividend decision recognized',
        '[{"account":"1530","description":"Dividend receivable","debit":"100.00","credit":"0.00","currency":"NOK"},{"account":"8070","description":"Dividend income","debit":"0.00","credit":"100.00","currency":"NOK"}]'::jsonb,
        'INVESTMENTS', '${lifecycleDividendEventId}',
        'lifecycle-dividend-recognition', '${ownerId}', date '2026-12-30',
        'ledger-supported-patterns-2026.1', '${lifecycleDividendSources}'::jsonb
      );
      create temporary table lifecycle_dividend_recognized as
      select investments.complete_received_dividend_recognition_v2(
        '${lifecycleDividendRequest}'::jsonb,
        (select ledger_entry_id from lifecycle_dividend_entry),
        '${lifecycleDividendPrepared}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_dividend_settlement_prepared as
      select investments.prepare_cash_settlement_v2(
        '${lifecycleDividendSettlementRequest}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_dividend_settlement_entry as
      select * from ledger.post_investment_lifecycle_entry_v2(
        'lifecycle-dividend-settlement-0001', '${companyId}', 2026,
        'DIVIDEND_RECEIVED', 'Investment income receivable settled',
        '[{"account":"1920","description":"Investment income received","debit":"100.00","credit":"0.00","currency":"NOK"},{"account":"1530","description":"Investment income receivable cleared","debit":"0.00","credit":"100.00","currency":"NOK"}]'::jsonb,
        'INVESTMENTS', '${lifecycleDividendSettlementId}',
        'lifecycle-dividend-settlement', '${ownerId}', date '2026-12-31',
        'ledger-supported-patterns-2026.1',
        pg_catalog.jsonb_build_array(
          pg_catalog.jsonb_build_object(
            'role', 'PRIMARY', 'capability', 'INVESTMENTS',
            'recordId', '${lifecycleDividendSettlementId}', 'revision', 1,
            'factSha256', (select value ->> 'eventFactSha256'
              from lifecycle_dividend_settlement_prepared)
          ),
          pg_catalog.jsonb_build_object(
            'role', 'CORROBORATING', 'capability', 'BANKING',
            'recordId', '${lifecycleDividendBankFact}', 'revision', 1,
            'factSha256', repeat('a', 64)
          )
        )
      );
      create temporary table lifecycle_dividend_settled as
      select investments.complete_cash_settlement_v2(
        '${lifecycleDividendSettlementRequest}'::jsonb,
        (select ledger_entry_id from lifecycle_dividend_settlement_entry),
        (select value from lifecycle_dividend_settlement_prepared), '${ownerId}'
      ) as value;

      create temporary table lifecycle_fund_prepared as
      select investments.prepare_received_fund_distribution_recognition_v2(
        '${lifecycleFundRequest}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_fund_entry as
      select * from ledger.post_investment_lifecycle_entry_v2(
        'lifecycle-fund-recognition-0001', '${companyId}', 2026,
        'DIVIDEND_RECEIVED', 'Fund distribution recognized: Lifecycle Mixed Fund',
        '[{"account":"1530","description":"Fund distribution receivable","debit":"100.00","credit":"0.00","currency":"NOK"},{"account":"8070","description":"Fund dividend from Lifecycle Mixed Fund","debit":"0.00","credit":"50.00","currency":"NOK"},{"account":"8050","description":"Fund interest income from Lifecycle Mixed Fund","debit":"0.00","credit":"50.00","currency":"NOK"}]'::jsonb,
        'INVESTMENTS', '${lifecycleFundEventId}', 'lifecycle-fund-recognition',
        '${ownerId}', date '2026-12-30',
        'ledger-supported-patterns-2026.1', '${lifecycleFundSources}'::jsonb
      );
      create temporary table lifecycle_fund_recognized as
      select investments.complete_received_fund_distribution_recognition_v2(
        '${lifecycleFundRequest}'::jsonb,
        (select ledger_entry_id from lifecycle_fund_entry),
        '${lifecycleFundPrepared}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_fund_correction_prepared as
      select investments.prepare_economic_event_correction_v2(
        '${lifecycleFundCorrectionRequest}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_fund_replacement_prepared as
      select investments.prepare_received_fund_distribution_recognition_v2(
        '${lifecycleFundReplacementRequest}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_fund_replacement_entry as
      select * from ledger.post_investment_lifecycle_entry_v2(
        'lifecycle-fund-replacement-0001', '${companyId}', 2026,
        'DIVIDEND_RECEIVED',
        'Corrected fund distribution recognized: Lifecycle Mixed Fund',
        '[{"account":"1530","description":"Corrected fund distribution receivable","debit":"110.00","credit":"0.00","currency":"NOK"},{"account":"8070","description":"Corrected fund dividend from Lifecycle Mixed Fund","debit":"0.00","credit":"55.00","currency":"NOK"},{"account":"8050","description":"Corrected fund interest income from Lifecycle Mixed Fund","debit":"0.00","credit":"55.00","currency":"NOK"}]'::jsonb,
        'INVESTMENTS', '${lifecycleFundReplacementEventId}',
        'lifecycle-fund-replacement', '${ownerId}', date '2026-12-31',
        'ledger-supported-patterns-2026.1',
        '${lifecycleFundReplacementSources}'::jsonb
      );
      create temporary table lifecycle_fund_replacement_recognized as
      select investments.complete_received_fund_distribution_recognition_v2(
        '${lifecycleFundReplacementRequest}'::jsonb,
        (select ledger_entry_id from lifecycle_fund_replacement_entry),
        '${lifecycleFundReplacementPrepared}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_fund_correction_reversal as
      select ledger.link_investment_correction_v1(
        '${companyId}', 2026,
        (select (value ->> 'originalAccountingEntryId')::uuid
          from lifecycle_fund_correction_prepared),
        (select ledger_entry_id from lifecycle_fund_replacement_entry),
        '${lifecycleFundEventId}', '${lifecycleFundReplacementEventId}',
        'Correct fund entitlement amount', 'lifecycle-fund-event-correction',
        date '2026-12-31', '${ownerId}'
      ) as reversal_entry_id;
      create temporary table lifecycle_fund_corrected as
      select investments.complete_lifecycle_correction_v2(
        '${lifecycleFundCorrectionRequest}'::jsonb,
        (select (value ->> 'originalAccountingEntryId')::uuid
          from lifecycle_fund_correction_prepared),
        (select ledger_entry_id from lifecycle_fund_replacement_entry),
        (select reversal_entry_id from lifecycle_fund_correction_reversal),
        '${ownerId}'
      ) as value;
      create temporary table lifecycle_fund_settlement_prepared as
      select investments.prepare_cash_settlement_v2(
        '${lifecycleFundSettlementRequest}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table lifecycle_fund_settlement_entry as
      select * from ledger.post_investment_lifecycle_entry_v2(
        'lifecycle-fund-settlement-0001', '${companyId}', 2026,
        'DIVIDEND_RECEIVED', 'Investment income receivable settled',
        '[{"account":"1920","description":"Investment income received","debit":"110.00","credit":"0.00","currency":"NOK"},{"account":"1530","description":"Investment income receivable cleared","debit":"0.00","credit":"110.00","currency":"NOK"}]'::jsonb,
        'INVESTMENTS', '${lifecycleFundSettlementId}',
        'lifecycle-fund-settlement', '${ownerId}', date '2026-12-31',
        'ledger-supported-patterns-2026.1',
        pg_catalog.jsonb_build_array(
          pg_catalog.jsonb_build_object(
            'role', 'PRIMARY', 'capability', 'INVESTMENTS',
            'recordId', '${lifecycleFundSettlementId}', 'revision', 1,
            'factSha256', (select value ->> 'eventFactSha256'
              from lifecycle_fund_settlement_prepared)
          ),
          pg_catalog.jsonb_build_object(
            'role', 'CORROBORATING', 'capability', 'BANKING',
            'recordId', '${lifecycleFundBankFact}', 'revision', 1,
            'factSha256', repeat('e', 64)
          )
        )
      );
      create temporary table lifecycle_fund_settled as
      select investments.complete_cash_settlement_v2(
        '${lifecycleFundSettlementRequest}'::jsonb,
        (select ledger_entry_id from lifecycle_fund_settlement_entry),
        (select value from lifecycle_fund_settlement_prepared), '${ownerId}'
      ) as value;
      commit;
      select
        (select value ->> 'settlementBalanceKind'
          from lifecycle_dividend_recognized) || ':' ||
        (select taxable_add_back::text
          from investments.received_dividend_recognitions
          where event_id = '${lifecycleDividendEventId}') || ':' ||
        (select value ->> 'replayed' from lifecycle_dividend_settled) || ':' ||
        (select value ->> 'settlementBalanceKind'
          from lifecycle_fund_recognized) || ':' ||
        (select dividend_portion::text || ':' || interest_portion::text || ':' ||
          total_taxable_income::text
          from investments.received_fund_distribution_recognitions
          where event_id = '${lifecycleFundReplacementEventId}') || ':' ||
        (select value ->> 'targetKind' from lifecycle_fund_corrected) || ':' ||
        (select value ->> 'replayed' from lifecycle_fund_settled);
    `), "dividend_receivable:3.000000000000:false:fund_distribution_receivable:55.000000000000:55.000000000000:56.650000000000:economic_event:false");

    assert.equal(scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', false
      );
      select
        (investments.get_received_dividend_recognition_replay_v2(
          pg_catalog.jsonb_set(
            '${lifecycleDividendRequest}'::jsonb,
            '{correlationId}', '"lifecycle-dividend-retry"'
          ), '${ownerId}'
        ) ->> 'replayed') || ':' ||
        (investments.get_received_fund_distribution_recognition_replay_v2(
          pg_catalog.jsonb_set(
            '${lifecycleFundRequest}'::jsonb,
            '{correlationId}', '"lifecycle-fund-retry"'
          ), '${ownerId}'
        ) ->> 'replayed') || ':' ||
        (investments.get_lifecycle_correction_replay_v2(
          pg_catalog.jsonb_set(
            '${lifecycleFundCorrectionRequest}'::jsonb,
            '{correlationId}', '"lifecycle-fund-correction-retry"'
          ), '${ownerId}'
        ) ->> 'replayed');
    `), "true:true:true");

    const refusedIncomeLifecycleRollback = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test", "--file",
      `/repo/supabase/rollback/${investmentsIncomeLifecycleMigration}`,
    ]);
    assert.notEqual(refusedIncomeLifecycleRollback.status, 0);
    assert.match(
      `${refusedIncomeLifecycleRollback.stdout}\n${refusedIncomeLifecycleRollback.stderr}`,
      /investments_income_lifecycle_rollback_unsafe/u,
    );

    const reusedLifecycle = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test",
    ], { input: String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', false
      );
      select investments.get_share_purchase_recognition_replay_v2(
        pg_catalog.jsonb_set(
          '${lifecyclePurchaseRequest}'::jsonb, '{shareCount}', '"11.125"'
        ), '${ownerId}'
      );
    ` });
    assert.notEqual(reusedLifecycle.status, 0);
    assert.match(
      `${reusedLifecycle.stdout}\n${reusedLifecycle.stderr}`,
      /investments_idempotency_key_reused/u,
    );

    const refusedLifecycleRollback = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test", "--file",
      `/repo/supabase/rollback/${investmentsLifecycleWorkflowMigration}`,
    ]);
    assert.notEqual(refusedLifecycleRollback.status, 0);
    assert.match(
      `${refusedLifecycleRollback.stdout}\n${refusedLifecycleRollback.stderr}`,
      /investments_lifecycle_workflow_rollback_unsafe/u,
    );

    const tenantParentPositionId = "30000000-0000-0000-0000-000000000099";
    const tenantEventId = "90000000-0000-0000-0000-000000000001";
    const tenantLotId = "90000000-0000-0000-0000-000000000011";
    const tenantMeasurementId = "90000000-0000-0000-0000-000000000002";
    psql(containerName, [], String.raw`
      insert into public.companies (
        id, org_number, name, entity_type, address, postal_code, city,
        status_text, source, created_by, identity_confirmed_at, identity_locked_at
      ) values (
        '${secondCompanyId}', '271828182', 'Second Investments AS', 'AS',
        'Two', '0151', 'Oslo', 'Active', 'test', '${ownerId}',
        pg_catalog.now(), pg_catalog.now()
      );
      insert into public.company_memberships (company_id, user_id, role, accepted_at)
      values ('${secondCompanyId}', '${ownerId}', 'owner', pg_catalog.now());
      insert into investments.company_year_policies (
        company_id, income_year, policy_version, tax_law_version,
        current_measurement_rule, long_term_measurement_rule, created_by
      ) values
        ('${companyId}', 2026, 'domestic_2026_v2', 'norwegian_2026',
          'lower_of_cost_and_fair_value', 'cost_with_evidenced_impairment', '${ownerId}'),
        ('${secondCompanyId}', 2026, 'domestic_2026_v2', 'norwegian_2026',
          'lower_of_cost_and_fair_value', 'cost_with_evidenced_impairment', '${ownerId}')
      on conflict (company_id, income_year) do nothing;
      insert into investments.positions (
        id, company_id, investment_key, name, kind, tax_treatment, org_number,
        share_count, cost_basis, tax_basis, movements, lot_history_status,
        accounting_classification, created_by
      ) values (
        '${tenantParentPositionId}', '${companyId}', 'tenant-parent-as',
        'Tenant Parent AS', 'norwegian_private_company', 'fritaksmetoden',
        '123123123', 10, 1000, 1000, '[]'::jsonb, 'complete',
        'other_long_term', '${ownerId}'
      );
      insert into investments.economic_events (
        event_id, company_id, income_year, event_kind, position_id,
        recognition_date, policy_version, idempotency_key, request_fingerprint,
        evidence_mode, evidence_reference, owner_attested, evidence_digest,
        calculation_id, recognition_accounting_entry_id,
        expected_settlement_amount, settlement_balance_kind, created_by
      ) values (
        '${tenantEventId}', '${companyId}', 2026, 'share_purchase',
        '${tenantParentPositionId}', date '2026-06-01', 'domestic_2026_v2',
        'tenant-parent-event', repeat('1', 64), 'linked_sources',
        'broker-note-1', false, repeat('2', 64), repeat('3', 64),
        '90000000-0000-0000-0000-000000000003', 1000,
        'purchase_payable', '${ownerId}'
      );
      insert into investments.acquisition_lots (
        id, company_id, position_id, acquisition_action_id, acquisition_date,
        original_share_count, remaining_share_count,
        original_cost_basis, remaining_cost_basis,
        original_tax_basis, remaining_tax_basis, created_by
      ) values (
        '${tenantLotId}', '${companyId}', '${tenantParentPositionId}',
        '${tenantEventId}', date '2026-06-01', 10, 10,
        1000, 1000, 1000, 1000, '${ownerId}'
      );
    `);
    const crossCompanyCorrectionSourceId =
      "94000000-0000-0000-0000-000000000010";
    psql(containerName, [], String.raw`
      insert into investments.source_fact_registry (
        company_id, source_capability, source_record_id, source_revision,
        fact_sha256
      ) values (
        '${secondCompanyId}', 'DOCUMENTS',
        '${crossCompanyCorrectionSourceId}', 1, repeat('6', 64)
      );
    `);
    expectLifecycleForeignKeyFailure(String.raw`
      insert into investments.lifecycle_correction_sources (
        correction_id, company_id, ordinal, source_capability,
        source_record_id, source_revision, fact_sha256
      ) values (
        '${lifecycleFundCorrectionId}', '${secondCompanyId}', 99, 'DOCUMENTS',
        '${crossCompanyCorrectionSourceId}', 1, repeat('6', 64)
      );
    `, "lifecycle correction source tenant mismatch");
    psql(containerName, [], String.raw`
      delete from investments.source_fact_registry
      where company_id = '${secondCompanyId}'
        and source_capability = 'DOCUMENTS'
        and source_record_id = '${crossCompanyCorrectionSourceId}'
        and source_revision = 1;
    `);
    const expectTenantMismatch = (sql, label) => {
      const result = docker([
        "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
        "-U", "postgres", "-d", "talli_test",
      ], { input: sql });
      assert.notEqual(result.status, 0, `${label} must fail closed`);
      assert.match(`${result.stdout}\n${result.stderr}`, /foreign key constraint/iu, label);
    };
    expectTenantMismatch(String.raw`
      set role investments_store_owner;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      insert into investments.event_sources (
        event_id, company_id, ordinal, role, source_capability,
        source_record_id, source_revision, fact_sha256
      ) values (
        '${tenantEventId}', '${secondCompanyId}', 1, 'primary_document',
        'DOCUMENTS', '90000000-0000-0000-0000-000000000004', 1, repeat('4', 64)
      );
    `, "event source tenant mismatch");
    expectTenantMismatch(String.raw`
      set role investments_store_owner;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      insert into investments.cash_settlements (
        settlement_id, event_id, company_id, income_year, settlement_date,
        amount, source_capability, source_record_id, source_revision,
        fact_sha256, idempotency_key, request_fingerprint, evidence_mode,
        evidence_reference, owner_attested, evidence_digest,
        settlement_accounting_entry_id, created_by
      ) values (
        '90000000-0000-0000-0000-000000000005', '${tenantEventId}',
        '${secondCompanyId}', 2026, date '2026-06-02', 1000, 'BANKING',
        '90000000-0000-0000-0000-000000000006', 1, repeat('5', 64),
        'tenant-cross-settlement', repeat('6', 64), 'linked_sources',
        'bank-transaction-1', false, repeat('7', 64),
        '90000000-0000-0000-0000-000000000007', '${ownerId}'
      );
    `, "cash settlement tenant mismatch");
    expectTenantMismatch(String.raw`
      set role investments_store_owner;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      insert into investments.position_classifications (
        position_id, company_id, income_year, accounting_classification,
        purpose_reference, source_capability, source_record_id, source_revision,
        fact_sha256, created_by
      ) values (
        '${tenantParentPositionId}', '${secondCompanyId}', 2026,
        'other_long_term', 'owner purpose', 'DOCUMENTS',
        '90000000-0000-0000-0000-000000000008', 1, repeat('8', 64), '${ownerId}'
      );
    `, "position classification tenant mismatch");
    psql(containerName, [], String.raw`
      insert into investments.position_classifications (
        position_id, company_id, income_year, accounting_classification,
        purpose_reference, source_capability, source_record_id, source_revision,
        fact_sha256, created_by
      ) values (
        '${tenantParentPositionId}', '${companyId}', 2026, 'other_long_term',
        'owner purpose', 'DOCUMENTS',
        '90000000-0000-0000-0000-000000000009', 1, repeat('9', 64), '${ownerId}'
      );
    `);
    const measurementRequest = JSON.stringify({
      companyId, incomeYear: 2026, measurementId: tenantMeasurementId,
      positionId: tenantParentPositionId, asOf: "2026-12-31",
      observedOrRecoverableValue: "900.00", taxValue: "1000.00",
      idempotencyKey: "tenant-measurement-0001",
      correlationId: "tenant-measurement", evidenceMode: "linked_sources",
      evidenceReference: "tenant valuation", ownerAttested: false,
      documentFacts: [{
        capability: "DOCUMENTS",
        recordId: "90000000-0000-0000-0000-000000000009",
        revision: 1, factSha256: "c".repeat(64),
      }],
      bankFact: null,
    });
    assert.equal(scalar(containerName, String.raw`
      begin;
      set local role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', true);
      select pg_catalog.set_config(
        'talli.verified_actor_claims',
        '{"sub":"${ownerId}","role":"authenticated","aal":"aal2"}', true
      );
      create temporary table measurement_prepared as
      select investments.prepare_year_end_measurement_v2(
        pg_catalog.jsonb_set(
          '${measurementRequest}'::jsonb, '{evidenceDigest}',
          pg_catalog.to_jsonb(repeat('a', 64))
        ), '${ownerId}'
      ) as value;
      create temporary table measurement_entry as
      select * from ledger.post_investment_lifecycle_entry_v2(
        'tenant-measurement-0001', '${companyId}', 2026,
        'INVESTMENT_MEASUREMENT',
        'Year-end investment impairment: Tenant Parent AS',
        '[{"account":"8172","description":"Investment impairment: Tenant Parent AS","debit":"100.00","credit":"0.00","currency":"NOK"},{"account":"1350","description":"Investment carrying value reduced: Tenant Parent AS","debit":"0.00","credit":"100.00","currency":"NOK"}]'::jsonb,
        'INVESTMENTS', '${tenantMeasurementId}', 'tenant-measurement',
        '${ownerId}', date '2026-12-31',
        'ledger-supported-patterns-2026.1',
        pg_catalog.jsonb_build_array(
          pg_catalog.jsonb_build_object(
            'role', 'PRIMARY', 'capability', 'INVESTMENTS',
            'recordId', '${tenantMeasurementId}', 'revision', 1,
            'factSha256', repeat('b', 64)
          ),
          pg_catalog.jsonb_build_object(
            'role', 'CORROBORATING', 'capability', 'DOCUMENTS',
            'recordId', '90000000-0000-0000-0000-000000000009',
            'revision', 1, 'factSha256', repeat('c', 64)
          )
        )
      );
      select investments.complete_year_end_measurement_v2(
        '${measurementRequest}'::jsonb,
        (select ledger_entry_id from measurement_entry),
        pg_catalog.jsonb_build_object(
          'positionId', '${tenantParentPositionId}',
          'measurementRule', 'cost_with_evidenced_impairment',
          'quantity', '10.000000000000', 'sourceBookCost', '1000.00',
          'preMeasurementBookValue', '1000.00',
          'observedOrRecoverableValue', '900.00',
          'impairmentAmount', '100.00', 'reversalAmount', '0.00',
          'closingBookValue', '900.00', 'taxBasis', '1000.00',
          'taxValue', '1000.00', 'evidenceDigest', repeat('a', 64),
          'calculationId', repeat('b', 64)
        ), '${ownerId}'
      );
      commit;
      select (select cost_basis::text from investments.positions
        where id = '${tenantParentPositionId}') || ':' ||
        (select pg_catalog.sum(remaining_cost_basis)::text
          from investments.acquisition_lots
          where position_id = '${tenantParentPositionId}') || ':' ||
        (select pg_catalog.sum(remaining_tax_basis)::text
          from investments.acquisition_lots
          where position_id = '${tenantParentPositionId}') || ':' ||
        (select entry_kind from ledger.entries
          where source_record_id = '${tenantMeasurementId}') || ':' ||
        (select closing_book_value::text
          from investments.year_end_measurements
          where measurement_id = '${tenantMeasurementId}');
    `), "900.000000000000:900.000000000000:1000.000000000000:INVESTMENT_MEASUREMENT:900.000000000000");
    expectTenantMismatch(String.raw`
      set role investments_store_owner;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      insert into investments.measurement_sources (
        measurement_id, company_id, ordinal, role, source_capability,
        source_record_id, source_revision, fact_sha256
      ) values (
        '${tenantMeasurementId}', '${secondCompanyId}', 99, 'valuation',
        'DOCUMENTS', '90000000-0000-0000-0000-000000000010', 1, repeat('c', 64)
      );
    `, "measurement source tenant mismatch");
    psql(containerName, [], String.raw`
      delete from investments.measurement_sources
        where measurement_id = '${tenantMeasurementId}';
      delete from investments.year_end_measurements
        where measurement_id = '${tenantMeasurementId}';
      delete from investments.position_classifications
        where position_id = '${tenantParentPositionId}';
      delete from investments.economic_events where event_id = '${tenantEventId}';
      delete from investments.cash_settlements
        where settlement_id in (
          '${lifecycleDividendSettlementId}', '${lifecycleFundSettlementId}'
        );
      delete from investments.lifecycle_correction_sources
        where correction_id in (
          '${lifecycleFundCorrectionId}', '${lifecycleSettlementCorrectionId}'
        );
      delete from investments.lifecycle_corrections
        where correction_id in (
          '${lifecycleFundCorrectionId}', '${lifecycleSettlementCorrectionId}'
        );
      delete from investments.event_sources
        where event_id in (
          '${lifecycleDividendEventId}', '${lifecycleFundEventId}',
          '${lifecycleFundReplacementEventId}'
        );
      delete from investments.received_dividend_recognitions
        where event_id = '${lifecycleDividendEventId}';
      delete from investments.received_fund_distribution_recognitions
        where event_id in (
          '${lifecycleFundEventId}', '${lifecycleFundReplacementEventId}'
        );
      delete from investments.economic_events
        where event_id in (
          '${lifecycleDividendEventId}', '${lifecycleFundEventId}',
          '${lifecycleFundReplacementEventId}'
        );
      delete from investments.positions where id = '${lifecycleFundPositionId}';
      delete from investments.cash_settlements
        where settlement_id = '${lifecycleReplacementSettlementId}';
      delete from investments.cash_settlements
        where settlement_id = '${lifecycleSaleSettlementId}';
      delete from investments.event_sources
        where event_id = '${lifecycleSaleEventId}';
      delete from investments.share_sale_allocations
        where sale_action_id = '${lifecycleSaleEventId}';
      delete from investments.share_sales
        where action_id = '${lifecycleSaleEventId}';
      delete from investments.economic_events
        where event_id = '${lifecycleSaleEventId}';
      delete from investments.cash_settlements
        where settlement_id = '${lifecycleSettlementId}';
      delete from investments.event_sources
        where event_id = '${lifecycleEventId}';
      delete from investments.position_classifications
        where position_id = (
          select position_id from investments.share_purchase_recognitions
          where event_id = '${lifecycleEventId}'
        );
      delete from investments.share_purchase_recognitions
        where event_id = '${lifecycleEventId}';
      delete from investments.economic_events
        where event_id = '${lifecycleEventId}';
      delete from investments.source_fact_registry
        where company_id = '${companyId}';
      delete from investments.acquisition_lots
        where acquisition_action_id = '${lifecycleEventId}';
      delete from investments.positions
        where company_id = '${companyId}'
          and investment_key = 'lifecycle-private-as';
      delete from investments.company_year_policies
        where company_id in ('${companyId}', '${secondCompanyId}');
      delete from investments.acquisition_lots where id = '${tenantLotId}';
      delete from investments.positions where id = '${tenantParentPositionId}';
      delete from public.company_memberships where company_id = '${secondCompanyId}';
      delete from public.companies where id = '${secondCompanyId}';
    `);

    psql(containerName, [
      "--file", `/repo/supabase/rollback/${investmentsLifecycleCorrectionsMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/rollback/${investmentsIncomeLifecycleMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/rollback/${investmentsShareSaleLifecycleMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/rollback/${investmentsLifecycleWorkflowMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/rollback/${investmentsLifecycleMeasurementMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regclass('investments.economic_events') is null)::text || ':' ||
        (pg_catalog.to_regclass('investments.cash_settlements') is null)::text || ':' ||
        (select data_type from information_schema.columns
          where table_schema = 'investments' and table_name = 'positions'
            and column_name = 'share_count')::text;
    `), "true:true:bigint");

    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regclass('investments.received_fund_distributions') is not null)::text || ':' ||
        (pg_catalog.to_regclass('investments.corrections') is not null)::text || ':' ||
        (select count(*) from pg_catalog.pg_attribute attribute
          where attribute.attrelid = 'investments.positions'::regclass
            and attribute.attname in ('accounting_classification', 'tax_basis')
            and not attribute.attisdropped)::text || ':' ||
        (select count(*) from pg_catalog.pg_attribute attribute
          where attribute.attrelid = 'investments.share_sales'::regclass
            and attribute.attname = 'remaining_tax_basis'
            and attribute.attnotnull
            and not attribute.attisdropped)::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_received_fund_distribution_v1(jsonb,text)',
          'EXECUTE'
        )::text;
    `), "true:true:2:1:true");

    psql(containerName, [
      "--file", `/repo/supabase/rollback/${investmentsCompleteManualEvidenceMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/rollback/${investmentsSupportedPatternsMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regclass('investments.received_fund_distributions') is null)::text || ':' ||
        (pg_catalog.to_regclass('investments.corrections') is null)::text || ':' ||
        (pg_catalog.to_regprocedure(
          'investments.prepare_share_purchase_v1(jsonb,text)'
        ) is not null)::text || ':' ||
        (pg_catalog.to_regprocedure(
          'investments.rollback_190_prepare_share_purchase_v1(jsonb,text)'
        ) is null)::text || ':' ||
        (select count(*) from pg_catalog.pg_attribute attribute
          where attribute.attrelid = 'investments.positions'::regclass
            and attribute.attname in ('accounting_classification', 'tax_basis')
            and not attribute.attisdropped)::text;
    `), "true:true:true:true:0");

    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsSupportedPatternsMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsCompleteManualEvidenceMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsLifecycleMeasurementMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsLifecycleWorkflowMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsShareSaleLifecycleMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsIncomeLifecycleMigration}`,
    ]);
    psql(containerName, [
      "--file", `/repo/supabase/migrations/${investmentsLifecycleCorrectionsMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regclass('investments.received_fund_distributions') is not null)::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_received_fund_distribution_v1(jsonb,text)',
          'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'authenticated',
          'investments.prepare_share_purchase_v1(jsonb,text)',
          'EXECUTE'
        )::text;
    `), "true:true:false");

    const supportedFundPositionId = "30000000-0000-0000-0000-000000000090";
    const supportedFundPurchaseId = "20000000-0000-0000-0000-000000000090";
    const supportedFundSaleId = "20000000-0000-0000-0000-000000000091";
    const supportedFundDistributionId = "20000000-0000-0000-0000-000000000092";
    const correctedFundDistributionId = "20000000-0000-0000-0000-000000000093";
    const fundDistributionCorrectionId = "20000000-0000-0000-0000-000000000094";
    const failedSaleReplacementId = "20000000-0000-0000-0000-000000000095";
    const failedSaleCorrectionId = "20000000-0000-0000-0000-000000000096";
    const evidenceDigest = "a".repeat(64);
    const purchaseCalculationId = "b".repeat(64);
    const saleCalculationId = "c".repeat(64);
    const distributionCalculationId = "d".repeat(64);
    const fundPurchaseRequest = JSON.stringify({
      companyId, incomeYear: 2026, actionId: supportedFundPurchaseId,
      idempotencyKey: "fund-purchase-supported-0001", correlationId: "fund-purchase-supported",
      investmentKey: "NO0000000090", investmentName: "Norsk Kombinasjonsfond",
      investmentKind: "norwegian_equity_fund", accountingClassification: "current_fund",
      taxTreatment: "fritaksmetoden", acquisitionDate: "2026-01-02", shareCount: 10,
      purchaseAmount: "100.00", transactionCosts: "2.50", capitalizedCost: "102.50",
      orgNumber: null, fundEquityRatioBasisPoints: 6000,
      fundTaxStatementReference: "provider-tax-statement-2026-r1",
      evidenceMode: "manual_fallback", evidenceReference: "fund-contract-note-1",
      ownerAttested: true, bankTransactionId: manualEvidenceBankId,
      documentId: manualEvidenceDocumentId,
      documentStatus: "attached", evidenceDigest,
      calculationId: purchaseCalculationId,
    });
    const incompleteManualPurchaseRequest = JSON.stringify({
      ...JSON.parse(fundPurchaseRequest),
      actionId: "20000000-0000-0000-0000-000000000099",
      idempotencyKey: "fund-purchase-incomplete-0001",
      bankTransactionId: null,
      documentId: null,
      documentStatus: "missing_accepted_warning",
    });
    const fundSaleRequest = JSON.stringify({
      companyId, incomeYear: 2026, actionId: supportedFundSaleId,
      idempotencyKey: "fund-sale-supported-0001", correlationId: "fund-sale-supported",
      positionId: supportedFundPositionId, saleDate: "2026-06-01", soldShareCount: 10,
      proceeds: "120.00", transactionCosts: "2.50", netProceeds: "117.50",
      saleYearFundEquityRatioBasisPoints: 8000,
      fundTaxStatementReference: "provider-tax-statement-2026-r2",
      evidenceMode: "manual_fallback", evidenceReference: "fund-sale-note-1",
      ownerAttested: true, bankTransactionId: manualEvidenceBankId,
      documentId: manualEvidenceDocumentId,
      documentStatus: "attached", evidenceDigest,
    });
    const fundDistributionRequest = JSON.stringify({
      companyId, incomeYear: 2026, actionId: supportedFundDistributionId,
      idempotencyKey: "fund-distribution-supported-0001",
      correlationId: "fund-distribution-supported", positionId: supportedFundPositionId,
      fundName: "Norsk Kombinasjonsfond", entitlementDate: "2026-05-01",
      paidDate: "2026-05-15", grossAmount: "100.00",
      openingFundEquityRatioBasisPoints: 5000,
      fundTaxStatementReference: "provider-tax-statement-2026-r3",
      evidenceMode: "manual_fallback", evidenceReference: "fund-distribution-note-1",
      ownerAttested: true, bankTransactionId: manualEvidenceBankId,
      documentId: manualEvidenceDocumentId,
      documentStatus: "attached", evidenceDigest,
    });
    psql(containerName, [], String.raw`
      begin;
      set local role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', true);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', true);

      do $manual_evidence$
      begin
        begin
          perform investments.prepare_share_purchase_v1(
            '${incompleteManualPurchaseRequest}'::jsonb, '${ownerId}'
          );
          raise exception 'incomplete_manual_evidence_was_accepted';
        exception when others then
          if sqlerrm <> 'investments_invalid_input' then raise; end if;
        end;
      end
      $manual_evidence$;

      create temporary table supported_purchase_prepared as
      select investments.prepare_share_purchase_v1(
        '${fundPurchaseRequest}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table supported_purchase_entry as
      select * from ledger.post_entry(
        'fund-purchase-supported-0001', '${companyId}', 2026,
        'SHARE_PURCHASE', 'Fund purchase: Norsk Kombinasjonsfond',
        '[{"account":"1815","description":"Investment in Norsk Kombinasjonsfond","debit":"102.50","credit":"0.00","currency":"NOK"},{"account":"1920","description":"Paid from bank","debit":"0.00","credit":"102.50","currency":"NOK"}]'::jsonb,
        '[]'::jsonb, false, 'INVESTMENTS', '${supportedFundPurchaseId}',
        'fund-purchase-supported', '${ownerId}'
      );
      select investments.complete_share_purchase_v1(
        '${fundPurchaseRequest}'::jsonb,
        (select ledger_entry_id from supported_purchase_entry),
        (select value from supported_purchase_prepared), '${ownerId}'
      );

      create temporary table supported_sale_prepared as
      select investments.prepare_share_sale_v1(
        pg_catalog.jsonb_set(
          '${fundSaleRequest}'::jsonb, '{positionId}',
          (select value -> 'positionId' from supported_purchase_prepared)
        ), '${ownerId}'
      ) as value;
      create temporary table supported_sale_entry as
      select * from ledger.post_entry(
        'fund-sale-supported-0001', '${companyId}', 2026,
        'SHARE_SALE', 'Fund sale: Norsk Kombinasjonsfond',
        '[{"account":"1920","description":"Received in bank","debit":"117.50","credit":"0.00","currency":"NOK"},{"account":"1815","description":"Investment disposed","debit":"0.00","credit":"102.50","currency":"NOK"},{"account":"8071","description":"Investment gain","debit":"0.00","credit":"15.00","currency":"NOK"}]'::jsonb,
        '[]'::jsonb, false, 'INVESTMENTS', '${supportedFundSaleId}',
        'fund-sale-supported', '${ownerId}'
      );
      select investments.complete_share_sale_v1(
        pg_catalog.jsonb_set(
          '${fundSaleRequest}'::jsonb, '{positionId}',
          (select value -> 'positionId' from supported_purchase_prepared)
        ) || pg_catalog.jsonb_build_object(
          'bookGainOrLoss', '15.00', 'taxGainOrLoss', '15.00',
          'exemptGain', '10.50', 'taxableGain', '4.50',
          'nonDeductibleLoss', '0.00', 'deductibleLoss', '0.00',
          'calculationId', '${saleCalculationId}',
          'lotCalculations', pg_catalog.jsonb_build_array(
            pg_catalog.jsonb_build_object(
              'lotId', (select value -> 'lotFacts' -> 0 ->> 'lotId' from supported_sale_prepared),
              'allocationOrder', 1, 'allocatedNetProceeds', '117.50',
              'taxGainOrLoss', '15.00',
              'averageFundEquityRatioBasisPoints', '7000',
              'exemptGain', '10.50', 'taxableGain', '4.50',
              'nonDeductibleLoss', '0.00', 'deductibleLoss', '0.00'
            )
          )
        ),
        (select ledger_entry_id from supported_sale_entry), '${ownerId}'
      );

      create temporary table supported_distribution_prepared as
      select investments.prepare_received_fund_distribution_v1(
        pg_catalog.jsonb_set(
          '${fundDistributionRequest}'::jsonb, '{positionId}',
          (select value -> 'positionId' from supported_purchase_prepared)
        ), '${ownerId}'
      ) as value;
      create temporary table supported_distribution_entry as
      select * from ledger.post_entry(
        'fund-distribution-supported-0001', '${companyId}', 2026,
        'DIVIDEND_RECEIVED', 'Fund distribution: Norsk Kombinasjonsfond',
        '[{"account":"1920","description":"Received in bank","debit":"100.00","credit":"0.00","currency":"NOK"},{"account":"8070","description":"Fund dividend","debit":"0.00","credit":"50.00","currency":"NOK"},{"account":"8050","description":"Fund interest","debit":"0.00","credit":"50.00","currency":"NOK"}]'::jsonb,
        '[]'::jsonb, false, 'INVESTMENTS', '${supportedFundDistributionId}',
        'fund-distribution-supported', '${ownerId}'
      );
      select investments.complete_received_fund_distribution_v1(
        pg_catalog.jsonb_set(
          '${fundDistributionRequest}'::jsonb, '{positionId}',
          (select value -> 'positionId' from supported_purchase_prepared)
        ) || pg_catalog.jsonb_build_object(
          'dividendPortion', '50.00', 'interestPortion', '50.00',
          'taxableAddBack', '1.50', 'totalTaxableIncome', '51.50',
          'calculationId', '${distributionCalculationId}'
        ),
        (select ledger_entry_id from supported_distribution_entry), '${ownerId}'
      );
      commit;
    `);
    const supportedFundPositionActual = scalar(containerName, String.raw`
      select position_id::text from investments.share_purchases
      where action_id = '${supportedFundPurchaseId}';
    `);
    assert.equal(scalar(containerName, String.raw`
      select position.kind || ':' || position.accounting_classification || ':' ||
        position.share_count::text || ':' || position.cost_basis::text || ':' ||
        position.tax_basis::text
      from investments.positions position where position.id = '${supportedFundPositionActual}';
    `), "norwegian_equity_fund:current_fund:0.000000000000:0.000000000000:0.000000000000");
    const fundDistributionReplayRequest = JSON.stringify({
      ...JSON.parse(fundDistributionRequest), positionId: supportedFundPositionActual,
    });
    assert.equal(scalar(containerName, String.raw`
      select sale.book_gain_or_loss::text || ':' || sale.tax_gain_or_loss::text || ':' ||
        sale.exempt_gain::text || ':' || sale.taxable_gain::text || ':' ||
        allocation.average_fund_equity_ratio_basis_points::text
      from investments.share_sales sale
      join investments.share_sale_allocations allocation
        on allocation.sale_action_id = sale.action_id
      where sale.action_id = '${supportedFundSaleId}';
    `), "15.000000000000:15.000000000000:10.500000000000:4.500000000000:7000.00");
    assert.equal(scalar(containerName, String.raw`
      select dividend_portion::text || ':' || interest_portion::text || ':' ||
        taxable_add_back::text || ':' || total_taxable_income::text
      from investments.received_fund_distributions
      where action_id = '${supportedFundDistributionId}';
    `), "50.000000000000:50.000000000000:1.500000000000:51.500000000000");
    assert.equal(scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      select (investments.get_received_fund_distribution_replay_v1(
        '${fundDistributionReplayRequest}'::jsonb, '${ownerId}'
      ) ->> 'replayed')::text;
    `), "true");

    const replacementFundDistribution = {
      companyId, incomeYear: 2026, actionId: correctedFundDistributionId,
      idempotencyKey: "fund-distribution-replacement-0001",
      correlationId: "fund-distribution-replacement",
      positionId: supportedFundPositionActual,
      fundName: "Norsk Kombinasjonsfond", entitlementDate: "2026-05-01",
      paidDate: "2026-05-15", grossAmount: "120.00",
      openingFundEquityRatioBasisPoints: 5000,
      fundTaxStatementReference: "provider-tax-statement-2026-r4",
      evidenceMode: "manual_fallback",
      evidenceReference: "corrected-fund-distribution-note",
      ownerAttested: true, bankTransactionId: manualEvidenceBankId,
      documentId: manualEvidenceDocumentId,
      documentStatus: "attached",
    };
    const replacementFundDistributionRequest = JSON.stringify({
      ...replacementFundDistribution,
      evidenceDigest,
    });
    const fundDistributionCorrectionRequest = JSON.stringify({
      companyId, incomeYear: 2026,
      correctionId: fundDistributionCorrectionId,
      idempotencyKey: "fund-distribution-correction-0001",
      correlationId: "fund-distribution-correction",
      originalActionId: supportedFundDistributionId,
      originalActivityKind: "fund_distribution_received",
      replacementActionId: correctedFundDistributionId,
      replacementActivityKind: "fund_distribution_received",
      correctionDate: "2026-08-31",
      reason: "Correct gross fund distribution amount",
      evidenceMode: "manual_fallback",
      evidenceReference: "fund-distribution-correction-evidence",
      ownerAttested: true, bankTransactionId: manualEvidenceBankId,
      documentId: manualEvidenceDocumentId,
      documentStatus: "attached",
      evidenceDigest,
      replacement: replacementFundDistribution,
    });
    const correctionResult = JSON.parse(scalar(containerName, String.raw`
      begin;
      set local role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', true);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', true);
      create temporary table supported_correction_prepared as
      select investments.prepare_correction_v1(
        '${fundDistributionCorrectionRequest}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table replacement_distribution_prepared as
      select investments.prepare_received_fund_distribution_v1(
        '${replacementFundDistributionRequest}'::jsonb, '${ownerId}'
      ) as value;
      create temporary table replacement_distribution_entry as
      select * from ledger.post_entry(
        'fund-distribution-replacement-0001', '${companyId}', 2026,
        'DIVIDEND_RECEIVED', 'Fund distribution: Norsk Kombinasjonsfond',
        '[{"account":"1920","description":"Received in bank","debit":"120.00","credit":"0.00","currency":"NOK"},{"account":"8070","description":"Fund dividend","debit":"0.00","credit":"60.00","currency":"NOK"},{"account":"8050","description":"Fund interest","debit":"0.00","credit":"60.00","currency":"NOK"}]'::jsonb,
        '[]'::jsonb, false, 'INVESTMENTS', '${correctedFundDistributionId}',
        'fund-distribution-replacement', '${ownerId}'
      );
      select investments.complete_received_fund_distribution_v1(
        '${replacementFundDistributionRequest}'::jsonb || pg_catalog.jsonb_build_object(
          'dividendPortion', '60.00', 'interestPortion', '60.00',
          'taxableAddBack', '1.80', 'totalTaxableIncome', '61.80',
          'calculationId', '${distributionCalculationId}'
        ),
        (select ledger_entry_id from replacement_distribution_entry), '${ownerId}'
      );
      create temporary table supported_correction_link as
      select ledger.link_investment_correction_v1(
        '${companyId}', 2026,
        ((select value from supported_correction_prepared) ->> 'originalAccountingEntryId')::uuid,
        (select ledger_entry_id from replacement_distribution_entry),
        '${supportedFundDistributionId}', '${correctedFundDistributionId}',
        'Correct gross fund distribution amount',
        'fund-distribution-correction', date '2026-08-31', '${ownerId}'
      ) as reversal_entry_id;
      select investments.complete_correction_v1(
        '${fundDistributionCorrectionRequest}'::jsonb,
        ((select value from supported_correction_prepared) ->> 'originalAccountingEntryId')::uuid,
        (select ledger_entry_id from replacement_distribution_entry),
        (select reversal_entry_id from supported_correction_link), '${ownerId}'
      )::text;
      commit;
    `));
    assert.equal(correctionResult.correctionId, fundDistributionCorrectionId);
    assert.equal(correctionResult.originalActionId, supportedFundDistributionId);
    assert.equal(correctionResult.replacementActionId, correctedFundDistributionId);
    assert.equal(scalar(containerName, String.raw`
      with correction_entries as (
        select original_entry_id as entry_id from ledger.entry_corrections
          where original_entry_id = (
            select accounting_entry_id from investments.received_fund_distributions
            where action_id = '${supportedFundDistributionId}'
          )
        union all
        select reversal_entry_id from ledger.entry_corrections
          where original_entry_id = (
            select accounting_entry_id from investments.received_fund_distributions
            where action_id = '${supportedFundDistributionId}'
          )
        union all
        select replacement_entry_id from ledger.entry_corrections
          where original_entry_id = (
            select accounting_entry_id from investments.received_fund_distributions
            where action_id = '${supportedFundDistributionId}'
          )
      ), totals as (
        select line ->> 'account' as account,
          sum((line ->> 'debit')::numeric - (line ->> 'credit')::numeric) as net
        from ledger.entries entry
        join correction_entries selected on selected.entry_id = entry.id
        cross join lateral pg_catalog.jsonb_array_elements(entry.lines) line
        group by line ->> 'account'
      )
      select pg_catalog.string_agg(account || ':' || net::text, ',' order by account)
      from totals;
    `), "1920:120.00,8050:-60.00,8070:-60.00");
    assert.equal(scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', false);
      select (investments.get_correction_replay_v1(
        '${fundDistributionCorrectionRequest}'::jsonb, '${ownerId}'
      ) ->> 'replayed')::text;
    `), "true");

    const failedSaleCorrectionRequest = JSON.stringify({
      companyId, incomeYear: 2026, correctionId: failedSaleCorrectionId,
      idempotencyKey: "failed-sale-correction-0001",
      correlationId: "failed-sale-correction",
      originalActionId: supportedFundSaleId,
      originalActivityKind: "share_sale",
      replacementActionId: failedSaleReplacementId,
      replacementActivityKind: "share_sale",
      correctionDate: "2026-08-31", reason: "Deliberate rollback rehearsal",
      evidenceMode: "manual_fallback", evidenceReference: "rollback-evidence",
      ownerAttested: true, bankTransactionId: manualEvidenceBankId,
      documentId: manualEvidenceDocumentId,
      documentStatus: "attached", evidenceDigest,
      replacement: { actionId: failedSaleReplacementId },
    });
    assert.equal(scalar(containerName, String.raw`
      begin;
      set local role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', true);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}","aal":"aal2"}', true);
      do $forced_failure$
      begin
        begin
          perform investments.prepare_correction_v1(
            '${failedSaleCorrectionRequest}'::jsonb, '${ownerId}'
          );
          raise exception 'forced_correction_failure';
        exception when others then
          if sqlerrm <> 'forced_correction_failure' then raise; end if;
        end;
      end
      $forced_failure$;
      commit;
      select position.share_count::text || ':' || position.cost_basis::text || ':' ||
        position.tax_basis::text || ':' || lot.remaining_share_count::text || ':' ||
        lot.remaining_cost_basis::text || ':' ||
        (select count(*) from investments.corrections
          where correction_id = '${failedSaleCorrectionId}')::text
      from investments.positions position
      join investments.acquisition_lots lot on lot.position_id = position.id
      where position.id = '${supportedFundPositionActual}';
    `), "0.000000000000:0.000000000000:0.000000000000:0.000000000000:0.000000000000:0");
    assert.equal(scalar(containerName, String.raw`
      set role investments_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${outsiderId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${outsiderId}","aal":"aal2"}', false);
      select
        (select count(*) from investments.received_fund_distributions)::text || ':' ||
        (select count(*) from investments.corrections)::text;
    `), "0:0");

    const refusedRollback = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test", "--file",
      `/repo/supabase/rollback/${investmentsSupportedPatternsMigration}`,
    ]);
    assert.notEqual(refusedRollback.status, 0, "rollback must fail closed after #190 data exists");
    assert.match(
      `${refusedRollback.stdout}\n${refusedRollback.stderr}`,
      /investments_supported_patterns_rollback_has_new_data/u,
    );
    assert.equal(scalar(containerName, String.raw`
      select (select count(*) from investments.received_fund_distributions)::text || ':' ||
        (select count(*) from investments.corrections)::text;
    `), "2:1");

    psql(containerName, [
      "--file",
      `/repo/supabase/contract-migrations/${investmentsLifecyclePublicCutoverMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_share_purchase_v1(jsonb,text)',
          'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_share_sale_v1(jsonb,text)',
          'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_received_dividend_v1(jsonb,text)',
          'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_received_fund_distribution_v1(jsonb,text)',
          'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_correction_v1(jsonb,text)',
          'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_share_purchase_recognition_v2(jsonb,text)',
          'EXECUTE'
        )::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'investments.prepare_cash_settlement_v2(jsonb,text)',
          'EXECUTE'
        )::text || ':' ||
        (pg_catalog.to_regprocedure(
          'ledger.link_investment_correction_v1(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)'
        ) is null)::text || ':' ||
        (pg_catalog.to_regprocedure(
          'ledger.link_investment_lifecycle_correction_v2(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)'
        ) is not null)::text || ':' ||
        pg_catalog.has_function_privilege(
          'investments_workflow_executor',
          'ledger.link_investment_lifecycle_correction_v2(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)',
          'EXECUTE'
        )::text || ':' ||
        exists (
          select 1 from pg_catalog.pg_constraint constraint_record
          join pg_catalog.pg_namespace namespace
            on namespace.oid = constraint_record.connamespace
          where namespace.nspname = 'investments'
            and constraint_record.conname = 'cash_settlements_bank_fact_key'
            and constraint_record.contype = 'u'
        )::text || ':' ||
        exists (
          select 1 from pg_catalog.pg_constraint constraint_record
          join pg_catalog.pg_namespace namespace
            on namespace.oid = constraint_record.connamespace
          where namespace.nspname = 'investments'
            and constraint_record.conname =
              'cash_settlements_bank_fact_revision_check'
            and constraint_record.contype = 'c'
        )::text;
    `), "false:false:false:false:false:true:true:true:true:true:true:true");
    const refusedCallerBankRevision = docker([
      "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
      "-U", "postgres", "-d", "talli_test",
    ], { input: String.raw`
      select investments.cash_settlement_fingerprint_v2(
        pg_catalog.jsonb_set(
          '${lifecycleSaleSettlementRequest}'::jsonb,
          '{bankFact,revision}', '2'::jsonb
        )
      );
    ` });
    assert.notEqual(refusedCallerBankRevision.status, 0);
    assert.match(
      `${refusedCallerBankRevision.stdout}\n${refusedCallerBankRevision.stderr}`,
      /investments_invalid_input/u,
    );
    psql(containerName, [
      "--file",
      `/repo/supabase/rollback/${investmentsLifecyclePublicCutoverMigration}`,
    ]);
    psql(containerName, [
      "--file",
      `/repo/supabase/rollback/${investmentsLifecyclePublicCutoverMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select pg_catalog.has_function_privilege(
        'investments_workflow_executor',
        'investments.prepare_share_purchase_v1(jsonb,text)',
        'EXECUTE'
      )::text || ':' ||
      (pg_catalog.to_regprocedure(
        'ledger.link_investment_correction_v1(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)'
      ) is not null)::text || ':' ||
      (pg_catalog.to_regprocedure(
        'ledger.link_investment_lifecycle_correction_v2(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)'
      ) is null)::text || ':' ||
      exists (
        select 1 from pg_catalog.pg_constraint constraint_record
        join pg_catalog.pg_namespace namespace
          on namespace.oid = constraint_record.connamespace
        where namespace.nspname = 'investments'
          and constraint_record.conname = 'cash_settlements_bank_fact_key'
          and constraint_record.contype = 'u'
      )::text || ':' ||
      exists (
        select 1 from pg_catalog.pg_constraint constraint_record
        join pg_catalog.pg_namespace namespace
          on namespace.oid = constraint_record.connamespace
        where namespace.nspname = 'investments'
          and constraint_record.conname =
            'cash_settlements_bank_fact_revision_check'
          and constraint_record.contype = 'c'
      )::text;
    `), "true:true:true:true:true");
    psql(containerName, [
      "--file",
      `/repo/supabase/contract-migrations/${investmentsLifecyclePublicCutoverMigration}`,
    ]);
    assert.equal(scalar(containerName, String.raw`
      select pg_catalog.has_function_privilege(
        'investments_workflow_executor',
        'investments.prepare_share_purchase_v1(jsonb,text)',
        'EXECUTE'
      )::text || ':' ||
      (pg_catalog.to_regprocedure(
        'ledger.link_investment_correction_v1(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)'
      ) is null)::text || ':' ||
      pg_catalog.has_function_privilege(
        'investments_workflow_executor',
        'ledger.link_investment_lifecycle_correction_v2(uuid,integer,uuid,uuid,uuid,uuid,text,text,date,text)',
        'EXECUTE'
      )::text || ':' ||
      exists (
        select 1 from pg_catalog.pg_constraint constraint_record
        join pg_catalog.pg_namespace namespace
          on namespace.oid = constraint_record.connamespace
        where namespace.nspname = 'investments'
          and constraint_record.conname = 'cash_settlements_bank_fact_key'
          and constraint_record.contype = 'u'
      )::text || ':' ||
      exists (
        select 1 from pg_catalog.pg_constraint constraint_record
        join pg_catalog.pg_namespace namespace
          on namespace.oid = constraint_record.connamespace
        where namespace.nspname = 'investments'
          and constraint_record.conname =
            'cash_settlements_bank_fact_revision_check'
          and constraint_record.contype = 'c'
      )::text;
    `), "false:true:true:true:true");
  } finally {
    docker(["rm", "--force", containerName]);
  }
});
