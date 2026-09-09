-- Authority Connections expand: preserve row identity and one physical writer.
-- Temporary public views exist only until the independently deployed web cutover.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
select pg_catalog.pg_advisory_xact_lock(
  pg_catalog.hashtextextended('talli:authority-connections:capability:v1', 0)
);
lock table public.system_user_requests, public.authority_operations in share row exclusive mode;

do $roles$
begin
  if not exists (select 1 from pg_catalog.pg_roles where rolname='authority_connections_store_owner') then
    create role authority_connections_store_owner nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname='authority_connections_executor') then
    create role authority_connections_executor nologin noinherit nobypassrls;
  end if;
  if not exists (select 1 from pg_catalog.pg_roles where rolname='billing_authority_state_owner') then
    create role billing_authority_state_owner nologin noinherit nobypassrls;
  end if;
end
$roles$;
alter role authority_connections_store_owner nologin noinherit nobypassrls;
alter role authority_connections_executor nologin noinherit nobypassrls;
alter role billing_authority_state_owner nologin noinherit nobypassrls;
do $membership$
begin
  execute pg_catalog.format('grant authority_connections_store_owner, authority_connections_executor, billing_authority_state_owner, billing_store_owner, company_access_executor, ledger_store_owner to %I', current_user);
end
$membership$;

-- Technical ACL ledger: no runtime principal can read or mutate its rows.
set local role ledger_store_owner;
grant create on schema backend_system to ledger_store_owner;
create table if not exists backend_system.authority_connections_overlap_grants (
  target text not null check(target in ('request_insert','request_update','request_select',
    'pilot_status_update','pilot_updated_at_update','pilot_binding_select','pilot_status_select',
    'authority_schema_usage','billing_schema_usage')),
  grantee name not null,
  target_oid oid not null,
  primary key(target,grantee)
);
alter table backend_system.authority_connections_overlap_grants enable row level security;
alter table backend_system.authority_connections_overlap_grants force row level security;
revoke all on backend_system.authority_connections_overlap_grants from public,anon,authenticated,service_role;
revoke create on schema backend_system from ledger_store_owner;
reset role;

create schema if not exists authority_connections authorization authority_connections_store_owner;
revoke all on schema authority_connections from public, anon, authenticated, service_role;
grant usage on schema authority_connections to authority_connections_executor,
  authority_connections_store_owner, billing_authority_state_owner, billing_store_owner,
  company_access_executor, authenticated, service_role;
alter table public.authority_operations set schema authority_connections;
alter table public.system_user_requests set schema authority_connections;
alter table authority_connections.authority_operations owner to authority_connections_store_owner;
alter table authority_connections.system_user_requests owner to authority_connections_store_owner;
alter table authority_connections.authority_operations enable row level security;
alter table authority_connections.authority_operations force row level security;
alter table authority_connections.system_user_requests enable row level security;
alter table authority_connections.system_user_requests force row level security;

grant execute on function public.company_access_auth_uid_v1(),
  public.company_access_auth_jwt_v1(), public.company_access_is_accepted_owner_v1(uuid),
  public.company_access_is_accepted_owner_subject_v1(uuid,uuid),
  public.company_access_is_active_admin_v1(), public.company_access_has_fresh_mfa_v1(),
  public.company_access_read_company_identity_v1(uuid,text),
  public.company_access_has_open_support_case_v1(uuid,uuid,text),
  public.company_access_current_support_case_id_v1()
to authority_connections_store_owner, authority_connections_executor, billing_authority_state_owner;

create or replace function authority_connections.verified_actor_v1()
returns uuid language plpgsql stable security definer set search_path='' as $function$
declare
  v_actor uuid := nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
  v_claims jsonb := nullif(pg_catalog.current_setting('talli.verified_actor_claims',true),'')::jsonb;
begin
  if v_actor is null or v_claims->>'sub' is distinct from v_actor::text
    or v_claims->>'role' is distinct from 'authenticated'
    or public.company_access_auth_uid_v1() is distinct from v_actor
  then return null; end if;
  return v_actor;
end;
$function$;

