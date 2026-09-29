-- Exact read-only RF access to the unchanged Documents metadata query.
-- No table access, reader semantics, browser authority or business writer changes.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf_annual_documents_authority(prior jsonb) on commit drop;
do $borrow$
declare p jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'documents_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
  from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole('documents_store_owner')
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.rf_annual_documents_authority values(p);
  execute pg_catalog.format('grant documents_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role documents_store_owner;
revoke execute on function documents.list_documents_v1(uuid[],text) from shareholder_register_filing_executor;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf_annual_documents_authority loop
  execute pg_catalog.format('revoke documents_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant documents_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
