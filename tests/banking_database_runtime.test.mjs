import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import test from "node:test";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const contractPath = "/repo/supabase/contract-migrations/20260828101000_banking_capability_contract.sql";
const rollbackPath = "/repo/supabase/rollback/20260828101000_banking_capability_contract.sql";
const workflowPath = "/repo/supabase/migrations/20260828100500_banking_workflows.sql";
const ledgerContractPath = "/repo/supabase/contract-migrations/20260827101000_ledger_capability_contract.sql";
const dockerHost = process.env.TALLI_DOCKER_HOST;

const ownerId = "00000000-0000-0000-0000-000000000011";
const outsiderId = "00000000-0000-0000-0000-000000000022";
const companyId = "10000000-0000-0000-0000-000000000001";
const transactionId = "20000000-0000-0000-0000-000000000001";
const entryId = "30000000-0000-0000-0000-000000000001";
const acceptanceId = "40000000-0000-0000-0000-000000000001";
const canonicalTransactionId = "30000000-0000-0000-0000-000000000002";
const canonicalAcceptanceId = "40000000-0000-0000-0000-000000000002";
const canonicalEntryId = "50000000-0000-0000-0000-000000000002";

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

function psqlFailure(containerName, input) {
  return docker([
    "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
    "-U", "postgres", "-d", "talli_test",
  ], { input });
}

function scalar(containerName, sql) {
  return psql(containerName, ["-Atq"], sql).trim().split("\n").at(-1);
}

