-- Durable, tenant-isolated Systembruker request state. External authority calls
-- happen outside these short transition transactions; only safe metadata lands here.
create table if not exists public.system_user_requests (
  id uuid primary key,
  company_id uuid not null references public.companies(id) on delete cascade,
  initiating_owner_user_id uuid not null references auth.users(id) on delete restrict,
  obligation text not null default 'aksjonaerregisteroppgaven'
    check (obligation = 'aksjonaerregisteroppgaven'),
  external_ref text not null unique check (external_ref ~ '^[A-Za-z0-9_-]{43}$'),
  altinn_request_id uuid unique,
  status text not null check (
    status in ('creating', 'new', 'accepted', 'rejected', 'denied', 'timedout', 'verification_failed')
  ),
  confirm_url text,
  preflight_verified_at timestamptz,
  failure_code text check (failure_code is null or failure_code ~ '^[a-z0-9_]{1,64}$'),
  operator_evidence_id uuid references public.authority_operations(id) on delete set null,
  requested_at timestamptz,
  last_status_checked_at timestamptz,
  accepted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  resolved_at timestamptz,
  check (preflight_verified_at is null or status = 'accepted')
);

-- Earlier feature-branch rehearsals accepted multiple authority hosts and query
-- shapes. Clear any such draft metadata before enforcing the one safe value.
update public.system_user_requests
set confirm_url = null,
    updated_at = pg_catalog.now()
where confirm_url is not null
  and (
    altinn_request_id is null
    or confirm_url is distinct from (
      'https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id='
      || altinn_request_id::text
    )
  );

alter table public.system_user_requests
  drop constraint if exists system_user_requests_confirm_url_check;
alter table public.system_user_requests
  drop constraint if exists system_user_requests_confirm_url_canonical;
alter table public.system_user_requests
  add constraint system_user_requests_confirm_url_canonical
  check (
    confirm_url is null
    or (
      altinn_request_id is not null
      and confirm_url = (
        'https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id='
        || altinn_request_id::text
      )
    )
  );

create unique index if not exists system_user_requests_one_live_company_obligation
on public.system_user_requests(company_id, obligation)
where status in ('creating', 'new', 'accepted', 'verification_failed');

create index if not exists system_user_requests_company_idx
on public.system_user_requests(company_id, created_at desc);

create index if not exists system_user_requests_owner_idx
on public.system_user_requests(initiating_owner_user_id, company_id, created_at desc);

create index if not exists system_user_requests_operator_evidence_idx
on public.system_user_requests(operator_evidence_id)
where operator_evidence_id is not null;

alter table public.system_user_requests enable row level security;

revoke all on table public.system_user_requests from public, anon, authenticated, service_role;
grant select on table public.system_user_requests to authenticated;

drop policy if exists system_user_requests_owner_read on public.system_user_requests;
create policy system_user_requests_owner_read
on public.system_user_requests for select to authenticated
using (
  initiating_owner_user_id = (select auth.uid())
  and exists (
    select 1
    from public.company_memberships m
    where m.company_id = system_user_requests.company_id
      and m.user_id = (select auth.uid())
      and m.role = 'owner'
      and m.accepted_at is not null
  )
);

drop policy if exists system_user_requests_operator_read on public.system_user_requests;
create policy system_user_requests_operator_read
on public.system_user_requests for select to authenticated
using (
  exists (
    select 1
    from public.support_operators o
    where o.user_id = (select auth.uid())
      and o.active
  )
);

create or replace function public.begin_system_user_request(
  p_id uuid,
  p_company_id uuid,
  p_external_ref text
)
returns public.system_user_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_owner_id uuid;
  v_request public.system_user_requests%rowtype;
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'authenticated' then
    raise exception 'system_user_request_authenticated_owner_required';
  end if;

  if p_id is null or p_external_ref is null or p_external_ref !~ '^[A-Za-z0-9_-]{43}$' then
    raise exception 'system_user_request_invalid_identity';
  end if;

  v_owner_id := public.assert_fresh_production_owner(p_company_id);

  insert into public.system_user_requests (
    id,
    company_id,
    initiating_owner_user_id,
    obligation,
    external_ref,
    status
  ) values (
    p_id,
    p_company_id,
    v_owner_id,
    'aksjonaerregisteroppgaven',
    p_external_ref,
    'creating'
  )
  returning * into v_request;

  return v_request;
end;
$$;

