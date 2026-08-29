-- Durable consent proof and public-session-only aggregate reporting.
-- No release is approved or activated by this migration.

begin;

do $roles$
begin
  if not exists (
    select 1 from pg_catalog.pg_roles
    where rolname = 'marketing_measurement_provisioner_executor'
  ) then
    create role marketing_measurement_provisioner_executor
      nologin noinherit nobypassrls;
  end if;
end
$roles$;

select pg_catalog.set_config(
  'talli.marketing_consent_migration_principal', current_user, true
);
do $migration_authority$
begin
  execute pg_catalog.format(
    'grant ledger_store_owner, marketing_measurement_store_owner to %I',
    current_user
  );
end
$migration_authority$;

alter role marketing_measurement_provisioner_executor
  nologin noinherit nobypassrls;
grant usage on schema backend_system
to marketing_measurement_provisioner_executor;

set local role ledger_store_owner;
grant create on schema backend_system to marketing_measurement_store_owner;
reset role;

set local role marketing_measurement_store_owner;

create table backend_system.marketing_measurement_releases (
  consent_version text primary key
    check (consent_version = 'marketing-analytics-v1'),
  first_layer_notice_version text not null
    check (first_layer_notice_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
  first_layer_notice_sha256 text not null
    check (first_layer_notice_sha256 ~ '^[0-9a-f]{64}$'),
  privacy_notice_version text not null
    check (privacy_notice_version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
  privacy_notice_sha256 text not null
    check (privacy_notice_sha256 ~ '^[0-9a-f]{64}$'),
  release_sha256 text not null check (release_sha256 ~ '^[0-9a-f]{64}$'),
  starts_at timestamptz not null,
  expires_at timestamptz not null,
  raw_retention_days smallint not null check (raw_retention_days between 1 and 90),
  proof_retention_days smallint not null check (proof_retention_days between 1 and 3650),
  approved_by uuid not null,
  approved_at timestamptz not null default pg_catalog.clock_timestamp(),
  status text not null default 'approved'
    check (status = any (array['approved', 'retired'])),
  check (expires_at > starts_at)
);

create table backend_system.marketing_consent_actions (
  id bigint generated always as identity primary key,
  anonymous_session_hash text not null
    check (anonymous_session_hash ~ '^[0-9a-f]{64}$'),
  action text not null check (action = any (array['grant', 'withdraw'])),
  consent_version text not null,
  first_layer_notice_version text not null,
  first_layer_notice_sha256 text not null
    check (first_layer_notice_sha256 ~ '^[0-9a-f]{64}$'),
  privacy_notice_version text not null,
  privacy_notice_sha256 text not null
    check (privacy_notice_sha256 ~ '^[0-9a-f]{64}$'),
  release_sha256 text not null check (release_sha256 ~ '^[0-9a-f]{64}$'),
  received_at timestamptz not null default pg_catalog.clock_timestamp(),
  expires_at timestamptz not null,
  retained_until timestamptz not null,
  unique (anonymous_session_hash, action),
  check (expires_at >= received_at),
  check (retained_until > received_at)
);

alter table backend_system.marketing_measurement_releases enable row level security;
alter table backend_system.marketing_measurement_releases force row level security;
alter table backend_system.marketing_consent_actions enable row level security;
alter table backend_system.marketing_consent_actions force row level security;
create policy marketing_measurement_releases_owner_policy
on backend_system.marketing_measurement_releases for all
to marketing_measurement_store_owner using (true) with check (true);
create policy marketing_consent_actions_owner_policy
on backend_system.marketing_consent_actions for all
to marketing_measurement_store_owner using (true) with check (true);
create index marketing_consent_actions_retained_idx
on backend_system.marketing_consent_actions (retained_until);

create or replace function backend_system.provision_marketing_measurement_release_v1(
  p_consent_version text,
  p_first_layer_notice_version text,
  p_first_layer_notice_sha256 text,
  p_privacy_notice_version text,
  p_privacy_notice_sha256 text,
  p_release_sha256 text,
  p_starts_at timestamptz,
  p_expires_at timestamptz,
  p_raw_retention_days integer,
  p_proof_retention_days integer,
  p_approved_by uuid
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $function$
begin
  if p_consent_version is distinct from 'marketing-analytics-v1'
    or p_first_layer_notice_version is null
    or p_first_layer_notice_version !~ '^[a-z0-9][a-z0-9._-]{0,63}$'
    or p_first_layer_notice_sha256 is null
    or p_first_layer_notice_sha256 !~ '^[0-9a-f]{64}$'
    or p_privacy_notice_version is null
    or p_privacy_notice_version !~ '^[a-z0-9][a-z0-9._-]{0,63}$'
    or p_privacy_notice_sha256 is null
    or p_privacy_notice_sha256 !~ '^[0-9a-f]{64}$'
    or p_release_sha256 is null or p_release_sha256 !~ '^[0-9a-f]{64}$'
    or p_starts_at is null or p_expires_at is null or p_expires_at <= p_starts_at
    or p_raw_retention_days is null or p_raw_retention_days < 1
    or p_raw_retention_days > 90
    or p_proof_retention_days is null or p_proof_retention_days < 1
    or p_proof_retention_days > 3650
    or p_approved_by is null
  then
    raise exception 'marketing_measurement_invalid_release';
  end if;
  insert into backend_system.marketing_measurement_releases (
    consent_version, first_layer_notice_version,
    first_layer_notice_sha256, privacy_notice_version,
    privacy_notice_sha256, release_sha256, starts_at, expires_at,
    raw_retention_days, proof_retention_days, approved_by
  ) values (
    p_consent_version, p_first_layer_notice_version,
    p_first_layer_notice_sha256, p_privacy_notice_version,
    p_privacy_notice_sha256, p_release_sha256, p_starts_at, p_expires_at,
    p_raw_retention_days, p_proof_retention_days, p_approved_by
  );
  return true;
end
$function$;

create or replace function backend_system.record_marketing_funnel_event_v2(
  p_client_event_id uuid,
  p_anonymous_session_hash text,
  p_consent_version text,
  p_first_layer_notice_version text,
  p_first_layer_notice_sha256 text,
  p_privacy_notice_version text,
  p_privacy_notice_sha256 text,
  p_release_sha256 text,
  p_event_name text,
  p_reason_code text,
  p_surface text,
  p_campaign_source text
)
returns boolean
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_release backend_system.marketing_measurement_releases%rowtype;
  v_grant backend_system.marketing_consent_actions%rowtype;
  v_existing backend_system.marketing_funnel_events%rowtype;
  v_now timestamptz := pg_catalog.clock_timestamp();
begin
  if p_anonymous_session_hash is null
    or p_anonymous_session_hash !~ '^[0-9a-f]{64}$'
  then
    raise exception 'marketing_measurement_invalid_session';
  end if;
  if p_event_name is null or p_event_name <> all (array[
    'home_view', 'eligibility_start', 'provisional_supported',
    'provisional_clarify', 'provisional_blocked', 'definitive_eligible',
    'definitive_blocked', 'signup_start', 'unsupported_exit'
  ]) then
    raise exception 'marketing_measurement_invalid_event';
  end if;
  if p_surface is null or p_surface <> all (array['homepage', 'eligibility', 'signup'])
  then
    raise exception 'marketing_measurement_invalid_surface';
  end if;
  if p_campaign_source is null or p_campaign_source <> all (array[
    'direct', 'organic', 'community', 'partner', 'approved_campaign', 'unknown'
  ]) then
    raise exception 'marketing_measurement_invalid_campaign';
  end if;
  if not (
    (p_event_name = 'provisional_clarify' and p_reason_code = any (array[
      'unknown_material_facts', 'missing_required_facts'
    ]))
    or (p_event_name = 'provisional_blocked' and p_reason_code = any (array[
      'unsupported_company', 'unsupported_activity'
    ]))
    or (p_event_name = 'definitive_blocked' and p_reason_code = any (array[
      'unknown_material_facts', 'unsupported_company',
      'unsupported_activity', 'missing_required_facts'
    ]))
    or (p_event_name = 'unsupported_exit' and p_reason_code = any (array[
      'unknown_material_facts', 'unsupported_company',
      'unsupported_activity', 'new_unsupported_condition'
    ]))
    or (p_event_name <> all (array[
      'provisional_clarify', 'provisional_blocked',
      'definitive_blocked', 'unsupported_exit'
    ]) and p_reason_code is null)
  ) then
    raise exception 'marketing_measurement_invalid_reason';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(p_anonymous_session_hash, 196)
  );
  select * into strict v_release
  from backend_system.marketing_measurement_releases
  where consent_version = p_consent_version
    and first_layer_notice_version = p_first_layer_notice_version
    and first_layer_notice_sha256 = p_first_layer_notice_sha256
    and privacy_notice_version = p_privacy_notice_version
    and privacy_notice_sha256 = p_privacy_notice_sha256
    and release_sha256 = p_release_sha256
    and status = 'approved'
    and v_now >= starts_at and v_now < expires_at;

  if exists (
    select 1 from backend_system.marketing_consent_actions
    where anonymous_session_hash = p_anonymous_session_hash
      and action = 'withdraw'
  ) then
    raise exception 'marketing_measurement_consent_withdrawn';
  end if;

  select * into v_grant
  from backend_system.marketing_consent_actions
  where anonymous_session_hash = p_anonymous_session_hash and action = 'grant';
  if not found then
    insert into backend_system.marketing_consent_actions (
      anonymous_session_hash, action, consent_version,
      first_layer_notice_version, first_layer_notice_sha256,
      privacy_notice_version, privacy_notice_sha256, release_sha256,
      received_at, expires_at, retained_until
    ) values (
      p_anonymous_session_hash, 'grant', p_consent_version,
      p_first_layer_notice_version, p_first_layer_notice_sha256,
      p_privacy_notice_version, p_privacy_notice_sha256, p_release_sha256,
      v_now, v_now + interval '30 minutes',
      v_now + pg_catalog.make_interval(days => v_release.proof_retention_days)
    ) returning * into v_grant;
  end if;
  if v_grant.consent_version <> p_consent_version
    or v_grant.first_layer_notice_version <> p_first_layer_notice_version
    or v_grant.first_layer_notice_sha256 <> p_first_layer_notice_sha256
    or v_grant.privacy_notice_version <> p_privacy_notice_version
    or v_grant.privacy_notice_sha256 <> p_privacy_notice_sha256
    or v_grant.release_sha256 <> p_release_sha256
  then
    raise exception 'marketing_measurement_consent_binding_mismatch';
  end if;
  if v_now >= v_grant.expires_at then
    raise exception 'marketing_measurement_session_expired';
  end if;

  insert into backend_system.marketing_funnel_events (
    client_event_id, anonymous_session_hash, consent_version, event_name,
    reason_code, surface, campaign_source, received_at, retained_until
  ) values (
    p_client_event_id, p_anonymous_session_hash, p_consent_version, p_event_name,
    p_reason_code, p_surface, p_campaign_source, v_now,
    v_now + pg_catalog.make_interval(days => v_release.raw_retention_days)
  ) on conflict (client_event_id) do nothing;
  if found then return true; end if;

  select * into strict v_existing from backend_system.marketing_funnel_events
  where client_event_id = p_client_event_id;
  if v_existing.anonymous_session_hash = p_anonymous_session_hash
    and v_existing.consent_version = p_consent_version
    and v_existing.event_name = p_event_name
    and v_existing.reason_code is not distinct from p_reason_code
    and v_existing.surface = p_surface
    and v_existing.campaign_source = p_campaign_source
  then
    return false;
  end if;
  raise exception 'marketing_measurement_event_id_conflict';
exception when no_data_found then
  raise exception 'marketing_measurement_release_required';
end
$function$;

create or replace function backend_system.withdraw_marketing_funnel_session_v2(
  p_anonymous_session_hash text
)
returns bigint
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_grant backend_system.marketing_consent_actions%rowtype;
  v_deleted bigint;
  v_now timestamptz := pg_catalog.clock_timestamp();
begin
  if p_anonymous_session_hash is null
    or p_anonymous_session_hash !~ '^[0-9a-f]{64}$'
  then
    raise exception 'marketing_measurement_invalid_session';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended(p_anonymous_session_hash, 196)
  );
  select * into strict v_grant
  from backend_system.marketing_consent_actions
  where anonymous_session_hash = p_anonymous_session_hash and action = 'grant';
  delete from backend_system.marketing_funnel_events
  where anonymous_session_hash = p_anonymous_session_hash;
  get diagnostics v_deleted = row_count;
  insert into backend_system.marketing_consent_actions (
    anonymous_session_hash, action, consent_version,
    first_layer_notice_version, first_layer_notice_sha256,
    privacy_notice_version, privacy_notice_sha256, release_sha256,
    received_at, expires_at, retained_until
  ) values (
    p_anonymous_session_hash, 'withdraw', v_grant.consent_version,
    v_grant.first_layer_notice_version, v_grant.first_layer_notice_sha256,
    v_grant.privacy_notice_version, v_grant.privacy_notice_sha256,
    v_grant.release_sha256, v_now, v_now, v_grant.retained_until
  ) on conflict (anonymous_session_hash, action) do nothing;
  return v_deleted;
exception when no_data_found then
  raise exception 'marketing_measurement_consent_required';
end
$function$;

create or replace function backend_system.report_marketing_funnel_v2(
  p_window_days integer default 30
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid;
  v_from timestamptz;
  v_to timestamptz := pg_catalog.clock_timestamp();
  v_counts jsonb;
  v_signals jsonb;
  v_eligibility_sessions bigint;
  v_unsupported_sessions bigint;
begin
  if p_window_days is null or p_window_days < 1 or p_window_days > 90 then
    raise exception 'marketing_measurement_invalid_window';
  end if;
  begin
    v_actor_id := nullif(
      pg_catalog.current_setting('talli.verified_actor_id', true), ''
    )::uuid;
  exception when others then
    raise exception 'marketing_measurement_operator_required';
  end;
  if v_actor_id is null
    or not (select public.company_access_is_active_operator_v1())
  then
    raise exception 'marketing_measurement_operator_required';
  end if;
  v_from := v_to - pg_catalog.make_interval(days => p_window_days);

  with vocabulary(event_name) as (values
    ('home_view'), ('eligibility_start'), ('provisional_supported'),
    ('provisional_clarify'), ('provisional_blocked'), ('definitive_eligible'),
    ('definitive_blocked'), ('signup_start'), ('unsupported_exit')
  ), counts as (
    select vocabulary.event_name, pg_catalog.count(event.id)::bigint as event_count
    from vocabulary left join backend_system.marketing_funnel_events event
      on event.event_name = vocabulary.event_name
      and event.received_at >= v_from and event.received_at <= v_to
      and event.retained_until > v_to
    group by vocabulary.event_name
  )
  select pg_catalog.jsonb_object_agg(event_name, event_count order by event_name)
  into v_counts from counts;

  with sessions as (
    select anonymous_session_hash,
      pg_catalog.bool_or(event_name = 'eligibility_start') as eligibility,
      pg_catalog.bool_or(event_name = 'unsupported_exit') as unsupported
    from backend_system.marketing_funnel_events
    where received_at >= v_from and received_at <= v_to and retained_until > v_to
    group by anonymous_session_hash
  )
  select pg_catalog.count(*) filter (where eligibility),
    pg_catalog.count(*) filter (where eligibility and unsupported)
  into v_eligibility_sessions, v_unsupported_sessions from sessions;

  select coalesce(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
    'event', event_name, 'surface', surface,
    'reason', reason_code, 'count', session_count
  ) order by event_name, surface, reason_code), '[]'::jsonb)
  into v_signals from (
    select event_name, surface, reason_code,
      pg_catalog.count(distinct anonymous_session_hash)::bigint as session_count
    from backend_system.marketing_funnel_events
    where received_at >= v_from and received_at <= v_to
      and retained_until > v_to and reason_code is not null
      and event_name = any (array[
        'provisional_clarify', 'provisional_blocked',
        'definitive_blocked', 'unsupported_exit'
      ])
    group by event_name, surface, reason_code
    having pg_catalog.count(distinct anonymous_session_hash) >= 5
  ) signals;

  return pg_catalog.jsonb_build_object(
    'window_start', v_from,
    'window_end', v_to,
    'counts', v_counts,
    'rates', pg_catalog.jsonb_build_object(
      'home_to_purchase', null,
      'eligibility_to_purchase', null,
      'company_year_completion', null,
      'refund', null,
      'unsupported', case when v_eligibility_sessions = 0 then null
        else v_unsupported_sessions::numeric / v_eligibility_sessions end,
      'acquisition_cost_minor', null
    ),
    'median_seconds', pg_catalog.jsonb_build_object(
      'home_to_purchase', null, 'company_year_completion', null
    ),
    'support_by_surface', '{}'::jsonb,
    'repeated_signals', v_signals
  );
