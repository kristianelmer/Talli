-- Exact owning-reader admission for Corporate annual-close facts and Accounts.
-- No table access, reader semantics, browser authority or business writer changes.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table corporate_accounts_read_authority(role_name text, prior jsonb) on commit drop;
do $borrow$
declare p jsonb; r text;
begin
 foreach r in array array['ledger_workflow_store_owner','ledger_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(r)
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.corporate_accounts_read_authority values(r,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
-- Existing schema usage and actor/RLS guards remain prerequisites.
do $predecessor$ begin
 if not pg_catalog.has_schema_privilege('corporate_governance_workflow_executor','ledger','USAGE')
  or not pg_catalog.has_schema_privilege('corporate_governance_workflow_executor','backend_system','USAGE')
  or (select proowner from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure('ledger.list_entries(uuid[],text,integer,text)'))
   is distinct from 'ledger_store_owner'::regrole
  or (select proowner from pg_catalog.pg_proc where oid=pg_catalog.to_regprocedure('backend_system.read_new_year_opening_snapshots_v1(uuid[],text,integer,text,integer)'))
   is distinct from 'ledger_workflow_store_owner'::regrole then raise exception 'corporate_accounts_reader_predecessor_required'; end if;
end; $predecessor$;
set local role ledger_store_owner;
revoke execute on function ledger.list_entries(uuid[],text,integer,text) from corporate_governance_workflow_executor;
reset role;
set local role ledger_workflow_store_owner;
revoke execute on function backend_system.read_new_year_opening_snapshots_v1(uuid[],text,integer,text,integer) from corporate_governance_workflow_executor;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.corporate_accounts_read_authority loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