create or replace function public.record_system_user_authority_state(
  p_request_id uuid,
  p_company_id uuid,
  p_altinn_request_id uuid,
  p_external_ref text,
  p_status text,
  p_confirm_url text,
  p_failure_code text,
  p_operator_evidence_id uuid
)
returns public.system_user_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_request public.system_user_requests%rowtype;
  v_effective_altinn_request_id uuid;
  v_canonical_confirm_url text;
  v_transition_allowed boolean := false;
  v_now timestamptz := pg_catalog.now();
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'service_role' then
    raise exception 'system_user_request_service_role_required';
  end if;

  select r.*
  into v_request
  from public.system_user_requests r
  where r.id = p_request_id
  for update;

  if v_request.id is null then
    raise exception 'system_user_request_not_found';
  end if;

  if v_request.company_id is distinct from p_company_id
    or v_request.external_ref is distinct from p_external_ref
    or v_request.obligation <> 'aksjonaerregisteroppgaven'
    or not exists (
      select 1
      from public.company_memberships m
      where m.company_id = v_request.company_id
        and m.user_id = v_request.initiating_owner_user_id
        and m.role = 'owner'
        and m.accepted_at is not null
    )
  then
    raise exception 'system_user_request_relationship_mismatch';
  end if;

  if p_status is null or p_status not in (
    'creating', 'new', 'accepted', 'rejected', 'denied', 'timedout', 'verification_failed'
  ) then
    raise exception 'invalid_system_user_transition';
  end if;

  if v_request.status = 'creating'
    and p_status in (
      'creating', 'new', 'accepted', 'rejected', 'denied', 'timedout', 'verification_failed'
    )
  then
    v_transition_allowed := true;
  elsif v_request.status = 'new'
    and p_status in ('new', 'accepted', 'rejected', 'denied', 'timedout', 'verification_failed')
  then
    v_transition_allowed := true;
  elsif v_request.status = 'accepted'
    and p_status in ('accepted', 'verification_failed')
  then
    v_transition_allowed := true;
  elsif v_request.status = 'rejected' and p_status = 'rejected' then
    v_transition_allowed := true;
  elsif v_request.status = 'denied' and p_status = 'denied' then
    v_transition_allowed := true;
  elsif v_request.status = 'timedout' and p_status = 'timedout' then
    v_transition_allowed := true;
  elsif v_request.status = 'verification_failed'
    and p_status in ('verification_failed', 'accepted')
  then
    v_transition_allowed := true;
  end if;

  if not v_transition_allowed then
    raise exception 'invalid_system_user_transition';
  end if;

  if v_request.status in ('rejected', 'denied', 'timedout') then
    if p_altinn_request_id is distinct from v_request.altinn_request_id
      or p_confirm_url is distinct from v_request.confirm_url
      or p_failure_code is distinct from v_request.failure_code
      or p_operator_evidence_id is distinct from v_request.operator_evidence_id
    then
      raise exception 'system_user_request_terminal_evidence_immutable';
    end if;

    update public.system_user_requests
    set last_status_checked_at = v_now,
        updated_at = v_now
    where id = p_request_id
    returning * into v_request;

    return v_request;
  end if;

  if v_request.altinn_request_id is not null
    and v_request.altinn_request_id is distinct from p_altinn_request_id
  then
    raise exception 'system_user_request_relationship_mismatch';
  end if;

  v_effective_altinn_request_id := coalesce(
    v_request.altinn_request_id,
    p_altinn_request_id
  );
  if p_status in ('new', 'accepted', 'rejected', 'denied', 'timedout')
    and v_effective_altinn_request_id is null
  then
    raise exception 'system_user_request_relationship_mismatch';
  end if;

  if v_effective_altinn_request_id is not null then
    v_canonical_confirm_url :=
      'https://am.ui.altinn.no/accessmanagement/ui/systemuser/request?id='
      || v_effective_altinn_request_id::text;
  end if;

  if p_confirm_url is not null
    and p_confirm_url is distinct from v_canonical_confirm_url
  then
    raise exception 'system_user_request_invalid_confirmation_url';
  end if;

  if v_request.confirm_url is not null
    and v_request.confirm_url is distinct from v_canonical_confirm_url
  then
    raise exception 'system_user_request_invalid_confirmation_url';
  end if;

  if p_status = 'new'
    and coalesce(v_request.confirm_url, p_confirm_url) is null
  then
    raise exception 'system_user_request_invalid_confirmation_url';
  end if;

  if p_status = 'verification_failed' then
    if p_failure_code is null or p_failure_code not in (
      'invalid_environment',
      'invalid_timeout',
      'invalid_bearer_token',
      'invalid_organization_number',
      'invalid_external_reference',
      'invalid_request_id',
      'network_error',
      'response_too_large',
      'response_contract_mismatch',
      'invalid_confirmation_url',
      'duplicate_system_user_request',
      'authority_http_error',
      'maskinporten_grant_signing_failed',
      'maskinporten_network_error',
      'maskinporten_http_error',
      'maskinporten_response_invalid',
      'maskinporten_token_error'
    ) then
      raise exception 'system_user_request_failure_code_invalid';
    end if;
  elsif p_failure_code is not null then
    raise exception 'system_user_request_failure_code_invalid';
  end if;

  if p_operator_evidence_id is not null and not exists (
    select 1
    from public.authority_operations o
    where o.id = p_operator_evidence_id
      and o.operation = 'register_rf1086_system'
      and o.status = 'succeeded'
      and o.result_code in ('created_and_verified', 'already_verified')
  ) then
    raise exception 'system_user_request_operator_evidence_invalid';
  end if;

  if v_request.status = 'accepted' and p_status = 'verification_failed' then
    update public.production_pilot_entitlements
    set status = 'suspended',
        updated_at = v_now
    where system_user_request_id = v_request.id
      and status = 'active';
  end if;

  update public.system_user_requests
  set altinn_request_id = v_effective_altinn_request_id,
      status = p_status,
      confirm_url = case
        when confirm_url is not null or p_confirm_url is not null
          then v_canonical_confirm_url
        else null
      end,
      preflight_verified_at = case
        when p_status = 'accepted' then preflight_verified_at
        else null
      end,
      failure_code = p_failure_code,
      operator_evidence_id = coalesce(p_operator_evidence_id, operator_evidence_id),
      requested_at = case
        when v_effective_altinn_request_id is not null then coalesce(requested_at, v_now)
        else requested_at
      end,
      last_status_checked_at = v_now,
      accepted_at = case
        when p_status = 'accepted' then coalesce(accepted_at, v_now)
        else accepted_at
      end,
      resolved_at = case
        when p_status in ('accepted', 'rejected', 'denied', 'timedout')
          then coalesce(resolved_at, v_now)
        else resolved_at
      end,
      updated_at = v_now
  where id = p_request_id
  returning * into v_request;

  return v_request;
