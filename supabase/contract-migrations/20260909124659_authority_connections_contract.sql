-- Final Authority Connections resource boundary after the generated web and
-- approved frozen RF compatibility cutovers. No historical rows are deleted.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';

-- Do not drop a compatibility surface while any frozen downstream function
-- still reads it. The exact RF lock projection must already be bound.
do $rf_prerequisite$
begin
  if exists(select 1 from pg_catalog.pg_proc p where p.prokind='f'
    and (p.prosrc like '%public.system_user_requests%' or p.prosrc like '%public.authority_operations%'))
    or not exists(select 1 from pg_catalog.pg_proc p where p.prokind='f'
      and p.prosrc like '%authority_connections.lock_rf_request_v1%')
  then raise exception 'authority_rf_resource_cutover_required'; end if;
end;
$rf_prerequisite$;
do $membership$
begin
  execute pg_catalog.format('grant authority_connections_store_owner,billing_store_owner,company_access_executor,ledger_store_owner to %I',current_user);
end;
$membership$;

drop function public.begin_system_user_request(uuid,uuid,text);
drop function public.record_system_user_authority_state(uuid,uuid,uuid,text,text,text,text,uuid);
drop function public.verify_system_user_preflight(uuid,text);
drop view public.system_user_requests;
drop view public.authority_operations;
drop policy system_user_requests_owner_read on authority_connections.system_user_requests;
drop policy billing_store_reads_system_user_requests on authority_connections.system_user_requests;
drop policy support_case_read_system_user_requests on authority_connections.system_user_requests;
drop policy "active admin operators read authority operations" on authority_connections.authority_operations;
revoke all on authority_connections.system_user_requests from authenticated,service_role,billing_store_owner,company_access_executor;
revoke all on authority_connections.authority_operations from authenticated,service_role;
revoke usage on schema authority_connections from authenticated,service_role;

-- Preserve every preexisting grant. Only this expansion's recorded additions
-- are removed, including the two exact Billing UPDATE columns.
do $overlap_grants$
declare v_row record; v_privilege text; v_column text; v_schema name;
begin
  for v_row in select * from backend_system.authority_connections_overlap_grants loop
    if v_row.target in ('authority_schema_usage','billing_schema_usage') then
      select nspname into strict v_schema from pg_catalog.pg_namespace where oid=v_row.target_oid;
      execute pg_catalog.format('revoke usage on schema %I from %I',v_schema,v_row.grantee);
    elsif v_row.target like 'request_%' then
      v_privilege:=case v_row.target when 'request_insert' then 'INSERT' when 'request_update' then 'UPDATE' else 'SELECT' end;
      execute pg_catalog.format('revoke %s on table %s from %I',v_privilege,v_row.target_oid::regclass,v_row.grantee);
    else
      v_privilege:=case when v_row.target in ('pilot_status_update','pilot_updated_at_update') then 'UPDATE' else 'SELECT' end;
      v_column:=case v_row.target when 'pilot_updated_at_update' then 'updated_at' when 'pilot_binding_select' then 'system_user_request_id' else 'status' end;
      execute pg_catalog.format('revoke %s (%I) on table %s from %I',v_privilege,v_column,v_row.target_oid::regclass,v_row.grantee);
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
