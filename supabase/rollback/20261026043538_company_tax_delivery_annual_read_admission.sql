-- Exact read-only Tax delivery access to the unchanged frozen history API.
-- No table access, reader semantics, browser authority or business writer changes.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table tax_delivery_annual_reader_authority(role_name text, prior jsonb) on commit drop;
do $borrow$
declare p jsonb; r text;
begin
 foreach r in array array['backend_system_annual_data_reader','ledger_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(r)
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.tax_delivery_annual_reader_authority values(r,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
set local role ledger_store_owner;
revoke usage on schema backend_system from company_tax_filing_workflow_executor;
reset role;
set local role backend_system_annual_data_reader;
revoke execute on function backend_system.list_annual_data_legacy_v1(uuid,integer,text) from company_tax_filing_workflow_executor;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.tax_delivery_annual_reader_authority loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
