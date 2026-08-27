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
const companyYearClosePath = "/repo/supabase/migrations/20260827104000_ledger_company_year_close.sql";
const receivedDividendPath = "/repo/supabase/migrations/20260827105000_ledger_received_dividend_lifecycle.sql";
const bankLoanPath = "/repo/supabase/migrations/20260827106000_ledger_bank_loan_lifecycle.sql";
const cashCapitalIncreasePath = "/repo/supabase/migrations/20260827107000_ledger_cash_capital_increase_lifecycle.sql";
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
), (
  '70000000-0000-0000-0000-000000000004', '${otherCompanyId}', 2026,
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
), (
  '71000000-0000-0000-0000-000000000004', '${otherCompanyId}', 2026,
  '70000000-0000-0000-0000-000000000004', '2026.1',
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
), (
  '72000000-0000-0000-0000-000000000004',
  '71000000-0000-0000-0000-000000000004', '${otherCompanyId}', 2026,
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

function exactDatabaseError(errorCode) {
  return new RegExp(`ERROR:\\s+${errorCode}(?:\\r?\\n|$)`, "u");
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

function numericSql(value) {
  return value === null ? "null::numeric" : `'${sqlQuote(value)}'::numeric`;
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

function receivedDividendDecisionTransaction({
  actorId = ownerId,
  verifiedSubject = actorId,
  company = companyId,
  incomeYear = 2026,
  idempotencyKey = "66000000-0000-4000-8000-000000000001",
  memo = "Final investment-dividend decision recognized",
  lines = [
    { account: "1530", description: "Dividend receivable", debit: "5000.00", credit: "0.00", currency: "NOK" },
    { account: "8070", description: "Dividend income", debit: "0.00", credit: "5000.00", currency: "NOK" },
  ],
  sourceRecordId = "received-dividend-decision-runtime",
  correlationId = "received-dividend-decision-runtime",
  eventDate = "2026-04-20",
  sources = [
    { role: "PRIMARY", capability: "INVESTMENTS", recordId: "received-dividend-decision-runtime", revision: 1, factSha256: "1".repeat(64) },
    { role: "CORROBORATING", capability: "DOCUMENTS", recordId: "received-dividend-document-runtime", revision: 1, factSha256: "2".repeat(64) },
    { role: "CORROBORATING", capability: "COMPANY_TAX_FILING", recordId: "received-dividend-tax-runtime", revision: 1, factSha256: "3".repeat(64) },
  ],
} = {}) {
  return String.raw`
begin;
${actorContext(actorId)}
select row_to_json(posted)::text
from ledger.record_received_dividend_decision_v1(
  '${sqlQuote(idempotencyKey)}'::text, '${company}'::uuid, ${incomeYear}::integer,
  '${sqlQuote(memo)}'::text, '${sqlQuote(JSON.stringify(lines))}'::jsonb,
  'INVESTMENTS'::text, '${sqlQuote(sourceRecordId)}'::text,
  '${sqlQuote(correlationId)}'::text, '${verifiedSubject}'::text,
  '${eventDate}'::date, 'ledger-supported-patterns-2026.1'::text,
  '${sqlQuote(JSON.stringify(sources))}'::jsonb
) posted;
commit;
`;
}

function receivedDividendPaymentTransaction({
  decisionEntryId,
  actorId = ownerId,
  verifiedSubject = actorId,
  company = companyId,
  incomeYear = 2026,
  idempotencyKey = "66000000-0000-4000-8000-000000000002",
  memo = "Investment-dividend receivable settled",
  lines = [
    { account: "1920", description: "Dividend received", debit: "5000.00", credit: "0.00", currency: "NOK" },
    { account: "1530", description: "Dividend receivable settled", debit: "0.00", credit: "5000.00", currency: "NOK" },
  ],
  sourceRecordId = "received-dividend-payment-runtime",
  correlationId = "received-dividend-payment-runtime",
  eventDate = "2026-04-25",
  sources = [
    { role: "PRIMARY", capability: "INVESTMENTS", recordId: "received-dividend-payment-runtime", revision: 1, factSha256: "4".repeat(64) },
    { role: "CORROBORATING", capability: "BANKING", recordId: "received-dividend-bank-runtime", revision: 1, factSha256: "5".repeat(64) },
  ],
} = {}) {
  return String.raw`
begin;
${actorContext(actorId)}
select row_to_json(posted)::text
from ledger.record_received_dividend_payment_v1(
  '${sqlQuote(idempotencyKey)}'::text, '${company}'::uuid, ${incomeYear}::integer,
  '${decisionEntryId}'::uuid,
  '${sqlQuote(memo)}'::text, '${sqlQuote(JSON.stringify(lines))}'::jsonb,
  'INVESTMENTS'::text, '${sqlQuote(sourceRecordId)}'::text,
  '${sqlQuote(correlationId)}'::text, '${verifiedSubject}'::text,
  '${eventDate}'::date, 'ledger-supported-patterns-2026.1'::text,
  '${sqlQuote(JSON.stringify(sources))}'::jsonb
) posted;
commit;
`;
}

function bankLoanDisbursementTransaction({
  actorId = ownerId,
  verifiedSubject = actorId,
  company = companyId,
  incomeYear = 2026,
  idempotencyKey = "67000000-0000-4000-8000-000000000001",
  loanReference = "bank-loan:runtime-1",
  principalNok = "100000.00",
  memo = "Ordinary NOK bank-loan disbursement",
  lines = [
    { account: "1920", description: "Bank-loan proceeds", debit: "100000.00", credit: "0.00", currency: "NOK" },
    { account: "2220", description: "Bank-loan principal", debit: "0.00", credit: "100000.00", currency: "NOK" },
  ],
  sourceRecordId = "bank-loan-disbursement-runtime",
  correlationId = "bank-loan-disbursement-runtime",
  eventDate = "2026-03-15",
  sources = [
    { role: "PRIMARY", capability: "BANKING", recordId: "bank-loan-disbursement-runtime", revision: 1, factSha256: "d".repeat(64) },
  ],
} = {}) {
  const persistedSources = sources.length === 1
    ? [...sources, {
        role: "CORROBORATING",
        capability: "DOCUMENTS",
        recordId: `${sourceRecordId}:document`,
        revision: 1,
        factSha256: "a".repeat(64),
      }]
    : sources;
  return String.raw`
begin;
${actorContext(actorId)}
select row_to_json(posted)::text
from ledger.record_bank_loan_disbursement_v1(
  '${sqlQuote(idempotencyKey)}'::text, '${company}'::uuid, ${incomeYear}::integer,
  '${sqlQuote(loanReference)}'::text, ${numericSql(principalNok)},
  '${sqlQuote(memo)}'::text, '${sqlQuote(JSON.stringify(lines))}'::jsonb,
  'BANKING'::text, '${sqlQuote(sourceRecordId)}'::text,
  '${sqlQuote(correlationId)}'::text, '${verifiedSubject}'::text,
  '${eventDate}'::date, 'ledger-supported-patterns-2026.1'::text,
  '${sqlQuote(JSON.stringify(persistedSources))}'::jsonb
) posted;
commit;
`;
}

function bankLoanPaymentLines({ principalNok, interestNok, feeNok }) {
  const lines = [];
  if (Number(principalNok) > 0) {
    lines.push({
      account: "2220",
      description: "Bank-loan principal paid",
      debit: Number(principalNok).toFixed(2),
      credit: "0.00",
      currency: "NOK",
    });
  }
  if (Number(interestNok) > 0) {
    lines.push({
      account: "8150",
      description: "Bank-loan interest",
      debit: Number(interestNok).toFixed(2),
      credit: "0.00",
      currency: "NOK",
    });
  }
  if (Number(feeNok) > 0) {
    lines.push({
      account: "7770",
      description: "Bank-loan fee",
      debit: Number(feeNok).toFixed(2),
      credit: "0.00",
      currency: "NOK",
    });
  }
  lines.push({
    account: "1920",
    description: "Paid from bank",
    debit: "0.00",
    credit: (Number(principalNok) + Number(interestNok) + Number(feeNok)).toFixed(2),
    currency: "NOK",
  });
  return lines;
}

function bankLoanPaymentTransaction({
  actorId = ownerId,
  verifiedSubject = actorId,
  company = companyId,
  incomeYear = 2026,
  idempotencyKey = "67000000-0000-4000-8000-000000000002",
  loanReference = "bank-loan:runtime-1",
  principalNok = "25000.00",
  interestNok = "1000.00",
  feeNok = "0.00",
  memo = "Allocated ordinary NOK bank-loan payment",
  lines = bankLoanPaymentLines({ principalNok, interestNok, feeNok }),
  sourceRecordId = "bank-loan-payment-runtime",
  correlationId = "bank-loan-payment-runtime",
  eventDate = "2026-06-15",
  sources = [
    { role: "PRIMARY", capability: "BANKING", recordId: "bank-loan-payment-runtime", revision: 1, factSha256: "e".repeat(64) },
  ],
} = {}) {
  const persistedSources = sources.length === 1
    ? [...sources, {
        role: "CORROBORATING",
        capability: "DOCUMENTS",
        recordId: `${sourceRecordId}:document`,
        revision: 1,
        factSha256: "b".repeat(64),
      }]
    : sources;
  return String.raw`
begin;
${actorContext(actorId)}
select row_to_json(posted)::text
from ledger.record_bank_loan_payment_v1(
  '${sqlQuote(idempotencyKey)}'::text, '${company}'::uuid, ${incomeYear}::integer,
  '${sqlQuote(loanReference)}'::text, ${numericSql(principalNok)},
  ${numericSql(interestNok)}, ${numericSql(feeNok)},
  '${sqlQuote(memo)}'::text, '${sqlQuote(JSON.stringify(lines))}'::jsonb,
  'BANKING'::text, '${sqlQuote(sourceRecordId)}'::text,
  '${sqlQuote(correlationId)}'::text, '${verifiedSubject}'::text,
  '${eventDate}'::date, 'ledger-supported-patterns-2026.1'::text,
  '${sqlQuote(JSON.stringify(persistedSources))}'::jsonb
) posted;
commit;
`;
}

function cashCapitalIncreaseSources(phase, sourceRecordId) {
  const sources = [{
    role: "PRIMARY",
    capability: "CORPORATE_GOVERNANCE",
    recordId: sourceRecordId,
    revision: 1,
    factSha256: "1".repeat(64),
  }];
  if (phase !== "BINDING_SUBSCRIPTION") {
    sources.push({
      role: "CORROBORATING",
      capability: "BANKING",
      recordId: `${sourceRecordId}:bank`,
      revision: 1,
      factSha256: "2".repeat(64),
    });
  }
  sources.push({
    role: "CORROBORATING",
    capability: "DOCUMENTS",
    recordId: `${sourceRecordId}:documents`,
    revision: 1,
    factSha256: "3".repeat(64),
  });
  if (phase === "REGISTERED") {
    sources.push({
      role: "CORROBORATING",
      capability: "SHAREHOLDER_REGISTER_FILING",
      recordId: `${sourceRecordId}:shareholder-register`,
      revision: 1,
      factSha256: "4".repeat(64),
    });
  }
  return sources;
}

function cashCapitalIncreaseLines(phase, nominalIncreaseNok, sharePremiumNok) {
  const total = (Number(nominalIncreaseNok) + Number(sharePremiumNok)).toFixed(2);
  if (phase === "BINDING_SUBSCRIPTION") {
    return [
      { account: "1500", description: "Subscription receivable", debit: total, credit: "0.00", currency: "NOK" },
      { account: "2030", description: "Unregistered capital increase", debit: "0.00", credit: total, currency: "NOK" },
    ];
  }
  if (phase === "RESTRICTED_PAYMENT") {
    return [
      { account: "1921", description: "Restricted contribution bank", debit: total, credit: "0.00", currency: "NOK" },
      { account: "1500", description: "Subscription receivable", debit: "0.00", credit: total, currency: "NOK" },
    ];
  }
  return [
    { account: "2030", description: "Unregistered capital increase", debit: total, credit: "0.00", currency: "NOK" },
    { account: "2000", description: "Registered share capital", debit: "0.00", credit: Number(nominalIncreaseNok).toFixed(2), currency: "NOK" },
    { account: "2020", description: "Share premium", debit: "0.00", credit: Number(sharePremiumNok).toFixed(2), currency: "NOK" },
    { account: "1920", description: "Released contribution bank", debit: total, credit: "0.00", currency: "NOK" },
    { account: "1921", description: "Restricted contribution bank", debit: "0.00", credit: total, currency: "NOK" },
  ];
}

function cashCapitalIncreaseTransaction({
  phase,
  actorId = ownerId,
  verifiedSubject = actorId,
  company = companyId,
  incomeYear = 2026,
  idempotencyKey,
  capitalIncreaseReference = "capital-increase:runtime-1",
  nominalIncreaseNok = "10000.00",
  sharePremiumNok = "5000.00",
  memo,
  lines = cashCapitalIncreaseLines(phase, nominalIncreaseNok, sharePremiumNok),
  sourceRecordId,
  correlationId = sourceRecordId,
  eventDate,
  sources = cashCapitalIncreaseSources(phase, sourceRecordId),
}) {
  const functionName = {
    BINDING_SUBSCRIPTION: "record_cash_capital_increase_subscription_v1",
    RESTRICTED_PAYMENT: "record_cash_capital_increase_restricted_payment_v1",
    REGISTERED: "record_cash_capital_increase_registration_v1",
  }[phase];
  return String.raw`
begin;
${actorContext(actorId)}
select row_to_json(posted)::text
from ledger.${functionName}(
  '${sqlQuote(idempotencyKey)}'::text, '${company}'::uuid, ${incomeYear}::integer,
  '${sqlQuote(capitalIncreaseReference)}'::text,
  ${numericSql(nominalIncreaseNok)}, ${numericSql(sharePremiumNok)},
  '${sqlQuote(memo)}'::text, '${sqlQuote(JSON.stringify(lines))}'::jsonb,
  'CORPORATE_GOVERNANCE'::text, '${sqlQuote(sourceRecordId)}'::text,
  '${sqlQuote(correlationId)}'::text, '${verifiedSubject}'::text,
  '${eventDate}'::date, 'ledger-supported-patterns-2026.1'::text,
  '${sqlQuote(JSON.stringify(sources))}'::jsonb
) posted;
commit;
`;
}

function correctionCall({
  actorId = ownerId,
  verifiedSubject = actorId,
  company = companyId,
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
  incomeYear = 2026,
  eventDate = "2026-08-27",
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
  '${company}'::uuid,
  ${incomeYear}::integer,
  '${originalEntryId}'::uuid,
  '${sqlQuote(reason)}'::text,
  '${replacementKind}'::text,
  '${sqlQuote(replacementMemo)}'::text,
  '${sqlQuote(JSON.stringify(replacementLines))}'::jsonb,
  '${sqlQuote(correlationId)}'::text,
  '${verifiedSubject}'::text,
  '${eventDate}'::date,
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

function reconstructionEvidence({
  documentsReady = true,
  asOf = "2026-08-27",
  incomeYear = Number(asOf.slice(0, 4)),
} = {}) {
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
      ? `${incomeYear}-01-01`
      : null,
    coverageThrough: ["BANK_MOVEMENTS", "CURRENT_YEAR_ACTIVITY"].includes(kind)
      ? asOf
      : null,
    gapCode: kind === "DOCUMENTS" && !documentsReady ? "DOCUMENTS_INCOMPLETE" : null,
  }));
}

function reconstructionCall({
  actorId = ownerId,
  company = companyId,
  incomeYear = 2026,
  idempotencyKey = "61000000-0000-4000-8000-000000000001",
  documentsReady = true,
  asOf = "2026-08-27",
} = {}) {
  const evidence = reconstructionEvidence({ documentsReady, asOf, incomeYear });
  const state = documentsReady ? "READY" : "BLOCKED";
  const gaps = documentsReady ? "array[]::text[]" : "array['DOCUMENTS_INCOMPLETE']::text[]";
  return String.raw`
begin;
set local role ledger_executor;
${actorContext(actorId)}
select row_to_json(assessment)::text
from ledger.record_reconstruction_assessment(
  '${idempotencyKey}'::text,
  '${company}'::uuid,
  ${incomeYear}::integer,
  '${asOf}'::date,
  '${sqlQuote(JSON.stringify(evidence))}'::jsonb,
  '${state}'::text,
  ${gaps},
  'ledger-reconstruction-runtime'::text,
  '${actorId}'::text
) assessment;
commit;
`;
}

function companyYearCloseEvidence({
  periodEnd = "2026-12-31",
  ledgerStateDigest,
  statuses = {},
  omit = [],
  revision = 1,
} = {}) {
  const outputKinds = [
    "INVESTMENTS",
    "CORPORATE_GOVERNANCE",
    "SHAREHOLDER_REGISTER_FILING",
    "COMPANY_TAX_FILING",
    "ANNUAL_ACCOUNTS_FILING",
    "SAF_T",
    "COMPANY_ARCHIVE",
  ];
  const pairs = [
    ["BANK_ROWS_RESOLVED", "BANKING", "UNRESOLVED_BANK_ROW"],
    ["MATERIAL_BALANCES_DOCUMENTED", "DOCUMENTS", "MATERIAL_BALANCE_UNDOCUMENTED"],
    ["REPORTING_RECONCILED", "LEDGER", "REPORTING_NOT_RECONCILED"],
  ];
  return pairs.filter(([kind]) => !omit.includes(kind)).map(([
    kind, issuer, gapCode,
  ], index) => {
    const status = statuses[kind] ?? "CONFIRMED";
    return {
      kind,
      issuer,
      status,
      sourceRecordId: `close:${issuer.toLowerCase()}:${index}`,
      revision,
      factSha256: (index + 10).toString(16).padStart(64, "0"),
      ledgerStateDigest,
      coverageThrough: periodEnd,
      gapCode: status === "CONFIRMED" ? null : gapCode,
      outputs: kind === "REPORTING_RECONCILED" && status === "CONFIRMED"
        ? outputKinds.map((outputKind, outputIndex) => ({
            kind: outputKind,
            sourceRecordId: `close-output:${outputKind.toLowerCase()}:${revision}`,
            revision,
            factSha256: (outputIndex + 20 + revision).toString(16).padStart(64, "0"),
          }))
        : [],
    };
  });
}

function companyYearCloseCall({
  actorId = ownerId,
  verifiedSubject = actorId,
  company = companyId,
  incomeYear = 2026,
  idempotencyKey = "65000000-0000-4000-8000-000000000001",
  periodEnd = "2026-12-31",
  reason = "Evidence-complete company-year close",
  reconstructionAssessmentId,
  reconstructionDigest,
  reconstructionLedgerStateDigest,
  evidence = companyYearCloseEvidence({
    periodEnd,
    ledgerStateDigest: reconstructionLedgerStateDigest,
  }),
  derivedState = "CLOSED",
  gapCodes = [],
  correlationId = "ledger-company-year-close-runtime",
} = {}) {
  const gapsSql = gapCodes.length === 0
    ? "array[]::text[]"
    : `array[${gapCodes.map((gap) => `'${sqlQuote(gap)}'`).join(",")}]::text[]`;
  return String.raw`
select row_to_json(closed)::text
from ledger.close_company_year_v1(
  '${sqlQuote(idempotencyKey)}'::text,
  '${company}'::uuid,
  ${incomeYear}::integer,
  '${periodEnd}'::date,
  '${sqlQuote(reason)}'::text,
  '${reconstructionAssessmentId}'::uuid,
  '${reconstructionDigest}'::text,
  '${sqlQuote(JSON.stringify(evidence))}'::jsonb,
  '${derivedState}'::text,
  ${gapsSql},
  '${sqlQuote(correlationId)}'::text,
  '${verifiedSubject}'::text
) closed;
`;
}

function companyYearCloseTransaction(options = {}) {
  const actorId = options.actorId ?? ownerId;
  return String.raw`
begin;
${actorContext(actorId)}
${companyYearCloseCall(options)}
commit;
`;
}

function companyYearCloseReplayTransaction({
  actorId = ownerId,
  verifiedSubject = actorId,
  idempotencyKey = "65000000-0000-4000-8000-000000000001",
  periodEnd = "2026-12-31",
  reason = "Evidence-complete company-year close",
  reconstructionAssessmentId,
  reconstructionDigest,
  reconstructionLedgerStateDigest,
  evidence = companyYearCloseEvidence({
    periodEnd,
    ledgerStateDigest: reconstructionLedgerStateDigest,
  }),
  correlationId = "ledger-company-year-close-runtime",
} = {}) {
  return String.raw`
begin;
${actorContext(actorId)}
select row_to_json(close_replay)::text
from ledger.get_company_year_close_replay_v1(
  '${sqlQuote(idempotencyKey)}'::text,
  '${companyId}'::uuid,
  2026::integer,
  '${periodEnd}'::date,
  '${sqlQuote(reason)}'::text,
  '${reconstructionAssessmentId}'::uuid,
  '${reconstructionDigest}'::text,
  '${sqlQuote(JSON.stringify(evidence))}'::jsonb,
  '${sqlQuote(correlationId)}'::text,
  '${verifiedSubject}'::text
) close_replay;
commit;
`;
}

function latestCompanyYearCloseTransaction({ actorId = ownerId } = {}) {
  return String.raw`
begin;
${actorContext(actorId)}
select row_to_json(assessment)::text
from ledger.get_company_year_close_assessment_v1(
  '${companyId}'::uuid, 2026::integer, '${actorId}'::text
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
    psql(containerName, ["--file", companyYearClosePath]);
    psql(containerName, ["--file", receivedDividendPath]);
    psql(containerName, ["--file", bankLoanPath]);
    psql(containerName, ["--file", cashCapitalIncreasePath]);

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
            'entry_corrections', 'company_year_close_assessments',
            'company_year_close_evidence', 'company_year_close_locks',
            'company_year_close_reporting_outputs',
            'received_dividend_decisions', 'received_dividend_settlements',
            'bank_loan_anchors', 'bank_loan_payment_allocations',
            'cash_capital_increase_phases'
          ]))
        or (namespace.nspname = 'backend_system'
          and class.relname = any(array[
            'ledger_command_receipts', 'ledger_workflow_receipts'
          ]));
    `));
    assert.equal(
      forcedRls,
      "backend_system.ledger_command_receipts:true:true,backend_system.ledger_workflow_receipts:true:true,ledger.bank_loan_anchors:true:true,ledger.bank_loan_payment_allocations:true:true,ledger.cash_capital_increase_phases:true:true,ledger.company_year_close_assessments:true:true,ledger.company_year_close_evidence:true:true,ledger.company_year_close_locks:true:true,ledger.company_year_close_reporting_outputs:true:true,ledger.entries:true:true,ledger.entry_contexts:true:true,ledger.entry_corrections:true:true,ledger.entry_sources:true:true,ledger.period_locks:true:true,ledger.received_dividend_decisions:true:true,ledger.received_dividend_settlements:true:true,ledger.reconstruction_assessments:true:true,ledger.reconstruction_evidence:true:true",
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

    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        has_function_privilege(
          'ledger_executor',
          'ledger.record_received_dividend_decision_v1(text,uuid,integer,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ),
        has_function_privilege(
          'ledger_executor',
          'ledger.record_received_dividend_payment_v1(text,uuid,integer,uuid,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ),
        has_function_privilege(
          'authenticated',
          'ledger.record_received_dividend_decision_v1(text,uuid,integer,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ),
        has_table_privilege(
          'ledger_executor', 'ledger.received_dividend_decisions', 'insert'
        ),
        has_table_privilege(
          'ledger_executor', 'ledger.received_dividend_settlements', 'insert'
        ));
    `)), "t:t:f:f:f");

    const receivedDividendDecision = jsonOutput(
      containerName,
      receivedDividendDecisionTransaction(),
    );
    assert.equal(receivedDividendDecision.entry_kind, "DIVIDEND_RECEIVED");
    assert.equal(receivedDividendDecision.replayed, false);
    const receivedDividendDecisionReplay = jsonOutput(
      containerName,
      receivedDividendDecisionTransaction(),
    );
    assert.equal(
      receivedDividendDecisionReplay.ledger_entry_id,
      receivedDividendDecision.ledger_entry_id,
    );
    assert.equal(receivedDividendDecisionReplay.replayed, true);
    assert.deepEqual(jsonOutput(containerName, String.raw`
      select pg_catalog.jsonb_build_object(
        'decisionEntryId', decision.decision_entry_id,
        'companyId', decision.company_id,
        'incomeYear', decision.income_year,
        'lines', entry.lines
      )::text
      from ledger.received_dividend_decisions decision
      join ledger.entries entry on entry.id = decision.decision_entry_id
      where decision.decision_entry_id = '${receivedDividendDecision.ledger_entry_id}';
    `), {
      companyId,
      decisionEntryId: receivedDividendDecision.ledger_entry_id,
      incomeYear: 2026,
      lines: [
        { account: "1530", credit: 0, currency: "NOK", debit: 5000, description: "Dividend receivable" },
        { account: "8070", credit: 5000, currency: "NOK", debit: 0, description: "Dividend income" },
      ],
    });

    const receivedDividendState = () => lastOutputLine(psql(
      containerName,
      ["-Atq"],
      String.raw`
        select concat_ws(':',
          (select count(*) from ledger.entries),
          (select count(*) from ledger.entry_contexts),
          (select count(*) from ledger.entry_sources),
          (select count(*) from ledger.received_dividend_decisions),
          (select count(*) from ledger.received_dividend_settlements),
          (select count(*) from backend_system.ledger_command_receipts));
      `,
    ));
    const decisionOnlyState = receivedDividendState();
    const changedDecisionSources = [
      { role: "PRIMARY", capability: "INVESTMENTS", recordId: "received-dividend-decision-runtime", revision: 1, factSha256: "9".repeat(64) },
      { role: "CORROBORATING", capability: "DOCUMENTS", recordId: "received-dividend-document-runtime", revision: 1, factSha256: "2".repeat(64) },
      { role: "CORROBORATING", capability: "COMPANY_TAX_FILING", recordId: "received-dividend-tax-runtime", revision: 1, factSha256: "3".repeat(64) },
    ];
    assert.match(psqlFailure(containerName, receivedDividendDecisionTransaction({
      sources: changedDecisionSources,
    })), /ledger_idempotency_key_reused/iu);
    assert.equal(receivedDividendState(), decisionOnlyState);
    assert.match(psqlFailure(containerName, receivedDividendDecisionTransaction({
      idempotencyKey: "66000000-0000-4000-8000-000000000003",
    })), /ledger_idempotency_key_reused/iu);
    assert.equal(receivedDividendState(), decisionOnlyState);
    assert.match(psqlFailure(containerName, receivedDividendDecisionTransaction({
      actorId: reviewerId,
      idempotencyKey: "66000000-0000-4000-8000-000000000004",
    })), /ledger_forbidden/iu);
    assert.equal(receivedDividendState(), decisionOnlyState);

    const backdatedPaymentSourceRecordId = "received-dividend-backdated-payment-runtime";
    assert.match(psqlFailure(containerName, receivedDividendPaymentTransaction({
      decisionEntryId: receivedDividendDecision.ledger_entry_id,
      eventDate: "2026-04-19",
      idempotencyKey: "66000000-0000-4000-8000-000000000012",
      sourceRecordId: backdatedPaymentSourceRecordId,
      sources: [
        {
          role: "PRIMARY",
          capability: "INVESTMENTS",
          recordId: backdatedPaymentSourceRecordId,
          revision: 1,
          factSha256: "d".repeat(64),
        },
        {
          role: "CORROBORATING",
          capability: "BANKING",
          recordId: "received-dividend-backdated-bank-runtime",
          revision: 1,
          factSha256: "e".repeat(64),
        },
      ],
    })), /ledger_received_dividend_decision_invalid/iu);
    assert.equal(receivedDividendState(), decisionOnlyState);

    const absentDecisionId = "67000000-0000-4000-8000-000000000099";
    assert.match(psqlFailure(containerName, receivedDividendPaymentTransaction({
      decisionEntryId: absentDecisionId,
      idempotencyKey: "66000000-0000-4000-8000-000000000005",
    })), /ledger_received_dividend_decision_invalid/iu);
    assert.equal(receivedDividendState(), decisionOnlyState);
    assert.match(psqlFailure(containerName, receivedDividendPaymentTransaction({
      decisionEntryId: receivedDividendDecision.ledger_entry_id,
      actorId: otherOwnerId,
      company: otherCompanyId,
      idempotencyKey: "66000000-0000-4000-8000-000000000007",
    })), /ledger_received_dividend_decision_invalid/iu);
    assert.equal(receivedDividendState(), decisionOnlyState);
    const shortPaymentLines = [
      { account: "1920", description: "Dividend received", debit: "4000.00", credit: "0.00", currency: "NOK" },
      { account: "1530", description: "Dividend receivable settled", debit: "0.00", credit: "4000.00", currency: "NOK" },
    ];
    assert.match(psqlFailure(containerName, receivedDividendPaymentTransaction({
      decisionEntryId: receivedDividendDecision.ledger_entry_id,
      idempotencyKey: "66000000-0000-4000-8000-000000000008",
      lines: shortPaymentLines,
    })), /ledger_received_dividend_decision_invalid/iu);
    assert.equal(receivedDividendState(), decisionOnlyState);

    const receivedDividendPayment = jsonOutput(containerName,
      receivedDividendPaymentTransaction({
        decisionEntryId: receivedDividendDecision.ledger_entry_id,
      }));
    assert.equal(receivedDividendPayment.entry_kind, "DIVIDEND_RECEIVED");
    assert.equal(receivedDividendPayment.replayed, false);
    const receivedDividendPaymentReplay = jsonOutput(containerName,
      receivedDividendPaymentTransaction({
        decisionEntryId: receivedDividendDecision.ledger_entry_id,
      }));
    assert.equal(
      receivedDividendPaymentReplay.ledger_entry_id,
      receivedDividendPayment.ledger_entry_id,
    );
    assert.equal(receivedDividendPaymentReplay.replayed, true);
    assert.deepEqual(jsonOutput(containerName, String.raw`
      select pg_catalog.jsonb_build_object(
        'decisionEntryId', settlement.decision_entry_id,
        'paymentEntryId', settlement.payment_entry_id,
        'companyId', settlement.company_id,
        'decisionIncomeYear', settlement.decision_income_year,
        'paymentIncomeYear', settlement.payment_income_year,
        'lines', entry.lines
      )::text
      from ledger.received_dividend_settlements settlement
      join ledger.entries entry on entry.id = settlement.payment_entry_id
      where settlement.decision_entry_id = '${receivedDividendDecision.ledger_entry_id}';
    `), {
      companyId,
      decisionIncomeYear: 2026,
      decisionEntryId: receivedDividendDecision.ledger_entry_id,
      lines: [
        { account: "1920", credit: 0, currency: "NOK", debit: 5000, description: "Dividend received" },
        { account: "1530", credit: 5000, currency: "NOK", debit: 0, description: "Dividend receivable settled" },
      ],
      paymentIncomeYear: 2026,
      paymentEntryId: receivedDividendPayment.ledger_entry_id,
    });
    const settledState = receivedDividendState();
    const changedPaymentSources = [
      { role: "PRIMARY", capability: "INVESTMENTS", recordId: "received-dividend-payment-runtime", revision: 1, factSha256: "8".repeat(64) },
      { role: "CORROBORATING", capability: "BANKING", recordId: "received-dividend-bank-runtime", revision: 1, factSha256: "5".repeat(64) },
    ];
    assert.match(psqlFailure(containerName, receivedDividendPaymentTransaction({
      decisionEntryId: receivedDividendDecision.ledger_entry_id,
      sources: changedPaymentSources,
    })), /ledger_idempotency_key_reused/iu);
    assert.equal(receivedDividendState(), settledState);
    assert.match(psqlFailure(containerName, receivedDividendPaymentTransaction({
      decisionEntryId: receivedDividendDecision.ledger_entry_id,
      idempotencyKey: "66000000-0000-4000-8000-000000000009",
      sourceRecordId: "received-dividend-second-payment-runtime",
      sources: [
        { role: "PRIMARY", capability: "INVESTMENTS", recordId: "received-dividend-second-payment-runtime", revision: 1, factSha256: "6".repeat(64) },
        { role: "CORROBORATING", capability: "BANKING", recordId: "received-dividend-second-bank-runtime", revision: 1, factSha256: "7".repeat(64) },
      ],
    })), /ledger_received_dividend_already_settled/iu);
    assert.equal(receivedDividendState(), settledState);

    const yearBoundaryDecisionSourceRecordId =
      "received-dividend-year-boundary-decision-runtime";
    const yearBoundaryDecisionOptions = {
      eventDate: "2026-12-20",
      idempotencyKey: "66000000-0000-4000-8000-000000000013",
      sourceRecordId: yearBoundaryDecisionSourceRecordId,
      sources: [
        {
          role: "PRIMARY",
          capability: "INVESTMENTS",
          recordId: yearBoundaryDecisionSourceRecordId,
          revision: 1,
          factSha256: "1".repeat(64),
        },
        {
          role: "CORROBORATING",
          capability: "DOCUMENTS",
          recordId: "received-dividend-year-boundary-document-runtime",
          revision: 1,
          factSha256: "2".repeat(64),
        },
        {
          role: "CORROBORATING",
          capability: "COMPANY_TAX_FILING",
          recordId: "received-dividend-year-boundary-tax-runtime",
          revision: 1,
          factSha256: "3".repeat(64),
        },
      ],
    };
    const yearBoundaryDecision = jsonOutput(
      containerName,
      receivedDividendDecisionTransaction(yearBoundaryDecisionOptions),
    );
    assert.equal(yearBoundaryDecision.income_year, 2026);
    assert.equal(yearBoundaryDecision.replayed, false);
    const yearBoundaryPaymentSourceRecordId =
      "received-dividend-year-boundary-payment-runtime";
    const yearBoundaryPaymentOptions = {
      decisionEntryId: yearBoundaryDecision.ledger_entry_id,
      eventDate: "2027-01-10",
      idempotencyKey: "66000000-0000-4000-8000-000000000014",
      incomeYear: 2027,
      sourceRecordId: yearBoundaryPaymentSourceRecordId,
      sources: [
        {
          role: "PRIMARY",
          capability: "INVESTMENTS",
          recordId: yearBoundaryPaymentSourceRecordId,
          revision: 1,
          factSha256: "4".repeat(64),
        },
        {
          role: "CORROBORATING",
          capability: "BANKING",
          recordId: "received-dividend-year-boundary-bank-runtime",
          revision: 1,
          factSha256: "5".repeat(64),
        },
      ],
    };
    const yearBoundaryPayment = jsonOutput(
      containerName,
      receivedDividendPaymentTransaction(yearBoundaryPaymentOptions),
    );
    assert.equal(yearBoundaryPayment.income_year, 2027);
    assert.equal(yearBoundaryPayment.replayed, false);
    const yearBoundaryDecisionReplay = jsonOutput(
      containerName,
      receivedDividendDecisionTransaction(yearBoundaryDecisionOptions),
    );
    assert.equal(
      yearBoundaryDecisionReplay.ledger_entry_id,
      yearBoundaryDecision.ledger_entry_id,
    );
    assert.equal(yearBoundaryDecisionReplay.replayed, true);
    const yearBoundaryPaymentReplay = jsonOutput(
      containerName,
      receivedDividendPaymentTransaction(yearBoundaryPaymentOptions),
    );
    assert.equal(
      yearBoundaryPaymentReplay.ledger_entry_id,
      yearBoundaryPayment.ledger_entry_id,
    );
    assert.equal(yearBoundaryPaymentReplay.replayed, true);
    assert.deepEqual(jsonOutput(containerName, String.raw`
      select pg_catalog.jsonb_build_object(
        'companyId', settlement.company_id,
        'decisionYear', decision.income_year,
        'decisionEventDate', decision_context.event_date,
        'paymentYear', payment.income_year,
        'paymentEventDate', payment_context.event_date
      )::text
      from ledger.received_dividend_settlements settlement
      join ledger.received_dividend_decisions decision
        on decision.decision_entry_id = settlement.decision_entry_id
      join ledger.entries payment
        on payment.id = settlement.payment_entry_id
      join ledger.entry_contexts decision_context
        on decision_context.entry_id = decision.decision_entry_id
      join ledger.entry_contexts payment_context
        on payment_context.entry_id = payment.id
      where settlement.decision_entry_id = '${yearBoundaryDecision.ledger_entry_id}';
    `), {
      companyId,
      decisionEventDate: "2026-12-20",
      decisionYear: 2026,
      paymentEventDate: "2027-01-10",
      paymentYear: 2027,
    });

    const concurrentDecisionSourceRecordId =
      "received-dividend-concurrent-decision-runtime";
    const concurrentDecision = jsonOutput(
      containerName,
      receivedDividendDecisionTransaction({
        eventDate: "2026-12-21",
        idempotencyKey: "66000000-0000-4000-8000-000000000015",
        sourceRecordId: concurrentDecisionSourceRecordId,
        sources: [
          {
            role: "PRIMARY",
            capability: "INVESTMENTS",
            recordId: concurrentDecisionSourceRecordId,
            revision: 1,
            factSha256: "6".repeat(64),
          },
          {
            role: "CORROBORATING",
            capability: "DOCUMENTS",
            recordId: "received-dividend-concurrent-document-runtime",
            revision: 1,
            factSha256: "7".repeat(64),
          },
          {
            role: "CORROBORATING",
            capability: "COMPANY_TAX_FILING",
            recordId: "received-dividend-concurrent-tax-runtime",
            revision: 1,
            factSha256: "8".repeat(64),
          },
        ],
      }),
    );
    const concurrentPaymentOptions = [
      {
        applicationName: "received_dividend_payment_2027",
        eventDate: "2027-01-11",
        idempotencyKey: "66000000-0000-4000-8000-000000000016",
        incomeYear: 2027,
        sourceRecordId: "received-dividend-concurrent-payment-2027-runtime",
        bankRecordId: "received-dividend-concurrent-bank-2027-runtime",
        sourceHash: "9".repeat(64),
        bankHash: "a".repeat(64),
      },
      {
        applicationName: "received_dividend_payment_2029",
        eventDate: "2029-01-11",
        idempotencyKey: "66000000-0000-4000-8000-000000000017",
        incomeYear: 2029,
        sourceRecordId: "received-dividend-concurrent-payment-2029-runtime",
        bankRecordId: "received-dividend-concurrent-bank-2029-runtime",
        sourceHash: "b".repeat(64),
        bankHash: "c".repeat(64),
      },
    ];
    const concurrentPaymentTransaction = (options) =>
      receivedDividendPaymentTransaction({
        decisionEntryId: concurrentDecision.ledger_entry_id,
        eventDate: options.eventDate,
        idempotencyKey: options.idempotencyKey,
        incomeYear: options.incomeYear,
        sourceRecordId: options.sourceRecordId,
        sources: [
          {
            role: "PRIMARY",
            capability: "INVESTMENTS",
            recordId: options.sourceRecordId,
            revision: 1,
            factSha256: options.sourceHash,
          },
          {
            role: "CORROBORATING",
            capability: "BANKING",
            recordId: options.bankRecordId,
            revision: 1,
            factSha256: options.bankHash,
          },
        ],
      });
    const firstConcurrentPayment = interactivePsql(containerName);
    firstConcurrentPayment.child.stdin.write(String.raw`
      set application_name = '${concurrentPaymentOptions[0].applicationName}';
      ${concurrentPaymentTransaction(concurrentPaymentOptions[0]).replace(
        "commit;",
        "select 'received_dividend_first_payment_uncommitted';",
      )}
    `);
    await waitForOutput(
      firstConcurrentPayment,
      /received_dividend_first_payment_uncommitted/u,
    );
    const secondConcurrentPayment = interactivePsql(containerName);
    secondConcurrentPayment.child.stdin.end(String.raw`
      set application_name = '${concurrentPaymentOptions[1].applicationName}';
      ${concurrentPaymentTransaction(concurrentPaymentOptions[1])}
    `);
    let secondConcurrentPaymentBlocked = false;
    for (let attempt = 0; attempt < 50; attempt += 1) {
      secondConcurrentPaymentBlocked = lastOutputLine(psql(
        containerName,
        ["-Atq"],
        String.raw`
          select count(*) from pg_catalog.pg_stat_activity
          where application_name = 'received_dividend_payment_2029'
            and wait_event_type = 'Lock';
        `,
      )) === "1";
      if (secondConcurrentPaymentBlocked) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.equal(
      secondConcurrentPaymentBlocked,
      true,
      "second cross-year dividend payment did not contend with the first",
    );
    firstConcurrentPayment.child.stdin.end("commit;\n\\q\n");
    const concurrentPaymentResults = await Promise.all([
      processResult(firstConcurrentPayment),
      processResult(secondConcurrentPayment),
    ]);
    const concurrentPaymentSuccesses = concurrentPaymentResults.filter(
      (result) => result.code === 0,
    );
    const concurrentPaymentFailures = concurrentPaymentResults.filter(
      (result) => result.code !== 0,
    );
    assert.equal(concurrentPaymentSuccesses.length, 1);
    assert.equal(concurrentPaymentFailures.length, 1);
    assert.match(
      concurrentPaymentFailures[0].stderr,
      /ledger_received_dividend_already_settled/iu,
    );
    assert.deepEqual(jsonOutput(containerName, String.raw`
      select pg_catalog.jsonb_build_object(
        'entries', (select count(*) from ledger.entries entry
          where entry.source_record_id in (
            'received-dividend-concurrent-payment-2027-runtime',
            'received-dividend-concurrent-payment-2029-runtime'
          )),
        'contexts', (select count(*) from ledger.entry_contexts context
          join ledger.entries entry on entry.id = context.entry_id
          where entry.source_record_id in (
            'received-dividend-concurrent-payment-2027-runtime',
            'received-dividend-concurrent-payment-2029-runtime'
          )),
        'sources', (select count(*) from ledger.entry_sources source
          join ledger.entries entry on entry.id = source.entry_id
          where entry.source_record_id in (
            'received-dividend-concurrent-payment-2027-runtime',
            'received-dividend-concurrent-payment-2029-runtime'
          )),
        'receipts', (select count(*) from backend_system.ledger_command_receipts receipt
          where receipt.idempotency_key in (
            '66000000-0000-4000-8000-000000000016',
            '66000000-0000-4000-8000-000000000017'
          )),
        'settlements', (select count(*)
          from ledger.received_dividend_settlements settlement
          where settlement.decision_entry_id = '${concurrentDecision.ledger_entry_id}')
      )::text;
    `), {
      contexts: 1,
      entries: 1,
      receipts: 1,
      settlements: 1,
      sources: 2,
    });
    for (const table of ["received_dividend_decisions", "received_dividend_settlements"]) {
      assert.match(psqlFailure(containerName, String.raw`
        begin;
        ${actorContext(ownerId)}
        insert into ledger.${table} default values;
        commit;
      `), /permission denied/iu);
    }

    const bankLoanDisbursementOptions = {
      idempotencyKey: "67000000-0000-4000-8000-000000000001",
      loanReference: "bank-loan:runtime-1",
      sourceRecordId: "bank-loan-disbursement-runtime",
      sources: [{
        role: "PRIMARY",
        capability: "BANKING",
        recordId: "bank-loan-disbursement-runtime",
        revision: 1,
        factSha256: "d".repeat(64),
      }],
    };
    const bankLoanDisbursement = jsonOutput(
      containerName,
      bankLoanDisbursementTransaction(bankLoanDisbursementOptions),
    );
    assert.equal(bankLoanDisbursement.entry_kind, "BANK_LOAN");
    assert.equal(bankLoanDisbursement.replayed, false);
    const bankLoanDisbursementReplay = jsonOutput(
      containerName,
      bankLoanDisbursementTransaction(bankLoanDisbursementOptions),
    );
    assert.equal(
      bankLoanDisbursementReplay.ledger_entry_id,
      bankLoanDisbursement.ledger_entry_id,
    );
    assert.equal(bankLoanDisbursementReplay.replayed, true);
    assert.match(psqlFailure(containerName, bankLoanDisbursementTransaction({
      ...bankLoanDisbursementOptions,
      loanReference: "bank-loan:changed-retry",
    })), exactDatabaseError("ledger_idempotency_key_reused"));
    assert.match(psqlFailure(containerName, bankLoanDisbursementTransaction({
      idempotencyKey: "67000000-0000-4000-8000-000000000020",
      loanReference: "bank-loan:null-principal",
      principalNok: null,
      sourceRecordId: "bank-loan-null-disbursement-principal-runtime",
      correlationId: "bank-loan-null-disbursement-principal-runtime",
      sources: [{
        role: "PRIMARY",
        capability: "BANKING",
        recordId: "bank-loan-null-disbursement-principal-runtime",
        revision: 1,
        factSha256: "c".repeat(64),
      }],
    })), exactDatabaseError("ledger_bank_loan_event_invalid"));
    const mismatchedDisbursementSource = "bank-loan-mismatched-disbursement-runtime";
    assert.match(psqlFailure(containerName, bankLoanDisbursementTransaction({
      idempotencyKey: "67000000-0000-4000-8000-000000000024",
      loanReference: "bank-loan:mismatched-disbursement",
      principalNok: "50000.00",
      sourceRecordId: mismatchedDisbursementSource,
      correlationId: mismatchedDisbursementSource,
    })), exactDatabaseError("ledger_bank_loan_event_invalid"));
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.entries
          where source_record_id = '${mismatchedDisbursementSource}'),
        (select count(*) from backend_system.ledger_command_receipts
          where idempotency_key = '67000000-0000-4000-8000-000000000024'),
        (select count(*) from ledger.bank_loan_anchors
          where loan_reference_id = 'bank-loan:mismatched-disbursement'));
    `)), "0:0:0");
    const malformedDisbursementSource = "bank-loan-malformed-disbursement-runtime";
    assert.match(psqlFailure(containerName, bankLoanDisbursementTransaction({
      idempotencyKey: "67000000-0000-4000-8000-000000000026",
      loanReference: "bank-loan:malformed-disbursement",
      lines: { unexpected: "object" },
      sourceRecordId: malformedDisbursementSource,
      correlationId: malformedDisbursementSource,
    })), exactDatabaseError("ledger_bank_loan_event_invalid"));
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':', anchor.loan_reference_id, anchor.principal_disbursed,
        anchor.disbursement_income_year, context.event_date)
      from ledger.bank_loan_anchors anchor
      join ledger.entry_contexts context
        on context.entry_id = anchor.disbursement_entry_id
        and context.company_id = anchor.company_id
        and context.income_year = anchor.disbursement_income_year
      where anchor.disbursement_entry_id = '${bankLoanDisbursement.ledger_entry_id}';
    `)), "bank-loan:runtime-1:100000.00:2026:2026-03-15");

    const duplicateLoanSource = "bank-loan-duplicate-disbursement-runtime";
    assert.match(psqlFailure(containerName, bankLoanDisbursementTransaction({
      idempotencyKey: "67000000-0000-4000-8000-000000000003",
      loanReference: bankLoanDisbursementOptions.loanReference,
      sourceRecordId: duplicateLoanSource,
      correlationId: duplicateLoanSource,
      sources: [{
        role: "PRIMARY",
        capability: "BANKING",
        recordId: duplicateLoanSource,
        revision: 1,
        factSha256: "f".repeat(64),
      }],
    })), exactDatabaseError("ledger_bank_loan_already_exists"));
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.entries
          where source_record_id = '${duplicateLoanSource}'),
        (select count(*) from backend_system.ledger_command_receipts
          where idempotency_key = '67000000-0000-4000-8000-000000000003'));
    `)), "0:0");

    const missingLoanPaymentSource = "bank-loan-missing-payment-runtime";
    assert.match(psqlFailure(containerName, bankLoanPaymentTransaction({
      idempotencyKey: "67000000-0000-4000-8000-000000000004",
      loanReference: "bank-loan:missing",
      sourceRecordId: missingLoanPaymentSource,
      correlationId: missingLoanPaymentSource,
      sources: [{
        role: "PRIMARY",
        capability: "BANKING",
        recordId: missingLoanPaymentSource,
        revision: 1,
        factSha256: "0".repeat(64),
      }],
    })), exactDatabaseError("ledger_opening_loan_anchor_missing"));
    const openingLoanPaymentSource = "bank-loan-opening-payment-runtime";
    assert.match(psqlFailure(containerName, bankLoanPaymentTransaction({
      idempotencyKey: "67000000-0000-4000-8000-000000000005",
      loanReference: "opening-bank-loan:legacy-1",
      sourceRecordId: openingLoanPaymentSource,
      correlationId: openingLoanPaymentSource,
      sources: [{
        role: "PRIMARY",
        capability: "BANKING",
        recordId: openingLoanPaymentSource,
        revision: 1,
        factSha256: "1".repeat(64),
      }],
    })), exactDatabaseError("ledger_opening_loan_anchor_missing"));
    const crossCompanyPaymentSource = "bank-loan-cross-company-payment-runtime";
    assert.match(psqlFailure(containerName, bankLoanPaymentTransaction({
      actorId: otherOwnerId,
      company: otherCompanyId,
      idempotencyKey: "67000000-0000-4000-8000-000000000006",
      loanReference: bankLoanDisbursementOptions.loanReference,
      sourceRecordId: crossCompanyPaymentSource,
      correlationId: crossCompanyPaymentSource,
      sources: [{
        role: "PRIMARY",
        capability: "BANKING",
        recordId: crossCompanyPaymentSource,
        revision: 1,
        factSha256: "2".repeat(64),
      }],
    })), exactDatabaseError("ledger_opening_loan_anchor_missing"));
    const backdatedLoanPaymentSource = "bank-loan-backdated-payment-runtime";
    assert.match(psqlFailure(containerName, bankLoanPaymentTransaction({
      eventDate: "2026-03-14",
      idempotencyKey: "67000000-0000-4000-8000-000000000007",
      sourceRecordId: backdatedLoanPaymentSource,
      correlationId: backdatedLoanPaymentSource,
      sources: [{
        role: "PRIMARY",
        capability: "BANKING",
        recordId: backdatedLoanPaymentSource,
        revision: 1,
        factSha256: "3".repeat(64),
      }],
    })), exactDatabaseError("ledger_bank_loan_event_invalid"));
    for (const [suffix, idempotencyKey, allocations] of [
      ["principal", "67000000-0000-4000-8000-000000000021", {
        principalNok: null,
        interestNok: "1000.00",
        feeNok: "0.00",
      }],
      ["interest", "67000000-0000-4000-8000-000000000022", {
        principalNok: "1000.00",
        interestNok: null,
        feeNok: "0.00",
      }],
      ["fee", "67000000-0000-4000-8000-000000000023", {
        principalNok: "1000.00",
        interestNok: "0.00",
        feeNok: null,
      }],
    ]) {
      const sourceRecordId = `bank-loan-null-payment-${suffix}-runtime`;
      assert.match(psqlFailure(containerName, bankLoanPaymentTransaction({
        ...allocations,
        idempotencyKey,
        sourceRecordId,
        correlationId: sourceRecordId,
        sources: [{
          role: "PRIMARY",
          capability: "BANKING",
          recordId: sourceRecordId,
          revision: 1,
          factSha256: "d".repeat(64),
        }],
      })), exactDatabaseError("ledger_bank_loan_event_invalid"));
    }
    const mismatchedPaymentSource = "bank-loan-mismatched-payment-runtime";
    assert.match(psqlFailure(containerName, bankLoanPaymentTransaction({
      idempotencyKey: "67000000-0000-4000-8000-000000000025",
      principalNok: "1000.00",
      interestNok: "0.00",
      feeNok: "0.00",
      lines: bankLoanPaymentLines({
        principalNok: "2000.00",
        interestNok: "0.00",
        feeNok: "0.00",
      }),
      sourceRecordId: mismatchedPaymentSource,
      correlationId: mismatchedPaymentSource,
    })), exactDatabaseError("ledger_bank_loan_event_invalid"));
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.entries
          where source_record_id = '${mismatchedPaymentSource}'),
        (select count(*) from backend_system.ledger_command_receipts
          where idempotency_key = '67000000-0000-4000-8000-000000000025'),
        (select count(*) from ledger.bank_loan_payment_allocations allocation
          join ledger.entries entry on entry.id = allocation.payment_entry_id
          where entry.source_record_id = '${mismatchedPaymentSource}'));
    `)), "0:0:0");
    const malformedPaymentSource = "bank-loan-malformed-payment-runtime";
    assert.match(psqlFailure(containerName, bankLoanPaymentTransaction({
      idempotencyKey: "67000000-0000-4000-8000-000000000027",
      lines: [
        { account: "2220", description: "Principal", debit: "not-a-number", credit: "0.00", currency: "NOK" },
        { account: "1920", description: "Bank", debit: "0.00", credit: "26000.00", currency: "NOK" },
      ],
      sourceRecordId: malformedPaymentSource,
      correlationId: malformedPaymentSource,
    })), exactDatabaseError("ledger_bank_loan_event_invalid"));
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.entries
          where source_record_id in (
            '${malformedDisbursementSource}', '${malformedPaymentSource}'
          )),
        (select count(*) from backend_system.ledger_command_receipts
          where idempotency_key in (
            '67000000-0000-4000-8000-000000000026',
            '67000000-0000-4000-8000-000000000027'
          )));
    `)), "0:0");

    const firstLoanPaymentOptions = {
      idempotencyKey: "67000000-0000-4000-8000-000000000002",
      principalNok: "25000.00",
      interestNok: "1000.00",
      feeNok: "0.00",
      sourceRecordId: "bank-loan-payment-runtime",
      sources: [{
        role: "PRIMARY",
        capability: "BANKING",
        recordId: "bank-loan-payment-runtime",
        revision: 1,
        factSha256: "e".repeat(64),
      }],
    };
    const firstLoanPayment = jsonOutput(
      containerName,
      bankLoanPaymentTransaction(firstLoanPaymentOptions),
    );
    assert.equal(firstLoanPayment.entry_kind, "BANK_LOAN");
    assert.equal(firstLoanPayment.replayed, false);
    const firstLoanPaymentReplay = jsonOutput(
      containerName,
      bankLoanPaymentTransaction(firstLoanPaymentOptions),
    );
    assert.equal(firstLoanPaymentReplay.ledger_entry_id, firstLoanPayment.ledger_entry_id);
    assert.equal(firstLoanPaymentReplay.replayed, true);
    assert.match(psqlFailure(containerName, bankLoanPaymentTransaction({
      ...firstLoanPaymentOptions,
      principalNok: "24000.00",
    })), exactDatabaseError("ledger_idempotency_key_reused"));

    const secondLoanPaymentOptions = {
      eventDate: "2027-02-15",
      idempotencyKey: "67000000-0000-4000-8000-000000000008",
      incomeYear: 2027,
      principalNok: "20000.00",
      interestNok: "800.00",
      feeNok: "200.00",
      sourceRecordId: "bank-loan-payment-2027-runtime",
      correlationId: "bank-loan-payment-2027-runtime",
      sources: [{
        role: "PRIMARY",
        capability: "BANKING",
        recordId: "bank-loan-payment-2027-runtime",
        revision: 1,
        factSha256: "4".repeat(64),
      }],
    };
    const secondLoanPayment = jsonOutput(
      containerName,
      bankLoanPaymentTransaction(secondLoanPaymentOptions),
    );
    assert.equal(secondLoanPayment.income_year, 2027);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':', count(*), sum(allocation.principal_paid),
        sum(allocation.interest_paid), sum(allocation.fee_paid),
        min(allocation.payment_income_year), max(allocation.payment_income_year))
      from ledger.bank_loan_payment_allocations allocation
      join ledger.bank_loan_anchors anchor
        on anchor.company_id = allocation.company_id
        and anchor.loan_reference_id = allocation.loan_reference_id
      where anchor.company_id = '${companyId}'
        and anchor.loan_reference_id = '${bankLoanDisbursementOptions.loanReference}';
    `)), "2:45000.00:1800.00:200.00:2026:2027");

    const overpaymentSource = "bank-loan-overpayment-runtime";
    assert.match(psqlFailure(containerName, bankLoanPaymentTransaction({
      eventDate: "2027-03-15",
      idempotencyKey: "67000000-0000-4000-8000-000000000009",
      incomeYear: 2027,
      principalNok: "56000.00",
      interestNok: "0.00",
      sourceRecordId: overpaymentSource,
      correlationId: overpaymentSource,
      sources: [{
        role: "PRIMARY",
        capability: "BANKING",
        recordId: overpaymentSource,
        revision: 1,
        factSha256: "5".repeat(64),
      }],
    })), exactDatabaseError("ledger_bank_loan_principal_exceeded"));
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.entries
          where source_record_id = '${overpaymentSource}'),
        (select count(*) from ledger.entry_contexts context
          join ledger.entries entry on entry.id = context.entry_id
          where entry.source_record_id = '${overpaymentSource}'),
        (select count(*) from ledger.entry_sources source
          join ledger.entries entry on entry.id = source.entry_id
          where entry.source_record_id = '${overpaymentSource}'),
        (select count(*) from backend_system.ledger_command_receipts
          where idempotency_key = '67000000-0000-4000-8000-000000000009'),
        (select count(*) from ledger.bank_loan_payment_allocations
          where payment_entry_id in (select id from ledger.entries
            where source_record_id = '${overpaymentSource}')));
    `)), "0:0:0:0:0");

    const concurrentLoanPaymentOptions = [
      {
        applicationName: "bank_loan_payment_2027",
        eventDate: "2027-04-15",
        idempotencyKey: "67000000-0000-4000-8000-000000000010",
        incomeYear: 2027,
        sourceRecordId: "bank-loan-concurrent-payment-2027-runtime",
        sourceHash: "6".repeat(64),
      },
      {
        applicationName: "bank_loan_payment_2029",
        eventDate: "2029-04-15",
        idempotencyKey: "67000000-0000-4000-8000-000000000011",
        incomeYear: 2029,
        sourceRecordId: "bank-loan-concurrent-payment-2029-runtime",
        sourceHash: "7".repeat(64),
      },
    ];
    const concurrentLoanPaymentTransaction = (options) =>
      bankLoanPaymentTransaction({
        eventDate: options.eventDate,
        idempotencyKey: options.idempotencyKey,
        incomeYear: options.incomeYear,
        principalNok: "40000.00",
        interestNok: "500.00",
        sourceRecordId: options.sourceRecordId,
        correlationId: options.sourceRecordId,
        sources: [{
          role: "PRIMARY",
          capability: "BANKING",
          recordId: options.sourceRecordId,
          revision: 1,
          factSha256: options.sourceHash,
        }],
      });
    const firstConcurrentLoanPayment = interactivePsql(containerName);
    firstConcurrentLoanPayment.child.stdin.write(String.raw`
      set application_name = '${concurrentLoanPaymentOptions[0].applicationName}';
      ${concurrentLoanPaymentTransaction(concurrentLoanPaymentOptions[0]).replace(
        "commit;",
        "select 'bank_loan_first_payment_uncommitted';",
      )}
    `);
    await waitForOutput(
      firstConcurrentLoanPayment,
      /bank_loan_first_payment_uncommitted/u,
    );
    const secondConcurrentLoanPayment = interactivePsql(containerName);
    secondConcurrentLoanPayment.child.stdin.end(String.raw`
      set application_name = '${concurrentLoanPaymentOptions[1].applicationName}';
      ${concurrentLoanPaymentTransaction(concurrentLoanPaymentOptions[1])}
    `);
    let secondConcurrentLoanPaymentBlocked = false;
    for (let attempt = 0; attempt < 50; attempt += 1) {
      secondConcurrentLoanPaymentBlocked = lastOutputLine(psql(
        containerName,
        ["-Atq"],
        String.raw`
          select count(*) from pg_catalog.pg_stat_activity
          where application_name = 'bank_loan_payment_2029'
            and wait_event_type = 'Lock';
        `,
      )) === "1";
      if (secondConcurrentLoanPaymentBlocked) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.equal(
      secondConcurrentLoanPaymentBlocked,
      true,
      "second cross-year bank-loan payment did not contend on its loan anchor",
    );
    firstConcurrentLoanPayment.child.stdin.end("commit;\n\\q\n");
    const concurrentLoanPaymentResults = await Promise.all([
      processResult(firstConcurrentLoanPayment),
      processResult(secondConcurrentLoanPayment),
    ]);
    const concurrentLoanPaymentSuccesses = concurrentLoanPaymentResults.filter(
      (result) => result.code === 0,
    );
    const concurrentLoanPaymentFailures = concurrentLoanPaymentResults.filter(
      (result) => result.code !== 0,
    );
    assert.equal(concurrentLoanPaymentSuccesses.length, 1);
    assert.equal(concurrentLoanPaymentFailures.length, 1);
    assert.match(
      concurrentLoanPaymentFailures[0].stderr,
      exactDatabaseError("ledger_bank_loan_principal_exceeded"),
    );
    assert.deepEqual(jsonOutput(containerName, String.raw`
      select pg_catalog.jsonb_build_object(
        'entries', (select count(*) from ledger.entries entry
          where entry.source_record_id in (
            'bank-loan-concurrent-payment-2027-runtime',
            'bank-loan-concurrent-payment-2029-runtime'
          )),
        'contexts', (select count(*) from ledger.entry_contexts context
          join ledger.entries entry on entry.id = context.entry_id
          where entry.source_record_id in (
            'bank-loan-concurrent-payment-2027-runtime',
            'bank-loan-concurrent-payment-2029-runtime'
          )),
        'sources', (select count(*) from ledger.entry_sources source
          join ledger.entries entry on entry.id = source.entry_id
          where entry.source_record_id in (
            'bank-loan-concurrent-payment-2027-runtime',
            'bank-loan-concurrent-payment-2029-runtime'
          )),
        'receipts', (select count(*) from backend_system.ledger_command_receipts receipt
          where receipt.idempotency_key in (
            '67000000-0000-4000-8000-000000000010',
            '67000000-0000-4000-8000-000000000011'
          )),
        'allocations', (select count(*)
          from ledger.bank_loan_payment_allocations allocation
          where allocation.payment_entry_id in (select id from ledger.entries
            where source_record_id in (
              'bank-loan-concurrent-payment-2027-runtime',
              'bank-loan-concurrent-payment-2029-runtime'
            )))
      )::text;
    `), {
      allocations: 1,
      contexts: 1,
      entries: 1,
      receipts: 1,
      sources: 2,
    });
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':', count(*), sum(allocation.principal_paid),
        sum(allocation.interest_paid), sum(allocation.fee_paid),
        min(allocation.payment_income_year), max(allocation.payment_income_year))
      from ledger.bank_loan_payment_allocations allocation
      join ledger.bank_loan_anchors anchor
        on anchor.company_id = allocation.company_id
        and anchor.loan_reference_id = allocation.loan_reference_id
      where anchor.company_id = '${companyId}'
        and anchor.loan_reference_id = '${bankLoanDisbursementOptions.loanReference}';
    `)), "3:85000.00:2300.00:200.00:2026:2027");

    for (const table of ["bank_loan_anchors", "bank_loan_payment_allocations"]) {
      assert.match(psqlFailure(containerName, String.raw`
        begin;
        ${actorContext(ownerId)}
        insert into ledger.${table} default values;
        commit;
      `), /permission denied/iu);
    }
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        pg_catalog.has_function_privilege(
          'ledger_executor',
          'ledger.record_bank_loan_disbursement_v1(text,uuid,integer,text,numeric,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ),
        pg_catalog.has_function_privilege(
          'authenticated',
          'ledger.record_bank_loan_disbursement_v1(text,uuid,integer,text,numeric,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ),
        pg_catalog.has_function_privilege(
          'ledger_executor',
          'ledger.record_bank_loan_payment_v1(text,uuid,integer,text,numeric,numeric,numeric,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ),
        pg_catalog.has_function_privilege(
          'authenticated',
          'ledger.record_bank_loan_payment_v1(text,uuid,integer,text,numeric,numeric,numeric,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ),
        pg_catalog.has_table_privilege(
          'ledger_executor', 'ledger.bank_loan_anchors', 'insert'
        ),
        pg_catalog.has_table_privilege(
          'ledger_executor', 'ledger.bank_loan_payment_allocations', 'insert'
        ));
    `)), "t:f:t:f:f:f");

    const capitalSubscriptionOptions = {
      phase: "BINDING_SUBSCRIPTION",
      idempotencyKey: "68000000-0000-4000-8000-000000000001",
      memo: "Binding cash-capital subscription",
      sourceRecordId: "cash-capital-increase-subscription-runtime",
      eventDate: "2026-02-01",
    };
    const capitalRestrictedPaymentOptions = {
      phase: "RESTRICTED_PAYMENT",
      idempotencyKey: "68000000-0000-4000-8000-000000000002",
      memo: "Cash contribution paid to restricted account",
      sourceRecordId: "cash-capital-increase-restricted-payment-runtime",
      eventDate: "2026-02-10",
    };
    const capitalRegistrationOptions = {
      phase: "REGISTERED",
      idempotencyKey: "68000000-0000-4000-8000-000000000003",
      memo: "Registered cash-capital increase",
      sourceRecordId: "cash-capital-increase-registration-runtime",
      eventDate: "2026-02-20",
    };
    const capitalSubscription = jsonOutput(
      containerName,
      cashCapitalIncreaseTransaction(capitalSubscriptionOptions),
    );
    assert.equal(capitalSubscription.entry_kind, "CAPITAL_INCREASE");
    assert.equal(capitalSubscription.replayed, false);
    const capitalSubscriptionReplay = jsonOutput(
      containerName,
      cashCapitalIncreaseTransaction(capitalSubscriptionOptions),
    );
    assert.equal(capitalSubscriptionReplay.ledger_entry_id, capitalSubscription.ledger_entry_id);
    assert.equal(capitalSubscriptionReplay.replayed, true);
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalSubscriptionOptions,
      nominalIncreaseNok: "11000.00",
    })), exactDatabaseError("ledger_idempotency_key_reused"));

    const missingOpeningAnchorCases = [
      {
        ...capitalRestrictedPaymentOptions,
        idempotencyKey: "68000000-0000-4000-8000-000000000004",
        capitalIncreaseReference: "capital-increase:missing-subscription",
        sourceRecordId: "cash-capital-increase-missing-subscription-payment-runtime",
      },
      {
        ...capitalRegistrationOptions,
        idempotencyKey: "68000000-0000-4000-8000-000000000005",
        capitalIncreaseReference: "capital-increase:missing-subscription",
        sourceRecordId: "cash-capital-increase-missing-subscription-registration-runtime",
      },
    ];
    for (const missingOpeningAnchor of missingOpeningAnchorCases) {
      assert.match(
        psqlFailure(
          containerName,
          cashCapitalIncreaseTransaction(missingOpeningAnchor),
        ),
        exactDatabaseError("ledger_opening_capital_increase_anchor_missing"),
      );
    }
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalRegistrationOptions,
      idempotencyKey: "68000000-0000-4000-8000-000000000006",
      sourceRecordId: "cash-capital-increase-skipped-payment-registration-runtime",
    })), exactDatabaseError("ledger_cash_capital_increase_phase_missing"));

    const invalidSourceCases = [
      {
        ...capitalSubscriptionOptions,
        idempotencyKey: "68000000-0000-4000-8000-000000000007",
        capitalIncreaseReference: "capital-increase:invalid-subscription-sources",
        sourceRecordId: "cash-capital-increase-invalid-subscription-sources-runtime",
        sources: [
          { role: "PRIMARY", capability: "DOCUMENTS", recordId: "cash-capital-increase-invalid-subscription-sources-runtime", revision: 1, factSha256: "5".repeat(64) },
          { role: "CORROBORATING", capability: "CORPORATE_GOVERNANCE", recordId: "cash-capital-increase-invalid-subscription-governance-runtime", revision: 1, factSha256: "6".repeat(64) },
        ],
      },
      {
        ...capitalRestrictedPaymentOptions,
        idempotencyKey: "68000000-0000-4000-8000-000000000008",
        sourceRecordId: "cash-capital-increase-invalid-payment-sources-runtime",
        sources: cashCapitalIncreaseSources(
          "RESTRICTED_PAYMENT",
          "cash-capital-increase-invalid-payment-sources-runtime",
        ).slice(0, 2),
      },
      {
        ...capitalRegistrationOptions,
        idempotencyKey: "68000000-0000-4000-8000-000000000009",
        sourceRecordId: "cash-capital-increase-invalid-registration-sources-runtime",
        sources: [
          ...cashCapitalIncreaseSources(
            "REGISTERED",
            "cash-capital-increase-invalid-registration-sources-runtime",
          ),
          { role: "CORROBORATING", capability: "DOCUMENTS", recordId: "cash-capital-increase-extra-registration-document-runtime", revision: 1, factSha256: "7".repeat(64) },
        ],
      },
    ];
    for (const invalidSources of invalidSourceCases) {
      assert.match(
        psqlFailure(containerName, cashCapitalIncreaseTransaction(invalidSources)),
        exactDatabaseError("ledger_cash_capital_increase_phase_invalid"),
      );
    }

    const backdatedCapitalPaymentSource = "cash-capital-increase-backdated-payment-runtime";
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalRestrictedPaymentOptions,
      idempotencyKey: "68000000-0000-4000-8000-000000000010",
      sourceRecordId: backdatedCapitalPaymentSource,
      eventDate: "2026-01-31",
    })), exactDatabaseError("ledger_cash_capital_increase_phase_invalid"));
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalRestrictedPaymentOptions,
      idempotencyKey: "68000000-0000-4000-8000-000000000011",
      nominalIncreaseNok: "9999.00",
      sourceRecordId: "cash-capital-increase-payment-amount-mismatch-runtime",
    })), exactDatabaseError("ledger_cash_capital_increase_amount_mismatch"));
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalSubscriptionOptions,
      idempotencyKey: "68000000-0000-4000-8000-000000000012",
      capitalIncreaseReference: "capital-increase:malformed-lines",
      lines: { unexpected: "object" },
      sourceRecordId: "cash-capital-increase-malformed-subscription-runtime",
    })), exactDatabaseError("ledger_cash_capital_increase_phase_invalid"));
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalSubscriptionOptions,
      idempotencyKey: "68000000-0000-4000-8000-000000000013",
      capitalIncreaseReference: "capital-increase:mismatched-lines",
      lines: cashCapitalIncreaseLines("BINDING_SUBSCRIPTION", "12000.00", "5000.00"),
      sourceRecordId: "cash-capital-increase-mismatched-subscription-runtime",
    })), exactDatabaseError("ledger_cash_capital_increase_amount_mismatch"));

    const capitalRestrictedPayment = jsonOutput(
      containerName,
      cashCapitalIncreaseTransaction(capitalRestrictedPaymentOptions),
    );
    assert.equal(capitalRestrictedPayment.entry_kind, "CAPITAL_INCREASE");
    assert.equal(capitalRestrictedPayment.replayed, false);
    assert.equal(
      jsonOutput(
        containerName,
        cashCapitalIncreaseTransaction(capitalRestrictedPaymentOptions),
      ).replayed,
      true,
    );
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalRestrictedPaymentOptions,
      sharePremiumNok: "4999.00",
    })), exactDatabaseError("ledger_idempotency_key_reused"));
    const backdatedCapitalRegistrationSource =
      "cash-capital-increase-backdated-registration-runtime";
    const backdatedCapitalRegistrationKey =
      "68000000-0000-4000-8000-000000000026";
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalRegistrationOptions,
      idempotencyKey: backdatedCapitalRegistrationKey,
      sourceRecordId: backdatedCapitalRegistrationSource,
      eventDate: "2026-02-09",
    })), exactDatabaseError("ledger_cash_capital_increase_phase_invalid"));
    assert.deepEqual(jsonOutput(containerName, String.raw`
      select pg_catalog.jsonb_build_object(
        'entries', (select count(*) from ledger.entries entry
          where entry.source_record_id = '${backdatedCapitalRegistrationSource}'),
        'contexts', (select count(*) from ledger.entry_contexts context
          join ledger.entries entry on entry.id = context.entry_id
          where entry.source_record_id = '${backdatedCapitalRegistrationSource}'),
        'sources', (select count(*) from ledger.entry_sources source
          join ledger.entries entry on entry.id = source.entry_id
          where entry.source_record_id = '${backdatedCapitalRegistrationSource}'),
        'receipts', (select count(*) from backend_system.ledger_command_receipts receipt
          where receipt.idempotency_key = '${backdatedCapitalRegistrationKey}')
      )::text;
    `), { contexts: 0, entries: 0, receipts: 0, sources: 0 });
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalRestrictedPaymentOptions,
      idempotencyKey: "68000000-0000-4000-8000-000000000014",
      sourceRecordId: "cash-capital-increase-duplicate-payment-runtime",
    })), exactDatabaseError("ledger_cash_capital_increase_phase_already_recorded"));
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalRegistrationOptions,
      idempotencyKey: "68000000-0000-4000-8000-000000000015",
      sharePremiumNok: "5001.00",
      sourceRecordId: "cash-capital-increase-registration-amount-mismatch-runtime",
    })), exactDatabaseError("ledger_cash_capital_increase_amount_mismatch"));
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalRegistrationOptions,
      idempotencyKey: "68000000-0000-4000-8000-000000000016",
      lines: cashCapitalIncreaseLines("REGISTERED", "10001.00", "5000.00"),
      sourceRecordId: "cash-capital-increase-mismatched-registration-runtime",
    })), exactDatabaseError("ledger_cash_capital_increase_amount_mismatch"));
    const capitalRegistration = jsonOutput(
      containerName,
      cashCapitalIncreaseTransaction(capitalRegistrationOptions),
    );
    assert.equal(capitalRegistration.entry_kind, "CAPITAL_INCREASE");
    assert.equal(capitalRegistration.replayed, false);
    assert.equal(
      jsonOutput(
        containerName,
        cashCapitalIncreaseTransaction(capitalRegistrationOptions),
      ).replayed,
      true,
    );
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalRegistrationOptions,
      eventDate: "2026-02-21",
    })), exactDatabaseError("ledger_idempotency_key_reused"));
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalSubscriptionOptions,
      idempotencyKey: "68000000-0000-4000-8000-000000000017",
      sourceRecordId: "cash-capital-increase-duplicate-subscription-runtime",
    })), exactDatabaseError("ledger_cash_capital_increase_phase_already_recorded"));
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalRegistrationOptions,
      idempotencyKey: "68000000-0000-4000-8000-000000000018",
      sourceRecordId: "cash-capital-increase-duplicate-registration-runtime",
    })), exactDatabaseError("ledger_cash_capital_increase_phase_already_recorded"));
    assert.deepEqual(jsonOutput(containerName, String.raw`
      select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
        'phase', phase.phase,
        'incomeYear', phase.income_year,
        'eventDate', phase.event_date,
        'nominalIncrease', phase.nominal_increase,
        'sharePremium', phase.share_premium,
        'sources', (select pg_catalog.jsonb_agg(source.source_capability order by source.ordinal)
          from ledger.entry_sources source where source.entry_id = phase.entry_id)
      ) order by phase.event_date)::text
      from ledger.cash_capital_increase_phases phase
      where phase.company_id = '${companyId}'
        and phase.capital_increase_reference_id = 'capital-increase:runtime-1';
    `), [
      { phase: "BINDING_SUBSCRIPTION", incomeYear: 2026, eventDate: "2026-02-01", nominalIncrease: 10000, sharePremium: 5000, sources: ["CORPORATE_GOVERNANCE", "DOCUMENTS"] },
      { phase: "RESTRICTED_PAYMENT", incomeYear: 2026, eventDate: "2026-02-10", nominalIncrease: 10000, sharePremium: 5000, sources: ["CORPORATE_GOVERNANCE", "BANKING", "DOCUMENTS"] },
      { phase: "REGISTERED", incomeYear: 2026, eventDate: "2026-02-20", nominalIncrease: 10000, sharePremium: 5000, sources: ["CORPORATE_GOVERNANCE", "BANKING", "DOCUMENTS", "SHAREHOLDER_REGISTER_FILING"] },
    ]);

    const crossYearCapitalReference = "capital-increase:cross-year-runtime";
    const crossYearCapitalOptions = [
      {
        ...capitalSubscriptionOptions,
        idempotencyKey: "68000000-0000-4000-8000-000000000019",
        capitalIncreaseReference: crossYearCapitalReference,
        sourceRecordId: "cash-capital-increase-cross-year-subscription-runtime",
        eventDate: "2026-12-20",
      },
      {
        ...capitalRestrictedPaymentOptions,
        idempotencyKey: "68000000-0000-4000-8000-000000000020",
        capitalIncreaseReference: crossYearCapitalReference,
        incomeYear: 2027,
        sourceRecordId: "cash-capital-increase-cross-year-payment-runtime",
        eventDate: "2027-01-10",
      },
      {
        ...capitalRegistrationOptions,
        idempotencyKey: "68000000-0000-4000-8000-000000000021",
        capitalIncreaseReference: crossYearCapitalReference,
        incomeYear: 2029,
        sourceRecordId: "cash-capital-increase-cross-year-registration-runtime",
        eventDate: "2029-01-15",
      },
    ];
    const crossYearCapitalEntries = crossYearCapitalOptions.map((options) =>
      jsonOutput(containerName, cashCapitalIncreaseTransaction(options)));
    assert.deepEqual(crossYearCapitalEntries.map((entry) => entry.income_year), [2026, 2027, 2029]);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select pg_catalog.string_agg(
        phase.phase || ':' || phase.income_year::text,
        ',' order by phase.event_date
      )
      from ledger.cash_capital_increase_phases phase
      where phase.company_id = '${companyId}'
        and phase.capital_increase_reference_id = '${crossYearCapitalReference}';
    `)), "BINDING_SUBSCRIPTION:2026,RESTRICTED_PAYMENT:2027,REGISTERED:2029");

    const crossTenantCapitalSource = "cash-capital-increase-cross-tenant-payment-runtime";
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalRestrictedPaymentOptions,
      actorId: otherOwnerId,
      company: otherCompanyId,
      idempotencyKey: "68000000-0000-4000-8000-000000000022",
      sourceRecordId: crossTenantCapitalSource,
    })), exactDatabaseError("ledger_opening_capital_increase_anchor_missing"));
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      begin;
      ${actorContext(otherOwnerId)}
      set local role ledger_store_owner;
      select count(*) from ledger.cash_capital_increase_phases
      where company_id = '${companyId}';
      commit;
    `)), "0");

    const concurrentCapitalReference = "capital-increase:concurrent-runtime";
    jsonOutput(containerName, cashCapitalIncreaseTransaction({
      ...capitalSubscriptionOptions,
      idempotencyKey: "68000000-0000-4000-8000-000000000023",
      capitalIncreaseReference: concurrentCapitalReference,
      sourceRecordId: "cash-capital-increase-concurrent-subscription-runtime",
      eventDate: "2026-03-01",
    }));
    const concurrentCapitalPaymentOptions = [
      {
        applicationName: "cash_capital_payment_first",
        eventDate: "2027-03-10",
        idempotencyKey: "68000000-0000-4000-8000-000000000024",
        incomeYear: 2027,
        sourceRecordId: "cash-capital-increase-concurrent-payment-first-runtime",
      },
      {
        applicationName: "cash_capital_payment_second",
        eventDate: "2029-03-10",
        idempotencyKey: "68000000-0000-4000-8000-000000000025",
        incomeYear: 2029,
        sourceRecordId: "cash-capital-increase-concurrent-payment-second-runtime",
      },
    ];
    const concurrentCapitalPaymentTransaction = (options) =>
      cashCapitalIncreaseTransaction({
        ...capitalRestrictedPaymentOptions,
        idempotencyKey: options.idempotencyKey,
        capitalIncreaseReference: concurrentCapitalReference,
        incomeYear: options.incomeYear,
        sourceRecordId: options.sourceRecordId,
        eventDate: options.eventDate,
      });
    const firstConcurrentCapitalPayment = interactivePsql(containerName);
    firstConcurrentCapitalPayment.child.stdin.write(String.raw`
      set application_name = '${concurrentCapitalPaymentOptions[0].applicationName}';
      ${concurrentCapitalPaymentTransaction(concurrentCapitalPaymentOptions[0]).replace(
        "commit;",
        "select 'cash_capital_first_payment_uncommitted';",
      )}
    `);
    await waitForOutput(
      firstConcurrentCapitalPayment,
      /cash_capital_first_payment_uncommitted/u,
    );
    const secondConcurrentCapitalPayment = interactivePsql(containerName);
    secondConcurrentCapitalPayment.child.stdin.end(String.raw`
      set application_name = '${concurrentCapitalPaymentOptions[1].applicationName}';
      ${concurrentCapitalPaymentTransaction(concurrentCapitalPaymentOptions[1])}
    `);
    let secondConcurrentCapitalPaymentBlocked = false;
    for (let attempt = 0; attempt < 50; attempt += 1) {
      secondConcurrentCapitalPaymentBlocked = lastOutputLine(psql(
        containerName,
        ["-Atq"],
        String.raw`
          select count(*) from pg_catalog.pg_stat_activity
          where application_name = 'cash_capital_payment_second'
            and wait_event_type = 'Lock';
        `,
      )) === "1";
      if (secondConcurrentCapitalPaymentBlocked) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.equal(
      secondConcurrentCapitalPaymentBlocked,
      true,
      "second cash-capital phase did not contend on its stable lifecycle reference",
    );
    firstConcurrentCapitalPayment.child.stdin.end("commit;\n\\q\n");
    const concurrentCapitalPaymentResults = await Promise.all([
      processResult(firstConcurrentCapitalPayment),
      processResult(secondConcurrentCapitalPayment),
    ]);
    assert.equal(concurrentCapitalPaymentResults.filter((result) => result.code === 0).length, 1);
    const concurrentCapitalPaymentFailures = concurrentCapitalPaymentResults.filter(
      (result) => result.code !== 0,
    );
    assert.equal(concurrentCapitalPaymentFailures.length, 1);
    assert.match(
      concurrentCapitalPaymentFailures[0].stderr,
      exactDatabaseError("ledger_cash_capital_increase_phase_already_recorded"),
    );
    assert.deepEqual(jsonOutput(containerName, String.raw`
      select pg_catalog.jsonb_build_object(
        'entries', (select count(*) from ledger.entries entry
          where entry.source_record_id in (
            'cash-capital-increase-concurrent-payment-first-runtime',
            'cash-capital-increase-concurrent-payment-second-runtime'
          )),
        'contexts', (select count(*) from ledger.entry_contexts context
          join ledger.entries entry on entry.id = context.entry_id
          where entry.source_record_id in (
            'cash-capital-increase-concurrent-payment-first-runtime',
            'cash-capital-increase-concurrent-payment-second-runtime'
          )),
        'receipts', (select count(*) from backend_system.ledger_command_receipts receipt
          where receipt.idempotency_key in (
            '68000000-0000-4000-8000-000000000024',
            '68000000-0000-4000-8000-000000000025'
          )),
        'phases', (select count(*) from ledger.cash_capital_increase_phases phase
          where phase.company_id = '${companyId}'
            and phase.capital_increase_reference_id = '${concurrentCapitalReference}'
            and phase.phase = 'RESTRICTED_PAYMENT')
      )::text;
    `), { contexts: 1, entries: 1, phases: 1, receipts: 1 });

    assert.match(psqlFailure(containerName, String.raw`
      begin;
      ${actorContext(ownerId)}
      insert into ledger.cash_capital_increase_phases default values;
      commit;
    `), /permission denied/iu);
    const capitalIncreaseSignature =
      "(text,uuid,integer,text,numeric,numeric,text,jsonb,text,text,text,text,date,text,jsonb)";
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        pg_catalog.has_function_privilege(
          'ledger_executor',
          'ledger.record_cash_capital_increase_subscription_v1${capitalIncreaseSignature}',
          'execute'
        ),
        pg_catalog.has_function_privilege(
          'ledger_executor',
          'ledger.record_cash_capital_increase_restricted_payment_v1${capitalIncreaseSignature}',
          'execute'
        ),
        pg_catalog.has_function_privilege(
          'ledger_executor',
          'ledger.record_cash_capital_increase_registration_v1${capitalIncreaseSignature}',
          'execute'
        ),
        pg_catalog.has_function_privilege(
          'authenticated',
          'ledger.record_cash_capital_increase_subscription_v1${capitalIncreaseSignature}',
          'execute'
        ),
        pg_catalog.has_table_privilege(
          'ledger_executor', 'ledger.cash_capital_increase_phases', 'insert'
        ));
    `)), "t:t:t:f:f");
    for (const forbiddenRole of [
      "anon",
      "authenticated",
      "service_role",
      "ledger_workflow_executor",
      "talli_ledger_backend",
    ]) {
      assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
        select concat_ws(':',
          pg_catalog.bool_or(pg_catalog.has_function_privilege(
            '${forbiddenRole}', wrapper.function_name, 'execute'
          )),
          pg_catalog.has_table_privilege(
            '${forbiddenRole}', 'ledger.cash_capital_increase_phases', 'insert'
          ) or pg_catalog.has_table_privilege(
            '${forbiddenRole}', 'ledger.cash_capital_increase_phases', 'update'
          ) or pg_catalog.has_table_privilege(
            '${forbiddenRole}', 'ledger.cash_capital_increase_phases', 'delete'
          ) or pg_catalog.has_table_privilege(
            '${forbiddenRole}', 'ledger.cash_capital_increase_phases', 'truncate'
          ))
        from (values
          ('ledger.record_cash_capital_increase_subscription_v1${capitalIncreaseSignature}'::regprocedure),
          ('ledger.record_cash_capital_increase_restricted_payment_v1${capitalIncreaseSignature}'::regprocedure),
          ('ledger.record_cash_capital_increase_registration_v1${capitalIncreaseSignature}'::regprocedure)
        ) wrapper(function_name);
      `)), "f:f", `${forbiddenRole} gained direct capital lifecycle authority`);
    }

    const blockedReconstruction = jsonOutput(
      containerName,
      reconstructionCall({ documentsReady: false }),
    );
    assert.equal(blockedReconstruction.state, "BLOCKED");
    assert.deepEqual(blockedReconstruction.gap_codes, ["DOCUMENTS_INCOMPLETE"]);
    assert.match(blockedReconstruction.evidence_digest, /^[a-f0-9]{64}$/u);
    assert.match(blockedReconstruction.ledger_state_digest, /^[a-f0-9]{64}$/u);
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
          where company_id = '${companyId}' and income_year = 2029
            and entry_kind = 'OPENING_BALANCE'),
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

    const lockCountBeforeBlockedClose = lastOutputLine(psql(
      containerName,
      ["-Atq"],
      "select count(*) from ledger.period_locks;",
    ));
    const closeReadyReconstruction = jsonOutput(
      containerName,
      reconstructionCall({
        idempotencyKey: "61000000-0000-4000-8000-000000000008",
      }),
    );
    const incompleteCloseEvidence = companyYearCloseEvidence({
      periodEnd: "2026-08-27",
      ledgerStateDigest: closeReadyReconstruction.ledger_state_digest,
      omit: ["MATERIAL_BALANCES_DOCUMENTED"],
    });
    const blockedClose = jsonOutput(containerName, companyYearCloseTransaction({
      idempotencyKey: "65000000-0000-4000-8000-000000000002",
      periodEnd: "2026-08-27",
      reconstructionAssessmentId: closeReadyReconstruction.assessment_id,
      reconstructionDigest: closeReadyReconstruction.evidence_digest,
      reconstructionLedgerStateDigest:
        closeReadyReconstruction.ledger_state_digest,
      evidence: incompleteCloseEvidence,
      derivedState: "BLOCKED",
      gapCodes: ["PERIOD_END_UNSUPPORTED", "CHECK_EVIDENCE_INCOMPLETE"],
    }));
    assert.equal(blockedClose.state, "BLOCKED");
    assert.equal(blockedClose.close_lock_id, null);
    assert.deepEqual(
      blockedClose.gap_codes,
      ["CHECK_EVIDENCE_INCOMPLETE", "PERIOD_END_UNSUPPORTED"],
    );
    assert.equal(lastOutputLine(psql(
      containerName,
      ["-Atq"],
      "select count(*) from ledger.period_locks;",
    )), lockCountBeforeBlockedClose);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.company_year_close_assessments
          where id = '${blockedClose.assessment_id}'),
        (select count(*) from ledger.company_year_close_evidence
          where assessment_id = '${blockedClose.assessment_id}'));
    `)), "1:2");

    const blockedYearEndReconstruction = jsonOutput(
      containerName,
      reconstructionCall({
        idempotencyKey: "61000000-0000-4000-8000-000000000009",
        documentsReady: false,
        asOf: "2026-12-31",
      }),
    );
    const reconstructionBlockedClose = jsonOutput(
      containerName,
      companyYearCloseTransaction({
        idempotencyKey: "65000000-0000-4000-8000-000000000008",
        reconstructionAssessmentId: blockedYearEndReconstruction.assessment_id,
        reconstructionDigest: blockedYearEndReconstruction.evidence_digest,
        reconstructionLedgerStateDigest:
          blockedYearEndReconstruction.ledger_state_digest,
        derivedState: "BLOCKED",
        gapCodes: ["SOURCE_INCOMPLETE"],
      }),
    );
    assert.equal(reconstructionBlockedClose.close_lock_id, null);
    assert.deepEqual(reconstructionBlockedClose.gap_codes, ["SOURCE_INCOMPLETE"]);
    assert.equal(
      reconstructionBlockedClose.gap_codes.includes("DOCUMENTS_INCOMPLETE"),
      false,
    );

    const yearEndReconstruction = jsonOutput(containerName, reconstructionCall({
      idempotencyKey: "61000000-0000-4000-8000-000000000010",
      asOf: "2026-12-31",
    }));
    assert.equal(yearEndReconstruction.state, "READY");
    assert.match(psqlFailure(containerName, companyYearCloseTransaction({
      idempotencyKey: "65000000-0000-4000-8000-000000000003",
      reconstructionAssessmentId: readyReconstruction.assessment_id,
      reconstructionDigest: readyReconstruction.evidence_digest,
      reconstructionLedgerStateDigest: readyReconstruction.ledger_state_digest,
    })), /ledger_company_year_close_reconstruction_stale/iu);
    assert.match(psqlFailure(containerName, companyYearCloseTransaction({
      idempotencyKey: "65000000-0000-4000-8000-000000000004",
      reconstructionAssessmentId: yearEndReconstruction.assessment_id,
      reconstructionDigest: "f".repeat(64),
      reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
    })), /ledger_company_year_close_reconstruction_stale/iu);

    const unresolvedBankClose = jsonOutput(
      containerName,
      companyYearCloseTransaction({
        idempotencyKey: "65000000-0000-4000-8000-000000000009",
        reconstructionAssessmentId: yearEndReconstruction.assessment_id,
        reconstructionDigest: yearEndReconstruction.evidence_digest,
        reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
        evidence: companyYearCloseEvidence({
          ledgerStateDigest: yearEndReconstruction.ledger_state_digest,
          statuses: { BANK_ROWS_RESOLVED: "GAP" },
        }),
        derivedState: "BLOCKED",
        gapCodes: ["UNRESOLVED_BANK_ROW"],
      }),
    );
    assert.equal(unresolvedBankClose.close_lock_id, null);
    assert.deepEqual(unresolvedBankClose.gap_codes, ["UNRESOLVED_BANK_ROW"]);

    const reportingGapClose = jsonOutput(
      containerName,
      companyYearCloseTransaction({
        idempotencyKey: "65000000-0000-4000-8000-000000000015",
        reconstructionAssessmentId: yearEndReconstruction.assessment_id,
        reconstructionDigest: yearEndReconstruction.evidence_digest,
        reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
        evidence: companyYearCloseEvidence({
          ledgerStateDigest: yearEndReconstruction.ledger_state_digest,
          statuses: { REPORTING_RECONCILED: "GAP" },
        }),
        derivedState: "BLOCKED",
        gapCodes: ["REPORTING_NOT_RECONCILED"],
      }),
    );
    assert.equal(reportingGapClose.close_lock_id, null);
    assert.deepEqual(reportingGapClose.gap_codes, ["REPORTING_NOT_RECONCILED"]);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select count(*) from ledger.company_year_close_reporting_outputs
      where assessment_id = '${reportingGapClose.assessment_id}';
    `)), "0");

    const partialCoverageEvidence = companyYearCloseEvidence({
      ledgerStateDigest: yearEndReconstruction.ledger_state_digest,
    });
    partialCoverageEvidence[0].coverageThrough = "2026-12-30";
    const partialCoverageClose = jsonOutput(
      containerName,
      companyYearCloseTransaction({
        idempotencyKey: "65000000-0000-4000-8000-000000000011",
        reconstructionAssessmentId: yearEndReconstruction.assessment_id,
        reconstructionDigest: yearEndReconstruction.evidence_digest,
        reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
        evidence: partialCoverageEvidence,
        derivedState: "BLOCKED",
        gapCodes: ["CHECK_EVIDENCE_INCOMPLETE"],
      }),
    );
    assert.equal(partialCoverageClose.close_lock_id, null);
    assert.deepEqual(
      partialCoverageClose.gap_codes,
      ["CHECK_EVIDENCE_INCOMPLETE"],
    );
    const invalidDateEvidence = companyYearCloseEvidence({
      ledgerStateDigest: yearEndReconstruction.ledger_state_digest,
    });
    invalidDateEvidence[0].coverageThrough = "2026-02-30";
    assert.match(psqlFailure(containerName, companyYearCloseTransaction({
      idempotencyKey: "65000000-0000-4000-8000-000000000012",
      reconstructionAssessmentId: yearEndReconstruction.assessment_id,
      reconstructionDigest: yearEndReconstruction.evidence_digest,
      reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
      evidence: invalidDateEvidence,
      derivedState: "BLOCKED",
      gapCodes: ["CHECK_EVIDENCE_INCOMPLETE"],
    })), /ledger_company_year_close_evidence_invalid/iu);
    const wrongStateDigestEvidence = companyYearCloseEvidence({
      ledgerStateDigest: yearEndReconstruction.ledger_state_digest,
    });
    wrongStateDigestEvidence[0].ledgerStateDigest = "e".repeat(64);
    assert.match(psqlFailure(containerName, companyYearCloseTransaction({
      idempotencyKey: "65000000-0000-4000-8000-000000000016",
      reconstructionAssessmentId: yearEndReconstruction.assessment_id,
      reconstructionDigest: yearEndReconstruction.evidence_digest,
      reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
      evidence: wrongStateDigestEvidence,
    })), /ledger_company_year_close_evidence_invalid/iu);
    const missingOutputEvidence = companyYearCloseEvidence({
      ledgerStateDigest: yearEndReconstruction.ledger_state_digest,
    });
    missingOutputEvidence[2].outputs.pop();
    assert.match(psqlFailure(containerName, companyYearCloseTransaction({
      idempotencyKey: "65000000-0000-4000-8000-000000000017",
      reconstructionAssessmentId: yearEndReconstruction.assessment_id,
      reconstructionDigest: yearEndReconstruction.evidence_digest,
      reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
      evidence: missingOutputEvidence,
    })), /ledger_company_year_close_evidence_invalid/iu);

    assert.equal(psql(containerName, ["-Atq"],
      companyYearCloseReplayTransaction({
        idempotencyKey: "65000000-0000-4000-8000-000000000099",
        reconstructionAssessmentId: yearEndReconstruction.assessment_id,
        reconstructionDigest: yearEndReconstruction.evidence_digest,
        reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
      })).trim(), "");

    const closedCompanyYear = jsonOutput(containerName, companyYearCloseTransaction({
      reconstructionAssessmentId: yearEndReconstruction.assessment_id,
      reconstructionDigest: yearEndReconstruction.evidence_digest,
      reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
    }));
    assert.equal(closedCompanyYear.state, "CLOSED");
    assert.deepEqual(closedCompanyYear.gap_codes, []);
    assert.notEqual(closedCompanyYear.close_lock_id, lockReplay.period_lock_id);
    assert.ok(closedCompanyYear.close_lock_id);
    assert.equal(
      closedCompanyYear.reconstruction_assessment_id,
      yearEndReconstruction.assessment_id,
    );
    assert.match(closedCompanyYear.evidence_digest, /^[a-f0-9]{64}$/u);
    assert.match(closedCompanyYear.ledger_state_digest, /^[a-f0-9]{64}$/u);
    assert.equal(closedCompanyYear.is_current, true);
    assert.equal(closedCompanyYear.replayed, false);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.company_year_close_locks),
        (select count(*) from ledger.company_year_close_reporting_outputs
          where assessment_id = '${closedCompanyYear.assessment_id}'),
        (select bool_and(
          evidence.ledger_state_digest = '${closedCompanyYear.ledger_state_digest}'
        ) from ledger.company_year_close_evidence evidence
          where evidence.assessment_id = '${closedCompanyYear.assessment_id}'),
        (select string_agg(output.kind, ',' order by output.ordinal)
          from ledger.company_year_close_reporting_outputs output
          where output.assessment_id = '${closedCompanyYear.assessment_id}'));
    `)), "1:7:t:INVESTMENTS,CORPORATE_GOVERNANCE,SHAREHOLDER_REGISTER_FILING,COMPANY_TAX_FILING,ANNUAL_ACCOUNTS_FILING,SAF_T,COMPANY_ARCHIVE");
    const closedCompanyYearReplay = jsonOutput(
      containerName,
      companyYearCloseTransaction({
        reconstructionAssessmentId: yearEndReconstruction.assessment_id,
        reconstructionDigest: yearEndReconstruction.evidence_digest,
        reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
      }),
    );
    assert.equal(closedCompanyYearReplay.assessment_id, closedCompanyYear.assessment_id);
    assert.equal(closedCompanyYearReplay.replayed, true);
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      update public.company_memberships
      set role = 'reviewer'
      where company_id = '${companyId}' and user_id = '${ownerId}';
      ${actorContext(ownerId)}
      select * from ledger.get_company_year_close_replay_v1(
        '65000000-0000-4000-8000-000000000001',
        '${companyId}', 2026, date '2026-12-31',
        'Evidence-complete company-year close',
        '${yearEndReconstruction.assessment_id}',
        '${yearEndReconstruction.evidence_digest}',
        '${sqlQuote(JSON.stringify(companyYearCloseEvidence({
          ledgerStateDigest: yearEndReconstruction.ledger_state_digest,
        })))}'::jsonb,
        'ledger-company-year-close-runtime', '${ownerId}'
      );
      commit;
    `), /ledger_forbidden/iu);
    assert.match(psqlFailure(containerName, companyYearCloseReplayTransaction({
      reconstructionAssessmentId: yearEndReconstruction.assessment_id,
      reconstructionDigest: yearEndReconstruction.evidence_digest,
      reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
      correlationId: "changed-replay-correlation",
    })), /ledger_idempotency_key_reused/iu);
    assert.match(psqlFailure(containerName, companyYearCloseTransaction({
      reconstructionAssessmentId: yearEndReconstruction.assessment_id,
      reconstructionDigest: yearEndReconstruction.evidence_digest,
      reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
      reason: "Changed close reason on reused key",
    })), /ledger_idempotency_key_reused/iu);

    const statutoryPostOptions = {
      actorId: otherOwnerId,
      company: otherCompanyId,
      incomeYear: 2026,
      idempotencyKey: "50000000-0000-4000-8000-000000000071",
      entryKind: "ADMINISTRATIVE_COST",
      memo: "Pre-close other-company cost",
      lines: [
        { account: "7795", description: "Administration cost", debit: "75.00", credit: "0.00", currency: "NOK" },
        { account: "1920", description: "Bank", debit: "0.00", credit: "75.00", currency: "NOK" },
      ],
      sourceCapability: "BANKING",
      sourceRecordId: "statutory-close:pre-close-cost",
      correlationId: "statutory-close-pre-close-post",
    };
    const preCloseStatutoryPost = jsonOutput(
      containerName,
      postTransaction(statutoryPostOptions),
    );
    const statutoryReconstruction = jsonOutput(
      containerName,
      reconstructionCall({
        actorId: otherOwnerId,
        company: otherCompanyId,
        idempotencyKey: "61000000-0000-4000-8000-000000000071",
        asOf: "2026-12-31",
      }),
    );
    const freshPostAfterClose = {
      ...statutoryPostOptions,
      idempotencyKey: "50000000-0000-4000-8000-000000000072",
      memo: "Forbidden post-close cost",
      sourceRecordId: "statutory-close:forbidden-cost",
      correlationId: "statutory-close-forbidden-post",
    };
    const statutoryCloseSession = interactivePsql(containerName);
    statutoryCloseSession.child.stdin.write(String.raw`
      set application_name = 'ledger_statutory_close';
      begin;
      ${actorContext(otherOwnerId)}
      ${companyYearCloseCall({
        actorId: otherOwnerId,
        company: otherCompanyId,
        idempotencyKey: "65000000-0000-4000-8000-000000000071",
        reconstructionAssessmentId: statutoryReconstruction.assessment_id,
        reconstructionDigest: statutoryReconstruction.evidence_digest,
        reconstructionLedgerStateDigest: statutoryReconstruction.ledger_state_digest,
        correlationId: "statutory-close-other-company",
      })}
      select 'statutory_close_holds_company_year_lock';
    `);
    await waitForOutput(
      statutoryCloseSession,
      /statutory_close_holds_company_year_lock/u,
    );
    const racedPostSession = interactivePsql(containerName);
    racedPostSession.child.stdin.end(String.raw`
      set application_name = 'ledger_post_during_statutory_close';
      ${postTransaction(freshPostAfterClose)}
    `);
    let racedPostBlocked = false;
    for (let attempt = 0; attempt < 50; attempt += 1) {
      racedPostBlocked = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
        select count(*) from pg_catalog.pg_stat_activity
        where application_name = 'ledger_post_during_statutory_close'
          and wait_event_type = 'Lock' and wait_event = 'advisory';
      `)) === "1";
      if (racedPostBlocked) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.equal(
      racedPostBlocked,
      true,
      "ordinary post did not serialize behind statutory close",
    );
    statutoryCloseSession.child.stdin.end("commit;\n\\q\n");
    const statutoryCloseResult = await processResult(statutoryCloseSession);
    assert.equal(statutoryCloseResult.code, 0, statutoryCloseResult.stderr);
    const statutoryClose = JSON.parse(
      statutoryCloseResult.stdout.split("\n").find((line) => (
        line.startsWith('{"assessment_id"')
      )),
    );
    const racedPostResult = await processResult(racedPostSession);
    assert.notEqual(racedPostResult.code, 0);
    assert.match(racedPostResult.stderr, /ledger_period_locked/iu);
    assert.equal(statutoryClose.state, "CLOSED");
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select count(*) from ledger.period_locks
      where company_id = '${otherCompanyId}' and income_year = 2026;
    `)), "0");
    const postReplayAfterStatutoryClose = jsonOutput(
      containerName,
      postTransaction(statutoryPostOptions),
    );
    assert.equal(
      postReplayAfterStatutoryClose.ledger_entry_id,
      preCloseStatutoryPost.ledger_entry_id,
    );
    assert.equal(postReplayAfterStatutoryClose.replayed, true);

    const supportedPostAfterStatutoryClose = String.raw`
      begin;
      ${actorContext(otherOwnerId)}
      select * from ledger.post_supported_entry_v1(
        '62000000-0000-4000-8000-000000000072', '${otherCompanyId}', 2026,
        'BANK_INTEREST', 'Forbidden post-close bank interest',
        '[{"account":"1920","description":"Bank","debit":"25.00","credit":"0.00","currency":"NOK"},
          {"account":"8050","description":"Interest","debit":"0.00","credit":"25.00","currency":"NOK"}]'::jsonb,
        'BANKING', 'statutory-close:forbidden-interest',
        'statutory-close-forbidden-supported', '${otherOwnerId}',
        '2026-12-31', 'ledger-supported-patterns-2026.1',
        '[{"role":"PRIMARY","capability":"BANKING","recordId":"statutory-close:forbidden-interest","revision":1,"factSha256":"${"d".repeat(64)}"}]'::jsonb
      );
      commit;
    `;
    assert.match(
      psqlFailure(containerName, supportedPostAfterStatutoryClose),
      /ledger_period_locked/iu,
    );
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.entries
          where company_id = '${otherCompanyId}'
            and source_record_id in (
              'statutory-close:forbidden-cost',
              'statutory-close:forbidden-interest'
            )),
        (select count(*) from backend_system.ledger_command_receipts
          where company_id = '${otherCompanyId}'
            and idempotency_key in (
              '50000000-0000-4000-8000-000000000072',
              '62000000-0000-4000-8000-000000000072'
            )));
    `)), "0:0");

    const linkedCorrectionAfterStatutoryClose = jsonOutput(
      containerName,
      correctionTransaction({
        actorId: otherOwnerId,
        company: otherCompanyId,
        originalEntryId: preCloseStatutoryPost.ledger_entry_id,
        idempotencyKey: "63000000-0000-4000-8000-000000000071",
        correlationId: "statutory-close-linked-correction",
        sources: [
          { role: "PRIMARY", capability: "DOCUMENTS", recordId: "statutory-close:correction-document", revision: 1, factSha256: "e".repeat(64) },
          { role: "CORROBORATING", capability: "BANKING", recordId: "statutory-close:correction-bank", revision: 1, factSha256: "f".repeat(64) },
        ],
      }),
    );
    assert.equal(linkedCorrectionAfterStatutoryClose.company_id, otherCompanyId);
    assert.equal(linkedCorrectionAfterStatutoryClose.replayed, false);

    assert.match(psqlFailure(containerName, companyYearCloseTransaction({
      actorId: reviewerId,
      idempotencyKey: "65000000-0000-4000-8000-000000000005",
      reconstructionAssessmentId: yearEndReconstruction.assessment_id,
      reconstructionDigest: yearEndReconstruction.evidence_digest,
      reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
    })), /ledger_forbidden/iu);
    assert.match(psqlFailure(containerName, String.raw`
      begin;
      set local role ledger_executor;
      insert into ledger.company_year_close_assessments (
        company_id, income_year, period_end, reason,
        reconstruction_assessment_id, reconstruction_digest, state, gap_codes,
        evidence_digest, ledger_state_digest, correlation_id, recorded_by
      ) values (
        '${companyId}', 2026, date '2026-12-31', 'Forged close',
        '${yearEndReconstruction.assessment_id}',
        '${yearEndReconstruction.evidence_digest}', 'BLOCKED',
        array['SOURCE_INCOMPLETE']::text[], '${"1".repeat(64)}',
        '${"2".repeat(64)}', 'forged-close', '${ownerId}'
      );
      commit;
    `), /permission denied/iu);
    const staleCloseDigest = closedCompanyYear.ledger_state_digest;

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
    assert.match(psqlFailure(containerName, correctionTransaction({
      originalEntryId: correctionOriginal.ledger_entry_id,
      idempotencyKey: "63000000-0000-4000-8000-000000000007",
      incomeYear: 2025,
      eventDate: "2025-08-27",
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

    const closeReplayBeforeFreshness = jsonOutput(
      containerName,
      companyYearCloseReplayTransaction({
        reconstructionAssessmentId: yearEndReconstruction.assessment_id,
        reconstructionDigest: yearEndReconstruction.evidence_digest,
        reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
      }),
    );
    assert.equal(closeReplayBeforeFreshness.assessment_id, closedCompanyYear.assessment_id);
    assert.equal(closeReplayBeforeFreshness.ledger_state_digest, staleCloseDigest);
    assert.equal(closeReplayBeforeFreshness.is_current, false);
    assert.equal(closeReplayBeforeFreshness.replayed, true);
    assert.match(psqlFailure(containerName, companyYearCloseTransaction({
      idempotencyKey: "65000000-0000-4000-8000-000000000006",
      reconstructionAssessmentId: yearEndReconstruction.assessment_id,
      reconstructionDigest: yearEndReconstruction.evidence_digest,
      reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
      correlationId: "ledger-company-year-reclose-runtime",
    })), /ledger_company_year_close_reconstruction_stale/iu);

    const refreshedYearEndReconstruction = jsonOutput(
      containerName,
      reconstructionCall({
        idempotencyKey: "61000000-0000-4000-8000-000000000011",
        asOf: "2026-12-31",
      }),
    );
    assert.notEqual(
      refreshedYearEndReconstruction.ledger_state_digest,
      yearEndReconstruction.ledger_state_digest,
    );
    const refreshedCloseEvidence = companyYearCloseEvidence({
      ledgerStateDigest: refreshedYearEndReconstruction.ledger_state_digest,
      revision: 2,
    });
    const reclosedCompanyYear = jsonOutput(containerName, companyYearCloseTransaction({
      idempotencyKey: "65000000-0000-4000-8000-000000000006",
      reconstructionAssessmentId: refreshedYearEndReconstruction.assessment_id,
      reconstructionDigest: refreshedYearEndReconstruction.evidence_digest,
      reconstructionLedgerStateDigest:
        refreshedYearEndReconstruction.ledger_state_digest,
      evidence: refreshedCloseEvidence,
      correlationId: "ledger-company-year-reclose-runtime",
    }));
    assert.equal(reclosedCompanyYear.state, "CLOSED");
    assert.equal(reclosedCompanyYear.close_lock_id, closedCompanyYear.close_lock_id);
    assert.notEqual(reclosedCompanyYear.assessment_id, closedCompanyYear.assessment_id);
    assert.notEqual(reclosedCompanyYear.ledger_state_digest, staleCloseDigest);
    const historicalCloseReplay = jsonOutput(
      containerName,
      companyYearCloseReplayTransaction({
        reconstructionAssessmentId: yearEndReconstruction.assessment_id,
        reconstructionDigest: yearEndReconstruction.evidence_digest,
        reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
      }),
    );
    assert.equal(historicalCloseReplay.assessment_id, closedCompanyYear.assessment_id);
    assert.equal(historicalCloseReplay.ledger_state_digest, staleCloseDigest);
    assert.equal(historicalCloseReplay.is_current, false);
    assert.equal(historicalCloseReplay.replayed, true);
    const latestCloseAssessment = jsonOutput(
      containerName,
      latestCompanyYearCloseTransaction(),
    );
    assert.equal(latestCloseAssessment.assessment_id, reclosedCompanyYear.assessment_id);
    assert.equal(latestCloseAssessment.reconstruction_assessment_id,
      refreshedYearEndReconstruction.assessment_id);
    assert.equal(latestCloseAssessment.is_current, true);

    const journalDefenseEntryId = "40000000-0000-0000-0000-000000000088";
    psql(containerName, [], String.raw`
      alter table ledger.entries disable trigger ledger_entries_enforce_boundary;
      insert into ledger.entries (
        id, company_id, income_year, entry_kind, memo, lines, risk_flags,
        warning_accepted_by, warning_accepted_at, posted_at, created_by,
        created_at, source_capability, source_record_id, correlation_id
      ) select
        '${journalDefenseEntryId}', company_id, income_year, 'MANUAL_JOURNAL',
        'Defense-in-depth unbalanced fixture',
        '[{"account":"7795","description":"Cost","debit":"25.00","credit":"0.00","currency":"NOK"},
          {"account":"1920","description":"Bank","debit":"0.00","credit":"20.00","currency":"NOK"}]'::jsonb,
        '[]'::jsonb, null, null, pg_catalog.statement_timestamp(),
        '${ownerId}', pg_catalog.statement_timestamp(), 'LEDGER',
        'defense:journal-unbalanced', 'defense-journal-unbalanced'
      from ledger.entries where id = '${correctionOriginal.ledger_entry_id}';
      alter table ledger.entries enable trigger ledger_entries_enforce_boundary;
    `);
    const journalDefenseReconstruction = jsonOutput(
      containerName,
      reconstructionCall({
        idempotencyKey: "61000000-0000-4000-8000-000000000012",
        asOf: "2026-12-31",
      }),
    );
    const journalUnbalancedClose = jsonOutput(
      containerName,
      companyYearCloseTransaction({
        idempotencyKey: "65000000-0000-4000-8000-000000000013",
        reconstructionAssessmentId: journalDefenseReconstruction.assessment_id,
        reconstructionDigest: journalDefenseReconstruction.evidence_digest,
        reconstructionLedgerStateDigest:
          journalDefenseReconstruction.ledger_state_digest,
        evidence: companyYearCloseEvidence({
          ledgerStateDigest: journalDefenseReconstruction.ledger_state_digest,
          revision: 3,
        }),
      }),
    );
    assert.equal(journalUnbalancedClose.state, "BLOCKED");
    assert.deepEqual(journalUnbalancedClose.gap_codes, ["JOURNAL_UNBALANCED"]);
    assert.equal(journalUnbalancedClose.close_lock_id, null);
    psql(containerName, [], String.raw`
      delete from ledger.entries where id = '${journalDefenseEntryId}';
    `);

    const duplicateDefenseEntryId = "40000000-0000-0000-0000-000000000089";
    psql(containerName, [], String.raw`
      drop index ledger.ledger_entries_source_capability_record_uidx;
      insert into ledger.entries (
        id, company_id, income_year, entry_kind, memo, lines, risk_flags,
        warning_accepted_by, warning_accepted_at, posted_at, created_by,
        created_at, source_capability, source_record_id, correlation_id
      ) select
        '${duplicateDefenseEntryId}', company_id, income_year, entry_kind,
        'Defense-in-depth duplicate fixture', lines, risk_flags,
        warning_accepted_by, warning_accepted_at,
        pg_catalog.statement_timestamp(), '${ownerId}',
        pg_catalog.statement_timestamp(), source_capability, source_record_id,
        'defense-duplicate-posting'
      from ledger.entries where id = '${correctionOriginal.ledger_entry_id}';
    `);
    const duplicateDefenseReconstruction = jsonOutput(
      containerName,
      reconstructionCall({
        idempotencyKey: "61000000-0000-4000-8000-000000000013",
        asOf: "2026-12-31",
      }),
    );
    const duplicatePostingClose = jsonOutput(
      containerName,
      companyYearCloseTransaction({
        idempotencyKey: "65000000-0000-4000-8000-000000000014",
        reconstructionAssessmentId: duplicateDefenseReconstruction.assessment_id,
        reconstructionDigest: duplicateDefenseReconstruction.evidence_digest,
        reconstructionLedgerStateDigest:
          duplicateDefenseReconstruction.ledger_state_digest,
        evidence: companyYearCloseEvidence({
          ledgerStateDigest: duplicateDefenseReconstruction.ledger_state_digest,
          revision: 4,
        }),
      }),
    );
    assert.equal(duplicatePostingClose.state, "BLOCKED");
    assert.deepEqual(duplicatePostingClose.gap_codes, ["DUPLICATE_POSTING_FOUND"]);
    assert.equal(duplicatePostingClose.close_lock_id, null);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select count(*) from ledger.company_year_close_locks;
    `)), "2");
    psql(containerName, [], String.raw`
      delete from ledger.entries where id = '${duplicateDefenseEntryId}';
      create unique index ledger_entries_source_capability_record_uidx
        on ledger.entries(company_id, source_capability, source_record_id);
    `);

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
        (select count(*) from ledger.company_year_close_assessments),
        (select count(*) from ledger.company_year_close_evidence),
        (select count(*) from ledger.company_year_close_locks),
        (select count(*) from ledger.company_year_close_reporting_outputs),
        (select count(*) from ledger.received_dividend_decisions),
        (select count(*) from ledger.received_dividend_settlements),
        (select count(*) from ledger.bank_loan_anchors),
        (select count(*) from ledger.bank_loan_payment_allocations),
        (select count(*) from ledger.cash_capital_increase_phases),
        (select count(*) from backend_system.ledger_command_receipts),
        encode(extensions.digest(coalesce((select string_agg(id::text || '|' || lines::text, E'\n' order by id)
          from ledger.entries), ''), 'sha256'), 'hex'));
    `));

    psql(containerName, ["--file", rollbackPath]);
    assert.match(psqlFailure(containerName, receivedDividendDecisionTransaction({
      idempotencyKey: "66000000-0000-4000-8000-000000000010",
      sourceRecordId: "received-dividend-rollback-denied",
      sources: [
        { role: "PRIMARY", capability: "INVESTMENTS", recordId: "received-dividend-rollback-denied", revision: 1, factSha256: "a".repeat(64) },
        { role: "CORROBORATING", capability: "DOCUMENTS", recordId: "received-dividend-rollback-document", revision: 1, factSha256: "b".repeat(64) },
        { role: "CORROBORATING", capability: "COMPANY_TAX_FILING", recordId: "received-dividend-rollback-tax", revision: 1, factSha256: "c".repeat(64) },
      ],
    })), /permission denied/iu);
    assert.match(psqlFailure(containerName, receivedDividendPaymentTransaction({
      decisionEntryId: receivedDividendDecision.ledger_entry_id,
      idempotencyKey: "66000000-0000-4000-8000-000000000011",
    })), /permission denied/iu);
    assert.match(psqlFailure(containerName, bankLoanDisbursementTransaction({
      idempotencyKey: "67000000-0000-4000-8000-000000000012",
      loanReference: "bank-loan:rollback-denied",
      sourceRecordId: "bank-loan-rollback-disbursement-denied",
      correlationId: "bank-loan-rollback-disbursement-denied",
      sources: [{
        role: "PRIMARY",
        capability: "BANKING",
        recordId: "bank-loan-rollback-disbursement-denied",
        revision: 1,
        factSha256: "8".repeat(64),
      }],
    })), /permission denied/iu);
    assert.match(psqlFailure(containerName, bankLoanPaymentTransaction({
      idempotencyKey: "67000000-0000-4000-8000-000000000013",
      sourceRecordId: "bank-loan-rollback-payment-denied",
      correlationId: "bank-loan-rollback-payment-denied",
      sources: [{
        role: "PRIMARY",
        capability: "BANKING",
        recordId: "bank-loan-rollback-payment-denied",
        revision: 1,
        factSha256: "9".repeat(64),
      }],
    })), /permission denied/iu);
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalSubscriptionOptions,
      idempotencyKey: "68000000-0000-4000-8000-000000000026",
      capitalIncreaseReference: "capital-increase:rollback-denied",
      sourceRecordId: "cash-capital-increase-rollback-subscription-denied",
    })), /permission denied/iu);
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalRestrictedPaymentOptions,
      idempotencyKey: "68000000-0000-4000-8000-000000000027",
      sourceRecordId: "cash-capital-increase-rollback-payment-denied",
    })), /permission denied/iu);
    assert.match(psqlFailure(containerName, cashCapitalIncreaseTransaction({
      ...capitalRegistrationOptions,
      idempotencyKey: "68000000-0000-4000-8000-000000000028",
      sourceRecordId: "cash-capital-increase-rollback-registration-denied",
    })), /permission denied/iu);
    assert.match(psqlFailure(containerName, correctionTransaction({
      originalEntryId: correctionOriginal.ledger_entry_id,
    })), /permission denied/iu);
    assert.match(psqlFailure(containerName, companyYearCloseTransaction({
      idempotencyKey: "65000000-0000-4000-8000-000000000007",
      reconstructionAssessmentId: yearEndReconstruction.assessment_id,
      reconstructionDigest: yearEndReconstruction.evidence_digest,
      reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
    })), /permission denied/iu);
    assert.match(psqlFailure(containerName, reconstructionCall({
      idempotencyKey: "61000000-0000-4000-8000-000000000099",
      asOf: "2026-12-31",
    })), /permission denied/iu);
    assert.equal(lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        has_function_privilege(
          'ledger_executor',
          'ledger.post_supported_entry_v1(text,uuid,integer,text,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ),
        has_function_privilege(
          'ledger_executor',
          'ledger.correct_entry_v1(text,uuid,integer,uuid,text,text,text,jsonb,text,text,date,text,text,jsonb)',
          'execute'
        ),
        has_function_privilege(
          'ledger_executor',
          'ledger.record_reconstruction_assessment(text,uuid,integer,date,jsonb,text,text[],text,text)',
          'execute'
        ),
        has_function_privilege(
          'ledger_executor',
          'ledger.close_company_year_v1(text,uuid,integer,date,text,uuid,text,jsonb,text,text[],text,text)',
          'execute'
        ),
        has_function_privilege(
          'ledger_executor',
          'ledger.record_received_dividend_decision_v1(text,uuid,integer,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ),
        has_function_privilege(
          'ledger_executor',
          'ledger.record_received_dividend_payment_v1(text,uuid,integer,uuid,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ),
        has_function_privilege(
          'ledger_executor',
          'ledger.record_bank_loan_disbursement_v1(text,uuid,integer,text,numeric,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ),
        has_function_privilege(
          'ledger_executor',
          'ledger.record_bank_loan_payment_v1(text,uuid,integer,text,numeric,numeric,numeric,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ),
        has_function_privilege(
          'ledger_executor',
          'ledger.record_cash_capital_increase_subscription_v1(text,uuid,integer,text,numeric,numeric,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ),
        has_function_privilege(
          'ledger_executor',
          'ledger.record_cash_capital_increase_restricted_payment_v1(text,uuid,integer,text,numeric,numeric,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ),
        has_function_privilege(
          'ledger_executor',
          'ledger.record_cash_capital_increase_registration_v1(text,uuid,integer,text,numeric,numeric,text,jsonb,text,text,text,text,date,text,jsonb)',
          'execute'
        ));
    `)), "f:f:f:f:f:f:f:f:f:f:f");
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
      set local request.jwt.claim.sub = '${otherOwnerId}';
      insert into public.ledger_entries (
        id, company_id, income_year, entry_type, memo, lines, risk_flags,
        posted_at, created_by, created_at
      ) values (
        '64000000-0000-4000-8000-000000000071', '${otherCompanyId}', 2026,
        'manual_journal', 'Forbidden rollback-window post-close write',
        '[{"account":"7795","description":"Cost","debit":"25.00","credit":"0.00","currency":"NOK"},
          {"account":"1920","description":"Bank","debit":"0.00","credit":"25.00","currency":"NOK"}]'::jsonb,
        '[]'::jsonb, timestamptz '2026-12-31 23:00:00+00', '${otherOwnerId}',
        timestamptz '2026-12-31 23:00:00+00'
      );
      commit;
    `), /ledger_period_locked/iu);
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
    psql(containerName, ["--file", companyYearClosePath]);
    psql(containerName, ["--file", receivedDividendPath]);
    psql(containerName, ["--file", bankLoanPath]);
    psql(containerName, ["--file", cashCapitalIncreasePath]);
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
    const recutoverCloseReplay = jsonOutput(
      containerName,
      companyYearCloseReplayTransaction({
        reconstructionAssessmentId: yearEndReconstruction.assessment_id,
        reconstructionDigest: yearEndReconstruction.evidence_digest,
        reconstructionLedgerStateDigest: yearEndReconstruction.ledger_state_digest,
      }),
    );
    assert.equal(recutoverCloseReplay.assessment_id, closedCompanyYear.assessment_id);
    assert.equal(recutoverCloseReplay.ledger_state_digest, staleCloseDigest);
    assert.equal(recutoverCloseReplay.is_current, false);
    assert.equal(recutoverCloseReplay.replayed, true);
    const recutoverReceivedDividendDecision = jsonOutput(
      containerName,
      receivedDividendDecisionTransaction(),
    );
    assert.equal(
      recutoverReceivedDividendDecision.ledger_entry_id,
      receivedDividendDecision.ledger_entry_id,
    );
    assert.equal(recutoverReceivedDividendDecision.replayed, true);
    const recutoverReceivedDividendPayment = jsonOutput(
      containerName,
      receivedDividendPaymentTransaction({
        decisionEntryId: receivedDividendDecision.ledger_entry_id,
      }),
    );
    assert.equal(
      recutoverReceivedDividendPayment.ledger_entry_id,
      receivedDividendPayment.ledger_entry_id,
    );
    assert.equal(recutoverReceivedDividendPayment.replayed, true);
    const recutoverYearBoundaryDecision = jsonOutput(
      containerName,
      receivedDividendDecisionTransaction(yearBoundaryDecisionOptions),
    );
    assert.equal(
      recutoverYearBoundaryDecision.ledger_entry_id,
      yearBoundaryDecision.ledger_entry_id,
    );
    assert.equal(recutoverYearBoundaryDecision.replayed, true);
    const recutoverYearBoundaryPayment = jsonOutput(
      containerName,
      receivedDividendPaymentTransaction(yearBoundaryPaymentOptions),
    );
    assert.equal(
      recutoverYearBoundaryPayment.ledger_entry_id,
      yearBoundaryPayment.ledger_entry_id,
    );
    assert.equal(recutoverYearBoundaryPayment.replayed, true);
    const recutoverBankLoanDisbursement = jsonOutput(
      containerName,
      bankLoanDisbursementTransaction(bankLoanDisbursementOptions),
    );
    assert.equal(
      recutoverBankLoanDisbursement.ledger_entry_id,
      bankLoanDisbursement.ledger_entry_id,
    );
    assert.equal(recutoverBankLoanDisbursement.replayed, true);
    const recutoverBankLoanPayment = jsonOutput(
      containerName,
      bankLoanPaymentTransaction(firstLoanPaymentOptions),
    );
    assert.equal(
      recutoverBankLoanPayment.ledger_entry_id,
      firstLoanPayment.ledger_entry_id,
    );
    assert.equal(recutoverBankLoanPayment.replayed, true);
    const recutoverCapitalSubscription = jsonOutput(
      containerName,
      cashCapitalIncreaseTransaction(capitalSubscriptionOptions),
    );
    assert.equal(
      recutoverCapitalSubscription.ledger_entry_id,
      capitalSubscription.ledger_entry_id,
    );
    assert.equal(recutoverCapitalSubscription.replayed, true);
    const recutoverCapitalRestrictedPayment = jsonOutput(
      containerName,
      cashCapitalIncreaseTransaction(capitalRestrictedPaymentOptions),
    );
    assert.equal(
      recutoverCapitalRestrictedPayment.ledger_entry_id,
      capitalRestrictedPayment.ledger_entry_id,
    );
    assert.equal(recutoverCapitalRestrictedPayment.replayed, true);
    const recutoverCapitalRegistration = jsonOutput(
      containerName,
      cashCapitalIncreaseTransaction(capitalRegistrationOptions),
    );
    assert.equal(
      recutoverCapitalRegistration.ledger_entry_id,
      capitalRegistration.ledger_entry_id,
    );
    assert.equal(recutoverCapitalRegistration.replayed, true);

    const durableAfterRecutover = lastOutputLine(psql(containerName, ["-Atq"], String.raw`
      select concat_ws(':',
        (select count(*) from ledger.entries) - 1,
        (select count(*) from ledger.period_locks),
        (select count(*) from ledger.company_year_close_assessments),
        (select count(*) from ledger.company_year_close_evidence),
        (select count(*) from ledger.company_year_close_locks),
        (select count(*) from ledger.company_year_close_reporting_outputs),
        (select count(*) from ledger.received_dividend_decisions),
        (select count(*) from ledger.received_dividend_settlements),
        (select count(*) from ledger.bank_loan_anchors),
        (select count(*) from ledger.bank_loan_payment_allocations),
        (select count(*) from ledger.cash_capital_increase_phases),
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
