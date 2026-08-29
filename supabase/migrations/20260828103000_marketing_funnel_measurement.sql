-- Provider-neutral, consent-gated marketing measurement owned by backend-system.
-- Raw rows contain bounded enums and an irreversible anonymous-session hash only.

begin;

create schema if not exists backend_system;

do $roles$
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'marketing_measurement_store_owner') then
    create role marketing_measurement_store_owner nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'marketing_measurement_ingest_executor') then
    create role marketing_measurement_ingest_executor nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'marketing_measurement_report_executor') then
    create role marketing_measurement_report_executor nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname = 'talli_marketing_measurement_backend') then
    create role talli_marketing_measurement_backend nologin noinherit nobypassrls;
  end if;
end
$roles$;

-- Hosted Supabase applies migrations as a non-superuser. Borrow only the
-- memberships needed to create objects under the private store owner and to
-- use the ledger-owned backend_system schema, then return them before commit.
select pg_catalog.set_config(
  'talli.marketing_measurement_migration_principal', current_user, true
);
do $marketing_measurement_migration_authority$
begin
  execute pg_catalog.format(
    'grant ledger_store_owner, marketing_measurement_store_owner to %I',
    current_user
  );
end
$marketing_measurement_migration_authority$;

alter role marketing_measurement_store_owner nologin noinherit nobypassrls;
alter role marketing_measurement_ingest_executor nologin noinherit nobypassrls;
alter role marketing_measurement_report_executor nologin noinherit nobypassrls;
alter role talli_marketing_measurement_backend nologin noinherit nobypassrls;

grant marketing_measurement_ingest_executor, marketing_measurement_report_executor
to talli_marketing_measurement_backend;

set local role ledger_store_owner;
grant usage, create on schema backend_system to marketing_measurement_store_owner;
reset role;
grant usage on schema backend_system
to marketing_measurement_ingest_executor, marketing_measurement_report_executor;
grant execute on function public.company_access_is_active_operator_v1()
to marketing_measurement_store_owner;

set local role marketing_measurement_store_owner;

create table backend_system.marketing_funnel_events (
  id bigint generated always as identity primary key,
  client_event_id uuid not null unique,
  anonymous_session_hash text not null,
  consent_version text not null,
  event_name text not null,
  reason_code text,
  surface text not null,
  campaign_source text not null,
  received_at timestamptz not null default pg_catalog.clock_timestamp(),
  retained_until timestamptz not null default (pg_catalog.clock_timestamp() + interval '90 days'),
  constraint marketing_funnel_events_session_hash_check
    check (anonymous_session_hash ~ '^[0-9a-f]{64}$'),
  constraint marketing_funnel_events_consent_check
    check (consent_version = 'marketing-analytics-v1'),
  constraint marketing_funnel_events_event_check
    check (event_name = any (array[
      'home_view', 'eligibility_start', 'provisional_supported',
      'provisional_clarify', 'provisional_blocked', 'definitive_eligible',
      'definitive_blocked', 'signup_start', 'terms_accept', 'checkout_start',
      'purchase_complete', 'purchase_failed', 'company_year_started',
      'bank_connected', 'year_ready', 'filing_accepted',
      'company_year_complete', 'support_contact', 'unsupported_exit',
      'refund_started', 'refund_completed'
    ])),
  constraint marketing_funnel_events_surface_check
    check (surface = any (array[
      'homepage', 'eligibility', 'signup', 'checkout', 'workspace',
      'banking', 'year_close', 'filing', 'support', 'refund'
    ])),
  constraint marketing_funnel_events_campaign_check
    check (campaign_source = any (array[
      'direct', 'organic', 'community', 'partner', 'approved_campaign', 'unknown'
    ])),
  constraint marketing_funnel_events_reason_check check (
    (event_name = 'provisional_clarify' and reason_code = any (array[
      'unknown_material_facts', 'missing_required_facts'
    ]))
    or (event_name = 'provisional_blocked' and reason_code = any (array[
      'unsupported_company', 'unsupported_activity'
    ]))
    or (event_name = 'definitive_blocked' and reason_code = any (array[
      'unknown_material_facts', 'unsupported_company', 'unsupported_activity',
      'missing_required_facts'
    ]))
    or (event_name = 'purchase_failed' and reason_code = any (array[
      'payment_declined', 'provider_unavailable', 'technical_failure'
    ]))
    or (event_name = 'filing_accepted' and reason_code = any (array[
      'rf1086', 'company_tax', 'annual_accounts'
    ]))
    or (event_name = 'support_contact' and reason_code = any (array[
      'eligibility_help', 'signup_help', 'checkout_help', 'banking_help',
      'year_close_help', 'filing_help', 'refund_help', 'other_help'
    ]))
    or (event_name = 'unsupported_exit' and reason_code = any (array[
      'unknown_material_facts', 'unsupported_company', 'unsupported_activity',
      'new_unsupported_condition'
    ]))
    or (event_name = any (array['refund_started', 'refund_completed']) and reason_code = any (array[
      'customer_changed_mind', 'talli_should_have_blocked',
      'talli_delivery_failure', 'new_unsupported_condition',
      'customer_uncured_evidence'
    ]))
    or (event_name <> all (array[
      'provisional_clarify', 'provisional_blocked', 'definitive_blocked',
      'purchase_failed', 'filing_accepted', 'support_contact',
      'unsupported_exit', 'refund_started', 'refund_completed'
    ]) and reason_code is null)
  ),
  constraint marketing_funnel_events_retention_check
    check (retained_until > received_at and retained_until <= received_at + interval '90 days')
);

