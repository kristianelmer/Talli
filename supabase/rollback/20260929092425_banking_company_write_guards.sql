-- Suspend writer APIs while retaining facts, wrappers and row guard coverage.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table banking_guard_authority(prior jsonb, borrowed boolean, had_create boolean) on commit drop;
do $borrow$
declare p jsonb; b boolean:=not pg_catalog.pg_has_role(current_user,'banking_store_owner','SET');
begin
 if b then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
  from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole('banking_store_owner')
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  execute pg_catalog.format('grant banking_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
 insert into pg_temp.banking_guard_authority values(p,b,pg_catalog.has_schema_privilege('banking_store_owner','banking','CREATE'));
end; $borrow$;
do $create$
declare o text;
begin
 if not (select had_create from pg_temp.banking_guard_authority) then
  select pg_catalog.pg_get_userbyid(nspowner) into o from pg_catalog.pg_namespace where nspname='banking';
  execute pg_catalog.format('set local role %I',o);
  grant create on schema banking to banking_store_owner;
  reset role;
 end if;
end; $create$;
set local role banking_store_owner;
create or replace function banking.acquire_company_write_guard_v1(p_company uuid,p_subject text)
returns void language plpgsql security definer set search_path='' as $guard$
begin raise exception 'banking_company_guard_rollback'; end; $guard$;
reset role;
do $restore$
declare r record; o text;
begin
 select * into r from pg_temp.banking_guard_authority;
 if not r.had_create then
  select pg_catalog.pg_get_userbyid(nspowner) into o from pg_catalog.pg_namespace where nspname='banking';
  execute pg_catalog.format('set local role %I',o);
  revoke create on schema banking from banking_store_owner;
  reset role;
 end if;
 if r.borrowed then
  execute pg_catalog.format('revoke banking_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant banking_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end if;
end; $restore$;
commit;