create policy authority_requests_owner_read on authority_connections.system_user_requests
for select to authority_connections_executor, authority_connections_store_owner
using (initiating_owner_user_id=authority_connections.verified_actor_v1()
  and public.company_access_is_accepted_owner_v1(company_id));
create policy authority_requests_owner_write on authority_connections.system_user_requests
for all to authority_connections_store_owner
using (initiating_owner_user_id=authority_connections.verified_actor_v1()
  and public.company_access_is_accepted_owner_v1(company_id))
with check (initiating_owner_user_id=authority_connections.verified_actor_v1()
  and public.company_access_is_accepted_owner_v1(company_id));
-- SELECT FOR UPDATE for the fixed billing verification projection. WITH CHECK
-- false denies actual admin writes through this policy; mutation RPCs require owner.
drop policy if exists authority_requests_admin_projection_read on authority_connections.system_user_requests;
create policy authority_requests_admin_projection_read on authority_connections.system_user_requests
for select to authority_connections_store_owner
using (authority_connections.verified_actor_v1() is not null
  and public.company_access_is_active_admin_v1() and public.company_access_has_fresh_mfa_v1());
drop policy if exists authority_requests_admin_projection_lock on authority_connections.system_user_requests;
create policy authority_requests_admin_projection_lock on authority_connections.system_user_requests
for update to authority_connections_store_owner
using (authority_connections.verified_actor_v1() is not null
  and public.company_access_is_active_admin_v1() and public.company_access_has_fresh_mfa_v1())
with check (false);
create policy authority_requests_support_projection_read on authority_connections.system_user_requests
for select to authority_connections_store_owner
using (authority_connections.verified_actor_v1() is not null
  and public.company_access_has_open_support_case_v1(
  public.company_access_current_support_case_id_v1(),company_id,'authority'));
create policy authority_operations_callback_read on authority_connections.authority_operations
for select to authority_connections_store_owner
using (operation='set_rf1086_systembruker_callback');

grant select on authority_connections.system_user_requests to authority_connections_executor;
grant select,insert,update on authority_connections.system_user_requests to authority_connections_store_owner;
grant select on authority_connections.authority_operations to authority_connections_store_owner;

create function authority_connections.assert_owner_v1(p_company_id uuid,p_fresh boolean)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare
  v_actor uuid := nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'')::uuid;
  v_claims jsonb := nullif(pg_catalog.current_setting('talli.verified_actor_claims',true),'')::jsonb;
begin
  if v_actor is null or v_claims->>'sub' is distinct from v_actor::text
    or v_claims->>'role' is distinct from 'authenticated'
    or public.company_access_auth_uid_v1() is distinct from v_actor
    or not public.company_access_is_accepted_owner_v1(p_company_id)
  then raise exception 'authority_owner_required'; end if;
  if p_fresh and not public.company_access_has_fresh_mfa_v1()
  then raise exception 'authority_step_up_required'; end if;
  return public.company_access_read_company_identity_v1(p_company_id,v_actor::text);
end;
$function$;

create function authority_connections.begin_request_v1(p_id uuid,p_company_id uuid,p_external_ref text)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare v_request authority_connections.system_user_requests%rowtype;
begin
  perform authority_connections.assert_owner_v1(p_company_id,true);
  insert into authority_connections.system_user_requests
    (id,company_id,initiating_owner_user_id,obligation,external_ref,status)
  values (p_id,p_company_id,public.company_access_auth_uid_v1(),'aksjonaerregisteroppgaven',p_external_ref,'creating')
  returning * into v_request;
  perform authority_connections.assert_owner_v1(p_company_id,true);
  return pg_catalog.to_jsonb(v_request);
end;
$function$;

create function authority_connections.lock_owned_request_v1(p_request_id uuid,p_company_id uuid)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare v_request authority_connections.system_user_requests%rowtype;
begin
  perform authority_connections.assert_owner_v1(p_company_id,false);
  select * into v_request from authority_connections.system_user_requests
  where id=p_request_id and company_id=p_company_id for update;
  if v_request.id is null then raise exception 'system_user_request_not_found'; end if;
  perform authority_connections.assert_owner_v1(p_company_id,false);
  if v_request.initiating_owner_user_id is distinct from public.company_access_auth_uid_v1()
  then raise exception 'system_user_request_relationship_mismatch'; end if;
  return pg_catalog.to_jsonb(v_request);
