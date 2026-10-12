-- Complete Governance reporting inputs on the caller's guarded RF connection.
-- Delegate through owner public projections; never grant another owner's tables.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table rf193_governance_read_authority(role_name text,prior jsonb) on commit drop;
create temporary table rf193_governance_read_create(had_create boolean) on commit drop;
do $borrow$
declare name text; prior jsonb;
begin
 foreach name in array array['corporate_governance_store_owner','ledger_store_owner'] loop
  if not pg_catalog.pg_has_role(current_user,name,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
   into prior from pg_catalog.pg_auth_members m where m.roleid=pg_catalog.to_regrole(name)
    and m.member=pg_catalog.to_regrole(current_user) and m.grantor=m.member;
   insert into pg_temp.rf193_governance_read_authority values(name,prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',name,current_user,current_user);
  end if;
 end loop;
 insert into pg_temp.rf193_governance_read_create values(pg_catalog.has_schema_privilege('corporate_governance_store_owner','corporate_governance','CREATE'));
end; $borrow$;
set local role ledger_store_owner;
grant usage on schema ledger to corporate_governance_store_owner;
grant execute on function ledger.list_entry_amendments_v1(uuid,text) to corporate_governance_store_owner;
reset role;
set local role corporate_governance_store_owner;
grant create on schema corporate_governance to corporate_governance_store_owner;
create or replace function corporate_governance.read_guarded_reporting_year_inputs_v1(p_company uuid,p_year integer,p_subject text)
returns jsonb language plpgsql volatile security definer set search_path='' as $function$
declare lock_key bigint; lifecycle jsonb; supported jsonb; amendments jsonb;
begin
 if p_company is null or p_year is null or p_year<2000 or p_year>2100 then raise exception 'corporate_governance_invalid_input'; end if;
 if pg_catalog.current_setting('transaction_isolation') <> 'read committed' then
  raise exception 'corporate_governance_reporting_guard_required'; end if;
 if p_subject is null or nullif(pg_catalog.current_setting('talli.verified_actor_id',true),'') is distinct from p_subject
   or public.company_access_auth_uid_v1()::text is distinct from p_subject
   or not public.company_access_is_accepted_owner_v1(p_company)
 then raise exception 'corporate_governance_forbidden'; end if;
 lock_key := pg_catalog.hashtextextended(p_company::text,157);
 if not exists(select 1 from pg_catalog.pg_locks l
   where l.pid=pg_catalog.pg_backend_pid() and l.locktype='advisory' and l.granted
    and l.mode='ExclusiveLock' and l.objsubid=1
    and l.database=(select oid from pg_catalog.pg_database where datname=pg_catalog.current_database())
    and l.classid=((lock_key >> 32) & 4294967295)::oid
    and l.objid=(lock_key & 4294967295)::oid)
 then raise exception 'corporate_governance_reporting_guard_required'; end if;
 -- Ensure transaction ownership even if the matching guard was session-scoped.
 perform public.company_archive_lock_company_v1(p_company);
 if not public.company_access_is_accepted_owner_v1(p_company) then raise exception 'corporate_governance_forbidden'; end if;
 lifecycle := corporate_governance.read_corporate_lifecycle_v1(array[p_company],null,p_subject);
 select coalesce(pg_catalog.jsonb_agg(e.value order by e.ordinality),'[]'::jsonb) into supported
 from corporate_governance.list_supported_events_v1(array[p_company],p_subject) with ordinality as e(value,ordinality);
 select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(a) order by a.original_entry_id,a.reversal_entry_id),'[]'::jsonb) into amendments
 from ledger.list_entry_amendments_v1(p_company,p_subject) a;
 return pg_catalog.jsonb_build_object('companyId',p_company,'incomeYear',p_year,
   'lifecycle',lifecycle,'supportedEvents',supported,'amendments',amendments);
end; $function$;
revoke all on function corporate_governance.read_guarded_reporting_year_inputs_v1(uuid,integer,text)
 from public,anon,authenticated,service_role;
grant usage on schema corporate_governance to shareholder_register_filing_executor;
grant execute on function corporate_governance.read_guarded_reporting_year_inputs_v1(uuid,integer,text)
 to shareholder_register_filing_executor;
reset role;
do $restore$
declare item record;
begin
 if not (select had_create from pg_temp.rf193_governance_read_create) then
  set local role corporate_governance_store_owner;
  revoke create on schema corporate_governance from corporate_governance_store_owner;
  reset role;
 end if;
 for item in select * from pg_temp.rf193_governance_read_authority loop
  execute pg_catalog.format('revoke %I from %I granted by %I',item.role_name,current_user,current_user);
  if item.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',item.role_name,current_user,item.prior->>'admin',item.prior->>'inherit',item.prior->>'set',current_user);
  end if;
 end loop;
end; $restore$;
commit;
