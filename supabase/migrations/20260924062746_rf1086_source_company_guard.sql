-- Serialize RF source mutations with the existing company-wide owner guard.
-- This is only RF writer coverage, not a cross-owner production freshness lease.
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
-- The guard grants no table access. Browser/service roles retain no execute.
grant execute on function public.company_archive_lock_company_v1(uuid) to shareholder_register_filing_store_owner;
set local role shareholder_register_filing_store_owner;

create or replace function shareholder_register_filing.lock_year_source_v1(p_company uuid,p_year integer) returns void
language plpgsql security definer set search_path='' as $fn$
begin
 -- Reject unauthorized callers before allowing them to hold a company lock.
 perform shareholder_register_filing.assert_preparation_access_v1(p_company);
 if p_year is null or p_year not between 2000 and 2100 then raise exception 'rf1086_invalid_input'; end if;
 -- Company first, then RF year, then document/head row locks. READ COMMITTED
 -- callers see any owner/eligibility change committed while this lock waited.
 perform public.company_archive_lock_company_v1(p_company);
 perform shareholder_register_filing.assert_preparation_access_v1(p_company);
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('rf1086:year-source:'||p_company::text||':'||p_year::text,0));
 if not public.company_access_company_year_allows_consequential_v1(p_company,p_year)
 then raise exception 'rf1086_company_year_not_admitted'; end if;
end; $fn$;

-- Backstop every permitted row mutation, including empty-year inserts. The
-- public append commands acquire this guard before local locks; a trigger by
-- itself would be too late to establish that lock order for those commands.
create or replace function shareholder_register_filing.lock_source_company_write_v1() returns trigger
language plpgsql security invoker set search_path='' as $fn$
declare company uuid;
begin
 for company in
  select distinct value from (
   select old.company_id as value where tg_op in ('UPDATE','DELETE')
   union all select new.company_id as value where tg_op in ('INSERT','UPDATE')
  ) changed where value is not null order by value
 loop
  perform public.company_archive_lock_company_v1(company);
 end loop;
 return coalesce(new,old);
end; $fn$;
revoke all on function shareholder_register_filing.lock_source_company_write_v1() from public,anon,authenticated,service_role,shareholder_register_filing_executor;
do $triggers$
declare name text;
begin
 foreach name in array array['year_source_versions','year_source_heads','register_observations','source_previews'] loop
  execute pg_catalog.format('drop trigger if exists source_company_guard on shareholder_register_filing.%I',name);
  execute pg_catalog.format('create trigger source_company_guard before insert or update or delete on shareholder_register_filing.%I for each row execute function shareholder_register_filing.lock_source_company_write_v1()',name);
 end loop;
end; $triggers$;

revoke all on function shareholder_register_filing.lock_year_source_v1(uuid,integer) from public,anon,authenticated,service_role;
-- Also resumes the exact commands suspended by this migration's safe rollback.
grant execute on function shareholder_register_filing.lock_year_source_v1(uuid,integer),
 shareholder_register_filing.append_year_source_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz),
 shareholder_register_filing.append_register_observation_v1(uuid,uuid,integer,integer,text,text,text,uuid,text,text,text,timestamptz),
 shareholder_register_filing.append_source_preview_v1(uuid,uuid,integer,uuid,text,text,text,text)
 to shareholder_register_filing_executor;
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