alter table backend_system.marketing_funnel_events enable row level security;
alter table backend_system.marketing_funnel_events force row level security;

create policy marketing_funnel_events_store_owner_policy
on backend_system.marketing_funnel_events
for all
to marketing_measurement_store_owner
using (true)
with check (true);

create index marketing_funnel_events_received_event_idx
on backend_system.marketing_funnel_events (received_at, event_name);

create index marketing_funnel_events_retained_until_idx
on backend_system.marketing_funnel_events (retained_until);

create index marketing_funnel_events_session_received_event_idx
on backend_system.marketing_funnel_events (anonymous_session_hash, received_at, event_name);

create table backend_system.marketing_funnel_withdrawals (
  anonymous_session_hash text primary key,
  withdrawn_at timestamptz not null default pg_catalog.clock_timestamp(),
  withdrawn_until timestamptz not null,
  constraint marketing_funnel_withdrawals_session_hash_check
    check (anonymous_session_hash ~ '^[0-9a-f]{64}$'),
  constraint marketing_funnel_withdrawals_lifetime_check
    check (
      withdrawn_until > withdrawn_at
      and withdrawn_until <= withdrawn_at + interval '30 minutes'
    )
);

alter table backend_system.marketing_funnel_withdrawals enable row level security;
alter table backend_system.marketing_funnel_withdrawals force row level security;

create policy marketing_funnel_withdrawals_store_owner_policy
on backend_system.marketing_funnel_withdrawals
for all
to marketing_measurement_store_owner
using (true)
with check (true);

create index marketing_funnel_withdrawals_until_idx
on backend_system.marketing_funnel_withdrawals (withdrawn_until);

create or replace function backend_system.purge_expired_marketing_funnel_events_v1()
returns bigint
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_deleted_events bigint;
  v_deleted_withdrawals bigint;
begin
  delete from backend_system.marketing_funnel_events
  where retained_until <= pg_catalog.clock_timestamp();
  get diagnostics v_deleted_events = row_count;
  delete from backend_system.marketing_funnel_withdrawals
  where withdrawn_until <= pg_catalog.clock_timestamp();
  get diagnostics v_deleted_withdrawals = row_count;
  return v_deleted_events + v_deleted_withdrawals;
end
$function$;

