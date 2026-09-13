-- #152 read contracts. Expansion remains unavailable until a separate cutover.
begin;
set local lock_timeout='5s';
set local statement_timeout='120s';
set local search_path='';
create temporary table tax152_read_borrowed_roles(role_name name primary key,prior jsonb) on commit drop;
do $borrow$ declare r text:='company_tax_filing_store_owner'; v_prior jsonb; begin
 if not pg_catalog.pg_has_role(current_user,r,'SET') then
  select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option) into v_prior
  from pg_catalog.pg_auth_members m where m.roleid=(select oid from pg_catalog.pg_roles where rolname=r)
   and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user)
   and m.grantor=(select oid from pg_catalog.pg_roles where rolname=current_user);
  insert into tax152_read_borrowed_roles values(r,v_prior);
  execute pg_catalog.format('grant %I to %I with set true granted by %I',r,current_user,current_user);
 end if;
end; $borrow$;
set local role company_tax_filing_store_owner;
create function company_tax_filing.return_phase_v1() returns text
language sql stable security definer set search_path='' as $function$
 select phase from backend_system.company_tax_return_migration_state where singleton;
$function$;
revoke all on function company_tax_filing.return_phase_v1() from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

create function company_tax_filing.verified_filing_actor_v1(p_subject text) returns uuid
language plpgsql stable security definer set search_path='' as $function$
declare actor uuid:=public.company_access_auth_uid_v1();
 claims jsonb:=nullif(pg_catalog.current_setting('talli.verified_actor_claims',true),'')::jsonb;
begin
 if actor is null or actor::text is distinct from p_subject
  or pg_catalog.current_setting('talli.verified_actor_id',true) is distinct from actor::text
  or claims->>'sub' is distinct from actor::text or claims->>'role' is distinct from 'authenticated'
 then raise exception 'company_tax_return_forbidden'; end if;
 return actor;
end; $function$;
revoke all on function company_tax_filing.verified_filing_actor_v1(text) from public,anon,authenticated,service_role,company_tax_filing_workflow_executor;

-- A runtime cannot use stale expansion copies, even if it can assume the store
-- role. No insert/update/delete policy or business write grant is added here.
create policy tax_return_member_read on company_tax_filing.filing_previews for select to company_tax_filing_store_owner
using(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_is_accepted_member_v1(company_id));
create policy tax_return_member_read on company_tax_filing.filing_submissions for select to company_tax_filing_store_owner
using(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_is_accepted_member_v1(company_id));
create policy tax_return_member_read on company_tax_filing.filing_overrides for select to company_tax_filing_store_owner
using(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_is_accepted_member_v1(company_id));
create policy tax_return_member_read on company_tax_filing.filing_review_comments for select to company_tax_filing_store_owner
using(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_is_accepted_member_v1(company_id));
create policy tax_return_member_read on company_tax_filing.authority_permissions for select to company_tax_filing_store_owner
using(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_is_accepted_member_v1(company_id));
create policy tax_return_member_read on company_tax_filing.authority_test_runs for select to company_tax_filing_store_owner
using(company_tax_filing.return_phase_v1() in ('cutover','contracted') and public.company_access_is_accepted_member_v1(company_id));

create function company_tax_filing.read_workspace_v1(p_company uuid,p_year integer,p_subject text) returns jsonb
language plpgsql stable security definer set search_path='' as $function$
begin
 perform company_tax_filing.verified_filing_actor_v1(p_subject);
 if not public.company_access_is_accepted_member_v1(p_company) then raise exception 'company_tax_return_not_found'; end if;
 if p_year is not null and p_year not between 2000 and 2100 then raise exception 'company_tax_return_invalid_input'; end if;
 if company_tax_filing.return_phase_v1() is null or company_tax_filing.return_phase_v1() not in ('cutover','contracted') then
  raise exception 'company_tax_return_unavailable';
 end if;
 return pg_catalog.jsonb_build_object(
  'previews',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) order by created_at desc,id),'[]'::jsonb) from company_tax_filing.filing_previews r where company_id=p_company and (p_year is null or income_year=p_year)),
  'submissions',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) order by created_at desc,id),'[]'::jsonb) from company_tax_filing.filing_submissions r where company_id=p_company and (p_year is null or income_year=p_year)),
  'overrides',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) order by created_at desc,id),'[]'::jsonb) from company_tax_filing.filing_overrides r where company_id=p_company and (p_year is null or income_year=p_year)),
  'review_comments',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) order by r.created_at desc,r.id),'[]'::jsonb) from company_tax_filing.filing_review_comments r join company_tax_filing.filing_previews p on p.id=r.preview_id and p.company_id=r.company_id where r.company_id=p_company and (p_year is null or p.income_year=p_year)),
  'permissions',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) order by confirmed_at desc,id),'[]'::jsonb) from company_tax_filing.authority_permissions r where company_id=p_company),
  'test_evidence',(select coalesce(pg_catalog.jsonb_agg(pg_catalog.to_jsonb(r) order by recorded_at desc,id),'[]'::jsonb) from company_tax_filing.authority_test_runs r where company_id=p_company)
 );
end; $function$;
revoke all on function company_tax_filing.read_workspace_v1(uuid,integer,text) from public,anon,authenticated,service_role;
grant execute on function company_tax_filing.read_workspace_v1(uuid,integer,text) to company_tax_filing_workflow_executor;
reset role;
do $restore$ declare r record; begin
 for r in select * from tax152_read_borrowed_roles loop
  execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
  if r.prior is not null then
   execute pg_catalog.format('grant %I to %I with admin %s,inherit %s,set %s granted by %I',r.role_name,current_user,(r.prior->>'admin')::boolean,(r.prior->>'inherit')::boolean,(r.prior->>'set')::boolean,current_user);
  end if;
 end loop;
end; $restore$;
commit;