test("banking authority survives reconciliation, contract, rollback, security, and recutover", { timeout: 240_000 }, () => {
  assert.equal(docker(["info", "--format", "{{.ServerVersion}}"]).status, 0,
    "Docker is required for the mandatory banking PostgreSQL rehearsal");
  const containerName = `talli-banking-${process.pid}-${randomUUID().slice(0, 8)}`;

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
    for (const migration of migrations) {
      psql(containerName, ["--file", `/repo/supabase/migrations/${migration}`]);
    }
    psql(containerName, ["--file", ledgerContractPath]);

    psql(containerName, [], String.raw`
      insert into auth.users (id, email) values
        ('${ownerId}', 'owner@example.test'),
        ('${outsiderId}', 'outsider@example.test');
      insert into public.companies (
        id, org_number, name, entity_type, address, postal_code, city,
        status_text, source, created_by
      ) values (
        '${companyId}', '314159265', 'Banking AS', 'AS', 'One', '0150',
        'Oslo', 'Active', 'test', '${ownerId}'
      );
      insert into public.company_memberships (company_id, user_id, role, accepted_at)
      values ('${companyId}', '${ownerId}', 'owner', now());
      select set_config('request.jwt.claim.sub', '${ownerId}', false);
      select set_config(
        'request.jwt.claims',
        '{"sub":"${ownerId}","aal":"aal2"}',
        false
      );
      alter table ledger.entries disable trigger ledger_entries_enforce_boundary;
      insert into ledger.entries (
        id, company_id, income_year, entry_kind, memo, lines, risk_flags,
        created_by, source_capability, source_record_id, correlation_id
      ) values (
        '${entryId}', '${companyId}', 2026, 'BANK_RULE_SUGGESTION',
        'Accepted banking suggestion',
        '[{"account":"7770","debit":"25.00","credit":"0.00"},{"account":"1920","debit":"0.00","credit":"25.00"}]'::jsonb,
        '[]'::jsonb, '${ownerId}', 'BANKING', '${acceptanceId}',
        'banking-runtime-rehearsal'
      );
      alter table ledger.entries enable trigger ledger_entries_enforce_boundary;
      alter table banking.transactions no force row level security;
      alter table banking.suggestion_acceptances no force row level security;
      insert into public.bank_transactions (
        id, company_id, income_year, transaction_date, text, amount, balance,
        source_hash, matched_entry_id, created_by
      ) values (
        '${transactionId}', '${companyId}', 2026, '2026-02-01', 'Bank fee',
        -25.00, 1000.00, repeat('a', 64), '${entryId}', '${ownerId}'
      );
      insert into public.bank_suggestion_acceptances (
        id, company_id, bank_transaction_id, ledger_entry_id, rule_id,
        rule_version, reason, lines, accepted_by
      ) values (
        '${acceptanceId}', '${companyId}', '${transactionId}', '${entryId}',
        'bank_fee', '2026-07-13.1', 'Matched bank fee',
        '[{"account":"7770","debit":"25.00","credit":"0.00"},{"account":"1920","debit":"0.00","credit":"25.00"}]'::jsonb,
        '${ownerId}'
      );
      alter table banking.transactions force row level security;
      alter table banking.suggestion_acceptances force row level security;
    `);

    psql(containerName, [], String.raw`
      alter table ledger.entries disable trigger ledger_entries_enforce_boundary;
      insert into ledger.entries (
        id, company_id, income_year, entry_kind, memo, lines, risk_flags,
        created_by, source_capability, source_record_id, correlation_id
      ) values (
        '${canonicalEntryId}', '${companyId}', 2026, 'BANK_RULE_SUGGESTION',
        'Canonical acceptance during overlap',
        '[{"account":"7770","debit":"30.00","credit":"0.00"},{"account":"1920","debit":"0.00","credit":"30.00"}]'::jsonb,
        '[]'::jsonb, '${ownerId}', 'BANKING', '${canonicalAcceptanceId}',
        'banking-canonical-overlap-rehearsal'
      );
      alter table ledger.entries enable trigger ledger_entries_enforce_boundary;
      alter table banking.transactions no force row level security;
      alter table banking.suggestion_acceptances no force row level security;
      set role banking_store_owner;
      select set_config('request.jwt.claim.sub', '${ownerId}', false);
      select set_config(
        'request.jwt.claims',
        '{"sub":"${ownerId}","aal":"aal2"}',
        false
      );
      insert into banking.transactions (
        id, company_id, income_year, transaction_date, text, amount, balance,
        source_hash, matched_accounting_entry_id, created_by
      ) values (
        '${canonicalTransactionId}', '${companyId}', 2026, '2026-02-02',
        'Canonical bank fee', -30.00, 970.00, repeat('b', 64),
        '${canonicalEntryId}', '${ownerId}'
      );
      insert into banking.suggestion_acceptances (
        id, company_id, bank_transaction_id, accounting_entry_id,
        suggestion_kind, rule_version, reason, accepted_by
      ) values (
        '${canonicalAcceptanceId}', '${companyId}', '${canonicalTransactionId}',
        '${canonicalEntryId}', 'BANK_FEE', '2026-07-13.1',
        'Canonical matched bank fee', '${ownerId}'
      );
      reset role;
      alter table banking.transactions force row level security;
      alter table banking.suggestion_acceptances force row level security;
    `);
    assert.equal(scalar(containerName, String.raw`
      select (select count(*) from public.bank_transactions) || ':' ||
        (select count(*) from banking.transactions) || ':' ||
        (select count(*) from public.bank_suggestion_acceptances) || ':' ||
        (select count(*) from banking.suggestion_acceptances);
    `), "2:2:2:2");

    psql(containerName, [], String.raw`
      alter table banking.transactions disable trigger banking_transactions_sync_to_legacy;
      update banking.transactions set text = 'Diverged' where id = '${transactionId}';
      alter table banking.transactions enable trigger banking_transactions_sync_to_legacy;
    `);
    const failedContract = psqlFailure(containerName, `\\i ${contractPath}\n`);
    assert.notEqual(failedContract.status, 0);
    assert.match(failedContract.stderr, /banking_contract_transaction_reconciliation_failed/u);
    assert.equal(scalar(containerName, "select relkind from pg_class where oid='public.bank_transactions'::regclass;"), "r");
    psql(containerName, [], String.raw`
      alter table banking.transactions disable trigger banking_transactions_sync_to_legacy;
      update banking.transactions set text = 'Bank fee' where id = '${transactionId}';
      alter table banking.transactions enable trigger banking_transactions_sync_to_legacy;
    `);

    const evidenceRows = scalar(containerName,
      "select count(*) from backend_system.banking_migration_reconciliations;");
    psql(containerName, ["--file", contractPath]);
    assert.equal(scalar(containerName, String.raw`
      select
        (select relkind::text from pg_class where oid='public.bank_transactions'::regclass) || ':' ||
        (select relkind::text from pg_class where oid='public.bank_suggestion_acceptances'::regclass) || ':' ||
        (pg_catalog.to_regprocedure('public.accept_bank_transaction_suggestion(uuid,text,text)') is null)::text || ':' ||
        (pg_catalog.to_regprocedure('backend_system.prepare_bank_transaction_suggestion_v1(jsonb,text)') is null)::text || ':' ||
        (select count(*) from banking.transactions) || ':' ||
        (select count(*) from banking.suggestion_acceptances);
    `), "v:v:true:true:2:2");
    assert.equal(scalar(containerName, String.raw`
      select count(*) from pg_constraint constraint_record
      where constraint_record.conname = 'holding_actions_bank_transaction_id_fkey'
        and constraint_record.confrelid = 'banking.transactions'::regclass;
    `), "1");
    assert.equal(scalar(containerName, String.raw`
      select count(*) from pg_trigger trigger_record
      where trigger_record.tgname = 'company_archive_track_bank_suggestion_acceptances'
        and trigger_record.tgrelid = 'banking.suggestion_acceptances'::regclass
        and not trigger_record.tgisinternal;
    `), "1");

    assert.equal(scalar(containerName, String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '${ownerId}', false);
      select set_config('request.jwt.claims', '{"sub":"${ownerId}"}', false);
      select count(*) from public.bank_suggestion_acceptances;
    `), "2");
    assert.equal(scalar(containerName, String.raw`
      set role authenticated;
      select set_config('request.jwt.claim.sub', '${outsiderId}', false);
      select set_config('request.jwt.claims', '{"sub":"${outsiderId}"}', false);
      select count(*) from public.bank_suggestion_acceptances;
    `), "0");
    const forbiddenLegacyRead = psqlFailure(containerName, String.raw`
      set role authenticated;
      select * from public.bank_transactions;
    `);
    assert.notEqual(forbiddenLegacyRead.status, 0);
    assert.match(forbiddenLegacyRead.stderr, /permission denied/u);

    psql(containerName, ["--file", rollbackPath]);
    assert.equal(scalar(containerName, String.raw`
      select
        (select relkind::text from pg_class where oid='public.bank_transactions'::regclass) || ':' ||
        (select relkind::text from pg_class where oid='public.bank_suggestion_acceptances'::regclass) || ':' ||
        (pg_catalog.to_regprocedure('backend_system.prepare_bank_transaction_suggestion_v1(jsonb,text)') is not null)::text || ':' ||
        (select count(*) from public.bank_transactions) || ':' ||
        (select count(*) from public.bank_suggestion_acceptances);
    `), "r:r:true:2:2");
    assert.equal(scalar(containerName, String.raw`
      select
        has_function_privilege('banking_executor', 'banking.import_statement_v1(jsonb,text)', 'EXECUTE')::text || ':' ||
        has_function_privilege('ledger_workflow_executor', 'backend_system.prepare_bank_transaction_suggestion_v1(jsonb,text)', 'EXECUTE')::text;
    `), "false:true");

    psql(containerName, ["--file", workflowPath]);
    psql(containerName, ["--file", contractPath]);
    assert.equal(scalar(containerName, String.raw`
      select
        (select relkind::text from pg_class where oid='public.bank_transactions'::regclass) || ':' ||
        (select count(*) from banking.transactions) || ':' ||
        (select count(*) from banking.suggestion_acceptances) || ':' ||
        (select count(*) from backend_system.banking_migration_reconciliations);
    `), `v:2:2:${evidenceRows}`);
  } finally {
    docker(["rm", "-f", containerName]);
  }
});
