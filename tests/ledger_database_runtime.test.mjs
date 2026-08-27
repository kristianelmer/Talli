import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import test from "node:test";

const repositoryRoot = fileURLToPath(new URL("..", import.meta.url));
const expandPath = "/repo/supabase/migrations/20260827100000_ledger_capability.sql";
const coordinatorPath = "/repo/supabase/migrations/20260827100500_ledger_writer_coordinators.sql";
const reconstructionPath = "/repo/supabase/migrations/20260827101000_ledger_full_year_reconstruction.sql";
const supportedPatternsPath = "/repo/supabase/migrations/20260827102000_ledger_supported_patterns.sql";
const correctionsPath = "/repo/supabase/migrations/20260827103000_ledger_corrections.sql";
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
const overlapOpeningEntryId = "40000000-0000-0000-0000-000000000097";
const overlapOpeningSetupId = "30000000-0000-0000-0000-000000000097";

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
create schema extensions;
create extension pgcrypto with schema extensions;
grant usage on schema extensions to public;
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

insert into public.opening_shareholders (
  id, setup_id, company_id, name, shareholder_kind, national_id,
  org_number, share_count, created_by, created_at
) values (
  '31000000-0000-0000-0000-000000000001',
  '30000000-0000-0000-0000-000000000001', '${companyId}',
  'Runtime Owner', 'norwegian_person', '01010112345', null, 100,
  '${ownerId}', timestamptz '2026-01-01 09:00:00+00'
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

const archiveFreshnessFixtureSql = String.raw`
create role company_archive_projection_executor nologin noinherit nobypassrls;
create table public.company_archive_source_generations (
  company_id uuid not null,
  income_year integer not null,
  generation bigint not null default 0,
  updated_at timestamptz not null default statement_timestamp(),
  primary key (company_id, income_year)
);
create table public.company_archive_export_attempts (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null,
  income_year integer not null,
  source_generation bigint not null,
  started_at timestamptz not null default statement_timestamp()
);
alter table public.company_archive_source_generations enable row level security;
alter table public.company_archive_export_attempts enable row level security;
create policy "archive projection executor manages generations"
on public.company_archive_source_generations for all
to company_archive_projection_executor using (true) with check (true);
create policy "archive projection executor manages attempts"
on public.company_archive_export_attempts for all
to company_archive_projection_executor using (true) with check (true);
grant select, insert, update, delete
on public.company_archive_source_generations, public.company_archive_export_attempts
to company_archive_projection_executor;
revoke all
on public.company_archive_source_generations, public.company_archive_export_attempts
from public, anon, authenticated, service_role;
create or replace function public.company_archive_lock_company_v1(p_company_id uuid)
returns void
language plpgsql
volatile
set search_path = ''
as $function$
begin
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(p_company_id::text, 157)
  );
end;
$function$;
create or replace function public.company_archive_lock_scope_v1(
  p_company_id uuid, p_income_year integer
) returns void
language sql
volatile
set search_path = ''
as $function$
  select public.company_archive_lock_company_v1(p_company_id);
$function$;
create or replace function public.company_archive_track_source_write_v1()
returns trigger
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_company_id uuid;
  v_scope record;
begin
  for v_company_id in
    with changed_rows(row_data) as (
      select pg_catalog.to_jsonb(old) where tg_op in ('UPDATE', 'DELETE')
      union all
      select pg_catalog.to_jsonb(new) where tg_op in ('INSERT', 'UPDATE')
    )
    select distinct (row_data ->> tg_argv[1])::uuid
    from changed_rows
    where (row_data ->> tg_argv[1]) is not null
    order by 1
  loop
    perform public.company_archive_lock_company_v1(v_company_id);
  end loop;

  if tg_argv[0] = 'year' then
    for v_scope in
      with changed_rows(row_data) as (
        select pg_catalog.to_jsonb(old) where tg_op in ('UPDATE', 'DELETE')
        union all
        select pg_catalog.to_jsonb(new) where tg_op in ('INSERT', 'UPDATE')
      )
      select distinct (row_data ->> tg_argv[1])::uuid as scope_company_id,
             (row_data ->> 'income_year')::integer as scope_income_year
      from changed_rows
      where (row_data ->> tg_argv[1]) is not null
        and (row_data ->> 'income_year') is not null
      order by 1, 2
    loop
      insert into public.company_archive_source_generations(
        company_id, income_year, generation, updated_at
      ) values (
        v_scope.scope_company_id, v_scope.scope_income_year, 1,
        pg_catalog.statement_timestamp()
      )
      on conflict (company_id, income_year) do update
        set generation = public.company_archive_source_generations.generation + 1,
            updated_at = excluded.updated_at;
    end loop;
  end if;
  return coalesce(new, old);
end;
$function$;
alter function public.company_archive_track_source_write_v1()
  owner to company_archive_projection_executor;
grant execute on function public.company_archive_lock_company_v1(uuid),
  public.company_archive_lock_scope_v1(uuid, integer)
to company_archive_projection_executor;
revoke all on function public.company_archive_track_source_write_v1()
from public, anon, authenticated, service_role;
create trigger company_archive_track_ledger_entries
before insert or update or delete on public.ledger_entries
for each row execute function public.company_archive_track_source_write_v1(
  'year', 'company_id'
);
create or replace function public.company_archive_begin_export_fixture(
  p_company_id uuid, p_income_year integer
) returns uuid
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_attempt_id uuid;
begin
  perform public.company_archive_lock_scope_v1(p_company_id, p_income_year);
  insert into public.company_archive_source_generations(
    company_id, income_year, generation
  ) values (p_company_id, p_income_year, 0)
  on conflict (company_id, income_year) do nothing;
  insert into public.company_archive_export_attempts(
    company_id, income_year, source_generation
  )
  select p_company_id, p_income_year, generation
  from public.company_archive_source_generations
  where company_id = p_company_id and income_year = p_income_year
  returning id into v_attempt_id;
  return v_attempt_id;
end;
$function$;
alter function public.company_archive_begin_export_fixture(uuid, integer)
  owner to company_archive_projection_executor;
create or replace function public.company_archive_complete_export_fixture(
  p_attempt_id uuid
) returns void
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_attempt public.company_archive_export_attempts%rowtype;
  v_generation bigint;
begin
  select * into strict v_attempt
  from public.company_archive_export_attempts
  where id = p_attempt_id for update;
  perform public.company_archive_lock_scope_v1(
    v_attempt.company_id, v_attempt.income_year
  );
  select generation into strict v_generation
  from public.company_archive_source_generations
  where company_id = v_attempt.company_id
    and income_year = v_attempt.income_year;
  if v_generation <> v_attempt.source_generation then
    raise exception 'archive_export_stale';
  end if;
end;
$function$;
alter function public.company_archive_complete_export_fixture(uuid)
  owner to company_archive_projection_executor;
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

function openingSnapshotCall({
  actorId = ownerId,
  verifiedSubject = actorId,
  companyIds = [companyId],
  cursor = null,
  limit = 100,
  page = false,
} = {}) {
  const ids = companyIds.map((id) => `'${id}'::uuid`).join(",");
  const cursorSql = cursor === null ? "null" : `'${sqlQuote(cursor)}'`;
  const projection = page
    ? "pg_catalog.jsonb_build_object('items', items, 'nextCursor', next_cursor, 'hasMore', has_more)"
    : "items";
  return String.raw`
begin;
${actorContext(actorId)}
select ${projection}::text
from backend_system.list_opening_snapshots_legacy_v1(
  array[${ids}]::uuid[], ${cursorSql}, ${limit}, '${verifiedSubject}'
);
commit;
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

function correctionCall({
  actorId = ownerId,
  verifiedSubject = actorId,
  originalEntryId,
  idempotencyKey = "63000000-0000-4000-8000-000000000001",
  reason = "Documented category was wrong",
  replacementKind = "ADMINISTRATIVE_COST",
  replacementMemo = "Corrected legal advisory cost",
  replacementLines = [
    { account: "6720", description: "Legal advisory", debit: "500.00", credit: "0.00", currency: "NOK" },
    { account: "1920", description: "Bank", debit: "0.00", credit: "500.00", currency: "NOK" },
  ],
  correlationId = "ledger-correction-runtime",
  correctionScope = "CURRENT_COMPANY_YEAR",
  sources = [
    { role: "PRIMARY", capability: "DOCUMENTS", recordId: "correction:document:1", revision: 1, factSha256: "b".repeat(64) },
    { role: "CORROBORATING", capability: "BANKING", recordId: "correction:bank:1", revision: 1, factSha256: "c".repeat(64) },
  ],
} = {}) {
  return String.raw`
select row_to_json(corrected)::text
from ledger.correct_entry_v1(
  '${sqlQuote(idempotencyKey)}'::text,
  '${companyId}'::uuid,
  2026::integer,
  '${originalEntryId}'::uuid,
  '${sqlQuote(reason)}'::text,
  '${replacementKind}'::text,
  '${sqlQuote(replacementMemo)}'::text,
  '${sqlQuote(JSON.stringify(replacementLines))}'::jsonb,
  '${sqlQuote(correlationId)}'::text,
  '${verifiedSubject}'::text,
  '2026-08-27'::date,
  '${correctionScope}'::text,
  'ledger-supported-patterns-2026.1'::text,
  '${sqlQuote(JSON.stringify(sources))}'::jsonb
) corrected;
`;
}

function correctionTransaction(options = {}) {
  const actorId = options.actorId ?? ownerId;
  return String.raw`
begin;
${actorContext(actorId)}
${correctionCall(options)}
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

function reconstructionEvidence({ documentsReady = true } = {}) {
  const pairs = [
    ["PRIOR_CLOSING_OPENING", "LEDGER"],
    ["BANK_MOVEMENTS", "BANKING"],
    ["BANK_RECONCILIATION", "BANKING"],
    ["INVESTMENTS", "INVESTMENTS"],
    ["SHAREHOLDERS", "SHAREHOLDER_REGISTER_FILING"],
    ["LOANS", "BANKING"],
    ["LOANS", "CORPORATE_GOVERNANCE"],
    ["EQUITY", "CORPORATE_GOVERNANCE"],
    ["EQUITY", "SHAREHOLDER_REGISTER_FILING"],
    ["TAX_HISTORY", "COMPANY_TAX_FILING"],
    ["CURRENT_YEAR_ACTIVITY", "LEDGER"],
    ["DOCUMENTS", "DOCUMENTS"],
    ["UNSUPPORTED_ACTIVITY_CHECK", "COMPANY_ACCESS"],
  ];
  return pairs.map(([kind, issuer], index) => ({
    kind,
    issuer,
    confirmation: kind === "DOCUMENTS" && !documentsReady ? "UNKNOWN" : "CONFIRMED",
    sourceRecordId: `runtime:${issuer.toLowerCase()}:${index}`,
    factSha256: index.toString(16).padStart(64, "0"),
    coverageFrom: ["BANK_MOVEMENTS", "CURRENT_YEAR_ACTIVITY"].includes(kind)
      ? "2026-01-01"
      : null,
    coverageThrough: ["BANK_MOVEMENTS", "CURRENT_YEAR_ACTIVITY"].includes(kind)
      ? "2026-08-27"
      : null,
    gapCode: kind === "DOCUMENTS" && !documentsReady ? "DOCUMENTS_INCOMPLETE" : null,
  }));
}

function reconstructionCall({
  actorId = ownerId,
  idempotencyKey = "61000000-0000-4000-8000-000000000001",
  documentsReady = true,
} = {}) {
  const evidence = reconstructionEvidence({ documentsReady });
  const state = documentsReady ? "READY" : "BLOCKED";
  const gaps = documentsReady ? "array[]::text[]" : "array['DOCUMENTS_INCOMPLETE']::text[]";
  return String.raw`
begin;
set local role ledger_executor;
${actorContext(actorId)}
select row_to_json(assessment)::text
from ledger.record_reconstruction_assessment(
  '${idempotencyKey}'::text,
  '${companyId}'::uuid,
  2026::integer,
  '2026-08-27'::date,
  '${sqlQuote(JSON.stringify(evidence))}'::jsonb,
  '${state}'::text,
  ${gaps},
  'ledger-reconstruction-runtime'::text,
  '${actorId}'::text
) assessment;
commit;
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

function writerCoordinatorPrivileges(containerName) {
  return lastOutputLine(psql(containerName, ["-Atq"], String.raw`
    select concat_ws(':',
      pg_catalog.has_function_privilege(
        'ledger_workflow_executor',
        'backend_system.prepare_administrative_cost_v1(jsonb,text)', 'execute'
      ),
      pg_catalog.has_function_privilege(
        'authenticated',
        'backend_system.prepare_administrative_cost_v1(jsonb,text)', 'execute'
      ),
      pg_catalog.has_function_privilege(
        'ledger_workflow_executor',
        'backend_system.complete_bank_transaction_suggestion_v1(jsonb,uuid,jsonb,text)',
        'execute'
      ),
      pg_catalog.has_function_privilege(
        'authenticated',
        'backend_system.complete_bank_transaction_suggestion_v1(jsonb,uuid,jsonb,text)',
        'execute'
      ));
  `));
}

function archiveTriggerState(containerName, relation) {
  return lastOutputLine(psql(containerName, ["-Atq"], String.raw`
    select concat_ws(':', count(*), coalesce(bool_and(
      trigger.tgname = 'company_archive_track_ledger_entries'
      and trigger.tgenabled in ('O', 'A')
      and trigger.tgtype = 31
      and trigger.tgnargs = 2
      and encode(trigger.tgargs, 'hex') = '7965617200636f6d70616e795f696400'
    ), false))
    from pg_catalog.pg_trigger trigger
    where trigger.tgrelid = '${relation}'::regclass
      and trigger.tgfoid = pg_catalog.to_regprocedure(
        'public.company_archive_track_source_write_v1()'
      )
      and not trigger.tgisinternal;
  `));
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
    psql(containerName, [], archiveFreshnessFixtureSql);

    psql(containerName, ["--file", expandPath]);
    psql(containerName, ["--file", coordinatorPath]);
    psql(containerName, ["--file", reconstructionPath]);
    psql(containerName, ["--file", supportedPatternsPath]);
    psql(containerName, ["--file", correctionsPath]);

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
          and class.relname = any(array[
            'entries', 'period_locks', 'reconstruction_assessments',
            'reconstruction_evidence', 'entry_contexts', 'entry_sources',
            'entry_corrections'
          ]))
        or (namespace.nspname = 'backend_system'
          and class.relname = any(array[
            'ledger_command_receipts', 'ledger_workflow_receipts'
          ]));
    `));
    assert.equal(
      forcedRls,
      "backend_system.ledger_command_receipts:true:true,backend_system.ledger_workflow_receipts:true:true,ledger.entries:true:true,ledger.entry_contexts:true:true,ledger.entry_corrections:true:true,ledger.entry_sources:true:true,ledger.period_locks:true:true,ledger.reconstruction_assessments:true:true,ledger.reconstruction_evidence:true:true",
    );

    const supportedSources = JSON.stringify([{
      role: "PRIMARY",
      capability: "BANKING",
      recordId: "golden:runtime-bank-interest",
      revision: 1,
      factSha256: "a".repeat(64),
    }]);
    const supportedLines = JSON.stringify([
      { account: "1920", description: "Bank interest received", debit: "500.00", credit: "0.00", currency: "NOK" },
      { account: "8050", description: "Bank interest income", debit: "0.00", credit: "500.00", currency: "NOK" },
    ]);
    const supportedCall = ({ sources = supportedSources, actorId = ownerId } = {}) => String.raw`
      begin;
      ${actorContext(actorId)}
      select row_to_json(posted)::text
      from ledger.post_supported_entry_v1(
        '62000000-0000-4000-8000-000000000001', '${companyId}', 2026,
        'BANK_INTEREST', 'Bank interest supported by bank advice',
        '${sqlQuote(supportedLines)}'::jsonb, 'BANKING',
        'golden:runtime-bank-interest', 'supported-pattern-runtime', '${actorId}',
        '2026-08-27', 'ledger-supported-patterns-2026.1',
        '${sqlQuote(sources)}'::jsonb
      ) posted;
      commit;
    `;
    const supportedPosting = jsonOutput(containerName, supportedCall());
    assert.equal(supportedPosting.entry_kind, "BANK_INTEREST");
    assert.equal(supportedPosting.replayed, false);
    assert.equal(jsonOutput(containerName, supportedCall()).replayed, true);
    const correctionOriginal = jsonOutput(containerName, postTransaction({
      idempotencyKey: "50000000-0000-4000-8000-000000000032",
      entryKind: "ADMINISTRATIVE_COST",
      memo: "Original administration cost",
      lines: [
        { account: "7795", description: "Administration cost", debit: "500.00", credit: "0.00", currency: "NOK" },
        { account: "1920", description: "Bank", debit: "0.00", credit: "500.00", currency: "NOK" },
      ],
      sourceCapability: "BANKING",
      sourceRecordId: "correction-original:admin-cost",
      correlationId: "correction-original-runtime",
    }));
    assert.equal(correctionOriginal.entry_kind, "ADMINISTRATIVE_COST");
    const capitalReductionLines = JSON.stringify([
      { account: "2033", description: "Unregistered capital reduction", debit: "20000.00", credit: "0.00", currency: "NOK" },
      { account: "2080", description: "Uncovered loss", debit: "0.00", credit: "20000.00", currency: "NOK" },
    ]);
    const capitalReductionSources = JSON.stringify([{
      role: "PRIMARY",
      capability: "CORPORATE_GOVERNANCE",
      recordId: "golden:runtime-capital-reduction",
      revision: 1,
      factSha256: "d".repeat(64),
    }]);
    const capitalReductionPosting = jsonOutput(containerName, String.raw`
      begin;
      ${actorContext(ownerId)}
      select row_to_json(posted)::text
      from ledger.post_supported_entry_v1(
        '62000000-0000-4000-8000-000000000002', '${companyId}', 2026,
        'CAPITAL_REDUCTION', 'Loss-coverage capital reduction decided, not registered',
        '${sqlQuote(capitalReductionLines)}'::jsonb, 'CORPORATE_GOVERNANCE',
        'golden:runtime-capital-reduction', 'capital-reduction-runtime', '${ownerId}',
        '2026-08-27', 'ledger-supported-patterns-2026.1',
        '${sqlQuote(capitalReductionSources)}'::jsonb
      ) posted;
      commit;
    `);
    assert.equal(capitalReductionPosting.entry_kind, "CAPITAL_REDUCTION");
    const intercompanyLoanLines = JSON.stringify([
      { account: "1320", description: "Intercompany loan receivable", debit: "80000.00", credit: "0.00", currency: "NOK" },
      { account: "1920", description: "Intercompany funding paid", debit: "0.00", credit: "80000.00", currency: "NOK" },
    ]);
    const intercompanyLoanSources = JSON.stringify([
      {
        role: "PRIMARY",
        capability: "CORPORATE_GOVERNANCE",
        recordId: "golden:runtime-intercompany-approval",
        revision: 1,
        factSha256: "e".repeat(64),
      },
      {
        role: "CORROBORATING",
        capability: "BANKING",
        recordId: "golden:runtime-intercompany-bank",
        revision: 1,
        factSha256: "f".repeat(64),
      },
    ]);
    const intercompanyLoanPosting = jsonOutput(containerName, String.raw`
      begin;
      ${actorContext(ownerId)}
      select row_to_json(posted)::text
      from ledger.post_supported_entry_v1(
        '62000000-0000-4000-8000-000000000003', '${companyId}', 2026,
        'INTERCOMPANY_LOAN', 'Approved intercompany loan funding: LENDER',
        '${sqlQuote(intercompanyLoanLines)}'::jsonb, 'CORPORATE_GOVERNANCE',
        'golden:runtime-intercompany-approval', 'intercompany-loan-runtime', '${ownerId}',
        '2026-08-27', 'ledger-supported-patterns-2026.1',
        '${sqlQuote(intercompanyLoanSources)}'::jsonb
      ) posted;
      commit;
    `);
    assert.equal(intercompanyLoanPosting.entry_kind, "INTERCOMPANY_LOAN");
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select count(*) from ledger.entry_sources
      where entry_id = '${intercompanyLoanPosting.ledger_entry_id}';
    `)), "2");
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.entry_contexts
          where entry_id = '${supportedPosting.ledger_entry_id}'),
        (select count(*) from ledger.entry_sources
          where entry_id = '${supportedPosting.ledger_entry_id}'),
        (select event_date from ledger.entry_contexts
          where entry_id = '${supportedPosting.ledger_entry_id}'));
    `)), "1:1:2026-08-27");
    const changedSources = JSON.stringify([{
      ...JSON.parse(supportedSources)[0],
      factSha256: "b".repeat(64),
    }]);
    assert.match(
      psqlFailure(containerName, supportedCall({ sources: changedSources })),
      /ledger_idempotency_key_reused/iu,
    );
    assert.match(
      psqlFailure(containerName, supportedCall({ actorId: reviewerId })),
      /ledger_forbidden/iu,
    );
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      ${actorContext(ownerId)}
      insert into ledger.entry_sources (
        entry_id, company_id, income_year, ordinal, source_role,
        source_capability, source_record_id, source_revision, fact_sha256
      ) values (
        '${supportedPosting.ledger_entry_id}', '${companyId}', 2026, 2,
        'CORROBORATING', 'BANKING', 'forbidden-direct-source', 1,
        '${"c".repeat(64)}'
      );
      commit;
    `), /permission denied/iu);

    const blockedReconstruction = jsonOutput(
      containerName,
      reconstructionCall({ documentsReady: false }),
    );
    assert.equal(blockedReconstruction.state, "BLOCKED");
    assert.deepEqual(blockedReconstruction.gap_codes, ["DOCUMENTS_INCOMPLETE"]);
    assert.match(blockedReconstruction.evidence_digest, /^[a-f0-9]{64}$/u);
    assert.equal(
      jsonOutput(
        containerName,
        reconstructionCall({ documentsReady: false }),
      ).assessment_id,
      blockedReconstruction.assessment_id,
    );
    const readyReconstruction = jsonOutput(
      containerName,
      reconstructionCall({
        documentsReady: true,
        idempotencyKey: "61000000-0000-4000-8000-000000000002",
      }),
    );
    assert.equal(readyReconstruction.state, "READY");
    assert.deepEqual(readyReconstruction.gap_codes, []);
    assert.equal(
      lastOutputLine(psql(containerName, ["-Atq"], String.raw`
        begin;
        ${actorContext(ownerId)}
        select state || ':' || pg_catalog.cardinality(gap_codes)::text
        from ledger.get_reconstruction_assessment(
          '${companyId}'::uuid, 2026, '${ownerId}'
        );
        commit;
      `)),
      "READY:0",
    );
    assert.match(
      psqlFailure(containerName, reconstructionCall({ actorId: reviewerId })),
      /ledger_forbidden/iu,
    );
    assert.match(
      psqlFailure(containerName, reconstructionCall({
        idempotencyKey: "61000000-0000-4000-8000-000000000002",
        documentsReady: false,
      })),
      /ledger_idempotency_key_reused/iu,
    );
    assert.equal(
      lastOutputLine(psql(containerName, ["-Atq"], String.raw`
        select concat_ws(':',
          pg_catalog.has_function_privilege(
            'ledger_executor',
            'ledger.record_reconstruction_assessment(text,uuid,integer,date,jsonb,text,text[],text,text)',
            'execute'
          ),
          pg_catalog.has_function_privilege(
            'authenticated',
            'ledger.record_reconstruction_assessment(text,uuid,integer,date,jsonb,text,text[],text,text)',
            'execute'
          ),
          pg_catalog.has_table_privilege(
            'ledger_executor', 'ledger.reconstruction_assessments', 'insert'
          )
        );
      `)),
      "t:f:f",
    );

    for (const actorId of [ownerId, reviewerId, readOnlyId]) {
      const projection = jsonOutput(containerName, openingSnapshotCall({ actorId }));
      assert.equal(projection.length, 1);
      assert.equal(projection[0].companyId, companyId);
      assert.equal(projection[0].setupId, "30000000-0000-0000-0000-000000000001");
      assert.equal(projection[0].bankBalance, "30000.00");
      assert.equal(projection[0].shareholders[0].nationalId, "01010112345");
    }
    const exactMoneyProjection = jsonOutput(containerName, String.raw`
      begin;
      update public.opening_balance_setups
      set bank_balance = 9007199254740993.12
      where id = '30000000-0000-0000-0000-000000000001';
      ${actorContext(ownerId)}
      select items::text
      from backend_system.list_opening_snapshots_legacy_v1(
        array['${companyId}'::uuid], null, 100, '${ownerId}'
      );
      rollback;
    `);
    assert.equal(
      exactMoneyProjection[0].bankBalance,
      "9007199254740993.12",
    );
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      update public.opening_balance_setups
      set bank_balance = 30000.001
      where id = '30000000-0000-0000-0000-000000000001';
      ${actorContext(ownerId)}
      select items::text
      from backend_system.list_opening_snapshots_legacy_v1(
        array['${companyId}'::uuid], null, 100, '${ownerId}'
      );
      rollback;
    `), /ledger_dependency_unavailable/iu);
    assert.deepEqual(
      jsonOutput(containerName, openingSnapshotCall({ actorId: outsiderId })),
      [],
    );
    assert.deepEqual(
      jsonOutput(containerName, openingSnapshotCall({
        actorId: ownerId,
        companyIds: [companyId, otherCompanyId],
      })).map((item) => item.companyId),
      [companyId],
    );
    assert.match(psqlFailure(containerName, openingSnapshotCall({
      actorId: ownerId,
      verifiedSubject: reviewerId,
    })), /ledger_forbidden/iu);
    assert.match(psqlFailure(containerName, openingSnapshotCall({
      actorId: ownerId,
      companyIds: [companyId, companyId],
    })), /ledger_invalid_input/iu);

    psql(containerName, [], String.raw`
      insert into public.opening_shareholders (
        setup_id, company_id, name, shareholder_kind, national_id,
        share_count, created_by
      )
      select
        '30000000-0000-0000-0000-000000000001', '${companyId}',
        'Overflow ' || ordinal, 'norwegian_person',
        pg_catalog.lpad(ordinal::text, 11, '0'), 0, '${ownerId}'
      from pg_catalog.generate_series(1, 100) as series(ordinal);
    `);
    assert.match(
      psqlFailure(containerName, openingSnapshotCall({ actorId: ownerId })),
      /ledger_dependency_unavailable/iu,
    );
    psql(containerName, [], String.raw`
      delete from public.opening_shareholders where name like 'Overflow %';
    `);

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

    const adminBankId = "81000000-0000-0000-0000-000000000001";
    const failedAdminBankId = "81000000-0000-0000-0000-000000000002";
    const suggestionBankId = "81000000-0000-0000-0000-000000000003";
    psql(containerName, [], String.raw`
      insert into public.bank_transactions (
        id, company_id, income_year, transaction_date, text, amount,
        source_hash, created_by
      ) values
        ('${adminBankId}', '${companyId}', 2026, date '2026-03-01',
          'Talli annual fee', -1490.00, 'runtime-admin-cost', '${ownerId}'),
        ('${failedAdminBankId}', '${companyId}', 2026, date '2026-03-02',
          'Talli failed fee', -1490.00, 'runtime-admin-cost-failure', '${ownerId}'),
        ('${suggestionBankId}', '${companyId}', 2026, date '2026-03-03',
          'Årsgebyr', -89.00, 'runtime-bank-suggestion', '${ownerId}');
    `);

    const adminRequest = {
      companyId,
      incomeYear: 2026,
      idempotencyKey: "82000000-0000-4000-8000-000000000001",
      correlationId: "runtime-admin-coordinator",
      bankTransactionId: adminBankId,
      category: "SOFTWARE",
      payee: "Talli AS",
      amount: "1490.00",
      paidDate: "2026-03-01",
      documentId: null,
    };
    const adminRequestSql = sqlQuote(JSON.stringify(adminRequest));
    const adminLinesSql = sqlQuote(JSON.stringify([
      { account: "6420", description: "Admin cost: Talli AS", debit: "1490.00", credit: "0.00", currency: "NOK" },
      { account: "1920", description: "Paid from bank", debit: "0.00", credit: "1490.00", currency: "NOK" },
    ]));
    const adminResult = jsonOutput(containerName, String.raw`
      begin;
      ${workflowActorContext(ownerId)}
      select backend_system.prepare_administrative_cost_v1(
        '${adminRequestSql}'::jsonb, '${ownerId}'
      ) as prepared \gset
      select * from ledger.post_entry(
        '${adminRequest.idempotencyKey}', '${companyId}', 2026,
        'ADMINISTRATIVE_COST', 'Admin cost paid to Talli AS on 2026-03-01',
        '${adminLinesSql}'::jsonb, '[]'::jsonb, false, 'BANKING',
        '${adminBankId}', '${adminRequest.correlationId}', '${ownerId}'
      ) \gset admin_
      select backend_system.complete_administrative_cost_v1(
        '${adminRequestSql}'::jsonb, :'admin_ledger_entry_id'::uuid,
        :'prepared'::jsonb, '${ownerId}'
      )::text;
      commit;
    `);
    assert.equal(adminResult.entryKind, "ADMINISTRATIVE_COST");
    assert.equal(adminResult.auditRequired, true);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.entries where id = '${adminResult.entryId}'),
        (select count(*) from public.bank_transactions
          where id = '${adminBankId}' and matched_entry_id = '${adminResult.entryId}'),
        (select count(*) from backend_system.ledger_workflow_receipts
          where operation_name = 'record_administrative_cost'
            and idempotency_key = '${adminRequest.idempotencyKey}'),
        (select count(*) from public.audit_events
          where action = 'admin_cost_posted_and_matched'));
    `)), "1:1:1:0");
    const adminReplay = jsonOutput(containerName, String.raw`
      begin;
      ${workflowActorContext(ownerId)}
      select backend_system.prepare_administrative_cost_v1(
        '${adminRequestSql}'::jsonb, '${ownerId}'
      )::text;
      commit;
    `);
    assert.equal(adminReplay.replay.entryId, adminResult.entryId);
    assert.equal(adminReplay.replay.auditRequired, true);
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      ${workflowActorContext(ownerId)}
      select backend_system.prepare_administrative_cost_v1(
        '${sqlQuote(JSON.stringify({ ...adminRequest, amount: "1491.00" }))}'::jsonb,
        '${ownerId}'
      );
      commit;
    `), /ledger_idempotency_key_reused/iu);

    const failedAdminRequest = {
      ...adminRequest,
      idempotencyKey: "82000000-0000-4000-8000-000000000002",
      correlationId: "runtime-admin-coordinator-failure",
      bankTransactionId: failedAdminBankId,
      paidDate: "2026-03-02",
    };
    const failedAdminRequestSql = sqlQuote(JSON.stringify(failedAdminRequest));
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      ${workflowActorContext(ownerId)}
      select backend_system.prepare_administrative_cost_v1(
        '${failedAdminRequestSql}'::jsonb, '${ownerId}'
      ) as prepared \gset
      select * from ledger.post_entry(
        '${failedAdminRequest.idempotencyKey}', '${companyId}', 2026,
        'ADMINISTRATIVE_COST', 'Admin cost paid to Talli AS on 2026-03-02',
        '${adminLinesSql}'::jsonb, '[]'::jsonb, false, 'BANKING',
        '${failedAdminBankId}', '${failedAdminRequest.correlationId}', '${ownerId}'
      );
      select backend_system.complete_administrative_cost_v1(
        '${failedAdminRequestSql}'::jsonb, '${adminResult.entryId}'::uuid,
        :'prepared'::jsonb, '${ownerId}'
      );
      commit;
    `), /ledger_dependency_unavailable/iu);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.entries
          where source_record_id = '${failedAdminBankId}'),
        (select count(*) from public.bank_transactions
          where id = '${failedAdminBankId}' and matched_entry_id is not null),
        (select count(*) from backend_system.ledger_workflow_receipts
          where idempotency_key = '${failedAdminRequest.idempotencyKey}'));
    `)), "0:0:0");

    const suggestionRequest = {
      companyId,
      incomeYear: 2026,
      idempotencyKey: "82000000-0000-4000-8000-000000000003",
      correlationId: "runtime-suggestion-coordinator",
      acceptanceId: "83000000-0000-0000-0000-000000000003",
      bankTransactionId: suggestionBankId,
      rule: "bank_fee",
      ruleVersion: "2026-07-13.1",
    };
    const suggestionRequestSql = sqlQuote(JSON.stringify(suggestionRequest));
    const suggestionLinesSql = sqlQuote(JSON.stringify([
      { account: "7770", description: "Bankomkostninger", debit: "89.00", credit: "0.00", currency: "NOK" },
      { account: "1920", description: "Bank", debit: "0.00", credit: "89.00", currency: "NOK" },
    ]));
    const suggestionResult = jsonOutput(containerName, String.raw`
      begin;
      ${workflowActorContext(ownerId)}
      select backend_system.prepare_bank_transaction_suggestion_v1(
        '${suggestionRequestSql}'::jsonb, '${ownerId}'
      ) as prepared \gset
      select * from ledger.post_entry(
        '${suggestionRequest.idempotencyKey}', '${companyId}', 2026,
        'BANK_RULE_SUGGESTION', 'Godkjent bankforslag: Årsgebyr',
        '${suggestionLinesSql}'::jsonb, '[]'::jsonb, false, 'BANKING',
        '${suggestionRequest.acceptanceId}', '${suggestionRequest.correlationId}',
        '${ownerId}'
      ) \gset suggestion_
      select backend_system.complete_bank_transaction_suggestion_v1(
        '${suggestionRequestSql}'::jsonb, :'suggestion_ledger_entry_id'::uuid,
        :'prepared'::jsonb, '${ownerId}'
      )::text;
      commit;
    `);
    assert.equal(suggestionResult.entryKind, "BANK_RULE_SUGGESTION");
    assert.equal(suggestionResult.auditRequired, false);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from public.bank_suggestion_acceptances
          where id = '${suggestionRequest.acceptanceId}'
            and ledger_entry_id = '${suggestionResult.entryId}'),
        (select count(*) from public.audit_events
          where action = 'bank_suggestion_accepted'),
        (select count(*) from backend_system.ledger_workflow_receipts
          where operation_name = 'accept_bank_transaction_suggestion'
            and idempotency_key = '${suggestionRequest.idempotencyKey}'));
    `)), "1:1:1");
    const suggestionReplay = jsonOutput(containerName, String.raw`
      begin;
      ${workflowActorContext(ownerId)}
      select backend_system.prepare_bank_transaction_suggestion_v1(
        '${suggestionRequestSql}'::jsonb, '${ownerId}'
      )::text;
      commit;
    `);
    assert.equal(suggestionReplay.replay.entryId, suggestionResult.entryId);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select count(*) from public.audit_events where action = 'bank_suggestion_accepted';
    `)), "1");

    assert.match(psqlFailure(containerName, String.raw`
      begin;
      set local role authenticated;
      set local talli.verified_actor_id = '${ownerId}';
      select backend_system.prepare_administrative_cost_v1(
        '${adminRequestSql}'::jsonb, '${ownerId}'
      );
      commit;
    `), /permission denied/iu);

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
      insert into public.opening_balance_setups (
        id, company_id, income_year, bank_balance, share_capital,
        share_count, nominal_value, locked_at, created_by, created_at
      ) values (
        '${overlapOpeningSetupId}', '${companyId}', 2028,
        30000.00, 30000.00, 100, 300.00,
        timestamptz '2028-01-01 09:00:00+00', '${ownerId}',
        timestamptz '2028-01-01 09:00:00+00'
      );
      insert into public.ledger_entries (
        id, company_id, setup_id, income_year, entry_type, memo, lines,
        risk_flags, posted_at, created_by, created_at
      ) values (
        '${overlapOpeningEntryId}', '${companyId}', '${overlapOpeningSetupId}',
        2028, 'opening_balance', 'Expand overlap opening',
        '[{"account":"1920","description":"Bank","debit":"30000.00","credit":"0.00","currency":"NOK"},
          {"account":"2000","description":"Equity","debit":"0.00","credit":"30000.00","currency":"NOK"}]'::jsonb,
        '[]'::jsonb, timestamptz '2028-01-01 09:00:00+00', '${ownerId}',
        timestamptz '2028-01-01 09:00:00+00'
      );
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

    const contractOpeningProjection = jsonOutput(
      containerName,
      openingSnapshotCall({ actorId: reviewerId }),
    );
    assert.deepEqual(
      contractOpeningProjection.map((item) => item.incomeYear),
      [2028, 2027, 2026],
    );
    const openingPageOne = jsonOutput(
      containerName,
      openingSnapshotCall({ actorId: reviewerId, limit: 1, page: true }),
    );
    assert.equal(openingPageOne.items.length, 1);
    assert.equal(openingPageOne.items[0].incomeYear, 2028);
    assert.equal(openingPageOne.hasMore, true);
    assert.equal(typeof openingPageOne.nextCursor, "string");
    const openingPageTwo = jsonOutput(
      containerName,
      openingSnapshotCall({
        actorId: reviewerId,
        cursor: openingPageOne.nextCursor,
        limit: 1,
        page: true,
      }),
    );
    assert.equal(openingPageTwo.items[0].incomeYear, 2027);
    assert.match(
      psqlFailure(containerName, openingSnapshotCall({
        actorId: reviewerId,
        cursor: `${openingPageOne.nextCursor}tampered`,
        limit: 1,
      })),
      /ledger_invalid_cursor/iu,
    );

    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':', source_capability, source_record_id,
        created_at = timestamptz '2028-01-01 09:00:00+00')
      from ledger.entries where id = '${overlapOpeningEntryId}';
    `)), `SHAREHOLDER_REGISTER_FILING:opening-setup:${overlapOpeningSetupId}:t`);

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
    assert.equal(writerCoordinatorPrivileges(containerName), "t:f:t:f");

    assert.equal(archiveTriggerState(containerName, "ledger.entries"), "1:t");
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        role.rolcanlogin,
        role.rolinherit,
        role.rolbypassrls,
        owner.rolname = 'company_archive_projection_executor',
        has_table_privilege(
          'company_archive_projection_executor',
          'public.company_archive_source_generations', 'insert,update'
        ),
        has_table_privilege(
          'authenticated', 'public.company_archive_source_generations', 'select'
        ),
        generation.relrowsecurity
      )
      from pg_catalog.pg_roles role
      join pg_catalog.pg_proc function
        on function.oid = pg_catalog.to_regprocedure(
          'public.company_archive_track_source_write_v1()'
        )
      join pg_catalog.pg_roles owner on owner.oid = function.proowner
      join pg_catalog.pg_class generation
        on generation.oid = 'public.company_archive_source_generations'::regclass
      where role.rolname = 'company_archive_projection_executor';
    `)), "f:f:f:t:t:f:t");
    const archiveAttemptId = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select public.company_archive_begin_export_fixture('${companyId}', 2026);
    `));
    const archiveGenerationBeforePost = Number(lastOutputLine(psql(
      containerName,
      ["-Atq"],
      String.raw`
        select generation from public.company_archive_source_generations
        where company_id = '${companyId}' and income_year = 2026;
      `,
    )));

    const firstPost = jsonOutput(containerName, postTransaction());
    const archiveGenerationAfterPost = Number(lastOutputLine(psql(
      containerName,
      ["-Atq"],
      String.raw`
        select generation from public.company_archive_source_generations
        where company_id = '${companyId}' and income_year = 2026;
      `,
    )));
    assert.equal(archiveGenerationAfterPost, archiveGenerationBeforePost + 1);
    assert.match(psqlFailure(containerName, String.raw`
      select public.company_archive_complete_export_fixture('${archiveAttemptId}');
    `), /archive_export_stale/iu);
    const replayedPost = jsonOutput(containerName, postTransaction());
    assert.equal(Number(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select generation from public.company_archive_source_generations
      where company_id = '${companyId}' and income_year = 2026;
    `))), archiveGenerationAfterPost);
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

    const concurrentArchiveAttemptId = lastOutputLine(psql(
      containerName,
      ["-Atq"],
      String.raw`
        select public.company_archive_begin_export_fixture('${companyId}', 2027);
      `,
    ));
    const archiveWriter = interactivePsql(containerName);
    archiveWriter.child.stdin.write(String.raw`
      set application_name = 'ledger_archive_writer';
      begin;
      ${actorContext(ownerId)}
      ${postCall({
        incomeYear: 2027,
        idempotencyKey: "50000000-0000-4000-8000-000000000040",
        sourceRecordId: "manual:archive-concurrency",
        correlationId: "ledger-archive-concurrency",
      })}
      select 'ledger_archive_writer_ready';
    `);
    await waitForOutput(archiveWriter, /ledger_archive_writer_ready/u);

    const archiveCompletion = interactivePsql(containerName);
    archiveCompletion.child.stdin.end(String.raw`
      set application_name = 'ledger_archive_completion';
      select public.company_archive_complete_export_fixture(
        '${concurrentArchiveAttemptId}'
      );
    `);
    let completionBlocked = false;
    for (let attempt = 0; attempt < 50; attempt += 1) {
      completionBlocked = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
        select count(*) from pg_catalog.pg_stat_activity
        where application_name = 'ledger_archive_completion'
          and wait_event_type = 'Lock' and wait_event = 'advisory';
      `)) === "1";
      if (completionBlocked) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.equal(
      completionBlocked,
      true,
      "archive completion did not serialize behind the ledger write",
    );
    archiveWriter.child.stdin.end("commit;\n\\q\n");
    assert.equal((await processResult(archiveWriter)).code, 0);
    const completionResult = await processResult(archiveCompletion);
    assert.notEqual(completionResult.code, 0);
    assert.match(completionResult.stderr, /archive_export_stale/iu);

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

    const missingCorrectionId = "40000000-0000-0000-0000-000000000099";
    assert.match(psqlFailure(containerName, correctionTransaction({
      originalEntryId: missingCorrectionId,
      idempotencyKey: "63000000-0000-4000-8000-000000000002",
    })), /ledger_not_found/iu);
    assert.match(psqlFailure(containerName, correctionTransaction({
      actorId: reviewerId,
      originalEntryId: correctionOriginal.ledger_entry_id,
      idempotencyKey: "63000000-0000-4000-8000-000000000003",
    })), /ledger_forbidden/iu);
    assert.match(psqlFailure(containerName, correctionTransaction({
      originalEntryId: supportedPosting.ledger_entry_id,
      idempotencyKey: "63000000-0000-4000-8000-000000000005",
    })), /ledger_correction_original_kind_unsupported/iu);
    assert.match(psqlFailure(containerName, correctionTransaction({
      originalEntryId: correctionOriginal.ledger_entry_id,
      idempotencyKey: "63000000-0000-4000-8000-000000000006",
      correctionScope: "PRIOR_YEAR_ERROR",
    })), /ledger_prior_year_correction_policy_unresolved/iu);

    const correction = jsonOutput(containerName, correctionTransaction({
      originalEntryId: correctionOriginal.ledger_entry_id,
    }));
    assert.equal(correction.company_id, companyId);
    assert.equal(correction.income_year, 2026);
    assert.equal(correction.replayed, false);
    assert.notEqual(correction.reversal_entry_id, correctionOriginal.ledger_entry_id);
    assert.notEqual(correction.replacement_entry_id, correctionOriginal.ledger_entry_id);
    const correctionReplay = jsonOutput(containerName, correctionTransaction({
      originalEntryId: correctionOriginal.ledger_entry_id,
    }));
    assert.equal(correctionReplay.reversal_entry_id, correction.reversal_entry_id);
    assert.equal(correctionReplay.replacement_entry_id, correction.replacement_entry_id);
    assert.equal(correctionReplay.replayed, true);
    assert.match(psqlFailure(containerName, correctionTransaction({
      originalEntryId: correctionOriginal.ledger_entry_id,
      reason: "Changed retry reason",
    })), /ledger_idempotency_key_reused/iu);
    assert.match(psqlFailure(containerName, correctionTransaction({
      originalEntryId: correctionOriginal.ledger_entry_id,
      idempotencyKey: "63000000-0000-4000-8000-000000000004",
    })), /ledger_entry_already_corrected/iu);

    const correctionEvidence = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        original.entry_kind,
        reversal.entry_kind,
        replacement.entry_kind,
        (reversal.lines -> 0 ->> 'debit')::numeric,
        (reversal.lines -> 0 ->> 'credit')::numeric,
        (reversal.lines -> 1 ->> 'debit')::numeric,
        (reversal.lines -> 1 ->> 'credit')::numeric,
        reversal_source.source_capability,
        reversal_source.source_record_id,
        replacement_primary.source_capability,
        replacement_bank.source_capability,
        correction.reason)
      from ledger.entry_corrections correction
      join ledger.entries original on original.id = correction.original_entry_id
      join ledger.entries reversal on reversal.id = correction.reversal_entry_id
      join ledger.entries replacement on replacement.id = correction.replacement_entry_id
      join ledger.entry_sources reversal_source
        on reversal_source.entry_id = reversal.id and reversal_source.ordinal = 1
      join ledger.entry_sources replacement_primary
        on replacement_primary.entry_id = replacement.id and replacement_primary.ordinal = 1
      join ledger.entry_sources replacement_bank
        on replacement_bank.entry_id = replacement.id and replacement_bank.ordinal = 2
      where correction.original_entry_id = '${correctionOriginal.ledger_entry_id}';
    `));
    assert.equal(
      correctionEvidence,
      `ADMINISTRATIVE_COST:CORRECTION_REVERSAL:ADMINISTRATIVE_COST:0.00:500.00:500.00:0.00:LEDGER:${correctionOriginal.ledger_entry_id}:DOCUMENTS:BANKING:Documented category was wrong`,
    );
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      set local role ledger_executor;
      insert into ledger.entry_corrections (
        original_entry_id, reversal_entry_id, replacement_entry_id,
        company_id, income_year, reason, corrected_by
      ) values (
        '${correctionOriginal.ledger_entry_id}', '${correction.reversal_entry_id}',
        '${correction.replacement_entry_id}', '${companyId}', 2026,
        'forbidden direct write', '${ownerId}'
      );
      commit;
    `), /permission denied/iu);
    const reviewerEntries = jsonOutput(containerName, listCall({
      actorId: reviewerId,
      resource: "entries",
      limit: 100,
    }));
    const visibleCorrectionIds = new Set(reviewerEntries.items.map((entry) => entry.entryId));
    assert.equal(visibleCorrectionIds.has(correctionOriginal.ledger_entry_id), true);
    assert.equal(visibleCorrectionIds.has(correction.reversal_entry_id), true);
    assert.equal(visibleCorrectionIds.has(correction.replacement_entry_id), true);

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
        encode(extensions.digest(coalesce((select string_agg(id::text || '|' || lines::text, E'\n' order by id)
          from ledger.entries), ''), 'sha256'), 'hex'));
    `));

    psql(containerName, ["--file", rollbackPath]);
    assert.match(psqlFailure(containerName, correctionTransaction({
      originalEntryId: correctionOriginal.ledger_entry_id,
    })), /ledger_cutover_inactive/iu);
    assert.equal(writerCoordinatorPrivileges(containerName), "f:f:f:f");
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        pg_catalog.has_function_privilege(
          'authenticated', 'public.accept_bank_transaction_suggestion(uuid,text,text)',
          'execute'
        ),
        pg_catalog.has_function_privilege(
          'authenticated', 'public.record_share_sale_fifo(uuid,uuid,integer,uuid,date,bigint,numeric,uuid,uuid,text)',
          'execute'
        ));
    `)), "t:t");
    const rollbackOpeningProjection = jsonOutput(
      containerName,
      openingSnapshotCall({ actorId: readOnlyId }),
    );
    assert.deepEqual(
      rollbackOpeningProjection.map((item) => item.incomeYear),
      [2028, 2027, 2026],
    );
    assert.equal(
      archiveTriggerState(containerName, "public.ledger_entries"),
      "1:t",
    );
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select setup_id from public.ledger_entries
      where id = '${overlapOpeningEntryId}';
    `)), overlapOpeningSetupId);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select pg_catalog.bool_and(entry_type = pg_catalog.lower(entry_type))
      from public.ledger_entries;
    `)), "t");
    const overlapPrivileges = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        has_table_privilege('authenticated', 'public.ledger_entries', 'insert'),
        has_table_privilege('authenticated', 'public.period_locks', 'insert'),
        has_table_privilege('authenticated', 'public.opening_balance_setups', 'insert'),
        has_table_privilege('service_role', 'public.ledger_entries', 'insert'));
    `));
    assert.equal(overlapPrivileges, "t:t:t:f");
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      set local role authenticated;
      set local request.jwt.claim.sub = '${ownerId}';
      insert into public.ledger_entries (
        id, company_id, income_year, entry_type, memo, lines, risk_flags,
        posted_at, created_by, created_at
      ) values (
        '64000000-0000-4000-8000-000000000001', '${companyId}', 2028,
        'correction_reversal', 'Forged rollback reversal',
        '[{"account":"7795","description":"Cost","debit":"0.00","credit":"25.00","currency":"NOK"},
          {"account":"1920","description":"Bank","debit":"25.00","credit":"0.00","currency":"NOK"}]'::jsonb,
        '[]'::jsonb, timestamptz '2028-03-01 09:00:00+00', '${ownerId}',
        timestamptz '2028-03-01 09:00:00+00'
      );
      commit;
    `), /ledger_invalid_input/iu);

    const rollbackGenerationBeforeInsert = Number(lastOutputLine(psql(
      containerName,
      ["-Atq"],
      String.raw`
        select coalesce((
          select generation from public.company_archive_source_generations
          where company_id = '${companyId}' and income_year = 2028
        ), 0::bigint);
      `,
    )));
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
    assert.equal(Number(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select generation from public.company_archive_source_generations
      where company_id = '${companyId}' and income_year = 2028;
    `))), rollbackGenerationBeforeInsert + 1);

    psql(containerName, ["--file", expandPath]);
    psql(containerName, ["--file", coordinatorPath]);
    psql(containerName, ["--file", supportedPatternsPath]);
    psql(containerName, ["--file", correctionsPath]);
    psql(containerName, ["--file", contractPath]);
    assert.deepEqual(
      jsonOutput(containerName, openingSnapshotCall({ actorId: ownerId }))
        .map((item) => item.incomeYear),
      [2028, 2027, 2026],
    );
    assert.equal(archiveTriggerState(containerName, "ledger.entries"), "1:t");
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select source_record_id from ledger.entries
      where id = '${overlapOpeningEntryId}';
    `)), `opening-setup:${overlapOpeningSetupId}`);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select pg_catalog.bool_and(entry_kind = pg_catalog.upper(entry_kind))
      from ledger.entries;
    `)), "t");

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
    assert.equal(writerCoordinatorPrivileges(containerName), "t:f:t:f");

    const recutoverReplay = jsonOutput(containerName, postTransaction());
    assert.equal(recutoverReplay.ledger_entry_id, firstPost.ledger_entry_id);
    assert.equal(recutoverReplay.replayed, true);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select count(*) from backend_system.ledger_command_receipts
      where idempotency_key = '50000000-0000-4000-8000-000000000001';
    `)), "1");
    const recutoverCorrectionReplay = jsonOutput(containerName, correctionTransaction({
      originalEntryId: correctionOriginal.ledger_entry_id,
    }));
    assert.equal(recutoverCorrectionReplay.reversal_entry_id, correction.reversal_entry_id);
    assert.equal(recutoverCorrectionReplay.replacement_entry_id, correction.replacement_entry_id);
    assert.equal(recutoverCorrectionReplay.replayed, true);

    const durableAfterRecutover = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.entries) - 1,
        (select count(*) from ledger.period_locks),
        (select count(*) from backend_system.ledger_command_receipts),
        encode(extensions.digest(coalesce((select string_agg(id::text || '|' || lines::text, E'\n' order by id)
          from ledger.entries where id <> '${malformedLegacyEntryId}'), ''),
          'sha256'), 'hex'));
    `));
    assert.equal(durableAfterRecutover, durableBeforeRollback);
  } finally {
    docker(["rm", "--force", containerName]);
  }
});