create or replace function backend_system.record_marketing_funnel_event_v1(
  p_client_event_id uuid,
  p_anonymous_session_hash text,
  p_consent_version text,
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
  v_existing backend_system.marketing_funnel_events%rowtype;
  v_first_received_at timestamptz;
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
  perform backend_system.purge_expired_marketing_funnel_events_v1();
  if exists (
    select 1 from backend_system.marketing_funnel_withdrawals
    where anonymous_session_hash = p_anonymous_session_hash
      and withdrawn_until > v_now
  ) then
    raise exception 'marketing_measurement_consent_withdrawn';
  end if;
  if p_consent_version is distinct from 'marketing-analytics-v1' then
    raise exception 'marketing_measurement_consent_required';
  end if;
  if p_event_name is null or p_event_name <> all (array[
    'home_view', 'eligibility_start', 'provisional_supported',
    'provisional_clarify', 'provisional_blocked', 'definitive_eligible',
    'definitive_blocked', 'signup_start', 'terms_accept', 'checkout_start',
    'purchase_complete', 'purchase_failed', 'company_year_started',
    'bank_connected', 'year_ready', 'filing_accepted',
    'company_year_complete', 'support_contact', 'unsupported_exit',
    'refund_started', 'refund_completed'
  ]) then
    raise exception 'marketing_measurement_invalid_event';
  end if;
  if p_surface is null or p_surface <> all (array[
    'homepage', 'eligibility', 'signup', 'checkout', 'workspace',
    'banking', 'year_close', 'filing', 'support', 'refund'
  ]) then
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
      'unknown_material_facts', 'unsupported_company', 'unsupported_activity',
      'missing_required_facts'
    ]))
    or (p_event_name = 'purchase_failed' and p_reason_code = any (array[
      'payment_declined', 'provider_unavailable', 'technical_failure'
    ]))
    or (p_event_name = 'filing_accepted' and p_reason_code = any (array[
      'rf1086', 'company_tax', 'annual_accounts'
    ]))
    or (p_event_name = 'support_contact' and p_reason_code = any (array[
      'eligibility_help', 'signup_help', 'checkout_help', 'banking_help',
      'year_close_help', 'filing_help', 'refund_help', 'other_help'
    ]))
    or (p_event_name = 'unsupported_exit' and p_reason_code = any (array[
      'unknown_material_facts', 'unsupported_company', 'unsupported_activity',
      'new_unsupported_condition'
    ]))
    or (p_event_name = any (array['refund_started', 'refund_completed']) and p_reason_code = any (array[
      'customer_changed_mind', 'talli_should_have_blocked',
      'talli_delivery_failure', 'new_unsupported_condition',
      'customer_uncured_evidence'
    ]))
    or (p_event_name <> all (array[
      'provisional_clarify', 'provisional_blocked', 'definitive_blocked',
      'purchase_failed', 'filing_accepted', 'support_contact',
      'unsupported_exit', 'refund_started', 'refund_completed'
    ]) and p_reason_code is null)
  ) then
    raise exception 'marketing_measurement_invalid_reason';
  end if;

  select pg_catalog.min(received_at) into v_first_received_at
  from backend_system.marketing_funnel_events
  where anonymous_session_hash = p_anonymous_session_hash;
  if v_first_received_at is not null and v_now > v_first_received_at + interval '30 minutes' then
    raise exception 'marketing_measurement_session_expired';
  end if;

  insert into backend_system.marketing_funnel_events (
    client_event_id, anonymous_session_hash, consent_version, event_name,
    reason_code, surface, campaign_source, received_at, retained_until
  ) values (
    p_client_event_id, p_anonymous_session_hash, p_consent_version, p_event_name,
    p_reason_code, p_surface, p_campaign_source, v_now, v_now + interval '90 days'
  ) on conflict (client_event_id) do nothing;
  if found then
    return true;
  end if;

  select * into strict v_existing
  from backend_system.marketing_funnel_events
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
end
$function$;