end;
$function$;

create or replace function authority_connections.record_authority_state_v1(
  p_request_id uuid,
  p_company_id uuid,
  p_altinn_request_id uuid,
  p_external_ref text,
  p_status text,
  p_confirm_url text,
  p_failure_code text
)
returns jsonb
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
  perform authority_connections.assert_owner_v1(p_company_id, false);

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
    or v_request.initiating_owner_user_id is distinct from public.company_access_auth_uid_v1()
    or not public.company_access_is_accepted_owner_v1(v_request.company_id)
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
    then
      raise exception 'system_user_request_terminal_evidence_immutable';
    end if;

    update authority_connections.system_user_requests
    set last_status_checked_at = v_now,
        updated_at = v_now
    where id = p_request_id
    returning * into v_request;
    if not found then raise exception 'system_user_request_not_found'; end if;

    perform authority_connections.assert_owner_v1(p_company_id, false);
    return pg_catalog.to_jsonb(v_request);
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
  if not found then raise exception 'system_user_request_not_found'; end if;

  perform authority_connections.assert_owner_v1(p_company_id, false);
    return pg_catalog.to_jsonb(v_request);
end;
$$;


create function authority_connections.verify_preflight_v1(p_request_id uuid,p_company_id uuid,p_expected_external_ref text)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare v_request authority_connections.system_user_requests%rowtype;
begin
  perform authority_connections.lock_owned_request_v1(p_request_id,p_company_id);
  select * into v_request from authority_connections.system_user_requests where id=p_request_id;
  if v_request.external_ref is distinct from p_expected_external_ref
  then raise exception 'system_user_request_relationship_mismatch'; end if;
  if v_request.status<>'accepted' or v_request.altinn_request_id is null
  then raise exception 'system_user_request_preflight_not_allowed'; end if;
  update authority_connections.system_user_requests
  set preflight_verified_at=coalesce(preflight_verified_at,pg_catalog.now()),
    failure_code=null,updated_at=pg_catalog.now()
  where id=p_request_id returning * into v_request;
  if not found then raise exception 'system_user_request_not_found'; end if;
  perform authority_connections.assert_owner_v1(p_company_id,false);
  return pg_catalog.to_jsonb(v_request);
end;
$function$;

create function authority_connections.latest_callback_operation_v1(p_company_id uuid)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare v_result jsonb;
begin
  perform authority_connections.assert_owner_v1(p_company_id,false);
  select pg_catalog.jsonb_build_object('operation',operation,'status',status,
    'result_code',result_code,'metadata',metadata) into v_result
  from authority_connections.authority_operations
  where operation='set_rf1086_systembruker_callback'
  order by created_at desc limit 1;
  return v_result;
end;
$function$;

create or replace function authority_connections.lock_verified_pilot_request_v1(p_request_id uuid,p_company_id uuid,p_owner_id uuid)
returns table(id uuid,external_ref text)
language plpgsql security definer set search_path='' as $function$
begin
  if authority_connections.verified_actor_v1() is null
    or not public.company_access_is_active_admin_v1()
    or not public.company_access_has_fresh_mfa_v1()
  then raise exception 'production_pilot_admin_required'; end if;
  return query select r.id,r.external_ref from authority_connections.system_user_requests r
  where r.id=p_request_id and r.company_id=p_company_id and r.initiating_owner_user_id=p_owner_id
    and r.obligation='aksjonaerregisteroppgaven' and r.status='accepted'
    and r.preflight_verified_at is not null
    and public.company_access_is_accepted_owner_subject_v1(r.company_id,r.initiating_owner_user_id)
  for update;
  if not public.company_access_is_active_admin_v1() or not public.company_access_has_fresh_mfa_v1()
  then raise exception 'production_pilot_admin_required'; end if;
