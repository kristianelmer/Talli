-- Close new Accounts correction admissions and creation; retain all original readers and in-flight results.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
create temporary table accounts_event_rollback_role(prior jsonb) on commit drop;
do $borrow$ declare p jsonb; begin
 if not pg_catalog.pg_has_role(current_user,'annual_accounts_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
  from pg_catalog.pg_auth_members m where m.roleid='annual_accounts_filing_store_owner'::regrole
   and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.accounts_event_rollback_role values(p);
  execute pg_catalog.format('grant annual_accounts_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
set local role annual_accounts_filing_store_owner;
create or replace function annual_accounts_filing.delivery_corrections_enabled_v1() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$begin return false; end;$function$;
create or replace function annual_accounts_filing.delivery_operations_enabled_v1() returns boolean
language plpgsql volatile security invoker set search_path='' as $function$begin return false; end;$function$;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.accounts_event_rollback_role loop
  execute pg_catalog.format('revoke annual_accounts_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant annual_accounts_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',
   current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
