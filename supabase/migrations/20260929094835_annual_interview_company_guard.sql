-- Serialize existing annual interview facts with company-scoped RF admission.
-- No new writer, public facade, table grant, validation rule or ownership transfer.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table annual_interview_guard_authority(had_create boolean, had_usage boolean) on commit drop;
create temporary table annual_interview_guard_roles(role_name text primary key, prior jsonb) on commit drop;
do $borrow$
declare p jsonb; target text;
begin
 insert into pg_temp.annual_interview_guard_authority values(
  pg_catalog.has_schema_privilege('company_archive_projection_executor','backend_system','CREATE'),
  pg_catalog.has_schema_privilege('company_archive_projection_executor','backend_system','USAGE'));
 -- Function ownership and schema ownership are independent. Supabase's
 -- migration principal may administer either role without permanent SET access.
 for target in
  select 'company_archive_projection_executor'
  union select pg_catalog.pg_get_userbyid(nspowner) from pg_catalog.pg_namespace
   where nspname='backend_system'
    and not (select had_create and had_usage from pg_temp.annual_interview_guard_authority)
 loop
  if not pg_catalog.pg_has_role(current_user,target,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(target)
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.annual_interview_guard_roles values(target,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',target,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
do $create$
declare o text;
begin
 if not (select had_create and had_usage from pg_temp.annual_interview_guard_authority) then
  select pg_catalog.pg_get_userbyid(nspowner) into o from pg_catalog.pg_namespace where nspname='backend_system';
  execute pg_catalog.format('set local role %I',o);
  grant usage,create on schema backend_system to company_archive_projection_executor;
  reset role;
 end if;
end; $create$;
select pg_catalog.set_config('talli.annual_guard_migrator',current_user,true);
set local role company_archive_projection_executor;
create or replace function backend_system.guard_annual_interview_write_v1()
returns trigger language plpgsql security definer set search_path='' as $guard$
declare company uuid;
begin
 -- Infrastructure only: retain the caller's existing RLS, values and effects.
 -- Lock before any guarded RF reader may observe a committed interview change.
 for company in select distinct value from (
   select old.company_id as value where tg_op in ('UPDATE','DELETE')
   union all select new.company_id as value where tg_op in ('INSERT','UPDATE')
  ) changed where value is not null order by value
 loop perform public.company_archive_lock_company_v1(company); end loop;
 return coalesce(new,old);
end; $guard$;
revoke all on function backend_system.guard_annual_interview_write_v1()
 from public,anon,authenticated,service_role;
do $borrow_execute$
declare principal text:=pg_catalog.current_setting('talli.annual_guard_migrator');
begin
 perform pg_catalog.set_config('talli.annual_guard_borrowed_execute','false',true);
 if not pg_catalog.has_function_privilege(principal,'backend_system.guard_annual_interview_write_v1()','EXECUTE') then
  execute pg_catalog.format('grant execute on function backend_system.guard_annual_interview_write_v1() to %I',principal);
  perform pg_catalog.set_config('talli.annual_guard_borrowed_execute','true',true);
 end if;
end; $borrow_execute$;
reset role;
drop trigger if exists annual_interview_company_guard on public.annual_data;
create trigger annual_interview_company_guard before insert or update or delete on public.annual_data
 for each row execute function backend_system.guard_annual_interview_write_v1();
set local role company_archive_projection_executor;
do $return_execute$
begin
 if pg_catalog.current_setting('talli.annual_guard_borrowed_execute')='true' then
  execute pg_catalog.format('revoke execute on function backend_system.guard_annual_interview_write_v1() from %I',
    pg_catalog.current_setting('talli.annual_guard_migrator'));
 end if;
end; $return_execute$;
reset role;
do $restore$
declare r record; o text;
begin
 select * into r from pg_temp.annual_interview_guard_authority;
 if not (r.had_create and r.had_usage) then
  select pg_catalog.pg_get_userbyid(nspowner) into o from pg_catalog.pg_namespace where nspname='backend_system';
  execute pg_catalog.format('set local role %I',o);
  if not r.had_create then revoke create on schema backend_system from company_archive_projection_executor; end if;
  if not r.had_usage then revoke usage on schema backend_system from company_archive_projection_executor; end if;
  reset role;
 end if;
 for r in select * from pg_temp.annual_interview_guard_roles order by role_name loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
