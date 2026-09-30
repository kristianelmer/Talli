-- Removes only the observation API; no bank facts, policies or grants change.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table banking_projection_authority(prior jsonb, borrowed boolean) on commit drop;
do $borrow$
declare p jsonb; b boolean:=not pg_catalog.pg_has_role(current_user,'banking_store_owner','SET');
begin
 if b then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
  from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole('banking_store_owner')
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  execute pg_catalog.format('grant banking_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
 insert into pg_temp.banking_projection_authority values(p,b);
end; $borrow$;
set local role banking_store_owner;
drop function if exists banking.read_year_reconciliation_v1(uuid,integer,text);
reset role;
do $restore$
declare r record;
begin
 select * into r from pg_temp.banking_projection_authority;
 if r.borrowed then
  execute pg_catalog.format('revoke banking_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant banking_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end if;
end; $restore$;
commit;
