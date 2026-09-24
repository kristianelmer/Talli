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

-- Capture whether this is the first activation, before adding derived columns.
create temporary table rf193_archive_activation on commit drop as
select not exists(select 1 from pg_catalog.pg_attribute
  where attrelid='shareholder_register_filing.production_filing_events'::regclass
    and attname='company_id' and not attisdropped) first_activation;
create temporary table rf193_archive_new_scopes(company_id uuid,income_year integer) on commit drop;

-- These tables have FORCE RLS under the canonical contracted owner. The brief
-- owner-only backfill is transactional; no principal or runtime ACL is widened.
do $force_precondition$
begin
  if exists(select 1 from pg_catalog.pg_class where oid in
    ('shareholder_register_filing.production_filing_events'::regclass,
     'shareholder_register_filing.production_filing_submissions'::regclass,
     'shareholder_register_filing.filing_approval_snapshots'::regclass) and not relforcerowsecurity)
  then raise exception 'rf1086_archive_force_rls_precondition'; end if;
end; $force_precondition$;
alter table shareholder_register_filing.production_filing_events add column if not exists company_id uuid, add column if not exists income_year integer;
alter table shareholder_register_filing.production_filing_events no force row level security;
alter table shareholder_register_filing.production_filing_submissions no force row level security;
alter table shareholder_register_filing.filing_approval_snapshots no force row level security;
insert into pg_temp.rf193_archive_new_scopes
select company_id,income_year from shareholder_register_filing.filing_approval_snapshots
where (select first_activation from pg_temp.rf193_archive_activation)
union select company_id,income_year from shareholder_register_filing.production_filing_submissions
where (select first_activation from pg_temp.rf193_archive_activation);
update shareholder_register_filing.production_filing_events e
set company_id=s.company_id,income_year=s.income_year
from shareholder_register_filing.production_filing_submissions s where s.id=e.submission_id and (e.company_id is null or e.income_year is null);
alter table shareholder_register_filing.production_filing_events alter column company_id set not null, alter column income_year set not null;
alter table shareholder_register_filing.production_filing_events force row level security;
alter table shareholder_register_filing.production_filing_submissions force row level security;
alter table shareholder_register_filing.filing_approval_snapshots force row level security;

-- Existing exports predate these sources. Invalidate their technical generation
-- once, under its original owner, without updating any filing/receipt row.
grant select on pg_temp.rf193_archive_new_scopes to company_archive_projection_executor;
reset role;
set local role company_archive_projection_executor;
do $activate_scopes$
declare r record;
begin
  for r in select * from pg_temp.rf193_archive_new_scopes order by company_id,income_year loop
    perform public.company_archive_lock_scope_v1(r.company_id,r.income_year);
    insert into public.company_archive_source_generations(company_id,income_year,generation,updated_at)
    values(r.company_id,r.income_year,1,pg_catalog.statement_timestamp())
    on conflict(company_id,income_year) do update
      set generation=company_archive_source_generations.generation+1,updated_at=excluded.updated_at;
  end loop;
end; $activate_scopes$;
reset role;
set local role shareholder_register_filing_store_owner;
do $constraints$
begin
  if not exists(select 1 from pg_catalog.pg_constraint where conrelid='shareholder_register_filing.production_filing_submissions'::regclass and conname='rf193_submission_archive_scope') then
    alter table shareholder_register_filing.production_filing_submissions
      add constraint rf193_submission_archive_scope unique(id,company_id,income_year);
  end if;
  if not exists(select 1 from pg_catalog.pg_constraint where conrelid='shareholder_register_filing.production_filing_events'::regclass and conname='rf193_event_archive_scope') then
    alter table shareholder_register_filing.production_filing_events
      add constraint rf193_event_archive_scope foreign key(submission_id,company_id,income_year)
      references shareholder_register_filing.production_filing_submissions(id,company_id,income_year) on delete cascade;
  end if;