end;
$function$;

create function authority_connections.read_support_requests_v1(p_company_id uuid,p_case_id uuid)
returns jsonb language plpgsql stable security definer set search_path='' as $function$
begin
  if not public.company_access_has_open_support_case_v1(p_case_id,p_company_id,'authority')
  then return '[]'::jsonb; end if;
  return coalesce((select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
    'id',s.id,'company_id',s.company_id,'obligation',s.obligation,
    'status',s.status,'failure_code',s.failure_code,'requested_at',s.requested_at,'updated_at',s.updated_at
  ) order by s.updated_at desc)
  from authority_connections.system_user_requests s where s.company_id=p_company_id),'[]'::jsonb);
end;
$function$;


create function authority_connections.read_rf_request_v1(p_request_id uuid,p_company_id uuid,p_actor_id uuid)
returns table(id uuid,company_id uuid,initiating_owner_user_id uuid,obligation text,
  external_ref text,status text,preflight_verified_at timestamptz)
language plpgsql security definer set search_path='' as $function$
begin
  perform authority_connections.assert_owner_v1(p_company_id,false);
  if p_actor_id is distinct from authority_connections.verified_actor_v1()
  then raise exception 'authority_owner_required'; end if;
  return query select r.id,r.company_id,r.initiating_owner_user_id,r.obligation,
    r.external_ref,r.status,r.preflight_verified_at
  from authority_connections.system_user_requests r
  where r.id=p_request_id and r.company_id=p_company_id and r.initiating_owner_user_id=p_actor_id;
  perform authority_connections.assert_owner_v1(p_company_id,false);
end;
$function$;

create function authority_connections.lock_rf_request_v1(p_request_id uuid,p_company_id uuid,p_actor_id uuid)
returns table(id uuid,company_id uuid,initiating_owner_user_id uuid,obligation text,
  external_ref text,status text,preflight_verified_at timestamptz)
language plpgsql security definer set search_path='' as $function$
begin
  perform authority_connections.assert_owner_v1(p_company_id,false);
  if p_actor_id is distinct from authority_connections.verified_actor_v1()
  then raise exception 'authority_owner_required'; end if;
  return query select r.id,r.company_id,r.initiating_owner_user_id,r.obligation,
    r.external_ref,r.status,r.preflight_verified_at
  from authority_connections.system_user_requests r
  where r.id=p_request_id and r.company_id=p_company_id and r.initiating_owner_user_id=p_actor_id for update;
  perform authority_connections.assert_owner_v1(p_company_id,false);
end;
$function$;

-- Only the named state workflow can execute this Billing-owned command. Its
-- function owner cannot activate/grant/rebind an entitlement or read AU storage.
grant usage on schema billing to billing_authority_state_owner;
grant select,update on billing.production_pilot_entitlements to billing_authority_state_owner;
create policy billing_authority_state_read on billing.production_pilot_entitlements
for select to billing_authority_state_owner
using (user_id=public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id));
create policy billing_authority_state_suspend on billing.production_pilot_entitlements
for update to billing_authority_state_owner
using (status='active' and user_id=public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id))
with check (status='suspended' and user_id=public.company_access_auth_uid_v1()
  and public.company_access_is_accepted_owner_v1(company_id));
create function billing.suspend_pilot_for_authority_failure_v1(p_request_id uuid,p_company_id uuid,p_owner_id uuid)
returns void language plpgsql security definer set search_path='' as $function$
declare v_request jsonb;
begin
  v_request:=authority_connections.lock_owned_request_v1(p_request_id,p_company_id);
  if v_request->>'status'<>'accepted'
    or v_request->>'initiating_owner_user_id' is distinct from p_owner_id::text
    or p_owner_id is distinct from public.company_access_auth_uid_v1()
  then raise exception 'system_user_request_relationship_mismatch'; end if;
  update billing.production_pilot_entitlements set status='suspended',updated_at=pg_catalog.now()
  where system_user_request_id=p_request_id and company_id=p_company_id and user_id=p_owner_id and status='active';
