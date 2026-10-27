-- Historical company archives keep their existing year range; delivery remains2025-only.
begin;
set local search_path='';
set local lock_timeout='5s';
set local statement_timeout='120s';
select pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('talli:annual-accounts-filing:migration:v1',0));
create temporary table accounts_company_archive_borrowed_role(prior jsonb) on commit drop;
do $borrow$ declare p jsonb; begin
 if not pg_catalog.pg_has_role(current_user,'annual_accounts_filing_store_owner','SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into p
   from pg_catalog.pg_auth_members m where m.roleid='annual_accounts_filing_store_owner'::regrole
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
  insert into pg_temp.accounts_company_archive_borrowed_role values(p);
  execute pg_catalog.format('grant annual_accounts_filing_store_owner to %I with set true granted by %I',current_user,current_user);
 end if;
end; $borrow$;
do $predecessor$ begin
 if pg_catalog.to_regprocedure('annual_accounts_filing.lock_delivery_archive_v1(uuid,integer,text)') is null
  or not pg_catalog.has_function_privilege('annual_accounts_filing_store_owner','public.company_archive_lock_company_v1(uuid)','EXECUTE') then
  raise exception 'annual_accounts_company_archive_predecessor_required';
 end if;
end; $predecessor$;
set local role annual_accounts_filing_store_owner;
create function annual_accounts_filing.lock_company_year_archive_v1(p_company uuid,p_year integer,p_subject text) returns void
language plpgsql volatile security definer set search_path='' as $function$
begin
 perform annual_accounts_filing.assert_filing_available_v1(p_subject);
 if pg_catalog.current_setting('transaction_isolation')<>'read committed' then raise exception 'annual_accounts_unavailable'; end if;
 if p_year is null or p_year not between 2000 and 2100 then raise exception 'annual_accounts_invalid_input'; end if;
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'annual_accounts_not_found'; end if;
 perform public.company_archive_lock_company_v1(p_company);
 perform annual_accounts_filing.assert_filing_available_v1(p_subject);
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'annual_accounts_not_found'; end if;
 if public.company_access_has_fresh_mfa_v1() is distinct from true then raise exception 'annual_accounts_mfa_required'; end if;
end; $function$;
revoke all on function annual_accounts_filing.lock_company_year_archive_v1(uuid,integer,text) from public,anon,authenticated,service_role;
grant execute on function annual_accounts_filing.lock_company_year_archive_v1(uuid,integer,text) to annual_accounts_filing_workflow_executor;
reset role;
do $restore$ declare r record; begin
 for r in select * from pg_temp.accounts_company_archive_borrowed_role loop
  execute pg_catalog.format('revoke annual_accounts_filing_store_owner from %I granted by %I',current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant annual_accounts_filing_store_owner to %I with admin %s,inherit %s,set %s granted by %I',current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
