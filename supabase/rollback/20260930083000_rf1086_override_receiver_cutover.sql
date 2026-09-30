-- Suspend new RF approval/dispatch effects without reopening the retired
-- shared table. Retain historical approvals, claims and original evidence.
-- Replay the forward migration to restore the current owned override query.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf_override_receiver_roles(role_name text primary key,prior jsonb) on commit drop;
create temporary table rf_override_receiver_schema(owner_name text,had_create boolean,had_usage boolean) on commit drop;
do $borrow$
declare target text; p jsonb; receiver text;
begin
 -- Discover ownership without requiring the migrator to have schema USAGE
 -- before borrowing it. regprocedure resolution would require that privilege.
 select pg_catalog.pg_get_userbyid(p.proowner) into receiver from pg_catalog.pg_proc p
 join pg_catalog.pg_namespace n on n.oid=p.pronamespace
 where n.nspname='backend_system' and p.proname='rf1086_stored_release_inputs_v1'
  and p.pronargs=3 and p.proargtypes[0]='uuid'::regtype
  and p.proargtypes[1]='integer'::regtype and p.proargtypes[2]='text'::regtype;
 if receiver is null then raise exception 'rf1086_annual_receiver_owner_missing'; end if;
 insert into pg_temp.rf_override_receiver_schema values(receiver,
  pg_catalog.has_schema_privilege(receiver,'backend_system','CREATE'),
  pg_catalog.has_schema_privilege(receiver,'backend_system','USAGE'));
 for target in select 'shareholder_register_filing_store_owner' union select receiver
  union select pg_catalog.pg_get_userbyid(nspowner) from pg_catalog.pg_namespace
   where nspname='backend_system' and not(select had_create and had_usage from pg_temp.rf_override_receiver_schema)
 loop
  if not pg_catalog.pg_has_role(current_user,target,'SET') then
   select pg_catalog.jsonb_build_object('admin',admin_option,'inherit',inherit_option,'set',set_option) into p
   from pg_catalog.pg_auth_members where roleid=pg_catalog.to_regrole(target)
    and member=pg_catalog.to_regrole(current_user) and grantor=member;
   insert into pg_temp.rf_override_receiver_roles values(target,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',target,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
do $receiver$
declare r record; schema_owner text;
begin
 select * into r from pg_temp.rf_override_receiver_schema;
 if not(r.had_create and r.had_usage) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='backend_system';
  execute pg_catalog.format('set local role %I',schema_owner);
  execute pg_catalog.format('grant usage,create on schema backend_system to %I',r.owner_name);
  reset role;
 end if;
 execute pg_catalog.format('set local role %I',r.owner_name);
 execute $sql$create or replace function backend_system.rf1086_other_overrides_ready_v1(p_company uuid,p_year integer)
 returns boolean language sql stable security definer set search_path='' as $body$
  select false;
 $body$;$sql$;
 revoke all on function backend_system.rf1086_other_overrides_ready_v1(uuid,integer) from public,anon,authenticated,service_role,shareholder_register_filing_executor;
 grant execute on function backend_system.rf1086_other_overrides_ready_v1(uuid,integer) to shareholder_register_filing_store_owner;
 reset role;
end; $receiver$;
do $restore$
declare r record; schema_owner text;
begin
 select * into r from pg_temp.rf_override_receiver_schema;
 if not(r.had_create and r.had_usage) then
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname='backend_system';
  execute pg_catalog.format('set local role %I',schema_owner);
  if not r.had_create then execute pg_catalog.format('revoke create on schema backend_system from %I',r.owner_name); end if;
  if not r.had_usage then execute pg_catalog.format('revoke usage on schema backend_system from %I',r.owner_name); end if;
  reset role;
 end if;
 for r in select * from pg_temp.rf_override_receiver_roles order by role_name loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
