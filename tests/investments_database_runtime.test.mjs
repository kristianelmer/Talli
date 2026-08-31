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
const investmentsContractMigration = "20260831133000_investments_share_purchase_contract.sql";
const investmentsRollbackMigration = "20260831133000_investments_share_purchase_contract.sql";
const investmentsSaleContractMigration = "20260831170000_investments_share_sale_contract.sql";
const investmentsSaleRollbackMigration = "20260831170000_investments_share_sale_contract.sql";
const ownerId = "00000000-0000-0000-0000-000000000011";
const outsiderId = "00000000-0000-0000-0000-000000000022";
const companyId = "10000000-0000-0000-0000-000000000001";
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

    assert.equal(scalar(containerName, String.raw`
      select
        (pg_catalog.to_regclass('investments.positions') is not null)::text || ':' ||
        (pg_catalog.to_regclass('investments.acquisition_lots') is not null)::text || ':' ||
        (pg_catalog.to_regclass('investments.share_purchases') is not null)::text || ':' ||
        (pg_catalog.to_regprocedure('investments.prepare_share_purchase_v1(jsonb,text)') is not null)::text || ':' ||
        (select rolbypassrls::text from pg_catalog.pg_roles where rolname = 'investments_executor') || ':' ||
        (select relrowsecurity::text || ':' || relforcerowsecurity::text
         from pg_catalog.pg_class where oid = 'investments.positions'::regclass) || ':' ||
        pg_catalog.has_schema_privilege('authenticated', 'investments', 'usage')::text || ':' ||
        pg_catalog.has_table_privilege('service_role', 'investments.positions', 'select')::text;
    `), "true:true:true:true:false:true:true:false:false");
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
  } finally {
    docker(["rm", "--force", containerName]);
  }
});
