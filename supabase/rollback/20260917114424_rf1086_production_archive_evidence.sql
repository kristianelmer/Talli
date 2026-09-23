-- Roll back code and archive response with this migration before an RF #151 rollback.
-- Original journal, approval, submission and receipt content is never removed.
-- Complete RF archive sources without changing original submission/receipt content.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '120s';
set local search_path = '';
create temporary table rf193_archive_borrowed_roles(role_name text, prior jsonb) on commit drop;
do $borrow$
declare v_role text; v_prior jsonb;
begin
  foreach v_role in array array['shareholder_register_filing_store_owner','company_archive_projection_executor'] loop
    if not pg_catalog.pg_has_role(current_user,v_role,'SET') then
      select pg_catalog.jsonb_build_object('admin',m.admin_option,'inherit',m.inherit_option,'set',m.set_option)
      into v_prior from pg_catalog.pg_auth_members m
      where m.roleid=(select oid from pg_catalog.pg_roles where rolname=v_role)
        and m.member=(select oid from pg_catalog.pg_roles where rolname=current_user) and m.grantor=m.member;
      insert into pg_temp.rf193_archive_borrowed_roles values(v_role,v_prior);
      execute pg_catalog.format('grant %I to %I with set true granted by %I',v_role,current_user,current_user);
    end if;
  end loop;
end; $borrow$;
create temporary table rf193_archive_prior_execute on commit drop as
select pg_catalog.has_function_privilege('shareholder_register_filing_store_owner',
  'public.company_archive_track_source_write_v1()','EXECUTE') had_execute;
set local role company_archive_projection_executor;
do $grant_tracker$ begin
  if not pg_catalog.has_function_privilege('shareholder_register_filing_store_owner',
    'public.company_archive_track_source_write_v1()','EXECUTE') then
    grant execute on function public.company_archive_track_source_write_v1() to shareholder_register_filing_store_owner;
  end if;
end; $grant_tracker$;
reset role;
set local role shareholder_register_filing_store_owner;

drop trigger if exists company_archive_track_rf193_approvals on shareholder_register_filing.filing_approval_snapshots;
drop trigger if exists company_archive_track_rf193_submissions on shareholder_register_filing.production_filing_submissions;
drop trigger if exists company_archive_track_rf193_events on shareholder_register_filing.production_filing_events;
drop trigger if exists company_archive_track_rf193_artifacts on shareholder_register_filing.production_feedback_artifacts;
drop trigger if exists a_rf193_event_archive_scope on shareholder_register_filing.production_filing_events;
drop function if exists shareholder_register_filing.derive_event_archive_scope_v1();
alter table shareholder_register_filing.production_filing_events drop constraint if exists rf193_event_archive_scope;
alter table shareholder_register_filing.production_filing_submissions drop constraint if exists rf193_submission_archive_scope;
alter table shareholder_register_filing.production_filing_events drop column if exists company_id, drop column if exists income_year;
create or replace function shareholder_register_filing.read_scope_inventory_v1(p_company_id uuid,p_income_year integer,p_verified_subject text)
returns jsonb language plpgsql stable security definer set search_path='' as $function$
declare result jsonb:='{}'::jsonb; family_value jsonb; begin
 if p_verified_subject is distinct from shareholder_register_filing.assert_preparation_access_v1(p_company_id)::text then raise exception 'rf1086_forbidden'; end if;

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.opening_balance_setups t where t.company_id=p_company_id and t.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('opening_balance_setups',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.opening_shareholders t join shareholder_register_filing.opening_balance_setups p on p.id=t.setup_id where p.company_id=p_company_id and p.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('opening_shareholders',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_previews t where t.company_id=p_company_id and t.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('filing_previews',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_submissions t where t.company_id=p_company_id and t.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('filing_submissions',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_overrides t where t.company_id=p_company_id and t.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('filing_overrides',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_review_comments t join shareholder_register_filing.filing_previews p on p.id=t.preview_id where p.company_id=p_company_id and p.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('filing_review_comments',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.authority_permissions t where t.company_id=p_company_id) source;
 result:=result||pg_catalog.jsonb_build_object('authority_permissions',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.authority_test_runs t where t.company_id=p_company_id) source;
 result:=result||pg_catalog.jsonb_build_object('authority_test_runs',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.filing_approval_snapshots t where t.company_id=p_company_id and t.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('filing_approval_snapshots',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.production_filing_submissions t where t.company_id=p_company_id and t.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('production_filing_submissions',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.production_filing_events t join shareholder_register_filing.production_filing_submissions p on p.id=t.submission_id where p.company_id=p_company_id and p.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('production_filing_events',family_value);

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t) item from shareholder_register_filing.production_feedback_artifacts t join shareholder_register_filing.production_filing_submissions p on p.id=t.submission_id where p.company_id=p_company_id and p.income_year=p_income_year) source;
 result:=result||pg_catalog.jsonb_build_object('production_feedback_artifacts',family_value);

return result;
end; $function$;
alter function shareholder_register_filing.read_scope_inventory_v1(uuid,integer,text) owner to shareholder_register_filing_store_owner;
revoke all on function shareholder_register_filing.read_scope_inventory_v1(uuid,integer,text) from public,anon,authenticated,service_role;
grant execute on function shareholder_register_filing.read_scope_inventory_v1(uuid,integer,text) to postgres;
grant usage on schema extensions to shareholder_register_filing_store_owner;
grant execute on function extensions.digest(text,text) to shareholder_register_filing_store_owner;
reset role;
do $restore_execute$
begin
  if not (select had_execute from pg_temp.rf193_archive_prior_execute) then
    set local role company_archive_projection_executor;
    revoke execute on function public.company_archive_track_source_write_v1() from shareholder_register_filing_store_owner;
    reset role;
  end if;
end; $restore_execute$;
do $restore_roles$
declare r record;
begin
  for r in select * from pg_temp.rf193_archive_borrowed_roles loop
    execute pg_catalog.format('revoke %I from %I granted by %I',r.role_name,current_user,current_user);
    if r.prior is not null then
      execute pg_catalog.format('grant %I to %I with admin %s, inherit %s, set %s granted by %I',
        r.role_name,current_user,r.prior->>'admin',r.prior->>'inherit',r.prior->>'set',current_user);
    end if;
  end loop;
end; $restore_roles$;
commit;
