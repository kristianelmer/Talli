-- Reverse contract only: the owned writer stays canonical and old writes stay denied.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:company-tax-filing:migration:v1',0));
create temporary table tax152_contract_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; previous jsonb; begin
 foreach r in array array['company_tax_filing_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') or not pg_catalog.pg_has_role(current_user,r,'USAGE') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into previous
   from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
    and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
   insert into tax152_contract_roles values(r,previous);
   execute pg_catalog.format('grant %I to %I with set true, inherit true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
select phase from backend_system.company_tax_return_migration_state where singleton for update;
do $phase$ begin
 if (select phase from backend_system.company_tax_return_migration_state where singleton) is distinct from 'contracted'
 then raise exception 'company_tax_return_contract_rollback_wrong_phase'; end if;
end; $phase$;
create function public.import_company_tax_tt02_evidence(p_payload jsonb) returns jsonb
language plpgsql security definer set search_path='' as $function$
begin raise exception 'company_tax_return_legacy_writer_retired'; end; $function$;
revoke all on function public.import_company_tax_tt02_evidence(jsonb) from public,anon,authenticated,service_role;
update backend_system.company_tax_return_migration_state set phase='cutover',changed_at=pg_catalog.now() where singleton;
do $restore$ declare r record; begin
 for r in select * from pg_temp.tax152_contract_roles loop
  if r.prior is null then execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  else execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
