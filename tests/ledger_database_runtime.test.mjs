import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import test from "node:test";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const expandPath = "/repo/supabase/migrations/20260827100000_ledger_capability.sql";
const contractPath = "/repo/supabase/contract-migrations/20260827101000_ledger_capability_contract.sql";
const rollbackPath = "/repo/supabase/rollback/20260827101000_ledger_capability_contract.sql";
const predecessorMigrations = [
  "0001_authenticated_workspace.sql",
  "0002_fifo_investment_lots.sql",
  "0003_bank_rule_suggestions.sql",
  "0004_corporate_document_artifacts.sql",
];

const ownerId = "00000000-0000-0000-0000-000000000011";
const reviewerId = "00000000-0000-0000-0000-000000000022";
const readOnlyId = "00000000-0000-0000-0000-000000000033";
const outsiderId = "00000000-0000-0000-0000-000000000044";
const otherOwnerId = "00000000-0000-0000-0000-000000000055";
const companyId = "10000000-0000-0000-0000-000000000001";
const otherCompanyId = "20000000-0000-0000-0000-000000000002";
const malformedLegacyEntryId = "40000000-0000-0000-0000-000000000002";

const futurePostingRoutines = [
  "accept_bank_transaction_suggestion",
  "record_share_purchase_fifo",
  "record_share_sale_fifo",
  "finalize_corporate_decision",
  "record_owner_dividend_payment",
];

const bootstrapSql = String.raw`
create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;
create schema auth;
create table auth.users (id uuid primary key, email text);
create or replace function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$;
create or replace function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb, '{}'::jsonb);
$$;
grant usage on schema auth to authenticated, anon, service_role;
revoke all on function auth.uid(), auth.jwt() from public;
grant execute on function auth.uid(), auth.jwt() to authenticated, anon, service_role;
create schema storage;
create table storage.buckets (
  id text primary key,
  name text not null,
  public boolean not null default false,
  file_size_limit bigint,
  allowed_mime_types text[]
);
create table storage.objects (
  id uuid primary key default gen_random_uuid(),
  bucket_id text not null references storage.buckets(id),
  name text not null,
  owner uuid,
  created_at timestamptz not null default now(),
  unique (bucket_id, name)
);
create or replace function storage.foldername(name text) returns text[] language sql immutable as $$
  select string_to_array(name, '/');
$$;
grant usage on schema storage to authenticated, anon, service_role;
grant select, insert on storage.objects to authenticated;
`;

const predecessorCompanyAccessSql = String.raw`
create role company_access_executor nologin noinherit nobypassrls;
create table public.company_eligibility_assessments (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete restrict,
  accounting_year integer not null,
  decision text not null,
  consequential_operations_allowed boolean not null,
  capability_manifest_version text not null,
  capability_manifest_sha256 text not null,
  assessed_at timestamptz not null,
  unique (id, company_id, accounting_year)
);
create table public.company_year_admissions (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete restrict,
  accounting_year integer not null,
  eligibility_assessment_id uuid not null,
  capability_manifest_version text not null,
  capability_manifest_sha256 text not null,
  unique (company_id, accounting_year),
  unique (id, company_id, accounting_year),
  foreign key (eligibility_assessment_id, company_id, accounting_year)
    references public.company_eligibility_assessments(id, company_id, accounting_year)
    on delete restrict
);
create table public.company_year_acceptances (
  id uuid primary key,
  company_year_admission_id uuid not null unique,
  company_id uuid not null references public.companies(id) on delete restrict,
  accounting_year integer not null,
  capability_manifest_version text not null,
  capability_manifest_sha256 text not null,
  foreign key (company_year_admission_id, company_id, accounting_year)
    references public.company_year_admissions(id, company_id, accounting_year)
    on delete restrict
);
grant select on public.company_eligibility_assessments,
  public.company_year_admissions, public.company_year_acceptances,
  public.company_memberships
to company_access_executor;
create policy "company access fixture reads memberships"
on public.company_memberships for select to company_access_executor
using (true);

create or replace function public.company_access_auth_uid_v1()
returns uuid
language sql
stable
security definer
set search_path = ''
as $function$
  select nullif(pg_catalog.current_setting('talli.verified_actor_id', true), '')::uuid;
$function$;

create or replace function public.company_access_auth_jwt_v1()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $function$
  select coalesce(
    nullif(pg_catalog.current_setting('talli.verified_actor_claims', true), '')::jsonb,
    '{}'::jsonb
  );
$function$;

create or replace function public.company_access_has_current_agreement_v1(
  p_company_id uuid
)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select p_company_id is not null;
$function$;

create or replace function public.company_access_is_accepted_owner_v1(p_company_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1
    from public.company_memberships membership
    where membership.company_id = p_company_id
      and membership.user_id = public.company_access_auth_uid_v1()
      and membership.role = 'owner'
      and membership.accepted_at is not null
  );
$function$;

create or replace function public.company_access_is_accepted_member_v1(p_company_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select exists (
    select 1
    from public.company_memberships membership
    where membership.company_id = p_company_id
      and membership.user_id = public.company_access_auth_uid_v1()
      and membership.accepted_at is not null
  );
$function$;

alter function public.company_access_auth_uid_v1()
  owner to company_access_executor;
alter function public.company_access_auth_jwt_v1()
  owner to company_access_executor;
alter function public.company_access_has_current_agreement_v1(uuid)
  owner to company_access_executor;
alter function public.company_access_is_accepted_owner_v1(uuid)
  owner to company_access_executor;
alter function public.company_access_is_accepted_member_v1(uuid)
  owner to company_access_executor;

revoke all on function public.company_access_auth_uid_v1(),
  public.company_access_auth_jwt_v1(),
  public.company_access_has_current_agreement_v1(uuid),
  public.company_access_is_accepted_owner_v1(uuid),
  public.company_access_is_accepted_member_v1(uuid)
from public, anon, authenticated, service_role;
`;