end;
$function$;
grant create on schema billing to billing_authority_state_owner;
alter function billing.suspend_pilot_for_authority_failure_v1(uuid,uuid,uuid) owner to billing_authority_state_owner;
revoke create on schema billing from billing_authority_state_owner;
revoke all on function billing.suspend_pilot_for_authority_failure_v1(uuid,uuid,uuid) from public,anon,authenticated,service_role;
grant execute on function billing.suspend_pilot_for_authority_failure_v1(uuid,uuid,uuid) to authority_connections_executor;
grant usage on schema billing to authority_connections_executor;

-- Rebind only the three existing compatibility lifecycle bodies. Their return
-- type OIDs already follow the moved physical table; no row or receipt is copied.
do $compatibility$
declare v_signature text; v_definition text;
begin
  foreach v_signature in array array[
    'public.begin_system_user_request(uuid,uuid,text)',
    'public.record_system_user_authority_state(uuid,uuid,uuid,text,text,text,text,uuid)',
    'public.verify_system_user_preflight(uuid,text)'
  ] loop
    v_definition:=pg_catalog.pg_get_functiondef(v_signature::regprocedure);
    v_definition:=pg_catalog.replace(v_definition,'public.system_user_requests','authority_connections.system_user_requests');
    v_definition:=pg_catalog.replace(v_definition,'public.authority_operations','authority_connections.authority_operations');
    execute v_definition;
  end loop;
end;
$compatibility$;

create view public.system_user_requests with(security_invoker=true)
as select * from authority_connections.system_user_requests;
create view public.authority_operations with(security_invoker=true)
as select * from authority_connections.authority_operations;
grant select on public.system_user_requests to authenticated,billing_store_owner,company_access_executor;
grant select on public.authority_operations to authenticated,service_role;
grant insert,update on public.authority_operations to service_role;

-- Existing callers receive only the purpose-specific projection once cut over;
-- the compatibility view/direct privileges are removed in the contract release.

do $function_owners$
declare v_function record;
begin
  for v_function in select p.oid::regprocedure as signature from pg_catalog.pg_proc p
    join pg_catalog.pg_namespace n on n.oid=p.pronamespace where n.nspname='authority_connections'
  loop
    execute pg_catalog.format('alter function %s owner to authority_connections_store_owner',v_function.signature);
    execute pg_catalog.format('revoke all on function %s from public,anon,authenticated,service_role',v_function.signature);
  end loop;
end;
$function_owners$;
grant execute on function authority_connections.verified_actor_v1(),
  authority_connections.assert_owner_v1(uuid,boolean),
  authority_connections.begin_request_v1(uuid,uuid,text),
  authority_connections.lock_owned_request_v1(uuid,uuid),
  authority_connections.record_authority_state_v1(uuid,uuid,uuid,text,text,text,text),
  authority_connections.verify_preflight_v1(uuid,uuid,text),
  authority_connections.latest_callback_operation_v1(uuid)
to authority_connections_executor;
grant execute on function authority_connections.lock_owned_request_v1(uuid,uuid) to billing_authority_state_owner;
grant execute on function authority_connections.lock_verified_pilot_request_v1(uuid,uuid,uuid) to billing_store_owner;
grant execute on function authority_connections.read_support_requests_v1(uuid,uuid) to company_access_executor;

-- Company Access keeps its exact opened-case authorization and response fields.
do $support_projection$
declare v_definition text;
begin
  v_definition:=pg_catalog.pg_get_functiondef('public.company_access_read_support_case(uuid)'::regprocedure);
  if pg_catalog.strpos(v_definition,$old$      'system_user_requests', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', s.id, 'company_id', s.company_id, 'obligation', s.obligation,
          'status', s.status, 'failure_code', s.failure_code,
          'requested_at', s.requested_at, 'updated_at', s.updated_at
        ) order by s.updated_at desc)
        from public.system_user_requests s where s.company_id = v_grant.company_id
      ), '[]'::jsonb),
