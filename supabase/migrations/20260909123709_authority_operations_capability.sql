-- Backend-only operator audit for the two fixed existing authority operations.
begin;
set local lock_timeout='5s';
do $membership$
begin
  execute pg_catalog.format('grant authority_connections_store_owner to %I',current_user);
end;
$membership$;

create policy authority_operations_admin_read on authority_connections.authority_operations
for select to authority_connections_store_owner
using (authority_connections.verified_actor_v1() is not null
  and public.company_access_is_active_admin_v1());
create policy authority_operations_admin_insert on authority_connections.authority_operations
for insert to authority_connections_store_owner
with check (actor_id=authority_connections.verified_actor_v1()
  and public.company_access_is_active_admin_v1() and public.company_access_has_fresh_mfa_v1());
create policy authority_operations_admin_update on authority_connections.authority_operations
for update to authority_connections_store_owner
using (actor_id=authority_connections.verified_actor_v1() and public.company_access_is_active_admin_v1())
with check (actor_id=authority_connections.verified_actor_v1() and public.company_access_is_active_admin_v1());
grant insert,update on authority_connections.authority_operations to authority_connections_store_owner;

create function authority_connections.assert_operator_v1(p_fresh boolean)
returns void language plpgsql security definer set search_path='' as $function$
begin
  if authority_connections.verified_actor_v1() is null or not public.company_access_is_active_admin_v1()
  then raise exception 'admin_operator_required'; end if;
  if p_fresh and not public.company_access_has_fresh_mfa_v1()
  then raise exception 'authority_step_up_required'; end if;
end;
$function$;

create function authority_connections.begin_operation_v1(
  p_id uuid,p_operation text,p_request_hash text,p_metadata jsonb
)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare v_row authority_connections.authority_operations%rowtype;
begin
  perform authority_connections.assert_operator_v1(true);
  if p_operation not in ('register_rf1086_system','set_rf1086_systembruker_callback')
    or p_request_hash is null or p_request_hash !~ '^[a-f0-9]{64}$'
    or p_metadata is null or pg_catalog.jsonb_typeof(p_metadata)<>'object'
    or p_metadata->>'systemId' is distinct from '930835978_talli'
  then raise exception 'authority_operation_invalid'; end if;
  if p_operation='register_rf1086_system' then
    if p_metadata - array['systemId','clientId','right'] <> '{}'::jsonb
      or p_metadata->>'right' is distinct from 'ske-innrapportering-aksjonaerregisteroppgave'
      or p_metadata->>'clientId' is null
      or p_metadata->>'clientId' !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
    then raise exception 'authority_operation_invalid'; end if;
  elsif p_metadata - array['systemId','callbackPath'] <> '{}'::jsonb
    or p_metadata->>'callbackPath' is distinct from '/auth/systembruker/confirm'
  then raise exception 'authority_operation_invalid'; end if;
  insert into authority_connections.authority_operations
    (id,operation,actor_id,status,request_hash,result_code,metadata)
  values(p_id,p_operation,authority_connections.verified_actor_v1(),'started',p_request_hash,'started',p_metadata)
  returning * into v_row;
  if not found then raise exception 'authority_audit_start_failed'; end if;
  perform authority_connections.assert_operator_v1(true);
  return pg_catalog.to_jsonb(v_row);
end;
$function$;

create function authority_connections.complete_operation_v1(
  p_id uuid,p_status text,p_result_code text,p_http_status integer
)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare v_row authority_connections.authority_operations%rowtype;
begin
  perform authority_connections.assert_operator_v1(false);
  select * into v_row from authority_connections.authority_operations
  where id=p_id and actor_id=authority_connections.verified_actor_v1() for update;
  if v_row.id is null then raise exception 'authority_audit_completion_failed'; end if;
  perform authority_connections.assert_operator_v1(false);
  if v_row.status<>'started' then raise exception 'authority_operation_conflict'; end if;
  if p_status is null or p_result_code is null or not (
    (p_status='succeeded' and p_result_code in ('created_and_verified','already_verified','callback_already_verified','callback_updated_and_verified'))
    or (p_status='conflict' and p_result_code='definition_conflict')
    or (p_status='failed' and p_result_code in ('authority_token_error','authority_network_error','authority_http_error',
      'authority_response_invalid','authority_verification_error','authority_operation_failed'))
  ) then raise exception 'authority_operation_invalid'; end if;
  update authority_connections.authority_operations
  set status=p_status,result_code=p_result_code,authority_http_status=p_http_status,completed_at=pg_catalog.now()
  where id=p_id and actor_id=authority_connections.verified_actor_v1() and status='started'
  returning * into v_row;
  if not found then raise exception 'authority_audit_completion_failed'; end if;
  perform authority_connections.assert_operator_v1(false);
  return pg_catalog.to_jsonb(v_row);
end;
$function$;

create function authority_connections.list_operations_v1(p_limit integer)
returns jsonb language plpgsql security definer set search_path='' as $function$
declare v_result jsonb;
begin
  perform authority_connections.assert_operator_v1(false);
  if p_limit is null or p_limit not between 1 and 10 then raise exception 'authority_operation_invalid'; end if;
  select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(row) order by row.created_at desc),'[]'::jsonb)
  into v_result from (select * from authority_connections.authority_operations order by created_at desc limit p_limit) row;
  perform authority_connections.assert_operator_v1(false);
  return v_result;
end;
$function$;

do $functions$
declare v_signature text;
begin
  foreach v_signature in array array[
    'authority_connections.assert_operator_v1(boolean)',
    'authority_connections.begin_operation_v1(uuid,text,text,jsonb)',
    'authority_connections.complete_operation_v1(uuid,text,text,integer)',
    'authority_connections.list_operations_v1(integer)'
  ] loop
    execute pg_catalog.format('alter function %s owner to authority_connections_store_owner',v_signature);
    execute pg_catalog.format('revoke all on function %s from public,anon,authenticated,service_role',v_signature);
    execute pg_catalog.format('grant execute on function %s to authority_connections_executor',v_signature);
  end loop;
end;
$functions$;
do $cleanup$
begin
  execute pg_catalog.format('revoke authority_connections_store_owner from %I',current_user);
end;
$cleanup$;
commit;