const seedSql = String.raw`
insert into auth.users (id, email) values
  ('${ownerId}', 'owner@example.test'),
  ('${reviewerId}', 'reviewer@example.test'),
  ('${readOnlyId}', 'read-only@example.test'),
  ('${outsiderId}', 'outsider@example.test'),
  ('${otherOwnerId}', 'other-owner@example.test');

insert into public.companies (
  id, org_number, name, entity_type, address, postal_code, city,
  status_text, source, created_by, identity_confirmed_at, identity_locked_at
) values
  ('${companyId}', '314159265', 'Ledger Holding AS', 'AS', 'Testveien 1',
   '0150', 'OSLO', 'aktiv', 'brreg', '${ownerId}', now(), now()),
  ('${otherCompanyId}', '271828182', 'Other Holding AS', 'AS', 'Testveien 2',
   '5003', 'BERGEN', 'aktiv', 'brreg', '${otherOwnerId}', now(), now());

insert into public.company_memberships (company_id, user_id, role, accepted_at) values
  ('${companyId}', '${ownerId}', 'owner', now()),
  ('${companyId}', '${reviewerId}', 'reviewer', now()),
  ('${companyId}', '${readOnlyId}', 'read_only', now()),
  ('${otherCompanyId}', '${otherOwnerId}', 'owner', now());

insert into public.company_eligibility_assessments (
  id, company_id, accounting_year, decision, consequential_operations_allowed,
  capability_manifest_version, capability_manifest_sha256, assessed_at
) values (
  '70000000-0000-0000-0000-000000000001', '${companyId}', 2026,
  'supported', true, '2026.1',
  '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de',
  timestamptz '2026-01-01 08:00:00+00'
), (
  '70000000-0000-0000-0000-000000000002', '${companyId}', 2027,
  'supported', true, '2026.1',
  '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de',
  timestamptz '2026-01-01 08:00:00+00'
), (
  '70000000-0000-0000-0000-000000000003', '${companyId}', 2029,
  'supported', true, '2026.1',
  '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de',
  timestamptz '2026-01-01 08:00:00+00'
);
insert into public.company_year_admissions (
  id, company_id, accounting_year, eligibility_assessment_id,
  capability_manifest_version, capability_manifest_sha256
) values (
  '71000000-0000-0000-0000-000000000001', '${companyId}', 2026,
  '70000000-0000-0000-0000-000000000001', '2026.1',
  '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de'
), (
  '71000000-0000-0000-0000-000000000002', '${companyId}', 2027,
  '70000000-0000-0000-0000-000000000002', '2026.1',
  '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de'
), (
  '71000000-0000-0000-0000-000000000003', '${companyId}', 2029,
  '70000000-0000-0000-0000-000000000003', '2026.1',
  '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de'
);
insert into public.company_year_acceptances (
  id, company_year_admission_id, company_id, accounting_year,
  capability_manifest_version, capability_manifest_sha256
) values (
  '72000000-0000-0000-0000-000000000001',
  '71000000-0000-0000-0000-000000000001', '${companyId}', 2026,
  '2026.1',
  '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de'
), (
  '72000000-0000-0000-0000-000000000002',
  '71000000-0000-0000-0000-000000000002', '${companyId}', 2027,
  '2026.1',
  '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de'
), (
  '72000000-0000-0000-0000-000000000003',
  '71000000-0000-0000-0000-000000000003', '${companyId}', 2029,
  '2026.1',
  '9f91a66d0e2cb560d880b6b290c707bc45a8d117a4175780c75e2d1ccdb694de'
);

insert into public.opening_balance_setups (
  id, company_id, income_year, bank_balance, share_capital,
  share_count, nominal_value, locked_at, created_by, created_at
) values (
  '30000000-0000-0000-0000-000000000001', '${companyId}', 2026,
  30000.00, 30000.00, 100, 300.00,
  timestamptz '2026-01-01 09:00:00+00', '${ownerId}',
  timestamptz '2026-01-01 09:00:00+00'
);

insert into public.ledger_entries (
  id, company_id, setup_id, income_year, entry_type, memo, lines, risk_flags,
  posted_at, created_by, created_at
) values
  (
    '40000000-0000-0000-0000-000000000001', '${companyId}',
    '30000000-0000-0000-0000-000000000001', 2026, 'opening_balance',
    'Opening balance',
    '[{"account":"1920","description":"Bankinnskudd","debit":"30000.00","credit":"0.00"},
      {"account":"2000","description":"Aksjekapital","debit":"0.00","credit":"30000.00"}]'::jsonb,
    '[]'::jsonb, timestamptz '2026-01-01 09:00:00+00', '${ownerId}',
    timestamptz '2026-01-01 09:00:00+00'
  ),
  (
    '${malformedLegacyEntryId}', '${companyId}', null, 2026, 'manual_journal',
    'Malformed legacy imbalance',
    '[{"account":"7795","description":"Cost","debit":"100.00","credit":"0.00"},
      {"account":"1920","description":"Bank","debit":"0.00","credit":"99.00"}]'::jsonb,
    '[]'::jsonb, timestamptz '2026-02-01 09:00:00+00', '${ownerId}',
    timestamptz '2026-02-01 09:00:00+00'
  );
`;

