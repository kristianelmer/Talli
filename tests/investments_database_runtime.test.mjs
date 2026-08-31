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
const ownerId = "00000000-0000-0000-0000-000000000011";
const outsiderId = "00000000-0000-0000-0000-000000000022";
const companyId = "10000000-0000-0000-0000-000000000001";
const actionId = "20000000-0000-0000-0000-000000000002";
const positionId = "30000000-0000-0000-0000-000000000003";
const lotId = "40000000-0000-0000-0000-000000000004";
const newActionId = "20000000-0000-0000-0000-000000000012";
const newEntryId = "70000000-0000-0000-0000-000000000017";
const rollbackActionId = "20000000-0000-0000-0000-000000000013";

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
      ![investmentsMigration, investmentsWorkflowMigration].includes(name))) {
      psql(containerName, ["--file", `/repo/supabase/migrations/${migration}`]);
    }
    psql(containerName, [], String.raw`
      insert into auth.users (id, email) values
        ('${ownerId}', 'owner@example.test'),
        ('${outsiderId}', 'outsider@example.test');
      insert into public.companies (
        id, org_number, name, entity_type, address, postal_code, city,
        status_text, source, created_by
      ) values (
        '${companyId}', '314159265', 'Investments AS', 'AS', 'One', '0150',
        'Oslo', 'Active', 'test', '${ownerId}'
      );
      insert into public.company_memberships (company_id, user_id, role, accepted_at)
      values ('${companyId}', '${ownerId}', 'owner', pg_catalog.now());
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
        '{"investment_key":"example-as","investment_name":"Example AS","share_count":10,"purchase_amount":125.50,"position_id":"${positionId}","acquisition_lot_id":"${lotId}"}'::jsonb,
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
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}"}', false);
      select count(*) from investments.positions;
    `), "1");
    assert.equal(scalar(containerName, String.raw`
      set role investments_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${outsiderId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${outsiderId}"}', false);
      select count(*) from investments.positions;
    `), "0");

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
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}"}', false);
      with prepared as (
        select investments.prepare_share_purchase_v1(
          '${purchaseRequest}'::jsonb, '${ownerId}'
        ) as value
      )
      select investments.complete_share_purchase_v1(
        '${purchaseRequest}'::jsonb, '${newEntryId}', prepared.value, '${ownerId}'
      )::text from prepared;
    `);
    assert.equal(JSON.parse(completed).accountingEntryId, newEntryId);
    assert.equal(scalar(containerName, String.raw`
      set role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}"}', false);
      select investments.get_share_purchase_replay_v1(
        '${purchaseRequest}'::jsonb, '${ownerId}'
      ) ->> 'replayed';
    `), "true");
    assert.equal(scalar(containerName, String.raw`
      set role investments_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', false);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}"}', false);
      select purchase.share_count::text || ':' || purchase.purchase_amount::text || ':' ||
        position.share_count::text || ':' || position.cost_basis::text || ':' ||
        lot.original_share_count::text || ':' || lot.original_cost_basis::text
      from investments.share_purchases purchase
      join investments.positions position on position.id = purchase.position_id
      join investments.acquisition_lots lot on lot.id = purchase.acquisition_lot_id
      where purchase.action_id = '${newActionId}';
    `), "25:500.00:25:500.00:25:500.00");

    const rollbackRequest = JSON.stringify({
      ...JSON.parse(purchaseRequest), actionId: rollbackActionId,
      idempotencyKey: "purchase-command-0002", investmentKey: "rollback-as",
      investmentName: "Rollback AS", orgNumber: null,
    });
    psql(containerName, [], String.raw`
      begin;
      set local role investments_workflow_executor;
      select pg_catalog.set_config('talli.verified_actor_id', '${ownerId}', true);
      select pg_catalog.set_config('talli.verified_actor_claims', '{"sub":"${ownerId}"}', true);
      select investments.prepare_share_purchase_v1(
        '${rollbackRequest}'::jsonb, '${ownerId}'
      );
      rollback;
    `);
    assert.equal(scalar(containerName, String.raw`
      select count(*) from investments.share_purchases
      where action_id = '${rollbackActionId}';
    `), "0");
    assert.equal(scalar(containerName, String.raw`
      select count(*) from investments.positions
      where company_id = '${companyId}' and investment_key = 'rollback-as';
    `), "0");

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
  } finally {
    docker(["rm", "--force", containerName]);
  }
});