end
$function$;

create or replace function backend_system.purge_marketing_measurement_v2()
returns bigint
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_events bigint;
  v_actions bigint;
begin
  delete from backend_system.marketing_funnel_events
  where retained_until <= pg_catalog.clock_timestamp();
  get diagnostics v_events = row_count;
  delete from backend_system.marketing_consent_actions
  where retained_until <= pg_catalog.clock_timestamp();
  get diagnostics v_actions = row_count;
  delete from backend_system.marketing_funnel_withdrawals
  where withdrawn_until <= pg_catalog.clock_timestamp();
  return v_events + v_actions;
end
$function$;

reset role;

revoke all on table
  backend_system.marketing_measurement_releases,
  backend_system.marketing_consent_actions
from public, anon, authenticated, service_role,
  marketing_measurement_ingest_executor,
  marketing_measurement_report_executor,
  marketing_measurement_provisioner_executor,
  talli_marketing_measurement_backend;
revoke all on sequence backend_system.marketing_consent_actions_id_seq
from public, anon, authenticated, service_role,
  marketing_measurement_ingest_executor,
  marketing_measurement_report_executor,
  marketing_measurement_provisioner_executor,
  talli_marketing_measurement_backend;

revoke execute on function
  backend_system.record_marketing_funnel_event_v1(uuid, text, text, text, text, text, text),
  backend_system.withdraw_marketing_funnel_session_v1(text),
  backend_system.purge_expired_marketing_funnel_events_v1()