end; $constraints$;

create or replace function shareholder_register_filing.derive_event_archive_scope_v1()
returns trigger language plpgsql security invoker set search_path='' as $function$
declare v_company uuid; v_year integer;
begin
  if tg_op='UPDATE' and (new.submission_id is distinct from old.submission_id
    or new.company_id is distinct from old.company_id or new.income_year is distinct from old.income_year)
  then raise exception 'rf1086_archive_event_scope_immutable'; end if;
  select company_id,income_year into v_company,v_year
  from shareholder_register_filing.production_filing_submissions where id=new.submission_id;
  if v_company is null or (new.company_id is not null and new.company_id<>v_company)
    or (new.income_year is not null and new.income_year<>v_year)
  then raise exception 'rf1086_archive_event_scope_mismatch'; end if;
  new.company_id:=v_company; new.income_year:=v_year;
  return new;
end; $function$;
revoke all on function shareholder_register_filing.derive_event_archive_scope_v1() from public,anon,authenticated,service_role;
-- Alphabetical ordering populates scope before the generation tracker reads NEW.
drop trigger if exists a_rf193_event_archive_scope on shareholder_register_filing.production_filing_events;
create trigger a_rf193_event_archive_scope before insert or update of submission_id,company_id,income_year
on shareholder_register_filing.production_filing_events for each row
execute function shareholder_register_filing.derive_event_archive_scope_v1();

drop trigger if exists company_archive_track_rf193_approvals on shareholder_register_filing.filing_approval_snapshots;
create trigger company_archive_track_rf193_approvals before insert or update or delete on shareholder_register_filing.filing_approval_snapshots
for each row execute function public.company_archive_track_source_write_v1('year', 'company_id');
drop trigger if exists company_archive_track_rf193_submissions on shareholder_register_filing.production_filing_submissions;
create trigger company_archive_track_rf193_submissions before insert or update or delete on shareholder_register_filing.production_filing_submissions
for each row execute function public.company_archive_track_source_write_v1('year', 'company_id');
drop trigger if exists company_archive_track_rf193_events on shareholder_register_filing.production_filing_events;
create trigger company_archive_track_rf193_events before insert or update or delete on shareholder_register_filing.production_filing_events
for each row execute function public.company_archive_track_source_write_v1('year', 'company_id');
drop trigger if exists company_archive_track_rf193_artifacts on shareholder_register_filing.production_feedback_artifacts;
create trigger company_archive_track_rf193_artifacts before insert or update or delete on shareholder_register_filing.production_feedback_artifacts
for each row execute function public.company_archive_track_source_write_v1('company', 'company_id');

-- Exactly one generation trigger per new source, including after rehearsal replay.
do $tracker_inventory$
begin
  if exists(select table_name from (values ('filing_approval_snapshots'),('production_filing_submissions'),('production_filing_events'),('production_feedback_artifacts')) sources(table_name)
    where (select count(*) from pg_catalog.pg_trigger t
      where t.tgrelid=pg_catalog.to_regclass('shareholder_register_filing.'||table_name)
        and t.tgfoid='public.company_archive_track_source_write_v1()'::regprocedure)<>1)
  then raise exception 'rf1086_archive_duplicate_generation_tracker'; end if;
end; $tracker_inventory$;

-- v1 migration/source comparison hashes retain exactly their original journal
-- content. The new redundant scope is enforced by trigger + composite FK.
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

select pg_catalog.jsonb_build_object('count',count(*),'digest',pg_catalog.encode(extensions.digest(coalesce(pg_catalog.string_agg(item::text,E'\n' order by item->>'id'),''),'sha256'),'hex')) into family_value from (select pg_catalog.to_jsonb(t)-'company_id'-'income_year' item from shareholder_register_filing.production_filing_events t join shareholder_register_filing.production_filing_submissions p on p.id=t.submission_id where p.company_id=p_company_id and p.income_year=p_income_year) source;
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
