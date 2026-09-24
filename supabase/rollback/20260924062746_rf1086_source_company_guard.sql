-- Safe rollback suspends source writes; it never reinstates an unguarded writer.
-- Retain original data, read access, immutable triggers and the company guard.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_source_guard_borrowed_role(prior jsonb) on commit drop;
do $borrow$
declare v_prior jsonb;
begin
 if not pg_catalog.pg_has_role(current_user,'shareholder_register_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
  into v_prior from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname='shareholder_register_filing_store_owner')
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
  insert into pg_temp.rf193_source_guard_borrowed_role values(v_prior);
  execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role shareholder_register_filing_store_owner;
revoke execute on function shareholder_register_filing.lock_year_source_v1(uuid,integer),
 shareholder_register_filing.append_year_source_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz),
 shareholder_register_filing.append_register_observation_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz),
 shareholder_register_filing.append_source_preview_v1(uuid,uuid,integer,uuid,text,text,text,text)
 from shareholder_register_filing_executor;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_source_guard_borrowed_role loop
  execute pg_catalog.format('revoke shareholder_register_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant shareholder_register_filing_store_owner to %I with admin %s, inherit %s, set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