end;
$$;

create or replace function public.verify_system_user_preflight(
  p_request_id uuid,
  p_expected_external_ref text
)
returns public.system_user_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_request public.system_user_requests%rowtype;
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'service_role' then
    raise exception 'system_user_request_service_role_required';
  end if;

  select r.*
  into v_request
  from public.system_user_requests r
  where r.id = p_request_id
  for update;

  if v_request.id is null then
    raise exception 'system_user_request_not_found';
  end if;
  if v_request.external_ref is distinct from p_expected_external_ref then
    raise exception 'system_user_request_relationship_mismatch';
  end if;
  if v_request.status <> 'accepted' or v_request.altinn_request_id is null then
    raise exception 'system_user_request_preflight_not_allowed';
  end if;

  update public.system_user_requests
  set preflight_verified_at = coalesce(preflight_verified_at, pg_catalog.now()),
      failure_code = null,
      updated_at = pg_catalog.now()
  where id = p_request_id
  returning * into v_request;

  return v_request;
end;
$$;

revoke all on function public.begin_system_user_request(uuid, uuid, text)
  from public, anon, authenticated, service_role;
revoke all on function public.record_system_user_authority_state(uuid, uuid, uuid, text, text, text, text, uuid)
  from public, anon, authenticated, service_role;
revoke all on function public.verify_system_user_preflight(uuid, text)
  from public, anon, authenticated, service_role;

grant execute on function public.begin_system_user_request(uuid, uuid, text)
  to authenticated;
grant execute on function public.record_system_user_authority_state(uuid, uuid, uuid, text, text, text, text, uuid)
  to service_role;
grant execute on function public.verify_system_user_preflight(uuid, text)
  to service_role;

-- Existing active beta rows are not silently blessed. NOT VALID preserves
-- migration safety for those rows while enforcing the binding on every new or
-- subsequently updated entitlement; begin_production_filing blocks them until
-- an operator explicitly binds a verified request through the replacement RPC.
alter table public.production_pilot_entitlements
  add column if not exists system_user_request_id uuid
  references public.system_user_requests(id) on delete restrict;

alter table public.production_pilot_entitlements
  drop constraint if exists production_pilot_entitlements_verified_request_required;
alter table public.production_pilot_entitlements
  add constraint production_pilot_entitlements_verified_request_required
  check (status <> 'active' or system_user_request_id is not null)
  not valid;

create index if not exists production_pilot_entitlements_system_user_request_idx
on public.production_pilot_entitlements(system_user_request_id)
where system_user_request_id is not null;