function docker(args, options = {}) {
  return spawnSync("docker", args, {
    encoding: "utf8",
    maxBuffer: 24 * 1024 * 1024,
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
  const result = docker([
    "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
    "-U", "postgres", "-d", "talli_test", "-Atq",
  ], { input });
  assert.notEqual(result.status, 0, `statement unexpectedly succeeded:\n${input}`);
  return `${result.stdout}\n${result.stderr}`;
}

function lastOutputLine(output) {
  const lines = output.split("\n").map((line) => line.trim()).filter(Boolean);
  assert.ok(lines.length > 0, `expected query output, received ${JSON.stringify(output)}`);
  return lines.at(-1);
}

function jsonOutput(containerName, input) {
  return JSON.parse(lastOutputLine(psql(containerName, ["-Atq"], input)));
}

function sqlQuote(value) {
  return String(value).replaceAll("'", "''");
}

function actorContext(actorId) {
  return String.raw`
set local role ledger_executor;
set local talli.verified_actor_id = '${actorId}';
set local talli.verified_actor_claims = '{"sub":"${actorId}","role":"authenticated","aal":"aal2"}';
`;
}

function workflowActorContext(actorId, aal = "aal2") {
  return String.raw`
set local role ledger_workflow_executor;
set local talli.verified_actor_id = '${actorId}';
set local talli.verified_actor_claims = '{"sub":"${actorId}","role":"authenticated","aal":"${aal}"}';
`;
}

function newYearRequest(incomeYear = 2027, bankBalance = "45000.00") {
  return {
    companyId,
    incomeYear,
    bankBalance,
    shareCapital: "30000.00",
    shareCount: 100,
    nominalValue: "300.00",
    shareholders: [{
      name: "Runtime Owner",
      shareholderKind: "norwegian_person",
      nationalId: "01010112345",
      orgNumber: "999999999",
      shareCount: 100,
    }],
  };
}

function postCall({
  actorId = ownerId,
  verifiedSubject = actorId,
  company = companyId,
  incomeYear = 2026,
  idempotencyKey = "50000000-0000-4000-8000-000000000001",
  entryKind = "MANUAL_JOURNAL",
  memo = "Runtime manual journal",
  lines = [
    { account: "7795", description: "Cost", debit: "100.00", credit: "0.00", currency: "NOK" },
    { account: "1920", description: "Bank", debit: "0.00", credit: "100.00", currency: "NOK" },
  ],
  sourceCapability = "LEDGER",
  sourceRecordId = "manual:runtime-1",
  correlationId = "ledger-runtime",
} = {}) {
  return String.raw`
select row_to_json(posted)::text
from ledger.post_entry(
  '${sqlQuote(idempotencyKey)}'::text,
  '${company}'::uuid,
  ${incomeYear}::integer,
  '${entryKind}'::text,
  '${sqlQuote(memo)}'::text,
  '${sqlQuote(JSON.stringify(lines))}'::jsonb,
  '[]'::jsonb,
  false,
  '${sourceCapability}'::text,
  '${sqlQuote(sourceRecordId)}'::text,
  '${sqlQuote(correlationId)}'::text,
  '${verifiedSubject}'::text
) posted;
`;
}

function postTransaction(options = {}) {
  const actorId = options.actorId ?? ownerId;
  return String.raw`
begin;
${actorContext(actorId)}
${postCall(options)}
commit;
`;
}

function lockCall({
  actorId = ownerId,
  verifiedSubject = actorId,
  company = companyId,
  incomeYear = 2026,
  idempotencyKey = "60000000-0000-4000-8000-000000000001",
  reason = "Filing complete",
  correlationId = "ledger-runtime-lock",
} = {}) {
  return String.raw`
select row_to_json(locked)::text
from ledger.lock_period(
  '${sqlQuote(idempotencyKey)}'::text,
  '${company}'::uuid,
  ${incomeYear}::integer,
  '${sqlQuote(reason)}'::text,
  '${sqlQuote(correlationId)}'::text,
  '${verifiedSubject}'::text
) locked;
`;
}

function listCall({
  actorId,
  companyIds = [companyId],
  limit = 100,
  cursor = null,
  resource = "entries",
}) {
  const functionName = resource === "entries" ? "list_entries" : "list_period_locks";
  const ids = companyIds.map((id) => `'${id}'::uuid`).join(",");
  const cursorSql = cursor === null ? "null::text" : `'${sqlQuote(cursor)}'::text`;
  return String.raw`
begin;
${actorContext(actorId)}
select row_to_json(page)::text
from ledger.${functionName}(
  array[${ids}]::uuid[], ${cursorSql}, ${limit}::integer, '${actorId}'::text
) page;
commit;
`;
}

function interactivePsql(containerName) {
  const child = spawn("docker", [
    "exec", "-i", containerName, "psql", "-v", "ON_ERROR_STOP=1",
    "-U", "postgres", "-d", "talli_test", "-Atq",
  ], { stdio: ["pipe", "pipe", "pipe"] });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk) => { stdout += chunk; });
  child.stderr.on("data", (chunk) => { stderr += chunk; });
  const exited = new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => resolve({ code, stdout: () => stdout, stderr: () => stderr }));
  });
  return { child, exited, stdout: () => stdout, stderr: () => stderr };
}

function waitForOutput(process, pattern, timeoutMs = 10_000) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(
      `Timed out waiting for ${pattern}; stdout=${process.stdout()} stderr=${process.stderr()}`,
    )), timeoutMs);
    const inspect = () => {
      if (pattern.test(`${process.stdout()}\n${process.stderr()}`)) {
        clearTimeout(timeout);
        resolve();
      }
    };
    process.child.stdout.on("data", inspect);
    process.child.stderr.on("data", inspect);
    inspect();
  });
}

async function processResult(process) {
  const result = await process.exited;
  return { code: result.code, stdout: result.stdout(), stderr: result.stderr() };
}

