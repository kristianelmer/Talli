-- Suspend interview changes while preserving facts and the installed guard.
-- Reapply the migration to resume existing writers. Reads stay available.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table annual_interview_guard_authority(prior jsonb, borrowed boolean, had_create boolean, had_usage boolean) on commit drop;
do $borrow$
declare p jsonb; b boolean:=not pg_catalog.pg_has_role(current_user,'company_archive_projection_executor','SET');
begin
 if b then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
  from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole('company_archive_projection_executor')
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  execute pg_catalog.format('grant company_archive_projection_executor to %I with set true granted by %I',current_user,current_user);
 end if;
 insert into pg_temp.annual_interview_guard_authority values(p,b,pg_catalog.has_schema_privilege('company_archive_projection_executor','backend_system','CREATE'),pg_catalog.has_schema_privilege('company_archive_projection_executor','backend_system','USAGE'));
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
set local role company_archive_projection_executor;
create or replace function backend_system.guard_annual_interview_write_v1()
returns trigger language plpgsql security definer set search_path='' as $guard$
begin raise exception 'annual_interview_company_guard_rollback'; end; $guard$;
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
 if r.borrowed then
  execute pg_catalog.format('revoke company_archive_projection_executor from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant company_archive_projection_executor to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end if;
end; $restore$;
commit;
