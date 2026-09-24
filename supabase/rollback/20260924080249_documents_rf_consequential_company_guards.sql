-- Safe rollback: stop new guarded writes; preserve original evidence, ACLs and guard backstops.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_consequential_borrowed_roles(role_name name, prior jsonb) on commit drop;
do $borrow$
declare r name; p jsonb;
begin
 foreach r in array array['documents_store_owner','shareholder_register_filing_store_owner','company_archive_projection_executor'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
   insert into pg_temp.rf193_consequential_borrowed_roles values(r,p);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
set local role documents_store_owner;
create or replace function documents.lock_company_write_v1(p_company uuid,p_subject text) returns void
language plpgsql volatile security definer set search_path='' as $fn$
begin raise exception 'documents_guard_suspended'; end; $fn$;
reset role;
set local role shareholder_register_filing_store_owner;
create or replace function shareholder_register_filing.lock_company_write_v1(p_company uuid,p_review boolean default false) returns void
language plpgsql volatile security definer set search_path='' as $fn$
begin raise exception 'rf1086_guard_suspended'; end; $fn$;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_consequential_borrowed_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
