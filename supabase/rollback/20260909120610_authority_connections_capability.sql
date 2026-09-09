-- Reverse only this expand after the web/contract rollback. Preserve all rows,
-- original type OIDs, evidence and the already-contracted Billing topology.
begin;
do $rf_order$
begin
  if exists(select 1 from pg_catalog.pg_proc p where p.prokind='f'
    and p.oid='public.begin_production_filing(uuid)'::regprocedure
    and p.prosrc like '%authority_connections.lock_rf_request_v1%')
  then raise exception 'authority_rf_cutover_rollback_required'; end if;
end;
$rf_order$;
set local lock_timeout='5s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:authority-connections:capability:v1',0));
do $membership$
begin
  execute pg_catalog.format('grant authority_connections_store_owner, authority_connections_executor, billing_authority_state_owner, billing_store_owner, company_access_executor to %I',current_user);
end;
$membership$;

do $support_projection$
declare v_definition text;
begin
  v_definition:=pg_catalog.pg_get_functiondef('public.company_access_read_support_case(uuid)'::regprocedure);
  v_definition:=pg_catalog.replace(v_definition,$new$      'system_user_requests', authority_connections.read_support_requests_v1(v_grant.company_id,p_case_id),
$new$,$old$      'system_user_requests', coalesce((
        select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
          'id', s.id, 'company_id', s.company_id, 'obligation', s.obligation,
          'status', s.status, 'failure_code', s.failure_code,
          'requested_at', s.requested_at, 'updated_at', s.updated_at
        ) order by s.updated_at desc)
        from public.system_user_requests s where s.company_id = v_grant.company_id
      ), '[]'::jsonb),
$old$);
  execute v_definition;
end;
$support_projection$;

drop function billing.suspend_pilot_for_authority_failure_v1(uuid,uuid,uuid);
drop policy billing_authority_state_read on billing.production_pilot_entitlements;
drop policy billing_authority_state_suspend on billing.production_pilot_entitlements;
revoke select,update on billing.production_pilot_entitlements from billing_authority_state_owner;
revoke usage on schema billing from billing_authority_state_owner,authority_connections_executor;

drop policy authority_requests_owner_read on authority_connections.system_user_requests;
drop policy authority_requests_owner_write on authority_connections.system_user_requests;
drop policy authority_requests_support_projection_read on authority_connections.system_user_requests;
drop policy authority_operations_callback_read on authority_connections.authority_operations;
drop function authority_connections.read_rf_request_v1(uuid,uuid,uuid);
drop function authority_connections.lock_rf_request_v1(uuid,uuid,uuid);
drop function authority_connections.latest_callback_operation_v1(uuid);
drop function authority_connections.begin_request_v1(uuid,uuid,text);
drop function authority_connections.record_authority_state_v1(uuid,uuid,uuid,text,text,text,text);
drop function authority_connections.verify_preflight_v1(uuid,uuid,text);
drop function authority_connections.lock_owned_request_v1(uuid,uuid);
drop function authority_connections.read_support_requests_v1(uuid,uuid);
drop function authority_connections.assert_owner_v1(uuid,boolean);

-- Drop compatibility views before moving the original physical relations back.
drop view public.system_user_requests;
drop view public.authority_operations;
revoke all on authority_connections.system_user_requests from authority_connections_executor,authority_connections_store_owner;
revoke all on authority_connections.authority_operations from authority_connections_store_owner;
alter table authority_connections.system_user_requests owner to current_user;
alter table authority_connections.authority_operations owner to current_user;
alter table authority_connections.system_user_requests set schema public;
alter table authority_connections.authority_operations set schema public;
alter table public.system_user_requests no force row level security;
alter table public.authority_operations no force row level security;
grant all on public.system_user_requests,public.authority_operations to current_user;

do $compatibility$
declare v_signature text; v_definition text;
begin
  foreach v_signature in array array[
    'public.begin_system_user_request(uuid,uuid,text)',
    'public.record_system_user_authority_state(uuid,uuid,uuid,text,text,text,text,uuid)',
    'public.verify_system_user_preflight(uuid,text)'
  ] loop
    v_definition:=pg_catalog.pg_get_functiondef(v_signature::regprocedure);
    v_definition:=pg_catalog.replace(v_definition,'authority_connections.system_user_requests','public.system_user_requests');
    v_definition:=pg_catalog.replace(v_definition,'authority_connections.authority_operations','public.authority_operations');
    execute v_definition;
  end loop;
end;
$compatibility$;

grant select on public.system_user_requests to authenticated,billing_store_owner,company_access_executor;
grant select on public.authority_operations to authenticated,service_role;
grant insert,update on public.authority_operations to service_role;
revoke execute on function public.company_access_auth_uid_v1(),
  public.company_access_auth_jwt_v1(),public.company_access_is_accepted_owner_v1(uuid),
  public.company_access_is_accepted_owner_subject_v1(uuid,uuid),
  public.company_access_is_active_admin_v1(),public.company_access_has_fresh_mfa_v1(),
  public.company_access_read_company_identity_v1(uuid,text),
  public.company_access_has_open_support_case_v1(uuid,uuid,text),
  public.company_access_current_support_case_id_v1()
from authority_connections_store_owner,authority_connections_executor,billing_authority_state_owner;
-- One read/lock contract survives to support the already deployed Billing
-- consumer while its predecessor physical table is restored. It cannot write
-- request state; owner lifecycle/executor functions above are absent.
do $projection_survivor$
declare v_definition text;
begin
  v_definition:=pg_catalog.pg_get_functiondef('authority_connections.lock_verified_pilot_request_v1(uuid,uuid,uuid)'::regprocedure);
  v_definition:=pg_catalog.replace(v_definition,'authority_connections.system_user_requests','public.system_user_requests');
  execute v_definition;
end;
$projection_survivor$;
grant select,update on public.system_user_requests to authority_connections_store_owner;
grant execute on function public.company_access_auth_uid_v1(),
  public.company_access_is_active_admin_v1(),public.company_access_has_fresh_mfa_v1(),
  public.company_access_is_accepted_owner_subject_v1(uuid,uuid)
to authority_connections_store_owner;
revoke usage on schema authority_connections from authenticated,service_role,
  company_access_executor,authority_connections_executor,billing_authority_state_owner;
grant usage on schema authority_connections to billing_store_owner;

do $backend_membership$
begin
  if exists(select 1 from pg_catalog.pg_roles where rolname='talli_ledger_backend') then
    revoke authority_connections_executor from talli_ledger_backend;
  end if;
end;
$backend_membership$;
do $cleanup$
begin
  execute pg_catalog.format('revoke authority_connections_store_owner,authority_connections_executor,billing_authority_state_owner,billing_store_owner,company_access_executor from %I',current_user);
end;
$cleanup$;
commit;