$old$)=0
  then raise exception 'authority_support_projection_predecessor_mismatch'; end if;
  v_definition:=pg_catalog.replace(v_definition,$old$      'system_user_requests', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', s.id, 'company_id', s.company_id, 'obligation', s.obligation,
          'status', s.status, 'failure_code', s.failure_code,
          'requested_at', s.requested_at, 'updated_at', s.updated_at
        ) order by s.updated_at desc)
        from public.system_user_requests s where s.company_id = v_grant.company_id
      ), '[]'::jsonb),
$old$,$new$      'system_user_requests', authority_connections.read_support_requests_v1(v_grant.company_id,p_case_id),
$new$);
  execute v_definition;
end;
$support_projection$;


-- The old RPC function owner temporarily needs its former DML authority after
-- table ownership moves. Do not count migration-borrowed memberships as existing
-- privilege, and record only grants absent from the actual overlap principal.
do $unborrow_for_acl_check$
begin
  execute pg_catalog.format('revoke authority_connections_store_owner,authority_connections_executor,billing_authority_state_owner,billing_store_owner,company_access_executor from %I',current_user);
end;
$unborrow_for_acl_check$;
do $overlap_grant_inventory$
declare v_owner name; v_target record; v_exists boolean;
begin
  for v_owner in select distinct pg_catalog.pg_get_userbyid(p.proowner)::name
    from pg_catalog.pg_proc p where p.oid in (
      'public.begin_system_user_request(uuid,uuid,text)'::regprocedure,
      'public.record_system_user_authority_state(uuid,uuid,uuid,text,text,text,text,uuid)'::regprocedure,
      'public.verify_system_user_preflight(uuid,text)'::regprocedure)
  loop
    for v_target in select * from (values
      ('request_insert','table','authority_connections.system_user_requests'::regclass::oid,'INSERT',''),
      ('request_update','table','authority_connections.system_user_requests'::regclass::oid,'UPDATE',''),
      ('request_select','table','authority_connections.system_user_requests'::regclass::oid,'SELECT',''),
      ('pilot_status_update','column','billing.production_pilot_entitlements'::regclass::oid,'UPDATE','status'),
      ('pilot_updated_at_update','column','billing.production_pilot_entitlements'::regclass::oid,'UPDATE','updated_at'),
      ('pilot_binding_select','column','billing.production_pilot_entitlements'::regclass::oid,'SELECT','system_user_request_id'),
      ('pilot_status_select','column','billing.production_pilot_entitlements'::regclass::oid,'SELECT','status'),
      ('authority_schema_usage','schema','authority_connections'::regnamespace::oid,'USAGE',''),
      ('billing_schema_usage','schema','billing'::regnamespace::oid,'USAGE','')
    ) targets(target,kind,target_oid,privilege,column_name)
    loop
      v_exists:=case v_target.kind
        when 'table' then pg_catalog.has_table_privilege(v_owner,v_target.target_oid,v_target.privilege)
        when 'column' then pg_catalog.has_column_privilege(v_owner,v_target.target_oid,v_target.column_name,v_target.privilege)
        else pg_catalog.has_schema_privilege(v_owner,v_target.target_oid,v_target.privilege) end;
      if not v_exists then
        insert into backend_system.authority_connections_overlap_grants(target,grantee,target_oid)
        values(v_target.target,v_owner,v_target.target_oid) on conflict do nothing;
      end if;
    end loop;
  end loop;
end;
$overlap_grant_inventory$;
do $reborrow_for_acl_grants$
begin
  execute pg_catalog.format('grant authority_connections_store_owner,authority_connections_executor,billing_authority_state_owner,billing_store_owner,company_access_executor to %I',current_user);
end;
$reborrow_for_acl_grants$;
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

do $backend_membership$
begin
  if exists(select 1 from pg_catalog.pg_roles where rolname='talli_ledger_backend') then
    grant authority_connections_executor to talli_ledger_backend with inherit false,set true;
  end if;
end;
$backend_membership$;
do $cleanup$
begin
  execute pg_catalog.format('revoke authority_connections_store_owner, authority_connections_executor, billing_authority_state_owner, billing_store_owner, company_access_executor, ledger_store_owner from %I',current_user);
end;
$cleanup$;
commit;
