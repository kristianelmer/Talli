-- Safe rollback suspends the new consequential admission contract. All existing
-- Company Access writes retain their guard ordering and trigger backstops, all
-- original evidence remains untouched, and no unsafe old writer is reinstated.
-- Keep the existing narrow company-lock helper grant; it exposes no table data.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table ca193_borrowed_role(prior jsonb) on commit drop;
do $borrow$
declare prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'company_access_executor','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into prior from pg_catalog.pg_auth_members m
  where m.roleid=(select oid from pg_catalog.pg_roles where rolname='company_access_executor')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.ca193_borrowed_role values(prior);
  execute pg_catalog.format('grant company_access_executor to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role company_access_executor;
revoke execute on function public.company_access_read_rf_admission_v1(uuid,integer,text)
 from shareholder_register_filing_store_owner,shareholder_register_filing_executor;
reset role;
do $restore$
declare item record;
begin
 for item in select * from pg_temp.ca193_borrowed_role loop
  execute pg_catalog.format('revoke company_access_executor from %I granted by %I',current_user,current_user);
  if item.prior is not null then
   execute pg_catalog.format('grant company_access_executor to %I with admin %s, inherit %s, set %s granted by %I',current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
