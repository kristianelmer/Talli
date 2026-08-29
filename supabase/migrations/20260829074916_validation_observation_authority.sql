-- Private, fail-closed authority and bounded storage for invited validation.
-- The migration provisions no run, entitlement, reviewer, participant or event.

begin;

create schema if not exists backend_system;

do $roles$
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'validation_observation_store_owner') then
    create role validation_observation_store_owner nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'validation_observation_writer_executor') then
    create role validation_observation_writer_executor nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'validation_observation_reviewer_executor') then
    create role validation_observation_reviewer_executor nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'validation_observation_provisioner_executor') then
    create role validation_observation_provisioner_executor nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'validation_observation_maintenance_executor') then
    create role validation_observation_maintenance_executor nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'validation_observation_gate_executor') then
    create role validation_observation_gate_executor nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'talli_validation_observation_backend') then
    create role talli_validation_observation_backend nologin noinherit nobypassrls;
  end if;
end
$roles$;

select pg_catalog.set_config(
  'talli.validation_observation_migration_principal', current_user, true
);
do $migration_authority$
begin
  execute pg_catalog.format(
    'grant ledger_store_owner, validation_observation_store_owner to %I',
    current_user
  );
end
$migration_authority$;

alter role validation_observation_store_owner nologin noinherit nobypassrls;
alter role validation_observation_writer_executor nologin noinherit nobypassrls;
alter role validation_observation_reviewer_executor nologin noinherit nobypassrls;
alter role validation_observation_provisioner_executor nologin noinherit nobypassrls;
alter role validation_observation_maintenance_executor nologin noinherit nobypassrls;
alter role validation_observation_gate_executor nologin noinherit nobypassrls;
alter role talli_validation_observation_backend nologin noinherit nobypassrls;

grant validation_observation_writer_executor
to talli_validation_observation_backend;

set local role ledger_store_owner;
grant usage, create on schema backend_system to validation_observation_store_owner;
reset role;
grant usage on schema backend_system to
  validation_observation_writer_executor,
  validation_observation_reviewer_executor,
  validation_observation_provisioner_executor,
  validation_observation_maintenance_executor,
  validation_observation_gate_executor;

set local role validation_observation_store_owner;

create table backend_system.validation_observation_control (
  singleton boolean primary key default true check (singleton),
  mode text not null default 'off' check (mode = any (array['off', 'invited-pilot'])),
  changed_at timestamptz not null default pg_catalog.clock_timestamp()
);

