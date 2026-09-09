-- Restore only the deployment-overlap authority surface. The physical owned
-- rows, case-bound projections and approved RF backend cutover remain intact.
begin;
set local lock_timeout='5s';
do $membership$
begin
  execute pg_catalog.format('grant authority_connections_store_owner,billing_store_owner,company_access_executor,ledger_store_owner to %I',current_user);
end;
$membership$;

grant usage on schema authority_connections to authenticated,service_role;
create view public.system_user_requests with(security_invoker=true)
as select * from authority_connections.system_user_requests;
create view public.authority_operations with(security_invoker=true)
as select * from authority_connections.authority_operations;
grant select on public.system_user_requests to authenticated,billing_store_owner,company_access_executor;
grant select on authority_connections.system_user_requests to authenticated,billing_store_owner,company_access_executor;
grant select,insert,update on public.authority_operations to service_role;
grant select,insert,update on authority_connections.authority_operations to service_role;
grant select on public.authority_operations,authority_connections.authority_operations to authenticated;
create policy system_user_requests_owner_read on authority_connections.system_user_requests
for select to authenticated using (
  initiating_owner_user_id=(select auth.uid()) and exists(
    select 1 from public.company_memberships m where m.company_id=system_user_requests.company_id
      and m.user_id=(select auth.uid()) and m.role='owner' and m.accepted_at is not null));
create policy billing_store_reads_system_user_requests on authority_connections.system_user_requests
for select to billing_store_owner using(public.company_access_is_active_admin_v1() and public.company_access_has_fresh_mfa_v1());
create policy support_case_read_system_user_requests on authority_connections.system_user_requests
for select to company_access_executor using(public.company_access_has_open_support_case_v1(
  public.company_access_current_support_case_id_v1(),company_id,'authority'));
create policy "active admin operators read authority operations" on authority_connections.authority_operations
for select to authenticated using(exists(select 1 from public.support_operators o
  where o.user_id=(select auth.uid()) and o.role='admin' and o.active));
create or replace function public.begin_system_user_request(
  p_id uuid,
  p_company_id uuid,
  p_external_ref text
)
returns authority_connections.system_user_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_owner_id uuid;
  v_request authority_connections.system_user_requests%rowtype;
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'authenticated' then
    raise exception 'system_user_request_authenticated_owner_required';
  end if;

  if p_id is null or p_external_ref is null or p_external_ref !~ '^[A-Za-z0-9_-]{43}$' then
    raise exception 'system_user_request_invalid_identity';
  end if;

  v_owner_id := public.assert_fresh_production_owner(p_company_id);

  insert into authority_connections.system_user_requests (
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
returns authority_connections.system_user_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_request authority_connections.system_user_requests%rowtype;
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
  from authority_connections.system_user_requests r
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

    update authority_connections.system_user_requests
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
    from authority_connections.authority_operations o
    where o.id = p_operator_evidence_id
      and o.operation = 'register_rf1086_system'
      and o.status = 'succeeded'
      and o.result_code in ('created_and_verified', 'already_verified')
  ) then
    raise exception 'system_user_request_operator_evidence_invalid';
  end if;

  if v_request.status = 'accepted' and p_status = 'verification_failed' then
    update billing.production_pilot_entitlements
    set status = 'suspended',
        updated_at = v_now
    where system_user_request_id = v_request.id
      and status = 'active';
  end if;

  update authority_connections.system_user_requests
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
returns authority_connections.system_user_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_request authority_connections.system_user_requests%rowtype;
begin
  if coalesce((select auth.jwt()) ->> 'role', '') <> 'service_role' then
    raise exception 'system_user_request_service_role_required';
  end if;

  select r.*
  into v_request
  from authority_connections.system_user_requests r
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

  update authority_connections.system_user_requests
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


do $overlap_grants$
declare v_row record; v_privilege text; v_column text; v_schema name;
begin
  for v_row in select * from backend_system.authority_connections_overlap_grants loop
    if v_row.target in ('authority_schema_usage','billing_schema_usage') then
      select nspname into strict v_schema from pg_catalog.pg_namespace where oid=v_row.target_oid;
      execute pg_catalog.format('grant usage on schema %I to %I',v_schema,v_row.grantee);
    elsif v_row.target like 'request_%' then
      v_privilege:=case v_row.target when 'request_insert' then 'INSERT' when 'request_update' then 'UPDATE' else 'SELECT' end;
      execute pg_catalog.format('grant %s on table %s to %I',v_privilege,v_row.target_oid::regclass,v_row.grantee);
    else
      v_privilege:=case when v_row.target in ('pilot_status_update','pilot_updated_at_update') then 'UPDATE' else 'SELECT' end;
      v_column:=case v_row.target when 'pilot_updated_at_update' then 'updated_at' when 'pilot_binding_select' then 'system_user_request_id' else 'status' end;
      execute pg_catalog.format('grant %s (%I) on table %s to %I',v_privilege,v_column,v_row.target_oid::regclass,v_row.grantee);
    end if;
  end loop;
end;
$overlap_grants$;
do $cleanup$
begin
  execute pg_catalog.format('revoke authority_connections_store_owner,billing_store_owner,company_access_executor,ledger_store_owner from %I',current_user);
end;
$cleanup$;
commit;