from marketing_measurement_ingest_executor;
revoke execute on function backend_system.report_marketing_funnel_v1(integer)
from marketing_measurement_report_executor;

revoke all on function
  backend_system.provision_marketing_measurement_release_v1(text, text, text, text, text, text, timestamptz, timestamptz, integer, integer, uuid),
  backend_system.record_marketing_funnel_event_v2(uuid, text, text, text, text, text, text, text, text, text, text, text),
  backend_system.withdraw_marketing_funnel_session_v2(text),
  backend_system.report_marketing_funnel_v2(integer),
  backend_system.purge_marketing_measurement_v2()
from public, anon, authenticated, service_role,
  marketing_measurement_ingest_executor,
  marketing_measurement_report_executor,
  marketing_measurement_provisioner_executor,
  talli_marketing_measurement_backend;

grant execute on function
  backend_system.record_marketing_funnel_event_v2(uuid, text, text, text, text, text, text, text, text, text, text, text),
  backend_system.withdraw_marketing_funnel_session_v2(text),
  backend_system.purge_marketing_measurement_v2()
to marketing_measurement_ingest_executor;
grant execute on function backend_system.report_marketing_funnel_v2(integer)
to marketing_measurement_report_executor;
grant execute on function
  backend_system.provision_marketing_measurement_release_v1(text, text, text, text, text, text, timestamptz, timestamptz, integer, integer, uuid)
to marketing_measurement_provisioner_executor;

set local role ledger_store_owner;
revoke create on schema backend_system from marketing_measurement_store_owner;
reset role;

do $migration_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke ledger_store_owner, marketing_measurement_store_owner from %I',
    pg_catalog.current_setting('talli.marketing_consent_migration_principal')
  );
end
$migration_authority_revoke$;

commit;