do $migration$
begin
  if pg_catalog.to_regprocedure(
    'public.manage_production_pilot_entitlement(uuid,uuid,uuid,integer,text,boolean,text,timestamptz,timestamptz,text)'
  ) is not null then
    execute 'revoke all on function public.manage_production_pilot_entitlement(uuid, uuid, uuid, integer, text, boolean, text, timestamptz, timestamptz, text) from public, anon, authenticated, service_role';
  end if;
end;
$migration$;
drop function if exists public.manage_production_pilot_entitlement(uuid, uuid, uuid, integer, text, boolean, text, timestamptz, timestamptz, text);

create or replace function public.manage_production_pilot_entitlement(
  p_id uuid,
  p_company_id uuid,
  p_user_id uuid,
  p_income_year integer,
  p_status text,
  p_billing_exempt boolean,
  p_system_user_request_id uuid,
  p_starts_at timestamptz,
  p_expires_at timestamptz,
  p_evidence_reference text
)
returns public.production_pilot_entitlements
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_actor_id uuid := auth.uid();
  v_request public.system_user_requests%rowtype;
  v_existing public.production_pilot_entitlements%rowtype;
  v_row public.production_pilot_entitlements%rowtype;
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'authenticated'
    or not exists (
      select 1
      from public.support_operators o
      where o.user_id = v_actor_id
        and o.active
        and o.role = 'admin'
    )
  then
    raise exception 'production_pilot_admin_required';
  end if;

  select r.*
  into v_request
  from public.system_user_requests r
  where r.id = p_system_user_request_id
  for update;

  if v_request.id is null
    or v_request.company_id <> p_company_id
    or v_request.initiating_owner_user_id <> p_user_id
    or v_request.obligation <> 'aksjonaerregisteroppgaven'
    or v_request.status <> 'accepted'
    or v_request.preflight_verified_at is null
    or not exists (
      select 1
      from public.company_memberships m
      where m.company_id = v_request.company_id
        and m.user_id = v_request.initiating_owner_user_id
        and m.role = 'owner'
        and m.accepted_at is not null
    )
  then
    raise exception 'production_pilot_verified_system_user_required';
  end if;

  if p_income_year not between 2000 and 2100
    or p_status not in ('pending', 'active', 'suspended', 'completed', 'revoked')
    or p_starts_at >= p_expires_at
    or length(trim(coalesce(p_evidence_reference, ''))) not between 1 and 1000
  then
    raise exception 'production_pilot_invalid_entitlement';
  end if;

  if p_id is not null then
    select e.*
    into v_existing
    from public.production_pilot_entitlements e
    where e.id = p_id
    for update;

    if v_existing.id is null
      or v_existing.company_id <> p_company_id
      or v_existing.user_id <> p_user_id
      or v_existing.income_year <> p_income_year
      or v_existing.obligation <> 'aksjonaerregisteroppgaven'
      or v_existing.case_profile <> 'rf1086_no_activity_v1'
    then
      raise exception 'production_pilot_entitlement_not_found';
    end if;
  end if;

  if p_id is null then
    insert into public.production_pilot_entitlements (
      company_id,
      user_id,
      income_year,
      obligation,
      case_profile,
      status,
      billing_exempt,
      system_user_request_id,
      system_user_external_reference,
      starts_at,
      expires_at,
      evidence_reference,
      approved_by
    ) values (
      p_company_id,
      p_user_id,
      p_income_year,
      'aksjonaerregisteroppgaven',
      'rf1086_no_activity_v1',
      p_status,
      p_billing_exempt,
      v_request.id,
      v_request.external_ref,
      p_starts_at,
      p_expires_at,
      trim(p_evidence_reference),
      v_actor_id
    )
    returning * into v_row;
  else
    update public.production_pilot_entitlements
    set status = p_status,
        billing_exempt = p_billing_exempt,
        system_user_request_id = v_request.id,
        system_user_external_reference = v_request.external_ref,
        starts_at = p_starts_at,
        expires_at = p_expires_at,
        evidence_reference = trim(p_evidence_reference),
        approved_by = v_actor_id,
        updated_at = pg_catalog.now()
    where id = v_existing.id
    returning * into v_row;
  end if;

  return v_row;
end;
$$;

create or replace function public.begin_production_filing(p_approval_id uuid)
returns public.production_filing_submissions
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_approval public.filing_approval_snapshots%rowtype;
  v_actor_id uuid;
  v_system_user_request_id uuid;
  v_request public.system_user_requests%rowtype;
  v_entitlement public.production_pilot_entitlements%rowtype;
  v_row public.production_filing_submissions%rowtype;