create table backend_system.validation_runs (
  run_id text primary key check (run_id ~ '^V2P8-[0-9]{8}-[A-Z0-9]{4,16}$'),
  release_sha256 text not null check (release_sha256 ~ '^[0-9a-f]{64}$'),
  participant_information_version text not null
    check (participant_information_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
  participant_information_sha256 text not null
    check (participant_information_sha256 ~ '^[0-9a-f]{64}$'),
  starts_at timestamptz not null,
  expires_at timestamptz not null,
  retention_days smallint not null check (retention_days between 1 and 90),
  retention_approved_at timestamptz not null default pg_catalog.clock_timestamp(),
  approved_by uuid not null,
  status text not null default 'approved' check (status = any (array['approved', 'closed'])),
  created_at timestamptz not null default pg_catalog.clock_timestamp(),
  check (expires_at > starts_at and expires_at <= starts_at + interval '90 days')
);

create table backend_system.validation_pilot_entitlements (
  entitlement_id uuid primary key,
  run_id text not null references backend_system.validation_runs(run_id),
  case_code text not null check (case_code ~ '^V-(0[1-9]|1[0-2])$'),
  subject_binding_sha256 text not null check (subject_binding_sha256 ~ '^[0-9a-f]{64}$'),
  starts_at timestamptz not null,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  withdrawn_at timestamptz,
  created_at timestamptz not null default pg_catalog.clock_timestamp(),
  unique (run_id, case_code),
  unique (run_id, entitlement_id),
  check (expires_at > starts_at and expires_at <= starts_at + interval '90 days'),
  check (revoked_at is null or withdrawn_at is null)
);

create table backend_system.validation_reviewers (
  run_id text not null references backend_system.validation_runs(run_id),
  actor_id uuid not null,
  starts_at timestamptz not null,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  created_at timestamptz not null default pg_catalog.clock_timestamp(),
  primary key (run_id, actor_id),
  check (expires_at > starts_at and expires_at <= starts_at + interval '90 days')
);

create table backend_system.validation_observations (
  observation_id uuid primary key,
  entitlement_id uuid not null,
  run_id text not null,
  case_code text not null check (case_code ~ '^V-(0[1-9]|1[0-2])$'),
  task_code text not null check (task_code = any (array[
    'eligibility_precheck', 'eligibility_definitive', 'company_year_admission',
    'opening_reconstruction', 'bank_connection', 'bank_import', 'bookkeeping',
    'year_close', 'shareholder_register_filing', 'company_tax_filing',
    'annual_accounts_filing', 'archive_export'
  ])),
  state_code text not null check (state_code = any (array[
    'started', 'completed', 'failed', 'blocked'
  ])),
  stage_code text not null check (stage_code = any (array[
    'eligibility', 'onboarding', 'reconstruction', 'banking', 'bookkeeping',
    'year_close', 'shareholder_register', 'company_tax', 'annual_accounts', 'archive'
  ])),
  reason_code text not null check (reason_code = any (array[
    'none', 'unsupported_boundary', 'missing_evidence', 'authorization_required',
    'provider_unavailable', 'technical_failure', 'difference_detected',
    'participant_withdrew'
  ])),
  elapsed_milliseconds integer not null check (elapsed_milliseconds between 0 and 86400000),
  intervention_type text not null check (intervention_type = any (array[
    'none', 'navigation_help', 'evidence_help', 'technical_support'
  ])),
  intervention_count smallint not null check (intervention_count between 0 and 100),
  intervention_milliseconds integer not null
    check (intervention_milliseconds between 0 and 86400000),
  difference_classification text not null check (difference_classification = any (array[
    'none', 'talli_defect', 'source_defect', 'presentation_only', 'unresolved_judgment'
  ])),
  rerun_result text not null check (rerun_result = any (array[
    'not_required', 'pending', 'passed', 'failed'
  ])),
  package_outcome text not null check (package_outcome = any (array[
    'not_applicable', 'pending', 'accepted', 'blocked', 'failed'
  ])),
  received_at timestamptz not null default pg_catalog.clock_timestamp(),
  retained_until timestamptz not null,
  foreign key (run_id, entitlement_id)
    references backend_system.validation_pilot_entitlements(run_id, entitlement_id),
  check (retained_until > received_at and retained_until <= received_at + interval '90 days')
);

insert into backend_system.validation_observation_control (singleton, mode)
values (true, 'off');

alter table backend_system.validation_observation_control enable row level security;
alter table backend_system.validation_observation_control force row level security;
alter table backend_system.validation_runs enable row level security;
alter table backend_system.validation_runs force row level security;
alter table backend_system.validation_pilot_entitlements enable row level security;
alter table backend_system.validation_pilot_entitlements force row level security;
alter table backend_system.validation_reviewers enable row level security;
alter table backend_system.validation_reviewers force row level security;
alter table backend_system.validation_observations enable row level security;
alter table backend_system.validation_observations force row level security;

create policy validation_observation_control_owner_policy
on backend_system.validation_observation_control for all
to validation_observation_store_owner using (true) with check (true);
create policy validation_runs_owner_policy
on backend_system.validation_runs for all
to validation_observation_store_owner using (true) with check (true);
create policy validation_pilot_entitlements_owner_policy
on backend_system.validation_pilot_entitlements for all
to validation_observation_store_owner using (true) with check (true);
create policy validation_reviewers_owner_policy
on backend_system.validation_reviewers for all
to validation_observation_store_owner using (true) with check (true);
create policy validation_observations_owner_policy
on backend_system.validation_observations for all
to validation_observation_store_owner using (true) with check (true);

create index validation_entitlements_active_idx
on backend_system.validation_pilot_entitlements (expires_at, starts_at)
where revoked_at is null and withdrawn_at is null;
create index validation_observations_run_case_received_idx
on backend_system.validation_observations (run_id, case_code, received_at);
create index validation_observations_retained_until_idx
on backend_system.validation_observations (retained_until);
create index validation_reviewers_active_idx
on backend_system.validation_reviewers (actor_id, run_id, expires_at)
where revoked_at is null;

create or replace function backend_system.provision_validation_run_v1(
  p_run_id text,
  p_release_sha256 text,
  p_participant_information_version text,
  p_participant_information_sha256 text,
  p_starts_at timestamptz,
  p_expires_at timestamptz,
  p_retention_days integer,
  p_approved_by uuid
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if p_run_id is null or p_run_id !~ '^V2P8-[0-9]{8}-[A-Z0-9]{4,16}$'
    or p_release_sha256 is null or p_release_sha256 !~ '^[0-9a-f]{64}$'
    or p_participant_information_version is null
    or p_participant_information_version !~ '^[a-z0-9][a-z0-9._-]{0,63}$'
    or p_participant_information_sha256 is null
    or p_participant_information_sha256 !~ '^[0-9a-f]{64}$'
    or p_starts_at is null or p_expires_at is null
    or p_expires_at <= p_starts_at or p_expires_at > p_starts_at + interval '90 days'
    or p_retention_days is null or p_retention_days < 1 or p_retention_days > 90
    or p_approved_by is null
  then
    raise exception 'validation_observation_invalid_run';
  end if;
  insert into backend_system.validation_runs (
    run_id, release_sha256, participant_information_version,
    participant_information_sha256, starts_at, expires_at,
    retention_days, approved_by
  ) values (
    p_run_id, p_release_sha256, p_participant_information_version,
    p_participant_information_sha256, p_starts_at, p_expires_at,
    p_retention_days, p_approved_by
  );
  return true;
end
$function$;

create or replace function backend_system.provision_validation_entitlement_v1(
  p_entitlement_id uuid,
  p_run_id text,
  p_case_code text,
  p_subject_binding_sha256 text,
  p_starts_at timestamptz,
  p_expires_at timestamptz
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_run backend_system.validation_runs%rowtype;
begin
  select * into strict v_run from backend_system.validation_runs
  where run_id = p_run_id and status = 'approved';
  if p_entitlement_id is null
    or p_case_code is null or p_case_code !~ '^V-(0[1-9]|1[0-2])$'
    or p_subject_binding_sha256 is null or p_subject_binding_sha256 !~ '^[0-9a-f]{64}$'
    or p_starts_at is null or p_expires_at is null
    or p_starts_at < v_run.starts_at or p_expires_at > v_run.expires_at
    or p_expires_at <= p_starts_at
  then
    raise exception 'validation_observation_invalid_entitlement';
  end if;
  insert into backend_system.validation_pilot_entitlements (
    entitlement_id, run_id, case_code, subject_binding_sha256, starts_at, expires_at
  ) values (
    p_entitlement_id, p_run_id, p_case_code, p_subject_binding_sha256,
    p_starts_at, p_expires_at
  );
  return true;
exception when no_data_found then
  raise exception 'validation_observation_invalid_run';
end
$function$;

create or replace function backend_system.provision_validation_reviewer_v1(
  p_run_id text,
  p_actor_id uuid,
  p_starts_at timestamptz,
  p_expires_at timestamptz
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_run backend_system.validation_runs%rowtype;
begin
  select * into strict v_run from backend_system.validation_runs
  where run_id = p_run_id and status = 'approved';
  if p_actor_id is null or p_starts_at < v_run.starts_at
    or p_expires_at > v_run.expires_at or p_expires_at <= p_starts_at
  then
    raise exception 'validation_observation_invalid_reviewer';
  end if;
  insert into backend_system.validation_reviewers (
    run_id, actor_id, starts_at, expires_at
  ) values (p_run_id, p_actor_id, p_starts_at, p_expires_at);
  return true;
exception when no_data_found then
  raise exception 'validation_observation_invalid_run';
end
$function$;

create or replace function backend_system.set_validation_observation_mode_v1(
  p_mode text
)
returns text
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if p_mode is null or p_mode <> all (array['off', 'invited-pilot']) then
    raise exception 'validation_observation_invalid_mode';
  end if;
  if p_mode = 'invited-pilot' and not exists (
    select 1
    from backend_system.validation_pilot_entitlements entitlement
    join backend_system.validation_runs run on run.run_id = entitlement.run_id
    where run.status = 'approved'
      and pg_catalog.clock_timestamp() >= run.starts_at
      and pg_catalog.clock_timestamp() < run.expires_at
      and pg_catalog.clock_timestamp() >= entitlement.starts_at
      and pg_catalog.clock_timestamp() < entitlement.expires_at
      and entitlement.revoked_at is null and entitlement.withdrawn_at is null
  ) then
    raise exception 'validation_observation_no_active_entitlement';
  end if;
  update backend_system.validation_observation_control
  set mode = p_mode, changed_at = pg_catalog.clock_timestamp()
  where singleton;
  return p_mode;
end
$function$;

create or replace function backend_system.record_validation_observation_v1(
  p_observation_id uuid,
  p_entitlement_id uuid,
  p_run_id text,
  p_release_sha256 text,
  p_participant_information_sha256 text,
  p_subject_binding_sha256 text,
  p_task_code text,
  p_state_code text,
  p_stage_code text,
  p_reason_code text,
  p_elapsed_milliseconds integer,
  p_intervention_type text,
  p_intervention_count integer,
  p_intervention_milliseconds integer,
  p_difference_classification text,
  p_rerun_result text,
  p_package_outcome text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_authority record;
  v_existing backend_system.validation_observations%rowtype;
  v_now timestamptz := pg_catalog.clock_timestamp();
begin
  if not exists (
    select 1 from backend_system.validation_observation_control
    where singleton and mode = 'invited-pilot'
  ) then
    raise exception 'validation_observation_mode_off';
  end if;
  if p_observation_id is null or p_entitlement_id is null then
    raise exception 'validation_observation_invalid_identifier';
  end if;
  if p_task_code is null or p_task_code <> all (array[
    'eligibility_precheck', 'eligibility_definitive', 'company_year_admission',
    'opening_reconstruction', 'bank_connection', 'bank_import', 'bookkeeping',
    'year_close', 'shareholder_register_filing', 'company_tax_filing',
    'annual_accounts_filing', 'archive_export'
  ]) then
    raise exception 'validation_observation_invalid_task';
  end if;
  if p_state_code is null or p_state_code <> all (array['started', 'completed', 'failed', 'blocked'])
    or p_stage_code is null or p_stage_code <> all (array[
      'eligibility', 'onboarding', 'reconstruction', 'banking', 'bookkeeping',
      'year_close', 'shareholder_register', 'company_tax', 'annual_accounts', 'archive'
    ])
    or p_reason_code is null or p_reason_code <> all (array[
      'none', 'unsupported_boundary', 'missing_evidence', 'authorization_required',
      'provider_unavailable', 'technical_failure', 'difference_detected', 'participant_withdrew'
    ])
  then
    raise exception 'validation_observation_invalid_state';
  end if;
  if p_elapsed_milliseconds is null or p_elapsed_milliseconds < 0
    or p_elapsed_milliseconds > 86400000
    or p_intervention_type is null or p_intervention_type <> all (array[
      'none', 'navigation_help', 'evidence_help', 'technical_support'
    ])
    or p_intervention_count is null or p_intervention_count < 0 or p_intervention_count > 100
    or p_intervention_milliseconds is null or p_intervention_milliseconds < 0
    or p_intervention_milliseconds > 86400000
    or p_difference_classification is null or p_difference_classification <> all (array[
      'none', 'talli_defect', 'source_defect', 'presentation_only', 'unresolved_judgment'
    ])
    or p_rerun_result is null or p_rerun_result <> all (array[
      'not_required', 'pending', 'passed', 'failed'
    ])
    or p_package_outcome is null or p_package_outcome <> all (array[
      'not_applicable', 'pending', 'accepted', 'blocked', 'failed'
    ])
  then
    raise exception 'validation_observation_invalid_metrics';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(p_entitlement_id::text, 196)
  );
  select
    entitlement.case_code,
    entitlement.run_id,
    entitlement.subject_binding_sha256,
    entitlement.starts_at as entitlement_starts_at,
    entitlement.expires_at as entitlement_expires_at,
    entitlement.revoked_at,
    entitlement.withdrawn_at,
    run.release_sha256,
    run.participant_information_sha256,
    run.starts_at as run_starts_at,
    run.expires_at as run_expires_at,
    run.status as run_status,
    run.retention_days
  into strict v_authority
  from backend_system.validation_pilot_entitlements entitlement
  join backend_system.validation_runs run on run.run_id = entitlement.run_id
  where entitlement.entitlement_id = p_entitlement_id
  for update of entitlement;

  if v_authority.run_id <> p_run_id
    or v_authority.release_sha256 <> p_release_sha256
    or v_authority.participant_information_sha256 <> p_participant_information_sha256
  then
    raise exception 'validation_observation_authority_mismatch';
  end if;
  if v_authority.subject_binding_sha256 <> p_subject_binding_sha256 then
    raise exception 'validation_observation_subject_mismatch';
  end if;
  if v_authority.run_status <> 'approved'
    or v_now < v_authority.run_starts_at or v_now >= v_authority.run_expires_at
    or v_now < v_authority.entitlement_starts_at
    or v_now >= v_authority.entitlement_expires_at
    or v_authority.revoked_at is not null or v_authority.withdrawn_at is not null
  then
    raise exception 'validation_observation_entitlement_inactive';
  end if;

  insert into backend_system.validation_observations (
    observation_id, entitlement_id, run_id, case_code, task_code, state_code,
    stage_code, reason_code, elapsed_milliseconds, intervention_type,
    intervention_count, intervention_milliseconds, difference_classification,
    rerun_result, package_outcome, received_at, retained_until
  ) values (
    p_observation_id, p_entitlement_id, p_run_id, v_authority.case_code,
    p_task_code, p_state_code, p_stage_code, p_reason_code,
    p_elapsed_milliseconds, p_intervention_type, p_intervention_count,
    p_intervention_milliseconds, p_difference_classification, p_rerun_result,
    p_package_outcome, v_now,
    v_now + pg_catalog.make_interval(days => v_authority.retention_days)
  ) on conflict (observation_id) do nothing;
  if found then
    return true;
  end if;

  select * into strict v_existing
  from backend_system.validation_observations
  where observation_id = p_observation_id;
  if v_existing.entitlement_id = p_entitlement_id
    and v_existing.run_id = p_run_id
    and v_existing.task_code = p_task_code
    and v_existing.state_code = p_state_code
    and v_existing.stage_code = p_stage_code
    and v_existing.reason_code = p_reason_code
    and v_existing.elapsed_milliseconds = p_elapsed_milliseconds
    and v_existing.intervention_type = p_intervention_type
    and v_existing.intervention_count = p_intervention_count
    and v_existing.intervention_milliseconds = p_intervention_milliseconds
    and v_existing.difference_classification = p_difference_classification
    and v_existing.rerun_result = p_rerun_result
    and v_existing.package_outcome = p_package_outcome
  then
    return false;
  end if;
  raise exception 'validation_observation_event_id_conflict';
exception when no_data_found then
  raise exception 'validation_observation_authority_mismatch';
end
$function$;

create or replace function backend_system.withdraw_validation_entitlement_v1(
  p_entitlement_id uuid
)
returns bigint
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_deleted bigint;
begin
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(p_entitlement_id::text, 196)
  );
  update backend_system.validation_pilot_entitlements
  set withdrawn_at = pg_catalog.clock_timestamp()
  where entitlement_id = p_entitlement_id
    and revoked_at is null and withdrawn_at is null;
  if not found then
    raise exception 'validation_observation_entitlement_inactive';
  end if;
  delete from backend_system.validation_observations
  where entitlement_id = p_entitlement_id;
  get diagnostics v_deleted = row_count;
  return v_deleted;
end
$function$;

create or replace function backend_system.revoke_validation_entitlement_v1(
  p_entitlement_id uuid
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $function$
begin
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(p_entitlement_id::text, 196)
  );
  update backend_system.validation_pilot_entitlements
  set revoked_at = pg_catalog.clock_timestamp()
  where entitlement_id = p_entitlement_id
    and revoked_at is null and withdrawn_at is null;
  if not found then
    raise exception 'validation_observation_entitlement_inactive';
  end if;
  return true;
end
$function$;

create or replace function backend_system.report_validation_observations_v1(
  p_run_id text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid;
  v_now timestamptz := pg_catalog.clock_timestamp();
  v_result jsonb;
begin
  begin
    v_actor_id := nullif(
      pg_catalog.current_setting('talli.verified_actor_id', true), ''
    )::uuid;
  exception when others then
    raise exception 'validation_observation_reviewer_required';
  end;
  if v_actor_id is null or not exists (
    select 1 from backend_system.validation_reviewers
    where run_id = p_run_id and actor_id = v_actor_id
      and v_now >= starts_at and v_now < expires_at and revoked_at is null
  ) then
    raise exception 'validation_observation_reviewer_required';
  end if;
  select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
    'observation_id', observation_id,
    'run_id', run_id,
    'case_code', case_code,
    'task', task_code,
    'state', state_code,
    'stage', stage_code,
    'reason', reason_code,
    'elapsed_milliseconds', elapsed_milliseconds,
    'intervention_type', intervention_type,
    'intervention_count', intervention_count,
    'intervention_milliseconds', intervention_milliseconds,
    'difference_classification', difference_classification,
    'rerun_result', rerun_result,
    'package_outcome', package_outcome,
    'received_at', received_at
  ) order by case_code, received_at, observation_id), '[]'::jsonb)
  into v_result
  from backend_system.validation_observations
  where run_id = p_run_id and retained_until > v_now;
  return v_result;
end
$function$;

create or replace function backend_system.purge_expired_validation_observations_v1()
returns bigint
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_deleted bigint;
begin
  delete from backend_system.validation_observations
  where retained_until <= pg_catalog.clock_timestamp();
  get diagnostics v_deleted = row_count;
  return v_deleted;
end
$function$;

create or replace function backend_system.validation_observation_launch_status_v1()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $function$
  with status as (
    select
      control.mode,
      pg_catalog.count(entitlement.entitlement_id) filter (
        where run.status = 'approved'
          and pg_catalog.clock_timestamp() >= run.starts_at
          and pg_catalog.clock_timestamp() < run.expires_at
          and pg_catalog.clock_timestamp() >= entitlement.starts_at
          and pg_catalog.clock_timestamp() < entitlement.expires_at
          and entitlement.revoked_at is null and entitlement.withdrawn_at is null
      )::bigint as active_entitlements
    from backend_system.validation_observation_control control
    left join backend_system.validation_pilot_entitlements entitlement on true
    left join backend_system.validation_runs run on run.run_id = entitlement.run_id
    where control.singleton
    group by control.mode
  )
  select pg_catalog.jsonb_build_object(
    'mode', mode,
    'active_entitlements', active_entitlements,
    'ready_for_full_launch', mode = 'off' and active_entitlements = 0
  ) from status;
$function$;

reset role;

revoke all on table
  backend_system.validation_observation_control,
  backend_system.validation_runs,
  backend_system.validation_pilot_entitlements,
  backend_system.validation_reviewers,
  backend_system.validation_observations
from public, anon, authenticated, service_role,
  validation_observation_writer_executor,
  validation_observation_reviewer_executor,
  validation_observation_provisioner_executor,
  validation_observation_maintenance_executor,
  validation_observation_gate_executor,
  talli_validation_observation_backend;

revoke all on function
  backend_system.provision_validation_run_v1(text, text, text, text, timestamptz, timestamptz, integer, uuid),
  backend_system.provision_validation_entitlement_v1(uuid, text, text, text, timestamptz, timestamptz),
  backend_system.provision_validation_reviewer_v1(text, uuid, timestamptz, timestamptz),
  backend_system.set_validation_observation_mode_v1(text),
  backend_system.record_validation_observation_v1(uuid, uuid, text, text, text, text, text, text, text, text, integer, text, integer, integer, text, text, text),
  backend_system.withdraw_validation_entitlement_v1(uuid),
  backend_system.revoke_validation_entitlement_v1(uuid),
  backend_system.report_validation_observations_v1(text),
  backend_system.purge_expired_validation_observations_v1(),
  backend_system.validation_observation_launch_status_v1()
from public, anon, authenticated, service_role,
  validation_observation_writer_executor,
  validation_observation_reviewer_executor,
  validation_observation_provisioner_executor,
  validation_observation_maintenance_executor,
  validation_observation_gate_executor,
  talli_validation_observation_backend;

grant execute on function
  backend_system.record_validation_observation_v1(uuid, uuid, text, text, text, text, text, text, text, text, integer, text, integer, integer, text, text, text)
to validation_observation_writer_executor;
grant execute on function backend_system.report_validation_observations_v1(text)
to validation_observation_reviewer_executor;
grant execute on function backend_system.purge_expired_validation_observations_v1()
to validation_observation_maintenance_executor;
grant execute on function backend_system.validation_observation_launch_status_v1()
to validation_observation_gate_executor;
grant execute on function
  backend_system.provision_validation_run_v1(text, text, text, text, timestamptz, timestamptz, integer, uuid),
  backend_system.provision_validation_entitlement_v1(uuid, text, text, text, timestamptz, timestamptz),
  backend_system.provision_validation_reviewer_v1(text, uuid, timestamptz, timestamptz),
  backend_system.set_validation_observation_mode_v1(text),
  backend_system.withdraw_validation_entitlement_v1(uuid),
  backend_system.revoke_validation_entitlement_v1(uuid)
to validation_observation_provisioner_executor;

set local role ledger_store_owner;
revoke create on schema backend_system from validation_observation_store_owner;
reset role;

do $migration_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke ledger_store_owner, validation_observation_store_owner from %I',
    pg_catalog.current_setting('talli.validation_observation_migration_principal')
  );
end
$migration_authority_revoke$;

commit;
