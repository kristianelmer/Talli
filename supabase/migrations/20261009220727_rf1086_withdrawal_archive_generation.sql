-- Register only RF-owned withdrawal writes with the existing archive protocol.
-- This invalidates older generations, not old-format exports begun afterwards.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_withdrawal_generation_roles(role_name text,prior jsonb) on commit drop;
do $borrow$
declare r text; prior jsonb;
begin
 foreach r in array array['company_archive_projection_executor','shareholder_register_filing_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into prior from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
   insert into pg_temp.rf193_withdrawal_generation_roles values(r,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
create temporary table rf193_withdrawal_generation_grant on commit drop as
 select pg_catalog.has_function_privilege('shareholder_register_filing_store_owner',
  'public.company_archive_track_source_write_v1()','EXECUTE') had;
grant select on pg_temp.rf193_withdrawal_generation_grant to company_archive_projection_executor;
create temporary table rf193_withdrawal_generation_scopes(
 company_id uuid,income_year integer,primary key(company_id,income_year)) on commit drop;
grant select,insert on pg_temp.rf193_withdrawal_generation_scopes to shareholder_register_filing_store_owner;
grant select on pg_temp.rf193_withdrawal_generation_scopes to company_archive_projection_executor;
set local role company_archive_projection_executor;
do $grant$
begin
 if not (select had from pg_temp.rf193_withdrawal_generation_grant) then
  grant execute on function public.company_archive_track_source_write_v1() to shareholder_register_filing_store_owner;
 end if;
end; $grant$;
reset role;
set local role shareholder_register_filing_store_owner;
-- Serialize activation against row writes. A concurrent company-first writer
-- may require retrying this bounded migration; no partial activation can commit.
lock table shareholder_register_filing.register_observation_withdrawals in access exclusive mode;
do $register$
declare forced boolean; protected boolean; installed boolean;
begin
 select relforcerowsecurity,relkind='r' and relrowsecurity and relowner=current_user::regrole
 into forced,protected from pg_catalog.pg_class
 where oid='shareholder_register_filing.register_observation_withdrawals'::regclass;
 if protected is distinct from true then raise exception 'rf1086_archive_generation_owner_precondition'; end if;
 -- AFTER tracking preserves no-op INSERT replay. The existing BEFORE guard
 -- must already take the company lock before the row can change.
 if not exists(select 1 from pg_catalog.pg_trigger
  where tgrelid='shareholder_register_filing.register_observation_withdrawals'::regclass
   and tgname='source_company_guard' and tgenabled='O' and tgtype=31
   and tgqual is null and not tgisinternal and tgconstraint=0 and not tgdeferrable and not tginitdeferred
   and tgoldtable is null and tgnewtable is null and tgnargs=0
   and tgfoid='shareholder_register_filing.lock_source_company_write_v1()'::regprocedure)
 then raise exception 'rf1086_archive_generation_company_guard_required'; end if;
 select exists(select 1 from pg_catalog.pg_trigger
  where tgrelid='shareholder_register_filing.register_observation_withdrawals'::regclass
   and tgname='company_archive_track_rf_withdrawal' and tgenabled='O' and tgtype=29
   and tgqual is null and not tgisinternal and tgconstraint=0 and not tgdeferrable and not tginitdeferred
   and tgoldtable is null and tgnewtable is null and tgnargs=2
   and tgfoid='public.company_archive_track_source_write_v1()'::regprocedure
   and pg_catalog.encode(tgargs,'escape')=E'year\\000company_id\\000') into installed;
 if not installed then
  -- Older receipts may predate retained withdrawals. Invalidate each affected
  -- year once; do not change historical receipts, source rows or other years.
  if forced then alter table shareholder_register_filing.register_observation_withdrawals no force row level security; end if;
  insert into pg_temp.rf193_withdrawal_generation_scopes
   select distinct company_id,income_year from shareholder_register_filing.register_observation_withdrawals;
  if forced then alter table shareholder_register_filing.register_observation_withdrawals force row level security; end if;
 end if;
 drop trigger if exists company_archive_track_rf_withdrawal on shareholder_register_filing.register_observation_withdrawals;
 create trigger company_archive_track_rf_withdrawal after insert or update or delete
  on shareholder_register_filing.register_observation_withdrawals for each row
  execute function public.company_archive_track_source_write_v1('year','company_id');
end; $register$;
reset role;
set local role company_archive_projection_executor;
do $invalidate$
declare r record;
begin
 for r in select * from pg_temp.rf193_withdrawal_generation_scopes order by company_id,income_year loop
  perform public.company_archive_lock_scope_v1(r.company_id,r.income_year);
  insert into public.company_archive_source_generations(company_id,income_year,generation,updated_at)
   values(r.company_id,r.income_year,1,pg_catalog.statement_timestamp())
   on conflict(company_id,income_year) do update
    set generation=company_archive_source_generations.generation+1,updated_at=excluded.updated_at;
 end loop;
end; $invalidate$;
do $revoke$
begin
 if not (select had from pg_temp.rf193_withdrawal_generation_grant) then
  revoke execute on function public.company_archive_track_source_write_v1() from shareholder_register_filing_store_owner;
 end if;
end; $revoke$;
reset role;
do $restore$
declare r record;
begin
 for r in select * from pg_temp.rf193_withdrawal_generation_roles order by role_name loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',
   r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user); end if;
 end loop;
end; $restore$;
commit;