function assertLegacyRoutinesDisabled(containerName) {
  const privileges = jsonOutput(containerName, String.raw`
    select pg_catalog.jsonb_object_agg(proc.proname, pg_catalog.jsonb_build_object(
      'authenticated', pg_catalog.has_function_privilege('authenticated', proc.oid, 'execute'),
      'serviceRole', pg_catalog.has_function_privilege('service_role', proc.oid, 'execute'),
      'executor', pg_catalog.has_function_privilege('ledger_executor', proc.oid, 'execute')
    ))::text
    from pg_catalog.pg_proc proc
    join pg_catalog.pg_namespace namespace on namespace.oid = proc.pronamespace
    where namespace.nspname = 'public'
      and proc.proname = any(array[${futurePostingRoutines.map((name) => `'${name}'`).join(",")}]);
  `);
  assert.deepEqual(Object.keys(privileges).sort(), [...futurePostingRoutines].sort());
  for (const privilege of Object.values(privileges)) {
    assert.deepEqual(privilege, {
      authenticated: false,
      executor: false,
      serviceRole: false,
    });
  }
}

test("ledger authority survives expand, contract, concurrency, rollback, and recutover", { timeout: 180_000 }, async (t) => {
  const dockerInfo = docker(["info", "--format", "{{.ServerVersion}}"]).status;
  if (dockerInfo !== 0) {
    t.skip("Docker daemon is required for the fresh PostgreSQL ledger rehearsal");
    return;
  }

  const containerName = `talli-ledger-${process.pid}-${randomUUID().slice(0, 8)}`;
  try {
    const started = docker([
      "run", "--rm", "--detach", "--name", containerName,
      "--env", "POSTGRES_PASSWORD=postgres", "--env", "POSTGRES_DB=talli_test",
      "--volume", `${repositoryRoot}:/repo:ro`, "postgres:17",
    ]);
    assert.equal(started.status, 0, started.stderr);

    let readyChecks = 0;
    for (let attempt = 0; attempt < 48; attempt += 1) {
      if (docker(["exec", containerName, "pg_isready", "-U", "postgres", "-d", "talli_test"]).status === 0) {
        readyChecks += 1;
        if (readyChecks === 2) break;
      } else {
        readyChecks = 0;
      }
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 250);
    }
    assert.equal(readyChecks, 2, "PostgreSQL container did not become ready");

    psql(containerName, [], bootstrapSql);
    for (const migration of predecessorMigrations) {
      psql(containerName, ["--file", `/repo/supabase/migrations/${migration}`]);
    }
    psql(containerName, [], predecessorCompanyAccessSql);
    psql(containerName, [], seedSql);

    psql(containerName, ["--file", expandPath]);

    const roleBoundary = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':', executor.rolcanlogin, executor.rolinherit, executor.rolbypassrls,
        backend.rolcanlogin, backend.rolinherit, backend.rolbypassrls,
        membership.inherit_option, membership.set_option)
      from pg_catalog.pg_roles executor
      join pg_catalog.pg_roles backend on backend.rolname = 'talli_ledger_backend'
      join pg_catalog.pg_auth_members membership
        on membership.roleid = executor.oid and membership.member = backend.oid
      where executor.rolname = 'ledger_executor';
    `));
    assert.equal(roleBoundary, "f:f:f:f:f:f:f:t");

    const forcedRls = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select pg_catalog.string_agg(
        namespace.nspname || '.' || class.relname || ':' ||
          class.relrowsecurity::text || ':' || class.relforcerowsecurity::text,
        ',' order by namespace.nspname, class.relname
      )
      from pg_catalog.pg_class class
      join pg_catalog.pg_namespace namespace on namespace.oid = class.relnamespace
      where (namespace.nspname = 'ledger'
          and class.relname = any(array['entries', 'period_locks']))
        or (namespace.nspname = 'backend_system'
          and class.relname = any(array[
            'ledger_command_receipts', 'ledger_workflow_receipts'
          ]));
    `));
    assert.equal(
      forcedRls,
      "backend_system.ledger_command_receipts:true:true,backend_system.ledger_workflow_receipts:true:true,ledger.entries:true:true,ledger.period_locks:true:true",
    );

    const workflowRequest = newYearRequest();
    const workflowRequestSql = sqlQuote(JSON.stringify(workflowRequest));
    const shareholdersSql = sqlQuote(JSON.stringify(workflowRequest.shareholders));
    const openingLines = [
      { account: "1920", description: "Bankinnskudd", debit: "45000.00", credit: "0.00", currency: "NOK" },
      { account: "2000", description: "Aksjekapital", debit: "0.00", credit: "30000.00", currency: "NOK" },
      { account: "2050", description: "Annen egenkapital", debit: "0.00", credit: "15000.00", currency: "NOK" },
    ];
    const openingLinesSql = sqlQuote(JSON.stringify(openingLines));
    const workflowKey = "73000000-0000-4000-8000-000000000007";

    const aal1Failure = psqlFailure(containerName, String.raw`
      begin;
      ${workflowActorContext(ownerId, "aal1")}
      select backend_system.claim_ledger_workflow_v1(
        'new_year_start', '${workflowKey}', '${companyId}',
        '${workflowRequestSql}'::jsonb, '${ownerId}'
      );
      select backend_system.record_opening_snapshot_legacy_v1(
        '${companyId}', 2027, 45000.00, 30000.00, 100, 300.00,
        '${shareholdersSql}'::jsonb, '${ownerId}'
      );
      commit;
    `);
    assert.match(aal1Failure, /ledger_company_year_not_admitted/iu);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select count(*) from public.opening_balance_setups
      where company_id = '${companyId}' and income_year = 2027;
    `)), "0");

    psql(containerName, [], String.raw`
      begin;
      ${workflowActorContext(ownerId)}
      select backend_system.claim_ledger_workflow_v1(
        'new_year_start', '${workflowKey}', '${companyId}',
        '${workflowRequestSql}'::jsonb, '${ownerId}'
      );
      select backend_system.record_opening_snapshot_legacy_v1(
        '${companyId}', 2027, 45000.00, 30000.00, 100, 300.00,
        '${shareholdersSql}'::jsonb, '${ownerId}'
      ) as setup_id \gset
      select * from ledger.post_entry(
        '${workflowKey}', '${companyId}', 2027, 'OPENING_BALANCE',
        'Åpningsbalanse for Talli-start', '${openingLinesSql}'::jsonb,
        '[]'::jsonb, false, 'SHAREHOLDER_REGISTER_FILING',
        'opening-setup:' || :'setup_id', 'new-year-runtime', '${ownerId}'
      ) \gset posted_
      select backend_system.complete_ledger_workflow_v1(
        'new_year_start', '${workflowKey}', '${companyId}',
        '${workflowRequestSql}'::jsonb,
        pg_catalog.jsonb_build_object(
          'setupId', :'setup_id',
          'entryId', :'posted_ledger_entry_id',
          'companyId', :'posted_company_id',
          'incomeYear', :'posted_income_year'::integer,
          'entryKind', :'posted_entry_kind',
          'postedAt', :'posted_posted_at'
        ),
        '${ownerId}'
      );
      commit;
    `);

    const newYearEvidence = jsonOutput(containerName, String.raw`
      select pg_catalog.jsonb_build_object(
        'setups', (select count(*) from public.opening_balance_setups
          where company_id = '${companyId}' and income_year = 2027),
        'shareholders', (select count(*) from public.opening_shareholders shareholder
          join public.opening_balance_setups setup on setup.id = shareholder.setup_id
          where setup.company_id = '${companyId}' and setup.income_year = 2027),
        'identifiers', (select pg_catalog.jsonb_build_object(
            'nationalId', shareholder.national_id,
            'orgNumber', shareholder.org_number
          )
          from public.opening_shareholders shareholder
          join public.opening_balance_setups setup on setup.id = shareholder.setup_id
          where setup.company_id = '${companyId}' and setup.income_year = 2027),
        'entries', (select count(*) from ledger.entries
          where company_id = '${companyId}' and income_year = 2027
            and entry_kind = 'OPENING_BALANCE'),
        'lines', (select lines from ledger.entries
          where company_id = '${companyId}' and income_year = 2027
            and entry_kind = 'OPENING_BALANCE'),
        'workflowReceipts', (select count(*)
          from backend_system.ledger_workflow_receipts
          where company_id = '${companyId}' and operation_name = 'new_year_start'
            and idempotency_key = '${workflowKey}')
      )::text;
    `);
    assert.deepEqual(newYearEvidence, {
      entries: 1,
      identifiers: {
        nationalId: "01010112345",
        orgNumber: "999999999",
      },
      lines: [
        { account: "1920", description: "Bankinnskudd", debit: 45000, credit: 0, currency: "NOK" },
        { account: "2000", description: "Aksjekapital", debit: 0, credit: 30000, currency: "NOK" },
        { account: "2050", description: "Annen egenkapital", debit: 0, credit: 15000, currency: "NOK" },
      ],
      setups: 1,
      shareholders: 1,
      workflowReceipts: 1,
    });

    const replay = jsonOutput(containerName, String.raw`
      begin;
      ${workflowActorContext(ownerId)}
      select backend_system.claim_ledger_workflow_v1(
        'new_year_start', '${workflowKey}', '${companyId}',
        '${workflowRequestSql}'::jsonb, '${ownerId}'
      )::text;
      commit;
    `);
    assert.equal(replay.incomeYear, 2027);

    const changedRequest = sqlQuote(JSON.stringify(newYearRequest(2027, "45001.00")));
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      ${workflowActorContext(ownerId)}
      select backend_system.claim_ledger_workflow_v1(
        'new_year_start', '${workflowKey}', '${companyId}',
        '${changedRequest}'::jsonb, '${ownerId}'
      );
      commit;
    `), /ledger_idempotency_key_reused/iu);

    const failedRequest = newYearRequest(2029, "50000.00");
    const failedRequestSql = sqlQuote(JSON.stringify(failedRequest));
    const failedShareholdersSql = sqlQuote(JSON.stringify(failedRequest.shareholders));
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      ${workflowActorContext(ownerId)}
      select backend_system.claim_ledger_workflow_v1(
        'new_year_start', '73000000-0000-4000-8000-000000000009',
        '${companyId}', '${failedRequestSql}'::jsonb, '${ownerId}'
      );
      select backend_system.record_opening_snapshot_legacy_v1(
        '${companyId}', 2029, 50000.00, 30000.00, 100, 300.00,
        '${failedShareholdersSql}'::jsonb, '${ownerId}'
      ) as setup_id \gset
      select * from ledger.post_entry(
        '73000000-0000-4000-8000-000000000009', '${companyId}', 2029,
        'OPENING_BALANCE', 'Åpningsbalanse for Talli-start',
        '${sqlQuote(JSON.stringify([
          { account: "1920", description: "Bankinnskudd", debit: "50000.00", credit: "0.00", currency: "NOK" },
          { account: "2000", description: "Aksjekapital", debit: "0.00", credit: "30000.00", currency: "NOK" },
          { account: "2050", description: "Annen egenkapital", debit: "0.00", credit: "20000.00", currency: "NOK" },
        ]))}'::jsonb, '[]'::jsonb, false,
        'SHAREHOLDER_REGISTER_FILING', 'opening-setup:' || :'setup_id',
        'new-year-runtime-failure', '${ownerId}'
      );
      select backend_system.complete_ledger_workflow_v1(
        'unsupported_operation', '73000000-0000-4000-8000-000000000009',
        '${companyId}', '${failedRequestSql}'::jsonb, '{}'::jsonb, '${ownerId}'
      );
      commit;
    `), /ledger_invalid_input/iu);
    assert.deepEqual(jsonOutput(containerName, String.raw`
      select pg_catalog.jsonb_build_object(
        'setups', (select count(*) from public.opening_balance_setups
          where company_id = '${companyId}' and income_year = 2029),
        'entries', (select count(*) from ledger.entries
          where company_id = '${companyId}' and income_year = 2029),
        'receipts', (select count(*) from backend_system.ledger_workflow_receipts
          where company_id = '${companyId}'
            and idempotency_key = '73000000-0000-4000-8000-000000000009')
      )::text;
    `), { entries: 0, receipts: 0, setups: 0 });

    assert.match(psqlFailure(containerName, String.raw`
      begin;
      ${workflowActorContext(ownerId)}
      insert into public.opening_balance_setups (
        company_id, income_year, bank_balance, share_capital,
        share_count, nominal_value, created_by
      ) values ('${companyId}', 2030, 0, 30000, 100, 300, '${ownerId}');
      commit;
    `), /permission denied/iu);

    psql(containerName, [], String.raw`
      begin;
      set local role authenticated;
      set local request.jwt.claim.sub = '${ownerId}';
      insert into public.ledger_entries (
        id, company_id, income_year, entry_type, memo, lines, risk_flags,
        posted_at, created_by, created_at
      ) values (
        '40000000-0000-0000-0000-000000000098', '${companyId}', 2028,
        'manual_journal', 'Expand overlap write',
        '[{"account":"7795","description":"Cost","debit":"10.00","credit":"0.00","currency":"NOK"},
          {"account":"1920","description":"Bank","debit":"0.00","credit":"10.00","currency":"NOK"}]'::jsonb,
        '[]'::jsonb, timestamptz '2028-02-28 10:00:00+00', '${ownerId}',
        timestamptz '2028-02-28 10:00:00+00'
      );
      commit;
    `);

    const reconciliation = jsonOutput(containerName, String.raw`
      select jsonb_object_agg(source_table, jsonb_build_object(
        'source', source_row_count,
        'accepted', accepted_row_count,
        'quarantined', quarantined_row_count,
        'sourceHashLength', char_length(source_sha256),
        'acceptedHashLength', char_length(accepted_sha256),
        'quarantineHashLength', char_length(quarantine_sha256)
      ) order by source_table)::text
      from backend_system.ledger_migration_reconciliations
      where recorded_at = (
        select max(recorded_at)
        from backend_system.ledger_migration_reconciliations
      );
    `);
    assert.deepEqual(reconciliation, {
      ledger_entries: {
        accepted: 1,
        acceptedHashLength: 64,
        quarantineHashLength: 64,
        quarantined: 1,
        source: 2,
        sourceHashLength: 64,
      },
      period_locks: {
        accepted: 0,
        acceptedHashLength: 64,
        quarantineHashLength: 64,
        quarantined: 0,
        source: 0,
        sourceHashLength: 64,
      },
    });
    const quarantine = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':', count(*), min(source_table), min(source_id::text),
        bool_and(btrim(reason_code) <> ''), min(char_length(payload_sha256)))
      from backend_system.ledger_migration_quarantine
      where source_table = 'ledger_entries' and source_id = '${malformedLegacyEntryId}';
    `));
    assert.equal(quarantine, `1:ledger_entries:${malformedLegacyEntryId}:t:64`);
    const normalized = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        not exists (select 1 from ledger.entries where id = '${malformedLegacyEntryId}'),
        bool_and(line ->> 'currency' = 'NOK'),
        bool_and(round((line ->> 'debit')::numeric, 2) = (line ->> 'debit')::numeric),
        bool_and(round((line ->> 'credit')::numeric, 2) = (line ->> 'credit')::numeric)
      )
      from ledger.entries entry
      cross join lateral pg_catalog.jsonb_array_elements(entry.lines) line;
    `));
    assert.equal(normalized, "t:t:t:t");

    psql(containerName, ["--file", contractPath]);

    const directWrites = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        to_regclass('public.ledger_entries') is null,
        to_regclass('public.period_locks') is null,
        has_table_privilege('authenticated', 'ledger.entries', 'insert'),
        has_table_privilege('authenticated', 'ledger.period_locks', 'insert'),
        has_table_privilege('authenticated', 'public.opening_balance_setups', 'insert'),
        has_table_privilege('service_role', 'ledger.entries', 'insert'),
        has_table_privilege('service_role', 'ledger.period_locks', 'insert'));
    `));
    assert.equal(directWrites, "t:t:f:f:f:f:f");
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      set local role authenticated;
      set local request.jwt.claim.sub = '${ownerId}';
      insert into public.ledger_entries (
        company_id, income_year, entry_type, memo, lines, created_by
      ) values (
        '${companyId}', 2026, 'manual_journal', 'browser bypass', '[]'::jsonb, '${ownerId}'
      );
      commit;
    `), /does not exist|permission denied|violates row-level security/iu);
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      set local role service_role;
      insert into ledger.period_locks (company_id, income_year, reason, locked_by)
      values ('${companyId}', 2026, 'service bypass', '${ownerId}');
      commit;
    `), /permission denied/iu);

    assertLegacyRoutinesDisabled(containerName);

    const firstPost = jsonOutput(containerName, postTransaction());
    const replayedPost = jsonOutput(containerName, postTransaction());
    assert.equal(firstPost.company_id, companyId);
    assert.equal(firstPost.income_year, 2026);
    assert.equal(firstPost.entry_kind, "MANUAL_JOURNAL");
    assert.equal(firstPost.replayed, false);
    assert.equal(replayedPost.ledger_entry_id, firstPost.ledger_entry_id);
    assert.equal(replayedPost.replayed, true);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        count(*) filter (where id = '${firstPost.ledger_entry_id}'),
        (select count(*) from backend_system.ledger_command_receipts
          where idempotency_key = '50000000-0000-4000-8000-000000000001'))
      from ledger.entries;
    `)), "1:1");

    const conflict = psqlFailure(containerName, postTransaction({
      fingerprint: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      memo: "Reused key with changed request",
    }));
    assert.match(conflict, /ledger_idempotency_key_reused/iu);

    const countsBeforeInvalid = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select (select count(*) from ledger.entries)::text || ':' ||
        (select count(*) from backend_system.ledger_command_receipts)::text;
    `));
    const invalidPostings = [
      {
        idempotencyKey: "50000000-0000-4000-8000-000000000010",
        fingerprint: "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
        lines: [
          { account: "7795", description: "Cost", debit: "100.00", credit: "0.00", currency: "NOK" },
          { account: "1920", description: "Bank", debit: "0.00", credit: "99.00", currency: "NOK" },
        ],
      },
      {
        idempotencyKey: "50000000-0000-4000-8000-000000000011",
        fingerprint: "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        lines: [
          { account: "7795", description: "Cost", debit: "100.00", credit: "0.00", currency: "EUR" },
          { account: "1920", description: "Bank", debit: "0.00", credit: "100.00", currency: "EUR" },
        ],
      },
      {
        idempotencyKey: "50000000-0000-4000-8000-000000000012",
        fingerprint: "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        lines: [
          { account: "7795", description: "Cost", debit: "100.001", credit: "0.00", currency: "NOK" },
          { account: "1920", description: "Bank", debit: "0.00", credit: "100.001", currency: "NOK" },
        ],
      },
    ];
    for (const invalid of invalidPostings) {
      assert.match(psqlFailure(containerName, postTransaction(invalid)), /ledger_invalid_input/iu);
    }
    const countsAfterInvalid = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select (select count(*) from ledger.entries)::text || ':' ||
        (select count(*) from backend_system.ledger_command_receipts)::text;
    `));
    assert.equal(countsAfterInvalid, countsBeforeInvalid, "invalid postings left partial state");

    assert.match(psqlFailure(containerName, postTransaction({
      actorId: ownerId,
      verifiedSubject: reviewerId,
      idempotencyKey: "50000000-0000-4000-8000-000000000020",
      fingerprint: "1111111111111111111111111111111111111111111111111111111111111111",
    })), /ledger_forbidden/iu);
    assert.match(psqlFailure(containerName, postTransaction({
      actorId: reviewerId,
      idempotencyKey: "50000000-0000-4000-8000-000000000021",
      fingerprint: "2222222222222222222222222222222222222222222222222222222222222222",
    })), /ledger_forbidden/iu);
    assert.match(psqlFailure(containerName, postTransaction({
      actorId: readOnlyId,
      idempotencyKey: "50000000-0000-4000-8000-000000000022",
      fingerprint: "3333333333333333333333333333333333333333333333333333333333333333",
    })), /ledger_forbidden/iu);
    assert.match(psqlFailure(containerName, postTransaction({
      actorId: outsiderId,
      idempotencyKey: "50000000-0000-4000-8000-000000000023",
      fingerprint: "4444444444444444444444444444444444444444444444444444444444444444",
    })), /ledger_not_found/iu);
    assert.match(psqlFailure(containerName, postTransaction({
      actorId: otherOwnerId,
      idempotencyKey: "50000000-0000-4000-8000-000000000024",
      fingerprint: "5555555555555555555555555555555555555555555555555555555555555555",
    })), /ledger_not_found/iu);

    const firstPage = jsonOutput(containerName, listCall({ actorId: reviewerId, limit: 1 }));
    assert.equal(Array.isArray(firstPage.items), true);
    assert.equal(firstPage.items.length, 1);
    assert.equal(firstPage.has_more, true);
    assert.equal(typeof firstPage.next_cursor, "string");
    assert.equal(firstPage.next_cursor.includes(firstPage.items[0].entryId), false);
    const secondPage = jsonOutput(containerName, listCall({
      actorId: reviewerId,
      limit: 1,
      cursor: firstPage.next_cursor,
    }));
    assert.equal(secondPage.items.length, 1);
    assert.notEqual(secondPage.items[0].entryId, firstPage.items[0].entryId);
    assert.match(psqlFailure(containerName, listCall({
      actorId: reviewerId,
      cursor: "not-a-valid-ledger-cursor",
    })), /ledger_invalid_(?:input|cursor)/iu);
    const readOnlyPage = jsonOutput(containerName, listCall({ actorId: readOnlyId }));
    assert.ok(readOnlyPage.items.length >= 2);
    const concealedPage = jsonOutput(containerName, listCall({ actorId: outsiderId }));
    assert.deepEqual(concealedPage.items, []);
    const mixedTenantPage = jsonOutput(containerName, listCall({
      actorId: ownerId,
      companyIds: [companyId, otherCompanyId],
    }));
    assert.equal(mixedTenantPage.items.every((item) => item.companyId === companyId), true);

    const postingSession = interactivePsql(containerName);
    postingSession.child.stdin.write(String.raw`
      begin;
      ${actorContext(ownerId)}
      ${postCall({
        incomeYear: 2026,
        idempotencyKey: "50000000-0000-4000-8000-000000000030",
        fingerprint: "6666666666666666666666666666666666666666666666666666666666666666",
        sourceRecordId: "manual:serialization",
      })}
      select 'poster_holds_company_year_lock';
    `);
    await waitForOutput(postingSession, /poster_holds_company_year_lock/u);

    const lockingSession = interactivePsql(containerName);
    lockingSession.child.stdin.end(String.raw`
      begin;
      ${actorContext(ownerId)}
      ${lockCall()}
      commit;
    `);
    let lockingSettled = false;
    const lockingResultPromise = processResult(lockingSession).then((result) => {
      lockingSettled = true;
      return result;
    });
    await new Promise((resolve) => setTimeout(resolve, 400));
    assert.equal(lockingSettled, false, "period lock did not serialize behind in-flight posting");

    postingSession.child.stdin.end("commit;\n");
    const postingResult = await processResult(postingSession);
    const lockingResult = await lockingResultPromise;
    assert.equal(postingResult.code, 0, postingResult.stderr);
    assert.equal(lockingResult.code, 0, lockingResult.stderr);

    const lockReplay = jsonOutput(containerName, String.raw`
      begin;
      ${actorContext(ownerId)}
      ${lockCall()}
      commit;
    `);
    assert.equal(lockReplay.replayed, true);
    assert.equal(lockReplay.company_id, companyId);
    assert.equal(lockReplay.income_year, 2026);
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      ${actorContext(ownerId)}
      ${lockCall({
        fingerprint: "8888888888888888888888888888888888888888888888888888888888888888",
        reason: "Changed reason on reused key",
      })}
      commit;
    `), /ledger_idempotency_key_reused/iu);
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      ${actorContext(reviewerId)}
      ${lockCall({
        actorId: reviewerId,
        incomeYear: 2026,
        idempotencyKey: "60000000-0000-4000-8000-000000000002",
        fingerprint: "9999999999999999999999999999999999999999999999999999999999999999",
      })}
      commit;
    `), /ledger_forbidden/iu);
    assert.match(psqlFailure(containerName, postTransaction({
      incomeYear: 2026,
      idempotencyKey: "50000000-0000-4000-8000-000000000031",
      fingerprint: "7777777777777777777777777777777777777777777777777777777777777777",
      sourceRecordId: "manual:after-lock",
    })), /ledger_period_locked/iu);

    const periodLocks = jsonOutput(containerName, listCall({
      actorId: reviewerId,
      resource: "period_locks",
      limit: 1,
    }));
    assert.equal(periodLocks.items.length, 1);
    assert.equal(periodLocks.items[0].companyId, companyId);

    const durableBeforeRollback = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.entries),
        (select count(*) from ledger.period_locks),
        (select count(*) from backend_system.ledger_command_receipts),
        encode(digest(coalesce((select string_agg(id::text || '|' || lines::text, E'\n' order by id)
          from ledger.entries), ''), 'sha256'), 'hex'));
    `));

    psql(containerName, ["--file", rollbackPath]);
    const overlapPrivileges = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        has_table_privilege('authenticated', 'public.ledger_entries', 'insert'),
        has_table_privilege('authenticated', 'public.period_locks', 'insert'),
        has_table_privilege('authenticated', 'public.opening_balance_setups', 'insert'),
        has_table_privilege('service_role', 'public.ledger_entries', 'insert'));
    `));
    assert.equal(overlapPrivileges, "t:t:t:f");

    psql(containerName, [], String.raw`
      begin;
      set local role authenticated;
      set local request.jwt.claim.sub = '${ownerId}';
      insert into public.ledger_entries (
        id, company_id, income_year, entry_type, memo, lines, risk_flags,
        posted_at, created_by, created_at
      ) values (
        '${malformedLegacyEntryId}', '${companyId}', 2028,
        'manual_journal', 'Reviewed rollback-window write',
        '[{"account":"7795","description":"Cost","debit":"25.00","credit":"0.00","currency":"NOK"},
          {"account":"1920","description":"Bank","debit":"0.00","credit":"25.00","currency":"NOK"}]'::jsonb,
        '[]'::jsonb, timestamptz '2028-03-01 10:00:00+00', '${ownerId}',
        timestamptz '2028-03-01 10:00:00+00'
      );
      commit;
    `);

    psql(containerName, ["--file", expandPath]);
    psql(containerName, ["--file", contractPath]);

    const recutoverWrites = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        to_regclass('public.ledger_entries') is null,
        to_regclass('public.period_locks') is null,
        has_table_privilege('authenticated', 'ledger.entries', 'insert'),
        has_table_privilege('authenticated', 'ledger.period_locks', 'insert'),
        has_table_privilege('authenticated', 'public.opening_balance_setups', 'insert'),
        has_table_privilege('service_role', 'ledger.entries', 'insert'));
    `));
    assert.equal(recutoverWrites, "t:t:f:f:f:f");
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select count(*) from ledger.entries
      where id = '${malformedLegacyEntryId}';
    `)), "1");
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select count(*) from backend_system.ledger_migration_quarantine
      where source_table = 'ledger_entries' and source_id = '${malformedLegacyEntryId}';
    `)), "1");
    assert.ok(Number(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select count(*) from backend_system.ledger_migration_reconciliations;
    `))) >= 4);
    assertLegacyRoutinesDisabled(containerName);

    const recutoverReplay = jsonOutput(containerName, postTransaction());
    assert.equal(recutoverReplay.ledger_entry_id, firstPost.ledger_entry_id);
    assert.equal(recutoverReplay.replayed, true);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select count(*) from backend_system.ledger_command_receipts
      where idempotency_key = '50000000-0000-4000-8000-000000000001';
    `)), "1");

    const durableAfterRecutover = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.entries) - 1,
        (select count(*) from ledger.period_locks),
        (select count(*) from backend_system.ledger_command_receipts),
        encode(digest(coalesce((select string_agg(id::text || '|' || lines::text, E'\n' order by id)
          from ledger.entries where id <> '${malformedLegacyEntryId}'), ''),
          'sha256'), 'hex'));
    `));
    assert.equal(durableAfterRecutover, durableBeforeRollback);
  } finally {
    docker(["rm", "--force", containerName]);
  }
});