begin
  select *
  into v_approval
  from public.filing_approval_snapshots
  where id = p_approval_id;

  if v_approval.id is null or v_approval.invalidated_at is not null then
    raise exception 'production_approval_invalid';
  end if;

  v_actor_id := public.assert_fresh_production_owner(v_approval.company_id);
  if v_actor_id <> v_approval.user_id then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  -- Discover the foreign key without locking, then acquire authorization locks
  -- in one order everywhere: exact request first, linked entitlement second.
  select e.system_user_request_id
  into v_system_user_request_id
  from public.production_pilot_entitlements e
  where e.id = v_approval.entitlement_id;

  if v_system_user_request_id is null then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  select r.*
  into v_request
  from public.system_user_requests r
  where r.id = v_system_user_request_id
  for update;

  if v_request.id is null then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  select e.*
  into v_entitlement
  from public.production_pilot_entitlements e
  where e.id = v_approval.entitlement_id
  for update;

  if v_entitlement.id is null
    or v_entitlement.system_user_request_id is distinct from v_request.id
    or v_entitlement.company_id <> v_approval.company_id
    or v_entitlement.user_id <> v_actor_id
    or v_entitlement.income_year <> v_approval.income_year
    or v_entitlement.obligation <> v_approval.obligation
    or v_entitlement.case_profile <> v_approval.case_profile
    or v_entitlement.status <> 'active'
    or v_entitlement.starts_at > pg_catalog.now()
    or v_entitlement.expires_at <= pg_catalog.now()
    or v_request.company_id <> v_approval.company_id
    or v_request.initiating_owner_user_id <> v_actor_id
    or v_request.obligation <> v_approval.obligation
    or v_request.status <> 'accepted'
    or v_request.preflight_verified_at is null
    or v_request.external_ref <> v_entitlement.system_user_external_reference
    or not exists (
      select 1
      from public.authority_permissions p
      where p.company_id = v_approval.company_id
        and p.obligation = v_approval.obligation
        and p.submitter_user_id = v_actor_id
        and p.confirmed_by = v_actor_id
        and p.production_enabled
    )
    or not coalesce((
      select r.ready and jsonb_array_length(r.hard_blocks) = 0
      from public.filing_readiness_snapshots r
      where r.company_id = v_approval.company_id
        and r.income_year = v_approval.income_year
        and r.obligation = v_approval.obligation
      order by r.updated_at desc, r.id desc
      limit 1
    ), false)
    or exists (
      select 1
      from public.filing_overrides o
      where o.company_id = v_approval.company_id
        and o.income_year = v_approval.income_year
        and o.risk_level = 'block'
    )
    or exists (
      select 1
      from public.filing_review_comments c
      where c.preview_id = v_approval.preview_id
        and c.severity = 'hard_block'
        and c.acknowledged_at is null
    )
    or exists (
      select 1
      from unnest(array[
        'launch_legal_name_public_copy', 'legal_policy_pack', 'security_restore',
        'support_rollback', 'founder_production_go_live', 'rf1086_authority'
      ]) required_key
      where not exists (
        select 1
        from public.launch_signoffs s
        where s.key = required_key
          and s.status = 'approved'
          and s.reviewed_at <= pg_catalog.now()
          and (
            s.key <> 'security_restore'
            or s.reviewed_at >= pg_catalog.now() - interval '30 days'
          )
      )
    )
  then
    raise exception 'production_filing_release_gate_blocked';
  end if;

  insert into public.production_filing_submissions (
    approval_id,
    entitlement_id,
    company_id,
    user_id,
    income_year,
    obligation,
    case_profile,
    payload_hash,
    adapter_version,
    environment,
    status,
    submitted_by
  ) values (
    v_approval.id,
    v_approval.entitlement_id,
    v_approval.company_id,
    v_actor_id,
    v_approval.income_year,
    v_approval.obligation,
    v_approval.case_profile,
    v_approval.payload_hash,
    v_approval.adapter_version,
    'production',
    'sending',
    v_actor_id
  )
  on conflict (approval_id) do update
  set updated_at = public.production_filing_submissions.updated_at
  returning * into v_row;

  return v_row;
end;
$$;

revoke all on function public.manage_production_pilot_entitlement(uuid, uuid, uuid, integer, text, boolean, uuid, timestamptz, timestamptz, text)
  from public, anon, authenticated, service_role;
revoke all on function public.begin_production_filing(uuid)
  from public, anon, authenticated, service_role;

grant execute on function public.manage_production_pilot_entitlement(uuid, uuid, uuid, integer, text, boolean, uuid, timestamptz, timestamptz, text)
  to authenticated;
grant execute on function public.begin_production_filing(uuid)
  to authenticated;

notify pgrst, 'reload schema';
