-- Controlled production beta: additive, deny-by-default production aggregate.

create table if not exists public.production_pilot_entitlements (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  obligation text not null check (obligation = 'aksjonaerregisteroppgaven'),
  case_profile text not null check (case_profile = 'rf1086_no_activity_v1'),
  status text not null default 'pending' check (status in ('pending', 'active', 'suspended', 'completed', 'revoked')),
  billing_exempt boolean not null default true,
  system_user_external_reference text not null check (length(trim(system_user_external_reference)) between 1 and 200),
  starts_at timestamptz not null,
  expires_at timestamptz not null,
  evidence_reference text not null check (length(trim(evidence_reference)) between 1 and 1000),
  approved_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (starts_at < expires_at)
);

create unique index if not exists production_pilot_entitlements_active_exact_key
on public.production_pilot_entitlements (company_id, user_id, income_year, obligation, case_profile)
where status = 'active';

create table if not exists public.filing_approval_snapshots (
  id uuid primary key default gen_random_uuid(),
  entitlement_id uuid not null references public.production_pilot_entitlements(id) on delete restrict,
  preview_id uuid not null references public.filing_previews(id) on delete restrict,
  company_id uuid not null references public.companies(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  obligation text not null check (obligation = 'aksjonaerregisteroppgaven'),
  case_profile text not null check (case_profile = 'rf1086_no_activity_v1'),
  adapter_version text not null check (length(trim(adapter_version)) between 1 and 100),
  payload_hash text not null check (payload_hash ~ '^[0-9a-f]{64}$'),
  manifest_hash text not null check (manifest_hash ~ '^[0-9a-f]{64}$'),
  manifest jsonb not null check (jsonb_typeof(manifest) = 'object'),
  approved_by uuid not null references auth.users(id) on delete restrict,
  approved_at timestamptz not null default now(),
  invalidated_at timestamptz,
  invalidation_reason text,
  check (approved_by = user_id),
  check ((invalidated_at is null) = (invalidation_reason is null))
);

create unique index if not exists filing_approval_snapshots_current_preview_key
on public.filing_approval_snapshots (preview_id)
where invalidated_at is null;

create table if not exists public.production_filing_submissions (
  id uuid primary key default gen_random_uuid(),
  approval_id uuid not null unique references public.filing_approval_snapshots(id) on delete restrict,
  entitlement_id uuid not null references public.production_pilot_entitlements(id) on delete restrict,
  company_id uuid not null references public.companies(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete restrict,
  income_year integer not null check (income_year between 2000 and 2100),
  obligation text not null check (obligation = 'aksjonaerregisteroppgaven'),
  case_profile text not null check (case_profile = 'rf1086_no_activity_v1'),
  payload_hash text not null check (payload_hash ~ '^[0-9a-f]{64}$'),
  adapter_version text not null check (length(trim(adapter_version)) between 1 and 100),
  environment text not null check (environment = 'production'),
  status text not null check (status in ('approved', 'sending', 'received', 'processing', 'accepted', 'rejected', 'action_required', 'unknown')),
  authority_references jsonb not null default '{}'::jsonb check (jsonb_typeof(authority_references) = 'object'),
  failure_class text,
  supersedes_submission_id uuid references public.production_filing_submissions(id) on delete restrict,
  submitted_by uuid not null references auth.users(id) on delete restrict,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (submitted_by = user_id)
);

create table if not exists public.production_filing_events (
  id uuid primary key default gen_random_uuid(),
  submission_id uuid not null references public.production_filing_submissions(id) on delete cascade,
  operation_name text not null check (length(trim(operation_name)) between 1 and 120),
  operation_state text not null check (operation_state in ('prepared', 'succeeded', 'failed', 'unknown')),
  attempt integer not null default 1 check (attempt between 1 and 20),
  body_hash text check (body_hash is null or body_hash ~ '^[0-9a-f]{64}$'),
  idempotency_key uuid,
  authority_reference text check (authority_reference is null or length(authority_reference) <= 500),
  failure_class text check (failure_class is null or failure_class in ('retryable', 'blocked', 'unknown')),
  resulting_status text not null check (resulting_status in ('approved', 'sending', 'received', 'processing', 'accepted', 'rejected', 'action_required', 'unknown')),
  created_at timestamptz not null default now(),
  unique (submission_id, operation_name, attempt, operation_state),
  check (operation_state <> 'prepared' or authority_reference is null),
  check (operation_state not in ('failed', 'unknown') or failure_class is not null)
);

create index if not exists production_pilot_entitlements_company_idx
on public.production_pilot_entitlements (company_id, income_year, obligation, updated_at desc);
create index if not exists filing_approval_snapshots_company_idx
on public.filing_approval_snapshots (company_id, income_year, obligation, approved_at desc);
create index if not exists production_filing_submissions_company_idx
on public.production_filing_submissions (company_id, income_year, obligation, updated_at desc);
create index if not exists production_filing_events_submission_idx
on public.production_filing_events (submission_id, created_at, id);

alter table public.production_pilot_entitlements enable row level security;
alter table public.filing_approval_snapshots enable row level security;
alter table public.production_filing_submissions enable row level security;
alter table public.production_filing_events enable row level security;

revoke all on table public.production_pilot_entitlements from public, anon, authenticated;
revoke all on table public.filing_approval_snapshots from public, anon, authenticated;
revoke all on table public.production_filing_submissions from public, anon, authenticated;
revoke all on table public.production_filing_events from public, anon, authenticated;

grant select on table public.production_pilot_entitlements to authenticated;
grant select on table public.filing_approval_snapshots to authenticated;
grant select on table public.production_filing_submissions to authenticated;
grant select on table public.production_filing_events to authenticated;
grant select, insert, update on table public.production_pilot_entitlements to service_role;
grant select, insert, update on table public.filing_approval_snapshots to service_role;
grant select, insert, update on table public.production_filing_submissions to service_role;
grant select, insert on table public.production_filing_events to service_role;

drop policy if exists "company members read production pilot entitlements" on public.production_pilot_entitlements;
create policy "company members read production pilot entitlements"
on public.production_pilot_entitlements for select to authenticated
using (exists (
  select 1 from public.company_memberships m
  where m.company_id = production_pilot_entitlements.company_id
    and m.user_id = (select auth.uid())
    and m.accepted_at is not null
));

drop policy if exists "company members read filing approval snapshots" on public.filing_approval_snapshots;
create policy "company members read filing approval snapshots"
on public.filing_approval_snapshots for select to authenticated
using (exists (
  select 1 from public.company_memberships m
  where m.company_id = filing_approval_snapshots.company_id
    and m.user_id = (select auth.uid())
    and m.accepted_at is not null
));

drop policy if exists "company members read production filing submissions" on public.production_filing_submissions;
create policy "company members read production filing submissions"
on public.production_filing_submissions for select to authenticated
using (exists (
  select 1 from public.company_memberships m
  where m.company_id = production_filing_submissions.company_id
    and m.user_id = (select auth.uid())
    and m.accepted_at is not null
));

drop policy if exists "company members read production filing events" on public.production_filing_events;
create policy "company members read production filing events"
on public.production_filing_events for select to authenticated
using (exists (
  select 1
  from public.production_filing_submissions s
  join public.company_memberships m on m.company_id = s.company_id
  where s.id = production_filing_events.submission_id
    and m.user_id = (select auth.uid())
    and m.accepted_at is not null
));

drop policy if exists "active operators read production pilot entitlements" on public.production_pilot_entitlements;
create policy "active operators read production pilot entitlements"
on public.production_pilot_entitlements for select to authenticated
using (exists (select 1 from public.support_operators o where o.user_id = (select auth.uid()) and o.active));
drop policy if exists "active operators read filing approval snapshots" on public.filing_approval_snapshots;
create policy "active operators read filing approval snapshots"
on public.filing_approval_snapshots for select to authenticated
using (exists (select 1 from public.support_operators o where o.user_id = (select auth.uid()) and o.active));
drop policy if exists "active operators read production filing submissions" on public.production_filing_submissions;
create policy "active operators read production filing submissions"
on public.production_filing_submissions for select to authenticated
using (exists (select 1 from public.support_operators o where o.user_id = (select auth.uid()) and o.active));
drop policy if exists "active operators read production filing events" on public.production_filing_events;
create policy "active operators read production filing events"
on public.production_filing_events for select to authenticated
using (exists (select 1 from public.support_operators o where o.user_id = (select auth.uid()) and o.active));

create or replace function public.assert_fresh_production_owner(target_company_id uuid)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_actor_id uuid := auth.uid();
  v_claims jsonb := coalesce((select auth.jwt()), '{}'::jsonb);
  v_mfa_verified_at timestamptz;
begin
  if v_actor_id is null
    or coalesce(v_claims ->> 'sub', '') <> v_actor_id::text
    or coalesce(v_claims ->> 'aal', '') <> 'aal2'
    or not exists (
      select 1 from public.company_memberships m
      where m.company_id = target_company_id
        and m.user_id = v_actor_id
        and m.role = 'owner'
        and m.accepted_at is not null
    )
  then
    raise exception 'production_filing_fresh_owner_step_up_required';
  end if;

  if jsonb_typeof(v_claims -> 'amr') <> 'array' then
    raise exception 'production_filing_fresh_owner_step_up_required';
  end if;

  select to_timestamp((entry ->> 'timestamp')::double precision)
  into v_mfa_verified_at
  from jsonb_array_elements(v_claims -> 'amr') as entry
  where entry ->> 'method' in ('totp', 'mfa/totp', 'mfa/phone', 'mfa/webauthn')
    and entry ->> 'timestamp' ~ '^[0-9]{1,12}$'
  order by (entry ->> 'timestamp')::bigint desc
  limit 1;

  if v_mfa_verified_at is null
    or v_mfa_verified_at > now()
    or v_mfa_verified_at < now() - interval '15 minutes'
  then
    raise exception 'production_filing_fresh_owner_step_up_required';
  end if;
  return v_actor_id;
end;
$$;

create or replace function public.manage_production_pilot_entitlement(
  p_id uuid,
  p_company_id uuid,
  p_user_id uuid,
  p_income_year integer,
  p_status text,
  p_billing_exempt boolean,
  p_system_user_external_reference text,
  p_starts_at timestamptz,
  p_expires_at timestamptz,
  p_evidence_reference text
)
returns public.production_pilot_entitlements
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_actor_id uuid := auth.uid();
  v_row public.production_pilot_entitlements%rowtype;
begin
  if not exists (
    select 1 from public.support_operators o
    where o.user_id = v_actor_id and o.active and o.role = 'admin'
  ) then
    raise exception 'production_pilot_admin_required';
  end if;
  if p_income_year not between 2000 and 2100
    or p_status not in ('pending', 'active', 'suspended', 'completed', 'revoked')
    or p_starts_at >= p_expires_at
    or length(trim(coalesce(p_evidence_reference, ''))) not between 1 and 1000
    or length(trim(coalesce(p_system_user_external_reference, ''))) not between 1 and 200
    or not exists (
      select 1 from public.company_memberships m
      where m.company_id = p_company_id
        and m.user_id = p_user_id
        and m.role = 'owner'
        and m.accepted_at is not null
    )
  then
    raise exception 'production_pilot_invalid_entitlement';
  end if;

  if p_id is null then
    insert into public.production_pilot_entitlements (
      company_id, user_id, income_year, obligation, case_profile, status,
      billing_exempt, system_user_external_reference, starts_at, expires_at, evidence_reference, approved_by
    ) values (
      p_company_id, p_user_id, p_income_year, 'aksjonaerregisteroppgaven',
      'rf1086_no_activity_v1', p_status, p_billing_exempt, trim(p_system_user_external_reference), p_starts_at,
      p_expires_at, trim(p_evidence_reference), v_actor_id
    ) returning * into v_row;
  else
    update public.production_pilot_entitlements
    set status = p_status,
        billing_exempt = p_billing_exempt,
        system_user_external_reference = trim(p_system_user_external_reference),
        starts_at = p_starts_at,
        expires_at = p_expires_at,
        evidence_reference = trim(p_evidence_reference),
        approved_by = v_actor_id,
        updated_at = now()
    where id = p_id
      and company_id = p_company_id
      and user_id = p_user_id
      and income_year = p_income_year
      and obligation = 'aksjonaerregisteroppgaven'
      and case_profile = 'rf1086_no_activity_v1'
    returning * into v_row;
    if v_row.id is null then raise exception 'production_pilot_entitlement_not_found'; end if;
  end if;
  return v_row;
end;
$$;

create or replace function public.approve_production_filing(
  p_preview_id uuid,
  p_entitlement_id uuid,
  p_manifest jsonb,
  p_manifest_hash text,
  p_adapter_version text
)
returns public.filing_approval_snapshots
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_preview public.filing_previews%rowtype;
  v_entitlement public.production_pilot_entitlements%rowtype;
  v_actor_id uuid;
  v_row public.filing_approval_snapshots%rowtype;
  v_payload_hash text;
begin
  select * into v_preview from public.filing_previews where id = p_preview_id;
  if v_preview.id is null then raise exception 'production_preview_not_found'; end if;
  v_actor_id := public.assert_fresh_production_owner(v_preview.company_id);
  select * into v_entitlement
  from public.production_pilot_entitlements
  where id = p_entitlement_id
    and company_id = v_preview.company_id
    and user_id = v_actor_id
    and income_year = v_preview.income_year
    and obligation = 'aksjonaerregisteroppgaven'
    and case_profile = 'rf1086_no_activity_v1'
    and status = 'active'
    and starts_at <= now()
    and expires_at > now();
  if v_entitlement.id is null then raise exception 'production_pilot_entitlement_required'; end if;
  if v_preview.status <> 'ready'
    or v_preview.filing <> 'aksjonaerregisteroppgaven'
    or v_preview.hovedskjema_xml is null
    or jsonb_object_length(v_preview.underskjema_xml) < 1
    or jsonb_typeof(p_manifest) <> 'object'
    or p_manifest_hash !~ '^[0-9a-f]{64}$'
    or length(trim(coalesce(p_adapter_version, ''))) not between 1 and 100
    or coalesce(p_manifest ->> 'companyId', '') <> v_preview.company_id::text
    or coalesce(p_manifest ->> 'userId', '') <> v_actor_id::text
    or coalesce((p_manifest ->> 'incomeYear')::integer, -1) <> v_preview.income_year
    or coalesce(p_manifest ->> 'obligation', '') <> 'aksjonaerregisteroppgaven'
    or coalesce(p_manifest ->> 'caseProfile', '') <> 'rf1086_no_activity_v1'
    or coalesce(p_manifest ->> 'adapterVersion', '') <> p_adapter_version
    or coalesce(p_manifest ->> 'previewId', '') <> v_preview.id::text
    or jsonb_array_length(coalesce(p_manifest -> 'blockers', '[]'::jsonb)) <> 0
  then
    raise exception 'production_approval_manifest_invalid';
  end if;
  v_payload_hash := p_manifest ->> 'payloadHash';
  if v_payload_hash !~ '^[0-9a-f]{64}$' then raise exception 'production_approval_payload_hash_invalid'; end if;

  update public.filing_approval_snapshots
  set invalidated_at = now(), invalidation_reason = 'superseded_by_new_approval'
  where preview_id = p_preview_id and invalidated_at is null;

  insert into public.filing_approval_snapshots (
    entitlement_id, preview_id, company_id, user_id, income_year, obligation,
    case_profile, adapter_version, payload_hash, manifest_hash, manifest,
    approved_by
  ) values (
    v_entitlement.id, v_preview.id, v_preview.company_id, v_actor_id,
    v_preview.income_year, 'aksjonaerregisteroppgaven', 'rf1086_no_activity_v1',
    p_adapter_version, v_payload_hash, p_manifest_hash, p_manifest, v_actor_id
  ) returning * into v_row;
  return v_row;
end;
$$;

create or replace function public.begin_production_filing(p_approval_id uuid)
returns public.production_filing_submissions
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_approval public.filing_approval_snapshots%rowtype;
  v_actor_id uuid;
  v_row public.production_filing_submissions%rowtype;
begin
  select * into v_approval from public.filing_approval_snapshots where id = p_approval_id;
  if v_approval.id is null or v_approval.invalidated_at is not null then raise exception 'production_approval_invalid'; end if;
  v_actor_id := public.assert_fresh_production_owner(v_approval.company_id);
  if v_actor_id <> v_approval.user_id
    or not exists (
      select 1 from public.production_pilot_entitlements e
      where e.id = v_approval.entitlement_id
        and e.company_id = v_approval.company_id
        and e.user_id = v_actor_id
        and e.income_year = v_approval.income_year
        and e.obligation = v_approval.obligation
        and e.case_profile = v_approval.case_profile
        and e.status = 'active'
        and e.starts_at <= now() and e.expires_at > now()
    )
    or not exists (
      select 1 from public.authority_permissions p
      where p.company_id = v_approval.company_id
        and p.obligation = v_approval.obligation
        and p.submitter_user_id = v_actor_id
        and p.confirmed_by = v_actor_id
        and p.production_enabled
    )
    or not exists (
      select 1 from public.authority_test_runs t
      where t.company_id = v_approval.company_id
        and t.obligation = v_approval.obligation
        and t.status = 'accepted'
        and t.receipt_reference is not null
        and t.archive_reference is not null
    )
    or exists (
      select 1 from unnest(array[
        'launch_legal_name_public_copy', 'legal_policy_pack', 'security_restore',
        'support_rollback', 'founder_production_go_live', 'rf1086_authority'
      ]) required_key
      where not exists (
        select 1 from public.launch_signoffs s
        where s.key = required_key and s.status = 'approved'
      )
    )
  then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  insert into public.production_filing_submissions (
    approval_id, entitlement_id, company_id, user_id, income_year, obligation,
    case_profile, payload_hash, adapter_version, environment, status,
    submitted_by
  ) values (
    v_approval.id, v_approval.entitlement_id, v_approval.company_id,
    v_actor_id, v_approval.income_year, v_approval.obligation,
    v_approval.case_profile, v_approval.payload_hash, v_approval.adapter_version,
    'production', 'sending', v_actor_id
  ) on conflict (approval_id) do update set updated_at = public.production_filing_submissions.updated_at
  returning * into v_row;
  return v_row;
end;
$$;

create or replace function public.append_production_filing_event(
  p_submission_id uuid,
  p_operation_name text,
  p_operation_state text,
  p_attempt integer,
  p_body_hash text,
  p_idempotency_key uuid,
  p_authority_reference text,
  p_failure_class text,
  p_status text,
  p_final_authority_decision boolean default false
)
returns public.production_filing_events
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_submission public.production_filing_submissions%rowtype;
  v_event public.production_filing_events%rowtype;
  v_allowed boolean := false;
begin
  select * into v_submission from public.production_filing_submissions where id = p_submission_id for update;
  if v_submission.id is null then raise exception 'production_submission_not_found'; end if;
  if p_status = v_submission.status then
    v_allowed := true;
  elsif v_submission.status = 'sending' and p_status in ('received', 'unknown', 'rejected') then
    v_allowed := true;
  elsif v_submission.status = 'received' and p_status in ('processing', 'rejected', 'action_required') then
    v_allowed := true;
  elsif v_submission.status = 'processing' and p_status in ('accepted', 'rejected', 'action_required') then
    v_allowed := true;
  end if;
  if not v_allowed then raise exception 'production_submission_transition_invalid'; end if;
  if p_status = 'accepted' and p_final_authority_decision is not true then
    raise exception 'production_final_authority_decision_required';
  end if;

  insert into public.production_filing_events (
    submission_id, operation_name, operation_state, attempt, body_hash,
    idempotency_key, authority_reference, failure_class, resulting_status
  ) values (
    p_submission_id, trim(p_operation_name), p_operation_state, p_attempt,
    p_body_hash, p_idempotency_key, left(p_authority_reference, 500),
    p_failure_class, p_status
  ) returning * into v_event;

  update public.production_filing_submissions
  set status = p_status,
      authority_references = case
        when p_authority_reference is null then authority_references
        else authority_references || jsonb_build_object(p_operation_name, left(p_authority_reference, 500))
      end,
      failure_class = p_failure_class,
      updated_at = now()
  where id = p_submission_id;
  return v_event;
end;
$$;

revoke all on function public.assert_fresh_production_owner(uuid) from public, anon, authenticated;
revoke all on function public.manage_production_pilot_entitlement(uuid, uuid, uuid, integer, text, boolean, text, timestamptz, timestamptz, text) from public, anon, authenticated;
revoke all on function public.approve_production_filing(uuid, uuid, jsonb, text, text) from public, anon, authenticated;
revoke all on function public.begin_production_filing(uuid) from public, anon, authenticated;
revoke all on function public.append_production_filing_event(uuid, text, text, integer, text, uuid, text, text, text, boolean) from public, anon, authenticated;

grant execute on function public.manage_production_pilot_entitlement(uuid, uuid, uuid, integer, text, boolean, text, timestamptz, timestamptz, text) to authenticated;
grant execute on function public.approve_production_filing(uuid, uuid, jsonb, text, text) to authenticated;
grant execute on function public.begin_production_filing(uuid) to authenticated;
grant execute on function public.append_production_filing_event(uuid, text, text, integer, text, uuid, text, text, text, boolean) to service_role;
