-- Safe rollback suspends writer APIs; immutable rows and backstop guards remain.
-- Company guard first for Governance and Ledger source writers.
-- Preserve routine identity/ACLs and original bodies, including topology-specific
-- implementations. Admission readers still need their own exact evidence checks.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_writer_borrowed_roles(role_name text, prior jsonb) on commit drop;
do $borrow$
declare name text; prior jsonb;
begin
 foreach name in array array['corporate_governance_store_owner','ledger_store_owner','ledger_workflow_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into prior from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name)
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.rf193_writer_borrowed_roles values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
create temporary table rf193_writer_schema_create(schema_name text,role_name text) on commit drop;
do $create_privileges$
declare item record; schema_owner text;
begin
 for item in select * from (values
  ('corporate_governance','corporate_governance_store_owner'),
  ('ledger','ledger_store_owner'),
  ('backend_system','ledger_store_owner'),
  ('backend_system','ledger_workflow_store_owner')
 ) required(schema_name,role_name) loop
  if not pg_catalog.has_schema_privilege(item.role_name,item.schema_name,'CREATE') then
   insert into pg_temp.rf193_writer_schema_create values(item.schema_name,item.role_name);
   select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname=item.schema_name;
   execute pg_catalog.format('set local role %I',schema_owner);
   execute pg_catalog.format('grant create on schema %I to %I',item.schema_name,item.role_name);
   reset role;
  end if;
 end loop;
end; $create_privileges$;
grant execute on function public.company_archive_lock_company_v1(uuid)
 to corporate_governance_store_owner,ledger_store_owner,ledger_workflow_store_owner;

set local role corporate_governance_store_owner;
create or replace function corporate_governance.acquire_company_write_guard_v1(p_company uuid,p_subject text)
returns void language plpgsql security definer set search_path='' as $guard$
begin raise exception 'corporate_governance_company_guard_rollback'; end; $guard$;
reset role;

set local role ledger_store_owner;
create or replace function ledger.acquire_company_write_guard_v1(p_company uuid,p_subject text)
returns void language plpgsql security definer set search_path='' as $guard$
begin raise exception 'ledger_company_guard_rollback'; end; $guard$;
reset role;

reset role;
do $restore_create$
declare item record; schema_owner text;
begin
 for item in select * from pg_temp.rf193_writer_schema_create loop
  select pg_catalog.pg_get_userbyid(nspowner) into schema_owner from pg_catalog.pg_namespace where nspname=item.schema_name;
  execute pg_catalog.format('set local role %I',schema_owner);
  execute pg_catalog.format('revoke create on schema %I from %I',item.schema_name,item.role_name);
  reset role;
 end loop;
end; $restore_create$;
do $restore$
declare item record;
begin
 for item in select * from pg_temp.rf193_writer_borrowed_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s, inherit %s, set %s granted by %I',item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
