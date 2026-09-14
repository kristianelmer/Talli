-- #153 inactive dependency contracts. Callers are rebound only during cutover.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table accounts153_dependency_borrowed_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text; v_prior jsonb; begin
 foreach r in array array['annual_accounts_filing_store_owner','company_access_executor'] loop
  if not pg_catalog.pg_has_role(current_user,r,'SET') then
   select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into v_prior
   from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
    and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
    and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
   insert into accounts153_dependency_borrowed_roles values(r,v_prior);
   execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
  end if;
 end loop;
end; $borrow$;
set local role company_access_executor;
grant execute on function public.company_access_has_open_support_case_v1(uuid,uuid,text),
 public.company_access_current_support_case_id_v1() to annual_accounts_filing_store_owner;
reset role;
set local role annual_accounts_filing_store_owner;
grant usage on schema annual_accounts_filing to postgres,documents_store_owner,company_access_executor,company_tax_filing_store_owner;

create function annual_accounts_filing.has_blocking_override_v1(p_company uuid,p_year integer) returns boolean
language plpgsql volatile security definer set search_path='' as $function$
begin
 if coalesce(annual_accounts_filing.filing_phase_v1() not in ('cutover','contracted'),true) then raise exception 'annual_accounts_unavailable'; end if;
 return public.company_access_is_accepted_member_v1(p_company) and exists(
  select 1 from annual_accounts_filing.filing_overrides where company_id=p_company and income_year=p_year and risk_level='block');
end; $function$;
revoke all on function annual_accounts_filing.has_blocking_override_v1(uuid,integer) from public,anon,authenticated,service_role,annual_accounts_filing_workflow_executor;
grant execute on function annual_accounts_filing.has_blocking_override_v1(uuid,integer) to postgres;

create function annual_accounts_filing.has_document_reference_v1(p_document uuid) returns boolean
language plpgsql volatile security definer set search_path='' as $function$
begin
 if coalesce(annual_accounts_filing.filing_phase_v1() not in ('cutover','contracted'),true) then raise exception 'annual_accounts_unavailable'; end if;
 return exists(select 1 from annual_accounts_filing.filing_submissions s
  where coalesce(s.feedback_document_ids,'[]'::jsonb) @> pg_catalog.jsonb_build_array(p_document::text)
   or s.receipt_id=p_document::text);
end; $function$;
create policy accounts153_document_reference_read on annual_accounts_filing.filing_submissions for select to annual_accounts_filing_store_owner
using(pg_catalog.current_setting('role',true)='documents_executor');
revoke all on function annual_accounts_filing.has_document_reference_v1(uuid) from public,anon,authenticated,service_role,annual_accounts_filing_workflow_executor;
grant execute on function annual_accounts_filing.has_document_reference_v1(uuid) to documents_store_owner,postgres;

create function annual_accounts_filing.read_support_filing_history_v1(p_company uuid,p_case uuid) returns jsonb
language plpgsql volatile security definer set search_path='' as $function$
begin
 if coalesce(annual_accounts_filing.filing_phase_v1() not in ('cutover','contracted'),true) then raise exception 'annual_accounts_unavailable'; end if;
 if p_case is distinct from public.company_access_current_support_case_id_v1() then
  return '{"filing_submissions":[],"authority_permissions":[],"authority_test_runs":[]}'::jsonb;
 end if;
 return pg_catalog.jsonb_build_object(
  'filing_submissions',case when public.company_access_has_open_support_case_v1(p_case,p_company,'filing') then coalesce((
   select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('id',f.id,'company_id',f.company_id,'income_year',f.income_year,
    'filing',f.filing,'status',f.status,'updated_at',f.updated_at) order by f.updated_at desc)
   from annual_accounts_filing.filing_submissions f where f.company_id=p_company),'[]'::jsonb) else '[]'::jsonb end,
  'authority_permissions',case when public.company_access_has_open_support_case_v1(p_case,p_company,'authority') then coalesce((
   select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('id',a.id,'company_id',a.company_id,'obligation',a.obligation,
    'production_enabled',a.production_enabled,'updated_at',a.updated_at))
   from annual_accounts_filing.authority_permissions a where a.company_id=p_company),'[]'::jsonb) else '[]'::jsonb end,
  'authority_test_runs',case when public.company_access_has_open_support_case_v1(p_case,p_company,'authority') then coalesce((
   select pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object('id',a.id,'company_id',a.company_id,'obligation',a.obligation,
    'environment',a.environment,'status',a.status,'test_reference',a.test_reference,'recorded_at',a.recorded_at) order by a.recorded_at desc)
   from annual_accounts_filing.authority_test_runs a where a.company_id=p_company),'[]'::jsonb) else '[]'::jsonb end);
end; $function$;
create policy accounts153_support_read on annual_accounts_filing.filing_submissions for select to annual_accounts_filing_store_owner
using(public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(),company_id,'filing'));
create policy accounts153_support_read on annual_accounts_filing.authority_permissions for select to annual_accounts_filing_store_owner
using(public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(),company_id,'authority'));
create policy accounts153_support_read on annual_accounts_filing.authority_test_runs for select to annual_accounts_filing_store_owner
using(public.company_access_has_open_support_case_v1(public.company_access_current_support_case_id_v1(),company_id,'authority'));
revoke all on function annual_accounts_filing.read_support_filing_history_v1(uuid,uuid) from public,anon,authenticated,service_role,annual_accounts_filing_workflow_executor;
grant execute on function annual_accounts_filing.read_support_filing_history_v1(uuid,uuid) to company_access_executor;

-- The last generic store's physical retirement is an owned fact for predecessor
-- coverage checks. It cannot be inferred from a missing source relation alone.
create function annual_accounts_filing.generic_store_retired_v1() returns boolean
language sql stable security definer set search_path='' as $function$
 select (select phase='contracted' from backend_system.annual_accounts_migration_state where singleton)
 and not exists(select 1 from backend_system.annual_accounts_quarantine)
 and (select count(distinct family)=6 from backend_system.annual_accounts_reconciliations
  where phase='cutover' and source_count=target_count and source_digest=target_digest)
 and pg_catalog.to_regclass('public.filing_previews') is null
 and pg_catalog.to_regclass('public.filing_submissions') is null
 and pg_catalog.to_regclass('public.filing_overrides') is null
 and pg_catalog.to_regclass('public.filing_review_comments') is null
 and pg_catalog.to_regclass('public.authority_permissions') is null
 and pg_catalog.to_regclass('public.authority_test_runs') is null;
$function$;
revoke all on function annual_accounts_filing.generic_store_retired_v1() from public,anon,authenticated,service_role,annual_accounts_filing_workflow_executor;
grant execute on function annual_accounts_filing.generic_store_retired_v1() to company_tax_filing_store_owner;
reset role;
do $restore$ declare r record; begin
 for r in select * from accounts153_dependency_borrowed_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,(r.prior->>'admin')::boolean,(r.prior->>'inherit')::boolean,(r.prior->>'set')::boolean,current_user);
  end if;
 end loop;
end; $restore$;
commit;