create or replace function backend_system.withdraw_marketing_funnel_session_v1(
  p_anonymous_session_hash text
)
returns bigint
language plpgsql
security definer
set search_path = ''
as $function$
declare
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
  delete from backend_system.marketing_funnel_events
  where anonymous_session_hash = p_anonymous_session_hash;
  get diagnostics v_deleted = row_count;
  insert into backend_system.marketing_funnel_withdrawals (
    anonymous_session_hash, withdrawn_at, withdrawn_until
  ) values (
    p_anonymous_session_hash,
    v_now,
    v_now + interval '30 minutes'
  )
  on conflict (anonymous_session_hash) do update
  set withdrawn_at = excluded.withdrawn_at,
    withdrawn_until = excluded.withdrawn_until;
  return v_deleted;
end
$function$;

create or replace function backend_system.report_marketing_funnel_v1(
  p_window_days integer default 30
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $function$
declare
  v_actor_id uuid;
  v_counts jsonb;
  v_support_by_surface jsonb;
  v_repeated_signals jsonb;
  v_home_sessions bigint;
  v_eligibility_sessions bigint;
  v_home_purchase_sessions bigint;
  v_eligibility_purchase_sessions bigint;
  v_eligibility_unsupported_sessions bigint;
  v_home_purchase_median numeric;
  v_from timestamptz;
  v_to timestamptz := pg_catalog.clock_timestamp();
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

  perform backend_system.purge_expired_marketing_funnel_events_v1();
  v_from := v_to - pg_catalog.make_interval(days => p_window_days);

  with event_vocabulary(event_name) as (
    values
      ('home_view'), ('eligibility_start'), ('provisional_supported'),
      ('provisional_clarify'), ('provisional_blocked'), ('definitive_eligible'),
      ('definitive_blocked'), ('signup_start'), ('terms_accept'),
      ('checkout_start'), ('purchase_complete'), ('purchase_failed'),
      ('company_year_started'), ('bank_connected'), ('year_ready'),
      ('filing_accepted'), ('company_year_complete'), ('support_contact'),
      ('unsupported_exit'), ('refund_started'), ('refund_completed')
  ), counts as (
    select e.event_name, pg_catalog.count(m.id)::bigint as event_count
    from event_vocabulary e
    left join backend_system.marketing_funnel_events m
      on m.event_name = e.event_name
      and m.received_at >= v_from and m.received_at <= v_to
      and m.retained_until > v_to
    group by e.event_name
  )
  select pg_catalog.jsonb_object_agg(event_name, event_count order by event_name)
  into v_counts
  from counts;

  with session_flags as (
    select anonymous_session_hash,
      pg_catalog.bool_or(event_name = 'home_view') as home_viewed,
      pg_catalog.bool_or(event_name = 'eligibility_start') as eligibility_started,
      pg_catalog.bool_or(event_name = 'purchase_complete') as purchase_completed,
      pg_catalog.bool_or(event_name = 'unsupported_exit') as unsupported_exited
    from backend_system.marketing_funnel_events
    where received_at >= v_from and received_at <= v_to and retained_until > v_to
    group by anonymous_session_hash
  )
  select
    pg_catalog.count(*) filter (where home_viewed),
    pg_catalog.count(*) filter (where eligibility_started),
    pg_catalog.count(*) filter (where home_viewed and purchase_completed),
    pg_catalog.count(*) filter (where eligibility_started and purchase_completed),
    pg_catalog.count(*) filter (where eligibility_started and unsupported_exited)
  into
    v_home_sessions,
    v_eligibility_sessions,
    v_home_purchase_sessions,
    v_eligibility_purchase_sessions,
    v_eligibility_unsupported_sessions
  from session_flags;

  select coalesce(
    pg_catalog.jsonb_object_agg(surface, event_count order by surface), '{}'::jsonb
  ) into v_support_by_surface
  from (
    select surface, pg_catalog.count(*)::bigint as event_count
    from backend_system.marketing_funnel_events
    where event_name = 'support_contact'
      and received_at >= v_from and received_at <= v_to and retained_until > v_to
    group by surface
  ) support;

  select coalesce(
    pg_catalog.jsonb_agg(
      pg_catalog.jsonb_build_object(
        'event', event_name, 'surface', surface,
        'reason', reason_code, 'count', event_count
      ) order by event_name, surface, reason_code
    ), '[]'::jsonb
  ) into v_repeated_signals
  from (
    select event_name, surface, reason_code, pg_catalog.count(*)::bigint as event_count
    from backend_system.marketing_funnel_events
    where received_at >= v_from and received_at <= v_to
      and retained_until > v_to and reason_code is not null
    group by event_name, surface, reason_code
    having pg_catalog.count(*) >= 5
  ) signals;

  with session_stages as (
    select anonymous_session_hash,
      pg_catalog.min(received_at) filter (where event_name = 'home_view') as started_at,
      pg_catalog.min(received_at) filter (where event_name = 'purchase_complete') as completed_at
    from backend_system.marketing_funnel_events
    where received_at >= v_from and received_at <= v_to and retained_until > v_to
    group by anonymous_session_hash
  )
  select pg_catalog.round(
    pg_catalog.percentile_cont(0.5) within group (
      order by extract(epoch from completed_at - started_at)
    )::numeric
  ) into v_home_purchase_median
  from session_stages
  where completed_at >= started_at;

  return pg_catalog.jsonb_build_object(
    'window_start', v_from,
    'window_end', v_to,
    'counts', v_counts,
    'rates', pg_catalog.jsonb_build_object(
      'home_to_purchase', case when v_home_sessions = 0 then null else v_home_purchase_sessions::numeric / v_home_sessions end,
      'eligibility_to_purchase', case when v_eligibility_sessions = 0 then null else v_eligibility_purchase_sessions::numeric / v_eligibility_sessions end,
      'company_year_completion', null,
      'refund', null,
      'unsupported', case when v_eligibility_sessions = 0 then null else v_eligibility_unsupported_sessions::numeric / v_eligibility_sessions end,
      'acquisition_cost_minor', null
    ),
    'median_seconds', pg_catalog.jsonb_build_object(
      'home_to_purchase', v_home_purchase_median,
      'company_year_completion', null
    ),
    'support_by_surface', v_support_by_surface,
    'repeated_signals', v_repeated_signals
  );
end
$function$;

reset role;

revoke all on table
  backend_system.marketing_funnel_events,
  backend_system.marketing_funnel_withdrawals
from public, anon, authenticated, service_role,
  marketing_measurement_ingest_executor, marketing_measurement_report_executor,
  talli_marketing_measurement_backend;
revoke all on sequence backend_system.marketing_funnel_events_id_seq
from public, anon, authenticated, service_role,
  marketing_measurement_ingest_executor, marketing_measurement_report_executor,
  talli_marketing_measurement_backend;

revoke all on function
  backend_system.record_marketing_funnel_event_v1(uuid, text, text, text, text, text, text),
  backend_system.withdraw_marketing_funnel_session_v1(text),
  backend_system.purge_expired_marketing_funnel_events_v1(),
  backend_system.report_marketing_funnel_v1(integer)
from public, anon, authenticated, service_role,
  marketing_measurement_ingest_executor, marketing_measurement_report_executor,
  talli_marketing_measurement_backend;

grant execute on function
  backend_system.record_marketing_funnel_event_v1(uuid, text, text, text, text, text, text),
  backend_system.withdraw_marketing_funnel_session_v1(text),
  backend_system.purge_expired_marketing_funnel_events_v1()
to marketing_measurement_ingest_executor;
grant execute on function backend_system.report_marketing_funnel_v1(integer)
to marketing_measurement_report_executor;

set local role ledger_store_owner;
revoke create on schema backend_system from marketing_measurement_store_owner;
reset role;

do $marketing_measurement_migration_authority_revoke$
begin
  execute pg_catalog.format(
    'revoke ledger_store_owner, marketing_measurement_store_owner from %I',
    pg_catalog.current_setting('talli.marketing_measurement_migration_principal')
  );
end
$marketing_measurement_migration_authority_revoke$;

commit;
